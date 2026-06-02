#!/usr/bin/env python3
"""
Validate frontend external evidence wiring.

Prints FRONTEND_EXTERNAL_EVIDENCE_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BROKER_PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'BrokerIntelligencePanel.js'
DRP_PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'DailyReportPackPanel.js'
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'

REQUIRED = (
    'External Evidence',
    'External evidence is separated from our final prediction',
    'broker_prediction_candidate',
    'stock_news_evidence',
    'market_context',
    'macro_context',
    'broker_candidates',
    'stock_news',
)


def _fail(msg: str) -> int:
    print(f'FRONTEND_EXTERNAL_EVIDENCE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for path in (BROKER_PANEL, DRP_PANEL, INDEX):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    combined = (
        BROKER_PANEL.read_text(encoding='utf-8')
        + DRP_PANEL.read_text(encoding='utf-8')
        + INDEX.read_text(encoding='utf-8')
    )
    for token in REQUIRED:
        if token not in combined:
            return _fail(f'missing marker: {token!r}')

    print('FRONTEND_EXTERNAL_EVIDENCE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
