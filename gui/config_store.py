"""Helpers for loading and saving GUI configuration."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from .state import Configuration


CONFIG_DIR = Path(
    os.environ.get("DUINO_GUI_CONFIG_DIR", Path.home() / ".config" / "duinocoin_gui")
)
CONFIG_PATH = CONFIG_DIR / "settings.json"
ENV_USERNAME = "DUINO_WALLET_USERNAME"
ENV_TOKEN = "DUINO_WALLET_TOKEN"


def _merge_config_dict(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = base.copy()
    for key, value in updates.items():
        if key in merged:
            merged[key] = value
    return merged


def load_config(defaults: Configuration) -> Configuration:
    """Load persisted configuration with environment overrides."""
    data = asdict(defaults)

    if CONFIG_PATH.exists():
        try:
            file_data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            file_data = {}
        data = _merge_config_dict(data, file_data)

    env_username = os.environ.get(ENV_USERNAME)
    env_token = os.environ.get(ENV_TOKEN)
    if env_username:
        data["wallet_username"] = env_username
    if env_token:
        data["wallet_token"] = env_token

    return replace(defaults, **data)


def save_config(config: Configuration) -> None:
    """Persist configuration to disk with restricted permissions."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    serialized = asdict(config)
    CONFIG_PATH.write_text(json.dumps(serialized, indent=2), encoding="utf-8")
    try:
        CONFIG_PATH.chmod(0o600)
    except OSError:
        # Best effort; environments like Windows may not support chmod the same way.
        pass
