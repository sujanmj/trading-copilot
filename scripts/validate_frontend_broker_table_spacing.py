#!/usr/bin/env python3
"""
Validate Stage 44F broker evidence table spacing and label mapping.

Prints exactly FRONTEND_BROKER_TABLE_SPACING_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'
PANEL = PROJECT_ROOT / 'frontend' / 'components' / 'BrokerIntelligencePanel.js'


def _fail(msg: str) -> int:
    print(f'FRONTEND_BROKER_TABLE_SPACING_FAIL: {msg}', file=sys.stderr)
    return 1


def _css_block(src: str, selector: str) -> str:
    match = re.search(rf'{re.escape(selector)}\s*\{{([^}}]*)\}}', src)
    return match.group(1) if match else ''


def main() -> int:
    for path in (INDEX, PANEL):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    index_src = INDEX.read_text(encoding='utf-8')
    panel_src = PANEL.read_text(encoding='utf-8')

    ticker_css = _css_block(index_src, '.bi-evidence-table .bi-col-ticker')
    direction_css = _css_block(index_src, '.bi-evidence-table .bi-col-direction')
    class_css = _css_block(index_src, '.bi-evidence-table .bi-col-class')

    if 'min-width: 110px' not in ticker_css:
        return _fail('.bi-col-ticker must have min-width 110px')
    if 'min-width: 100px' not in direction_css:
        return _fail('.bi-col-direction must have min-width 100px')
    if 'text-align: center' not in direction_css:
        return _fail('.bi-col-direction must center badge')
    if 'min-width: 150px' not in class_css:
        return _fail('.bi-col-class must have min-width 150px')

    if 'bi-direction-badge' not in index_src:
        return _fail('direction badge styling missing')

    label_map = {
        'broker_prediction_candidate': 'Broker candidate',
        'stock_news_evidence': 'Stock news',
        'market_context': 'Market context',
        'macro_context': 'Macro context',
    }
    for raw, readable in label_map.items():
        if raw not in panel_src or readable not in panel_src:
            return _fail(f'missing class label mapping: {raw!r} -> {readable!r}')

    if 'formatClassLabel' not in panel_src:
        return _fail('BrokerIntelligencePanel must use formatClassLabel')

    if 'title="${titleEsc}"' not in panel_src and 'title=\"${titleEsc}\"' not in panel_src:
        return _fail('title column must set title attribute for truncate tooltip')

    if 'bi-evidence-table' not in panel_src or 'bi-col-ticker' not in panel_src:
        return _fail('BrokerIntelligencePanel must render bi-evidence-table columns')

    print('FRONTEND_BROKER_TABLE_SPACING_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
