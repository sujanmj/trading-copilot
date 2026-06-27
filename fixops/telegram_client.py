"""Minimal Telegram Bot API client for FixOps Phase 1."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


class TelegramAPIError(RuntimeError):
    """Raised when Telegram API calls fail."""


def _to_unix_time(value: datetime | float | int) -> int:
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    return int(value)


class TelegramClient:
    def __init__(self, *, bot_token: str, chat_id: str, api_base: str = "https://api.telegram.org") -> None:
        self.bot_token = str(bot_token or "").strip()
        self.chat_id = str(chat_id or "").strip()
        self.api_base = api_base.rstrip("/")
        if not self.bot_token:
            raise TelegramAPIError("TELEGRAM_BOT_TOKEN is missing.")
        if not self.chat_id:
            raise TelegramAPIError("TELEGRAM_CHAT_ID is missing.")

    def _api_url(self, method: str) -> str:
        return f"{self.api_base}/bot{self.bot_token}/{method}"

    def _request(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = urllib.parse.urlencode({
            key: json.dumps(value) if isinstance(value, (dict, list)) else value
            for key, value in payload.items()
            if value is not None
        }).encode("utf-8")
        request = urllib.request.Request(
            self._api_url(method),
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=max(10, int(payload.get("timeout") or 10) + 5)) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8")[:300]
            except Exception:
                detail = str(exc)
            raise TelegramAPIError(f"Telegram API {method} failed with HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise TelegramAPIError(f"Telegram API {method} failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise TelegramAPIError(f"Telegram API {method} timed out.") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TelegramAPIError(f"Telegram API {method} returned invalid JSON.") from exc

        if not parsed.get("ok"):
            description = str(parsed.get("description") or "unknown error")[:300]
            raise TelegramAPIError(f"Telegram API {method} failed: {description}")
        return parsed

    def send_message(self, text: str) -> dict[str, Any]:
        """Send a Telegram message to the configured chat."""
        return self._request("sendMessage", {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }).get("result", {})

    def send_command(self, command: str) -> dict[str, Any]:
        """Send a slash command to the configured chat."""
        text = str(command or "").strip()
        if not text.startswith("/"):
            text = f"/{text}"
        return self.send_message(text)

    def read_recent_updates(
        self,
        *,
        offset: int | None = None,
        timeout_seconds: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Read recent updates visible to this bot token."""
        result = self._request("getUpdates", {
            "offset": offset,
            "timeout": max(0, int(timeout_seconds)),
            "limit": max(1, min(100, int(limit))),
            "allowed_updates": ["message", "edited_message", "channel_post"],
        }).get("result", [])
        return result if isinstance(result, list) else []

    def collect_messages_after(
        self,
        start_time: datetime | float | int,
        *,
        timeout_seconds: int = 180,
        idle_timeout_seconds: int = 15,
    ) -> list[dict[str, Any]]:
        """Collect messages from the configured chat after start_time.

        Collection stops when the overall timeout is reached or no new matching
        message arrives for idle_timeout_seconds.
        """
        start_ts = _to_unix_time(start_time)
        deadline = time.monotonic() + max(1, int(timeout_seconds))
        last_new_message = time.monotonic()
        offset: int | None = None
        seen: set[tuple[str, int]] = set()
        messages: list[dict[str, Any]] = []

        while time.monotonic() < deadline:
            remaining = max(1, int(deadline - time.monotonic()))
            poll_timeout = min(10, remaining)
            updates = self.read_recent_updates(offset=offset, timeout_seconds=poll_timeout)

            if updates:
                offset = max(int(update.get("update_id", 0)) for update in updates) + 1

            new_count = 0
            for update in updates:
                message = (
                    update.get("message")
                    or update.get("edited_message")
                    or update.get("channel_post")
                )
                if not isinstance(message, dict):
                    continue
                chat = message.get("chat") or {}
                if str(chat.get("id") or "") != self.chat_id:
                    continue
                message_date = int(message.get("date") or 0)
                if message_date < start_ts:
                    continue
                message_id = int(message.get("message_id") or 0)
                key = (str(chat.get("id") or ""), message_id)
                if key in seen:
                    continue
                seen.add(key)
                sender = message.get("from") or {}
                text = (
                    message.get("text")
                    or message.get("caption")
                    or ""
                )
                messages.append({
                    "update_id": update.get("update_id"),
                    "message_id": message_id,
                    "date": message_date,
                    "iso_time": datetime.fromtimestamp(message_date, tz=timezone.utc).isoformat(),
                    "chat_id": str(chat.get("id") or ""),
                    "from_id": sender.get("id"),
                    "from_username": sender.get("username"),
                    "from_is_bot": sender.get("is_bot"),
                    "text": str(text),
                    "raw": message,
                })
                new_count += 1

            if new_count:
                last_new_message = time.monotonic()
            elif time.monotonic() - last_new_message >= max(1, int(idle_timeout_seconds)):
                break

        return messages
