"""
Database Manager v1 - Path D
SQLite database for tracking AI predictions, scanner signals, and outcomes

Tables:
1. predictions       - Every AI recommendation (buy/sell/avoid)
2. signals           - Every scanner signal (volume spikes, breakouts)
3. outcomes          - Actual market prices 1d/3d/7d after prediction
4. accuracy_metrics  - Daily/weekly aggregated accuracy stats

This is the LEARNING ENGINE that will make your system smarter over time.
"""

import sqlite3
import json
import sys
import io
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Force UTF-8 stdout on Windows
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# ============================================================
# CONFIGURATION
# ============================================================

from backend.utils.config import DB_PATH, ensure_dirs

ensure_dirs()

# ============================================================
# SCHEMA - 4 TABLES
# ============================================================

SCHEMA = """
-- Table 1: AI Predictions (from master_analyzer.py output)
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    prediction_date DATE NOT NULL,
    run_type TEXT,                    -- overnight_brief, premarket, midday, post_close, intraday
    use_case TEXT,                    -- AI model used (sonnet/haiku/gemini)
    
    -- Stock & Recommendation
    ticker TEXT NOT NULL,
    sector TEXT,
    recommendation TEXT NOT NULL,     -- BUY, SELL, HOLD, ACCUMULATE, AVOID, WATCH
    category TEXT NOT NULL,           -- 'opportunity' or 'risk'
    rank_in_list INTEGER,             -- 1-10 in opportunity/risk list
    
    -- Trade Setup
    entry_price REAL,
    target_price REAL,
    stop_loss REAL,
    confidence TEXT,                  -- HIGH, MEDIUM, LOW
    
    -- Cross-validation
    reasoning TEXT,
    cross_validation TEXT,            -- e.g., "Govt + Scanner aligned"
    
    -- Conviction
    overall_conviction INTEGER,       -- 0-10
    
    -- Metadata
    raw_data TEXT,                    -- JSON of full prediction details
    UNIQUE(prediction_date, ticker, category, run_type)
);

CREATE INDEX IF NOT EXISTS idx_pred_date ON predictions(prediction_date);
CREATE INDEX IF NOT EXISTS idx_pred_ticker ON predictions(ticker);
CREATE INDEX IF NOT EXISTS idx_pred_category ON predictions(category);


-- Table 2: Scanner Signals (from stock_scanner.py)
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    signal_date DATE NOT NULL,
    
    ticker TEXT NOT NULL,
    sector TEXT,
    
    -- Signal details
    strength TEXT NOT NULL,           -- ULTRA, STRONG, MODERATE, WEAK
    direction TEXT NOT NULL,          -- BULLISH, BEARISH, NEUTRAL
    signal_types TEXT,                -- JSON array: ["VOLUME_SPIKE","BREAKOUT"]
    
    -- Price data at signal time
    price REAL,
    change_percent REAL,
    volume_ratio REAL,
    high_20d REAL,
    low_20d REAL,
    gap_percent REAL,
    
    raw_data TEXT,                    -- Full JSON
    UNIQUE(signal_date, ticker, strength)
);

CREATE INDEX IF NOT EXISTS idx_sig_date ON signals(signal_date);
CREATE INDEX IF NOT EXISTS idx_sig_ticker ON signals(ticker);
CREATE INDEX IF NOT EXISTS idx_sig_strength ON signals(strength);


-- Table 3: Outcomes (price checks 1d/3d/7d later)
CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Link back to prediction or signal
    source_type TEXT NOT NULL,        -- 'prediction' or 'signal'
    source_id INTEGER NOT NULL,
    
    ticker TEXT NOT NULL,
    prediction_date DATE NOT NULL,
    entry_price REAL,                 -- Price at prediction time
    
    -- Outcomes at different horizons
    price_1d REAL,
    change_1d_pct REAL,
    price_3d REAL,
    change_3d_pct REAL,
    price_7d REAL,
    change_7d_pct REAL,
    
    -- Verdict
    target_hit BOOLEAN DEFAULT 0,     -- Did target_price hit within 7 days?
    stop_loss_hit BOOLEAN DEFAULT 0,  -- Did stop_loss hit within 7 days?
    max_gain_pct REAL,                -- Best move within 7 days
    max_loss_pct REAL,                -- Worst move within 7 days
    
    verdict TEXT,                     -- WIN, LOSS, NEUTRAL, PENDING
    last_checked TIMESTAMP,
    
    UNIQUE(source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_out_ticker ON outcomes(ticker);
CREATE INDEX IF NOT EXISTS idx_out_verdict ON outcomes(verdict);
CREATE INDEX IF NOT EXISTS idx_out_date ON outcomes(prediction_date);


-- Table 4: Accuracy Metrics (aggregated stats)
CREATE TABLE IF NOT EXISTS accuracy_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_date DATE NOT NULL,
    metric_type TEXT NOT NULL,         -- 'daily', 'weekly', 'all_time'
    
    -- Counts
    total_predictions INTEGER,
    total_evaluated INTEGER,
    wins INTEGER,
    losses INTEGER,
    neutral INTEGER,
    pending INTEGER,
    
    -- Rates
    win_rate REAL,                    -- 0-100%
    avg_gain_pct REAL,
    avg_loss_pct REAL,
    profit_factor REAL,               -- avg_gain / avg_loss
    
    -- By category
    opportunity_win_rate REAL,
    risk_avoidance_rate REAL,         -- Were our "AVOID" picks indeed losers?
    
    -- By confidence
    high_conf_win_rate REAL,
    medium_conf_win_rate REAL,
    low_conf_win_rate REAL,
    
    UNIQUE(metric_date, metric_type)
);

CREATE INDEX IF NOT EXISTS idx_metrics_date ON accuracy_metrics(metric_date);
"""

