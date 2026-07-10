#!/usr/bin/env python3
"""Phase 4B.13 — tradecard decision memory foundation."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

IST = ZoneInfo('Asia/Kolkata')


def _fail(msg: str) -> int:
    print(f'TRADECARD_MEMORY_4B13_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _dt(y: int, m: int, d: int, hour: int, minute: int) -> datetime:
    return datetime(y, m, d, hour, minute, tzinfo=IST)


def _row(
    ticker: str,
    *,
    score: int = 70,
    volume_ratio: float = 1.2,
    state: str = 'TOP_GAINER_CONFIRM',
    bucket: str = 'large cap',
) -> dict:
    return {
        'ticker': ticker,
        'change_percent': 3.8,
        'volume_ratio': volume_ratio,
        'price': 500.0,
        'open_price': 480.0,
        'vwap': 490.0,
        'direction': 'BULLISH',
        'state': state,
        'score': score,
        'why': ['top large cap gainer', 'IT sector breadth'],
        'gainer_bucket': bucket,
        'gainer_promoted': True,
    }


class _MemoryEnv:
    """Isolated empty tradecard memory file for each test."""

    def __init__(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / 'tradecard_memory.jsonl'

    def __enter__(self) -> Path:
        os.environ['TRADECARD_MEMORY_FILE'] = str(self.path)
        self.path.write_text('', encoding='utf-8')
        return self.path

    def __exit__(self, *args: object) -> None:
        os.environ.pop('TRADECARD_MEMORY_FILE', None)
        self._tmpdir.cleanup()


def _fixed_memory_now() -> datetime:
    return _dt(2026, 5, 27, 10, 30)


def _live_board(*tickers: str) -> dict:
    from backend.trading.opening_rally_radar import build_opening_rally_board

    scanner = {
        'session_date': '2026-05-27',
        'scan_time_local': '2026-05-27 10:30:00',
        'top_signals': [
            _row(
                t,
                score=78 - (idx * 6),
                volume_ratio=2.4 - (idx * 0.35),
            )
            for idx, t in enumerate(tickers)
        ],
    }
    now = _dt(2026, 5, 27, 10, 30)
    with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
         patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
         patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]), \
         patch('backend.trading.opening_rally_radar._load_json', return_value={}):
        return build_opening_rally_board(
            now=now,
            catalyst_payload={},
            scanner_payload=scanner,
            premarket_payload={},
        )


def test_tradecards_stores_ranked_candidates() -> int:
    from backend.trading.tradecard_memory import load_tradecard_memory, record_tradecards_memory

    fixed_now = _fixed_memory_now()
    with _MemoryEnv(), patch('backend.trading.tradecard_memory._now_ist', return_value=fixed_now):
        board = _live_board('PERSISTENT', 'COFORGE')
        if board.get('reference_only'):
            return _fail('live board must not be reference_only for this test')
        ranked = list(board.get('ranked_candidates') or [])
        if len(ranked) < 2:
            return _fail(f'expected at least 2 ranked candidates got {len(ranked)}')
        expected_rank1 = str((ranked[0] or {}).get('ticker') or '').upper()
        record_tradecards_memory(board, command_source='/tradecards')
        rows = load_tradecard_memory(limit=20)
        if len(rows) < 2:
            return _fail(f'expected at least 2 tradecards records got {len(rows)}')
        top = rows[0]
        if not top.get('symbol'):
            return _fail('memory record missing symbol')
        if int(top.get('rank') or 0) != 1:
            return _fail(f'expected rank 1 on newest record got {top.get("rank")!r}')
        if str(top.get('symbol') or '').upper() != expected_rank1:
            return _fail(
                f'expected rank-1 symbol {expected_rank1!r} on newest record got {top.get("symbol")!r}'
            )
        if top.get('created_at') != fixed_now.replace(microsecond=0).isoformat():
            return _fail('batch tradecards memory must share one deterministic created_at')
        if not top.get('cap_bucket'):
            return _fail('memory record missing cap_bucket')
        if not top.get('reasons'):
            return _fail('memory record missing reasons')
        if top.get('outcome_status') != 'pending':
            return _fail(f'live tradecards must store pending got {top.get("outcome_status")!r}')
    return 0


def test_tradecard_stores_selected_best() -> int:
    from backend.trading.tradecard_memory import load_tradecard_memory, record_tradecard_memory

    fixed_now = _fixed_memory_now()
    with _MemoryEnv(), patch('backend.trading.tradecard_memory._now_ist', return_value=fixed_now):
        board = _live_board('PERSISTENT')
        sync = {
            'selected': 'PERSISTENT',
            'tradecards_best': 'PERSISTENT',
            'board': board,
            'board_row': _row('PERSISTENT', score=78, volume_ratio=2.4),
        }
        record_tradecard_memory(
            board=board,
            sync=sync,
            symbol='PERSISTENT',
            row=_row('PERSISTENT', score=78, volume_ratio=2.4),
            card={'ticker': 'PERSISTENT', 'status': 'VALID_ENTRY', 'reason': 'aligned with board'},
            evidence_matrix={
                'direct_confirms': ['volume 2.2x'],
                'indirect_confirms': ['IT sector breadth'],
                'risk_filters': ['extended/chase'],
                'missing_modules': [],
            },
        )
        rows = load_tradecard_memory(symbol='PERSISTENT', limit=5)
        if not rows:
            return _fail('expected tradecard memory record')
        newest = rows[0]
        if not newest.get('selected_best'):
            return _fail('selected /tradecard must set selected_best=true')
        if int(newest.get('rank') or 0) != 1:
            return _fail(f'newest selected-best record must be rank 1 got {newest.get("rank")!r}')
        if newest.get('created_at') != fixed_now.replace(microsecond=0).isoformat():
            return _fail('selected-best record must use deterministic created_at')
    return 0


def test_reference_stores_reference_only() -> int:
    from backend.trading.tradecard_memory import load_tradecard_memory, record_tradecards_memory

    with _MemoryEnv():
        board = _live_board('PERSISTENT', 'COFORGE')
        now = _dt(2026, 7, 4, 2, 5)
        scanner = {
            'session_date': '2026-07-04',
            'scan_time_local': '2026-07-04 02:05:00',
            'top_signals': [_row('PERSISTENT'), _row('COFORGE')],
        }
        from backend.trading.opening_rally_radar import build_opening_rally_board

        with patch('backend.trading.opening_rally_radar._live_registry', return_value={}), \
             patch('backend.trading.opening_rally_radar._previous_session_movers', return_value=set()), \
             patch('backend.trading.opening_rally_radar._theme_matches_for_ticker', return_value=[]), \
             patch('backend.trading.opening_rally_radar._load_json', return_value={}):
            board = build_opening_rally_board(
                now=now,
                catalyst_payload={},
                scanner_payload=scanner,
                premarket_payload={},
            )
        if not board.get('reference_only'):
            return _fail('weekend board must be reference_only')
        record_tradecards_memory(board, command_source='/tradecards')
        rows = load_tradecard_memory(limit=10)
        if not rows:
            return _fail('expected reference tradecards memory rows')
        if any(r.get('outcome_status') == 'pending' for r in rows):
            return _fail('reference board must not store pending active learning rows')
        if not all(r.get('outcome_status') == 'reference_only' for r in rows):
            return _fail('reference board must store outcome_status=reference_only')
    return 0


def test_stale_not_active_pending() -> int:
    from backend.trading.tradecard_memory import load_tradecard_memory, record_tradecards_memory, resolve_board_status

    with _MemoryEnv():
        board = {
            'session_stale': True,
            'data_status': 'stale',
            'reference_only': True,
            'ranked_candidates': [],
            'reference_candidates': [_row('PERSISTENT')],
        }
        if resolve_board_status(board) != 'stale_blocked':
            return _fail('expected stale_blocked board status')
        stored = record_tradecards_memory(board, command_source='/tradecards')
        if stored:
            return _fail('stale_blocked board should not store active tradecards memory')
        rows = load_tradecard_memory(limit=5)
        if rows:
            return _fail('stale_blocked should leave memory empty')
    return 0


def test_memory_stock_summary() -> int:
    from backend.telegram.response_format import format_tradecard_memory_stock_telegram
    from backend.trading.tradecard_memory import append_tradecard_memory, build_memory_record, summarize_symbol_memory

    with _MemoryEnv(), patch('backend.trading.tradecard_memory._now_ist', return_value=_fixed_memory_now()):
        board = {'session_date': '2026-05-27', 'data_status': 'current', 'market_lifecycle': 'MARKET_OPEN'}
        for rank, sym in enumerate(('PERSISTENT', 'PERSISTENT'), start=1):
            record = build_memory_record(
                command_source='/tradecards',
                board=board,
                symbol=sym,
                row=_row(sym, score=90 - rank),
                rank=rank,
                selected_best=(rank == 1),
            )
            record['created_at'] = _dt(2026, 5, 27, 10, 29 + rank).replace(microsecond=0).isoformat()
            append_tradecard_memory(record)
        summary = summarize_symbol_memory('PERSISTENT')
        if int(summary.get('count') or 0) != 2:
            return _fail(f'expected count 2 got {summary.get("count")!r}')
        text = format_tradecard_memory_stock_telegram('PERSISTENT')
        if 'MEMORY — PERSISTENT' not in text:
            return _fail('memory stock output missing title')
        if 'Seen in tradecards: 2 times' not in text:
            return _fail('memory stock output missing seen count')
    return 0


def test_memory_latest() -> int:
    from backend.telegram.response_format import format_tradecard_memory_latest_telegram
    from backend.trading.tradecard_memory import append_tradecard_memory, build_memory_record, latest_tradecard_memory

    with _MemoryEnv(), patch('backend.trading.tradecard_memory._now_ist', return_value=_fixed_memory_now()):
        board = {'session_date': '2026-05-27', 'data_status': 'current'}
        append_tradecard_memory(build_memory_record(
            command_source='/tradecard',
            board=board,
            symbol='COFORGE',
            row=_row('COFORGE'),
            rank=1,
            selected_best=True,
        ))
        rows = latest_tradecard_memory(limit=5)
        if len(rows) != 1:
            return _fail(f'expected 1 latest record got {len(rows)}')
        text = format_tradecard_memory_latest_telegram(limit=5)
        if 'COFORGE' not in text:
            return _fail('/memory latest must include recent symbol')
    return 0


def test_memory_stats() -> int:
    from backend.telegram.response_format import format_tradecard_memory_stats_telegram
    from backend.trading.tradecard_memory import append_tradecard_memory, build_memory_record, memory_stats

    with _MemoryEnv(), patch('backend.trading.tradecard_memory._now_ist', return_value=_fixed_memory_now()):
        board = {'session_date': '2026-05-27', 'data_status': 'current'}
        record_a = build_memory_record(
            command_source='/tradecards',
            board=board,
            symbol='PERSISTENT',
            row=_row('PERSISTENT'),
            rank=1,
            selected_best=True,
        )
        record_a['created_at'] = _dt(2026, 5, 27, 10, 30).replace(microsecond=0).isoformat()
        append_tradecard_memory(record_a)
        ref_board = {'session_date': '2026-07-04', 'reference_only': True, 'data_status': 'previous_session_reference'}
        record_b = build_memory_record(
            command_source='/tradecards',
            board=ref_board,
            symbol='COFORGE',
            row=_row('COFORGE'),
            rank=1,
            selected_best=True,
            no_current_entry=True,
        )
        record_b['created_at'] = _dt(2026, 5, 27, 10, 31).replace(microsecond=0).isoformat()
        append_tradecard_memory(record_b)
        stats = memory_stats()
        if int(stats.get('total') or 0) != 2:
            return _fail(f'expected total 2 got {stats.get("total")!r}')
        if int(stats.get('reference_only') or 0) != 1:
            return _fail(f'expected reference_only 1 got {stats.get("reference_only")!r}')
        text = format_tradecard_memory_stats_telegram()
        if 'Total records: 2' not in text:
            return _fail('memory stats must show total records')
    return 0


def test_temp_path_monkeypatch() -> int:
    from backend.trading.tradecard_memory import append_tradecard_memory, build_memory_record, memory_file_path

    with _MemoryEnv() as path, patch('backend.trading.tradecard_memory._now_ist', return_value=_fixed_memory_now()):
        append_tradecard_memory(build_memory_record(
            command_source='test',
            board={'session_date': '2026-05-27'},
            symbol='TESTME',
            row={'ticker': 'TESTME', 'score': 10, 'why': ['test']},
            rank=1,
        ))
        if memory_file_path() != path:
            return _fail('memory_file_path must honor TRADECARD_MEMORY_FILE')
        lines = path.read_text(encoding='utf-8').strip().splitlines()
        if len(lines) != 1:
            return _fail('expected one JSONL line in temp memory file')
        row = json.loads(lines[0])
        if row.get('symbol') != 'TESTME':
            return _fail('temp memory file must contain written record')
    return 0


def test_build_label_51o() -> int:
    from scripts.test_build_helpers import assert_canonical_build

    err = assert_canonical_build(_fail)
    if err:
        return err
    return 0


def main() -> int:
    tests = [
        test_tradecards_stores_ranked_candidates,
        test_tradecard_stores_selected_best,
        test_reference_stores_reference_only,
        test_stale_not_active_pending,
        test_memory_stock_summary,
        test_memory_latest,
        test_memory_stats,
        test_temp_path_monkeypatch,
        test_build_label_51o,
    ]
    failed = 0
    for test in tests:
        rc = test()
        if rc:
            failed += 1
        else:
            print(f'OK: {test.__name__}')
    if failed:
        print(f'FAILED: {failed}/{len(tests)}', file=sys.stderr)
        return 1
    print(f'ALL {len(tests)} TRADECARD_MEMORY_4B13 TESTS PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
