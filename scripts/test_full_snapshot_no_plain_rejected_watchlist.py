#!/usr/bin/env python3
"""Unit tests — /full surfaces never show plain rejected watchlist (Stage 48U)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'FULL_SNAPSHOT_NO_PLAIN_REJECTED_WATCHLIST_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _run(script: str, token: str) -> int | None:
    proc = subprocess.run([sys.executable, f'scripts/{script}'], cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    combined = (proc.stdout or '') + (proc.stderr or '')
    if proc.returncode != 0 or token not in combined:
        return _fail(f'{script} failed: {combined.strip()[-200:]}')
    return None


def main() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD
    from backend.telegram.lazy_command_runner import FULL_SNAPSHOT_SEQUENCE
    from backend.telegram.response_format import format_aihub_full, strip_stage_markers

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 49A':
        return _fail(f'expected AstraEdge 49A got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    if len(FULL_SNAPSHOT_SEQUENCE) != 33:
        return _fail(f'/full must stay 33 steps, got {len(FULL_SNAPSHOT_SEQUENCE)}')

    scan_payload = {
        'summary': {'live_scanner_count': 30},
        'live_scanner': [{'ticker': 'EASEMYTRIP'}],
        'watchlist_candidates': [
            {'ticker': 'RELIANCE'},
            {'ticker': 'AMBER'},
            {'ticker': 'AVANTIFEED'},
        ],
    }
    journal_payload = {
        'summary': {'history': {'count': 0}},
        'items': [{'ticker': 'RELIANCE'}, {'ticker': 'AVANTIFEED'}],
    }

    with patch(
        'backend.analytics.unified_decision_engine.build_live_rejection_set',
        return_value={'AVANTIFEED': 'STRONG BEARISH breakdown'},
    ):
        text = strip_stage_markers(format_aihub_full({
            'scan': scan_payload,
            'journal': journal_payload,
            'calib': {'summary': {}},
        }))

    if 'top watchlist: RELIANCE, AMBER, AVANTIFEED' in text:
        return _fail('/full must not show rejected ticker in plain top watchlist')
    if 'rejected today: avantifeed' not in text.lower():
        return _fail('/full must label rejected today ticker')

    for script, token in (
        ('test_full_snapshot_polish_48t.py', 'FULL_SNAPSHOT_POLISH_48T_TEST_OK'),
        ('test_aihub_full_rejected_ticker_removed.py', 'AIHUB_FULL_REJECTED_TICKER_REMOVED_TEST_OK'),
        ('test_aihub_journal_rejected_ticker_removed.py', 'AIHUB_JOURNAL_REJECTED_TICKER_REMOVED_TEST_OK'),
    ):
        err = _run(script, token)
        if err:
            return err

    print('FULL_SNAPSHOT_NO_PLAIN_REJECTED_WATCHLIST_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
