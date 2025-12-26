"""PySide6 GUI entry point for Duino Coin."""

from __future__ import annotations

import sys
from typing import Callable, Iterable

from concurrent.futures import Future, ThreadPoolExecutor

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSpacerItem,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config_store import load_config, save_config
from .state import AppState, Configuration, LiveStats, MinerStatus, WalletData
from .wallet_client import WalletAuthError, WalletClient, WalletClientError, WalletCredentials
from .wallet_dialog import WalletCredentialsDialog
from .miner_process import MinerProcessManager


def format_hashrate(hashrate: float) -> str:
    """Return a human-friendly hashrate string."""
    if hashrate >= 1_000_000:
        return f"{hashrate / 1_000_000:.2f} MH/s"
    if hashrate >= 1_000:
        return f"{hashrate / 1_000:.2f} kH/s"
    return f"{hashrate:.2f} H/s"


def format_uptime(seconds: int) -> str:
    """Return uptime in a readable format."""
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{int(secs):02d}"


class WalletSummaryPanel(QGroupBox):
    """Shows wallet balances and payout data."""

    def __init__(self, state: AppState, on_edit_credentials, on_manual_refresh) -> None:
        super().__init__("Wallet Summary")
        self.state = state

        layout = QFormLayout()
        self.username_label = QLabel("-")
        self.balance_label = QLabel("0 DUCO")
        self.pending_label = QLabel("0 DUCO")
        self.last_payout_label = QLabel("N/A")

        layout.addRow("Username:", self.username_label)
        layout.addRow("Balance:", self.balance_label)
        layout.addRow("Pending:", self.pending_label)
        layout.addRow("Last payout:", self.last_payout_label)

        button_row = QHBoxLayout()
        settings_button = QPushButton("Wallet settings")
        settings_button.clicked.connect(on_edit_credentials)
        button_row.addWidget(settings_button)
        refresh_button = QPushButton("Refresh now")
        refresh_button.clicked.connect(lambda: on_manual_refresh(force=True))
        button_row.addWidget(refresh_button)
        button_row.addSpacerItem(QSpacerItem(20, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))
        layout.addRow(button_row)
        self.setLayout(layout)

        self.state.wallet_changed.connect(self.refresh)
        self.refresh(self.state.wallet)

    def refresh(self, wallet: WalletData) -> None:
        self.username_label.setText(wallet.username or "-")
        self.balance_label.setText(f"{wallet.balance:.4f} DUCO")
        self.pending_label.setText(f"{wallet.pending_rewards:.4f} DUCO")
        self.last_payout_label.setText(wallet.last_payout or "N/A")


class CpuMinerPanel(QGroupBox):
    """Controls and status for the CPU miner."""

    def __init__(
        self,
        state: AppState,
        start_callback: Callable[[], None],
        stop_callback: Callable[[], None],
    ) -> None:
        super().__init__("CPU Miner")
        self.state = state
        self._start_callback = start_callback
        self._stop_callback = stop_callback

        layout = QVBoxLayout()
        self.status_label = QLabel("Stopped")
        self.hashrate_label = QLabel("0.00 H/s")
        self.shares_label = QLabel("0 accepted / 0 rejected")
        self.temp_label = QLabel("Temp: -")

        button_row = QHBoxLayout()
        self.start_button = QPushButton("Start CPU Miner")
        self.stop_button = QPushButton("Stop")
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.stop_button)

        layout.addWidget(self.status_label)
        layout.addWidget(self.hashrate_label)
        layout.addWidget(self.shares_label)
        layout.addWidget(self.temp_label)
        layout.addLayout(button_row)
        self.setLayout(layout)

        self.start_button.clicked.connect(self._handle_start)
        self.stop_button.clicked.connect(self._handle_stop)

        self.state.cpu_status_changed.connect(self.refresh)
        self.refresh(self.state.cpu_status)

    def _handle_start(self) -> None:
        self._start_callback()

    def _handle_stop(self) -> None:
        self._stop_callback()

    def refresh(self, status: MinerStatus) -> None:
        self.status_label.setText("Running" if status.running else "Stopped")
        self.status_label.setStyleSheet(
            "color: green;" if status.running else "color: #a00;"
        )
        self.hashrate_label.setText(format_hashrate(status.hashrate))
        self.shares_label.setText(
            f"{status.accepted_shares} accepted / {status.rejected_shares} rejected"
        )
        if status.temperature_c is None:
            self.temp_label.setText("Temp: -")
        else:
            self.temp_label.setText(f"Temp: {status.temperature_c:.1f}°C")
        self.start_button.setEnabled(not status.running)
        self.stop_button.setEnabled(status.running)


