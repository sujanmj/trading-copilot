"""
Historical simulation performance adapter — read-only evidence for final confidence.

Uses historical_strategy_performance and historical_simulated_outcomes.
Does not write predictions/outcomes or trigger trades.
"""

from __future__ import annotations

import json
import re
from typing import Any

from backend.storage.historical_market_store import (
    get_connection,
    get_simulation_stats,
    get_strategy_performance as _store_get_strategy_performance,
)

SIMULATION_ADJUSTMENT_CAP = 10
LOW_STRATEGY_SAMPLE = 50
LOW_TICKER_SAMPLE = 20

KNOWN_STRATEGIES = (
    'momentum_breakout_20',
    'mean_reversion_rsi',
    'bearish_breakdown_20',
)
KNOWN_STRATEGY_SET = frozenset(KNOWN_STRATEGIES)
DEFAULT_MARKET = 'INDIA'

MOMENTUM_TOKENS = re.compile(
    r'\b(breakout|momentum|ultra\s*scanner|high\s*volume)\b',
    re.IGNORECASE,
)
MEAN_REVERSION_TOKENS = re.compile(
    r'\b(oversold|reversal|rsi|mean\s*reversion)\b',
    re.IGNORECASE,
)
BEARISH_TOKENS = re.compile(r'\b(breakdown|bearish)\b', re.IGNORECASE)


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


def _candidate_text_blob(candidate: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ('signal_type', 'direction', 'confidence_label', 'category'):
        val = candidate.get(key)
        if val is not None and str(val).strip():
            parts.append(str(val))
    raw = _parse_json_field(candidate.get('raw_payload'))
    if raw:
        for key in ('category', 'signal_type', 'direction', 'notes', 'label', 'text'):
            val = raw.get(key)
            if val is not None and str(val).strip():
                parts.append(str(val))
        parts.append(json.dumps(raw, default=str))
    return ' '.join(parts)


def _win_rate_percent(win_rate: object) -> float | None:
    if win_rate is None:
        return None
    try:
        value = float(win_rate)
    except (TypeError, ValueError):
        return None
    if value <= 1.0:
        return value * 100.0
    return value


def _clamp_adj(value: int) -> int:
    return int(max(-SIMULATION_ADJUSTMENT_CAP, min(SIMULATION_ADJUSTMENT_CAP, value)))


def _zero_strategy_row(
    strategy: str,
    *,
    market: str = DEFAULT_MARKET,
    warning: str = 'missing_strategy_performance_row',
) -> dict[str, Any]:
    return {
        'strategy': strategy,
        'market': market,
        'predictions': 0,
        'resolved': 0,
        'wins': 0,
        'losses': 0,
        'ambiguous': 0,
        'win_rate': None,
        'avg_gain_pct': None,
        'avg_loss_pct': None,
        'expectancy_pct': None,
        'max_drawdown_proxy': None,
        'sample_warning': warning,
        'coverage_warning': warning,
    }


def _aggregate_strategy_from_outcomes(
    strategy: str,
    *,
    market: str | None = None,
) -> dict[str, Any]:
    """Aggregate one strategy directly from simulated outcomes when perf row is missing."""
    clauses = ['o.strategy = ?']
    params: list[Any] = [strategy]
    if market:
        clauses.append('COALESCE(p.market, ?) = ?')
        params.extend([DEFAULT_MARKET, str(market).strip().upper()])

    conn = get_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT
                o.result,
                o.max_gain_pct,
                o.max_loss_pct,
                o.close_move_pct,
                COALESCE(p.market, ?) AS market
            FROM historical_simulated_outcomes o
            LEFT JOIN historical_simulated_predictions p
              ON p.sim_prediction_id = o.sim_prediction_id
            WHERE {' AND '.join(clauses)}
            """,
            [DEFAULT_MARKET, *params],
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return _zero_strategy_row(strategy, market=market or DEFAULT_MARKET)

    market_key = str(rows[0]['market'] or market or DEFAULT_MARKET)
    wins = losses = ambiguous = 0
    gains: list[float] = []
    loss_vals: list[float] = []
    for row in rows:
        token = str(row['result'] or '').strip().upper()
        if token in ('WIN',) or token.startswith('WIN'):
            wins += 1
        elif token in ('LOSS',) or token.startswith('LOSS'):
            losses += 1
        elif token == 'AMBIGUOUS_DAILY_CANDLE':
            ambiguous += 1
        for field, dest in (('max_gain_pct', gains), ('max_loss_pct', loss_vals)):
            val = row[field]
            if val is not None:
                try:
                    dest.append(float(val))
                except (TypeError, ValueError):
                    pass

    resolved = wins + losses + ambiguous
    predictions = len(rows)
    if resolved < predictions:
        resolved = predictions
    win_rate = wins / (wins + losses) if (wins + losses) > 0 else None
    avg_gain = sum(gains) / len(gains) if gains else None
    avg_loss = sum(loss_vals) / len(loss_vals) if loss_vals else None
    expectancy_pct = None
    if win_rate is not None and avg_gain is not None and avg_loss is not None:
        expectancy_pct = (win_rate * avg_gain) + ((1 - win_rate) * avg_loss)

    return {
        'strategy': strategy,
        'market': market_key,
        'predictions': predictions,
        'resolved': resolved,
        'wins': wins,
        'losses': losses,
        'ambiguous': ambiguous,
        'win_rate': win_rate,
        'avg_gain_pct': avg_gain,
        'avg_loss_pct': avg_loss,
        'expectancy_pct': expectancy_pct,
        'max_drawdown_proxy': min(loss_vals) if loss_vals else None,
        'sample_warning': 'low_sample_size' if resolved < 5 else None,
        'coverage_warning': 'derived_from_outcomes',
    }


def _distinct_outcome_strategies(*, market: str | None = None) -> set[str]:
    conn = get_connection()
    try:
        if market:
            rows = conn.execute(
                """
                SELECT DISTINCT o.strategy AS strategy
                FROM historical_simulated_outcomes o
                LEFT JOIN historical_simulated_predictions p
                  ON p.sim_prediction_id = o.sim_prediction_id
                WHERE COALESCE(p.market, ?) = ?
                ORDER BY o.strategy ASC
                """,
                (DEFAULT_MARKET, str(market).strip().upper()),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT DISTINCT strategy
                FROM historical_simulated_outcomes
                WHERE strategy IS NOT NULL AND TRIM(strategy) != ''
                ORDER BY strategy ASC
                """
            ).fetchall()
    finally:
        conn.close()
    return {str(row['strategy']) for row in rows if row['strategy']}


