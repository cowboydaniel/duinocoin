"""Shared application state for the PySide6 GUI."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import List, Optional

from PySide6.QtCore import QObject, Signal


@dataclass
class WalletData:
    """Represents wallet metadata and balances."""

    username: str = ""
    balance: float = 0.0
    pending_rewards: float = 0.0
    last_payout: Optional[str] = None


@dataclass
class MinerStatus:
    """Represents status for a single miner."""

    running: bool = False
    hashrate: float = 0.0
    accepted_shares: int = 0
    rejected_shares: int = 0
    temperature_c: Optional[float] = None


@dataclass
class MinerMetrics:
    """Normalized metrics derived from miner stdout."""

    hashrate: float = 0.0
    share_rate_per_min: float = 0.0
    accepted_shares: int = 0
    rejected_shares: int = 0
    rewards_duco: float = 0.0
    projected_duco_per_day: float = 0.0
    temperature_c: Optional[float] = None
    last_error: Optional[str] = None


@dataclass
class MinerLogEntry:
    """A recent message emitted by the miner processes."""

    level: str
    message: str


@dataclass
class LiveStats:
    """Aggregated statistics about the mining session."""

    uptime_seconds: int = 0
    total_hashes: int = 0
    difficulty: float = 0.0
    ping_ms: Optional[float] = None


@dataclass
class Configuration:
    """User configuration for the miners."""

    cpu_threads: int = 1
    gpu_devices: List[str] = field(default_factory=list)
    intensity: int = 1
    server: str = "server.duinocoin.com"
    port: int = 2813
    auto_start: bool = False


class AppState(QObject):
    """Central store that emits signals whenever state changes."""

    wallet_changed = Signal(WalletData)
    cpu_status_changed = Signal(MinerStatus)
    gpu_status_changed = Signal(MinerStatus)
    stats_changed = Signal(LiveStats)
    config_changed = Signal(Configuration)
    metrics_changed = Signal(str, MinerMetrics)
    log_added = Signal(MinerLogEntry)

    def __init__(self) -> None:
        super().__init__()
        self.wallet = WalletData()
        self.cpu_status = MinerStatus()
        self.gpu_status = MinerStatus()
        self.live_stats = LiveStats()
        self.config = Configuration()
        self.metrics: dict[str, MinerMetrics] = {"cpu": MinerMetrics(), "gpu": MinerMetrics()}
        self.logs: List[MinerLogEntry] = []

    def set_wallet(self, wallet: WalletData) -> None:
        self.wallet = wallet
        self.wallet_changed.emit(self.wallet)

    def update_wallet(self, **updates) -> None:
        self.wallet = replace(self.wallet, **updates)
        self.wallet_changed.emit(self.wallet)

    def set_cpu_status(self, status: MinerStatus) -> None:
        self.cpu_status = status
        self.cpu_status_changed.emit(self.cpu_status)

    def update_cpu_status(self, **updates) -> None:
        self.cpu_status = replace(self.cpu_status, **updates)
        self.cpu_status_changed.emit(self.cpu_status)

    def set_gpu_status(self, status: MinerStatus) -> None:
        self.gpu_status = status
        self.gpu_status_changed.emit(self.gpu_status)

    def update_gpu_status(self, **updates) -> None:
        self.gpu_status = replace(self.gpu_status, **updates)
        self.gpu_status_changed.emit(self.gpu_status)

    def set_live_stats(self, stats: LiveStats) -> None:
        self.live_stats = stats
        self.stats_changed.emit(self.live_stats)

    def update_live_stats(self, **updates) -> None:
        self.live_stats = replace(self.live_stats, **updates)
        self.stats_changed.emit(self.live_stats)

    def set_config(self, config: Configuration) -> None:
        self.config = config
        self.config_changed.emit(self.config)

    def update_config(self, **updates) -> None:
        self.config = replace(self.config, **updates)
        self.config_changed.emit(self.config)

    def set_metrics(self, miner_type: str, metrics: MinerMetrics) -> None:
        """Persist metrics for a miner (e.g., 'cpu' or 'gpu') and emit changes."""
        self.metrics[miner_type] = metrics
        self.metrics_changed.emit(miner_type, metrics)

    def update_metrics(self, miner_type: str, **updates) -> None:
        current = self.metrics.get(miner_type, MinerMetrics())
        self.metrics[miner_type] = replace(current, **updates)
        self.metrics_changed.emit(miner_type, self.metrics[miner_type])

    def add_log_entry(self, entry: MinerLogEntry, max_entries: int = 100) -> None:
        """Append a log entry and keep the buffer bounded."""
        self.logs.append(entry)
        if len(self.logs) > max_entries:
            self.logs = self.logs[-max_entries:]
        self.log_added.emit(entry)
