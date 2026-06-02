"""
Per-tab AI Hub freshness from real source files (read-only).

Tabs: brain/runtime, govt, scan, mkt, global, news, tv, rdt, calib, journal
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.utils.config import DATA_DIR, RUNTIME_SNAPSHOT_CACHE, RUNTIME_DIR

STALE_HOURS = 2.0

TIMESTAMP_KEYS = (
    'package_generated_at',
    'generated_at',
    'intelligence_timestamp',
    'published_at',
    'updated_at',
    'last_updated',
    'timestamp',
    'generation_time',
    'exported_at',
    'collected_at',
)

TAB_FILES: dict[str, list[Path]] = {
    'brain': [
        RUNTIME_SNAPSHOT_CACHE,
        DATA_DIR / 'active_snapshot.json',
        DATA_DIR / 'unified_intelligence.json',
        RUNTIME_DIR / 'current_snapshot.json',
    ],
    'govt': [DATA_DIR / 'govt_intelligence.json'],
    'scan': [DATA_DIR / 'scanner_data.json', DATA_DIR / 'analysis_state.json'],
    'mkt': [
        DATA_DIR / 'latest_market_data.json',
        DATA_DIR / 'latest_market_data_memory_enriched.json',
    ],
    'global': [DATA_DIR / 'global_markets.json'],
    'news': [DATA_DIR / 'live_news_feed.json', DATA_DIR / 'news_feed.json'],
    'tv': [DATA_DIR / 'tv_intelligence.json', DATA_DIR / 'youtube_feed.json'],
    'rdt': [DATA_DIR / 'reddit_data.json'],
    'calib': [DATA_DIR / 'stats_data.json'],
    'journal': [DATA_DIR / 'history_data.json', DATA_DIR / 'analysis_explanations.json'],
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


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
    delta = _now_utc() - dt.astimezone(timezone.utc)
    return round(max(0.0, delta.total_seconds()) / 3600.0, 2)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _file_meta(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            'exists': False,
            'path': str(path),
            'timestamp': None,
            'age_hours': None,
            'basis': 'missing',
        }
    data = _load_json(path)
    embedded_dt: Optional[datetime] = None
    embedded_key: Optional[str] = None
    for key in TIMESTAMP_KEYS:
        dt = _parse_iso(data.get(key))
        if dt is not None:
            embedded_dt = dt
            embedded_key = key
            break
    mtime_dt = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    if embedded_dt is not None:
        return {
            'exists': True,
            'path': str(path),
            'timestamp': embedded_dt.isoformat(),
            'age_hours': _age_hours(embedded_dt),
            'basis': 'embedded',
            'timestamp_key': embedded_key,
        }
    return {
        'exists': True,
        'path': str(path),
        'timestamp': mtime_dt.isoformat(),
        'age_hours': _age_hours(mtime_dt),
        'basis': 'mtime',
        'timestamp_key': 'mtime',
    }


def _pick_freshest(paths: list[Path]) -> dict[str, Any]:
    candidates = [_file_meta(path) for path in paths]
    existing = [item for item in candidates if item.get('exists')]
    if not existing:
        return {
            'exists': False,
            'path': str(paths[0]) if paths else None,
            'timestamp': None,
            'age_hours': None,
            'basis': 'missing',
            'source_files': [str(p) for p in paths],
        }
    best = min(
        existing,
        key=lambda item: item.get('age_hours') if item.get('age_hours') is not None else float('inf'),
    )
    return {
        **best,
        'source_files': [str(p) for p in paths],
        'candidates': candidates,
    }


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


def _brain_tab() -> dict[str, Any]:
    cache_meta = _file_meta(RUNTIME_SNAPSHOT_CACHE)
    cache_data = _load_json(RUNTIME_SNAPSHOT_CACHE) if RUNTIME_SNAPSHOT_CACHE.is_file() else {}
    package_generated_at = cache_data.get('package_generated_at') or cache_data.get('generated_at')
    data_as_of = cache_data.get('data_as_of')
    package_age = _age_hours(_parse_iso(package_generated_at))
    data_age = _age_hours(_parse_iso(data_as_of))
    if data_age is None:
        underlying = _pick_freshest([
            DATA_DIR / 'active_snapshot.json',
            DATA_DIR / 'unified_intelligence.json',
            DATA_DIR / 'latest_market_data.json',
        ])
        data_as_of = underlying.get('timestamp')
        data_age = underlying.get('age_hours')

    market_status = cache_data.get('market_status') or _market_status_label()
    market_closed = market_status == 'closed'
    stale = bool(data_age is not None and float(data_age) > STALE_HOURS and not market_closed)

    return {
        'tab': 'brain',
        'package_generated_at': package_generated_at or cache_meta.get('timestamp'),
        'package_age_hours': package_age if package_age is not None else cache_meta.get('age_hours'),
        'data_as_of': data_as_of,
        'data_age_hours': data_age,
        'market_status': market_status,
        'stale': stale,
        'source_files': TAB_FILES['brain'],
        'cache_path': str(RUNTIME_SNAPSHOT_CACHE),
        'cache_exists': cache_meta.get('exists', False),
    }


def _simple_tab(tab: str) -> dict[str, Any]:
    meta = _pick_freshest(TAB_FILES[tab])
    age = meta.get('age_hours')
    return {
        'tab': tab,
        'timestamp': meta.get('timestamp'),
        'age_hours': age,
        'stale': bool(age is not None and float(age) > STALE_HOURS),
        'path': meta.get('path'),
        'basis': meta.get('basis'),
        'source_files': meta.get('source_files'),
        'exists': meta.get('exists', False),
    }


def get_aihub_tab_freshness_report() -> dict[str, Any]:
    """Return per-tab freshness from real local source files."""
    tabs = {
        'brain': _brain_tab(),
        'govt': _simple_tab('govt'),
        'scan': _simple_tab('scan'),
        'mkt': _simple_tab('mkt'),
        'global': _simple_tab('global'),
        'news': _simple_tab('news'),
        'tv': _simple_tab('tv'),
        'rdt': _simple_tab('rdt'),
        'calib': _simple_tab('calib'),
        'journal': _simple_tab('journal'),
    }
    return {
        'ok': True,
        'checked_at': _now_utc().isoformat(),
        'market_status': _market_status_label(),
        'tabs': tabs,
    }
