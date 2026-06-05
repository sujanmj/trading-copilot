#!/usr/bin/env python3
"""Validate Railway post-deploy smoke stage comparator pack (Stage 47B)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'RAILWAY_SMOKE_STAGE_COMPARE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    smoke_src = (PROJECT_ROOT / 'scripts/railway_post_deploy_smoke.py').read_text(encoding='utf-8')
    for fragment in (
        '_parse_build_stage',
        '_stage_at_least',
        '_stage_at_least_46e',
    ):
        if fragment not in smoke_src:
            return _fail(f'railway_post_deploy_smoke.py missing: {fragment}')

    proc = subprocess.run(
        [sys.executable, 'scripts/test_railway_smoke_stage_compare.py'],
        cwd=PROJECT_ROOT,
    )
    if proc.returncode != 0:
        return _fail('test_railway_smoke_stage_compare.py failed')

    print('RAILWAY_SMOKE_STAGE_COMPARE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
