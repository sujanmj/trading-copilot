#!/usr/bin/env python3
"""Validate scanner scope terminal-status regression coverage."""

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

TEST_MARKER = 'REFRESH_SCANNER_SCOPE_PRINTS_TERMINAL_STATUS_TEST_OK'
MARKER = 'REFRESH_SCANNER_SCOPE_PRINTS_TERMINAL_STATUS_OK'


def _fail(msg: str) -> int:
    safe_print(f'REFRESH_SCANNER_SCOPE_PRINTS_TERMINAL_STATUS_FAIL: {msg}', fallback='stderr')
    return 1


def main() -> int:
    src = (PROJECT_ROOT / 'scripts/refresh_local_intelligence.py').read_text(encoding='utf-8')
    for token in (
        'SAFE_SMOKE_SCANNER_STATUS',
        '_scanner_safe_smoke_enabled',
        "safe_print(f\"[REFRESH_LOCAL] scanner={scope_results['scanner']}\")",
    ):
        if token not in src:
            return _fail(f'refresh_local_intelligence.py missing {token}')

    env = os.environ.copy()
    env.setdefault('PYTHONIOENCODING', 'utf-8')
    proc = subprocess.run(
        [sys.executable, 'scripts/test_refresh_scanner_scope_prints_terminal_status.py'],
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
