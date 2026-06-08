#!/usr/bin/env python3
"""Validate Budget Impact Intelligence engine pack (Stage 48A)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'BUDGET_IMPACT_ENGINE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    engine = PROJECT_ROOT / 'backend/analytics/budget_impact.py'
    if not engine.is_file():
        return _fail('missing budget_impact.py')
    src = engine.read_text(encoding='utf-8')
    for needle in ('STAGE = \'48C\'', 'get_budget_overview', 'analyze_news_text', 'handle_budget_command'):
        if needle not in src:
            return _fail(f'budget_impact.py missing {needle!r}')

    proc = subprocess.run([sys.executable, 'scripts/test_budget_impact_engine.py'], cwd=PROJECT_ROOT)
    if proc.returncode != 0:
        return _fail('test_budget_impact_engine.py failed')
    print('BUDGET_IMPACT_ENGINE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
