#!/usr/bin/env python3
"""
Compact CLI for per-tab AI Hub freshness report.

Usage:
  python scripts/inspect_aihub_tab_freshness.py
  python scripts/inspect_aihub_tab_freshness.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description='Inspect AI Hub per-tab freshness (read-only)')
    parser.add_argument('--json', action='store_true', help='Print full JSON payload')
    args = parser.parse_args()

    from backend.analytics.aihub_tab_freshness import get_aihub_tab_freshness_report

    report = get_aihub_tab_freshness_report()
    tabs = report.get('tabs') or {}

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    brain = tabs.get('brain') or {}
    print(f"[AIHUB_FRESHNESS] brain_package_age_hours={brain.get('package_age_hours')}")
    print(f"[AIHUB_FRESHNESS] brain_data_age_hours={brain.get('data_age_hours')}")
    print(f"[AIHUB_FRESHNESS] govt_age_hours={(tabs.get('govt') or {}).get('age_hours')}")
    print(f"[AIHUB_FRESHNESS] scan_age_hours={(tabs.get('scan') or {}).get('age_hours')}")
    print(f"[AIHUB_FRESHNESS] market_age_hours={(tabs.get('mkt') or {}).get('age_hours')}")
    print(f"[AIHUB_FRESHNESS] global_age_hours={(tabs.get('global') or {}).get('age_hours')}")
    print(f"[AIHUB_FRESHNESS] news_age_hours={(tabs.get('news') or {}).get('age_hours')}")
    print(f"[AIHUB_FRESHNESS] tv_age_hours={(tabs.get('tv') or {}).get('age_hours')}")
    print(f"[AIHUB_FRESHNESS] reddit_age_hours={(tabs.get('rdt') or {}).get('age_hours')}")
    print(f"[AIHUB_FRESHNESS] calib_age_hours={(tabs.get('calib') or {}).get('age_hours')}")
    print(f"[AIHUB_FRESHNESS] journal_age_hours={(tabs.get('journal') or {}).get('age_hours')}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
