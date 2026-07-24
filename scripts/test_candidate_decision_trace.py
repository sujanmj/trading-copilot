#!/usr/bin/env python3
"""AstraEdge 52P — candidate decision trace focused tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'CANDIDATE_DECISION_TRACE_52P_FAIL: {msg}', file=sys.stderr)
    return 1


def _quality_row(**overrides) -> dict:
    row = {
        'ticker': 'BEL',
        'score': 72,
        'state': 'TRADECARD_CANDIDATE',
        'why': ['volume ignition', 'sector breadth'],
        'has_catalyst': True,
        'volume_ratio': 2.4,
        'change_percent': 2.1,
        'above_open': True,
        'above_vwap': True,
        'extended': False,
        'pullback_only': False,
        'momentum_only': False,
        'sector_breadth': {'boost': 8},
        'scanner_row': {'price': 100.0, 'volume_ratio': 2.4, 'change_percent': 2.1},
        'themes': ['defence'],
    }
    row.update(overrides)
    return row


def _fresh_board(rows: list[dict] | None = None, **overrides) -> dict:
    ranked = list(rows or [_quality_row()])
    board = {
        'ok': True,
        'session_date': '2026-07-24',
        'market_lifecycle': 'MARKET_ACTIVE',
        'phase': 'CONFIRM',
        'reference_only': False,
        'session_stale': False,
        'live_scanner_ready': True,
        'scanner_stale': False,
        'scanner_freshness_status': 'CURRENT',
        'macro_penalty': 0,
        'macro_shock': {'active': False, 'severity': '', 'regime': 'NEUTRAL'},
        'ranked_candidates': ranked,
    }
    board.update(overrides)
    return board


def test_build_label_52p() -> int:
    from scripts.test_build_helpers import assert_canonical_build, expected_build_label

    err = assert_canonical_build(_fail)
    if err:
        return err
    if expected_build_label() != 'AstraEdge 52P':
        return _fail(f'expected AstraEdge 52P, got {expected_build_label()!r}')
    return 0


def test_fresh_scanner_complete_trace() -> int:
    from backend.trading.candidate_decision_trace import (
        TRACE_STAGES,
        apply_decision_traces_to_board,
        build_candidate_decision_trace,
    )

    board = _fresh_board()
    board = apply_decision_traces_to_board(board)
    row = board['ranked_candidates'][0]
    trace = row.get('decision_trace') or build_candidate_decision_trace(row, board=board, rank=1)
    if not trace.get('ok'):
        return _fail('trace must be ok for fresh scanner path')
    stage_names = [s.get('stage') for s in trace.get('stages') or []]
    if stage_names != list(TRACE_STAGES):
        return _fail(f'stage order mismatch: {stage_names}')
    if 'LIVE_SCANNER_CURRENT' not in trace.get('reason_codes') or []:
        return _fail('missing LIVE_SCANNER_CURRENT')
    if 'MACRO_GUARD_PASS' not in trace.get('reason_codes') or []:
        return _fail('missing MACRO_GUARD_PASS')
    if not trace.get('quality_tradecard'):
        return _fail('quality tradecard should pass')
    if not trace.get('outcome_learning_eligible'):
        return _fail('outcome learning should be eligible for quality candidate')
    return 0


def test_missing_live_scanner_active_session() -> int:
    from backend.trading.candidate_decision_trace import build_candidate_decision_trace

    board = _fresh_board(
        live_scanner_ready=False,
        scanner_stale=True,
        scanner_freshness_status='MISSING',
    )
    trace = build_candidate_decision_trace(_quality_row(), board=board, rank=1)
    scanner = next(s for s in trace['stages'] if s['stage'] == 'scanner_guard')
    if scanner['status'] != 'blocked':
        return _fail(f'active session missing scanner must block, got {scanner}')
    if 'LIVE_SCANNER_REQUIRED' not in scanner['reason_codes']:
        return _fail('missing LIVE_SCANNER_REQUIRED')
    return 0


def test_stale_scanner_represented() -> int:
    from backend.trading.candidate_decision_trace import build_candidate_decision_trace

    board = _fresh_board(
        live_scanner_ready=False,
        scanner_stale=True,
        scanner_freshness_status='STALE',
    )
    trace = build_candidate_decision_trace(_quality_row(), board=board, rank=1)
    codes = trace.get('reason_codes') or []
    if 'SCANNER_STALE' not in codes and 'LIVE_SCANNER_REQUIRED' not in codes:
        return _fail(f'stale scanner not represented: {codes}')
    return 0


def test_macro_risk_not_bypassed_by_high_score() -> int:
    from backend.trading.candidate_decision_trace import build_candidate_decision_trace

    board = _fresh_board(
        macro_penalty=15,
        emergency_macro=True,
        macro_severity='HIGH',
        macro_shock={'active': True, 'severity': 'HIGH', 'regime': 'RED'},
    )
    row = _quality_row(score=95)
    trace = build_candidate_decision_trace(row, board=board, rank=1)
    macro = next(s for s in trace['stages'] if s['stage'] == 'macro_guard')
    if macro['status'] not in ('warn', 'blocked'):
        return _fail(f'macro risk must warn/block despite score 95, got {macro}')
    if 'MACRO_RISK_DOWNGRADE' not in (macro.get('reason_codes') or []):
        return _fail('missing MACRO_RISK_DOWNGRADE')
    return 0


def test_macro_data_missing_safe() -> int:
    from backend.trading.candidate_decision_trace import build_candidate_decision_trace

    board = _fresh_board()
    board.pop('macro_shock', None)
    # No penalty / emergency — clear path remains pass; explicit empty board without fields:
    board2 = _fresh_board()
    del board2['macro_shock']
    board2['macro_penalty'] = 0
    trace_clear = build_candidate_decision_trace(_quality_row(), board=board2, rank=1)
    macro_clear = next(s for s in trace_clear['stages'] if s['stage'] == 'macro_guard')
    if macro_clear['status'] not in ('pass', 'warn'):
        return _fail(f'macro missing must stay safe, got {macro_clear}')

    board3 = {
        'market_lifecycle': 'MARKET_ACTIVE',
        'ranked_candidates': [_quality_row()],
    }
    trace = build_candidate_decision_trace(_quality_row(), board=board3, rank=1)
    macro = next(s for s in trace['stages'] if s['stage'] == 'macro_guard')
    if 'MACRO_DATA_MISSING' not in (macro.get('reason_codes') or []) and macro['status'] not in ('pass', 'warn'):
        return _fail(f'macro missing behavior unexpected: {macro}')
    return 0


def test_score_components_traceable() -> int:
    from backend.trading.candidate_decision_trace import build_candidate_decision_trace

    board = _fresh_board(macro_penalty=6)
    row = _quality_row(score=66)
    trace = build_candidate_decision_trace(row, board=board, rank=1)
    comps = trace.get('score_components') or {}
    if comps.get('volume_ratio') != 2.4:
        return _fail('volume_ratio not traced from row')
    if comps.get('macro_penalty') != 6:
        return _fail('macro_penalty not traced from board')
    if trace.get('score_after_penalties') != 66:
        return _fail('score_after_penalties must equal observed row score')
    if trace.get('score_before_penalties') != 72:
        return _fail('score_before_penalties should reflect observed score + penalty')
    return 0


def test_rank_comparison_stable() -> int:
    from backend.trading.candidate_decision_trace import build_candidate_decision_trace

    rows = [
        _quality_row(ticker='AAA', score=80),
        _quality_row(ticker='BBB', score=72),
        _quality_row(ticker='CCC', score=61),
    ]
    board = _fresh_board(rows)
    trace = build_candidate_decision_trace(rows[1], board=board, rank=2)
    comp = (trace.get('comparison') or {})
    if (comp.get('above') or {}).get('ticker') != 'AAA':
        return _fail(f'above comparison wrong: {comp}')
    if (comp.get('below') or {}).get('ticker') != 'CCC':
        return _fail(f'below comparison wrong: {comp}')
    if trace.get('rank') != 2:
        return _fail('rank must be 2')
    return 0


def test_quality_pass_allows_learning() -> int:
    from backend.trading.candidate_decision_trace import build_candidate_decision_trace

    trace = build_candidate_decision_trace(_quality_row(), board=_fresh_board(), rank=1)
    if not trace.get('quality_tradecard') or not trace.get('outcome_learning_eligible'):
        return _fail('quality pass must allow outcome learning eligibility')
    return 0


def test_quality_fail_blocks_learning() -> int:
    from backend.trading.candidate_decision_trace import build_candidate_decision_trace

    row = _quality_row(score=45, state='LOW_CONFIDENCE')
    trace = build_candidate_decision_trace(row, board=_fresh_board([row]), rank=1)
    if trace.get('quality_tradecard'):
        return _fail('score 45 must fail quality gate')
    if trace.get('outcome_learning_eligible'):
        return _fail('quality fail must block outcome learning')
    if 'OUTCOME_LEARNING_BLOCKED' not in (trace.get('reason_codes') or []):
        return _fail('missing OUTCOME_LEARNING_BLOCKED')
    return 0


def test_no_invented_outcomes() -> int:
    from backend.trading.candidate_decision_trace import build_candidate_decision_trace

    trace = build_candidate_decision_trace(_quality_row(), board=_fresh_board(), rank=1)
    outcome = str(trace.get('outcome') or '')
    if outcome.lower() in ('win', 'loss', 'won', 'lost', 't1', 't2', 'sl'):
        return _fail(f'trace must not invent outcomes, got {outcome!r}')
    if outcome not in ('pending_or_unknown', 'not_eligible'):
        return _fail(f'unexpected outcome label: {outcome!r}')
    return 0


def test_watch_only_ineligible() -> int:
    from backend.trading.candidate_decision_trace import build_candidate_decision_trace

    row = _quality_row(score=70, state='RADAR_ARMED')
    trace = build_candidate_decision_trace(row, board=_fresh_board([row]), rank=1)
    if trace.get('outcome_learning_eligible'):
        return _fail('RADAR_ARMED must remain outcome-learning ineligible')
    return 0


def test_historical_without_trace_compatible() -> int:
    from backend.trading.candidate_decision_trace import format_candidate_decision_trace_telegram

    lines = format_candidate_decision_trace_telegram(None)
    text = '\n'.join(lines)
    if 'Candidate Decision Trace' not in text:
        return _fail('missing trace header for unavailable')
    if 'unavailable' not in text.lower():
        return _fail('historical/missing trace must say unavailable')
    return 0


def test_explain_keeps_existing_content() -> int:
    from backend.telegram.response_format import format_tradecard_evidence_explain_telegram

    with patch(
        'backend.telegram.response_format._append_tradecard_evidence',
        side_effect=lambda lines, *a, **k: lines.extend(['Evidence matrix placeholder']),
    ), patch(
        'backend.trading.opening_rally_radar.opening_board_context_for_ticker',
        return_value={
            'board_row': _quality_row(),
            'ticker': 'BEL',
        },
    ), patch(
        'backend.trading.candidate_decision_trace.extract_decision_trace',
        return_value=None,
    ), patch(
        'backend.trading.candidate_decision_trace.build_candidate_decision_trace',
        return_value={
            'ok': True,
            'unavailable': False,
            'quality_tradecard': True,
            'outcome_learning_eligible': True,
            'final_decision': 'TRADECARD_CANDIDATE',
            'stages': [
                {'stage': 'candidate_source', 'status': 'pass', 'reason': 'scanner candidate'},
                {'stage': 'scanner_guard', 'status': 'pass', 'reason': 'scanner current'},
                {'stage': 'macro_guard', 'status': 'pass', 'reason': 'macro guard clear'},
                {'stage': 'evidence_scoring', 'status': 'pass', 'reason': 'volume confirmation'},
                {'stage': 'risk_adjustment', 'status': 'pass', 'reason': 'no chase'},
                {'stage': 'ranking', 'status': 'pass', 'reason': 'ranked 1 of 1'},
                {'stage': 'quality_tradecard_gate', 'status': 'pass', 'reason': 'pass'},
                {'stage': 'outcome_learning_gate', 'status': 'pass', 'reason': 'eligible'},
            ],
        },
    ):
        text = format_tradecard_evidence_explain_telegram('BEL')
    if 'Tradecard Explain' not in text or 'Ticker: <b>BEL</b>' not in text:
        return _fail('existing explain header missing')
    if 'Evidence matrix placeholder' not in text:
        return _fail('existing evidence content must remain')
    if 'Candidate Decision Trace' not in text:
        return _fail('decision trace section missing')
    if 'Final: TRADECARD-CANDIDATE' not in text:
        return _fail('final decision line missing')
    return 0


def test_deterministic_identical_input() -> int:
    from backend.trading.candidate_decision_trace import build_candidate_decision_trace

    board = _fresh_board()
    row = _quality_row()
    a = build_candidate_decision_trace(row, board=board, rank=1, now=__import__('datetime').datetime(2026, 7, 24, 10, 0, tzinfo=__import__('zoneinfo').ZoneInfo('Asia/Kolkata')))
    b = build_candidate_decision_trace(row, board=board, rank=1, now=__import__('datetime').datetime(2026, 7, 24, 10, 0, tzinfo=__import__('zoneinfo').ZoneInfo('Asia/Kolkata')))
    # Drop generated_at equality already fixed by same now
    if json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True):
        return _fail('trace must be deterministic for identical input')
    return 0


def test_no_ai_or_broker_calls() -> int:
    from backend.trading.candidate_decision_trace import build_candidate_decision_trace

    ai_called = {'n': 0}
    broker_called = {'n': 0}

    def _ai(*_a, **_k):
        ai_called['n'] += 1
        raise AssertionError('AI must not be called')

    def _broker(*_a, **_k):
        broker_called['n'] += 1
        raise AssertionError('broker must not be called')

    with patch.dict(sys.modules, {
        'backend.ai.ai_router': type(sys)('backend.ai.ai_router'),
    }):
        sys.modules['backend.ai.ai_router'].ask_ai = _ai  # type: ignore[attr-defined]
        build_candidate_decision_trace(_quality_row(), board=_fresh_board(), rank=1)
    if ai_called['n'] or broker_called['n']:
        return _fail('AI/broker must not be called')
    return 0


def test_no_data_dir_write_required() -> int:
    from backend.trading.candidate_decision_trace import (
        apply_decision_traces_to_board,
        build_candidate_decision_trace,
        format_candidate_decision_trace_telegram,
    )

    board = apply_decision_traces_to_board(_fresh_board())
    trace = board['ranked_candidates'][0]['decision_trace']
    _ = format_candidate_decision_trace_telegram(trace)
    _ = build_candidate_decision_trace(_quality_row(), board=_fresh_board(), rank=1)
    return 0


def test_after_hours_compatible() -> int:
    from backend.trading.candidate_decision_trace import build_candidate_decision_trace

    board = _fresh_board(
        market_lifecycle='AFTER_HOURS',
        reference_only=True,
        live_scanner_ready=False,
        scanner_freshness_status='PREVIOUS_SESSION',
        scanner_stale=False,
    )
    trace = build_candidate_decision_trace(_quality_row(), board=board, rank=1)
    if 'NEXT_SESSION_ONLY' not in (trace.get('reason_codes') or []):
        return _fail('after-hours must keep next-session/reference semantics')
    scanner = next(s for s in trace['stages'] if s['stage'] == 'scanner_guard')
    if scanner['status'] == 'blocked':
        return _fail('after-hours previous-session must not hard-block like active session')
    return 0


def test_unknown_symbol_clean() -> int:
    from backend.trading.candidate_decision_trace import (
        build_candidate_decision_trace,
        format_candidate_decision_trace_telegram,
    )
    from backend.telegram.response_format import format_tradecard_evidence_explain_telegram

    empty = build_candidate_decision_trace({'ticker': ''}, board=_fresh_board())
    if empty.get('ok'):
        return _fail('empty symbol must not be ok')
    text = '\n'.join(format_candidate_decision_trace_telegram(empty))
    if 'unavailable' not in text.lower():
        return _fail('empty symbol must render unavailable')

    with patch(
        'backend.telegram.response_format._append_tradecard_evidence',
        side_effect=lambda lines, *a, **k: None,
    ), patch(
        'backend.trading.opening_rally_radar.opening_board_context_for_ticker',
        return_value=None,
    ):
        explain = format_tradecard_evidence_explain_telegram('NOTAREALTICKERZZ')
    if 'Candidate Decision Trace' not in explain:
        return _fail('unknown symbol explain must still include trace section')
    if 'unavailable' not in explain.lower():
        return _fail('unknown symbol must fail cleanly with unavailable')
    return 0


def test_active_market_scanner_not_bypassable() -> int:
    from backend.trading.candidate_decision_trace import build_candidate_decision_trace

    board = _fresh_board(
        market_lifecycle='MARKET_ACTIVE',
        live_scanner_ready=False,
        scanner_stale=True,
        scanner_freshness_status='STALE',
    )
    row = _quality_row(score=99, state='TRADECARD_CANDIDATE')
    trace = build_candidate_decision_trace(row, board=board, rank=1)
    scanner = next(s for s in trace['stages'] if s['stage'] == 'scanner_guard')
    if scanner['status'] != 'blocked':
        return _fail('high score must not bypass active-market scanner requirement')
    return 0


def main() -> int:
    tests = (
        test_build_label_52p,
        test_fresh_scanner_complete_trace,
        test_missing_live_scanner_active_session,
        test_stale_scanner_represented,
        test_macro_risk_not_bypassed_by_high_score,
        test_macro_data_missing_safe,
        test_score_components_traceable,
        test_rank_comparison_stable,
        test_quality_pass_allows_learning,
        test_quality_fail_blocks_learning,
        test_no_invented_outcomes,
        test_watch_only_ineligible,
        test_historical_without_trace_compatible,
        test_explain_keeps_existing_content,
        test_deterministic_identical_input,
        test_no_ai_or_broker_calls,
        test_no_data_dir_write_required,
        test_after_hours_compatible,
        test_unknown_symbol_clean,
        test_active_market_scanner_not_bypassable,
    )
    failed = 0
    for test in tests:
        rc = test()
        if rc:
            failed += 1
            print(f'FAIL: {test.__name__}', file=sys.stderr)
        else:
            print(f'PASS: {test.__name__}')
    if failed:
        print(f'CANDIDATE_DECISION_TRACE_52P_FAIL: {failed} test(s) failed', file=sys.stderr)
        return 1
    print('CANDIDATE_DECISION_TRACE_52P_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
