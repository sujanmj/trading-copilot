#!/usr/bin/env python3
"""
Validate Stage 44 browser frontend mode wiring.

Prints exactly FRONTEND_BROWSER_MODE_OK on success.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND = PROJECT_ROOT / 'frontend'
PACKAGE = FRONTEND / 'package.json'
INDEX = FRONTEND / 'index.html'
WORKSPACE = FRONTEND / 'components' / 'WorkspaceManager.js'
VITE_CONFIG = FRONTEND / 'vite.config.js'
API_SERVER = PROJECT_ROOT / 'backend' / 'api' / 'api_server.py'
LIVE_SMOKE = PROJECT_ROOT / 'scripts' / 'live_system_smoke.py'


def _fail(msg: str) -> int:
    print(f'FRONTEND_BROWSER_MODE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not FRONTEND.is_dir():
        return _fail('frontend/ directory missing')

    if not PACKAGE.is_file():
        return _fail('frontend/package.json missing')

    pkg = json.loads(PACKAGE.read_text(encoding='utf-8'))
    scripts = pkg.get('scripts') or {}
    dev_deps = pkg.get('devDependencies') or {}

    if str(scripts.get('start') or '') != 'electron .':
        return _fail('npm start must remain electron .')

    for name in ('web', 'dev:web', 'preview:web'):
        if name not in scripts:
            return _fail(f'package.json missing script: {name}')

    web_script = str(scripts.get('web') or '')
    if '5173' not in web_script or '127.0.0.1' not in web_script:
        return _fail('web script must serve 127.0.0.1:5173')

    if 'vite' not in dev_deps and 'vite' not in web_script:
        return _fail('vite must be listed in devDependencies or web script')

    if not VITE_CONFIG.is_file():
        return _fail('frontend/vite.config.js missing')

    vite_src = VITE_CONFIG.read_text(encoding='utf-8')
    if '5173' not in vite_src:
        return _fail('vite.config.js must configure port 5173')

    index_src = INDEX.read_text(encoding='utf-8')
    for token in (
        '__GUI_RUNTIME__',
        'WEB LOCAL',
        '127.0.0.1:8080',
        'GUI_RUNTIME.isElectron',
        'localStorage.getItem(\'API_BASE_URL\')',
        'applyGuiModeBadge',
    ):
        if token not in index_src:
            return _fail(f'index.html missing browser marker: {token!r}')

    workspace_src = WORKSPACE.read_text(encoding='utf-8')
    if 'isBrowserGui' not in workspace_src or "window.open(url, '_blank'" not in workspace_src:
        return _fail('WorkspaceManager.js missing browser window.open external behavior')

    api_src = API_SERVER.read_text(encoding='utf-8')
    for origin in (
        'http://127.0.0.1:5173',
        'http://localhost:5173',
        'http://127.0.0.1:4173',
        'http://localhost:4173',
    ):
        if origin not in api_src:
            return _fail(f'backend CORS missing local origin: {origin}')

    smoke_src = LIVE_SMOKE.read_text(encoding='utf-8')
    if '--frontend-mode' not in smoke_src or '5173' not in smoke_src:
        return _fail('live_system_smoke.py must support web mode on port 5173')

    print('FRONTEND_BROWSER_MODE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
