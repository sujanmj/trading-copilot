"""
One-time and startup prediction state migration — canonical lifecycle backfill.

Migrates SQLite outcomes, JSON caches, and rebuilds history/stats exports.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pytz

from backend.lifecycle.lifecycle_rules import EXPIRE_AFTER_DAYS
from backend.lifecycle.prediction_reconciliation import (
    ACTIVE,
    EXPIRED,
    NEUTRALIZED,
    canonical_to_storage_verdict,
    is_legacy_storage_verdict,
    log_lifecycle_transition,
    normalize_canonical_state,
    reconcile_prediction_stats,
)
from backend.storage.db_manager import get_connection, init_db
from backend.utils.config import DATA_DIR

IST = pytz.timezone('Asia/Kolkata')

ACTIVE_PREDICTIONS_FILE = DATA_DIR / 'active_predictions.json'
PREDICTION_HISTORY_FILE = DATA_DIR / 'prediction_history.json'
ARCHIVE_FILE = DATA_DIR / 'expired_predictions_archive.json'
CALIBRATION_HISTORY_FILE = DATA_DIR / 'calibration_history.json'
RUNTIME_SNAPSHOT_FILE = DATA_DIR / 'cache' / 'runtime_snapshot.json'
HISTORY_DATA_FILE = DATA_DIR / 'history_data.json'
STATS_DATA_FILE = DATA_DIR / 'stats_data.json'

_JSON_STATE_KEYS = ('state', 'verdict', 'lifecycle_state', 'status')


def _ist_today() -> date:
    return datetime.now(IST).date()


def _parse_prediction_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()[:10]
    try:
        return datetime.strptime(text, '%Y-%m-%d').date()
    except ValueError:
        return None


def _prediction_age_days(prediction_date: Any, *, today: Optional[date] = None) -> int:
    pred = _parse_prediction_date(prediction_date)
    if pred is None:
        return 0
    ref = today or _ist_today()
    return max(0, (ref - pred).days)


def resolve_migrated_canonical(
    verdict: Optional[str],
    *,
    state: Optional[str] = None,
    prediction_date: Any = None,
    auto_expire: bool = True,
) -> str:
    """Canonical bucket after legacy mapping and optional ACTIVE age expiry."""
    canon = normalize_canonical_state(verdict, state=state)
    if auto_expire and canon == ACTIVE and prediction_date is not None:
        if _prediction_age_days(prediction_date) > EXPIRE_AFTER_DAYS:
            return EXPIRED
    return canon


def migrate_storage_verdict(
    verdict: Optional[str],
    *,
    state: Optional[str] = None,
    prediction_date: Any = None,
) -> str:
    """Target outcomes.verdict value for SQLite / JSON persistence."""
    canon = resolve_migrated_canonical(
        verdict, state=state, prediction_date=prediction_date, auto_expire=True,
    )
    return canonical_to_storage_verdict(canon)


def _load_json_records(path: Path) -> Tuple[List[dict], dict]:
    if not path.exists():
        return [], {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return [], {}
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)], {}
    if not isinstance(data, dict):
        return [], {}
    for key in ('predictions', 'entries', 'records', 'history'):
        block = data.get(key)
        if isinstance(block, list):
            return [r for r in block if isinstance(r, dict)], data
    return [], data


def _migrate_json_record(rec: dict, *, today: Optional[date] = None) -> bool:
    changed = False
    pred_date = rec.get('prediction_date') or rec.get('date')
    for key in _JSON_STATE_KEYS:
        if key not in rec:
            continue
        old = rec.get(key)
        if not isinstance(old, (str, type(None))):
            continue
        new = migrate_storage_verdict(old, prediction_date=pred_date)
        if key == 'state' and new == 'NEUTRAL':
            new_state = 'NEUTRALIZED'
        elif key == 'state':
            new_state = new
        else:
            new_state = new
        if str(old or '').upper() != str(new_state).upper():
            rec[key] = new_state
            changed = True
    return changed


def _migrate_json_tree(node: Any, *, updated: List[int]) -> None:
    if isinstance(node, dict):
        if any(k in node for k in _JSON_STATE_KEYS):
            if _migrate_json_record(node):
                updated[0] += 1
        for value in node.values():
            _migrate_json_tree(value, updated=updated)
    elif isinstance(node, list):
        for item in node:
            _migrate_json_tree(item, updated=updated)


def migrate_json_prediction_file(path: Path, *, dry_run: bool = False) -> Dict[str, int]:
    if not path.exists():
        return {'path': str(path), 'records': 0, 'updated': 0}
    try:
        wrapper = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {'path': str(path), 'records': 0, 'updated': 0, 'error': 'read_failed'}
    updated = [0]
    _migrate_json_tree(wrapper, updated=updated)
    records, _ = _load_json_records(path)
    if updated[0] and not dry_run:
        from backend.storage.json_io import atomic_write_json
        atomic_write_json(path, wrapper)
    return {'path': str(path), 'records': len(records), 'updated': updated[0]}


def migrate_sqlite_predictions(*, dry_run: bool = False) -> Dict[str, Any]:
    """Rewrite outcomes.verdict for all predictions using canonical mapping."""
    init_db()
    conn = get_connection()
    counts: Dict[str, int] = {
        'scanned': 0, 'updated': 0, 'inserted': 0, 'unchanged': 0, 'auto_expired': 0,
    }
    transitions: List[str] = []
    try:
        rows = conn.execute(
            """
            SELECT
                p.id AS prediction_id,
                p.prediction_date,
                p.ticker,
                o.id AS outcome_id,
                o.verdict
            FROM predictions p
            LEFT JOIN outcomes o ON o.source_type = 'prediction' AND o.source_id = p.id
            ORDER BY p.id
            """
        ).fetchall()
        for row in rows:
            counts['scanned'] += 1
            d = dict(row)
            old = d.get('verdict')
            old_canon = normalize_canonical_state(old)
            new_storage = migrate_storage_verdict(old, prediction_date=d.get('prediction_date'))
            new_canon = normalize_canonical_state(new_storage)
            if old_canon == ACTIVE and new_canon == EXPIRED:
                counts['auto_expired'] += 1
            if str(old or '').upper() == str(new_storage).upper():
                counts['unchanged'] += 1
                continue
            counts['updated'] += 1
            transitions.append(f"{d['prediction_id']}:{old}->{new_storage}")
            if dry_run:
                continue
            if d.get('outcome_id'):
                conn.execute(
                    "UPDATE outcomes SET verdict = ?, last_checked = CURRENT_TIMESTAMP WHERE id = ?",
                    (new_storage, d['outcome_id']),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO outcomes (
                        source_type, source_id, ticker, prediction_date, entry_price, verdict
                    )
                    SELECT 'prediction', p.id, p.ticker, p.prediction_date, p.entry_price, ?
                    FROM predictions p WHERE p.id = ?
                    """,
                    (new_storage, d['prediction_id']),
                )
                counts['inserted'] += 1
            log_lifecycle_transition(
                d['prediction_id'], str(old or 'NULL'), new_storage, resolution_reason='state_migration',
            )
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    counts['transitions_sample'] = transitions[:15]
    return counts


