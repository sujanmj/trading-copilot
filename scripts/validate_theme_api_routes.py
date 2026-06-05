#!/usr/bin/env python3
"""Validate theme API routes pack (Stage 47A)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'THEME_API_ROUTES_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    api_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    for route in (
        '/api/theme-baskets',
        '/api/theme-baskets/{theme_id}',
        '/api/theme-baskets/{theme_id}/news',
        '/api/theme-baskets/{theme_id}/scan',
        '/api/theme-baskets/{theme_id}/add',
        '/api/theme-baskets/{theme_id}/remove',
        '/api/theme-baskets/refresh',
    ):
        if route not in api_src:
            return _fail(f'missing route {route}')

    if "'stage': '47A'" not in api_src:
        return _fail('build-info stage not 47A')

    proc = subprocess.run(
        [sys.executable, 'scripts/test_theme_api_routes.py'],
        cwd=PROJECT_ROOT,
    )
    if proc.returncode != 0:
        return _fail('test_theme_api_routes.py failed')

    print('THEME_API_ROUTES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
