"""
AstraEdge Broker Overview cache — Stage 48L.

Cache-first broker intelligence for GUI mount. Heavy refresh runs only on POST /api/brokers/refresh.
Delegates to broker_intelligence_cache.json via broker_intelligence module.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path
from backend.storage.json_io import atomic_write_json

IST = ZoneInfo('Asia/Kolkata')
STAGE = '48L'
ENGINE_NAME = 'Broker Overview Cache'
CACHE_FILE = get_data_path('broker_overview_cache.json')
INTEL_CACHE_FILE = get_data_path('broker_intelligence_cache.json')
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


def _load_intel_cache() -> dict[str, Any]:
    if INTEL_CACHE_FILE.is_file():
        try:
            data = json.loads(INTEL_CACHE_FILE.read_text(encoding='utf-8'))
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
        'freshness': {'status': 'missing'},
        'tracked_tickers': 0,
        'top_positive': [],
        'top_negative': [],
        'impact_today': [],
        'impact_tomorrow': [],
        'evidence_items': [],
        'disclaimer': 'External broker/app evidence — not our final prediction.',
    }


def _merge_intel_lite(intel: dict[str, Any], legacy: dict[str, Any] | None = None) -> dict[str, Any]:
    legacy = legacy or {}
    fresh = intel.get('freshness') or {}
    stale = fresh.get('status') in {'stale', 'missing'} or bool(intel.get('stale_reason'))
    return {
        'ok': True,
        'lite': True,
        'from_cache': True,
        'cache_missing': False,
        'stale': stale,
        'stage': STAGE,
        'engine': ENGINE_NAME,
        'generated_at': intel.get('generated_at') or legacy.get('generated_at'),
        'message': intel.get('message'),
        'freshness': fresh,
        'tracked_tickers': intel.get('tracked_tickers') or len(intel.get('consensus_by_ticker') or {}),
        'source_counts': intel.get('source_counts') or {},
        'top_positive': (intel.get('top_positive') or [])[:8],
        'top_negative': (intel.get('top_negative') or [])[:8],
        'top_upgrades': (intel.get('top_upgrades') or [])[:6],
        'top_downgrades': (intel.get('top_downgrades') or [])[:6],
        'target_price_changes': (intel.get('target_price_changes') or [])[:6],
        'impact_today': (intel.get('impact_today') or [])[:4],
        'impact_tomorrow': (intel.get('impact_tomorrow') or [])[:4],
        'evidence_items': (intel.get('evidence_items') or [])[:12],
        'broker_mentions': (intel.get('broker_mentions') or [])[:8],
        'consensus_by_ticker': intel.get('consensus_by_ticker') or {},
        'brokers': legacy.get('brokers') or [],
        'signals': legacy.get('signals') or [],
        'consensus': legacy.get('consensus') or [],
        'stats': {
            **(legacy.get('stats') or {}),
            'tracked_tickers': intel.get('tracked_tickers') or 0,
            'unique_tickers': intel.get('tracked_tickers') or 0,
        },
        'dashboard': legacy.get('dashboard') or {},
        'collector': legacy.get('collector') or {},
        'coverage': legacy.get('coverage') or {},
        'comparison': legacy.get('comparison') or {},
        'stale_reason': intel.get('stale_reason'),
        'disclaimer': intel.get('disclaimer') or 'External broker/app evidence — not our final prediction.',
    }


def _build_full_overview(*, persist: bool = True) -> dict[str, Any]:
    from backend.analytics.broker_intelligence import refresh_broker_intelligence
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

    intel = refresh_broker_intelligence(persist=True)
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
        **intel,
        'ok': True,
        'stage': STAGE,
        'engine': ENGINE_NAME,
        'generated_at': intel.get('generated_at') or _now_iso(),
        'refreshed_at': _now_iso(),
        'stale': False,
        'brokers': brokers,
        'signals': signals,
        'consensus': consensus,
        'stats': {
            **(dashboard.get('stats') or {}),
            'tracked_tickers': intel.get('tracked_tickers') or 0,
        },
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
        _log(
            f"refreshed broker overview tickers={intel.get('tracked_tickers')} "
            f"brokers={len(brokers)} signals={len(signals)}"
        )
    return payload


def get_broker_overview(*, cache_only: bool = False, lite: bool = False) -> dict[str, Any]:
    intel = _load_intel_cache()
    legacy = _load_cache()

    if cache_only and lite:
        if intel and intel.get('ok'):
            return _merge_intel_lite(intel, legacy)
        if legacy and legacy.get('ok') and not legacy.get('cache_missing'):
            stale = bool(legacy.get('stale')) or _is_stale(
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
                'generated_at': legacy.get('generated_at'),
                'brokers': (legacy.get('brokers') or [])[:12],
                'signals': (legacy.get('signals') or [])[:12],
                'consensus': (legacy.get('consensus') or [])[:12],
                'stats': legacy.get('stats') or {},
                'disclaimer': legacy.get('disclaimer') or 'External broker/app evidence — not our final prediction.',
            }
        return _missing_lite_payload()

    if cache_only:
        if intel and intel.get('ok'):
            out = dict(intel)
            out['from_cache'] = True
            out.setdefault('stage', STAGE)
            out.setdefault('engine', ENGINE_NAME)
            return out
        if legacy and legacy.get('ok'):
            out = dict(legacy)
            out['from_cache'] = True
            out['stale'] = bool(out.get('stale')) or _is_stale(_file_age_hours(CACHE_FILE))
            return out
        return _missing_lite_payload()

    return _build_full_overview(persist=True)


def get_broker_status(*, lite: bool = False) -> dict[str, Any]:
    intel = _load_intel_cache()
    legacy = _load_cache()
    cached = intel or legacy
    cache_age_h = _file_age_hours(INTEL_CACHE_FILE if intel else CACHE_FILE)
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
            'tracked_tickers': (cached or {}).get('tracked_tickers') or len((cached or {}).get('consensus_by_ticker') or {}),
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
        'tracked_tickers': (cached or {}).get('tracked_tickers') or 0,
    }


def refresh_broker_intel(*, persist: bool = True) -> dict[str, Any]:
    return _build_full_overview(persist=persist)
