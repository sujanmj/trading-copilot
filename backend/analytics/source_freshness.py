"""
Source freshness and health report for local GUI/runtime data files.

Read-only inspection — never invents timestamps; uses embedded JSON fields or file mtime.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.utils.config import (
    DATA_DIR,
    RUNTIME_SNAPSHOT_CACHE,
    RUNTIME_DIR,
)
from backend.storage.market_memory_db import get_market_memory_path, get_market_memory_stats

STALE_HOURS = 2.0

TIMESTAMP_KEYS = (
    'last_updated',
    'updated_at',
    'generated_at',
    'snapshot_published_at',
    'published_at',
    'intelligence_timestamp',
    'timestamp',
    'checked_at',
)

FILE_MAP = {
    'prices': DATA_DIR / 'latest_market_data.json',
    'enriched_prices': DATA_DIR / 'latest_market_data_memory_enriched.json',
    'live_news': DATA_DIR / 'live_news_feed.json',
    'news': DATA_DIR / 'news_feed.json',
    'reddit': DATA_DIR / 'reddit_data.json',
    'global': DATA_DIR / 'global_markets.json',
    'govt': DATA_DIR / 'govt_intelligence.json',
    'orchestrator': DATA_DIR / 'orchestrator_state.json',
    'analysis': DATA_DIR / 'analysis_state.json',
    'market_source_status': DATA_DIR / 'market_source_status.json',
    'advisor_report': DATA_DIR / 'market_memory_advisor_report.json',
    'runtime_cache': RUNTIME_SNAPSHOT_CACHE,
    'active_snapshot': DATA_DIR / 'active_snapshot.json',
    'current_snapshot': RUNTIME_DIR / 'current_snapshot.json',
    'unified_intelligence': DATA_DIR / 'unified_intelligence.json',
    'external_evidence': DATA_DIR / 'external_evidence_latest.json',
}


def _parse_iso_timestamp(raw: object) -> Optional[datetime]:
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


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _age_hours_from_dt(dt: Optional[datetime]) -> Optional[float]:
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


def _embedded_timestamp(path: Path) -> tuple[Optional[datetime], Optional[str]]:
    data = _load_json(path)
    for key in TIMESTAMP_KEYS:
        dt = _parse_iso_timestamp(data.get(key))
        if dt is not None:
            return dt, key
    return None, None


def _file_freshness(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            'exists': False,
            'path': str(path),
            'age_hours': None,
            'timestamp': None,
            'timestamp_key': None,
            'basis': 'missing',
        }

    embedded_dt, key = _embedded_timestamp(path)
    mtime_dt = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    if embedded_dt is not None:
        return {
            'exists': True,
            'path': str(path),
            'age_hours': _age_hours_from_dt(embedded_dt),
            'timestamp': embedded_dt.isoformat(),
            'timestamp_key': key,
            'basis': 'embedded',
        }

    return {
        'exists': True,
        'path': str(path),
        'age_hours': _age_hours_from_dt(mtime_dt),
        'timestamp': mtime_dt.isoformat(),
        'timestamp_key': 'mtime',
        'basis': 'mtime',
    }


def _pick_freshest(paths: list[Path]) -> dict[str, Any]:
    candidates = [_file_freshness(path) for path in paths if path]
    existing = [item for item in candidates if item.get('exists')]
    if not existing:
        return {
            'exists': False,
            'path': str(paths[0]) if paths else None,
            'age_hours': None,
            'timestamp': None,
            'timestamp_key': None,
            'basis': 'missing',
            'candidates': candidates,
        }
    best = min(existing, key=lambda item: item.get('age_hours') if item.get('age_hours') is not None else float('inf'))
    best = dict(best)
    best['candidates'] = candidates
    return best


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


def _market_closed() -> bool:
    return _market_status_label() == 'closed'


def _freshness_status(age_hours: Optional[float], *, closed_market: bool = False) -> str:
    if closed_market:
        return 'closed-market'
    if age_hours is None:
        return 'missing'
    if age_hours > STALE_HOURS:
        return 'stale'
    return 'fresh'


def _runtime_snapshot_freshness() -> dict[str, Any]:
    paths = [FILE_MAP['runtime_cache'], FILE_MAP['active_snapshot'], FILE_MAP['current_snapshot']]
    for path in paths:
        meta = _file_freshness(path)
        if meta.get('exists'):
            meta['selected_path'] = str(path)
            return meta
    return {
        'exists': False,
        'path': str(FILE_MAP['runtime_cache']),
        'age_hours': None,
        'timestamp': None,
        'timestamp_key': None,
        'basis': 'missing',
        'selected_path': None,
    }


def _news_freshness() -> dict[str, Any]:
    return _pick_freshest([FILE_MAP['live_news'], FILE_MAP['news']])


def _reddit_only_news(news_meta: dict[str, Any], reddit_meta: dict[str, Any]) -> bool:
    news_stale = (
        not news_meta.get('exists')
        or news_meta.get('age_hours') is None
        or float(news_meta.get('age_hours') or 0) > STALE_HOURS
    )
    if not news_stale:
        news_data = _load_json(Path(news_meta.get('path') or FILE_MAP['news']))
        articles = int(news_data.get('total_articles') or len(news_data.get('articles') or []) or 0)
        if articles >= 5:
            return False

    if not reddit_meta.get('exists'):
        return False

    reddit_data = _load_json(Path(reddit_meta.get('path') or FILE_MAP['reddit']))
    posts = int(reddit_data.get('total_posts_analyzed') or len(reddit_data.get('posts') or []) or 0)
    if posts <= 0:
        return False

    reddit_age = reddit_meta.get('age_hours')
    news_age = news_meta.get('age_hours')
    if reddit_age is None:
        return False
    if news_age is None:
        return True
    return float(reddit_age) <= float(news_age) + 0.01


def _ai_package_freshness() -> dict[str, Any]:
    """AI package age from runtime snapshot / unified intelligence — never masked as fresh when old."""
    cache_meta = _file_freshness(FILE_MAP['runtime_cache'])
    cache_data = _load_json(FILE_MAP['runtime_cache']) if FILE_MAP['runtime_cache'].is_file() else {}
    package_ts = (
        cache_data.get('package_generated_at')
        or cache_data.get('generated_at')
        or cache_meta.get('timestamp')
    )
    package_dt = _parse_iso_timestamp(package_ts)
    package_age = _age_hours_from_dt(package_dt)
    if package_age is None:
        unified_meta = _file_freshness(FILE_MAP['unified_intelligence'])
        package_ts = unified_meta.get('timestamp')
        package_dt = _parse_iso_timestamp(package_ts)
        package_age = unified_meta.get('age_hours')

    status = _freshness_status(package_age, closed_market=False)
    return {
        'status': status,
        'age_hours': package_age,
        'timestamp': package_dt.isoformat() if package_dt else package_ts,
        'path': str(FILE_MAP['runtime_cache']),
        'basis': cache_meta.get('basis'),
        'exists': bool(cache_meta.get('exists') or FILE_MAP['unified_intelligence'].is_file()),
    }


def _external_evidence_freshness() -> dict[str, Any]:
    meta = _file_freshness(FILE_MAP['external_evidence'])
    data = _load_json(FILE_MAP['external_evidence'])
    age_hours = meta.get('age_hours')
    return {
        'status': _freshness_status(age_hours, closed_market=False),
        'age_hours': age_hours,
        'timestamp': meta.get('timestamp'),
        'path': meta.get('path'),
        'basis': meta.get('basis'),
        'exists': bool(meta.get('exists')),
        'items': int(data.get('total_items') or len(data.get('items') or []) or 0),
        'broker_candidates': int(data.get('broker_candidates') or 0),
    }


def _market_memory_freshness() -> dict[str, Any]:
    db_path = get_market_memory_path()
    db_meta = _file_freshness(db_path)
    advisor_meta = _file_freshness(FILE_MAP['advisor_report'])
    stats = get_market_memory_stats()

    latest_prediction_ts: Optional[str] = None
    latest_outcome_ts: Optional[str] = None
    if db_path.is_file():
        try:
            conn = sqlite3.connect(str(db_path), timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    'SELECT MAX(timestamp) AS ts FROM predictions'
                ).fetchone()
                latest_prediction_ts = row['ts'] if row and row['ts'] else None
                row = conn.execute(
                    'SELECT MAX(resolved_at) AS ts FROM outcomes'
                ).fetchone()
                latest_outcome_ts = row['ts'] if row and row['ts'] else None
            finally:
                conn.close()
        except Exception:
            pass

    pred_age = _age_hours_from_dt(_parse_iso_timestamp(latest_prediction_ts))
    outcome_age = _age_hours_from_dt(_parse_iso_timestamp(latest_outcome_ts))
    content_ages = [value for value in (pred_age, outcome_age, db_meta.get('age_hours')) if value is not None]
    age_hours = min(content_ages) if content_ages else db_meta.get('age_hours')

    status = _freshness_status(age_hours)
    if not db_meta.get('exists'):
        status = 'missing'

    return {
        'status': status,
        'age_hours': age_hours,
        'file': db_path.name,
        'path': str(db_path),
        'timestamp': db_meta.get('timestamp'),
        'basis': db_meta.get('basis'),
        'predictions': int(stats.get('predictions') or 0),
        'outcomes': int(stats.get('outcomes') or 0),
        'latest_prediction_timestamp': latest_prediction_ts,
        'latest_outcome_timestamp': latest_outcome_ts,
        'latest_prediction_age_hours': pred_age,
        'latest_outcome_age_hours': outcome_age,
        'advisor_report_age_hours': advisor_meta.get('age_hours'),
        'advisor_report_timestamp': advisor_meta.get('timestamp'),
    }


def _source_block(
    key: str,
    meta: dict[str, Any],
    *,
    closed_market: bool = False,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    age_hours = meta.get('age_hours')
    block = {
        'status': _freshness_status(age_hours, closed_market=closed_market and key == 'prices'),
        'age_hours': age_hours,
        'file': Path(meta.get('path') or '').name or None,
        'path': meta.get('path'),
        'timestamp': meta.get('timestamp'),
        'timestamp_key': meta.get('timestamp_key'),
        'basis': meta.get('basis'),
        'exists': bool(meta.get('exists')),
    }
    if extra:
        block.update(extra)
    return block


def get_source_freshness_report() -> dict[str, Any]:
    """Inspect local data files and return freshness/source-health report."""
    runtime_meta = _runtime_snapshot_freshness()
    prices_meta = _file_freshness(FILE_MAP['prices'])
    enriched_meta = _file_freshness(FILE_MAP['enriched_prices'])
    news_meta = _news_freshness()
    reddit_meta = _file_freshness(FILE_MAP['reddit'])
    global_meta = _file_freshness(FILE_MAP['global'])
    govt_meta = _file_freshness(FILE_MAP['govt'])
    market_closed = _market_closed()
    market_status = _market_status_label()

    prices_data = _load_json(FILE_MAP['prices'])
    news_data = _load_json(Path(news_meta.get('path') or FILE_MAP['news']))
    reddit_data = _load_json(FILE_MAP['reddit'])
    global_data = _load_json(FILE_MAP['global'])
    govt_data = _load_json(FILE_MAP['govt'])
    source_status = _load_json(FILE_MAP['market_source_status'])

    runtime_age = runtime_meta.get('age_hours')
    news_age = news_meta.get('age_hours')
    latest_market_data_age = prices_meta.get('age_hours')
    enriched_price_age = enriched_meta.get('age_hours')

    warnings: list[str] = []
    if market_closed:
        warnings.append('market_closed')
    if runtime_age is not None and float(runtime_age) > STALE_HOURS:
        warnings.append('runtime_snapshot_stale')
    elif runtime_age is None and not runtime_meta.get('exists'):
        warnings.append('runtime_snapshot_stale')
    if news_age is not None and float(news_age) > STALE_HOURS:
        warnings.append('news_feed_stale')
    elif not news_meta.get('exists'):
        warnings.append('news_feed_stale')
    if _reddit_only_news(news_meta, reddit_meta):
        warnings.append('reddit_only_news')

    ai_package = _ai_package_freshness()
    external_evidence = _external_evidence_freshness()
    if ai_package.get('status') == 'stale':
        warnings.append('ai_package_stale')
    if external_evidence.get('status') == 'stale':
        warnings.append('external_evidence_stale')
    if market_closed and (
        'news_feed_stale' in warnings
        or 'runtime_snapshot_stale' in warnings
        or 'ai_package_stale' in warnings
    ):
        warnings.append('refresh_intelligence_before_next_session')

    safe_to_use = (
        'runtime_snapshot_stale' not in warnings
        and 'news_feed_stale' not in warnings
        and 'ai_package_stale' not in warnings
    )

    return {
        'ok': True,
        'checked_at': _now_utc().isoformat(),
        'market_status': market_status,
        'market_closed': market_closed,
        'safe_to_use': safe_to_use,
        'runtime_snapshot_age_hours': runtime_age,
        'latest_market_data_age_hours': latest_market_data_age,
        'enriched_price_age_hours': enriched_price_age,
        'news_age_hours': news_age,
        'sources': {
            'prices': _source_block(
                'prices',
                prices_meta,
                closed_market=market_closed,
                extra={
                    'symbols_ok': prices_data.get('symbols_ok'),
                    'market_period': prices_data.get('market_period') or source_status.get('market_period'),
                    'active_source': source_status.get('active_source') or prices_data.get('source_meta', {}).get('primary_source'),
                    'degraded': source_status.get('degraded'),
                },
            ),
            'news': _source_block(
                'news',
                news_meta,
                extra={
                    'total_articles': news_data.get('total_articles') or len(news_data.get('articles') or []),
                    'feeds_ok': news_data.get('feeds_ok'),
                },
            ),
            'reddit': _source_block(
                'reddit',
                reddit_meta,
                extra={
                    'total_posts_analyzed': reddit_data.get('total_posts_analyzed'),
                    'market_mood': (reddit_data.get('market_mood') or {}).get('sentiment'),
                },
            ),
            'global': _source_block(
                'global',
                global_meta,
                extra={
                    'sentiment': global_data.get('sentiment'),
                    'coverage': global_data.get('coverage'),
                },
            ),
            'govt': _source_block(
                'govt',
                govt_meta,
                extra={
                    'total_items': govt_data.get('total_items') or len(govt_data.get('items') or []),
                },
            ),
            'market_memory': _market_memory_freshness(),
            'ai_package': ai_package,
            'external_evidence': external_evidence,
        },
        'runtime_snapshot': {
            'status': _freshness_status(runtime_age),
            'age_hours': runtime_age,
            'path': runtime_meta.get('selected_path') or runtime_meta.get('path'),
            'timestamp': runtime_meta.get('timestamp'),
            'basis': runtime_meta.get('basis'),
        },
        'ai_package_age_hours': ai_package.get('age_hours'),
        'external_evidence_age_hours': external_evidence.get('age_hours'),
        'warnings': warnings,
    }
