#!/usr/bin/env python3
"""
Unit checks for Stage 44 browser frontend mode.

Prints exactly FRONTEND_BROWSER_MODE_TEST_OK on success.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND = PROJECT_ROOT / 'frontend'
PACKAGE = FRONTEND / 'package.json'
INDEX = FRONTEND / 'index.html'

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'FRONTEND_BROWSER_MODE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not PACKAGE.is_file():
        return _fail('frontend/package.json missing')

    pkg = json.loads(PACKAGE.read_text(encoding='utf-8'))
    scripts = pkg.get('scripts') or {}

    if str(scripts.get('start') or '') != 'electron .':
        return _fail('electron start script missing')

    if 'web' not in scripts:
        return _fail('web script missing')

    if '5173' not in str(scripts.get('web') or ''):
        return _fail('web script must target port 5173')

    index_src = INDEX.read_text(encoding='utf-8')
    if '127.0.0.1:8080' not in index_src:
        return _fail('browser API base default missing')

    if 'GUI_RUNTIME.isElectron' not in index_src:
        return _fail('Electron API access must be guarded')

    if 'require(\'electron\')' in index_src and 'if (GUI_RUNTIME.isElectron)' not in index_src:
        return _fail('electron require must be guarded')

    if 'window.open' not in index_src:
        return _fail('browser open fallback missing')

    from scripts.live_system_smoke import _resolve_auto_frontend_mode, HttpResponse

    def _web_up(url: str, headers: dict[str, str], timeout: float = 5.0) -> HttpResponse:
        if url.rstrip('/').endswith('5173'):
            return HttpResponse(status=200, body='<html>ok</html>')
        return HttpResponse(status=404, body='')

    def _web_down(url: str, headers: dict[str, str], timeout: float = 5.0) -> HttpResponse:
        return HttpResponse(status=0, body='', error='connection refused')

    if _resolve_auto_frontend_mode(fetch=_web_up, frontend_base='http://127.0.0.1:5173') != 'web':
        return _fail('auto mode should choose web when port reachable')

    if _resolve_auto_frontend_mode(fetch=_web_down, frontend_base='http://127.0.0.1:5173') != 'electron':
        return _fail('auto mode should choose electron when web port down')

    print('FRONTEND_BROWSER_MODE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
