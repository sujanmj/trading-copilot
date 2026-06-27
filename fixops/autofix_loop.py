"""FixOps automation loop: diagnostics -> AI analysis -> Codex -> validation."""

from __future__ import annotations

import argparse
import json
import os
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
ANALYSIS_JSON_PATH = INCIDENTS_DIR / "latest_gpt_analysis.json"
CODEX_RUN_JSON_PATH = INCIDENTS_DIR / "latest_codex_run.json"
LOOP_JSON_PATH = INCIDENTS_DIR / "latest_autofix_loop.json"
LOOP_TXT_PATH = INCIDENTS_DIR / "latest_autofix_loop.txt"

DEFAULT_MAX_LOOPS = 3
GENERATED_ANALYTICS_TRENDS = "data/provider_analytics/trends.json"
GENERATED_ANALYTICS_DAILY_PREFIX = "data/provider_analytics/daily_"
GENERATED_ANALYTICS_DAILY_SUFFIX = ".json"

UNSAFE_EXACT = {
    ".env",
    "keys.env",
    "config/keys.env",
    "data/telegram_ai_usage_log.jsonl",
    "backend/trading/tradecard_journal.py",
}
UNSAFE_DIRS = {
    "data/cache",
    "data/debug_snapshots",
    "data/ai_cache",
}
UNSAFE_PREFIXES = {
    "scripts/test_tradecard_",
    "scripts/validate_tradecard_",
}

