#!/usr/bin/env python3
"""
Local daily startup readiness guard — safety, DBs, validators, router, scheduler, API.

Usage:
  python scripts/daily_startup_check.py
  python scripts/daily_startup_check.py --skip-api --strict
  python scripts/daily_startup_check.py --json --make-backup

Prints [DAILY_CHECK] lines and DAILY_STARTUP_READY / _WITH_WARNINGS / _NOT_READY.
Does not place trades, send Telegram, or write outcomes.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

Status = Literal['ok', 'warn', 'fail']
CheckStatus = Literal['ok', 'warn', 'fail', 'skipped']

API_BASE = 'http://127.0.0.1:8080'
RECOVERY_DIR = PROJECT_ROOT / 'recovery'
CHECKPOINT_PREFIX = 'clean_checkpoint_'

CANONICAL_DB = PROJECT_ROOT / 'data' / 'canonical_market_memory.db'
HISTORICAL_DB = PROJECT_ROOT / 'data' / 'historical_market_memory.db'
TRADING_DB = PROJECT_ROOT / 'data' / 'trading_history.db'
ENRICHED_PATH = PROJECT_ROOT / 'data' / 'latest_market_data_memory_enriched.json'
FINAL_REPORT_PATH = PROJECT_ROOT / 'data' / 'final_confidence_report.json'

SCHEDULER_BUCKETS = {
    'premarket': ('premarket', 'pre_market', 'overnight_brief', 'market_open'),
    'midmarket': ('midday', 'intraday', 'midmarket'),
    'postmarket': ('market_close', 'postmarket', 'post_market'),
    'eod': ('eod_lifecycle', 'eod'),
}

REPORT_PACK_SCHEDULER_JOBS = (
    'premarket_report_pack',
    'postmarket_report_pack',
    'research_mode_report_pack',
)


@dataclass
class DailyCheckResult:
    sections: dict[str, CheckStatus] = field(default_factory=dict)
    messages: dict[str, list[str]] = field(default_factory=dict)
    strict: bool = False

    def set_section(self, name: str, status: CheckStatus, *msgs: str) -> None:
        self.sections[name] = status
        if msgs:
            self.messages.setdefault(name, []).extend(msgs)

    def any_fail(self) -> bool:
        return any(s == 'fail' for s in self.sections.values())

    def any_warn(self) -> bool:
        return any(s == 'warn' for s in self.sections.values())

    def ready(self) -> bool:
        if self.any_fail():
            return False
        if self.strict and self.any_warn():
            return False
        return True

    def verdict_token(self) -> str:
        if self.any_fail() or (self.strict and self.any_warn()):
            return 'DAILY_STARTUP_NOT_READY'
        if self.any_warn():
            return 'DAILY_STARTUP_READY_WITH_WARNINGS'
        return 'DAILY_STARTUP_READY'


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, '').strip() in ('1', 'true', 'True', 'yes', 'YES')


def _apply_local_defaults() -> None:
    defaults = {
        'LOCAL_DEV_MODE': '1',
        'LOCAL_ONLY': '1',
        'DISABLE_TELEGRAM': '1',
        'DISABLE_TELEGRAM_LISTENER': '1',
        'DISABLE_TELEGRAM_SENDS': '1',
    }
    for key, val in defaults.items():
        os.environ.setdefault(key, val)


def _load_api_key() -> str:
    key = os.environ.get('API_KEY', '').strip()
    if key:
        return key
    try:
        from backend.utils.config import get_env, load_env

        load_env()
        return get_env('API_KEY')
    except Exception:
        return ''


def _fetch_json(path: str, api_key: str = '') -> tuple[dict | None, str | None]:
    url = API_BASE.rstrip('/') + path
    headers = {'Accept': 'application/json'}
    if api_key:
        headers['X-API-Key'] = api_key
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
            if not isinstance(payload, dict):
                return None, 'invalid JSON object'
            return payload, None
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode('utf-8', errors='replace')[:200]
        except Exception:
            detail = str(exc)
        return None, f'HTTP {exc.code}: {detail}'
    except urllib.error.URLError as exc:
        reason = getattr(exc, 'reason', exc)
        return None, f'server not reachable ({reason})'
    except json.JSONDecodeError as exc:
        return None, f'invalid JSON: {exc}'
    except Exception as exc:
        return None, str(exc)


def _api_reachable(api_key: str) -> bool:
    payload, _ = _fetch_json('/api/runtime/snapshot', api_key)
    return payload is not None


def _run_validator_script(script_name: str) -> tuple[bool, str]:
    script = PROJECT_ROOT / 'scripts' / script_name
    if not script.is_file():
        return False, f'missing script: {script_name}'
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    combined = (proc.stdout or '') + (proc.stderr or '')
    if proc.returncode != 0:
        tail = combined.strip().splitlines()[-1] if combined.strip() else f'exit {proc.returncode}'
        return False, tail
    return True, combined.strip().splitlines()[-1] if combined.strip() else 'ok'


def _check_local_safety(result: DailyCheckResult) -> None:
    _apply_local_defaults()
    msgs: list[str] = []
    status: CheckStatus = 'ok'

    local_ok = _env_truthy('LOCAL_ONLY') or _env_truthy('LOCAL_DEV_MODE')
    if not local_ok:
        status = 'fail'
        msgs.append('LOCAL_ONLY and LOCAL_DEV_MODE both unset')

    telegram_flags = (
        'DISABLE_TELEGRAM',
        'DISABLE_TELEGRAM_LISTENER',
        'DISABLE_TELEGRAM_SENDS',
    )
    for flag in telegram_flags:
        if not _env_truthy(flag):
            status = 'fail'
            msgs.append(f'{flag} != 1')

    try:
        from backend.utils import config as cfg
        from backend.utils import telegram_guard as tg

        if not (cfg.LOCAL_ONLY or cfg.IS_LOCAL_DEV):
            status = 'fail'
            msgs.append('config LOCAL_ONLY/IS_LOCAL_DEV not set')
        if tg.is_telegram_send_enabled() or tg.is_telegram_listener_enabled():
            status = 'fail'
            msgs.append('telegram_guard reports Telegram enabled')
    except Exception as exc:
        if status == 'ok':
            status = 'warn'
        msgs.append(f'config import: {exc}')

    result.set_section('local_safety', status, *msgs)


def _db_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _check_market_memory_db(result: DailyCheckResult) -> None:
    msgs: list[str] = []
    status: CheckStatus = 'ok'

    if not CANONICAL_DB.is_file():
        result.set_section('market_memory', 'fail', f'missing {CANONICAL_DB.name}')
        return

    if not TRADING_DB.is_file():
        status = 'fail'
        msgs.append(f'missing {TRADING_DB.name}')

    try:
        conn = sqlite3.connect(f'file:{CANONICAL_DB}?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        try:
            for table in ('predictions', 'broker_predictions', 'outcomes', 'market_context_snapshots'):
                if not _db_table_exists(conn, table):
                    status = 'fail'
                    msgs.append(f'missing table: {table}')

            legacy_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM predictions WHERE prediction_id LIKE 'legacy:%'",
                ).fetchone()[0]
            )
            if legacy_count > 0:
                status = 'warn' if status == 'ok' else status
                msgs.append(f'legacy_prediction_ids={legacy_count}')

            pred_count = int(conn.execute('SELECT COUNT(*) FROM predictions').fetchone()[0])
            if pred_count <= 0:
                status = 'warn' if status == 'ok' else status
                msgs.append('predictions=0')
        finally:
            conn.close()
    except sqlite3.Error as exc:
        status = 'fail'
        msgs.append(str(exc))

    result.set_section('market_memory', status, *msgs)


def _check_historical_memory_db(result: DailyCheckResult) -> None:
    msgs: list[str] = []
    status: CheckStatus = 'ok'

    if not HISTORICAL_DB.is_file():
        result.set_section('historical_memory', 'fail', f'missing {HISTORICAL_DB.name}')
        return

    try:
        conn = sqlite3.connect(f'file:{HISTORICAL_DB}?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        try:
            for table in ('historical_prices', 'historical_outcome_replay', 'historical_source_performance'):
                if not _db_table_exists(conn, table):
                    status = 'fail'
                    msgs.append(f'missing table: {table}')
        finally:
            conn.close()
    except sqlite3.Error as exc:
        status = 'fail'
        msgs.append(str(exc))

    result.set_section('historical_memory', status, *msgs)


def _check_price_coverage(result: DailyCheckResult) -> None:
    msgs: list[str] = []
    status: CheckStatus = 'ok'

    if not ENRICHED_PATH.is_file():
        result.set_section('price_coverage', 'warn', 'enriched price file missing')
        return

    try:
        from scripts.validate_enriched_price_file import count_fake_prices

        data = json.loads(ENRICHED_PATH.read_text(encoding='utf-8'))
        prices = data.get('prices') if isinstance(data, dict) else None
        if not isinstance(prices, dict):
            result.set_section('price_coverage', 'fail', 'prices dict missing')
            return

        symbol_count = len(prices)
        fake_count = count_fake_prices(prices)
        msgs.append(f'symbols={symbol_count} fake_prices={fake_count}')

        if fake_count > 0:
            status = 'fail'
            msgs.append('fake prices detected')
        elif symbol_count <= 15:
            status = 'warn'
            msgs.append('low symbol coverage')
    except Exception as exc:
        status = 'fail'
        msgs.append(str(exc))

    result.set_section('price_coverage', status, *msgs)


def _validate_final_report_file() -> tuple[bool, str]:
    if not FINAL_REPORT_PATH.is_file():
        return False, 'report file missing'
    try:
        report = json.loads(FINAL_REPORT_PATH.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        return False, f'invalid JSON: {exc}'
    if report.get('ok') is not True:
        return False, 'report ok != true'
    if report.get('shadow_mode') is not True:
        return False, 'shadow_mode != true'
    summary = report.get('summary')
    if not isinstance(summary, dict):
        return False, 'summary missing'
    return True, 'report valid'


def _check_final_confidence(result: DailyCheckResult) -> None:
    ok, detail = _validate_final_report_file()
    if ok:
        result.set_section('final_confidence', 'ok', detail)
        return

    try:
        from backend.analytics.final_confidence_fusion import build_final_confidence_report

        report = build_final_confidence_report(limit=30)
        if report.get('ok') is True:
            result.set_section(
                'final_confidence',
                'warn',
                f'{detail}; can_generate=True checked={report.get("checked", 0)}',
            )
        else:
            result.set_section(
                'final_confidence',
                'fail',
                report.get('error') or detail,
            )
    except Exception as exc:
        result.set_section('final_confidence', 'fail', f'{detail}; generate_error={exc}')


def _check_market_router(result: DailyCheckResult) -> None:
    msgs: list[str] = []
    status: CheckStatus = 'ok'

    try:
        from backend.analytics.market_calendar_router import (
            MODE_INDIA,
            MODE_INDIA_POSTMARKET,
            MODE_INDIA_PREMARKET,
            MODE_RESEARCH,
            MODE_USA,
            MODE_USA_POSTMARKET,
            MODE_USA_PREMARKET,
            SESSION_CLOSED,
            SESSION_REGULAR,
            get_market_router_payload,
        )

        payload = get_market_router_payload()
        active_mode = str(payload.get('active_mode') or '')
        india_session = str(payload.get('india_session') or '')
        usa_session = str(payload.get('usa_session') or '')

        msgs.append(f'active_mode={active_mode}')
        msgs.append(f'india_session={india_session}')
        msgs.append(f'usa_session={usa_session}')

        india_modes = {MODE_INDIA, MODE_INDIA_PREMARKET, MODE_INDIA_POSTMARKET}
        usa_modes = {MODE_USA, MODE_USA_PREMARKET, MODE_USA_POSTMARKET}

        if india_session == SESSION_REGULAR and active_mode not in india_modes:
            status = 'warn'
            msgs.append('India regular session but active_mode is not India-family')
        elif usa_session == SESSION_REGULAR and india_session == SESSION_CLOSED and active_mode not in usa_modes:
            status = 'warn'
            msgs.append('USA regular session but active_mode is not USA-family')
        elif (
            india_session == SESSION_CLOSED
            and usa_session == SESSION_CLOSED
            and active_mode != MODE_RESEARCH
        ):
            status = 'warn'
            msgs.append(f'both markets closed but active_mode={active_mode}')

        router_warnings = payload.get('warnings') or []
        if router_warnings and status == 'ok':
            msgs.append(f'router_warnings={len(router_warnings)} (informational)')
    except Exception as exc:
        status = 'fail'
        msgs.append(str(exc))

    result.set_section('market_router', status, *msgs)


def _scheduler_job_names() -> list[str]:
    try:
        import backend.orchestration.master_scheduler  # noqa: F401 — register IST jobs
        from backend.orchestration.schedule_registry import get_task_registry

        registry = get_task_registry()
        tasks = registry.get('tasks') or []
        return [str(t.get('name') or '') for t in tasks if t.get('name')]
    except Exception:
        return []


def _check_scheduler(result: DailyCheckResult) -> None:
    msgs: list[str] = []
    status: CheckStatus = 'ok'

    names = _scheduler_job_names()
    if not names:
        result.set_section('scheduler', 'warn', 'no registered scheduler jobs found')
        return

    lowered = {n.lower() for n in names}
    missing_buckets: list[str] = []
    for bucket, keywords in SCHEDULER_BUCKETS.items():
        if not any(any(kw in name for name in lowered) for kw in keywords):
            missing_buckets.append(bucket)

    msgs.append(f'registered_jobs={len(names)}')
    if missing_buckets:
        status = 'warn'
        msgs.append(f'missing_buckets={",".join(missing_buckets)}')

    sample = ', '.join(sorted(names)[:8])
    if len(names) > 8:
        sample += ', ...'
    msgs.append(f'sample={sample}')

    result.set_section('scheduler', status, *msgs)


def _check_report_pack_scheduler(result: DailyCheckResult) -> None:
    msgs: list[str] = []
    status: CheckStatus = 'ok'

    names = _scheduler_job_names()
    lowered = {n.lower() for n in names}
    missing = [job for job in REPORT_PACK_SCHEDULER_JOBS if job not in lowered]
    if missing:
        status = 'warn'
        msgs.append(f'missing_jobs={",".join(missing)}')
    else:
        msgs.append('jobs=premarket,postmarket,research')

    try:
        job_module = PROJECT_ROOT / 'backend' / 'scheduler' / 'daily_report_pack_job.py'
        if not job_module.is_file():
            status = 'warn'
            msgs.append('missing backend/scheduler/daily_report_pack_job.py')
    except Exception as exc:
        status = 'warn'
        msgs.append(str(exc))

    result.set_section('report_pack_scheduler', status, *msgs)


def _check_api(result: DailyCheckResult, *, skip_api: bool) -> None:
    if skip_api:
        result.set_section('api', 'skipped', 'skipped via --skip-api')
        return

    api_key = _load_api_key()
    if not _api_reachable(api_key):
        result.set_section(
            'api',
            'warn',
            'API not running',
            'start with: python run_local.py',
        )
        return

    endpoints = (
        '/api/runtime/snapshot',
        '/api/debug/market-router',
        '/api/debug/final-confidence',
    )
    failures: list[str] = []
    for path in endpoints:
        payload, err = _fetch_json(path, api_key)
        if payload is None:
            failures.append(f'{path}: {err}')
            continue
        if payload.get('ok') is not True and path != '/api/runtime/snapshot':
            failures.append(f'{path}: ok != true')

    if failures:
        result.set_section('api', 'warn', *failures)
    else:
        result.set_section('api', 'ok', f'endpoints_ok={len(endpoints)}')


def _list_checkpoint_zips() -> list[Path]:
    if not RECOVERY_DIR.is_dir():
        return []
    return sorted(
        (p for p in RECOVERY_DIR.glob(f'{CHECKPOINT_PREFIX}*.zip') if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _check_backup(result: DailyCheckResult) -> None:
    zips = _list_checkpoint_zips()
    if zips:
        latest = zips[0]
        result.set_section('backup', 'ok', f'latest={latest.name}')
    else:
        result.set_section(
            'backup',
            'warn',
            'no clean_checkpoint zip in recovery/',
            'run: python scripts/create_clean_checkpoint.py',
        )


def _make_backup() -> tuple[bool, str]:
    script = PROJECT_ROOT / 'scripts' / 'create_clean_checkpoint.py'
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or '').strip().splitlines()
        return False, tail[-1] if tail else f'exit {proc.returncode}'
    return True, 'CLEAN_CHECKPOINT_OK'


def run_daily_startup_check(
    *,
    skip_api: bool = False,
    strict: bool = False,
    make_backup: bool = False,
) -> DailyCheckResult:
    result = DailyCheckResult(strict=strict)

    _check_local_safety(result)
    _check_market_memory_db(result)
    _check_historical_memory_db(result)
    _check_price_coverage(result)
    _check_final_confidence(result)
    _check_market_router(result)
    _check_scheduler(result)
    _check_report_pack_scheduler(result)
    _check_api(result, skip_api=skip_api)
    _check_backup(result)

    if make_backup:
        ok, detail = _make_backup()
        if ok:
            result.set_section('backup', 'ok', detail)
        else:
            result.set_section('backup', 'warn', f'backup_failed: {detail}')

    return result


def _print_human(result: DailyCheckResult) -> None:
    order = (
        'local_safety',
        'market_memory',
        'historical_memory',
        'price_coverage',
        'final_confidence',
        'market_router',
        'scheduler',
        'report_pack_scheduler',
        'api',
        'backup',
    )
    for name in order:
        status = result.sections.get(name, 'warn')
        print(f'[DAILY_CHECK] {name}={status}')
        for msg in result.messages.get(name, []):
            print(f'[DAILY_CHECK] {name}_detail={msg}')
    print(f'[DAILY_CHECK] ready={result.ready()}')
    print(result.verdict_token())


def _print_json(result: DailyCheckResult) -> None:
    payload = {
        'sections': result.sections,
        'messages': result.messages,
        'ready': result.ready(),
        'verdict': result.verdict_token(),
        'strict': result.strict,
    }
    print(json.dumps(payload, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description='Local daily startup readiness guard.')
    parser.add_argument('--skip-api', action='store_true', help='Skip live API endpoint checks')
    parser.add_argument('--strict', action='store_true', help='Treat warnings as not ready')
    parser.add_argument('--json', action='store_true', help='Print JSON summary')
    parser.add_argument('--make-backup', action='store_true', help='Create clean checkpoint if possible')
    args = parser.parse_args()

    result = run_daily_startup_check(
        skip_api=args.skip_api,
        strict=args.strict,
        make_backup=args.make_backup,
    )

    if args.json:
        _print_json(result)
    else:
        _print_human(result)

    return 0 if result.ready() else 1


if __name__ == '__main__':
    raise SystemExit(main())
