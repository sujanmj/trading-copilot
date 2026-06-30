#!/usr/bin/env python3
"""Phase 4A tests for Actual Learning Resolver."""

from __future__ import annotations

import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'ACTUAL_LEARNING_RESOLVER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _sources() -> dict:
    return {
        'tradecards': [
            {
                'ticker': 'NOFILL',
                'status': 'VALID_ENTRY',
                'outcome_status': 'NO_FILL',
                'price_at_signal': 100.0,
                'created_at': '2026-06-30T10:00:00+05:30',
            }
        ],
        'stock_today': {
            'top_pick': {
                'ticker': 'WATCHWIN',
                'action': 'WATCH_FOR_ENTRY',
                'price': 100.0,
                'score': 88,
                'timestamp': '2026-06-30T09:30:00+05:30',
            },
            'ranked_candidates': [
                {
                    'ticker': 'WATCHLOSS',
                    'action': 'WATCH_FOR_ENTRY',
                    'price': 100.0,
                    'score': 82,
                    'timestamp': '2026-06-30T09:30:00+05:30',
                },
                {
                    'ticker': 'WATCHNEUTRAL',
                    'action': 'WATCH_FOR_ENTRY',
                    'price': 100.0,
                    'score': 74,
                    'timestamp': '2026-06-30T09:30:00+05:30',
                },
                {
                    'ticker': 'MISSPRICE',
                    'action': 'WATCH_FOR_ENTRY',
                    'price': 100.0,
                    'score': 70,
                    'timestamp': '2026-06-30T09:30:00+05:30',
                },
            ],
        },
        'final_confidence': {
            'rows': [
                {
                    'ticker': 'AVOIDOK',
                    'action': 'AVOID',
                    'price': 100.0,
                    'score': 80,
                    'timestamp': '2026-06-30T09:30:00+05:30',
                },
                {
                    'ticker': 'AVOIDBAD',
                    'action': 'AVOID',
                    'price': 100.0,
                    'score': 80,
                    'timestamp': '2026-06-30T09:30:00+05:30',
                },
            ],
        },
        'scanner': {
            'signals': [
                {
                    'ticker': 'SCANNERWIN',
                    'price': 50.0,
                    'volume_ratio': 2.5,
                    'strength': 'STRONG',
                    'timestamp': '2026-06-30T10:00:00+05:30',
                }
            ]
        },
        'missed': [
            {
                'ticker': 'MISSEDUP',
                'price': 100.0,
                'move_pct': 4.0,
                'timestamp': '2026-06-30T11:00:00+05:30',
            }
        ],
    }


def _market_data() -> dict:
    return {
        'last_updated': '2026-06-30T10:30:00+00:00',
        'prices': {
            'WATCHWIN': {'price': 101.0, 'high': 101.5, 'low': 99.8},
            'WATCHLOSS': {'price': 99.0, 'high': 100.2, 'low': 98.8},
            'WATCHNEUTRAL': {'price': 100.2, 'high': 100.4, 'low': 99.9},
            'AVOIDOK': {'price': 99.0, 'high': 100.1, 'low': 98.7},
            'AVOIDBAD': {'price': 102.0, 'high': 102.5, 'low': 99.8},
            'SCANNERWIN': {'price': 50.6, 'high': 50.8, 'low': 49.8},
            'MISSEDUP': {'price': 104.0, 'high': 105.0, 'low': 100.0},
        },
    }


def _with_temp_db():
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    db_path = root / 'canonical_market_memory.db'
    state_path = root / 'actual_learning_last_run.json'
    return tmp, db_path, state_path


