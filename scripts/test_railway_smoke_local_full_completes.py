#!/usr/bin/env python3
"""Regression test: full railway_smoke_local completes scanner scope and exits OK."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

from backend.utils.safe_stdio import safe_print  # noqa: E402

MARKER = 'RAILWAY_SMOKE_LOCAL_FULL_COMPLETES_TEST_OK'


def _fail(msg: str) -> int:
    safe_print(f'RAILWAY_SMOKE_LOCAL_FULL_COMPLETES_TEST_FAIL: {msg}', fallback='stderr')
    return 1


def main() -> int:
    env = os.environ.copy()
    env.update({
        'RAILWAY_SMOKE_LOCAL': '1',
        'REFRESH_SCANNER_SAFE_SMOKE': '1',
        'SAFE_STDIO_FORCE_FD': '1',
        'LOCAL_DEV_MODE': '1',
        'LOCAL_ONLY': '1',
        'DISABLE_TRADE_EXECUTION': '1',
        'TELEGRAM_TRADE_COMMANDS_ENABLED': '0',
        'DISABLE_TELEGRAM': '1',
        'DISABLE_TELEGRAM_LISTENER': '1',
        'DISABLE_TELEGRAM_SENDS': '1',
        'PYTHONIOENCODING': 'utf-8',
    })
    proc = subprocess.run(
        [sys.executable, 'scripts/railway_smoke_local.py'],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    output = (proc.stdout or '') + (proc.stderr or '')
    if proc.returncode != 0:
        return _fail(f'railway_smoke_local rc={proc.returncode}: {output[-800:]}')

    required = (
        '[REFRESH_LOCAL] scope=scanner started',
        '[REFRESH_LOCAL] done',
        '[RAILWAY_SMOKE] scanner_refresh=ok',
        'RAILWAY_SMOKE_LOCAL_OK',
    )
    for token in required:
        if token not in output:
            return _fail(f'missing output token: {token!r}; output tail={output[-1200:]}')
    if '[REFRESH_LOCAL] scanner=ok' not in output and '[REFRESH_LOCAL] scanner=skipped_safe_smoke' not in output:
        return _fail(f'missing scanner terminal status; output tail={output[-1200:]}')
    if output.index('[REFRESH_LOCAL] scope=scanner started') > output.index('[REFRESH_LOCAL] done'):
        return _fail('refresh done printed before scanner start')
    if output.rfind('RAILWAY_SMOKE_LOCAL_OK') < output.rfind('[RAILWAY_SMOKE] stock_decision_engine=ok'):
        return _fail('OK marker printed before final core check')

    safe_print(MARKER)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
