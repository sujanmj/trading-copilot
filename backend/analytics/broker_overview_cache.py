"""
AstraEdge Broker Overview cache — Stage 48E.

Cache-first broker intelligence for GUI mount. Heavy refresh runs only on POST /api/brokers/refresh.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path
from backend.storage.json_io import atomic_write_json

IST = ZoneInfo('Asia/Kolkata')
STAGE = '48E'
ENGINE_NAME = 'Broker Overview Cache'
CACHE_FILE = get_data_path('broker_overview_cache.json')
MISSING_MESSAGE = 'Broker cache unavailable. Tap Refresh Brokers.'

BROKER_COLLECTOR_CACHE = get_data_path('broker_app_collector_latest.json')


def _log(msg: str) -> None:
    print(f'[BROKER_OVERVIEW] {msg}', flush=True)


def _now_iso() -> str:
    return datetime.now(IST).replace(microsecond=0).isoformat()


def _load_cache() -> dict[str, Any]:
    if CACHE_FILE.is_file():
        try:
            data = json.loads(CACHE_FILE.read_text(encoding='utf-8'))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _save_cache(payload: dict[str, Any]) -> None:
    payload['stage'] = STAGE
    payload['engine'] = ENGINE_NAME
    atomic_write_json(CACHE_FILE, payload)


def _file_age_hours(path) -> Optional[float]:
    try:
        if not path.is_file():
            return None
        mtime = datetime.fromtimestamp(path.stat().st_mtime, IST)
        return (datetime.now(IST) - mtime).total_seconds() / 3600.0
    except OSError:
        return None


def _is_stale(*ages: Optional[float]) -> bool:
    valid = [a for a in ages if a is not None]
    if not valid:
        return True
    return any(a > 24 for a in valid)


def _missing_lite_payload() -> dict[str, Any]:
    return {
        'ok': True,
        'lite': True,
        'cache_missing': True,
        'stale': True,
        'stage': STAGE,
        'engine': ENGINE_NAME,
        'generated_at': _now_iso(),
        'message': MISSING_MESSAGE,
        'brokers': [],
        'signals': [],
        'consensus': [],
        'stats': {},
        'disclaimer': 'External broker/app evidence — not our final prediction.',
    }


def _lite_from_cache(cached: dict[str, Any]) -> dict[str, Any]:
    stale = bool(cached.get('stale')) or _is_stale(
        _file_age_hours(CACHE_FILE),
        _file_age_hours(BROKER_COLLECTOR_CACHE),
    )
    return {
        'ok': True,
        'lite': True,
        'from_cache': True,
        'cache_missing': False,
        'stale': stale,
        'stage': STAGE,
        'engine': ENGINE_NAME,
        'generated_at': cached.get('generated_at') or cached.get('refreshed_at'),
        'message': cached.get('message'),
        'brokers': (cached.get('brokers') or [])[:12],
        'signals': (cached.get('signals') or [])[:12],
        'consensus': (cached.get('consensus') or [])[:12],
        'stats': cached.get('stats') or {},
        'dashboard': cached.get('dashboard') or {},
        'collector': cached.get('collector') or {},
        'coverage': cached.get('coverage') or {},
        'comparison': cached.get('comparison') or {},
        'disclaimer': cached.get('disclaimer') or 'External broker/app evidence — not our final prediction.',
    }


def _build_full_overview(*, persist: bool = True) -> dict[str, Any]:
    from backend.analytics.broker_prediction_intelligence import (
        compare_our_predictions_vs_brokers,
        get_broker_intelligence_dashboard,
        get_source_performance,
        get_top_broker_display_candidates,
    )
    from backend.collectors.broker_app_collector import (
        get_broker_app_collector_dashboard,
        get_external_source_coverage,
        run_broker_app_collector,
    )

    collector_run = run_broker_app_collector()
    dashboard = get_broker_intelligence_dashboard()
    comparison = compare_our_predictions_vs_brokers(limit=100)
    collector = get_broker_app_collector_dashboard()
    coverage = get_external_source_coverage()
    display = get_top_broker_display_candidates(limit=12)
    sources = get_source_performance()

    brokers = [
        {
            'source': row.get('source') or row.get('broker_source'),
            'picks': row.get('pick_count') or row.get('picks'),
            'accuracy': row.get('accuracy'),
        }
        for row in (sources or [])[:12]
    ]
    signals = list(display.get('candidates') or [])[:12]
    consensus = list((comparison.get('pairs') or []))[:12]

    payload: dict[str, Any] = {
        'ok': True,
        'stage': STAGE,
        'engine': ENGINE_NAME,
        'generated_at': _now_iso(),
        'refreshed_at': _now_iso(),
        'stale': False,
        'brokers': brokers,
        'signals': signals,
        'consensus': consensus,
        'stats': dashboard.get('stats') or {},
        'dashboard': dashboard,
        'comparison': comparison,
        'collector': collector,
        'coverage': coverage,
        'collector_run': {
            'ok': collector_run.get('ok'),
            'items': collector_run.get('items_written') or collector_run.get('item_count'),
        },
        'disclaimer': dashboard.get('disclaimer') or 'External broker/app evidence — not our final prediction.',
    }
    if persist:
        _save_cache(payload)
        _log(f'refreshed broker overview brokers={len(brokers)} signals={len(signals)}')
    return payload


def get_broker_overview(*, cache_only: bool = False, lite: bool = False) -> dict[str, Any]:
    if cache_only and lite:
        cached = _load_cache()
        if cached and cached.get('ok') and not cached.get('cache_missing'):
            return _lite_from_cache(cached)
        return _missing_lite_payload()

    if cache_only:
        cached = _load_cache()
        if cached and cached.get('ok') and not cached.get('cache_missing'):
            out = dict(cached)
            out['from_cache'] = True
            out.setdefault('stage', STAGE)
            out.setdefault('engine', ENGINE_NAME)
            out['stale'] = bool(out.get('stale')) or _is_stale(_file_age_hours(CACHE_FILE))
            return out
        return {
            'ok': True,
            'cache_missing': True,
            'stale': True,
            'stage': STAGE,
            'engine': ENGINE_NAME,
            'generated_at': _now_iso(),
            'message': MISSING_MESSAGE,
            'brokers': [],
            'signals': [],
            'consensus': [],
            'stats': {},
            'disclaimer': 'External broker/app evidence — not our final prediction.',
        }

    return _build_full_overview(persist=True)


def get_broker_status(*, lite: bool = False) -> dict[str, Any]:
    cached = _load_cache()
    cache_age_h = _file_age_hours(CACHE_FILE)
    collector_age_h = _file_age_hours(BROKER_COLLECTOR_CACHE)
    stale = _is_stale(cache_age_h, collector_age_h)
    if lite:
        return {
            'ok': True,
            'lite': True,
            'stage': STAGE,
            'cache_exists': bool(cached and cached.get('ok')),
            'cache_missing': not bool(cached and cached.get('ok')),
            'stale': stale,
            'generated_at': (cached or {}).get('generated_at'),
            'cache_age_hours': cache_age_h,
            'collector_cache_age_hours': collector_age_h,
            'broker_count': len((cached or {}).get('brokers') or []),
            'signal_count': len((cached or {}).get('signals') or []),
            'message': None if cached else MISSING_MESSAGE,
        }

    return {
        'ok': True,
        'stage': STAGE,
        'cache_exists': bool(cached and cached.get('ok')),
        'stale': stale,
        'generated_at': (cached or {}).get('generated_at'),
        'freshness': {
            'overview_cache_age_hours': cache_age_h,
            'collector_cache_age_hours': collector_age_h,
            'status': 'stale' if stale else 'fresh',
        },
        'stats': (cached or {}).get('stats') or {},
    }


def refresh_broker_intel(*, persist: bool = True) -> dict[str, Any]:
    return _build_full_overview(persist=persist)