def test_resolver_classifies_and_is_idempotent() -> int:
    from backend.analytics.actual_learning_resolver import (
        AVOID_FAIL,
        AVOID_SUCCESS,
        HOLDING_PERIOD,
        MISSED_OPPORTUNITY,
        NO_FILL,
        run_actual_learning_resolver,
    )
    from backend.storage import market_memory_db as mmdb

    tmp, db_path, state_path = _with_temp_db()
    with tmp, patch.object(mmdb, 'get_market_memory_path', return_value=db_path):
        first = run_actual_learning_resolver(
            session_date='2026-06-30',
            sources=_sources(),
            market_data=_market_data(),
            refresh_cache=False,
            state_path=state_path,
        )
        if int(first.get('sample_updated') or 0) != 6:
            return _fail(f'expected 6 learning samples, got {first.get("sample_updated")}: {first!r}')
        if first.get('watchlist') != {'win': 2, 'loss': 1, 'neutral': 1}:
            return _fail(f'watchlist W/L/N mismatch: {first.get("watchlist")!r}')
        if first.get('avoid') != {'success': 1, 'fail': 1, 'neutral': 0}:
            return _fail(f'avoid success/fail mismatch: {first.get("avoid")!r}')
        if int((first.get('tradecard') or {}).get('no_fill') or 0) != 1:
            return _fail('tradecard NO_FILL should be counted separately')
        if int(first.get('pending_data') or 0) != 1:
            return _fail('missing price row should stay pending_data')

        conn = mmdb.get_connection()
        try:
            rows = conn.execute(
                """
                SELECT p.ticker, o.resolved_as, o.holding_period
                FROM outcomes o
                JOIN predictions p ON p.prediction_id = o.prediction_id
                WHERE o.holding_period = ?
                """,
                (HOLDING_PERIOD,),
            ).fetchall()
            outcome_by_ticker = {str(r['ticker']): str(r['resolved_as']) for r in rows}
        finally:
            conn.close()
        for ticker, expected in {
            'NOFILL': NO_FILL,
            'WATCHWIN': 'WIN',
            'WATCHLOSS': 'LOSS',
            'WATCHNEUTRAL': 'NEUTRAL',
            'AVOIDOK': AVOID_SUCCESS,
            'AVOIDBAD': AVOID_FAIL,
            'MISSEDUP': MISSED_OPPORTUNITY,
        }.items():
            if outcome_by_ticker.get(ticker) != expected:
                return _fail(f'{ticker} outcome {outcome_by_ticker.get(ticker)!r} expected {expected!r}')
        if 'MISSPRICE' in outcome_by_ticker:
            return _fail('missing price data must not create fake W/L outcome')

        second = run_actual_learning_resolver(
            session_date='2026-06-30',
            sources=_sources(),
            market_data=_market_data(),
            refresh_cache=False,
            state_path=state_path,
        )
        if int(second.get('written') or 0) != 0:
            return _fail('idempotent rerun must not write duplicate outcomes')
        if int(second.get('sample_updated') or 0) != 6:
            return _fail('idempotent rerun should still summarize resolved learning samples')
        if int(second.get('already_resolved') or 0) < 7:
            return _fail('idempotent rerun should detect already resolved rows')
    return 0