class GpuMinerPanel(QGroupBox):
    """Controls and status for the GPU miner."""

    def __init__(
        self,
        state: AppState,
        start_callback: Callable[[], None],
        stop_callback: Callable[[], None],
    ) -> None:
        super().__init__("GPU Miner")
        self.state = state
        self._start_callback = start_callback
        self._stop_callback = stop_callback

        layout = QVBoxLayout()
        self.status_label = QLabel("Stopped")
        self.hashrate_label = QLabel("0.00 H/s")
        self.shares_label = QLabel("0 accepted / 0 rejected")

        devices_label = QLabel("Devices:")
        self.device_list = QListWidget()

        button_row = QHBoxLayout()
        self.start_button = QPushButton("Start GPU Miner")
        self.stop_button = QPushButton("Stop")
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.stop_button)

        layout.addWidget(self.status_label)
        layout.addWidget(self.hashrate_label)
        layout.addWidget(self.shares_label)
        layout.addWidget(devices_label)
        layout.addWidget(self.device_list)
        layout.addLayout(button_row)
        self.setLayout(layout)

        self.start_button.clicked.connect(self._handle_start)
        self.stop_button.clicked.connect(self._handle_stop)

        self.state.gpu_status_changed.connect(self.refresh_status)
        self.state.config_changed.connect(self.refresh_devices)

        self.refresh_status(self.state.gpu_status)
        self.refresh_devices(self.state.config)

    def _handle_start(self) -> None:
        self._start_callback()

    def _handle_stop(self) -> None:
        self._stop_callback()

    def refresh_status(self, status: MinerStatus) -> None:
        self.status_label.setText("Running" if status.running else "Stopped")
        self.status_label.setStyleSheet(
            "color: green;" if status.running else "color: #a00;"
        )
        self.hashrate_label.setText(format_hashrate(status.hashrate))
        self.shares_label.setText(
            f"{status.accepted_shares} accepted / {status.rejected_shares} rejected"
        )
        self.start_button.setEnabled(not status.running)
        self.stop_button.setEnabled(status.running)

    def refresh_devices(self, config: Configuration) -> None:
        self.device_list.clear()
        for device in config.gpu_devices:
            QListWidgetItem(device, self.device_list)


class LiveStatsPanel(QGroupBox):
    """Displays live mining statistics."""

    def __init__(self, state: AppState) -> None:
        super().__init__("Live Stats")
        self.state = state

        layout = QFormLayout()
        self.uptime_label = QLabel(format_uptime(self.state.live_stats.uptime_seconds))
        self.hashes_label = QLabel(str(self.state.live_stats.total_hashes))
        self.difficulty_label = QLabel(f"{self.state.live_stats.difficulty:.4f}")
        self.ping_label = QLabel("N/A")

        layout.addRow("Uptime:", self.uptime_label)
        layout.addRow("Total hashes:", self.hashes_label)
        layout.addRow("Difficulty:", self.difficulty_label)
        layout.addRow("Ping:", self.ping_label)
        self.setLayout(layout)

        self.state.stats_changed.connect(self.refresh)
        self.refresh(self.state.live_stats)

    def refresh(self, stats: LiveStats) -> None:
        self.uptime_label.setText(format_uptime(stats.uptime_seconds))
        self.hashes_label.setText(f"{stats.total_hashes:,}")
        self.difficulty_label.setText(f"{stats.difficulty:.4f}")
        self.ping_label.setText(f"{stats.ping_ms:.1f} ms" if stats.ping_ms else "N/A")


