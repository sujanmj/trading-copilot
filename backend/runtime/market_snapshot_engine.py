"""
Market snapshot engine — sole composer of cross-surface intelligence state.

Delegates to runtime_state, unified_metrics, canonical_metrics, active_snapshot,
and existing intelligence modules. Does not reimplement business logic.
"""

from __future__ import annotations

import json
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytz

from backend.runtime.market_snapshot import MarketSnapshot, new_snapshot_id
from backend.utils.config import CURRENT_SNAPSHOT_FILE, DATA_DIR

IST = pytz.timezone('Asia/Kolkata')

_cache_lock = threading.Lock()
_cached_snapshot: Optional[MarketSnapshot] = None
_cached_at: float = 0.0
_CACHE_TTL_SECONDS = 3.0


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _load_intel_raw() -> Dict[str, Any]:
    try:
        from backend.intelligence.active_snapshot import get_canonical_intelligence
        data = get_canonical_intelligence()
        if isinstance(data, dict) and data:
            return data
    except Exception:
        pass
    path = DATA_DIR / 'unified_intelligence.json'
    if path.exists():
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}


def _normalize_intel_view(intel: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from backend.orchestration.telegram_brain_pusher import normalize_intel
        return normalize_intel(intel) or {}
    except Exception:
        return intel if isinstance(intel, dict) else {}


def _load_elite_summary() -> Dict[str, Any]:
    path = DATA_DIR / 'high_conviction_alerts.json'
    if not path.exists():
        return {'elite_signals': [], 'engine_mode': None}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {'elite_signals': []}
    except Exception:
        return {'elite_signals': [], 'engine_mode': None}


def _build_feeds(runtime_state: Dict[str, Any]) -> Dict[str, Any]:
    sources = runtime_state.get('source_freshness') or {}
    mapping = {
        'scanner': 'scanner',
        'govt': 'govt',
        'news': 'news',
        'reddit': 'reddit',
        'global': 'global',
        'tv': 'youtube',
    }
    feeds: Dict[str, Any] = {}
    for key, src_key in mapping.items():
        row = sources.get(src_key) or sources.get(key) or {}
        feeds[key] = {
            'status': row.get('status'),
            'age_seconds': row.get('age_seconds'),
            'age_display': row.get('age_display'),
            'stale': bool(row.get('stale')),
        }
    return feeds


def _build_providers(provider_health: Dict[str, Any]) -> Dict[str, Any]:
    raw = provider_health.get('providers') or {}
    out: Dict[str, Any] = {}
    for name in ('groq', 'gemini', 'claude'):
        row = raw.get(name) or raw.get(name.upper()) or {}
        out[name] = row if isinstance(row, dict) else {'status': provider_health.get('status', 'unknown')}
    if not any(out.values()):
        out['aggregate'] = {
            'status': provider_health.get('status', 'unknown'),
            'degraded_mode': provider_health.get('degraded_mode'),
        }
    return out


def _build_blockers_warnings(
    runtime_state: Dict[str, Any],
    secondary: Dict[str, Any],
) -> Tuple[List[str], List[str]]:
    blockers: List[str] = []
    warnings: List[str] = []
    alert = runtime_state.get('alert_eligibility') or {}
    for r in alert.get('block_reasons') or []:
        if r not in blockers:
            blockers.append(str(r))
    if secondary.get('stale_snapshot') and 'stale_snapshot' not in blockers:
        blockers.append('stale_snapshot')
    if secondary.get('scanner_stalled') and 'scanner_stalled' not in blockers:
        blockers.append('scanner_stalled')
    if secondary.get('missing_confirmation') and 'missing_confirmation' not in blockers:
        blockers.append('missing_confirmation')
    intel = runtime_state.get('intelligence_status') or {}
    if intel.get('degraded') and intel.get('message'):
        warnings.append(str(intel['message']))
    fresh = runtime_state.get('snapshot_freshness') or {}
    if fresh.get('degraded') and not fresh.get('stale'):
        warnings.append('Snapshot aging — partial degradation')
    stall = runtime_state.get('stall_watchdog') or {}
    for issue in (stall.get('issues') or [])[:4]:
        tag = str(issue)
        if tag not in warnings:
            warnings.append(tag)
    return blockers, warnings


def _secondary_flags(runtime_state: Dict[str, Any]) -> Dict[str, bool]:
    base = dict(runtime_state.get('secondary_flags') or {})
    alert = runtime_state.get('alert_eligibility') or {}
    reasons = alert.get('block_reasons') or []
    base['missing_confirmation'] = base.get('missing_confirmation') or (
        'missing_ai_confirmation' in reasons
    )
    if base.get('cache_only'):
        base['cache_mode'] = True
    else:
        base.setdefault('cache_mode', False)
    return base


def build_market_snapshot(*, force_refresh: bool = False) -> MarketSnapshot:
    """Compose canonical MarketSnapshot from existing intelligence modules."""
    global _cached_snapshot, _cached_at
    now = time.time()
    with _cache_lock:
        if (
            not force_refresh
            and _cached_snapshot
            and (now - _cached_at) < _CACHE_TTL_SECONDS
        ):
            return _cached_snapshot

    from backend.runtime.runtime_state import build_runtime_state

    rs = build_runtime_state(force_refresh=force_refresh)
    intel_raw = _load_intel_raw()
    intel_view = _normalize_intel_view(intel_raw)
    elite = _load_elite_summary()

    mood = intel_view.get('market_mood') or {}
    if isinstance(mood, dict):
        global_mood = str(mood.get('global_mood') or mood.get('market_bias') or '')
        india_bias = str(mood.get('india_bias') or mood.get('india_sentiment') or '')
        retail_sentiment = str(mood.get('retail_sentiment') or mood.get('sentiment') or '')
        confidence = mood.get('confidence_level') or mood.get('confidence')
    else:
        global_mood = india_bias = retail_sentiment = ''
        confidence = intel_raw.get('confidence_score')

    counts = rs.get('prediction_counts') or {}
    metrics_block = {
        'wins': counts.get('wins', 0),
        'losses': counts.get('losses', 0),
        'partials': counts.get('partials', 0),
        'resolved': counts.get('resolved', 0),
        'pending': counts.get('pending', 0),
        'evaluated': counts.get('evaluated', 0),
        'win_rate': (rs.get('win_rate') or {}).get('win_rate'),
        'win_rate_display': (rs.get('win_rate') or {}).get('win_rate_display'),
        'statistically_confident': (rs.get('win_rate') or {}).get('statistically_confident'),
        'source': 'canonical_metrics_via_runtime_state',
    }

    secondary = _secondary_flags(rs)
    rs = dict(rs)
    rs['secondary_flags'] = secondary

    blockers, warnings = _build_blockers_warnings(rs, secondary)
    pipeline = rs.get('pipeline') or {}
    fresh = rs.get('snapshot_freshness') or {}
    pipeline_health = {
        'stages': pipeline.get('stages') or {},
        'stalled_stages': pipeline.get('stalled_stages') or [],
        'any_stalled': bool(pipeline.get('any_stalled')),
        'last_stage': pipeline.get('last_stage'),
        'freshness_tier': fresh.get('health_tier'),
        'snapshot_stale': bool(fresh.get('stale')),
        'collectors_active': (rs.get('collector_activity') or {}).get('collectors_active'),
    }

    session = rs.get('session') or {}
    lc = rs.get('lifecycle') or {}
    age_sec = None
    if fresh.get('age_minutes') is not None:
        try:
            age_sec = float(fresh['age_minutes']) * 60.0
        except (TypeError, ValueError):
            pass

    snap = MarketSnapshot(
        snapshot_id=new_snapshot_id(),
        generated_at=_now_iso(),
        market_session=str(session.get('session_status') or lc.get('lifecycle_state') or ''),
        lifecycle=lc,
        runtime_state=rs,
        snapshot_age_sec=age_sec,
        freshness=fresh,
        regime=rs.get('regime') or {},
        confidence=confidence,
        quality_score=rs.get('quality_score') or {},
        market_mood=mood if isinstance(mood, dict) else {},
        global_mood=global_mood,
        india_bias=india_bias,
        retail_sentiment=retail_sentiment,
        sector_rotation=intel_view.get('sector_rotation') or {},
        top_opportunities=intel_view.get('top_opportunities') or [],
        risk_list=intel_view.get('risks_and_avoids') or [],
        action_plan=str(intel_view.get('action_plan') or ''),
        elite_summary=elite,
        metrics=metrics_block,
        providers=_build_providers(rs.get('provider_health') or {}),
        feeds=_build_feeds(rs),
        blockers=blockers,
        warnings=warnings,
        pipeline_health=pipeline_health,
        intelligence=intel_view,
        calibration=intel_view.get('self_calibration'),
        executive_summary=str(intel_view.get('executive_summary') or ''),
        collector_at=(rs.get('collector_activity') or {}).get('updated_at'),
        snapshot_built_at=_now_iso(),
        published_at=None,
    )

    with _cache_lock:
        _cached_snapshot = snap
        _cached_at = now
    return snap


def validate_market_snapshot(snapshot: MarketSnapshot) -> Tuple[bool, List[str]]:
    issues: List[str] = []
    if not snapshot.snapshot_id:
        issues.append('missing snapshot_id')
    if not snapshot.generated_at:
        issues.append('missing generated_at')
    rs = snapshot.runtime_state or {}
    if rs.get('authority') != 'runtime_state':
        issues.append('runtime_state missing authority')
    primary = rs.get('primary_state')
    from backend.runtime.runtime_state import PRIMARY_RUNTIME_STATES
    if primary and primary not in PRIMARY_RUNTIME_STATES:
        issues.append(f'invalid primary_state: {primary}')
    fresh = snapshot.freshness or {}
    if fresh.get('stale') and fresh.get('fresh'):
        issues.append('freshness contradiction')
    if fresh.get('stale') and fresh.get('health_tier') == 'healthy':
        issues.append('stale flag contradicts healthy tier')
    sec = rs.get('secondary_flags') or {}
    age = fresh.get('age_minutes')
    tier = fresh.get('health_tier')
    if age is not None and tier:
        from backend.runtime.freshness_engine import freshness_health_tier, is_snapshot_stale
        expected_tier = freshness_health_tier(age)
        if tier != expected_tier:
            issues.append(f'freshness tier mismatch: {tier} vs {expected_tier}')
        if sec.get('stale_snapshot') and age is not None and not is_snapshot_stale(age):
            issues.append('stale_snapshot flag set while age is below stale threshold')
    return len(issues) == 0, issues


def build_degraded_snapshot(warnings: List[str]) -> MarketSnapshot:
    """Minimal valid snapshot when composition fails — never return malformed JSON."""
    from backend.runtime.runtime_state import build_runtime_state
    rs = build_runtime_state()
    snap = build_market_snapshot(force_refresh=True)
    snap.warnings = list(dict.fromkeys((snap.warnings or []) + warnings))
    snap.blockers = list(dict.fromkeys((snap.blockers or []) + ['snapshot_validation_failed']))
    return snap


def commit_market_snapshot(snapshot: MarketSnapshot) -> Path:
    """Persist canonical snapshot — atomic write, no partial publish."""
    from backend.storage.json_io import atomic_write_json
    from backend.utils.config import CURRENT_SNAPSHOT_FILE

    snapshot.published_at = _now_iso()
    payload = snapshot.to_dict()
    payload['_committed_at'] = snapshot.published_at
    atomic_write_json(CURRENT_SNAPSHOT_FILE, payload)
    return CURRENT_SNAPSHOT_FILE


def load_committed_snapshot() -> Optional[MarketSnapshot]:
    if not CURRENT_SNAPSHOT_FILE.exists():
        return None
    try:
        data = json.loads(CURRENT_SNAPSHOT_FILE.read_text(encoding='utf-8'))
        return MarketSnapshot.from_dict(data)
    except Exception:
        return None


def get_current_market_snapshot(*, force_refresh: bool = False) -> MarketSnapshot:
    """Return in-memory snapshot; fall back to committed file if cache cold."""
    snap = build_market_snapshot(force_refresh=force_refresh)
    if not force_refresh and CURRENT_SNAPSHOT_FILE.exists():
        try:
            mtime = CURRENT_SNAPSHOT_FILE.stat().st_mtime
            if mtime > _cached_at and (time.time() - _cached_at) >= _CACHE_TTL_SECONDS:
                committed = load_committed_snapshot()
                if committed:
                    return committed
        except Exception:
            pass
    return snap


def invalidate_snapshot_cache() -> None:
    global _cached_snapshot, _cached_at
    with _cache_lock:
        _cached_snapshot = None
        _cached_at = 0.0
    try:
        from backend.runtime.runtime_state import build_runtime_state
        build_runtime_state(force_refresh=True)
    except Exception:
        pass


def snapshot_stale_notice(snapshot: Optional[MarketSnapshot] = None) -> str:
    """Single canonical stale/session notice for Telegram renderers."""
    snap = snapshot or get_current_market_snapshot()
    rs = snap.runtime_state or {}
    try:
        from backend.telegram.formatting.telegram_formatter import session_notice
        return session_notice(rs)
    except Exception:
        return ''
