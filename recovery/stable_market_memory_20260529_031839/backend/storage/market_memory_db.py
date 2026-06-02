"""
Canonical Market Memory DB — standalone SQLite at data/canonical_market_memory.db.

Tables:
  A. predictions
  B. broker_predictions
  C. outcomes
  D. market_context_snapshots
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

MARKET_MEMORY_DB_NAME = 'canonical_market_memory.db'

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    prediction_id TEXT PRIMARY KEY,
    legacy_prediction_id INTEGER,
    ticker TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    source TEXT,
    direction TEXT,
    confidence REAL,
    confidence_label TEXT,
    market_regime TEXT,
    sector TEXT,
    reasoning TEXT,
    signal_stack TEXT,
    raw_payload TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_mm_predictions_ticker ON predictions(ticker);
CREATE INDEX IF NOT EXISTS idx_mm_predictions_timestamp ON predictions(timestamp);
CREATE INDEX IF NOT EXISTS idx_mm_predictions_source ON predictions(source);
CREATE INDEX IF NOT EXISTS idx_mm_predictions_direction ON predictions(direction);
CREATE INDEX IF NOT EXISTS idx_mm_predictions_market_regime ON predictions(market_regime);
CREATE INDEX IF NOT EXISTS idx_mm_predictions_sector ON predictions(sector);

CREATE TABLE IF NOT EXISTS broker_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id TEXT,
    broker_source TEXT NOT NULL,
    ticker TEXT NOT NULL,
    bullish_or_bearish TEXT,
    target_type TEXT,
    timeframe TEXT,
    confidence REAL,
    raw_payload TEXT,
    dedupe_key TEXT UNIQUE,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_mm_broker_ticker ON broker_predictions(ticker);
CREATE INDEX IF NOT EXISTS idx_mm_broker_source ON broker_predictions(broker_source);
CREATE INDEX IF NOT EXISTS idx_mm_broker_direction ON broker_predictions(bullish_or_bearish);
CREATE INDEX IF NOT EXISTS idx_mm_broker_timeframe ON broker_predictions(timeframe);

CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id TEXT NOT NULL,
    actual_move REAL,
    high REAL,
    low REAL,
    expiry_result TEXT,
    resolved_as TEXT,
    holding_period TEXT NOT NULL,
    market_context TEXT,
    vix REAL,
    crude REAL,
    fii_dii TEXT,
    global_sentiment TEXT,
    india_sentiment TEXT,
    sector_strength TEXT,
    market_regime TEXT,
    raw_payload TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(prediction_id, holding_period)
);

CREATE INDEX IF NOT EXISTS idx_mm_outcomes_prediction_id ON outcomes(prediction_id);
CREATE INDEX IF NOT EXISTS idx_mm_outcomes_resolved_as ON outcomes(resolved_as);
CREATE INDEX IF NOT EXISTS idx_mm_outcomes_market_regime ON outcomes(market_regime);
CREATE INDEX IF NOT EXISTS idx_mm_outcomes_holding_period ON outcomes(holding_period);

CREATE TABLE IF NOT EXISTS market_context_snapshots (
    context_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    market_regime TEXT,
    vix REAL,
    crude REAL,
    fii_dii TEXT,
    global_sentiment TEXT,
    india_sentiment TEXT,
    sector_strength TEXT,
    raw_payload TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_mm_context_timestamp ON market_context_snapshots(timestamp);
CREATE INDEX IF NOT EXISTS idx_mm_context_market_regime ON market_context_snapshots(market_regime);
"""


def get_market_memory_path() -> Path:
    """Return path to canonical market memory SQLite DB."""
    return DATA_DIR / MARKET_MEMORY_DB_NAME


def get_connection(timeout: float = 30.0) -> sqlite3.Connection:
    """Open SQLite connection with Row factory and canonical pragmas."""
    ensure_dirs()
    conn = sqlite3.connect(str(get_market_memory_path()), timeout=timeout)
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
    print(f'[MARKET_MEMORY] {message}', file=sys.stderr)


