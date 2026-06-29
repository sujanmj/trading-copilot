"""Lightweight live runtime snapshot publisher.

This path is intentionally scanner-backed only. It refreshes canonical runtime
freshness during live market without rebuilding full reports or calling AI
providers.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytz

from backend.storage.json_io import atomic_write_json
from backend.utils.config import (
    CURRENT_SNAPSHOT_FILE,
    DATA_DIR,
    RUNTIME_SNAPSHOT_CACHE,
)

IST = pytz.timezone('Asia/Kolkata')

SCANNER_FILE = DATA_DIR / 'scanner_data.json'
MARKET_FILE = DATA_DIR / 'latest_market_data.json'
ENRICHED_MARKET_FILE = DATA_DIR / 'latest_market_data_memory_enriched.json'

LIVE_SCANNER_MAX_AGE_MINUTES = int(os.environ.get('LIVE_LITE_SCANNER_MAX_AGE_MINUTES', '5'))
LIVE_LITE_MIN_INTERVAL_SECONDS = int(os.environ.get('LIVE_LITE_MIN_INTERVAL_SECONDS', '180'))


def _now() -> datetime:
    return datetime.now(IST)


def _now_iso() -> str:
    return _now().isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file():
            return {}
        payload = json.loads(path.read_text(encoding='utf-8'))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _file_age_minutes(path: Path) -> int | None:
    try:
        if not path.is_file():
            return None
        return max(0, int((time.time() - path.stat().st_mtime) / 60))
    except Exception:
        return None


def _is_live_market(operational: dict[str, Any] | None = None) -> bool:
    op = operational
    if op is None:
        try:
            from backend.utils.market_hours import get_operational_status

            op = get_operational_status() or {}
        except Exception:
            op = {}
    state = str(
        (op or {}).get('canonical_lifecycle')
        or (op or {}).get('lifecycle_state')
        or ''
    ).upper()
    period = str((op or {}).get('period') or '').lower()
    return bool((op or {}).get('market_hours')) or state in (
        'INDIA_MARKET_HOURS',
        'MARKET_ACTIVE',
        'LIVE',
    ) or period in ('market', 'market_hours', 'regular')


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or value == '':
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _ticker(row: dict[str, Any]) -> str:
    for key in ('symbol', 'ticker', 'nse_symbol', 'tradingsymbol', 'name'):
        value = str(row.get(key) or '').strip().upper()
        if value:
            return value
    return ''


def _rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in (
        'top_signals',
        'signals',
        'live_scanner',
        'stocks',
        'items',
        'opportunities',
        'top_opportunities',
    ):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    nested = payload.get('scanner') if isinstance(payload.get('scanner'), dict) else {}
    if nested:
        return _rows_from_payload(nested)
    return []


def _market_price_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    candidates: list[Any] = []
    for key in ('stocks', 'data', 'items', 'quotes', 'market_data'):
        value = payload.get(key)
        if isinstance(value, list):
            candidates.extend(value)
        elif isinstance(value, dict):
            candidates.extend(value.values())
    if not candidates and isinstance(payload.get('prices'), dict):
        candidates.extend(payload.get('prices', {}).values())
    out: dict[str, dict[str, Any]] = {}
    for item in candidates:
        if not isinstance(item, dict):
            continue
        sym = _ticker(item)
        if sym:
            out[sym] = item
    return out


def _score(row: dict[str, Any]) -> float:
    for key in ('score', 'confidence_score', 'strength_score', 'composite_score', 'rank_score'):
        if key in row:
            return _safe_float(row.get(key))
    strength = str(row.get('strength') or '').upper()
    if strength == 'ULTRA':
        return 90.0
    if strength == 'STRONG':
        return 80.0
    if strength:
        return 65.0
    return 50.0


def _candidate_from_row(row: dict[str, Any], prices: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    sym = _ticker(row)
    if not sym:
        return None
    price_row = prices.get(sym) or {}
    price = (
        row.get('price')
        or row.get('current_price')
        or row.get('last_price')
        or price_row.get('price')
        or price_row.get('last_price')
        or price_row.get('ltp')
    )
    volume_ratio = (
        row.get('volume_ratio')
        or row.get('relative_volume')
        or row.get('volume_spike')
        or price_row.get('volume_ratio')
    )
    change = (
        row.get('change_percent')
        or row.get('change_pct')
        or row.get('pct_change')
        or price_row.get('change_percent')
        or price_row.get('pChange')
    )
    return {
        'symbol': sym,
        'ticker': sym,
        'score': _score(row),
        'price': _safe_float(price, 0.0) or None,
        'change_percent': _safe_float(change, 0.0),
        'volume_ratio': _safe_float(volume_ratio, 0.0),
        'direction': str(row.get('direction') or row.get('bias') or 'WATCH').upper(),
        'action': str(row.get('action') or row.get('status') or 'WATCH').upper(),
        'source': 'live_lite_scanner',
        'reason': row.get('reason') or row.get('logic') or 'scanner price/volume refresh',
    }


def _is_avoid(row: dict[str, Any]) -> bool:
    text = ' '.join(
        str(row.get(k) or '')
        for k in ('action', 'status', 'direction', 'bias', 'risk', 'flag')
    ).upper()
    return any(token in text for token in ('AVOID', 'BEARISH', 'RISK', 'DOWNGRADE'))


def _optional_stale_warnings() -> list[str]:
    try:
        from backend.runtime.runtime_state import _load_intelligence_freshness

        rows = (_load_intelligence_freshness().get('rows') or {})
    except Exception:
        rows = {}
    warnings: list[str] = []
    for key in ('news', 'budget', 'theme', 'catalysts', 'aihub_brain', 'aihub_govt', 'aihub_market'):
        row = rows.get(key) or {}
        if row.get('stale') or row.get('status') in ('stale', 'missing'):
            label = row.get('label') or key
            age = row.get('age_display') or row.get('status') or 'unknown'
            warnings.append(f'{label} stale warning: {age}')
    return warnings


def _scanner_health() -> dict[str, Any]:
    try:
        from backend.runtime.scanner_heartbeat_monitor import evaluate_scanner_health

        health = evaluate_scanner_health(stall_minutes=LIVE_SCANNER_MAX_AGE_MINUTES) or {}
    except Exception:
        health = {}
    if health.get('age_minutes') is None:
        file_age = _file_age_minutes(SCANNER_FILE)
        if file_age is not None:
            health['age_minutes'] = file_age
            health['healthy'] = file_age < LIVE_SCANNER_MAX_AGE_MINUTES
            health['stalled'] = file_age >= LIVE_SCANNER_MAX_AGE_MINUTES
    return health


def publish_live_lite_snapshot(
    *,
    force: bool = False,
    reason: str = 'on_demand',
    snapshot_age_minutes: int | None = None,
) -> dict[str, Any]:
    """Publish a scanner-only live runtime snapshot; returns a compact result."""
    try:
        from backend.utils.market_hours import get_operational_status

        operational = get_operational_status() or {}
    except Exception:
        operational = {}
    live_market = _is_live_market(operational)
    if not live_market and not force:
        return {'ok': False, 'skipped': True, 'reason': 'market_not_live', 'ai_calls': 0}

    health = _scanner_health()
    scanner_age = health.get('age_minutes')
    scanner_stale = (
        scanner_age is None
        or bool(health.get('stalled'))
        or int(scanner_age) >= LIVE_SCANNER_MAX_AGE_MINUTES
    )
    if scanner_stale:
        print(
            f'[LIVE_LITE_SNAPSHOT] ai_calls=0 scanner_age={scanner_age} '
            f'snapshot_age={snapshot_age_minutes} status=scanner_stale',
            flush=True,
        )
        return {
            'ok': False,
            'skipped': True,
            'reason': 'scanner_stale',
            'ai_calls': 0,
            'scanner_age_minutes': scanner_age,
        }

    if not force and snapshot_age_minutes is not None:
        min_age = max(1, int(LIVE_LITE_MIN_INTERVAL_SECONDS / 60))
        if int(snapshot_age_minutes) < min_age:
            return {
                'ok': False,
                'skipped': True,
                'reason': 'snapshot_fresh_enough',
                'ai_calls': 0,
                'scanner_age_minutes': scanner_age,
            }

    scanner_payload = _load_json(SCANNER_FILE)
    market_payload = _load_json(ENRICHED_MARKET_FILE) or _load_json(MARKET_FILE)
    price_map = _market_price_map(market_payload)
    rows = _rows_from_payload(scanner_payload)
    candidates = [
        candidate
        for row in rows
        if not _is_avoid(row)
        for candidate in [_candidate_from_row(row, price_map)]
        if candidate
    ]
    candidates.sort(key=lambda r: _safe_float(r.get('score')), reverse=True)
    avoid_candidates = [
        candidate
        for row in rows
        if _is_avoid(row)
        for candidate in [_candidate_from_row(row, price_map)]
        if candidate
    ][:10]

    now_iso = _now_iso()
    snapshot_id = f'live_lite_{int(time.time())}'
    warnings = _optional_stale_warnings()
    freshness = {
        'fresh': True,
        'stale': False,
        'degraded': False,
        'age_minutes': 0,
        'age_display': '0m',
        'health_tier': 'lite from scanner',
        'status_label': 'fresh/lite from scanner',
        'source': 'live_lite_scanner',
        'live_lite_snapshot': True,
        'scanner_age_minutes': scanner_age,
        'live_scanner_stale_minutes': LIVE_SCANNER_MAX_AGE_MINUTES,
        'stale_intelligence_warnings': warnings,
        'suppress_confidence': False,
        'block_elite_outputs': False,
        'quality_score_penalty': 0.0,
        'ai_calls': 0,
    }
    lifecycle_state = 'INDIA_MARKET_HOURS'
    runtime_state = {
        'generated_at': now_iso,
        'authority': 'runtime_state',
        'primary_state': 'LIVE',
        'lifecycle': {
            'lifecycle_state': lifecycle_state,
            'lifecycle_display': 'Live market scanner-lite runtime',
            'market_session_open': True,
            'after_hours_mode': False,
            'suppress_trading_language': False,
        },
        'session': {
            'session_status': lifecycle_state,
            'session_display': 'India market hours',
            'market_session_open': True,
            'after_hours_mode': False,
        },
        'snapshot_freshness': freshness,
        'scanner_health': health,
        'pipeline': {'stages': {}, 'stalled_stages': [], 'any_stalled': False},
        'secondary_flags': {'live_lite_snapshot': True},
        'alert_eligibility': {
            'eligible': True,
            'execution_eligible': True,
            'watchlist_only': False,
            'block_reasons': [],
        },
        'intelligence_status': {
            'status': 'ready',
            'degraded': False,
            'elite_blocked': False,
            'health_tier': 'lite from scanner',
        },
        'operational': operational,
    }
    intelligence = {
        'snapshot_id': snapshot_id,
        'cycle_id': snapshot_id,
        'timestamp': now_iso,
        'source': 'live_lite_scanner',
        'top_opportunities': candidates[:10],
        'opportunities': candidates[:10],
        'risks_and_avoids': avoid_candidates,
        'canonical_opportunity_feed': {
            'source': 'live_lite_scanner',
            'top_count': len(candidates[:10]),
            'avoid_count': len(avoid_candidates),
        },
        'market_mood': {
            'status': 'live scanner-lite',
            'warnings': warnings,
        },
        'action_plan': 'Scanner-lite runtime refresh; confirm with fresh price and volume before action.',
    }
    payload = {
        'snapshot_id': snapshot_id,
        'active_snapshot_id': snapshot_id,
        'snapshot_version': int(time.time()),
        'generated_at': now_iso,
        'published_at': now_iso,
        '_committed_at': now_iso,
        'snapshot_generated_at': now_iso,
        'snapshot_built_at': now_iso,
        'market_session': lifecycle_state,
        'mode': lifecycle_state,
        'source': 'live_lite_scanner',
        'live_lite_snapshot': True,
        'ai_calls': 0,
        'freshness': freshness,
        'snapshot_freshness': freshness,
        'runtime_state': runtime_state,
        'top_opportunities': candidates[:10],
        'risk_list': avoid_candidates,
        'risks_and_avoids': avoid_candidates,
        'warnings': warnings,
        'intelligence': intelligence,
        'pipeline_health': {'stalled_stages': [], 'any_stalled': False},
        'metadata': {
            'reason': reason,
            'scanner_age_minutes': scanner_age,
            'input_snapshot_age_minutes': snapshot_age_minutes,
            'ai_calls': 0,
        },
    }

    atomic_write_json(CURRENT_SNAPSHOT_FILE, payload)
    atomic_write_json(RUNTIME_SNAPSHOT_CACHE, payload)
    try:
        from backend.intelligence.active_snapshot import sync_active_snapshot_from_market_snapshot

        sync_active_snapshot_from_market_snapshot(payload, source='live_lite_scanner')
    except Exception as exc:
        payload.setdefault('warnings', []).append(f'active_snapshot_sync_failed:{exc}')
    try:
        from backend.runtime.pipeline_stage_log import refresh_stages_on_snapshot_publish

        refresh_stages_on_snapshot_publish('live_lite_scanner')
    except Exception:
        pass

    print(
        f'[LIVE_LITE_SNAPSHOT] ai_calls=0 scanner_age={scanner_age} '
        f'snapshot_age={snapshot_age_minutes} status=ok',
        flush=True,
    )
    return {
        'ok': True,
        'skipped': False,
        'status': 'ok',
        'reason': reason,
        'ai_calls': 0,
        'scanner_age_minutes': scanner_age,
        'snapshot_age_minutes': snapshot_age_minutes,
        'current_snapshot_path': str(CURRENT_SNAPSHOT_FILE),
        'runtime_snapshot_path': str(RUNTIME_SNAPSHOT_CACHE),
        'candidate_count': len(candidates),
        'avoid_count': len(avoid_candidates),
    }


def maybe_publish_live_lite_snapshot(
    *,
    snapshot_age_minutes: int | None = None,
    reason: str = 'freshness_monitor',
) -> dict[str, Any]:
    return publish_live_lite_snapshot(
        force=False,
        reason=reason,
        snapshot_age_minutes=snapshot_age_minutes,
    )
