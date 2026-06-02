#!/usr/bin/env python3
"""
Railway preflight audit — local 90% gate before deployment (Stage 45B4 / 46A).

Usage:
  python scripts/railway_preflight_audit.py

Prints RAILWAY_PREFLIGHT_AUDIT_OK on success.
Does not deploy or mutate Railway.
Marker: RAILWAY_STAGE_45B4_PREFLIGHT_READY
Stage 46A readiness: scripts/validate_railway_readiness_pack.py
"""

from __future__ import annotations

import argparse
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

STAGE_MARKER = 'RAILWAY_STAGE_45B4_PREFLIGHT_READY'

REQUIRED_FILES = (
    'Procfile',
    'railway.json',
    'run_local.py',
    'nixpacks.toml',
    'backend/api/api_server.py',
    'backend/orchestration/master_scheduler.py',
    'backend/telegram/lazy_command_runner.py',
    'backend/telegram/telegram_analysis_bot.py',
    'scripts/run_telegram_analysis_bot.py',
    'scripts/run_railway_web.py',
    'scripts/run_railway_telegram_worker.py',
    'scripts/run_railway_morning_brief.py',
    'scripts/run_railway_market_close.py',
    'scripts/run_railway_overnight_brief.py',
    'scripts/validate_railway_env.py',
    'scripts/railway_smoke_local.py',
    'scripts/validate_railway_readiness_pack.py',
    'backend/storage/data_paths.py',
    'docs/RAILWAY_DEPLOYMENT.md',
    'backend/scheduler/daily_report_pack_job.py',
    'README.md',
    'DEPLOY_CHECKLIST.md',
)

SCHEDULED_BRIEF_SLOTS = (
    (8, 0, 'morning'),
    (16, 30, 'close'),
    (6, 30, 'overnight'),
)

SECRET_PATTERNS = (
    re.compile(r'AIza[0-9A-Za-z\-_]{20,}'),
    re.compile(r'sk-[a-zA-Z0-9]{20,}'),
    re.compile(r'bot[0-9]{8,}:[A-Za-z0-9_-]{20,}'),
)

AUDIT_SECTIONS = (
    'required_files',
    'railway_config',
    'telegram_runner',
    'scheduler',
    'no_secrets_committed',
    'keys_env_ignored',
    'data_strategy',
    'scheduled_jobs',
    'health_endpoint',
    'no_trade_execution',
    'lazy_runners',
)


@dataclass
class AuditResult:
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