def test_canonical_summary_and_quality_lines() -> int:
    from backend.analytics.actual_learning_resolver import run_actual_learning_resolver
    from backend.analytics.actual_learning_resolver import format_actual_learning_close_lines
    from backend.orchestration.alert_quality_engine import format_daily_review_quality_lines
    from backend.storage import market_memory_db as mmdb
    from backend.storage.outcome_resolver import get_canonical_outcome_stats

    tmp, db_path, state_path = _with_temp_db()
    with tmp, patch.object(mmdb, 'get_market_memory_path', return_value=db_path):
        summary = run_actual_learning_resolver(
            session_date='2026-06-30',
            sources=_sources(),
            market_data=_market_data(),
            refresh_cache=False,
            state_path=state_path,
        )
        stats = get_canonical_outcome_stats()
        if int(stats.get('resolved_total') or 0) < 7:
            return _fail(f'market memory summary not updated: {stats!r}')
        if int(stats.get('pending_total') or 0) != 1:
            return _fail(f'pending_data should appear as one pending outcome: {stats!r}')
        memory = summary.get('market_memory') or {}
        if int(memory.get('predictions_tracked') or 0) < 8:
            return _fail(f'resolver summary missing predictions_tracked: {memory!r}')
        if int(memory.get('resolved_outcomes') or 0) < 7:
            return _fail(f'resolver summary missing resolved_outcomes: {memory!r}')
        if int(memory.get('pending_outcomes') or 0) != 1:
            return _fail(f'resolver summary missing pending_outcomes: {memory!r}')
        if memory.get('hit_rate') is None:
            return _fail(f'resolver summary missing hit_rate: {memory!r}')
        if memory.get('bullish_hit_rate') is None:
            return _fail(f'resolver summary missing bullish_hit_rate: {memory!r}')
        if memory.get('avoid_rejection_hit_rate') is None:
            return _fail(f'resolver summary missing avoid_rejection_hit_rate: {memory!r}')
        if not memory.get('last_resolved_timestamp'):
            return _fail(f'resolver summary missing last_resolved_timestamp: {memory!r}')
        lines = '\n'.join(format_daily_review_quality_lines(actual_learning_summary=summary))
        if 'Actual learning sample updated: 6' not in lines:
            return _fail(f'/close quality lines missing learning update: {lines}')
        if 'Watchlist resolved: 2/1/1' not in lines:
            return _fail(f'/close quality lines missing watchlist W/L/N: {lines}')
        if 'Avoid resolved: success 1 / fail 1' not in lines:
            return _fail(f'/close quality lines missing avoid counts: {lines}')
        if 'Pending data: 1' not in lines:
            return _fail(f'/close quality lines missing pending_data: {lines}')
        if 'Tradecard resolved/no-fill: 0/1' not in lines:
            return _fail(f'/close quality lines missing tradecard no-fill: {lines}')
        close_lines = '\n'.join(format_actual_learning_close_lines(summary))
        for needle in (
            'Actual learning sample updated: 6',
            'Watchlist resolved: 2/1/1',
            'Avoid resolved: success 1 / fail 1',
            'Pending data: 1',
        ):
            if needle not in close_lines or needle not in lines:
                return _fail(f'daily review and /close learning counts diverged for {needle!r}')
    return 0


def test_no_ai_dependency() -> int:
    from backend.analytics.actual_learning_resolver import run_actual_learning_resolver
    from backend.storage import market_memory_db as mmdb

    def _ai_should_not_run(*_args, **_kwargs):
        raise AssertionError('AI router must not run for actual learning resolver')

    fake_ai_router = types.ModuleType('backend.ai.ai_router')
    fake_ai_router.ask_ai = _ai_should_not_run

    tmp, db_path, state_path = _with_temp_db()
    with tmp, patch.object(mmdb, 'get_market_memory_path', return_value=db_path), \
         patch.dict(sys.modules, {'backend.ai.ai_router': fake_ai_router}):
        summary = run_actual_learning_resolver(
            session_date='2026-06-30',
            sources=_sources(),
            market_data=_market_data(),
            refresh_cache=False,
            state_path=state_path,
        )
    if int(summary.get('errors') or 0) != 0:
        return _fail(f'actual learning resolver errored with fake AI module: {summary!r}')
    return 0


def test_dry_run_does_not_write_db() -> int:
    from backend.analytics.actual_learning_resolver import run_actual_learning_resolver
    from backend.storage import market_memory_db as mmdb

    with patch.object(mmdb, 'init_market_memory_db', side_effect=AssertionError('dry run must not init DB')), \
         patch.object(mmdb, 'upsert_prediction', side_effect=AssertionError('dry run must not write predictions')), \
         patch.object(mmdb, 'upsert_outcome', side_effect=AssertionError('dry run must not write outcomes')):
        summary = run_actual_learning_resolver(
            session_date='2026-06-30',
            sources=_sources(),
            market_data=_market_data(),
            dry_run=True,
            refresh_cache=False,
        )
    if int(summary.get('sample_updated') or 0) != 6:
        return _fail(f'dry run should classify learning samples without DB writes: {summary!r}')
    if int((summary.get('market_memory') or {}).get('resolved_outcomes') or 0) != 8:
        return _fail(f'dry run market_memory summary mismatch: {summary!r}')
    return 0