def _db_strategy_performance_count(*, market: str | None = None) -> int:
    conn = get_connection()
    try:
        if market:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT strategy) AS cnt
                FROM historical_strategy_performance
                WHERE market = ?
                """,
                (str(market).strip().upper(),),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT strategy) AS cnt
                FROM historical_strategy_performance
                """
            ).fetchone()
    finally:
        conn.close()
    return int(row['cnt']) if row else 0


def _normalize_strategy_rows(
    *,
    market: str | None = None,
) -> list[dict[str, Any]]:
    """
    Return all relevant strategy rows without hiding DB-backed strategies.

    Uses historical_strategy_performance first, then fills gaps from simulated
    outcomes or zero-sample placeholders for known strategies.
    """
    perf_rows = _store_get_strategy_performance(market=market)
    perf_by_name = {str(row.get('strategy') or ''): row for row in perf_rows if row.get('strategy')}
    outcome_names = _distinct_outcome_strategies(market=market)
    target_names = list(KNOWN_STRATEGIES) + sorted(
        name for name in (set(perf_by_name) | outcome_names)
        if name not in KNOWN_STRATEGY_SET
    )

    normalized: list[dict[str, Any]] = []
    for name in target_names:
        if name in perf_by_name:
            row = dict(perf_by_name[name])
            row.setdefault('coverage_warning', None)
            normalized.append(row)
            continue

        derived = _aggregate_strategy_from_outcomes(name, market=market)
        if int(derived.get('resolved') or 0) > 0:
            normalized.append(derived)
        else:
            normalized.append(_zero_strategy_row(name, market=market or DEFAULT_MARKET))

    return normalized


