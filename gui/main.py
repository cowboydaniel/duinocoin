"""PySide6 GUI entry point for Duino Coin."""

from __future__ import annotations

import sys
import json
import time
from typing import Iterable, Optional

import requests
from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .state import (
    AppState,
    Configuration,
    LiveStats,
    MinerStatus,
    NotificationEntry,
    WalletData,
)


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

    def __init__(self, state: AppState) -> None:
        super().__init__("Wallet Summary")
        self.state = state
        self._worker: Optional[WalletWorker] = None

        layout = QFormLayout()
        self.username_label = QLabel("-")
        self.balance_label = QLabel("0 DUCO")
        self.pending_label = QLabel("0 DUCO")
        self.last_payout_label = QLabel("N/A")
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: red;")
        self.refresh_button = QPushButton("Refresh Wallet")

        layout.addRow("Username:", self.username_label)
        layout.addRow("Balance:", self.balance_label)
        layout.addRow("Pending:", self.pending_label)
        layout.addRow("Last payout:", self.last_payout_label)
        layout.addRow(self.refresh_button)
        layout.addRow(self.error_label)
        self.setLayout(layout)

        self.state.wallet_changed.connect(self.refresh)
        self.refresh_button.clicked.connect(self._refresh_wallet)
        self.refresh(self.state.wallet)

    def refresh(self, wallet: WalletData) -> None:
        self.username_label.setText(wallet.username or "-")
        self.balance_label.setText(f"{wallet.balance:.4f} DUCO")
        self.pending_label.setText(f"{wallet.pending_rewards:.4f} DUCO")
        self.last_payout_label.setText(wallet.last_payout or "N/A")
        self.error_label.setText("")

    def _refresh_wallet(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self.error_label.setText("Refreshing...")
        self._worker = WalletWorker(self.state)
        self._worker.success.connect(self._on_success)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_success(self, data: WalletData) -> None:
        self.state.set_wallet(data)
        self.error_label.setText("")

    def _on_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.state.log_error(message)


class CpuMinerPanel(QGroupBox):
    """Controls and status for the CPU miner."""

    def __init__(self, state: AppState) -> None:
        super().__init__("CPU Miner")
        self.state = state

        layout = QVBoxLayout()
        self.status_label = QLabel("Stopped")
        self.hashrate_label = QLabel("0.00 H/s")
        self.shares_label = QLabel("0 accepted / 0 rejected")
        self.temp_label = QLabel("Temp: -")
        self.connection_label = QLabel("Status: Connected")
        self.connection_label.setStyleSheet("color: green;")

        button_row = QHBoxLayout()
        self.start_button = QPushButton("Start CPU Miner")
        self.stop_button = QPushButton("Stop")
        self.restart_button = QPushButton("Restart")
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.stop_button)
        button_row.addWidget(self.restart_button)

        layout.addWidget(self.status_label)
        layout.addWidget(self.hashrate_label)
        layout.addWidget(self.shares_label)
        layout.addWidget(self.temp_label)
        layout.addWidget(self.connection_label)
        layout.addLayout(button_row)
        self.setLayout(layout)

        self.start_button.clicked.connect(self._handle_start)
        self.stop_button.clicked.connect(self._handle_stop)
        self.restart_button.clicked.connect(self._handle_restart)

        self.state.cpu_status_changed.connect(self.refresh)
        self.refresh(self.state.cpu_status)

    def _handle_start(self) -> None:
        self.state.update_cpu_status(running=True)

    def _handle_stop(self) -> None:
        self.state.update_cpu_status(running=False, hashrate=0.0)

    def _handle_restart(self) -> None:
        self.state.update_cpu_status(running=True, hashrate=0.0, last_error=None, connected=True)
        self.state.add_notification("CPU miner restarted", miner="CPU")

    def refresh(self, status: MinerStatus) -> None:
        self.status_label.setText("Running" if status.running else "Stopped")
        self.hashrate_label.setText(format_hashrate(status.hashrate))
        self.shares_label.setText(
            f"{status.accepted_shares} accepted / {status.rejected_shares} rejected"
        )
        if status.temperature_c is None:
            self.temp_label.setText("Temp: -")
        else:
            self.temp_label.setText(f"Temp: {status.temperature_c:.1f}°C")
        if status.running and status.connected:
            self.connection_label.setText("Status: Connected")
            self.connection_label.setStyleSheet("color: green;")
        elif not status.running:
            self.connection_label.setText("Status: Stopped")
            self.connection_label.setStyleSheet("color: gray;")
        else:
            self.connection_label.setText(status.last_error or "Status: Disconnected")
            self.connection_label.setStyleSheet("color: red;")


