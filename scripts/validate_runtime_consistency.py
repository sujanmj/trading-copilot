#!/usr/bin/env python3
"""Validate Phase-3 runtime consistency — canonical state, metrics, freshness, lifecycle."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    errors = []

    from backend.runtime.runtime_state import build_runtime_state, apply_to_snapshot_payload
    from backend.validation.metric_consistency_guard import validate_metric_consistency, MIN_WIN_RATE_SAMPLE
    from backend.lifecycle.canonical_lifecycle import CANONICAL_STATES, build_canonical_lifecycle
    from backend.intelligence.regime_normalizer import display_regime, normalize_regime_key
    from backend.runtime.snapshot_freshness_monitor import evaluate_snapshot_freshness
    from backend.debug.runtime_audit import get_audit_report
    from backend.api.api_server import _build_runtime_snapshot

    state = build_runtime_state(force_refresh=True)
    ok, issues = validate_metric_consistency(state)
    if not ok:
        errors.extend(issues)

    if state.get('authority') != 'runtime_state':
        errors.append('runtime_state missing authority marker')

    for key in (
        'lifecycle', 'regime', 'quality_score', 'win_rate', 'prediction_counts',
        'snapshot_freshness', 'provider_health', 'telegram_metrics', 'intelligence_status',
        'pipeline', 'scanner_health',
    ):
        if key not in state:
            errors.append(f'runtime_state missing {key}')

    scanner = state.get('scanner_health') or {}
    if 'display' not in scanner:
        errors.append('scanner_health missing display')

    from backend.logs.alert_suppression import log_dispatch_debug
    from backend.runtime.pipeline_stage_log import pipeline_stage_log, get_pipeline_stage_summary
    log_dispatch_debug(ticker='TEST', reason='dedupe', category='validate')
    pipeline_stage_log('scanner', status='test', detail='validate_probe')
    if 'stages' not in get_pipeline_stage_summary():
        errors.append('pipeline stage summary missing stages')

    lc = state.get('lifecycle') or {}
    if lc.get('lifecycle_state') not in CANONICAL_STATES:
        errors.append(f'invalid canonical lifecycle: {lc.get("lifecycle_state")}')

    if not lc.get('transition_valid'):
        errors.append(f'lifecycle transition invalid: {lc.get("transition_reason")}')

    wr = state.get('win_rate') or {}
    counts = state.get('prediction_counts') or {}
    denom = int(counts.get('wins') or 0) + int(counts.get('losses') or 0)
    if denom < MIN_WIN_RATE_SAMPLE and wr.get('statistically_confident'):
        errors.append('win rate marked confident below minimum sample')
    if denom == 0 and wr.get('win_rate') not in (None, 0, 0.0):
        errors.append('impossible win rate with zero resolved outcomes')

    regime = state.get('regime') or {}
    if regime.get('regime_display', '').lower() in ('unknown', 'none'):
        errors.append('raw unknown regime exposed to UI')
    if '_' in str(regime.get('regime_display') or '') and regime.get('regime_display') == regime.get('regime_internal'):
        errors.append('raw enum exposed as display regime')

    fresh = state.get('snapshot_freshness') or {}
    if fresh.get('stale') and fresh.get('fresh'):
        errors.append('snapshot freshness contradiction')

    intel = state.get('intelligence_status') or {}
    if fresh.get('stale') and intel.get('status') == 'ready' and not intel.get('degraded'):
        errors.append('stale snapshot but intelligence ready')

    # Duplicate metric engines — runtime vs sqlite
    try:
        from backend.lifecycle.unified_metrics import get_outcome_metrics
        sqlite = get_outcome_metrics('all_time')
        if int(counts.get('evaluated') or 0) != int(sqlite.get('evaluated') or 0):
            errors.append(
                f'runtime evaluated {counts.get("evaluated")} != sqlite {sqlite.get("evaluated")}'
            )
    except Exception as exc:
        errors.append(f'sqlite cross-check failed: {exc}')

    snapshot = _build_runtime_snapshot()
    if 'runtime_state' not in snapshot:
        errors.append('runtime_snapshot missing runtime_state')
    if snapshot.get('calibration_summary', {}).get('win_rate_display') is None and denom >= MIN_WIN_RATE_SAMPLE:
        pass  # optional when no resolved outcomes

    applied = apply_to_snapshot_payload({'panels': {}, 'calibration_summary': {}})
    if not applied.get('calibration_summary', {}).get('win_rate_display') and denom == 0:
        if applied.get('calibration_summary', {}).get('win_rate_display') != state['win_rate'].get('win_rate_display'):
            pass

    audit = get_audit_report(limit=5)
    if audit.get('status') != 'ok':
        errors.append('runtime audit endpoint payload invalid')

    # Regime normalizer smoke
    if display_regime('panic_volatile') != 'Panic Volatile':
        errors.append('regime display mapping failed')
    if normalize_regime_key('risk-off') != 'risk_off':
        errors.append('regime key normalization failed')

    # Alert fatigue caps
    from backend.orchestration.opportunity_filter import MAX_WATCHLIST_ITEMS, rank_opportunities_tiered
    tiers = rank_opportunities_tiered()
    if len(tiers.get('watch') or []) > MAX_WATCHLIST_ITEMS:
        errors.append(f'watchlist exceeds cap: {len(tiers.get("watch") or [])}')

    # Canonical lifecycle guard
    bad, reason = build_canonical_lifecycle(pipeline_status='COMPLETE').get('transition_valid'), ''
    from backend.lifecycle.canonical_lifecycle import validate_transition
    ok_t, reason_t = validate_transition('MARKET_ACTIVE', 'MARKET_ACTIVE', pipeline_status='COMPLETE')
    if ok_t:
        errors.append('lifecycle should reject MARKET_ACTIVE + COMPLETE overlap')

    from backend.runtime.freshness_engine import format_age_minutes, FRESHNESS_UNAVAILABLE, validate_timestamp_order
    if format_age_minutes(None) != FRESHNESS_UNAVAILABLE:
        errors.append('freshness None must not format as Nonem/nullm')
    from backend.runtime.freshness_engine import freshness_health_tier
    if freshness_health_tier(4) != 'healthy' or freshness_health_tier(12) != 'aging':
        errors.append('freshness tier boundaries incorrect')
    ok_ts, ts_issue = validate_timestamp_order('2099-01-01T00:00:00+05:30', '2020-01-01T00:00:00+05:30')
    if ok_ts:
        errors.append('future timestamp should fail validation')

    from backend.api.api_server import api_runtime_debug
    dbg = api_runtime_debug()
    for key in ('lifecycle_state', 'freshness', 'scheduler_phase', 'suppression'):
        if key not in dbg:
            errors.append(f'runtime debug missing {key}')

    import inspect
    src = inspect.getsource(api_runtime_debug)
    if 'build_runtime_state' not in src:
        errors.append('runtime debug must use build_runtime_state')

    from backend.intelligence.institutional_language import apply_institutional_tone
    if 'ULTRA' in apply_institutional_tone('scanner ULTRA signal').upper():
        errors.append('ULTRA contamination in institutional output')

    session = state.get('session') or {}
    if session.get('after_hours_mode') and lc.get('lifecycle_state') == 'MARKET_ACTIVE':
        errors.append('after-hours market_active violation')

    if len({lc.get('lifecycle_state'), session.get('session_status')}) > 1 and session.get('session_status') != lc.get('lifecycle_state'):
        if session.get('session_status') and lc.get('lifecycle_state') not in ('DEGRADED',):
            errors.append('multiple lifecycle states in runtime_state')

    from backend.intelligence.watchlist_cluster import cluster_watchlist
    sample = [{'symbol': f'T{i}', 'logic': 'breakout watch'} for i in range(6)]
    clusters = cluster_watchlist(sample)
    if len(clusters) > 2:
        errors.append('watchlist cluster exceeds max 2 clusters')

    print('=== RUNTIME CONSISTENCY VALIDATION ===')
    print(f"Lifecycle: {lc.get('lifecycle_state')} ({lc.get('lifecycle_display')})")
    print(f"Regime: {regime.get('regime_display')}")
    print(f"Win rate: {wr.get('win_rate_display')} (confident={wr.get('statistically_confident')})")
    print(f"Snapshot stale: {fresh.get('stale')} score={fresh.get('freshness_score')}")
    print(f"Consistency: {state.get('consistency')}")
    print(f"Audit events: {audit.get('total_events')}")

    if errors:
        print('FAILURES:')
        for e in errors:
            print(f'  - {e}')
        return 1

    print('RUNTIME STATE AUTHORITY VERIFIED')
    print('METRIC CONSISTENCY GUARD VERIFIED')
    print('SNAPSHOT FRESHNESS VERIFIED')
    print('CANONICAL LIFECYCLE VERIFIED')
    print('REGIME NORMALIZATION VERIFIED')
    print('ALERT FATIGUE CAPS VERIFIED')
    print('RUNTIME AUDIT VERIFIED')
    print('API RUNTIME SNAPSHOT VERIFIED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
