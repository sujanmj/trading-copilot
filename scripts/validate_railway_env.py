#!/usr/bin/env python3
"""
Railway environment validation (Stage 46A).

Usage:
  python scripts/validate_railway_env.py
  python scripts/validate_railway_env.py --local-check

Prints RAILWAY_ENV_VALIDATE_OK on success.
Does not print secret values.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

STAGE_MARKER = 'RAILWAY_STAGE_46A_ENV_VALIDATE'

REQUIRED_RAILWAY_ENV = (
    'RAILWAY_ENVIRONMENT',
    'PORT',
    'RAILWAY_DATA_DIR',
    'APP_MODE',
    'LOCAL_DEV_MODE',
    'LOCAL_ONLY',
)

REQUIRED_TELEGRAM_WORKER_ENV = (
    'DISABLE_TELEGRAM',
    'DISABLE_TELEGRAM_SENDS',
    'DISABLE_TELEGRAM_LISTENER',
    'TELEGRAM_COMMANDS_ENABLED',
    'TELEGRAM_TRADE_COMMANDS_ENABLED',
    'DISABLE_TRADE_EXECUTION',
)

RAILWAY_RUNNER_SCRIPTS = (
    'scripts/run_railway_web.py',
    'scripts/run_railway_telegram_worker.py',
    'scripts/run_railway_morning_brief.py',
    'scripts/run_railway_market_close.py',
    'scripts/run_railway_overnight_brief.py',
)

SECRET_PRINT_PATTERNS = (
    re.compile(r'print\s*\([^)]*TELEGRAM_BOT_TOKEN[^)]*\)', re.IGNORECASE),
    re.compile(r'print\s*\([^)]*TELEGRAM_CHAT_ID[^)]*\)', re.IGNORECASE),
    re.compile(r'print\s*\([^)]*API_KEY[^)]*\)', re.IGNORECASE),
    re.compile(r'print\s*\([^)]*ANTHROPIC_API_KEY[^)]*\)', re.IGNORECASE),
)

AUDIT_SECTIONS = (
    'required_scripts',
    'trade_execution_disabled',
    'telegram_safety',
    'no_secrets_printed',
    'data_path_writable',
    'port_handling',
    'env_keys',
    'no_keys_env_required',
)


@dataclass
class EnvResult:
    sections: dict[str, str] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def set_ok(self, name: str) -> None:
        self.sections[name] = 'ok'

    def set_fail(self, name: str, message: str) -> None:
        self.sections[name] = 'fail'
        self.failures[name] = message

    def ready(self) -> bool:
        return not self.failures and all(
            self.sections.get(name) == 'ok' for name in AUDIT_SECTIONS
        )


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


def _check_required_scripts(result: EnvResult) -> None:
    missing = [rel for rel in RAILWAY_RUNNER_SCRIPTS if not (PROJECT_ROOT / rel).is_file()]
    if missing:
        result.set_fail('required_scripts', f'missing: {", ".join(missing)}')
        return
    result.set_ok('required_scripts')


def _check_trade_execution_disabled(result: EnvResult) -> None:
    from backend.telegram.response_format import TRADE_EXECUTION_PERMANENTLY_DISABLED

    if not TRADE_EXECUTION_PERMANENTLY_DISABLED:
        result.set_fail('trade_execution_disabled', 'TRADE_EXECUTION_PERMANENTLY_DISABLED not True')
        return
    if not _env_truthy('DISABLE_TRADE_EXECUTION'):
        result.warnings.append('DISABLE_TRADE_EXECUTION not set to 1 in current env')
    result.set_ok('trade_execution_disabled')


def _check_telegram_safety(result: EnvResult, *, local_check: bool) -> None:
    worker_src = (PROJECT_ROOT / 'scripts/run_railway_telegram_worker.py').read_text(encoding='utf-8')
    for token in ('TELEGRAM_COMMANDS_ENABLED', 'TELEGRAM_TRADE_COMMANDS_ENABLED', 'DISABLE_TRADE_EXECUTION'):
        if token not in worker_src:
            result.set_fail('telegram_safety', f'worker missing {token} check')
            return

    if local_check:
        result.set_ok('telegram_safety')
        return

    if _env_truthy('TELEGRAM_TRADE_COMMANDS_ENABLED'):
        result.set_fail('telegram_safety', 'TELEGRAM_TRADE_COMMANDS_ENABLED must be 0')
        return
    if not _env_truthy('DISABLE_TRADE_EXECUTION'):
        result.set_fail('telegram_safety', 'DISABLE_TRADE_EXECUTION must be 1')
        return
    result.set_ok('telegram_safety')


def _check_no_secrets_printed(result: EnvResult) -> None:
    for rel in RAILWAY_RUNNER_SCRIPTS + ('scripts/validate_railway_env.py',):
        path = PROJECT_ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8')
        for pattern in SECRET_PRINT_PATTERNS:
            if pattern.search(text):
                result.set_fail('no_secrets_printed', f'possible secret print in {rel}')
                return
    result.set_ok('no_secrets_printed')


def _check_data_path_writable(result: EnvResult) -> None:
    from backend.storage.data_paths import get_data_path, get_data_root

    try:
        root = get_data_root()
        root.mkdir(parents=True, exist_ok=True)
        probe = get_data_path('.railway_env_probe')
        probe.write_text('ok', encoding='utf-8')
        probe.unlink(missing_ok=True)
    except OSError as exc:
        result.set_fail('data_path_writable', str(exc))
        return
    result.set_ok('data_path_writable')


def _check_port_handling(result: EnvResult) -> None:
    web_src = (PROJECT_ROOT / 'scripts/run_railway_web.py').read_text(encoding='utf-8')
    if "os.environ.get('PORT'" not in web_src and 'os.environ.get("PORT"' not in web_src:
        result.set_fail('port_handling', 'run_railway_web.py must read PORT from env')
        return
    if "'0.0.0.0'" not in web_src and '"0.0.0.0"' not in web_src:
        result.set_fail('port_handling', 'run_railway_web.py must default HOST to 0.0.0.0')
        return
    result.set_ok('port_handling')


def _check_env_keys(result: EnvResult, *, local_check: bool) -> None:
    if local_check:
        missing = [key for key in REQUIRED_RAILWAY_ENV if key not in os.environ]
        if missing:
            result.warnings.append(f'local-check unset (expected locally): {", ".join(missing)}')
        result.set_ok('env_keys')
        return

    missing = [key for key in REQUIRED_RAILWAY_ENV if not os.environ.get(key, '').strip()]
    if missing:
        result.set_fail('env_keys', f'missing: {", ".join(missing)}')
        return

    if os.environ.get('APP_MODE', '').strip().lower() != 'railway':
        result.set_fail('env_keys', 'APP_MODE must be railway')
        return
    if _env_truthy('LOCAL_DEV_MODE') or _env_truthy('LOCAL_ONLY'):
        result.set_fail('env_keys', 'LOCAL_DEV_MODE and LOCAL_ONLY must be 0 on Railway')
        return
    result.set_ok('env_keys')


def _check_no_keys_env_required(result: EnvResult) -> None:
    for rel in RAILWAY_RUNNER_SCRIPTS:
        text = (PROJECT_ROOT / rel).read_text(encoding='utf-8')
        if 'keys.env' in text and 'require' in text.lower():
            result.set_fail('no_keys_env_required', f'{rel} appears to require keys.env')
            return
    result.set_ok('no_keys_env_required')


def run_validate_railway_env(*, local_check: bool = False) -> EnvResult:
    result = EnvResult()
    _check_required_scripts(result)
    _check_trade_execution_disabled(result)
    _check_telegram_safety(result, local_check=local_check)
    _check_no_secrets_printed(result)
    _check_data_path_writable(result)
    _check_port_handling(result)
    _check_env_keys(result, local_check=local_check)
    _check_no_keys_env_required(result)
    return result


def print_result(result: EnvResult) -> None:
    for name in AUDIT_SECTIONS:
        status = result.sections.get(name, 'fail' if name in result.failures else 'pending')
        if status == 'pending' and name not in result.sections:
            continue
        print(f'[RAILWAY_ENV] {name}={status}')

    for warning in result.warnings:
        print(f'[RAILWAY_ENV] warn={warning}')

    if result.failures:
        first = next(iter(result.failures.items()))
        print(f'[RAILWAY_ENV] fail={first[0]}: {first[1]}')

    print(f'[RAILWAY_ENV] ready={result.ready()}')
    if result.ready():
        print(STAGE_MARKER)
        print('RAILWAY_ENV_VALIDATE_OK')


def main() -> int:
    parser = argparse.ArgumentParser(description='Validate Railway deployment environment.')
    parser.add_argument(
        '--local-check',
        action='store_true',
        help='Validate scripts and local data path without requiring Railway env vars',
    )
    args = parser.parse_args()

    if args.local_check:
        os.environ.setdefault('LOCAL_DEV_MODE', '1')
        os.environ.setdefault('DISABLE_TRADE_EXECUTION', '1')
        os.environ.setdefault('TELEGRAM_TRADE_COMMANDS_ENABLED', '0')

    result = run_validate_railway_env(local_check=args.local_check)
    print_result(result)
    return 0 if result.ready() else 1


if __name__ == '__main__':
    raise SystemExit(main())
