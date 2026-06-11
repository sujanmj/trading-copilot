#!/usr/bin/env python3
"""Stage 50H — GUI/API non-JSON handling uses Railway API base message."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MSG = 'API JSON unavailable — endpoint returned HTML. Check API base/path.'


def _fail(msg: str) -> int:
    print(f'GUI_API_NON_JSON_HANDLING_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    index = (PROJECT_ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    sf = (PROJECT_ROOT / 'frontend/components/SourceFreshnessCard.js').read_text(encoding='utf-8')
    mr = (PROJECT_ROOT / 'frontend/components/MarketRouterCard.js').read_text(encoding='utf-8')

    for name, text in (('index.html', index), ('SourceFreshnessCard.js', sf), ('MarketRouterCard.js', mr)):
        if MSG not in text:
            return _fail(f'{name} missing non-JSON guard message')

    if 'function astraApiBase' not in index or 'function astraFetchJson' not in index:
        return _fail('index.html missing astraApiBase/astraFetchJson')
    if 'astraParseJsonResponse' not in index:
        return _fail('index.html missing astraParseJsonResponse')
    if 'patchFreshnessRouterOnly' not in index:
        return _fail('index.html missing patchFreshnessRouterOnly')
    if index.count('async function astraFetchJson') != 1:
        return _fail('index.html must define astraFetchJson exactly once')

    if 'getApiBase: () => API_BASE' not in index:
        return _fail('Freshness/Router cards must init with API_BASE')

    api_server = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    if 'JSONResponse' not in api_server or 'api_not_found' not in api_server:
        return _fail('api_server must return JSON for API routes')

    print('GUI_API_NON_JSON_HANDLING_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
