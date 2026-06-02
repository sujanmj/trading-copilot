#!/usr/bin/env python3
"""
Validate final confidence report includes external evidence integration.

Usage:
  python scripts/generate_final_confidence_report.py
  python scripts/validate_final_confidence_external_evidence.py

Prints exactly FINAL_CONFIDENCE_EXTERNAL_EVIDENCE_OK on success.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = PROJECT_ROOT / 'data' / 'final_confidence_report.json'

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'FINAL_CONFIDENCE_EXTERNAL_EVIDENCE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.external_evidence_adapter import EXTERNAL_EVIDENCE_CAP
    from backend.analytics.final_confidence_fusion import build_final_confidence_report

    report = build_final_confidence_report(limit=25)
    if report.get('ok') is not True:
        return _fail('build_final_confidence_report failed')

    rows = report.get('rows') or []
    if not rows:
        return _fail('report has no rows')

    has_external = False
    for row in rows:
        if 'external_evidence' in row or 'external_evidence_adjustment' in row:
            has_external = True
            adj = int(row.get('external_evidence_adjustment') or 0)
            if abs(adj) > EXTERNAL_EVIDENCE_CAP:
                return _fail(f'row {row.get("ticker")} external adj {adj} exceeds cap')

    if not has_external:
        return _fail('no row contains external_evidence fields')

    if REPORT_PATH.is_file():
        disk = json.loads(REPORT_PATH.read_text(encoding='utf-8'))
        disk_rows = disk.get('rows') or []
        if disk_rows and 'external_evidence' not in disk_rows[0]:
            return _fail('final_confidence_report.json missing external_evidence on disk row')

    active_mode = str(report.get('active_mode') or '')
    if active_mode == 'RESEARCH_MODE' and int(report.get('summary', {}).get('buy_candidate') or 0) > 0:
        return _fail('RESEARCH_MODE report must not expose buy_candidate > 0')

    print('FINAL_CONFIDENCE_EXTERNAL_EVIDENCE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
