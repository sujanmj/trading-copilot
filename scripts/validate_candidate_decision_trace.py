#!/usr/bin/env python3
"""Validate AstraEdge 52P candidate decision trace."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_candidate_decision_trace.py') != 0:
        print('ASTRAEDGE_PHASE_52P_CANDIDATE_DECISION_TRACE_FAIL', file=sys.stderr)
        return 1
    print('ASTRAEDGE_PHASE_52P_CANDIDATE_DECISION_TRACE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
