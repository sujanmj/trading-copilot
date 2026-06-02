#!/usr/bin/env python3
"""
Validate /action plan and /aihub brain full wiring (Stage 45B4).

Prints TELEGRAM_ACTION_PLAN_OK on success.
Marker: TELEGRAM_STAGE_45B4_DATA_ACCURACY_ACTION_PLAN
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

MARKER = 'TELEGRAM_STAGE_45B4_DATA_ACCURACY_ACTION_PLAN'


def _fail(msg: str) -> int:
    print(f'TELEGRAM_ACTION_PLAN_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    bot_src = (PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')
    fmt_src = (PROJECT_ROOT / 'backend/telegram/response_format.py').read_text(encoding='utf-8')
    lazy_src = (PROJECT_ROOT / 'backend/telegram/lazy_command_runner.py').read_text(encoding='utf-8')

    if MARKER not in fmt_src and MARKER not in lazy_src:
        return _fail(f'missing stage marker {MARKER}')

    if 'run_action_plan_only' not in lazy_src:
        return _fail('lazy_command_runner missing run_action_plan_only')
    if 'run_aihub_brain_full_only' not in lazy_src:
        return _fail('lazy_command_runner missing run_aihub_brain_full_only')

    if 'format_action_plan_telegram' not in fmt_src:
        return _fail('response_format missing format_action_plan_telegram')
    if 'format_aihub_brain_full' not in fmt_src:
        return _fail('response_format missing format_aihub_brain_full')

    if 'build_stock_decision' not in fmt_src:
        return _fail('formatters must use stock_decision_engine')
    if 'build_brain_payload' not in fmt_src:
        return _fail('formatters must use AI Hub brain payload')

    if "cmd == 'action' and (args or '').strip().lower() == 'plan'" not in bot_src:
        return _fail('/action plan handler missing')
    if "tab == 'brain full'" not in bot_src:
        return _fail('/aihub brain full handler missing')

    if "elif cmd == 'action'" in bot_src.replace(
        "elif cmd == 'action' and (args or '').strip().lower() == 'plan'", ''
    ):
        return _fail('/action alias must not exist as standalone handler')

    forbidden_aliases = (
        "cmd == 'action_plan'",
        "cmd in ('action',",
        "'/action\\n'",
        '/brain full',
    )
    for token in forbidden_aliases:
        if token in bot_src and token != "cmd == 'action' and (args or '').strip().lower() == 'plan'":
            if token == "cmd in ('action',":
                if "cmd in ('action'," in bot_src:
                    return _fail('/action alias must not be registered')
            elif token in bot_src:
                return _fail(f'forbidden alias pattern: {token}')

    if '/action plan' not in bot_src:
        return _fail('help must include /action plan')
    if '/aihub brain full' not in bot_src:
        return _fail('help must include /aihub brain full')

    help_block = bot_src.split('HELP_TEXT = """', 1)[-1].split('"""', 1)[0]
    if '/action\n' in help_block or help_block.strip().endswith('/action'):
        return _fail('help must not list bare /action')
    if '/action_plan' in help_block:
        return _fail('help must not list /action_plan')
    if '/brain full' in help_block and '/aihub brain full' not in help_block:
        return _fail('help must not list /brain full alias')

    if 'guarded_ask_ai' in fmt_src:
        return _fail('action plan formatters must not call LLM by default')

    from backend.telegram.response_format import (
        ACTION_PLAN_STAGE_MARKER,
        format_action_plan_telegram,
        format_aihub_brain_full,
        strip_stage_markers,
    )

    if ACTION_PLAN_STAGE_MARKER != MARKER:
        return _fail('ACTION_PLAN_STAGE_MARKER mismatch')

    plan_text = strip_stage_markers(format_action_plan_telegram())
    brain_text = strip_stage_markers(format_aihub_brain_full())
    for label, text in (('action plan', plan_text), ('brain full', brain_text)):
        if MARKER in text or 'TELEGRAM_STAGE' in text:
            return _fail(f'{label} output must not expose stage markers')

    test_path = PROJECT_ROOT / 'scripts/test_telegram_action_plan.py'
    if not test_path.is_file():
        return _fail('missing scripts/test_telegram_action_plan.py')

    print(MARKER)
    print('TELEGRAM_ACTION_PLAN_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