def test_source_binding_uses_emitted_symbols_only() -> int:
    from backend.analytics.actual_learning_resolver import run_actual_learning_resolver
    from backend.storage import market_memory_db as mmdb

    emitted_rows = [
        {
            'timestamp': '2026-06-30T10:00:00+05:30',
            'alert_type': 'intraday',
            'category': 'INTRADAY_EVENT',
            'tickers': ['KEC'],
            'direction': 'BULLISH',
            'score': 0.86,
            'price_at_alert': 100.0,
            'reason_preview': 'live scanner watch',
        }
    ]
    quality_state = {
        'date': '2026-06-30',
        'premarket_last_signature': {
            'date': '2026-06-30',
            'rows': [
                {
                    'ticker': 'AJANTPHARM',
                    'action': 'WATCH',
                    'score': 84,
                    'price': 100.0,
                    'reason': 'premarket watch list',
                }
            ],
        },
    }
    market_data = {
        'last_updated': '2026-06-30T11:00:00+05:30',
        'prices': {
            'KEC': {'price': 102.0, 'timestamp': '2026-06-30T11:00:00+05:30'},
            'AJANTPHARM': {'price': 101.0, 'timestamp': '2026-06-30T11:00:00+05:30'},
            'MARUTI': {'price': 12000.0, 'timestamp': '2026-06-30T11:00:00+05:30'},
            'INFY': {'price': 1600.0, 'timestamp': '2026-06-30T11:00:00+05:30'},
        },
    }
    tmp, db_path, state_path = _with_temp_db()
    with tmp, patch.object(mmdb, 'get_market_memory_path', return_value=db_path), \
         patch('backend.orchestration.alert_event_log.read_alert_events_for_date', return_value=emitted_rows), \
         patch('backend.orchestration.alert_quality_engine._load_json', return_value=quality_state), \
         patch('backend.orchestration.alert_quality_engine.missed_opportunities_summary', return_value={'rows': [], 'count': 0}), \
         patch('backend.analytics.actual_learning_resolver._scanner_saved_candidates', return_value=[]), \
         patch('backend.trading.tradecard_journal.summarize_today_outcomes', return_value={'rows': [], 'counts': {}}):
        summary = run_actual_learning_resolver(
            session_date='2026-06-30',
            market_data=market_data,
            refresh_cache=False,
            state_path=state_path,
        )
    sent = set((summary.get('source_binding') or {}).get('sent_symbols') or [])
    if not {'KEC', 'AJANTPHARM'}.issubset(sent):
        return _fail(f'emitted KEC/AJANTPHARM candidates missing: {summary!r}')
    if {'MARUTI', 'INFY'} & sent:
        return _fail(f'stale/default symbols leaked into source binding: {summary!r}')
    if int(summary.get('sample_updated') or 0) != 2:
        return _fail(f'emitted candidates should resolve from fixture prices: {summary!r}')
    latest = {row.get('ticker') for row in summary.get('latest_outcomes') or []}
    if 'KEC' not in latest:
        return _fail(f'KEC-like intraday alert was not resolved: {summary!r}')
    return 0


