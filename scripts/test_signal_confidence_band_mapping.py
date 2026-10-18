#!/usr/bin/env python3
"""Regression tests for confidence labels used by outcome calibration."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analytics.signal_outcomes import _parse_confidence_band


def main() -> int:
    cases = {
        'Very low': (0.35, 'LOW'),
        ' low confidence ': (0.35, 'LOW'),
        'Weak': (0.35, 'LOW'),
        'Very high': (0.85, 'HIGH'),
        'Strong': (0.85, 'HIGH'),
        'Ultra': (0.85, 'HIGH'),
        'Moderate': (0.55, 'MEDIUM'),
    }
    for raw, expected in cases.items():
        actual = _parse_confidence_band(raw)
        if actual != expected:
            raise AssertionError(f'{raw!r}: expected {expected!r}, got {actual!r}')

    print('SIGNAL_CONFIDENCE_BAND_MAPPING_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
