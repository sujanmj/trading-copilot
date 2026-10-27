"""Focused checks for autonomous date-scoped missed-session recovery."""

import json
import sys
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.orchestration import missed_session_recovery as recovery


def test_session_calendar_excludes_weekend_and_exchange_holiday():
    def market_day(value):
        return value.weekday() < 5 and value.isoformat() != '2026-10-22'

    with patch('backend.analytics.market_calendar_router.is_india_market_day', side_effect=market_day):
        days = recovery._session_dates(date(2026, 10, 26), 5)
    assert days == ['2026-10-21', '2026-10-23']


def test_recovery_retries_pending_and_notifies_once():
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / 'missed_session_recovery.json'
        outcomes_path = Path(tmp) / 'candidate_outcomes.jsonl'
        calls = []
        sent = []

        def resolve(*, session_date, run_ai):
            calls.append((session_date, run_ai))
            row = {
                'snapshot_id': 'fri-1', 'session_date': session_date, 'symbol': 'TEST',
                'outcome': 'PENDING', 'pending_reason': 'insufficient_price_delta_evidence',
            }
            outcomes_path.write_text(json.dumps(row) + '\n', encoding='utf-8')
            return {'prediction_postmortem': {'pending': 1}}

        with (
            patch.object(recovery, '_session_dates', return_value=['2026-10-23']),
            patch.object(recovery, '_snapshot_dates', return_value={'2026-10-23'}),
            patch.object(recovery, '_data_path', return_value=state_path),
            patch('backend.trading.candidate_outcome_learning.resolve_candidate_outcomes', side_effect=resolve, create=True),
            patch('backend.trading.candidate_outcome_learning._outcomes_path', return_value=outcomes_path, create=True),
            patch('backend.trading.candidate_outcome_learning._load_jsonl', side_effect=lambda p: [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else [], create=True),
            patch('backend.analytics.eod_outcome_scoring.compute_eod_outcome_summary', return_value={'date': '2026-10-23', 'resolved': 0, 'alerts_pending_score': 1}),
            patch('backend.analytics.eod_outcome_scoring.persist_eod_summary'),
            patch('backend.analytics.prediction_postmortem.format_eod_postmortem_digest', return_value=''),
        ):
            first = recovery.recover_missed_sessions(today=date(2026, 10, 26), send_fn=lambda msg: sent.append(msg) or True)
            second = recovery.recover_missed_sessions(today=date(2026, 10, 26), send_fn=lambda msg: sent.append(msg) or True)

        assert len(calls) == 2, 'pending outcomes should be retried'
        assert len(sent) == 1, 'recovered review should be sent once per session'
        assert first['sessions'][0]['pending'] == 1 and second['sessions'][0]['pending'] == 1
        assert '2026-10-23' in sent[0] and 'insufficient_price_delta_evidence' in sent[0]


if __name__ == '__main__':
    test_session_calendar_excludes_weekend_and_exchange_holiday()
    test_recovery_retries_pending_and_notifies_once()
    print('MISSED_SESSION_RECOVERY_TESTS_PASS')
