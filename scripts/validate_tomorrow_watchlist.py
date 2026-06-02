#!/usr/bin/env python3
"""
Validate tomorrow watchlist report structure and shadow-only rules.

Prints exactly TOMORROW_WATCHLIST_VALIDATE_OK on success.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = PROJECT_ROOT / 'data' / 'tomorrow_watchlist_report.json'

FORBIDDEN_KEYS = frozenset({
    'trade_execution',
    'execute_trade',
    'order_placed',
    'telegram_sent',
})


def _fail(msg: str) -> int:
    print(f'TOMORROW_WATCHLIST_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def _walk_keys(obj: object, prefix: str = '') -> list[str]:
    keys: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f'{prefix}.{key}' if prefix else str(key)
            keys.append(path.lower())
            keys.extend(_walk_keys(value, path))
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            keys.extend(_walk_keys(value, f'{prefix}[{idx}]'))
    return keys


def main() -> int:
    if not REPORT_PATH.is_file():
        return _fail(f'missing report: {REPORT_PATH}')

    try:
        report = json.loads(REPORT_PATH.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        return _fail(f'invalid JSON: {exc}')

    if report.get('ok') is not True:
        return _fail('report ok != true')
    if report.get('shadow_mode') is not True:
        return _fail('shadow_mode must be true')

    for key in ('generated_at', 'market_mode', 'summary', 'top_watchlist', 'avoid', 'no_decision', 'disclaimer'):
        if key not in report:
            return _fail(f'missing key: {key}')

    all_keys = _walk_keys(report)
    for forbidden in FORBIDDEN_KEYS:
        if any(forbidden in key for key in all_keys):
            return _fail(f'forbidden trade field present: {forbidden}')

    for item in (report.get('top_watchlist') or [])[:5]:
        for req in ('ticker', 'score', 'reason', 'warnings'):
            if req not in item:
                return _fail(f'top_watchlist item missing {req}: {item.get("ticker")}')

    mode = str(report.get('market_mode') or '').upper()
    summary = report.get('summary') or {}
    if mode == 'RESEARCH_MODE' and int(summary.get('buy_candidates') or 0) != 0:
        return _fail('RESEARCH_MODE must have buy_candidates=0')

    disclaimer = str(report.get('disclaimer') or '').lower()
    if 'trade execution' not in disclaimer and 'not trade' not in disclaimer:
        return _fail('disclaimer must mention not trade execution')

    print('TOMORROW_WATCHLIST_VALIDATE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
