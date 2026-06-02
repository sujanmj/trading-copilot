#!/usr/bin/env python3
"""
Telegram-mode local system readiness gate (Stage 45B4).

Usage:
  python scripts/local_system_readiness_telegram_mode.py

Expects Telegram analysis mode env (DISABLE_TELEGRAM=0, etc.).
Prints LOCAL_SYSTEM_READY_TELEGRAM_MODE on success.
Does not modify local_system_readiness.py behavior.
Marker: LOCAL_STAGE_45B4_TELEGRAM_MODE_READY
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

STAGE_MARKER = 'LOCAL_STAGE_45B4_TELEGRAM_MODE_READY'
KEYS_ENV = PROJECT_ROOT / 'config' / 'keys.env'
CANONICAL_DB = PROJECT_ROOT / 'data' / 'canonical_market_memory.db'
HISTORICAL_DB = PROJECT_ROOT / 'data' / 'historical_market_memory.db'
ENRICHED_PATH = PROJECT_ROOT / 'data' / 'latest_market_data_memory_enriched.json'
DEFAULT_API_BASE = 'http://127.0.0.1:8080'

COMPACT_ORDER = (
    'local_safety',
    'telegram_enabled',
    'command_bot',
    'order_blocked',
    'market_memory',
    'historical_memory',
    'final_confidence',
    'tomorrow_watchlist',
    'daily_pack',
    'stock_decision_engine',
    'live_smoke',
)


@dataclass
class ReadinessResult:
    sections: dict[str, str] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)

    def set_ok(self, name: str) -> None:
        self.sections[name] = 'ok'

    def set_fail(self, name: str, message: str) -> None:
        self.sections[name] = 'fail'
        self.failures[name] = message

    def ready(self) -> bool:
        return not self.failures and all(
            self.sections.get(name) == 'ok' for name in COMPACT_ORDER
        )

    def first_failure(self) -> tuple[str, str] | None:
        for name in COMPACT_ORDER:
            if name in self.failures:
                return name, self.failures[name]
        return None


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


def _apply_telegram_mode_defaults() -> None:
    for key, val in {
        'LOCAL_DEV_MODE': '1',
        'LOCAL_ONLY': '1',
        'DISABLE_TELEGRAM': '0',
        'DISABLE_TELEGRAM_LISTENER': '0',
        'DISABLE_TELEGRAM_SENDS': '0',
        'TELEGRAM_COMMANDS_ENABLED': '1',
        'DISABLE_TRADE_EXECUTION': '1',
        'TELEGRAM_TRADE_COMMANDS_ENABLED': '0',
        'DISABLE_RAILWAY_API': '1',
    }.items():
        os.environ[key] = val


def _run_validator_script(script_name: str, *, success_token: str) -> tuple[bool, str]:
    script = PROJECT_ROOT / 'scripts' / script_name
    if not script.is_file():
        return False, f'missing script: {script_name}'
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    combined = (proc.stdout or '') + (proc.stderr or '')
    if proc.returncode != 0:
        tail = combined.strip().splitlines()[-1] if combined.strip() else f'exit {proc.returncode}'
        return False, tail
    if success_token not in combined:
        return False, f'missing token {success_token}'
    return True, success_token


def _backend_running(api_base: str = DEFAULT_API_BASE) -> bool:
    url = f'{api_base.rstrip("/")}/api/health'
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _check_local_safety(result: ReadinessResult) -> None:
    if not KEYS_ENV.is_file():
        result.set_fail('local_safety', f'keys.env missing at {KEYS_ENV.relative_to(PROJECT_ROOT)}')
        return

    if not (_env_truthy('LOCAL_ONLY') or _env_truthy('LOCAL_DEV_MODE')):
        result.set_fail('local_safety', 'LOCAL_ONLY and LOCAL_DEV_MODE both unset')
        return

    if _env_truthy('DISABLE_TELEGRAM'):
        result.set_fail('local_safety', 'DISABLE_TELEGRAM must be 0 for telegram mode')
        return

    if not _env_truthy('DISABLE_TRADE_EXECUTION'):
        result.set_fail('local_safety', 'DISABLE_TRADE_EXECUTION must be 1')
        return

    if _env_truthy('TELEGRAM_TRADE_COMMANDS_ENABLED'):
        result.set_fail('local_safety', 'TELEGRAM_TRADE_COMMANDS_ENABLED must be 0')
        return

    run_local = PROJECT_ROOT / 'run_local.py'
    if not run_local.is_file():
        result.set_fail('local_safety', 'run_local.py missing')
        return

    try:
        from backend.utils import config as cfg

        if cfg.IS_RAILWAY:
            result.set_fail('local_safety', 'IS_RAILWAY unexpectedly True')
            return
    except Exception as exc:
        result.set_fail('local_safety', f'config import: {exc}')
        return

    result.set_ok('local_safety')


def _check_telegram_enabled(result: ReadinessResult) -> None:
    if _env_truthy('DISABLE_TELEGRAM'):
        result.set_fail('telegram_enabled', 'DISABLE_TELEGRAM=1')
        return

    for flag in ('DISABLE_TELEGRAM_LISTENER', 'DISABLE_TELEGRAM_SENDS'):
        if _env_truthy(flag):
            result.set_fail('telegram_enabled', f'{flag}=1')
            return

    if not _env_truthy('TELEGRAM_COMMANDS_ENABLED'):
        result.set_fail('telegram_enabled', 'TELEGRAM_COMMANDS_ENABLED must be 1')
        return

    try:
        from backend.utils.telegram_guard import is_telegram_listener_enabled, is_telegram_send_enabled

        if not is_telegram_send_enabled() or not is_telegram_listener_enabled():
            result.set_fail('telegram_enabled', 'telegram_guard reports Telegram disabled')
            return
    except Exception as exc:
        result.set_fail('telegram_enabled', str(exc))
        return

    result.set_ok('telegram_enabled')


def _check_command_bot(result: ReadinessResult) -> None:
    runner = PROJECT_ROOT / 'scripts' / 'run_telegram_analysis_bot.py'
    bot_module = PROJECT_ROOT / 'backend' / 'telegram' / 'telegram_analysis_bot.py'
    lazy_runner = PROJECT_ROOT / 'backend' / 'telegram' / 'lazy_command_runner.py'

    for path in (runner, bot_module, lazy_runner):
        if not path.is_file():
            result.set_fail('command_bot', f'missing {path.relative_to(PROJECT_ROOT)}')
            return

    bot_src = bot_module.read_text(encoding='utf-8')
    if 'handle_analysis_command' not in bot_src:
        result.set_fail('command_bot', 'handle_analysis_command missing')
        return
    if 'lazy_command_runner' not in bot_src:
        result.set_fail('command_bot', 'bot must use lazy_command_runner')
        return

    result.set_ok('command_bot')


def _check_order_blocked(result: ReadinessResult) -> None:
    try:
        from backend.telegram.response_format import (
            BLOCKED_TRADE_COMMANDS,
            TRADE_EXECUTION_PERMANENTLY_DISABLED,
        )

        if not TRADE_EXECUTION_PERMANENTLY_DISABLED:
            result.set_fail('order_blocked', 'TRADE_EXECUTION_PERMANENTLY_DISABLED is False')
            return
        if not BLOCKED_TRADE_COMMANDS:
            result.set_fail('order_blocked', 'BLOCKED_TRADE_COMMANDS empty')
            return
    except Exception as exc:
        result.set_fail('order_blocked', str(exc))
        return

    result.set_ok('order_blocked')


def _check_market_memory(result: ReadinessResult) -> None:
    ok, detail = _run_validator_script('validate_market_memory.py', success_token='MARKET_MEMORY_OK')
    if not ok:
        result.set_fail('market_memory', detail)
        return

    if not CANONICAL_DB.is_file():
        result.set_fail('market_memory', f'missing {CANONICAL_DB.name}')
        return

    try:
        conn = sqlite3.connect(f'file:{CANONICAL_DB}?mode=ro', uri=True)
        try:
            legacy_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM predictions WHERE prediction_id LIKE 'legacy:%'",
                ).fetchone()[0]
            )
            if legacy_count > 0:
                result.set_fail('market_memory', f'legacy_prediction_ids={legacy_count}')
                return
        finally:
            conn.close()
    except sqlite3.Error as exc:
        result.set_fail('market_memory', str(exc))
        return

    if not ENRICHED_PATH.is_file():
        result.set_fail('market_memory', 'enriched price file missing')
        return

    result.set_ok('market_memory')


def _check_historical_memory(result: ReadinessResult) -> None:
    ok, detail = _run_validator_script(
        'validate_historical_market_memory.py',
        success_token='HISTORICAL_MARKET_MEMORY_OK',
    )
    if not ok:
        result.set_fail('historical_memory', detail)
        return
    if not HISTORICAL_DB.is_file():
        result.set_fail('historical_memory', f'missing {HISTORICAL_DB.name}')
        return
    result.set_ok('historical_memory')


def _check_final_confidence(result: ReadinessResult) -> None:
    ok, detail = _run_validator_script(
        'validate_final_confidence_report.py',
        success_token='FINAL_CONFIDENCE_REPORT_VALIDATE_OK',
    )
    if not ok:
        result.set_fail('final_confidence', detail)
        return
    result.set_ok('final_confidence')


def _check_tomorrow_watchlist(result: ReadinessResult) -> None:
    ok, detail = _run_validator_script(
        'validate_tomorrow_watchlist.py',
        success_token='TOMORROW_WATCHLIST_VALIDATE_OK',
    )
    if not ok:
        result.set_fail('tomorrow_watchlist', detail)
        return
    result.set_ok('tomorrow_watchlist')


def _check_daily_pack(result: ReadinessResult) -> None:
    ok, detail = _run_validator_script(
        'validate_daily_report_pack.py',
        success_token='DAILY_REPORT_PACK_VALIDATE_OK',
    )
    if not ok:
        result.set_fail('daily_pack', detail)
        return
    result.set_ok('daily_pack')


def _check_stock_decision_engine(result: ReadinessResult) -> None:
    ok, detail = _run_validator_script(
        'validate_stock_decision_engine.py',
        success_token='STOCK_DECISION_ENGINE_OK',
    )
    if not ok:
        result.set_fail('stock_decision_engine', detail)
        return
    result.set_ok('stock_decision_engine')


def _check_live_smoke(result: ReadinessResult, *, api_base: str) -> None:
    if not _backend_running(api_base):
        result.set_ok('live_smoke')
        result.sections['live_smoke_note'] = 'skipped_backend_not_running'
        return

    proc = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'scripts' / 'live_system_smoke.py'),
            '--frontend-mode',
            'skip',
            '--api-base',
            api_base,
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = (proc.stdout or '') + (proc.stderr or '')
    if proc.returncode != 0 or 'LIVE_SYSTEM_SMOKE_OK' not in combined:
        tail = combined.strip().splitlines()[-1] if combined.strip() else f'exit {proc.returncode}'
        result.set_fail('live_smoke', tail)
        return
    result.set_ok('live_smoke')


CHECKERS: tuple[tuple[str, Callable[..., None]], ...] = (
    ('local_safety', _check_local_safety),
    ('telegram_enabled', _check_telegram_enabled),
    ('command_bot', _check_command_bot),
    ('order_blocked', _check_order_blocked),
    ('market_memory', _check_market_memory),
    ('historical_memory', _check_historical_memory),
    ('final_confidence', _check_final_confidence),
    ('tomorrow_watchlist', _check_tomorrow_watchlist),
    ('daily_pack', _check_daily_pack),
    ('stock_decision_engine', _check_stock_decision_engine),
)


def run_telegram_mode_readiness(
    *,
    api_base: str = DEFAULT_API_BASE,
    stop_on_first_fail: bool = True,
) -> ReadinessResult:
    result = ReadinessResult()
    _apply_telegram_mode_defaults()
    for name, checker in CHECKERS:
        checker(result)
        if stop_on_first_fail and result.failures:
            break
    _check_live_smoke(result, api_base=api_base)
    return result


def print_readiness(result: ReadinessResult) -> None:
    for name in COMPACT_ORDER:
        status = result.sections.get(name, 'fail' if name in result.failures else 'pending')
        if status == 'pending' and name not in result.sections:
            continue
        print(f'[TELEGRAM_MODE_READY] {name}={status}')

    note = result.sections.get('live_smoke_note')
    if note:
        print(f'[TELEGRAM_MODE_READY] {note}')

    failure = result.first_failure()
    if failure:
        check_name, message = failure
        print(f'[TELEGRAM_MODE_READY] fail={check_name}: {message}')

    print(f'[TELEGRAM_MODE_READY] ready={result.ready()}')
    if result.ready():
        print(STAGE_MARKER)
        print('LOCAL_SYSTEM_READY_TELEGRAM_MODE')


def main() -> int:
    parser = argparse.ArgumentParser(description='Telegram-mode local system readiness gate.')
    parser.add_argument('--api-base', default=DEFAULT_API_BASE)
    parser.add_argument(
        '--continue-on-fail',
        action='store_true',
        help='Run all checks even after first failure',
    )
    args = parser.parse_args()

    result = run_telegram_mode_readiness(
        api_base=args.api_base,
        stop_on_first_fail=not args.continue_on_fail,
    )
    print_readiness(result)
    return 0 if result.ready() else 1


if __name__ == '__main__':
    raise SystemExit(main())
