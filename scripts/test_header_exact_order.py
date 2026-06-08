#!/usr/bin/env python3
"""Unit tests for exact header order (Stage 48E)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'HEADER_EXACT_ORDER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _pos(text: str, needle: str) -> int:
    idx = text.find(needle)
    if idx < 0:
        raise ValueError(f'missing {needle!r}')
    return idx


def main() -> int:
    src = INDEX.read_text(encoding='utf-8')
    header = src[src.find('<header class="app-header"'):src.find('</header>')]
    nav = header[header.find('header-nav-group'):header.find('id="brokerSourceRow"')]

    order = [
        ('live-badge', 'LIVE'),
        ('id="routerNavBtn"', 'Router'),
        ('id="guiModeBadge"', 'WEB LOCAL'),
        ('id="apiTargetBadge"', 'API target'),
        ('id="aiOpsBtn"', 'OPS'),
        ('id="apiStatus"', 'API status'),
        ('id="reviewBtn"', 'REVIEW'),
        ('btn-group-label">AI:', 'AI label'),
        ('id="memoryNavBtn"', 'Memory'),
        ('id="budgetNavBtn"', 'Budget'),
        ('id="brokersNavBtn"', 'Brokers'),
        ('id="aiHubNavBtn"', 'AI Hub'),
    ]
    positions = []
    for needle, label in order:
        try:
            positions.append(_pos(nav, needle))
        except ValueError as exc:
            return _fail(str(exc))
    if positions != sorted(positions):
        return _fail(
            'Expected LIVE → Router → WEB LOCAL → API → OPS → API → REVIEW → AI: → Memory → Budget → Brokers → AI Hub'
        )

    brokers_pos = header.find('id="brokerSourceRow"')
    news_pos = header.find('id="newsSourceRow"')
    if brokers_pos < 0 or news_pos < 0 or not (positions[-1] < brokers_pos < news_pos):
        return _fail('BROKERS row must follow AI nav and precede NEWS row')

    router_css = re.search(r'\.primary-nav-btn\.router-nav-btn\s*\{([^}]+)\}', src, re.S)
    badge_css = re.search(r'\.gui-mode-badge\s*\{\s*display:\s*inline-block;\s*font-size:\s*9px', src, re.S)
    if not router_css or not badge_css:
        return _fail('missing router or API badge CSS blocks')
    if 'font-size: 9px' not in router_css.group(1):
        return _fail('Router button must match API badge font-size')

    for label in ('Angel', 'MC', 'NSE'):
        if label not in header:
            return _fail(f'broker/news missing {label!r}')

    print('HEADER_EXACT_ORDER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
