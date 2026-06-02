#!/usr/bin/env python3
"""
Validate emergency GUI fix in the active frontend file (frontend/index.html).

Prints exactly ACTIVE_FRONTEND_GUI_FIX_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ACTIVE_INDEX = PROJECT_ROOT / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'ACTIVE_FRONTEND_GUI_FIX_FAIL: {msg}', file=sys.stderr)
    return 1


def _section(src: str, start_marker: str, end_marker: str) -> str:
    start = src.find(start_marker)
    end = src.find(end_marker, start)
    if start < 0 or end < 0:
        return ''
    return src[start:end]


def _button_classes(block: str, btn_id: str) -> str:
    pattern = re.compile(
        rf'<button[^>]*id="{re.escape(btn_id)}"[^>]*class="([^"]+)"',
        re.IGNORECASE,
    )
    match = pattern.search(block)
    if match:
        return match.group(1)
    pattern2 = re.compile(
        rf'<button[^>]*class="([^"]+)"[^>]*id="{re.escape(btn_id)}"',
        re.IGNORECASE,
    )
    match2 = pattern2.search(block)
    return match2.group(1) if match2 else ''


def _function_body(src: str, name: str) -> str:
    match = re.search(rf'function {re.escape(name)}\([^)]*\)\s*\{{', src)
    if not match:
        return ''
    start = match.end()
    depth = 1
    i = start
    while i < len(src) and depth:
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
        i += 1
    return src[start:i - 1]


def main() -> int:
    if not ACTIVE_INDEX.is_file():
        return _fail('frontend/index.html missing')

    src = ACTIVE_INDEX.read_text(encoding='utf-8')

    if 'GUI_BUILD_STAGE_44P_HEADER_AND_FRESHNESS_FIXED' not in src:
        return _fail('GUI_BUILD_STAGE_44P_HEADER_AND_FRESHNESS_FIXED marker missing')

    header_end_idx = src.find('</header>')
    header_start_idx = src.find('<header class="app-header"')
    if header_start_idx < 0 or header_end_idx < 0:
        return _fail('app-header block missing')
    header = src[header_start_idx:header_end_idx]

    ai_hub_pos = src.find('id="aiHubWorkspace"')
    header_end = src.find('</header>')
    main_pos = src.find('<div class="main"', header_end)
    if ai_hub_pos < 0 or header_end < 0 or main_pos < 0:
        return _fail('header / main / AI Hub structure missing')

    if not (header_end < main_pos < ai_hub_pos):
        return _fail('header block must exist before AI Hub container')

    if '⚡ AstraEdge AI' not in header:
        return _fail('AstraEdge AI header missing')

    if 'header-row-main' not in header:
        return _fail('row 1 main nav missing')

    if 'header-row-brokers' not in header or 'BROKERS:' not in header:
        return _fail('row 2 BROKERS label missing')

    if 'header-row-news' not in header or 'NEWS:' not in header:
        return _fail('row 3 NEWS label missing')

    broker_row = _section(header, 'id="brokerSourceRow"', 'id="newsSourceRow"')
    news_row = _section(header, 'id="newsSourceRow"', '')
    if news_row == '' and 'id="newsSourceRow"' in header:
        news_row = header[header.find('id="newsSourceRow"'):]
    if not broker_row or not news_row:
        return _fail('broker/news source rows missing')

    ai_hub_block = _section(src, 'id="aiHubWorkspace"', '</div>')
    if 'BROKERS:' in ai_hub_block or 'id="brokerSourceRow"' in ai_hub_block:
        return _fail('BROKERS row must be outside AI Hub container')
    if 'NEWS:' in ai_hub_block or 'id="newsSourceRow"' in ai_hub_block:
        return _fail('NEWS row must be outside AI Hub container')

    router_block = _section(src, 'id="routerMainPanel"', 'id="aiHubWorkspace"')
    if 'id="routerFreshnessHost"' not in router_block:
        return _fail('Router workspace must contain routerFreshnessHost for Intelligence Freshness')

    if 'Intelligence Freshness' not in router_block and "mount('#routerFreshnessHost')" not in src:
        return _fail('Intelligence Freshness wiring missing in Router section')

    ai_scroll = _section(src, 'id="aiHubScroll"', 'id="tab-brain"')
    if not ai_scroll:
        ai_scroll = _section(src, 'class="ai-hub-scroll"', 'id="tab-brain"')
    if 'Intelligence Freshness' in ai_scroll:
        return _fail('Intelligence Freshness must not appear in AI Hub scroll area')
    if 'source-freshness-card' in ai_scroll:
        return _fail('source-freshness-card must not appear in AI Hub scroll area')
    if 'aiHubFreshnessHost' in ai_scroll:
        return _fail('aiHubFreshnessHost must not remain in AI Hub scroll area')

    tab_section = _section(src, 'id="tab-brain"', 'id="tab-govt"')
    if 'Intelligence Freshness' in tab_section or 'source-freshness-card' in tab_section:
        return _fail('Intelligence Freshness must not appear in AI Hub tab template')

    forbidden = (
        'sourcesToggleBtn', 'sourcesBar', 'sources-bar', 'Sources</button>',
        'brokers-menu', 'news-menu', 'astra-drop', 'BROKERS ▼', 'NEWS ▼',
        'activeDropdown', 'toggleSourcesBar', 'setSourcesBarOpen',
    )
    for token in forbidden:
        if token in src:
            return _fail(f'removed UI artifact still present: {token!r}')

    for label in ('Angel', 'Zerodha', 'Groww', 'Upstox', 'IndMoney', '💼 Portfolio'):
        if label not in broker_row:
            return _fail(f'broker row missing: {label!r}')

    for label in ('MC', 'ET', 'Mint', 'NDTV', '📱 Inshorts', '🤖 Reddit', 'ET Now', 'CNBC', 'NSE'):
        if label not in news_row:
            return _fail(f'news row missing: {label!r}')

    main_row = _section(header, 'header-row-main', 'header-row-brokers')
    mem = _button_classes(main_row, 'memoryNavBtn')
    brokers = _button_classes(main_row, 'brokersNavBtn')
    ai = _button_classes(main_row, 'aiHubNavBtn')
    if 'primary-nav-btn' not in mem or mem != brokers or mem != ai:
        return _fail('Memory, Brokers, AI Hub must share primary-nav-btn class')

    mem_pos = main_row.find('memoryNavBtn')
    brokers_pos = main_row.find('brokersNavBtn')
    ai_pos = main_row.find('aiHubNavBtn')
    router_pos = main_row.find('routerNavBtn')
    if not (mem_pos < brokers_pos < ai_pos < router_pos):
        return _fail('nav order must be Memory, Brokers, AI Hub, Router')

    bind_body = _function_body(src, 'bindAstraSourceItemClick')
    if 'renderSourceFeed' not in bind_body:
        return _fail('source click handler must call renderSourceFeed')
    if 'window.open' in bind_body:
        return _fail('source click handler must not directly window.open')

    if 'Open External' not in src:
        return _fail('Open External button missing')

    if 'Back to Dashboard' not in src:
        return _fail('Back to Dashboard missing')

    if '#browserToolbar { display: none !important; }' not in src:
        return _fail('external browser toolbar must be hidden')

    if 'clearPersistedSourceLanding' not in src:
        return _fail('must clear persisted source landing on load')

    if '/api/debug/source-feed' not in src:
        return _fail('must fetch internal source feed API')

    if 'No cached items for this source yet. Use Open External.' not in src:
        return _fail('empty state message missing')

    if 'id="aiHubMarketChip"' not in src:
        return _fail('AI Hub compact market chip missing')

    if 'header-body-boundary' not in src:
        return _fail('header/content boundary separator missing')

    print('ACTIVE_FRONTEND_GUI_FIX_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
