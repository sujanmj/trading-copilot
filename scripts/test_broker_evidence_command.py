#!/usr/bin/env python3
"""Unit tests for /broker evidence command (Stage 48N)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'BROKER_EVIDENCE_COMMAND_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.broker_intelligence import handle_broker_command
    from unittest.mock import patch

    overview = {
        'ok': True,
        'cache_missing': False,
        'evidence_items': [{
            'ticker': 'NIFTY50',
            'headline': 'Asia markets mixed',
            'broker_house': 'Economic Times',
            'rating': 'neutral',
        }],
        'consensus_by_ticker': {
            'NIFTY50': {'consensus_label': 'Neutral', 'freshness': 'fresh'},
        },
    }

    with patch('backend.analytics.broker_intelligence.get_broker_intel_overview', return_value=overview):
        with patch('backend.analytics.broker_intelligence._cache_exists_on_disk', return_value=True):
            text = handle_broker_command('evidence')
    if 'NIFTY50' not in text or 'Asia markets mixed' not in text:
        return _fail('evidence command must show latest evidence')

    slashless = handle_broker_command('evidence')
    if 'Latest evidence' not in slashless:
        return _fail('broker evidence subcommand must render evidence block')

    print('BROKER_EVIDENCE_COMMAND_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
