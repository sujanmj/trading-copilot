#!/usr/bin/env python3
"""Stage 50L — intraday anomaly alerts include action labels."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _fail(msg: str) -> int:
    print(f'INTRADAY_ALERT_ACTION_LABEL_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.telegram.response_format import (
        INTRADAY_ACTION_LABELS,
        classify_intraday_action_label,
        format_intraday_anomaly_alert,
    )

    ixigo = {
        'ticker': 'IXIGO',
        'change_percent': 4.8,
        'volume_ratio': 1.4,
        'direction': 'BULLISH',
        'reason': 'Scanner momentum with sector support',
    }
    label = classify_intraday_action_label(ixigo)
    if label not in INTRADAY_ACTION_LABELS:
        return _fail(f'label {label!r} not in allowed set')
    text = format_intraday_anomaly_alert(ixigo, confidence=0.72)
    for token in ('IXIGO', 'Move:', 'Volume/participation:', 'Confidence:', 'Action:', 'Reason:', 'Entry status:'):
        if token not in text:
            return _fail(f'missing {token} in alert text')
    if 'BUY' in text.split('Action:')[-1] or 'SELL' in text.split('Action:')[-1]:
        return _fail('alert must not contain naked BUY/SELL')

    missed = {'ticker': 'TBOTEK', 'change_percent': 10.2, 'volume_ratio': 1.1, 'direction': 'BULLISH'}
    if classify_intraday_action_label(missed) != 'ENTRY MISSED':
        return _fail('TBOTEK +10% should be ENTRY MISSED')

    print('INTRADAY_ALERT_ACTION_LABEL_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
