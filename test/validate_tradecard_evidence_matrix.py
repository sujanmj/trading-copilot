#!/usr/bin/env python3
"""Validate tradecard evidence matrix scoring and Telegram explain output."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

IST = ZoneInfo('Asia/Kolkata')


def _now() -> str:
    return datetime.now(IST).replace(microsecond=0).isoformat()


def _base_context(ticker: str = 'TATAMOTORS') -> dict:
    return {
        'market_mode': 'LIVE',
        'scanner': {
            'generated_at': _now(),
            'top_signals': [{
                'ticker': ticker,
                'direction': 'BULLISH',
                'change_percent': 2.4,
                'volume_ratio': 2.2,
                'strength': 'STRONG',
            }],
        },
        'news': {
            'generated_at': _now(),
            'items': [{
                'ticker': ticker,
                'side': 'BULLISH',
                'headline': f'{ticker} wins order for EV manufacturing project',
            }],
        },
        'budget': {
            'generated_at': _now(),
            'stock_rankings': [{
                'ticker': ticker,
                'reason': 'EV manufacturing budget beneficiary',
            }],
        },
        'theme': {
            'generated_at': _now(),
            'baskets': [{
                'theme_id': 'auto_ev',
                'stocks': {'direct': [ticker], 'indirect': [], 'avoid_or_risk': []},
            }],
        },
        'global': {'generated_at': _now(), 'summary': 'risk on global support'},
        'my_feed': [],
        'broker': [],
        'tv': [],
        'memory': [],
        'risk': {},
    }


def main() -> int:
    from backend.telegram.formatting.telegram_formatter import sanitize_telegram_text
    import backend.telegram.response_format as response_format
    from backend.telegram.response_format import format_tradecard_evidence_explain_telegram
    from backend.trading.tradecard_evidence import (
        build_tradecard_evidence_matrix,
        format_tradecard_evidence_matrix_telegram,
    )
    from backend.trading.tradecard_refresh import parse_tradecard_explain_ticker

    strong = build_tradecard_evidence_matrix('TATAMOTORS', _base_context())
    assert strong['consensus_score'] >= 80, strong
    assert strong['decision'] in ('HIGH CONVICTION WATCH', 'VALID ENTRY'), strong
    assert any(row['module'] == 'scanner' for row in strong['direct_confirms'])
    assert any(row['module'] == 'news' for row in strong['direct_confirms'])

    no_scanner_ctx = _base_context('TATAMOTORS')
    no_scanner_ctx['scanner'] = {'generated_at': _now(), 'top_signals': []}
    no_scanner = build_tradecard_evidence_matrix('TATAMOTORS', no_scanner_ctx)
    assert no_scanner['decision'] == 'RESEARCH WATCH ONLY', no_scanner
    assert no_scanner['consensus_score'] <= 55, no_scanner

    risk_off_ctx = _base_context('TATAMOTORS')
    risk_off_ctx['global'] = {'generated_at': _now(), 'summary': 'risk-off global weakness and crude spike'}
    risk_off = build_tradecard_evidence_matrix('TATAMOTORS', risk_off_ctx)
    assert risk_off['consensus_score'] < strong['consensus_score'], (risk_off, strong)
    assert any(row['module'] == 'global' and row['verdict'] == 'warn' for row in risk_off['risk_filters'])

    blocked_ctx = _base_context('TATAMOTORS')
    blocked_ctx['risk'] = {'blocked': ['TATAMOTORS'], 'reason': 'avoid list conflict'}
    blocked = build_tradecard_evidence_matrix('TATAMOTORS', blocked_ctx)
    assert blocked['decision'] == 'AVOID / BLOCKED', blocked

    assert any(row['module'] == 'budget' for row in strong['indirect_confirms'])
    assert any(row['module'] == 'theme' for row in strong['indirect_confirms'])
    assert not any(row['module'] == 'budget' for row in strong['direct_confirms'])
    assert not any(row['module'] == 'theme' for row in strong['direct_confirms'])

    compact = format_tradecard_evidence_matrix_telegram(strong, compact=True)
    assert 'Evidence Matrix' in compact
    assert 'Consensus:' in compact
    assert 'Direct confirms:' in compact

    assert parse_tradecard_explain_ticker('explain TATAMOTORS fresh') == 'TATAMOTORS'
    explain_text = format_tradecard_evidence_explain_telegram('TATAMOTORS')
    assert 'Evidence Matrix - TATAMOTORS' in explain_text

    import backend.trading.trade_card_engine as trade_card_engine

    original_get_trade_card = trade_card_engine.get_trade_card
    original_is_stale = trade_card_engine.is_trade_card_stale
    original_source = trade_card_engine.resolve_tradecard_source_label
    original_top = response_format._tradecard_unified_today_top
    original_fallback = response_format._tradecard_reviewed_fallback
    try:
        trade_card_engine.get_trade_card = lambda rebuild=False: {
            'ok': True,
            'session_date': '2026-06-28',
            'generated_at': _now(),
            'ticker': 'TATAMOTORS',
            'status': 'NEXT_SESSION_WATCH',
            'after_hours': True,
            'entry_zone': 'NO ACTIVE ENTRY',
            'reason': 'market closed/after-hours',
            'paper_only': True,
        }
        trade_card_engine.is_trade_card_stale = lambda card: False
        trade_card_engine.resolve_tradecard_source_label = lambda card, ticker: 'Source: scanner-confirmed'
        response_format._tradecard_unified_today_top = lambda: ('', '')
        response_format._tradecard_reviewed_fallback = lambda: ('', '')
        tradecard_text = response_format.format_tradecard_telegram(freshness_meta={'refresh_skipped': True})
    finally:
        trade_card_engine.get_trade_card = original_get_trade_card
        trade_card_engine.is_trade_card_stale = original_is_stale
        trade_card_engine.resolve_tradecard_source_label = original_source
        response_format._tradecard_unified_today_top = original_top
        response_format._tradecard_reviewed_fallback = original_fallback
    assert 'Evidence Matrix' in tradecard_text, tradecard_text
    assert 'Use /tradecard explain TATAMOTORS' in tradecard_text, tradecard_text

    empty_ctx = {
        'market_mode': 'LIVE',
        'scanner': [],
        'news': [],
        'my_feed': [],
        'broker': [],
        'budget': {},
        'theme': {},
        'global': {},
        'tv': [],
        'memory': [],
        'risk': {},
    }
    empty = build_tradecard_evidence_matrix('RANDOMX', empty_ctx)
    assert empty['selection_basis_ok'] is False, empty
    assert empty['decision'] == 'NO TRADE / REJECTED', empty

    after_hours_ctx = _base_context('TATAMOTORS')
    after_hours_ctx['market_mode'] = 'AFTER_HOURS'
    after_hours_ctx['live_trigger'] = True
    after_hours = build_tradecard_evidence_matrix('TATAMOTORS', after_hours_ctx)
    assert after_hours['decision'] != 'VALID ENTRY', after_hours
    assert 'WATCH' in after_hours['decision'], after_hours

    emoji_text = sanitize_telegram_text('\U0001f534 Risk\n\U0001f7e2 Fresh')
    assert '\U0001f534' in emoji_text and '\U0001f7e2' in emoji_text
    assert '\ufffd' not in emoji_text

    assert 'BUY' not in compact.upper()
    assert 'SELL' not in compact.upper()

    print('TRADECARD_EVIDENCE_MATRIX_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
