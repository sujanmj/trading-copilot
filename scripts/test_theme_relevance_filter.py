#!/usr/bin/env python3
"""Unit tests for theme catalyst relevance filter (Stage 47B)."""

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
    print(f'THEME_RELEVANCE_FILTER_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
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

            false_positives = [
                ('Wipro announces ₹10,000 crore buyback programme', 'infrastructure'),
                ('Hindustan Zinc stake sale worth ₹5,000 crore', 'infrastructure'),
                ('Hindustan Zinc stake sale worth ₹5,000 crore', 'roads_highways'),
                ('Page Industries sees heavy F&O activity ahead of expiry', 'railways'),
                ('RBI steps in for currency defence as rupee weakens', 'defence_aerospace'),
            ]
            for headline, theme_id in false_positives:
                if tb.is_theme_catalyst_relevant(headline, theme_id):
                    return _fail(f'false positive: {theme_id!r} matched {headline!r}')
                matches = tb.match_headline_to_themes(headline)
                bad = [m for m in matches if m.get('theme_id') == theme_id]
                if bad:
                    return _fail(f'match_headline_to_themes kept {theme_id!r} for {headline!r}')

            valid = [
                ('Govt announces ₹11,000 crore road project in Delhi', 'roads_highways'),
                ('L&T wins ₹2,500 crore highway order in Maharashtra', 'roads_highways'),
                ('IRCON bags railway signalling contract from Indian Railways', 'railways_metro'),
                ('HAL wins ₹1,200 crore defence order from Indian Army', 'defence_aerospace'),
                ('Ram Mandir tourism boost expected to lift Ayodhya travel demand', 'tourism_temple_culture'),
            ]
            for headline, theme_id in valid:
                if not tb.is_theme_catalyst_relevant(headline, theme_id):
                    return _fail(f'expected relevant: {theme_id!r} for {headline!r}')

            generic = tb.score_theme_catalyst(
                'Infrastructure sector may benefit from policy support',
                'infrastructure',
            )
            if generic is None:
                return _fail('generic policy should still score when sector keyword present')
            if generic.get('impact_10', 10) > 3:
                return _fail('generic policy should cap impact at 3/10')
            if not generic.get('hide_from_top3'):
                return _fail('generic policy should hide from top 3')

            detail = tb.format_theme_detail_telegram('defence_aerospace')
            if tb.NO_CATALYST_MESSAGE not in detail and 'Latest catalysts' not in detail:
                return _fail('detail output missing catalyst section')
            if 'buy now' in detail.lower() or 'guaranteed' in detail.lower():
                return _fail('detail must not contain buy/guaranteed language')

            broad_only = tb.score_theme_catalyst('Government may support infra in coming years', 'infrastructure')
            if broad_only and broad_only.get('impact_10', 10) > 3:
                return _fail('broad-only policy must cap impact at 3/10')
        finally:
            tb.BASKETS_FILE = orig_baskets
            tb.CATALYST_LOG_FILE = orig_log

    print('THEME_RELEVANCE_FILTER_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