REFRESH_RECOVERY_PATTERNS = (
    "stale snapshot",
    "snapshot stale",
    "snapshot_export stalled",
    "pipeline stalled",
    "sla exceeded",
    "alerts blocked",
    "alerts: blocked",
    "blocked alerts",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _max_loops_from_env() -> int:
    raw = os.environ.get("FIXOPS_MAX_LOOPS", "").strip()
    if not raw:
        return DEFAULT_MAX_LOOPS
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MAX_LOOPS


def _command_text(args: list[str]) -> str:
    return subprocess.list2cmdline(args) if os.name == "nt" else " ".join(args)


def _run_command(args: list[str], *, timeout_seconds: int | None = None) -> dict[str, Any]:
    started = time.monotonic()
    result: dict[str, Any] = {
        "command": _command_text(args),
        "exit_code": None,
        "duration_seconds": 0,
        "stdout": "",
        "stderr": "",
        "ok": False,
    }
    try:
        completed = subprocess.run(
            args,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        result.update(
            {
                "exit_code": completed.returncode,
                "stdout": completed.stdout or "",
                "stderr": completed.stderr or "",
                "ok": completed.returncode == 0,
            }
        )
    except subprocess.TimeoutExpired as exc:
        result.update(
            {
                "stdout": exc.stdout or "",
                "stderr": f"Command timed out after {timeout_seconds}s.\n{exc.stderr or ''}",
                "ok": False,
            }
        )
    except FileNotFoundError as exc:
        result["stderr"] = f"Command not found: {exc}"
    except Exception as exc:  # noqa: BLE001 - loop should record local failures.
        result["stderr"] = f"Command failed before completion: {type(exc).__name__}: {exc}"
    finally:
        result["duration_seconds"] = round(time.monotonic() - started, 3)
    return result


def _run_python_script(script: str, *extra: str, timeout_seconds: int | None = None) -> dict[str, Any]:
    return _run_command([sys.executable, script, *extra], timeout_seconds=timeout_seconds)


def _git_status_short() -> dict[str, Any]:
    return _run_command(["git", "status", "--short"], timeout_seconds=60)


def _git_diff_safety_info() -> dict[str, Any]:
    return {
        "name_status": _run_command(["git", "diff", "--name-status"], timeout_seconds=60),
        "stat": _run_command(["git", "diff", "--stat"], timeout_seconds=60),
    }


def _read_analysis() -> dict[str, Any]:
    if not ANALYSIS_JSON_PATH.exists():
        return {
            "status": "UNCERTAIN",
            "confidence": 0.0,
            "failed_sections": ["missing latest_gpt_analysis.json"],
            "suspected_root_cause": "FixOps analyzer did not produce an analysis file",
            "should_run_codex": False,
            "codex_prompt": "",
        }
    try:
        data = json.loads(ANALYSIS_JSON_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001 - report malformed analysis.
        return {
            "status": "UNCERTAIN",
            "confidence": 0.0,
            "failed_sections": ["invalid latest_gpt_analysis.json"],
            "suspected_root_cause": f"Could not parse analysis JSON: {type(exc).__name__}: {exc}",
            "should_run_codex": False,
            "codex_prompt": "",
        }


def _normalize_path(path: str) -> str:
    path = path.strip().strip('"').replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def _parse_status_paths(stdout: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        status = line[:2]
        raw = line[3:].strip() if len(line) > 3 else line.strip()
        paths = raw.split(" -> ") if " -> " in raw else [raw]
        for raw_path in paths:
            path = _normalize_path(raw_path)
            if path:
                entries.append({"status": status, "path": path, "line": line})
    return entries


def _unsafe_reason(path: str) -> str | None:
    path = _normalize_path(path)
    lower = path.lower()
    if path in UNSAFE_EXACT:
        return "unsafe_exact"
    if any(path == d or path.startswith(f"{d}/") for d in UNSAFE_DIRS):
        return "unsafe_directory"
    if any(path.startswith(prefix) for prefix in UNSAFE_PREFIXES):
        return "unsafe_tradecard_test_prefix"
    if lower.endswith(".env") or lower.endswith(".env.local") or lower.endswith("keys.env"):
        return "unsafe_env_or_key_file"
    return None


def _unsafe_changes_from_status(status_result: dict[str, Any]) -> list[dict[str, str]]:
    unsafe: list[dict[str, str]] = []
    for entry in _parse_status_paths(str(status_result.get("stdout") or "")):
        reason = _unsafe_reason(entry["path"])
        if reason:
            unsafe.append({**entry, "reason": reason})
    return unsafe


def cleanup_generated_noise() -> dict[str, Any]:
    """Remove generated analyzer artifacts before unsafe-change checks."""
    cleanup: dict[str, Any] = {
        "trends_status": {},
        "trends_restore": {},
        "daily_status": {},
        "deleted_daily_files": [],
        "errors": [],
    }

    trends_status = _run_command(["git", "status", "--short", "--", GENERATED_ANALYTICS_TRENDS], timeout_seconds=60)
    cleanup["trends_status"] = trends_status
    if trends_status.get("ok"):
        for entry in _parse_status_paths(str(trends_status.get("stdout") or "")):
            if entry["path"] == GENERATED_ANALYTICS_TRENDS and entry.get("status") != "??":
                cleanup["trends_restore"] = _run_command(
                    ["git", "restore", "--", GENERATED_ANALYTICS_TRENDS],
                    timeout_seconds=60,
                )
                break
    else:
        cleanup["errors"].append(
            {
                "path": GENERATED_ANALYTICS_TRENDS,
                "action": "git_status",
                "error": str(trends_status.get("stderr") or "git status failed"),
            }
        )

    daily_status = _run_command(["git", "status", "--short", "--", "data/provider_analytics"], timeout_seconds=60)
    cleanup["daily_status"] = daily_status
    if not daily_status.get("ok"):
        cleanup["errors"].append(
            {
                "path": "data/provider_analytics",
                "action": "git_status",
                "error": str(daily_status.get("stderr") or "git status failed"),
            }
        )
        return cleanup

    for entry in _parse_status_paths(str(daily_status.get("stdout") or "")):
        path = entry["path"]
        if (
            entry.get("status") == "??"
            and path.startswith(GENERATED_ANALYTICS_DAILY_PREFIX)
            and path.endswith(GENERATED_ANALYTICS_DAILY_SUFFIX)
        ):
            try:
                target = _safe_repo_path(path)
                if target.is_file():
                    target.unlink()
                    action = "deleted_untracked_file"
                elif target.exists():
                    action = "skipped_not_file"
                else:
                    action = "untracked_missing"
                cleanup["deleted_daily_files"].append({"path": path, "action": action, "ok": True})
            except Exception as exc:  # noqa: BLE001 - report cleanup failures without hiding guard results.
                cleanup["deleted_daily_files"].append(
                    {
                        "path": path,
                        "action": "delete_failed",
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    return cleanup

def _safe_repo_path(path: str) -> Path:
    candidate = (PROJECT_ROOT / _normalize_path(path)).resolve()
    root = PROJECT_ROOT.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"Refusing unsafe path outside repo: {path}") from exc
    return candidate


def _auto_revert_unsafe(unsafe: list[dict[str, str]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for item in unsafe:
        path = item["path"]
        status = item.get("status", "")
        try:
            if status == "??":
                target = _safe_repo_path(path)
                if not _unsafe_reason(path):
                    raise RuntimeError("path no longer matches unsafe guard")
                if target.is_dir():
                    shutil.rmtree(target)
                    action = "removed_untracked_directory"
                elif target.exists():
                    target.unlink()
                    action = "removed_untracked_file"
                else:
                    action = "untracked_missing"
                actions.append({"path": path, "action": action, "ok": True})
            else:
                result = _run_command(["git", "restore", "--staged", "--worktree", "--", path], timeout_seconds=60)
                actions.append({"path": path, "action": "git_restore", "ok": bool(result.get("ok")), "result": result})
        except Exception as exc:  # noqa: BLE001 - keep reporting all attempted reverts.
            actions.append({"path": path, "action": "revert_failed", "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return actions


def _print_loop_header(loop_number: int, max_loops: int) -> None:
    print(f"FixOps loop {loop_number}/{max_loops}")


def _print_analysis(prefix: str, analysis: dict[str, Any]) -> None:
    print(f"{prefix} status: {analysis.get('status')}")
    print(f"{prefix} failed sections: {analysis.get('failed_sections') or []}")
    print(f"{prefix} should_run_codex: {analysis.get('should_run_codex')}")
    if analysis.get("fixops_override"):
        print(f"{prefix} fixops_override: {analysis.get('fixops_override')}")


def _run_pre_analysis() -> dict[str, Any]:
    return {
        "runtime_state_probe": _run_python_script("fixops/runtime_state_probe.py", timeout_seconds=300),
        "internal_diagnostic_runner": _run_python_script("fixops/internal_diagnostic_runner.py", timeout_seconds=300),
        "gpt_report_analyzer": _run_python_script("fixops/gpt_report_analyzer.py", timeout_seconds=300),
    }


def _run_validation() -> dict[str, Any]:
    compile_result = _run_command(
        [sys.executable, "-m", "compileall", "backend", "fixops"],
        timeout_seconds=300,
    )
    return {
        "compileall": compile_result,
        "runtime_state_probe": _run_python_script("fixops/runtime_state_probe.py", timeout_seconds=300),
        "internal_diagnostic_runner": _run_python_script("fixops/internal_diagnostic_runner.py", timeout_seconds=300),
        "gpt_report_analyzer": _run_python_script("fixops/gpt_report_analyzer.py", timeout_seconds=300),
    }


def _run_refresh_recovery() -> dict[str, Any]:
    result = {
        "attempted": True,
        "internal_refresh_runner": _run_python_script("fixops/internal_refresh_runner.py", timeout_seconds=1200),
        "internal_diagnostic_runner": {},
        "gpt_report_analyzer": {},
        "post_analysis": {},
    }
    result["internal_diagnostic_runner"] = _run_python_script(
        "fixops/internal_diagnostic_runner.py",
        timeout_seconds=300,
    )
    result["gpt_report_analyzer"] = _run_python_script(
        "fixops/gpt_report_analyzer.py",
        timeout_seconds=300,
    )
    result["post_analysis"] = _read_analysis()
    return result


def _codex_timeout_for_wrapper() -> int:
    try:
        return max(1, int(os.environ.get("FIXOPS_CODEX_TIMEOUT_SECONDS", "900"))) + 120
    except ValueError:
        return 1020


def _run_codex_runner() -> dict[str, Any]:
    """Invoke codex_runner normal execution only; never forward autofix CLI flags."""
    return _run_command([sys.executable, "fixops/codex_runner.py"], timeout_seconds=_codex_timeout_for_wrapper())


def _read_codex_run_report() -> dict[str, Any]:
    if not CODEX_RUN_JSON_PATH.exists():
        return {
            "ok": False,
            "failure_reason": "missing_codex_run_report",
            "fatal_patterns_detected": [],
        }
    try:
        data = json.loads(CODEX_RUN_JSON_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {
            "ok": False,
            "failure_reason": "invalid_codex_run_report_shape",
            "fatal_patterns_detected": [],
        }
    except Exception as exc:  # noqa: BLE001 - loop should stop cleanly.
        return {
            "ok": False,
            "failure_reason": f"invalid_codex_run_report:{type(exc).__name__}",
            "fatal_patterns_detected": [],
        }


def _codex_runtime_failed(wrapper_result: dict[str, Any], codex_report: dict[str, Any]) -> bool:
    if not wrapper_result.get("ok"):
        return True
    if codex_report.get("failure_reason"):
        return True
    return codex_report.get("ok") is False


def _is_count_mismatch_observation_only(analysis: dict[str, Any]) -> bool:
    return analysis.get("fixops_override") == "count_mismatch_observation_only"


def _analysis_mentions_refresh_recoverable_issue(analysis: dict[str, Any]) -> bool:
    failed_sections = analysis.get("failed_sections") or []
    if not isinstance(failed_sections, list):
        return False
    combined = "\n".join(str(section or "") for section in failed_sections).lower()
    return any(pattern in combined for pattern in REFRESH_RECOVERY_PATTERNS)


def _analysis_allows_no_codex_after_refresh(analysis: dict[str, Any]) -> bool:
    status = str(analysis.get("status") or "").upper()
    should_run_codex = bool(analysis.get("should_run_codex"))
    return (
        status == "FIXED"
        or (status == "UNCERTAIN" and not should_run_codex)
        or _is_count_mismatch_observation_only(analysis)
    )


def _analysis_requires_codex_after_refresh(analysis: dict[str, Any]) -> bool:
    return str(analysis.get("status") or "").upper() == "BROKEN" and bool(analysis.get("should_run_codex"))


def run_autofix_loop(max_loops: int) -> dict[str, Any]:
    report: dict[str, Any] = {
        "started_at": _utc_now(),
        "finished_at": "",
        "max_loops": max_loops,
        "final_status": "running",
        "generated_noise_cleanup_before_loop": cleanup_generated_noise(),
        "loops": [],
    }

    for loop_number in range(1, max_loops + 1):
        _print_loop_header(loop_number, max_loops)
        loop: dict[str, Any] = {
            "loop_number": loop_number,
            "started_at": _utc_now(),
            "git_status_before": _git_status_short(),
            "pre_commands": {},
            "pre_analysis": {},
            "generated_noise_cleanup_after_pre_analysis": {},
            "refresh_recovery": {},
            "codex_ran": False,
            "codex_run": {},
            "codex_run_report": {},
            "validation": {},
            "post_analysis": {},
            "generated_noise_cleanup_after_post_analysis": {},
            "generated_noise_cleanup_before_unsafe_guard": {},
            "git_status_after": {},
            "git_diff_after": {},
            "unsafe_changes": [],
            "reverted_unsafe": [],
            "finished_at": "",
        }

        loop["pre_commands"] = _run_pre_analysis()
        loop["pre_analysis"] = _read_analysis()
        _print_analysis("Pre-analysis", loop["pre_analysis"])
        loop["generated_noise_cleanup_after_pre_analysis"] = cleanup_generated_noise()

        if _is_count_mismatch_observation_only(loop["pre_analysis"]):
            report["final_status"] = "observation_only_no_action"
            loop["finished_at"] = _utc_now()
            report["loops"].append(loop)
            break

        status = str(loop["pre_analysis"].get("status") or "UNCERTAIN")
        should_run_codex = bool(loop["pre_analysis"].get("should_run_codex"))
        if status == "FIXED" or not should_run_codex:
            report["final_status"] = "success_or_no_action"
            loop["finished_at"] = _utc_now()
            report["loops"].append(loop)
            break

        active_analysis = loop["pre_analysis"]
        if _analysis_mentions_refresh_recoverable_issue(loop["pre_analysis"]):
            print("Pre-Codex recovery: stale/stalled/blocked condition detected; running internal refresh once.")
            loop["refresh_recovery"] = _run_refresh_recovery()
            active_analysis = loop["refresh_recovery"].get("post_analysis") or {}
            _print_analysis("Post-refresh analysis", active_analysis)
            if _analysis_allows_no_codex_after_refresh(active_analysis):
                report["final_status"] = "refresh_recovered_no_codex"
                loop["post_analysis"] = active_analysis
                loop["finished_at"] = _utc_now()
                report["loops"].append(loop)
                break
            if not _analysis_requires_codex_after_refresh(active_analysis):
                report["final_status"] = "refresh_recovered_no_codex"
                loop["post_analysis"] = active_analysis
                loop["finished_at"] = _utc_now()
                report["loops"].append(loop)
                break

        loop["codex_ran"] = True
        loop["codex_run"] = _run_codex_runner()
        loop["codex_run_report"] = _read_codex_run_report()
        print(f"Codex ran: true")
        print(f"Codex exit code: {loop['codex_run'].get('exit_code')}")
        if loop["codex_run_report"].get("failure_reason"):
            print(f"Codex failure reason: {loop['codex_run_report'].get('failure_reason')}")
        if loop["codex_run_report"].get("fatal_patterns_detected"):
            print(f"Codex fatal patterns: {loop['codex_run_report'].get('fatal_patterns_detected')}")

        if _codex_runtime_failed(loop["codex_run"], loop["codex_run_report"]):
            failure_reason = str(loop["codex_run_report"].get("failure_reason") or "")
            if failure_reason == "codex_usage_limit":
                print("Codex usage limit reached; retry after reset or add credits.")
                report["final_status"] = "codex_usage_limit"
            else:
                report["final_status"] = "codex_runtime_error"
            loop["git_status_after"] = _git_status_short()
            loop["git_diff_after"] = _git_diff_safety_info()
            loop["unsafe_changes"] = _unsafe_changes_from_status(loop["git_status_after"])
            loop["finished_at"] = _utc_now()
            report["loops"].append(loop)
            break

        loop["validation"] = _run_validation()
        compile_result = loop["validation"].get("compileall", {})
        print(f"Compile result: {compile_result.get('exit_code')}")

        loop["post_analysis"] = _read_analysis()
        _print_analysis("Post-analysis", loop["post_analysis"])
        loop["generated_noise_cleanup_after_post_analysis"] = cleanup_generated_noise()
        loop["generated_noise_cleanup_before_unsafe_guard"] = cleanup_generated_noise()

        loop["git_status_after"] = _git_status_short()
        loop["git_diff_after"] = _git_diff_safety_info()
        loop["unsafe_changes"] = _unsafe_changes_from_status(loop["git_status_after"])
        if loop["unsafe_changes"]:
            print(f"Unsafe changes detected: {[item['path'] for item in loop['unsafe_changes']]}")
            report["final_status"] = "unsafe_changes_detected"
            if os.environ.get("FIXOPS_AUTO_REVERT_UNSAFE", "").strip() == "1":
                loop["reverted_unsafe"] = _auto_revert_unsafe(loop["unsafe_changes"])
            loop["finished_at"] = _utc_now()
            report["loops"].append(loop)
            break

        if str(loop["post_analysis"].get("status") or "") == "FIXED":
            report["final_status"] = "fixed"
            loop["finished_at"] = _utc_now()
            report["loops"].append(loop)
            break

        loop["finished_at"] = _utc_now()
        report["loops"].append(loop)
    else:
        report["final_status"] = "max_loops_reached"

    report["finished_at"] = _utc_now()
    return report


def _build_txt_report(report: dict[str, Any]) -> str:
    lines = [
        f"started_at: {report.get('started_at', '')}",
        f"finished_at: {report.get('finished_at', '')}",
        f"max_loops: {report.get('max_loops')}",
        f"final_status: {report.get('final_status')}",
        "",
    ]
    for loop in report.get("loops", []):
        pre = loop.get("pre_analysis") or {}
        post = loop.get("post_analysis") or {}
        codex = loop.get("codex_run") or {}
        codex_report = loop.get("codex_run_report") or {}
        recovery = loop.get("refresh_recovery") or {}
        recovery_post = recovery.get("post_analysis") or {}
        compile_result = (loop.get("validation") or {}).get("compileall") or {}
        diff_info = loop.get("git_diff_after") or {}
        diff_name_status = (diff_info.get("name_status") or {}).get("stdout", "")
        lines.extend(
            [
                f"loop: {loop.get('loop_number')}",
                f"pre_status: {pre.get('status')}",
                f"pre_failed_sections: {pre.get('failed_sections') or []}",
                f"pre_fixops_override: {pre.get('fixops_override', '')}",
                f"refresh_recovery_attempted: {recovery.get('attempted', False)}",
                f"refresh_exit_code: {(recovery.get('internal_refresh_runner') or {}).get('exit_code')}",
                f"refresh_post_status: {recovery_post.get('status')}",
                f"refresh_post_should_run_codex: {recovery_post.get('should_run_codex')}",
                f"refresh_post_failed_sections: {recovery_post.get('failed_sections') or []}",
                f"codex_ran: {loop.get('codex_ran')}",
                f"codex_exit_code: {codex.get('exit_code')}",
                f"codex_ok: {codex_report.get('ok')}",
                f"codex_failure_reason: {codex_report.get('failure_reason', '')}",
                f"codex_fatal_patterns: {codex_report.get('fatal_patterns_detected', [])}",
                f"compile_exit_code: {compile_result.get('exit_code')}",
                f"post_status: {post.get('status')}",
                f"post_fixops_override: {post.get('fixops_override', '')}",
                f"post_failed_sections: {post.get('failed_sections') or []}",
                f"unsafe_changes: {[item.get('path') for item in loop.get('unsafe_changes', [])]}",
                f"git_diff_name_status: {diff_name_status.strip()}",
                "",
            ]
        )
    return "\n".join(lines)


def _save_report(report: dict[str, Any]) -> tuple[Path, Path]:
    INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)
    LOOP_JSON_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    LOOP_TXT_PATH.write_text(_build_txt_report(report), encoding="utf-8")
    return LOOP_TXT_PATH, LOOP_JSON_PATH


def _print_final(report: dict[str, Any], txt_path: Path, json_path: Path) -> None:
    print(f"Final status: {report.get('final_status')}")
    print(f"Saved txt path: {txt_path}")
    print(f"Saved json path: {json_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the FixOps autofix loop.")
    parser.add_argument("--max-loops", type=int, default=None, help="Maximum repair loops to run.")
    args = parser.parse_args(argv)

    max_loops = max(1, args.max_loops if args.max_loops is not None else _max_loops_from_env())
    report = run_autofix_loop(max_loops)
    txt_path, json_path = _save_report(report)
    _print_final(report, txt_path, json_path)
    return 0 if report.get("final_status") in {
        "fixed",
        "success_or_no_action",
        "observation_only_no_action",
        "refresh_recovered_no_codex",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
