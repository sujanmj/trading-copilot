"""Run the existing Telegram refresh pipeline internally and capture output.

This runner is intentionally operational: it may update normal Trading Copilot
runtime data through the existing refresh pipeline. It does not send Telegram
messages; outgoing Telegram-style messages are monkeypatched into local files.
"""

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
TXT_PATH = INCIDENTS_DIR / "latest_refresh_report.txt"
JSON_PATH = INCIDENTS_DIR / "latest_refresh_report.json"
COMMAND = "/refresh"
FROM_USER = "fixops"
DEFAULT_TIMEOUT_SECONDS = 900


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
    messages: list[dict[str, Any]] = field(default_factory=list)

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
                "command": f"/{str(command).lstrip('/')}" if command else self.command,
                "cycle_id": cycle_id or self.cycle_id,
                "message_kind": message_kind or "final",
                "text": _as_text(text),
            }
        )
        return True

    def capture_error(self, exc: Exception) -> None:
        self.messages.append(
            {
                "timestamp": _utc_now(),
                "command": self.command,
                "cycle_id": self.cycle_id,
                "message_kind": "error",
                "text": f"FixOps refresh failed: {type(exc).__name__}: {exc}",
            }
        )


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


def _patch_if_present(module: Any, attr_name: str, replacement: Any, originals: list[tuple[Any, str, Any]]) -> None:
    if module is not None and hasattr(module, attr_name):
        original = getattr(module, attr_name)
        originals.append((module, attr_name, original))
        setattr(module, attr_name, replacement)


def _patch_brain_push_bridge(
    listener: Any,
    brain_pusher: Any,
    capture: CaptureState,
    originals: list[tuple[Any, str, Any]],
) -> None:
    if brain_pusher is None or not hasattr(listener, "run_module_with_arg"):
        return

    original_run_module_with_arg = listener.run_module_with_arg
    originals.append((listener, "run_module_with_arg", original_run_module_with_arg))

    def _run_module_with_arg(module_name: str, arg: str, timeout: int = 120) -> bool:
        if module_name == "telegram_brain_pusher" and arg == "full" and hasattr(brain_pusher, "push_full_brain"):
            try:
                return bool(
                    brain_pusher.push_full_brain(
                        command="refresh",
                        cycle_id=capture.cycle_id,
                        sync=True,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - keep refresh report complete.
                capture.capture_error(exc)
                return False
        return original_run_module_with_arg(module_name, arg, timeout=timeout)

    listener.run_module_with_arg = _run_module_with_arg


def run_internal_refresh(*, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    import backend.orchestration.telegram_listener as listener

    brain_pusher = None
    try:
        import backend.orchestration.telegram_brain_pusher as brain_pusher
    except Exception:
        brain_pusher = None

    capture = CaptureState(
        command=COMMAND,
        cycle_id=f"fixops-refresh-{uuid.uuid4().hex[:12]}",
    )
    originals: list[tuple[Any, str, Any]] = []
    started_at = _utc_now()
    started_monotonic = time.monotonic()

    try:
        _patch_if_present(listener, "send_message", capture.send_message, originals)
        _patch_if_present(brain_pusher, "send_message", capture.send_message, originals)
        _patch_if_present(listener, "REFRESH_TIMEOUT_SEC", int(timeout_seconds), originals)
        _patch_brain_push_bridge(listener, brain_pusher, capture, originals)

        if hasattr(listener, "_do_refresh"):
            listener._do_refresh()
        else:
            # Fallback only for older listener builds. Keep daemon work in-process
            # so patched send functions cannot outlive the capture context.
            if hasattr(listener, "run_in_background"):
                original_background = listener.run_in_background
                originals.append((listener, "run_in_background", original_background))

                def _run_inline(target: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
                    target(*args, **kwargs)

                listener.run_in_background = _run_inline
            listener.handle_command(COMMAND, FROM_USER)
    except Exception as exc:  # noqa: BLE001 - save local report with failure details.
        capture.capture_error(exc)
    finally:
        for module, attr_name, original in reversed(originals):
            setattr(module, attr_name, original)

    duration_seconds = round(time.monotonic() - started_monotonic, 3)
    finished_at = _utc_now()
    return {
        "command": COMMAND,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration_seconds,
        "message_count": len(capture.messages),
        "messages": capture.messages,
    }


def _print_summary(payload: dict[str, Any], txt_path: Path, json_path: Path, report_text: str) -> None:
    print(f"Refresh started: {payload['started_at']}")
    print(f"Duration seconds: {payload['duration_seconds']}")
    print(f"Message count: {payload['message_count']}")
    print(f"Saved txt path: {txt_path}")
    print(f"Saved json path: {json_path}")
    print("First 500 chars:")
    print(report_text[:500])
    print("Last 500 chars:")
    print(report_text[-500:] if report_text else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run internal /refresh and capture Telegram-style output locally.")
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Maximum refresh timeout in seconds passed to the refresh pipeline (default: {DEFAULT_TIMEOUT_SECONDS}).",
    )
    args = parser.parse_args(argv)

    try:
        payload = run_internal_refresh(timeout_seconds=args.timeout)
        txt_path, json_path, report_text = _save_report(payload)
        _print_summary(payload, txt_path, json_path, report_text)
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI should show a clear local error.
        print(f"FixOps refresh runner error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
