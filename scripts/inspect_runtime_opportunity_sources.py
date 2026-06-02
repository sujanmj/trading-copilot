#!/usr/bin/env python3
"""
Inspect local runtime opportunity / prediction sources (API + data files).

Read-only — never writes DB or JSON files.

Usage:
  python scripts/inspect_runtime_opportunity_sources.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

API_BASE = 'http://127.0.0.1:8080'
API_ENDPOINTS = (
    '/opps',
    '/api/all',
    '/api/runtime/snapshot',
    '/api/debug/market-memory',
)

DATA_FILES = (
    'unified_intelligence.json',
    'active_snapshot.json',
    'history_data.json',
    'stats_data.json',
    'latest_market_data.json',
    'analysis_state.json',
    'analysis_explanations.json',
)

CANDIDATE_KEYS = frozenset({
    'opportunities',
    'ranked',
    'ranked_opportunities',
    'picks',
    'predictions',
    'recommendations',
    'signals',
    'stocks',
    'candidates',
    'watchlist',
    'final_recommendations',
    'top_opportunities',
    'risks_and_avoids',
    'canonical_opportunity_feed',
})

TICKER_KEYS = ('ticker', 'symbol', 'stock', 'stock_symbol', 'nse_symbol', 'name')

GENERIC_WORDS = frozenset({
    'NIFTY', 'BANKNIFTY', 'SENSEX', 'INDIA', 'MARKET', 'INDEX', 'CASH', 'BUY', 'SELL',
    'FOCUS', 'WATCH', 'AVOID', 'HOLD', 'IST', 'EOD', 'AI', 'OPS', 'HTTP', 'THE', 'AND',
    'FOR', 'WITH', 'FROM', 'NEXT', 'DAY', 'RISK', 'SIZE', 'STOP', 'LOSS', 'TARGET',
    'AUTO', 'BANKS', 'BANKING', 'IT', 'TELECOM', 'METALS', 'CONSUMER', 'COMMODITIES',
    'OIL_GAS', 'JEWELLERY', 'MEDIA', 'POWER', 'PHARMA', 'FMCG', 'REALTY', 'INFRA',
})

TICKER_RE = re.compile(r'^[A-Z][A-Z0-9&.-]{1,14}$')
MAX_NEST_DEPTH = 5


def _load_api_key() -> str:
    key = os.environ.get('API_KEY', '').strip()
    if key:
        return key
    try:
        from backend.utils.config import get_env, load_env

        load_env()
        return get_env('API_KEY')
    except Exception:
        return ''


def extract_ticker(item: Any) -> Optional[str]:
    """Extract a plausible ticker/symbol from a candidate item."""
    if isinstance(item, str):
        sym = item.strip().upper()
        return sym if _looks_like_ticker(sym) else None
    if not isinstance(item, dict):
        return None
    for key in TICKER_KEYS:
        val = item.get(key)
        if val is None:
            continue
        sym = str(val).strip().upper()
        if _looks_like_ticker(sym):
            return sym
    return None


def _looks_like_ticker(sym: str) -> bool:
    if not sym or len(sym) < 2 or len(sym) > 15:
        return False
    if sym in GENERIC_WORDS:
        return False
    if '_' in sym:
        return False
    return bool(TICKER_RE.match(sym))


def _type_label(value: Any) -> str:
    if isinstance(value, dict):
        return 'dict'
    if isinstance(value, list):
        return 'list'
    if value is None:
        return 'null'
    return type(value).__name__


def _top_level_keys(value: Any) -> List[str]:
    if isinstance(value, dict):
        return sorted(str(k) for k in value.keys())
    return []


def _find_candidate_arrays(
    value: Any,
    *,
    path: str = '',
    depth: int = 0,
) -> List[Tuple[str, List[Any]]]:
    found: List[Tuple[str, List[Any]]] = []
    if depth > MAX_NEST_DEPTH:
        return found

    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f'{path}.{key}' if path else str(key)
            if key in CANDIDATE_KEYS and isinstance(child, list):
                found.append((child_path, child))
            elif isinstance(child, (dict, list)):
                found.extend(_find_candidate_arrays(child, path=child_path, depth=depth + 1))
    elif isinstance(value, list) and depth == 0:
        for idx, child in enumerate(value):
            if isinstance(child, (dict, list)):
                found.extend(_find_candidate_arrays(child, path=f'[{idx}]', depth=depth + 1))
    return found


def _analyze_candidates(items: List[Any]) -> Dict[str, Any]:
    tickers: List[str] = []
    stock_specific_count = 0
    for item in items:
        ticker = extract_ticker(item)
        if ticker:
            tickers.append(ticker)
            stock_specific_count += 1
    sample = tickers[:3]
    stock_specific = stock_specific_count > 0
    if items and stock_specific_count == 0:
        stock_specific = False
    return {
        'count': len(items),
        'sample_tickers': sample,
        'stock_specific': stock_specific,
        'stock_specific_count': stock_specific_count,
    }


def _fetch_api_json(path: str, api_key: str = '') -> Tuple[Optional[Any], Optional[str], Optional[int]]:
    url = API_BASE.rstrip('/') + path
    headers = {'Accept': 'application/json'}
    if api_key:
        headers['X-API-Key'] = api_key
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read().decode('utf-8')
            return json.loads(body), None, resp.status
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode('utf-8', errors='replace')[:200]
        except Exception:
            detail = str(exc)
        return None, f'HTTP {exc.code}: {detail}', exc.code
    except urllib.error.URLError as exc:
        return None, str(getattr(exc, 'reason', exc)), None
    except json.JSONDecodeError as exc:
        return None, f'invalid JSON: {exc}', None
    except Exception as exc:
        return None, str(exc), None


def _inspect_payload(source_name: str, payload: Any, *, found: bool = True) -> Dict[str, Any]:
    print(f'[SOURCE] name={source_name} found={str(found).lower()}')
    print(f'[SOURCE] type={_type_label(payload)}')
    print(f'[SOURCE] keys={_top_level_keys(payload)}')

    candidate_sources: List[Dict[str, Any]] = []
    for array_path, items in _find_candidate_arrays(payload):
        info = _analyze_candidates(items)
        print(
            f'[SOURCE] candidate_key={array_path} count={info["count"]} '
            f'sample_tickers={info["sample_tickers"]} stock_specific={info["stock_specific"]}'
        )
        candidate_sources.append({
            'path': array_path,
            **info,
        })

    total_candidates = sum(c['count'] for c in candidate_sources)
    all_tickers: List[str] = []
    for c in candidate_sources:
        all_tickers.extend(c['sample_tickers'])
    stock_specific_any = any(c['stock_specific'] and c['count'] > 0 for c in candidate_sources)

    return {
        'name': source_name,
        'candidate_arrays': candidate_sources,
        'total_candidates': total_candidates,
        'sample_tickers': all_tickers[:3],
        'has_stock_specific': stock_specific_any,
    }


def _load_json_file(rel_path: str) -> Tuple[Optional[Any], Optional[str]]:
    path = PROJECT_ROOT / 'data' / rel_path
    if not path.exists():
        return None, 'missing'
    try:
        return json.loads(path.read_text(encoding='utf-8')), None
    except Exception as exc:
        return None, str(exc)


def inspect_api_sources(api_key: str) -> Tuple[bool, List[Dict[str, Any]], bool]:
    """Return (api_available, source_reports, printed_unavailable)."""
    reports: List[Dict[str, Any]] = []
    api_available = False
    printed_unavailable = False

    for path in API_ENDPOINTS:
        source_name = f'api:{path}'
        data, err, status = _fetch_api_json(path)
        if err and (
            'Connection refused' in err
            or 'actively refused' in err.lower()
            or 'WinError 10061' in err
            or 'timed out' in err.lower()
            or 'No connection' in err
        ):
            if not printed_unavailable:
                print('[API] unavailable - backend not running; continuing with files')
                printed_unavailable = True
            print(f'[SOURCE] name={source_name} found=False error={err}')
            continue

        if status in (401, 403) or (err and 'HTTP 401' in err) or (err and 'HTTP 403' in err):
            if api_key:
                data, err, status = _fetch_api_json(path, api_key=api_key)
            if err and ('HTTP 401' in err or 'HTTP 403' in err):
                print(f'[SOURCE] name={source_name} found=False auth_required status={status}')
                api_available = True
                continue

        if err:
            if status == 404:
                api_available = True
                print(f'[SOURCE] name={source_name} found=False status=404')
            else:
                print(f'[SOURCE] name={source_name} found=False error={err}')
                if status is not None:
                    api_available = True
            continue

        api_available = True
        reports.append(_inspect_payload(source_name, data))

    return api_available, reports, printed_unavailable


def inspect_file_sources() -> List[Dict[str, Any]]:
    reports: List[Dict[str, Any]] = []
    for rel_path in DATA_FILES:
        source_name = f'file:{rel_path}'
        payload, err = _load_json_file(rel_path)
        if err == 'missing':
            print(f'[SOURCE] name={source_name} found=False')
            continue
        if err:
            print(f'[SOURCE] name={source_name} found=True error={err}')
            continue
        reports.append(_inspect_payload(source_name, payload))
    return reports


def main() -> int:
    api_key = _load_api_key()
    api_available, api_reports, _ = inspect_api_sources(api_key)
    file_reports = inspect_file_sources()
    all_reports = api_reports + file_reports

    summary_sources: List[Dict[str, Any]] = []
    total_candidates = 0
    for report in all_reports:
        count = int(report.get('total_candidates') or 0)
        if count <= 0:
            continue
        total_candidates += count
        summary_sources.append(report)

    print(f'[RUNTIME_SOURCES] api_available={str(api_available).lower()}')
    for report in summary_sources:
        tickers = report.get('sample_tickers') or []
        print(
            f'[RUNTIME_SOURCES] source={report["name"]} candidates={report["total_candidates"]} '
            f'tickers={tickers}'
        )
    print(f'[RUNTIME_SOURCES] total_candidate_sources={len(summary_sources)}')
    print(f'[RUNTIME_SOURCES] total_candidates={total_candidates}')
    print('RUNTIME_OPPORTUNITY_SOURCES_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
