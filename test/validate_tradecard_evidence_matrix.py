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
    assert strong['decision'] in ('HIGH CONVICTION WATCH', 'VALID_ENTRY'), strong
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

    import backend.trading.tradecard_journal as tradecard_journal

    mismatch_matrix = {
        'ticker': 'MISMATCHX',
        'direct_confirms': [{
            'module': 'scanner',
            'scope': 'direct',
            'verdict': 'confirm',
            'weight': 20,
            'freshness': '1m',
            'reason': 'Price/volume confirmation',
            'tickers_matched': ['MISMATCHX'],
            'sectors_matched': [],
        }],
        'indirect_confirms': [{
            'module': 'theme',
            'scope': 'indirect',
            'verdict': 'confirm',
            'weight': 5,
            'freshness': '1m',
            'reason': 'sector basket support',
            'tickers_matched': ['MISMATCHX'],
            'sectors_matched': ['pharma'],
        }],
        'risk_filters': [{
            'module': 'global',
            'scope': 'risk',
            'verdict': 'warn',
            'weight': -8,
            'freshness': '1m',
            'reason': 'Macro risk tone: war',
            'tickers_matched': [],
            'sectors_matched': [],
        }],
        'missing_modules': [
            {'module': 'news', 'scope': 'no_data', 'verdict': 'neutral', 'weight': 0, 'freshness': 'missing', 'reason': 'No direct stock catalyst'},
            {'module': 'my_feed', 'scope': 'no_data', 'verdict': 'neutral', 'weight': 0, 'freshness': 'missing', 'reason': 'No direct feed catalyst'},
            {'module': 'broker', 'scope': 'no_data', 'verdict': 'neutral', 'weight': 0, 'freshness': 'missing', 'reason': 'No broker confirmation'},
            {'module': 'budget', 'scope': 'no_data', 'verdict': 'neutral', 'weight': 0, 'freshness': 'missing', 'reason': 'No budget link'},
        ],
        'consensus_score': 64,
        'confidence': 'LOW',
        'decision': 'MOMENTUM-ONLY WATCH',
        'final_reason': 'Scanner confirms price/volume, but no fresh direct catalyst was found.',
        'market_mode': 'LIVE',
        'selection_basis_ok': True,
        'scanner_confirmed': True,
        'direct_catalyst_confirmed': False,
    }
    original_get_trade_card = trade_card_engine.get_trade_card
    original_is_stale = trade_card_engine.is_trade_card_stale
    original_source = trade_card_engine.resolve_tradecard_source_label
    original_top = response_format._tradecard_unified_today_top
    original_fallback = response_format._tradecard_reviewed_fallback
    original_matrix = response_format._build_tradecard_evidence_matrix
    original_active = tradecard_journal.get_active_valid_entry
    try:
        trade_card_engine.get_trade_card = lambda rebuild=False: {
            'ok': True,
            'session_date': '2026-06-29',
            'generated_at': _now(),
            'ticker': 'MISMATCHX',
            'status': 'VALID_ENTRY',
            'current_price': 100.0,
            'entry_zone': '99.80-100.30',
            'stop_loss': 99.0,
            'target_1': 101.0,
            'target_2': 102.0,
            'risk_reward': 1.8,
            'confidence': 'MEDIUM',
            'capital_plan': 'Paper only',
            'reason': 'legacy card says valid',
            'invalid_if': 'volume fades',
            'paper_only': True,
        }
        trade_card_engine.is_trade_card_stale = lambda card: False
        trade_card_engine.resolve_tradecard_source_label = lambda card, ticker: 'Source: scanner-confirmed'
        response_format._tradecard_unified_today_top = lambda: ('', '')
        response_format._tradecard_reviewed_fallback = lambda: ('', '')
        response_format._build_tradecard_evidence_matrix = lambda ticker, card=None, freshness_meta=None: mismatch_matrix
        tradecard_journal.get_active_valid_entry = lambda ticker: None
        mismatch_text = response_format.format_tradecard_telegram(freshness_meta={'refresh_skipped': True})
    finally:
        trade_card_engine.get_trade_card = original_get_trade_card
        trade_card_engine.is_trade_card_stale = original_is_stale
        trade_card_engine.resolve_tradecard_source_label = original_source
        response_format._tradecard_unified_today_top = original_top
        response_format._tradecard_reviewed_fallback = original_fallback
        response_format._build_tradecard_evidence_matrix = original_matrix
        tradecard_journal.get_active_valid_entry = original_active
    assert '<b>MISMATCHX</b>' in mismatch_text, mismatch_text
    assert '<code>MOMENTUM-ONLY WATCH</code>' in mismatch_text, mismatch_text
    assert '<b>MISMATCHX</b> · <code>VALID_ENTRY</code>' not in mismatch_text, mismatch_text
    assert 'Confidence: LOW' in mismatch_text, mismatch_text
    assert 'Decision: <code>MOMENTUM-ONLY WATCH</code>' in mismatch_text, mismatch_text
    assert 'Capital plan: Watch only; no chase.' in mismatch_text, mismatch_text

    def _active_row(ticker='MISMATCHX'):
        return {
            'ticker': ticker,
            'status': 'VALID_ENTRY',
            'price_at_signal': 100.0,
            'entry_low': 99.8,
            'entry_high': 100.3,
            'stop': 99.0,
            't1': 101.0,
            't2': 102.0,
            'outcome_status': 'PENDING',
            'confidence': 'MEDIUM',
            'reason': 'old paper card',
        }

    original_get_trade_card = trade_card_engine.get_trade_card
    original_is_stale = trade_card_engine.is_trade_card_stale
    original_source = trade_card_engine.resolve_tradecard_source_label
    original_top = response_format._tradecard_unified_today_top
    original_fallback = response_format._tradecard_reviewed_fallback
    original_matrix = response_format._build_tradecard_evidence_matrix
    original_active = tradecard_journal.get_active_valid_entry
    original_track = tradecard_journal.track_active_tradecard_outcome
    try:
        trade_card_engine.get_trade_card = lambda rebuild=False: {
            'ok': True,
            'session_date': '2026-06-29',
            'generated_at': _now(),
            'ticker': 'MISMATCHX',
            'status': 'VALID_ENTRY',
            'current_price': 100.1,
            'entry_zone': '99.80-100.30',
            'stop_loss': 99.0,
            'target_1': 101.0,
            'target_2': 102.0,
            'risk_reward': 1.8,
            'confidence': 'MEDIUM',
            'reason': 'legacy active card',
            'invalid_if': 'volume fades',
            'paper_only': True,
        }
        trade_card_engine.is_trade_card_stale = lambda card: False
        trade_card_engine.resolve_tradecard_source_label = lambda card, ticker: 'Source: scanner-confirmed'
        response_format._tradecard_unified_today_top = lambda: ('', '')
        response_format._tradecard_reviewed_fallback = lambda: ('', '')
        response_format._build_tradecard_evidence_matrix = lambda ticker, card=None, freshness_meta=None: mismatch_matrix
        tradecard_journal.get_active_valid_entry = lambda ticker: _active_row(ticker)
        tradecard_journal.track_active_tradecard_outcome = lambda active, refresh=False, source='': active
        active_downgraded_text = response_format.format_tradecard_telegram(freshness_meta={'refresh_skipped': True})
    finally:
        trade_card_engine.get_trade_card = original_get_trade_card
        trade_card_engine.is_trade_card_stale = original_is_stale
        trade_card_engine.resolve_tradecard_source_label = original_source
        response_format._tradecard_unified_today_top = original_top
        response_format._tradecard_reviewed_fallback = original_fallback
        response_format._build_tradecard_evidence_matrix = original_matrix
        tradecard_journal.get_active_valid_entry = original_active
        tradecard_journal.track_active_tradecard_outcome = original_track
    assert 'TRADE CARD — EXISTING PAPER CARD' in active_downgraded_text, active_downgraded_text
    assert 'EVIDENCE DOWNGRADED: MOMENTUM-ONLY WATCH' in active_downgraded_text, active_downgraded_text
    assert 'ACTIVE CARD EXISTS' not in active_downgraded_text, active_downgraded_text
    assert '· <code>TRACKING</code>' not in active_downgraded_text, active_downgraded_text
    assert 'Plan: Track old paper card only. No new entry. No duplicate card. Do not chase.' in active_downgraded_text, active_downgraded_text
    assert 'Confidence: LOW' in active_downgraded_text, active_downgraded_text
    assert 'Decision: <code>MOMENTUM-ONLY WATCH</code>' in active_downgraded_text, active_downgraded_text

    valid_active_matrix = {
        **mismatch_matrix,
        'consensus_score': 82,
        'confidence': 'HIGH',
        'decision': 'VALID_ENTRY',
        'final_reason': 'Scanner and direct catalyst align.',
        'direct_catalyst_confirmed': True,
        'direct_confirms': [
            *mismatch_matrix['direct_confirms'],
            {
                'module': 'news',
                'scope': 'direct',
                'verdict': 'confirm',
                'weight': 15,
                'freshness': '1m',
                'reason': 'fresh direct catalyst',
                'tickers_matched': ['MISMATCHX'],
                'sectors_matched': [],
            },
        ],
        'risk_filters': [],
    }
    original_get_trade_card = trade_card_engine.get_trade_card
    original_is_stale = trade_card_engine.is_trade_card_stale
    original_source = trade_card_engine.resolve_tradecard_source_label
    original_top = response_format._tradecard_unified_today_top
    original_fallback = response_format._tradecard_reviewed_fallback
    original_matrix = response_format._build_tradecard_evidence_matrix
    original_active = tradecard_journal.get_active_valid_entry
    original_track = tradecard_journal.track_active_tradecard_outcome
    try:
        trade_card_engine.get_trade_card = lambda rebuild=False: {
            'ok': True,
            'session_date': '2026-06-29',
            'generated_at': _now(),
            'ticker': 'MISMATCHX',
            'status': 'VALID_ENTRY',
            'current_price': 100.1,
            'entry_zone': '99.80-100.30',
            'stop_loss': 99.0,
            'target_1': 101.0,
            'target_2': 102.0,
            'risk_reward': 1.8,
            'confidence': 'MEDIUM',
            'reason': 'legacy active card',
            'invalid_if': 'volume fades',
            'paper_only': True,
        }
        trade_card_engine.is_trade_card_stale = lambda card: False
        trade_card_engine.resolve_tradecard_source_label = lambda card, ticker: 'Source: catalyst-backed + scanner-confirmed'
        response_format._tradecard_unified_today_top = lambda: ('', '')
        response_format._tradecard_reviewed_fallback = lambda: ('', '')
        response_format._build_tradecard_evidence_matrix = lambda ticker, card=None, freshness_meta=None: valid_active_matrix
        tradecard_journal.get_active_valid_entry = lambda ticker: _active_row(ticker)
        tradecard_journal.track_active_tradecard_outcome = lambda active, refresh=False, source='': active
        active_valid_text = response_format.format_tradecard_telegram(freshness_meta={'refresh_skipped': True})
    finally:
        trade_card_engine.get_trade_card = original_get_trade_card
        trade_card_engine.is_trade_card_stale = original_is_stale
        trade_card_engine.resolve_tradecard_source_label = original_source
        response_format._tradecard_unified_today_top = original_top
        response_format._tradecard_reviewed_fallback = original_fallback
        response_format._build_tradecard_evidence_matrix = original_matrix
        tradecard_journal.get_active_valid_entry = original_active
        tradecard_journal.track_active_tradecard_outcome = original_track
    assert 'TRADE CARD — ACTIVE CARD EXISTS' in active_valid_text, active_valid_text
    assert '· <code>TRACKING</code>' in active_valid_text, active_valid_text
    assert 'EVIDENCE DOWNGRADED' not in active_valid_text, active_valid_text
    assert 'Confidence: HIGH' in active_valid_text, active_valid_text
    assert 'Decision: <code>VALID_ENTRY</code>' in active_valid_text, active_valid_text

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
