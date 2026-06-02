"""
External evidence adapter — read-only ticker-level evidence for final confidence.

Reads data/external_evidence_latest.json only. Does not write broker DB,
place trades, or convert stock news into broker predictions.
"""

from __future__ import annotations

import json
import re
from typing import Any

from backend.utils.config import DATA_DIR

EXTERNAL_EVIDENCE_PATH = DATA_DIR / 'external_evidence_latest.json'
EXTERNAL_EVIDENCE_CAP = 3

STOCK_NEWS_CLASS = 'stock_news_evidence'
MARKET_CONTEXT_CLASS = 'market_context'
MACRO_CONTEXT_CLASS = 'macro_context'
BROKER_PRED_CLASS = 'broker_prediction_candidate'

CONTEXT_CLASSES = frozenset({MARKET_CONTEXT_CLASS, MACRO_CONTEXT_CLASS})
SCORING_CLASSES = frozenset({STOCK_NEWS_CLASS})

POSITIVE_DIRECTIONS = frozenset({'BULLISH', 'BUY', 'LONG'})
NEGATIVE_DIRECTIONS = frozenset({'BEARISH', 'SELL', 'SHORT'})
NEUTRAL_DIRECTIONS = frozenset({'NEUTRAL', 'HOLD'})
WATCH_DIRECTIONS = frozenset({'WATCH'})

DISCLAIMER = 'External evidence is read-only and not trade execution.'

RELIANCE_TITLE_RE = re.compile(
    r'\b(?:RELIANCE|RIL|Reliance(?:\s+(?:Industries|Communications|Petroleum))?)\b',
    re.IGNORECASE,
)


