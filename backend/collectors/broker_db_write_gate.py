"""
Broker DB write eligibility gate (Stage 39E).

Human-review safe list before any broker_predictions table write.
No fake recommendations; no inferring BUY from price/credit/block/question headlines.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from backend.collectors.broker_app_collector import _dedupe_key
from backend.collectors.external_evidence_classifier import (
    BUY_SELL_HOLD_RE,
    DIRECT_RECOMMENDATION_RE,
    EXPLICIT_BEARISH_RE,
    EXPLICIT_BULLISH_RE,
    MACRO_CONTEXT_RE,
    MARKET_CONTEXT_RE,
    NEUTRAL_HOLD_RE,
    PURE_PRICE_MOVEMENT_RE,
    REJECT_RE,
    TARGET_PRICE_RE,
    WATCH_TEXT_RE,
    has_explicit_recommendation_signal,
)
from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR

REVIEW_OUTPUT_PATH = DATA_DIR / 'broker_db_write_review.json'

CREDIT_RATING_RE = re.compile(
    r'\b('
    r"credit\s+rating|moody'?s|s&p\s+global|fitch|crisil|icra|care\s+ratings|"
    r'rating\s+(?:upgrade|downgrade|affirm|revis)|affirmed?\s+rating|'
    r'long[\s-]term\s+rating|issuer\s+rating'
    r')\b',
    re.IGNORECASE,
)

BLOCK_DEAL_RE = re.compile(
    r'\b(block\s+deal|bulk\s+deal|cross[\s-]?border\s+deal|large\s+deal)\b',
    re.IGNORECASE,
)

QUESTION_HEADLINE_RE = re.compile(
    r'\b('
    r'should\s+you\s+(?:buy|sell|hold)|'
    r'buy,\s*sell\s+or\s*hold|'
    r'buy\s+or\s+sell(?:\s+or\s+hold)?|'
    r'what\s+should\s+investors\s+do'
    r')\b',
    re.IGNORECASE,
)

EXPLICIT_CONCLUSION_RE = re.compile(
    r'\b('
    r'buy|sell|hold|neutral|accumulate|reduce|add|trim|'
    r'outperform|underperform|overweight|underweight|'
    r'top\s+picks?|preferred\s+pick|conviction\s+pick|'
    r'upgrade(?:d|s)?(?:\s+to)?|downgrade(?:d|s)?(?:\s+to)?|'
    r'recommends?|maintains?\s+(?:buy|sell|hold)|'
    r'target\s+price|price\s+target'
    r')\b',
    re.IGNORECASE,
)

ANALYST_BROKER_SOURCE_RE = re.compile(
    r'\b('
    r'broker(?:age)?s?|analysts?|research\s+house|equity\s+research|'
    r'nomura|motilal|icici\s+securities|jefferies|goldman|jpmorgan|'
    r'morgan\s+stanley|clsa|kotak|axis\s+capital|emkay|elara|sharekhan|'
    r'hdfc\s+securities|motilal\s+oswal|angel\s+one|iifl|dam capital|'
    r'prabhudas|dolat|nirmal\s+bang|systematix'
    r')\b',
    re.IGNORECASE,
)

CORPORATE_ACTION_RE = re.compile(
    r'\b('
    r'dividend|bonus\s+issue|stock\s+split|buyback|rights\s+issue|'
    r'board\s+meeting|agm|egm|merger|demerger|acquisition\s+of'
    r')\b',
    re.IGNORECASE,
)

EARNINGS_RE = re.compile(
    r'\b(q[1-4]|quarterly|annual)\s+(?:results|earnings)|'
    r'earnings\s+(?:beat|miss)|profit\s+(?:rises|falls)|'
    r'revenue\s+(?:rises|falls)|net\s+profit\b',
    re.IGNORECASE,
)

STOCK_NEWS_ONLY_RE = re.compile(
    r'\b(supreme\s+court|sebi\s+probe|fraud\s+case|relief\s+from|'
    r'penalty|fine|investigation|court\s+order)\b',
    re.IGNORECASE,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _combined_text(item: dict[str, Any]) -> str:
    raw = item.get('raw_payload') if isinstance(item.get('raw_payload'), dict) else {}
    parts = [
        item.get('title'),
        item.get('headline'),
        item.get('notes'),
        raw.get('title'),
        raw.get('headline'),
        raw.get('description'),
        raw.get('summary'),
        raw.get('notes'),
        raw.get('text'),
    ]
    return ' '.join(str(p or '').strip() for p in parts if p).strip()


def _item_ticker(item: dict[str, Any]) -> str | None:
    token = str(item.get('ticker') or '').strip().upper()
    return token or None


def _item_title(item: dict[str, Any]) -> str:
    return str(item.get('title') or item.get('headline') or '')[:240]


def _item_source(item: dict[str, Any]) -> str:
    raw = item.get('raw_payload') if isinstance(item.get('raw_payload'), dict) else {}
    return str(
        item.get('source')
        or item.get('broker_source')
        or raw.get('source')
        or raw.get('broker_source')
        or raw.get('channel')
        or '',
    ).strip()


def _item_direction(item: dict[str, Any]) -> str:
    raw = item.get('raw_payload') if isinstance(item.get('raw_payload'), dict) else {}
    return str(
        item.get('direction')
        or item.get('stance')
        or item.get('bullish_or_bearish')
        or raw.get('direction')
        or raw.get('stance')
        or 'NEUTRAL',
    ).strip().upper()


def _is_manual_inbox(item: dict[str, Any]) -> bool:
    raw = item.get('raw_payload') if isinstance(item.get('raw_payload'), dict) else {}
    collector_source = str(
        item.get('collector_source')
        or raw.get('collector_source')
        or '',
    ).strip().lower()
    if collector_source == 'manual':
        return True
    source_type = str(item.get('source_type') or raw.get('source_type') or '').strip().lower()
    return source_type in {'manual', 'manual_inbox'}


def _has_analyst_or_broker_source(item: dict[str, Any], text: str) -> bool:
    if _is_manual_inbox(item):
        return True
    source = _item_source(item)
    if ANALYST_BROKER_SOURCE_RE.search(f'{source} {text}'):
        return True
    classification_reason = str(item.get('classification_reason') or '')
    if 'explicit_recommendation' in classification_reason:
        return True
    return bool(item.get('direction_confidence') == 'explicit')


def _has_explicit_conclusion(text: str, item: dict[str, Any]) -> bool:
    if QUESTION_HEADLINE_RE.search(text):
        post_question = re.search(
            r'\b(recommends?|rated?|assigns?|maintains?|upgrades?|downgrades?)\b'
            r'.{0,40}\b(buy|sell|hold|accumulate|reduce|outperform|underperform)\b',
            text,
            re.IGNORECASE,
        )
        broker_after = re.search(
            r'\b(broker(?:age)?|analyst)\b.{0,60}\b(buy|sell|hold|accumulate|outperform)\b',
            text,
            re.IGNORECASE,
        )
        if not post_question and not broker_after:
            return False

    if not EXPLICIT_CONCLUSION_RE.search(text):
        has_signal, _ = has_explicit_recommendation_signal(text)
        if not has_signal:
            return False

    if WATCH_TEXT_RE.search(text):
        if not EXPLICIT_BULLISH_RE.search(text) and not EXPLICIT_BEARISH_RE.search(text):
            if not NEUTRAL_HOLD_RE.search(text):
                if not re.search(r'\b(outperform|underperform|overweight|underweight|top\s+picks?)\b', text, re.I):
                    return False

    direction_conf = str(item.get('direction_confidence') or '')
    if direction_conf == 'context_only':
        return False
    if direction_conf == 'watch_only':
        return False

    direction = _item_direction(item)
    if direction == 'BULLISH' and PURE_PRICE_MOVEMENT_RE.search(text):
        if not EXPLICIT_BULLISH_RE.search(text) and not DIRECT_RECOMMENDATION_RE.search(text):
            return False

    return True


def _is_credit_rating_only(text: str) -> bool:
    if not CREDIT_RATING_RE.search(text):
        return False
    if BROKER_REC_OVERRIDE_RE.search(text) and ANALYST_BROKER_SOURCE_RE.search(text):
        return False
    return True


BROKER_REC_OVERRIDE_RE = re.compile(
    r'\b('
    r'recommends?|rated?\s+(?:buy|sell|hold)|maintains?\s+(?:buy|sell|hold)|'
    r'upgrade(?:d|s)?(?:\s+to)?\s+(?:buy|sell)|downgrade(?:d|s)?(?:\s+to)?\s+(?:buy|sell)|'
    r'buy\s+call|sell\s+call|'
    r'(?:raises?|cuts?|hikes?)\s+(?:the\s+)?(?:price\s+)?target|target\s+price\s+(?:of|at|to|raised)'
    r')\b',
    re.IGNORECASE,
)


def _is_block_deal_only(text: str) -> bool:
    if not BLOCK_DEAL_RE.search(text):
        return False
    return not BROKER_REC_OVERRIDE_RE.search(text)


def _is_pure_price_movement_only(text: str) -> bool:
    if not PURE_PRICE_MOVEMENT_RE.search(text):
        return False
    has_signal, _ = has_explicit_recommendation_signal(text)
    return not has_signal


def _is_question_without_conclusion(text: str) -> bool:
    if not QUESTION_HEADLINE_RE.search(text):
        return False
    return not _has_explicit_conclusion(text, {})


def _is_watch_only(text: str) -> bool:
    if not WATCH_TEXT_RE.search(text):
        return False
    return not _has_explicit_conclusion(text, {})


def _load_db_dedupe_keys() -> set[str]:
    keys: set[str] = set()
    try:
        from backend.storage.market_memory_db import get_connection, init_market_memory_db

        if not init_market_memory_db():
            return keys
        conn = get_connection()
        try:
            rows = conn.execute(
                'SELECT dedupe_key, broker_source, ticker, raw_payload FROM broker_predictions',
            ).fetchall()
            for row in rows:
                if row['dedupe_key']:
                    keys.add(str(row['dedupe_key']))
                raw_text = str(row['raw_payload'] or '')
                title = ''
                if raw_text.startswith('{'):
                    try:
                        parsed = json.loads(raw_text)
                        if isinstance(parsed, dict):
                            title = str(parsed.get('headline') or parsed.get('title') or '')
                    except json.JSONDecodeError:
                        title = ''
                keys.add(_dedupe_key(
                    str(row['broker_source'] or ''),
                    str(row['ticker'] or ''),
                    title,
                    '',
                ))
        finally:
            conn.close()
    except Exception:
        pass
    return keys


def _is_duplicate_in_db(item: dict[str, Any], db_keys: set[str]) -> bool:
    raw = item.get('raw_payload') if isinstance(item.get('raw_payload'), dict) else {}
    if raw.get('dedupe_key') and str(raw['dedupe_key']) in db_keys:
        return True
    source = _item_source(item)
    ticker = _item_ticker(item) or ''
    title = _item_title(item)
    date_part = str(item.get('prediction_date') or item.get('published_at') or '')[:10]
    key = _dedupe_key(source, ticker, title, date_part)
    if key in db_keys:
        return True
    try:
        from backend.analytics.broker_prediction_intelligence import prepare_broker_pick_for_import

        prepared = prepare_broker_pick_for_import(item, source_hint=source)
        if prepared and prepared.get('dedupe_key') in db_keys:
            return True
        if prepared and prepared.get('prediction_id') in db_keys:
            return True
    except Exception:
        pass
    return False


def evaluate_broker_write_eligibility(item: dict[str, Any]) -> dict[str, Any]:
    """Evaluate whether one item may be written to broker_predictions."""
    ticker = _item_ticker(item)
    title = _item_title(item)
    source = _item_source(item)
    direction = _item_direction(item)
    text = _combined_text(item)
    warnings: list[str] = []
    classification = str(item.get('classification') or '')

    base = {
        'ticker': ticker,
        'title': title,
        'source': source,
        'direction': direction,
        'eligible': False,
        'eligibility': 'reject',
        'reason': '',
        'warnings': warnings,
        'required_human_review': False,
    }

    if REJECT_RE.search(text):
        base['reason'] = 'unrelated_content'
        return base

    if not ticker:
        base['reason'] = 'no_ticker'
        return base

    if MACRO_CONTEXT_RE.search(text) and not EXPLICIT_CONCLUSION_RE.search(text):
        base['reason'] = 'macro_only'
        return base

    if MARKET_CONTEXT_RE.search(text) and (
        not ticker or ticker in {'NIFTY', 'NIFTY50', 'SENSEX', 'BANKNIFTY', 'FINNIFTY'}
    ):
        base['reason'] = 'market_only'
        return base

    db_keys = _load_db_dedupe_keys()
    is_duplicate = _is_duplicate_in_db(item, db_keys)

    review_reasons: list[str] = []

    if classification == 'stock_news_evidence':
        review_reasons.append('stock_news_evidence')
    if classification in {'market_context', 'macro_context'}:
        review_reasons.append(classification)
    if _is_pure_price_movement_only(text):
        review_reasons.append('pure_price_movement')
    if _is_credit_rating_only(text):
        review_reasons.append('credit_rating_only')
    if _is_block_deal_only(text):
        review_reasons.append('block_deal_only')
    if _is_question_without_conclusion(text):
        review_reasons.append('question_headline_without_conclusion')
    if _is_watch_only(text):
        review_reasons.append('stocks_to_watch_only')
    if CORPORATE_ACTION_RE.search(text) and 'explicit_recommendation' not in str(item.get('classification_reason') or ''):
        review_reasons.append('corporate_action')
    if EARNINGS_RE.search(text) and not ANALYST_BROKER_SOURCE_RE.search(text):
        review_reasons.append('earnings_headline')
    if STOCK_NEWS_ONLY_RE.search(text) and classification != 'broker_prediction_candidate':
        review_reasons.append('stock_news_context')
    if TARGET_PRICE_RE.search(text) and not _has_explicit_conclusion(text, item):
        review_reasons.append('target_without_clear_recommendation')
    if is_duplicate:
        review_reasons.append('duplicate_in_broker_predictions')

    write_safe_checks = {
        'has_ticker': bool(ticker),
        'explicit_conclusion': _has_explicit_conclusion(text, item),
        'analyst_or_manual_source': _has_analyst_or_broker_source(item, text),
        'not_duplicate': not is_duplicate,
        'not_pure_price_movement': 'pure_price_movement' not in review_reasons,
        'not_credit_only': 'credit_rating_only' not in review_reasons,
        'not_block_deal_only': 'block_deal_only' not in review_reasons,
        'not_question_only': 'question_headline_without_conclusion' not in review_reasons,
        'not_watch_only': 'stocks_to_watch_only' not in review_reasons,
    }

    if all(write_safe_checks.values()):
        base['eligible'] = True
        base['eligibility'] = 'write_safe'
        base['reason'] = 'explicit_broker_recommendation'
        base['required_human_review'] = False
        return base

    if review_reasons:
        base['eligibility'] = 'review_only'
        base['reason'] = review_reasons[0]
        base['warnings'] = review_reasons
        base['required_human_review'] = True
        return base

    base['reason'] = 'failed_write_safe_checks'
    base['warnings'] = [k for k, ok in write_safe_checks.items() if not ok]
    base['required_human_review'] = True
    return base


def build_broker_write_review(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify candidate items into write_safe, review_only, and rejected buckets."""
    write_safe: list[dict[str, Any]] = []
    review_only: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    duplicates = 0

    for item in items:
        if not isinstance(item, dict):
            continue
        verdict = evaluate_broker_write_eligibility(item)
        row = {**verdict, 'item': item}
        token = verdict.get('eligibility')
        if token == 'write_safe':
            write_safe.append(row)
        elif token == 'review_only':
            review_only.append(row)
            if 'duplicate_in_broker_predictions' in (verdict.get('warnings') or []):
                duplicates += 1
        else:
            rejected.append(row)

    return {
        'ok': True,
        'generated_at': _now_iso(),
        'summary': {
            'total_candidates': len(items),
            'write_safe': len(write_safe),
            'review_only': len(review_only),
            'rejected': len(rejected),
            'duplicates': duplicates,
        },
        'write_safe': write_safe,
        'review_only': review_only,
        'rejected': rejected,
    }