class GpuMinerPanel(QGroupBox):
    """Controls and status for the GPU miner."""

    def __init__(self, state: AppState) -> None:
        super().__init__("GPU Miner")
        self.state = state

        layout = QVBoxLayout()
        self.status_label = QLabel("Stopped")
        self.hashrate_label = QLabel("0.00 H/s")
        self.shares_label = QLabel("0 accepted / 0 rejected")
        self.connection_label = QLabel("Status: Connected")
        self.connection_label.setStyleSheet("color: green;")

        devices_label = QLabel("Devices:")
        self.device_list = QListWidget()

        button_row = QHBoxLayout()
        self.start_button = QPushButton("Start GPU Miner")
        self.stop_button = QPushButton("Stop")
        self.restart_button = QPushButton("Restart")
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.stop_button)
        button_row.addWidget(self.restart_button)

        layout.addWidget(self.status_label)
        layout.addWidget(self.hashrate_label)
        layout.addWidget(self.shares_label)
        layout.addWidget(self.connection_label)
        layout.addWidget(devices_label)
        layout.addWidget(self.device_list)
        layout.addLayout(button_row)
        self.setLayout(layout)

        self.start_button.clicked.connect(self._handle_start)
        self.stop_button.clicked.connect(self._handle_stop)
        self.restart_button.clicked.connect(self._handle_restart)

        self.state.gpu_status_changed.connect(self.refresh_status)
        self.state.config_changed.connect(self.refresh_devices)

        self.refresh_status(self.state.gpu_status)
        self.refresh_devices(self.state.config)

    def _handle_start(self) -> None:
        self.state.update_gpu_status(running=True)

    def _handle_stop(self) -> None:
        self.state.update_gpu_status(running=False, hashrate=0.0)

    def _handle_restart(self) -> None:
        self.state.update_gpu_status(running=True, hashrate=0.0, last_error=None, connected=True)
        self.state.add_notification("GPU miner restarted", miner="GPU")

    def refresh_status(self, status: MinerStatus) -> None:
        self.status_label.setText("Running" if status.running else "Stopped")
        self.hashrate_label.setText(format_hashrate(status.hashrate))
        self.shares_label.setText(
            f"{status.accepted_shares} accepted / {status.rejected_shares} rejected"
        )
        if status.running and status.connected:
            self.connection_label.setText("Status: Connected")
            self.connection_label.setStyleSheet("color: green;")
        elif not status.running:
            self.connection_label.setText("Status: Stopped")
            self.connection_label.setStyleSheet("color: gray;")
        else:
            self.connection_label.setText(status.last_error or "Status: Disconnected")
            self.connection_label.setStyleSheet("color: red;")

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


class NotificationPanel(QGroupBox):
    """Displays notifications about miner health and API errors."""

    def __init__(self, state: AppState) -> None:
        super().__init__("Notifications")
        self.state = state

        layout = QVBoxLayout()
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)
        self.setLayout(layout)

        self.state.notification_added.connect(self._add_entry)
        for entry in self.state.notifications:
            self._append_item(entry)

    def _add_entry(self, entry: NotificationEntry) -> None:
        self._append_item(entry)
        self.list_widget.scrollToBottom()

    def _append_item(self, entry: NotificationEntry) -> None:
        timestamp = time.strftime("%H:%M:%S", time.localtime(entry.timestamp))
        prefix = entry.severity.upper()
        miner = f" ({entry.miner})" if entry.miner else ""
        QListWidgetItem(f"[{timestamp}] {prefix}{miner}: {entry.message}", self.list_widget)


