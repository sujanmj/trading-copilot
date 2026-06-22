#!/usr/bin/env python3
"""Validate closed-stdio safety for scanner refresh."""

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

TEST_MARKER = 'REFRESH_SCANNER_CLOSED_STDERR_SAFE_TEST_OK'
MARKER = 'REFRESH_SCANNER_CLOSED_STDERR_SAFE_OK'


def _fail(msg: str) -> int:
    safe_print(f'REFRESH_SCANNER_CLOSED_STDERR_SAFE_FAIL: {msg}', fallback='stderr')
    return 1


def main() -> int:
    refresh_src = (PROJECT_ROOT / 'scripts/refresh_local_intelligence.py').read_text(encoding='utf-8')
    scanner_src = (PROJECT_ROOT / 'backend/analyzers/stock_scanner.py').read_text(encoding='utf-8')
    helper_src = (PROJECT_ROOT / 'backend/utils/safe_stdio.py').read_text(encoding='utf-8')

    for token in ('safe_output_sink', 'ensure_safe_standard_streams', 'safe_print'):
        if token not in refresh_src:
            return _fail(f'refresh_local_intelligence.py missing {token}')
    for token in ('progress=False', 'threads=not in_smoke_local_ci_mode()', 'safe_stream'):
        if token not in scanner_src:
            return _fail(f'stock_scanner.py missing {token}')
    for token in ('sys.__stderr__', 'sys.__stdout__', 'os.devnull', 'TQDM_DISABLE'):
        if token not in helper_src:
            return _fail(f'safe_stdio.py missing {token}')

    env = os.environ.copy()
    env.setdefault('LOCAL_DEV_MODE', '1')
    env.setdefault('LOCAL_ONLY', '1')
    env.setdefault('PYTHONIOENCODING', 'utf-8')
    proc = subprocess.run(
        [sys.executable, 'scripts/test_refresh_scanner_closed_stderr_safe.py'],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = (proc.stdout or '') + (proc.stderr or '')
    if proc.returncode != 0:
        return _fail(f'test failed rc={proc.returncode}: {output[-500:]}')
    if TEST_MARKER not in output:
        return _fail('test marker missing')

    safe_print(MARKER)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
