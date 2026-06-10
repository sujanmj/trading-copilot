#!/usr/bin/env python3
"""Unit tests for /theme Telegram commands (Stage 47A)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'THEME_TELEGRAM_COMMANDS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _text(results: list) -> str:
    return str(results[0].get('text', '')) if results else ''


def main() -> int:
    import backend.analytics.theme_baskets as tb
    from backend.telegram.telegram_analysis_bot import HELP_TEXT, handle_analysis_command

    with tempfile.TemporaryDirectory() as tmp:
        baskets_path = Path(tmp) / 'theme_baskets.json'
        log_path = Path(tmp) / 'theme_catalyst_log.jsonl'
        orig_baskets = tb.BASKETS_FILE
        orig_log = tb.CATALYST_LOG_FILE
        tb.BASKETS_FILE = baskets_path
        tb.CATALYST_LOG_FILE = log_path
        try:
            tb.bootstrap_theme_baskets(force=True)

            if '/theme' not in HELP_TEXT:
                return _fail('/theme missing from HELP_TEXT')
            for phrase in ('Theme Wishlist', 'search', 'category', 'refresh'):
                if phrase not in HELP_TEXT:
                    return _fail(f'{phrase} missing from HELP_TEXT')

            list_text = _text(handle_analysis_command('/theme list', 'test', dry_run=True))
            if 'AstraEdge Theme Wishlist' not in list_text:
                return _fail('/theme list missing Theme Wishlist title')
            if 'Government/Budget' not in list_text:
                return _fail('/theme list missing grouped category')
            if 'Infrastructure' not in list_text:
                return _fail('/theme list missing Infrastructure')

            infra_text = _text(handle_analysis_command('/theme infra', 'test', dry_run=True))
            if 'Theme Wishlist' not in infra_text:
                return _fail('/theme infra missing wishlist header')
            if 'Direct beneficiaries' not in infra_text:
                return _fail('/theme infra missing direct beneficiaries')
            if 'buy now' in infra_text.lower() or 'guaranteed' in infra_text.lower():
                return _fail('/theme infra must not contain buy/guaranteed')

            budget_text = _text(handle_analysis_command('/theme budget', 'test', dry_run=True))
            if 'Budget Theme Monitor' not in budget_text:
                return _fail('/theme budget missing title')
            if 'Infrastructure' not in budget_text:
                return _fail('/theme budget missing infrastructure theme')

            news_text = _text(handle_analysis_command('/theme news infra', 'test', dry_run=True))
            if 'Theme News' not in news_text:
                return _fail('/theme news infra missing title')

            scan_text = _text(handle_analysis_command('/theme scan infra', 'test', dry_run=True))
            if 'Theme Scan' not in scan_text:
                return _fail('/theme scan infra missing title')

            health = handle_analysis_command('/health', 'test', dry_run=True)
            if 'AstraEdge 50B' not in _text(health):
                return _fail('/health missing AstraEdge 50B')

            status = handle_analysis_command('/status', 'test', dry_run=True)
            if 'AstraEdge 50B' not in _text(status):
                return _fail('/status missing AstraEdge 50B build line')
        finally:
            tb.BASKETS_FILE = orig_baskets
            tb.CATALYST_LOG_FILE = orig_log

    print('THEME_TELEGRAM_COMMANDS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
