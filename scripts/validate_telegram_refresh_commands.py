#!/usr/bin/env python3
"""Validate Telegram refresh commands pack (Stage 46H)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'TELEGRAM_REFRESH_COMMANDS_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    api_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    if "'stage': '47D'" not in api_src:
        return _fail('build-info stage not 47D')

    safe_src = (PROJECT_ROOT / 'backend/config/local_safe_mode.py').read_text(encoding='utf-8')
    if 'AstraEdge 47D' not in safe_src:
        return _fail('local_safe_mode missing AstraEdge 47D')

    proc = subprocess.run([sys.executable, 'scripts/test_telegram_refresh_commands.py'], cwd=PROJECT_ROOT)
    if proc.returncode != 0:
        return _fail('test_telegram_refresh_commands.py failed')

    print('TELEGRAM_REFRESH_COMMANDS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
