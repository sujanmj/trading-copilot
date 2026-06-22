#!/usr/bin/env python3
"""Validate Stage 50Z RESEARCH_MODE /close stale-pack suppression."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

TEST_MARKER = 'RESEARCH_MODE_CLOSE_SUPPRESSES_STALE_PACK_TEST_OK'
MARKER = 'RESEARCH_MODE_CLOSE_SUPPRESSES_STALE_PACK_OK'


def _fail(msg: str) -> int:
    print(f'RESEARCH_MODE_CLOSE_SUPPRESSES_STALE_PACK_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = (PROJECT_ROOT / 'backend/telegram/telegram_brief_scheduler.py').read_text(encoding='utf-8')
    for token in (
        '_build_research_mode_close_brief_text',
        'Research-mode summary',
        'Report cache stale',
        'Audit-only',
        'NEXT-SESSION WATCH ONLY',
    ):
        if token not in src:
            return _fail(f'telegram_brief_scheduler.py missing {token}')

    proc = subprocess.run(
        [sys.executable, 'scripts/test_research_mode_close_suppresses_stale_pack.py'],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = (proc.stdout or '') + (proc.stderr or '')
    if proc.returncode != 0:
        return _fail(f'test failed rc={proc.returncode}: {output[-800:]}')
    if TEST_MARKER not in output:
        return _fail('test marker missing')

    print(MARKER)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
