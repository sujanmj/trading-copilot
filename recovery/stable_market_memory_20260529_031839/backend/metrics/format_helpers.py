"""
Safe numeric formatting — prevents None/format crashes on metrics surfaces.
"""

from __future__ import annotations

from typing import Any, Optional, Union

Number = Union[int, float, str, None]

AWAITING_CONFIDENCE = 'Awaiting statistical confidence'
CONFIDENCE_BUILDING = 'Confidence building'
UNAVAILABLE = 'N/A'


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace('%', '').replace('/10', '')
    if not text or text.lower() in ('none', 'null', 'nan', 'n/a', '—', '-'):
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def safe_num(
    value: Number,
    *,
    fmt: str = '.1f',
    fallback: str = UNAVAILABLE,
    prefix: str = '',
    suffix: str = '',
) -> str:
    n = _to_float(value)
    if n is None:
        return fallback
    spec = fmt if fmt.startswith('.') else f'.{fmt.lstrip(".")}'
    return f'{prefix}{n:{spec}}{suffix}'


def safe_pct(
    value: Number,
    *,
    decimals: int = 1,
    signed: bool = False,
    fallback: str = AWAITING_CONFIDENCE,
) -> str:
    n = _to_float(value)
    if n is None:
        return fallback
    if signed:
        return f'{n:+.{decimals}f}%'
    return f'{n:.{decimals}f}%'


def safe_ratio(
    value: Number,
    *,
    decimals: int = 2,
    fallback: str = UNAVAILABLE,
) -> str:
    return safe_num(value, fmt=f'.{decimals}f', fallback=fallback)


def safe_confidence(value: Number, *, fallback: str = UNAVAILABLE) -> str:
    n = _to_float(value)
    if n is None:
        return fallback
    if n <= 10:
        return f'{n:.1f}/10'
    return safe_pct(n, decimals=0, fallback=fallback)
