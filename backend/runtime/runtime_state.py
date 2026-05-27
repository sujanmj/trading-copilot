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


def _load_alert_eligibility(lifecycle: dict, freshness: dict, intelligence_status: dict) -> Dict[str, Any]:
    lc_state = lifecycle.get('lifecycle_state')
    after_hours = bool(lifecycle.get('after_hours_mode'))
    stale = bool(freshness.get('stale'))
    ai_blocked = intelligence_status.get('elite_blocked')
    eligible = not stale and lc_state not in ('DEGRADED',) and not after_hours
    reasons = []
    if stale:
        reasons.append('stale_snapshot')
    if after_hours:
        reasons.append('after_hours_block')
    if lc_state == 'DEGRADED':
        reasons.append('lifecycle_mismatch')
    if ai_blocked and intelligence_status.get('status') == 'degraded':
        reasons.append('missing_ai_confirmation')
    try:
        from backend.logs.alert_suppression import suppression_summary
        sup = suppression_summary(limit=100)
    except Exception:
        sup = {'suppression_count': 0, 'by_reason': {}}
    return {
        'eligible': eligible,
        'block_reasons': reasons,
        'suppression_count': sup.get('suppression_count', 0),
        'suppression_by_reason': sup.get('by_reason') or {},
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
    if freshness.get('stale') or freshness.get('degraded'):
        lifecycle = dict(lifecycle)
        lifecycle['lifecycle_state'] = 'DEGRADED'
        lifecycle['lifecycle_display'] = 'Degraded — Stale or Conflicting State'
        lifecycle['suppress_trading_language'] = True

    operational = get_operational_status()
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
        'session': session,
        'collector_activity': collector_activity,
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