def get_simulation_summary() -> dict[str, Any]:
    """Aggregate simulation stats plus strategy performance rows."""
    stats = get_simulation_stats()
    strategies = _normalize_strategy_rows()
    db_strategy_count = _db_strategy_performance_count()
    return {
        'ok': True,
        'stats': stats,
        'strategy_count': len(strategies),
        'db_strategy_count': db_strategy_count,
        'strategies': strategies,
    }


def get_strategy_performance(strategy: str | None = None) -> dict[str, Any]:
    """Return strategy performance rows, optionally filtered to one strategy."""
    rows = _normalize_strategy_rows()
    if strategy:
        token = str(strategy).strip()
        rows = [row for row in rows if str(row.get('strategy') or '') == token]

    if not rows:
        placeholder = _zero_strategy_row(
            str(strategy or 'UNKNOWN'),
            warning='strategy_not_found',
        )
        rows = [placeholder]

    predictions = sum(int(row.get('predictions') or 0) for row in rows)
    resolved = sum(int(row.get('resolved') or 0) for row in rows)
    wins = sum(int(row.get('wins') or 0) for row in rows)
    losses = sum(int(row.get('losses') or 0) for row in rows)
    win_rate = wins / (wins + losses) if (wins + losses) > 0 else None

    expectancy_values = [
        float(row['expectancy_pct'])
        for row in rows
        if row.get('expectancy_pct') is not None
    ]
    expectancy_pct = None
    if expectancy_values and resolved > 0:
        weights = [int(row.get('resolved') or 0) for row in rows if row.get('expectancy_pct') is not None]
        total_w = sum(weights)
        if total_w > 0:
            expectancy_pct = sum(
                float(row['expectancy_pct']) * int(row.get('resolved') or 0)
                for row in rows
                if row.get('expectancy_pct') is not None
            ) / total_w

    return {
        'ok': True,
        'strategy': strategy,
        'rows': rows,
        'aggregate': {
            'predictions': predictions,
            'resolved': resolved,
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'expectancy_pct': expectancy_pct,
        },
    }


