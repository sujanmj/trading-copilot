"""Read-only chronological evaluation of stored historical simulations.

This report keeps simulation runs separate and splits each run by signal date so
that later periods remain out of sample. It is research evidence only; it is not
used by live confidence or trade-decision code.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import mean, median
from typing import Any

from backend.storage.historical_market_store import get_connection, list_runs

SPLIT_RATIOS = (0.60, 0.20, 0.20)
SPLIT_NAMES = ('train', 'validation', 'test')


def _finite_float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float('inf'), float('-inf')):
        return None
    return result


def _realized_return_pct(row: dict[str, Any]) -> float | None:
    """Reconstruct return from target/stop fills or expiry close movement."""
    result = str(row.get('result') or '').strip().upper()
    expiry = str(row.get('expiry_result') or '').strip().upper()
    direction = str(row.get('direction') or '').strip().upper()
    entry = _finite_float(row.get('entry_price'))
    target = _finite_float(row.get('target_price'))
    stop = _finite_float(row.get('stop_loss'))
    if entry is None or entry <= 0:
        return None
    sign = 1.0 if direction == 'BULLISH' else -1.0 if direction == 'BEARISH' else None
    if sign is None:
        return None
    if expiry == 'TARGET_HIT' and target is not None:
        return sign * (target - entry) / entry * 100.0
    if expiry == 'STOP_LOSS_HIT' and stop is not None:
        return sign * (stop - entry) / entry * 100.0
    if expiry == 'EXPIRED' or result in {'EXPIRED', 'EXPIRED_FLAT', 'NEUTRAL'}:
        return _finite_float(row.get('close_move_pct'))
    # Older stored rows may not carry expiry_result. Fall back only when that
    # field is absent; newer expired win/loss rows must use their close move.
    if not expiry and result.startswith('WIN') and target is not None:
        return sign * (target - entry) / entry * 100.0
    if not expiry and result.startswith('LOSS') and stop is not None:
        return sign * (stop - entry) / entry * 100.0
    return None


def _split_dates(signal_dates: list[str]) -> dict[str, set[str]]:
    dates = sorted(set(signal_dates))
    total = len(dates)
    if total == 0:
        return {name: set() for name in SPLIT_NAMES}
    train_end = max(1, int(total * SPLIT_RATIOS[0]))
    validation_end = max(train_end, int(total * (SPLIT_RATIOS[0] + SPLIT_RATIOS[1])))
    validation_end = min(total, validation_end)
    return {
        'train': set(dates[:train_end]),
        'validation': set(dates[train_end:validation_end]),
        'test': set(dates[validation_end:]),
    }


def _slice_metrics(rows: list[dict[str, Any]], *, cost_bps: float) -> dict[str, Any]:
    returns: list[float] = []
    ambiguous = 0
    unresolved = 0
    for row in rows:
        outcome = str(row.get('result') or '').strip().upper()
        if outcome == 'AMBIGUOUS_DAILY_CANDLE':
            ambiguous += 1
            continue
        value = _realized_return_pct(row)
        if value is None:
            unresolved += 1
            continue
        returns.append(value - cost_bps / 100.0)

    wins = sum(value > 0 for value in returns)
    losses = sum(value < 0 for value in returns)
    gross_profit = sum(value for value in returns if value > 0)
    gross_loss = -sum(value for value in returns if value < 0)
    return {
        'signals': len(rows),
        'scored_trades': len(returns),
        'wins': wins,
        'losses': losses,
        'ambiguous_excluded': ambiguous,
        'unscored': unresolved,
        'win_rate_pct': (wins / len(returns) * 100.0) if returns else None,
        'mean_net_return_pct': mean(returns) if returns else None,
        'median_net_return_pct': median(returns) if returns else None,
        'net_expectancy_pct_per_trade': mean(returns) if returns else None,
        'profit_factor': (gross_profit / gross_loss) if gross_loss > 0 else None,
        'cost_bps_round_trip': cost_bps,
    }


def get_walk_forward_report(
    *,
    market: str | None = 'INDIA',
    run_id: str | None = None,
    cost_bps: float = 0.0,
) -> dict[str, Any]:
    """Return chronological train/validation/test performance for one run."""
    cost = _finite_float(cost_bps)
    if cost is None or cost < 0:
        raise ValueError('cost_bps must be a finite non-negative number')

    normalized_market = str(market).strip().upper() if market else None
    selected_run_id = str(run_id).strip() if run_id else None
    if not selected_run_id:
        latest_runs = list_runs(market=normalized_market, limit=1)
        if not latest_runs:
            return {
                'ok': True,
                'run_id': None,
                'market': normalized_market,
                'status': 'no_simulation_runs',
                'strategies': [],
            }
        selected_run_id = str(latest_runs[0].get('run_id') or '')

    conn = get_connection()
    try:
        run = conn.execute(
            'SELECT run_id, market, from_date, to_date, strategy_set, created_at '
            'FROM historical_simulation_runs WHERE run_id = ?',
            (selected_run_id,),
        ).fetchone()
        if run is None:
            return {
                'ok': False,
                'run_id': selected_run_id,
                'market': normalized_market,
                'status': 'run_not_found',
                'strategies': [],
            }
        run_market = str(run['market'] or '').strip().upper() or None
        if normalized_market and run_market and run_market != normalized_market:
            return {
                'ok': False,
                'run_id': selected_run_id,
                'market': normalized_market,
                'status': 'run_market_mismatch',
                'strategies': [],
            }
        rows = conn.execute(
            """
            SELECT p.strategy, p.ticker, p.signal_date, p.direction,
                   p.entry_price, p.target_price, p.stop_loss,
                   o.result, o.expiry_result, o.close_move_pct
            FROM historical_simulated_predictions p
            LEFT JOIN historical_simulated_outcomes o
              ON o.sim_prediction_id = p.sim_prediction_id
            WHERE p.run_id = ?
            ORDER BY p.signal_date ASC, p.ticker ASC, p.strategy ASC
            """,
            (selected_run_id,),
        ).fetchall()
    finally:
        conn.close()

    predictions = [dict(row) for row in rows]
    date_splits = _split_dates([str(row['signal_date']) for row in predictions if row.get('signal_date')])
    strategies: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in predictions:
        strategies[str(row.get('strategy') or 'unknown')].append(row)

    strategy_reports = []
    for strategy, strategy_rows in sorted(strategies.items()):
        slices = {}
        for name in SPLIT_NAMES:
            split_rows = [row for row in strategy_rows if row.get('signal_date') in date_splits[name]]
            split_dates = sorted({str(row['signal_date']) for row in split_rows if row.get('signal_date')})
            slices[name] = {
                'from_date': split_dates[0] if split_dates else None,
                'to_date': split_dates[-1] if split_dates else None,
                **_slice_metrics(split_rows, cost_bps=cost),
            }
        strategy_reports.append({'strategy': strategy, 'splits': slices})

    return {
        'ok': True,
        'run_id': selected_run_id,
        'market': run_market,
        'from_date': run['from_date'],
        'to_date': run['to_date'],
        'strategy_set': run['strategy_set'],
        'created_at': run['created_at'],
        'signal_dates': len(date_splits['train'] | date_splits['validation'] | date_splits['test']),
        'cost_bps_round_trip': cost,
        'status': 'ready' if predictions else 'run_has_no_predictions',
        'strategies': strategy_reports,
        'method': {
            'split': 'chronological 60/20/20 by unique signal date; run remains isolated',
            'test_period_is_later_than_validation': True,
            'ambiguous_daily_candles': 'excluded from returns and counted separately',
            'returns': 'target/stop fill price for wins/losses; recorded close move for expiry',
            'cost_model': 'flat round-trip basis points deducted from each scored trade',
            'limitations': [
                'This evaluates the stored strategy run; it does not retune parameters.',
                'Overlapping trades are scored independently, so returns are not portfolio equity.',
                'A chronological split is only as representative as the stored market data.',
            ],
        },
        'disclaimer': 'Research report only; it does not affect live confidence or trade decisions.',
    }
