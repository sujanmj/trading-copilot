#!/usr/bin/env python3
"""
Railway first-deploy pack validator (Stage 46B).

Usage:
  python scripts/validate_railway_first_deploy_pack.py

Prints RAILWAY_FIRST_DEPLOY_PACK_OK on success.
Marker: RAILWAY_STAGE_46B_FIRST_DEPLOY_PACK
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

STAGE_MARKER = 'RAILWAY_STAGE_46B_FIRST_DEPLOY_PACK'
DOC_PATH = 'docs/RAILWAY_FIRST_DEPLOY.md'

REQUIRED_FILES = (
    DOC_PATH,
    'scripts/railway_post_deploy_smoke.py',
    'scripts/check_no_secrets_before_push.py',
    'scripts/validate_railway_first_deploy_pack.py',
)

AUDIT_SECTIONS = (
    'required_files',
    'first_deploy_doc',
    'service_names',
    'cron_commands',
    'env_vars',
    'volume_path',
    'rollback',
    'post_deploy_smoke_script',
    'no_secrets_script',
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


def _run_subprocess(script: str, *extra: str) -> tuple[int, str]:
    path = PROJECT_ROOT / script
    proc = subprocess.run(
        [sys.executable, str(path), *extra],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc.returncode, (proc.stdout or '') + (proc.stderr or '')


def _check_required_files(result: PackResult) -> None:
    missing = [rel for rel in REQUIRED_FILES if not (PROJECT_ROOT / rel).is_file()]
    if missing:
        result.set_fail('required_files', f'missing: {", ".join(missing)}')
        return
    result.set_ok('required_files')


def _doc_text() -> str:
    return (PROJECT_ROOT / DOC_PATH).read_text(encoding='utf-8')


def _check_first_deploy_doc(result: PackResult) -> None:
    doc = _doc_text()
    if STAGE_MARKER not in doc:
        result.set_fail('first_deploy_doc', f'doc missing marker {STAGE_MARKER}')
        return
    for token in (
        'Pre-push local checks',
        'Git push checklist',
        'Post-deploy checks',
        'Rollback steps',
        'RAILWAY_POST_DEPLOY_SMOKE_OK',
        'NO_SECRETS_BEFORE_PUSH_OK',
    ):
        if token not in doc:
            result.set_fail('first_deploy_doc', f'doc missing section/token: {token}')
            return
    result.set_ok('first_deploy_doc')


def _check_service_names(result: PackResult) -> None:
    doc = _doc_text()
    for name in (
        'astraedge-web',
        'astraedge-telegram-worker',
        'astraedge-morning-brief',
        'astraedge-market-close',
        'astraedge-overnight-brief',
    ):
        if name not in doc:
            result.set_fail('service_names', f'doc missing service: {name}')
            return
    result.set_ok('service_names')


def _check_cron_commands(result: PackResult) -> None:
    doc = _doc_text()
    for token in (
        '30 2 * * 1-5',
        '0 11 * * 1-5',
        '0 1 * * 1-5',
        'run_railway_morning_brief.py',
        'run_railway_market_close.py',
        'run_railway_overnight_brief.py',
        'run_railway_web.py',
        'run_railway_telegram_worker.py',
    ):
        if token not in doc:
            result.set_fail('cron_commands', f'doc missing cron token: {token}')
            return
    result.set_ok('cron_commands')


def _check_env_vars(result: PackResult) -> None:
    doc = _doc_text()
    for token in (
        'APP_MODE=railway',
        'LOCAL_DEV_MODE=0',
        'LOCAL_ONLY=0',
        'RAILWAY_DATA_DIR=/data',
        'DISABLE_TRADE_EXECUTION=1',
        'TELEGRAM_TRADE_COMMANDS_ENABLED=0',
        'TELEGRAM_COMMANDS_ENABLED=1',
        'TELEGRAM_BOT_TOKEN',
        'TELEGRAM_CHAT_ID',
        'ANTHROPIC_API_KEY',
        'GOOGLE_API_KEY_1',
        'GROQ_API_KEY_1',
        'ANGEL_API_KEY',
    ):
        if token not in doc:
            result.set_fail('env_vars', f'doc missing env token: {token}')
            return
    result.set_ok('env_vars')


def _check_volume_path(result: PackResult) -> None:
    doc = _doc_text()
    for token in ('RAILWAY_DATA_DIR=/data', '/data', 'persistent Railway volume'):
        if token not in doc:
            result.set_fail('volume_path', f'doc missing volume token: {token}')
            return
    result.set_ok('volume_path')


def _check_rollback(result: PackResult) -> None:
    doc = _doc_text()
    for token in (
        'Rollback',
        'disable Telegram worker',
        'disable cron',
        'keep web',
        'recovery/',
    ):
        if token.lower() not in doc.lower():
            result.set_fail('rollback', f'doc missing rollback token: {token}')
            return
    result.set_ok('rollback')


def _check_post_deploy_smoke_script(result: PackResult) -> None:
    src = (PROJECT_ROOT / 'scripts/railway_post_deploy_smoke.py').read_text(encoding='utf-8')
    for token in (
        '--base-url',
        '/api/health',
        '/api/debug/final-confidence',
        '/api/debug/daily-report-pack',
        '/api/debug/stock-decision',
        '/api/debug/aihub-tab/brain',
        'RAILWAY_POST_DEPLOY_SMOKE_OK',
    ):
        if token not in src:
            result.set_fail('post_deploy_smoke_script', f'smoke script missing: {token}')
            return
    result.set_ok('post_deploy_smoke_script')


def _check_no_secrets_script(result: PackResult) -> None:
    code, output = _run_subprocess('scripts/check_no_secrets_before_push.py')
    if code != 0:
        tail = output.strip().splitlines()[-1] if output.strip() else f'exit {code}'
        result.set_fail('no_secrets_script', f'check_no_secrets_before_push failed: {tail}')
        return
    if 'NO_SECRETS_BEFORE_PUSH_OK' not in output:
        result.set_fail('no_secrets_script', 'missing NO_SECRETS_BEFORE_PUSH_OK')
        return
    result.set_ok('no_secrets_script')


def run_first_deploy_pack() -> PackResult:
    result = PackResult()
    _check_required_files(result)
    _check_first_deploy_doc(result)
    _check_service_names(result)
    _check_cron_commands(result)
    _check_env_vars(result)
    _check_volume_path(result)
    _check_rollback(result)
    _check_post_deploy_smoke_script(result)
    _check_no_secrets_script(result)
    return result


def print_result(result: PackResult) -> None:
    for name in AUDIT_SECTIONS:
        status = result.sections.get(name, 'fail' if name in result.failures else 'pending')
        if status == 'pending' and name not in result.sections:
            continue
        print(f'[RAILWAY_FIRST_DEPLOY] {name}={status}')

    if result.failures:
        first = next(iter(result.failures.items()))
        print(f'[RAILWAY_FIRST_DEPLOY] fail={first[0]}: {first[1]}')

    print(f'[RAILWAY_FIRST_DEPLOY] ready={result.ready()}')
    if result.ready():
        print(STAGE_MARKER)
        print('RAILWAY_FIRST_DEPLOY_PACK_OK')


def main() -> int:
    result = run_first_deploy_pack()
    print_result(result)
    return 0 if result.ready() else 1


if __name__ == '__main__':
    raise SystemExit(main())
