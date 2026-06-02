#!/usr/bin/env python3
"""
Offline validator for Electron GUI smoke checks (Stage 42B).

Usage:
  python scripts/validate_electron_frontend_smoke.py

Prints ELECTRON_FRONTEND_SMOKE_OK when package.json, GUI markers, and
live_system_smoke --frontend-mode electron support are present.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'ELECTRON_FRONTEND_SMOKE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from scripts.live_system_smoke import (
        FRONTEND_MARKERS,
        _load_frontend_package,
        _scan_electron_source_corpus,
        run_live_system_smoke,
    )

    pkg, pkg_err = _load_frontend_package()
    if pkg_err:
        return _fail(pkg_err)

    start = str((pkg.get('scripts') or {}).get('start') or '')
    if 'electron' not in start.lower():
        return _fail('frontend/package.json start script does not contain electron')

    corpus = _scan_electron_source_corpus()
    missing = [marker for marker in FRONTEND_MARKERS if marker not in corpus]
    if missing:
        return _fail(f'missing GUI markers: {", ".join(missing)}')

    sig = inspect.signature(run_live_system_smoke)
    if 'frontend_mode' not in sig.parameters:
        return _fail('run_live_system_smoke missing frontend_mode parameter')

    source = Path(__file__).resolve().parent / 'live_system_smoke.py'
    text = source.read_text(encoding='utf-8')
    if '--frontend-mode' not in text or "'electron'" not in text:
        return _fail('live_system_smoke missing --frontend-mode electron support')

    print('ELECTRON_FRONTEND_SMOKE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
