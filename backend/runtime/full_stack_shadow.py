"""54C observational enrichment: no ranking inputs, writes or synchronous I/O.

One process-local worker, no task queue, a twelve-symbol batch, a 60-second
batch admission budget and cooldown bound broker load. An in-flight provider
call cannot be cancelled; a stuck worker prevents any replacement worker.
Results retain their own observation cutoff and expire after sixty seconds.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import logging
import os
import threading
import time
from zoneinfo import ZoneInfo

from backend.runtime.full_stack_adapter import adapt_full_stack
from backend.runtime.full_stack_source import build_source_bundle

IST = ZoneInfo('Asia/Kolkata')
MAX_CANDIDATES = 12
TTL_SECONDS = 60
BATCH_SECONDS = 60
SOURCE_SPACING_SECONDS = 1.05
LOG = logging.getLogger(__name__)


def pending(symbol, cutoff, reason):
    return {'schema_version': '54C', 'mode': 'SHADOW_ONLY', 'symbol': symbol,
            'observation_cutoff': cutoff, 'adapter_state': 'INPUT_NOT_READY',
            'missing_inputs': [reason], 'full_stack_result': None}


class ShadowRunner:
    def __init__(self, source=build_source_bundle, adapter=adapt_full_stack,
                 clock=lambda: datetime.now(IST), monotonic=time.monotonic,
                 sleeper=time.sleep):
        self.source, self.adapter = source, adapter
        self.clock, self.monotonic = clock, monotonic
        self.sleeper = sleeper
        self.lock = threading.Lock()
        self.worker = None
        self.cache = {}
        self.next_run = 0.0

    def _run(self, symbols):
        deadline = self.monotonic() + BATCH_SECONDS
        results = {}
        next_source_start = self.monotonic()
        try:
            for symbol in symbols:
                # Each source build can issue one FULL quote. Leave a gap after
                # completion, including failures, to avoid quote bursts.
                delay = next_source_start - self.monotonic()
                if delay > 0:
                    if next_source_start >= deadline:
                        break
                    self.sleeper(delay)
                if self.monotonic() >= deadline:
                    break
                observed = self.clock()
                cutoff = observed.isoformat()
                try:
                    result = self.adapter(self.source(symbol, cutoff))
                    # Cache only the adapter envelope, never provider credentials/errors.
                    result = deepcopy(result)
                    result.update(schema_version='54C', mode='SHADOW_ONLY')
                except Exception:
                    result = pending(symbol, cutoff, 'SHADOW_SOURCE_ERROR')
                next_source_start = self.monotonic() + SOURCE_SPACING_SECONDS
                results[symbol] = (observed, result)
                LOG.info('FULL_STACK_SHADOW symbol=%s state=%s', symbol,
                         result.get('adapter_state', 'INPUT_NOT_READY'))
        finally:
            with self.lock:
                self.cache = results  # bounded, replace previous batch, no growing history
                self.next_run = self.monotonic() + TTL_SECONDS

    def enrich(self, board, now):
        result = dict(board)
        rows = list(board.get('ranked_candidates') or [])
        result['ranked_candidates'] = rows
        cutoff = now.isoformat()
        reason = None
        if now.tzinfo is None or now.utcoffset() is None:
            reason = 'INVALID_OBSERVATION_TIME'
        elif os.environ.get('LOCAL_ONLY') == '1' or os.environ.get('DISABLE_SCHEDULER') == '1':
            reason = 'LOCAL_SHADOW_DISABLED'
        elif board.get('reference_only') or board.get('session_stale'):
            reason = 'REFERENCE_OR_STALE_BOARD'
        else:
            local = now.astimezone(IST)
            if local.weekday() >= 5 or not (9 * 60 + 15 <= local.hour * 60 + local.minute < 15 * 60 + 30):
                reason = 'OUTSIDE_REGULAR_SESSION'
        symbols = tuple(dict.fromkeys(str(row.get('ticker') or '').strip().upper()
                                     for row in rows[:MAX_CANDIDATES] if isinstance(row, dict)))
        symbols = tuple(s for s in symbols if s and len(s) <= 32 and
                        all(c.isalnum() or c in '&-.' for c in s))
        with self.lock:
            cached = dict(self.cache)
            if not reason and symbols and (self.worker is None or not self.worker.is_alive()) and self.monotonic() >= self.next_run:
                self.worker = threading.Thread(target=self._run, args=(symbols,),
                                               name='full-stack-shadow', daemon=True)
                self.worker.start()
        for index, row in enumerate(rows[:MAX_CANDIDATES]):
            if not isinstance(row, dict):
                continue
            symbol = str(row.get('ticker') or '').strip().upper()
            fact = pending(symbol, cutoff, reason or 'SHADOW_PENDING')
            if not reason and symbol in cached:
                observed, entry = cached[symbol]
                age = (now - observed).total_seconds()
                if observed.astimezone(IST).date() == now.astimezone(IST).date() and 0 <= age <= TTL_SECONDS:
                    fact = deepcopy(entry)
                else:
                    fact = pending(symbol, cutoff, 'SHADOW_EXPIRED')
            rows[index] = {**row, 'full_stack_shadow': fact}
        result['full_stack_shadow'] = {'schema_version': '54C', 'mode': 'SHADOW_ONLY',
                                      'candidate_limit': MAX_CANDIDATES,
                                      'state': reason or 'ACTIVE'}
        return result


RUNNER = ShadowRunner()


def append_full_stack_shadow(board, *, now):
    """Called only after the board's existing decisions are final."""
    return RUNNER.enrich(board, now)
