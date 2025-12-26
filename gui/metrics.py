"""Parsing helpers for miner stdout to normalized metrics."""

from __future__ import annotations

import re
from collections import deque
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Deque, Optional, Tuple

from .state import MinerLogEntry, MinerMetrics


HASHRATE_PATTERN = re.compile(r"(?P<value>\\d+(?:\\.\\d+)?)\\s*(?P<unit>mh/s|kh/s|h/s)", re.IGNORECASE)
TEMP_PATTERN = re.compile(r"(temp(?:erature)?[:=]?\\s*)(?P<value>\\d+(?:\\.\\d+)?)", re.IGNORECASE)
REWARD_PATTERN = re.compile(r"(?P<value>\\d+(?:\\.\\d+)?)\\s*duco", re.IGNORECASE)
SHARE_RATE_PATTERN = re.compile(r"share rate[:=]?\\s*(?P<value>\\d+(?:\\.\\d+)?)/?\\s*(?:m|min)", re.IGNORECASE)


def _normalize_hashrate(value: float, unit: str) -> float:
    unit_lower = unit.lower()
    if unit_lower.startswith("mh"):
        return value * 1_000_000
    if unit_lower.startswith("kh"):
        return value * 1_000
    return value


class MinerMetricsParser:
    """Stateful parser that transforms miner stdout lines into metrics."""

    def __init__(self, window_seconds: int = 60) -> None:
        self.metrics = MinerMetrics()
        self.share_events: Deque[datetime] = deque()
        self.window = timedelta(seconds=window_seconds)

    def parse_line(self, line: str) -> Tuple[MinerMetrics, Optional[MinerLogEntry]]:
        """Parse a single stdout line and update internal metrics."""
        metrics = replace(self.metrics)
        log_entry: Optional[MinerLogEntry] = None
        text = line.strip()
        if not text:
            return metrics, None
        lowered = text.lower()

        hashrate_match = HASHRATE_PATTERN.search(lowered)
        if hashrate_match:
            metrics.hashrate = _normalize_hashrate(
                float(hashrate_match.group("value")), hashrate_match.group("unit")
            )

        temp_match = TEMP_PATTERN.search(lowered)
        if temp_match:
            metrics.temperature_c = float(temp_match.group("value"))

        share_rate_match = SHARE_RATE_PATTERN.search(lowered)
        if share_rate_match:
            metrics.share_rate_per_min = float(share_rate_match.group("value"))

        reward_match = REWARD_PATTERN.search(lowered)
        reward_in_line = reward_match.group("value") if reward_match else None

        if "accepted" in lowered and "share" in lowered:
            metrics.accepted_shares += 1
            self._track_share_event()
            metrics.share_rate_per_min = self._current_share_rate_per_min()
            if reward_in_line:
                metrics.rewards_duco += float(reward_in_line)
        elif "rejected" in lowered and "share" in lowered:
            metrics.rejected_shares += 1
            self._track_share_event()
            metrics.share_rate_per_min = self._current_share_rate_per_min()
            log_entry = MinerLogEntry(level="warning", message=text)
        elif reward_in_line:
            metrics.rewards_duco += float(reward_in_line)

        if any(term in lowered for term in ["error", "disconnect", "timeout"]):
            metrics.last_error = text
            log_entry = MinerLogEntry(level="error", message=text)

        metrics.projected_duco_per_day = self._project_duco_per_day(metrics)

        if log_entry is None:
            # Default to info-level log for visibility of recent miner messages.
            log_entry = MinerLogEntry(level="info", message=text)

        self.metrics = metrics
        return metrics, log_entry

    def _track_share_event(self) -> None:
        now = datetime.utcnow()
        self.share_events.append(now)
        self._trim_events(now)

    def _trim_events(self, now: datetime) -> None:
        while self.share_events and now - self.share_events[0] > self.window:
            self.share_events.popleft()

    def _current_share_rate_per_min(self) -> float:
        now = datetime.utcnow()
        self._trim_events(now)
        return len(self.share_events) / (self.window.total_seconds() / 60)

    def _project_duco_per_day(self, metrics: MinerMetrics) -> float:
        if metrics.accepted_shares == 0 or metrics.share_rate_per_min == 0:
            return 0.0
        avg_reward_per_share = metrics.rewards_duco / metrics.accepted_shares
        return avg_reward_per_share * metrics.share_rate_per_min * 60 * 24

    def get_metrics(self) -> MinerMetrics:
        """Return the latest metrics snapshot."""
        return self.metrics
