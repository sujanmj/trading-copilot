#!/usr/bin/env python3
"""
Validate frontend external evidence wiring in Final Confidence / Watchlist.

Prints FRONTEND_EXTERNAL_EVIDENCE_CONFIDENCE_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'FinalConfidencePanel.js'

REQUIRED = (
    'External Evidence',
    'External evidence is read-only and not trade execution',
    'external_evidence_summary',
    'stock_news_count',
    'latest_titles',
    'score_adjustment',
    'renderExternalEvidenceSection',
)


def _fail(msg: str) -> int:
    print(f'FRONTEND_EXTERNAL_EVIDENCE_CONFIDENCE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not PANEL.is_file():
        return _fail(f'missing {PANEL.relative_to(PROJECT_ROOT)}')

    src = PANEL.read_text(encoding='utf-8')
    for token in REQUIRED:
        if token not in src:
            return _fail(f'FinalConfidencePanel.js missing marker: {token!r}')

    print('FRONTEND_EXTERNAL_EVIDENCE_CONFIDENCE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
