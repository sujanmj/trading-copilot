#!/usr/bin/env python3
"""
Railway deployment readiness pack validator (Stage 46A).

Usage:
  python scripts/validate_railway_readiness_pack.py

Prints RAILWAY_READINESS_PACK_OK on success.
Marker: RAILWAY_STAGE_46A_READINESS_PACK
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

STAGE_MARKER = 'RAILWAY_STAGE_46A_READINESS_PACK'

REQUIRED_FILES = (
    'railway.json',
    'Procfile',
    'docs/RAILWAY_DEPLOYMENT.md',
    'backend/storage/data_paths.py',
    'scripts/run_railway_web.py',
    'scripts/run_railway_telegram_worker.py',
    'scripts/run_railway_morning_brief.py',
    'scripts/run_railway_market_close.py',
    'scripts/run_railway_overnight_brief.py',
    'scripts/validate_railway_env.py',
    'scripts/railway_smoke_local.py',
    'scripts/validate_railway_readiness_pack.py',
)

CRON_SCRIPTS = (
    'scripts/run_railway_morning_brief.py',
    'scripts/run_railway_market_close.py',
    'scripts/run_railway_overnight_brief.py',
)

AUDIT_SECTIONS = (
    'required_files',
    'railway_config',
    'data_paths_helper',
    'trade_execution_disabled',
    'cron_one_shot',
    'no_keys_env_dependency',
    'no_secrets_printed',
    'env_validator',
    'smoke_local',
    'deployment_doc',
)

SECRET_PRINT_PATTERNS = (
    re.compile(r'print\s*\([^)]*TELEGRAM_BOT_TOKEN[^)]*\)', re.IGNORECASE),
    re.compile(r'print\s*\([^)]*TELEGRAM_CHAT_ID[^)]*\)', re.IGNORECASE),
)


@dataclass
class PackResult:
    sections: dict[str, str] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)

    def set_ok(self, name: str) -> None:
        self.sections[name] = 'ok'

    def set_fail(self, name: str, message: str) -> None:
        self.sections[name] = 'fail'
        self.failures[name] = message

    def ready(self) -> bool:
        return not self.failures and all(
            self.sections.get(name) == 'ok' for name in AUDIT_SECTIONS
        )


def _check_required_files(result: PackResult) -> None:
    missing = [rel for rel in REQUIRED_FILES if not (PROJECT_ROOT / rel).is_file()]
    if missing:
        result.set_fail('required_files', f'missing: {", ".join(missing)}')
        return
    result.set_ok('required_files')


def _check_railway_config(result: PackResult) -> None:
    procfile = (PROJECT_ROOT / 'Procfile').read_text(encoding='utf-8')
    railway = (PROJECT_ROOT / 'railway.json').read_text(encoding='utf-8')
    if 'run_railway_web.py' not in procfile:
        result.set_fail('railway_config', 'Procfile missing run_railway_web.py')
        return
    if 'run_railway_web.py' not in railway:
        result.set_fail('railway_config', 'railway.json missing run_railway_web.py startCommand')
        return
    result.set_ok('railway_config')


def _check_data_paths_helper(result: PackResult) -> None:
    src = (PROJECT_ROOT / 'backend/storage/data_paths.py').read_text(encoding='utf-8')
    if 'def get_data_path' not in src or 'RAILWAY_DATA_DIR' not in src:
        result.set_fail('data_paths_helper', 'get_data_path / RAILWAY_DATA_DIR missing')
        return
    result.set_ok('data_paths_helper')


def _check_trade_execution_disabled(result: PackResult) -> None:
    from backend.telegram.response_format import TRADE_EXECUTION_PERMANENTLY_DISABLED

    if not TRADE_EXECUTION_PERMANENTLY_DISABLED:
        result.set_fail('trade_execution_disabled', 'TRADE_EXECUTION_PERMANENTLY_DISABLED not True')
        return
    worker = (PROJECT_ROOT / 'scripts/run_railway_telegram_worker.py').read_text(encoding='utf-8')
    if 'DISABLE_TRADE_EXECUTION' not in worker:
        result.set_fail('trade_execution_disabled', 'worker missing DISABLE_TRADE_EXECUTION')
        return
    result.set_ok('trade_execution_disabled')


def _check_cron_one_shot(result: PackResult) -> None:
    blocked = ('listen_forever', 'uvicorn.run')
    for rel in CRON_SCRIPTS:
        text = (PROJECT_ROOT / rel).read_text(encoding='utf-8')
        for token in blocked:
            if token in text:
                result.set_fail('cron_one_shot', f'{rel} must not call {token}')
                return
        if 'send_brief' not in text:
            result.set_fail('cron_one_shot', f'{rel} missing send_brief')
            return
    result.set_ok('cron_one_shot')


def _check_no_keys_env_dependency(result: PackResult) -> None:
    scan = (
        'scripts/run_railway_web.py',
        'scripts/run_railway_telegram_worker.py',
        *CRON_SCRIPTS,
    )
    for rel in scan:
        text = (PROJECT_ROOT / rel).read_text(encoding='utf-8')
        if 'keys.env' in text and 'require' in text.lower():
            result.set_fail('no_keys_env_dependency', f'{rel} requires keys.env')
            return
    result.set_ok('no_keys_env_dependency')


def _check_no_secrets_printed(result: PackResult) -> None:
    scan = (
        'scripts/run_railway_web.py',
        'scripts/run_railway_telegram_worker.py',
        *CRON_SCRIPTS,
    )
    for rel in scan:
        text = (PROJECT_ROOT / rel).read_text(encoding='utf-8')
        for pattern in SECRET_PRINT_PATTERNS:
            if pattern.search(text):
                result.set_fail('no_secrets_printed', f'possible secret print in {rel}')
                return
    result.set_ok('no_secrets_printed')


def _run_subprocess(script: str, *extra: str) -> tuple[int, str]:
    path = PROJECT_ROOT / script
    proc = subprocess.run(
        [sys.executable, str(path), *extra],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    return proc.returncode, (proc.stdout or '') + (proc.stderr or '')


def _check_env_validator(result: PackResult) -> None:
    code, output = _run_subprocess('scripts/validate_railway_env.py', '--local-check')
    if code != 0:
        tail = output.strip().splitlines()[-1] if output.strip() else f'exit {code}'
        result.set_fail('env_validator', f'validate_railway_env failed: {tail}')
        return
    if 'RAILWAY_ENV_VALIDATE_OK' not in output:
        result.set_fail('env_validator', 'missing RAILWAY_ENV_VALIDATE_OK')
        return
    result.set_ok('env_validator')


def _check_smoke_local(result: PackResult) -> None:
    code, output = _run_subprocess('scripts/railway_smoke_local.py')
    if code != 0:
        tail = output.strip().splitlines()[-1] if output.strip() else f'exit {code}'
        result.set_fail('smoke_local', f'railway_smoke_local failed: {tail}')
        return
    if 'RAILWAY_SMOKE_LOCAL_OK' not in output:
        result.set_fail('smoke_local', 'missing RAILWAY_SMOKE_LOCAL_OK')
        return
    result.set_ok('smoke_local')


def _check_deployment_doc(result: PackResult) -> None:
    doc = (PROJECT_ROOT / 'docs/RAILWAY_DEPLOYMENT.md').read_text(encoding='utf-8')
    required_tokens = (
        'astraedge-web',
        'astraedge-telegram-worker',
        'run_railway_web.py',
        'run_railway_telegram_worker.py',
        '30 2 * * 1-5',
        '0 11 * * 1-5',
        '0 1 * * 1-5',
        'RAILWAY_DATA_DIR',
        '/app/data',
        'no order execution',
        'DISABLE_TRADE_EXECUTION',
        'TELEGRAM_COMMANDS_ENABLED',
    )
    for token in required_tokens:
        if token not in doc:
            result.set_fail('deployment_doc', f'doc missing token: {token}')
            return
    result.set_ok('deployment_doc')


def run_readiness_pack() -> PackResult:
    result = PackResult()
    _check_required_files(result)
    _check_railway_config(result)
    _check_data_paths_helper(result)
    _check_trade_execution_disabled(result)
    _check_cron_one_shot(result)
    _check_no_keys_env_dependency(result)
    _check_no_secrets_printed(result)
    _check_env_validator(result)
    _check_smoke_local(result)
    _check_deployment_doc(result)
    return result


def print_result(result: PackResult) -> None:
    for name in AUDIT_SECTIONS:
        status = result.sections.get(name, 'fail' if name in result.failures else 'pending')
        if status == 'pending' and name not in result.sections:
            continue
        print(f'[RAILWAY_PACK] {name}={status}')

    if result.failures:
        first = next(iter(result.failures.items()))
        print(f'[RAILWAY_PACK] fail={first[0]}: {first[1]}')

    print(f'[RAILWAY_PACK] ready={result.ready()}')
    if result.ready():
        print(STAGE_MARKER)
        print('RAILWAY_READINESS_PACK_OK')


def main() -> int:
    result = run_readiness_pack()
    print_result(result)
    return 0 if result.ready() else 1


if __name__ == '__main__':
    raise SystemExit(main())
