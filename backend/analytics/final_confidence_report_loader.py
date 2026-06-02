"""
Cached final confidence report loader — fast read-only API payloads (Stage 44AX).

Reads data/final_confidence_report.json only. No live runtime, market scan, or AI providers.
"""

from __future__ import annotations

import json
from typing import Any

from backend.utils.config import DATA_DIR

# BACKEND_STAGE_44AX_FINAL_CONFIDENCE_ENDPOINT_STABLE
BACKEND_STAGE_44AX_FINAL_CONFIDENCE_ENDPOINT_STABLE = True

FINAL_CONFIDENCE_REPORT_REL = 'data/final_confidence_report.json'
FINAL_CONFIDENCE_REPORT_PATH = DATA_DIR / 'final_confidence_report.json'
MISSING_MESSAGE = 'Decision cache is warming. Try again in 1–2 minutes.'

_SUMMARY_KEYS = (
    'checked',
    'buy_candidate',
    'watch',
    'avoid',
    'no_decision',
    'active_mode',
    'active_mode_label',
    'market_closed',
    'buy_cap_active',
)


def _build_summary(report: dict[str, Any]) -> dict[str, Any]:
    embedded = report.get('summary') if isinstance(report.get('summary'), dict) else {}
    summary: dict[str, Any] = dict(embedded)
    for key in _SUMMARY_KEYS:
        if report.get(key) is not None and summary.get(key) is None:
            summary[key] = report[key]
    return summary


def _normalize_report(report: dict[str, Any], *, limit: int = 50) -> dict[str, Any]:
    payload = dict(report)
    rows = payload.get('rows')
    if not isinstance(rows, list):
        top = payload.get('top_candidates') or []
        payload['rows'] = list(top)[:limit] if isinstance(top, list) else []
    elif limit and len(payload['rows']) > limit:
        payload['rows'] = payload['rows'][:limit]

    top_candidates = payload.get('top_candidates')
    if isinstance(top_candidates, list) and limit and len(top_candidates) > limit:
        payload['top_candidates'] = top_candidates[:limit]

    summary = _build_summary(payload)
    for key in ('checked', 'buy_candidate', 'watch', 'avoid', 'no_decision'):
        if payload.get(key) is None and summary.get(key) is not None:
            payload[key] = summary[key]

    payload.setdefault('ok', True)
    payload.setdefault('shadow_mode', True)
    return payload


def _missing_payload() -> dict[str, Any]:
    return {
        'ok': False,
        'error': 'final_confidence_report_missing',
        'message': MISSING_MESSAGE,
    }


def _invalid_payload(message: str) -> dict[str, Any]:
    return {
        'ok': False,
        'error': 'final_confidence_report_invalid',
        'message': message,
    }


def _wrap_success(report: dict[str, Any]) -> dict[str, Any]:
    summary = _build_summary(report)
    payload: dict[str, Any] = {
        'ok': True,
        'source': FINAL_CONFIDENCE_REPORT_REL,
        'report': report,
        'summary': summary,
    }
    for key, value in report.items():
        if key == 'summary':
            continue
        payload.setdefault(key, value)
    return payload


def load_cached_final_confidence_report(*, limit: int = 50) -> dict[str, Any]:
    """Read cached final confidence report JSON and return a stable API payload."""
    if not FINAL_CONFIDENCE_REPORT_PATH.is_file():
        return _missing_payload()

    try:
        raw = json.loads(FINAL_CONFIDENCE_REPORT_PATH.read_text(encoding='utf-8'))
    except OSError as exc:
        return _invalid_payload(str(exc))
    except json.JSONDecodeError as exc:
        return _invalid_payload(f'invalid JSON: {exc}')

    if not isinstance(raw, dict):
        return _invalid_payload('expected JSON object')

    report = _normalize_report(raw, limit=limit)
    return _wrap_success(report)


def load_cached_final_confidence_ticker_breakdown(ticker: str, *, limit: int = 500) -> dict[str, Any]:
    """Ticker breakdown from cached report rows (no live DB scoring)."""
    from backend.analytics.final_confidence_fusion import _normalize_ticker

    normalized = _normalize_ticker(ticker)
    if not normalized:
        return {'ok': False, 'error': 'ticker is required'}

    cached = load_cached_final_confidence_report(limit=limit)
    if cached.get('ok') is not True:
        return cached

    report = cached.get('report') if isinstance(cached.get('report'), dict) else {}
    rows = report.get('rows') or report.get('top_candidates') or []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get('ticker') or '').upper() == normalized:
            return {
                'ok': True,
                'source': cached.get('source', FINAL_CONFIDENCE_REPORT_REL),
                'ticker': normalized,
                'found': True,
                'candidate_count': 1,
                'breakdown': row,
                'shadow_mode': report.get('shadow_mode', True),
                'disclaimer': report.get('disclaimer'),
            }

    return {
        'ok': True,
        'source': cached.get('source', FINAL_CONFIDENCE_REPORT_REL),
        'ticker': normalized,
        'found': False,
        'message': 'no predictions found for ticker in cached report',
        'shadow_mode': report.get('shadow_mode', True),
        'disclaimer': report.get('disclaimer'),
    }
