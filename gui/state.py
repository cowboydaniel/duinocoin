"""Shared application state for the PySide6 GUI."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from PySide6.QtCore import QObject, Signal

from .config import Configuration, load_config, save_config, validate_config


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
class LiveStats:
    """Aggregated statistics about the mining session."""

    uptime_seconds: int = 0
    total_hashes: int = 0
    difficulty: float = 0.0
    ping_ms: Optional[float] = None


class AppState(QObject):
    """Central store that emits signals whenever state changes."""

    wallet_changed = Signal(WalletData)
    cpu_status_changed = Signal(MinerStatus)
    gpu_status_changed = Signal(MinerStatus)
    stats_changed = Signal(LiveStats)
    config_changed = Signal(Configuration)

    def __init__(self) -> None:
        super().__init__()
        self.wallet = WalletData()
        self.cpu_status = MinerStatus()
        self.gpu_status = MinerStatus()
        self.live_stats = LiveStats()
        self.config = load_config()

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
        self.config = validate_config(config)
        save_config(self.config)
        self.config_changed.emit(self.config)

    def update_config(self, **updates) -> None:
        updated = replace(self.config, **updates)
        self.set_config(updated)
