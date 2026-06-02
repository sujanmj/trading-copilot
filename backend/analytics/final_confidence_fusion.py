"""
Final Confidence Fusion Engine — read-only shadow scoring.

Combines market memory advisor, broker consensus/intelligence, historical learning,
market router, source freshness, and price sanity into a 0–100 score with
BUY_CANDIDATE / WATCH / AVOID / NO_DECISION labels. Never places trades.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from backend.analytics.broker_consensus_score import score_broker_evidence
from backend.analytics.market_memory_advisor import (
    _prediction_to_candidate,
    advise_prediction,
    fetch_unresolved_predictions,
)
from backend.storage.price_outcome_sanity import (
    check_price_sanity_gates,
    extract_prices,
    is_suspicious_price_scale,
)

SHADOW_MODE = True
BASE_SCORE = 50
DISCLAIMER = 'Shadow confidence only — not trade execution.'

VALID_DECISIONS = frozenset({'BUY_CANDIDATE', 'WATCH', 'AVOID', 'NO_DECISION'})

BULLISH_TOKENS = frozenset({'BUY', 'BULLISH', 'LONG', 'ACCUMULATE', 'OUTPERFORM'})
BEARISH_TOKENS = frozenset({'SELL', 'BEARISH', 'SHORT', 'REDUCE', 'UNDERPERFORM'})

ADJUSTMENT_CAPS: dict[str, int] = {
    'A_memory_advisor': 15,
    'B_broker_consensus': 20,
    'C_broker_intelligence': 10,
    'D_historical_learning': 10,
    'H_historical_simulation': 10,
    'E_market_router': 8,
    'F_source_freshness': 10,
    'G_price_sanity': 15,
    'I_external_evidence': 3,
}

HARD_NO_DECISION = frozenset({
    'missing_ticker',
    'missing_prediction_id',
    'suspicious_price_scale',
    'insufficient_evidence',
})

BUY_CAP_MODES = frozenset({
    'RESEARCH_MODE',
    'INDIA_POSTMARKET_MODE',
    'USA_POSTMARKET_MODE',
})

CALIBRATION_SCORE_TYPES = frozenset({'increase_score', 'reduce_score'})
CALIBRATION_STRENGTH_CAPS: dict[str, int] = {
    'weak': 0,
    'medium': 5,
    'strong': 10,
}
CALIBRATION_STRENGTH_RANK = {'weak': 1, 'medium': 2, 'strong': 3}


def _get_market_context(ctx: dict[str, Any]) -> tuple[str, bool]:
    """Return (active_mode, market_closed) from scoring context or live router/freshness."""
    if ctx.get('router_fn'):
        payload = ctx['router_fn']()
        active_mode = str(payload.get('active_mode') or 'RESEARCH_MODE')
    else:
        from backend.analytics.market_calendar_router import get_active_market_mode

        payload = get_active_market_mode()
        active_mode = str(payload.get('active_mode') or 'RESEARCH_MODE')

    market_closed = bool(ctx.get('market_closed'))
    if not market_closed:
        if ctx.get('freshness_fn'):
            market_closed = bool(ctx['freshness_fn']().get('market_closed'))
        else:
            from backend.analytics.source_freshness import get_source_freshness_report

            market_closed = bool(get_source_freshness_report().get('market_closed'))

    india_session = str(payload.get('india_session') or '')
    usa_session = str(payload.get('usa_session') or '')
    if india_session == 'closed' and usa_session == 'closed':
        market_closed = True

    return active_mode, market_closed


def _is_buy_cap_mode(active_mode: str, *, market_closed: bool) -> bool:
    if market_closed:
        return True
    if active_mode in BUY_CAP_MODES:
        return True
    return active_mode.endswith('_POSTMARKET_MODE')


def _has_minimum_evidence(
    candidate: dict[str, Any],
    *,
    direction: str | None,
    advice: dict[str, Any],
    adjustments: dict[str, int],
    soft_warnings: list[str],
) -> bool:
    if not str(candidate.get('prediction_id') or '').strip():
        return False

    if direction or candidate.get('confidence_label'):
        return True

    if int(advice.get('sample_size') or 0) > 0:
        return True

    if str(advice.get('overall_advice') or 'neutral') != 'neutral':
        return True

    for key in (
        'B_broker_consensus',
        'C_broker_intelligence',
        'D_historical_learning',
        'A_memory_advisor',
    ):
        if adjustments.get(key, 0) != 0:
            return True

    evidence_markers = (
        'broker_conflict',
        'mixed_broker_signals',
        'broker_intelligence_conflict',
        'advisor_avoid_candidate',
        'historical_low_sample',
    )
    return any(marker in soft_warnings for marker in evidence_markers)


def _missing_price_without_evidence(
    candidate: dict[str, Any],
    latest_prices: dict[str, float],
    *,
    has_minimum_evidence: bool,
) -> bool:
    if has_minimum_evidence:
        return False

    ticker = _normalize_ticker(candidate.get('ticker'))
    signal_stack = _parse_json_field(candidate.get('signal_stack'))
    raw_payload = _parse_json_field(candidate.get('raw_payload'))
    prices = extract_prices(None, raw_payload, signal_stack)
    latest_price = prices.get('latest_price')
    if latest_price is None and ticker and ticker in latest_prices:
        latest_price = latest_prices[ticker]

    return latest_price is None and prices.get('entry_price') is None


def _clamp(value: float, low: int, high: int) -> int:
    return int(max(low, min(high, round(value))))


def _normalize_ticker(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def _parse_json_field(value: object) -> dict | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _candidate_direction(candidate: dict[str, Any]) -> str | None:
    for key in ('direction', 'signal_type', 'bias'):
        val = candidate.get(key)
        if val is None or not str(val).strip():
            continue
        token = str(val).strip().upper()
        if token in BULLISH_TOKENS:
            return 'BULLISH'
        if token in BEARISH_TOKENS:
            return 'BEARISH'
        if token in {'WATCH', 'HOLD', 'NEUTRAL'}:
            return 'NEUTRAL'
        return token
    return None


def _load_latest_prices() -> dict[str, float]:
    try:
        from backend.storage.market_memory_outcomes import load_latest_market_data
        from backend.utils.config import DATA_DIR

        for path in (
            DATA_DIR / 'latest_market_data_memory_enriched.json',
            DATA_DIR / 'latest_market_data.json',
        ):
            data = load_latest_market_data(path)
            if not data:
                continue
            prices = data.get('prices') or data.get('symbols') or {}
            if isinstance(prices, dict) and prices:
                result: dict[str, float] = {}
                for symbol, payload in prices.items():
                    if not isinstance(payload, dict):
                        continue
                    for key in ('ltp', 'last_price', 'close', 'price'):
                        val = payload.get(key)
                        if val is not None:
                            try:
                                result[str(symbol).strip().upper()] = float(val)
                            except (TypeError, ValueError):
                                pass
                            break
                if result:
                    return result
    except Exception:
        pass
    return {}


def _adjustment_a_memory_advisor(advice: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    learning_score = advice.get('learning_score')
    score_val = float(learning_score) if isinstance(learning_score, (int, float)) else 50.0
    adjustment = _clamp((score_val - 50.0) * 0.30, -ADJUSTMENT_CAPS['A_memory_advisor'], ADJUSTMENT_CAPS['A_memory_advisor'])

    warnings: list[str] = []
    explanations: list[str] = []
    overall = str(advice.get('overall_advice') or 'neutral')

    if overall == 'boost':
        adjustment = _clamp(adjustment + 5, -ADJUSTMENT_CAPS['A_memory_advisor'], ADJUSTMENT_CAPS['A_memory_advisor'])
        explanations.append(f'A: advisor boost (learning_score={learning_score}) => +5 bonus')
    elif overall == 'caution':
        adjustment = _clamp(adjustment - 3, -ADJUSTMENT_CAPS['A_memory_advisor'], ADJUSTMENT_CAPS['A_memory_advisor'])
        explanations.append(f'A: advisor caution => -3')
    elif overall == 'avoid_candidate':
        adjustment = _clamp(adjustment - 8, -ADJUSTMENT_CAPS['A_memory_advisor'], ADJUSTMENT_CAPS['A_memory_advisor'])
        explanations.append(f'A: advisor avoid_candidate => -8')

    sample_size = int(advice.get('sample_size') or 0)
    if sample_size >= 5 and overall == 'avoid_candidate':
        warnings.append('advisor_avoid_candidate')

    for item in advice.get('warnings') or []:
        token = str(item).strip()
        if token and token not in warnings:
            warnings.append(token)

    explanations.insert(0, f'A: memory advisor learning_score={learning_score} overall={overall} => {adjustment:+d}')
    return adjustment, warnings, explanations


def _adjustment_b_broker_consensus(candidate: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    result = score_broker_evidence(candidate)
    adjustment = int(result.get('confidence_adjustment') or 0)
    adjustment = _clamp(adjustment, -ADJUSTMENT_CAPS['B_broker_consensus'], ADJUSTMENT_CAPS['B_broker_consensus'])
    reason = result.get('reason') or 'broker_consensus'
    explanations = [f'B: broker consensus ({reason}) => {adjustment:+d}']
    warnings: list[str] = []
    if reason == 'broker_conflicts_with_candidate':
        warnings.append('broker_conflict')
    elif reason == 'mixed_broker_signals':
        warnings.append('mixed_broker_signals')
    return adjustment, warnings, explanations


def _adjustment_c_broker_intelligence(ticker: str) -> tuple[int, list[str], list[str]]:
    from backend.analytics.broker_prediction_intelligence import get_ticker_intelligence

    payload = get_ticker_intelligence(ticker)
    comparison = payload.get('our_vs_broker') or {}
    relationship = str(comparison.get('relationship') or 'unclear').lower()

    adjustment = 0
    if relationship == 'agreement':
        adjustment = 8
    elif relationship == 'conflict':
        adjustment = -10
    elif payload.get('pick_count', 0) > 0:
        adjustment = 2

    adjustment = _clamp(adjustment, -ADJUSTMENT_CAPS['C_broker_intelligence'], ADJUSTMENT_CAPS['C_broker_intelligence'])
    explanations = [f'C: broker intelligence relationship={relationship} picks={payload.get("pick_count", 0)} => {adjustment:+d}']
    warnings: list[str] = []
    if relationship == 'conflict':
        warnings.append('broker_intelligence_conflict')
    return adjustment, warnings, explanations


def _adjustment_d_historical_learning(ticker: str) -> tuple[int, list[str], list[str]]:
    from backend.analytics.historical_learning_engine import get_historical_ticker_performance

    payload = get_historical_ticker_performance(ticker)
    if payload.get('ok') is not True:
        return 0, [], [f'D: historical learning unavailable => 0']

    overall = payload.get('overall') or {}
    perf = payload.get('performance') or {}
    resolved = int(perf.get('resolved') or (overall.get('wins', 0) + overall.get('losses', 0)))
    win_rate = overall.get('win_rate')
    if win_rate is None:
        win_rate = perf.get('win_rate')

    adjustment = 0
    warnings: list[str] = []
    if resolved >= 5 and isinstance(win_rate, (int, float)):
        if float(win_rate) >= 0.60:
            adjustment = 8
        elif float(win_rate) <= 0.25:
            adjustment = -10
        elif float(win_rate) >= 0.40:
            adjustment = 3
    elif resolved > 0:
        warnings.append('historical_low_sample')

    adjustment = _clamp(adjustment, -ADJUSTMENT_CAPS['D_historical_learning'], ADJUSTMENT_CAPS['D_historical_learning'])
    rate_pct = f'{float(win_rate) * 100:.1f}%' if isinstance(win_rate, (int, float)) else 'N/A'
    explanations = [f'D: historical replay n={resolved} win_rate={rate_pct} => {adjustment:+d}']
    return adjustment, warnings, explanations


def _adjustment_e_market_router() -> tuple[int, list[str], list[str]]:
    from backend.analytics.market_calendar_router import get_active_market_mode

    mode_payload = get_active_market_mode()
    active_mode = str(mode_payload.get('active_mode') or 'RESEARCH_MODE')
    warnings: list[str] = list(mode_payload.get('warnings') or [])

    adjustment = 0
    if active_mode == 'INDIA_MODE':
        adjustment = 5
    elif active_mode in {'INDIA_PREMARKET_MODE', 'INDIA_POSTMARKET_MODE'}:
        adjustment = 2
    elif active_mode == 'RESEARCH_MODE':
        adjustment = -3
    elif active_mode.startswith('USA_'):
        adjustment = 1

    adjustment = _clamp(adjustment, -ADJUSTMENT_CAPS['E_market_router'], ADJUSTMENT_CAPS['E_market_router'])
    explanations = [f'E: market router mode={active_mode} => {adjustment:+d}']
    return adjustment, warnings, explanations


def _adjustment_f_source_freshness() -> tuple[int, list[str], list[str]]:
    from backend.analytics.source_freshness import get_source_freshness_report

    report = get_source_freshness_report()
    safe = bool(report.get('safe_to_use'))
    warnings = list(report.get('warnings') or [])

    adjustment = 3 if safe else -8
    prices = (report.get('sources') or {}).get('prices') or {}
    if prices.get('status') == 'stale' and not report.get('market_closed'):
        adjustment -= 5
        warnings.append('stale_prices')

    if not safe and {'runtime_snapshot_stale', 'news_feed_stale'} & set(warnings):
        warnings.append('stale_critical_sources')

    adjustment = _clamp(adjustment, -ADJUSTMENT_CAPS['F_source_freshness'], ADJUSTMENT_CAPS['F_source_freshness'])
    explanations = [f'F: source freshness safe_to_use={safe} => {adjustment:+d}']
    return adjustment, warnings, explanations


def _adjustment_g_price_sanity(candidate: dict[str, Any], latest_prices: dict[str, float]) -> tuple[int, list[str], list[str], list[str]]:
    hard_warnings: list[str] = []
    warnings: list[str] = []
    explanations: list[str] = []

    signal_stack = _parse_json_field(candidate.get('signal_stack'))
    raw_payload = _parse_json_field(candidate.get('raw_payload'))
    prices = extract_prices(None, raw_payload, signal_stack)

    ticker = _normalize_ticker(candidate.get('ticker'))
    latest_price = prices.get('latest_price')
    if latest_price is None and ticker and ticker in latest_prices:
        latest_price = latest_prices[ticker]
        prices['latest_price'] = latest_price

    gate_failures = check_price_sanity_gates(
        entry_price=prices.get('entry_price'),
        latest_price=prices.get('latest_price'),
        target_price=prices.get('target_price'),
        stop_loss=prices.get('stop_loss'),
    )

    adjustment = 0
    if is_suspicious_price_scale(
        entry_price=prices.get('entry_price'),
        latest_price=prices.get('latest_price'),
        target_price=prices.get('target_price'),
        stop_loss=prices.get('stop_loss'),
    ):
        adjustment = -15
        hard_warnings.append('suspicious_price_scale')
        explanations.append(f'G: suspicious price scale gates={gate_failures} => -15')
    elif latest_price is None and prices.get('entry_price') is not None:
        adjustment = -5
        warnings.append('missing_latest_price')
        explanations.append('G: missing latest price for entry context => -5')
    elif prices.get('entry_price') is not None:
        adjustment = 2
        explanations.append('G: price context present and sane => +2')
    else:
        explanations.append('G: no price context => 0')

    adjustment = _clamp(adjustment, -ADJUSTMENT_CAPS['G_price_sanity'], ADJUSTMENT_CAPS['G_price_sanity'])
    return adjustment, warnings, explanations, hard_warnings


def _resolve_decision(
    *,
    final_score: int,
    direction: str | None,
    hard_warnings: list[str],
    soft_warnings: list[str],
    has_minimum_evidence: bool,
) -> str:
    if any(token in HARD_NO_DECISION for token in hard_warnings):
        return 'NO_DECISION'

    bullish = direction == 'BULLISH'
    bearish = direction == 'BEARISH'

    if final_score >= 70 and bullish:
        return 'BUY_CANDIDATE'

    if final_score >= 50 or (final_score >= 43 and not bearish):
        return 'WATCH'

    if has_minimum_evidence and final_score > 35:
        return 'WATCH'

    if 'advisor_avoid_candidate' in soft_warnings and final_score < 55:
        return 'AVOID'
    if bearish and final_score <= 50:
        return 'AVOID'
    if {'broker_intelligence_conflict', 'broker_conflict'} & set(soft_warnings) and final_score < 50:
        return 'AVOID'
    if final_score <= 42:
        return 'AVOID'

    if has_minimum_evidence:
        return 'WATCH'

    if not direction and not has_minimum_evidence:
        return 'NO_DECISION'

    return 'WATCH'


def load_calibration_report() -> dict[str, Any] | None:
    """Load shadow calibration report JSON if present."""
    try:
        from backend.analytics.confidence_calibration_engine import CALIBRATION_REPORT_PATH

        path = CALIBRATION_REPORT_PATH
    except ImportError:
        from backend.utils.config import DATA_DIR

        path = DATA_DIR / 'confidence_calibration_report.json'

    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and data.get('ok') is True else None


def _bucket_sample_warning_map(calibration_report: dict[str, Any]) -> dict[str, str]:
    """Map bucket label -> sample_warning from combined/live bucket sections."""
    result: dict[str, str] = {}
    for section_key in ('combined', 'live'):
        section = calibration_report.get(section_key) or {}
        for bucket in section.get('buckets') or []:
            if not isinstance(bucket, dict):
                continue
            label = str(bucket.get('bucket') or '').strip()
            if label and label not in result:
                result[label] = str(bucket.get('sample_warning') or 'low_sample')
    return result


def _pick_bucket_score_recommendation(
    calibration_report: dict[str, Any],
    bucket_label: str,
) -> dict[str, Any] | None:
    recs = calibration_report.get('recommendations') or []
    matches = [
        rec for rec in recs
        if isinstance(rec, dict)
        and str(rec.get('bucket') or '') == bucket_label
        and str(rec.get('type') or '') in CALIBRATION_SCORE_TYPES
    ]
    if not matches:
        return None
    return max(
        matches,
        key=lambda rec: CALIBRATION_STRENGTH_RANK.get(str(rec.get('strength') or 'weak'), 0),
    )


def apply_soft_calibration_adjustment(
    candidate_score: int,
    candidate: dict[str, Any],
    calibration_report: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Apply soft shadow calibration from confidence_calibration_report.json.

    Does not modify canonical outcomes or place trades.
    """
    _ = candidate  # reserved for future per-candidate calibration context
    base_score = _clamp(candidate_score, 0, 100)
    empty_component = {
        'component': 'calibration',
        'points': 0,
        'reason': 'no calibration report or bucket match',
    }
    default = {
        'adjusted_score': base_score,
        'calibration_applied': False,
        'calibration_adjustment': 0,
        'calibration_warning': None,
        'calibration_component': empty_component,
        'soft_warnings': [],
    }
    if not calibration_report or calibration_report.get('ok') is not True:
        return default

    from backend.analytics.confidence_calibration_engine import _score_bucket_label

    bucket_label = _score_bucket_label(base_score)
    if not bucket_label:
        return default

    rec = _pick_bucket_score_recommendation(calibration_report, bucket_label)
    if not rec:
        return default

    strength = str(rec.get('strength') or 'weak').lower()
    rec_type = str(rec.get('type') or '')
    sample_map = _bucket_sample_warning_map(calibration_report)
    sample_warning = sample_map.get(bucket_label, 'low_sample')
    sample_size = int(rec.get('sample_size') or 0)
    if sample_warning == 'low_sample' or sample_size < 10:
        return default

    if strength == 'weak':
        return {
            'adjusted_score': base_score,
            'calibration_applied': False,
            'calibration_adjustment': 0,
            'calibration_warning': 'weak_calibration_signal',
            'calibration_component': {
                'component': 'calibration',
                'points': 0,
                'reason': (
                    f'weak {rec_type} signal for bucket {bucket_label} '
                    f'(sample={sample_size}) — score unchanged'
                ),
            },
            'soft_warnings': ['weak_calibration_signal'],
        }

    cap = CALIBRATION_STRENGTH_CAPS.get(strength, 0)
    if cap <= 0:
        return default

    adjustment = cap if rec_type == 'increase_score' else -cap
    adjusted_score = _clamp(base_score + adjustment, 0, 100)
    applied = adjustment != 0
    reason = (
        f'{strength} {rec_type} for bucket {bucket_label} '
        f'(sample={sample_size}, error={rec.get("calibration_error")}) => {adjustment:+d}'
    )
    return {
        'adjusted_score': adjusted_score,
        'calibration_applied': applied,
        'calibration_adjustment': adjustment,
        'calibration_warning': None,
        'calibration_component': {
            'component': 'calibration',
            'points': adjustment,
            'reason': reason,
        },
        'soft_warnings': [],
    }


