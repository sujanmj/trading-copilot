"""Run Codex non-interactively from the latest FixOps repair prompt."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FIXOPS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = FIXOPS_DIR.parent
INCIDENTS_DIR = FIXOPS_DIR / "incidents"
CODEX_PROMPT_PATH = INCIDENTS_DIR / "latest_codex_prompt.txt"
CURRENT_PROMPT_PATH = INCIDENTS_DIR / "codex_prompt_current.txt"
RUN_TXT_PATH = INCIDENTS_DIR / "latest_codex_run.txt"
RUN_JSON_PATH = INCIDENTS_DIR / "latest_codex_run.json"

DEFAULT_CODEX_COMMAND = "codex exec"
DEFAULT_TIMEOUT_SECONDS = 900
FATAL_PATTERNS = [
    "orchestrator_helper_launch_failed",
    "codex-windows-sandbox-setup.exe",
    "execution error",
    "Exit code: -1073741819",
    "program not found",
    "windows sandbox:",
]
USAGE_LIMIT_PATTERNS = [
    "You've hit your usage limit",
    "usage limit",
    "try again at",
    "purchase more credits",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timeout_seconds() -> int:
    raw = os.environ.get("FIXOPS_CODEX_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _resolve_prompt_path(value: str | None) -> Path:
    if not value:
        return CODEX_PROMPT_PATH
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _split_command(command: str) -> list[str]:
    command = command.strip() or DEFAULT_CODEX_COMMAND
    return shlex.split(command, posix=(os.name != "nt"))


def _prompt_mode(prompt: str) -> str:
    mode = os.environ.get("FIXOPS_CODEX_PROMPT_MODE", "auto").strip().lower()
    if mode in {"arg", "argument", "args"}:
        return "arg"
    if mode in {"stdin", "pipe"}:
        return "stdin"
    # Windows command-line length is finite; stdin is safer for long prompts.
    return "arg" if len(prompt) < 12000 else "stdin"


def _build_txt_report(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"started_at: {result.get('started_at', '')}",
            f"finished_at: {result.get('finished_at', '')}",
            f"ok: {result.get('ok')}",
            f"exit_code: {result.get('exit_code')}",
            f"duration_seconds: {result.get('duration_seconds')}",
            f"command: {result.get('command')}",
            f"prompt_path: {result.get('prompt_path')}",
            f"failure_reason: {result.get('failure_reason', '')}",
            f"fatal_patterns_detected: {result.get('fatal_patterns_detected', [])}",
            "",
            "--- stdout ---",
            str(result.get("stdout") or ""),
            "",
            "--- stderr ---",
            str(result.get("stderr") or ""),
            "",
        ]
    )


def _save_run(result: dict[str, Any]) -> tuple[Path, Path]:
    INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)
    RUN_TXT_PATH.write_text(_build_txt_report(result), encoding="utf-8")
    RUN_JSON_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return RUN_TXT_PATH, RUN_JSON_PATH


def _detect_patterns(stdout: Any, stderr: Any, patterns: list[str]) -> list[str]:
    combined = f"{stdout or ''}\n{stderr or ''}".lower()
    found: list[str] = []
    for pattern in patterns:
        if pattern.lower() in combined:
            found.append(pattern)
    return found


def _detect_fatal_patterns(stdout: Any, stderr: Any) -> list[str]:
    return _detect_patterns(stdout, stderr, FATAL_PATTERNS)


def _detect_usage_limit_patterns(stdout: Any, stderr: Any) -> list[str]:
    return _detect_patterns(stdout, stderr, USAGE_LIMIT_PATTERNS)


def _apply_fatal_pattern_result(result: dict[str, Any]) -> dict[str, Any]:
    usage_limit = _detect_usage_limit_patterns(result.get("stdout"), result.get("stderr"))
    if usage_limit:
        result["ok"] = False
        result["fatal_patterns_detected"] = usage_limit
        result["failure_reason"] = "codex_usage_limit"
        return result

    found = _detect_fatal_patterns(result.get("stdout"), result.get("stderr"))
    if found:
        result["ok"] = False
        result["fatal_patterns_detected"] = found
        result["failure_reason"] = "codex_internal_tool_failure"
    return result


def _read_prompt(prompt_path: Path) -> str:
    if not prompt_path.exists():
        raise FileNotFoundError(f"Missing Codex prompt file: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8").strip()


def _codex_executable(command: str) -> str:
    args = _split_command(command)
    return args[0] if args else ""


def _run_args_for_display(command: str, prompt: str) -> list[str]:
    args = _split_command(command)
    if not args:
        return []
    return args + ["<prompt>"] if _prompt_mode(prompt) == "arg" else args


def check_command(command: str) -> bool:
    executable = _codex_executable(command)
    found = bool(executable and shutil.which(executable))
    print(f"Codex command: {command}")
    print(f"Executable: {executable or '(none)'}")
    print(f"Found: {found}")
    if found:
        print(f"Path: {shutil.which(executable)}")
    return found


def dry_run(*, command: str, prompt_path: Path, timeout_seconds: int) -> int:
    try:
        prompt = _read_prompt(prompt_path)
    except Exception as exc:  # noqa: BLE001 - CLI should show a clear local error.
        print(f"Dry run failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print("Dry run: Codex will not be executed.")
    print(f"Command: {command}")
    print(f"Run args: {_command_text(_run_args_for_display(command, prompt))}")
    print(f"Prompt path: {prompt_path}")
    print(f"Current prompt path: {CURRENT_PROMPT_PATH}")
    print(f"Timeout seconds: {timeout_seconds}")
    print(f"Prompt chars: {len(prompt)}")
    return 0


def _command_text(args: list[str]) -> str:
    return subprocess.list2cmdline(args) if os.name == "nt" else " ".join(shlex.quote(arg) for arg in args)


def run_codex(*, prompt_path: Path = CODEX_PROMPT_PATH, timeout_seconds: int | None = None) -> dict[str, Any]:
    INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)
    command = os.environ.get("FIXOPS_CODEX_COMMAND", DEFAULT_CODEX_COMMAND).strip() or DEFAULT_CODEX_COMMAND
    timeout_seconds = timeout_seconds if timeout_seconds is not None else _timeout_seconds()
    started_at = _utc_now()
    started = time.monotonic()

    base_result: dict[str, Any] = {
        "ok": False,
        "exit_code": None,
        "duration_seconds": 0,
        "command": command,
        "stdout": "",
        "stderr": "",
        "prompt_path": str(CURRENT_PROMPT_PATH),
        "started_at": started_at,
        "finished_at": "",
    }

    if not prompt_path.exists():
        base_result["stderr"] = f"Missing Codex prompt file: {prompt_path}"
        base_result["finished_at"] = _utc_now()
        return base_result

    prompt = prompt_path.read_text(encoding="utf-8").strip()
    CURRENT_PROMPT_PATH.write_text(prompt, encoding="utf-8")
    if not prompt:
        base_result["stderr"] = f"Codex prompt file is empty: {prompt_path}"
        base_result["finished_at"] = _utc_now()
        return base_result

    mode = _prompt_mode(prompt)
    try:
        args = _split_command(command)
        if not args:
            raise ValueError("FIXOPS_CODEX_COMMAND resolved to an empty command.")

        run_args = args + [prompt] if mode == "arg" else args
        completed = subprocess.run(
            run_args,
            cwd=str(PROJECT_ROOT),
            input=prompt if mode == "stdin" else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        base_result.update(
            {
                "ok": completed.returncode == 0,
                "exit_code": completed.returncode,
                "stdout": completed.stdout or "",
                "stderr": completed.stderr or "",
            }
        )
    except subprocess.TimeoutExpired as exc:
        base_result.update(
            {
                "ok": False,
                "exit_code": None,
                "stdout": exc.stdout or "",
                "stderr": f"Codex command timed out after {timeout_seconds}s.\n{exc.stderr or ''}",
            }
        )
    except FileNotFoundError as exc:
        base_result["stderr"] = f"Codex command not found: {exc}"
    except Exception as exc:  # noqa: BLE001 - runner should record local failures.
        base_result["stderr"] = f"Codex runner failed: {type(exc).__name__}: {exc}"
    finally:
        base_result["duration_seconds"] = round(time.monotonic() - started, 3)
        base_result["finished_at"] = _utc_now()

    return _apply_fatal_pattern_result(base_result)


def _print_summary(result: dict[str, Any], txt_path: Path, json_path: Path) -> None:
    print(f"Codex command: {result.get('command')}")
    print(f"Codex ok: {result.get('ok')}")
    print(f"Codex exit code: {result.get('exit_code')}")
    if result.get("failure_reason"):
        print(f"Failure reason: {result.get('failure_reason')}")
    if result.get("fatal_patterns_detected"):
        print(f"Fatal patterns detected: {result.get('fatal_patterns_detected')}")
    print(f"Duration seconds: {result.get('duration_seconds')}")
    print(f"Prompt path: {result.get('prompt_path')}")
    print(f"Saved txt path: {txt_path}")
    print(f"Saved json path: {json_path}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Codex non-interactively from a FixOps repair prompt.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read the prompt and print the command that would run without invoking Codex.",
    )
    parser.add_argument(
        "--check-command",
        action="store_true",
        help="Check whether the configured Codex executable exists without invoking Codex.",
    )
    parser.add_argument(
        "--prompt-file",
        default=str(CODEX_PROMPT_PATH),
        help="Prompt file to read. Defaults to fixops/incidents/latest_codex_prompt.txt.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Codex timeout in seconds. Defaults to FIXOPS_CODEX_TIMEOUT_SECONDS or 900.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    command = os.environ.get("FIXOPS_CODEX_COMMAND", DEFAULT_CODEX_COMMAND).strip() or DEFAULT_CODEX_COMMAND
    timeout_seconds = max(1, args.timeout) if args.timeout is not None else _timeout_seconds()
    prompt_path = _resolve_prompt_path(args.prompt_file)

    if args.check_command:
        return 0 if check_command(command) else 1
    if args.dry_run:
        return dry_run(command=command, prompt_path=prompt_path, timeout_seconds=timeout_seconds)

    result = run_codex(prompt_path=prompt_path, timeout_seconds=timeout_seconds)
    txt_path, json_path = _save_run(result)
    _print_summary(result, txt_path, json_path)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
