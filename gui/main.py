"""PySide6 GUI entry point for Duino Coin."""

from __future__ import annotations

import sys
from typing import Iterable

from PySide6.QtCore import Qt
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
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .state import AppState, Configuration, LiveStats, MinerStatus, WalletData


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

        layout = QFormLayout()
        self.username_label = QLabel("-")
        self.balance_label = QLabel("0 DUCO")
        self.pending_label = QLabel("0 DUCO")
        self.last_payout_label = QLabel("N/A")

        layout.addRow("Username:", self.username_label)
        layout.addRow("Balance:", self.balance_label)
        layout.addRow("Pending:", self.pending_label)
        layout.addRow("Last payout:", self.last_payout_label)
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

    def __init__(self, state: AppState) -> None:
        super().__init__("CPU Miner")
        self.state = state

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
        self.state.update_cpu_status(running=True)

    def _handle_stop(self) -> None:
        self.state.update_cpu_status(running=False, hashrate=0.0)

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


class GpuMinerPanel(QGroupBox):
    """Controls and status for the GPU miner."""

    def __init__(self, state: AppState) -> None:
        super().__init__("GPU Miner")
        self.state = state

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
        self.state.update_gpu_status(running=True)

    def _handle_stop(self) -> None:
        self.state.update_gpu_status(running=False, hashrate=0.0)

    def refresh_status(self, status: MinerStatus) -> None:
        self.status_label.setText("Running" if status.running else "Stopped")
        self.hashrate_label.setText(format_hashrate(status.hashrate))
        self.shares_label.setText(
            f"{status.accepted_shares} accepted / {status.rejected_shares} rejected"
        )

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
        self.setWindowTitle("Duino Coin")

        central = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(WalletSummaryPanel(self.state))
        layout.addWidget(CpuMinerPanel(self.state))
        layout.addWidget(GpuMinerPanel(self.state))
        layout.addWidget(LiveStatsPanel(self.state))
        layout.addWidget(SettingsPanel(self.state))
        layout.addStretch(1)
        central.setLayout(layout)
        self.setCentralWidget(central)

        self._seed_default_state()

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