def _apply_buy_cap(
    decision: str,
    *,
    active_mode: str,
    market_closed: bool,
    soft_warnings: list[str],
) -> str:
    if decision != 'BUY_CANDIDATE':
        return decision
    if not _is_buy_cap_mode(active_mode, market_closed=market_closed):
        return decision
    if 'market_closed_buy_capped_to_watch' not in soft_warnings:
        soft_warnings.append('market_closed_buy_capped_to_watch')
    return 'WATCH'


def _merge_candidate(prediction: dict[str, Any]) -> dict[str, Any]:
    candidate = _prediction_to_candidate(prediction)
    candidate['signal_stack'] = prediction.get('signal_stack')
    candidate['raw_payload'] = prediction.get('raw_payload')
    candidate['source'] = prediction.get('source')
    candidate['confidence'] = prediction.get('confidence')
    return candidate


def _fetch_scoring_candidates(
    *,
    limit: int = 50,
    ticker: str | None = None,
    include_resolved: bool = False,
) -> list[dict[str, Any]]:
    if not include_resolved:
        predictions = fetch_unresolved_predictions(limit=limit, ticker=ticker)
        return [_merge_candidate(row) for row in predictions]

    from backend.storage.market_memory_db import get_connection, get_market_memory_stats, init_market_memory_db

    init_market_memory_db()
    stats = get_market_memory_stats()
    if not stats.get('db_exists'):
        return []

    clauses: list[str] = ['1=1']
    params: list[Any] = []
    if ticker:
        clauses.append('UPPER(p.ticker) = ?')
        params.append(str(ticker).strip().upper())

    sql = f"""
        SELECT p.*
        FROM predictions p
        WHERE {' AND '.join(clauses)}
        ORDER BY p.timestamp DESC
        LIMIT ?
    """
    params.append(max(0, int(limit)))

    conn = get_connection()
    try:
        conn.execute('PRAGMA query_only = ON')
        rows = conn.execute(sql, params).fetchall()
        return [_merge_candidate(dict(row)) for row in rows]
    finally:
        conn.close()


