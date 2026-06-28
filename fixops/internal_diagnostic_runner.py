"""Capture read-only Telegram diagnostics internally for FixOps analysis."""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


FIXOPS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = FIXOPS_DIR.parent
INCIDENTS_DIR = FIXOPS_DIR / "incidents"
TXT_PATH = INCIDENTS_DIR / "latest_diagnostic_report.txt"
JSON_PATH = INCIDENTS_DIR / "latest_diagnostic_report.json"
FROM_USER = "fixops"
COMMAND_SET = "fixops_readonly_diagnostics"
COMMANDS = [
    "/status",
    "/stats",
    "/elite",
    "/opps",
    "/risks",
    "/calibration",
    "/review",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        from backend.telegram.formatting.telegram_formatter import sanitize_telegram_text

        return sanitize_telegram_text(value)
    except Exception:
        return str(value).replace("\ufffd", "")


@dataclass
class CaptureState:
    current_command: str = ""
    current_cycle_id: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)

    def start_command(self, command: str) -> None:
        self.current_command = command
        self.current_cycle_id = f"fixops-{command.strip('/').replace('/', '-')}-{uuid.uuid4().hex[:8]}"

    def send_message(
        self,
        text: Any,
        parse_mode: str = "HTML",
        *,
        command: str = "",
        cycle_id: str = "",
        message_kind: str = "final",
        **_kwargs: Any,
    ) -> bool:
        self.messages.append(
            {
                "timestamp": _utc_now(),
                "command": f"/{str(command).lstrip('/')}" if command else self.current_command,
                "cycle_id": cycle_id or self.current_cycle_id,
                "message_kind": message_kind or "final",
                "text": _as_text(text),
            }
        )
        return True

    def capture_error(self, command: str, exc: Exception) -> None:
        self.messages.append(
            {
                "timestamp": _utc_now(),
                "command": command,
                "cycle_id": self.current_cycle_id,
                "message_kind": "error",
                "text": f"FixOps diagnostic command failed: {type(exc).__name__}: {exc}",
            }
        )


def _wait_for_capture_idle(capture: CaptureState, *, timeout_seconds: float = 4.0, idle_seconds: float = 0.6) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_count = len(capture.messages)
    idle_since = time.monotonic()
    while time.monotonic() < deadline:
        time.sleep(0.1)
        count = len(capture.messages)
        if count != last_count:
            last_count = count
            idle_since = time.monotonic()
            continue
        if time.monotonic() - idle_since >= idle_seconds:
            return


def _format_text_report(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for index, message in enumerate(messages, start=1):
        parts.append(
            "\n".join(
                [
                    (
                        f"--- message {index} | {message.get('timestamp', '')} | "
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


def _patch_if_present(module: Any, attr_name: str, replacement: Callable[..., Any], originals: list[tuple[Any, str, Any]]) -> None:
    if module is not None and hasattr(module, attr_name):
        original = getattr(module, attr_name)
        originals.append((module, attr_name, original))
        setattr(module, attr_name, replacement)


def run_internal_diagnostics() -> dict[str, Any]:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    import backend.orchestration.telegram_listener as listener

    review = None
    brain_pusher = None
    try:
        import backend.orchestration.telegram_review as review
    except Exception:
        review = None
    try:
        import backend.orchestration.telegram_brain_pusher as brain_pusher
    except Exception:
        brain_pusher = None

    capture = CaptureState()
    originals: list[tuple[Any, str, Any]] = []
    started_at = _utc_now()

    try:
        _patch_if_present(listener, "send_message", capture.send_message, originals)
        _patch_if_present(review, "send_message", capture.send_message, originals)
        _patch_if_present(brain_pusher, "send_message", capture.send_message, originals)

        # Keep this diagnostic runner read-only and deterministic by preventing
        # daemon command work from escaping the capture window.
        if hasattr(listener, "run_in_background"):
            original_background = listener.run_in_background
            originals.append((listener, "run_in_background", original_background))

            def _run_inline(target: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
                target(*args, **kwargs)

            listener.run_in_background = _run_inline

        for command in COMMANDS:
            capture.start_command(command)
            try:
                listener.handle_command(command, FROM_USER)
            except Exception as exc:  # noqa: BLE001 - continue collecting remaining diagnostics.
                capture.capture_error(command, exc)
            _wait_for_capture_idle(capture)
    finally:
        for module, attr_name, original in reversed(originals):
            setattr(module, attr_name, original)

    finished_at = _utc_now()
    return {
        "command_set": COMMAND_SET,
        "started_at": started_at,
        "finished_at": finished_at,
        "commands": COMMANDS,
        "message_count": len(capture.messages),
        "messages": capture.messages,
    }


def _print_summary(payload: dict[str, Any], txt_path: Path, json_path: Path, report_text: str) -> None:
    print(f"Command set executed: {payload['command_set']}")
    print(f"Message count: {payload['message_count']}")
    print(f"Saved txt path: {txt_path}")
    print(f"Saved json path: {json_path}")
    print("First 500 chars:")
    print(report_text[:500])
    print("Last 500 chars:")
    print(report_text[-500:] if report_text else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture read-only internal Telegram diagnostics locally.")
    parser.parse_args(argv)

    try:
        payload = run_internal_diagnostics()
        txt_path, json_path, report_text = _save_report(payload)
        _print_summary(payload, txt_path, json_path, report_text)
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI should show a clear local error.
        print(f"FixOps diagnostic runner error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
