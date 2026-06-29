#!/usr/bin/env python3
"""Regression tests for post-market /close pack freshness and tradecard no-fill."""

from __future__ import annotations

import json
import sys
import tempfile
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'POSTMARKET_CLOSE_REPORT_NO_FILL_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')


def _pack(generated_at: str, *, pack_mode: str = '') -> dict:
    return {
        'ok': True,
        'generated_at': generated_at,
        'pack_mode': pack_mode,
        'market_mode': 'INDIA_POSTMARKET_MODE',
        'summary': {'market_mode': 'INDIA_POSTMARKET_MODE'},
        'final_confidence': {
            'active_mode': 'INDIA_POSTMARKET_MODE',
            'watch': 2,
            'avoid': 1,
            'buy_candidate': 0,
        },
    }


def _append_sample_card() -> dict:
    from backend.trading import tradecard_journal as tcj

    card = {
        'generated_at': '2026-06-29T10:00:00+05:30',
        'session_date': '2026-06-29',
        'ticker': 'TESTCO',
        'status': 'VALID_ENTRY',
        'current_price': 99.50,
        'entry_zone': '100.00-101.00',
        'stop_loss': 98.00,
        'target_1': 103.00,
        'target_2': 105.00,
        'confidence': 'MEDIUM',
        'reason': 'paper watch entry',
    }
    record = tcj.journal_record_from_card(card)
    return tcj.append_journal_record(record)


def _close_patch_context(pack_path: Path, catchup):
    from backend.telegram import telegram_brief_scheduler as scheduler
    from backend.telegram import lazy_command_runner

    fixed_now = datetime.fromisoformat('2026-06-29T16:36:00+05:30')
    meta = {
        'report_age_min': 391,
        'scanner_age_min': 9,
        'scanner_fresh': True,
        'report_stale': True,
        'report_suppressed': False,
        'lines': {
            'report': 'Report: stale',
            'scanner': 'Scanner: fresh',
            'news': 'News: fresh',
        },
    }
    market_payload = {
        'market_mode': 'INDIA_AFTER_HOURS',
        'summary': {'market_mode': 'INDIA_AFTER_HOURS'},
        'cache_age_seconds': 0,
    }
    return (
        patch.object(scheduler, '_now_ist', return_value=fixed_now),
        patch.object(scheduler, '_run_safe_postmarket_pack_catchup_once', side_effect=catchup),
        patch.object(lazy_command_runner, 'DAILY_PACK_FILE', pack_path),
        patch('backend.telegram.india_mode_lock.is_premarket_phase', return_value=False),
        patch('backend.telegram.india_mode_lock.resolve_telegram_market_phase', return_value='INDIA_POSTMARKET_MODE'),
        patch('backend.telegram.india_mode_lock.is_live_market_hours_phase', return_value=False),
        patch('backend.telegram.lazy_command_runner.run_memory_only', return_value={'text': 'memory'}),
        patch('backend.analytics.aihub_tab_payloads.build_market_payload', return_value=market_payload),
        patch('backend.telegram.telegram_brief_scheduler._build_today_tomorrow_text', return_value='tomorrow'),
        patch('backend.analytics.unified_decision_engine.get_feed_freshness_meta', return_value=meta),
    )


