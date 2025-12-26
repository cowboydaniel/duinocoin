"""PySide6 GUI entry point for Duino Coin."""

from __future__ import annotations

import sys
from dataclasses import replace
from typing import Iterable
from typing import Callable, Iterable

from concurrent.futures import Future, ThreadPoolExecutor

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QFrame,
    QListWidgetItem,
    QSpacerItem,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config import Configuration, THEMES, validate_config
from .state import AppState, LiveStats, MinerStatus, WalletData
from .metrics import MinerMetricsParser
from .state import (
    AppState,
    Configuration,
    LiveStats,
    MinerMetrics,
    MinerStatus,
    MinerLogEntry,
    WalletData,
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


class GaugeWidget(QFrame):
    """Simple colored gauge with a title and value label."""

    STATES = {
        "ok": "background-color: #e8f5e9; border: 1px solid #66bb6a;",
        "warn": "background-color: #fff3e0; border: 1px solid #ffa726;",
        "error": "background-color: #ffebee; border: 1px solid #ef5350;",
    }

    def __init__(self, title: str) -> None:
        super().__init__()
        layout = QVBoxLayout()
        self.title_label = QLabel(title)
        self.value_label = QLabel("-")
        self.detail_label = QLabel("")
        self.title_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)
        layout.addStretch(1)
        self.setLayout(layout)
        self.setFrameStyle(QFrame.Panel | QFrame.Raised)
        self.set_state("ok")

    def set_state(self, state: str) -> None:
        style = self.STATES.get(state, self.STATES["ok"])
        self.setStyleSheet(style)

    def update_value(self, value: str, detail: str = "", state: str = "ok") -> None:
        self.value_label.setText(value)
        self.detail_label.setText(detail)
        self.set_state(state)


class MinerGaugesPanel(QGroupBox):
    """Dashboard gauges fed by live miner metrics."""

    def __init__(self, state: AppState, miner_type: str = "cpu") -> None:
        super().__init__("Miner Gauges")
        self.state = state
        self.miner_type = miner_type
        self.metrics = MinerMetrics()

        gauges_row = QHBoxLayout()
        self.hashrate_gauge = GaugeWidget("Hashrate")
        self.share_rate_gauge = GaugeWidget("Share rate")
        self.temperature_gauge = GaugeWidget("Temperature")
        self.rewards_gauge = GaugeWidget("Projected DUCO/day")
        gauges_row.addWidget(self.hashrate_gauge)
        gauges_row.addWidget(self.share_rate_gauge)
        gauges_row.addWidget(self.temperature_gauge)
        gauges_row.addWidget(self.rewards_gauge)

        self.alert_label = QLabel("")
        self.alert_label.setStyleSheet("color: #ef5350; font-weight: bold;")

        self.log_list = QListWidget()
        self.log_list.setMaximumHeight(150)

        layout = QVBoxLayout()
        layout.addLayout(gauges_row)
        layout.addWidget(self.alert_label)
        layout.addWidget(QLabel("Recent miner messages:"))
        layout.addWidget(self.log_list)
        self.setLayout(layout)

        self.state.metrics_changed.connect(self._on_metrics_changed)
        self.state.log_added.connect(self._on_log_added)

        self.refresh(self.state.metrics.get(self.miner_type, MinerMetrics()))
        self._start_refresh_timer()

    def _start_refresh_timer(self) -> None:
        timer = QTimer(self)
        timer.setInterval(1000)
        timer.timeout.connect(self._refresh_from_state)
        timer.start()
        self.timer = timer

    def _refresh_from_state(self) -> None:
        self.refresh(self.state.metrics.get(self.miner_type, MinerMetrics()))

    def _on_metrics_changed(self, miner_type: str, metrics: MinerMetrics) -> None:
        if miner_type == self.miner_type:
            self.refresh(metrics)

    def _on_log_added(self, entry: MinerLogEntry) -> None:
        item = QListWidgetItem(f"[{entry.level.upper()}] {entry.message}")
        if entry.level == "error":
            item.setForeground(Qt.red)
        elif entry.level == "warning":
            item.setForeground(Qt.darkYellow)
        else:
            item.setForeground(Qt.darkGreen)
        self.log_list.addItem(item)
        self.log_list.scrollToBottom()
        if self.log_list.count() > 200:
            self.log_list.takeItem(0)

    def refresh(self, metrics: MinerMetrics) -> None:
        self.metrics = metrics

        hashrate_state = "ok" if metrics.hashrate > 0 else "warn"
        self.hashrate_gauge.update_value(format_hashrate(metrics.hashrate), "", hashrate_state)

        share_state = "ok" if metrics.share_rate_per_min > 0 else "warn"
        if metrics.rejected_shares > 0:
            share_state = "warn"
        self.share_rate_gauge.update_value(f"{metrics.share_rate_per_min:.2f} / min", "", share_state)

        temp_detail = "-" if metrics.temperature_c is None else f"{metrics.temperature_c:.1f} °C"
        temp_state = "ok"
        if metrics.temperature_c is not None:
            if metrics.temperature_c >= 85:
                temp_state = "error"
            elif metrics.temperature_c >= 75:
                temp_state = "warn"
        self.temperature_gauge.update_value(temp_detail, state=temp_state)

        reward_state = "ok"
        if metrics.last_error:
            reward_state = "error"
        elif metrics.rejected_shares > 0:
            reward_state = "warn"
        self.rewards_gauge.update_value(f"{metrics.projected_duco_per_day:.4f}", "DUCO / day", reward_state)

        alert_text = metrics.last_error or ""
        if metrics.rejected_shares > 0 and not alert_text:
            alert_text = f"Rejected shares: {metrics.rejected_shares}"
        self.alert_label.setText(alert_text)


