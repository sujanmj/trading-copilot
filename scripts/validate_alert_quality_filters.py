#!/usr/bin/env python3
"""Validate alert quality filters pack (Stage 46H)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'ALERT_QUALITY_FILTERS_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    root = PROJECT_ROOT
    for rel in (
        'backend/orchestration/alert_quality_filters.py',
        'backend/orchestration/intraday_alert_state.py',
    ):
        if not (root / rel).is_file():
            return _fail(f'missing {rel}')

    filt = (root / 'backend/orchestration/alert_quality_filters.py').read_text(encoding='utf-8')
    for log in ('EMERGENCY_MACRO_SENT', 'EMERGENCY_MACRO_DEDUPED', 'EMERGENCY_MACRO_SKIPPED'):
        if log not in filt:
            return _fail(f'missing log {log}')

    intra = (root / 'backend/orchestration/intraday_alert_state.py').read_text(encoding='utf-8')
    if 'INTRADAY_ALERT_SUPPRESSED' not in intra:
        return _fail('missing INTRADAY_ALERT_SUPPRESSED log')
    if 'last_intraday_alert_state.json' not in intra:
        return _fail('missing state file reference')

    import subprocess
    proc = subprocess.run([sys.executable, 'scripts/test_alert_quality_filters.py'], cwd=root)
    if proc.returncode != 0:
        return _fail('test_alert_quality_filters.py failed')

    print('ALERT_QUALITY_FILTERS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