def test_close_runs_postmarket_catchup_and_resolves_no_fill() -> int:
    from scripts._tradecard_journal_test_helpers import isolated_tradecard_store
    from backend.telegram.telegram_brief_scheduler import build_close_brief_text
    from backend.trading import tradecard_journal as tcj

    with tempfile.TemporaryDirectory() as tmp, isolated_tradecard_store():
        pack_path = Path(tmp) / 'daily_report_pack_latest.json'
        _write_json(pack_path, _pack('2026-06-29T05:04:04+00:00'))
        _append_sample_card()

        market_data = {
            'prices': {
                'TESTCO': {
                    'price': 99.40,
                    'high': 99.80,
                    'low': 99.10,
                    'volume': 1000,
                }
            }
        }
        catchup_calls: list[str] = []

        def _catchup():
            catchup_calls.append('called')
            _write_json(pack_path, _pack('2026-06-29T11:05:00+00:00', pack_mode='postmarket'))
            return {'ok': True, 'method': 'test'}

        patches = _close_patch_context(pack_path, _catchup)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], \
             patch.object(tcj, '_today', return_value='2026-06-29'), \
             patch.object(tcj, '_now_iso', return_value='2026-06-29T15:55:00+05:30'), \
             patch.object(tcj, '_load_market_data_with_optional_refresh', return_value=market_data):
            text = build_close_brief_text()

        if catchup_calls != ['called']:
            return _fail('/close should run one post-market catchup when morning pack is stale')
        if 'Report: fresh' not in text:
            return _fail('/close should show fresh report after post-market catchup')
        if 'Post-market pack generated at 2026-06-29 16:35 IST' not in text:
            return _fail('/close should show post-market pack generation time')
        if 'Close report is previous-session cache' in text:
            return _fail('/close should not warn stale when fresh post-market pack exists')
        if 'Report: stale' in text:
            return _fail('/close fresh top pack must not contain stale internal Market payload')
        if 'Market payload' not in text or 'Mode: <code>' not in text:
            return _fail('/close should include fresh post-market Market payload source')
        for marker in ('Generated: 1', 'Filled: 0', 'No fill: 1', 'Pending: 0'):
            if marker not in text:
                return _fail(f'missing tradecard EOD marker: {marker}')
        if 'Tradecard resolution: no fill 1 / pending 0 / resolved 0' not in text:
            return _fail('tradecard resolution summary missing no-fill result')

        summary = tcj.summarize_today_outcomes(session_date='2026-06-29')
        counts = summary.get('counts') or {}
        if int(counts.get('no_fill') or 0) != 1:
            return _fail('untouched entry zone should become NO_FILL')
        if int(counts.get('pending') or 0) != 0:
            return _fail('pending count should decrease after NO_FILL')
        if int(counts.get('filled') or 0) != 0:
            return _fail('NO_FILL should not count as filled')
        if summary.get('best') or summary.get('worst'):
            return _fail('NO_FILL should not be counted as win/loss performance')
        if tcj.get_active_valid_entry('TESTCO', session_date='2026-06-29') is not None:
            return _fail('NO_FILL card must not remain active')

        from backend.orchestration.alert_quality_engine import format_daily_review_quality_lines

        quality = '\n'.join(format_daily_review_quality_lines(tradecard_counts=counts))
        if 'Actual learning sample updated: 0' not in quality:
            return _fail('NO_FILL should not update actual learning sample')
        if 'No tradecard fills today. Watchlist accuracy only.' not in quality:
            return _fail('daily review should avoid W/L framing when no cards filled')
    return 0


def test_close_refuses_stale_pack_when_catchup_fails() -> int:
    from scripts._tradecard_journal_test_helpers import isolated_tradecard_store
    from backend.telegram.telegram_brief_scheduler import build_close_brief_text
    from backend.trading import tradecard_journal as tcj

    with tempfile.TemporaryDirectory() as tmp, isolated_tradecard_store():
        pack_path = Path(tmp) / 'daily_report_pack_latest.json'
        old_generated = '2026-06-29T05:04:04+00:00'
        _write_json(pack_path, _pack(old_generated))

        def _catchup():
            return {'ok': False, 'reason': 'source unavailable'}

        patches = _close_patch_context(pack_path, _catchup)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], \
             patch.object(tcj, '_today', return_value='2026-06-29'), \
             patch.object(tcj, '_load_market_data_with_optional_refresh', return_value=None):
            text = build_close_brief_text()

        if 'Close report is previous-session cache' not in text:
            return _fail('/close should refuse stale morning pack when catchup fails')
        if 'Post-market pack unavailable - source unavailable' not in text:
            return _fail('/close should include exact catchup failure reason')
        if old_generated in text:
            return _fail('/close must not show stale morning pack as current report body')
    return 0


