#!/usr/bin/env python3
"""Validate stale AIHub cache labels (Stage 48J)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TELEGRAM_STALE_AIHUB_LABELS_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    fmt = (PROJECT_ROOT / 'backend/telegram/response_format.py').read_text(encoding='utf-8')
    for needle in (
        '_aihub_payload_is_stale',
        '_stale_aihub_prefix_lines',
        'Research cache · stale',
        '_global_item_display_label',
        'Global/Noise',
    ):
        if needle not in fmt:
            return _fail(f'response_format missing {needle!r}')
    if os.system(f'{sys.executable} scripts/test_telegram_stale_aihub_labels.py') != 0:
        return _fail('test_telegram_stale_aihub_labels.py failed')
    print('TELEGRAM_STALE_AIHUB_LABELS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