SIGNAL_TRACKING_SCHEMA = """
-- Outcome learning: unified signal event tracking
CREATE TABLE IF NOT EXISTS signal_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event_ts TEXT NOT NULL,
    event_date DATE NOT NULL,
    signal_type TEXT NOT NULL,
    source TEXT,
    ticker TEXT,
    direction TEXT,
    confidence REAL,
    confidence_band TEXT,
    regime TEXT,
    sector TEXT,
    reasoning_summary TEXT,
    contradiction_severity REAL,
    source_consensus REAL,
    entry_price REAL,
    dedupe_key TEXT,
    metadata TEXT,
    UNIQUE(event_date, signal_type, source, ticker, dedupe_key)
);

CREATE INDEX IF NOT EXISTS idx_se_date ON signal_events(event_date);
CREATE INDEX IF NOT EXISTS idx_se_type ON signal_events(signal_type);
CREATE INDEX IF NOT EXISTS idx_se_ticker ON signal_events(ticker);
CREATE INDEX IF NOT EXISTS idx_se_regime ON signal_events(regime);

CREATE TABLE IF NOT EXISTS signal_horizons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    horizon TEXT NOT NULL,
    due_at TEXT,
    evaluated_at TEXT,
    price REAL,
    change_pct REAL,
    mfe_pct REAL,
    mae_pct REAL,
    hit_miss TEXT DEFAULT 'PENDING',
    UNIQUE(event_id, horizon)
);

CREATE INDEX IF NOT EXISTS idx_sh_event ON signal_horizons(event_id);
CREATE INDEX IF NOT EXISTS idx_sh_horizon ON signal_horizons(horizon);
CREATE INDEX IF NOT EXISTS idx_sh_hit ON signal_horizons(hit_miss);
"""


# ============================================================
# DATABASE CONNECTION
# ============================================================

_init_db_logged = False


def get_trading_db_path() -> Path:
    """Canonical path for trading history / lifecycle (never market memory)."""
    return Path(DB_PATH)


def init_db():
    """Create all tables if they don't exist"""
    global _init_db_logged
    db_path = get_trading_db_path()
    if not _init_db_logged:
        print(f"[DB] Initializing database at: {db_path}")
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.executescript(SIGNAL_TRACKING_SCHEMA)
        cols = {row[1] for row in conn.execute('PRAGMA table_info(predictions)').fetchall()}
        for name, col_type in (
            ('prediction_horizon', 'TEXT'),
            ('signal_type', 'TEXT'),
            ('failure_reason', 'TEXT'),
        ):
            if name not in cols:
                conn.execute(f'ALTER TABLE predictions ADD COLUMN {name} {col_type}')
        conn.commit()
        if not _init_db_logged:
            print("[DB] Schema initialized successfully")
            _init_db_logged = True
    except Exception as e:
        print(f"[DB] ERROR initializing: {e}")
    finally:
        conn.close()


