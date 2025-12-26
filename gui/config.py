"""Configuration helpers for the Duino Coin GUI."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import List


CONFIG_PATH = Path.home() / ".duinocoin_gui.json"
THEMES = {"system", "light", "dark"}


def _default_threads() -> int:
    cpu_count = os.cpu_count() or 1
    # Leave a core free for the OS when possible.
    return max(1, cpu_count - 1)


@dataclass
class Configuration:
    """Persistent user configuration for the miners."""

    cpu_threads: int = field(default_factory=_default_threads)
    gpu_devices: List[str] = field(default_factory=list)
    intensity: int = 10
    server: str = "server.duinocoin.com"
    port: int = 2813
    auto_start: bool = False
    refresh_interval: int = 5
    theme: str = "system"


def validate_config(config: Configuration) -> Configuration:
    """Validate and normalize a configuration.

    Raises:
        ValueError: If any field contains an invalid value.
    """

    errors = []

    if config.cpu_threads < 1:
        errors.append("CPU threads must be at least 1.")
    if config.cpu_threads > 512:
        errors.append("CPU threads cannot exceed 512.")

    if config.intensity < 1 or config.intensity > 100:
        errors.append("Intensity must be between 1 and 100.")

    if not config.server.strip():
        errors.append("Server hostname cannot be empty.")

    if config.port < 1 or config.port > 65535:
        errors.append("Port must be between 1 and 65535.")

    if config.refresh_interval < 1:
        errors.append("Refresh interval must be at least 1 second.")

    normalized_theme = config.theme.lower()
    if normalized_theme not in THEMES:
        errors.append("Theme must be one of: system, light, dark.")

    if errors:
        raise ValueError("\n".join(errors))

    return replace(config, server=config.server.strip(), theme=normalized_theme)


def _merge_config(defaults: Configuration, overrides: dict) -> Configuration:
    merged = asdict(defaults)
    merged.update(overrides)
    return Configuration(**merged)


def load_config(path: Path = CONFIG_PATH) -> Configuration:
    """Load configuration from disk or return defaults on failure."""

    defaults = Configuration()
    if not path.exists():
        return defaults

    try:
        raw = json.loads(path.read_text())
        config = _merge_config(defaults, raw)
        return validate_config(config)
    except Exception:
        # Fall back to defaults if anything goes wrong.
        return defaults


def save_config(config: Configuration, path: Path = CONFIG_PATH) -> None:
    """Persist configuration to disk after validation."""

    validated = validate_config(config)
    path.write_text(json.dumps(asdict(validated), indent=2))
