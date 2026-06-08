"""
Broker/app prediction intelligence — external evidence separate from our predictions.

Normalizes broker picks, builds deterministic IDs, compares with canonical predictions,
and tracks source-level reliability (read-only analytics).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from typing import Any

from backend.analytics.broker_consensus_engine import (
    calculate_consensus,
    get_broker_predictions_for_ticker,
    normalize_broker_stance as _consensus_normalize_stance,
)

WATCH_TOKENS = frozenset(
    {'WATCH', 'WATCHLIST', 'WAIT', 'ADD_TO_WATCHLIST', 'ON_WATCHLIST', 'TRACK'}
)
OUTCOME_TARGET_TYPES = frozenset(
    {
        'eod_gainer',
        'eod_loser',
        'eod_gainers',
        'eod_losers',
        'gainer',
        'loser',
        'gainers',
        'losers',
        'outcome',
        'eod_mover',
        'top_gainer',
        'top_loser',
    }
)
OUTCOME_TEXT_RE = re.compile(
    r'\b(top\s+)?(gainers?|losers?|eod\s+movers?|ended\s+(higher|lower)|'
    r'most\s+active|52[\s-]?week)\b',
    re.IGNORECASE,
)
BULLISH_TEXT_RE = re.compile(
    r'\b(buy|bullish|accumulate|outperform|long|upgrade|positive)\b',
    re.IGNORECASE,
)
BEARISH_TEXT_RE = re.compile(
    r'\b(sell|bearish|reduce|underperform|short|downgrade|negative)\b',
    re.IGNORECASE,
)
WATCH_TEXT_RE = re.compile(
    r'\b(watchlist|watch\s+list|add\s+to\s+watch|on\s+watch)\b',
    re.IGNORECASE,
)
OUR_BULLISH = frozenset({'BUY', 'BULLISH', 'LONG', 'ACCUMULATE', 'OUTPERFORM'})
OUR_BEARISH = frozenset({'SELL', 'BEARISH', 'SHORT', 'REDUCE', 'UNDERPERFORM'})
LOW_INFERENCE_CONFIDENCE = 0.35


def _log_error(message: str) -> None:
    print(f'[BROKER_INTEL] error: {message}', file=sys.stderr)


def _parse_json_field(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _slug_source(value: str | None) -> str:
    text = str(value or '').strip()
    if not text:
        return 'unknown'
    slug = re.sub(r'[^A-Za-z0-9]+', '_', text).strip('_').lower()
    return slug or 'unknown'


def _normalize_ticker(value: str | None) -> str:
    return str(value or '').strip().upper()


def _broker_date_for_id(payload: dict, raw: dict | None = None) -> str:
    raw = raw or _parse_json_field(payload.get('raw_payload'))
    for container in (raw, payload):
        if not isinstance(container, dict):
            continue
        for key in ('prediction_date', 'pick_date', 'date', 'published_at', 'created_at'):
            val = container.get(key)
            if val is None:
                continue
            text = str(val).strip()
            if len(text) >= 10 and text[4] == '-' and text[7] == '-':
                return text[:10]
            if text:
                return text[:10]
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _combined_text(payload: dict, raw: dict) -> str:
    parts: list[str] = []
    for key in ('notes', 'headline', 'title', 'summary', 'reason', 'comment'):
        val = payload.get(key) or raw.get(key)
        if val is not None and str(val).strip():
            parts.append(str(val).strip())
    return ' '.join(parts)


def is_outcome_evidence(item: dict) -> bool:
    """EOD gainers/losers and similar rows are outcomes, not broker predictions."""
    if not isinstance(item, dict):
        return False
    raw = _parse_json_field(item.get('raw_payload'))
    target_type = str(item.get('target_type') or raw.get('target_type') or '').strip().lower()
    if target_type in OUTCOME_TARGET_TYPES:
        return True
    record_type = str(item.get('record_type') or raw.get('record_type') or '').strip().lower()
    if record_type in {'outcome', 'eod_gainer', 'eod_loser', 'gainer', 'loser'}:
        return True
    if item.get('is_outcome') is True or raw.get('is_outcome') is True:
        return True
    text = _combined_text(item, raw)
    if text and OUTCOME_TEXT_RE.search(text):
        return True
    stance = str(item.get('bullish_or_bearish') or item.get('stance') or '').strip().upper()
    if stance in {'GAINER', 'LOSER', 'TOP_GAINER', 'TOP_LOSER', 'EOD_GAINER', 'EOD_LOSER'}:
        return True
    return False


def infer_direction_from_text(text: str) -> tuple[str | None, float | None]:
    """Infer BULLISH/BEARISH/WATCH from free text with low confidence."""
    if not text or not str(text).strip():
        return None, None
    body = str(text)
    if WATCH_TEXT_RE.search(body):
        return 'WATCH', LOW_INFERENCE_CONFIDENCE
    bullish = bool(BULLISH_TEXT_RE.search(body))
    bearish = bool(BEARISH_TEXT_RE.search(body))
    if bullish and not bearish:
        return 'BULLISH', LOW_INFERENCE_CONFIDENCE
    if bearish and not bullish:
        return 'BEARISH', LOW_INFERENCE_CONFIDENCE
    return None, None


def normalize_broker_pick_stance(
    value: str | None,
    *,
    text_hint: str | None = None,
) -> tuple[str | None, float | None, list[str]]:
    """
    Normalize broker stance. WATCH/watchlist stays WATCH (never BULLISH).
    Returns (stance, inferred_confidence_or_none, normalization_notes).
    """
    notes: list[str] = []
    if value is None and text_hint:
        inferred, conf = infer_direction_from_text(text_hint)
        if inferred:
            notes.append('inferred_from_text')
            return inferred, conf, notes
        return None, None, notes

    token = str(value or '').strip().upper().replace(' ', '_').replace('-', '_')
    if not token:
        if text_hint:
            inferred, conf = infer_direction_from_text(text_hint)
            if inferred:
                notes.append('inferred_from_text')
                return inferred, conf, notes
        return None, None, notes

    if token in WATCH_TOKENS or 'WATCHLIST' in token or token == 'WATCH':
        notes.append('watchlist_not_bullish')
        return 'WATCH', None, notes

    if token in {'GAINER', 'LOSER', 'TOP_GAINER', 'TOP_LOSER'}:
        notes.append('rejected_outcome_stance')
        return None, None, notes

    mapped = _consensus_normalize_stance(token)
    if mapped == 'NEUTRAL' and token not in {'HOLD', 'NEUTRAL'} and 'WATCH' in token:
        notes.append('watchlist_not_bullish')
        return 'WATCH', None, notes
    return mapped, None, notes


def make_broker_prediction_id(payload: dict) -> str:
    """Deterministic ID: broker:<source>:<ticker>:<date>:<hash>."""
    raw = _parse_json_field(payload.get('raw_payload'))
    source = _slug_source(payload.get('broker_source') or raw.get('broker_source'))
    ticker = _normalize_ticker(payload.get('ticker') or raw.get('ticker'))
    date_part = _broker_date_for_id(payload, raw)
    stance = str(payload.get('bullish_or_bearish') or '').strip().upper()
    target_type = str(payload.get('target_type') or '').strip().lower()
    timeframe = str(payload.get('timeframe') or '').strip().lower()
    headline = str(payload.get('headline') or raw.get('headline') or '')[:120]
    parts = '|'.join((source, ticker, date_part, stance, target_type, timeframe, headline))
    digest = hashlib.sha256(parts.encode('utf-8')).hexdigest()[:12]
    return f'broker:{source}:{ticker}:{date_part}:{digest}'


def prepare_broker_pick_for_import(
    item: dict,
    *,
    source_hint: str | None = None,
) -> dict | None:
    """
    Validate and normalize a broker inbox item for upsert_broker_prediction.
    Returns None when the row is invalid or outcome-only evidence.
    """
    if not isinstance(item, dict):
        return None
    if is_outcome_evidence(item):
        return None

    raw = _parse_json_field(item.get('raw_payload'))
    broker_source = (
        item.get('broker_source')
        or source_hint
        or raw.get('broker_source')
        or raw.get('source')
    )
    ticker = item.get('ticker') or raw.get('ticker') or raw.get('symbol')
    if not str(broker_source or '').strip() or not str(ticker or '').strip():
        return None

    text_hint = _combined_text(item, raw)
    raw_stance = (
        item.get('bullish_or_bearish')
        or item.get('stance')
        or item.get('direction')
        or raw.get('bullish_or_bearish')
        or raw.get('stance')
    )
    stance, inferred_conf, norm_notes = normalize_broker_pick_stance(
        raw_stance,
        text_hint=text_hint,
    )
    if stance is None:
        return None

    confidence = item.get('confidence')
    if confidence is None and inferred_conf is not None:
        confidence = inferred_conf
    if confidence is not None:
        try:
            confidence = float(confidence)
            if inferred_conf is not None:
                confidence = min(confidence, 0.55)
        except (TypeError, ValueError):
            confidence = inferred_conf

    merged_raw = {**raw}
    for key in ('notes', 'headline', 'prediction_date', 'pick_date'):
        if item.get(key) is not None:
            merged_raw[key] = item[key]
    if norm_notes:
        merged_raw['normalization_notes'] = norm_notes

    payload: dict[str, Any] = {
        'broker_source': str(broker_source).strip(),
        'ticker': _normalize_ticker(str(ticker)),
        'bullish_or_bearish': stance,
        'target_type': item.get('target_type') or raw.get('target_type'),
        'timeframe': item.get('timeframe') or raw.get('timeframe'),
        'confidence': confidence,
        'raw_payload': merged_raw,
    }
    if item.get('created_at'):
        payload['created_at'] = item['created_at']

    prediction_id = make_broker_prediction_id(payload)
    payload['prediction_id'] = prediction_id
    payload['dedupe_key'] = prediction_id
    return payload


def _our_direction_token(direction: str | None) -> str | None:
    if direction is None:
        return None
    token = str(direction).strip().upper()
    if token in OUR_BULLISH:
        return 'BULLISH'
    if token in OUR_BEARISH:
        return 'BEARISH'
    if token in {'WATCH', 'HOLD', 'NEUTRAL'}:
        return 'NEUTRAL'
    return token


def _broker_direction_token(stance: str | None) -> str | None:
    if stance is None:
        return None
    token = str(stance).strip().upper()
    if token == 'WATCH':
        return 'NEUTRAL'
    if token in {'BULLISH', 'BEARISH', 'NEUTRAL'}:
        return token
    mapped = _consensus_normalize_stance(token)
    return mapped


def _directions_agree(our_dir: str | None, broker_dir: str | None) -> bool | None:
    if not our_dir or not broker_dir:
        return None
    if our_dir == broker_dir:
        return True
    if our_dir == 'NEUTRAL' or broker_dir == 'NEUTRAL':
        return None
    return False


def _fetch_all_broker_rows() -> list[dict]:
    try:
        from backend.storage.market_memory_db import get_connection, init_market_memory_db

        if not init_market_memory_db():
            return []
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT id, prediction_id, broker_source, ticker, bullish_or_bearish,
                       target_type, timeframe, confidence, raw_payload, created_at
                FROM broker_predictions
                ORDER BY created_at DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
    except Exception as exc:
        _log_error(f'_fetch_all_broker_rows failed: {exc}')
        return []


def _fetch_recent_predictions(limit: int = 500) -> list[dict]:
    try:
        from backend.storage.market_memory_db import get_connection, init_market_memory_db

        if not init_market_memory_db():
            return []
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT prediction_id, ticker, timestamp, source, direction, confidence
                FROM predictions
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
    except Exception as exc:
        _log_error(f'_fetch_recent_predictions failed: {exc}')
        return []


def get_intelligence_stats() -> dict[str, Any]:
    """High-level broker_predictions table stats."""
    from backend.storage.market_memory_db import get_market_memory_stats

    stats = get_market_memory_stats()
    rows = _fetch_all_broker_rows()
    sources: dict[str, int] = {}
    tickers: dict[str, int] = {}
    stances: dict[str, int] = {}
    for row in rows:
        src = str(row.get('broker_source') or 'unknown')
        sources[src] = sources.get(src, 0) + 1
        tick = str(row.get('ticker') or '').upper()
        if tick:
            tickers[tick] = tickers.get(tick, 0) + 1
        stance = str(row.get('bullish_or_bearish') or 'UNKNOWN').upper()
        stances[stance] = stances.get(stance, 0) + 1

    top_sources = sorted(sources.items(), key=lambda x: (-x[1], x[0]))[:10]
    top_tickers = sorted(tickers.items(), key=lambda x: (-x[1], x[0]))[:10]

    return {
        'ok': True,
        'db_path': stats.get('db_path'),
        'broker_predictions': stats.get('broker_predictions', 0),
        'unique_sources': len(sources),
        'unique_tickers': len(tickers),
        'stance_breakdown': stances,
        'top_sources': [{'source': s, 'count': c} for s, c in top_sources],
        'top_tickers': [{'ticker': t, 'count': c} for t, c in top_tickers],
        'disclaimer': 'External broker/app evidence — not our final prediction.',
    }


def get_source_performance(*, limit_days: int | None = None) -> list[dict[str, Any]]:
    """
    Per-source pick counts and alignment hints vs our predictions (same ticker, latest each).
    """
    broker_rows = _fetch_all_broker_rows()
    our_rows = _fetch_recent_predictions(limit=1000)
    our_by_ticker: dict[str, dict] = {}
    for row in our_rows:
        tick = str(row.get('ticker') or '').upper()
        if tick and tick not in our_by_ticker:
            our_by_ticker[tick] = row

    buckets: dict[str, dict[str, Any]] = {}
    for row in broker_rows:
        src = str(row.get('broker_source') or 'unknown')
        bucket = buckets.setdefault(
            src,
            {
                'broker_source': src,
                'pick_count': 0,
                'stances': {},
                'compared': 0,
                'agreements': 0,
                'conflicts': 0,
                'neutral_or_unknown': 0,
            },
        )
        bucket['pick_count'] += 1
        stance = str(row.get('bullish_or_bearish') or 'UNKNOWN').upper()
        bucket['stances'][stance] = bucket['stances'].get(stance, 0) + 1

        tick = str(row.get('ticker') or '').upper()
        ours = our_by_ticker.get(tick)
        if not ours:
            continue
        our_dir = _our_direction_token(ours.get('direction'))
        broker_dir = _broker_direction_token(row.get('bullish_or_bearish'))
        agree = _directions_agree(our_dir, broker_dir)
        if agree is None:
            bucket['neutral_or_unknown'] += 1
            continue
        bucket['compared'] += 1
        if agree:
            bucket['agreements'] += 1
        else:
            bucket['conflicts'] += 1

    result: list[dict[str, Any]] = []
    for src, bucket in sorted(buckets.items(), key=lambda x: (-x[1]['pick_count'], x[0])):
        compared = bucket['compared']
        alignment_rate = round(bucket['agreements'] / compared, 4) if compared else None
        reliability_score = None
        if compared >= 3 and alignment_rate is not None:
            reliability_score = round(0.5 + alignment_rate * 0.5, 4)
        bucket['alignment_rate'] = alignment_rate
        bucket['reliability_score'] = reliability_score
        bucket['warnings'] = ['low_sample'] if compared < 3 else []
        result.append(bucket)
    return result


def get_ticker_intelligence(ticker: str, *, timeframe: str | None = None) -> dict[str, Any]:
    """Broker evidence + consensus for one ticker."""
    normalized = _normalize_ticker(ticker)
    picks = get_broker_predictions_for_ticker(normalized, timeframe=timeframe)
    consensus = calculate_consensus(picks)
    our_rows = [r for r in _fetch_recent_predictions(200) if str(r.get('ticker') or '').upper() == normalized]
    latest_ours = our_rows[0] if our_rows else None
    comparison = None
    if latest_ours:
        our_dir = _our_direction_token(latest_ours.get('direction'))
        broker_dir = consensus.get('agreement_direction')
        if broker_dir == 'MIXED':
            broker_dir = None
        agree = _directions_agree(our_dir, broker_dir)
        comparison = {
            'our_prediction_id': latest_ours.get('prediction_id'),
            'our_direction': our_dir,
            'broker_consensus': broker_dir,
            'relationship': (
                'agreement' if agree is True
                else 'conflict' if agree is False
                else 'unclear'
            ),
        }
    return {
        'ok': True,
        'ticker': normalized,
        'timeframe': timeframe,
        'pick_count': len(picks),
        'picks': picks,
        'consensus': consensus,
        'our_vs_broker': comparison,
        'disclaimer': 'External broker/app evidence — not our final prediction.',
    }


def get_source_intelligence(source: str) -> dict[str, Any]:
    """All broker picks and summary for one source."""
    needle = str(source or '').strip().lower()
    if not needle:
        return {'ok': False, 'error': 'source is required'}

    rows = [
        row for row in _fetch_all_broker_rows()
        if str(row.get('broker_source') or '').strip().lower() == needle
        or _slug_source(row.get('broker_source')) == _slug_source(source)
    ]
    stances: dict[str, int] = {}
    tickers: dict[str, int] = {}
    for row in rows:
        stance = str(row.get('bullish_or_bearish') or 'UNKNOWN').upper()
        stances[stance] = stances.get(stance, 0) + 1
        tick = str(row.get('ticker') or '').upper()
        if tick:
            tickers[tick] = tickers.get(tick, 0) + 1

    perf = next(
        (
            p for p in get_source_performance()
            if str(p.get('broker_source') or '').strip().lower() == needle
            or _slug_source(p.get('broker_source')) == _slug_source(source)
        ),
        None,
    )

    return {
        'ok': True,
        'broker_source': rows[0]['broker_source'] if rows else source,
        'pick_count': len(rows),
        'stance_breakdown': stances,
        'top_tickers': sorted(
            [{'ticker': t, 'count': c} for t, c in tickers.items()],
            key=lambda x: (-x['count'], x['ticker']),
        )[:15],
        'picks': rows[:50],
        'performance': perf,
        'disclaimer': 'External broker/app evidence — not our final prediction.',
    }


def _consensus_label_to_direction(label: object) -> str:
    text = str(label or '').strip().lower()
    if not text or text == 'unknown':
        return 'NEUTRAL'
    if 'mixed' in text:
        return 'MIXED'
    if 'negative' in text or 'avoid' in text:
        return 'BEARISH'
    if 'positive' in text:
        return 'BULLISH'
    return 'NEUTRAL'


def _display_candidates_from_intel_cache(*, limit: int) -> dict[str, Any] | None:
    """Cache-first broker intel rows mapped to legacy Telegram display shape."""
    try:
        from backend.analytics.broker_intelligence import get_broker_intel_overview

        overview = get_broker_intel_overview(cache_only=True, lite=True)
    except Exception as exc:
        _log_error(f'get_top_broker_display_candidates intel cache failed: {exc}')
        return {
            'ok': True,
            'origin': 'broker_intel_cache',
            'section_label': 'Top broker candidates:',
            'candidates': [],
            'pick_count': 0,
        }

    if overview.get('cache_missing'):
        return {
            'ok': True,
            'origin': 'broker_intel_cache',
            'section_label': 'Top broker candidates:',
            'candidates': [],
            'pick_count': 0,
        }

    capped = max(1, int(limit))
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _append_candidate(
        *,
        ticker: str | None,
        direction: str,
        source: object,
        title: object,
        confidence_score: object = None,
        freshness: object = None,
        headline: object = None,
    ) -> None:
        sym = _normalize_ticker(ticker)
        if not sym or sym in seen or len(candidates) >= capped:
            return
        seen.add(sym)
        candidates.append({
            'ticker': sym,
            'direction': str(direction or 'NEUTRAL').upper(),
            'source': str(source or 'broker_intel')[:80],
            'title': str(title or headline or '')[:80] or None,
            'headline': str(headline or title or '')[:120] or None,
            'confidence_score': confidence_score,
            'freshness': freshness,
            'origin': 'broker_intel_cache',
        })

    for row in (overview.get('top_positive') or []) + (overview.get('top_negative') or []):
        if not isinstance(row, dict):
            continue
        evidence = (row.get('evidence') or [])
        first_ev = evidence[0] if evidence and isinstance(evidence[0], dict) else {}
        _append_candidate(
            ticker=row.get('ticker'),
            direction=_consensus_label_to_direction(row.get('consensus_label')),
            source=first_ev.get('broker_house') or first_ev.get('source') or row.get('consensus_label'),
            title=first_ev.get('headline') or row.get('consensus_label'),
            confidence_score=row.get('confidence_score'),
            freshness=row.get('freshness'),
            headline=first_ev.get('headline'),
        )

    if len(candidates) < capped:
        for row in overview.get('evidence_items') or []:
            if not isinstance(row, dict):
                continue
            rating = str(row.get('rating') or row.get('direction') or 'neutral').lower()
            direction = {
                'positive': 'BULLISH',
                'negative': 'BEARISH',
                'neutral': 'NEUTRAL',
            }.get(rating, 'NEUTRAL')
            _append_candidate(
                ticker=row.get('ticker'),
                direction=direction,
                source=row.get('broker_house') or row.get('source'),
                title=row.get('headline'),
                confidence_score=row.get('confidence_score'),
                freshness=row.get('freshness'),
                headline=row.get('headline'),
            )

    tracked = int(overview.get('tracked_tickers') or 0)
    if candidates or tracked > 0:
        return {
            'ok': True,
            'origin': 'broker_intel_cache',
            'section_label': 'Top broker candidates:',
            'candidates': candidates[:capped],
            'pick_count': tracked or len(candidates),
        }
    return None


def get_top_broker_display_candidates(*, limit: int = 5) -> dict[str, Any]:
    """Latest broker or external-evidence rows for Telegram/GUI display (cache-first)."""
    capped = max(1, int(limit))
    intel_display = _display_candidates_from_intel_cache(limit=capped)
    if intel_display is not None:
        return intel_display

    db_rows = _fetch_all_broker_rows()
    if db_rows:
        candidates: list[dict[str, Any]] = []
        for row in db_rows[:capped]:
            raw = _parse_json_field(row.get('raw_payload'))
            text_hint = _combined_text(row, raw)
            candidates.append({
                'ticker': _normalize_ticker(row.get('ticker')) or '?',
                'direction': str(row.get('bullish_or_bearish') or '—').upper(),
                'source': str(row.get('broker_source') or '—'),
                'title': text_hint[:80] if text_hint else None,
                'origin': 'broker_db',
            })
        return {
            'ok': True,
            'origin': 'broker_db',
            'section_label': 'Top broker candidates:',
            'candidates': candidates,
            'pick_count': len(db_rows),
        }

    try:
        from backend.collectors.broker_app_collector import get_external_evidence_dashboard

        ext = get_external_evidence_dashboard()
        ext_rows = [
            row for row in (ext.get('broker_candidates') or [])
            if isinstance(row, dict)
        ]
        if ext_rows:
            candidates = []
            for row in ext_rows[:capped]:
                candidates.append({
                    'ticker': _normalize_ticker(row.get('ticker')) or '?',
                    'direction': str(row.get('direction') or '—').upper(),
                    'source': str(row.get('source') or '—'),
                    'title': str(row.get('title') or '')[:80] or None,
                    'origin': 'external_evidence',
                })
            return {
                'ok': True,
                'origin': 'external_evidence',
                'section_label': 'External evidence candidates',
                'candidates': candidates,
                'pick_count': int(ext.get('broker_prediction_candidate') or len(ext_rows)),
            }
    except Exception as exc:
        _log_error(f'get_top_broker_display_candidates external fallback failed: {exc}')

    return {
        'ok': True,
        'origin': 'none',
        'section_label': 'Top broker candidates:',
        'candidates': [],
        'pick_count': 0,
    }


def compare_our_predictions_vs_brokers(
    *,
    ticker: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Compare canonical predictions vs broker picks with agreement/conflict stats."""
    our_rows = _fetch_recent_predictions(limit=limit)
    broker_rows = _fetch_all_broker_rows()

    if ticker:
        tick = _normalize_ticker(ticker)
        our_rows = [r for r in our_rows if str(r.get('ticker') or '').upper() == tick]
        broker_rows = [r for r in broker_rows if str(r.get('ticker') or '').upper() == tick]

    broker_by_ticker: dict[str, list[dict]] = {}
    for row in broker_rows:
        tick = str(row.get('ticker') or '').upper()
        if tick:
            broker_by_ticker.setdefault(tick, []).append(row)

    agreements = 0
    conflicts = 0
    unclear = 0
    broker_only = 0
    our_only = 0
    pairs: list[dict[str, Any]] = []

    seen_tickers = set()
    for row in our_rows:
        tick = str(row.get('ticker') or '').upper()
        if not tick:
            continue
        seen_tickers.add(tick)
        picks = broker_by_ticker.get(tick) or []
        if not picks:
            our_only += 1
            continue
        consensus = calculate_consensus(picks)
        our_dir = _our_direction_token(row.get('direction'))
        broker_dir = consensus.get('agreement_direction')
        if broker_dir in {'MIXED', 'UNKNOWN'}:
            broker_dir = None
        agree = _directions_agree(our_dir, broker_dir)
        if agree is True:
            agreements += 1
            rel = 'agreement'
        elif agree is False:
            conflicts += 1
            rel = 'conflict'
        else:
            unclear += 1
            rel = 'unclear'
        pairs.append({
            'ticker': tick,
            'our_prediction_id': row.get('prediction_id'),
            'our_direction': our_dir,
            'broker_consensus': broker_dir,
            'broker_pick_count': len(picks),
            'relationship': rel,
        })

    for tick, picks in broker_by_ticker.items():
        if tick not in seen_tickers:
            broker_only += 1

    compared = agreements + conflicts + unclear
    return {
        'ok': True,
        'ticker_filter': _normalize_ticker(ticker) if ticker else None,
        'our_predictions': len(our_rows),
        'broker_picks': len(broker_rows),
        'pairs_compared': compared,
        'agreements': agreements,
        'conflicts': conflicts,
        'unclear': unclear,
        'our_only_tickers': our_only,
        'broker_only_tickers': broker_only,
        'agreement_rate': round(agreements / compared, 4) if compared else None,
        'pairs': pairs[:30],
        'disclaimer': 'Broker picks are external evidence; not copied as our predictions.',
    }


def get_broker_intelligence_dashboard() -> dict[str, Any]:
    """Unified payload for API and GUI."""
    display = get_top_broker_display_candidates(limit=5)
    our_vs = compare_our_predictions_vs_brokers(limit=100)
    our_vs = {
        **our_vs,
        'top_broker_candidates': display.get('candidates') or [],
        'display_origin': display.get('origin'),
        'display_section_label': display.get('section_label'),
    }
    stats = get_intelligence_stats()
    return {
        'ok': True,
        'stats': {
            **stats,
            'picks_tracked': max(
                int(stats.get('broker_predictions') or 0),
                int(display.get('pick_count') or 0),
            ),
        },
        'source_performance': get_source_performance(),
        'our_vs_broker': our_vs,
        'collect_hint': 'python scripts/collect_broker_app_predictions.py --write-broker-db',
        'import_hint': (
            'python scripts/collect_broker_app_predictions.py --source manual --write-broker-db'
        ),
        'disclaimer': 'External broker/app evidence — not our final prediction.',
    }
