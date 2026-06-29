"""
IST daily report pack scheduler job — local-only, shadow mode.

Generates final confidence / watchlist / calibration (by mode) and the daily report pack.
No trades, Telegram, or canonical outcome writes.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pytz

from backend.analytics.daily_report_pack import FILE_PATHS, generate_daily_report_pack
from backend.analytics.market_calendar_router import MODE_RESEARCH, get_market_router_payload
from backend.utils.config import DATA_DIR, IS_LOCAL_DEV, LOCAL_ONLY

IST = pytz.timezone('Asia/Kolkata')
STATE_PATH = DATA_DIR / 'daily_report_pack_job_state.json'
DEFAULT_LIMIT = 25

REPORT_PACK_JOBS = frozenset({
    'premarket_report_pack',
    'postmarket_report_pack',
    'research_mode_report_pack',
})


def _now_ist() -> datetime:
    return datetime.now(IST)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


def _local_allowed() -> bool:
    return bool(LOCAL_ONLY or IS_LOCAL_DEV or _env_truthy('LOCAL_ONLY') or _env_truthy('LOCAL_DEV_MODE'))


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.is_file():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(state: dict[str, Any]) -> None:
    if not _local_allowed():
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str), encoding='utf-8')


def _relative_files() -> dict[str, str]:
    return {
        key: str(path.relative_to(DATA_DIR.parent)).replace('\\', '/')
        for key, path in FILE_PATHS.items()
    } | {'latest': 'data/daily_report_pack_latest.json'}


def _market_closed_or_research(router: dict[str, Any]) -> bool:
    mode = str(router.get('active_mode') or '')
    if mode == MODE_RESEARCH:
        return True
    india = (router.get('india') or {})
    usa = (router.get('usa') or {})
    if india.get('session') == 'closed' and usa.get('session') == 'closed':
        return True
    return _now_ist().weekday() >= 5


def _resolve_auto_mode(router: dict[str, Any], now: datetime | None = None) -> str:
    now = now or _now_ist()
    mode = str(router.get('active_mode') or MODE_RESEARCH)

    if _market_closed_or_research(router):
        return 'research'

    if mode in ('INDIA_PREMARKET_MODE', 'USA_PREMARKET_MODE'):
        return 'premarket'
    if mode in ('INDIA_POSTMARKET_MODE', 'USA_POSTMARKET_MODE'):
        return 'postmarket'

    hour, minute = now.hour, now.minute
    if hour == 8 and 25 <= minute <= 40:
        return 'premarket'
    if hour == 16 and 25 <= minute <= 40:
        return 'postmarket'
    if hour < 12:
        return 'premarket'
    if hour >= 15:
        return 'postmarket'
    return 'research'


def _research_already_ran_today(now: datetime | None = None) -> bool:
    now = now or _now_ist()
    state = _load_state()
    last = str(state.get('research_last_ist_date') or '')
    return last == now.strftime('%Y-%m-%d')


def _mark_research_ran(now: datetime | None = None) -> None:
    now = now or _now_ist()
    state = _load_state()
    state['research_last_ist_date'] = now.strftime('%Y-%m-%d')
    _save_state(state)


def _refresh_components(mode: str, *, limit: int) -> dict[str, str]:
    """Refresh underlying JSON reports for the job mode (no pack/history writes)."""
    statuses: dict[str, str] = {}
    include_calibration = mode == 'postmarket'

    from backend.analytics.final_confidence_fusion import build_final_confidence_report

    fc = build_final_confidence_report(limit=max(limit, 50))
    if fc.get('ok') is not True:
        statuses['final_confidence'] = 'fail'
    else:
        FILE_PATHS['final_confidence'].parent.mkdir(parents=True, exist_ok=True)
        FILE_PATHS['final_confidence'].write_text(
            json.dumps(fc, indent=2, default=str),
            encoding='utf-8',
        )
        statuses['final_confidence'] = 'ok'

    from backend.analytics.tomorrow_watchlist_report import write_tomorrow_watchlist_report

    tw = write_tomorrow_watchlist_report(limit=limit)
    statuses['tomorrow_watchlist'] = 'ok' if tw.get('ok') is True else 'fail'

    if include_calibration:
        from backend.analytics.confidence_calibration_engine import build_confidence_calibration_report

        cal = build_confidence_calibration_report()
        if cal.get('ok') is not True:
            statuses['calibration'] = 'fail'
        else:
            FILE_PATHS['calibration'].parent.mkdir(parents=True, exist_ok=True)
            FILE_PATHS['calibration'].write_text(
                json.dumps(cal, indent=2, default=str),
                encoding='utf-8',
            )
            statuses['calibration'] = 'ok'
    else:
        statuses['calibration'] = 'skipped'

    return statuses


def _canonical_counts_unchanged(before: dict[str, Any], after: dict[str, Any]) -> bool:
    for key in ('predictions', 'outcomes'):
        if int(after.get(key) or 0) != int(before.get(key) or 0):
            return False
    return True


def run_daily_report_pack_job(
    mode: str = 'auto',
    *,
    dry_run: bool = False,
    limit: int = DEFAULT_LIMIT,
    allow_runtime: bool = False,
) -> dict[str, Any]:
    """
    Run scheduled daily report pack generation.

    Modes: auto, premarket, postmarket, research.
    dry_run: compute routing only; write no files.
    """
    requested = (mode or 'auto').strip().lower()
    warnings: list[str] = []
    files = _relative_files()

    if not (allow_runtime or _local_allowed()):
        return {
            'ok': False,
            'mode': requested,
            'generated': False,
            'market_mode': MODE_RESEARCH,
            'files': files,
            'warnings': ['refused: LOCAL_ONLY=1 or LOCAL_DEV_MODE=1 required'],
        }

    try:
        router = get_market_router_payload() or {}
    except Exception as exc:
        router = {'ok': False, 'error': str(exc)}
        warnings.append(f'market_router_error={exc}')

    market_mode = str(router.get('active_mode') or MODE_RESEARCH)
    effective = _resolve_auto_mode(router) if requested == 'auto' else requested

    if effective not in ('premarket', 'postmarket', 'research'):
        warnings.append(f'unknown_mode={requested}; using auto')
        effective = _resolve_auto_mode(router)

    if effective == 'research':
        if not _market_closed_or_research(router):
            return {
                'ok': True,
                'mode': effective,
                'generated': False,
                'market_mode': market_mode,
                'files': files,
                'warnings': ['skipped: markets open — research pack not due'],
            }
        if _research_already_ran_today():
            return {
                'ok': True,
                'mode': effective,
                'generated': False,
                'market_mode': market_mode,
                'files': files,
                'warnings': ['skipped: research pack already ran today'],
            }

    if dry_run:
        return {
            'ok': True,
            'mode': effective,
            'generated': False,
            'market_mode': market_mode,
            'files': files,
            'warnings': warnings or ['dry_run: no files written'],
        }

    stats_before: dict[str, Any] = {}
    try:
        from backend.storage.market_memory_db import get_market_memory_stats, init_market_memory_db

        if init_market_memory_db():
            stats_before = get_market_memory_stats()
    except Exception as exc:
        warnings.append(f'market_memory_stats_unavailable={exc}')

    refresh_status = _refresh_components(effective, limit=limit)
    if refresh_status.get('final_confidence') == 'fail':
        warnings.append('final_confidence refresh failed')
    if refresh_status.get('tomorrow_watchlist') == 'fail':
        warnings.append('tomorrow_watchlist refresh failed')
    if effective == 'postmarket' and refresh_status.get('calibration') == 'fail':
        warnings.append('calibration refresh failed')

    pack = generate_daily_report_pack(refresh=False, limit=limit, pack_mode=effective)
    generated = pack.get('ok') is True

    if stats_before:
        try:
            from backend.storage.market_memory_db import get_market_memory_stats

            stats_after = get_market_memory_stats()
            if not _canonical_counts_unchanged(stats_before, stats_after):
                warnings.append('canonical memory counts changed during job')
                generated = False
        except Exception as exc:
            warnings.append(f'post_stats_check_failed={exc}')

    if effective == 'research' and generated:
        _mark_research_ran()

    if generated:
        market_mode = str(pack.get('market_mode') or market_mode)
        files = {**(pack.get('files') or files), 'latest': pack.get('output_path', files.get('latest'))}

    return {
        'ok': True,
        'mode': effective,
        'generated': generated,
        'market_mode': market_mode,
        'files': files,
        'warnings': warnings,
        'refresh_status': refresh_status,
    }
