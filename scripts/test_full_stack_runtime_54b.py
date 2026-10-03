"""Offline source/adapter tests. All persistence is in temporary directories."""
from __future__ import annotations

import ast
import copy
import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.collectors import nse_preopen_iep as nse
from backend.runtime.full_stack_adapter import adapt_full_stack
from backend.runtime.full_stack_contract import completed_candles, validate_bundle
from backend.runtime.full_stack_source import build_source_bundle, daily_previous_close

DAY = '2026-09-30'
def clock(value):
    return nse.timestamp(f'{DAY}T{value}+05:30')

def packet(event='09:00:00', price=101, symbol='TEST', response='09:00:00'):
    return {'timestamp': clock(response).isoformat(), 'data': [{
        'metadata': {'symbol': symbol, 'previousClose': 100},
        'detail': {'preOpenMarket': {'IEP': price, 'finalPrice': 0,
                  'totalBuyQuantity': 20, 'totalSellQuantity': 10,
                  'lastUpdateTime': clock(event).isoformat()}}}]}

def complete_capture(single=False):
    capture = nse.new_capture(clock('08:58:00'))
    now = clock('09:00:00')
    while now <= clock('09:15:30'):
        event = '09:00:00' if single or now < clock('09:07:00') else '09:07:00'
        price = 101 if event == '09:00:00' else 102
        p = packet(event, price, response=now.strftime('%H:%M:%S'))
        nse.record_poll(capture, now, nse.normalize_events(p, DAY, now))
        now += timedelta(seconds=30)
    return capture

def providers():
    quote = {'symbol': 'TEST', 'source': 'ANGEL_FULL', 'ltp': 103, 'previous_close': 100,
             'exch_trade_time': clock('09:24:50').isoformat(),
             'exch_feed_time': clock('09:24:55').isoformat()}
    q = Mock(return_value={'source_state': 'READY', 'data': {'TEST': quote}})
    def candles(symbol, interval, start, end):
        if interval == 'ONE_DAY':
            data = [['2026-09-29T09:15:00+05:30', 99, 102, 98, 100, 1000]]
        else:
            minutes = 1 if interval == 'ONE_MINUTE' else 5
            data = []
            now = clock('09:15:00')
            while now <= end:
                data.append([now.isoformat(), 101, 104, 100, 103, 500])
                now += timedelta(minutes=minutes)
        return {'source_state': 'READY', 'symbol': symbol, 'interval': interval, 'data': data}
    return q, Mock(side_effect=candles)

def ready_bundle():
    q, c = providers()
    with patch('backend.runtime.full_stack_source.is_cash_session', side_effect=lambda day: day.weekday() < 5):
        return build_source_bundle('TEST', clock('09:25:00').isoformat(), capture=complete_capture(), quote_fetch=q, candle_fetch=c)