def get_ticker_simulation_performance(ticker: str) -> dict[str, Any]:
    """Aggregate simulated outcome stats for a ticker."""
    normalized = _normalize_ticker(ticker)
    if not normalized:
        return {
            'ok': False,
            'error': 'ticker is required',
            'ticker': None,
            'sample': 0,
            'wins': 0,
            'losses': 0,
            'ambiguous': 0,
            'win_rate': None,
            'expectancy_pct': None,
        }

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT result, max_gain_pct, max_loss_pct, close_move_pct, strategy
            FROM historical_simulated_outcomes
            WHERE ticker = ?
            """,
            (normalized,),
        ).fetchall()
    finally:
        conn.close()

    wins = losses = ambiguous = 0
    gains: list[float] = []
    loss_vals: list[float] = []
    for row in rows:
        token = str(row['result'] or '').strip().upper()
        if token in ('WIN',) or token.startswith('WIN'):
            wins += 1
        elif token in ('LOSS',) or token.startswith('LOSS'):
            losses += 1
        elif token == 'AMBIGUOUS_DAILY_CANDLE':
            ambiguous += 1
        for field, dest in (('max_gain_pct', gains), ('max_loss_pct', loss_vals)):
            val = row[field]
            if val is not None:
                try:
                    dest.append(float(val))
                except (TypeError, ValueError):
                    pass

    resolved = wins + losses + ambiguous
    win_rate = wins / (wins + losses) if (wins + losses) > 0 else None
    avg_gain = sum(gains) / len(gains) if gains else None
    avg_loss = sum(loss_vals) / len(loss_vals) if loss_vals else None
    expectancy_pct = None
    if win_rate is not None and avg_gain is not None and avg_loss is not None:
        expectancy_pct = (win_rate * avg_gain) + ((1 - win_rate) * avg_loss)

    return {
        'ok': True,
        'ticker': normalized,
        'sample': resolved,
        'wins': wins,
        'losses': losses,
        'ambiguous': ambiguous,
        'win_rate': win_rate,
        'expectancy_pct': expectancy_pct,
    }


def infer_candidate_strategy(candidate: dict[str, Any]) -> dict[str, Any]:
    """Map candidate metadata to a simulated strategy name."""
    blob = _candidate_text_blob(candidate)
    reasons: list[str] = []

    direction = str(candidate.get('direction') or '').strip().upper()
    category = str(candidate.get('category') or '').strip().upper()
    if not category:
        raw = _parse_json_field(candidate.get('raw_payload'))
        if raw:
            category = str(raw.get('category') or '').strip().upper()

    if direction == 'BEARISH' or category in {'BREAKDOWN', 'BEARISH'} or BEARISH_TOKENS.search(blob):
        reasons.append('bearish/breakdown signals')
        return {
            'ok': True,
            'inferred_strategy': 'bearish_breakdown_20',
            'confidence': 'high',
            'reasons': reasons,
        }

    if MOMENTUM_TOKENS.search(blob):
        reasons.append('momentum/breakout signals')
        return {
            'ok': True,
            'inferred_strategy': 'momentum_breakout_20',
            'confidence': 'high',
            'reasons': reasons,
        }

    if MEAN_REVERSION_TOKENS.search(blob):
        reasons.append('mean-reversion/rsi signals')
        return {
            'ok': True,
            'inferred_strategy': 'mean_reversion_rsi',
            'confidence': 'high',
            'reasons': reasons,
        }

    reasons.append('no strong strategy keyword match')
    return {
        'ok': True,
        'inferred_strategy': 'UNKNOWN',
        'confidence': 'low',
        'reasons': reasons,
    }


def _pick_strategy_row(inferred: str, rows: list[dict]) -> dict | None:
    matches = [row for row in rows if str(row.get('strategy') or '') == inferred]
    if not matches:
        return None
    return max(matches, key=lambda row: int(row.get('resolved') or 0))


def _strategy_adjustment(
    *,
    inferred: str,
    strategy_row: dict | None,
    broad_agg: dict,
    candidate: dict[str, Any],
) -> tuple[int, list[str], list[str]]:
    warnings: list[str] = []
    reasons: list[str] = []
    adjustment = 0

    if strategy_row:
        sample = int(strategy_row.get('resolved') or 0)
        win_rate_pct = _win_rate_percent(strategy_row.get('win_rate'))
        expectancy = strategy_row.get('expectancy_pct')
    elif inferred == 'UNKNOWN':
        sample = int(broad_agg.get('resolved') or 0)
        win_rate_pct = _win_rate_percent(broad_agg.get('win_rate'))
        expectancy = broad_agg.get('expectancy_pct')
    else:
        return 0, ['strategy_not_in_simulation_db'], ['inferred strategy has no performance row']

    if sample < LOW_STRATEGY_SAMPLE:
        warnings.append('low_simulation_sample')
        reasons.append(f'strategy sample {sample} < {LOW_STRATEGY_SAMPLE} => no adjustment')
        return 0, warnings, reasons

    try:
        exp_val = float(expectancy) if expectancy is not None else None
    except (TypeError, ValueError):
        exp_val = None

    max_adj = 2 if inferred == 'UNKNOWN' else SIMULATION_ADJUSTMENT_CAP

    if exp_val is not None and exp_val > 0 and win_rate_pct is not None and win_rate_pct >= 45.0:
        strength = min(1.0, (exp_val / 2.0) + ((win_rate_pct - 45.0) / 40.0))
        raw = 2 + round(3 * strength)
        adjustment = _clamp_adj(min(raw, max_adj))
        reasons.append(
            f'positive simulation expectancy={exp_val:.3f}% win_rate={win_rate_pct:.1f}% => +{adjustment}'
        )
    elif (
        (exp_val is not None and exp_val < -0.5)
        or (win_rate_pct is not None and win_rate_pct < 42.0)
    ):
        neg_strength = 0.5
        if exp_val is not None and exp_val < -0.5:
            neg_strength += min(1.0, abs(exp_val + 0.5) / 2.0)
        if win_rate_pct is not None and win_rate_pct < 42.0:
            neg_strength += min(1.0, (42.0 - win_rate_pct) / 20.0)
        raw = -3 - round(5 * min(1.0, neg_strength))
        adjustment = _clamp_adj(max(raw, -max_adj))
        reasons.append(
            f'weak simulation expectancy={exp_val} win_rate={win_rate_pct} => {adjustment}'
        )
    else:
        reasons.append('simulation metrics neutral — no adjustment')

    if (
        inferred == 'bearish_breakdown_20'
        and exp_val is not None
        and exp_val < 0
        and _is_bearish_candidate(candidate)
    ):
        extra = -2 if exp_val < -0.5 else -1
        adjustment = _clamp_adj(adjustment + extra)
        reasons.append(f'bearish_breakdown_20 negative expectancy extra {extra}')

    return adjustment, warnings, reasons


def _is_bearish_candidate(candidate: dict[str, Any]) -> bool:
    direction = str(candidate.get('direction') or '').strip().upper()
    if direction in {'BEARISH', 'SELL', 'SHORT'}:
        return True
    blob = _candidate_text_blob(candidate)
    return bool(BEARISH_TOKENS.search(blob))


def _ticker_overlay(ticker_perf: dict[str, Any], base_adj: int) -> tuple[int, list[str]]:
    sample = int(ticker_perf.get('sample') or 0)
    if sample < LOW_TICKER_SAMPLE:
        return base_adj, []

    win_rate_pct = _win_rate_percent(ticker_perf.get('win_rate'))
    exp_val = ticker_perf.get('expectancy_pct')
    reasons: list[str] = []
    overlay = 0

    try:
        exp_f = float(exp_val) if exp_val is not None else None
    except (TypeError, ValueError):
        exp_f = None

    if exp_f is not None and exp_f > 0 and win_rate_pct is not None and win_rate_pct >= 45.0:
        overlay = 1
        reasons.append(f'ticker n={sample} positive expectancy => +{overlay}')
    elif (
        (exp_f is not None and exp_f < -0.5)
        or (win_rate_pct is not None and win_rate_pct < 42.0)
    ):
        overlay = -2
        reasons.append(f'ticker n={sample} weak performance => {overlay}')

    combined = _clamp_adj(base_adj + overlay)
    return combined, reasons


def score_simulation_evidence(candidate: dict[str, Any]) -> dict[str, Any]:
    """
    Score historical simulation evidence for a candidate.

    Returns ok, ticker, inferred_strategy, strategy metrics, ticker metrics,
    confidence_adjustment, warnings, and reasons.
    """
    ticker = _normalize_ticker(candidate.get('ticker'))
    inference = infer_candidate_strategy(candidate)
    inferred = str(inference.get('inferred_strategy') or 'UNKNOWN')

    all_rows = _normalize_strategy_rows()
    broad = get_strategy_performance().get('aggregate') or {}
    strategy_row = _pick_strategy_row(inferred, all_rows) if inferred in KNOWN_STRATEGY_SET else None

    strategy_sample = int(strategy_row.get('resolved') or 0) if strategy_row else int(broad.get('resolved') or 0)
    strategy_win_rate = strategy_row.get('win_rate') if strategy_row else broad.get('win_rate')
    strategy_expectancy = (
        strategy_row.get('expectancy_pct') if strategy_row else broad.get('expectancy_pct')
    )

    adjustment, warnings, reasons = _strategy_adjustment(
        inferred=inferred,
        strategy_row=strategy_row,
        broad_agg=broad,
        candidate=candidate,
    )

    ticker_perf: dict[str, Any] = {'ok': False, 'sample': 0, 'win_rate': None}
    ticker_sample = 0
    ticker_win_rate = None
    if ticker:
        ticker_perf = get_ticker_simulation_performance(ticker)
        ticker_sample = int(ticker_perf.get('sample') or 0)
        ticker_win_rate = ticker_perf.get('win_rate')
        if ticker_sample >= LOW_TICKER_SAMPLE:
            adjustment, ticker_reasons = _ticker_overlay(ticker_perf, adjustment)
            reasons.extend(ticker_reasons)

    return {
        'ok': True,
        'ticker': ticker,
        'inferred_strategy': inferred,
        'strategy_sample': strategy_sample,
        'strategy_win_rate': strategy_win_rate,
        'strategy_expectancy_pct': strategy_expectancy,
        'ticker_sample': ticker_sample,
        'ticker_win_rate': ticker_win_rate,
        'confidence_adjustment': adjustment,
        'warnings': warnings,
        'reasons': reasons,
    }
