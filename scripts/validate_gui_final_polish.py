#!/usr/bin/env python3
"""
Validate Stage 21 GUI final polish: compact empty states, compact banners,
price recovery wiring, and refresh prices full/no-shrink mode.

Prints exactly GUI_FINAL_POLISH_OK on success.
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

INDEX_HTML = PROJECT_ROOT / 'frontend' / 'index.html'
RUNTIME_JS = PROJECT_ROOT / 'frontend' / 'runtime' / 'runtimeManager.js'
REFRESH_SCRIPT = PROJECT_ROOT / 'scripts' / 'refresh_local_intelligence.py'
RECOVERY_SCRIPT = PROJECT_ROOT / 'scripts' / 'recover_price_coverage.py'


def _fail(msg: str) -> int:
    print(f'GUI_FINAL_POLISH_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    if not INDEX_HTML.is_file():
        return _fail('frontend/index.html missing')
    if not RUNTIME_JS.is_file():
        return _fail('frontend/runtime/runtimeManager.js missing')
    if not REFRESH_SCRIPT.is_file():
        return _fail('scripts/refresh_local_intelligence.py missing')
    if not RECOVERY_SCRIPT.is_file():
        return _fail('scripts/recover_price_coverage.py missing')

    index_src = INDEX_HTML.read_text(encoding='utf-8')
    refresh_src = REFRESH_SCRIPT.read_text(encoding='utf-8')
    recovery_src = RECOVERY_SCRIPT.read_text(encoding='utf-8')

    required_index = (
        'compactEmptyStateHtml',
        'No TV intelligence yet',
        'Use Refresh to run TV collector',
        'Source missing or collector not completed',
        'empty-state-panel compact',
        'dedupePanelBanners',
    )
    for token in required_index:
        if token not in index_src:
            return _fail(f'index.html missing token: {token}')

    if "padding: 4px 8px" not in index_src and "padding:4px 8px" not in index_src:
        return _fail('compact panel-status-banner padding not found')

    if index_src.count('live collectors active') > 2:
        return _fail('duplicate hardcoded live collectors active in index.html')

    refresh_required = (
        'run_enrichment',
        '_count_enriched_symbols',
        'coverage_below_previous_peak',
    )
    for token in refresh_required:
        if token not in refresh_src:
            return _fail(f'refresh_local_intelligence.py missing token: {token}')

    if "'--limit', '50'" in refresh_src or '"--limit", "50"' in refresh_src:
        return _fail('refresh_local_intelligence.py still hardcodes --limit 50')

    recovery_required = (
        '[PRICE_RECOVERY] before_symbols=',
        '[PRICE_RECOVERY] after_symbols=',
        '[PRICE_RECOVERY] fake_prices=',
        'PRICE_COVERAGE_RECOVERY_OK',
        'limit=None',
    )
    for token in recovery_required:
        if token not in recovery_src:
            return _fail(f'recover_price_coverage.py missing token: {token}')

    print('GUI_FINAL_POLISH_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
