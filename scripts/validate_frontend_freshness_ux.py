#!/usr/bin/env python3
"""
Validate Stage 43C AI Hub / Memory freshness UX.

Prints exactly FRONTEND_FRESHNESS_UX_OK on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
CARD = PROJECT_ROOT / 'frontend' / 'components' / 'SourceFreshnessCard.js'
WORKSPACE = PROJECT_ROOT / 'frontend' / 'components' / 'WorkspaceManager.js'
SOURCE_FRESHNESS = PROJECT_ROOT / 'backend' / 'analytics' / 'source_freshness.py'


def _fail(msg: str) -> int:
    print(f'FRONTEND_FRESHNESS_UX_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    for path in (INDEX, CARD, WORKSPACE, SOURCE_FRESHNESS):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    index_src = INDEX.read_text(encoding='utf-8')
    card_src = CARD.read_text(encoding='utf-8')
    workspace_src = WORKSPACE.read_text(encoding='utf-8')
    backend_src = SOURCE_FRESHNESS.read_text(encoding='utf-8')

    index_tokens = (
        'aiHubFreshnessHost',
        'ai-freshness-strip',
        'sf-closed',
        'sf-helper',
    )
    for token in index_tokens:
        if token not in index_src:
            return _fail(f'index.html missing token: {token!r}')

    card_tokens = (
        'Refresh Intelligence',
        'Price data',
        'AI package',
        'Runtime snapshot',
        'External evidence',
        'closed-market',
        'Refresh intelligence before next-session planning.',
        'Updates news/global/external evidence and recalculates watchlist. Does not place trades.',
        'refresh_closed_market_intelligence.py',
        'data-sf-scope="intelligence"',
        'ai-freshness-strip',
    )
    for token in card_tokens:
        if token not in card_src:
            return _fail(f'SourceFreshnessCard.js missing token: {token!r}')

    if 'Refresh All' in card_src:
        return _fail('SourceFreshnessCard must rename Refresh All → Refresh Intelligence')

    if 'aiHubFreshnessHost' not in workspace_src:
        return _fail('WorkspaceManager must mount freshness in AI Hub')

    backend_tokens = (
        'ai_package',
        'external_evidence',
        'refresh_intelligence_before_next_session',
        '_ai_package_freshness',
        '_external_evidence_freshness',
    )
    for token in backend_tokens:
        if token not in backend_src:
            return _fail(f'source_freshness.py missing token: {token!r}')

    print('FRONTEND_FRESHNESS_UX_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
