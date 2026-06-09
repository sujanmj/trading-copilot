#!/usr/bin/env python3
"""Validate broker evidence_type classification (Stage 48O)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    src = (PROJECT_ROOT / 'backend/analytics/broker_intelligence.py').read_text(encoding='utf-8')
    for needle in ('classify_evidence_type', 'market_watchlist_mention', 'CONSENSUS_EVIDENCE_TYPES'):
        if needle not in src:
            print(f'BROKER_EVIDENCE_TYPE_CLASSIFICATION_FAIL: missing {needle}', file=sys.stderr)
            return 1
    if os.system(f'{sys.executable} scripts/test_broker_evidence_type_classification.py') != 0:
        return 1
    print('BROKER_EVIDENCE_TYPE_CLASSIFICATION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