def test_missing_price_is_pending_not_zero_neutral() -> int:
    from backend.analytics.actual_learning_resolver import run_actual_learning_resolver
    from backend.storage import market_memory_db as mmdb

    emitted_rows = [
        {
            'timestamp': '2026-06-30T10:00:00+05:30',
            'alert_type': 'intraday',
            'category': 'INTRADAY_EVENT',
            'tickers': ['HONASA'],
            'direction': 'BULLISH',
            'score': 0.82,
            'price_at_alert': 100.0,
            'reason_preview': 'live scanner watch',
        }
    ]
    tmp, db_path, state_path = _with_temp_db()
    with tmp, patch.object(mmdb, 'get_market_memory_path', return_value=db_path), \
         patch('backend.orchestration.alert_event_log.read_alert_events_for_date', return_value=emitted_rows), \
         patch('backend.orchestration.alert_quality_engine._load_json', return_value={'date': '2026-06-30'}), \
         patch('backend.orchestration.alert_quality_engine.missed_opportunities_summary', return_value={'rows': [], 'count': 0}), \
         patch('backend.analytics.actual_learning_resolver._scanner_saved_candidates', return_value=[]), \
         patch('backend.trading.tradecard_journal.summarize_today_outcomes', return_value={'rows': [], 'counts': {}}):
        summary = run_actual_learning_resolver(
            session_date='2026-06-30',
            market_data={'last_updated': '2026-06-30T11:00:00+05:30', 'prices': {}},
            refresh_cache=False,
            state_path=state_path,
        )
    if int(summary.get('pending_data') or 0) != 1:
        return _fail(f'missing price should be pending_data: {summary!r}')
    if summary.get('latest_outcomes'):
        return _fail(f'missing price must not create NEUTRAL +0.00 outcome: {summary!r}')
    return 0


def test_live_scanner_saved_candidate_included() -> int:
    from backend.analytics import actual_learning_resolver as resolver

    scanner = {
        'last_updated': '2026-06-30T10:05:00+05:30',
        'top_signals': [
            {'ticker': 'KEC', 'price': 100.0, 'score': 88, 'volume_ratio': 2.2},
        ],
    }
    with patch('backend.analytics.actual_learning_resolver._load_json', return_value=scanner):
        rows = resolver._scanner_saved_candidates('2026-06-30')
    if not rows or rows[0].get('ticker') != 'KEC':
        return _fail(f'current-day live scanner watch was not included: {rows!r}')
    if rows[0].get('source') != 'scanner_data_today':
        return _fail(f'current-day scanner candidate source mismatch: {rows!r}')
    return 0


def test_daily_review_learning_runs_before_formatting() -> int:
    from backend.orchestration import telegram_review
    from backend.runtime.market_snapshot import MarketSnapshot

    order: list[str] = []

    def _render(_snap):
        if order != ['learning']:
            raise AssertionError(f'review formatted before learning prep: {order!r}')
        return [('daily', 'Daily Review')]

    with patch('backend.orchestration.telegram_review.load_review_snapshot', return_value=MarketSnapshot(snapshot_id='test')), \
         patch('backend.orchestration.telegram_review.normalize_review_snapshot', side_effect=lambda snap: snap), \
         patch('backend.orchestration.telegram_review._prepare_daily_review_learning', side_effect=lambda: order.append('learning') or {'sample_updated': 1}), \
         patch('backend.telegram.formatting.review_formatter.render_review_messages', side_effect=_render), \
         patch('backend.orchestration.telegram_review._send_review_text', return_value=True):
        ok = telegram_review.push_review(command='review', cycle_id='test')
    if not ok:
        return _fail('push_review should succeed in learning-order fixture')
    if order != ['learning']:
        return _fail(f'learning prep did not run exactly once before formatting: {order!r}')
    return 0


def test_daily_review_learning_helper_order() -> int:
    from backend.orchestration import telegram_review

    order: list[str] = []

    with patch('backend.telegram.india_mode_lock.is_live_market_hours_phase', return_value=False), \
         patch('backend.telegram.india_mode_lock.is_premarket_phase', return_value=False), \
         patch('backend.trading.tradecard_journal.resolve_close_pending_tradecards', side_effect=lambda refresh=True: order.append('tradecard') or {'updated': 1}), \
         patch('backend.analytics.actual_learning_resolver.run_actual_learning_resolver', side_effect=lambda refresh_cache=True: order.append('learning') or {'sample_updated': 2, 'pending_data': 1}), \
         patch('backend.storage.outcome_resolver.refresh_memory_dashboard_cache', side_effect=lambda: order.append('memory') or True):
        summary = telegram_review._prepare_daily_review_learning()
    if order != ['tradecard', 'learning', 'memory']:
        return _fail(f'daily review learning helper order mismatch: {order!r}')
    if summary.get('sample_updated') != 2 or summary.get('pending_data') != 1:
        return _fail(f'daily review learning helper returned wrong summary: {summary!r}')
    return 0


