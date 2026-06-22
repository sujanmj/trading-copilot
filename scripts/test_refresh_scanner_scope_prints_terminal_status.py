#!/usr/bin/env python3
"""Regression test: scanner scope always prints a terminal status line."""

from __future__ import annotations

import contextlib
import io
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

from backend.utils.safe_stdio import safe_print  # noqa: E402

MARKER = 'REFRESH_SCANNER_SCOPE_PRINTS_TERMINAL_STATUS_TEST_OK'


def _fail(msg: str) -> int:
    safe_print(f'REFRESH_SCANNER_SCOPE_PRINTS_TERMINAL_STATUS_TEST_FAIL: {msg}', fallback='stderr')
    return 1


def main() -> int:
    from scripts.refresh_local_intelligence import SAFE_SMOKE_SCANNER_STATUS, run_refresh_scoped

    previous = os.environ.get('REFRESH_SCANNER_SAFE_SMOKE')
    os.environ['REFRESH_SCANNER_SAFE_SMOKE'] = '1'
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            result = run_refresh_scoped('scanner', dry_run=False)
    finally:
        if previous is None:
            os.environ.pop('REFRESH_SCANNER_SAFE_SMOKE', None)
        else:
            os.environ['REFRESH_SCANNER_SAFE_SMOKE'] = previous

    output = buf.getvalue()
    required = (
        '[REFRESH_LOCAL] scope=scanner started',
        f'[REFRESH_LOCAL] scanner={SAFE_SMOKE_SCANNER_STATUS}',
        '[REFRESH_LOCAL] done',
    )
    for token in required:
        if token not in output:
            return _fail(f'missing output token: {token!r}; output={output!r}')
    if output.index(required[0]) > output.index(required[1]):
        return _fail('scanner terminal status printed before start')
    if output.index(required[1]) > output.index(required[2]):
        return _fail('done printed before scanner terminal status')
    if not isinstance(result, dict) or result.get('ok') is not True:
        return _fail(f'unexpected result: {result!r}')
    if result.get('scanner') != SAFE_SMOKE_SCANNER_STATUS:
        return _fail(f'unexpected scanner status: {result!r}')

    safe_print(MARKER)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
