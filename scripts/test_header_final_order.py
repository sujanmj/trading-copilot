#!/usr/bin/env python3
"""Unit tests for final header order (Stage 48D)."""

from __future__ import annotations

import sys
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'HEADER_FINAL_ORDER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = INDEX.read_text(encoding='utf-8')
    header = src[src.find('<header class="app-header"'):src.find('</header>')]
    nav = header[header.find('header-nav-group'):header.find('id="brokerSourceRow"')]

    router_pos = nav.find('id="routerNavBtn"')
    live_pos = nav.find('live-badge')
    review_pos = nav.find('id="reviewBtn"')
    memory_pos = nav.find('id="memoryNavBtn"')
    budget_pos = nav.find('id="budgetNavBtn"')
    brokers_pos = nav.find('id="brokersNavBtn"')
    aihub_pos = nav.find('id="aiHubNavBtn"')

    if min(router_pos, live_pos, review_pos, memory_pos) < 0:
        return _fail('header controls missing')
    if not (router_pos < live_pos < review_pos < memory_pos < budget_pos < brokers_pos < aihub_pos):
        return _fail('Router/LIVE/API/REVIEW must appear before Memory/Budget/Brokers/AI Hub')

    for label in ('Angel', 'MC', 'NSE'):
        if label not in header:
            return _fail(f'broker/news missing {label!r}')

    print('HEADER_FINAL_ORDER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
