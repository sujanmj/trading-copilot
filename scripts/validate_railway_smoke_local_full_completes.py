#!/usr/bin/env python3
"""Validate full railway_smoke_local scanner-scope completion."""

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

TEST_MARKER = 'RAILWAY_SMOKE_LOCAL_FULL_COMPLETES_TEST_OK'
MARKER = 'RAILWAY_SMOKE_LOCAL_FULL_COMPLETES_OK'


def _fail(msg: str) -> int:
    safe_print(f'RAILWAY_SMOKE_LOCAL_FULL_COMPLETES_FAIL: {msg}', fallback='stderr')
    return 1


def main() -> int:
    smoke_src = (PROJECT_ROOT / 'scripts/railway_smoke_local.py').read_text(encoding='utf-8')
    helper_src = (PROJECT_ROOT / 'backend/utils/safe_stdio.py').read_text(encoding='utf-8')
    for token in (
        'REFRESH_SCANNER_SAFE_SMOKE',
        'SAFE_STDIO_FORCE_FD',
        '_check_scanner_refresh',
        'scanner_refresh=warning',
        'scanner_refresh=ok',
    ):
        if token not in smoke_src:
            return _fail(f'railway_smoke_local.py missing {token}')
    for token in ('_FdTextStream', 'SAFE_STDIO_FORCE_FD'):
        if token not in helper_src:
            return _fail(f'safe_stdio.py missing {token}')

    env = os.environ.copy()
    env.setdefault('PYTHONIOENCODING', 'utf-8')
    proc = subprocess.run(
        [sys.executable, 'scripts/test_railway_smoke_local_full_completes.py'],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = (proc.stdout or '') + (proc.stderr or '')
    if proc.returncode != 0:
        return _fail(f'test failed rc={proc.returncode}: {output[-800:]}')
    if TEST_MARKER not in output:
        return _fail('test marker missing')

    safe_print(MARKER)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
