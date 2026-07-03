"""
All-cap top gainers discovery — Phase 4B.7.

Derives market-wide top gainers from scanner/live quote data.
Paper/research only — no LLM calls.
"""

from __future__ import annotations

from typing import Any

from backend.trading.opening_rally_radar import (
    SCANNER_FILE,
    _load_json,
    _normalize_ticker,
    _safe_float,
    _scanner_index,
    _sector_for_symbol,
    pick_primary_theme_for_symbol,
    theme_matches_for_symbol,
)

STAGE = '4B.8'

BUCKET_LARGE = 'large cap'
BUCKET_MID = 'mid cap'
BUCKET_SMALL = 'small cap'
BUCKET_BROAD = 'Nifty 500 / broad market'
BUCKET_NEW = 'new listings / demerged'

LARGE_CAP_TICKERS = frozenset({
    'INFY', 'TCS', 'HCLTECH', 'WIPRO', 'TECHM', 'LTIM', 'COFORGE', 'PERSISTENT',
    'HDFCBANK', 'ICICIBANK', 'SBIN', 'AXISBANK', 'KOTAKBANK', 'BHARTIARTL',
    'RELIANCE', 'ITC', 'LT', 'MARUTI', 'TITAN', 'ASIANPAINT', 'NESTLEIND',
    'M&M', 'BAJFINANCE', 'SUNPHARMA', 'ULTRACEMCO', 'POWERGRID', 'NTPC',
})

MID_CAP_TICKERS = frozenset({
    'SONACOMS', 'AEGISLOG', 'THANGAMAYL', 'COFORGE', 'PERSISTENT', 'MPHASIS',
    'INDHOTEL', 'AUROPHARMA', 'BHEL', 'IRCTC', 'POLYCAB', 'DIXON', 'APLAPOLLO',
})

NEW_LISTING_DEMERGER_TICKERS = frozenset({
    'VISL', 'VOGL', 'VEDPOWER', 'VALIND', 'VEDL',
})

PUMP_ILLIQUID_TICKERS = frozenset({
    'SUZLON', 'YESBANK', 'IDEA', 'PCJEWELLER',
})

MIN_GAINER_PCT = 2.0
MIN_VOLUME_RATIO_TRADECARD = 0.35
CIRCUIT_LOW_LIQ_VOL = 0.25
CIRCUIT_MOVE_PCT = 9.5


def _classify_bucket(sym: str, row: dict[str, Any]) -> str:
    ticker = _normalize_ticker(sym)
    if ticker in NEW_LISTING_DEMERGER_TICKERS:
        return BUCKET_NEW
    if ticker in LARGE_CAP_TICKERS:
        return BUCKET_LARGE
    if ticker in MID_CAP_TICKERS:
        return BUCKET_MID
    price = _safe_float(row.get('price') or row.get('last_price'))
    if price >= 1500:
        return BUCKET_LARGE
    if price >= 300:
        return BUCKET_MID
    if price >= 50:
        return BUCKET_SMALL
    universe = str(row.get('universe') or '').lower()
    if '500' in universe or 'nifty' in universe:
        return BUCKET_BROAD
    return BUCKET_BROAD if _safe_float(row.get('change_percent')) >= 3 else BUCKET_SMALL


def _is_bullish_gainer(row: dict[str, Any]) -> bool:
    change = _safe_float(row.get('change_percent'))
    direction = str(row.get('direction') or '').upper()
    if change < MIN_GAINER_PCT:
        return False
    if direction == 'BEARISH':
        return False
    return True


def _detect_new_listing(row: dict[str, Any], sym: str) -> bool:
    if _normalize_ticker(sym) in NEW_LISTING_DEMERGER_TICKERS:
        return True
    blob = ' '.join(
        str(row.get(k) or '')
        for k in ('signals', 'signal_details', 'detail', 'notes', 'headline')
    ).lower()
    if isinstance(row.get('signals'), list):
        blob += ' ' + ' '.join(str(s) for s in row.get('signals'))
    return any(k in blob for k in ('new listing', 'demerger', 'demerged', 'listing debut'))


def _detect_demerger(sym: str, row: dict[str, Any]) -> bool:
    ticker = _normalize_ticker(sym)
    if ticker in {'VISL', 'VOGL', 'VEDPOWER'}:
        return True
    blob = str(row.get('sector') or '') + str(row.get('signals') or '')
    return 'demerger' in blob.lower() or 'vedanta' in blob.lower()


def _52_week_high_momentum(row: dict[str, Any]) -> bool:
    price = _safe_float(row.get('price') or row.get('last_price'))
    high = _safe_float(row.get('high_20d') or row.get('high_52w'))
    return bool(price and high and price >= high * 0.995)