def get_connection(timeout: float = 30.0):
    """Get a database connection with busy-timeout (avoids indefinite SQLite locks)."""
    db_path = get_trading_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=timeout)
    conn.row_factory = sqlite3.Row  # Allow dict-like access
    conn.execute("PRAGMA foreign_keys = ON")
    busy_ms = max(1000, int(timeout * 1000))
    conn.execute(f"PRAGMA busy_timeout = {busy_ms}")
    return conn


# ============================================================
# PREDICTION OPERATIONS
# ============================================================

def insert_prediction(prediction_data):
    """
    Insert a single AI prediction
    
    prediction_data dict should have:
    - prediction_date (YYYY-MM-DD)
    - run_type, use_case
    - ticker, sector, recommendation, category, rank_in_list
    - entry_price, target_price, stop_loss
    - confidence, reasoning, cross_validation
    - overall_conviction, raw_data
    """
    conn = get_connection()
    try:
        cursor = conn.execute("""
            INSERT OR REPLACE INTO predictions (
                prediction_date, run_type, use_case,
                ticker, sector, recommendation, category, rank_in_list,
                entry_price, target_price, stop_loss,
                confidence, reasoning, cross_validation,
                overall_conviction, raw_data,
                prediction_horizon, signal_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            prediction_data.get('prediction_date'),
            prediction_data.get('run_type'),
            prediction_data.get('use_case'),
            prediction_data.get('ticker'),
            prediction_data.get('sector'),
            prediction_data.get('recommendation'),
            prediction_data.get('category'),
            prediction_data.get('rank_in_list'),
            prediction_data.get('entry_price'),
            prediction_data.get('target_price'),
            prediction_data.get('stop_loss'),
            prediction_data.get('confidence'),
            prediction_data.get('reasoning'),
            prediction_data.get('cross_validation'),
            prediction_data.get('overall_conviction'),
            json.dumps(prediction_data.get('raw_data', {})),
            prediction_data.get('prediction_horizon'),
            prediction_data.get('signal_type'),
        ))
        conn.commit()
        row_id = cursor.lastrowid
        try:
            from backend.storage.market_memory_capture import capture_prediction

            capture_payload = dict(prediction_data)
            if row_id:
                capture_payload['id'] = row_id
            capture_prediction(capture_payload, source_hint='trading_history')
        except Exception:
            pass
        return row_id
    except Exception as e:
        print(f"[DB] ERROR inserting prediction: {e}")
        return None
    finally:
        conn.close()


def get_pending_predictions(days_back=8):
    """Get predictions that need outcome checking (not yet evaluated)"""
    cutoff = (datetime.now() - timedelta(days=days_back)).date().isoformat()
    
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT p.* FROM predictions p
            LEFT JOIN outcomes o ON o.source_type='prediction' AND o.source_id=p.id
            WHERE p.prediction_date >= ?
              AND (o.id IS NULL OR o.verdict='PENDING')
            ORDER BY p.prediction_date DESC
        """, (cutoff,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_predictions_by_date(date):
    """Get all predictions for a specific date"""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT * FROM predictions 
            WHERE prediction_date = ?
            ORDER BY category, rank_in_list
        """, (date,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ============================================================
# SIGNAL OPERATIONS
# ============================================================

def insert_signal(signal_data):
    """Insert a scanner signal"""
    conn = get_connection()
    try:
        cursor = conn.execute("""
            INSERT OR REPLACE INTO signals (
                signal_date, ticker, sector,
                strength, direction, signal_types,
                price, change_percent, volume_ratio,
                high_20d, low_20d, gap_percent,
                raw_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal_data.get('signal_date'),
            signal_data.get('ticker'),
            signal_data.get('sector'),
            signal_data.get('strength'),
            signal_data.get('direction'),
            json.dumps(signal_data.get('signal_types', [])),
            signal_data.get('price'),
            signal_data.get('change_percent'),
            signal_data.get('volume_ratio'),
            signal_data.get('high_20d'),
            signal_data.get('low_20d'),
            signal_data.get('gap_percent'),
            json.dumps(signal_data.get('raw_data', {})),
        ))
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        print(f"[DB] ERROR inserting signal: {e}")
        return None
    finally:
        conn.close()


# ============================================================
# OUTCOME OPERATIONS
# ============================================================

def _normalize_sqlite_value(value, field_name=None):
    """Coerce Python values into SQLite-bindable scalars."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (str, int, float, bytes)):
        return value
    if isinstance(value, (tuple, list)):
        if field_name == 'verdict' and value:
            return str(value[0])
        if field_name in ('target_hit', 'stop_loss_hit') and value:
            return int(bool(value[0]))
        for item in value:
            if isinstance(item, (int, float)):
                return item
            if isinstance(item, str) and item:
                return item
        return str(value[0]) if value else None
    if isinstance(value, dict):
        return json.dumps(value)
    return str(value)


def _normalize_outcome_data(outcome_data):
    """Normalize outcome payload — unwrap verdict tuples and coerce bind types."""
    data = dict(outcome_data or {})
    verdict = data.get('verdict')
    if isinstance(verdict, tuple):
        data['verdict'] = verdict[0]
        if len(verdict) > 1 and 'target_hit' not in outcome_data:
            data['target_hit'] = verdict[1]
        if len(verdict) > 2 and 'stop_loss_hit' not in outcome_data:
            data['stop_loss_hit'] = verdict[2]
    for key in (
        'source_type', 'source_id', 'ticker', 'prediction_date', 'entry_price',
        'price_1d', 'change_1d_pct', 'price_3d', 'change_3d_pct', 'price_7d', 'change_7d_pct',
        'target_hit', 'stop_loss_hit', 'max_gain_pct', 'max_loss_pct', 'verdict',
    ):
        if key in data:
            data[key] = _normalize_sqlite_value(data[key], key)
    return data


def upsert_outcome(outcome_data):
    """Insert or update an outcome record"""
    outcome_data = _normalize_outcome_data(outcome_data)
    conn = get_connection()
    try:
        # Check if exists
        existing = conn.execute("""
            SELECT id FROM outcomes 
            WHERE source_type=? AND source_id=?
        """, (outcome_data['source_type'], outcome_data['source_id'])).fetchone()
        
        if existing:
            # Update
            conn.execute("""
                UPDATE outcomes SET
                    price_1d=?, change_1d_pct=?,
                    price_3d=?, change_3d_pct=?,
                    price_7d=?, change_7d_pct=?,
                    target_hit=?, stop_loss_hit=?,
                    max_gain_pct=?, max_loss_pct=?,
                    verdict=?, last_checked=CURRENT_TIMESTAMP
                WHERE id=?
            """, (
                outcome_data.get('price_1d'),
                outcome_data.get('change_1d_pct'),
                outcome_data.get('price_3d'),
                outcome_data.get('change_3d_pct'),
                outcome_data.get('price_7d'),
                outcome_data.get('change_7d_pct'),
                outcome_data.get('target_hit', 0),
                outcome_data.get('stop_loss_hit', 0),
                outcome_data.get('max_gain_pct'),
                outcome_data.get('max_loss_pct'),
                outcome_data.get('verdict'),
                existing['id'],
            ))
        else:
            # Insert
            conn.execute("""
                INSERT INTO outcomes (
                    source_type, source_id, ticker, prediction_date, entry_price,
                    price_1d, change_1d_pct,
                    price_3d, change_3d_pct,
                    price_7d, change_7d_pct,
                    target_hit, stop_loss_hit,
                    max_gain_pct, max_loss_pct,
                    verdict, last_checked
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                outcome_data['source_type'],
                outcome_data['source_id'],
                outcome_data.get('ticker'),
                outcome_data.get('prediction_date'),
                outcome_data.get('entry_price'),
                outcome_data.get('price_1d'),
                outcome_data.get('change_1d_pct'),
                outcome_data.get('price_3d'),
                outcome_data.get('change_3d_pct'),
                outcome_data.get('price_7d'),
                outcome_data.get('change_7d_pct'),
                outcome_data.get('target_hit', 0),
                outcome_data.get('stop_loss_hit', 0),
                outcome_data.get('max_gain_pct'),
                outcome_data.get('max_loss_pct'),
                outcome_data.get('verdict'),
            ))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"[DB] ERROR upserting outcome: {e}")
        return False
    finally:
        conn.close()


