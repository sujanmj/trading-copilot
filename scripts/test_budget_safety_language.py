#!/usr/bin/env python3
"""Unit tests for budget safety language guard (Stage 48F)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.analytics.budget_impact import FORBIDDEN_WORDS, analyze_news_text, format_budget_analyze_telegram


def _fail(msg: str) -> int:
    print(f'BUDGET_SAFETY_LANGUAGE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    bi_src = (PROJECT_ROOT / 'backend/analytics/budget_impact.py').read_text(encoding='utf-8')
    panel = (PROJECT_ROOT / 'frontend/components/BudgetImpactPanel.js').read_text(encoding='utf-8')
    for word in FORBIDDEN_WORDS:
        if word in panel.lower():
            return _fail(f'frontend must not contain forbidden phrase {word!r}')

    result = analyze_news_text('Govt announces highway project with guaranteed returns buy now')
    blob = str(result) + format_budget_analyze_telegram('Govt announces highway project buy now guaranteed')
    for word in FORBIDDEN_WORDS:
        if word in blob.lower():
            return _fail(f'output must sanitize forbidden phrase {word!r}')

    print('BUDGET_SAFETY_LANGUAGE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
