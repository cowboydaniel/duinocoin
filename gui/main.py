"""PySide6 GUI entry point for Duino Coin."""

from __future__ import annotations

import sys
from typing import Iterable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QFrame,
    QListWidgetItem,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

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
        self.parsers = {"cpu": MinerMetricsParser(), "gpu": MinerMetricsParser()}
        self.setWindowTitle("Duino Coin")

        central = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(WalletSummaryPanel(self.state))
        layout.addWidget(CpuMinerPanel(self.state))
        layout.addWidget(GpuMinerPanel(self.state))
        layout.addWidget(LiveStatsPanel(self.state))
        layout.addWidget(MinerGaugesPanel(self.state))
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
