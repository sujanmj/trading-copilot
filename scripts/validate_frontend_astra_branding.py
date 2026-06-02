#!/usr/bin/env python3
"""
Deprecated — use validate_frontend_astraedge_branding.py (Stage 44F).

Delegates to the AstraEdge AI branding validator for backward compatibility.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent / 'validate_frontend_astraedge_branding.py'


def main() -> int:
    if not TARGET.is_file():
        print('FRONTEND_ASTRA_BRANDING_FAIL: validate_frontend_astraedge_branding.py missing', file=sys.stderr)
        return 1
    completed = subprocess.run([sys.executable, str(TARGET)], check=False)
    return int(completed.returncode)


if __name__ == '__main__':
    raise SystemExit(main())