def test_close_displays_actual_learning_summary() -> int:
    from backend.telegram.telegram_brief_scheduler import build_close_brief_text

    learning_summary = {
        'sample_updated': 2,
        'watchlist': {'win': 1, 'loss': 0, 'neutral': 1},
        'avoid': {'success': 1, 'fail': 0, 'neutral': 0},
        'tradecard': {'resolved': 0, 'no_fill': 1},
        'explanation': {
            'best_signal_today': 'WATCHWIN WIN +1.00%',
            'worst_signal_today': 'WATCHNEUTRAL NEUTRAL +0.20%',
            'trust_tomorrow': 'Trust scanner-confirmed setups.',
            'reduce_tomorrow': 'Reduce stale setups.',
        },
    }
    with patch('backend.telegram.india_mode_lock.is_premarket_phase', return_value=False), \
         patch('backend.telegram.india_mode_lock.resolve_telegram_market_phase', return_value='INDIA_AFTER_HOURS'), \
         patch('backend.telegram.india_mode_lock.is_live_market_hours_phase', return_value=False), \
         patch('backend.telegram.telegram_brief_scheduler._postmarket_close_pack_lines', return_value=(
             ['Report: fresh · 0m', 'Post-market pack generated at 2026-06-30 16:00 IST', ''],
             False,
             {'fresh': True, 'freshness_meta': {'lines': {'report': 'Report: fresh · 0m'}}},
         )), \
         patch('backend.trading.tradecard_journal.resolve_close_pending_tradecards', return_value={'updated': 0}), \
         patch('backend.trading.tradecard_journal.format_tradecard_review_section', return_value='<b>Tradecards:</b>\nGenerated: 1'), \
         patch('backend.trading.tradecard_journal.summarize_today_outcomes', return_value={'counts': {'generated': 1, 'no_fill': 1, 'pending': 0}}), \
         patch('backend.analytics.actual_learning_resolver.run_actual_learning_resolver', return_value=learning_summary), \
         patch('backend.telegram.lazy_command_runner.run_memory_only', return_value={'text': 'memory'}), \
         patch('backend.telegram.lazy_command_runner.run_market_only', return_value={'text': '<b>Market payload</b>\nReport: fresh · 0m'}), \
         patch('backend.telegram.telegram_brief_scheduler._build_today_tomorrow_text', return_value='tomorrow'):
        text = build_close_brief_text()

    for needle in (
        'Actual learning sample updated: 2',
        'Watchlist resolved: 1/0/1',
        'Avoid resolved: success 1 / fail 0',
        'Pending data: 0',
        'Tradecard resolved/no-fill: 0/1',
        'Best signal today: WATCHWIN WIN +1.00%',
    ):
        if needle not in text:
            return _fail(f'/close missing actual learning line: {needle}')
    return 0


def main() -> int:
    for test in (
        test_resolver_classifies_and_is_idempotent,
        test_canonical_summary_and_quality_lines,
        test_no_ai_dependency,
        test_dry_run_does_not_write_db,
        test_source_binding_uses_emitted_symbols_only,
        test_missing_price_is_pending_not_zero_neutral,
        test_live_scanner_saved_candidate_included,
        test_daily_review_learning_runs_before_formatting,
        test_daily_review_learning_helper_order,
        test_close_displays_actual_learning_summary,
    ):
        code = test()
        if code:
            return code
    print('ACTUAL_LEARNING_RESOLVER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
