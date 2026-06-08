#!/usr/bin/env python3
"""Validate frontend API JSON guard + backend JSON 404 (Stage 47F)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'FRONTEND_API_JSON_GUARD_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_frontend_api_json_guard.py') != 0:
        return _fail('test_frontend_api_json_guard.py failed')
    print('FRONTEND_API_JSON_GUARD_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