def _gainer_why_lines(
    sym: str,
    row: dict[str, Any],
    meta: dict[str, Any],
    *,
    sector_breadth_row: dict[str, Any] | None = None,
) -> list[str]:
    parts: list[str] = []
    bucket = meta.get('bucket') or ''
    rank = int(meta.get('rank_in_bucket') or 0)
    change = _safe_float(row.get('change_percent'))
    themes = theme_matches_for_symbol(sym)
    primary_theme = pick_primary_theme_for_symbol(sym, themes, sector_breadth_row)
    if rank <= 3:
        parts.append(f'top {bucket} gainer')
    elif rank <= 10:
        parts.append(f'top-10 {bucket} gainer')
    else:
        parts.append(f'{bucket} gainer')
    if primary_theme:
        parts.append(f'{primary_theme.replace("_", " ")} theme')
    if meta.get('sector_breadth'):
        parts.append(str(meta.get('sector_breadth')))
    if meta.get('new_listing'):
        parts.append('new listing momentum')
    if meta.get('demerger'):
        parts.append('demerged entity momentum')
    if _52_week_high_momentum(row):
        parts.append('52-week-high momentum')
    if change >= 5 and not meta.get('has_catalyst'):
        parts.append('dip-buying rebound' if _sector_for_symbol(sym) == 'IT' else 'price ignition')
    if not parts:
        parts.append(f'+{change:.1f}% move')
    return list(parts)


def _gainer_risk_assessment(sym: str, row: dict[str, Any], meta: dict[str, Any]) -> tuple[bool, str]:
    """Return (blocked, reason)."""
    ticker = _normalize_ticker(sym)
    vol_ratio = _safe_float(row.get('volume_ratio'))
    change = _safe_float(row.get('change_percent'))
    volume = _safe_float(row.get('volume'))

    if ticker in PUMP_ILLIQUID_TICKERS:
        return True, 'known pump/illiquid risk'
    if change >= CIRCUIT_MOVE_PCT and vol_ratio < CIRCUIT_LOW_LIQ_VOL:
        return True, 'circuit-only/low liquidity'
    if vol_ratio < 0.15 and volume < 50000 and change >= 8:
        return True, 'low liquidity / no volume'
    if meta.get('new_listing') and change >= 12 and vol_ratio < MIN_VOLUME_RATIO_TRADECARD:
        return True, 'new listing circuit/chase risk'
    return False, ''


def _score_gainer_boost(meta: dict[str, Any], row: dict[str, Any], *, has_catalyst: bool, sector_breadth: bool, previous_mover: bool) -> tuple[float, float, list[str]]:
    score_delta = 0.0
    penalty = 0.0
    notes: list[str] = []
    rank = int(meta.get('rank_in_bucket') or 99)
    if rank <= 3:
        score_delta += 12
        notes.append('top-3 gainer boost')
    elif rank <= 10:
        score_delta += 8
        notes.append('top-10 gainer boost')
    if sector_breadth:
        score_delta += 10
    if has_catalyst:
        score_delta += 8
    if previous_mover:
        score_delta += 6
    if meta.get('new_listing') or meta.get('demerger'):
        vol_ratio = _safe_float(row.get('volume_ratio'))
        if vol_ratio >= MIN_VOLUME_RATIO_TRADECARD:
            score_delta += 10
            notes.append('new listing/demerger volume confirm')
    vol_ratio = _safe_float(row.get('volume_ratio'))
    change = _safe_float(row.get('change_percent'))
    if vol_ratio < CIRCUIT_LOW_LIQ_VOL and change >= 8:
        penalty += 12
        notes.append('low liquidity penalty')
    if change >= 8 and not has_catalyst and not sector_breadth:
        penalty += 8
        notes.append('no news/no breadth penalty')
    if change >= 6 and meta.get('extended'):
        penalty += 10
        notes.append('extended opening range penalty')
    return score_delta, penalty, notes


