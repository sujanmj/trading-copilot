#!/usr/bin/env python3
"""
Inspect external source coverage from broker/app collector cache.

Prints [EXT_COVERAGE] lines and EXTERNAL_SOURCE_COVERAGE_OK.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'EXTERNAL_SOURCE_COVERAGE_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.collectors.broker_app_collector import get_external_source_coverage

    coverage = get_external_source_coverage()
    if coverage.get('ok') is not True:
        return _fail(coverage.get('error') or 'coverage unavailable')

    print(f"[EXT_COVERAGE] collected_items={coverage.get('collected_items', 0)}")
    print(f"[EXT_COVERAGE] normalized_items={coverage.get('normalized_items', 0)}")
    print(f"[EXT_COVERAGE] rejected_items={coverage.get('rejected_items', 0)}")
    print(f"[EXT_COVERAGE] source_count={coverage.get('source_count', 0)}")
    print(f"[EXT_COVERAGE] unique_tickers={coverage.get('unique_tickers', 0)}")
    print(f"[EXT_COVERAGE] broker_db_pick_count={coverage.get('broker_db_pick_count', 0)}")
    print(f"[EXT_COVERAGE] fake_predictions={coverage.get('fake_predictions', 0)}")
    print(f"[EXT_COVERAGE] latest_sources={coverage.get('latest_sources', [])}")
    warnings = coverage.get('warnings') or []
    print(f"[EXT_COVERAGE] warnings={warnings}")
    print('EXTERNAL_SOURCE_COVERAGE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
