"""Offline shadow isolation, load bounds and real-board behavior regression."""
import copy
import os
import sys
import threading
import tempfile
import time
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.runtime.full_stack_shadow import ShadowRunner
from backend.runtime.full_stack_adapter import adapt_full_stack
from scripts.test_full_stack_runtime_54b import clock, ready_bundle


def board(n=2):
    return {'ranked_candidates': [{'ticker': f'TEST{i}', 'score': 90-i,
                                  'decision': {'state': 'WATCH'}} for i in range(n)],
            'best_pick': 'TEST0', 'confidence': 70}


def strip_shadow(value):
    value = copy.deepcopy(value)
    value.pop('full_stack_shadow', None)
    for row in value['ranked_candidates']:
        row.pop('full_stack_shadow', None)
    return value


class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {
            'LOCAL_ONLY': '0', 'DISABLE_SCHEDULER': '0',
            'INTRADAY_CANDLES_FILE': self.temp.name + '/candles.jsonl',
            'CANDIDATE_HEARTBEAT_FILE': self.temp.name + '/heartbeat.json'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.now = clock('09:25:00')

    def runner(self, source=None, **kwargs):
        return ShadowRunner(source=source or Mock(return_value=ready_bundle()),
                            clock=lambda: self.now, **kwargs)

    def test_final_order_values_and_input_unchanged(self):
        original = board(15)
        before = copy.deepcopy(original)
        runner = self.runner()
        out = runner.enrich(original, self.now)
        runner.worker.join(2)
        self.assertEqual(original, before)
        self.assertEqual(strip_shadow(out), before)
        self.assertEqual(runner.source.call_count, 12)
        self.assertEqual(sum('full_stack_shadow' in r for r in out['ranked_candidates']), 12)

    def test_valid_53g_result_attached_without_reinterpretation(self):
        bundle = ready_bundle()
        runner = self.runner(Mock(return_value=bundle))
        data = {'ranked_candidates': [{'ticker': 'TEST', 'score': 72}]}
        runner.enrich(data, self.now)
        runner.worker.join(2)
        result = runner.enrich(data, self.now)['ranked_candidates'][0]['full_stack_shadow']
        self.assertEqual(result['adapter_state'], 'OK')
        self.assertEqual(result['full_stack_result'], adapt_full_stack(bundle)['full_stack_result'])
        result['full_stack_result'].clear()
        self.assertTrue(runner.cache['TEST'][1]['full_stack_result'])

    def test_stuck_source_never_blocks_or_spawns_more_workers(self):
        release = threading.Event()
        entered = threading.Event()
        def blocked(*args):
            entered.set()
            release.wait(3)
            return {}
        runner = self.runner(Mock(side_effect=blocked))
        self.addCleanup(release.set)
        started = time.monotonic()
        runner.enrich(board(), self.now)
        self.assertLess(time.monotonic()-started, 0.5)
        self.assertTrue(entered.wait(1))
        first = runner.worker
        for _ in range(30):
            runner.enrich(board(), self.now)
        self.assertIs(runner.worker, first)
        self.assertEqual(runner.source.call_count, 1)
        release.set()
        first.join(2)

    def test_provider_error_is_sanitized_and_other_candidates_continue(self):
        runner = self.runner(Mock(side_effect=[RuntimeError('SECRET'), ready_bundle()]))
        runner.enrich(board(), self.now)
        runner.worker.join(2)
        out = runner.enrich(board(), self.now)
        self.assertNotIn('SECRET', str(out))
        self.assertEqual(out['ranked_candidates'][0]['full_stack_shadow']['missing_inputs'], ['SHADOW_SOURCE_ERROR'])
        self.assertEqual(out['ranked_candidates'][1]['full_stack_shadow']['adapter_state'], 'OK')

    def test_cooldown_and_total_batch_budget(self):
        ticks = [0.0]
        def source(*args):
            ticks[0] += 61
            return {}
        runner = self.runner(Mock(side_effect=source), monotonic=lambda: ticks[0])
        runner.enrich(board(12), self.now)
        runner.worker.join(2)
        runner.enrich(board(12), self.now)
        self.assertEqual(runner.source.call_count, 1)
        ticks[0] += 61
        runner.enrich(board(12), self.now)
        runner.worker.join(2)
        self.assertEqual(runner.source.call_count, 2)

    def test_missing_source_truth_stays_not_ready(self):
        runner = self.runner(Mock(return_value={'missing_inputs': ['CAPTURE_MISSING']}))
        runner.enrich(board(), self.now)
        runner.worker.join(2)
        out = runner.enrich(board(), self.now)
        self.assertEqual(out['ranked_candidates'][0]['full_stack_shadow']['adapter_state'], 'INPUT_NOT_READY')

    def test_expired_future_previous_day_cache_never_reused(self):
        for offset in (61, -1, 86400):
            runner = self.runner()
            runner.cache['TEST0'] = (self.now-timedelta(seconds=offset), {'adapter_state': 'OK'})
            runner.next_run = float('inf')
            out = runner.enrich(board(), self.now)
            self.assertEqual(out['ranked_candidates'][0]['full_stack_shadow']['missing_inputs'], ['SHADOW_EXPIRED'])

    def test_reference_stale_weekend_afterhours_and_local_skip_network(self):
        for data, now, env in [(dict(board(), reference_only=True), self.now, {}),
                               (dict(board(), session_stale=True), self.now, {}),
                               (board(), self.now+timedelta(days=3), {}),
                               (board(), clock('16:00:00'), {}),
                               (board(), self.now, {'LOCAL_ONLY': '1'}),
                               (board(), self.now.replace(tzinfo=None), {})]:
            runner = self.runner()
            with patch.dict(os.environ, env):
                out = runner.enrich(data, now)
            self.assertIsNone(runner.worker)
            runner.source.assert_not_called()
            self.assertEqual(strip_shadow(out), data)

    def test_duplicate_symbols_fetched_once(self):
        runner = self.runner()
        runner.enrich({'ranked_candidates': [{'ticker': 'TEST'}]*12}, self.now)
        runner.worker.join(2)
        self.assertEqual(runner.source.call_count, 1)

    def test_real_board_and_selection_unchanged_and_failure_isolated(self):
        from backend.trading.opening_rally_radar import build_opening_rally_board, pick_best_opening_tradecard
        from scripts.test_opening_rally_radar import _scanner, _row, _railtel_catalyst
        args = dict(now=self.now, registry={}, premarket_payload={},
                    catalyst_payload=_railtel_catalyst(),
                    scanner_payload=_scanner(_row('RAILTEL', 3.8), now=self.now))
        target = 'backend.runtime.full_stack_shadow.append_full_stack_shadow'
        # Local guard avoids network while exercising the real board integration.
        with patch.dict(os.environ, {'LOCAL_ONLY': '1', 'DISABLE_SCHEDULER': '1'}):
            with patch(target, side_effect=lambda b, **kw: b):
                baseline = build_opening_rally_board(**args)
            enriched = build_opening_rally_board(**args)
            self.assertEqual(strip_shadow(enriched), baseline)
            self.assertEqual(pick_best_opening_tradecard(copy.deepcopy(enriched)),
                             pick_best_opening_tradecard(copy.deepcopy(baseline)))
            with patch(target, side_effect=RuntimeError('shadow broke')):
                self.assertEqual(build_opening_rally_board(**args), baseline)


if __name__ == '__main__':
    unittest.main()
