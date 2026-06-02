"""
Unified read-only dashboard payload for canonical market memory.

Combines stats, learning, advisor batch, price coverage, and outcome audit.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from backend.analytics.market_memory_advisor import get_advisor_batch_report
from backend.analytics.market_memory_learning import get_learning_summary
from backend.storage.market_memory_db import get_connection, get_market_memory_stats, init_market_memory_db
from backend.storage.market_memory_outcomes import load_latest_market_data
from backend.utils.config import DATA_DIR

DEFAULT_DASHBOARD_PRICE_FILE = DATA_DIR / 'latest_market_data_memory_enriched.json'

_PRICE_COVERAGE_KEYS = (
    'missing_price_context',
    'missing_latest_price',
    'suspicious_price_scale',
    'eligible_unresolved',
)

_audit_price_coverage_mod: Any | None = None


def _load_audit_price_coverage_module() -> Any:
    global _audit_price_coverage_mod
    if _audit_price_coverage_mod is not None:
        return _audit_price_coverage_mod

    audit_path = Path(__file__).resolve().parents[2] / 'scripts' / 'audit_price_coverage.py'
    spec = importlib.util.spec_from_file_location('_audit_price_coverage', audit_path)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot load audit module from {audit_path}')

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _audit_price_coverage_mod = module
    return module


def _get_price_coverage_summary(price_file: Path) -> dict[str, Any]:
    """Return compact price coverage counts (read-only)."""
    summary: dict[str, Any] = {
        'price_file': str(price_file),
        'symbols': 0,
        'missing_latest_price': 0,
        'missing_price_context': 0,
        'suspicious_price_scale': 0,
        'eligible_unresolved': 0,
    }

    market_data = load_latest_market_data(price_file)
    if not market_data:
        return summary

    audit_mod = _load_audit_price_coverage_module()
    structure = audit_mod.describe_market_data(market_data)
    summary['symbols'] = int(structure.get('price_symbol_count') or 0)

    predictions = audit_mod.fetch_predictions()
    counts = {key: 0 for key in _PRICE_COVERAGE_KEYS}
    for prediction in predictions:
        record = audit_mod.classify_prediction(prediction, market_data)
        classification = record.get('classification')
        if classification in counts:
            counts[classification] += 1

    summary.update(counts)
    return summary


def _get_outcome_audit_summary() -> dict[str, Any]:
    """Return outcome audit counts from price-resolved rows (read-only)."""
    from backend.storage.price_outcome_sanity import fetch_price_outcomes

    init_market_memory_db()
    conn = get_connection()
    try:
        conn.execute('PRAGMA query_only = ON')
        rows = fetch_price_outcomes(conn)
    finally:
        conn.close()

    anomaly_ids = {
        row['prediction_id']
        for row in rows
        if row.get('anomalies')
    }
    return {
        'outcomes_checked': len(rows),
        'anomalies': len(anomaly_ids),
    }


def _fetch_latest_predictions(limit: int) -> list[dict[str, Any]]:
    init_market_memory_db()
    stats = get_market_memory_stats()
    if not stats.get('db_exists'):
        return []

    conn = get_connection()
    try:
        conn.execute('PRAGMA query_only = ON')
        rows = conn.execute(
            """
            SELECT prediction_id, ticker, timestamp, source, direction,
                   confidence, confidence_label, market_regime, sector
            FROM predictions
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (max(0, int(limit)),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _fetch_latest_outcomes(limit: int) -> list[dict[str, Any]]:
    init_market_memory_db()
    stats = get_market_memory_stats()
    if not stats.get('db_exists'):
        return []

    conn = get_connection()
    try:
        conn.execute('PRAGMA query_only = ON')
        rows = conn.execute(
            """
            SELECT o.prediction_id, p.ticker, o.resolved_as, o.expiry_result,
                   o.actual_move, o.holding_period, o.created_at
            FROM outcomes o
            LEFT JOIN predictions p ON p.prediction_id = o.prediction_id
            ORDER BY o.created_at DESC
            LIMIT ?
            """,
            (max(0, int(limit)),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _collect_warnings(
    *,
    raw_stats: dict[str, Any],
    learning: dict[str, Any],
    price_coverage: dict[str, Any],
    outcome_audit: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []

    if not raw_stats.get('db_exists'):
        warnings.append('db_missing')

    price_path = Path(str(price_coverage.get('price_file') or ''))
    if not price_path.exists() or not load_latest_market_data(price_path):
        warnings.append('price_file_missing_or_invalid')

    overall = learning.get('overall') if isinstance(learning.get('overall'), dict) else {}
    for item in overall.get('warnings') or []:
        token = str(item).strip()
        if token and token not in warnings:
            warnings.append(token)

    if int(outcome_audit.get('anomalies') or 0) > 0:
        warnings.append('outcome_audit_anomalies')

    if int(price_coverage.get('suspicious_price_scale') or 0) > 0:
        warnings.append('suspicious_price_scale_detected')

    return warnings


def get_market_memory_dashboard(
    limit: int = 50,
    price_file: str | Path | None = None,
) -> dict[str, Any]:
    """Build unified read-only dashboard payload for market memory."""
    init_market_memory_db()
    raw_stats = get_market_memory_stats()
    stats = {
        'predictions': int(raw_stats.get('predictions') or 0),
        'outcomes': int(raw_stats.get('outcomes') or 0),
        'broker_predictions': int(raw_stats.get('broker_predictions') or 0),
        'context_snapshots': int(raw_stats.get('market_context_snapshots') or 0),
    }

    learning = get_learning_summary()

    advisor_report = get_advisor_batch_report(limit=limit)
    advisor = {
        'checked': int(advisor_report.get('checked') or 0),
        'boost': int(advisor_report.get('boost') or 0),
        'neutral': int(advisor_report.get('neutral') or 0),
        'caution': int(advisor_report.get('caution') or 0),
        'avoid_candidate': int(advisor_report.get('avoid_candidate') or 0),
        'shadow_mode': bool(advisor_report.get('shadow_mode')),
    }

    price_path = Path(price_file) if price_file is not None else DEFAULT_DASHBOARD_PRICE_FILE
    price_coverage = _get_price_coverage_summary(price_path)
    outcome_audit = _get_outcome_audit_summary()

    latest_predictions = _fetch_latest_predictions(limit)
    latest_outcomes = _fetch_latest_outcomes(limit)
    warnings = _collect_warnings(
        raw_stats=raw_stats,
        learning=learning,
        price_coverage=price_coverage,
        outcome_audit=outcome_audit,
    )

    return {
        'ok': True,
        'stats': stats,
        'learning': learning,
        'advisor': advisor,
        'price_coverage': price_coverage,
        'outcome_audit': outcome_audit,
        'latest_predictions': latest_predictions,
        'latest_outcomes': latest_outcomes,
        'warnings': warnings,
    }
