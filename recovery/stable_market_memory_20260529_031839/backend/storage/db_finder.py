"""
Shared database discovery for Railway and standalone environments.
"""

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from backend.utils.config import DATA_DIR, DB_PATH, IS_RAILWAY, PROJECT_ROOT

SKIP_PREFIXES = ('/proc', '/sys', '/dev')

KNOWN_DB_NAMES = ('trading_copilot.db', 'trading_history.db')

# Never treat market-memory DBs as the main trading/history database.
MARKET_MEMORY_DB_NAMES = frozenset({'canonical_market_memory.db'})
MARKET_MEMORY_NAME_FRAGMENTS = ('market_memory',)

_resolved_db_path = None


def is_market_memory_db_path(path: str | Path) -> bool:
    """True if path is canonical or other market-memory SQLite file."""
    name = Path(path).name.lower()
    if name in MARKET_MEMORY_DB_NAMES:
        return True
    return any(fragment in name for fragment in MARKET_MEMORY_NAME_FRAGMENTS)


def is_trading_predictions_schema(db_path: str | Path) -> bool:
    """
    True when predictions table matches trading_history layout (not market memory).
    Market memory uses prediction_id; trading history uses id + prediction_date.
    """
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='predictions'"
        )
        if not cur.fetchone():
            conn.close()
            return False
        cur.execute('PRAGMA table_info(predictions)')
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        if 'prediction_id' in cols and 'id' not in cols:
            return False
        if 'id' not in cols:
            return False
        if 'prediction_date' not in cols and 'created_at' not in cols:
            return False
        return True
    except Exception:
        return False


def _should_skip(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + os.sep) for prefix in SKIP_PREFIXES)


def find_all_db_files(start='/'):
    """Walk filesystem and return metadata for every .db file found."""
    results = []
    for root, dirs, files in os.walk(start, topdown=True, onerror=lambda _e: None):
        if _should_skip(root):
            dirs.clear()
            continue
        dirs[:] = [d for d in dirs if not _should_skip(os.path.join(root, d))]
        for filename in files:
            if not filename.endswith('.db'):
                continue
            filepath = os.path.join(root, filename)
            try:
                stat = os.stat(filepath)
                results.append({
                    'path': filepath,
                    'size_kb': round(stat.st_size / 1024, 1),
                    'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
            except OSError:
                continue
    return results


def _db_has_predictions_table(db_path: str):
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='predictions'")
        has_table = cur.fetchone() is not None
        count = 0
        if has_table:
            cur.execute('SELECT COUNT(*) FROM predictions')
            count = cur.fetchone()[0]
        conn.close()
        return has_table, count
    except Exception:
        return False, 0


def collect_db_candidates():
    """Build ordered list of DB paths to inspect."""
    candidates = []
    seen = set()

    for name in KNOWN_DB_NAMES:
        path = str(DATA_DIR / name)
        if path not in seen:
            candidates.append(path)
            seen.add(path)

    for extra in (
        '/app/data/trading_history.db',
        '/data/trading_history.db',
        '/app/data/trading_copilot.db',
        '/data/trading_copilot.db',
    ):
        if extra not in seen:
            candidates.append(extra)
            seen.add(extra)

    for entry in find_all_db_files(str(PROJECT_ROOT)):
        path = entry['path']
        if is_market_memory_db_path(path):
            continue
        if path not in seen:
            candidates.append(path)
            seen.add(path)

    if IS_RAILWAY:
        for entry in find_all_db_files('/'):
            path = entry['path']
            if is_market_memory_db_path(path):
                continue
            if path not in seen:
                candidates.append(path)
                seen.add(path)

    return candidates


def find_predictions_db():
    """
    Return (db_path, prediction_count) for the best DB containing predictions.
    Prefers the DB with the highest prediction count.
    """
    best_path = None
    best_count = 0

    for path in collect_db_candidates():
        if not os.path.exists(path):
            continue
        if is_market_memory_db_path(path):
            continue
        has_table, count = _db_has_predictions_table(path)
        if not has_table or count <= 0:
            continue
        if not is_trading_predictions_schema(path):
            continue
        if count > best_count:
            best_path = path
            best_count = count

    return best_path, best_count


def resolve_db_path():
    """
    Resolve and cache the active trading-history DB path (never market memory).
    Prefers data/trading_history.db; may pick a legacy trading DB with more rows.
    """
    global _resolved_db_path
    default = str(DB_PATH)

    if _resolved_db_path and os.path.exists(_resolved_db_path):
        if (
            not is_market_memory_db_path(_resolved_db_path)
            and is_trading_predictions_schema(_resolved_db_path)
        ):
            return _resolved_db_path
        _resolved_db_path = None

    if os.path.exists(default) and is_trading_predictions_schema(default):
        _resolved_db_path = default
        return default

    found, _count = find_predictions_db()
    if found and is_trading_predictions_schema(found):
        _resolved_db_path = found
        return found

    _resolved_db_path = default
    return default


def run_predictions_dedup(db_path: str):
    """Remove duplicate predictions, keeping earliest row per ticker+recommendation+date."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM predictions')
    before = cur.fetchone()[0]
    cur.execute("""
        DELETE FROM predictions
        WHERE rowid NOT IN (
            SELECT MIN(rowid) FROM predictions
            GROUP BY ticker, recommendation, prediction_date
        )
    """)
    conn.commit()
    cur.execute('SELECT COUNT(*) FROM predictions')
    after = cur.fetchone()[0]
    conn.close()
    return before, after, before - after