class DiagnosticsPanel(QGroupBox):
    """Shows diagnostic logs and allows refresh without leaving the app."""

    def __init__(self, state: AppState) -> None:
        super().__init__("Diagnostics")
        self.state = state

        layout = QVBoxLayout()
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.refresh_button = QPushButton("Refresh Log")

        layout.addWidget(self.log_view)
        layout.addWidget(self.refresh_button)
        self.setLayout(layout)

        self.refresh_button.clicked.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self.log_view.setPlainText(self.state.read_log_tail())


class HealthMonitor(QObject):
    """Detects miner crashes or disconnects and notifies the user."""

    def __init__(self, state: AppState, timeout_seconds: int = 10, interval_ms: int = 3000) -> None:
        super().__init__()
        self.state = state
        self.timeout_seconds = timeout_seconds
        self.timer = QTimer(self)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self._check_health)

    def start(self) -> None:
        self.timer.start()

    def _check_health(self) -> None:
        now = time.time()
        for miner_name, status, updater in [
            ("CPU", self.state.cpu_status, self.state.update_cpu_status),
            ("GPU", self.state.gpu_status, self.state.update_gpu_status),
        ]:
            if status.running and status.last_heartbeat and now - status.last_heartbeat > self.timeout_seconds:
                updater(running=False, connected=False, last_error="Miner unresponsive")
                self.state.log_error(f"{miner_name} miner stopped responding; stopped for safety.")
            elif status.running and not status.connected:
                updater(last_error=status.last_error or "Lost connection")
                self.state.log_error(f"{miner_name} miner lost connection.")


class WalletWorker(QThread):
    """Fetch wallet data with retry/backoff without blocking the UI."""

    success = Signal(WalletData)
    error = Signal(str)

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self.max_attempts = 3
        self.base_backoff = 1.0

    def run(self) -> None:
        endpoint = f"https://{self.state.config.server}:{self.state.config.port}/wallet"
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = requests.get(endpoint, timeout=5)
                response.raise_for_status()
                payload = response.json()
                wallet = WalletData(
                    username=payload.get("username", ""),
                    balance=float(payload.get("balance", 0.0)),
                    pending_rewards=float(payload.get("pending_rewards", 0.0)),
                    last_payout=payload.get("last_payout"),
                )
                self.success.emit(wallet)
                return
            except requests.RequestException as exc:
                last_error = f"Wallet refresh failed (attempt {attempt}): {exc}"
                self.state.logger.warning(last_error)
                if attempt < self.max_attempts:
                    time.sleep(self.base_backoff * attempt)
                    continue
            except (ValueError, json.JSONDecodeError) as exc:  # malformed payload
                last_error = f"Wallet response error: {exc}"
                self.state.logger.warning(last_error)
                break
        if last_error:
            self.error.emit(last_error)
class AppWindow(QMainWindow):
    """Main application window that wires together panels and state."""

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self.setWindowTitle("Duino Coin")
        self.health_monitor = HealthMonitor(self.state)

        central = QWidget()
        layout = QVBoxLayout()
        self.wallet_panel = WalletSummaryPanel(self.state)
        layout.addWidget(self.wallet_panel)
        layout.addWidget(CpuMinerPanel(self.state))
        layout.addWidget(GpuMinerPanel(self.state))
        layout.addWidget(LiveStatsPanel(self.state))
        layout.addWidget(SettingsPanel(self.state))
        layout.addWidget(NotificationPanel(self.state))
        layout.addWidget(DiagnosticsPanel(self.state))
        layout.addStretch(1)
        central.setLayout(layout)
        self.setCentralWidget(central)

        self._seed_default_state()
        self.health_monitor.start()
        self.wallet_panel._refresh_wallet()

    def _seed_default_state(self) -> None:
        """Populate placeholder data so the UI has initial content."""
        self.state.update_wallet(username="anonymous", balance=0.0, pending_rewards=0.0)
        self.state.update_live_stats(uptime_seconds=0, difficulty=0.0, total_hashes=0)
        self.state.update_config(gpu_devices=["GPU 0", "GPU 1"])


def main(argv: Iterable[str] | None = None) -> int:
    """Start the PySide6 application."""
    app = QApplication(list(argv) if argv is not None else sys.argv)
    state = AppState()
    window = AppWindow(state)
    window.resize(600, 800)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
