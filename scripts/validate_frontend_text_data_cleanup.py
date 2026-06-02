#!/usr/bin/env python3
"""
Validate Stage 44AF — frontend text/data cleanup in index.html.

Prints exactly FRONTEND_TEXT_DATA_CLEANUP_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'

BROKER_DISCLAIMER = 'External broker/app evidence — not our final prediction.'
BRAND_FALLBACK_CSS = (
    'position: absolute !important',
    'width: 1px !important',
    'clip: rect(0, 0, 0, 0) !important',
)
FC_REPORT = '/api/debug/final-confidence/report'
FC_FALLBACK = 'data/final_confidence_report.json'
HL_SOURCE = '/api/debug/historical-learning'


def _fail(msg: str) -> int:
    print(f'FRONTEND_TEXT_DATA_CLEANUP_FAIL: {msg}', file=sys.stderr)
    return 1


def _section(src: str, start_marker: str, end_marker: str) -> str:
    start = src.find(start_marker)
    if start < 0:
        return ''
    end = src.find(end_marker, start)
    if end < 0:
        return src[start:]
    return src[start:end]


def main() -> int:
    if not INDEX.is_file():
        return _fail('frontend/index.html missing')

    src = INDEX.read_text(encoding='utf-8')

    if 'GUI_BUILD_STAGE_44AH_AIHUB_TAB_FALLBACKS' not in src:
        return _fail('GUI_BUILD_STAGE_44AH_AIHUB_TAB_FALLBACKS marker missing')

    if '44AH aihub tab fallbacks' not in src:
        return _fail('boot log must mention 44AH aihub tab fallbacks')

    brokers_panel = _section(src, 'id="brokersMainPanel"', 'id="routerMainPanel"')
    if not brokers_panel:
        return _fail('brokers workspace section missing')

    disclaimer_count = brokers_panel.count(BROKER_DISCLAIMER)
    if disclaimer_count > 0:
        return _fail(
            f'broker disclaimer must not be duplicated in brokers workspace HTML ({disclaimer_count} found)',
        )

    if 'bi-shadow-label' not in src or '.bi-shadow-label' not in src:
        return _fail('broker bi-shadow-label dedup patch missing')

    if 'querySelectorAll(\'.bi-shadow-label\')' not in src and 'querySelectorAll(".bi-shadow-label")' not in src:
        return _fail('broker shadow-label removal hook missing')

    brand_css = _section(src, '.brand-fallback {', '}')
    if not brand_css:
        return _fail('.brand-fallback CSS missing')
    for token in BRAND_FALLBACK_CSS:
        if token not in brand_css:
            return _fail(f'.brand-fallback missing accessible hidden rule: {token!r}')

    if 'alt=""' not in src or 'astraedge-logo-wide.png' not in src:
        return _fail('logo image must use empty alt to avoid duplicate visible brand text')

    if 'Market closed · data as-of' in src:
        return _fail('duplicate market closed/data-as-of badge render must be removed from index.html')

    stale_fn = _section(src, 'function staleBadgeHtml()', 'function pickSourceTimestamp')
    if not stale_fn or "return ''" not in stale_fn or 'marketClosed' not in stale_fn:
        return _fail('staleBadgeHtml must skip market-closed badge (handled by aiHubMarketChip)')

    chip_fn = _section(src, 'function updateAiHubMarketChip()', 'function patchTextDataCleanup44AF')
    if not chip_fn:
        return _fail('updateAiHubMarketChip missing')
    if 'data as-of' not in chip_fn or 'Age' not in chip_fn:
        return _fail('aiHubMarketChip must combine market status, data-as-of, and age')

    patch_fn = _section(src, 'function patchTextDataCleanup44AF()', 'function patchFreshnessRouterOnly')
    if not patch_fn:
        return _fail('patchTextDataCleanup44AF missing')

    if FC_REPORT not in patch_fn:
        return _fail(f'final confidence loader must use {FC_REPORT!r}')
    if FC_FALLBACK not in patch_fn:
        return _fail(f'final confidence fallback must reference {FC_FALLBACK!r}')
    if 'generate_final_confidence_report.py' not in patch_fn:
        return _fail('final confidence failure message must mention generate_final_confidence_report.py')

    if HL_SOURCE not in patch_fn:
        return _fail(f'historical learning loader must reference {HL_SOURCE!r}')
    if 'Historical learning unavailable — backend endpoint not reachable' not in patch_fn:
        return _fail('historical learning unavailable compact card message missing')

    if 'patchFreshnessRouterOnly' not in src:
        return _fail('patchFreshnessRouterOnly guard missing')

    if 'id="routerFreshnessHost"' not in src:
        return _fail('router freshness host missing')

    if 'class="header-grid"' not in src or 'class="brand-block"' not in src:
        return _fail('header redesign detected — header-grid/brand-block layout required')

    if re.search(r'<div class="topbar">', src):
        return _fail('header redesign detected — legacy topbar must not return')

    print('FRONTEND_TEXT_DATA_CLEANUP_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
