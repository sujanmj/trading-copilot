#!/usr/bin/env python3
"""Unit tests for broker GUI evidence sections (Stage 48O)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _fail(msg: str) -> int:
    print(f'BROKER_GUI_EVIDENCE_SECTIONS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    panel = (PROJECT_ROOT / 'frontend/components/BrokerIntelligencePanel.js').read_text(encoding='utf-8')
    for needle in (
        'renderBrokerConsensusSection',
        'renderMarketWatchlistSection',
        'renderExternalEvidenceSection',
        'Market Watchlist Mentions',
        'Broker/Analyst Consensus',
    ):
        if needle not in panel:
            return _fail(f'missing {needle!r} in BrokerIntelligencePanel.js')

    print('BROKER_GUI_EVIDENCE_SECTIONS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
