#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    rc = subprocess.call([sys.executable, str(PROJECT_ROOT / 'scripts/test_aihub_stale_metadata_clean_labels.py')])
    if rc != 0:
        return rc
    print('AIHUB_STALE_METADATA_CLEAN_LABELS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