class SettingsPanel(QGroupBox):
    """Shows configuration summary and opens the settings dialog."""

    def __init__(self, state: AppState) -> None:
        super().__init__("Settings")
        self.state = state

        layout = QFormLayout()
        self.cpu_threads_label = QLabel("-")
        self.intensity_label = QLabel("-")
        self.server_label = QLabel("-")
        self.refresh_label = QLabel("-")
        self.theme_label = QLabel("-")
        self.auto_start_label = QLabel("-")

        self.edit_button = QPushButton("Edit settings")
        self.edit_button.clicked.connect(self._open_dialog)

        layout.addRow("CPU threads:", self.cpu_threads_label)
        layout.addRow("Intensity:", self.intensity_label)
        layout.addRow("Server:", self.server_label)
        layout.addRow("Refresh interval:", self.refresh_label)
        layout.addRow("Theme:", self.theme_label)
        layout.addRow("Auto start:", self.auto_start_label)
        layout.addRow(self.edit_button)
        self.setLayout(layout)

        self.state.config_changed.connect(self.refresh)
        self.refresh(self.state.config)

    def _open_dialog(self) -> None:
        dialog = SettingsDialog(self.state)
        dialog.exec()

    def refresh(self, config: Configuration) -> None:
        self.cpu_threads_label.setText(str(config.cpu_threads))
        self.intensity_label.setText(str(config.intensity))
        self.server_label.setText(f"{config.server}:{config.port}")
        self.refresh_label.setText(f"Every {config.refresh_interval} s")
        self.theme_label.setText(config.theme.title())
        self.auto_start_label.setText("Yes" if config.auto_start else "No")


