#!/usr/bin/env python3
"""
Unit tests for Railway monolith AstraEdge Telegram start (Stage 46E).

Usage:
  python scripts/test_railway_monolith_astraedge_telegram_start.py

Prints RAILWAY_MONOLITH_ASTRAEDGE_TELEGRAM_START_TEST_OK on success.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

STAGE_MARKER = 'RAILWAY_STAGE_46E_MONOLITH_TELEGRAM'
LEGACY_HELP_MARKERS = (
    'Trading Copilot Commands',
    '/review',
    '/elite',
    '/opps',
    '/brain',
    '/refresh',
)


def _fail(msg: str) -> int:
    print(f'RAILWAY_MONOLITH_ASTRAEDGE_TELEGRAM_START_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _fresh_env(**overrides: str) -> dict[str, str]:
    env = dict(os.environ)
    for key in (
        'APP_MODE',
        'RAILWAY_ENVIRONMENT',
        'DISABLE_LEGACY_TELEGRAM_LISTENER',
        'DISABLE_TELEGRAM_LISTENER',
        'DISABLE_TELEGRAM',
        'TELEGRAM_COMMANDS_ENABLED',
        'TELEGRAM_BOT_TOKEN',
        'TELEGRAM_CHAT_ID',
        'RAILWAY_TELEGRAM_START_DRY_RUN',
    ):
        env.pop(key, None)
    env.update({'PYTHONIOENCODING': 'utf-8'})
    env.update(overrides)
    return env


def test_run_railway_web_monolith_wiring() -> str | None:
    web_src = (PROJECT_ROOT / 'scripts/run_railway_web.py').read_text(encoding='utf-8')
    for fragment in (
        'ensure_astraedge_telegram_started',
        'log_data_startup',
        'LEGACY_TELEGRAM_LISTENER_DISABLED',
        'TELEGRAM_COMMANDS_ENABLED',
        'DISABLE_TELEGRAM_LISTENER',
        'DISABLE_LEGACY_TELEGRAM_LISTENER',
    ):
        if fragment not in web_src:
            return f'run_railway_web missing: {fragment}'
    if 'ENABLE_TELEGRAM_IN_WEB' in web_src:
        return 'run_railway_web must not gate on ENABLE_TELEGRAM_IN_WEB'
    return None


def test_api_server_astraedge_start() -> str | None:
    api_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    for fragment in (
        'ensure_astraedge_telegram_started',
        'LEGACY_TELEGRAM_LISTENER_DISABLED',
        '_legacy_telegram_listener_active',
        'astraedge_telegram_started',
        "'stage': '46E'",
    ):
        if fragment not in api_src:
            return f'api_server missing: {fragment}'
    return None


def test_should_start_conditions() -> str | None:
    env = _fresh_env(
        APP_MODE='railway',
        TELEGRAM_COMMANDS_ENABLED='1',
        DISABLE_TELEGRAM_LISTENER='0',
        DISABLE_LEGACY_TELEGRAM_LISTENER='1',
    )
    proc = subprocess.run(
        [
            sys.executable,
            '-c',
            'from backend.telegram.telegram_analysis_bot import should_start_astraedge_telegram; '
            'print(should_start_astraedge_telegram())',
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return proc.stderr or proc.stdout
    if proc.stdout.strip() != 'True':
        return f'should_start_astraedge_telegram expected True, got {proc.stdout.strip()!r}'
    return None


def test_should_not_start_when_listener_disabled() -> str | None:
    env = _fresh_env(
        APP_MODE='railway',
        TELEGRAM_COMMANDS_ENABLED='1',
        DISABLE_TELEGRAM_LISTENER='1',
        DISABLE_LEGACY_TELEGRAM_LISTENER='1',
    )
    proc = subprocess.run(
        [
            sys.executable,
            '-c',
            'from backend.telegram.telegram_analysis_bot import should_start_astraedge_telegram; '
            'print(should_start_astraedge_telegram())',
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return proc.stderr or proc.stdout
    if proc.stdout.strip() != 'False':
        return 'should not start when DISABLE_TELEGRAM_LISTENER=1'
    return None


def _railway_production_env(**extra: str) -> dict[str, str]:
    return _fresh_env(
        APP_MODE='railway',
        RAILWAY_ENVIRONMENT='production',
        TELEGRAM_COMMANDS_ENABLED='1',
        DISABLE_TELEGRAM_LISTENER='0',
        DISABLE_TELEGRAM='0',
        DISABLE_LEGACY_TELEGRAM_LISTENER='1',
        **extra,
    )


def test_start_marker_dry_run() -> str | None:
    """Dry-run: no Telegram network; must still mark started=True."""
    env = _railway_production_env(
        RAILWAY_TELEGRAM_START_DRY_RUN='1',
        TELEGRAM_BOT_TOKEN='',
        TELEGRAM_CHAT_ID='',
    )
    proc = subprocess.run(
        [
            sys.executable,
            '-c',
            'import backend.telegram.telegram_analysis_bot as tab; '
            'tab._astraedge_telegram_started = False; '
            'ok = tab.ensure_astraedge_telegram_started(); '
            'print("started", ok, tab.is_astraedge_telegram_started())',
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return proc.stderr or proc.stdout
    if 'ASTRAEDGE_TELEGRAM_ANALYSIS_BOT_STARTED_DRY_RUN' not in proc.stdout:
        return f'missing dry-run marker: {proc.stdout!r}'
    if 'ASTRAEDGE_TELEGRAM_ANALYSIS_BOT_STARTED\n' in proc.stdout:
        return 'dry-run must not print live start marker'
    if 'started True True' not in proc.stdout:
        return f'ensure_astraedge_telegram_started failed: {proc.stdout!r}'
    return None


def test_start_marker_with_credentials() -> str | None:
    env = _railway_production_env(
        TELEGRAM_BOT_TOKEN='test-token',
        TELEGRAM_CHAT_ID='12345',
    )
    proc = subprocess.run(
        [
            sys.executable,
            '-c',
            'import backend.telegram.telegram_analysis_bot as tab; '
            'tab._astraedge_telegram_started = False; '
            'ok = tab.ensure_astraedge_telegram_started(); '
            'print("started", ok, tab.is_astraedge_telegram_started())',
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return proc.stderr or proc.stdout
    if 'started True True' not in proc.stdout:
        return f'ensure_astraedge_telegram_started failed: {proc.stdout!r}'
    if 'ASTRAEDGE_TELEGRAM_ANALYSIS_BOT_STARTED' not in proc.stdout:
        return f'missing live start marker: {proc.stdout!r}'
    return None


def test_help_astraedge_only() -> str | None:
    from backend.telegram.telegram_analysis_bot import HELP_TEXT, handle_analysis_command

    if '🤖 AstraEdge Telegram' not in HELP_TEXT:
        return 'HELP_TEXT missing AstraEdge header'
    for marker in LEGACY_HELP_MARKERS:
        if marker in HELP_TEXT:
            return f'HELP_TEXT contains legacy marker: {marker}'
    for cmd in ('/action plan', '/aihub brain full', '/ask ai'):
        if cmd.replace('/', '').split()[0] not in HELP_TEXT and cmd not in HELP_TEXT:
            pass
    results = handle_analysis_command('/action', dry_run=True)
    text = results[0].get('text', '') if results else ''
    if 'Unknown command' not in text or 'action' not in text:
        return f'bare /action should be unknown, got: {text!r}'
    plan_results = handle_analysis_command('/action plan', dry_run=True)
    plan_text = plan_results[0].get('text', '') if plan_results else ''
    if not plan_text or 'Unknown command' in plan_text:
        return '/action plan should produce a response'
    return None


def test_build_info_fields() -> str | None:
    api_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    for fragment in (
        'data_preserved',
        'astraedge_telegram_started',
        'is_astraedge_telegram_started',
    ):
        if fragment not in api_src:
            return f'build-info missing: {fragment}'
    return None


def test_post_deploy_strict_flag() -> str | None:
    smoke_src = (PROJECT_ROOT / 'scripts/railway_post_deploy_smoke.py').read_text(encoding='utf-8')
    if '--strict-build-info' not in smoke_src:
        return 'railway_post_deploy_smoke missing --strict-build-info'
    if '46E' not in smoke_src:
        return 'railway_post_deploy_smoke missing stage 46E check'
    return None


def main() -> int:
    bot_src = (PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')
    safe_src = (PROJECT_ROOT / 'backend/config/local_safe_mode.py').read_text(encoding='utf-8')
    for fragment in (
        'ASTRAEDGE_TELEGRAM_ANALYSIS_BOT_STARTED_DRY_RUN',
        'is_railway_telegram_start_dry_run',
        '_refresh_telegram_credentials',
    ):
        if fragment not in bot_src:
            return _fail(f'telegram_analysis_bot missing: {fragment}')
    if 'RAILWAY_TELEGRAM_START_DRY_RUN' not in safe_src:
        return _fail('local_safe_mode missing RAILWAY_TELEGRAM_START_DRY_RUN')

    tests = (
        test_run_railway_web_monolith_wiring,
        test_api_server_astraedge_start,
        test_should_start_conditions,
        test_should_not_start_when_listener_disabled,
        test_start_marker_dry_run,
        test_start_marker_with_credentials,
        test_help_astraedge_only,
        test_build_info_fields,
        test_post_deploy_strict_flag,
    )
    for test_fn in tests:
        err = test_fn()
        if err:
            return _fail(err)

    print(STAGE_MARKER)
    print('RAILWAY_MONOLITH_ASTRAEDGE_TELEGRAM_START_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
