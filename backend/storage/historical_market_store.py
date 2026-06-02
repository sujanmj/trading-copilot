"""
Historical market memory — separate SQLite at data/historical_market_memory.db.

Stores OHLCV price history and replayed prediction outcomes (read-only from canonical).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.utils.config import DATA_DIR, ensure_dirs

HISTORICAL_DB_NAME = 'historical_market_memory.db'
SIMULATION_UNIVERSE_FILENAME = 'historical_ticker_universe.json'

SCHEMA = """
CREATE TABLE IF NOT EXISTS historical_prices (
    market TEXT NOT NULL,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    source TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    fake_prices INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (market, ticker, date, source)
);

CREATE INDEX IF NOT EXISTS idx_hmp_market_ticker ON historical_prices(market, ticker);
CREATE INDEX IF NOT EXISTS idx_hmp_date ON historical_prices(date);
CREATE INDEX IF NOT EXISTS idx_hmp_ticker_date ON historical_prices(ticker, date);

CREATE TABLE IF NOT EXISTS historical_outcome_replay (
    replay_id TEXT PRIMARY KEY,
    prediction_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    market TEXT,
    prediction_date TEXT,
    direction TEXT,
    entry_price REAL,
    target_price REAL,
    stop_loss REAL,
    holding_period TEXT NOT NULL DEFAULT 'historical_replay',
    resolved_as TEXT,
    expiry_result TEXT,
    replay_date TEXT,
    candle_high REAL,
    candle_low REAL,
    candle_close REAL,
    actual_move REAL,
    source TEXT,
    raw_payload TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_hmor_prediction_id ON historical_outcome_replay(prediction_id);
CREATE INDEX IF NOT EXISTS idx_hmor_ticker ON historical_outcome_replay(ticker);
CREATE INDEX IF NOT EXISTS idx_hmor_resolved_as ON historical_outcome_replay(resolved_as);
CREATE INDEX IF NOT EXISTS idx_hmor_prediction_date ON historical_outcome_replay(prediction_date);
CREATE INDEX IF NOT EXISTS idx_hmor_replay_date ON historical_outcome_replay(replay_date);

CREATE TABLE IF NOT EXISTS historical_source_performance (
    source TEXT NOT NULL,
    market TEXT NOT NULL,
    total_replays INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    ambiguous INTEGER NOT NULL DEFAULT 0,
    unresolved INTEGER NOT NULL DEFAULT 0,
    win_rate REAL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source, market)
);

CREATE INDEX IF NOT EXISTS idx_hmsp_market ON historical_source_performance(market);

