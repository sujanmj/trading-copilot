#!/usr/bin/env python3
"""
Validate India/USA market holiday JSON files.

Usage:
  python scripts/validate_market_holiday_files.py

Prints exactly MARKET_HOLIDAY_FILES_OK on success; exits 1 on failure.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / 'data'

FILES = (
    DATA_DIR / 'market_holidays_india.json',
    DATA_DIR / 'market_holidays_usa.json',
)

VALID_TYPES = frozenset({'full_day', 'early_close', 'special_session'})


def _fail(msg: str) -> int:
    print(f'MARKET_HOLIDAY_FILES_FAIL: {msg}', file=sys.stderr)
    return 1


def _validate_file(path: Path, current_year: int) -> str | None:
    if not path.is_file():
        return f'missing file: {path.relative_to(PROJECT_ROOT)}'

    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        return f'{path.name}: invalid JSON: {exc}'

    if not isinstance(raw, dict):
        return f'{path.name}: root must be an object'

    for key in ('market', 'year', 'timezone', 'holidays'):
        if key not in raw:
            return f'{path.name}: missing required key {key!r}'

    file_year = raw.get('year')
    if file_year != current_year:
        return f'{path.name}: year {file_year!r} != current year {current_year}'

    holidays = raw.get('holidays')
    if not isinstance(holidays, list):
        return f'{path.name}: holidays must be a list'

    seen_dates: set[str] = set()
    for idx, item in enumerate(holidays):
        if not isinstance(item, dict):
            return f'{path.name}: holidays[{idx}] must be an object'
        day_text = str(item.get('date') or '').strip()
        if not day_text:
            return f'{path.name}: holidays[{idx}] missing date'
        try:
            date.fromisoformat(day_text)
        except ValueError:
            return f'{path.name}: holidays[{idx}] invalid date {day_text!r}'
        if day_text in seen_dates:
            return f'{path.name}: duplicate holiday date {day_text}'
        seen_dates.add(day_text)
        htype = str(item.get('type') or 'full_day')
        if htype not in VALID_TYPES:
            return f'{path.name}: holidays[{idx}] invalid type {htype!r}'

    for section in ('early_closes', 'special_sessions'):
        entries = raw.get(section) or []
        if not isinstance(entries, list):
            return f'{path.name}: {section} must be a list'
        for idx, item in enumerate(entries):
            if not isinstance(item, dict):
                return f'{path.name}: {section}[{idx}] must be an object'
            day_text = str(item.get('date') or '').strip()
            if not day_text:
                return f'{path.name}: {section}[{idx}] missing date'
            try:
                date.fromisoformat(day_text)
            except ValueError:
                return f'{path.name}: {section}[{idx}] invalid date {day_text!r}'
            htype = str(item.get('type') or section.rstrip('s'))
            if htype not in VALID_TYPES:
                return f'{path.name}: {section}[{idx}] invalid type {htype!r}'

    return None


def main() -> int:
    current_year = date.today().year
    for path in FILES:
        err = _validate_file(path, current_year)
        if err:
            return _fail(err)

    print('MARKET_HOLIDAY_FILES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