# ============================================================
# ACCURACY METRICS
# ============================================================

def calculate_accuracy_metrics(metric_type='all_time'):
    """Calculate aggregate accuracy stats — delegates to unified_metrics."""
    from backend.lifecycle.unified_metrics import get_outcome_metrics
    metrics = get_outcome_metrics(metric_type)
    if not metrics or metrics.get('total_predictions', 0) == 0:
        return metrics

    conn = get_connection()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO accuracy_metrics (
                metric_date, metric_type,
                total_predictions, total_evaluated,
                wins, losses, neutral, pending,
                win_rate, avg_gain_pct, avg_loss_pct, profit_factor,
                opportunity_win_rate, risk_avoidance_rate,
                high_conf_win_rate, medium_conf_win_rate, low_conf_win_rate
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            metrics['metric_date'], metrics['metric_type'],
            metrics['total_predictions'], metrics['total_evaluated'],
            metrics['wins'], metrics['losses'], metrics['neutral'], metrics['pending'],
            metrics['win_rate'], metrics['avg_gain_pct'], metrics['avg_loss_pct'], metrics['profit_factor'],
            metrics['opportunity_win_rate'], metrics['risk_avoidance_rate'],
            metrics['high_conf_win_rate'], metrics['medium_conf_win_rate'], metrics['low_conf_win_rate'],
        ))
        conn.commit()
    finally:
        conn.close()
    return metrics


