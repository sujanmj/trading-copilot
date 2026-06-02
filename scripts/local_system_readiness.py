#!/usr/bin/env python3
"""
Master local system readiness gate (Stage 41).

Usage:
  python scripts/local_system_readiness.py

Prints [LOCAL_READY] lines and LOCAL_SYSTEM_READY on success.
Does not place trades, send Telegram, mutate Railway, or print keys.env contents.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

CANONICAL_DB = PROJECT_ROOT / 'data' / 'canonical_market_memory.db'
HISTORICAL_DB = PROJECT_ROOT / 'data' / 'historical_market_memory.db'
ENRICHED_PATH = PROJECT_ROOT / 'data' / 'latest_market_data_memory_enriched.json'
KEYS_ENV = PROJECT_ROOT / 'config' / 'keys.env'
FINAL_REPORT_PATH = PROJECT_ROOT / 'data' / 'final_confidence_report.json'
TOMORROW_WATCHLIST_PATH = PROJECT_ROOT / 'data' / 'tomorrow_watchlist_report.json'
DAILY_PACK_PATH = PROJECT_ROOT / 'data' / 'daily_report_pack_latest.json'
CALIBRATION_PATH = PROJECT_ROOT / 'data' / 'confidence_calibration_report.json'
EXTERNAL_EVIDENCE_PATH = PROJECT_ROOT / 'data' / 'external_evidence_latest.json'
BROKER_WRITE_REVIEW_PATH = PROJECT_ROOT / 'data' / 'broker_db_write_review.json'

REPORT_PACK_SCHEDULER_JOBS = (
    'premarket_report_pack',
    'postmarket_report_pack',
    'research_mode_report_pack',
)

COMPACT_ORDER = (
    'local_safety',
    'market_memory',
    'historical_memory',
    'broker_db_audit',
    'final_confidence',
    'tomorrow_watchlist',
    'daily_pack',
    'external_evidence',
    'scheduler',
    'frontend',
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
    return os.environ.get(name, '').strip() in ('1', 'true', 'True', 'yes', 'YES')


def _apply_local_defaults() -> None:
    for key, val in {
        'LOCAL_DEV_MODE': '1',
        'LOCAL_ONLY': '1',
        'DISABLE_TELEGRAM': '1',
        'DISABLE_TELEGRAM_LISTENER': '1',
        'DISABLE_TELEGRAM_SENDS': '1',
        'DISABLE_RAILWAY_API': '1',
    }.items():
        os.environ.setdefault(key, val)


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


def _check_telegram_send_only(result: ReadinessResult) -> None:
    try:
        from backend.notifications.local_telegram_notifier import telegram_notifications_enabled

        status = telegram_notifications_enabled()
        if status.get('enabled'):
            if not status.get('listener_disabled'):
                result.sections['telegram_send_only'] = 'warn'
            else:
                result.sections['telegram_send_only'] = 'ok'
            return
        if status.get('local_notifications_flag') or status.get('sends_allowed_flag'):
            result.sections['telegram_send_only'] = 'warn'
            return
        result.sections['telegram_send_only'] = 'disabled'
    except Exception:
        result.sections['telegram_send_only'] = 'warn'


def _check_local_safety(result: ReadinessResult) -> None:
    _apply_local_defaults()
    if not KEYS_ENV.is_file():
        result.set_fail('local_safety', f'keys.env missing at {KEYS_ENV.relative_to(PROJECT_ROOT)}')
        return

    if not (_env_truthy('LOCAL_ONLY') or _env_truthy('LOCAL_DEV_MODE')):
        result.set_fail('local_safety', 'LOCAL_ONLY and LOCAL_DEV_MODE both unset')
        return

    for flag in ('DISABLE_TELEGRAM', 'DISABLE_TELEGRAM_LISTENER', 'DISABLE_TELEGRAM_SENDS'):
        if not _env_truthy(flag):
            result.set_fail('local_safety', f'{flag} != 1')
            return

    run_local = PROJECT_ROOT / 'run_local.py'
    if not run_local.is_file():
        result.set_fail('local_safety', 'run_local.py missing')
        return
    run_local_src = run_local.read_text(encoding='utf-8')
    if 'DISABLE_RAILWAY_API' not in run_local_src or 'LOCAL_ONLY' not in run_local_src:
        result.set_fail('local_safety', 'run_local.py missing LOCAL_ONLY / DISABLE_RAILWAY_API defaults')
        return

    if 'DISABLE_RAILWAY_API' not in (PROJECT_ROOT / 'scripts' / 'validate_local_mode.py').read_text(encoding='utf-8'):
        result.set_fail('local_safety', 'validate_local_mode.py missing DISABLE_RAILWAY_API guard')
        return

    try:
        from backend.utils import config as cfg
        from backend.utils import telegram_guard as tg

        if not (cfg.LOCAL_ONLY or cfg.IS_LOCAL_DEV):
            result.set_fail('local_safety', 'config LOCAL_ONLY/IS_LOCAL_DEV not set')
            return
        if tg.is_telegram_send_enabled() or tg.is_telegram_listener_enabled():
            result.set_fail('local_safety', 'telegram_guard reports Telegram enabled')
            return
        if cfg.IS_RAILWAY:
            result.set_fail('local_safety', 'IS_RAILWAY unexpectedly True')
            return
    except Exception as exc:
        result.set_fail('local_safety', f'config import: {exc}')
        return

    result.set_ok('local_safety')


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

    try:
        from scripts.validate_enriched_price_file import count_fake_prices

        data = json.loads(ENRICHED_PATH.read_text(encoding='utf-8'))
        prices = data.get('prices') if isinstance(data, dict) else None
        if not isinstance(prices, dict):
            result.set_fail('market_memory', 'prices dict missing in enriched file')
            return
        fake_count = count_fake_prices(prices)
        if fake_count > 0:
            result.set_fail('market_memory', f'fake_prices={fake_count}')
            return
    except Exception as exc:
        result.set_fail('market_memory', str(exc))
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


def _check_broker_db_audit(result: ReadinessResult) -> None:
    try:
        from backend.collectors.broker_app_collector import load_collector_cache
        from backend.collectors.broker_db_audit import audit_all_broker_predictions

        cache = load_collector_cache()
        fake_predictions = int(cache.get('fake_predictions') or 0)
        if fake_predictions != 0:
            result.set_fail('broker_db_audit', f'fake_predictions={fake_predictions}')
            return

        audit = audit_all_broker_predictions()
        if audit.get('ok') is not True:
            result.set_fail('broker_db_audit', 'audit failed')
            return

        counts = audit.get('counts') or {}
        unsafe = int(counts.get('unsafe') or 0)
        if unsafe > 0:
            result.set_fail('broker_db_audit', f'unsafe_broker_rows={unsafe}')
            return

        ok, detail = _run_validator_script(
            'audit_broker_predictions_db.py',
            success_token='BROKER_PREDICTIONS_DB_AUDIT_OK',
        )
        if not ok:
            result.set_fail('broker_db_audit', detail)
            return
    except Exception as exc:
        result.set_fail('broker_db_audit', str(exc))
        return

    result.set_ok('broker_db_audit')


def _validate_report_script(script_name: str, success_token: str) -> tuple[bool, str]:
    return _run_validator_script(script_name, success_token=success_token)


def _check_intelligence_for_final_confidence() -> tuple[bool, str]:
    try:
        from backend.analytics.market_calendar_router import get_market_router_payload

        payload = get_market_router_payload()
        if payload.get('ok') is False:
            return False, f'market_router: {payload.get("error") or "ok=false"}'
    except Exception as exc:
        return False, f'market_router: {exc}'

    try:
        from backend.analytics.source_freshness import get_source_freshness_report

        freshness = get_source_freshness_report()
        if freshness.get('ok') is not True:
            return False, f'source_freshness: {freshness.get("error") or "ok != true"}'
    except Exception as exc:
        return False, f'source_freshness: {exc}'

    try:
        ok, detail = _run_validator_script(
            'validate_simulation_performance_adapter.py',
            success_token='SIMULATION_PERFORMANCE_ADAPTER_OK',
        )
        if not ok:
            return False, f'simulation_adapter: {detail}'
    except Exception as exc:
        return False, f'simulation_adapter: {exc}'

    ok, detail = _validate_report_script(
        'validate_confidence_calibration_report.py',
        success_token='CONFIDENCE_CALIBRATION_VALIDATE_OK',
    )
    if not ok:
        return False, f'calibration_report: {detail}'

    if not FINAL_REPORT_PATH.is_file():
        return False, 'final_confidence_report.json missing'

    try:
        report = json.loads(FINAL_REPORT_PATH.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        return False, f'final_confidence_report invalid JSON: {exc}'

    active_mode = str(report.get('active_mode') or report.get('market_mode') or '').upper()
    if not active_mode:
        try:
            from backend.analytics.market_calendar_router import get_market_router_payload

            active_mode = str(get_market_router_payload().get('active_mode') or '').upper()
        except Exception:
            active_mode = ''

    if active_mode == 'RESEARCH_MODE':
        summary = report.get('summary') or {}
        buy_count = int(summary.get('buy_candidate') or 0)
        if buy_count > 0:
            return False, f'RESEARCH_MODE buy_candidate={buy_count}'

        for row in report.get('rows') or []:
            if isinstance(row, dict) and row.get('decision') == 'BUY_CANDIDATE':
                return False, 'RESEARCH_MODE must not contain BUY_CANDIDATE rows'

    return True, 'ok'


def _check_final_confidence(result: ReadinessResult) -> None:
    ok, detail = _validate_report_script(
        'validate_final_confidence_report.py',
        success_token='FINAL_CONFIDENCE_REPORT_VALIDATE_OK',
    )
    if not ok:
        result.set_fail('final_confidence', detail)
        return

    intel_ok, intel_detail = _check_intelligence_for_final_confidence()
    if not intel_ok:
        result.set_fail('final_confidence', intel_detail)
        return

    result.set_ok('final_confidence')


def _check_tomorrow_watchlist(result: ReadinessResult) -> None:
    ok, detail = _validate_report_script(
        'validate_tomorrow_watchlist.py',
        success_token='TOMORROW_WATCHLIST_VALIDATE_OK',
    )
    if not ok:
        result.set_fail('tomorrow_watchlist', detail)
        return
    result.set_ok('tomorrow_watchlist')


def _check_daily_pack(result: ReadinessResult) -> None:
    ok, detail = _validate_report_script(
        'validate_daily_report_pack.py',
        success_token='DAILY_REPORT_PACK_VALIDATE_OK',
    )
    if not ok:
        result.set_fail('daily_pack', detail)
        return

    if BROKER_WRITE_REVIEW_PATH.is_file():
        try:
            review = json.loads(BROKER_WRITE_REVIEW_PATH.read_text(encoding='utf-8'))
            if review.get('ok') is not True:
                result.set_fail('daily_pack', 'broker_db_write_review ok != true')
                return
            summary = review.get('summary')
            if not isinstance(summary, dict):
                result.set_fail('daily_pack', 'broker_db_write_review summary missing')
                return
        except json.JSONDecodeError as exc:
            result.set_fail('daily_pack', f'broker_db_write_review invalid JSON: {exc}')
            return

    result.set_ok('daily_pack')


def _check_external_evidence(result: ReadinessResult) -> None:
    ok, detail = _run_validator_script(
        'validate_external_evidence_adapter.py',
        success_token='EXTERNAL_EVIDENCE_ADAPTER_OK',
    )
    if not ok:
        result.set_fail('external_evidence', detail)
        return

    if not EXTERNAL_EVIDENCE_PATH.is_file():
        result.set_fail('external_evidence', 'external_evidence_latest.json missing')
        return

    try:
        cache = json.loads(EXTERNAL_EVIDENCE_PATH.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        result.set_fail('external_evidence', f'invalid JSON: {exc}')
        return

    if cache.get('ok') is not True and not cache.get('items'):
        result.set_fail('external_evidence', 'external_evidence_latest ok != true')
        return

    summary = cache.get('summary') or {}
    fake_predictions = int(summary.get('fake_predictions') or cache.get('fake_predictions') or 0)
    if fake_predictions != 0:
        result.set_fail('external_evidence', f'fake_predictions={fake_predictions}')
        return

    result.set_ok('external_evidence')


def _scheduler_job_names() -> list[str]:
    try:
        import backend.orchestration.master_scheduler  # noqa: F401

        from backend.orchestration.schedule_registry import get_task_registry

        tasks = get_task_registry().get('tasks') or []
        return [str(t.get('name') or '') for t in tasks if t.get('name')]
    except Exception:
        return []


def _check_scheduler(result: ReadinessResult) -> None:
    job_module = PROJECT_ROOT / 'backend' / 'scheduler' / 'daily_report_pack_job.py'
    if not job_module.is_file():
        result.set_fail('scheduler', 'missing daily_report_pack_job.py')
        return

    names = _scheduler_job_names()
    lowered = {n.lower() for n in names}
    missing = [job for job in REPORT_PACK_SCHEDULER_JOBS if job not in lowered]
    if missing:
        result.set_fail('scheduler', f'missing report pack jobs: {", ".join(missing)}')
        return

    try:
        from scripts import daily_startup_check as startup_mod

        startup = startup_mod.run_daily_startup_check(skip_api=True, strict=False)
        if not startup.ready() and startup.any_fail():
            failed = [name for name, status in startup.sections.items() if status == 'fail']
            result.set_fail('scheduler', f'daily_startup_check failed: {", ".join(failed)}')
            return
    except Exception as exc:
        result.set_fail('scheduler', f'daily_startup_check: {exc}')
        return

    ok, detail = _run_validator_script(
        'validate_daily_report_pack_scheduler.py',
        success_token='DAILY_REPORT_PACK_SCHEDULER_OK',
    )
    if not ok:
        result.set_fail('scheduler', detail)
        return

    result.set_ok('scheduler')


def _check_frontend(result: ReadinessResult) -> None:
    frontend_scripts = (
        ('validate_frontend_final_confidence.py', 'FRONTEND_FINAL_CONFIDENCE_OK'),
        ('validate_frontend_tomorrow_watchlist.py', 'FRONTEND_TOMORROW_WATCHLIST_OK'),
        ('validate_frontend_daily_report_pack.py', 'FRONTEND_DAILY_REPORT_PACK_OK'),
        ('validate_frontend_external_evidence.py', 'FRONTEND_EXTERNAL_EVIDENCE_OK'),
        ('validate_frontend_broker_write_gate.py', 'FRONTEND_BROKER_WRITE_GATE_OK'),
        ('validate_frontend_market_memory_wiring.py', 'FRONTEND_MARKET_MEMORY_WIRING_OK'),
    )
    for script_name, token in frontend_scripts:
        ok, detail = _run_validator_script(script_name, success_token=token)
        if not ok:
            result.set_fail('frontend', f'{script_name}: {detail}')
            return
    result.set_ok('frontend')


CHECKERS: tuple[tuple[str, Callable[[ReadinessResult], None]], ...] = (
    ('local_safety', _check_local_safety),
    ('market_memory', _check_market_memory),
    ('historical_memory', _check_historical_memory),
    ('broker_db_audit', _check_broker_db_audit),
    ('final_confidence', _check_final_confidence),
    ('tomorrow_watchlist', _check_tomorrow_watchlist),
    ('daily_pack', _check_daily_pack),
    ('external_evidence', _check_external_evidence),
    ('scheduler', _check_scheduler),
    ('frontend', _check_frontend),
)


def run_local_system_readiness(*, stop_on_first_fail: bool = True) -> ReadinessResult:
    result = ReadinessResult()
    _apply_local_defaults()
    _check_telegram_send_only(result)
    for _name, checker in CHECKERS:
        checker(result)
        if stop_on_first_fail and result.failures:
            break
    return result


def print_readiness(result: ReadinessResult) -> None:
    for name in COMPACT_ORDER:
        status = result.sections.get(name, 'fail' if name in result.failures else 'pending')
        if status == 'pending' and name not in result.sections:
            continue
        print(f'[LOCAL_READY] {name}={status}')

    tg_status = result.sections.get('telegram_send_only')
    if tg_status:
        print(f'[LOCAL_READY] telegram_send_only={tg_status}')

    failure = result.first_failure()
    if failure:
        check_name, message = failure
        print(f'[LOCAL_READY] fail={check_name}: {message}')

    print(f'[LOCAL_READY] ready={result.ready()}')
    if result.ready():
        print('LOCAL_SYSTEM_READY')


def main() -> int:
    parser = argparse.ArgumentParser(description='Master local system readiness gate.')
    parser.add_argument(
        '--continue-on-fail',
        action='store_true',
        help='Run all checks even after first failure',
    )
    args = parser.parse_args()

    result = run_local_system_readiness(stop_on_first_fail=not args.continue_on_fail)
    print_readiness(result)
    return 0 if result.ready() else 1


if __name__ == '__main__':
    raise SystemExit(main())