def scan_all_cap_gainers(
    *,
    scanner_payload: dict[str, Any] | None = None,
    catalyst_map: dict[str, dict[str, Any]] | None = None,
    previous_movers: set[str] | None = None,
    sector_breadth_symbols: set[str] | None = None,
    sector_breadth_map: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Scan all-cap top gainers and build promotion map for radar merge."""
    scanner_index = _scanner_index(scanner_payload)
    catalyst_map = catalyst_map or {}
    previous_movers = previous_movers or set()
    sector_breadth_symbols = sector_breadth_symbols or set()
    sector_breadth_map = sector_breadth_map or {}

    bullish: list[tuple[str, dict[str, Any]]] = []
    for sym, row in scanner_index.items():
        if _is_bullish_gainer(row):
            bullish.append((_normalize_ticker(sym), row))
    bullish.sort(key=lambda item: _safe_float(item[1].get('change_percent')), reverse=True)

    buckets: dict[str, list[dict[str, Any]]] = {
        BUCKET_LARGE: [],
        BUCKET_MID: [],
        BUCKET_SMALL: [],
        BUCKET_BROAD: [],
        BUCKET_NEW: [],
    }
    by_symbol: dict[str, dict[str, Any]] = {}

    for sym, row in bullish:
        bucket = _classify_bucket(sym, row)
        if bucket not in buckets:
            bucket = BUCKET_BROAD
        rank = len(buckets[bucket]) + 1
        if rank > 10:
            continue
        new_listing = _detect_new_listing(row, sym)
        demerger = _detect_demerger(sym, row)
        meta = {
            'bucket': bucket,
            'rank_in_bucket': rank,
            'change_percent': _safe_float(row.get('change_percent')),
            'volume_ratio': _safe_float(row.get('volume_ratio')),
            'new_listing': new_listing,
            'demerger': demerger,
            'has_catalyst': sym in catalyst_map,
            'extended': _safe_float(row.get('change_percent')) >= 6.0,
        }
        blocked, risk_reason = _gainer_risk_assessment(sym, row, meta)
        meta['risk_blocked'] = blocked
        meta['risk_reason'] = risk_reason
        sb_row = sector_breadth_map.get(sym)
        meta['why'] = _gainer_why_lines(sym, row, meta, sector_breadth_row=sb_row)
        by_symbol[sym] = dict(meta)
        buckets[bucket].append({'ticker': sym, **row, **dict(meta)})

    bucket_count = sum(1 for b in buckets.values() if b)
    total = len(by_symbol)
    print(f'[ALL_CAP_GAINERS_SCAN] buckets={bucket_count} total={total}', flush=True)

    promoted: list[str] = []
    missed: list[str] = []

    for sym, meta in by_symbol.items():
        row = scanner_index.get(sym) or {}
        blocked = meta.get('risk_blocked')
        if blocked:
            print(
                f'[TOP_GAINER_RISK_FILTER] symbol={sym} reason={meta.get("risk_reason")}',
                flush=True,
            )
            if _safe_float(meta.get('change_percent')) >= 5:
                missed.append(sym)
                print(
                    f'[TOP_GAINER_MISSED_OPPORTUNITY] symbol={sym} move={meta.get("change_percent")}',
                    flush=True,
                )
            continue
        if meta.get('rank_in_bucket', 99) <= 10 and _safe_float(meta.get('change_percent')) >= MIN_GAINER_PCT:
            promoted.append(sym)
            print(
                f'[GAINER_PROMOTED_TO_RADAR] symbol={sym} bucket={meta.get("bucket")} '
                f'score_rank={meta.get("rank_in_bucket")}',
                flush=True,
            )
        if meta.get('new_listing'):
            print(f'[NEW_LISTING_MOMENTUM] symbol={sym}', flush=True)
        if meta.get('demerger'):
            print(f'[DEMERGER_MOMENTUM] symbol={sym}', flush=True)

    return {
        'ok': True,
        'stage': STAGE,
        'buckets': buckets,
        'by_symbol': by_symbol,
        'promoted_symbols': promoted,
        'missed_symbols': missed,
        'total_scanned': total,
    }


def apply_gainer_context_to_candidate(
    row: dict[str, Any],
    gainer_meta: dict[str, Any] | None,
    *,
    scanner_row: dict[str, Any] | None,
    has_catalyst: bool,
    sector_breadth: bool,
    previous_mover: bool,
) -> dict[str, Any]:
    """Apply gainer boosts/penalties and optional state override."""
    if not gainer_meta or gainer_meta.get('risk_blocked'):
        return row

    boost, penalty, _notes = _score_gainer_boost(
        gainer_meta,
        scanner_row or {},
        has_catalyst=has_catalyst,
        sector_breadth=sector_breadth,
        previous_mover=previous_mover,
    )
    score = int(row.get('score') or 0) + int(boost) - int(penalty)
    score = max(0, score)
    row = dict(row)
    row['score'] = score
    row['gainer_promoted'] = True
    row['gainer_bucket'] = gainer_meta.get('bucket')
    row['gainer_rank'] = gainer_meta.get('rank_in_bucket')

    why = list(row.get('why') or [])
    for part in list(gainer_meta.get('why') or []):
        if part not in why:
            why.insert(0, part)
    row['why'] = list(why[:6])

    state = str(row.get('state') or '')
    change = _safe_float(row.get('change_percent'))
    vol_ratio = _safe_float(row.get('volume_ratio'))

    if gainer_meta.get('demerger') and vol_ratio >= MIN_VOLUME_RATIO_TRADECARD:
        row['state'] = 'DEMERGER_MOMENTUM'
    elif gainer_meta.get('new_listing') and vol_ratio >= MIN_VOLUME_RATIO_TRADECARD:
        row['state'] = 'NEW_LISTING_MOMENTUM'
    elif int(gainer_meta.get('rank_in_bucket') or 99) <= 10 and change >= MIN_GAINER_PCT:
        if gainer_meta.get('extended') or row.get('extended') or change >= 8:
            row['state'] = 'PULLBACK_ONLY_PLAN'
            row['pullback_only'] = True
        elif vol_ratio >= MIN_VOLUME_RATIO_TRADECARD:
            row['state'] = 'TOP_GAINER_CONFIRM'
        elif change >= 3 and vol_ratio >= 1.0:
            row['state'] = 'PRICE_IGNITION'
    elif state == 'REJECTED' and change >= MIN_GAINER_PCT and vol_ratio >= MIN_VOLUME_RATIO_TRADECARD:
        row['state'] = 'TOP_GAINER_CONFIRM'

    if gainer_meta.get('risk_blocked'):
        row['state'] = 'CHASE_RISK'

    return row
