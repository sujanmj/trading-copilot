"""Phase 1 FixOps Controller loop.

Runs one /full collection cycle and prints a compact summary.
"""

from __future__ import annotations

import sys

from config import ConfigError, load_config
from report_collector import collect_full_report
from telegram_client import TelegramAPIError, TelegramClient


def _clip(text: str, limit: int = 500) -> str:
    body = str(text or "")
    return body[:limit]


def main() -> int:
    try:
        config = load_config()
        client = TelegramClient(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )
        result = collect_full_report(client)
    except ConfigError as exc:
        print(f"FixOps config error: {exc}", file=sys.stderr)
        return 2
    except TelegramAPIError as exc:
        print(f"FixOps Telegram API error: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"FixOps unexpected error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    text = str(result.get("text") or "")
    messages = result.get("messages") or []
    text_path = result.get("text_path")

    print("FixOps cycle complete")
    print(f"Total messages collected: {len(messages)}")
    print(f"Saved report path: {text_path}")
    print("")
    print("First 500 chars:")
    print(_clip(text, 500))
    print("")
    print("Last 500 chars:")
    print(text[-500:] if len(text) > 500 else text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
