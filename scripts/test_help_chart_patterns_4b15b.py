#!/usr/bin/env python3
"""Phase 4B.15B — /help Chart Patterns section layout."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'HELP_CHART_PATTERNS_4B15B_FAIL: {msg}', file=sys.stderr)
    return 1


def _section_block(help_text: str, heading: str, *, next_heading: str) -> str:
    start = help_text.find(heading)
    end = help_text.find(next_heading)
    if start < 0 or end < 0 or end <= start:
        return ''
    return help_text[start:end]


def test_help_chart_patterns_section() -> int:
    from backend.telegram.telegram_analysis_bot import HELP_TEXT

    if '<b>Chart Patterns:</b>' not in HELP_TEXT:
        return _fail('help must contain Chart Patterns section')
    if '/patterns — scan chart patterns for /tradecards top 10' not in HELP_TEXT:
        return _fail('help must list /patterns board command')
    if '/pattern — best chart-pattern candidate from /tradecards top 10' not in HELP_TEXT:
        return _fail('help must list /pattern pick command')
    if '/pattern SYMBOL — check chart pattern for one stock' not in HELP_TEXT:
        return _fail('help must list /pattern SYMBOL')
    if '/candles SYMBOL — debug candle snapshots and pattern readiness' not in HELP_TEXT:
        return _fail('help must list /candles debug command')
    if '/patterns SYMBOL' in HELP_TEXT:
        return _fail('help must not list duplicate /patterns SYMBOL')
    return 0


def test_patterns_under_chart_patterns_not_trade_card() -> int:
    from backend.telegram.telegram_analysis_bot import HELP_TEXT

    trade_block = _section_block(
        HELP_TEXT,
        '<b>Trade Card:</b>',
        next_heading='<b>Chart Patterns:</b>',
    )
    chart_block = _section_block(
        HELP_TEXT,
        '<b>Chart Patterns:</b>',
        next_heading='<b>Briefs:</b>',
    )
    if not trade_block:
        return _fail('Trade Card section missing')
    if not chart_block:
        return _fail('Chart Patterns section missing')
    if '/patterns' in trade_block:
        return _fail('Trade Card section must not contain /patterns')
    if '/pattern SYMBOL' not in chart_block:
        return _fail('/pattern SYMBOL must appear under Chart Patterns')
    if '/patterns SYMBOL' in chart_block:
        return _fail('Chart Patterns must not list duplicate /patterns SYMBOL')
    return 0


def test_trade_card_section_commands_only() -> int:
    from backend.telegram.telegram_analysis_bot import HELP_TEXT

    trade_block = _section_block(
        HELP_TEXT,
        '<b>Trade Card:</b>',
        next_heading='<b>Chart Patterns:</b>',
    )
    required = (
        '/tradecard — one-stock paper trade card',
        '/tradecard today — today\'s trade card',
        '/tradecard explain — full trade card plan notes',
        '/tradecard journal — today\'s tradecard journal',
        '/tradecard outcome — tradecard outcome summary',
    )
    for line in required:
        if line not in trade_block:
            return _fail(f'Trade Card section missing {line!r}')
    return 0


def test_build_label_51w() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 51W' or ASTRAEDGE_BUILD_STAGE != '51W':
        return _fail(f'expected AstraEdge 51W got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    return 0


def main() -> int:
    for fn in (
        test_help_chart_patterns_section,
        test_patterns_under_chart_patterns_not_trade_card,
        test_trade_card_section_commands_only,
        test_build_label_51w,
    ):
        rc = fn()
        if rc:
            return rc
    print('HELP_CHART_PATTERNS_4B15B_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
