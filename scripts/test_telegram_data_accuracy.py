#!/usr/bin/env python3
"""
Dry-run checks for Telegram data mapping accuracy (Stage 45B2).

Prints TELEGRAM_DATA_ACCURACY_TEST_OK on success.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_LISTENER', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')
os.environ.setdefault('TELEGRAM_ALLOW_CLAUDE', '0')
os.environ.setdefault('TELEGRAM_TRADE_COMMANDS_ENABLED', '0')
os.environ.setdefault('DISABLE_TRADE_EXECUTION', '1')


def _fail(msg: str) -> int:
    print(f'TELEGRAM_DATA_ACCURACY_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.lazy_command_runner import (
        run_aihub_full_only,
        run_broker_only,
        run_memory_only,
    )
    from backend.telegram.response_format import format_status_text, strip_stage_markers
    from backend.telegram.telegram_analysis_bot import handle_analysis_command

    memory = run_memory_only()
    memory_text = strip_stage_markers(str(memory.get('text') or ''))
    if 'Win rate: 0.3%' in memory_text or 'Win rate: 0.33%' in memory_text:
        return _fail('/memory win rate must be percent not decimal')
    if 'Outcomes resolved: 0' in memory_text:
        if 'Pending resolution:' not in memory_text and 'Predictions tracked:' not in memory_text:
            return _fail('/memory unresolved block missing prediction/pending counts')
    elif 'Calibration warming up' in memory_text:
        if 'do not trust yet' not in memory_text.lower():
            return _fail('/memory warmup must caution against trusting hit rate')
        if 'Resolved outcomes:' not in memory_text or 'Pending outcomes:' not in memory_text:
            return _fail('/memory warmup missing resolved/pending counts')
    else:
        if not re.search(r'(Hit rate|Win rate): [\d.—]+%', memory_text):
            return _fail('/memory missing percent hit/win rate')
        if 'Resolved outcomes:' not in memory_text or 'Pending outcomes:' not in memory_text:
            return _fail('/memory ready sample missing resolved/pending counts')
    if 'Latest outcomes:' not in memory_text:
        return _fail('/memory missing latest outcomes section')
    if '—' in memory_text and 'TEXRAIL' not in memory_text and 'LOSS' not in memory_text:
        if 'No recent outcomes' not in memory_text:
            pass
    if re.search(r'• [A-Z0-9]+ — (WIN|LOSS)', memory_text):
        if not re.search(r'— [+-]?\d+\.\d+%', memory_text):
            return _fail('/memory outcome lines missing move percent')

    if re.search(r'cache age: \d{4,}m', memory_text):
        return _fail('/memory cache age must not show huge minute values')

    broker = run_broker_only(refresh=False)
    broker_text = strip_stage_markers(str(broker.get('text') or ''))
    stats = (broker.get('payload') or {}).get('stats') or {}
    picks = int(stats.get('picks_tracked') or stats.get('broker_predictions') or 0)
    if picks > 0 and 'No broker picks in cache' in broker_text:
        return _fail('/broker must not claim empty cache when picks exist')
    if picks > 0 and '•' not in broker_text.split('candidates')[-1]:
        if 'External evidence candidates' not in broker_text:
            return _fail('/broker missing candidate rows when picks tracked')

    status = strip_stage_markers(format_status_text())
    if 'Mode:' not in status or 'Telegram:' not in status:
        return _fail('/status missing mode or telegram line')
    if 'Market mode:' not in status or 'Report:' not in status:
        return _fail('/status missing market mode or latest report from daily pack')

    full = run_aihub_full_only()
    full_text = strip_stage_markers(str(full.get('text') or ''))
    if 'top risk: —' in full_text.lower() or 'top risk: -' in full_text:
        return _fail('/aihub full must not show empty top risk')

    results = handle_analysis_command('/memory', 'test_user', dry_run=True)
    if not results:
        return _fail('bot /memory returned no response')
    bot_memory = strip_stage_markers(str(results[0].get('text') or ''))
    if (
        'Win rate:' not in bot_memory
        and 'Hit rate:' not in bot_memory
        and 'Outcomes resolved: 0' not in bot_memory
    ):
        return _fail('bot /memory missing win/hit rate or unresolved block')

    print('TELEGRAM_DATA_ACCURACY_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
