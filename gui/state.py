"""Shared application state for the PySide6 GUI."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
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
    connected: bool = True
    last_error: Optional[str] = None
    last_heartbeat: Optional[float] = None


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


@dataclass
class NotificationEntry:
    """Represents an in-app notification about miner health or API errors."""

    message: str
    severity: str = "info"
    miner: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


class AppState(QObject):
    """Central store that emits signals whenever state changes."""

    wallet_changed = Signal(WalletData)
    cpu_status_changed = Signal(MinerStatus)
    gpu_status_changed = Signal(MinerStatus)
    stats_changed = Signal(LiveStats)
    config_changed = Signal(Configuration)
    notification_added = Signal(NotificationEntry)

    def __init__(self) -> None:
        super().__init__()
        self.wallet = WalletData()
        self.cpu_status = MinerStatus()
        self.gpu_status = MinerStatus()
        self.live_stats = LiveStats()
        self.config = Configuration()
        self.notifications: List[NotificationEntry] = []
        self.log_path = Path("duinocoin-gui.log")
        self.logger = logging.getLogger("duinocoin.gui")
        self._configure_logger()

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
        prepared = self._prepare_status_updates(self.cpu_status, updates)
        self.cpu_status = replace(self.cpu_status, **prepared)
        self.cpu_status_changed.emit(self.cpu_status)

    def set_gpu_status(self, status: MinerStatus) -> None:
        self.gpu_status = status
        self.gpu_status_changed.emit(self.gpu_status)

    def update_gpu_status(self, **updates) -> None:
        prepared = self._prepare_status_updates(self.gpu_status, updates)
        self.gpu_status = replace(self.gpu_status, **prepared)
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

    def add_notification(self, message: str, severity: str = "info", miner: Optional[str] = None) -> None:
        entry = NotificationEntry(message=message, severity=severity, miner=miner)
        self.notifications.append(entry)
        self.notification_added.emit(entry)

    def log_error(self, message: str) -> None:
        self.logger.error(message)
        self.add_notification(message, severity="error")

    def read_log_tail(self, max_bytes: int = 32_000) -> str:
        try:
            data = self.log_path.read_bytes()
        except FileNotFoundError:
            return "No log entries yet."
        if len(data) > max_bytes:
            data = data[-max_bytes:]
            prefix = b"... (truncated)\\n"
            data = prefix + data
        return data.decode("utf-8", errors="replace")

    def _prepare_status_updates(self, status: MinerStatus, updates: dict) -> dict:
        prepared = dict(updates)
        running = prepared.get("running", status.running)
        if running:
            prepared.setdefault("connected", True)
            prepared.setdefault("last_heartbeat", time.time())
        else:
            prepared.setdefault("connected", False)
        return prepared

    def _configure_logger(self) -> None:
        if self.logger.handlers:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(self.log_path, maxBytes=256_000, backupCount=3, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        handler.setFormatter(formatter)
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(handler)
