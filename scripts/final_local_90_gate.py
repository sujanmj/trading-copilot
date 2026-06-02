#!/usr/bin/env python3
"""
Final local 90% completion gate before Railway (Stage 45B4).

Usage:
  python scripts/final_local_90_gate.py
  python scripts/final_local_90_gate.py --with-gui

Prints LOCAL_90_GATE_OK on success.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

DEFAULT_API_BASE = 'http://127.0.0.1:8080'
FRONTEND_DIR = PROJECT_ROOT / 'frontend'

GATE_STEPS: tuple[tuple[str, list[str], str], ...] = (
    ('test_telegram_data_accuracy', ['scripts/test_telegram_data_accuracy.py'], 'TELEGRAM_DATA_ACCURACY_TEST_OK'),
    ('validate_telegram_data_accuracy', ['scripts/validate_telegram_data_accuracy.py'], 'TELEGRAM_DATA_ACCURACY_OK'),
    ('test_telegram_action_plan', ['scripts/test_telegram_action_plan.py'], 'TELEGRAM_ACTION_PLAN_TEST_OK'),
    ('validate_telegram_action_plan', ['scripts/validate_telegram_action_plan.py'], 'TELEGRAM_ACTION_PLAN_OK'),
    ('test_stock_decision_engine', ['scripts/test_stock_decision_engine.py'], 'STOCK_DECISION_ENGINE_TEST_OK'),
    ('validate_stock_decision_engine', ['scripts/validate_stock_decision_engine.py'], 'STOCK_DECISION_ENGINE_OK'),
    ('test_telegram_output_clean', ['scripts/test_telegram_output_clean.py'], 'TELEGRAM_OUTPUT_CLEAN_TEST_OK'),
    ('test_telegram_analysis_bot', ['scripts/test_telegram_analysis_bot.py'], 'TELEGRAM_ANALYSIS_BOT_TEST_OK'),
    ('local_system_readiness_telegram_mode', ['scripts/local_system_readiness_telegram_mode.py'], 'LOCAL_SYSTEM_READY_TELEGRAM_MODE'),
    ('validate_market_memory', ['scripts/validate_market_memory.py'], 'MARKET_MEMORY_OK'),
    ('validate_historical_market_memory', ['scripts/validate_historical_market_memory.py'], 'HISTORICAL_MARKET_MEMORY_OK'),
    ('railway_preflight_audit', ['scripts/railway_preflight_audit.py'], 'RAILWAY_PREFLIGHT_AUDIT_OK'),
    ('validate_railway_preflight_audit', ['scripts/validate_railway_preflight_audit.py'], 'RAILWAY_PREFLIGHT_VALIDATE_OK'),
)


@dataclass
class GateResult:
    sections: dict[str, str] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)

    def set_ok(self, name: str) -> None:
        self.sections[name] = 'ok'

    def set_fail(self, name: str, message: str) -> None:
        self.sections[name] = 'fail'
        self.failures[name] = message

    def ready(self) -> bool:
        return not self.failures


def _backend_running(api_base: str) -> bool:
    url = f'{api_base.rstrip("/")}/api/health'
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _run_step(name: str, argv: list[str], success_token: str) -> tuple[bool, str]:
    script = PROJECT_ROOT / argv[0]
    if not script.is_file():
        return False, f'missing {argv[0]}'
    proc = subprocess.run(
        [sys.executable, str(script), *argv[1:]],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )
    combined = (proc.stdout or '') + (proc.stderr or '')
    if proc.returncode != 0:
        tail = combined.strip().splitlines()[-1] if combined.strip() else f'exit {proc.returncode}'
        return False, tail
    if success_token not in combined:
        return False, f'missing token {success_token}'
    return True, success_token


def _run_npm(script_name: str) -> tuple[bool, str]:
    package_json = FRONTEND_DIR / 'package.json'
    if not package_json.is_file():
        return False, 'frontend/package.json missing'
    proc = subprocess.run(
        ['npm', 'run', script_name],
        cwd=str(FRONTEND_DIR),
        capture_output=True,
        text=True,
        timeout=900,
        shell=True,
    )
    combined = (proc.stdout or '') + (proc.stderr or '')
    if proc.returncode != 0:
        tail = combined.strip().splitlines()[-1] if combined.strip() else f'exit {proc.returncode}'
        return False, tail
    return True, 'ok'


def run_final_local_90_gate(
    *,
    api_base: str = DEFAULT_API_BASE,
    frontend_base: str = 'http://127.0.0.1:5173',
    with_gui: bool = False,
) -> GateResult:
    result = GateResult()

    for name, argv, token in GATE_STEPS:
        ok, detail = _run_step(name, argv, token)
        if ok:
            result.set_ok(name)
        else:
            result.set_fail(name, detail)
            return result

    if _backend_running(api_base):
        smoke_argv = [
            'scripts/live_system_smoke.py',
            '--frontend-mode',
            'web',
            '--frontend-base',
            frontend_base,
            '--api-base',
            api_base,
        ]
        ok, detail = _run_step('live_system_smoke', smoke_argv, 'LIVE_SYSTEM_SMOKE_OK')
        if not ok and 'frontend' in detail.lower():
            fallback_argv = [
                'scripts/live_system_smoke.py',
                '--skip-frontend',
                '--api-base',
                api_base,
            ]
            ok, detail = _run_step('live_system_smoke', fallback_argv, 'LIVE_SYSTEM_SMOKE_OK')
            if ok:
                result.set_ok('live_system_smoke')
                result.sections['live_system_smoke_note'] = 'frontend_skipped_unreachable'
            else:
                result.set_fail('live_system_smoke', detail)
                return result
        elif ok:
            result.set_ok('live_system_smoke')
        else:
            result.set_fail('live_system_smoke', detail)
            return result
    else:
        result.set_ok('live_system_smoke')
        result.sections['live_system_smoke_note'] = 'skipped_backend_not_running'

    if with_gui:
        for npm_script in ('test:gui', 'test:e2e'):
            ok, detail = _run_npm(npm_script)
            if ok:
                result.set_ok(npm_script)
            else:
                result.set_fail(npm_script, detail)
                return result

    return result


def print_gate(result: GateResult) -> None:
    for name, status in result.sections.items():
        if name.endswith('_note'):
            print(f'[LOCAL_90_GATE] {status}')
            continue
        print(f'[LOCAL_90_GATE] {name}={status}')

    if result.failures:
        first = next(iter(result.failures.items()))
        print(f'[LOCAL_90_GATE] fail={first[0]}: {first[1]}')

    print(f'[LOCAL_90_GATE] ready={result.ready()}')
    if result.ready():
        print('LOCAL_90_GATE_OK')


def main() -> int:
    parser = argparse.ArgumentParser(description='Final local 90% completion gate.')
    parser.add_argument('--api-base', default=DEFAULT_API_BASE)
    parser.add_argument('--frontend-base', default='http://127.0.0.1:5173')
    parser.add_argument(
        '--with-gui',
        action='store_true',
        help='Also run npm run test:gui and npm run test:e2e',
    )
    args = parser.parse_args()

    result = run_final_local_90_gate(
        api_base=args.api_base,
        frontend_base=args.frontend_base,
        with_gui=args.with_gui,
    )
    print_gate(result)
    return 0 if result.ready() else 1


if __name__ == '__main__':
    raise SystemExit(main())
