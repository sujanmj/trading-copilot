#!/usr/bin/env python3
"""Validate /broker evidence command (Stage 48N)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    src = (PROJECT_ROOT / 'backend/analytics/broker_intelligence.py').read_text(encoding='utf-8')
    panel = (PROJECT_ROOT / 'frontend/components/BrokerIntelligencePanel.js').read_text(encoding='utf-8')
    if 'format_broker_evidence_telegram' not in src:
        print('BROKER_EVIDENCE_COMMAND_FAIL: missing format_broker_evidence_telegram', file=sys.stderr)
        return 1
    if os.system(f'{sys.executable} scripts/test_broker_evidence_command.py') != 0:
        return 1
    print('BROKER_EVIDENCE_COMMAND_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
