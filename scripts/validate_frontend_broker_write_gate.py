#!/usr/bin/env python3
"""
Validate frontend broker DB write gate wiring.

Prints FRONTEND_BROKER_WRITE_GATE_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BROKER_PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'BrokerIntelligencePanel.js'
DRP_PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'DailyReportPackPanel.js'

REQUIRED = (
    'Broker DB Write Review',
    'Only write-safe items can enter broker prediction memory',
    'broker_write_review',
    'write_safe',
    'review_only',
    'rejected',
    'renderBrokerWriteReviewSection',
)


def _fail(msg: str) -> int:
    print(f'FRONTEND_BROKER_WRITE_GATE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for path in (BROKER_PANEL, DRP_PANEL):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    combined = BROKER_PANEL.read_text(encoding='utf-8') + DRP_PANEL.read_text(encoding='utf-8')
    for token in REQUIRED:
        if token not in combined:
            return _fail(f'missing marker: {token!r}')

    print('FRONTEND_BROKER_WRITE_GATE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
