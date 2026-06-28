"""
Canonical runtime state — SINGLE source of truth for orchestration surfaces.

Authority for: lifecycle, regime, market phase, quality score, win rate,
snapshot freshness, provider health, prediction counts, telegram metrics,
intelligence status.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pytz

IST = pytz.timezone('Asia/Kolkata')

_cache_lock = threading.Lock()
_cached_state: Optional[dict] = None
_cached_at: float = 0.0
_CACHE_TTL_SECONDS = 3.0

PRIMARY_RUNTIME_STATES = frozenset({'LIVE', 'AFTER_HOURS', 'DEGRADED', 'RECOVERING'})

def _source_files() -> Dict[str, str]:
    from backend.runtime.feed_registry import feed_files
    return feed_files()


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _load_regime() -> Dict[str, Any]:
    raw = ''
    try:
        from backend.utils.config import ANALYSIS_STATE_FILE
        if ANALYSIS_STATE_FILE.exists():
            import json
            state = json.loads(ANALYSIS_STATE_FILE.read_text(encoding='utf-8'))
            raw = str(state.get('last_regime') or '')
    except Exception:
        pass
    if not raw:
        try:
            from backend.ai.pipeline_observability import get_observability_summary
            obs = get_observability_summary() or {}
            raw = str(obs.get('market_regime') or '')
        except Exception:
            pass
    try:
        from backend.intelligence.regime_normalizer import normalize_regime_payload
        return normalize_regime_payload({'regime': raw})
    except Exception:
        return {'regime_internal': raw, 'regime_display': raw or 'Monitoring regime formation'}


def _load_metrics() -> Dict[str, Any]:
    try:
        from backend.lifecycle.unified_metrics import get_unified_snapshot
        from backend.metrics.canonical_metrics import build_canonical_metrics
        snap = get_unified_snapshot() or {}
        sections = snap.get('metric_sections') or {}
        base = build_canonical_metrics(snap.get('metrics_all_time') or {})
        if sections:
            base['sections'] = sections
        return base
    except Exception:
        return {}


def _load_prediction_counts(metrics: dict) -> Dict[str, Any]:
    return {
        'prediction_total': int(metrics.get('prediction_total') or metrics.get('total_predictions') or 0),
        'evaluated': int(metrics.get('evaluated') or metrics.get('total_evaluated') or 0),
        'pending': int(metrics.get('pending') or 0),
        'resolved': int(metrics.get('resolved') or 0),
        'wins': int(metrics.get('wins') or 0),
        'losses': int(metrics.get('losses') or 0),
        'partials': int(metrics.get('partials') or 0),
        'neutral': int(metrics.get('neutral') or metrics.get('neutralized') or 0),
        'neutralized': int(metrics.get('neutralized') or metrics.get('neutral') or 0),
        'expired': int(metrics.get('expired') or 0),
    }


def _load_provider_health() -> Dict[str, Any]:
    try:
        from backend.analytics.provider_analytics import get_ai_runtime_stats_payload
        rt = get_ai_runtime_stats_payload() or {}
        return {
            'status': rt.get('status', 'unknown'),
            'degraded_mode': rt.get('degraded_mode'),
            'ai_uptime_pct': rt.get('ai_uptime_pct'),
            'providers': rt.get('providers') or {},
        }
    except Exception:
        return {'status': 'unknown', 'degraded_mode': None}


def _load_telegram_metrics() -> Dict[str, Any]:
    try:
        from backend.utils.config import DATA_DIR
        path = DATA_DIR / 'telegram_alert_observability.json'
        if path.exists():
            import json
            data = json.loads(path.read_text(encoding='utf-8'))
            obs = data.get('telegram_alerts') or data
            return {
                'alerts_sent_today': int(obs.get('alerts_sent_today') or 0),
                'suppressed_today': int(obs.get('suppressed_today') or 0),
                'duplicate_blocks': int(obs.get('duplicate_blocks') or 0),
                'low_confidence_skips': int(obs.get('low_confidence_skips') or 0),
            }
    except Exception:
        pass
    return {
        'alerts_sent_today': 0,
        'suppressed_today': 0,
        'duplicate_blocks': 0,
        'low_confidence_skips': 0,
    }


def _load_quality_score(freshness: dict) -> Dict[str, Any]:
    base = 0.75
    try:
        from backend.ai.pipeline_observability import get_observability_summary
        obs = get_observability_summary() or {}
        q = obs.get('last_quality_score') or obs.get('intelligence_quality_score')
        if q is not None:
            base = float(q)
    except Exception:
        pass
    penalty = float(freshness.get('quality_score_penalty') or 0)
    score = max(0.0, min(1.0, base - penalty))
    return {
        'quality_score': round(score, 3),
        'quality_display': f'{score * 100:.0f}%' if score else 'Confidence building',
        'suppressed': bool(freshness.get('suppress_confidence')),
    }


def _load_collector_activity(freshness: dict) -> Dict[str, Any]:
    """Collector heartbeats — separate from market lifecycle."""
    try:
        from backend.runtime.snapshot_freshness_monitor import _load_heartbeats
        hb = _load_heartbeats()
        sources = hb.get('sources') or {}
        active = sum(1 for s in sources.values() if s.get('status') == 'ok')
        return {
            'collectors_active': bool(freshness.get('collectors_active', active > 0)),
            'collector_count': len(sources),
            'collector_ok_count': active,
            'collector_issues': freshness.get('collector_issues') or [],
        }
    except Exception:
        return {
            'collectors_active': bool(freshness.get('collectors_active')),
            'collector_count': 0,
            'collector_ok_count': 0,
            'collector_issues': freshness.get('collector_issues') or [],
        }


def _load_session_status(lifecycle: dict, operational: dict) -> Dict[str, Any]:
    lc_state = lifecycle.get('lifecycle_state')
    return {
        'session_status': lc_state,
        'session_display': lifecycle.get('lifecycle_display'),
        'market_session_open': bool(lifecycle.get('market_session_open')),
        'after_hours_mode': bool(lifecycle.get('after_hours_mode')),
        'suppress_trading_language': bool(lifecycle.get('suppress_trading_language')),
        'session_message': lifecycle.get('session_message') or operational.get('display_message'),
        'operational_mode': operational.get('operational_mode'),
    }


def _load_intelligence_status(freshness: dict) -> Dict[str, Any]:
    stale = bool(freshness.get('stale'))
    degraded = bool(freshness.get('degraded'))
    tier = freshness.get('health_tier') or ('stale' if stale else 'healthy')
    if stale or tier == 'stale':
        return {
            'status': 'degraded',
            'message': 'Snapshot stale — intelligence confidence suppressed',
            'degraded': True,
            'elite_blocked': True,
            'health_tier': tier,
        }
    if degraded or tier == 'aging':
        return {
            'status': 'degraded' if degraded else 'aging',
            'message': 'Snapshot aging — awaiting fresh cycle' if tier == 'aging' else 'Partial degradation — awaiting fresh cycle',
            'degraded': degraded,
            'elite_blocked': bool(freshness.get('block_elite_outputs')),
            'health_tier': tier,
        }
    return {
        'status': 'ready',
        'message': None,
        'degraded': False,
        'elite_blocked': False,
        'health_tier': tier,
    }


def _load_scheduler_phase(lifecycle: dict, operational: dict) -> Dict[str, Any]:
    pipeline = lifecycle.get('pipeline_status')
    orch_mode = operational.get('orchestrator_mode')
    phase = pipeline or operational.get('operational_mode') or 'unknown'
    return {
        'phase': phase,
        'pipeline_status': pipeline,
        'orchestrator_mode': orch_mode,
        'market_period': operational.get('period'),
    }


def _load_ai_state(provider_health: dict) -> Dict[str, Any]:
    return {
        'status': provider_health.get('status', 'unknown'),
        'degraded_mode': provider_health.get('degraded_mode'),
        'ai_uptime_pct': provider_health.get('ai_uptime_pct'),
        'providers': provider_health.get('providers') or {},
    }


def _load_pipeline_status(
    freshness: dict,
    lifecycle: dict,
    operational: Optional[dict] = None,
) -> Dict[str, Any]:
    try:
        from backend.runtime.pipeline_stage_log import get_pipeline_stage_summary
        age = freshness.get('age_minutes')
        operational = operational or {}
        lifecycle_state = str(lifecycle.get('lifecycle_state') or '').upper()
        period = str(operational.get('period') or '').lower()
        after_hours = (
            bool(lifecycle.get('after_hours_mode'))
            or bool(operational.get('expect_quiet_collectors'))
            or bool(operational.get('after_hours_mode'))
            or lifecycle_state in ('WEEKEND', 'HOLIDAY')
            or period in ('weekend', 'holiday')
        )
        return get_pipeline_stage_summary(
            snapshot_age_minutes=age,
            after_hours=after_hours,
        )
    except Exception:
        return {'stages': {}, 'stalled_stages': [], 'any_stalled': False}


def _load_scanner_health() -> Dict[str, Any]:
    try:
        from backend.runtime.scanner_heartbeat_monitor import evaluate_scanner_health
        return evaluate_scanner_health()
    except Exception:
        return {'healthy': True, 'display': 'Scanner: unknown'}


def _load_overnight_posture() -> Dict[str, Any]:
    try:
        from backend.intelligence.india_next_open_engine import build_india_next_open_report
        from backend.utils.config import DATA_DIR
        import json
        global_path = DATA_DIR / 'global_markets.json'
        payload = {}
        if global_path.exists():
            payload = json.loads(global_path.read_text(encoding='utf-8'))
        report = build_india_next_open_report(payload if isinstance(payload, dict) else {})
        return {
            'india_open_bias': report.get('india_open_bias'),
            'risk_score': report.get('risk_score'),
            'gap_probability': report.get('gap_probability'),
        }
    except Exception:
        return {}


def _map_primary_runtime_state(
    lifecycle: dict,
    operational: dict,
    freshness: dict,
    scanner_health: dict,
    pipeline: dict,
) -> str:
    """Canonical GUI/Telegram primary state — four values only."""
    orch = str(operational.get('orchestrator_mode') or '').upper()
    if orch == 'RECOVERING':
        return 'RECOVERING'

    lifecycle_state = str(lifecycle.get('lifecycle_state') or '').upper()
    period = str(operational.get('period') or '').lower()
    after_hours = (
        bool(lifecycle.get('after_hours_mode'))
        or bool(operational.get('after_hours_mode'))
        or bool(operational.get('expect_quiet_collectors'))
        or lifecycle_state in ('AFTER_HOURS', 'POST_MARKET', 'WEEKEND', 'HOLIDAY')
        or period in ('post_market', 'after_hours', 'night', 'weekend', 'holiday')
    )
    age = freshness.get('age_minutes')
    try:
        age_n = int(age) if age is not None else None
    except (TypeError, ValueError):
        age_n = None

    closed_threshold = int(freshness.get('closed_market_stale_threshold_minutes') or 360)
    strict_age_degraded = age_n is not None and age_n >= 15
    if after_hours and age_n is not None and age_n < closed_threshold:
        strict_age_degraded = False
    snapshot_degraded = bool(freshness.get('degraded')) or strict_age_degraded
    pipeline_stalled = bool(pipeline.get('any_stalled'))
    scanner_ok = bool(scanner_health.get('healthy', True)) and not scanner_health.get('stalled')
    if age_n is not None and age_n < 15 and not pipeline_stalled:
        scanner_ok = True

    if after_hours:
        return 'DEGRADED' if snapshot_degraded else 'AFTER_HOURS'

    if snapshot_degraded or pipeline_stalled:
        return 'DEGRADED'

    if age_n is not None and age_n < 5 and scanner_ok and not pipeline_stalled:
        return 'LIVE'

    if age_n is not None and age_n < 15 and scanner_ok and not pipeline_stalled:
        return 'LIVE'

    if age_n is None and not pipeline_stalled and scanner_ok:
        return 'LIVE'

    return 'DEGRADED'


def _load_secondary_flags(
    freshness: dict,
    scanner_health: dict,
    stall_report: dict,
) -> Dict[str, bool]:
    issues = stall_report.get('issues') or []
    return {
        'stale_snapshot': bool(freshness.get('stale')),
        'closed_market_snapshot_aging': bool(freshness.get('closed_market_aging')),
        'scanner_stalled': bool(scanner_health.get('stalled')),
        'cache_only': any('export:' in str(i) for i in issues),
    }


def _file_age_seconds(filename: str) -> Optional[float]:
    try:
        from backend.utils.config import DATA_DIR
        path = DATA_DIR / filename
        if not path.exists():
            return None
        return max(0.0, time.time() - path.stat().st_mtime)
    except Exception:
        return None


def _load_source_freshness(operational: dict) -> Dict[str, Any]:
    """Per-feed export ages for /status (mirrors API health source_status)."""
    from backend.utils.market_hours import classify_source_freshness, get_watchdog_config

    period = str(operational.get('period') or 'market')
    threshold = int(operational.get('stale_threshold_seconds') or 7200)
    try:
        threshold = int((get_watchdog_config() or {}).get('stale_threshold_seconds') or threshold)
    except Exception:
        pass

    rows = {}
    for key, filename in _source_files().items():
        age = _file_age_seconds(filename)
        if age is None:
            rows[key] = {'status': 'missing', 'age_seconds': None, 'age_display': 'missing', 'stale': True}
            continue
        status_name, _unhealthy = classify_source_freshness(age, threshold, period)
        stale = status_name in ('stale', 'missing') or (age > threshold and status_name not in ('idle', 'ok'))
        if age < 60:
            age_display = f'{int(age)}s'
        elif age < 3600:
            age_display = f'{int(age // 60)}m'
        else:
            age_display = f'{int(age // 3600)}h'
        rows[key] = {
            'status': status_name,
            'age_seconds': int(age),
            'age_display': age_display,
            'stale': stale,
            'file': filename,
        }
    return rows


def _load_brain_age_display() -> Dict[str, Any]:
    try:
        from backend.intelligence.active_snapshot import get_active_snapshot_meta
        meta = get_active_snapshot_meta() or {}
        age_m = meta.get('age_minutes')
        return {
            'age_minutes': age_m,
            'age_display': meta.get('age_display') or (f'{age_m}m' if age_m is not None else '—'),
            'stale': bool(meta.get('stale')),
        }
    except Exception:
        return {'age_display': '—', 'stale': False}


_INTELLIGENCE_TIMESTAMP_KEYS = (
    'refreshed_at',
    'cache_refreshed_at',
    'package_generated_at',
    'generated_at',
    'updated_at',
    'last_updated',
    'timestamp',
    'published_at',
    'collected_at',
)


def _parse_intelligence_timestamp(raw: object) -> Optional[datetime]:
    text = str(raw or '').strip()
    if not text:
        return None
    try:
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = IST.localize(parsed)
        return parsed.astimezone(IST)
    except Exception:
        return None


def _age_seconds_from_dt(dt: Optional[datetime]) -> Optional[float]:
    if dt is None:
        return None
    try:
        return max(0.0, (datetime.now(IST) - dt.astimezone(IST)).total_seconds())
    except Exception:
        return None


def _age_display_from_seconds(age_seconds: Optional[float]) -> str:
    if age_seconds is None:
        return 'missing'
    if age_seconds < 60:
        return f'{int(age_seconds)}s'
    if age_seconds < 3600:
        return f'{int(age_seconds // 60)}m'
    hours = age_seconds / 3600
    if hours < 24:
        return f'{hours:.1f}h'
    return f'{int(hours)}h'


def _load_json_payload(path: Path) -> dict:
    try:
        if not path.is_file():
            return {}
        payload = json.loads(path.read_text(encoding='utf-8'))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _cache_row(
    label: str,
    path: Path,
    *,
    timestamp_keys: tuple[str, ...] = _INTELLIGENCE_TIMESTAMP_KEYS,
    stale_after_seconds: int = 24 * 3600,
) -> Dict[str, Any]:
    if not path.is_file():
        return {
            'label': label,
            'status': 'missing',
            'age_seconds': None,
            'age_display': 'missing',
            'stale': True,
            'file': str(path),
            'reason': 'cache file missing',
        }

    payload = _load_json_payload(path)
    timestamp: Optional[datetime] = None
    timestamp_key = ''
    for key in timestamp_keys:
        timestamp = _parse_intelligence_timestamp(payload.get(key))
        if timestamp is not None:
            timestamp_key = key
            break
    if timestamp is None:
        try:
            timestamp = datetime.fromtimestamp(path.stat().st_mtime, IST)
            timestamp_key = 'mtime'
        except OSError:
            timestamp = None

    age_seconds = _age_seconds_from_dt(timestamp)
    stale = bool(age_seconds is None or age_seconds > stale_after_seconds)
    if age_seconds is None:
        status = 'missing'
    elif stale:
        status = 'stale'
    elif age_seconds > 6 * 3600:
        status = 'partial'
    else:
        status = 'fresh'
    return {
        'label': label,
        'status': status,
        'age_seconds': int(age_seconds) if age_seconds is not None else None,
        'age_display': _age_display_from_seconds(age_seconds),
        'timestamp': timestamp.isoformat() if timestamp is not None else None,
        'timestamp_key': timestamp_key,
        'stale': stale,
        'file': str(path),
    }


def _freshest_cache_row(label: str, paths: tuple[Path, ...]) -> Dict[str, Any]:
    rows = [_cache_row(label, path) for path in paths]
    existing = [row for row in rows if row.get('status') != 'missing']
    if not existing:
        row = rows[0] if rows else {'status': 'missing', 'age_seconds': None}
        return {**row, 'label': label, 'source_files': [str(p) for p in paths]}
    best = min(
        existing,
        key=lambda row: row.get('age_seconds') if row.get('age_seconds') is not None else float('inf'),
    )
    return {**best, 'label': label, 'source_files': [str(p) for p in paths], 'candidates': rows}


def _cache_mtime_row(
    label: str,
    path: Path,
    *,
    stale_after_seconds: int = 24 * 3600,
) -> Dict[str, Any]:
    if not path.is_file():
        return {
            'label': label,
            'status': 'missing',
            'age_seconds': None,
            'age_display': 'missing',
            'stale': True,
            'file': str(path),
            'reason': 'cache file missing',
        }
    try:
        timestamp = datetime.fromtimestamp(path.stat().st_mtime, IST)
    except OSError:
        timestamp = None
    age_seconds = _age_seconds_from_dt(timestamp)
    stale = bool(age_seconds is None or age_seconds > stale_after_seconds)
    return {
        'label': label,
        'status': 'stale' if stale else ('partial' if age_seconds and age_seconds > 6 * 3600 else 'fresh'),
        'age_seconds': int(age_seconds) if age_seconds is not None else None,
        'age_display': _age_display_from_seconds(age_seconds),
        'timestamp': timestamp.isoformat() if timestamp is not None else None,
        'timestamp_key': 'mtime',
        'stale': stale,
        'file': str(path),
    }


def _aihub_cache_row(label: str, path: Path, tab_meta: dict | None = None) -> Dict[str, Any]:
    row = _cache_mtime_row(label, path, stale_after_seconds=24 * 3600)
    meta = tab_meta or {}
    source_age_h = meta.get('data_age_hours') if 'data_age_hours' in meta else meta.get('age_hours')
    if source_age_h is not None:
        try:
            row['source_age_display'] = _age_display_from_seconds(float(source_age_h) * 3600)
        except (TypeError, ValueError):
            pass
    if meta.get('stale') and not row.get('stale'):
        row['source_status'] = 'underlying_source_stale'
        row['reason'] = 'AIHub cache refreshed; underlying source is older than tab SLA'
    return row


def _theme_catalyst_cache_row() -> Dict[str, Any]:
    try:
        from backend.analytics.theme_baskets import BASKETS_FILE
    except Exception:
        from backend.storage.data_paths import get_data_path
        BASKETS_FILE = get_data_path('theme_baskets.json')

    payload = _load_json_payload(BASKETS_FILE)
    if not BASKETS_FILE.is_file():
        return {
            'label': 'Theme catalysts',
            'status': 'missing',
            'age_seconds': None,
            'age_display': 'missing',
            'stale': True,
            'file': str(BASKETS_FILE),
            'reason': 'theme_baskets.json missing',
        }

    refreshed = _parse_intelligence_timestamp(payload.get('cache_refreshed_at'))
    if refreshed is None:
        generated = _parse_intelligence_timestamp(payload.get('generated_at'))
        return {
            'label': 'Theme catalysts',
            'status': 'static_wishlist',
            'age_seconds': None,
            'age_display': 'static wishlist',
            'timestamp': generated.isoformat() if generated is not None else None,
            'timestamp_key': 'generated_at' if generated is not None else '',
            'stale': False,
            'file': str(BASKETS_FILE),
            'reason': 'theme baskets are static until catalyst cache refresh runs',
        }

    age_seconds = _age_seconds_from_dt(refreshed)
    stale = bool(age_seconds is None or age_seconds > 24 * 3600)
    return {
        'label': 'Theme catalysts',
        'status': 'stale' if stale else ('partial' if age_seconds and age_seconds > 6 * 3600 else 'fresh'),
        'age_seconds': int(age_seconds) if age_seconds is not None else None,
        'age_display': _age_display_from_seconds(age_seconds),
        'timestamp': refreshed.isoformat(),
        'timestamp_key': 'cache_refreshed_at',
        'stale': stale,
        'file': str(BASKETS_FILE),
    }


def _broker_optional_row(data_dir: Path) -> Dict[str, Any]:
    row = _freshest_cache_row(
        'Broker cache',
        (
            data_dir / 'broker_intelligence_cache.json',
            data_dir / 'broker_overview_cache.json',
            data_dir / 'broker_app_collector_latest.json',
        ),
    )
    age = row.get('age_display')
    return {
        **row,
        'label': 'Broker',
        'status': 'optional',
        'age_display': age if age and age != 'missing' else 'not refreshed by full refresh',
        'stale': False,
        'optional': True,
        'reason': 'not refreshed by full refresh',
    }


def _load_intelligence_freshness() -> Dict[str, Any]:
    """Optional intelligence cache ages used by Telegram status and AI Hub surfaces."""
    try:
        from backend.utils.config import DATA_DIR
    except Exception:
        from backend.storage.data_paths import get_data_root
        DATA_DIR = get_data_root()

    try:
        from backend.analytics.budget_impact import CACHE_FILE as BUDGET_CACHE_FILE
    except Exception:
        from backend.storage.data_paths import get_data_path
        BUDGET_CACHE_FILE = get_data_path('budget_impact_cache.json')

    aihub_dir = DATA_DIR / 'cache' / 'aihub_tabs'
    try:
        from backend.analytics.aihub_tab_freshness import get_aihub_tab_freshness_report

        aihub_tabs = (get_aihub_tab_freshness_report().get('tabs') or {})
    except Exception:
        aihub_tabs = {}
    rows = {
        'runtime_snapshot': _freshest_cache_row(
            'Runtime snapshot',
            (
                DATA_DIR / 'cache' / 'runtime_snapshot.json',
                DATA_DIR / 'runtime' / 'current_snapshot.json',
            ),
        ),
        'legacy_report': _cache_row('Legacy report cache', DATA_DIR / 'daily_report_pack_latest.json'),
        'news': _freshest_cache_row(
            'News',
            (DATA_DIR / 'live_news_feed.json', DATA_DIR / 'news_feed.json'),
        ),
        'budget': _cache_row('Budget cache', BUDGET_CACHE_FILE, stale_after_seconds=90 * 60),
        'theme': _theme_catalyst_cache_row(),
        'catalysts': _cache_row('Catalyst radar', DATA_DIR / 'stock_catalyst_radar_latest.json'),
        'aihub_brain': _aihub_cache_row('AIHub brain', aihub_dir / 'brain.json', aihub_tabs.get('brain')),
        'aihub_govt': _aihub_cache_row('AIHub govt', aihub_dir / 'govt.json', aihub_tabs.get('govt')),
        'aihub_market': _aihub_cache_row('AIHub market', aihub_dir / 'market.json', aihub_tabs.get('mkt')),
        'broker': _broker_optional_row(DATA_DIR),
    }
    optional_keys = (
        'news',
        'budget',
        'theme',
        'catalysts',
        'aihub_brain',
        'aihub_govt',
        'aihub_market',
        'broker',
    )
    stale_optional = [
        key for key in optional_keys
        if rows.get(key, {}).get('stale') and rows.get(key, {}).get('status') != 'static_wishlist'
    ]
    return {
        'rows': rows,
        'optional_stale_keys': stale_optional,
        'optional_status': 'stale' if stale_optional else 'fresh',
    }


def _load_db_size_display() -> str:
    try:
        from backend.utils.config import DB_PATH
        if DB_PATH.exists():
            mb = DB_PATH.stat().st_size / (1024 * 1024)
            return f'{mb:.1f} MB'
    except Exception:
        pass
    return '—'


def _load_alert_eligibility(lifecycle: dict, freshness: dict, intelligence_status: dict) -> Dict[str, Any]:
    lc_state = str(lifecycle.get('lifecycle_state') or '').upper()
    after_hours = bool(lifecycle.get('after_hours_mode')) or bool(freshness.get('market_closed'))
    premarket = (
        lc_state in ('PREMARKET', 'PRE_MARKET', 'PRE_MARKET_PREP')
        or str(freshness.get('market_state') or '').upper() in ('PREMARKET', 'PRE_MARKET')
        or str(freshness.get('market_period') or '').lower() in ('pre_market', 'premarket')
    )
    stale = bool(freshness.get('stale'))
    ai_blocked = intelligence_status.get('elite_blocked')
    degraded_lifecycle = lc_state in ('DEGRADED',)
    if after_hours:
        eligible = not degraded_lifecycle and not bool(freshness.get('degraded'))
        execution_eligible = False
    elif premarket:
        eligible = not degraded_lifecycle
        execution_eligible = eligible and not stale and not bool(freshness.get('degraded'))
    else:
        eligible = not stale and not degraded_lifecycle
        execution_eligible = eligible
    reasons = []
    if stale and not (after_hours or premarket):
        reasons.append('stale_snapshot')
    if stale and premarket:
        reasons.append('stale_snapshot_live_setup_block')
    if degraded_lifecycle:
        reasons.append('lifecycle_mismatch')
    if ai_blocked and intelligence_status.get('status') == 'degraded' and not (after_hours or premarket):
        reasons.append('missing_ai_confirmation')
    try:
        from backend.orchestration.alert_suppression_log import suppression_summary
        sup = suppression_summary(limit=100)
    except Exception:
        sup = {'suppression_count': 0, 'by_reason': {}}
    if sup.get('suppression_count', 0) > 0 and not (after_hours or premarket):
        top = sorted((sup.get('by_reason') or {}).items(), key=lambda x: -x[1])[:2]
        for reason, _count in top:
            tag = f'suppressed:{reason}'
            if tag not in reasons:
                reasons.append(tag)
    return {
        'eligible': eligible,
        'execution_eligible': execution_eligible,
        'watchlist_only': bool(eligible and not execution_eligible),
        'block_reasons': reasons,
        'suppression_count': sup.get('suppression_count', 0),
        'suppression_by_reason': sup.get('by_reason') or {},
        'last_suppression_reason': sup.get('last_reason') or sup.get('last_suppression_reason') or '',
        'last_suppression_detail': sup.get('last_detail') or sup.get('last_suppression_detail') or '',
        'duplicate_alerts_avoided': sup.get('duplicate_alerts_avoided', 0),
        'ai_calls_avoided': sup.get('ai_calls_avoided', 0),
    }


def build_runtime_state(*, force_refresh: bool = False) -> Dict[str, Any]:
    """Build canonical runtime state — sole metric authority."""
    global _cached_state, _cached_at
    now = time.time()
    with _cache_lock:
        if not force_refresh and _cached_state and (now - _cached_at) < _CACHE_TTL_SECONDS:
            return dict(_cached_state)

    from backend.runtime.snapshot_freshness_monitor import evaluate_snapshot_freshness
    from backend.lifecycle.canonical_lifecycle import sync_with_scheduler
    from backend.validation.metric_consistency_guard import validate_metric_consistency
    from backend.metrics.canonical_metrics import format_win_rate_display
    from backend.utils.market_hours import get_operational_status

    freshness = evaluate_snapshot_freshness()
    lifecycle = sync_with_scheduler()
    stall_report = {}
    try:
        from backend.runtime.stall_watchdog import evaluate_stalls
        stall_report = evaluate_stalls()
    except Exception:
        pass

    operational = get_operational_status()
    pipeline_status = _load_pipeline_status(freshness, lifecycle, operational)
    scanner_health = _load_scanner_health()
    primary_state = _map_primary_runtime_state(
        lifecycle, operational, freshness, scanner_health, pipeline_status,
    )

    if primary_state == 'DEGRADED':
        lifecycle = dict(lifecycle)
        lifecycle['lifecycle_state'] = 'DEGRADED'
        causes = stall_report.get('root_causes') or []
        if causes:
            lifecycle['lifecycle_display'] = f"Degraded — {'; '.join(causes[:2])}"
        elif freshness.get('stale'):
            lifecycle['lifecycle_display'] = f"Degraded — snapshot {freshness.get('age_display', 'stale')}"
        elif pipeline_status.get('stalled_stages'):
            stalled = pipeline_status.get('stalled_stages') or []
            lifecycle['lifecycle_display'] = f"Degraded — pipeline stalled: {', '.join(stalled[:2])}"
        else:
            lifecycle['lifecycle_display'] = 'Degraded — Stale or Conflicting State'
        lifecycle['suppress_trading_language'] = True
    elif primary_state == 'AFTER_HOURS':
        lifecycle = dict(lifecycle)
        if lifecycle.get('lifecycle_state') == 'DEGRADED':
            lifecycle['lifecycle_state'] = (
                operational.get('canonical_lifecycle')
                or operational.get('lifecycle_state')
                or 'AFTER_HOURS'
            )
            lifecycle['lifecycle_display'] = operational.get('display_status') or 'After-Hours Intelligence Mode'
        else:
            lifecycle.setdefault('lifecycle_state', 'AFTER_HOURS')
        lifecycle['suppress_trading_language'] = True
    elif primary_state == 'LIVE':
        lifecycle = dict(lifecycle)
        if lifecycle.get('lifecycle_state') == 'DEGRADED':
            lifecycle['lifecycle_state'] = lifecycle.get('market_session_open') and 'MARKET_ACTIVE' or 'PRE_MARKET'
            lifecycle['lifecycle_display'] = lifecycle.get('lifecycle_display') or 'Market Active'
        lifecycle['suppress_trading_language'] = False
    overnight_posture = _load_overnight_posture()
    session = _load_session_status(lifecycle, operational)
    collector_activity = _load_collector_activity(freshness)
    metrics = _load_metrics()
    counts = _load_prediction_counts(metrics)
    win_rate = format_win_rate_display(counts['wins'], counts['losses'])
    regime = _load_regime()
    provider_health = _load_provider_health()
    telegram_metrics = _load_telegram_metrics()
    quality = _load_quality_score(freshness)
    intelligence_status = _load_intelligence_status(freshness)
    scheduler = _load_scheduler_phase(lifecycle, operational)
    ai_state = _load_ai_state(provider_health)
    alert_eligibility = _load_alert_eligibility(lifecycle, freshness, intelligence_status)
    secondary_flags = _load_secondary_flags(freshness, scanner_health, stall_report)
    if primary_state == 'DEGRADED':
        secondary_flags['runtime_degraded'] = True
    source_freshness = _load_source_freshness(operational)
    brain_age = _load_brain_age_display()
    intelligence_freshness = _load_intelligence_freshness()

    # Metric source trace for duplicate detection (read export file — no full re-export)
    metric_sources = {'sqlite_evaluated': counts['evaluated']}
    try:
        import json
        from backend.utils.config import DATA_DIR
        stats_path = DATA_DIR / 'stats_data.json'
        if stats_path.exists():
            exp = json.loads(stats_path.read_text(encoding='utf-8'))
            exp_m = (exp.get('metrics_all_time') or {}) if isinstance(exp, dict) else {}
            metric_sources['export_evaluated'] = int(
                exp_m.get('evaluated') or exp_m.get('total_evaluated') or 0
            )
    except Exception:
        pass

    state: Dict[str, Any] = {
        'generated_at': _now_iso(),
        'authority': 'runtime_state',
        'primary_state': primary_state,
        'secondary_flags': secondary_flags,
        'source_freshness': source_freshness,
        'brain_age': brain_age,
        'intelligence_freshness': intelligence_freshness,
        'db_size_display': _load_db_size_display(),
        'lifecycle': lifecycle,
        'session': session,
        'pipeline': pipeline_status,
        'scanner_health': scanner_health,
        'overnight_posture': overnight_posture,
        'stall_watchdog': stall_report,
        'collector_activity': collector_activity,
        'market_phase': operational.get('period'),
        'operational': operational,
        'regime': regime,
        'quality_score': quality,
        'win_rate': win_rate,
        'prediction_counts': counts,
        'metrics': {
            **metrics,
            **counts,
            'win_rate': win_rate.get('win_rate'),
            'win_rate_display': win_rate.get('win_rate_display'),
            'statistically_confident': win_rate.get('statistically_confident'),
        },
        'snapshot_freshness': freshness,
        'provider_health': provider_health,
        'telegram_metrics': telegram_metrics,
        'intelligence_status': intelligence_status,
        'scheduler': scheduler,
        'ai_state': ai_state,
        'alert_eligibility': alert_eligibility,
        'metric_sources': metric_sources,
        'consistency': {'valid': True, 'issues': []},
    }

    ok, issues = validate_metric_consistency(state)
    state['consistency'] = {'valid': ok, 'issues': issues}

    try:
        from backend.debug.runtime_audit import audit_from_runtime_state
        audit_from_runtime_state(state)
    except Exception:
        pass

    with _cache_lock:
        _cached_state = dict(state)
        _cached_at = now
    return state


def get_runtime_state(*, force_refresh: bool = False) -> Dict[str, Any]:
    return build_runtime_state(force_refresh=force_refresh)


def apply_to_snapshot_payload(snapshot: dict) -> dict:
    """Merge canonical runtime_state into API runtime snapshot."""
    state = build_runtime_state()
    out = dict(snapshot or {})
    out['runtime_state'] = state

    # Redirect fragmented panel fields to canonical state
    panels = dict(out.get('panels') or {})
    runtime_panel = dict(panels.get('runtime') or {})
    lc = state.get('lifecycle') or {}
    fresh = state.get('snapshot_freshness') or {}
    runtime_panel['lifecycle_state'] = lc.get('lifecycle_state')
    runtime_panel['lifecycle_display'] = lc.get('lifecycle_display')
    runtime_panel['snapshot_freshness_minutes'] = fresh.get('age_minutes')
    runtime_panel['snapshot_freshness_display'] = fresh.get('age_display')
    runtime_panel['snapshot_stale'] = fresh.get('stale')
    runtime_panel['after_hours_mode'] = (state.get('session') or {}).get('after_hours_mode')
    runtime_panel['session_status'] = (state.get('session') or {}).get('session_status')
    runtime_panel['collectors_active'] = (state.get('collector_activity') or {}).get('collectors_active')
    runtime_panel['quality_score'] = (state.get('quality_score') or {}).get('quality_score')
    runtime_panel['scheduler_phase'] = (state.get('scheduler') or {}).get('phase')
    runtime_panel['freshness_tier'] = fresh.get('health_tier')
    runtime_panel['alert_suppression_count'] = (state.get('alert_eligibility') or {}).get('suppression_count', 0)
    runtime_panel['scanner_display'] = (state.get('scanner_health') or {}).get('display')
    runtime_panel['pipeline_stalled'] = (state.get('pipeline') or {}).get('any_stalled')
    runtime_panel['primary_state'] = state.get('primary_state')
    runtime_panel['secondary_flags'] = state.get('secondary_flags')
    panels['runtime'] = runtime_panel
    out['panels'] = panels

    wr = state.get('win_rate') or {}
    counts = state.get('prediction_counts') or {}
    cal_summary = dict(out.get('calibration_summary') or {})
    sections = (state.get('metrics') or {}).get('sections') or {}
    cal_summary.update({
        'evaluated': counts.get('evaluated'),
        'pending': counts.get('pending'),
        'wins': counts.get('wins'),
        'losses': counts.get('losses'),
        'expired': counts.get('expired'),
        'neutralized': counts.get('neutralized'),
        'win_rate': wr.get('win_rate'),
        'win_rate_display': wr.get('win_rate_display'),
        'statistically_confident': wr.get('statistically_confident'),
        'metric_sections': sections,
        'live_session': sections.get('live_session') or {},
        'historical_calibration': sections.get('historical_calibration') or {},
        'archived': sections.get('archived') or {},
    })
    out['calibration_summary'] = cal_summary

    regime = state.get('regime') or {}
    out['regime_display'] = regime.get('regime_display')
    out['consistency_valid'] = (state.get('consistency') or {}).get('valid')
    return out