class CaptureTests(unittest.TestCase):
    def test_normalization_closed_contract(self):
        event = nse.normalize_events(packet(), DAY, clock('09:00:00'))[0]
        self.assertEqual(event['source'], nse.SOURCE)
        self.assertEqual(len(event), 11)
        self.assertEqual(event['iep'], 101)

    def test_bad_timestamp_session_future_and_price(self):
        for field, value in [('lastUpdateTime', '09:00:00'), ('IEP', float('nan')), ('IEP', True),
                             ('IEP', 0), ('lastUpdateTime', '2026-09-29T09:00:00+05:30'),
                             ('lastUpdateTime', clock('09:01:00').isoformat())]:
            with self.subTest(field=field, value=value):
                p = packet()
                p['data'][0]['detail']['preOpenMarket'][field] = value
                with self.assertRaises(ValueError):
                    nse.normalize_events(p, DAY, clock('09:00:00'))

    def test_wrong_and_future_response(self):
        for time in ('2026-09-29T09:00:00+05:30', clock('09:01:00').isoformat()):
            p = packet()
            p['timestamp'] = time
            with self.assertRaises(ValueError):
                nse.normalize_events(p, DAY, clock('09:00:00'))

    def test_dedup_is_not_poll_count(self):
        capture = complete_capture()
        self.assertEqual(capture['poll_count'], 32)
        self.assertEqual(len(capture['events_by_symbol']['TEST']), 2)
        self.assertEqual(capture['coverage_state'], 'COMPLETE')

    def test_range_and_reference(self):
        result = nse.derive_premarket(complete_capture(), 'TEST', clock('09:25:00'))
        self.assertEqual(result['missing_inputs'], [])
        self.assertEqual((result['premarket_low'], result['premarket_high'], result['premarket_reference_price']), (101, 102, 102))

    def test_same_price_distinct_source_times_is_valid(self):
        capture = complete_capture()
        capture['events_by_symbol']['TEST'][1]['iep'] = 101
        result = nse.derive_premarket(capture, 'TEST', clock('09:25:00'))
        self.assertEqual(result['missing_inputs'], [])
        self.assertEqual(result['premarket_high'], result['premarket_low'])

    def test_single_event_insufficient(self):
        result = nse.derive_premarket(complete_capture(single=True), 'TEST', clock('09:25:00'))
        self.assertEqual(result['missing_inputs'], ['RANGE_SOURCE_INSUFFICIENT'])
        self.assertIsNone(result['premarket_high'])

    def test_cutoff_reference_lookahead(self):
        result = nse.derive_premarket(complete_capture(), 'TEST', clock('09:05:00'))
        self.assertEqual(result['premarket_reference_price'], 101)
        self.assertIsNone(result['premarket_high'])

    def test_late_start_gap_and_short_end_partial(self):
        for key, value in [('capture_started_at', clock('09:00:00').isoformat()),
                           ('max_successful_poll_gap_seconds', 61),
                           ('last_successful_poll_at', clock('09:15:29').isoformat()),
                           ('first_successful_poll_at', clock('09:00:31').isoformat())]:
            capture = complete_capture()
            capture[key] = value
            self.assertEqual(nse.coverage_state(capture), 'PARTIAL')
            self.assertIsNone(nse.derive_premarket(capture, 'TEST', clock('09:25:00'))['premarket_high'])

    def test_coverage_threshold_boundaries(self):
        capture = complete_capture()
        capture['max_successful_poll_gap_seconds'] = 60
        capture['first_successful_poll_at'] = clock('09:00:30').isoformat()
        self.assertEqual(nse.coverage_state(capture), 'COMPLETE')

    def test_symbol_missing_polls_and_overflow_fail_closed(self):
        for key, value in [('max_gap', 61), ('overflow', True), ('first', clock('09:07:00').isoformat())]:
            capture = complete_capture()
            capture['symbol_coverage']['TEST'][key] = value
            self.assertIn('PREOPEN_COVERAGE_INCOMPLETE', nse.derive_premarket(capture, 'TEST', clock('09:25:00'))['missing_inputs'])

    def test_source_error_and_not_started(self):
        capture = nse.new_capture(clock('08:58:00'))
        self.assertEqual(nse.coverage_state(capture), 'NOT_STARTED')
        nse.record_poll(capture, clock('09:00:00'))
        self.assertEqual(capture['coverage_state'], 'SOURCE_ERROR')

    def test_cache_session_and_atomic_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'iep.json'
            capture = complete_capture()
            nse.save_capture(capture, path)
            self.assertEqual(nse.load_capture(DAY, path), capture)
            self.assertIsNone(nse.load_capture('2026-10-01', path))
            path.write_text('corrupt')
            self.assertIsNone(nse.load_capture(DAY, path))

    def test_weekend_holiday_and_launch_windows(self):
        with patch.object(nse, 'is_cash_session', return_value=True):
            self.assertTrue(nse.is_capture_window(clock('08:58:00')))
            self.assertFalse(nse.is_capture_window(clock('08:57:59')))
            self.assertFalse(nse.is_capture_window(clock('09:15:31')))
        with patch.object(nse, 'is_cash_session', return_value=False):
            self.assertFalse(nse.is_capture_window(clock('09:00:00')))

    def test_duplicate_dispatch_and_local_disable(self):
        fake = Mock()
        fake.is_alive.return_value = True
        with patch.dict('os.environ', {'LOCAL_ONLY': '0', 'DISABLE_SCHEDULER': '0'}), \
                patch.object(nse, 'is_cash_session', return_value=True), \
                patch.object(nse, '_worker', None), patch.object(nse, '_started_sessions', set()), \
                patch.object(nse.threading, 'Thread', return_value=fake):
            self.assertTrue(nse.start_capture(clock('08:58:00')))
            self.assertFalse(nse.start_capture(clock('08:58:00')))
            fake.start.assert_called_once()
        with patch.dict('os.environ', {'LOCAL_ONLY': '1'}):
            self.assertFalse(nse.start_capture(clock('08:58:00')))

    def test_normal_http_and_no_retry_on_denial(self):
        with patch.object(nse.requests, 'Session') as session:
            client = nse.OfficialNSEClient()
            session.return_value.get.return_value.raise_for_status.side_effect = nse.requests.HTTPError('denied')
            with self.assertRaises(nse.requests.HTTPError):
                client.fetch()
            session.return_value.get.assert_called_once()
            client.close()
            session.return_value.close.assert_called_once()

    def test_cross_process_lock_does_not_start_duplicate_client(self):
        import fcntl
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'capture.lock'
            with path.open('a') as holder:
                fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(nse, 'get_data_path', return_value=path), patch.object(nse, 'OfficialNSEClient') as client:
                    nse._capture_worker(DAY)
                    client.assert_not_called()

    def test_failed_poll_gap_and_restart_preserved(self):
        capture = nse.new_capture(clock('08:58:00'))
        events = nse.normalize_events(packet(), DAY, clock('09:00:00'))
        nse.record_poll(capture, clock('09:00:00'), events)
        nse.record_poll(capture, clock('09:00:25'), None)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'capture.json'
            nse.save_capture(capture, path)
            resumed = nse.load_capture(DAY, path)
            nse.record_poll(resumed, clock('09:15:30'), events)
            self.assertEqual(resumed['coverage_state'], 'PARTIAL')
            self.assertEqual(resumed['failed_poll_count'], 1)
            self.assertEqual(resumed['capture_started_at'], clock('08:58:00').isoformat())

    def test_worker_persists_source_error_and_closes_http(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(nse, 'get_data_path', side_effect=lambda rel: Path(directory) / Path(rel).name), \
                    patch.object(nse, 'OfficialNSEClient') as client:
                client.return_value.fetch.side_effect = nse.requests.HTTPError('blocked')
                nse._capture_worker(DAY, now_fn=lambda: clock('09:15:30'))
                client.return_value.fetch.assert_called_once()
                client.return_value.close.assert_called_once()
                captured = nse.load_capture(DAY)
                self.assertEqual(captured['coverage_state'], 'SOURCE_ERROR')
                self.assertEqual(captured['failed_poll_count'], 1)

    def test_monitor_is_background_singleton_and_dispatches(self):
        fake = Mock()
        fake.is_alive.return_value = True
        with patch.dict('os.environ', {'LOCAL_ONLY': '0', 'DISABLE_SCHEDULER': '0'}), \
                patch.object(nse, '_monitor', None), patch.object(nse.threading, 'Thread', return_value=fake) as thread:
            self.assertTrue(nse.start_automatic_capture())
            self.assertFalse(nse.start_automatic_capture())
            fake.start.assert_called_once()
            self.assertTrue(thread.call_args.kwargs['daemon'])
            callback = thread.call_args.kwargs['target']
            with patch.object(nse, 'start_capture') as dispatch, patch.object(nse.time, 'sleep', side_effect=StopIteration):
                with self.assertRaises(StopIteration):
                    callback()
                dispatch.assert_called_once()

    def test_full_worker_window_is_automatically_completed(self):
        state = {'now': clock('08:58:00')}
        def sleep(seconds):
            state['now'] += timedelta(seconds=seconds)
        def fetch():
            event = '09:00:00' if state['now'] < clock('09:07:00') else '09:07:00'
            return packet(event, 101 if event == '09:00:00' else 102,
                          response=state['now'].strftime('%H:%M:%S'))
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(nse, 'get_data_path', side_effect=lambda rel: Path(directory) / Path(rel).name), \
                    patch.object(nse.time, 'sleep', side_effect=sleep), patch.object(nse, 'OfficialNSEClient') as client:
                client.return_value.fetch.side_effect = fetch
                nse._capture_worker(DAY, now_fn=lambda: state['now'])
                capture = nse.load_capture(DAY)
                self.assertEqual(capture['coverage_state'], 'COMPLETE')
                self.assertEqual(capture['last_successful_poll_at'], clock('09:15:30').isoformat())
                self.assertEqual(len(capture['events_by_symbol']['TEST']), 2)
                client.return_value.close.assert_called_once()


class SourceTests(unittest.TestCase):
    def setUp(self):
        session = patch('backend.runtime.full_stack_source.is_cash_session', side_effect=lambda day: day.weekday() < 5)
        session.start()
        self.addCleanup(session.stop)

    def test_missing_calendar_does_not_guess_weekday(self):
        with patch('backend.analytics.market_calendar_router.get_holiday_calendar_summary',
                   return_value={'india': {'year': None, 'holidays': 0}}):
            with self.assertRaisesRegex(ValueError, 'CASH_CALENDAR_UNAVAILABLE'):
                nse.is_cash_session(clock('09:00:00').date())

    def test_ready_complete_bars_and_daily_proof(self):
        bundle = ready_bundle()
        self.assertEqual(bundle['missing_inputs'], [])
        self.assertEqual(bundle['source_state'], 'READY')
        self.assertEqual([len(f['candles']) for f in bundle['frames']], [10, 2])
        self.assertEqual(bundle['source_times']['previous_close_session'], '2026-09-29')

    def test_missing_auction_skips_all_broker_calls(self):
        q, c = providers()
        bundle = build_source_bundle('TEST', clock('09:25:00').isoformat(), capture={}, quote_fetch=q, candle_fetch=c)
        self.assertEqual(bundle['source_state'], 'INPUT_NOT_READY')
        q.assert_not_called()
        c.assert_not_called()

    def test_stale_future_wrong_quote_and_naive_time(self):
        for key, value in [('quote_trade_time', clock('09:23:29').isoformat()),
                           ('quote_feed_time', clock('09:25:01').isoformat()),
                           ('quote_trade_time', '2026-09-29T09:25:00+05:30'),
                           ('quote_feed_time', '2026-09-30T09:24:55')]:
            bundle = ready_bundle()
            bundle['source_times'][key] = value
            self.assertTrue(validate_bundle(bundle))

    def test_candle_future_wrong_day_duplicate_and_bad_geometry(self):
        valid = [clock('09:15:00').isoformat(), 101, 104, 100, 103, 500]
        for row in [[clock('09:26:00').isoformat(), *valid[1:]],
                    ['2026-09-29T09:15:00+05:30', *valid[1:]],
                    [valid[0], 101, 99, 100, 103, 500],
                    [valid[0], 101, 104, 100, 103, -1],
                    [valid[0], 101, 104, 100, 103, float('inf')]]:
            with self.assertRaises(ValueError):
                completed_candles([row], 1, clock('09:25:00'))
        with self.assertRaises(ValueError):
            completed_candles([valid, valid], 1, clock('09:25:00'))

    def test_cutoff_exact_and_partial_bar_slicing(self):
        row = [clock('09:20:00').isoformat(), 101, 104, 100, 103, 500]
        self.assertEqual(len(completed_candles([row], 5, clock('09:25:00'))), 1)
        self.assertEqual(completed_candles([row], 5, clock('09:24:59')), [])

    def test_missing_middle_bar_is_not_filled(self):
        rows = [[clock('09:15:00').isoformat(), 101, 104, 100, 103, 500],
                [clock('09:17:00').isoformat(), 101, 104, 100, 103, 500]]
        with self.assertRaisesRegex(ValueError, 'INVALID_CANDLE_SEQUENCE'):
            completed_candles(rows, 1, clock('09:25:00'))

    def test_provider_value_error_is_sanitized(self):
        q, c = providers()
        q.side_effect = ValueError('PRIVATE_TOKEN')
        bundle = build_source_bundle('TEST', clock('09:25:00').isoformat(), capture=complete_capture(), quote_fetch=q, candle_fetch=c)
        self.assertNotIn('PRIVATE_TOKEN', json.dumps(bundle))
        self.assertEqual(bundle['source_state'], 'INPUT_NOT_READY')

    def test_daily_session_and_source_mismatch(self):
        with self.assertRaises(ValueError):
            daily_previous_close([['2026-09-28T09:15:00+05:30', 99, 102, 98, 100, 50]], DAY)
        q, c = providers()
        capture = complete_capture()
        capture['events_by_symbol']['TEST'][0]['previous_close'] = 99
        bundle = build_source_bundle('TEST', clock('09:25:00').isoformat(), capture=capture, quote_fetch=q, candle_fetch=c)
        self.assertIn('PREVIOUS_CLOSE_SOURCE_MISMATCH', bundle['missing_inputs'])

    def test_rolled_full_close_uses_completed_previous_session(self):
        q, c = providers()
        q.return_value['data']['TEST']['previous_close'] = 103
        bundle = build_source_bundle('TEST', clock('09:25:00').isoformat(), capture=complete_capture(), quote_fetch=q, candle_fetch=c)
        self.assertEqual(bundle['source_state'], 'READY')
        self.assertEqual(bundle['previous_close'], 100)

    def test_partial_candle_in_supplied_bundle_rejected(self):
        bundle = ready_bundle()
        partial = dict(bundle['frames'][0]['candles'][-1])
        partial['timestamp'] = clock('09:25:00').isoformat()
        bundle['frames'][0]['candles'].append(partial)
        self.assertEqual(validate_bundle(bundle), ['PARTIAL_CANDLE'])

    def test_wrong_symbol_source_and_failure(self):
        for edit in ('wrong_symbol', 'provider_error'):
            q, c = providers()
            if edit == 'wrong_symbol':
                q.return_value['data']['TEST']['symbol'] = 'OTHER'
            else:
                c.side_effect = RuntimeError('secret must not leak')
            bundle = build_source_bundle('TEST', clock('09:25:00').isoformat(), capture=complete_capture(), quote_fetch=q, candle_fetch=c)
            self.assertEqual(bundle['source_state'], 'INPUT_NOT_READY')
            self.assertNotIn('secret', json.dumps(bundle))


class AdapterTests(unittest.TestCase):
    def test_not_ready_never_calls_analysis(self):
        bundle = ready_bundle()
        bundle['source_state'] = 'INPUT_NOT_READY'
        bundle['missing_inputs'] = ['PREOPEN_COVERAGE_INCOMPLETE']
        with patch('backend.runtime.full_stack_adapter.analyze_full_stack') as analyze:
            self.assertEqual(adapt_full_stack(bundle)['adapter_state'], 'INPUT_NOT_READY')
            analyze.assert_not_called()

    def test_ready_exactly_once_preserves_all_engine_states(self):
        bundle = ready_bundle()
        original = copy.deepcopy(bundle)
        for state in ('MALFORMED', 'SOURCE_NOT_READY', 'NO_MATCHES', 'OK'):
            underlying = {'analysis_state': state}
            with patch('backend.runtime.full_stack_adapter.analyze_full_stack', return_value=underlying) as analyze:
                envelope = adapt_full_stack(bundle)
                analyze.assert_called_once()
                self.assertIs(envelope['full_stack_result'], underlying)
                payload = analyze.call_args.args[0]
                self.assertEqual(payload['history'], [])
                self.assertEqual(payload['outcome_horizon'], 'INTRADAY_EOD')
        self.assertEqual(bundle, original)

    def test_engine_exception_isolated(self):
        with patch('backend.runtime.full_stack_adapter.analyze_full_stack', side_effect=RuntimeError('private data')):
            result = adapt_full_stack(ready_bundle())
            self.assertEqual(result['adapter_state'], 'ERROR')
            self.assertIsNone(result['full_stack_result'])
            self.assertNotIn('private', json.dumps(result))

    def test_closed_contract_bogus_ready_and_invalid_types(self):
        for bundle in (None, [], {}, {**ready_bundle(), 'untrusted_extra': 1}):
            with patch('backend.runtime.full_stack_adapter.analyze_full_stack') as analyze:
                self.assertEqual(adapt_full_stack(bundle)['adapter_state'], 'INPUT_NOT_READY')
                analyze.assert_not_called()

    def test_real_engine_result_and_import_boundaries(self):
        self.assertEqual(adapt_full_stack(ready_bundle())['adapter_state'], 'OK')
        for path in ('backend/runtime/full_stack_adapter.py', 'backend/runtime/full_stack_contract.py'):
            tree = ast.parse((ROOT / path).read_text())
            imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
            self.assertFalse(any(x and any(word in x for word in ('requests', 'telegram', 'angel', 'collectors', 'openai')) for x in imports))


class AngelTests(unittest.TestCase):
    def test_initialization_wait_is_bounded_and_not_duplicated(self):
        from backend.utils import angel_one_client as angel
        running = Mock()
        running.is_alive.return_value = True
        with patch.object(angel, '_angel_session', None), patch.object(angel, 'is_configured', return_value=True), \
                patch.object(angel, '_source_initialization_thread', running), \
                patch.object(angel, '_source_initialization_done') as done, patch.object(angel.threading, 'Thread') as thread:
            done.wait.return_value = False
            self.assertFalse(angel._initialize_sources_bounded())
            self.assertFalse(angel._initialize_sources_bounded())
            thread.assert_not_called()
            done.wait.assert_called_with(angel.SOURCE_INITIALIZATION_WAIT_SECONDS)

    def test_batch_mapping_identity_and_nonfinite(self):
        from backend.utils import angel_one_client as angel
        row = {'exchange': 'NSE', 'tradingSymbol': 'TEST-EQ', 'symbolToken': '1', 'ltp': 103,
               'close': 100, 'exchTradeTime': '30-Sep-2026 09:24:50', 'exchFeedTime': '30-Sep-2026 09:24:55'}
        fake = Mock()
        fake.getMarketData.return_value = {'status': True, 'data': {'fetched': [row]}}
        with patch.object(angel, '_initialize', return_value=True), patch.object(angel, '_angel_session', fake), \
                patch.object(angel, '_instrument_map', {'TEST': '1'}):
            result = angel.fetch_full_quotes(['TEST'])
            self.assertEqual(result['source_state'], 'READY')
            fake.getMarketData.assert_called_once_with('FULL', {'NSE': ['1']})
            row['symbolToken'] = '2'
            self.assertEqual(angel.fetch_full_quotes(['TEST'])['reason'], 'QUOTE_IDENTITY_MISMATCH')
            row['symbolToken'] = '1'
            row['ltp'] = float('nan')
            self.assertEqual(angel.fetch_full_quotes(['TEST'])['source_state'], 'SOURCE_NOT_READY')
        self.assertEqual(angel.fetch_full_quotes(['TEST'] * 13)['reason'], 'INVALID_SYMBOL_BATCH')

    def test_candle_request_bounds_and_errors(self):
        from backend.utils import angel_one_client as angel
        fake = Mock()
        fake.getCandleData.return_value = {'status': True, 'data': []}
        with patch.object(angel, '_initialize', return_value=True), patch.object(angel, '_angel_session', fake), \
                patch.object(angel, '_instrument_map', {'TEST': '1'}):
            result = angel.fetch_source_candles('TEST', 'ONE_MINUTE', clock('09:15:00'), clock('09:25:00'))
            self.assertEqual(result['source_state'], 'READY')
            self.assertEqual(fake.getCandleData.call_args.args[0]['interval'], 'ONE_MINUTE')
            self.assertEqual(angel.fetch_source_candles('TEST', 'ONE_MINUTE', clock('09:15:00'), clock('09:15:00') + timedelta(days=11))['reason'], 'INVALID_CANDLE_WINDOW')
            fake.getCandleData.side_effect = RuntimeError('secret')
            self.assertEqual(angel.fetch_source_candles('TEST', 'ONE_MINUTE', clock('09:15:00'), clock('09:25:00'))['reason'], 'ANGEL_CANDLES_ERROR')


if __name__ == '__main__':
    unittest.main(verbosity=2)