class SettingsPanel(QGroupBox):
    """Allows basic configuration updates for the miners."""

    def __init__(self, state: AppState) -> None:
        super().__init__("Settings")
        self.state = state

        layout = QFormLayout()

        self.cpu_threads = QSpinBox()
        self.cpu_threads.setMinimum(1)
        self.cpu_threads.setMaximum(128)

        self.intensity = QSpinBox()
        self.intensity.setMinimum(1)
        self.intensity.setMaximum(100)

        self.auto_start = QCheckBox("Start miners on launch")

        self.gpu_devices_label = QLabel("-")

        layout.addRow("CPU threads:", self.cpu_threads)
        layout.addRow("Intensity:", self.intensity)
        layout.addRow("GPU devices:", self.gpu_devices_label)
        layout.addRow(self.auto_start)

        self.setLayout(layout)

        self.cpu_threads.valueChanged.connect(self._update_threads)
        self.intensity.valueChanged.connect(self._update_intensity)
        self.auto_start.stateChanged.connect(self._update_auto_start)

        self.state.config_changed.connect(self.refresh)
        self.refresh(self.state.config)

    def _update_threads(self, value: int) -> None:
        self.state.update_config(cpu_threads=value)

    def _update_intensity(self, value: int) -> None:
        self.state.update_config(intensity=value)

    def _update_auto_start(self, state: int) -> None:
        self.state.update_config(auto_start=state == Qt.Checked)

    def refresh(self, config: Configuration) -> None:
        self.cpu_threads.blockSignals(True)
        self.intensity.blockSignals(True)
        self.auto_start.blockSignals(True)

        self.cpu_threads.setValue(config.cpu_threads)
        self.intensity.setValue(config.intensity)
        self.auto_start.setChecked(config.auto_start)
        self.gpu_devices_label.setText(", ".join(config.gpu_devices) or "No devices")

        self.cpu_threads.blockSignals(False)
        self.intensity.blockSignals(False)
        self.auto_start.blockSignals(False)


