#!/usr/bin/env python3
"""
Validate Telegram Analysis Bot wiring (Stage 45TG5).

Prints TELEGRAM_ANALYSIS_BOT_OK on success.
Marker: TELEGRAM_STAGE_45TG5_OUTPUT_CLEAN_AIHUB_FULL
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

MARKER = 'TELEGRAM_STAGE_51A_CANONICAL_REFRESH_STATUS'
BLOCKED_RESPONSE = (
    "I can't place orders. Try /today, /tomorrow, /aihub scan, or /ask ai <question>."
)

REQUIRED_FILES = (
    'backend/telegram/lazy_command_runner.py',
    'backend/telegram/ai_usage_guard.py',
    'backend/telegram/telegram_brief_scheduler.py',
    'backend/telegram/telegram_analysis_bot.py',
    'backend/telegram/response_format.py',
    'scripts/run_telegram_analysis_bot.py',
    'scripts/send_telegram_morning_brief.py',
    'scripts/send_telegram_market_close_summary.py',
    'scripts/send_telegram_overnight_brief.py',
    'scripts/test_telegram_analysis_bot.py',
    'scripts/test_telegram_output_clean.py',
    'scripts/validate_telegram_output_clean.py',
)

ALLOWED_COMMANDS = (
    'start', 'help', 'status', 'memory', 'broker', 'aihub', 'news', 'qa',
    'ask', 'morning', 'close', 'today', 'tomorrow', 'why',
)

BLOCKED_COMMANDS = ('buy', 'sell', 'execute', 'place_order', 'trade', 'auto_trade')

LAZY_RUNNERS = (
    'run_news_only',
    'run_scan_only',
    'run_market_only',
    'run_global_only',
    'run_daily_pack_only',
    'run_memory_only',
    'run_broker_only',
    'run_qa_status_only',
    'run_aihub_full_only',
)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_ANALYSIS_BOT_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for rel in REQUIRED_FILES:
        if not (PROJECT_ROOT / rel).is_file():
            return _fail(f'missing file: {rel}')

    lazy_src = (PROJECT_ROOT / 'backend/telegram/lazy_command_runner.py').read_text(encoding='utf-8')
    guard_src = (PROJECT_ROOT / 'backend/telegram/ai_usage_guard.py').read_text(encoding='utf-8')
    sched_src = (PROJECT_ROOT / 'backend/telegram/telegram_brief_scheduler.py').read_text(encoding='utf-8')
    bot_src = (PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')
    fmt_src = (PROJECT_ROOT / 'backend/telegram/response_format.py').read_text(encoding='utf-8')
    runner_src = (PROJECT_ROOT / 'scripts/run_telegram_analysis_bot.py').read_text(encoding='utf-8')

    if MARKER not in lazy_src:
        return _fail(f'lazy_command_runner missing marker {MARKER}')
    for fn in LAZY_RUNNERS:
        if f'def {fn}(' not in lazy_src:
            return _fail(f'lazy_command_runner missing {fn}')

    forbidden = ('import run_local', 'run_local.main(', 'subprocess.run([')
    for src_label, src in (('lazy_command_runner', lazy_src), ('telegram_analysis_bot', bot_src)):
        for token in forbidden:
            if token in src:
                return _fail(f'must not invoke full local pipeline in {src_label}: found {token}')

    if 'TELEGRAM_ALLOW_AI_SUMMARY' not in guard_src:
        return _fail('ai_usage_guard missing TELEGRAM_ALLOW_AI_SUMMARY gate')
    if 'TELEGRAM_ALLOW_CLAUDE' not in guard_src:
        return _fail('ai_usage_guard missing TELEGRAM_ALLOW_CLAUDE gate')
    if 'telegram_ai_usage_log.jsonl' not in guard_src:
        return _fail('ai_usage_guard must log to telegram_ai_usage_log.jsonl')

    if '08:00' not in sched_src and '(8, 0)' not in sched_src:
        return _fail('brief scheduler missing 08:00 morning slot')
    if '(16, 30)' not in sched_src:
        return _fail('brief scheduler missing 16:30 close slot')
    if '(6, 30)' not in sched_src:
        return _fail('brief scheduler missing 06:30 overnight slot')

    if 'def strip_stage_markers(' not in fmt_src:
        return _fail('missing strip_stage_markers helper')
    if BLOCKED_RESPONSE not in fmt_src:
        return _fail('missing clean blocked trade response')
    if 'Trading: <b>manual by user</b>' in fmt_src:
        return _fail('status must not show manual trading by user')
    if 'build_stock_decision' not in fmt_src:
        return _fail('today/tomorrow must use stock decision engine')
    if 'format_why_ticker' not in fmt_src:
        return _fail('format_why_ticker missing')
    if 'Stock Decision Engine is pending' in fmt_src:
        return _fail('pending wording must be removed')

    for cmd in ALLOWED_COMMANDS:
        if f"cmd == '{cmd}'" not in bot_src and f"cmd in ('{cmd}'" not in bot_src:
            if cmd in ('start', 'help') and "('start', 'help'" in bot_src:
                continue
            if cmd == 'ask' and "('ask', 'q', 'question')" in bot_src:
                continue
            return _fail(f'allowed command handler missing: /{cmd}')

    if 'BLOCKED_TRADE_COMMANDS' not in bot_src:
        return _fail('bot must use BLOCKED_TRADE_COMMANDS set')
    from backend.telegram.response_format import BLOCKED_TRADE_COMMANDS as blocked_set

    for cmd in BLOCKED_COMMANDS:
        if cmd not in blocked_set:
            return _fail(f'blocked command missing from BLOCKED_TRADE_COMMANDS: /{cmd}')

    routing_checks = (
        ('run_news_only', 'news'),
        ('run_scan_only', 'scan'),
        ('run_memory_only', 'memory'),
        ('run_broker_only', 'broker'),
        ('run_qa_status_only', 'qa'),
        ('run_aihub_full_only', 'aihub full'),
        ('build_aihub_tab_payload', 'aihub'),
        ('guarded_ask_ai', 'ask'),
    )
    for token, label in routing_checks:
        if token not in bot_src and token not in lazy_src:
            return _fail(f'lazy/AI routing missing for {label}: {token}')

    if "tab in ('full', 'all')" not in bot_src:
        return _fail('/aihub full and /aihub all alias missing')

    if 'TELEGRAM_BRIEF_SCHEDULER' not in runner_src:
        return _fail('run_telegram_analysis_bot missing TELEGRAM_BRIEF_SCHEDULER')
    if 'trade_execution_disabled' not in runner_src.lower():
        return _fail('runner must confirm trade execution disabled')
    if 'TELEGRAM_BOT_TOKEN' in runner_src and 'print' in runner_src:
        if 'token=' in runner_src.lower() and 'credentials_present' in runner_src:
            pass
        elif 'BOT_TOKEN' in runner_src and runner_src.count('print') > 3:
            return _fail('runner may print secrets')

    for rel in (
        'scripts/send_telegram_morning_brief.py',
        'scripts/send_telegram_market_close_summary.py',
        'scripts/send_telegram_overnight_brief.py',
    ):
        src = (PROJECT_ROOT / rel).read_text(encoding='utf-8')
        if 'send_brief' not in src and 'build_' not in src:
            return _fail(f'manual brief script incomplete: {rel}')

    from backend.telegram.lazy_command_runner import STAGE_MARKER
    from backend.telegram.response_format import TRADE_EXECUTION_PERMANENTLY_DISABLED

    if STAGE_MARKER != MARKER:
        return _fail('STAGE_MARKER mismatch')
    if not TRADE_EXECUTION_PERMANENTLY_DISABLED:
        return _fail('TRADE_EXECUTION_PERMANENTLY_DISABLED must be True')

    print(MARKER)
    print('TELEGRAM_ANALYSIS_BOT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
