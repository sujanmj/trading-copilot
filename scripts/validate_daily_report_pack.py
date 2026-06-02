#!/usr/bin/env python3
"""
Validate daily report pack files.

Prints exactly DAILY_REPORT_PACK_VALIDATE_OK on success.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

LATEST = PROJECT_ROOT / 'data' / 'daily_report_pack_latest.json'
HISTORY = PROJECT_ROOT / 'data' / 'daily_report_pack_history.jsonl'

FORBIDDEN = frozenset({
    'trade_execution',
    'execute_trade',
    'order_placed',
    'telegram_sent',
})


def _fail(msg: str) -> int:
    print(f'DAILY_REPORT_PACK_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not LATEST.is_file():
        return _fail(f'missing latest pack: {LATEST}')

    report = json.loads(LATEST.read_text(encoding='utf-8'))
    if report.get('ok') is not True:
        return _fail('latest ok != true')
    if report.get('shadow_mode') is not True:
        return _fail('shadow_mode must be true')

    blob = json.dumps(report).lower()
    for token in FORBIDDEN:
        if token in blob:
            return _fail(f'forbidden field token: {token}')

    for key in (
        'final_confidence',
        'tomorrow_watchlist',
        'historical_simulation',
        'confidence_calibration',
        'files',
        'disclaimer',
    ):
        if key not in report:
            return _fail(f'missing section: {key}')

    from backend.analytics.daily_report_pack import pack_contains_secrets

    if pack_contains_secrets(report):
        return _fail('possible secret-like content in pack')

    if not HISTORY.is_file():
        return _fail(f'missing history file: {HISTORY}')

    lines = [line for line in HISTORY.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not lines:
        return _fail('history jsonl is empty')

    try:
        last = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        return _fail(f'history jsonl invalid: {exc}')

    if last.get('generated_at') != report.get('generated_at'):
        return _fail('history tail does not match latest generated_at')

    print('DAILY_REPORT_PACK_VALIDATE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
