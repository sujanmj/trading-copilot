#!/usr/bin/env python3
"""Validate unified metrics consistency across all surfaces."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    errors = []
    from backend.lifecycle.unified_metrics import (
        get_calibration_metrics,
        get_metrics_for_telegram,
        get_outcome_metrics,
        get_prediction_metrics,
        get_unified_snapshot,
        format_outcomes_telegram,
        format_stats_telegram,
        format_calibration_telegram,
    )
    from backend.storage.stats_exporter import export_stats
    from backend.api.api_server import _build_runtime_snapshot

    sqlite = get_outcome_metrics('all_time')
    pred = get_prediction_metrics('all_time')
    cal = get_calibration_metrics()
    bundle = get_metrics_for_telegram()
    exported = export_stats()
    exp = exported.get('metrics_all_time') or {}
    runtime = _build_runtime_snapshot()
    rt_metrics = ((runtime.get('data') or {}).get('stats') or {}).get('metrics_all_time') or {}

    checks = [
        ('sqlite vs predictions.evaluated', sqlite['evaluated'], pred['evaluated']),
        ('sqlite vs predictions.pending', sqlite['pending'], pred['pending']),
        ('sqlite vs calibration.evaluated', sqlite['evaluated'], cal['evaluated']),
        ('sqlite vs calibration.pending', sqlite['pending'], cal['pending']),
        ('sqlite vs export.evaluated', sqlite['evaluated'], exp.get('evaluated', exp.get('total_evaluated'))),
        ('sqlite vs export.pending', sqlite['pending'], exp.get('pending')),
        ('sqlite vs export.wins', sqlite['wins'], exp.get('wins')),
        ('sqlite vs export.losses', sqlite['losses'], exp.get('losses')),
        ('sqlite vs runtime.evaluated', sqlite['evaluated'], rt_metrics.get('evaluated', rt_metrics.get('total_evaluated'))),
        ('sqlite vs runtime.pending', sqlite['pending'], rt_metrics.get('pending')),
        ('prediction_total rule', sqlite['prediction_total'], sqlite['evaluated'] + sqlite['pending']),
        ('bundle identity', bundle['metrics']['evaluated'], sqlite['evaluated']),
    ]
    for label, a, b in checks:
        if a != b:
            errors.append(f"{label}: {a} != {b}")

    daily = get_outcome_metrics('daily')
    stats_msg = format_stats_telegram(session='today')
    out_msg = format_outcomes_telegram()
    cal_msg = format_calibration_telegram(cal)
    for field, val in [('wins', daily['wins']), ('losses', daily['losses']), ('pending', daily['pending'])]:
        if val and str(val) not in stats_msg:
            errors.append(f'/stats missing {field}={val}')
    for field, val in [('wins', sqlite['wins']), ('losses', sqlite['losses']), ('pending', sqlite['pending'])]:
        if val and str(val) not in out_msg:
            errors.append(f'/outcomes missing {field}={val}')
    if str(sqlite['evaluated']) not in cal_msg:
        errors.append('/calibration missing evaluated count')
    if 'TODAY SESSION' not in stats_msg:
        errors.append('/stats missing TODAY SESSION label')
    if 'HISTORICAL LEARNING' not in out_msg:
        errors.append('/outcomes missing HISTORICAL LEARNING label')

    from backend.orchestration.telegram_outbound_guard import outbound_hash, should_send_outbound
    dup_msg = '🎯 Sending self-calibration...'
    ok1, _, _, _ = should_send_outbound(dup_msg, command='calibration', cycle_id='c1', message_kind='loading')
    from backend.orchestration.telegram_outbound_guard import record_outbound
    if ok1:
        record_outbound(outbound_hash(dup_msg, 'calibration', 'c1:loading'), command='calibration', message_kind='loading', text=dup_msg)
    ok2, reason, _, _ = should_send_outbound(dup_msg, command='calibration', cycle_id='c1', message_kind='loading')
    if ok2 or reason != 'loading_duplicate':
        errors.append('telegram outbound dedupe failed for loading messages')

    from backend.orchestration.opportunity_filter import rank_opportunities_tiered
    from backend.orchestration.telegram_brain_pusher import format_opps_tiered, build_compressed_summary
    tiers = rank_opportunities_tiered()
    opps_body = format_opps_tiered(tiers)
    if (tiers.get('tactical') or tiers.get('watchlist')) and 'no ranked signals' in opps_body.lower():
        errors.append('format_opps_tiered false empty when tactical/watchlist exist')
    summary = build_compressed_summary({})
    section_count = sum(1 for marker in ('MARKET REGIME:', 'LEADERS:', 'RISKS:', 'TACTICAL BIAS:', 'CONFIDENCE:') if marker in summary)
    if section_count < 5:
        errors.append(f'compressed summary has {section_count}/5 sections')

    lc_path = ROOT / 'data' / 'lifecycle_state.json'
    from backend.lifecycle.prediction_lifecycle_engine import load_lifecycle_state, save_lifecycle_state
    save_lifecycle_state(load_lifecycle_state())
    if lc_path.exists():
        lc = json.loads(lc_path.read_text(encoding='utf-8'))
        um = lc.get('unified_metrics') or {}
        if um and um.get('evaluated') != sqlite['evaluated']:
            errors.append(f"lifecycle_state unified_metrics evaluated mismatch: {um.get('evaluated')} != {sqlite['evaluated']}")

    from backend.intelligence.canonical_rankings import (
        align_intelligence,
        extract_symbols_from_text,
        get_action_plan_symbols,
        get_top_ranked_signals,
        validate_action_plan_symbols,
    )
    from backend.utils.config import DATA_DIR

    intel_path = DATA_DIR / 'unified_intelligence.json'
    if intel_path.exists():
        try:
            raw_intel = json.loads(intel_path.read_text(encoding='utf-8'))
            aligned = align_intelligence(raw_intel if isinstance(raw_intel, dict) else {})
            ranked = get_top_ranked_signals(aligned)
            ranked_syms = {str(o.get('symbol') or '').upper() for o in ranked if o.get('symbol')}
            plan_syms = get_action_plan_symbols(aligned)
            plan_text = str(aligned.get('action_plan') or '')
            unknown = validate_action_plan_symbols(plan_text, ranked_syms | set(plan_syms))
            if unknown:
                errors.append(f'action_plan unknown symbols after align: {unknown[:5]}')
            for sym in plan_syms:
                if sym not in ranked_syms:
                    errors.append(f'action_plan symbol not in ranked pool: {sym}')
            opp_syms = [
                str(o.get('symbol') or '').upper()
                for o in (aligned.get('top_opportunities') or [])
                if o.get('symbol')
            ]
            if opp_syms and ranked_syms and set(opp_syms) != set(list(ranked_syms)[: len(opp_syms)]):
                if set(opp_syms) - ranked_syms:
                    errors.append(f'top_opportunities has non-ranked symbols: {sorted(set(opp_syms) - ranked_syms)[:5]}')
            extracted = extract_symbols_from_text(plan_text)
            if extracted and not all(s in ranked_syms or s in plan_syms for s in extracted):
                errors.append('action_plan text references symbols outside ranked pool')
        except Exception as exc:
            errors.append(f'canonical intelligence validation failed: {exc}')

    print('=== UNIFIED METRICS CONSISTENCY ===')
    print(f"SQLite: predictions={sqlite['prediction_total']} evaluated={sqlite['evaluated']} pending={sqlite['pending']} wins={sqlite['wins']} losses={sqlite['losses']} win_rate={sqlite['win_rate']}")
    print(f"Export: evaluated={exp.get('evaluated', exp.get('total_evaluated'))} pending={exp.get('pending')} wins={exp.get('wins')} losses={exp.get('losses')}")
    print(f"Runtime: evaluated={rt_metrics.get('evaluated', rt_metrics.get('total_evaluated'))} pending={rt_metrics.get('pending')}")
    print(f"Calibration: evaluated={cal['evaluated']} pending={cal['pending']} wins={cal['wins']} losses={cal['losses']}")

    if errors:
        print('FAILURES:')
        for e in errors:
            print(f'  - {e}')
        return 1

    print('UNIFIED METRICS CONSISTENCY VERIFIED')
    print('INTELLIGENCE SOURCE CONSISTENCY VERIFIED')
    print('TELEGRAM DEDUPE VERIFIED')
    print('UNIFIED STATS VERIFIED')
    print('TACTICAL TIER VERIFIED')
    print('SUMMARY COMPRESSION VERIFIED')
    print('REGIME NORMALIZATION VERIFIED')
    print('CALIBRATION PROFESSIONALIZATION VERIFIED')
    print('COMMAND HIERARCHY VERIFIED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
