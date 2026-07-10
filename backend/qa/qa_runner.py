"""Safe allowlisted Python test runner for Telegram /qa (Phase 4B.16)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config.build_info import TELEGRAM_BUILD
from backend.qa.smoke_mode import QA_SMOKE_ENV
from backend.utils.config import DATA_DIR, PROJECT_ROOT

QA_LAST_RESULT_PATH = DATA_DIR / 'qa_last_result.json'

SMOKE_SCRIPT_ALLOWLIST: tuple[tuple[str, str], ...] = (
    ('telegram routing', 'scripts/test_telegram_stage_51a_canonical_routing.py'),
    ('chart patterns help', 'scripts/test_help_chart_patterns_4b15b.py'),
    ('intraday candle memory', 'scripts/test_intraday_candle_memory_4b15a.py'),
)

FULL_SCRIPT_ALLOWLIST: tuple[tuple[str, str], ...] = (
    ('chart patterns help', 'scripts/test_help_chart_patterns_4b15b.py'),
    ('intraday candle memory', 'scripts/test_intraday_candle_memory_4b15a.py'),
    ('chart patterns', 'scripts/test_chart_patterns_4b15.py'),
    ('screener longterm polish', 'scripts/test_screener_longterm_polish_4b14b.py'),
    ('screener import attachment', 'scripts/test_screener_import_attachment_4b14a.py'),
    ('tradecard memory', 'scripts/test_tradecard_memory_4b13.py'),
    ('cap bucket visibility', 'scripts/test_cap_bucket_visibility_4b12.py'),
    ('tradecard closed market', 'scripts/test_tradecard_closed_market_no_legacy_4b12.py'),
    ('pattern board consistency', 'scripts/test_pattern_board_consistency_4b17b.py'),
    ('qa smoke isolation', 'scripts/test_qa_smoke_isolation_4b18a.py'),
    ('telegram routing', 'scripts/test_telegram_stage_51a_canonical_routing.py'),
)

ALL_SCRIPT_ALLOWLIST: frozenset[str] = frozenset(
    script_rel for _, script_rel in SMOKE_SCRIPT_ALLOWLIST + FULL_SCRIPT_ALLOWLIST
)

SMOKE_SCRIPT_TIMEOUT_SECONDS = 45
FULL_SCRIPT_TIMEOUT_SECONDS = 90
ERROR_TAIL_MAX_LINES = 8


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _fail_token_from_script(script_rel: str) -> str:
    stem = Path(script_rel).stem
    if stem.startswith('test_'):
        stem = stem[5:]
    return stem.upper().replace('-', '_') + '_FAIL'


def _parse_script_failure(script_rel: str, stdout: str, stderr: str) -> dict[str, str]:
    """Extract direct failure for the running script (not nested cascade noise)."""
    token = _fail_token_from_script(script_rel)
    own_fail = ''
    nested_hints: list[str] = []
    failed_test = ''

    for line in (stdout + '\n' + stderr).splitlines():
        stripped = line.strip()
        if '_FAIL:' not in stripped:
            continue
        if f'{token}:' in stripped:
            own_fail = stripped
        else:
            nested_hints.append(stripped)

    if own_fail:
        message = own_fail.split(':', 1)[-1].strip()
        summary = message[:160]
        if ' failed with code ' in message:
            failed_test = message.split(' failed with code ')[0].strip()
        elif message.endswith(' failed'):
            failed_test = message[:-len(' failed')].strip()
        else:
            failed_test = message.split(':', 1)[0].strip()[:80]
    else:
        summary = _summary_from_output(stderr or stdout, fallback='failed')

    tail_lines: list[str] = []
    if own_fail:
        tail_lines.append(own_fail)
    elif nested_hints:
        tail_lines.append(nested_hints[-1])
    combined = '\n'.join(part for part in (stdout, stderr) if part).strip()
    if combined:
        for line in combined.splitlines()[-ERROR_TAIL_MAX_LINES:]:
            if line.strip() and line.strip() not in tail_lines:
                tail_lines.append(line.strip())
    error_tail = '\n'.join(tail_lines[-ERROR_TAIL_MAX_LINES:])[:1200]

    detail: dict[str, str] = {
        'summary': summary,
        'error_tail': error_tail or 'no output captured',
    }
    if failed_test:
        detail['failed_test'] = failed_test
    if nested_hints and own_fail:
        detail['nested_hint'] = nested_hints[-1][:240]
    return detail


def _error_tail(stdout: str, stderr: str) -> str:
    combined = '\n'.join(part for part in (stdout, stderr) if part).strip()
    if not combined:
        return 'no output captured'
    lines = combined.splitlines()
    tail = '\n'.join(lines[-ERROR_TAIL_MAX_LINES:])
    return tail[:1200]


def _summary_from_output(stdout: str, *, fallback: str) -> str:
    for line in reversed((stdout or '').splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped[:160]
    return fallback


def _save_last_result(result: dict[str, Any]) -> None:
    QA_LAST_RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    QA_LAST_RESULT_PATH.write_text(json.dumps(result, indent=2), encoding='utf-8')


def load_last_qa_result() -> dict[str, Any] | None:
    if not QA_LAST_RESULT_PATH.is_file():
        return None
    try:
        data = json.loads(QA_LAST_RESULT_PATH.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _execute_script(name: str, script_rel: str, *, timeout: int, smoke_mode: bool = False) -> dict[str, Any]:
    if script_rel not in ALL_SCRIPT_ALLOWLIST:
        return {
            'name': name,
            'status': 'FAIL',
            'duration_seconds': 0.0,
            'summary': 'script not allowlisted',
            'error_tail': f'blocked non-allowlisted script: {script_rel}',
        }

    script_path = (PROJECT_ROOT / script_rel).resolve()
    expected_root = PROJECT_ROOT.resolve()
    if expected_root not in script_path.parents and script_path != expected_root:
        return {
            'name': name,
            'status': 'FAIL',
            'duration_seconds': 0.0,
            'summary': 'script path escape blocked',
            'error_tail': f'blocked script path: {script_rel}',
        }

    if not script_path.is_file():
        return {
            'name': name,
            'status': 'FAIL',
            'duration_seconds': 0.0,
            'summary': f'missing script: {script_rel}',
            'error_tail': f'missing script: {script_rel}',
        }

    env = os.environ.copy()
    env.setdefault('DISABLE_TELEGRAM', '1')
    env.setdefault('DISABLE_TELEGRAM_SENDS', '1')
    env.setdefault('PYTHONHASHSEED', '0')
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    env['PYTHONPATH'] = str(PROJECT_ROOT)
    if smoke_mode:
        env[QA_SMOKE_ENV] = '1'
    else:
        env.pop(QA_SMOKE_ENV, None)

    started = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        duration = round(time.monotonic() - started, 1)
        return {
            'name': name,
            'status': 'FAIL',
            'duration_seconds': duration,
            'summary': f'timeout after {timeout}s',
            'error_tail': f'timeout after {timeout}s',
        }
    except OSError as exc:
        duration = round(time.monotonic() - started, 1)
        msg = str(exc)[:160]
        return {
            'name': name,
            'status': 'FAIL',
            'duration_seconds': duration,
            'summary': msg,
            'error_tail': msg,
        }

    duration = round(time.monotonic() - started, 1)
    stdout = proc.stdout or ''
    stderr = proc.stderr or ''
    if proc.returncode == 0:
        return {
            'name': name,
            'status': 'PASS',
            'duration_seconds': duration,
            'summary': _summary_from_output(stdout, fallback='passed'),
        }

    parsed = _parse_script_failure(script_rel, stdout, stderr)
    row: dict[str, Any] = {
        'name': name,
        'script': script_rel,
        'status': 'FAIL',
        'duration_seconds': duration,
        'summary': parsed.get('summary') or f'exit code {proc.returncode}',
        'error_tail': parsed.get('error_tail') or _error_tail(stdout, stderr),
    }
    if parsed.get('failed_test'):
        row['failed_test'] = parsed['failed_test']
    if parsed.get('nested_hint'):
        row['nested_hint'] = parsed['nested_hint']
    return row


def _run_script_suite(
    mode: str,
    scripts: tuple[tuple[str, str], ...],
    *,
    timeout: int,
    smoke_mode: bool = False,
) -> dict[str, Any]:
    started_at = _now_iso()
    wall_start = time.monotonic()
    tests: list[dict[str, Any]] = []
    passed_count = 0
    failed_count = 0
    skipped_count = 0

    for display_name, script_rel in scripts:
        row = _execute_script(display_name, script_rel, timeout=timeout, smoke_mode=smoke_mode)
        tests.append(row)
        status = row.get('status')
        if status == 'PASS':
            passed_count += 1
        elif status == 'SKIP':
            skipped_count += 1
        else:
            failed_count += 1

    result: dict[str, Any] = {
        'started_at': started_at,
        'finished_at': _now_iso(),
        'duration_seconds': round(time.monotonic() - wall_start, 1),
        'mode': mode,
        'overall_status': 'PASS' if failed_count == 0 else 'FAIL',
        'passed_count': passed_count,
        'failed_count': failed_count,
        'tests': tests,
    }
    if skipped_count:
        result['skipped_count'] = skipped_count
    _save_last_result(result)
    return result


def run_qa_smoke() -> dict[str, Any]:
    return _run_script_suite(
        'smoke',
        SMOKE_SCRIPT_ALLOWLIST,
        timeout=SMOKE_SCRIPT_TIMEOUT_SECONDS,
        smoke_mode=True,
    )


def run_qa_full() -> dict[str, Any]:
    return _run_script_suite(
        'full',
        FULL_SCRIPT_ALLOWLIST,
        timeout=FULL_SCRIPT_TIMEOUT_SECONDS,
        smoke_mode=False,
    )


def get_qa_status() -> str:
    lines = [
        'QA — AstraEdge',
        f'Build: {TELEGRAM_BUILD}',
        'Commands:',
        '/qa smoke — fast safe checks',
        '/qa full — safe regression suite',
        '/qa last — last QA result',
        '/qa explain — what QA covers',
    ]
    last = load_last_qa_result()
    if last:
        lines.extend([
            '',
            f"Last run: {last.get('mode', '?')} — {last.get('overall_status', '?')} "
            f"({last.get('duration_seconds', '?')}s)",
        ])
    return '\n'.join(lines)


def explain_qa() -> str:
    return '\n'.join([
        'QA explain — AstraEdge',
        '',
        'QA checks command routing, help layout, chart patterns, candle memory,',
        'Screener import, long-term scoring, tradecard memory, cap bucket,',
        'closed-market safety.',
        'QA does not place trades.',
        'QA does not call AI.',
        'QA does not verify live market data availability.',
        'QA is paper/research system validation only.',
    ])


def format_qa_result(result: dict[str, Any], *, detail: str = 'summary') -> str:
    mode = str(result.get('mode') or 'qa').upper()
    overall = str(result.get('overall_status') or 'UNKNOWN').upper()
    duration = result.get('duration_seconds', 0)
    passed = result.get('passed_count', 0)
    failed = result.get('failed_count', 0)
    tests = result.get('tests') or []

    if detail == 'last':
        lines = [
            f"QA LAST — {mode} — {overall}",
            f'Duration: {duration}s',
            f'Passed: {passed}',
            f'Failed: {failed}',
        ]
        if result.get('started_at'):
            lines.append(f"Started: {result['started_at']}")
        failed_rows = [row for row in tests if row.get('status') != 'PASS']
        if failed_rows:
            lines.append('')
            lines.append('Failed:')
            for row in failed_rows:
                name = row.get('name') or 'unknown'
                failed_test = row.get('failed_test')
                summary = row.get('summary') or row.get('error_tail') or 'failed'
                if failed_test:
                    lines.append(f"- {name} — {failed_test}")
                else:
                    lines.append(f"- {name}: {summary}")
                if failed_test and summary and summary != failed_test:
                    lines.append(f"  {summary[:240]}")
                tail = row.get('error_tail')
                if tail and tail != summary:
                    for tail_line in tail.splitlines()[:3]:
                        lines.append(f"  {tail_line[:240]}")
                nested = row.get('nested_hint')
                if nested:
                    lines.append(f"  nested: {nested[:200]}")
        elif tests:
            lines.append('')
            lines.append('All checks passed.')
        return '\n'.join(lines)

    title = f'QA {mode} — {overall}'
    lines = [
        title,
        f'Duration: {duration}s',
        f'Passed: {passed}',
        f'Failed: {failed}',
    ]

    if detail == 'summary' and tests and overall == 'PASS':
        lines.append('')
        for idx, row in enumerate(tests, start=1):
            name = row.get('name') or 'unknown'
            status = row.get('status') or 'UNKNOWN'
            lines.append(f'{idx}. {name} — {status}')
        return '\n'.join(lines)

    if failed:
        lines.append('')
        lines.append('Failed:')
        for row in tests:
            if row.get('status') == 'PASS':
                continue
            name = row.get('name') or 'unknown'
            summary = row.get('summary') or row.get('error_tail') or 'failed'
            lines.append(f'- {name}: {summary}')
        lines.append('Use /qa last for details.')

    return '\n'.join(lines)
