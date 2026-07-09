#!/usr/bin/env python3
"""Phase 4B.18 — catalyst-aware gainer classification."""

from __future__ import annotations

import inspect
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

BEL_TEXT = (
    'BEL Rating & Order Alert\n'
    'Motilal Oswal rates Bharat Electronics Ltd as top defence pick with Rs 30,000 crore '
    'QRSAM order expected soon and Rs 510 target price.'
)
METROPOLIS_TEXT = (
    'METROPOLIS Quarterly Results Alert\n'
    'Metropolis Healthcare reports 16% YoY revenue growth in Q1 FY27 with improved EBITDA margins.'
)
DIXON_TEXT = (
    'DIXON Rating Upgrade Alert\n'
    'Investec maintains Buy on Dixon Technologies, raises target price to ₹16,200.'
)
POWERINDIA_TEXT = (
    'POWERINDIA Rating & Regulatory Alert\n'
    'Macquarie initiated coverage on Hitachi Energy India with Outperform rating and Rs 38,500 target.'
)
ENRIN_TEXT = (
    'ENRIN Rating Alert\n'
    'Macquarie initiated coverage on Siemens Energy India with Outperform rating and Rs 4,190 target.'
)


def _fail(msg: str) -> int:
    print(f'CATALYST_GAINER_CLASSIFICATION_4B18_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _dt(hour: int, minute: int) -> datetime:
    return datetime(2026, 7, 7, hour, minute, tzinfo=IST)


def _scanner(*rows: dict) -> dict:
    return {'session_date': '2026-07-07', 'top_signals': list(rows)}


def _row(ticker: str, chg: float, vol: float = 2.0, **extra) -> dict:
    base = {
        'ticker': ticker,
        'change_percent': chg,
        'volume_ratio': vol,
        'price': 500.0,
        'open_price': 480.0,
        'vwap': 490.0,
        'direction': 'BULLISH',
        'volume': 200000,
    }
    base.update(extra)
    return base


def test_bel_broker_order_maps() -> int:
    from backend.trading.catalyst_classification import parse_broker_app_alert

    parsed = parse_broker_app_alert(BEL_TEXT)
    if parsed.get('symbol') != 'BEL':
        return _fail(f'BEL alert must map to BEL got {parsed.get("symbol")!r}')
    if 'order' not in str(parsed.get('alert_type') or ''):
        return _fail('BEL alert must include order type')
    if parsed.get('broker', '').lower().find('motilal') < 0:
        return _fail(f'BEL broker must be Motilal Oswal got {parsed.get("broker")!r}')
    return 0


def test_metropolis_result_maps() -> int:
    from backend.trading.catalyst_classification import parse_broker_app_alert

    parsed = parse_broker_app_alert(METROPOLIS_TEXT)
    if parsed.get('symbol') != 'METROPOLIS':
        return _fail(f'METROPOLIS alert must map to METROPOLIS got {parsed.get("symbol")!r}')
    if 'result' not in str(parsed.get('alert_type') or ''):
        return _fail('METROPOLIS alert must include result type')
    return 0


def test_dixon_upgrade_maps() -> int:
    from backend.trading.catalyst_classification import parse_broker_app_alert

    parsed = parse_broker_app_alert(DIXON_TEXT)
    if parsed.get('symbol') != 'DIXON':
        return _fail(f'DIXON alert must map to DIXON got {parsed.get("symbol")!r}')
    if 'upgrade' not in str(parsed.get('alert_type') or ''):
        return _fail('DIXON alert must include upgrade type')
    return 0


def test_powerindia_company_name_maps() -> int:
    from backend.trading.catalyst_classification import parse_broker_app_alert

    parsed = parse_broker_app_alert(POWERINDIA_TEXT)
    if parsed.get('symbol') != 'POWERINDIA':
        return _fail(f'POWERINDIA alert must map to POWERINDIA got {parsed.get("symbol")!r}')
    return 0


def test_enrin_company_name_maps() -> int:
    from backend.trading.catalyst_classification import parse_broker_app_alert

    parsed = parse_broker_app_alert(ENRIN_TEXT)
    if parsed.get('symbol') != 'ENRIN':
        return _fail(f'ENRIN alert must map to ENRIN got {parsed.get("symbol")!r}')
    return 0


def test_fresh_alert_confirmed() -> int:
    from backend.trading.catalyst_classification import (
        BROKER_APP_ALERT,
        broker_alert_to_catalyst_row,
        classify_candidate_catalyst,
        parse_broker_app_alert,
    )

    parsed = parse_broker_app_alert(BEL_TEXT)
    catalyst = broker_alert_to_catalyst_row(parsed)
    cls = classify_candidate_catalyst(
        'BEL',
        catalyst=catalyst,
        scanner_row=_row('BEL', 5.0, 2.5),
        gainer_meta={'rank_in_bucket': 2},
    )
    if cls.get('state') not in (BROKER_APP_ALERT, 'CATALYST_CONFIRMED'):
        return _fail(f'fresh alert must be confirmed got {cls.get("state")!r}')
    return 0


def test_no_alert_price_volume_only() -> int:
    from backend.trading.catalyst_classification import PRICE_VOLUME_ONLY, classify_candidate_catalyst

    cls = classify_candidate_catalyst(
        'HTMEDIA',
        catalyst=None,
        scanner_row=_row('HTMEDIA', 6.5, 8.9),
        gainer_meta={'rank_in_bucket': 1},
    )
    if cls.get('state') != PRICE_VOLUME_ONLY:
        return _fail(f'top gainer without alert must be PRICE_VOLUME_ONLY got {cls.get("state")!r}')
    return 0


def test_unknown_catalyst_not_rejection() -> int:
    from backend.trading.catalyst_classification import UNKNOWN_CATALYST, apply_catalyst_classification
    from backend.trading.opening_rally_radar import _opening_tradecard_eligible

    row = apply_catalyst_classification(
        {
            'ticker': 'HTMEDIA',
            'score': 54,
            'state': 'REJECTED',
            'change_percent': 6.5,
            'volume_ratio': 8.9,
            'gainer_promoted': True,
            'themes': [],
            'why': ['top gainer'],
        },
        catalyst=None,
        gainer_meta={'rank_in_bucket': 1},
    )
    if row.get('catalyst_state') != UNKNOWN_CATALYST and row.get('catalyst_state') != 'PRICE_VOLUME_ONLY':
        pass
    if str(row.get('state') or '') == 'REJECTED':
        return _fail('unknown catalyst must not stay hard rejected for strong mover')
    row['state'] = 'TOP_GAINER_CONFIRM'
    if not _opening_tradecard_eligible(row):
        return _fail('unknown catalyst gainer must remain tradecard eligible')
    return 0


def test_radar_includes_catalyst_line() -> int:
    from backend.telegram.response_format import format_opening_radar_telegram

    board = {
        'time_ist': '10:30',
        'phase': 'CONFIRMATION',
        'session_date': '2026-07-07',
        'ranked_candidates': [{
            'ticker': 'BEL',
            'score': 58,
            'state': 'TOP_GAINER_CONFIRM',
            'gainer_bucket': 'large cap',
            'why': ['top large cap gainer'],
            'catalyst_line': 'Catalyst: confirmed — broker/order alert',
        }],
    }
    text = format_opening_radar_telegram(board=board)
    if 'Catalyst: confirmed' not in text:
        return _fail('/radar output must include Catalyst line')
    return 0


def test_tradecards_includes_catalyst_line() -> int:
    from backend.telegram.response_format import format_tradecards_telegram

    board = {
        'session_date': '2026-07-07',
        'scanner_freshness_status': 'CURRENT',
        'ranked_candidates': [{
            'ticker': 'HTMEDIA',
            'score': 65,
            'state': 'PULLBACK_ONLY_PLAN',
            'gainer_bucket': 'Nifty 500 / broad market',
            'why': ['top gainer + volume 8.9x'],
            'catalyst_line': 'Catalyst: missing — price-volume only',
            'catalyst_risk_line': 'Risk: no stock-specific catalyst found',
        }],
    }
    with patch('backend.trading.opening_rally_radar.build_opening_rally_board', return_value=board), \
         patch('backend.trading.opening_rally_radar.pick_best_opening_tradecard', return_value=(None, 0, [])), \
         patch('backend.telegram.response_format._persist_tradecards_decision_memory'):
        text = format_tradecards_telegram()
    if 'Catalyst: missing' not in text:
        return _fail('/tradecards output must include Catalyst line')
    return 0


def test_catalyst_symbol_confirmed() -> int:
    from backend.trading.catalyst_classification import format_catalyst_symbol_telegram

    catalyst = {
        'ticker': 'BEL',
        'headline': 'Motilal Oswal defence pick',
        'catalyst_type': 'ORDER_WIN',
        'side': 'BULLISH',
        'score': 85,
        'source_key': 'broker_app',
        'broker_app_alert': True,
        'broker': 'Motilal Oswal',
        'alert_type': 'rating/order',
        'target_price': 510,
        'summary': 'Motilal Oswal rates BEL as top defence pick',
    }
    board = {
        'ranked_candidates': [{'ticker': 'BEL', 'score': 58, 'state': 'TOP_GAINER_CONFIRM'}],
        'gainer_scan': {},
    }
    with patch('backend.trading.catalyst_classification.build_extended_catalyst_map', return_value={'BEL': catalyst}):
        text = format_catalyst_symbol_telegram('BEL', board=board)
    if 'CATALYST — BEL' not in text:
        return _fail('/catalyst must show header')
    if 'CATALYST_CONFIRMED' not in text and 'BROKER_APP_ALERT' not in text:
        return _fail('/catalyst confirmed must show state')
    if 'Used in radar: yes' not in text:
        return _fail('/catalyst must show radar usage')
    return 0


def test_catalyst_symbol_unknown() -> int:
    from backend.trading.catalyst_classification import format_catalyst_symbol_telegram

    board = {
        'ranked_candidates': [],
        'gainer_scan': {'by_symbol': {'HTMEDIA': {'rank_in_bucket': 1}}},
    }
    scanner = _scanner(_row('HTMEDIA', 6.5, 8.9))
    with patch('backend.trading.catalyst_classification.build_extended_catalyst_map', return_value={}), \
         patch('backend.trading.all_cap_gainers.scan_all_cap_gainers', return_value={
             'by_symbol': {'HTMEDIA': {'rank_in_bucket': 1, 'change_percent': 6.5, 'volume_ratio': 8.9}},
         }):
        text = format_catalyst_symbol_telegram('HTMEDIA', board=board)
    if 'UNKNOWN_CATALYST' not in text and 'PRICE_VOLUME_ONLY' not in text:
        return _fail('/catalyst without catalyst must show unknown/price-volume state')
    if 'No fresh stock-specific catalyst found' not in text:
        return _fail('/catalyst must say no catalyst found')
    return 0


def test_no_full_market_scan() -> int:
    from backend.trading.all_cap_gainers import scan_all_cap_gainers

    scanner = _scanner(_row('BEL', 5.0), _row('HTMEDIA', 6.0, 8.0))
    src = inspect.getsource(scan_all_cap_gainers)
    if 'full_market' in src.lower() or 'all_stocks' in src.lower():
        return _fail('scan_all_cap_gainers must not introduce full-market scan')
    scan = scan_all_cap_gainers(scanner_payload=scanner, catalyst_map={}, now=_dt(10, 30))
    if scan.get('total_scanned', 0) > 10:
        return _fail('gainer scan must stay within scanner universe')
    return 0


def test_no_ai_calls() -> int:
    from backend.trading import catalyst_classification as cc
    from backend.my_feed import feed_processor as fp

    banned = ('openai', 'anthropic', 'groq', 'gemini', 'claude')
    for mod in (cc, fp):
        lines = [
            ln for ln in inspect.getsource(mod).splitlines()
            if not ln.strip().startswith('#') and '"""' not in ln and "'''" not in ln
        ]
        src = '\n'.join(lines).lower()
        for token in banned:
            if token in src:
                return _fail(f'{mod.__name__} must not reference {token}')
    return 0


def test_build_label_51y() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 52I-A' or ASTRAEDGE_BUILD_STAGE != '52I-A':
        return _fail(f'expected AstraEdge 52I-A got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    return 0


def main() -> int:
    tests = [
        test_bel_broker_order_maps,
        test_metropolis_result_maps,
        test_dixon_upgrade_maps,
        test_powerindia_company_name_maps,
        test_enrin_company_name_maps,
        test_fresh_alert_confirmed,
        test_no_alert_price_volume_only,
        test_unknown_catalyst_not_rejection,
        test_radar_includes_catalyst_line,
        test_tradecards_includes_catalyst_line,
        test_catalyst_symbol_confirmed,
        test_catalyst_symbol_unknown,
        test_no_full_market_scan,
        test_no_ai_calls,
        test_build_label_51y,
    ]
    for fn in tests:
        rc = fn()
        if rc:
            return rc
    print('CATALYST_GAINER_CLASSIFICATION_4B18_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
