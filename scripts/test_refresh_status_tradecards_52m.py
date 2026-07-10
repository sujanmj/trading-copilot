#!/usr/bin/env python3
"""AstraEdge 52M — /refresh status tradecards wording cleanup."""

from __future__ import annotations

import json
import os
import sys
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
SESSION = '2026-07-10'


def _fail(msg: str) -> int:
    print(f'REFRESH_STATUS_TRADECARDS_52M_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _dt(h: int, m: int) -> datetime:
    return datetime(2026, 7, 10, h, m, tzinfo=IST)


def _scanner_payload() -> dict:
    ts = _dt(10, 15).isoformat()
    return {
        'last_updated': ts,
        'scan_time_local': f'{SESSION} 10:15:00',
        'session_date': SESSION,
        'signals': [{'ticker': 'STYLAMIND', 'change_percent': 1.2, 'volume_ratio': 1.1}],
    }


def test_qa_expects_52m() -> int:
    from scripts.test_build_helpers import assert_canonical_build

    err = assert_canonical_build(_fail)
    if err:
        return err
    return 0


def test_current_scanner_not_waiting() -> int:
    from backend.trading.market_freshness_guard import (
        TRADECARDS_READY_NO_QUALITY,
        TRADECARDS_WAITING_SCANNER,
        evaluate_all_source_freshness,
        format_freshness_status_telegram,
    )

    scanner_path = PROJECT_ROOT / 'data' / 'scanner_data.json'
    with patch('backend.trading.market_freshness_guard.SCANNER_FILE', scanner_path), patch(
        'backend.trading.opening_session_freshness.resolve_market_lifecycle',
        return_value='MARKET_ACTIVE',
    ), patch('backend.trading.market_freshness_guard._load_json', return_value=_scanner_payload()):
        table = evaluate_all_source_freshness(now=_dt(10, 15))
        text = format_freshness_status_telegram(now=_dt(10, 15))
    tradecards_status = str((table.get('tradecards') or {}).get('freshness_status') or '')
    if tradecards_status == TRADECARDS_WAITING_SCANNER:
        return _fail('CURRENT scanner must not show WAITING LIVE SCANNER for tradecards')
    if TRADECARDS_READY_NO_QUALITY not in tradecards_status and 'CURRENT' not in tradecards_status:
        return _fail(f'unexpected tradecards status {tradecards_status!r}')
    if 'tradecards: WAITING LIVE SCANNER' in text:
        return _fail('/refresh status must not show tradecards WAITING when scanner is CURRENT')
    return 0


def test_stale_scanner_still_waiting() -> int:
    from backend.trading.market_freshness_guard import (
        TRADECARDS_WAITING_SCANNER,
        evaluate_all_source_freshness,
        format_freshness_status_telegram,
    )

    stale_payload = {
        'session_date': '2026-07-08',
        'last_updated': '2026-07-08T15:30:00+05:30',
        'signals': [],
    }
    with patch('backend.trading.market_freshness_guard._load_json', return_value=stale_payload), patch(
        'backend.trading.opening_session_freshness.resolve_market_lifecycle',
        return_value='MARKET_ACTIVE',
    ):
        table = evaluate_all_source_freshness(now=_dt(10, 15))
        text = format_freshness_status_telegram(now=_dt(10, 15))
    if (table.get('tradecards') or {}).get('freshness_status') != TRADECARDS_WAITING_SCANNER:
        return _fail('stale scanner must show WAITING LIVE SCANNER for tradecards')
    if 'tradecards: WAITING LIVE SCANNER' not in text:
        return _fail('/refresh status must show tradecards WAITING when scanner stale')
    return 0


def test_after_hours_reference_label() -> int:
    from backend.trading.market_freshness_guard import (
        TRADECARDS_AFTER_HOURS,
        evaluate_all_source_freshness,
    )

    with patch(
        'backend.trading.opening_session_freshness.resolve_market_lifecycle',
        return_value='AFTER_HOURS',
    ), patch('backend.trading.market_freshness_guard._load_json', return_value=_scanner_payload()):
        table = evaluate_all_source_freshness(now=_dt(18, 0))
    if (table.get('tradecards') or {}).get('freshness_status') != TRADECARDS_AFTER_HOURS:
        return _fail('after-hours must show next-session reference label')
    return 0


def main() -> int:
    checks = (
        test_qa_expects_52m,
        test_current_scanner_not_waiting,
        test_stale_scanner_still_waiting,
        test_after_hours_reference_label,
    )
    for check in checks:
        err = check()
        if err:
            return err
    print('REFRESH_STATUS_TRADECARDS_52M_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