def init_market_memory_db() -> bool:
    """Create schema idempotently. Returns True on success."""
    try:
        ensure_dirs()
        conn = get_connection()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception as exc:
        _log_error(f'init failed: {exc}')
        return False


def make_prediction_id(payload: dict) -> str:
    """Build stable prediction_id (legacy: or mm: sha256 prefix)."""
    legacy = payload.get('legacy_prediction_id')
    if legacy is not None and str(legacy).strip() != '':
        return f'legacy:{legacy}'

    parts = ''.join(
        str(payload.get(key) or '')
        for key in ('ticker', 'timestamp', 'source', 'direction', 'reasoning')
    )
    digest = hashlib.sha256(parts.encode('utf-8')).hexdigest()[:24]
    return f'mm:{digest}'


def _make_dedupe_key(payload: dict) -> str:
    return ''.join(
        str(payload.get(key) or '')
        for key in ('broker_source', 'ticker', 'timeframe', 'bullish_or_bearish', 'target_type')
    )


def _make_context_id(payload: dict) -> str:
    parts = ''.join(
        str(payload.get(key) or '')
        for key in ('timestamp', 'market_regime')
    )
    digest = hashlib.sha256(parts.encode('utf-8')).hexdigest()[:24]
    return f'ctx:{digest}'


