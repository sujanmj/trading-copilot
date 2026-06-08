#!/usr/bin/env python3
"""Unit tests for budget news analyzer/simulator (Stage 48F)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.analytics.budget_impact import analyze_news_text


def _fail(msg: str) -> int:
    print(f'BUDGET_NEWS_ANALYZER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    panel = (PROJECT_ROOT / 'frontend/components/BudgetImpactPanel.js').read_text(encoding='utf-8')
    for needle in ('Detected direction', 'Suggested stance', 'Direct beneficiaries', 'Risks / possible losers'):
        if needle not in panel:
            return _fail(f'BudgetImpactPanel missing simulator field {needle!r}')

    with patch('backend.analytics.budget_impact.compute_freshness_panel', return_value={'status': 'partial'}):
        highway = analyze_news_text('Govt announces ₹11,000 crore highway project in Bengaluru')
        if highway.get('catalyst_direction') != 'Positive':
            return _fail('simulator must detect positive highway catalyst')
        if not highway.get('positive'):
            return _fail('simulator must return direct beneficiaries')

        delay = analyze_news_text('Tata Steel UK project delayed')
        if delay.get('catalyst_direction') != 'Negative':
            return _fail('simulator must detect negative delay catalyst')
        risk_tickers = {r.get('ticker') for r in (delay.get('risk') or [])}
        if 'TATASTEEL' not in risk_tickers:
            return _fail('simulator must mark TATASTEEL as risk on delay headline')

        political = analyze_news_text('BJP may lose Karnataka election and Congress may come to power')
        if not political.get('political_neutral'):
            return _fail('political text must use neutral policy continuity mode')
        if political.get('stance') != 'Wait for Confirmation':
            return _fail('political text stance must be Wait for Confirmation')

    print('BUDGET_NEWS_ANALYZER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
