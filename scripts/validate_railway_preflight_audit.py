#!/usr/bin/env python3
"""
Validate railway_preflight_audit.py wiring (Stage 45B4).

Prints RAILWAY_PREFLIGHT_VALIDATE_OK on success.
Marker: RAILWAY_STAGE_45B4_PREFLIGHT_READY
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

MARKER = 'RAILWAY_STAGE_45B4_PREFLIGHT_READY'


def _fail(msg: str) -> int:
    print(f'RAILWAY_PREFLIGHT_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    audit_path = PROJECT_ROOT / 'scripts' / 'railway_preflight_audit.py'
    if not audit_path.is_file():
        return _fail('missing scripts/railway_preflight_audit.py')

    src = audit_path.read_text(encoding='utf-8')
    required = (
        MARKER,
        'RAILWAY_PREFLIGHT_AUDIT_OK',
        'run_railway_preflight_audit',
        'Procfile',
        'railway.json',
        'lazy_command_runner',
        'TRADE_EXECUTION_PERMANENTLY_DISABLED',
        '/api/health',
        'config/keys.env',
    )
    for token in required:
        if token not in src:
            return _fail(f'railway_preflight_audit missing token: {token}')

    proc = subprocess.run(
        [sys.executable, str(audit_path), '--continue-on-fail'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = (proc.stdout or '') + (proc.stderr or '')
    if proc.returncode != 0:
        tail = combined.strip().splitlines()[-1] if combined.strip() else f'exit {proc.returncode}'
        return _fail(f'audit script failed: {tail}')
    if MARKER not in combined:
        return _fail(f'audit output missing marker {MARKER}')
    if 'RAILWAY_PREFLIGHT_AUDIT_OK' not in combined:
        return _fail('audit output missing RAILWAY_PREFLIGHT_AUDIT_OK')

    print(MARKER)
    print('RAILWAY_PREFLIGHT_VALIDATE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
