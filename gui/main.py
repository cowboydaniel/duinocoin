"""PySide6 GUI entry point for Duino Coin."""

from __future__ import annotations

import sys
from dataclasses import replace
from typing import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config import Configuration, THEMES, validate_config
from .state import AppState, LiveStats, MinerStatus, WalletData


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
        if not self.state.config.gpu_devices:
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
