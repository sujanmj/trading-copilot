#!/usr/bin/env python3
"""Validate Stage 50L intraday alert action labels."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'INTRADAY_ALERT_ACTION_LABEL_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    src = (PROJECT_ROOT / 'backend/telegram/response_format.py').read_text(encoding='utf-8')
    for needle in ('format_intraday_anomaly_alert', 'classify_intraday_action_label', 'INTRADAY_ACTION_LABELS'):
        if needle not in src:
            return _fail(f'response_format missing {needle}')
    proc = os.system(f'{sys.executable} scripts/test_intraday_alert_action_label.py')
    if proc != 0:
        return _fail('test_intraday_alert_action_label.py failed')
    print('INTRADAY_ALERT_ACTION_LABEL_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
