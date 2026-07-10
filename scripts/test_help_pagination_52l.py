#!/usr/bin/env python3
"""AstraEdge 52L — /help pagination: compact index, section help, safe multi-part full."""

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

MAX_SINGLE_HELP_CHARS = 3500
COMPACT_TARGET_CHARS = 2500


def _fail(msg: str) -> int:
    print(f'HELP_PAGINATION_52L_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _help_texts(command: str) -> list[str]:
    from backend.telegram.telegram_analysis_bot import handle_analysis_command

    results = handle_analysis_command(command, 'help_pagination_test', dry_run=True)
    return [str(item.get('text') or '') for item in (results or [])]


def test_default_help_compact() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD
    from backend.telegram.help_text import format_help_index

    texts = _help_texts('/help')
    if len(texts) != 1:
        return _fail(f'/help must return one message, got {len(texts)}')
    text = texts[0]
    if text != format_help_index():
        return _fail('/help must return compact help index')
    if len(text) > COMPACT_TARGET_CHARS:
        return _fail(f'compact /help too long: {len(text)} chars')
    for marker in (
        '/help core',
        '/help full',
        '/help investor',
        '/help weekly',
        '/help patterns',
        'Build: AstraEdge 52L',
    ):
        if marker not in text:
            return _fail(f'compact /help missing {marker!r}')
    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 52L':
        return _fail(f'expected build 52L, got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    return 0


def test_commands_alias() -> int:
    default = _help_texts('/help')
    alias = _help_texts('/commands')
    if default != alias:
        return _fail('/commands must match /help')
    return 0


def test_help_full_multipart() -> int:
    from backend.telegram.help_text import HELP_TEXT, format_help_full_parts

    texts = _help_texts('/help full')
    expected = format_help_full_parts()
    if texts != expected:
        return _fail('/help full must match format_help_full_parts()')
    if len(texts) < 2:
        return _fail('/help full must split into multiple parts')
    for index, text in enumerate(texts, start=1):
        if len(text) > MAX_SINGLE_HELP_CHARS:
            return _fail(f'help part {index} exceeds {MAX_SINGLE_HELP_CHARS} chars')
        if f'Part {index}/{len(texts)}' not in text:
            return _fail(f'help part {index} missing Part header')
    joined = '\n'.join(texts)
    for marker in (
        '<b>Theme Wishlist:</b>',
        '<b>Budget Impact:</b>',
        '/ask ai &lt;question&gt;',
    ):
        if marker not in joined:
            return _fail(f'/help full missing ending marker {marker!r}')
    for block in ('<b>Theme Wishlist:</b>', '<b>Budget Impact:</b>', '/ask ai'):
        if block not in HELP_TEXT or block not in joined:
            return _fail(f'full help must preserve {block!r} from HELP_TEXT')
    all_alias = _help_texts('/help all')
    if all_alias != texts:
        return _fail('/help all must match /help full')
    return 0


def test_section_help() -> int:
    investor = _help_texts('/help investor')[0]
    for marker in (
        '<b>Investor Intelligence:</b>',
        '/investor SYMBOL',
        '/investor weekly',
        '/investor memory SYMBOL',
    ):
        if marker not in investor:
            return _fail(f'/help investor missing {marker!r}')

    weekly = _help_texts('/help weekly')[0]
    for marker in (
        '<b>Weekly Conviction:</b>',
        '/weekly picks',
        '/weekly history',
        '/weekly explain SYMBOL',
    ):
        if marker not in weekly:
            return _fail(f'/help weekly missing {marker!r}')

    patterns = _help_texts('/help patterns')[0]
    for marker in (
        '/patterns — scan chart patterns for /tradecards top 10',
        '/candles SYMBOL — debug candle snapshots and pattern readiness',
    ):
        if marker not in patterns:
            return _fail(f'/help patterns missing {marker!r}')
    if '/patterns SYMBOL' in patterns:
        return _fail('/help patterns must not list /patterns SYMBOL')
    return 0


def test_no_truncation_in_help_responses() -> int:
    cases = (
        '/help',
        '/help full',
        '/help investor',
        '/help weekly',
        '/help patterns',
        '/help trade',
    )
    for command in cases:
        for text in _help_texts(command):
            if '… (truncated)' in text:
                return _fail(f'{command} response was truncated')
            if len(text) > MAX_SINGLE_HELP_CHARS:
                return _fail(f'{command} part exceeds {MAX_SINGLE_HELP_CHARS} chars')
    return 0


def main() -> int:
    checks = (
        test_default_help_compact,
        test_commands_alias,
        test_help_full_multipart,
        test_section_help,
        test_no_truncation_in_help_responses,
    )
    for check in checks:
        err = check()
        if err:
            return err
    print('HELP_PAGINATION_52L_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
