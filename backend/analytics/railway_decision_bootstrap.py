"""
Railway cloud report bootstrap — generate cached reports when missing/stale (Stage 46F).

Safe for Railway: never resets memory DB, uses file/thread lock for single-flight generation.
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.storage.data_paths import get_data_path, is_railway_data_mode

LOG_PREFIX = '[RAILWAY_DECISION_BOOTSTRAP]'
REPORT_LOG_PREFIX = '[RAILWAY_REPORT_BOOTSTRAP]'
STAGE_MARKER = 'RAILWAY_STAGE_46F_LIVE_DATA_BOOTSTRAP'

STALE_HOURS_DEFAULT = 24
DEFAULT_TIMEOUT_SEC = 120
TELEGRAM_TIMEOUT_SEC = 45

WARMING_MESSAGE = 'Decision reports are being rebuilt. Try /today again in 1–2 minutes.'
BOOTSTRAP_STARTED_MESSAGE = 'Bootstrap started. Try /today again in 1–2 minutes.'
NO_CANDIDATE_MESSAGE = 'No clean candidate. Use /aihub market and /news.'
REBUILT_CACHE_MESSAGE = 'Decision file was missing, rebuilt from Railway cache.'

_THREAD_LOCK = threading.Lock()
_ALIGN_DONE = False
_LAST_RESULT: dict[str, Any] | None = None


def warming_message() -> str:
    return WARMING_MESSAGE


def bootstrap_started_reply() -> str:
    return BOOTSTRAP_STARTED_MESSAGE


def decision_rebuilding_reply(mode: str) -> str:
    cmd = '/today' if str(mode or 'today').strip().lower() == 'today' else '/tomorrow'
    return f'Decision reports are being rebuilt. Try {cmd} again in 1–2 minutes.'


def no_candidate_message() -> str:
    return NO_CANDIDATE_MESSAGE


def rebuilt_cache_message() -> str:
    return REBUILT_CACHE_MESSAGE


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _should_align_data_dir() -> bool:
    """True only on deployed Railway — not local smoke importing railway runners."""
    try:
        from backend.utils.config import IS_LOCAL_DEV, LOCAL_ONLY

        if IS_LOCAL_DEV or LOCAL_ONLY:
            return False
    except Exception:
        pass
    if os.environ.get('RAILWAY_ENVIRONMENT', '').strip():
        return True
    if os.environ.get('RAILWAY_DATA_DIR', '').strip():
        return True
    return is_railway_data_mode()


def _align_config_data_dir_once() -> None:
    """Point config DATA_DIR at Railway volume when it differs from repo data/."""
    global _ALIGN_DONE
    if _ALIGN_DONE:
        return
    if not _should_align_data_dir():
        _ALIGN_DONE = True
        return
    from backend.storage.data_paths import get_data_root
    import backend.utils.config as cfg

    root = get_data_root()
    if _should_align_data_dir():
        try:
            if cfg.DATA_DIR.resolve() != root.resolve():
                cfg.DATA_DIR = root
                cfg.RUNTIME_DIR = root / 'runtime'
                cfg.RUNTIME_CACHE_DIR = root / 'cache'
                cfg.RUNTIME_SNAPSHOT_CACHE = cfg.RUNTIME_CACHE_DIR / 'runtime_snapshot.json'
                cfg.CURRENT_SNAPSHOT_FILE = cfg.RUNTIME_DIR / 'current_snapshot.json'
                cfg.LOCKS_DIR = root / '.locks'
                cfg.DB_PATH = root / 'trading_history.db'
        except OSError:
            cfg.DATA_DIR = root
    _ALIGN_DONE = True


def _data_paths() -> dict[str, Path]:
    _align_config_data_dir_once()
    return {
        'final_confidence': get_data_path('final_confidence_report.json'),
        'tomorrow_watchlist': get_data_path('tomorrow_watchlist_report.json'),
        'daily_pack': get_data_path('daily_report_pack_latest.json'),
        'stock_today': get_data_path('stock_decision_today.json'),
        'stock_tomorrow': get_data_path('stock_decision_tomorrow.json'),
        'runtime_snapshot': get_data_path('cache/runtime_snapshot.json'),
        'memory_dashboard': get_data_path('market_memory_dashboard_cache.json'),
        'lock': get_data_path('.locks/railway_report_bootstrap.lock'),
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _file_age_hours(path: Path) -> float | None:
    if not path.is_file():
        return None
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        delta = datetime.now(timezone.utc) - mtime
        return delta.total_seconds() / 3600.0
    except OSError:
        return None


def _file_stale(path: Path, *, stale_hours: float = STALE_HOURS_DEFAULT) -> bool:
    age = _file_age_hours(path)
    if age is None:
        return True
    return age >= stale_hours


def report_cache_needs_bootstrap(*, stale_hours: float = STALE_HOURS_DEFAULT) -> bool:
    paths = _data_paths()
    checks = (
        paths['final_confidence'],
        paths['tomorrow_watchlist'],
        paths['daily_pack'],
        paths['stock_today'],
        paths['stock_tomorrow'],
    )
    return any(_file_stale(p, stale_hours=stale_hours) for p in checks)


def decision_cache_needs_bootstrap(*, stale_hours: float = STALE_HOURS_DEFAULT) -> bool:
    return report_cache_needs_bootstrap(stale_hours=stale_hours)


def _acquire_file_lock(lock_path: Path) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, _now_iso().encode('utf-8'))
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except OSError:
        return False


def _release_file_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding='utf-8')


def _refresh_runtime_snapshot_safe() -> str:
    try:
        from backend.api.api_server import ensure_runtime_snapshot_cache

        ensure_runtime_snapshot_cache()
        return 'ok'
    except Exception as exc:
        return f'skip:{exc}'[:80]


def _generate_final_confidence_safe(*, limit: int = 50) -> str:
    from backend.analytics.final_confidence_fusion import build_final_confidence_report

    report = build_final_confidence_report(limit=limit)
    if report.get('ok') is not True:
        return f"fail:{report.get('error') or 'build_failed'}"[:80]
    _write_json(get_data_path('final_confidence_report.json'), report)
    return 'ok'


def _generate_tomorrow_watchlist_safe(*, limit: int = 25) -> str:
    from backend.analytics.tomorrow_watchlist_report import write_tomorrow_watchlist_report

    report = write_tomorrow_watchlist_report(limit=limit)
    if report.get('ok') is not True:
        return f"fail:{report.get('error') or 'watchlist_failed'}"[:80]
    return 'ok'


def _generate_daily_pack_safe(*, limit: int = 25) -> str:
    from backend.analytics.daily_report_pack import generate_daily_report_pack

    pack = generate_daily_report_pack(refresh=True, limit=limit)
    if pack.get('ok') is not True:
        return f"fail:{pack.get('error') or 'pack_failed'}"[:80]
    return 'ok'


def _generate_stock_decision_safe(mode: str) -> str:
    from backend.analytics.stock_decision_engine import build_stock_decision

    payload = build_stock_decision(mode=mode)
    if payload.get('ok') is not True:
        return f"fail:{payload.get('error') or payload.get('message') or 'decision_failed'}"[:80]
    _write_json(get_data_path(f'stock_decision_{mode}.json'), payload)
    return 'ok'


def _generate_market_memory_dashboard_safe(*, limit: int = 20) -> str:
    try:
        from backend.analytics.market_memory_dashboard import get_market_memory_dashboard

        dashboard = get_market_memory_dashboard(limit=limit)
        if dashboard.get('ok') is not True:
            return f"fail:{dashboard.get('error') or 'memory_dashboard_failed'}"[:80]
        _write_json(get_data_path('market_memory_dashboard_cache.json'), dashboard)
        return 'ok'
    except Exception as exc:
        return f'skip:{exc}'[:80]


def stock_decision_cache_ready(mode: str, *, stale_hours: float = STALE_HOURS_DEFAULT) -> bool:
    """True when cached stock decision JSON exists and is not stale."""
    normalized = str(mode or 'today').strip().lower()
    paths = _data_paths()
    mode_path = paths['stock_today'] if normalized == 'today' else paths['stock_tomorrow']
    return mode_path.is_file() and not _file_stale(mode_path, stale_hours=stale_hours)


def start_background_bootstrap_reports(
    *,
    force: bool = False,
    delay_sec: float = 0.5,
    railway_only: bool = True,
) -> None:
    """Fire-and-forget report bootstrap for Telegram /bootstrap and lazy /today /tomorrow."""

    def _worker() -> None:
        time.sleep(delay_sec)
        try:
            run_railway_bootstrap_reports(
                timeout_sec=DEFAULT_TIMEOUT_SEC,
                force=force,
                railway_only=railway_only,
            )
        except Exception as exc:
            print(f'{REPORT_LOG_PREFIX} background_error={exc}', flush=True)

    threading.Thread(
        target=_worker,
        name='railway_bootstrap_reports_bg',
        daemon=True,
    ).start()


def _run_bootstrap_steps(*, limit: int = 25) -> dict[str, Any]:
    print(STAGE_MARKER, flush=True)
    print(f'{LOG_PREFIX} start', flush=True)
    from backend.storage.data_paths import get_data_root

    print(f'{REPORT_LOG_PREFIX} data_root={get_data_root()}', flush=True)
    result: dict[str, Any] = {
        'ok': False,
        'started_at': _now_iso(),
        'steps': {},
    }

    result['steps']['runtime_snapshot'] = _refresh_runtime_snapshot_safe()

    fc_status = _generate_final_confidence_safe(limit=max(limit, 50))
    result['steps']['final_confidence'] = fc_status
    print(f'{LOG_PREFIX} final_confidence={fc_status}', flush=True)

    tw_status = _generate_tomorrow_watchlist_safe(limit=limit)
    result['steps']['tomorrow_watchlist'] = tw_status
    print(f'{REPORT_LOG_PREFIX} tomorrow_watchlist={tw_status}', flush=True)

    pack_status = _generate_daily_pack_safe(limit=limit)
    result['steps']['daily_pack'] = pack_status
    print(f'{REPORT_LOG_PREFIX} daily_pack={pack_status}', flush=True)

    today_status = _generate_stock_decision_safe('today')
    result['steps']['stock_decision_today'] = today_status
    print(f'{LOG_PREFIX} stock_decision_today={today_status}', flush=True)

    tomorrow_status = _generate_stock_decision_safe('tomorrow')
    result['steps']['stock_decision_tomorrow'] = tomorrow_status
    print(f'{LOG_PREFIX} stock_decision_tomorrow={tomorrow_status}', flush=True)

    mem_status = _generate_market_memory_dashboard_safe()
    result['steps']['market_memory_dashboard'] = mem_status
    print(f'{REPORT_LOG_PREFIX} market_memory_dashboard={mem_status}', flush=True)

    critical = (fc_status, tw_status, pack_status, today_status, tomorrow_status)
    result['ok'] = all(status == 'ok' for status in critical)
    result['finished_at'] = _now_iso()
    return result


def run_railway_bootstrap_reports(
    *,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    limit: int = 25,
    force: bool = False,
    railway_only: bool = True,
) -> dict[str, Any]:
    """Single-flight cloud report bootstrap with timeout."""
    global _LAST_RESULT
    if railway_only and not force and not _should_align_data_dir():
        return {'ok': True, 'skipped': True, 'reason': 'not_railway_deploy'}
    _align_config_data_dir_once()

    if not force and not report_cache_needs_bootstrap():
        return {'ok': True, 'skipped': True, 'reason': 'cache_fresh'}

    paths = _data_paths()
    lock_path = paths['lock']

    if not _THREAD_LOCK.acquire(blocking=False):
        return {
            'ok': False,
            'warming': True,
            'message': WARMING_MESSAGE,
            'reason': 'thread_lock_busy',
        }

    file_locked = _acquire_file_lock(lock_path)
    if not file_locked:
        _THREAD_LOCK.release()
        return {
            'ok': False,
            'warming': True,
            'message': WARMING_MESSAGE,
            'reason': 'file_lock_busy',
        }

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run_bootstrap_steps, limit=limit)
            try:
                result = future.result(timeout=timeout_sec)
            except FuturesTimeoutError:
                result = {
                    'ok': False,
                    'timed_out': True,
                    'warming': True,
                    'message': WARMING_MESSAGE,
                    'finished_at': _now_iso(),
                }
        _LAST_RESULT = result
        if result.get('ok'):
            print('RAILWAY_BOOTSTRAP_REPORTS_OK', flush=True)
        return result
    finally:
        _release_file_lock(lock_path)
        _THREAD_LOCK.release()


def run_railway_decision_bootstrap(
    *,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    limit: int = 25,
    force: bool = False,
) -> dict[str, Any]:
    """Backward-compatible alias for run_railway_bootstrap_reports."""
    if not force and not _should_align_data_dir():
        return {'ok': True, 'skipped': True, 'reason': 'not_railway_deploy'}
    return run_railway_bootstrap_reports(timeout_sec=timeout_sec, limit=limit, force=force)


def load_cached_stock_decision(mode: str) -> dict[str, Any]:
    """Read cached stock decision JSON for the requested mode."""
    normalized = str(mode or 'today').strip().lower()
    paths = _data_paths()
    path = paths['stock_today'] if normalized == 'today' else paths['stock_tomorrow']
    payload = _load_json(path)
    if payload.get('ok') is True:
        return payload
    return {}


def _watchlist_fallback_rows(*, limit: int = 5) -> list[dict[str, Any]]:
    paths = _data_paths()
    pack = _load_json(paths['daily_pack'])
    tw = pack.get('tomorrow_watchlist') if pack else {}
    if not isinstance(tw, dict) or not tw.get('top_watchlist'):
        tw = _load_json(paths['tomorrow_watchlist'])
    fc = _load_json(paths['final_confidence'])
    if not isinstance(tw, dict):
        tw = {}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in (
        tw.get('top_watchlist') or tw.get('raw_candidates') or [],
        fc.get('top_candidates') or fc.get('rows') or [],
    ):
        if not isinstance(source, list):
            continue
        for row in source:
            if not isinstance(row, dict):
                continue
            ticker = str(row.get('ticker') or row.get('symbol') or '').upper().strip()
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            rows.append({
                'ticker': ticker,
                'action': str(row.get('action') or row.get('decision') or 'WATCH_FOR_ENTRY'),
            })
            if len(rows) >= limit:
                return rows
    return rows


def format_watchlist_fallback_telegram(mode: str, *, rebuilt: bool = False) -> str:
    """Clean Telegram fallback when stock decision file is still unavailable."""
    label = 'Today' if mode == 'today' else mode.capitalize()
    lines = [f'<b>📋 {label}</b>']
    if rebuilt:
        lines.extend(['', REBUILT_CACHE_MESSAGE])
    rows = _watchlist_fallback_rows(limit=5)
    watch_rows = [
        row for row in rows
        if str(row.get('action', '')).upper() not in ('AVOID', 'NO_DECISION')
    ]
    if watch_rows:
        lines.extend(['', 'Top watch-for-entry:'])
        for row in watch_rows[:5]:
            action = str(row.get('action') or 'WATCH_FOR_ENTRY').replace('_', ' ').upper()
            lines.append(f"• {row.get('ticker')} — {action}")
    else:
        lines.extend(['', NO_CANDIDATE_MESSAGE])
    return '\n'.join(lines)


def ensure_decision_cache_for_command(
    mode: str,
    *,
    timeout_sec: float = TELEGRAM_TIMEOUT_SEC,
    force: bool = False,
) -> dict[str, Any]:
    """Lazy bootstrap before /today or /tomorrow — lightweight when cache is fresh."""
    normalized = str(mode or 'today').strip().lower()
    if not force and not _should_align_data_dir():
        return {'ok': True, 'skipped': True, 'reason': 'not_railway_deploy'}
    paths = _data_paths()
    mode_path = paths['stock_today'] if normalized == 'today' else paths['stock_tomorrow']
    if (
        not force
        and not _file_stale(mode_path)
        and not _file_stale(paths['final_confidence'])
    ):
        return {'ok': True, 'skipped': True}
    return run_railway_bootstrap_reports(timeout_sec=timeout_sec, force=force)


def repair_decision_for_telegram(mode: str) -> tuple[dict[str, Any] | None, bool, bool]:
    """
    Bootstrap missing decision, retry load/build.

    Returns (payload, rebuilt, used_fallback).
    """
    normalized = str(mode or 'today').strip().lower()
    paths = _data_paths()
    mode_path = paths['stock_today'] if normalized == 'today' else paths['stock_tomorrow']
    was_missing = not mode_path.is_file() or _file_stale(mode_path)

    cached = load_cached_stock_decision(normalized)
    if cached and not was_missing:
        return cached, False, False

    bootstrap = ensure_decision_cache_for_command(normalized)
    rebuilt = was_missing and bootstrap.get('skipped') is not True

    cached = load_cached_stock_decision(normalized)
    if cached:
        return cached, rebuilt, False

    from backend.analytics.stock_decision_engine import build_stock_decision

    payload = build_stock_decision(mode=normalized)
    if payload.get('ok') is True:
        _write_json(mode_path, payload)
        return payload, rebuilt, False

    if bootstrap.get('warming'):
        return None, rebuilt, False

    return None, rebuilt, True


def start_background_report_bootstrap(
    *,
    stale_hours: float = STALE_HOURS_DEFAULT,
    delay_sec: float = 2.0,
) -> None:
    """Start daemon thread on Railway web startup — always logs STARTED on deploy."""
    if not _should_align_data_dir():
        return

    def _worker() -> None:
        time.sleep(delay_sec)
        try:
            if not report_cache_needs_bootstrap(stale_hours=stale_hours):
                print(STAGE_MARKER, flush=True)
                print('RAILWAY_BOOTSTRAP_REPORTS_OK', flush=True)
                return
            result = run_railway_bootstrap_reports(
                timeout_sec=DEFAULT_TIMEOUT_SEC,
                railway_only=True,
            )
            if result.get('ok'):
                print('RAILWAY_BOOTSTRAP_REPORTS_OK', flush=True)
            else:
                print('RAILWAY_REPORT_BOOTSTRAP_WARN', flush=True)
        except Exception as exc:
            print('RAILWAY_REPORT_BOOTSTRAP_WARN', flush=True)
            print(f'{REPORT_LOG_PREFIX} error={exc}', flush=True)

    print('RAILWAY_REPORT_BOOTSTRAP_STARTED', flush=True)
    threading.Thread(
        target=_worker,
        name='railway_report_bootstrap',
        daemon=True,
    ).start()


def start_background_bootstrap_if_needed(
    *,
    stale_hours: float = STALE_HOURS_DEFAULT,
    delay_sec: float = 2.0,
) -> bool:
    """Backward-compatible startup hook — delegates to start_background_report_bootstrap."""
    if not _should_align_data_dir():
        return False
    start_background_report_bootstrap(stale_hours=stale_hours, delay_sec=delay_sec)
    return report_cache_needs_bootstrap(stale_hours=stale_hours)
