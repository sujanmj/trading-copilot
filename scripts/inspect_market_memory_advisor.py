#!/usr/bin/env python3
"""
Inspect shadow learning advisor output for a prediction candidate.

Usage:
  python scripts/inspect_market_memory_advisor.py --ticker TEXRAIL --signal-type "ULTRA scanner" --confidence-label HIGH --horizon intraday
  python scripts/inspect_market_memory_advisor.py --ticker RELIANCE --json
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


def _format_rate(value: object) -> str:
    if value is None:
        return 'N/A'
    try:
        return f'{float(value) * 100:.2f}%'
    except (TypeError, ValueError):
        return 'N/A'


def _print_advice(payload: dict) -> None:
    ticker = payload.get('ticker') or 'N/A'
    print(f'[ADVISOR] ticker={ticker}')
    print(f"[ADVISOR] overall_advice={payload.get('overall_advice')}")
    print(f"[ADVISOR] learning_score={payload.get('learning_score')}")
    print(f"[ADVISOR] sample_size={payload.get('sample_size')}")

    warnings = payload.get('warnings') or []
    if warnings:
        print(f"[ADVISOR] warnings={','.join(warnings)}")

    reasons = payload.get('reasons') or []
    if reasons:
        print('[ADVISOR] reasons:')
        for reason in reasons:
            print(f'  - {reason}')

    components = payload.get('components') or {}
    if components:
        print('[ADVISOR] components:')
        for name, component in components.items():
            print(
                f"  {name}: advice={component.get('advice')} "
                f"score={component.get('learning_score')} "
                f"sample={component.get('sample_size')} "
                f"win_rate={_format_rate(component.get('win_rate'))}"
            )
            comp_warnings = component.get('warnings') or []
            if comp_warnings:
                print(f"    warnings={','.join(comp_warnings)}")

    print(f"[ADVISOR] shadow_mode={payload.get('shadow_mode')}")


def main() -> int:
    parser = argparse.ArgumentParser(description='Inspect market memory shadow advisor.')
    parser.add_argument('--ticker', required=True, help='Ticker symbol')
    parser.add_argument('--signal-type', default=None, help='Signal type label')
    parser.add_argument('--confidence-label', default=None, help='Confidence label')
    parser.add_argument('--horizon', default=None, help='Prediction horizon')
    parser.add_argument('--broker-consensus', default=None, help='Broker consensus agreement direction')
    parser.add_argument('--json', action='store_true', help='Print JSON output')
    args = parser.parse_args()

    from backend.analytics.market_memory_advisor import advise_prediction

    candidate: dict = {'ticker': args.ticker}
    if args.signal_type:
        candidate['signal_type'] = args.signal_type
    if args.confidence_label:
        candidate['confidence_label'] = args.confidence_label
    if args.horizon:
        candidate['prediction_horizon'] = args.horizon
    if args.broker_consensus:
        candidate['broker_consensus'] = {'agreement_direction': args.broker_consensus}

    payload = advise_prediction(candidate)

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return 0

    _print_advice(payload)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
