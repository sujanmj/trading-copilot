"""Safe runtime snapshot wrapper publisher — rebuilds GUI cache from existing data files."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.utils.config import DATA_DIR, RUNTIME_SNAPSHOT_CACHE, RUNTIME_DIR

STALE_HOURS = 2.0

WRAPPER_SOURCE_FILES = (
    DATA_DIR / 'active_snapshot.json',
    DATA_DIR / 'unified_intelligence.json',
    DATA_DIR / 'latest_market_data.json',
    DATA_DIR / 'scanner_data.json',
    DATA_DIR / 'stats_data.json',
    DATA_DIR / 'history_data.json',
    DATA_DIR / 'orchestrator_state.json',
    DATA_DIR / 'analysis_state.json',
    RUNTIME_DIR / 'current_snapshot.json',
)

DATA_AS_OF_FILES = (
    DATA_DIR / 'active_snapshot.json',
    DATA_DIR / 'unified_intelligence.json',
    DATA_DIR / 'latest_market_data.json',
    DATA_DIR / 'live_news_feed.json',
    DATA_DIR / 'news_feed.json',
)

TIMESTAMP_KEYS = (
    'intelligence_timestamp',
    'published_at',
    'snapshot_published_at',
    'generated_at',
    'updated_at',
    'last_updated',
    'timestamp',
    'collected_at',
)


def _now_iso() -> str:
    return datetime.now().isoformat()


def _parse_iso(raw: object) -> Optional[datetime]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _age_hours(dt: Optional[datetime]) -> Optional[float]:
    if dt is None:
        return None
    delta = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
    return round(max(0.0, delta.total_seconds()) / 3600.0, 2)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _embedded_timestamp(path: Path) -> Optional[datetime]:
    data = _load_json(path)
    for key in TIMESTAMP_KEYS:
        dt = _parse_iso(data.get(key))
        if dt is not None:
            return dt
    if path.is_file():
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return None


def _market_status_label() -> str:
    try:
        from backend.utils.market_hours import get_operational_status

        op = get_operational_status()
        period = str(op.get('period') or '')
        if op.get('market_hours') or period == 'pre_market':
            return 'open'
        if period in ('post_market', 'after_hours', 'night', 'weekend'):
            return 'closed'
    except Exception:
        pass
    return 'unknown'


def _collect_source_mtimes() -> list[float]:
    mtimes: list[float] = []
    for path in WRAPPER_SOURCE_FILES:
        if path.is_file():
            try:
                mtimes.append(path.stat().st_mtime)
            except Exception:
                pass
    return mtimes


def _compute_data_as_of() -> tuple[Optional[str], Optional[float]]:
    """Best-effort underlying intelligence/market timestamp (not package time)."""
    candidates: list[datetime] = []
    active = _load_json(DATA_DIR / 'active_snapshot.json')
    for key in ('intelligence_timestamp', 'published_at'):
        dt = _parse_iso(active.get(key))
        if dt is not None:
            candidates.append(dt)

    for path in DATA_AS_OF_FILES[1:]:
        dt = _embedded_timestamp(path)
        if dt is not None:
            candidates.append(dt)

    if not candidates:
        return None, None

    # Use the most recent underlying export as data-as-of anchor.
    best = max(candidates, key=lambda item: item.timestamp())
    return best.isoformat(), _age_hours(best)


def _compute_snapshot_id(package_generated_at: str, source_mtimes: list[float]) -> str:
    parts = [package_generated_at] + [f'{m:.6f}' for m in sorted(source_mtimes)]
    digest = hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()[:12]
    return f'snap_{digest}'


def _build_base_payload() -> dict[str, Any]:
    try:
        from backend.api.api_server import _build_gui_snapshot

        return _build_gui_snapshot()
    except Exception:
        pass
    try:
        from backend.api.api_server import _build_runtime_snapshot

        return _build_runtime_snapshot()
    except Exception as exc:
        return {
            'status': 'degraded',
            'validation_warnings': [f'publish_build_error: {exc}'],
            'generated_at': _now_iso(),
            'data': {},
            'exports': {},
            'panels': {},
            'market_snapshot': {},
        }


def _write_cache(payload: dict[str, Any]) -> None:
    RUNTIME_SNAPSHOT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_SNAPSHOT_CACHE.write_text(
        json.dumps(payload, indent=2, default=str) + '\n',
        encoding='utf-8',
    )


def publish_runtime_snapshot_wrapper(*, reason: str = 'local_refresh') -> dict[str, Any]:
    """
    Rebuild data/cache/runtime_snapshot.json from existing exports (no fake data).

    Sets package_generated_at (now), data_as_of (underlying), market_status, snapshot_id hash.
    """
    package_generated_at = _now_iso()
    source_mtimes = _collect_source_mtimes()
    data_as_of, data_age_hours = _compute_data_as_of()
    market_status = _market_status_label()
    market_closed = market_status == 'closed'

    payload = _build_base_payload()
    if not isinstance(payload, dict):
        payload = {}

    snapshot_id = _compute_snapshot_id(package_generated_at, source_mtimes)
    payload['snapshot_id'] = snapshot_id
    payload['active_snapshot_id'] = payload.get('active_snapshot_id') or snapshot_id
    payload['package_generated_at'] = package_generated_at
    payload['generated_at'] = package_generated_at
    payload['data_as_of'] = data_as_of
    payload['market_status'] = market_status

    underlying_stale = bool(
        data_age_hours is not None and float(data_age_hours) > STALE_HOURS and not market_closed
    )
    payload['freshness'] = {
        'stale': underlying_stale,
        'age_hours': data_age_hours,
        'package_age_hours': 0.0,
        'source': 'runtime_snapshot',
    }

    warnings: list[str] = list(payload.get('validation_warnings') or [])
    if market_closed and data_as_of:
        warnings.append('market_closed_data_as_of')
    payload['validation_warnings'] = warnings

    if payload.get('exports') is None and payload.get('data'):
        payload['exports'] = dict(payload['data'])
    elif payload.get('data') is None and payload.get('exports'):
        payload['data'] = dict(payload['exports'])

    try:
        from backend.runtime.snapshot_contract import wrap_runtime_snapshot_for_frontend

        payload = wrap_runtime_snapshot_for_frontend(payload, cache_path=RUNTIME_SNAPSHOT_CACHE)
    except Exception:
        payload['ok'] = True

    try:
        _write_cache(payload)
        ok = True
    except Exception as exc:
        ok = False
        return {
            'ok': False,
            'reason': reason,
            'error': str(exc),
            'snapshot_id': snapshot_id,
            'package_generated_at': package_generated_at,
        }

    return {
        'ok': ok,
        'reason': reason,
        'snapshot_id': snapshot_id,
        'package_generated_at': package_generated_at,
        'generated_at': package_generated_at,
        'data_as_of': data_as_of,
        'market_status': market_status,
        'freshness': payload['freshness'],
        'cache_path': str(RUNTIME_SNAPSHOT_CACHE),
    }
