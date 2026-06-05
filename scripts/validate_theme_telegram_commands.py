#!/usr/bin/env python3
"""Validate theme Telegram commands pack (Stage 47A)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'THEME_TELEGRAM_COMMANDS_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    bot_src = (PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')
    if 'run_theme_only' not in bot_src:
        return _fail('telegram_analysis_bot missing run_theme_only wiring')
    if "elif cmd == 'theme':" not in bot_src:
        return _fail('telegram_analysis_bot missing /theme handler')

    lazy_src = (PROJECT_ROOT / 'backend/telegram/lazy_command_runner.py').read_text(encoding='utf-8')
    if 'def run_theme_only' not in lazy_src:
        return _fail('lazy_command_runner missing run_theme_only')

    proc = subprocess.run(
        [sys.executable, 'scripts/test_theme_telegram_commands.py'],
        cwd=PROJECT_ROOT,
    )
    if proc.returncode != 0:
        return _fail('test_theme_telegram_commands.py failed')

    print('THEME_TELEGRAM_COMMANDS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