class AppWindow(QMainWindow):
    """Main application window that wires together panels and state."""

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self.wallet_client = WalletClient(server=self.state.config.server)
        self._wallet_executor = ThreadPoolExecutor(max_workers=1)
        self._inflight_wallet_future: Future | None = None
        self.process_manager = MinerProcessManager()
        self.setWindowTitle("Duino Coin")

        central = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(
            WalletSummaryPanel(
                self.state, self._open_wallet_dialog, self.refresh_wallet_data
            )
        )
        layout.addWidget(CpuMinerPanel(self.state))
        layout.addWidget(GpuMinerPanel(self.state))
        layout.addWidget(WalletSummaryPanel(self.state))
        layout.addWidget(
            CpuMinerPanel(
                self.state,
                start_callback=self._start_cpu_miner,
                stop_callback=self._stop_cpu_miner,
            )
        )
        layout.addWidget(
            GpuMinerPanel(
                self.state,
                start_callback=self._start_gpu_miner,
                stop_callback=self._stop_gpu_miner,
            )
        )
        layout.addWidget(LiveStatsPanel(self.state))
        layout.addWidget(SettingsPanel(self.state))
        layout.addStretch(1)
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(60_000)
        self.refresh_timer.timeout.connect(self.refresh_wallet_data)

        self.state.config_changed.connect(self._handle_config_changed)

        self._seed_default_state()
        self.refresh_timer.start()
        self.refresh_wallet_data()
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(1_000)
        self.status_timer.timeout.connect(self._sync_process_states)
        self.status_timer.start()

        self._seed_default_state()
        QApplication.instance().aboutToQuit.connect(self.process_manager.stop_all)

    def _sync_process_states(self) -> None:
        cpu_running = self.process_manager.is_cpu_running()
        gpu_running = self.process_manager.is_gpu_running()
        if self.state.cpu_status.running != cpu_running:
            self.state.update_cpu_status(running=cpu_running)
        if self.state.gpu_status.running != gpu_running:
            self.state.update_gpu_status(running=gpu_running)

    def _start_cpu_miner(self) -> None:
        started = self.process_manager.start_cpu_miner()
        self.state.update_cpu_status(running=started)

    def _stop_cpu_miner(self) -> None:
        self.process_manager.stop_cpu_miner()
        self.state.update_cpu_status(running=False, hashrate=0.0)

    def _start_gpu_miner(self) -> None:
        started = self.process_manager.start_gpu_miner()
        self.state.update_gpu_status(running=started)

    def _stop_gpu_miner(self) -> None:
        self.process_manager.stop_gpu_miner()
        self.state.update_gpu_status(running=False, hashrate=0.0)

    def _seed_default_state(self) -> None:
        """Populate placeholder data so the UI has initial content."""
        if not self.state.wallet.username:
            self.state.update_wallet(
                username="anonymous", balance=0.0, pending_rewards=0.0
            )
        self.state.update_live_stats(uptime_seconds=0, difficulty=0.0, total_hashes=0)
        if not self.state.config.gpu_devices:
            self.state.update_config(gpu_devices=["GPU 0", "GPU 1"])

    def _open_wallet_dialog(self) -> None:
        dialog = WalletCredentialsDialog(self.state.config, parent=self)
        if dialog.exec() == QDialog.Accepted:
            username, token = dialog.get_credentials()
            self.state.update_config(wallet_username=username, wallet_token=token)
            self.refresh_wallet_data(force=True)

    def refresh_wallet_data(self, force: bool = False) -> None:
        """Refresh wallet data from the API asynchronously."""
        if self._inflight_wallet_future and not self._inflight_wallet_future.done():
            if not force:
                return
            self._inflight_wallet_future.cancel()

        credentials = WalletCredentials(
            username=self.state.config.wallet_username,
            token=self.state.config.wallet_token or None,
        )
        if not credentials.username:
            return

        self._inflight_wallet_future = self._wallet_executor.submit(
            self.wallet_client.fetch_wallet, credentials
        )
        self._inflight_wallet_future.add_done_callback(self._handle_wallet_result)

    def _handle_wallet_result(self, future: Future) -> None:
        try:
            wallet = future.result()
        except WalletAuthError:
            wallet = WalletData(
                username=self.state.config.wallet_username,
                balance=0.0,
                pending_rewards=0.0,
                last_payout="Invalid credentials",
            )
        except WalletClientError:
            wallet = WalletData(
                username=self.state.config.wallet_username,
                balance=self.state.wallet.balance,
                pending_rewards=self.state.wallet.pending_rewards,
                last_payout=self.state.wallet.last_payout,
            )
        except Exception:
            wallet = WalletData(
                username=self.state.config.wallet_username,
                balance=self.state.wallet.balance,
                pending_rewards=self.state.wallet.pending_rewards,
                last_payout="Unable to refresh",
            )

        QTimer.singleShot(0, lambda: self.state.set_wallet(wallet))

    def _handle_config_changed(self, config: Configuration) -> None:
        self.wallet_client = WalletClient(server=config.server)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._wallet_executor.shutdown(cancel_futures=True)
        super().closeEvent(event)


def main(argv: Iterable[str] | None = None) -> int:
    """Start the PySide6 application."""
    app = QApplication(list(argv) if argv is not None else sys.argv)
    state = AppState()
    state.set_config(load_config(state.config))
    state.config_changed.connect(save_config)
    window = AppWindow(state)
    window.resize(600, 800)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