def _git_tracked_files() -> list[str]:
    proc = subprocess.run(
        ['git', 'ls-files'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in (proc.stdout or '').splitlines() if line.strip()]


def _check_required_files(result: AuditResult) -> None:
    missing = [rel for rel in REQUIRED_FILES if not (PROJECT_ROOT / rel).is_file()]
    if missing:
        result.set_fail('required_files', f'missing: {", ".join(missing)}')
        return
    result.set_ok('required_files')


def _check_railway_config(result: AuditResult) -> None:
    procfile = (PROJECT_ROOT / 'Procfile').read_text(encoding='utf-8')
    railway = (PROJECT_ROOT / 'railway.json').read_text(encoding='utf-8')
    if 'run_railway_web.py' not in procfile:
        result.set_fail('railway_config', 'Procfile missing run_railway_web.py start command')
        return
    if 'run_railway_web.py' not in railway:
        result.set_fail('railway_config', 'railway.json missing run_railway_web.py startCommand')
        return
    result.set_ok('railway_config')


def _check_telegram_runner(result: AuditResult) -> None:
    runner = PROJECT_ROOT / 'scripts' / 'run_telegram_analysis_bot.py'
    bot = PROJECT_ROOT / 'backend' / 'telegram' / 'telegram_analysis_bot.py'
    if not runner.is_file() or not bot.is_file():
        result.set_fail('telegram_runner', 'telegram runner scripts missing')
        return
    bot_src = bot.read_text(encoding='utf-8')
    if 'handle_analysis_command' not in bot_src:
        result.set_fail('telegram_runner', 'handle_analysis_command missing')
        return
    result.set_ok('telegram_runner')


def _check_scheduler(result: AuditResult) -> None:
    scheduler = PROJECT_ROOT / 'backend' / 'orchestration' / 'master_scheduler.py'
    pack_job = PROJECT_ROOT / 'backend' / 'scheduler' / 'daily_report_pack_job.py'
    if not scheduler.is_file() or not pack_job.is_file():
        result.set_fail('scheduler', 'scheduler modules missing')
        return
    try:
        from backend.orchestration.schedule_registry import get_task_registry

        tasks = get_task_registry().get('tasks') or []
        names = {str(t.get('name') or '').lower() for t in tasks if t.get('name')}
        for job in ('premarket_report_pack', 'postmarket_report_pack', 'research_mode_report_pack'):
            if job not in names:
                result.warnings.append(f'scheduler job not registered: {job}')
    except Exception as exc:
        result.warnings.append(f'schedule registry: {exc}')
    result.set_ok('scheduler')


def _check_no_secrets_committed(result: AuditResult) -> None:
    tracked = _git_tracked_files()
    bad_paths = [p for p in tracked if p.replace('\\', '/').endswith('keys.env')]
    if bad_paths:
        result.set_fail('no_secrets_committed', f'keys.env tracked: {bad_paths[0]}')
        return

    scan_roots = ('backend', 'scripts', 'config', 'frontend')
    for rel in tracked:
        if not rel.startswith(scan_roots):
            continue
        if rel.replace('\\', '/').endswith('.env'):
            result.set_fail('no_secrets_committed', f'tracked env file: {rel}')
            return
        path = PROJECT_ROOT / rel
        if not path.is_file() or path.suffix not in ('.py', '.js', '.ts', '.tsx', '.json', '.md', '.toml'):
            continue
        try:
            text = path.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                result.set_fail('no_secrets_committed', f'possible secret in {rel}')
                return

    result.set_ok('no_secrets_committed')


def _check_keys_env_ignored(result: AuditResult) -> None:
    gitignore = (PROJECT_ROOT / '.gitignore').read_text(encoding='utf-8')
    if 'config/keys.env' not in gitignore:
        result.set_fail('keys_env_ignored', '.gitignore must list config/keys.env')
        return
    result.set_ok('keys_env_ignored')


def _check_data_strategy(result: AuditResult) -> None:
    readme = (PROJECT_ROOT / 'README.md').read_text(encoding='utf-8')
    deploy = (PROJECT_ROOT / 'DEPLOY_CHECKLIST.md').read_text(encoding='utf-8')
    railway_doc = (PROJECT_ROOT / 'docs/RAILWAY_DEPLOYMENT.md').read_text(encoding='utf-8')
    if '/app/data' not in readme and 'Persistent volume' not in readme:
        result.set_fail('data_strategy', 'README missing data volume strategy')
        return
    if '/app/data' not in deploy:
        result.set_fail('data_strategy', 'DEPLOY_CHECKLIST missing /app/data volume')
        return
    if 'RAILWAY_DATA_DIR' not in railway_doc:
        result.set_fail('data_strategy', 'docs/RAILWAY_DEPLOYMENT.md missing RAILWAY_DATA_DIR')
        return
    result.set_ok('data_strategy')


def _check_scheduled_jobs(result: AuditResult) -> None:
    brief_src = (PROJECT_ROOT / 'backend' / 'telegram' / 'telegram_brief_scheduler.py').read_text(
        encoding='utf-8'
    )
    for hour, minute, label in SCHEDULED_BRIEF_SLOTS:
        if f'({hour}, {minute})' not in brief_src and f"'{label}'" not in brief_src:
            result.set_fail('scheduled_jobs', f'missing brief slot {label} {hour:02d}:{minute:02d}')
            return
    result.set_ok('scheduled_jobs')


def _check_health_endpoint(result: AuditResult) -> None:
    api_src = (PROJECT_ROOT / 'backend' / 'api' / 'api_server.py').read_text(encoding='utf-8')
    if '@app.get("/api/health")' not in api_src and "@app.get('/api/health')" not in api_src:
        result.set_fail('health_endpoint', '/api/health route missing')
        return
    result.set_ok('health_endpoint')


def _check_no_trade_execution(result: AuditResult) -> None:
    fmt_src = (PROJECT_ROOT / 'backend' / 'telegram' / 'response_format.py').read_text(encoding='utf-8')
    if 'TRADE_EXECUTION_PERMANENTLY_DISABLED = True' not in fmt_src:
        result.set_fail('no_trade_execution', 'TRADE_EXECUTION_PERMANENTLY_DISABLED not True')
        return
    result.set_ok('no_trade_execution')


def _check_lazy_runners(result: AuditResult) -> None:
    lazy_src = (PROJECT_ROOT / 'backend' / 'telegram' / 'lazy_command_runner.py').read_text(encoding='utf-8')
    bot_src = (PROJECT_ROOT / 'backend' / 'telegram' / 'telegram_analysis_bot.py').read_text(encoding='utf-8')
    required_runners = (
        'run_memory_only',
        'run_broker_only',
        'run_aihub_full_only',
        'run_action_plan_only',
        'run_aihub_brain_full_only',
    )
    for name in required_runners:
        if name not in lazy_src:
            result.set_fail('lazy_runners', f'missing {name}')
            return
    if 'run_local.py' in lazy_src and '_scoped_refresh' not in lazy_src:
        result.set_fail('lazy_runners', 'lazy runner must not invoke full run_local.py')
        return
    if 'lazy_command_runner' not in bot_src:
        result.set_fail('lazy_runners', 'telegram bot must import lazy_command_runner')
        return
    if 'run_without_ai' not in bot_src:
        result.set_fail('lazy_runners', 'telegram bot must route commands through run_without_ai')
        return
    result.set_ok('lazy_runners')


CHECKERS = (
    _check_required_files,
    _check_railway_config,
    _check_telegram_runner,
    _check_scheduler,
    _check_no_secrets_committed,
    _check_keys_env_ignored,
    _check_data_strategy,
    _check_scheduled_jobs,
    _check_health_endpoint,
    _check_no_trade_execution,
    _check_lazy_runners,
)


def run_railway_preflight_audit(*, stop_on_first_fail: bool = True) -> AuditResult:
    result = AuditResult()
    for checker in CHECKERS:
        checker(result)
        if stop_on_first_fail and result.failures:
            break
    return result


def print_audit(result: AuditResult) -> None:
    for name in AUDIT_SECTIONS:
        status = result.sections.get(name, 'fail' if name in result.failures else 'pending')
        if status == 'pending' and name not in result.sections:
            continue
        print(f'[RAILWAY_PREFLIGHT] {name}={status}')

    for warning in result.warnings:
        print(f'[RAILWAY_PREFLIGHT] warn={warning}')

    if result.failures:
        first = next(iter(result.failures.items()))
        print(f'[RAILWAY_PREFLIGHT] fail={first[0]}: {first[1]}')

    print(f'[RAILWAY_PREFLIGHT] ready={result.ready()}')
    if result.ready():
        print(STAGE_MARKER)
        print('RAILWAY_PREFLIGHT_AUDIT_OK')


def main() -> int:
    parser = argparse.ArgumentParser(description='Railway preflight audit (no deployment).')
    parser.add_argument(
        '--continue-on-fail',
        action='store_true',
        help='Run all checks even after first failure',
    )
    args = parser.parse_args()

    result = run_railway_preflight_audit(stop_on_first_fail=not args.continue_on_fail)
    print_audit(result)
    return 0 if result.ready() else 1


if __name__ == '__main__':
    raise SystemExit(main())