CREATE TABLE IF NOT EXISTS historical_price_anomalies (
    anomaly_id TEXT PRIMARY KEY,
    market TEXT,
    ticker TEXT,
    date TEXT,
    reason TEXT,
    severity TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    source TEXT,
    detected_at TEXT,
    status TEXT DEFAULT 'active',
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_hpa_ticker ON historical_price_anomalies(ticker);
CREATE INDEX IF NOT EXISTS idx_hpa_date ON historical_price_anomalies(date);
CREATE INDEX IF NOT EXISTS idx_hpa_severity ON historical_price_anomalies(severity);
CREATE INDEX IF NOT EXISTS idx_hpa_status ON historical_price_anomalies(status);

CREATE TABLE IF NOT EXISTS historical_simulation_runs (
    run_id TEXT PRIMARY KEY,
    strategy_set TEXT,
    market TEXT,
    from_date TEXT,
    to_date TEXT,
    tickers INTEGER NOT NULL DEFAULT 0,
    generated_predictions INTEGER NOT NULL DEFAULT 0,
    resolved_predictions INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    ambiguous INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    params_json TEXT,
    params_hash TEXT
);

CREATE INDEX IF NOT EXISTS idx_hsr_market ON historical_simulation_runs(market);
CREATE INDEX IF NOT EXISTS idx_hsr_created_at ON historical_simulation_runs(created_at);

CREATE TABLE IF NOT EXISTS historical_simulated_predictions (
    sim_prediction_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    market TEXT,
    ticker TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    strategy TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL,
    target_price REAL,
    stop_loss REAL,
    horizon TEXT,
    confidence REAL,
    features_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_hsp_run_id ON historical_simulated_predictions(run_id);
CREATE INDEX IF NOT EXISTS idx_hsp_ticker ON historical_simulated_predictions(ticker);
CREATE INDEX IF NOT EXISTS idx_hsp_signal_date ON historical_simulated_predictions(signal_date);
CREATE INDEX IF NOT EXISTS idx_hsp_strategy ON historical_simulated_predictions(strategy);
CREATE INDEX IF NOT EXISTS idx_hsp_market ON historical_simulated_predictions(market);

CREATE TABLE IF NOT EXISTS historical_simulated_outcomes (
    sim_outcome_id TEXT PRIMARY KEY,
    sim_prediction_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    strategy TEXT NOT NULL,
    result TEXT,
    expiry_result TEXT,
    max_gain_pct REAL,
    max_loss_pct REAL,
    close_move_pct REAL,
    bars_held INTEGER,
    evidence_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_hso_sim_prediction_id ON historical_simulated_outcomes(sim_prediction_id);
CREATE INDEX IF NOT EXISTS idx_hso_ticker ON historical_simulated_outcomes(ticker);
CREATE INDEX IF NOT EXISTS idx_hso_result ON historical_simulated_outcomes(result);
CREATE INDEX IF NOT EXISTS idx_hso_strategy ON historical_simulated_outcomes(strategy);

CREATE TABLE IF NOT EXISTS historical_strategy_performance (
    strategy TEXT NOT NULL,
    market TEXT NOT NULL,
    predictions INTEGER NOT NULL DEFAULT 0,
    resolved INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    ambiguous INTEGER NOT NULL DEFAULT 0,
    win_rate REAL,
    avg_gain_pct REAL,
    avg_loss_pct REAL,
    expectancy_pct REAL,
    max_drawdown_proxy REAL,
    sample_warning TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (strategy, market)
);

CREATE INDEX IF NOT EXISTS idx_hstrat_market ON historical_strategy_performance(market);
"""


def get_historical_db_path() -> Path:
    """Return path to historical market memory SQLite DB."""
    return DATA_DIR / HISTORICAL_DB_NAME


def get_connection(timeout: float = 30.0) -> sqlite3.Connection:
    """Open SQLite connection with Row factory and pragmas."""
    ensure_dirs()
    conn = sqlite3.connect(str(get_historical_db_path()), timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str, ensure_ascii=False)


def _log_error(message: str) -> None:
    print(f'[HISTORICAL_MARKET] {message}', file=sys.stderr)


def _parse_params_json(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def get_simulation_universe_path() -> Path:
    """Return path to historical ticker universe JSON."""
    return DATA_DIR / SIMULATION_UNIVERSE_FILENAME


def get_simulation_tickers(
    *,
    market: str,
    limit_tickers: int | None = None,
) -> list[str]:
    """Return tickers for simulation using universe file or historical prices."""
    tickers: list[str] = []
    universe_path = get_simulation_universe_path()
    if universe_path.is_file():
        try:
            data = json.loads(universe_path.read_text(encoding='utf-8'))
            raw = data.get('tickers') or []
            tickers = [
                str(item.get('ticker') if isinstance(item, dict) else item).strip().upper()
                for item in raw
                if str(item.get('ticker') if isinstance(item, dict) else item).strip()
            ]
        except (OSError, json.JSONDecodeError, TypeError):
            tickers = []

    if not tickers:
        tickers = get_distinct_tickers(market=market, limit=limit_tickers)

    tickers = [
        token for token in tickers
        if token and not token.startswith('__TEST__')
    ]
    if limit_tickers is not None and limit_tickers > 0:
        tickers = tickers[: int(limit_tickers)]
    return tickers


def _resolve_backfill_tickers(
    conn: sqlite3.Connection,
    *,
    market: str,
    run_id: str,
    params: dict,
) -> list[str]:
    stored = params.get('tickers')
    if isinstance(stored, list) and stored:
        return sorted(str(t).strip().upper() for t in stored if str(t).strip())

    limit_tickers = params.get('limit_tickers')
    tickers = get_simulation_tickers(
        market=market,
        limit_tickers=int(limit_tickers) if limit_tickers else None,
    )
    if tickers:
        return tickers
    return _tickers_for_run(conn, run_id)
    rows = conn.execute(
        """
        SELECT DISTINCT ticker
        FROM historical_simulated_predictions
        WHERE run_id = ?
        ORDER BY ticker ASC
        """,
        (run_id,),
    ).fetchall()
    return [
        str(row['ticker']).strip().upper()
        for row in rows
        if row['ticker']
    ]


def backfill_simulation_params_hashes(conn: sqlite3.Connection | None = None) -> int:
    """Compute and store params_hash for simulation runs missing or stale values."""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    updated = 0
    try:
        rows = conn.execute(
            """
            SELECT run_id, strategy_set, market, from_date, to_date, params_json, params_hash
            FROM historical_simulation_runs
            """
        ).fetchall()
        for row in rows:
            params = _parse_params_json(row['params_json'])
            market = str(row['market'] or '')
            tickers = _resolve_backfill_tickers(
                conn,
                market=market,
                run_id=row['run_id'],
                params=params,
            )
            params_hash = compute_simulation_params_hash(
                market=market,
                from_date=str(row['from_date'] or ''),
                to_date=str(row['to_date'] or ''),
                years=params.get('years'),
                strategy_set=str(row['strategy_set'] or ''),
                tickers=tickers,
                limit_tickers=params.get('limit_tickers'),
                max_signals_per_ticker_strategy=int(
                    params.get('max_signals_per_ticker_strategy') or 200
                ),
                anomaly_exclusion_mode=str(
                    params.get('anomaly_exclusion_mode') or 'exclude_from_simulation'
                ),
            )
            if row['params_hash'] == params_hash:
                continue
            conn.execute(
                """
                UPDATE historical_simulation_runs
                SET params_hash = ?
                WHERE run_id = ?
                """,
                (params_hash, row['run_id']),
            )
            updated += 1
        if updated:
            conn.commit()
    finally:
        if own_conn:
            conn.close()
    return updated


def _migrate_simulation_schema(conn: sqlite3.Connection) -> None:
    """Apply safe incremental migrations for simulation tables."""
    cols = {
        row[1]
        for row in conn.execute('PRAGMA table_info(historical_simulation_runs)').fetchall()
    }
    if 'params_hash' not in cols:
        conn.execute(
            'ALTER TABLE historical_simulation_runs ADD COLUMN params_hash TEXT',
        )
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_hsr_params_hash '
        'ON historical_simulation_runs(params_hash)',
    )
    backfill_simulation_params_hashes(conn)


def init_db() -> bool:
    """Create schema idempotently. Returns True on success."""
    try:
        ensure_dirs()
        conn = get_connection()
        try:
            conn.executescript(SCHEMA)
            _migrate_simulation_schema(conn)
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception as exc:
        _log_error(f'init failed: {exc}')
        return False


def make_replay_id(prediction_id: str, replay_date: str | None = None) -> str:
    """Deterministic replay id from prediction_id and optional replay date."""
    parts = '|'.join(str(part or '') for part in (prediction_id, replay_date or ''))
    digest = hashlib.sha256(parts.encode('utf-8')).hexdigest()[:24]
    return f'hr:{digest}'


def make_anomaly_id(
    market: str,
    ticker: str,
    date: str,
    reason: str,
    source: str = '',
) -> str:
    """Deterministic anomaly id from market/ticker/date/reason/source."""
    parts = '|'.join(
        str(part or '').strip().upper() if idx in (0, 1) else str(part or '')
        for idx, part in enumerate((market, ticker, date, reason, source))
    )
    digest = hashlib.sha256(parts.encode('utf-8')).hexdigest()[:24]
    return f'ha:{digest}'


def make_sim_prediction_id(
    run_id: str,
    market: str,
    ticker: str,
    signal_date: str,
    strategy: str,
) -> str:
    """Deterministic simulated prediction id."""
    parts = '|'.join(
        str(part or '')
        for part in (run_id, market, ticker, signal_date, strategy)
    )
    digest = hashlib.sha256(parts.encode('utf-8')).hexdigest()[:24]
    return f'hsp:{digest}'


def make_sim_outcome_id(sim_prediction_id: str) -> str:
    """Deterministic simulated outcome id from prediction id."""
    digest = hashlib.sha256(str(sim_prediction_id).encode('utf-8')).hexdigest()[:24]
    return f'hso:{digest}'


def make_simulation_run_id(
    market: str,
    from_date: str,
    to_date: str,
    strategy_set: str,
) -> str:
    """Unique simulation run id (timestamp suffix for explicit duplicates)."""
    stamp = _now_iso()
    parts = '|'.join(str(part or '') for part in (market, from_date, to_date, strategy_set, stamp))
    digest = hashlib.sha256(parts.encode('utf-8')).hexdigest()[:16]
    return f'hsr:{digest}'


def make_simulation_run_id_from_params_hash(params_hash: str) -> str:
    """Deterministic simulation run id from params_hash."""
    digest = str(params_hash or '').strip().lower()
    if not digest:
        digest = hashlib.sha256(b'').hexdigest()
    return f'hsr:{digest[:24]}'


def compute_simulation_params_hash(
    *,
    market: str,
    from_date: str,
    to_date: str,
    years: int | None = None,
    strategy_set: str,
    tickers: list[str],
    limit_tickers: int | None = None,
    max_signals_per_ticker_strategy: int = 200,
    anomaly_exclusion_mode: str = 'exclude_from_simulation',
) -> str:
    """Return sha256 hex of canonical simulation parameters."""
    canonical: dict[str, Any] = {
        'market': str(market or '').strip().upper(),
        'from_date': str(from_date or ''),
        'to_date': str(to_date or ''),
        'strategy_set': str(strategy_set or ''),
        'tickers': sorted(str(t).strip().upper() for t in tickers if str(t).strip()),
        'limit_tickers': limit_tickers,
        'max_signals_per_ticker_strategy': int(max_signals_per_ticker_strategy),
        'anomaly_exclusion_mode': str(anomaly_exclusion_mode or 'exclude_from_simulation'),
    }
    if years is not None and not (from_date and to_date):
        canonical['years'] = years
    payload = json.dumps(canonical, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def upsert_price_anomalies(rows: list[dict]) -> int:
    """Upsert anomaly quarantine rows; returns count written."""
    if not rows:
        return 0

    now = _now_iso()
    written = 0
    conn = get_connection()
    try:
        for row in rows:
            market = str(row.get('market') or '').strip().upper()
            ticker = str(row.get('ticker') or '').strip().upper()
            date = str(row.get('date') or '')
            reason = str(row.get('reason') or '')
            source = str(row.get('source') or '')
            anomaly_id = row.get('anomaly_id') or make_anomaly_id(
                market, ticker, date, reason, source,
            )
            conn.execute(
                """
                INSERT INTO historical_price_anomalies (
                    anomaly_id, market, ticker, date, reason, severity,
                    open, high, low, close, volume, source, detected_at,
                    status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(anomaly_id) DO UPDATE SET
                    market=excluded.market,
                    ticker=excluded.ticker,
                    date=excluded.date,
                    reason=excluded.reason,
                    severity=excluded.severity,
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume,
                    source=excluded.source,
                    detected_at=excluded.detected_at,
                    status=excluded.status,
                    notes=excluded.notes
                """,
                (
                    anomaly_id,
                    market,
                    ticker,
                    date,
                    reason,
                    row.get('severity'),
                    row.get('open'),
                    row.get('high'),
                    row.get('low'),
                    row.get('close'),
                    row.get('volume'),
                    source,
                    row.get('detected_at') or now,
                    row.get('status') or 'active',
                    row.get('notes'),
                ),
            )
            written += 1
        conn.commit()
    finally:
        conn.close()
    return written


def get_active_anomalies(
    *,
    market: str | None = None,
    ticker: str | None = None,
    severity: str | None = None,
) -> list[dict]:
    """Return active anomaly rows ordered by ticker, date."""
    clauses = ["status = 'active'"]
    params: list[Any] = []

    if market:
        clauses.append('market = ?')
        params.append(str(market).strip().upper())
    if ticker:
        clauses.append('ticker = ?')
        params.append(str(ticker).strip().upper())
    if severity:
        clauses.append('severity = ?')
        params.append(str(severity).strip())

    where = f"WHERE {' AND '.join(clauses)}"
    query = f"""
        SELECT *
        FROM historical_price_anomalies
        {where}
        ORDER BY ticker ASC, date ASC, reason ASC
    """

    conn = get_connection()
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def get_excluded_simulation_dates(market: str, ticker: str) -> set[str]:
    """Return dates with active exclude_from_simulation anomalies."""
    rows = get_active_anomalies(
        market=market,
        ticker=ticker,
        severity='exclude_from_simulation',
    )
    return {str(row['date']) for row in rows if row.get('date')}


def get_warning_simulation_dates(market: str, ticker: str) -> set[str]:
    """Return dates with active warning-severity anomalies."""
    rows = get_active_anomalies(
        market=market,
        ticker=ticker,
        severity='warning',
    )
    return {str(row['date']) for row in rows if row.get('date')}


def upsert_prices(rows: list[dict]) -> int:
    """Upsert OHLCV rows; returns count written."""
    if not rows:
        return 0

    now = _now_iso()
    written = 0
    conn = get_connection()
    try:
        for row in rows:
            conn.execute(
                """
                INSERT INTO historical_prices (
                    market, ticker, date, source, open, high, low, close, volume,
                    fake_prices, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(market, ticker, date, source) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume,
                    fake_prices=excluded.fake_prices,
                    updated_at=excluded.updated_at
                """,
                (
                    row.get('market'),
                    str(row.get('ticker') or '').strip().upper(),
                    row.get('date'),
                    row.get('source'),
                    row.get('open'),
                    row.get('high'),
                    row.get('low'),
                    row.get('close'),
                    row.get('volume'),
                    int(row.get('fake_prices') or 0),
                    row.get('created_at') or now,
                    now,
                ),
            )
            written += 1
        conn.commit()
    finally:
        conn.close()
    return written


def get_prices(
    *,
    market: str | None = None,
    ticker: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Return historical price rows ordered by date ASC."""
    clauses: list[str] = []
    params: list[Any] = []

    if market:
        clauses.append('market = ?')
        params.append(str(market).strip().upper())
    if ticker:
        clauses.append('ticker = ?')
        params.append(str(ticker).strip().upper())
    if from_date:
        clauses.append('date >= ?')
        params.append(from_date)
    if to_date:
        clauses.append('date <= ?')
        params.append(to_date)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
    query = f"""
        SELECT market, ticker, date, source, open, high, low, close, volume, fake_prices
        FROM historical_prices
        {where}
        ORDER BY date ASC, source ASC
    """
    if limit is not None and limit > 0:
        query += ' LIMIT ?'
        params.append(int(limit))

    conn = get_connection()
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def insert_replay(payload: dict, *, update_existing: bool = True) -> str | None:
    """Insert or upsert one replay row; returns replay_id."""
    try:
        prediction_id = payload.get('prediction_id')
        if not prediction_id:
            return None

        replay_id = payload.get('replay_id') or make_replay_id(
            str(prediction_id),
            payload.get('replay_date'),
        )
        now = _now_iso()
        conn = get_connection()
        try:
            if update_existing:
                conn.execute(
                    """
                    INSERT INTO historical_outcome_replay (
                        replay_id, prediction_id, ticker, market, prediction_date,
                        direction, entry_price, target_price, stop_loss, holding_period,
                        resolved_as, expiry_result, replay_date, candle_high, candle_low,
                        candle_close, actual_move, source, raw_payload, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(replay_id) DO UPDATE SET
                        prediction_id=excluded.prediction_id,
                        ticker=excluded.ticker,
                        market=excluded.market,
                        prediction_date=excluded.prediction_date,
                        direction=excluded.direction,
                        entry_price=excluded.entry_price,
                        target_price=excluded.target_price,
                        stop_loss=excluded.stop_loss,
                        holding_period=excluded.holding_period,
                        resolved_as=excluded.resolved_as,
                        expiry_result=excluded.expiry_result,
                        replay_date=excluded.replay_date,
                        candle_high=excluded.candle_high,
                        candle_low=excluded.candle_low,
                        candle_close=excluded.candle_close,
                        actual_move=excluded.actual_move,
                        source=excluded.source,
                        raw_payload=excluded.raw_payload,
                        updated_at=excluded.updated_at
                    """,
                    (
                        replay_id,
                        prediction_id,
                        payload.get('ticker'),
                        payload.get('market'),
                        payload.get('prediction_date'),
                        payload.get('direction'),
                        payload.get('entry_price'),
                        payload.get('target_price'),
                        payload.get('stop_loss'),
                        payload.get('holding_period') or 'historical_replay',
                        payload.get('resolved_as'),
                        payload.get('expiry_result'),
                        payload.get('replay_date'),
                        payload.get('candle_high'),
                        payload.get('candle_low'),
                        payload.get('candle_close'),
                        payload.get('actual_move'),
                        payload.get('source'),
                        _json_text(payload.get('raw_payload')),
                        payload.get('created_at') or now,
                        now,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO historical_outcome_replay (
                        replay_id, prediction_id, ticker, market, prediction_date,
                        direction, entry_price, target_price, stop_loss, holding_period,
                        resolved_as, expiry_result, replay_date, candle_high, candle_low,
                        candle_close, actual_move, source, raw_payload, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        replay_id,
                        prediction_id,
                        payload.get('ticker'),
                        payload.get('market'),
                        payload.get('prediction_date'),
                        payload.get('direction'),
                        payload.get('entry_price'),
                        payload.get('target_price'),
                        payload.get('stop_loss'),
                        payload.get('holding_period') or 'historical_replay',
                        payload.get('resolved_as'),
                        payload.get('expiry_result'),
                        payload.get('replay_date'),
                        payload.get('candle_high'),
                        payload.get('candle_low'),
                        payload.get('candle_close'),
                        payload.get('actual_move'),
                        payload.get('source'),
                        _json_text(payload.get('raw_payload')),
                        payload.get('created_at') or now,
                        now,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        return replay_id
    except Exception as exc:
        _log_error(f'insert_replay failed: {exc}')
        return None


def get_replays(
    *,
    ticker: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    resolved_as: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Return replay rows ordered by prediction_date ASC."""
    clauses: list[str] = []
    params: list[Any] = []

    if ticker:
        clauses.append('ticker = ?')
        params.append(str(ticker).strip().upper())
    if from_date:
        clauses.append('prediction_date >= ?')
        params.append(from_date)
    if to_date:
        clauses.append('prediction_date <= ?')
        params.append(to_date)
    if resolved_as:
        clauses.append('resolved_as = ?')
        params.append(resolved_as)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
    query = f"""
        SELECT *
        FROM historical_outcome_replay
        {where}
        ORDER BY prediction_date ASC, replay_date ASC
    """
    if limit is not None and limit > 0:
        query += ' LIMIT ?'
        params.append(int(limit))

    conn = get_connection()
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def rebuild_source_performance(*, market: str | None = None) -> int:
    """Recompute historical_source_performance from replay rows."""
    conn = get_connection()
    try:
        conn.execute('DELETE FROM historical_source_performance')
        clauses: list[str] = []
        params: list[Any] = []
        if market:
            clauses.append('market = ?')
            params.append(str(market).strip().upper())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ''

        rows = conn.execute(
            f"""
            SELECT
                COALESCE(source, 'UNKNOWN') AS source,
                COALESCE(market, 'UNKNOWN') AS market,
                resolved_as
            FROM historical_outcome_replay
            {where}
            """,
            params,
        ).fetchall()

        buckets: dict[tuple[str, str], dict[str, int]] = {}
        for row in rows:
            key = (str(row['source']), str(row['market']))
            bucket = buckets.setdefault(
                key,
                {'total': 0, 'wins': 0, 'losses': 0, 'ambiguous': 0, 'unresolved': 0},
            )
            bucket['total'] += 1
            token = str(row['resolved_as'] or '').strip().upper()
            if token in ('WIN',) or token.startswith('WIN'):
                bucket['wins'] += 1
            elif token in ('LOSS',) or token.startswith('LOSS'):
                bucket['losses'] += 1
            elif token == 'AMBIGUOUS_DAILY_CANDLE':
                bucket['ambiguous'] += 1
            else:
                bucket['unresolved'] += 1

        now = _now_iso()
        for (source, market_key), bucket in buckets.items():
            wins = bucket['wins']
            losses = bucket['losses']
            win_rate = wins / (wins + losses) if (wins + losses) > 0 else None
            conn.execute(
                """
                INSERT INTO historical_source_performance (
                    source, market, total_replays, wins, losses, ambiguous,
                    unresolved, win_rate, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source,
                    market_key,
                    bucket['total'],
                    wins,
                    losses,
                    bucket['ambiguous'],
                    bucket['unresolved'],
                    win_rate,
                    now,
                ),
            )
        conn.commit()
        return len(buckets)
    finally:
        conn.close()


def get_source_performance(*, market: str | None = None) -> list[dict]:
    """Return cached source performance rows."""
    conn = get_connection()
    try:
        if market:
            rows = conn.execute(
                """
                SELECT *
                FROM historical_source_performance
                WHERE market = ?
                ORDER BY total_replays DESC, source ASC
                """,
                (str(market).strip().upper(),),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM historical_source_performance
                ORDER BY total_replays DESC, source ASC, market ASC
                """
            ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def insert_run(payload: dict) -> str | None:
    """Insert one simulation run row; returns run_id."""
    try:
        run_id = payload.get('run_id')
        if not run_id:
            return None
        now = _now_iso()
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO historical_simulation_runs (
                    run_id, strategy_set, market, from_date, to_date, tickers,
                    generated_predictions, resolved_predictions, wins, losses,
                    ambiguous, created_at, params_json, params_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    strategy_set=excluded.strategy_set,
                    market=excluded.market,
                    from_date=excluded.from_date,
                    to_date=excluded.to_date,
                    tickers=excluded.tickers,
                    generated_predictions=excluded.generated_predictions,
                    resolved_predictions=excluded.resolved_predictions,
                    wins=excluded.wins,
                    losses=excluded.losses,
                    ambiguous=excluded.ambiguous,
                    params_json=excluded.params_json,
                    params_hash=excluded.params_hash
                """,
                (
                    run_id,
                    payload.get('strategy_set'),
                    payload.get('market'),
                    payload.get('from_date'),
                    payload.get('to_date'),
                    int(payload.get('tickers') or 0),
                    int(payload.get('generated_predictions') or 0),
                    int(payload.get('resolved_predictions') or 0),
                    int(payload.get('wins') or 0),
                    int(payload.get('losses') or 0),
                    int(payload.get('ambiguous') or 0),
                    payload.get('created_at') or now,
                    _json_text(payload.get('params_json')),
                    payload.get('params_hash'),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return run_id
    except Exception as exc:
        _log_error(f'insert_run failed: {exc}')
        return None


def find_run_by_params_hash(params_hash: str) -> dict | None:
    """Return the latest simulation run matching params_hash, or None."""
    if not params_hash:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT *
            FROM historical_simulation_runs
            WHERE params_hash = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (params_hash,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_simulation_run_cascade(run_id: str) -> dict[str, int]:
    """Delete outcomes, predictions, and run row for one simulation run."""
    if not run_id:
        return {'runs_deleted': 0, 'predictions_deleted': 0, 'outcomes_deleted': 0}

    conn = get_connection()
    try:
        pred_rows = conn.execute(
            """
            SELECT sim_prediction_id
            FROM historical_simulated_predictions
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchall()
        pred_ids = [row['sim_prediction_id'] for row in pred_rows]

        outcomes_deleted = 0
        if pred_ids:
            placeholders = ','.join('?' * len(pred_ids))
            outcomes_deleted = conn.execute(
                f"""
                DELETE FROM historical_simulated_outcomes
                WHERE sim_prediction_id IN ({placeholders})
                """,
                pred_ids,
            ).rowcount

        predictions_deleted = conn.execute(
            'DELETE FROM historical_simulated_predictions WHERE run_id = ?',
            (run_id,),
        ).rowcount
        runs_deleted = conn.execute(
            'DELETE FROM historical_simulation_runs WHERE run_id = ?',
            (run_id,),
        ).rowcount
        conn.commit()
    finally:
        conn.close()

    return {
        'runs_deleted': int(runs_deleted),
        'predictions_deleted': int(predictions_deleted),
        'outcomes_deleted': int(outcomes_deleted),
    }


def delete_simulation_by_params_hash(
    params_hash: str,
    *,
    keep_run_id: str | None = None,
) -> dict[str, int]:
    """Delete simulation rows for params_hash, optionally keeping one run."""
    if not params_hash:
        return {'runs_deleted': 0, 'predictions_deleted': 0, 'outcomes_deleted': 0}

    conn = get_connection()
    try:
        if keep_run_id:
            rows = conn.execute(
                """
                SELECT run_id
                FROM historical_simulation_runs
                WHERE params_hash = ? AND run_id != ?
                """,
                (params_hash, keep_run_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT run_id
                FROM historical_simulation_runs
                WHERE params_hash = ?
                """,
                (params_hash,),
            ).fetchall()
    finally:
        conn.close()

    totals = {'runs_deleted': 0, 'predictions_deleted': 0, 'outcomes_deleted': 0}
    for row in rows:
        result = delete_simulation_run_cascade(row['run_id'])
        for key in totals:
            totals[key] += int(result.get(key) or 0)
    return totals


def get_duplicate_params_groups() -> list[dict]:
    """Return params_hash groups with more than one simulation run."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT params_hash, COUNT(*) AS run_count
            FROM historical_simulation_runs
            WHERE params_hash IS NOT NULL AND params_hash != ''
            GROUP BY params_hash
            HAVING run_count > 1
            ORDER BY run_count DESC, params_hash ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def count_unique_params_hashes() -> int:
    """Return count of distinct non-empty params_hash values."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT params_hash) AS cnt
            FROM historical_simulation_runs
            WHERE params_hash IS NOT NULL AND params_hash != ''
            """
        ).fetchone()
        return int(row['cnt']) if row else 0
    finally:
        conn.close()


def upsert_sim_predictions(rows: list[dict]) -> int:
    """Upsert simulated prediction rows; returns count written."""
    if not rows:
        return 0

    now = _now_iso()
    written = 0
    conn = get_connection()
    try:
        for row in rows:
            sim_prediction_id = row.get('sim_prediction_id')
            if not sim_prediction_id:
                continue
            conn.execute(
                """
                INSERT INTO historical_simulated_predictions (
                    sim_prediction_id, run_id, market, ticker, signal_date, strategy,
                    direction, entry_price, target_price, stop_loss, horizon,
                    confidence, features_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sim_prediction_id) DO UPDATE SET
                    run_id=excluded.run_id,
                    market=excluded.market,
                    ticker=excluded.ticker,
                    signal_date=excluded.signal_date,
                    strategy=excluded.strategy,
                    direction=excluded.direction,
                    entry_price=excluded.entry_price,
                    target_price=excluded.target_price,
                    stop_loss=excluded.stop_loss,
                    horizon=excluded.horizon,
                    confidence=excluded.confidence,
                    features_json=excluded.features_json
                """,
                (
                    sim_prediction_id,
                    row.get('run_id'),
                    row.get('market'),
                    str(row.get('ticker') or '').strip().upper(),
                    row.get('signal_date'),
                    row.get('strategy'),
                    row.get('direction'),
                    row.get('entry_price'),
                    row.get('target_price'),
                    row.get('stop_loss'),
                    row.get('horizon'),
                    row.get('confidence'),
                    _json_text(row.get('features_json')),
                    row.get('created_at') or now,
                ),
            )
            written += 1
        conn.commit()
    finally:
        conn.close()
    return written


def upsert_sim_outcomes(rows: list[dict]) -> int:
    """Upsert simulated outcome rows; returns count written."""
    if not rows:
        return 0

    now = _now_iso()
    written = 0
    conn = get_connection()
    try:
        for row in rows:
            sim_prediction_id = row.get('sim_prediction_id')
            if not sim_prediction_id:
                continue
            sim_outcome_id = row.get('sim_outcome_id') or make_sim_outcome_id(sim_prediction_id)
            conn.execute(
                """
                INSERT INTO historical_simulated_outcomes (
                    sim_outcome_id, sim_prediction_id, ticker, signal_date, strategy,
                    result, expiry_result, max_gain_pct, max_loss_pct, close_move_pct,
                    bars_held, evidence_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sim_outcome_id) DO UPDATE SET
                    sim_prediction_id=excluded.sim_prediction_id,
                    ticker=excluded.ticker,
                    signal_date=excluded.signal_date,
                    strategy=excluded.strategy,
                    result=excluded.result,
                    expiry_result=excluded.expiry_result,
                    max_gain_pct=excluded.max_gain_pct,
                    max_loss_pct=excluded.max_loss_pct,
                    close_move_pct=excluded.close_move_pct,
                    bars_held=excluded.bars_held,
                    evidence_json=excluded.evidence_json
                """,
                (
                    sim_outcome_id,
                    sim_prediction_id,
                    str(row.get('ticker') or '').strip().upper(),
                    row.get('signal_date'),
                    row.get('strategy'),
                    row.get('result'),
                    row.get('expiry_result'),
                    row.get('max_gain_pct'),
                    row.get('max_loss_pct'),
                    row.get('close_move_pct'),
                    row.get('bars_held'),
                    _json_text(row.get('evidence_json')),
                    row.get('created_at') or now,
                ),
            )
            written += 1
        conn.commit()
    finally:
        conn.close()
    return written


def upsert_strategy_performance(rows: list[dict]) -> int:
    """Upsert strategy performance aggregate rows; returns count written."""
    if not rows:
        return 0

    now = _now_iso()
    written = 0
    conn = get_connection()
    try:
        for row in rows:
            strategy = row.get('strategy')
            market = str(row.get('market') or '').strip().upper()
            if not strategy or not market:
                continue
            conn.execute(
                """
                INSERT INTO historical_strategy_performance (
                    strategy, market, predictions, resolved, wins, losses, ambiguous,
                    win_rate, avg_gain_pct, avg_loss_pct, expectancy_pct,
                    max_drawdown_proxy, sample_warning, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy, market) DO UPDATE SET
                    predictions=excluded.predictions,
                    resolved=excluded.resolved,
                    wins=excluded.wins,
                    losses=excluded.losses,
                    ambiguous=excluded.ambiguous,
                    win_rate=excluded.win_rate,
                    avg_gain_pct=excluded.avg_gain_pct,
                    avg_loss_pct=excluded.avg_loss_pct,
                    expectancy_pct=excluded.expectancy_pct,
                    max_drawdown_proxy=excluded.max_drawdown_proxy,
                    sample_warning=excluded.sample_warning,
                    updated_at=excluded.updated_at
                """,
                (
                    strategy,
                    market,
                    int(row.get('predictions') or 0),
                    int(row.get('resolved') or 0),
                    int(row.get('wins') or 0),
                    int(row.get('losses') or 0),
                    int(row.get('ambiguous') or 0),
                    row.get('win_rate'),
                    row.get('avg_gain_pct'),
                    row.get('avg_loss_pct'),
                    row.get('expectancy_pct'),
                    row.get('max_drawdown_proxy'),
                    row.get('sample_warning'),
                    row.get('updated_at') or now,
                ),
            )
            written += 1
        conn.commit()
    finally:
        conn.close()
    return written


def list_runs(*, market: str | None = None, limit: int | None = None) -> list[dict]:
    """Return simulation runs ordered by created_at DESC."""
    clauses: list[str] = []
    params: list[Any] = []
    if market:
        clauses.append('market = ?')
        params.append(str(market).strip().upper())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
    query = f"""
        SELECT *
        FROM historical_simulation_runs
        {where}
        ORDER BY created_at DESC
    """
    if limit is not None and limit > 0:
        query += ' LIMIT ?'
        params.append(int(limit))

    conn = get_connection()
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def get_sim_predictions(
    *,
    run_id: str | None = None,
    market: str | None = None,
    ticker: str | None = None,
    strategy: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Return simulated prediction rows."""
    clauses: list[str] = []
    params: list[Any] = []
    if run_id:
        clauses.append('run_id = ?')
        params.append(run_id)
    if market:
        clauses.append('market = ?')
        params.append(str(market).strip().upper())
    if ticker:
        clauses.append('ticker = ?')
        params.append(str(ticker).strip().upper())
    if strategy:
        clauses.append('strategy = ?')
        params.append(strategy)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
    query = f"""
        SELECT *
        FROM historical_simulated_predictions
        {where}
        ORDER BY signal_date ASC, ticker ASC
    """
    if limit is not None and limit > 0:
        query += ' LIMIT ?'
        params.append(int(limit))

    conn = get_connection()
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def get_sim_outcomes(
    *,
    run_id: str | None = None,
    strategy: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Return simulated outcome rows, optionally filtered by run_id via join."""
    if run_id:
        query = """
            SELECT o.*
            FROM historical_simulated_outcomes o
            JOIN historical_simulated_predictions p
              ON p.sim_prediction_id = o.sim_prediction_id
            WHERE p.run_id = ?
            ORDER BY o.signal_date ASC, o.ticker ASC
        """
        params: list[Any] = [run_id]
        if limit is not None and limit > 0:
            query += ' LIMIT ?'
            params.append(int(limit))
    else:
        clauses: list[str] = []
        params = []
        if strategy:
            clauses.append('strategy = ?')
            params.append(strategy)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
        query = f"""
            SELECT *
            FROM historical_simulated_outcomes
            {where}
            ORDER BY signal_date ASC, ticker ASC
        """
        if limit is not None and limit > 0:
            query += ' LIMIT ?'
            params.append(int(limit))

    conn = get_connection()
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def get_strategy_performance(*, market: str | None = None) -> list[dict]:
    """Return cached strategy performance rows."""
    conn = get_connection()
    try:
        if market:
            rows = conn.execute(
                """
                SELECT *
                FROM historical_strategy_performance
                WHERE market = ?
                ORDER BY predictions DESC, strategy ASC
                """,
                (str(market).strip().upper(),),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM historical_strategy_performance
                ORDER BY predictions DESC, strategy ASC, market ASC
                """
            ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def get_simulation_stats() -> dict:
    """Return aggregate simulation table counts and summary metrics."""
    stats = {
        'simulation_runs': 0,
        'simulated_predictions': 0,
        'simulated_outcomes': 0,
        'strategy_performance_rows': 0,
        'sim_wins': 0,
        'sim_losses': 0,
        'sim_ambiguous': 0,
        'sim_resolved': 0,
        'sim_win_rate': None,
        'latest_run_id': None,
    }
    db_path = get_historical_db_path()
    if not db_path.exists():
        return stats

    conn = get_connection()
    try:
        for table, key in (
            ('historical_simulation_runs', 'simulation_runs'),
            ('historical_simulated_predictions', 'simulated_predictions'),
            ('historical_simulated_outcomes', 'simulated_outcomes'),
            ('historical_strategy_performance', 'strategy_performance_rows'),
        ):
            row = conn.execute(f'SELECT COUNT(*) AS cnt FROM {table}').fetchone()
            stats[key] = int(row['cnt']) if row else 0

        outcome_rows = conn.execute(
            """
            SELECT result, COUNT(*) AS cnt
            FROM historical_simulated_outcomes
            GROUP BY result
            """
        ).fetchall()
        for row in outcome_rows:
            token = str(row['result'] or '').strip().upper()
            count = int(row['cnt'])
            if token == 'WIN' or token.startswith('WIN'):
                stats['sim_wins'] += count
            elif token == 'LOSS' or token.startswith('LOSS'):
                stats['sim_losses'] += count
            elif token == 'AMBIGUOUS_DAILY_CANDLE':
                stats['sim_ambiguous'] += count

        stats['sim_resolved'] = stats['sim_wins'] + stats['sim_losses'] + stats['sim_ambiguous']
        if stats['sim_wins'] + stats['sim_losses'] > 0:
            stats['sim_win_rate'] = stats['sim_wins'] / (stats['sim_wins'] + stats['sim_losses'])

        latest = conn.execute(
            """
            SELECT run_id
            FROM historical_simulation_runs
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
        if latest:
            stats['latest_run_id'] = latest['run_id']
    finally:
        conn.close()
    return stats


def rebuild_strategy_performance(*, market: str | None = None) -> int:
    """Recompute historical_strategy_performance from simulated outcomes."""
    conn = get_connection()
    try:
        if market:
            conn.execute(
                'DELETE FROM historical_strategy_performance WHERE market = ?',
                (str(market).strip().upper(),),
            )
        else:
            conn.execute('DELETE FROM historical_strategy_performance')

        clauses: list[str] = []
        params: list[Any] = []
        if market:
            clauses.append('p.market = ?')
            params.append(str(market).strip().upper())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ''

        rows = conn.execute(
            f"""
            SELECT
                o.strategy,
                COALESCE(p.market, 'UNKNOWN') AS market,
                o.result,
                o.max_gain_pct,
                o.max_loss_pct,
                o.close_move_pct
            FROM historical_simulated_outcomes o
            JOIN historical_simulated_predictions p
              ON p.sim_prediction_id = o.sim_prediction_id
            {where}
            """,
            params,
        ).fetchall()

        buckets: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (str(row['strategy']), str(row['market']))
            bucket = buckets.setdefault(
                key,
                {
                    'predictions': 0,
                    'resolved': 0,
                    'wins': 0,
                    'losses': 0,
                    'ambiguous': 0,
                    'gains': [],
                    'losses_pct': [],
                    'close_moves': [],
                },
            )
            bucket['predictions'] += 1
            token = str(row['result'] or '').strip().upper()
            if token in ('WIN',) or token.startswith('WIN'):
                bucket['wins'] += 1
                bucket['resolved'] += 1
            elif token in ('LOSS',) or token.startswith('LOSS'):
                bucket['losses'] += 1
                bucket['resolved'] += 1
            elif token == 'AMBIGUOUS_DAILY_CANDLE':
                bucket['ambiguous'] += 1
                bucket['resolved'] += 1
            else:
                bucket['resolved'] += 1

            for field, dest in (
                ('max_gain_pct', 'gains'),
                ('max_loss_pct', 'losses_pct'),
                ('close_move_pct', 'close_moves'),
            ):
                val = row[field]
                if val is not None:
                    try:
                        bucket[dest].append(float(val))
                    except (TypeError, ValueError):
                        pass

        now = _now_iso()
        for (strategy, market_key), bucket in buckets.items():
            wins = bucket['wins']
            losses = bucket['losses']
            win_rate = wins / (wins + losses) if (wins + losses) > 0 else None
            avg_gain = (
                sum(bucket['gains']) / len(bucket['gains']) if bucket['gains'] else None
            )
            avg_loss = (
                sum(bucket['losses_pct']) / len(bucket['losses_pct'])
                if bucket['losses_pct'] else None
            )
            expectancy = None
            if win_rate is not None and avg_gain is not None and avg_loss is not None:
                expectancy = (win_rate * avg_gain) + ((1 - win_rate) * avg_loss)
            max_dd = min(bucket['losses_pct']) if bucket['losses_pct'] else None
            sample_warning = None
            if bucket['resolved'] < 5:
                sample_warning = 'low_sample_size'

            conn.execute(
                """
                INSERT INTO historical_strategy_performance (
                    strategy, market, predictions, resolved, wins, losses, ambiguous,
                    win_rate, avg_gain_pct, avg_loss_pct, expectancy_pct,
                    max_drawdown_proxy, sample_warning, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    strategy,
                    market_key,
                    bucket['predictions'],
                    bucket['resolved'],
                    wins,
                    losses,
                    bucket['ambiguous'],
                    win_rate,
                    avg_gain,
                    avg_loss,
                    expectancy,
                    max_dd,
                    sample_warning,
                    now,
                ),
            )
        conn.commit()
        return len(buckets)
    finally:
        conn.close()


def get_distinct_tickers(*, market: str | None = None, limit: int | None = None) -> list[str]:
    """Return distinct tickers from historical_prices."""
    clauses: list[str] = []
    params: list[Any] = []
    if market:
        clauses.append('market = ?')
        params.append(str(market).strip().upper())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
    query = f"""
        SELECT DISTINCT ticker
        FROM historical_prices
        {where}
        ORDER BY ticker ASC
    """
    if limit is not None and limit > 0:
        query += ' LIMIT ?'
        params.append(int(limit))

    conn = get_connection()
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    return [str(row['ticker']).strip().upper() for row in rows if row.get('ticker')]


def get_stats() -> dict:
    """Return table counts and DB metadata."""
    db_path = get_historical_db_path()
    stats = {
        'db_path': str(db_path),
        'db_exists': db_path.exists(),
        'historical_prices': 0,
        'historical_outcome_replay': 0,
        'historical_source_performance': 0,
        'historical_price_anomalies': 0,
        'historical_price_anomalies_active': 0,
        'historical_price_anomalies_warning': 0,
        'historical_price_anomalies_suspicious': 0,
        'historical_price_anomalies_exclude': 0,
        'fake_prices_rows': 0,
        'historical_simulation_runs': 0,
        'historical_simulated_predictions': 0,
        'historical_simulated_outcomes': 0,
        'historical_strategy_performance': 0,
    }
    if not db_path.exists():
        return stats

    conn = get_connection()
    try:
        for table, key in (
            ('historical_prices', 'historical_prices'),
            ('historical_outcome_replay', 'historical_outcome_replay'),
            ('historical_source_performance', 'historical_source_performance'),
            ('historical_price_anomalies', 'historical_price_anomalies'),
            ('historical_simulation_runs', 'historical_simulation_runs'),
            ('historical_simulated_predictions', 'historical_simulated_predictions'),
            ('historical_simulated_outcomes', 'historical_simulated_outcomes'),
            ('historical_strategy_performance', 'historical_strategy_performance'),
        ):
            row = conn.execute(f'SELECT COUNT(*) AS cnt FROM {table}').fetchone()
            stats[key] = int(row['cnt']) if row else 0

        active_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM historical_price_anomalies WHERE status = 'active'"
        ).fetchone()
        stats['historical_price_anomalies_active'] = int(active_row['cnt']) if active_row else 0

        for severity, key in (
            ('warning', 'historical_price_anomalies_warning'),
            ('suspicious', 'historical_price_anomalies_suspicious'),
            ('exclude_from_simulation', 'historical_price_anomalies_exclude'),
        ):
            row = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM historical_price_anomalies
                WHERE status = 'active' AND severity = ?
                """,
                (severity,),
            ).fetchone()
            stats[key] = int(row['cnt']) if row else 0

        fake_row = conn.execute(
            'SELECT COUNT(*) AS cnt FROM historical_prices WHERE fake_prices != 0'
        ).fetchone()
        stats['fake_prices_rows'] = int(fake_row['cnt']) if fake_row else 0
    finally:
        conn.close()
    return stats


def _main() -> int:
    ok = init_db()
    path = get_historical_db_path()
    stats = get_stats()
    print(f'[HISTORICAL_MARKET] path={path}')
    print(f'[HISTORICAL_MARKET] stats={json.dumps(stats, default=str)}')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(_main())