def detect_legacy_sqlite_states() -> bool:
    """True when any prediction outcome still uses a legacy verdict string."""
    init_db()
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM predictions p
            LEFT JOIN outcomes o ON o.source_type = 'prediction' AND o.source_id = p.id
            WHERE o.verdict IS NULL
               OR UPPER(o.verdict) IN (
                    'PENDING','UNRESOLVED','PARTIAL','STALE','ARCHIVED','TIMEOUT',
                    'UNKNOWN','INVALIDATED','INVALID','CANCELLED'
               )
               OR (
                    UPPER(o.verdict) = 'ACTIVE'
                    AND julianday('now') - julianday(p.prediction_date) > ?
               )
            """,
            (EXPIRE_AFTER_DAYS,),
        ).fetchone()
        return int(row['n'] if row else 0) > 0
    finally:
        conn.close()


def load_all_sqlite_prediction_rows() -> List[dict]:
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.prediction_date, p.ticker, o.verdict, o.verdict AS state
            FROM predictions p
            LEFT JOIN outcomes o ON o.source_type = 'prediction' AND o.source_id = p.id
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def print_migration_summary(records: Iterable[dict], *, label: str = 'all') -> Dict[str, Any]:
    stats = reconcile_prediction_stats(records, source=f'migration_{label}')
    print(
        f'[MIGRATION] wins={stats["wins"]} losses={stats["losses"]} '
        f'expired={stats["expired"]} neutralized={stats["neutralized"]} '
        f'active={stats["pending"]} total={stats["total"]}',
        flush=True,
    )
    return stats


def invalidate_timeline_caches() -> Dict[str, Any]:
    """
    Drop stale timeline / weekly aggregate snapshots so the next export rebuilds
    all windows from canonical SQLite prediction rows only.
    """
    removed: List[str] = []
    flag = DATA_DIR / '_runtime_cache_invalidate.flag'
    try:
        flag.write_text('timeline_rebuild', encoding='utf-8')
        removed.append(str(flag.name))
    except Exception as exc:
        print(f'[TIMELINE_REBUILD] cache flag write failed: {exc}', flush=True)

    for path in (HISTORY_DATA_FILE, STATS_DATA_FILE):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            data = None
        if not isinstance(data, dict):
            continue
        changed = False
        if path == HISTORY_DATA_FILE and isinstance(data.get('periods'), dict):
            data['periods'] = {}
            data.pop('export_manifest', None)
            changed = True
        if path == STATS_DATA_FILE:
            for key in ('metrics_weekly', 'metrics_daily', 'metrics_all_time'):
                if key in data:
                    data.pop(key, None)
                    changed = True
        if changed:
            from backend.storage.json_io import atomic_write_json
            atomic_write_json(path, data)
            removed.append(path.name)

    print(f'[TIMELINE_REBUILD] invalidated caches: {removed or ["none"]}', flush=True)
    return {'invalidated': removed}


def rebuild_exports() -> Dict[str, str]:
    """Regenerate history_data.json and stats_data.json from migrated SQLite."""
    paths: Dict[str, str] = {}
    invalidate_timeline_caches()
    from backend.history.history_engine import run_history_export
    from backend.storage.stats_exporter import export_stats

    run_history_export()
    paths['history'] = str(HISTORY_DATA_FILE)
    export_stats()
    paths['stats'] = str(STATS_DATA_FILE)
    return paths


def sync_lifecycle_json_from_sqlite() -> Dict[str, Any]:
    """Refresh active/history JSON mirrors via existing lifecycle sync."""
    from backend.lifecycle.prediction_lifecycle_engine import sync_prediction_json_files
    return sync_prediction_json_files()


def run_full_migration(*, dry_run: bool = False, rebuild: bool = True) -> Dict[str, Any]:
    """End-to-end migration: SQLite, JSON files, exports, reconciliation summary."""
    before = reconcile_prediction_stats(load_all_sqlite_prediction_rows(), source='before_migration')
    sqlite_result = migrate_sqlite_predictions(dry_run=dry_run)

    json_results = []
    for path in (
        ACTIVE_PREDICTIONS_FILE,
        PREDICTION_HISTORY_FILE,
        ARCHIVE_FILE,
        CALIBRATION_HISTORY_FILE,
        RUNTIME_SNAPSHOT_FILE,
    ):
        if path.exists():
            json_results.append(migrate_json_prediction_file(path, dry_run=dry_run))

    sync_result: Dict[str, Any] = {}
    export_paths: Dict[str, str] = {}
    if not dry_run:
        sync_result = sync_lifecycle_json_from_sqlite()
        if rebuild:
            export_paths = rebuild_exports()

    records = load_all_sqlite_prediction_rows()
    after = print_migration_summary(records, label='sqlite_all')

    from backend.storage.history_exporter import get_last_week_range, get_predictions_in_range
    lw_start, lw_end = get_last_week_range()
    lw_preds = get_predictions_in_range(lw_start, lw_end)
    lw_before = reconcile_prediction_stats(lw_preds, source='last_week_before')
    lw_after = print_migration_summary(lw_preds, label='last_week')

    return {
        'dry_run': dry_run,
        'before': before,
        'after': after,
        'sqlite': sqlite_result,
        'json_files': json_results,
        'sync': sync_result,
        'exports': export_paths,
        'last_week': {
            'range': (lw_start.isoformat(), lw_end.isoformat()),
            'before': lw_before,
            'after': lw_after,
        },
    }


def ensure_prediction_states_on_startup(*, force: bool = False) -> bool:
    """
    Lightweight startup guard — normalize legacy SQLite verdicts when detected.
    Called from history export path (not api/telegram/scheduler).
    """
    if not force and not detect_legacy_sqlite_states():
        return False
    print('[MIGRATION] legacy prediction states detected — running startup normalization', flush=True)
    migrate_sqlite_predictions(dry_run=False)
    try:
        sync_lifecycle_json_from_sqlite()
    except Exception as exc:
        print(f'[MIGRATION] lifecycle JSON sync skipped: {exc}', flush=True)
    records = load_all_sqlite_prediction_rows()
    print_migration_summary(records, label='startup_guard')
    return True
