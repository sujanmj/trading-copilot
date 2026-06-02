"""
Historical learning analytics from historical_market_memory.db.

Read-only from canonical memory; aggregates replay outcomes in the historical DB.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.analytics.historical_price_audit import audit_historical_prices
from backend.analytics.market_memory_learning import (
    _metric_block,
    _safe_win_rate,
    get_learning_summary,
)
from backend.storage.historical_market_store import (
    get_connection,
    get_prices,
    get_replays,
    get_source_performance,
    get_stats,
    init_db,
)
from backend.utils.config import DATA_DIR

IMPORT_REPORT_PATH = DATA_DIR / 'historical_import_report.json'
REPLAY_REPORT_PATH = DATA_DIR / 'historical_replay_report.json'
PROGRESS_PATH = DATA_DIR / 'historical_import_progress.json'
UNIVERSE_PATH = DATA_DIR / 'historical_ticker_universe.json'

WIN_TOKENS = frozenset({'WIN'})
LOSS_TOKENS = frozenset({'LOSS'})
AMBIGUOUS_TOKEN = 'AMBIGUOUS_DAILY_CANDLE'


def _is_win(resolved_as: str | None) -> bool:
    if not resolved_as:
        return False
    token = str(resolved_as).strip().upper()
    return token in WIN_TOKENS or token.startswith('WIN')


def _is_loss(resolved_as: str | None) -> bool:
    if not resolved_as:
        return False
    token = str(resolved_as).strip().upper()
    return token in LOSS_TOKENS or token.startswith('LOSS')


def _is_ambiguous(resolved_as: str | None) -> bool:
    return str(resolved_as or '').strip().upper() == AMBIGUOUS_TOKEN


def _aggregate_replays(replays: list[dict]) -> dict[str, Any]:
    wins = sum(1 for row in replays if _is_win(row.get('resolved_as')))
    losses = sum(1 for row in replays if _is_loss(row.get('resolved_as')))
    ambiguous = sum(1 for row in replays if _is_ambiguous(row.get('resolved_as')))
    unresolved = sum(
        1 for row in replays
        if not _is_win(row.get('resolved_as'))
        and not _is_loss(row.get('resolved_as'))
        and not _is_ambiguous(row.get('resolved_as'))
    )
    actual_moves: list[float] = []
    for row in replays:
        move = row.get('actual_move')
        if move is not None:
            try:
                actual_moves.append(float(move))
            except (TypeError, ValueError):
                pass

    warnings: list[str] = []
    if ambiguous > 0:
        warnings.append('ambiguous_daily_candle_present')
    if (wins + losses) < 5:
        warnings.append('low_sample_size')

    return {
        'total_replays': len(replays),
        'wins': wins,
        'losses': losses,
        'ambiguous': ambiguous,
        'unresolved': unresolved,
        'win_rate': _safe_win_rate(wins, losses),
        'avg_actual_move': (
            sum(actual_moves) / len(actual_moves) if actual_moves else None
        ),
        'warnings': warnings,
    }


def _ticker_rankings(replays: list[dict]) -> dict[str, list[dict]]:
    buckets: dict[str, dict[str, int]] = {}
    for row in replays:
        ticker = str(row.get('ticker') or '').strip().upper() or 'UNKNOWN'
        bucket = buckets.setdefault(ticker, {'wins': 0, 'losses': 0, 'ambiguous': 0, 'total': 0})
        bucket['total'] += 1
        if _is_win(row.get('resolved_as')):
            bucket['wins'] += 1
        elif _is_loss(row.get('resolved_as')):
            bucket['losses'] += 1
        elif _is_ambiguous(row.get('resolved_as')):
            bucket['ambiguous'] += 1

    ranked: list[dict] = []
    for ticker, bucket in buckets.items():
        wins = bucket['wins']
        losses = bucket['losses']
        ranked.append({
            'ticker': ticker,
            'total': bucket['total'],
            'wins': wins,
            'losses': losses,
            'ambiguous': bucket['ambiguous'],
            'win_rate': _safe_win_rate(wins, losses),
        })

    ranked.sort(key=lambda item: (-(item['win_rate'] or -1), -item['total'], item['ticker']))
    top = [item for item in ranked if item['wins'] + item['losses'] > 0][:5]
    bottom = list(reversed([item for item in ranked if item['wins'] + item['losses'] > 0][-5:]))
    return {'top_tickers': top, 'bottom_tickers': bottom}


def _load_json_file(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _count_distinct_historical_tickers() -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            'SELECT COUNT(DISTINCT ticker) AS cnt FROM historical_prices'
        ).fetchone()
        return int(row['cnt']) if row else 0
    finally:
        conn.close()


def _load_bulk_metadata() -> dict[str, Any]:
    audit = audit_historical_prices()
    universe = _load_json_file(UNIVERSE_PATH)
    import_report = _load_json_file(IMPORT_REPORT_PATH)
    replay_report = _load_json_file(REPLAY_REPORT_PATH)
    import_progress = _load_json_file(PROGRESS_PATH)

    universe_total = 0
    if universe:
        summary = universe.get('summary') or {}
        universe_total = int(summary.get('total') or len(universe.get('tickers') or []))

    return {
        'historical_ticker_count': _count_distinct_historical_tickers(),
        'universe_ticker_count': universe_total,
        'import_report': import_report,
        'replay_report': replay_report,
        'import_progress': import_progress,
        'quality_anomalies': int(audit.get('anomalies') or 0),
        'quality_audit': {
            'rows': audit.get('rows'),
            'tickers': audit.get('tickers'),
            'anomalies': audit.get('anomalies'),
            'fake_prices': audit.get('fake_prices'),
        },
    }


def get_historical_learning_summary(*, limit_prices: int = 10) -> dict:
    """Return overall historical replay stats, price coverage, and rankings."""
    init_db()
    stats = get_stats()
    replays = get_replays()
    overall = _aggregate_replays(replays)
    rankings = _ticker_rankings(replays)
    price_rows = get_prices(limit=limit_prices)
    source_rows = get_source_performance()
    bulk = _load_bulk_metadata()

    return {
        'ok': True,
        'db_path': stats.get('db_path'),
        'stats': stats,
        'overall': overall,
        'top_tickers': rankings['top_tickers'],
        'bottom_tickers': rankings['bottom_tickers'],
        'source_performance': source_rows,
        'sample_prices': price_rows,
        'price_row_count': stats.get('historical_prices', 0),
        'historical_ticker_count': bulk.get('historical_ticker_count', 0),
        'universe_ticker_count': bulk.get('universe_ticker_count', 0),
        'import_report': bulk.get('import_report'),
        'replay_report': bulk.get('replay_report'),
        'import_progress': bulk.get('import_progress'),
        'quality_anomalies': bulk.get('quality_anomalies', 0),
        'quality_audit': bulk.get('quality_audit'),
        'simulation': _load_simulation_summary(),
    }


def _load_simulation_summary() -> dict[str, Any]:
    from backend.analytics.historical_prediction_simulator import get_simulation_dashboard

    dashboard = get_simulation_dashboard()
    return dashboard.get('simulation') or {}


def get_historical_ticker_performance(ticker: str) -> dict:
    """Return replay performance for one ticker."""
    normalized = str(ticker or '').strip().upper()
    if not normalized:
        return {'ok': False, 'error': 'ticker is required'}

    init_db()
    replays = get_replays(ticker=normalized)
    overall = _aggregate_replays(replays)
    prices = get_prices(ticker=normalized, limit=20)

    return {
        'ok': True,
        'ticker': normalized,
        'performance': _metric_block(
            resolved=overall['wins'] + overall['losses'] + overall['ambiguous'],
            wins=overall['wins'],
            losses=overall['losses'],
            actual_moves=[
                float(row['actual_move'])
                for row in replays
                if row.get('actual_move') is not None
            ],
        ),
        'overall': overall,
        'recent_prices': prices,
        'recent_replays': replays[-10:],
    }


def get_historical_source_performance(*, market: str | None = None) -> dict:
    """Return cached source performance rows from historical DB."""
    init_db()
    rows = get_source_performance(market=market)
    return {
        'ok': True,
        'market': market,
        'sources': rows,
    }


def compare_live_memory_vs_historical() -> dict:
    """Compare canonical live memory learning vs historical replay outcomes."""
    live = get_learning_summary()
    historical = get_historical_learning_summary(limit_prices=0)

    live_overall = live.get('overall') or {}
    hist_overall = historical.get('overall') or {}

    live_rate = live_overall.get('win_rate')
    hist_rate = hist_overall.get('win_rate')
    delta = None
    if live_rate is not None and hist_rate is not None:
        delta = round(float(hist_rate) - float(live_rate), 4)

    return {
        'ok': True,
        'live_memory': {
            'total_predictions': live_overall.get('total_predictions', 0),
            'resolved_outcomes': live_overall.get('resolved_outcomes', 0),
            'wins': live_overall.get('wins', 0),
            'losses': live_overall.get('losses', 0),
            'win_rate': live_rate,
        },
        'historical_replay': {
            'total_replays': hist_overall.get('total_replays', 0),
            'wins': hist_overall.get('wins', 0),
            'losses': hist_overall.get('losses', 0),
            'ambiguous': hist_overall.get('ambiguous', 0),
            'win_rate': hist_rate,
        },
        'delta_win_rate': delta,
        'warnings': hist_overall.get('warnings') or [],
    }
