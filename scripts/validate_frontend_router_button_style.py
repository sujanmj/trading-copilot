#!/usr/bin/env python3
"""
Validate Stage 43C Router nav button matches REVIEW/OPS sizing.

Prints exactly FRONTEND_ROUTER_BUTTON_STYLE_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'FRONTEND_ROUTER_BUTTON_STYLE_FAIL: {msg}', file=sys.stderr)
    return 1


def _rule_block(src: str, selector: str) -> str:
    pattern = re.compile(rf'\.{re.escape(selector)}\s*\{{([^}}]+)\}}', re.DOTALL)
    match = pattern.search(src)
    return match.group(1) if match else ''


def _extract(rule: str, prop: str) -> str | None:
    match = re.search(rf'{re.escape(prop)}\s*:\s*([^;]+);', rule)
    return match.group(1).strip() if match else None


def main() -> int:
    if not INDEX.is_file():
        return _fail('frontend/index.html missing')

    src = INDEX.read_text(encoding='utf-8')
    router_rule = _rule_block(src, 'router-nav-btn')
    review_rule = _rule_block(src, 'ai-review-btn')
    ops_rule = _rule_block(src, 'ai-ops-btn')

    if not router_rule:
        return _fail('.router-nav-btn rule missing')
    if not review_rule or not ops_rule:
        return _fail('REVIEW/OPS button rules missing')

    for prop in ('font-size', 'padding', 'border-radius', 'font-weight'):
        router_val = _extract(router_rule, prop)
        review_val = _extract(review_rule, prop)
        ops_val = _extract(ops_rule, prop)
        if router_val != review_val or router_val != ops_val:
            return _fail(
                f'router-nav-btn {prop}={router_val!r} must match '
                f'REVIEW={review_val!r} OPS={ops_val!r}'
            )

    if 'font-size: 12px' in router_rule:
        return _fail('router button still uses 12px font (must match REVIEW/OPS 9px)')

    if 'padding: 4px 10px' in router_rule:
        return _fail('router button still uses old padding (must match 3px 8px)')

    if '🌍 Router' not in src or 'routerNavBtn' not in src:
        return _fail('Router nav button markup missing')

    print('FRONTEND_ROUTER_BUTTON_STYLE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
