#!/usr/bin/env python3
"""Unit tests for Budget safety language (Stage 48A)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

FORBIDDEN = ('buy now', 'guaranteed', 'sure shot', 'sell now')


def _fail(msg: str) -> int:
    print(f'BUDGET_SAFETY_LANGUAGE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _check_no_forbidden(text: str, label: str) -> int | None:
    lower = str(text or '').lower()
    for word in FORBIDDEN:
        if word in lower:
            return _fail(f'{label} contains forbidden phrase {word!r}')
    return None


def main() -> int:
    import backend.analytics.budget_impact as bi
    import backend.analytics.theme_baskets as tb

    index_html = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    panel_js = (PROJECT_ROOT / 'frontend/components/BudgetImpactPanel.js').read_text(encoding='utf-8')
    for src, label in ((index_html, 'index.html'), (panel_js, 'BudgetImpactPanel.js')):
        err = _check_no_forbidden(src, label)
        if err:
            return err

    with tempfile.TemporaryDirectory() as tmp:
        baskets_path = Path(tmp) / 'theme_baskets.json'
        log_path = Path(tmp) / 'theme_catalyst_log.jsonl'
        orig_baskets = tb.BASKETS_FILE
        orig_log = tb.CATALYST_LOG_FILE
        tb.BASKETS_FILE = baskets_path
        tb.CATALYST_LOG_FILE = log_path
        try:
            tb.bootstrap_theme_baskets(force=True)

            samples = [
                bi.get_budget_overview(),
                bi.analyze_news_text('Govt announces highway project in Bengaluru'),
                bi.analyze_news_text('Congress may lose Karnataka and BJP may come'),
            ]
            for sample in samples:
                blob = str(sample)
                err = _check_no_forbidden(blob, 'engine output')
                if err:
                    return err
                for row in (sample.get('positive') or []) + (sample.get('indirect') or []) + (sample.get('risk') or []):
                    stance = str(row.get('stance') or '')
                    if stance and stance not in bi.ALLOWED_STANCES:
                        return _fail(f'invalid stance {stance!r}')
                    err = _check_no_forbidden(stance, 'stance')
                    if err:
                        return err

            tg_overview = bi.format_budget_overview_telegram()
            tg_analyze = bi.format_budget_analyze_telegram('Union budget infrastructure capex')
            for text in (tg_overview, tg_analyze, bi.handle_budget_command('')):
                err = _check_no_forbidden(text, 'telegram output')
                if err:
                    return err
        finally:
            tb.BASKETS_FILE = orig_baskets
            tb.CATALYST_LOG_FILE = orig_log

    bot_src = (PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')
    if '/budget' not in bot_src or 'run_budget_only' not in bot_src:
        return _fail('telegram bot missing /budget wiring')

    print('BUDGET_SAFETY_LANGUAGE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