def write_broker_write_review(review: dict[str, Any]) -> None:
    """Persist review JSON to data/broker_db_write_review.json."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(REVIEW_OUTPUT_PATH, review)


def get_latest_broker_write_review() -> dict[str, Any]:
    """Load latest broker DB write review or empty shell."""
    if not REVIEW_OUTPUT_PATH.is_file():
        return {
            'ok': False,
            'generated_at': None,
            'summary': {
                'total_candidates': 0,
                'write_safe': 0,
                'review_only': 0,
                'rejected': 0,
                'duplicates': 0,
            },
            'write_safe': [],
            'review_only': [],
            'rejected': [],
            'warnings': ['review_missing'],
        }
    try:
        data = json.loads(REVIEW_OUTPUT_PATH.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            'ok': False,
            'error': str(exc),
            'summary': {'total_candidates': 0, 'write_safe': 0, 'review_only': 0, 'rejected': 0, 'duplicates': 0},
            'write_safe': [],
            'review_only': [],
            'rejected': [],
        }
    if isinstance(data, dict):
        data.setdefault('ok', True)
        return data
    return {'ok': False, 'error': 'invalid_review_json', 'write_safe': [], 'review_only': [], 'rejected': []}


def gather_broker_write_candidates_from_external_evidence() -> list[dict[str, Any]]:
    """Build gate input rows from latest external evidence cache."""
    from backend.collectors.broker_app_collector import load_external_evidence_cache

    cache = load_external_evidence_cache()
    candidates: list[dict[str, Any]] = []
    for row in cache.get('items') or []:
        if not isinstance(row, dict):
            continue
        if str(row.get('classification') or '') != 'broker_prediction_candidate':
            continue
        raw = row.get('raw_payload') if isinstance(row.get('raw_payload'), dict) else {}
        candidates.append({
            'ticker': row.get('ticker'),
            'title': row.get('title'),
            'source': row.get('source'),
            'direction': row.get('direction'),
            'direction_confidence': row.get('direction_confidence'),
            'classification': row.get('classification'),
            'classification_reason': row.get('classification_reason'),
            'direction_reason': row.get('direction_reason'),
            'raw_payload': raw,
            'collector_source': raw.get('collector_source'),
        })
    return candidates


def gate_normalized_items_for_db(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Filter normalized collector rows to write_safe only; persist review."""
    gate_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = item.get('raw_payload') if isinstance(item.get('raw_payload'), dict) else {}
        classification = str(
            item.get('classification')
            or raw.get('classification')
            or 'broker_prediction_candidate',
        )
        if classification != 'broker_prediction_candidate':
            continue
        gate_row = dict(item)
        gate_row.update({
            'ticker': item.get('ticker'),
            'title': item.get('headline') or item.get('title'),
            'source': item.get('broker_source') or item.get('source'),
            'direction': item.get('stance') or item.get('direction'),
            'direction_confidence': item.get('direction_confidence') or raw.get('direction_confidence'),
            'classification': classification,
            'classification_reason': item.get('classification_reason') or raw.get('classification_reason'),
            'direction_reason': item.get('direction_reason') or raw.get('direction_reason'),
            'raw_payload': raw,
            'collector_source': raw.get('collector_source'),
        })
        gate_items.append(gate_row)

    if not gate_items:
        gate_items = gather_broker_write_candidates_from_external_evidence()

    review = build_broker_write_review(gate_items)
    write_broker_write_review(review)

    safe_items: list[dict[str, Any]] = []
    seen_dedupe: set[str] = set()
    for item in items:
        raw = item.get('raw_payload') if isinstance(item.get('raw_payload'), dict) else {}
        classification = str(item.get('classification') or raw.get('classification') or '')
        if classification != 'broker_prediction_candidate':
            continue
        gate_row = {
            'ticker': item.get('ticker'),
            'title': item.get('headline') or item.get('title'),
            'source': item.get('broker_source') or item.get('source'),
            'direction': item.get('stance') or item.get('direction'),
            'direction_confidence': item.get('direction_confidence') or raw.get('direction_confidence'),
            'classification': classification,
            'classification_reason': item.get('classification_reason') or raw.get('classification_reason'),
            'direction_reason': item.get('direction_reason') or raw.get('direction_reason'),
            'raw_payload': raw,
            'collector_source': raw.get('collector_source'),
            'source_type': item.get('source_type') or raw.get('source_type'),
        }
        verdict = evaluate_broker_write_eligibility(gate_row)
        if verdict.get('eligibility') != 'write_safe':
            continue
        dedupe = str(raw.get('dedupe_key') or '')
        if dedupe:
            if dedupe in seen_dedupe:
                continue
            seen_dedupe.add(dedupe)
        safe_items.append(item)

    return safe_items, review
