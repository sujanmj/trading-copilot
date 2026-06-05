#!/usr/bin/env python3
"""Validate theme catalyst relevance filter pack (Stage 47B)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'THEME_RELEVANCE_FILTER_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    tb_src = (PROJECT_ROOT / 'backend/analytics/theme_baskets.py').read_text(encoding='utf-8')
    for fragment in (
        'is_theme_catalyst_relevant',
        'SKIP_KEYWORDS',
        'THEME_ANCHORS',
        'NO_CATALYST_MESSAGE',
        'hide_from_top3',
        '_filter_relevant_catalysts',
    ):
        if fragment not in tb_src:
            return _fail(f'theme_baskets.py missing: {fragment}')

    proc = subprocess.run(
        [sys.executable, 'scripts/test_theme_relevance_filter.py'],
        cwd=PROJECT_ROOT,
    )
    if proc.returncode != 0:
        return _fail('test_theme_relevance_filter.py failed')

    print('THEME_RELEVANCE_FILTER_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
