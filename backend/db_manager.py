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

DB_PATH = Path(__file__).parent.parent / 'data' / 'trading_history.db'

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


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection():
    """Get a database connection"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row  # Allow dict-like access
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create all tables if they don't exist"""
    print(f"[DB] Initializing database at: {DB_PATH}")
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        print("[DB] Schema initialized successfully")
    except Exception as e:
        print(f"[DB] ERROR initializing: {e}")
    finally:
        conn.close()


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
                overall_conviction, raw_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        ))
        conn.commit()
        return cursor.lastrowid
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

def upsert_outcome(outcome_data):
    """Insert or update an outcome record"""
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
        print(f"[DB] ERROR upserting outcome: {e}")
        return False
    finally:
        conn.close()


# ============================================================
# ACCURACY METRICS
# ============================================================

def calculate_accuracy_metrics(metric_type='all_time'):
    """Calculate aggregate accuracy stats"""
    conn = get_connection()
    try:
        # Base query joining predictions with outcomes
        if metric_type == 'daily':
            date_filter = "AND p.prediction_date = date('now')"
        elif metric_type == 'weekly':
            date_filter = "AND p.prediction_date >= date('now', '-7 days')"
        else:  # all_time
            date_filter = ""
        
        query = f"""
            SELECT 
                COUNT(p.id) as total_predictions,
                COUNT(o.id) as total_evaluated,
                SUM(CASE WHEN o.verdict='WIN' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN o.verdict='LOSS' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN o.verdict='NEUTRAL' THEN 1 ELSE 0 END) as neutral,
                SUM(CASE WHEN o.verdict='PENDING' OR o.verdict IS NULL THEN 1 ELSE 0 END) as pending,
                AVG(CASE WHEN o.verdict='WIN' THEN o.max_gain_pct END) as avg_gain,
                AVG(CASE WHEN o.verdict='LOSS' THEN o.max_loss_pct END) as avg_loss,
                
                -- By category
                SUM(CASE WHEN p.category='opportunity' AND o.verdict='WIN' THEN 1 ELSE 0 END) as opp_wins,
                SUM(CASE WHEN p.category='opportunity' AND o.verdict IS NOT NULL THEN 1 ELSE 0 END) as opp_total,
                SUM(CASE WHEN p.category='risk' AND o.verdict='LOSS' THEN 1 ELSE 0 END) as risk_correct,
                SUM(CASE WHEN p.category='risk' AND o.verdict IS NOT NULL THEN 1 ELSE 0 END) as risk_total,
                
                -- By confidence
                SUM(CASE WHEN p.confidence='HIGH' AND o.verdict='WIN' THEN 1 ELSE 0 END) as high_wins,
                SUM(CASE WHEN p.confidence='HIGH' AND o.verdict IS NOT NULL THEN 1 ELSE 0 END) as high_total,
                SUM(CASE WHEN p.confidence='MEDIUM' AND o.verdict='WIN' THEN 1 ELSE 0 END) as med_wins,
                SUM(CASE WHEN p.confidence='MEDIUM' AND o.verdict IS NOT NULL THEN 1 ELSE 0 END) as med_total,
                SUM(CASE WHEN p.confidence='LOW' AND o.verdict='WIN' THEN 1 ELSE 0 END) as low_wins,
                SUM(CASE WHEN p.confidence='LOW' AND o.verdict IS NOT NULL THEN 1 ELSE 0 END) as low_total
            FROM predictions p
            LEFT JOIN outcomes o ON o.source_type='prediction' AND o.source_id=p.id
            WHERE 1=1 {date_filter}
        """
        
        row = conn.execute(query).fetchone()
        if not row:
            return None
        
        d = dict(row)
        evaluated = d['total_evaluated'] or 0
        wins = d['wins'] or 0
        losses = d['losses'] or 0
        
        # Calculate rates
        win_rate = (wins / evaluated * 100) if evaluated > 0 else 0
        opp_rate = (d['opp_wins'] / d['opp_total'] * 100) if d['opp_total'] else 0
        risk_rate = (d['risk_correct'] / d['risk_total'] * 100) if d['risk_total'] else 0
        high_conf = (d['high_wins'] / d['high_total'] * 100) if d['high_total'] else 0
        med_conf = (d['med_wins'] / d['med_total'] * 100) if d['med_total'] else 0
        low_conf = (d['low_wins'] / d['low_total'] * 100) if d['low_total'] else 0
        
        avg_gain = d['avg_gain'] or 0
        avg_loss = abs(d['avg_loss'] or 1)
        profit_factor = avg_gain / avg_loss if avg_loss > 0 else 0
        
        metrics = {
            'metric_date': datetime.now().date().isoformat(),
            'metric_type': metric_type,
            'total_predictions': d['total_predictions'] or 0,
            'total_evaluated': evaluated,
            'wins': wins,
            'losses': losses,
            'neutral': d['neutral'] or 0,
            'pending': d['pending'] or 0,
            'win_rate': round(win_rate, 2),
            'avg_gain_pct': round(avg_gain, 2),
            'avg_loss_pct': round(avg_loss, 2),
            'profit_factor': round(profit_factor, 2),
            'opportunity_win_rate': round(opp_rate, 2),
            'risk_avoidance_rate': round(risk_rate, 2),
            'high_conf_win_rate': round(high_conf, 2),
            'medium_conf_win_rate': round(med_conf, 2),
            'low_conf_win_rate': round(low_conf, 2),
        }
        
        # Save to DB
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
            metrics['high_conf_win_rate'], metrics['medium_conf_win_rate'], metrics['low_conf_win_rate']
        ))
        conn.commit()
        
        return metrics
    finally:
        conn.close()


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
    conn = get_connection()
    try:
        stats = {}
        stats['total_predictions'] = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        stats['total_signals'] = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        stats['total_outcomes'] = conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
        stats['evaluated_outcomes'] = conn.execute("SELECT COUNT(*) FROM outcomes WHERE verdict != 'PENDING'").fetchone()[0]
        stats['db_size_kb'] = round(DB_PATH.stat().st_size / 1024, 1) if DB_PATH.exists() else 0
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