from __future__ import annotations

import tempfile
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

IST = ZoneInfo('Asia/Kolkata')


def _report(rows, *, fresh=True, mode='PREMARKET'):
    return {
        'freshness_ok': fresh,
        'hard_stale_lock': not fresh,
        'market_mode': {'market_mode': mode},
        'top_setups': rows,
    }


def _row(ticker, *, action='WATCH', score=80, volume=2.0, reason='same setup', catalyst=''):
    return {
        'ticker': ticker,
        'action': action,
        'score': score,
        'volume_ratio': volume,
        'reason': reason,
        'catalyst': catalyst,
    }


def main() -> None:
    from backend.orchestration import alert_quality_engine as aq

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        aq.STATE_FILE = tmp_path / 'alert_quality_state.json'
        aq.MISSED_FILE = tmp_path / 'missed_opportunities.jsonl'

        suppressed: list[tuple[str, str, str]] = []
        sent: list[tuple[str, str]] = []
        aq._record_suppression = lambda c, r, d='': suppressed.append((c, r, d))
        aq._record_sent = lambda c, d, meta=None: sent.append((c, d))

        base = _report([
            _row('AAA', score=80, volume=2.0),
            _row('BBB', score=78, volume=1.8),
            _row('CCC', score=74, volume=1.5),
        ])

        d1 = aq.evaluate_scheduled_premarket_alert(
            'premarket_top3',
            base,
            now=datetime(2026, 6, 29, 8, 30, tzinfo=IST),
        )
        assert d1['send'] is True
        aq.record_scheduled_premarket_sent('premarket_top3', d1)

        d2 = aq.evaluate_scheduled_premarket_alert(
            'premarket_action',
            base,
            now=datetime(2026, 6, 29, 8, 45, tzinfo=IST),
        )
        assert d2['send'] is False
        assert d2['reason'] == 'duplicate_premarket'

        text_gate_1 = aq.evaluate_text_alert('premarket', 'same premarket alert body')
        assert text_gate_1['send'] is True
        aq.record_text_alert_sent('premarket', text_gate_1)
        text_gate_2 = aq.evaluate_text_alert('premarket', 'same premarket alert body')
        assert text_gate_2['send'] is False
        assert text_gate_2['reason'] == 'duplicate_premarket'
        text_gate_3 = aq.evaluate_text_alert('today', 'same today alert body')
        assert text_gate_3['send'] is True
        aq.record_text_alert_sent('today', text_gate_3)
        text_gate_4 = aq.evaluate_text_alert('today', 'same today alert body')
        assert text_gate_4['send'] is False
        assert text_gate_4['reason'] == 'no_meaningful_delta'

        small_score_delta = _report([
            _row('AAA', score=94, volume=2.0),
            _row('BBB', score=78, volume=1.8),
            _row('CCC', score=74, volume=1.5),
        ])
        d3 = aq.evaluate_scheduled_premarket_alert(
            'preopen_watch',
            small_score_delta,
            now=datetime(2026, 6, 29, 9, 10, tzinfo=IST),
        )
        assert d3['send'] is False

        big_score_delta = _report([
            _row('AAA', score=96, volume=2.0),
            _row('BBB', score=78, volume=1.8),
            _row('CCC', score=74, volume=1.5),
        ])
        d4 = aq.evaluate_scheduled_premarket_alert(
            'preopen_watch',
            big_score_delta,
            now=datetime(2026, 6, 29, 9, 10, tzinfo=IST),
        )
        assert d4['send'] is True
        assert any('score_delta:AAA' == r for r in d4['deltas'])
        aq.record_scheduled_premarket_sent('preopen_watch', d4)

        new_top3 = _report([
            _row('AAA', score=96, volume=2.0),
            _row('DDD', score=90, volume=3.1, catalyst='fresh result'),
            _row('BBB', score=78, volume=1.8),
        ])
        d5 = aq.evaluate_scheduled_premarket_alert(
            'preopen_watch',
            new_top3,
            now=datetime(2026, 6, 29, 9, 10, tzinfo=IST),
        )
        assert d5['send'] is True
        assert 'new_ticker_top3' in d5['deltas']
        aq.record_scheduled_premarket_sent('preopen_watch', d5)

        confirmed = _report([
            _row('AAA', action='CONFIRMED', score=96, volume=2.0),
            _row('DDD', score=90, volume=3.1, catalyst='fresh result'),
            _row('BBB', score=78, volume=1.8),
        ], mode='MARKET_HOURS')
        d6 = aq.evaluate_scheduled_premarket_alert(
            'open_confirmation',
            confirmed,
            now=datetime(2026, 6, 29, 9, 30, tzinfo=IST),
        )
        assert d6['send'] is True
        assert any(r.startswith('action_changed:AAA') for r in d6['deltas'])

        aq.STATE_FILE = tmp_path / 'alert_quality_stale_state.json'
        stale = _report([_row('AAA')], fresh=False, mode='MARKET_HOURS')
        stale_1 = aq.evaluate_scheduled_premarket_alert(
            'live_validation',
            stale,
            now=datetime(2026, 6, 29, 9, 20, tzinfo=IST),
        )
        stale_2 = aq.evaluate_scheduled_premarket_alert(
            'open_confirmation',
            stale,
            now=datetime(2026, 6, 29, 9, 30, tzinfo=IST),
        )
        assert stale_1['send'] is True and stale_1.get('warning_only')
        assert 'No fresh live setups yet' in stale_1['warning_text']
        assert stale_2['send'] is False
        assert stale_2['reason'] == 'stale_scanner_repeat'

        missed_signal = {
            'ticker': 'MISS1',
            'change_percent': 7.0,
            'volume_ratio': 2.0,
            'score': 88,
            'reason': 'extended without pullback',
        }
        assert aq.should_suppress_entry_missed_intraday({'signal': missed_signal, 'confidence': 0.88}) is True
        missed_text = aq.MISSED_FILE.read_text(encoding='utf-8')
        assert 'Missed — no chase. Waiting for pullback/retest.' in missed_text

        exceptional_signal = {
            'ticker': 'MISS2',
            'change_percent': 7.2,
            'volume_ratio': 3.2,
            'score': 95,
            'reason': 'fresh catalyst breakout volume',
        }
        assert aq.should_suppress_entry_missed_intraday({'signal': exceptional_signal, 'confidence': 0.95}) is False

        missed_output = aq.format_missed_opportunities()
        assert 'ENTRY MISSED' in missed_output
        assert 'Missed — no chase. Waiting for pullback/retest.' in missed_output

        quality_lines = aq.format_daily_review_quality_lines(
            alert_summary={'recent_sent': [{'category': 'PRE_MARKET'}]},
            tradecard_counts={'generated': 0, 'filled': 0, 'T1': 0, 'T2': 0, 'SL': 0, 'pending': 0},
        )
        assert any('Research watchlist sent: 1' in line for line in quality_lines)
        assert any('No tradecard fills today. Watchlist accuracy only.' in line for line in quality_lines)

        from backend.runtime import runtime_state as rs_mod

        aihub_cache = tmp_path / 'brain.json'
        aihub_cache.write_text('{"generated_at":"2026-06-09T12:51:22+00:00"}', encoding='utf-8')
        aihub_row = rs_mod._aihub_cache_row(
            'AIHub brain',
            aihub_cache,
            {'stale': True, 'data_age_hours': 441},
        )
        assert aihub_row['status'] == 'fresh'
        assert aihub_row['stale'] is False
        assert aihub_row['timestamp_key'] == 'mtime'
        assert aihub_row['source_status'] == 'underlying_source_stale'

        from backend.runtime import snapshot_freshness_monitor as sfm
        import backend.intelligence.active_snapshot as active_snapshot

        orig_age = sfm._snapshot_age_minutes_direct
        orig_stalled = sfm._pipeline_stalled
        orig_hb = sfm._load_heartbeats
        orig_ctx = sfm._closed_market_context
        orig_meta = active_snapshot.get_active_snapshot_meta
        try:
            sfm._snapshot_age_minutes_direct = lambda: 28
            sfm._pipeline_stalled = lambda: False
            sfm._load_heartbeats = lambda: {'sources': {}}
            active_snapshot.get_active_snapshot_meta = lambda: {
                'published_at': datetime.now(IST).isoformat(),
                'active_snapshot_id': 'test',
            }
            sfm._closed_market_context = lambda: {
                'closed': True,
                'period': 'weekend',
                'state': 'WEEKEND',
            }
            weekend_fresh = sfm.evaluate_snapshot_freshness()
            assert weekend_fresh['stale'] is False
            assert weekend_fresh['degraded'] is False
            assert weekend_fresh['closed_market_relaxed'] is True

            sfm._closed_market_context = lambda: {
                'closed': False,
                'period': 'market',
                'state': 'INDIA_MARKET_HOURS',
            }
            market_fresh = sfm.evaluate_snapshot_freshness()
            assert market_fresh['stale'] is True
            assert market_fresh['degraded'] is True
        finally:
            sfm._snapshot_age_minutes_direct = orig_age
            sfm._pipeline_stalled = orig_stalled
            sfm._load_heartbeats = orig_hb
            sfm._closed_market_context = orig_ctx
            active_snapshot.get_active_snapshot_meta = orig_meta

        from backend.telegram.formatting.telegram_formatter import format_status
        from backend.telegram.formatting.telegram_formatter import sanitize_telegram_text
        from backend.telegram.response_format import strip_stage_markers

        status_text = format_status({
            'primary_state': 'AFTER_HOURS',
            'lifecycle': {'lifecycle_state': 'AFTER_HOURS'},
            'session': {'session_display': 'WEEKEND'},
            'snapshot_freshness': {'age_display': '4m', 'health_tier': 'healthy', 'stale': False},
            'scanner_health': {'display': 'Scanner: 1m fresh'},
            'alert_eligibility': {
                'eligible': True,
                'execution_eligible': True,
                'suppression_count': 2,
                'last_suppression_reason': 'duplicate_premarket',
                'duplicate_alerts_avoided': 1,
                'ai_calls_avoided': 2,
            },
            'telegram_metrics': {'alerts_sent_today': 1, 'suppressed_today': 0},
            'source_freshness': {},
            'intelligence_freshness': {'rows': {}},
            'pipeline': {},
            'metrics': {
                'sections': {
                    'live_session': {'active_predictions': 20, 'resolved_today': 0},
                    'historical_calibration': {'evaluated_sample': 0},
                    'archived': {},
                }
            },
            'prediction_counts': {},
            'win_rate': {},
        })
        assert 'Alerts:' in status_text
        assert 'suppressed 2' in status_text
        assert 'Last suppression reason: duplicate_premarket' in status_text
        assert 'AI calls avoided: 2' in status_text
        assert 'active_book' in status_text
        assert 'live_session_pending' in status_text
        assert '�' not in sanitize_telegram_text('��ABC�')
        assert '�' not in strip_stage_markers('��ABC�')

    review_src = Path('backend/telegram/formatting/review_formatter.py').read_text(encoding='utf-8')
    assert 'Today outcomes:' not in review_src
    aq_src = Path('backend/orchestration/alert_quality_engine.py').read_text(encoding='utf-8')
    assert 'ask_ai' not in aq_src
    assert 'OpenAI' not in aq_src

    print('ALERT_QUALITY_ENGINE_OK')


if __name__ == '__main__':
    main()
