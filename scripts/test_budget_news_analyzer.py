#!/usr/bin/env python3
"""Unit tests for Budget news analyzer (Stage 48A)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'BUDGET_NEWS_ANALYZER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    import backend.analytics.budget_impact as bi
    import backend.analytics.theme_baskets as tb

    with tempfile.TemporaryDirectory() as tmp:
        baskets_path = Path(tmp) / 'theme_baskets.json'
        log_path = Path(tmp) / 'theme_catalyst_log.jsonl'
        orig_baskets = tb.BASKETS_FILE
        orig_log = tb.CATALYST_LOG_FILE
        tb.BASKETS_FILE = baskets_path
        tb.CATALYST_LOG_FILE = log_path
        try:
            tb.bootstrap_theme_baskets(force=True)

            headline = 'Govt announces new highway project in Bengaluru'
            result = bi.analyze_news_text(headline)
            if not result.get('ok'):
                return _fail('analyzer returned not ok')
            names = [t.get('display_name', '') for t in (result.get('detected_themes') or [])]
            blob = ' '.join(names).lower()
            if 'road' not in blob and 'highway' not in blob:
                return _fail('highway project should map to Roads/Highways theme')
            if 'infrastructure' not in ' '.join(t.get('theme_id', '') for t in result.get('detected_themes') or []):
                return _fail('highway project should include infrastructure theme')

            if not result.get('impact_map') and result.get('detected_themes'):
                result['impact_map'] = bi.build_impact_map(result['detected_themes'][0]['theme_id'])
            impact = result.get('impact_map') or {}
            if not impact.get('direct_beneficiaries'):
                return _fail('impact map missing direct beneficiaries')

            political = bi.analyze_news_text('Congress may lose Karnataka election and BJP may come')
            if not political.get('political_neutral'):
                return _fail('political headline should use policy continuity mode')
            if political.get('stance') not in bi.ALLOWED_STANCES:
                return _fail('political stance not in allowed set')

            empty = bi.analyze_news_text('')
            if empty.get('ok'):
                return _fail('empty text should fail')

            telegram = bi.format_budget_analyze_telegram(headline)
            if 'highway' not in telegram.lower() and 'road' not in telegram.lower():
                return _fail('telegram analyze formatting missing theme context')
        finally:
            tb.BASKETS_FILE = orig_baskets
            tb.CATALYST_LOG_FILE = orig_log

    print('BUDGET_NEWS_ANALYZER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