class SettingsDialog(QDialog):
    """Dialog for editing miner configuration."""

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self.setWindowTitle("Settings")

        form = QFormLayout()
        self.cpu_threads = QSpinBox()
        self.cpu_threads.setMinimum(1)
        self.cpu_threads.setMaximum(512)
        self.cpu_threads.setValue(state.config.cpu_threads)

        self.intensity = QSpinBox()
        self.intensity.setMinimum(1)
        self.intensity.setMaximum(100)
        self.intensity.setValue(state.config.intensity)

        self.server = QLineEdit(state.config.server)

        self.port = QSpinBox()
        self.port.setMinimum(1)
        self.port.setMaximum(65535)
        self.port.setValue(state.config.port)

        self.refresh_interval = QSpinBox()
        self.refresh_interval.setMinimum(1)
        self.refresh_interval.setMaximum(3600)
        self.refresh_interval.setValue(state.config.refresh_interval)

        self.theme = QComboBox()
        for name in sorted(THEMES):
            self.theme.addItem(name.title(), name)
        current_index = self.theme.findData(state.config.theme.lower())
        self.theme.setCurrentIndex(max(0, current_index))

        self.auto_start = QCheckBox("Start miners on launch")
        self.auto_start.setChecked(state.config.auto_start)

        self.gpu_devices = QLineEdit(", ".join(state.config.gpu_devices))
        self.gpu_devices.setPlaceholderText("GPU 0, GPU 1")

        form.addRow("CPU threads:", self.cpu_threads)
        form.addRow("Intensity:", self.intensity)
        form.addRow("Server host:", self.server)
        form.addRow("Port:", self.port)
        form.addRow("Refresh interval (s):", self.refresh_interval)
        form.addRow("Theme:", self.theme)
        form.addRow("GPU devices:", self.gpu_devices)
        form.addRow(self.auto_start)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._handle_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def _collect_config(self) -> Configuration:
        devices = [d.strip() for d in self.gpu_devices.text().split(",") if d.strip()]
        candidate = replace(
            self.state.config,
            cpu_threads=self.cpu_threads.value(),
            intensity=self.intensity.value(),
            server=self.server.text(),
            port=self.port.value(),
            refresh_interval=self.refresh_interval.value(),
            theme=self.theme.currentData(),
            auto_start=self.auto_start.isChecked(),
            gpu_devices=devices,
        )
        return validate_config(candidate)

    def _needs_restart(self, new_config: Configuration) -> bool:
        current = self.state.config
        return any(
            [
                new_config.cpu_threads != current.cpu_threads,
                new_config.intensity != current.intensity,
                new_config.server != current.server,
                new_config.port != current.port,
            ]
        )

    def _handle_accept(self) -> None:
        try:
            new_config = self._collect_config()
        except ValueError as exc:
            QMessageBox.critical(self, "Invalid settings", str(exc))
            return

        if self._needs_restart(new_config) and (
            self.state.cpu_status.running or self.state.gpu_status.running
        ):
            answer = QMessageBox.question(
                self,
                "Restart required",
                "Changing threads, intensity, or server requires restarting miners. Stop them now?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if answer == QMessageBox.No:
                return
            self.state.update_cpu_status(running=False, hashrate=0.0)
            self.state.update_gpu_status(running=False, hashrate=0.0)

        self.state.set_config(new_config)
        self.accept()


class AppWindow(QMainWindow):
    """Main application window that wires together panels and state."""

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self.parsers = {"cpu": MinerMetricsParser(), "gpu": MinerMetricsParser()}
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
        layout.addWidget(MinerGaugesPanel(self.state))
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
        self.state.update_config(gpu_devices=["GPU 0", "GPU 1"])
        # Warm up gauges with sample miner output.
        sample_lines = [
            "Accepted share #1 3.2 kH/s reward: 0.0021 DUCO",
            "Hashrate: 3.2 kH/s",
            "Temperature: 68C",
            "Accepted share #2 reward 0.0019 DUCO",
            "Rejected share due to stale job",
        ]
        for line in sample_lines:
            self.process_miner_output("cpu", line)

    def process_miner_output(self, miner_type: str, line: str) -> None:
        """Parse miner stdout, update metrics, and surface logs."""
        parser = self.parsers.get(miner_type)
        if parser is None:
            return
        metrics, log_entry = parser.parse_line(line)
        self.state.set_metrics(miner_type, metrics)
        if log_entry:
            self.state.add_log_entry(log_entry)
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
