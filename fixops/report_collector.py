"""Collect a Telegram /full report for FixOps incidents."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telegram_client import TelegramClient

FIXOPS_DIR = Path(__file__).resolve().parent
INCIDENTS_DIR = FIXOPS_DIR / "incidents"
LATEST_TEXT_REPORT = INCIDENTS_DIR / "latest_full_report.txt"
LATEST_JSON_REPORT = INCIDENTS_DIR / "latest_full_report.json"


def _format_text_report(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for idx, message in enumerate(messages, 1):
        sender = message.get("from_username") or message.get("from_id") or "unknown"
        iso_time = message.get("iso_time") or ""
        text = str(message.get("text") or "")
        lines.extend([
            f"--- message {idx} | {iso_time} | from={sender} ---",
            text,
            "",
        ])
    return "\n".join(lines).rstrip() + ("\n" if lines else "")


def collect_full_report(
    client: TelegramClient,
    *,
    timeout_seconds: int = 180,
    idle_timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Send /full, collect replies, and save latest report artifacts."""
    INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)
    start_time = datetime.now(timezone.utc)
    sent = client.send_command("/full")
    messages = client.collect_messages_after(
        start_time,
        timeout_seconds=timeout_seconds,
        idle_timeout_seconds=idle_timeout_seconds,
    )

    text_report = _format_text_report(messages)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "command": "/full",
        "sent_message_id": sent.get("message_id"),
        "total_messages": len(messages),
        "timeout_seconds": timeout_seconds,
        "idle_timeout_seconds": idle_timeout_seconds,
        "messages": messages,
    }

    LATEST_TEXT_REPORT.write_text(text_report, encoding="utf-8")
    LATEST_JSON_REPORT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "messages": messages,
        "text": text_report,
        "json": payload,
        "text_path": LATEST_TEXT_REPORT,
        "json_path": LATEST_JSON_REPORT,
    }
