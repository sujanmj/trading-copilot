#!/usr/bin/env python3
"""
Generate stock confluence decision JSON + markdown reports (Stage 45B).

Usage:
  python scripts/generate_stock_decision.py --mode today
  python scripts/generate_stock_decision.py --mode tomorrow

Prints STOCK_DECISION_GENERATE_OK on success.
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

DATA_DIR = PROJECT_ROOT / 'data'
REPORTS_DIR = PROJECT_ROOT / 'reports'


def _fail(msg: str) -> int:
    print(f'STOCK_DECISION_GENERATE_FAIL: {msg}', file=sys.stderr)
    return 1


def _render_markdown(payload: dict) -> str:
    lines = [
        f"# Stock decision — {payload.get('mode', 'today')}",
        '',
        f"Generated: {payload.get('generated_at', '—')}",
        f"Decision: **{payload.get('decision', '—')}**",
        '',
    ]
    top = payload.get('top_pick')
    if isinstance(top, dict):
        lines.extend([
            '## Top pick',
            '',
            f"- Ticker: **{top.get('ticker')}**",
            f"- Action: {top.get('action')}",
            f"- Score: {top.get('score')}",
            f"- Confidence: {top.get('confidence')}",
            '',
            '### Why',
        ])
        for item in top.get('why') or []:
            lines.append(f'- {item}')
        lines.extend(['', '### Wait for'])
        for item in top.get('confirmation_needed') or []:
            lines.append(f'- {item}')
        if top.get('risk'):
            lines.extend(['', '### Risk'])
            for item in top.get('risk') or []:
                lines.append(f'- {item}')
    else:
        lines.extend(['## Top pick', '', 'No clean candidate.'])

    avoid = payload.get('avoid') or []
    if avoid:
        lines.extend(['', '## Avoid'])
        for row in avoid[:8]:
            if isinstance(row, dict):
                lines.append(f"- {row.get('ticker')} ({row.get('action')}) — score {row.get('score')}")

    lines.extend(['', '---', payload.get('disclaimer') or ''])
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate stock confluence decision reports.')
    parser.add_argument('--mode', choices=('today', 'tomorrow'), default='today')
    args = parser.parse_args()

    from backend.analytics.stock_decision_engine import build_stock_decision

    payload = build_stock_decision(mode=args.mode)
    if payload.get('ok') is not True:
        return _fail(payload.get('error') or payload.get('message') or 'build failed')

    json_path = DATA_DIR / f'stock_decision_{args.mode}.json'
    md_path = REPORTS_DIR / f'stock_decision_{args.mode}.md'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)

    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding='utf-8')
    md_path.write_text(_render_markdown(payload), encoding='utf-8')

    summary = payload.get('summary') or {}
    print(f'[STOCK_DECISION] mode={args.mode} decision={payload.get("decision")}')
    print(f'[STOCK_DECISION] wrote={json_path}')
    print(f'[STOCK_DECISION] wrote={md_path}')
    print(
        f"[STOCK_DECISION] universe={summary.get('universe_size', 0)} "
        f"buy={summary.get('buy_candidate', 0)} watch={summary.get('watch_for_entry', 0)} "
        f"avoid={summary.get('avoid', 0)}"
    )
    top = payload.get('top_pick') or {}
    if top:
        print(f"[STOCK_DECISION] top_pick={top.get('ticker')} action={top.get('action')} score={top.get('score')}")
    print('STOCK_DECISION_GENERATE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