def score_candidate(
    candidate: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score one prediction candidate (read-only shadow fusion)."""
    ctx = context or {}
    ticker = _normalize_ticker(candidate.get('ticker'))
    hard_warnings: list[str] = []
    soft_warnings: list[str] = []
    explanations: list[str] = []

    if not ticker:
        hard_warnings.append('missing_ticker')
        return {
            'ok': True,
            'ticker': None,
            'prediction_id': candidate.get('prediction_id'),
            'direction': candidate.get('direction'),
            'confidence_label': candidate.get('confidence_label'),
            'final_score': 0,
            'decision': 'NO_DECISION',
            'base_score': BASE_SCORE,
            'adjustments': {key: 0 for key in ADJUSTMENT_CAPS},
            'total_adjustment': 0,
            'hard_warnings': hard_warnings,
            'warnings': soft_warnings,
            'explanations': ['missing ticker => NO_DECISION'],
            'shadow_mode': SHADOW_MODE,
            'disclaimer': DISCLAIMER,
        }

    if not str(candidate.get('prediction_id') or '').strip():
        hard_warnings.append('missing_prediction_id')
        return {
            'ok': True,
            'ticker': ticker,
            'prediction_id': candidate.get('prediction_id'),
            'direction': candidate.get('direction'),
            'confidence_label': candidate.get('confidence_label'),
            'final_score': 0,
            'decision': 'NO_DECISION',
            'base_score': BASE_SCORE,
            'adjustments': {key: 0 for key in ADJUSTMENT_CAPS},
            'total_adjustment': 0,
            'hard_warnings': hard_warnings,
            'warnings': soft_warnings,
            'explanations': ['missing prediction_id => NO_DECISION'],
            'shadow_mode': SHADOW_MODE,
            'disclaimer': DISCLAIMER,
        }

    direction = _candidate_direction(candidate)

    latest_prices = ctx.get('latest_prices')
    if latest_prices is None:
        latest_prices = _load_latest_prices()

    advice_fn: Callable[..., dict[str, Any]] = ctx.get('advise_prediction') or advise_prediction
    advice = advice_fn(candidate)

    adjustments: dict[str, int] = {}
    components: dict[str, Any] = {'advisor': advice}

    a_adj, a_warn, a_expl = _adjustment_a_memory_advisor(advice)
    adjustments['A_memory_advisor'] = a_adj
    soft_warnings.extend(a_warn)
    explanations.extend(a_expl)

    b_adj, b_warn, b_expl = _adjustment_b_broker_consensus(candidate)
    adjustments['B_broker_consensus'] = b_adj
    soft_warnings.extend(b_warn)
    explanations.extend(b_expl)
    components['broker_consensus'] = {'adjustment': b_adj}

    c_fn = ctx.get('broker_intelligence_fn')
    if c_fn:
        c_payload = c_fn(ticker)
        relationship = str((c_payload.get('our_vs_broker') or {}).get('relationship') or 'unclear')
        c_adj = 8 if relationship == 'agreement' else (-10 if relationship == 'conflict' else 0)
        c_adj = _clamp(c_adj, -ADJUSTMENT_CAPS['C_broker_intelligence'], ADJUSTMENT_CAPS['C_broker_intelligence'])
        c_warn = ['broker_intelligence_conflict'] if relationship == 'conflict' else []
        c_expl = [f'C: broker intelligence relationship={relationship} => {c_adj:+d}']
    else:
        c_adj, c_warn, c_expl = _adjustment_c_broker_intelligence(ticker)
    adjustments['C_broker_intelligence'] = c_adj
    soft_warnings.extend(c_warn)
    explanations.extend(c_expl)

    d_fn = ctx.get('historical_fn')
    if d_fn:
        d_payload = d_fn(ticker)
        overall = d_payload.get('overall') or {}
        resolved = int(overall.get('wins', 0) + overall.get('losses', 0))
        win_rate = overall.get('win_rate')
        d_adj = 0
        if resolved >= 5 and isinstance(win_rate, (int, float)):
            if float(win_rate) >= 0.60:
                d_adj = 8
            elif float(win_rate) <= 0.25:
                d_adj = -10
        d_adj = _clamp(d_adj, -ADJUSTMENT_CAPS['D_historical_learning'], ADJUSTMENT_CAPS['D_historical_learning'])
        d_warn: list[str] = []
        d_expl = [f'D: historical replay n={resolved} => {d_adj:+d}']
    else:
        d_adj, d_warn, d_expl = _adjustment_d_historical_learning(ticker)
    adjustments['D_historical_learning'] = d_adj
    soft_warnings.extend(d_warn)
    explanations.extend(d_expl)

    sim_fn = ctx.get('simulation_fn')
    if sim_fn:
        sim_evidence = sim_fn(candidate)
    else:
        from backend.analytics.simulation_performance_adapter import score_simulation_evidence

        sim_evidence = score_simulation_evidence(candidate)
    h_adj = int(sim_evidence.get('confidence_adjustment') or 0)
    h_adj = _clamp(h_adj, -ADJUSTMENT_CAPS['H_historical_simulation'], ADJUSTMENT_CAPS['H_historical_simulation'])
    adjustments['H_historical_simulation'] = h_adj
    components['historical_simulation'] = sim_evidence
    sim_warn = list(sim_evidence.get('warnings') or [])
    soft_warnings.extend(sim_warn)
    sim_reasons = sim_evidence.get('reasons') or []
    if h_adj != 0:
        explanations.append(
            f'H: historical simulation {sim_evidence.get("inferred_strategy")} => {h_adj:+d}'
        )
    elif sim_warn:
        explanations.append('H: historical simulation — low sample, no adjustment')
    elif sim_reasons:
        explanations.append(f'H: historical simulation — {sim_reasons[0]}')

    if ctx.get('router_fn'):
        e_payload = ctx['router_fn']()
        active_mode = str(e_payload.get('active_mode') or 'RESEARCH_MODE')
        e_adj = 5 if active_mode == 'INDIA_MODE' else (-3 if active_mode == 'RESEARCH_MODE' else 1)
        e_adj = _clamp(e_adj, -ADJUSTMENT_CAPS['E_market_router'], ADJUSTMENT_CAPS['E_market_router'])
        e_warn = list(e_payload.get('warnings') or [])
        e_expl = [f'E: market router mode={active_mode} => {e_adj:+d}']
    else:
        e_adj, e_warn, e_expl = _adjustment_e_market_router()
    adjustments['E_market_router'] = e_adj
    soft_warnings.extend(e_warn)
    explanations.extend(e_expl)

    if ctx.get('freshness_fn'):
        f_report = ctx['freshness_fn']()
        safe = bool(f_report.get('safe_to_use'))
        f_adj = 3 if safe else -8
        f_adj = _clamp(f_adj, -ADJUSTMENT_CAPS['F_source_freshness'], ADJUSTMENT_CAPS['F_source_freshness'])
        f_warn = list(f_report.get('warnings') or [])
        if not safe:
            f_warn.append('stale_critical_sources')
        f_expl = [f'F: source freshness safe_to_use={safe} => {f_adj:+d}']
    else:
        f_adj, f_warn, f_expl = _adjustment_f_source_freshness()
    adjustments['F_source_freshness'] = f_adj
    soft_warnings.extend(f_warn)
    explanations.extend(f_expl)

    g_adj, g_warn, g_expl, g_hard = _adjustment_g_price_sanity(candidate, latest_prices)
    adjustments['G_price_sanity'] = g_adj
    soft_warnings.extend(g_warn)
    hard_warnings.extend(g_hard)
    explanations.extend(g_expl)

    total_adjustment = sum(adjustments.values())
    score_without_simulation = _clamp(
        BASE_SCORE + total_adjustment - adjustments.get('H_historical_simulation', 0),
        0,
        100,
    )
    pre_calibration_score = _clamp(BASE_SCORE + total_adjustment, 0, 100)

    has_minimum_evidence = _has_minimum_evidence(
        candidate,
        direction=direction,
        advice=advice,
        adjustments=adjustments,
        soft_warnings=soft_warnings,
    )
    if _missing_price_without_evidence(
        candidate,
        latest_prices,
        has_minimum_evidence=has_minimum_evidence,
    ):
        hard_warnings.append('insufficient_evidence')

    active_mode, market_closed = _get_market_context(ctx)

    pre_sim_decision = _resolve_decision(
        final_score=score_without_simulation,
        direction=direction,
        hard_warnings=hard_warnings,
        soft_warnings=soft_warnings,
        has_minimum_evidence=has_minimum_evidence,
    )

    pre_decision = _resolve_decision(
        final_score=pre_calibration_score,
        direction=direction,
        hard_warnings=hard_warnings,
        soft_warnings=soft_warnings,
        has_minimum_evidence=has_minimum_evidence,
    )
    if (
        pre_sim_decision == 'AVOID'
        and pre_decision == 'BUY_CANDIDATE'
        and adjustments.get('H_historical_simulation', 0) > 0
    ):
        pre_decision = 'WATCH'
        soft_warnings.append('simulation_avoid_buy_blocked')

    calibration_report = ctx.get('calibration_report')
    if calibration_report is None and ctx.get('load_calibration') is not False:
        calibration_report = load_calibration_report()

    cal_result = apply_soft_calibration_adjustment(
        pre_calibration_score,
        candidate,
        calibration_report,
    )
    final_score = int(cal_result.get('adjusted_score') or pre_calibration_score)
    calibration_adjustment = int(cal_result.get('calibration_adjustment') or 0)
    calibration_applied = bool(cal_result.get('calibration_applied'))
    calibration_warning = cal_result.get('calibration_warning')
    calibration_component = cal_result.get('calibration_component') or {
        'component': 'calibration',
        'points': 0,
        'reason': 'no calibration adjustment',
    }
    soft_warnings.extend(cal_result.get('soft_warnings') or [])
    if calibration_warning:
        soft_warnings.append(str(calibration_warning))
    if calibration_adjustment != 0:
        explanations.append(
            f'H: soft calibration {calibration_component.get("reason", "")} => {calibration_adjustment:+d}'
        )

    pre_external_decision = _resolve_decision(
        final_score=final_score,
        direction=direction,
        hard_warnings=hard_warnings,
        soft_warnings=soft_warnings,
        has_minimum_evidence=has_minimum_evidence,
    )

    ext_fn = ctx.get('external_evidence_fn')
    if ext_fn:
        ext_evidence = ext_fn(candidate, pre_decision=pre_external_decision)
    else:
        from backend.analytics.external_evidence_adapter import score_external_evidence

        ext_evidence = score_external_evidence(candidate, pre_decision=pre_external_decision)

    i_adj = int(ext_evidence.get('confidence_adjustment') or 0)
    i_adj = _clamp(i_adj, -ADJUSTMENT_CAPS['I_external_evidence'], ADJUSTMENT_CAPS['I_external_evidence'])
    adjustments['I_external_evidence'] = i_adj
    components['external_evidence'] = ext_evidence
    ext_warn = list(ext_evidence.get('warnings') or [])
    soft_warnings.extend(ext_warn)
    ext_reasons = ext_evidence.get('reasons') or []
    ext_reason = ext_reasons[0] if ext_reasons else str(ext_evidence.get('summary_reason') or 'external evidence')
    if i_adj != 0:
        explanations.append(f'I: external evidence {ext_reason} => {i_adj:+d}')
    elif ext_warn:
        explanations.append('I: external evidence — no score adjustment')

    final_score = _clamp(final_score + i_adj, 0, 100)
    total_adjustment = sum(adjustments.values())

    sim_component_reason = '; '.join(sim_reasons[:2]) if sim_reasons else 'historical simulation'
    if h_adj != 0:
        sim_breakdown = {
            'component': 'historical_simulation',
            'points': h_adj,
            'reason': sim_component_reason,
        }
    else:
        sim_breakdown = {
            'component': 'historical_simulation',
            'points': 0,
            'reason': sim_component_reason or 'no simulation adjustment',
        }

    score_breakdown: list[dict[str, Any]] = [
        {'component': key.replace('_', ' '), 'points': val, 'reason': key}
        for key, val in adjustments.items()
        if val != 0
    ]
    if h_adj != 0 or sim_warn:
        score_breakdown.append(sim_breakdown)
    score_breakdown.append(calibration_component)
    if i_adj != 0 or ext_warn:
        score_breakdown.append({
            'component': 'external_evidence',
            'points': i_adj,
            'reason': ext_reason,
        })

    decision = _resolve_decision(
        final_score=final_score,
        direction=direction,
        hard_warnings=hard_warnings,
        soft_warnings=soft_warnings,
        has_minimum_evidence=has_minimum_evidence,
    )
    if (
        pre_decision == 'AVOID'
        and decision == 'BUY_CANDIDATE'
        and calibration_adjustment > 0
    ):
        decision = 'WATCH'
        soft_warnings.append('calibration_avoid_buy_blocked')
    if (
        pre_external_decision == 'AVOID'
        and decision == 'BUY_CANDIDATE'
        and i_adj > 0
    ):
        decision = 'WATCH'
        soft_warnings.append('external_evidence_avoid_buy_blocked')
    if (
        pre_external_decision != 'BUY_CANDIDATE'
        and decision == 'BUY_CANDIDATE'
        and i_adj > 0
    ):
        decision = 'WATCH'
        soft_warnings.append('external_evidence_buy_blocked')

    decision = _apply_buy_cap(
        decision,
        active_mode=active_mode,
        market_closed=market_closed,
        soft_warnings=soft_warnings,
    )

    deduped_soft = sorted({str(item) for item in soft_warnings if str(item).strip()})
    deduped_hard = sorted({str(item) for item in hard_warnings if str(item).strip()})

    return {
        'ok': True,
        'ticker': ticker,
        'prediction_id': candidate.get('prediction_id'),
        'direction': candidate.get('direction'),
        'confidence_label': candidate.get('confidence_label'),
        'signal_type': candidate.get('signal_type'),
        'prediction_horizon': candidate.get('prediction_horizon'),
        'final_score': final_score,
        'pre_calibration_score': pre_calibration_score,
        'decision': decision,
        'base_score': BASE_SCORE,
        'adjustments': adjustments,
        'total_adjustment': total_adjustment,
        'calibration_applied': calibration_applied,
        'calibration_adjustment': calibration_adjustment,
        'calibration_warning': calibration_warning,
        'historical_simulation': sim_evidence,
        'simulation_adjustment': h_adj,
        'external_evidence': ext_evidence.get('external_evidence') or ext_evidence,
        'external_evidence_adjustment': i_adj,
        'hard_warnings': deduped_hard,
        'warnings': deduped_soft,
        'explanations': explanations,
        'score_breakdown': score_breakdown,
        'components': components,
        'active_mode': active_mode,
        'market_closed': market_closed,
        'buy_cap_active': _is_buy_cap_mode(active_mode, market_closed=market_closed),
        'shadow_mode': SHADOW_MODE,
        'disclaimer': DISCLAIMER,
    }


def score_all_candidates(
    limit: int = 50,
    *,
    ticker: str | None = None,
    include_resolved: bool = False,
) -> dict[str, Any]:
    """Score active/unresolved candidates and return sorted rows."""
    candidates = _fetch_scoring_candidates(limit=limit, ticker=ticker, include_resolved=include_resolved)
    latest_prices = _load_latest_prices()
    calibration_report = load_calibration_report()
    scoring_ctx: dict[str, Any] = {
        'latest_prices': latest_prices,
        'calibration_report': calibration_report,
    }
    rows: list[dict[str, Any]] = []
    candidates_adjusted = 0
    candidates_weak_signal = 0
    simulation_applied = 0
    simulation_positive = 0
    simulation_negative = 0
    simulation_neutral = 0

    for candidate in candidates:
        scored = score_candidate(candidate, context=scoring_ctx)
        if scored.get('calibration_applied'):
            candidates_adjusted += 1
        if scored.get('calibration_warning') == 'weak_calibration_signal':
            candidates_weak_signal += 1
        sim_adj = int(scored.get('simulation_adjustment') or 0)
        if sim_adj != 0:
            simulation_applied += 1
            if sim_adj > 0:
                simulation_positive += 1
            else:
                simulation_negative += 1
        else:
            simulation_neutral += 1
        rows.append({
            'ticker': scored.get('ticker'),
            'prediction_id': scored.get('prediction_id'),
            'direction': scored.get('direction'),
            'confidence_label': scored.get('confidence_label'),
            'signal_type': scored.get('signal_type'),
            'prediction_horizon': scored.get('prediction_horizon'),
            'final_score': scored.get('final_score'),
            'pre_calibration_score': scored.get('pre_calibration_score'),
            'decision': scored.get('decision'),
            'total_adjustment': scored.get('total_adjustment'),
            'calibration_applied': scored.get('calibration_applied'),
            'calibration_adjustment': scored.get('calibration_adjustment'),
            'calibration_warning': scored.get('calibration_warning'),
            'historical_simulation': scored.get('historical_simulation'),
            'simulation_adjustment': sim_adj,
            'external_evidence': scored.get('external_evidence'),
            'external_evidence_adjustment': scored.get('external_evidence_adjustment'),
            'hard_warnings': scored.get('hard_warnings'),
            'warnings': scored.get('warnings'),
            'explanations': scored.get('explanations'),
        })

    rows.sort(
        key=lambda item: (
            -(item.get('final_score') or 0),
            str(item.get('ticker') or ''),
        ),
    )

    counts = {key: 0 for key in VALID_DECISIONS}
    for row in rows:
        decision = str(row.get('decision') or 'NO_DECISION')
        if decision in counts:
            counts[decision] += 1

    return {
        'ok': True,
        'checked': len(rows),
        'buy_candidate': counts['BUY_CANDIDATE'],
        'watch': counts['WATCH'],
        'avoid': counts['AVOID'],
        'no_decision': counts['NO_DECISION'],
        'counts': counts,
        'rows': rows,
        'calibration': {
            'report_loaded': calibration_report is not None,
            'candidates_adjusted': candidates_adjusted,
            'candidates_weak_signal': candidates_weak_signal,
        },
        'simulation': {
            'simulation_applied': simulation_applied,
            'simulation_positive': simulation_positive,
            'simulation_negative': simulation_negative,
            'simulation_neutral': simulation_neutral,
        },
        'shadow_mode': SHADOW_MODE,
        'disclaimer': DISCLAIMER,
    }


def get_final_confidence_dashboard(limit: int = 50) -> dict[str, Any]:
    """Dashboard payload with decision counts and top candidates."""
    batch = score_all_candidates(limit=limit)
    top = list(batch.get('rows') or [])[: min(limit, 25)]

    return {
        'ok': True,
        'checked': batch.get('checked', 0),
        'buy_candidate': batch.get('buy_candidate', 0),
        'watch': batch.get('watch', 0),
        'avoid': batch.get('avoid', 0),
        'no_decision': batch.get('no_decision', 0),
        'counts': batch.get('counts') or {},
        'top_candidates': top,
        'rows': batch.get('rows') or [],
        'calibration': batch.get('calibration') or {},
        'simulation': batch.get('simulation') or {},
        'shadow_mode': SHADOW_MODE,
        'disclaimer': DISCLAIMER,
    }


def explain_score_breakdown(ticker: str) -> dict[str, Any]:
    """Detailed fusion breakdown for the latest candidate on a ticker."""
    normalized = _normalize_ticker(ticker)
    if not normalized:
        return {'ok': False, 'error': 'ticker is required'}

    candidates = _fetch_scoring_candidates(limit=5, ticker=normalized, include_resolved=True)
    if not candidates:
        return {
            'ok': True,
            'ticker': normalized,
            'found': False,
            'message': 'no predictions found for ticker',
            'shadow_mode': SHADOW_MODE,
            'disclaimer': DISCLAIMER,
        }

    scored = score_candidate(candidates[0])
    return {
        'ok': True,
        'ticker': normalized,
        'found': True,
        'candidate_count': len(candidates),
        'breakdown': scored,
        'shadow_mode': SHADOW_MODE,
        'disclaimer': DISCLAIMER,
    }


def build_final_confidence_report(limit: int = 50) -> dict[str, Any]:
    """Full report payload for JSON export."""
    from backend.analytics.market_calendar_router import get_active_market_mode

    mode_payload = get_active_market_mode()
    active_mode = str(mode_payload.get('active_mode') or 'RESEARCH_MODE')
    india_session = str(mode_payload.get('india_session') or '')
    usa_session = str(mode_payload.get('usa_session') or '')
    market_closed = india_session == 'closed' and usa_session == 'closed'

    dashboard = get_final_confidence_dashboard(limit=limit)
    buy_cap_active = _is_buy_cap_mode(active_mode, market_closed=market_closed)
    calibration_stats = dashboard.get('calibration') or {}
    simulation_stats = dashboard.get('simulation') or {}

    return {
        'ok': True,
        'report_type': 'final_confidence_fusion',
        'shadow_mode': SHADOW_MODE,
        'disclaimer': DISCLAIMER,
        'active_mode': active_mode,
        'market_closed': market_closed,
        'buy_cap_active': buy_cap_active,
        'summary': {
            'checked': dashboard.get('checked', 0),
            'buy_candidate': dashboard.get('buy_candidate', 0),
            'watch': dashboard.get('watch', 0),
            'avoid': dashboard.get('avoid', 0),
            'no_decision': dashboard.get('no_decision', 0),
            'active_mode': active_mode,
            'market_closed': market_closed,
            'buy_cap_active': buy_cap_active,
        },
        'calibration': {
            'report_loaded': bool(calibration_stats.get('report_loaded')),
            'candidates_adjusted': int(calibration_stats.get('candidates_adjusted') or 0),
            'candidates_weak_signal': int(calibration_stats.get('candidates_weak_signal') or 0),
        },
        'simulation': {
            'simulation_applied': int(simulation_stats.get('simulation_applied') or 0),
            'simulation_positive': int(simulation_stats.get('simulation_positive') or 0),
            'simulation_negative': int(simulation_stats.get('simulation_negative') or 0),
            'simulation_neutral': int(simulation_stats.get('simulation_neutral') or 0),
        },
        'top_candidates': dashboard.get('top_candidates') or [],
        'rows': dashboard.get('rows') or [],
    }
