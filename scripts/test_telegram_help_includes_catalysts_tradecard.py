#!/usr/bin/env python3
"""Stage 50P — /help lists catalyst radar and trade card commands."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

FORBIDDEN = re.compile(r'\b(guaranteed|99%)\b', re.IGNORECASE)
NAKED_BUY_SELL = re.compile(r'\bAction:\s*(BUY|SELL)\b', re.IGNORECASE)

HELP_CATALYST_MARKERS = (
    '<b>Catalyst Radar:</b>',
    '/catalysts — stock-specific catalyst radar',
    '/catalysts today — today\'s catalyst priority list',
    '/catalysts explain &lt;ticker&gt;',
)
HELP_TRADECARD_MARKERS = (
    '<b>Trade Card:</b>',
    '/tradecard — one-stock paper trade card',
    '/tradecard today — today\'s trade card',
    '/tradecard explain — full trade card plan notes',
)

COMMAND_CASES = (
    '/catalysts',
    '/catalysts today',
    '/catalysts explain HCLTECH',
    '/tradecard',
    '/tradecard today',
    '/tradecard explain',
)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_HELP_INCLUDES_CATALYSTS_TRADECARD_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD
    from backend.telegram.telegram_analysis_bot import HELP_TEXT, handle_analysis_command

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 50W':
        return _fail(f'expected AstraEdge 50W got {ASTRAEDGE_TELEGRAM_BUILD!r}')

    for marker in HELP_CATALYST_MARKERS:
        if marker not in HELP_TEXT:
            return _fail(f'HELP_TEXT missing catalyst marker {marker!r}')
    for marker in HELP_TRADECARD_MARKERS:
        if marker not in HELP_TEXT:
            return _fail(f'HELP_TEXT missing tradecard marker {marker!r}')

    bot_src = (PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')
    if "cmd == 'catalysts'" not in bot_src or "cmd == 'tradecard'" not in bot_src:
        return _fail('telegram_analysis_bot missing catalyst/tradecard handlers')

    fake_radar = {
        'priority_list': [{
            'ticker': 'HCLTECH',
            'side': 'BULLISH',
            'catalyst_type': 'ACQUISITION',
            'freshness_label': 'today',
            'change_pct': 3.1,
            'volume_ratio': 1.2,
            'priority': 'HIGH',
            'trade_status': 'WAIT FOR VOLUME',
        }],
        'items': [{
            'ticker': 'HCLTECH',
            'side': 'BULLISH',
            'catalyst_type': 'ACQUISITION',
            'headline': 'AI stake',
            'freshness_label': 'today',
            'change_pct': 3.1,
            'volume_ratio': 1.2,
            'score': 78,
            'priority': 'HIGH',
            'trade_status': 'WAIT FOR VOLUME',
            'score_breakdown': {'freshness': 20, 'quality': 22, 'price_reaction': 12, 'volume_confirmation': 8},
        }],
    }
    fake_card = {
        'ok': True,
        'ticker': 'IXIGO',
        'status': 'VALID_ENTRY',
        'current_price': 420,
        'entry_zone': '418–422',
        'stop_loss': 410,
        'target_1': 430,
        'target_2': 440,
        'risk_reward': 2.1,
        'capital_plan': 'Paper only',
        'reason': 'Aligned setup',
        'invalid_if': 'Below 410',
        'exit_rule': 'Trim at T1',
        'confidence': 'MEDIUM',
        'paper_only': True,
    }

    with patch('scripts.refresh_local_intelligence.run_refresh_scoped', return_value={'ok': True}), \
         patch('backend.intelligence.stock_catalyst_radar.build_catalyst_radar', return_value=fake_radar), \
         patch('backend.intelligence.stock_catalyst_radar.get_catalyst_radar', return_value=fake_radar), \
         patch('backend.trading.trade_card_engine.get_trade_card', return_value=fake_card):
        help_results = handle_analysis_command('/help', 'help_test', dry_run=True)
        help_text = str((help_results[0] if help_results else {}).get('text') or '')
        if help_text != HELP_TEXT:
            return _fail('/help must return HELP_TEXT verbatim')

        for cmd in COMMAND_CASES:
            results = handle_analysis_command(cmd, 'help_test', dry_run=True)
            if not results:
                return _fail(f'no response for {cmd}')
            text = str(results[0].get('text') or '')
            if len(text.strip()) < 20:
                return _fail(f'response too short for {cmd}')
            if FORBIDDEN.search(text):
                return _fail(f'forbidden language in {cmd}')
            if NAKED_BUY_SELL.search(text):
                return _fail(f'naked BUY/SELL in {cmd}')
            if cmd.startswith('/catalysts') and 'CATALYST' not in text.upper():
                return _fail(f'{cmd} must return catalyst output')
            if cmd.startswith('/tradecard') and 'TRADE CARD' not in text.upper():
                return _fail(f'{cmd} must return trade card output')

    print('TELEGRAM_HELP_INCLUDES_CATALYSTS_TRADECARD_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