def _normalize_ticker(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def _clamp_adj(value: int) -> int:
    return int(max(-EXTERNAL_EVIDENCE_CAP, min(EXTERNAL_EVIDENCE_CAP, value)))


def _load_external_evidence_payload() -> dict[str, Any]:
    if not EXTERNAL_EVIDENCE_PATH.is_file():
        return {'ok': False, 'error': 'external_evidence_latest.json missing', 'items': []}
    try:
        data = json.loads(EXTERNAL_EVIDENCE_PATH.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        return {'ok': False, 'error': str(exc), 'items': []}
    if not isinstance(data, dict):
        return {'ok': False, 'error': 'invalid external evidence payload', 'items': []}
    return data


def _accepted_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in payload.get('items') or []:
        if not isinstance(row, dict):
            continue
        if row.get('accepted') is not True:
            continue
        items.append(row)
    return items


def _direction_bucket(direction: object) -> str:
    token = str(direction or 'NEUTRAL').strip().upper()
    if token in POSITIVE_DIRECTIONS:
        return 'positive'
    if token in NEGATIVE_DIRECTIONS:
        return 'negative'
    if token in WATCH_DIRECTIONS:
        return 'watch'
    return 'neutral'


def _compact_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        'classification': row.get('classification'),
        'ticker': row.get('ticker'),
        'market': row.get('market'),
        'direction': row.get('direction'),
        'direction_confidence': row.get('direction_confidence'),
        'evidence_strength': row.get('evidence_strength'),
        'source': row.get('source'),
        'title': row.get('title'),
        'reason': row.get('reason'),
        'matched_keywords': row.get('matched_keywords') or [],
        'matched_ticker': row.get('matched_ticker'),
        'matched_alias': row.get('matched_alias'),
        'match_method': row.get('match_method'),
        'match_confidence': row.get('match_confidence'),
    }


def _title_supports_ticker(title: str, ticker: str, matched_alias: object) -> bool:
    """Ensure headline or alias explicitly names the requested company."""
    text = str(title or '').strip()
    if not text:
        return False
    token = str(ticker or '').strip().upper()
    if not token:
        return False
    if re.search(rf'\b{re.escape(token)}\b', text, re.IGNORECASE):
        return True
    alias = str(matched_alias or '').strip()
    if alias and re.search(rf'\b{re.escape(alias)}\b', text, re.IGNORECASE):
        return True
    if token == 'RELIANCE':
        if re.search(r'\bdell\b', text, re.IGNORECASE):
            return False
        return bool(RELIANCE_TITLE_RE.search(text))
    if token == 'MCX':
        return bool(re.search(r'\bMCX\b', text, re.IGNORECASE))
    return False


def _row_matches_requested_ticker(row: dict[str, Any], requested: str) -> bool:
    row_ticker = _normalize_ticker(row.get('ticker'))
    if row_ticker != requested:
        return False
    matched = _normalize_ticker(row.get('matched_ticker'))
    if matched and matched != requested:
        return False
    classification = str(row.get('classification') or '')
    if classification == BROKER_PRED_CLASS:
        return False
    if classification not in SCORING_CLASSES:
        return False
    match_confidence = str(row.get('match_confidence') or '')
    if match_confidence == 'none':
        return False
    if match_confidence == 'low' and not _title_supports_ticker(
        str(row.get('title') or ''),
        requested,
        row.get('matched_alias'),
    ):
        return False
    if not _title_supports_ticker(
        str(row.get('title') or ''),
        requested,
        row.get('matched_alias'),
    ):
        match_method = str(row.get('match_method') or '')
        if match_method not in {'explicit_ticker', 'ticker_symbol'}:
            return False
    return True


def get_external_evidence_summary() -> dict[str, Any]:
    """Aggregate accepted external evidence counts from latest JSON."""
    payload = _load_external_evidence_payload()
    if payload.get('ok') is False and not payload.get('items'):
        return {
            'ok': False,
            'error': payload.get('error') or 'external evidence unavailable',
            'disclaimer': DISCLAIMER,
        }

    items = _accepted_items(payload)
    file_summary = payload.get('summary') if isinstance(payload.get('summary'), dict) else {}

    counts = {
        'accepted': len(items),
        'broker_prediction_candidate': 0,
        'stock_news_evidence': 0,
        'market_context': 0,
        'macro_context': 0,
        'positive': 0,
        'negative': 0,
        'watch': 0,
        'neutral': 0,
    }
    tickers: set[str] = set()
    for row in items:
        classification = str(row.get('classification') or '')
        if classification in counts:
            counts[classification] += 1
        bucket = _direction_bucket(row.get('direction'))
        counts[bucket] += 1
        ticker = _normalize_ticker(row.get('ticker'))
        if ticker:
            tickers.add(ticker)

    return {
        'ok': True,
        'generated_at': payload.get('generated_at'),
        'total_raw': int(file_summary.get('total_raw') or len(payload.get('items') or [])),
        'accepted': counts['accepted'],
        'rejected': int(file_summary.get('rejected') or 0),
        'broker_prediction_candidate': counts['broker_prediction_candidate'],
        'stock_news_evidence': counts['stock_news_evidence'],
        'market_context': counts['market_context'],
        'macro_context': counts['macro_context'],
        'direction_counts': {
            'positive': counts['positive'],
            'negative': counts['negative'],
            'watch': counts['watch'],
            'neutral': counts['neutral'],
        },
        'unique_tickers': len(tickers),
        'sources': file_summary.get('sources') or [],
        'disclaimer': DISCLAIMER,
    }


def get_market_context_summary(*, limit: int = 10) -> dict[str, Any]:
    """Market/macro context headlines for risk notes — not ticker scoring."""
    payload = _load_external_evidence_payload()
    if payload.get('ok') is False and not payload.get('items'):
        return {
            'ok': False,
            'error': payload.get('error') or 'external evidence unavailable',
            'items': [],
            'warnings': [],
            'disclaimer': DISCLAIMER,
        }

    context_items: list[dict[str, Any]] = []
    warnings: list[str] = []
    market_count = 0
    macro_count = 0

    for row in _accepted_items(payload):
        classification = str(row.get('classification') or '')
        if classification == MARKET_CONTEXT_CLASS:
            market_count += 1
        elif classification == MACRO_CONTEXT_CLASS:
            macro_count += 1
        else:
            continue

        if len(context_items) < max(1, int(limit)):
            context_items.append(_compact_item(row))

        bucket = _direction_bucket(row.get('direction'))
        if bucket == 'negative':
            title = str(row.get('title') or '').strip()
            if title:
                warnings.append(f'Macro/market caution: {title[:100]}')

    if market_count + macro_count == 0:
        warnings.append('No market/macro context headlines loaded.')

    return {
        'ok': True,
        'market_context_count': market_count,
        'macro_context_count': macro_count,
        'total_context': market_count + macro_count,
        'items': context_items,
        'warnings': warnings[:8],
        'disclaimer': DISCLAIMER,
    }


def get_ticker_external_evidence(ticker: str, *, limit: int = 5) -> dict[str, Any]:
    """Stock news evidence for one ticker (excludes broker prediction candidates)."""
    normalized = _normalize_ticker(ticker)
    if not normalized:
        return {
            'ok': False,
            'error': 'ticker is required',
            'ticker': None,
            'items': [],
            'counts': {'positive': 0, 'negative': 0, 'watch': 0, 'neutral': 0},
            'score_adjustment': 0,
            'warnings': [],
            'summary_reason': 'missing ticker',
            'disclaimer': DISCLAIMER,
        }

    payload = _load_external_evidence_payload()
    if payload.get('ok') is False and not payload.get('items'):
        return {
            'ok': False,
            'error': payload.get('error') or 'external evidence unavailable',
            'ticker': normalized,
            'items': [],
            'counts': {'positive': 0, 'negative': 0, 'watch': 0, 'neutral': 0},
            'score_adjustment': 0,
            'warnings': ['external_evidence_unavailable'],
            'summary_reason': 'external evidence file unavailable',
            'disclaimer': DISCLAIMER,
        }

    counts = {'positive': 0, 'negative': 0, 'watch': 0, 'neutral': 0}
    items: list[dict[str, Any]] = []
    broker_skipped = 0

    for row in _accepted_items(payload):
        row_ticker = _normalize_ticker(row.get('ticker'))
        if row_ticker == normalized and str(row.get('classification') or '') == BROKER_PRED_CLASS:
            broker_skipped += 1
        if not _row_matches_requested_ticker(row, normalized):
            continue

        bucket = _direction_bucket(row.get('direction'))
        counts[bucket] += 1
        if len(items) < max(1, int(limit)):
            items.append(_compact_item(row))

    warnings: list[str] = []
    if broker_skipped:
        warnings.append('broker_prediction_candidate_excluded_from_scoring')
    if counts['negative'] > 0:
        warnings.append('external_negative_stock_news')
    if not items:
        warnings.append('no_stock_news_evidence_for_ticker')

    return {
        'ok': True,
        'ticker': normalized,
        'items': items,
        'counts': counts,
        'score_adjustment': 0,
        'warnings': warnings,
        'summary_reason': _summarize_ticker_evidence(counts, items),
        'broker_candidates_skipped': broker_skipped,
        'disclaimer': DISCLAIMER,
    }


def _summarize_ticker_evidence(counts: dict[str, int], items: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    if counts['negative']:
        parts.append(f"{counts['negative']} negative headline(s)")
    if counts['positive']:
        parts.append(f"{counts['positive']} positive headline(s)")
    if counts['watch']:
        parts.append(f"{counts['watch']} watch headline(s)")
    if counts['neutral']:
        parts.append(f"{counts['neutral']} neutral headline(s)")
    if not parts:
        return 'no stock news evidence for ticker'
    latest = items[0].get('title') if items else None
    if latest:
        return '; '.join(parts) + f' — latest: {str(latest)[:80]}'
    return '; '.join(parts)


def _score_from_counts(
    counts: dict[str, int],
    *,
    pre_decision: str | None,
) -> tuple[int, list[str], str]:
    """Compute capped adjustment from stock news direction counts."""
    warnings: list[str] = []
    decision = str(pre_decision or '').strip().upper()

    negative = int(counts.get('negative') or 0)
    positive = int(counts.get('positive') or 0)

    adjustment = 0
    reasons: list[str] = []

    if negative > 0:
        neg_adj = -min(EXTERNAL_EVIDENCE_CAP, negative)
        adjustment += neg_adj
        reasons.append(f'{negative} negative stock headline(s) => {neg_adj}')
        warnings.append('external_negative_stock_news')

    if positive > 0:
        if decision in {'WATCH', 'BUY_CANDIDATE'}:
            pos_adj = min(EXTERNAL_EVIDENCE_CAP, positive)
            if adjustment < 0:
                pos_adj = min(pos_adj, EXTERNAL_EVIDENCE_CAP + adjustment)
            adjustment += pos_adj
            reasons.append(f'{positive} positive headline(s) with {decision} => +{pos_adj}')
        else:
            reasons.append(f'{positive} positive headline(s) ignored — candidate not WATCH')
            warnings.append('external_positive_ignored_not_watch')

    watch_neutral = int(counts.get('watch') or 0) + int(counts.get('neutral') or 0)
    if watch_neutral and not negative and not positive:
        reasons.append(f'{watch_neutral} watch/neutral headline(s) => 0')

    adjustment = _clamp_adj(adjustment)
    summary = '; '.join(reasons) if reasons else 'no scoring impact from external stock news'
    return adjustment, warnings, summary


def score_external_evidence(
    candidate: dict[str, Any],
    *,
    pre_decision: str | None = None,
) -> dict[str, Any]:
    """
    Score read-only external stock news for a candidate.

    Broker prediction candidates are excluded (handled by broker DB).
    Market/macro context does not adjust ticker scores.
    """
    ticker = _normalize_ticker(candidate.get('ticker'))
    if not ticker:
        return {
            'ok': False,
            'error': 'ticker is required',
            'ticker': None,
            'confidence_adjustment': 0,
            'warnings': ['missing_ticker'],
            'reasons': ['missing ticker => no external evidence score'],
            'external_evidence': None,
            'disclaimer': DISCLAIMER,
        }

    decision_hint = pre_decision or candidate.get('pre_decision') or candidate.get('decision')
    ticker_payload = get_ticker_external_evidence(ticker)
    counts = ticker_payload.get('counts') or {}

    adjustment, score_warnings, score_reason = _score_from_counts(
        counts,
        pre_decision=decision_hint,
    )

    warnings = list(ticker_payload.get('warnings') or [])
    for token in score_warnings:
        if token not in warnings:
            warnings.append(token)

    ticker_payload['score_adjustment'] = adjustment
    ticker_payload['summary_reason'] = score_reason

    return {
        'ok': True,
        'ticker': ticker,
        'confidence_adjustment': adjustment,
        'warnings': warnings,
        'reasons': [score_reason] if score_reason else [],
        'external_evidence': ticker_payload,
        'counts': counts,
        'summary_reason': score_reason,
        'disclaimer': DISCLAIMER,
    }