def test_close_resolver_marks_unsampled_pending_no_fill() -> int:
    from scripts._tradecard_journal_test_helpers import isolated_tradecard_store
    from backend.trading import tradecard_journal as tcj

    with isolated_tradecard_store():
        _append_sample_card()
        with patch.object(tcj, '_today', return_value='2026-06-29'), \
             patch.object(tcj, '_now_iso', return_value='2026-06-29T15:55:00+05:30'), \
             patch.object(tcj, '_load_market_data_with_optional_refresh', return_value=None):
            result = tcj.resolve_close_pending_tradecards(
                session_date='2026-06-29',
                refresh=False,
            )

        if int(result.get('no_fill') or 0) != 1:
            return _fail('close resolver should mark unsampled same-day pending card NO_FILL')
        if int(result.get('pending') or 0) != 0:
            return _fail('unsampled same-day pending card must not remain pending after close')
    return 0


def test_next_session_watch_only_not_today_pending() -> int:
    from scripts._tradecard_journal_test_helpers import isolated_tradecard_store
    from backend.trading import tradecard_journal as tcj

    with isolated_tradecard_store():
        card = _append_sample_card()
        tcj.update_journal_record(str(card.get('id')), {
            'reason': 'NEXT-SESSION WATCH ONLY',
            'path_note': 'next-session watch only',
        })
        with patch.object(tcj, '_today', return_value='2026-06-29'), \
             patch.object(tcj, '_now_iso', return_value='2026-06-29T15:55:00+05:30'), \
             patch.object(tcj, '_load_market_data_with_optional_refresh', return_value=None):
            tcj.resolve_close_pending_tradecards(session_date='2026-06-29', refresh=False)
        counts = tcj.summarize_today_outcomes(session_date='2026-06-29').get('counts') or {}
        if int(counts.get('pending') or 0) != 0:
            return _fail('NEXT-SESSION WATCH ONLY must not remain as today pending tradecard')
        if int(counts.get('no_fill') or 0) != 1:
            return _fail('NEXT-SESSION WATCH ONLY same-day card should be closed as NO_FILL')
    return 0


def test_no_fill_resolver_has_no_ai_dependency() -> int:
    from scripts._tradecard_journal_test_helpers import isolated_tradecard_store
    from backend.trading import tradecard_journal as tcj

    with isolated_tradecard_store():
        record = _append_sample_card()
        tcj.append_path_sample(
            tradecard_id=str(record.get('id')),
            ticker='TESTCO',
            price=99.40,
            high=99.80,
            low=99.10,
            sampled_at='2026-06-29T15:55:00+05:30',
            source='test_eod_sample',
        )

        def _ai_should_not_run(*_args, **_kwargs):
            raise AssertionError('AI router should not run for simple no-fill resolver')

        fake_ai_router = types.ModuleType('backend.ai.ai_router')
        fake_ai_router.ask_ai = _ai_should_not_run

        with patch.object(tcj, '_today', return_value='2026-06-29'), \
             patch.dict(sys.modules, {'backend.ai.ai_router': fake_ai_router}):
            result = tcj.resolve_close_pending_tradecards(
                session_date='2026-06-29',
                refresh=False,
            )

        if int(result.get('updated') or 0) != 1:
            return _fail('resolver should update one pending card to NO_FILL')
        counts = tcj.summarize_today_outcomes(session_date='2026-06-29').get('counts') or {}
        if int(counts.get('no_fill') or 0) != 1 or int(counts.get('pending') or 0) != 0:
            return _fail('direct resolver should mark no-fill and clear pending')
    return 0


def main() -> int:
    for test in (
        test_close_runs_postmarket_catchup_and_resolves_no_fill,
        test_close_refuses_stale_pack_when_catchup_fails,
        test_close_resolver_marks_unsampled_pending_no_fill,
        test_next_session_watch_only_not_today_pending,
        test_no_fill_resolver_has_no_ai_dependency,
    ):
        code = test()
        if code:
            return code
    print('POSTMARKET_CLOSE_REPORT_NO_FILL_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
