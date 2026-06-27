"""Configuration helpers for FixOps Controller."""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Raised when required FixOps configuration is missing."""


@dataclass(frozen=True)
class FixOpsConfig:
    telegram_bot_token: str
    telegram_chat_id: str


def load_config() -> FixOpsConfig:
    """Load required Telegram settings from environment variables."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    missing: list[str] = []
    if not token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not chat_id:
        missing.append("TELEGRAM_CHAT_ID")

    if missing:
        joined = ", ".join(missing)
        raise ConfigError(
            f"Missing required environment variable(s): {joined}. "
            "Set them before running: python fixops/fixloop.py"
        )

    return FixOpsConfig(
        telegram_bot_token=token,
        telegram_chat_id=chat_id,
    )
