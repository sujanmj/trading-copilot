#!/usr/bin/env python3
"""Validate broker GUI evidence sections (Stage 48O)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.system(f'{sys.executable} scripts/test_broker_gui_evidence_sections.py') != 0:
        return 1
    if os.system(f'{sys.executable} scripts/validate_broker_gui_neutral_section.py') != 0:
        return 1
    print('BROKER_GUI_EVIDENCE_SECTIONS_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
