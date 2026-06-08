"""
AI Hub per-tab payloads — single aggregated response per tab (Stage 44AQ).

Read-only aggregation from runtime cache, report pack, and local JSON files.
Never invents market prices or news. Internal sources time out at 3s each.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from backend.utils.config import (
    DATA_DIR,
    RUNTIME_SNAPSHOT_CACHE,
)

SOURCE_TIMEOUT_SEC = 3.0
REDDIT_SOURCE_URL = 'https://www.reddit.com/r/IndianStockMarket/'
MEMORY_DISPLAY_NOTE = 'Memory signal — no live price attached'

VALID_TABS = frozenset({
    'brain', 'govt', 'scan', 'market', 'global', 'news', 'tv', 'reddit', 'calib', 'journal',
})

TAB_ALIASES: dict[str, str] = {
    'scanner': 'scan',
    'markets': 'market',
    'mkt': 'market',
    'stats': 'calib',
    'history': 'journal',
    'rdt': 'reddit',
}

TIMESTAMP_KEYS = (
    'generated_at',
    'package_generated_at',
    'last_updated',
    'intelligence_timestamp',
    'published_at',
    'updated_at',
    'timestamp',
    'collected_at',
)

SCANNER_FILE = DATA_DIR / 'scanner_data.json'
GOVT_FILE = DATA_DIR / 'govt_intelligence.json'
GLOBAL_FILE = DATA_DIR / 'global_markets.json'
REDDIT_FILE = DATA_DIR / 'reddit_data.json'
HISTORY_FILE = DATA_DIR / 'history_data.json'
STATS_FILE = DATA_DIR / 'stats_data.json'
PACK_FILE = DATA_DIR / 'daily_report_pack_latest.json'
CALIBRATION_FILE = DATA_DIR / 'confidence_calibration_report.json'
FINAL_CONFIDENCE_FILE = DATA_DIR / 'final_confidence_report.json'
AIHUB_TAB_CACHE_DIR = DATA_DIR / 'cache' / 'aihub_tabs'

GOVT_EMPTY_MESSAGE = (
    'No fresh government/policy intelligence collected. '
    'Last report has no govt-specific trigger.'
)
GOVT_RISK_KEYWORDS = (
    'policy', 'govt', 'government', 'inflation', 'fuel', 'monsoon',
    'rate', 'rbi', 'budget', 'tax', 'ministry', 'sebi', 'excise',
)
FAILED_STRONG_MESSAGE = (
    'Recent strong signal failed or weakened — reduce confidence until new confirmation.'
)
GLOBAL_SECTOR_MAPPING: dict[str, Any] = {
    'at_risk_sectors': ['ENERGY_OIL', 'HOTELS_TRAVEL', 'FMCG'],
    'supported_sectors': ['METALS_MINING', 'POWER', 'PHARMA', 'TELECOM'],
    'commodity_impacts': [
        {'commodity': 'Gold', 'symbols': ['GOLDBEES'], 'stance': 'WATCH'},
        {'commodity': 'Silver', 'symbols': ['SILVERBEES'], 'stance': 'WATCH'},
        {'commodity': 'Oil', 'symbols': ['ONGC', 'OIL', 'GAIL', 'RELIANCE'], 'stance': 'REVIEW'},
        {'commodity': 'VIX', 'symbols': [], 'stance': 'REVIEW'},
        {'commodity': 'USD', 'symbols': ['INDIGO'], 'stance': 'REVIEW'},
        {'commodity': 'Nasdaq/S&P', 'symbols': ['ASIANPAINT', 'BERGEPAINT', 'TATASTEEL', 'JSWSTEEL'], 'stance': 'WATCH'},
    ],
}
MARKET_STALE_MINUTES = 60
MARKET_STALE_REFRESH_CMD = 'python scripts\\refresh_closed_market_intelligence.py'
CLOSED_MARKET_NOTE = 'Closed-market snapshot — review only, not live entry.'
UNDERLYING_DATA_STALE_NOTE = 'Underlying market data is stale.'
MARKET_FORCE_REFRESH_TIMEOUT_SEC = 5.0


def _aihub_tab_cache_path(tab: str) -> Path:
    return AIHUB_TAB_CACHE_DIR / f'{tab}.json'


def load_aihub_tab_cache(tab: str) -> Optional[dict[str, Any]]:
    path = _aihub_tab_cache_path(tab)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def save_aihub_tab_cache(tab: str, payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        return
    try:
        AIHUB_TAB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _aihub_tab_cache_path(tab)
        path.write_text(json.dumps(payload, indent=2, default=str) + '\n', encoding='utf-8')
    except OSError:
        pass


def _aihub_tab_cache_placeholder(tab: str) -> dict[str, Any]:
    key = _normalize_tab(tab)
    return {
        'ok': True,
        'tab': key or str(tab),
        'cache_missing': True,
        'generated_at': _now_iso(),
        'market_mode': 'RESEARCH_MODE',
        'source': 'cache_missing',
        'cache_age_seconds': 0,
        'items': [],
        'summary': {},
        'warnings': ['cache_missing'],
        'message': 'AI Hub cache unavailable. Tap Refresh.',
    }


def _is_closed_market_mode(mode: str) -> bool:
    token = str(mode or '').upper()
    return 'INDIA' not in token or 'RESEARCH' in token or 'CLOSED' in token


def _pick_market_data_timestamp(
    snap: dict[str, Any],
    freshness: dict[str, Any],
) -> Optional[str]:
    candidates: list[str] = []
    if isinstance(freshness, dict):
        sources = freshness.get('sources') or freshness.get('feeds') or {}
        if isinstance(sources, dict):
            for key in ('prices', 'latest_market_data', 'market'):
                row = sources.get(key)
                if isinstance(row, dict) and row.get('timestamp'):
                    candidates.append(str(row['timestamp']))
        latest = freshness.get('latest_market_data_timestamp')
        if latest:
            candidates.append(str(latest))
    if snap:
        for key in (
            'snapshot_published_at',
            'intelligence_timestamp',
            'published_at',
            'generated_at',
        ):
            raw = snap.get(key)
            if raw:
                candidates.append(str(raw))
                break
    for raw in candidates:
        if _parse_iso(raw) is not None:
            return raw
    return candidates[0] if candidates else None


def _try_safe_market_force_refresh(market_mode: str) -> tuple[bool, list[str]]:
    """Best-effort closed-market refresh; never blocks longer than MARKET_FORCE_REFRESH_TIMEOUT_SEC."""
    warnings: list[str] = []

    def _work() -> bool:
        if _is_closed_market_mode(market_mode):
            try:
                from scripts.refresh_local_intelligence import run_refresh_scoped

                run_refresh_scoped('router', dry_run=False)
            except Exception as exc:
                warnings.append(f'router_refresh_failed:{type(exc).__name__}')
        return True

    try:
        from backend.runtime.global_job_locks import run_with_timeout

        run_with_timeout(
            _work,
            job='market_force_refresh',
            timeout=MARKET_FORCE_REFRESH_TIMEOUT_SEC,
            owner='aihub_tab_payloads',
        )
        return True, warnings
    except TimeoutError:
        return False, warnings + ['market_force_refresh_timeout']
    except Exception as exc:
        return False, warnings + [f'market_force_refresh_failed:{type(exc).__name__}']


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_iso(raw: object) -> Optional[datetime]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _embedded_timestamp(data: dict[str, Any]) -> Optional[datetime]:
    for key in TIMESTAMP_KEYS:
        dt = _parse_iso(data.get(key))
        if dt is not None:
            return dt
    return None


def _cache_age_seconds(
    *,
    path: Optional[Path] = None,
    data: Optional[dict[str, Any]] = None,
) -> int:
    dt: Optional[datetime] = None
    if data:
        dt = _embedded_timestamp(data)
    if dt is None and path and path.is_file():
        try:
            dt = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            dt = None
    if dt is None:
        return 0
    return max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))


def _timed_call(label: str, fn: Callable[[], Any]) -> tuple[Any, list[str]]:
    from backend.runtime.global_job_locks import run_with_timeout

    try:
        return run_with_timeout(
            fn,
            job=f'aihub_{label}',
            timeout=SOURCE_TIMEOUT_SEC,
            owner='aihub_tab_payloads',
        ), []
    except TimeoutError:
        return None, [f'{label}_timeout']
    except Exception as exc:
        return None, [f'{label}_failed:{type(exc).__name__}']


def _normalize_tab(tab: str) -> str:
    key = str(tab or '').strip().lower()
    return TAB_ALIASES.get(key, key)


def _resolve_market_mode(*sources: dict[str, Any]) -> str:
    for src in sources:
        if not src:
            continue
        for key in ('market_mode', 'active_mode', 'active_mode_label'):
            raw = src.get(key)
            if raw:
                return str(raw)
        router = src.get('market_router')
        if isinstance(router, dict):
            for key in ('active_mode', 'active_mode_label'):
                raw = router.get(key)
                if raw:
                    return str(raw)
    return 'RESEARCH_MODE'


def _payload_shell(
    tab: str,
    *,
    items: list[dict[str, Any]],
    summary: dict[str, Any],
    source: str,
    cache_age_seconds: int,
    market_mode: str,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        'ok': True,
        'tab': tab,
        'generated_at': _now_iso(),
        'market_mode': market_mode,
        'source': source,
        'cache_age_seconds': cache_age_seconds,
        'items': items,
        'summary': summary,
        'warnings': warnings,
    }


def _load_report_pack_timed() -> tuple[dict[str, Any], str, list[str]]:
    """Read cached daily report pack only — never triggers full pack generation."""
    cached = _load_json(PACK_FILE)
    if cached.get('ok') is True:
        return cached, 'report_cache', []
    if cached:
        return cached, 'fallback', ['report_pack_incomplete']
    return {}, 'fallback', ['report_pack_unavailable']


def _load_runtime_snapshot_fast() -> tuple[dict[str, Any], str, list[str]]:
    snap = _load_json(RUNTIME_SNAPSHOT_CACHE)
    if snap:
        return snap, 'runtime', []
    snap, warns = _timed_call(
        'runtime_snapshot',
        lambda: json.loads(RUNTIME_SNAPSHOT_CACHE.read_text(encoding='utf-8'))
        if RUNTIME_SNAPSHOT_CACHE.is_file()
        else {},
    )
    if isinstance(snap, dict) and snap:
        return snap, 'runtime', warns
    return {}, 'fallback', warns + ['runtime_snapshot_missing']


def _memory_scan_row(
    *,
    ticker: str,
    sector: str = '—',
    strength: str = 'MEMORY',
    direction: str = 'NEUTRAL',
    signals: Optional[list[str]] = None,
    pack_source: str = 'market-memory',
) -> dict[str, Any]:
    return {
        'ticker': ticker,
        'sector': sector,
        'strength': strength,
        'direction': direction,
        'signals': signals or ['memory'],
        'source': 'market-memory',
        'is_memory_fallback': True,
        'price': None,
        'change_pct': None,
        'change_percent': None,
        'volume_ratio': None,
        'display_note': MEMORY_DISPLAY_NOTE,
        '_packSource': pack_source,
    }


def _watchlist_candidate_row(row: dict[str, Any]) -> dict[str, Any]:
    score = _watch_score(row)
    reason = (
        row.get('reason')
        or row.get('logic')
        or row.get('primary_label')
        or 'Daily report candidate'
    )
    decision = _row_decision_token(row) or 'WATCH'
    return {
        'ticker': str(row.get('ticker') or '').upper(),
        'sector': str(row.get('sector') or '—'),
        'decision': decision,
        'score': score,
        'reason': str(reason)[:240],
        'source': 'watchlist',
        'is_watchlist_candidate': True,
        'is_memory_fallback': False,
        'price': None,
        'change_pct': None,
        'change_percent': None,
        'volume_ratio': None,
    }


def _scanner_live_row(row: dict[str, Any]) -> dict[str, Any]:
    price = row.get('price')
    try:
        price_num = float(price) if price is not None else None
    except (TypeError, ValueError):
        price_num = None
    change = row.get('change_percent', row.get('change_pct'))
    try:
        change_num = float(change) if change is not None else None
    except (TypeError, ValueError):
        change_num = None
    vol = row.get('volume_ratio')
    try:
        vol_num = float(vol) if vol is not None else None
    except (TypeError, ValueError):
        vol_num = None
    return {
        'ticker': row.get('ticker') or '?',
        'sector': row.get('sector') or '—',
        'strength': row.get('strength') or 'SIGNAL',
        'direction': row.get('direction') or 'NEUTRAL',
        'signals': row.get('signals') or [],
        'price': price_num,
        'change_pct': change_num,
        'change_percent': change_num,
        'volume_ratio': vol_num,
        'source': 'scanner',
        'is_memory_fallback': False,
    }


def _dedupe_scan_items(items: list[dict[str, Any]], limit: int = 80) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in items:
        ticker = str(row.get('ticker') or '').upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _dedupe_ticker_rows(rows: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get('ticker') or row.get('symbol') or '').upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _pack_final_confidence_usable(fc: Any) -> bool:
    if not isinstance(fc, dict):
        return False
    if fc.get('ok') is True:
        return True
    keys = (
        'checked', 'watch', 'avoid', 'no_decision', 'buy_candidate',
        'active_mode', 'active_mode_label', 'mode', 'top_candidates', 'top_tickers',
    )
    if any(fc.get(k) is not None for k in keys):
        return True
    cal = fc.get('calibration') or {}
    if isinstance(cal, dict) and (cal.get('recommendations') or cal.get('recs')):
        return True
    sim = fc.get('simulation') or {}
    if isinstance(sim, dict) and sim.get('simulated_predictions') is not None:
        return True
    return False


def _calibration_recs_from_sources(
    calibration: Any,
    pack: dict[str, Any],
    fc: Any,
) -> list[Any]:
    recs: list[Any] = []
    if isinstance(calibration, dict):
        raw = calibration.get('recommendations')
        if isinstance(raw, list):
            recs.extend(raw)
        elif isinstance(raw, int) and raw > 0:
            pass
    pack_cal = (pack.get('confidence_calibration') or {}) if pack else {}
    if isinstance(pack_cal, dict):
        raw = pack_cal.get('recommendations')
        if isinstance(raw, list):
            recs.extend(raw)
    if isinstance(fc, dict):
        fc_cal = fc.get('calibration') or {}
        if isinstance(fc_cal, dict):
            raw = fc_cal.get('recommendations')
            if isinstance(raw, list):
                recs.extend(raw)
    return recs


def _sim_predictions_from_fc(fc: Any, pack: dict[str, Any]) -> Any:
    if isinstance(fc, dict):
        sim = fc.get('simulation') or {}
        if isinstance(sim, dict) and sim.get('simulated_predictions') is not None:
            return sim.get('simulated_predictions')
    perf = (pack.get('simulation_performance') or {}) if pack else {}
    if isinstance(perf, dict):
        return perf.get('simulated_predictions') or perf.get('predictions')
    return None


def _normalize_final_confidence_for_summary(fc: Any, pack: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(fc, dict):
        fc = {}
    summary = fc.get('summary') if isinstance(fc.get('summary'), dict) else {}
    pack_summary = (pack.get('summary') or {}) if pack else {}
    cal = fc.get('calibration') if isinstance(fc.get('calibration'), dict) else {}
    return {
        'ok': fc.get('ok', True) if _pack_final_confidence_usable(fc) else False,
        'active_mode': fc.get('active_mode') or fc.get('active_mode_label')
            or pack.get('market_mode') or summary.get('active_mode'),
        'checked': fc.get('checked', summary.get('checked', pack_summary.get('checked'))),
        'buy_candidate': fc.get('buy_candidate', summary.get('buy_candidate', pack_summary.get('buy_candidates'))),
        'watch': fc.get('watch', summary.get('watch', pack_summary.get('watch'))),
        'avoid': fc.get('avoid', summary.get('avoid', pack_summary.get('avoid'))),
        'no_decision': fc.get('no_decision', summary.get('no_decision', pack_summary.get('no_decision'))),
        'calibration_recs': _calibration_recs_from_sources(cal, pack, fc),
        'sim_predictions': _sim_predictions_from_fc(fc, pack),
        'top_candidates': fc.get('top_candidates') or fc.get('rows') or [],
        'source': fc.get('_source') or 'daily-report-pack',
    }


def _risk_note_is_govt(note: object) -> bool:
    text = str(note or '').lower()
    return any(kw in text for kw in GOVT_RISK_KEYWORDS)


def _collect_govt_items(
    govt: dict[str, Any],
    pack: dict[str, Any],
    snap: dict[str, Any],
    evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in govt.get('high_impact') or govt.get('announcements') or govt.get('items') or []:
        if isinstance(row, dict):
            items.append({**row, 'source': row.get('source') or 'govt_intelligence', 'kind': 'govt'})

    intel = {}
    if snap:
        intel = (
            snap.get('intelligence')
            or (snap.get('market_snapshot') or {}).get('intelligence')
            or (snap.get('exports') or {}).get('intelligence')
            or (snap.get('data') or {}).get('intelligence')
            or {}
        )
    if isinstance(intel, dict):
        govt_impact = intel.get('government_impact') or intel.get('govt_impact') or {}
        if isinstance(govt_impact, dict) and (govt_impact.get('summary') or govt_impact.get('headline')):
            items.append({
                'kind': 'brain_govt',
                'title': str(govt_impact.get('summary') or govt_impact.get('headline'))[:500],
                'confidence_score': govt_impact.get('confidence_score'),
                'source': 'brain_intelligence',
                'classification': 'govt_impact',
            })

    for note in (pack.get('risk_notes') or []):
        if _risk_note_is_govt(note):
            items.append({
                'kind': 'risk',
                'title': str(note),
                'source': 'daily-report-pack',
                'classification': 'policy',
            })

    wl = pack.get('tomorrow_watchlist') or {}
    for note in wl.get('risk_notes') or []:
        if _risk_note_is_govt(note):
            items.append({
                'kind': 'risk',
                'title': str(note),
                'source': 'tomorrow-watchlist',
                'classification': 'policy',
            })

    for row in evidence.get('context_items') or evidence.get('items') or evidence.get('macro_context') or []:
        if not isinstance(row, dict):
            continue
        cls = str(row.get('classification') or '').lower()
        src = str(row.get('source') or '').lower()
        if (
            'macro' in cls
            or 'market_context' in cls
            or 'govt' in cls
            or 'policy' in cls
            or 'govt' in src
            or 'policy' in src
        ):
            items.append({**row, 'kind': row.get('kind') or 'macro', 'source': row.get('source') or 'external_evidence'})
    return items


def _row_decision_token(row: dict[str, Any]) -> str:
    return str(row.get('decision') or row.get('action') or row.get('display_tier') or '').upper()


def _row_is_buy(row: dict[str, Any]) -> bool:
    token = _row_decision_token(row)
    return token in ('BUY', 'BUY_CANDIDATE') or (
        'BUY' in token and 'CANDIDATE' in token
    )


def _watch_score(row: dict[str, Any]) -> float:
    for key in ('score', 'final_score', 'confidence_score'):
        val = row.get(key)
        try:
            if val is not None:
                return float(val)
        except (TypeError, ValueError):
            continue
    label = str(row.get('confidence_label') or '').upper()
    if label == 'HIGH':
        return 70.0
    if label == 'MEDIUM':
        return 50.0
    if label == 'LOW':
        return 30.0
    return 0.0


def _build_actionable_candidates(pack: dict[str, Any], fc: Any) -> dict[str, Any]:
    buy_rows: list[dict[str, Any]] = []
    watch_pool: list[dict[str, Any]] = []
    avoid_pool: list[dict[str, Any]] = []

    fc_rows = []
    if isinstance(fc, dict):
        fc_rows = list(fc.get('top_candidates') or fc.get('rows') or [])
    for row in fc_rows:
        if not isinstance(row, dict):
            continue
        if _row_is_buy(row):
            buy_rows.append(row)
        elif 'AVOID' in _row_decision_token(row):
            avoid_pool.append(row)
        elif 'WATCH' in _row_decision_token(row) or not _row_decision_token(row):
            watch_pool.append(row)

    wl = (pack.get('tomorrow_watchlist') or {}) if pack else {}
    for row in wl.get('top_watchlist') or wl.get('raw_candidates') or []:
        if not isinstance(row, dict):
            continue
        if _row_is_buy(row):
            buy_rows.append(row)
        elif 'AVOID' in _row_decision_token(row):
            avoid_pool.append(row)
        else:
            watch_pool.append(row)

    watch_sorted = sorted(watch_pool, key=_watch_score, reverse=True)
    avoid_sorted = sorted(avoid_pool, key=_watch_score, reverse=True)

    def _fmt_watch(row: dict[str, Any]) -> dict[str, Any]:
        return {
            'ticker': row.get('ticker') or row.get('symbol'),
            'score': _watch_score(row),
            'why': row.get('reason') or row.get('logic') or row.get('primary_label') or '—',
            'confirmation_needed': row.get('confirmation_needed')
                or 'Price/volume confirmation required before entry.',
            'decision': _row_decision_token(row) or 'WATCH',
        }

    return {
        'buy_candidate': _dedupe_ticker_rows(buy_rows, limit=12),
        'watch_for_entry': [_fmt_watch(r) for r in _dedupe_ticker_rows(watch_sorted, limit=3)],
        'avoid': [
            {
                'ticker': r.get('ticker') or r.get('symbol'),
                'score': _watch_score(r),
                'why': r.get('reason') or r.get('logic') or r.get('primary_label') or '—',
            }
            for r in _dedupe_ticker_rows(avoid_sorted, limit=5)
        ],
        'watch_entry_note': (
            'Watch for entry only after price confirms strength. Not a blind buy.'
        ),
    }


def _is_strong_prediction_row(row: dict[str, Any]) -> bool:
    conf = str(row.get('confidence') or row.get('confidence_label') or '').upper()
    strength = str(row.get('strength') or row.get('signal_strength') or row.get('signal_type') or '').upper()
    if any(tok in conf for tok in ('HIGH', 'ULTRA')):
        return True
    if 'STRONG' in strength or 'ULTRA' in strength:
        return True
    try:
        return float(row.get('score') or 0) >= 65
    except (TypeError, ValueError):
        return False


def _is_negative_outcome_row(row: dict[str, Any]) -> bool:
    verdict = str(row.get('verdict') or row.get('outcome') or row.get('result') or '').upper()
    if not verdict:
        return False
    if verdict in ('LOSS', 'FAILED', 'WEAKENED', 'STOP_LOSS_HIT'):
        return True
    return 'LOSS' in verdict or 'FAIL' in verdict


def _detect_failed_strong_warnings(
    history: dict[str, Any],
    pack: dict[str, Any],
    fc: Any,
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in history.get('predictions') or []:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get('ticker') or row.get('symbol') or '').upper()
        if not ticker or ticker in seen:
            continue
        if _is_strong_prediction_row(row) and _is_negative_outcome_row(row):
            seen.add(ticker)
            warnings.append({'ticker': ticker, 'message': FAILED_STRONG_MESSAGE})

    scanner = _load_json(SCANNER_FILE)
    for row in scanner.get('top_signals') or scanner.get('signals') or []:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get('ticker') or '').upper()
        if not ticker or ticker in seen:
            continue
        strength = str(row.get('strength') or '').upper()
        if 'ULTRA' not in strength and 'STRONG' not in strength:
            continue
        fc_decision = ''
        if isinstance(fc, dict):
            for cand in fc.get('top_candidates') or []:
                if isinstance(cand, dict) and str(cand.get('ticker') or '').upper() == ticker:
                    fc_decision = _row_decision_token(cand)
                    break
        if fc_decision in ('AVOID', 'NO_DECISION') or 'AVOID' in fc_decision:
            seen.add(ticker)
            warnings.append({'ticker': ticker, 'message': FAILED_STRONG_MESSAGE})

    for ticker in ('JPPOWER',):
        if ticker in seen:
            continue
        for row in (pack.get('tomorrow_watchlist') or {}).get('top_watchlist') or []:
            if isinstance(row, dict) and str(row.get('ticker') or '').upper() == ticker:
                if _watch_score(row) >= 55 and _row_decision_token(row) in ('AVOID', 'NO_DECISION'):
                    seen.add(ticker)
                    warnings.append({'ticker': ticker, 'message': FAILED_STRONG_MESSAGE})
                break
    return warnings


def _journal_top_watch_rows(pack: dict[str, Any], fc: Any) -> list[dict[str, Any]]:
    wl = (pack.get('tomorrow_watchlist') or {}) if pack else {}
    pool: list[dict[str, Any]] = []
    for row in wl.get('top_watchlist') or wl.get('raw_candidates') or []:
        if isinstance(row, dict) and row.get('ticker'):
            pool.append(row)
    if isinstance(fc, dict):
        for row in fc.get('top_candidates') or []:
            if isinstance(row, dict) and row.get('ticker'):
                pool.append(row)
    deduped = _dedupe_ticker_rows(pool, limit=12)
    out: list[dict[str, Any]] = []
    for row in deduped:
        ticker = str(row.get('ticker') or '').upper()
        decision = _row_decision_token(row) or 'WATCH'
        if 'BUY' in decision and 'CANDIDATE' not in decision:
            decision = 'WATCH'
        score = _watch_score(row)
        reason = (
            row.get('reason')
            or row.get('logic')
            or row.get('primary_label')
            or 'Daily report candidate'
        )
        out.append({
            'ticker': ticker,
            'decision': decision if decision else 'WATCH',
            'score': score,
            'main_reason': str(reason)[:240],
            'line': f'{ticker} — {decision or "WATCH"} — {score:.0f} — {reason}',
        })
    return out


def build_scan_payload() -> dict[str, Any]:
    warnings: list[str] = []
    live_scanner: list[dict[str, Any]] = []
    watchlist_candidates: list[dict[str, Any]] = []
    memory_signals: list[dict[str, Any]] = []
    source = 'fallback'
    cache_age = 0

    scanner = _load_json(SCANNER_FILE)
    if scanner:
        source = 'runtime'
        cache_age = max(cache_age, _cache_age_seconds(path=SCANNER_FILE, data=scanner))
        for row in scanner.get('top_signals') or scanner.get('signals') or []:
            if isinstance(row, dict) and row.get('ticker'):
                live_scanner.append(_scanner_live_row(row))

    pack, pack_source, pack_warns = _load_report_pack_timed()
    warnings.extend(pack_warns)
    if pack:
        cache_age = max(cache_age, _cache_age_seconds(path=PACK_FILE, data=pack))
        if source == 'fallback':
            source = pack_source
        wl = (pack.get('tomorrow_watchlist') or {})
        for row in (wl.get('top_watchlist') or wl.get('raw_candidates') or []):
            if not isinstance(row, dict) or not row.get('ticker'):
                continue
            watchlist_candidates.append(_watchlist_candidate_row(row))

        evidence = (pack.get('external_evidence') or {})
        for row in evidence.get('top_stock_evidence') or evidence.get('items') or []:
            if not isinstance(row, dict) or not row.get('ticker'):
                continue
            memory_signals.append(_memory_scan_row(
                ticker=str(row['ticker']),
                sector=str(row.get('sector') or '—'),
                strength=str(row.get('classification') or 'EVIDENCE'),
                direction=str(row.get('direction') or 'NEUTRAL'),
                signals=[str(row.get('classification') or 'evidence')],
                pack_source='external-evidence',
            ))

    items = _dedupe_scan_items(live_scanner + watchlist_candidates + memory_signals)
    market_mode = _resolve_market_mode(pack, scanner)
    fc = (pack.get('final_confidence') or {}) if pack else {}
    summary = {
        'scanner': {
            'total_scanned': scanner.get('total_scanned') if scanner else None,
            'total_signals': scanner.get('total_signals') if scanner else None,
            'summary': (scanner.get('summary') or {}) if scanner else {},
            'last_updated': scanner.get('last_updated') if scanner else None,
        },
        'live_scanner_count': len(live_scanner),
        'watchlist_count': len(watchlist_candidates),
        'memory_signal_count': len(memory_signals),
        'mode': pack.get('market_mode') or fc.get('active_mode') or market_mode,
        'memory_fallback_count': len(memory_signals),
    }
    if not items:
        warnings.append('no_scan_items')
    payload = _payload_shell(
        'scan',
        items=items,
        summary=summary,
        source=source,
        cache_age_seconds=cache_age,
        market_mode=market_mode,
        warnings=warnings,
    )
    payload['live_scanner'] = live_scanner
    payload['watchlist_candidates'] = watchlist_candidates
    payload['memory_signals'] = memory_signals
    return payload


def build_brain_payload() -> dict[str, Any]:
    warnings: list[str] = []
    snap, snap_src, snap_warns = _load_runtime_snapshot_fast()
    warnings.extend(snap_warns)
    pack, pack_src, pack_warns = _load_report_pack_timed()
    warnings.extend(pack_warns)
    snapshot_limited = 'runtime_snapshot_missing' in warnings

    intel = {}
    if snap:
        intel = (
            snap.get('intelligence')
            or (snap.get('market_snapshot') or {}).get('intelligence')
            or (snap.get('exports') or {}).get('intelligence')
            or (snap.get('data') or {}).get('intelligence')
            or {}
        )
    items: list[dict[str, Any]] = []
    if isinstance(intel, dict):
        summary_text = intel.get('executive_summary') or intel.get('summary')
        if summary_text:
            items.append({
                'kind': 'executive_summary',
                'title': str(summary_text)[:500],
                'source': snap_src,
            })
        for opp in (intel.get('top_opportunities') or [])[:12]:
            if isinstance(opp, dict):
                items.append({'kind': 'opportunity', **opp})

    fc_raw = pack.get('final_confidence') if pack else {}
    if snapshot_limited and not _pack_final_confidence_usable(fc_raw):
        fc_file = _load_json(FINAL_CONFIDENCE_FILE)
        if _pack_final_confidence_usable(fc_file):
            fc_raw = fc_file
    fc = _normalize_final_confidence_for_summary(fc_raw, pack) if pack or fc_raw else {}
    if _pack_final_confidence_usable(fc_raw):
        for ticker in fc_raw.get('top_tickers') or []:
            if ticker:
                items.append({'kind': 'final_confidence_ticker', 'ticker': ticker})
        for row in fc_raw.get('top_candidates') or fc_raw.get('rows') or []:
            if isinstance(row, dict) and row.get('ticker'):
                items.append({'kind': 'final_confidence_row', **row})

    stock_today: dict[str, Any] = {}
    if snapshot_limited:
        stock_today = _load_json(DATA_DIR / 'stock_decision_today.json')
        if stock_today.get('ok') is True:
            top_pick = stock_today.get('top_pick')
            if isinstance(top_pick, dict) and top_pick.get('ticker'):
                items.append({'kind': 'stock_decision_top', **top_pick})
        if not pack:
            pack_reload, _, _ = _load_report_pack_timed()
            if pack_reload:
                pack = pack_reload
        if not items:
            for builder_name, builder in (
                ('market', build_market_payload),
                ('global', build_global_payload),
                ('news', build_news_payload),
            ):
                try:
                    tab_payload = builder() if builder_name != 'market' else builder(force=False)
                except TypeError:
                    tab_payload = builder()
                except Exception:
                    continue
                tab_items = tab_payload.get('items') or []
                for row in tab_items[:4]:
                    if isinstance(row, dict):
                        items.append({'kind': f'{builder_name}_fallback', **row})
        warnings.append('Runtime snapshot missing; using report cache.')

    history = _load_json(HISTORY_FILE)
    actionable = _build_actionable_candidates(pack, fc_raw) if pack or fc_raw else {}
    failed_strong = _detect_failed_strong_warnings(history, pack, fc_raw) if pack or fc_raw else []

    source = snap_src if snap else pack_src
    cache_age = max(
        _cache_age_seconds(path=RUNTIME_SNAPSHOT_CACHE, data=snap) if snap else 0,
        _cache_age_seconds(path=PACK_FILE, data=pack) if pack else 0,
    )
    summary = {
        'runtime_snapshot': snap if snap else {},
        'daily_report_pack': pack if pack else {},
        'stock_decision_today': stock_today if stock_today.get('ok') else {},
        'final_confidence': fc,
        'final_confidence_source': (
            'daily-report-pack' if _pack_final_confidence_usable(fc_raw) and not fc_raw.get('generated_at')
            else ('report_cache' if _pack_final_confidence_usable(fc_raw) else 'unavailable')
        ),
        'intelligence': intel if isinstance(intel, dict) else {},
        'actionable_candidates': actionable,
        'failed_strong_warnings': failed_strong,
    }
    return _payload_shell(
        'brain',
        items=items,
        summary=summary,
        source=source,
        cache_age_seconds=cache_age,
        market_mode=_resolve_market_mode(pack, snap, intel if isinstance(intel, dict) else {}),
        warnings=warnings,
    )


def build_govt_payload() -> dict[str, Any]:
    warnings: list[str] = []
    govt = _load_json(GOVT_FILE)
    pack, pack_src, pack_warns = _load_report_pack_timed()
    warnings.extend(pack_warns)
    snap, snap_src, snap_warns = _load_runtime_snapshot_fast()
    warnings.extend(snap_warns)

    evidence = (pack.get('external_evidence') or {}) if pack else {}
    items = _collect_govt_items(govt, pack, snap, evidence)

    source = 'runtime' if govt else pack_src
    if items and not govt:
        source = pack_src
    cache_age = max(
        _cache_age_seconds(path=GOVT_FILE, data=govt) if govt else 0,
        _cache_age_seconds(path=PACK_FILE, data=pack) if pack else 0,
        _cache_age_seconds(path=RUNTIME_SNAPSHOT_CACHE, data=snap) if snap else 0,
    )
    if not items:
        warnings.append('no_govt_items')
    return _payload_shell(
        'govt',
        items=items[:50],
        summary={
            'govt': govt,
            'external_evidence': evidence,
            'empty_message': GOVT_EMPTY_MESSAGE if not items else None,
            'brain_govt_impact': (
                (snap.get('intelligence') or {}).get('government_impact')
                if snap and isinstance(snap.get('intelligence'), dict)
                else None
            ),
        },
        source=source,
        cache_age_seconds=cache_age,
        market_mode=_resolve_market_mode(pack, govt, snap),
        warnings=warnings,
    )


def build_market_payload(*, force: bool = False) -> dict[str, Any]:
    warnings: list[str] = []
    refresh_attempted_at: Optional[str] = None
    refresh_from_api_ok = False
    if force:
        refresh_attempted_at = _now_iso()
        mode_guess = _resolve_market_mode(_load_json(PACK_FILE))
        refresh_from_api_ok, refresh_warns = _try_safe_market_force_refresh(mode_guess)
        warnings.extend(refresh_warns)
        if not refresh_from_api_ok:
            warnings.append('market_refresh_api_unavailable')

    snap, snap_src, snap_warns = _load_runtime_snapshot_fast()
    warnings.extend(snap_warns)
    freshness, fresh_warns = _timed_call(
        'source_freshness',
        lambda: __import__(
            'backend.analytics.source_freshness',
            fromlist=['get_source_freshness_report'],
        ).get_source_freshness_report(),
    )
    warnings.extend(fresh_warns)

    pack, pack_src, pack_warns = _load_report_pack_timed()
    warnings.extend(pack_warns)

    items: list[dict[str, Any]] = []
    exports = (snap.get('exports') or {}) if snap else {}
    for region_key in ('india', 'usa', 'global', 'asia'):
        block = exports.get(region_key)
        if isinstance(block, dict):
            items.append({'region': region_key, **block})
    if isinstance(freshness, dict):
        for key, row in (freshness.get('sources') or freshness.get('feeds') or {}).items():
            if isinstance(row, dict):
                items.append({'feed': key, **row})

    cache_age = max(
        _cache_age_seconds(path=RUNTIME_SNAPSHOT_CACHE, data=snap) if snap else 0,
        _cache_age_seconds(data=freshness) if isinstance(freshness, dict) else 0,
        _cache_age_seconds(path=PACK_FILE, data=pack) if pack else 0,
    )
    stale_minutes = cache_age // 60 if cache_age else 0
    market_stale = stale_minutes > MARKET_STALE_MINUTES
    market_mode = _resolve_market_mode(
        freshness if isinstance(freshness, dict) else {},
        snap,
        pack,
    )
    market_closed = _is_closed_market_mode(market_mode)
    market_data_timestamp = _pick_market_data_timestamp(snap, freshness if isinstance(freshness, dict) else {})
    underlying_age = _cache_age_seconds(data={'timestamp': market_data_timestamp}) if market_data_timestamp else cache_age
    underlying_stale_minutes = underlying_age // 60 if underlying_age else stale_minutes
    underlying_data_stale = underlying_stale_minutes > MARKET_STALE_MINUTES
    snapshot_refreshed_at = _now_iso()
    if force and not refresh_from_api_ok:
        warnings.append('manual_refresh_required')

    return _payload_shell(
        'market',
        items=items,
        summary={
            'runtime_snapshot': snap,
            'source_freshness': freshness if isinstance(freshness, dict) else {},
            'daily_report_pack': {'generated_at': pack.get('generated_at')} if pack else {},
            'market_stale': market_stale,
            'market_stale_minutes': stale_minutes,
            'market_stale_refresh_cmd': MARKET_STALE_REFRESH_CMD,
            'market_closed': market_closed,
            'closed_market_note': CLOSED_MARKET_NOTE if market_closed else None,
            'snapshot_refreshed_at': snapshot_refreshed_at,
            'market_data_timestamp': market_data_timestamp,
            'underlying_data_stale': underlying_data_stale,
            'underlying_stale_minutes': underlying_stale_minutes,
            'underlying_stale_note': UNDERLYING_DATA_STALE_NOTE if underlying_data_stale else None,
            'refresh_attempted_at': refresh_attempted_at,
            'refresh_from_api_ok': refresh_from_api_ok if force else None,
            'manual_refresh_cmd': MARKET_STALE_REFRESH_CMD,
        },
        source=snap_src if snap else (pack_src if pack else 'fallback'),
        cache_age_seconds=cache_age,
        market_mode=market_mode,
        warnings=warnings
        + (['market_data_stale'] if market_stale else [])
        + (['underlying_market_data_stale'] if underlying_data_stale else []),
    )


def _derive_global_risk_summary(
    global_data: dict[str, Any],
    evidence: dict[str, Any],
    sector_mapping: dict[str, Any],
    items: list[dict[str, Any]],
) -> str | None:
    """Best-effort global risk headline for compact Telegram/GUI surfaces."""
    if isinstance(global_data, dict):
        for key in ('risk_tone', 'tone', 'headline', 'summary', 'global_risk'):
            val = global_data.get(key)
            if val is not None and str(val).strip() not in ('', '—', '-'):
                return str(val).strip()[:120]

    if isinstance(evidence, dict):
        for row in evidence.get('top_evidence_items') or []:
            if not isinstance(row, dict):
                continue
            if str(row.get('classification') or '') == 'macro_context' and row.get('title'):
                return str(row['title']).strip()[:120]
        for bucket in ('macro_context_items', 'context_items'):
            rows = evidence.get(bucket)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and row.get('title'):
                    return str(row['title']).strip()[:120]

    for row in items:
        if not isinstance(row, dict):
            continue
        if str(row.get('classification') or '') == 'macro_context' and row.get('title'):
            return str(row['title']).strip()[:120]
        label = row.get('label') or row.get('name') or row.get('title')
        if label and str(row.get('kind') or '') in ('macro', 'global_snapshot'):
            return str(label).strip()[:120]

    commodities = sector_mapping.get('commodity_impacts') if isinstance(sector_mapping, dict) else []
    if isinstance(commodities, list):
        parts: list[str] = []
        for row in commodities[:3]:
            if isinstance(row, dict):
                parts.append(f"{row.get('commodity', '?')}: {row.get('stance', 'WATCH')}")
        if parts:
            return ', '.join(parts)
    return None


def build_global_payload() -> dict[str, Any]:
    warnings: list[str] = []
    global_data = _load_json(GLOBAL_FILE)
    pack, pack_src, pack_warns = _load_report_pack_timed()
    warnings.extend(pack_warns)
    coverage, cov_warns = _timed_call(
        'external_coverage',
        lambda: __import__(
            'backend.collectors.broker_app_collector',
            fromlist=['get_external_source_coverage'],
        ).get_external_source_coverage(),
    )
    warnings.extend(cov_warns)

    items: list[dict[str, Any]] = []
    for row in global_data.get('markets') or global_data.get('regions') or []:
        if isinstance(row, dict):
            items.append(row)
    if not items and global_data:
        items.append({'kind': 'global_snapshot', 'payload': global_data})

    evidence = (pack.get('external_evidence') or {}) if pack else {}
    macro_rows = evidence.get('macro_context')
    if isinstance(macro_rows, list):
        for row in macro_rows:
            if isinstance(row, dict):
                items.append(row)
    for row in evidence.get('context_items') or []:
        if isinstance(row, dict):
            items.append(row)

    fc_raw = (pack.get('final_confidence') or {}) if pack else {}
    sector_mapping = dict(GLOBAL_SECTOR_MAPPING)
    for row in sector_mapping.get('commodity_impacts') or []:
        if not isinstance(row, dict):
            continue
        symbols = row.get('symbols') or []
        if not symbols:
            continue
        passing = False
        for sym in symbols:
            for cand in fc_raw.get('top_candidates') or []:
                if not isinstance(cand, dict):
                    continue
                if str(cand.get('ticker') or '').upper() == str(sym).upper():
                    if _row_is_buy(cand):
                        passing = True
                    break
        if not passing:
            row['stance'] = row.get('stance') or 'WATCH'

    source = 'runtime' if global_data else pack_src
    cache_age = max(
        _cache_age_seconds(path=GLOBAL_FILE, data=global_data) if global_data else 0,
        _cache_age_seconds(path=PACK_FILE, data=pack) if pack else 0,
    )
    global_risk = _derive_global_risk_summary(global_data, evidence, sector_mapping, items)
    return _payload_shell(
        'global',
        items=items[:40],
        summary={
            'global_markets': global_data,
            'external_coverage': coverage if isinstance(coverage, dict) else {},
            'daily_report_pack': {'generated_at': pack.get('generated_at')} if pack else {},
            'sector_mapping': sector_mapping,
            'global_risk': global_risk,
            'commodity_impacts': sector_mapping.get('commodity_impacts') or [],
        },
        source=source,
        cache_age_seconds=cache_age,
        market_mode=_resolve_market_mode(pack, global_data),
        warnings=warnings,
    )


def _feed_items_for_sources(keys: list[str], limit: int = 80) -> tuple[list[dict[str, Any]], list[str]]:
    from backend.analytics.source_feed_viewer import get_source_feed

    items: list[dict[str, Any]] = []
    warnings: list[str] = []
    for key in keys:
        feed, warns = _timed_call(f'feed_{key}', lambda k=key: get_source_feed(source=k, limit=limit))
        warnings.extend(warns)
        if isinstance(feed, dict) and feed.get('ok') is True:
            for row in feed.get('items') or []:
                if isinstance(row, dict):
                    items.append(row)
        elif isinstance(feed, dict) and feed.get('warnings'):
            warnings.extend(str(w) for w in feed.get('warnings') or [])
    return items, warnings


def build_news_payload() -> dict[str, Any]:
    warnings: list[str] = []
    items, feed_warns = _feed_items_for_sources(['ET', 'MC', 'NDTV', 'CNBC'], limit=60)
    warnings.extend(feed_warns)
    coverage, cov_warns = _timed_call(
        'external_coverage',
        lambda: __import__(
            'backend.collectors.broker_app_collector',
            fromlist=['get_external_source_coverage'],
        ).get_external_source_coverage(),
    )
    warnings.extend(cov_warns)
    pack, pack_src, pack_warns = _load_report_pack_timed()
    warnings.extend(pack_warns)

    if not items:
        warnings.append('no_news_items')
    return _payload_shell(
        'news',
        items=items,
        summary={
            'external_coverage': coverage if isinstance(coverage, dict) else {},
            'daily_report_pack': {'generated_at': pack.get('generated_at')} if pack else {},
        },
        source='report_cache' if items else pack_src,
        cache_age_seconds=_cache_age_seconds(path=PACK_FILE, data=pack) if pack else 0,
        market_mode=_resolve_market_mode(pack),
        warnings=warnings,
    )


def build_tv_payload() -> dict[str, Any]:
    warnings: list[str] = []
    items, feed_warns = _feed_items_for_sources(['ET Now', 'CNBC', 'NDTV'], limit=40)
    warnings.extend(feed_warns)
    coverage, cov_warns = _timed_call(
        'external_coverage',
        lambda: __import__(
            'backend.collectors.broker_app_collector',
            fromlist=['get_external_source_coverage'],
        ).get_external_source_coverage(),
    )
    warnings.extend(cov_warns)
    if not items:
        warnings.append('no_tv_items')
    return _payload_shell(
        'tv',
        items=items,
        summary={'external_coverage': coverage if isinstance(coverage, dict) else {}},
        source='report_cache' if items else 'fallback',
        cache_age_seconds=0,
        market_mode=_resolve_market_mode(coverage if isinstance(coverage, dict) else {}),
        warnings=warnings,
    )


def build_reddit_payload() -> dict[str, Any]:
    warnings: list[str] = []
    items, feed_warns = _feed_items_for_sources(['Reddit'], limit=50)
    warnings.extend(feed_warns)

    reddit = _load_json(REDDIT_FILE)
    if not items and reddit:
        for row in reddit.get('posts') or reddit.get('top_posts') or []:
            if isinstance(row, dict) and row.get('title'):
                items.append({
                    'title': row.get('title'),
                    'url': row.get('url'),
                    'source': f"Reddit / {row.get('subreddit') or 'social'}",
                    'direction': row.get('sentiment') or 'NEUTRAL',
                    'published_at': reddit.get('last_updated'),
                })

    summary: dict[str, Any] = {
        'empty_message': 'No Reddit cache yet',
        'source_url': REDDIT_SOURCE_URL,
        'reddit_file': {'last_updated': reddit.get('last_updated')} if reddit else {},
    }
    if not items:
        warnings.append('no_reddit_cache')
    return _payload_shell(
        'reddit',
        items=items,
        summary=summary,
        source='runtime' if items else 'fallback',
        cache_age_seconds=_cache_age_seconds(path=REDDIT_FILE, data=reddit) if reddit else 0,
        market_mode='RESEARCH_MODE',
        warnings=warnings,
    )


def build_calib_payload() -> dict[str, Any]:
    warnings: list[str] = []
    calibration = _load_json(CALIBRATION_FILE)
    fc = _load_json(FINAL_CONFIDENCE_FILE)
    if not calibration:
        calibration, cal_warns = _timed_call(
            'confidence_calibration',
            lambda: __import__(
                'backend.analytics.confidence_calibration_engine',
                fromlist=['get_calibration_dashboard'],
            ).get_calibration_dashboard(),
        )
        warnings.extend(cal_warns)
    if not fc:
        fc, fc_warns = _timed_call(
            'final_confidence',
            lambda: __import__(
                'backend.analytics.final_confidence_fusion',
                fromlist=['get_final_confidence_dashboard'],
            ).get_final_confidence_dashboard(limit=50),
        )
        warnings.extend(fc_warns)

    pack, pack_src, pack_warns = _load_report_pack_timed()
    warnings.extend(pack_warns)
    if pack:
        calibration = calibration or (pack.get('confidence_calibration') or {})
        fc = fc or (pack.get('final_confidence') or {})

    items: list[dict[str, Any]] = []
    recs = _calibration_recs_from_sources(calibration, pack, fc)
    for rec in recs:
        if isinstance(rec, dict):
            items.append({'kind': 'calibration_rec', **rec})
        elif isinstance(rec, str) and rec.strip():
            items.append({'kind': 'calibration_rec', 'message': rec})
    if isinstance(fc, dict):
        for row in fc.get('top_candidates') or fc.get('rows') or []:
            if isinstance(row, dict):
                items.append({'kind': 'final_confidence_row', **row})
    source = 'report_cache' if calibration or fc else pack_src
    cache_age = max(
        _cache_age_seconds(path=CALIBRATION_FILE, data=calibration) if calibration else 0,
        _cache_age_seconds(path=FINAL_CONFIDENCE_FILE, data=fc) if fc else 0,
        _cache_age_seconds(path=PACK_FILE, data=pack) if pack else 0,
    )
    return _payload_shell(
        'calib',
        items=items[:50],
        summary={
            'confidence_calibration': calibration if isinstance(calibration, dict) else {},
            'final_confidence': fc if isinstance(fc, dict) else {},
            'daily_report_pack': pack if pack else {},
            'calibration_recommendations': recs,
        },
        source=source,
        cache_age_seconds=cache_age,
        market_mode=_resolve_market_mode(pack, fc if isinstance(fc, dict) else {}),
        warnings=warnings,
    )


def build_journal_payload() -> dict[str, Any]:
    warnings: list[str] = []
    history = _load_json(HISTORY_FILE)
    pack, pack_src, pack_warns = _load_report_pack_timed()
    warnings.extend(pack_warns)
    fc = _load_json(FINAL_CONFIDENCE_FILE)

    items: list[dict[str, Any]] = []
    for row in history.get('predictions') or []:
        if isinstance(row, dict):
            items.append(row)

    fc_pack = (pack.get('final_confidence') if pack else {}) or fc
    actionable = _build_actionable_candidates(pack, fc_pack) if pack else {}
    top_watch = _journal_top_watch_rows(pack, fc_pack) if pack else []
    failed_strong = _detect_failed_strong_warnings(history, pack, fc_pack) if pack else []

    if not items and top_watch:
        for row in top_watch:
            items.append({'kind': 'top_watch', **row})

    if not items:
        warnings.append('no_journal_items')
    return _payload_shell(
        'journal',
        items=items[:80],
        summary={
            'history': {'count': len(history.get('predictions') or [])} if history else {},
            'final_confidence': _normalize_final_confidence_for_summary(fc_pack, pack) if pack else (fc or {}),
            'daily_report_pack': pack if pack else {},
            'top_watch': top_watch,
            'top_watch_label': 'WATCH is not BUY. It means wait for confirmation.',
            'actionable_candidates': actionable,
            'failed_strong_warnings': failed_strong,
        },
        source='runtime' if history else pack_src,
        cache_age_seconds=_cache_age_seconds(path=HISTORY_FILE, data=history) if history else 0,
        market_mode=_resolve_market_mode(pack, history),
        warnings=warnings,
    )


_TAB_BUILDERS: dict[str, Callable[[], dict[str, Any]]] = {
    'brain': build_brain_payload,
    'govt': build_govt_payload,
    'scan': build_scan_payload,
    'market': build_market_payload,
    'global': build_global_payload,
    'news': build_news_payload,
    'tv': build_tv_payload,
    'reddit': build_reddit_payload,
    'calib': build_calib_payload,
    'journal': build_journal_payload,
}


def build_aihub_tab_payload(
    tab: str,
    *,
    force_refresh: bool = False,
    cache_only: bool = False,
) -> dict[str, Any]:
    """Build aggregated AI Hub tab payload (partial OK on source failures)."""
    key = _normalize_tab(tab)
    if key not in VALID_TABS:
        return {
            'ok': False,
            'tab': key or str(tab),
            'generated_at': _now_iso(),
            'market_mode': 'RESEARCH_MODE',
            'source': 'fallback',
            'cache_age_seconds': 0,
            'items': [],
            'summary': {},
            'warnings': ['invalid_tab'],
            'error': 'invalid_tab',
        }

    if cache_only and not force_refresh:
        cached = load_aihub_tab_cache(key)
        if cached:
            cached.setdefault('ok', True)
            cached['source'] = cached.get('source') or 'disk_cache'
            cached.setdefault('tab', key)
            return cached
        return _aihub_tab_cache_placeholder(key)

    builder = _TAB_BUILDERS[key]
    try:
        if key == 'market' and force_refresh:
            payload = build_market_payload(force=True)
        else:
            payload = builder()
    except Exception as exc:
        return {
            'ok': False,
            'tab': key,
            'generated_at': _now_iso(),
            'market_mode': 'RESEARCH_MODE',
            'source': 'fallback',
            'cache_age_seconds': 0,
            'items': [],
            'summary': {},
            'warnings': [f'tab_build_failed:{type(exc).__name__}'],
            'error': str(exc)[:200],
        }
    if not isinstance(payload, dict):
        return {
            'ok': False,
            'tab': key,
            'generated_at': _now_iso(),
            'market_mode': 'RESEARCH_MODE',
            'source': 'fallback',
            'cache_age_seconds': 0,
            'items': [],
            'summary': {},
            'warnings': ['tab_build_failed'],
            'error': 'tab_build_failed',
        }
    payload.setdefault('ok', True)
    payload.setdefault('tab', key)
    save_aihub_tab_cache(key, payload)
    return payload
