#!/usr/bin/env python3
"""Unit tests for frontend API JSON guard + backend JSON 404 (Stage 47F)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'FRONTEND_API_JSON_GUARD_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    api_target = (PROJECT_ROOT / 'frontend/src/lib/apiTarget.js').read_text(encoding='utf-8')
    api_auth = (PROJECT_ROOT / 'frontend/src/lib/apiAuth.js').read_text(encoding='utf-8')
    index_html = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    api_server = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')

    checks = [
        (api_target, ('parseApiJsonResponse', 'fetchApiJson', 'API returned HTML/non-JSON')),
        (api_auth, ('parseApiJsonResponse',)),
        (index_html, ('astraParseJsonResponse', 'astraFetchJson', 'API returned HTML/non-JSON')),
        (PROJECT_ROOT / 'frontend/components/BrokerIntelligencePanel.js', (
            'API returned HTML/non-JSON',
            'Broker cache request timed out',
            'cache_only=1&lite=1',
        )),
        (PROJECT_ROOT / 'frontend/components/MarketRouterCard.js', ('API returned HTML/non-JSON',)),
        (PROJECT_ROOT / 'frontend/components/SourceFreshnessCard.js', ('API returned HTML/non-JSON',)),
    ]
    for path, needles in checks:
        text = path if isinstance(path, str) else path.read_text(encoding='utf-8')
        if isinstance(path, Path):
            name = path.name
        else:
            name = 'apiTarget.js'
        for needle in needles:
            if needle not in text:
                return _fail(f'{name} missing {needle!r}')

    for needle in ("'stage': '48E'", 'api_not_found', 'JSONResponse'):
        if needle not in api_server:
            return _fail(f'api_server.py missing {needle!r}')

    for rel in (
        '/api/debug/source-freshness',
        '/api/debug/market-router',
        '/api/budget/overview',
        '/api/brokers/overview',
        '/api/brokers/status',
        '/api/brokers/refresh',
    ):
        if rel not in api_server:
            return _fail(f'api_server.py missing route {rel!r}')

    budget_panel = PROJECT_ROOT / 'frontend/components/BudgetImpactPanel.js'
    if not budget_panel.is_file():
        return _fail('missing BudgetImpactPanel.js')
    budget_text = budget_panel.read_text(encoding='utf-8')
    if 'Budget API returned non-JSON' not in budget_text:
        return _fail('BudgetImpactPanel.js missing non-JSON guard')

    print('FRONTEND_API_JSON_GUARD_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