# ============================================================
# QUERY HELPERS (for GUI)
# ============================================================

def get_recent_predictions(limit=20):
    """Get most recent predictions"""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT p.*, o.verdict, o.change_1d_pct, o.change_7d_pct, o.max_gain_pct, o.max_loss_pct
            FROM predictions p
            LEFT JOIN outcomes o ON o.source_type='prediction' AND o.source_id=p.id
            ORDER BY p.created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_top_winners(limit=10):
    """Top winning predictions"""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT p.*, o.max_gain_pct, o.change_7d_pct, o.verdict
            FROM predictions p
            INNER JOIN outcomes o ON o.source_type='prediction' AND o.source_id=p.id
            WHERE o.verdict = 'WIN'
            ORDER BY o.max_gain_pct DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_top_losers(limit=10):
    """Top losing predictions (lessons learned)"""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT p.*, o.max_loss_pct, o.change_7d_pct, o.verdict
            FROM predictions p
            INNER JOIN outcomes o ON o.source_type='prediction' AND o.source_id=p.id
            WHERE o.verdict = 'LOSS' AND p.category='opportunity'
            ORDER BY o.max_loss_pct ASC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_db_stats():
    """Quick overview stats"""
    db_path = get_trading_db_path()
    conn = get_connection()
    try:
        stats = {}
        stats['total_predictions'] = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        stats['total_signals'] = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        stats['total_outcomes'] = conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
        stats['evaluated_outcomes'] = conn.execute("SELECT COUNT(*) FROM outcomes WHERE verdict != 'PENDING'").fetchone()[0]
        stats['db_size_kb'] = round(db_path.stat().st_size / 1024, 1) if db_path.exists() else 0
        return stats
    finally:
        conn.close()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("DB MANAGER v1 - Trading History Database")
    print("=" * 60)
    
    init_db()
    
    stats = get_db_stats()
    print(f"\nDatabase Stats:")
    print(f"  Path:                {DB_PATH}")
    print(f"  Size:                {stats['db_size_kb']} KB")
    print(f"  Predictions:         {stats['total_predictions']}")
    print(f"  Signals:             {stats['total_signals']}")
    print(f"  Outcomes:            {stats['total_outcomes']}")
    print(f"  Evaluated outcomes:  {stats['evaluated_outcomes']}")
    
    # Calculate metrics
    print(f"\n[INFO] Calculating accuracy metrics...")
    metrics = calculate_accuracy_metrics('all_time')
    if metrics and metrics['total_predictions'] > 0:
        print(f"\nAccuracy Metrics (all-time):")
        print(f"  Total predictions:   {metrics['total_predictions']}")
        print(f"  Evaluated:           {metrics['total_evaluated']}")
        print(f"  Win rate:            {metrics['win_rate']}%")
        print(f"  Avg gain (winners):  {metrics['avg_gain_pct']}%")
        print(f"  Avg loss (losers):   {metrics['avg_loss_pct']}%")
        print(f"  Profit factor:       {metrics['profit_factor']}")
    else:
        print(f"  No predictions yet — start running the analyzer!")
    
    print("=" * 60)