"""
Canonical runtime state — SINGLE source of truth for orchestration surfaces.

Authority for: lifecycle, regime, market phase, quality score, win rate,
snapshot freshness, provider health, prediction counts, telegram metrics,
intelligence status.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

import pytz

IST = pytz.timezone('Asia/Kolkata')

_cache_lock = threading.Lock()
_cached_state: Optional[dict] = None
_cached_at: float = 0.0
_CACHE_TTL_SECONDS = 3.0


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
        snap = get_unified_snapshot() or {}
        return snap.get('metrics_all_time') or {}
    except Exception:
        return {}


def _load_prediction_counts(metrics: dict) -> Dict[str, Any]:
    return {
        'prediction_total': int(metrics.get('prediction_total') or metrics.get('total_predictions') or 0),
        'evaluated': int(metrics.get('evaluated') or metrics.get('total_evaluated') or 0),
        'pending': int(metrics.get('pending') or 0),
        'wins': int(metrics.get('wins') or 0),
        'losses': int(metrics.get('losses') or 0),
        'neutral': int(metrics.get('neutral') or 0),
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


def _load_intelligence_status(freshness: dict) -> Dict[str, Any]:
    stale = bool(freshness.get('stale'))
    degraded = bool(freshness.get('degraded'))
    if stale:
        return {
            'status': 'degraded',
            'message': 'Snapshot stale — intelligence confidence suppressed',
            'degraded': True,
            'elite_blocked': True,
        }
    if degraded:
        return {
            'status': 'degraded',
            'message': 'Partial degradation — awaiting fresh cycle',
            'degraded': True,
            'elite_blocked': bool(freshness.get('block_elite_outputs')),
        }
    return {
        'status': 'ready',
        'message': None,
        'degraded': False,
        'elite_blocked': False,
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
    from backend.validation.metric_consistency_guard import (
        format_win_rate_display,
        validate_metric_consistency,
    )
    from backend.utils.market_hours import get_operational_status

    freshness = evaluate_snapshot_freshness()
    lifecycle = sync_with_scheduler()
    if freshness.get('stale') or freshness.get('degraded'):
        lifecycle = dict(lifecycle)
        lifecycle['lifecycle_state'] = 'DEGRADED'
        lifecycle['lifecycle_display'] = 'Degraded — Stale or Conflicting State'

    operational = get_operational_status()
    metrics = _load_metrics()
    counts = _load_prediction_counts(metrics)
    win_rate = format_win_rate_display(counts['wins'], counts['losses'])
    regime = _load_regime()
    provider_health = _load_provider_health()
    telegram_metrics = _load_telegram_metrics()
    quality = _load_quality_score(freshness)
    intelligence_status = _load_intelligence_status(freshness)

    # Metric source trace for duplicate detection
    metric_sources = {'sqlite_evaluated': counts['evaluated']}
    try:
        from backend.storage.stats_exporter import export_stats
        exp = (export_stats() or {}).get('metrics_all_time') or {}
        metric_sources['export_evaluated'] = int(exp.get('evaluated') or exp.get('total_evaluated') or 0)
    except Exception:
        pass

    state: Dict[str, Any] = {
        'generated_at': _now_iso(),
        'authority': 'runtime_state',
        'lifecycle': lifecycle,
        'market_phase': operational.get('period'),
        'operational': operational,
        'regime': regime,
        'quality_score': quality,
        'win_rate': win_rate,
        'prediction_counts': counts,
        'metrics': {**counts, 'win_rate': win_rate.get('win_rate')},
        'snapshot_freshness': freshness,
        'provider_health': provider_health,
        'telegram_metrics': telegram_metrics,
        'intelligence_status': intelligence_status,
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
    runtime_panel['snapshot_stale'] = fresh.get('stale')
    runtime_panel['quality_score'] = (state.get('quality_score') or {}).get('quality_score')
    panels['runtime'] = runtime_panel
    out['panels'] = panels

    wr = state.get('win_rate') or {}
    counts = state.get('prediction_counts') or {}
    cal_summary = dict(out.get('calibration_summary') or {})
    cal_summary.update({
        'evaluated': counts.get('evaluated'),
        'pending': counts.get('pending'),
        'wins': counts.get('wins'),
        'losses': counts.get('losses'),
        'win_rate': wr.get('win_rate'),
        'win_rate_display': wr.get('win_rate_display'),
        'statistically_confident': wr.get('statistically_confident'),
    })
    out['calibration_summary'] = cal_summary

    regime = state.get('regime') or {}
    out['regime_display'] = regime.get('regime_display')
    out['consistency_valid'] = (state.get('consistency') or {}).get('valid')
    return out