def upsert_prediction(payload: dict) -> str | None:
    """Insert or update a canonical prediction row."""
    try:
        prediction_id = payload.get('prediction_id') or make_prediction_id(payload)
        now = _now_iso()
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO predictions (
                    prediction_id, legacy_prediction_id, ticker, timestamp, source,
                    direction, confidence, confidence_label, market_regime, sector,
                    reasoning, signal_stack, raw_payload, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(prediction_id) DO UPDATE SET
                    legacy_prediction_id=excluded.legacy_prediction_id,
                    ticker=excluded.ticker,
                    timestamp=excluded.timestamp,
                    source=excluded.source,
                    direction=excluded.direction,
                    confidence=excluded.confidence,
                    confidence_label=excluded.confidence_label,
                    market_regime=excluded.market_regime,
                    sector=excluded.sector,
                    reasoning=excluded.reasoning,
                    signal_stack=excluded.signal_stack,
                    raw_payload=excluded.raw_payload,
                    updated_at=excluded.updated_at
                """,
                (
                    prediction_id,
                    payload.get('legacy_prediction_id'),
                    payload.get('ticker'),
                    payload.get('timestamp'),
                    payload.get('source'),
                    payload.get('direction'),
                    payload.get('confidence'),
                    payload.get('confidence_label'),
                    payload.get('market_regime'),
                    payload.get('sector'),
                    payload.get('reasoning'),
                    _json_text(payload.get('signal_stack')),
                    _json_text(payload.get('raw_payload')),
                    payload.get('created_at') or now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return prediction_id
    except Exception as exc:
        _log_error(f'upsert_prediction failed: {exc}')
        return None


def upsert_broker_prediction(payload: dict) -> int | None:
    """Insert broker prediction; dedupe via dedupe_key. Returns row id."""
    try:
        dedupe_key = payload.get('dedupe_key') or _make_dedupe_key(payload)
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO broker_predictions (
                    prediction_id, broker_source, ticker, bullish_or_bearish,
                    target_type, timeframe, confidence, raw_payload, dedupe_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.get('prediction_id'),
                    payload.get('broker_source'),
                    payload.get('ticker'),
                    payload.get('bullish_or_bearish'),
                    payload.get('target_type'),
                    payload.get('timeframe'),
                    payload.get('confidence'),
                    _json_text(payload.get('raw_payload')),
                    dedupe_key,
                    payload.get('created_at') or _now_iso(),
                ),
            )
            conn.commit()
            if cur.lastrowid:
                return int(cur.lastrowid)
            row = conn.execute(
                'SELECT id FROM broker_predictions WHERE dedupe_key = ?',
                (dedupe_key,),
            ).fetchone()
            return int(row['id']) if row else None
        finally:
            conn.close()
    except Exception as exc:
        _log_error(f'upsert_broker_prediction failed: {exc}')
        return None


def upsert_outcome(payload: dict) -> bool:
    """Insert or update outcome by UNIQUE(prediction_id, holding_period)."""
    try:
        now = _now_iso()
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO outcomes (
                    prediction_id, actual_move, high, low, expiry_result, resolved_as,
                    holding_period, market_context, vix, crude, fii_dii, global_sentiment,
                    india_sentiment, sector_strength, market_regime, raw_payload,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(prediction_id, holding_period) DO UPDATE SET
                    actual_move=excluded.actual_move,
                    high=excluded.high,
                    low=excluded.low,
                    expiry_result=excluded.expiry_result,
                    resolved_as=excluded.resolved_as,
                    market_context=excluded.market_context,
                    vix=excluded.vix,
                    crude=excluded.crude,
                    fii_dii=excluded.fii_dii,
                    global_sentiment=excluded.global_sentiment,
                    india_sentiment=excluded.india_sentiment,
                    sector_strength=excluded.sector_strength,
                    market_regime=excluded.market_regime,
                    raw_payload=excluded.raw_payload,
                    updated_at=excluded.updated_at
                """,
                (
                    payload.get('prediction_id'),
                    payload.get('actual_move'),
                    payload.get('high'),
                    payload.get('low'),
                    payload.get('expiry_result'),
                    payload.get('resolved_as'),
                    payload.get('holding_period'),
                    payload.get('market_context'),
                    payload.get('vix'),
                    payload.get('crude'),
                    payload.get('fii_dii'),
                    payload.get('global_sentiment'),
                    payload.get('india_sentiment'),
                    payload.get('sector_strength'),
                    payload.get('market_regime'),
                    _json_text(payload.get('raw_payload')),
                    payload.get('created_at') or now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception as exc:
        _log_error(f'upsert_outcome failed: {exc}')
        return False


def insert_market_context_snapshot(payload: dict) -> str | None:
    """Insert market context snapshot; ignore duplicates by context_id."""
    try:
        context_id = payload.get('context_id') or _make_context_id(payload)
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO market_context_snapshots (
                    context_id, timestamp, market_regime, vix, crude, fii_dii,
                    global_sentiment, india_sentiment, sector_strength, raw_payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    context_id,
                    payload.get('timestamp'),
                    payload.get('market_regime'),
                    payload.get('vix'),
                    payload.get('crude'),
                    payload.get('fii_dii'),
                    payload.get('global_sentiment'),
                    payload.get('india_sentiment'),
                    payload.get('sector_strength'),
                    _json_text(payload.get('raw_payload')),
                    payload.get('created_at') or _now_iso(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return context_id
    except Exception as exc:
        _log_error(f'insert_market_context_snapshot failed: {exc}')
        return None


def get_market_memory_stats() -> dict:
    """Return table counts and DB metadata."""
    db_path = get_market_memory_path()
    stats = {
        'db_path': str(db_path),
        'db_exists': db_path.exists(),
        'predictions': 0,
        'broker_predictions': 0,
        'outcomes': 0,
        'market_context_snapshots': 0,
    }
    if not db_path.exists():
        return stats

    conn = get_connection()
    try:
        for table, key in (
            ('predictions', 'predictions'),
            ('broker_predictions', 'broker_predictions'),
            ('outcomes', 'outcomes'),
            ('market_context_snapshots', 'market_context_snapshots'),
        ):
            row = conn.execute(f'SELECT COUNT(*) AS cnt FROM {table}').fetchone()
            stats[key] = int(row['cnt']) if row else 0
    finally:
        conn.close()
    return stats


def _main() -> int:
    ok = init_market_memory_db()
    path = get_market_memory_path()
    stats = get_market_memory_stats()
    print(f'[MARKET_MEMORY] path={path}')
    print(f'[MARKET_MEMORY] stats={json.dumps(stats, default=str)}')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(_main())
