"""Run Trading Copilot /full internally and capture Telegram output locally.

This runner deliberately avoids Telegram getUpdates. It monkeypatches the
listener send path for one command invocation, captures outgoing messages, and
then restores the original functions in a finally block.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


FIXOPS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = FIXOPS_DIR.parent
INCIDENTS_DIR = FIXOPS_DIR / "incidents"
TXT_PATH = INCIDENTS_DIR / "latest_full_report.txt"
JSON_PATH = INCIDENTS_DIR / "latest_full_report.json"
COMMAND = "/full"
FROM_USER = "fixops"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


@dataclass
class CaptureState:
    command: str
    cycle_id: str
    forward_to_telegram: bool
    original_send_message: Callable[..., Any]
    messages: list[dict[str, Any]] = field(default_factory=list)

    def send_message(
        self,
        text: Any,
        parse_mode: str = "HTML",
        *,
        command: str = "",
        cycle_id: str = "",
        message_kind: str = "final",
        **kwargs: Any,
    ) -> Any:
        """Capture a Telegram send call and optionally forward it."""

        record: dict[str, Any] = {
            "index": len(self.messages) + 1,
            "timestamp": _utc_now(),
            "text": _as_text(text),
            "command": command or self.command,
            "cycle_id": cycle_id or self.cycle_id,
            "message_kind": message_kind or "final",
            "parse_mode": parse_mode,
        }
        if kwargs:
            record["extra_keys"] = sorted(kwargs.keys())

        self.messages.append(record)

        if not self.forward_to_telegram:
            return True

        try:
            return self.original_send_message(
                text,
                parse_mode=parse_mode,
                command=command,
                cycle_id=cycle_id,
                message_kind=message_kind,
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001 - capture should not hide restore.
            record["forward_error"] = f"{type(exc).__name__}: {exc}"
            print(f"Telegram forward failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return False


def _format_text_report(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        parts.append(
            "\n".join(
                [
                    (
                        f"--- message {message['index']} | {message['timestamp']} | "
                        f"command={message.get('command', '')} | "
                        f"cycle_id={message.get('cycle_id', '')} | "
                        f"kind={message.get('message_kind', '')} ---"
                    ),
                    message.get("text", ""),
                ]
            )
        )
    return "\n\n".join(parts)


def _save_report(payload: dict[str, Any]) -> tuple[Path, Path, str]:
    INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)
    report_text = _format_text_report(payload["messages"])
    TXT_PATH.write_text(report_text, encoding="utf-8")
    JSON_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return TXT_PATH, JSON_PATH, report_text


def run_internal_full(*, send_telegram: bool = False) -> dict[str, Any]:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    import backend.orchestration.telegram_listener as listener
    import backend.orchestration.telegram_review as review

    started_at = _utc_now()
    cycle_id = f"fixops-{uuid.uuid4().hex[:12]}"

    original_listener_send = listener.send_message
    original_review_send = getattr(review, "send_message", None)

    capture = CaptureState(
        command=COMMAND,
        cycle_id=cycle_id,
        forward_to_telegram=send_telegram,
        original_send_message=original_listener_send,
    )

    listener.send_message = capture.send_message
    if original_review_send is not None:
        review.send_message = capture.send_message

    command_error = ""
    try:
        listener.handle_command(COMMAND, FROM_USER)
    except Exception as exc:  # noqa: BLE001 - save captured output before surfacing.
        command_error = f"{type(exc).__name__}: {exc}"
    finally:
        listener.send_message = original_listener_send
        if original_review_send is not None:
            review.send_message = original_review_send

    finished_at = _utc_now()
    payload: dict[str, Any] = {
        "command": COMMAND,
        "started_at": started_at,
        "finished_at": finished_at,
        "message_count": len(capture.messages),
        "messages": capture.messages,
    }
    if command_error:
        payload["command_error"] = command_error

    return payload


def _print_summary(payload: dict[str, Any], txt_path: Path, json_path: Path, report_text: str) -> None:
    print(f"Command executed: {payload['command']}")
    if payload.get("command_error"):
        print(f"Command warning: {payload['command_error']}")
    print(f"Message count: {payload['message_count']}")
    print(f"Saved txt path: {txt_path}")
    print(f"Saved json path: {json_path}")
    print("First 500 chars:")
    print(report_text[:500])
    print("Last 500 chars:")
    print(report_text[-500:] if report_text else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture the internal /full Telegram report locally.")
    parser.add_argument(
        "--send-telegram",
        action="store_true",
        help="Forward captured messages to the original Telegram send path.",
    )
    args = parser.parse_args(argv)

    try:
        payload = run_internal_full(send_telegram=args.send_telegram)
        txt_path, json_path, report_text = _save_report(payload)
        _print_summary(payload, txt_path, json_path, report_text)
        return 1 if payload.get("command_error") else 0
    except Exception as exc:  # noqa: BLE001 - CLI should show a clear local error.
        print(f"FixOps internal runner error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
