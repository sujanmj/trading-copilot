#!/usr/bin/env python3
"""
Unit tests for Railway Telegram handler selection (Stage 46D).

Usage:
  python scripts/test_railway_telegram_handler_selection.py

Prints RAILWAY_TELEGRAM_HANDLER_SELECTION_TEST_OK on success.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

STAGE_MARKER = 'RAILWAY_STAGE_46D_TELEGRAM_HANDLER'
LEGACY_HELP_MARKERS = (
    'Trading Copilot Commands',
    '/review',
    '/elite',
    '/opps',
    '/brain',
    '/refresh',
)


def _fail(msg: str) -> int:
    print(f'RAILWAY_TELEGRAM_HANDLER_SELECTION_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _fresh_env(**overrides: str) -> dict[str, str]:
    env = dict(os.environ)
    for key in (
        'APP_MODE',
        'RAILWAY_ENVIRONMENT',
        'RAILWAY_PROJECT_ID',
        'RAILWAY_SERVICE_NAME',
        'DISABLE_LEGACY_TELEGRAM_LISTENER',
        'DISABLE_TELEGRAM_LISTENER',
        'DISABLE_TELEGRAM',
        'TELEGRAM_COMMANDS_ENABLED',
    ):
        env.pop(key, None)
    env.update({'PYTHONIOENCODING': 'utf-8'})
    env.update(overrides)
    return env


def test_railway_defaults_legacy_off() -> str | None:
    env = _fresh_env(APP_MODE='railway')
    proc = subprocess.run(
        [
            sys.executable,
            '-c',
            'import os; '
            'from backend.config.local_safe_mode import apply_railway_telegram_defaults; '
            'apply_railway_telegram_defaults(); '
            'print(os.environ.get("DISABLE_LEGACY_TELEGRAM_LISTENER", ""))',
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return f'railway defaults subprocess failed: {proc.stderr or proc.stdout}'
    if proc.stdout.strip() != '1':
        return f'expected DISABLE_LEGACY_TELEGRAM_LISTENER=1, got {proc.stdout.strip()!r}'
    return None


def test_railway_environment_defaults_legacy_off() -> str | None:
    env = _fresh_env(RAILWAY_ENVIRONMENT='production')
    proc = subprocess.run(
        [
            sys.executable,
            '-c',
            'import os; '
            'from backend.config.local_safe_mode import apply_railway_telegram_defaults; '
            'apply_railway_telegram_defaults(); '
            'print(os.environ.get("DISABLE_LEGACY_TELEGRAM_LISTENER", ""))',
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return f'railway env defaults subprocess failed: {proc.stderr or proc.stdout}'
    if proc.stdout.strip() != '1':
        return f'RAILWAY_ENVIRONMENT should default legacy off, got {proc.stdout.strip()!r}'
    return None


def test_api_server_legacy_guard() -> str | None:
    api_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    for fragment in (
        'DISABLE_LEGACY_TELEGRAM_LISTENER',
        'LEGACY_TELEGRAM_LISTENER_DISABLED',
        '_legacy_telegram_listener_disabled',
        'apply_railway_telegram_defaults',
    ):
        if fragment not in api_src:
            return f'api_server missing legacy guard fragment: {fragment}'
    return None


def test_railway_web_disables_legacy() -> str | None:
    web_src = (PROJECT_ROOT / 'scripts/run_railway_web.py').read_text(encoding='utf-8')
    if 'DISABLE_LEGACY_TELEGRAM_LISTENER' not in web_src:
        return 'run_railway_web missing DISABLE_LEGACY_TELEGRAM_LISTENER'
    if 'legacy_telegram_listener_disabled' not in web_src:
        return 'run_railway_web missing legacy_telegram_listener_disabled log'
    return None


def test_railway_worker_uses_analysis_bot() -> str | None:
    worker_src = (PROJECT_ROOT / 'scripts/run_railway_telegram_worker.py').read_text(encoding='utf-8')
    for fragment in (
        "APP_MODE': 'railway'",
        'TELEGRAM_COMMANDS_ENABLED',
        'DISABLE_TELEGRAM_LISTENER',
        'DISABLE_LEGACY_TELEGRAM_LISTENER',
        'telegram_analysis_bot',
        'listen_forever',
    ):
        if fragment not in worker_src:
            return f'run_railway_telegram_worker missing: {fragment}'
    if 'orchestration.telegram_listener' in worker_src or 'telegram_listener import' in worker_src:
        return 'run_railway_telegram_worker must not import telegram_listener'
    return None


def test_new_help_not_legacy() -> str | None:
    from backend.telegram.telegram_analysis_bot import HELP_TEXT

    if '🤖 AstraEdge Telegram' not in HELP_TEXT:
        return 'HELP_TEXT missing AstraEdge header'
    for marker in LEGACY_HELP_MARKERS:
        if marker in HELP_TEXT:
            return f'HELP_TEXT must not contain legacy marker: {marker}'
    return None


def test_status_includes_build() -> str | None:
    from backend.telegram.response_format import format_status_text, strip_stage_markers

    status = strip_stage_markers(format_status_text())
    if 'Telegram build: AstraEdge 46D' not in status and 'AstraEdge 46D' not in status:
        return 'format_status_text missing Telegram build: AstraEdge 46D'
    return None


def test_build_info_payload() -> str | None:
    api_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    if '@app.get("/api/debug/build-info")' not in api_src:
        return 'build-info route missing in api_server.py'
    for fragment in (
        "'app': 'AstraEdge'",
        "'stage': '46D'",
        "'telegram_handler': 'astraedge_analysis_bot'",
        'legacy_telegram_listener',
        'get_data_root',
    ):
        if fragment not in api_src:
            return f'build-info source missing: {fragment}'

    env = _fresh_env(APP_MODE='railway', DISABLE_LEGACY_TELEGRAM_LISTENER='1')
    proc = subprocess.run(
        [
            sys.executable,
            '-c',
            'import os; '
            'os.environ["APP_MODE"] = "railway"; '
            'os.environ["DISABLE_LEGACY_TELEGRAM_LISTENER"] = "1"; '
            'from backend.config.local_safe_mode import is_legacy_telegram_listener_disabled; '
            'from backend.storage.data_paths import get_data_root; '
            'legacy_field = not is_legacy_telegram_listener_disabled(); '
            'assert legacy_field is False, legacy_field; '
            'assert os.environ.get("APP_MODE") == "railway"; '
            'assert get_data_root() is not None; '
            'print("ok")',
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return f'build-info logic check failed: {proc.stderr or proc.stdout}'
    return None


def main() -> int:
    tests = (
        test_railway_defaults_legacy_off,
        test_railway_environment_defaults_legacy_off,
        test_api_server_legacy_guard,
        test_railway_web_disables_legacy,
        test_railway_worker_uses_analysis_bot,
        test_new_help_not_legacy,
        test_status_includes_build,
        test_build_info_payload,
    )
    for test_fn in tests:
        err = test_fn()
        if err:
            return _fail(err)

    print(STAGE_MARKER)
    print('RAILWAY_TELEGRAM_HANDLER_SELECTION_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
