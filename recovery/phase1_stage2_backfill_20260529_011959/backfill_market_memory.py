#!/usr/bin/env python3
"""
Backfill predictions/outcomes from trading_history.db into canonical_market_memory.db.

Usage:
  python scripts/backfill_market_memory.py [--dry-run] [--limit N] [--verbose]
  python scripts/backfill_market_memory.py --reset-test-data
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

FALLBACK_SOURCE = PROJECT_ROOT / "data" / "trading_history.db"

TICKER_KEYS = ("ticker", "symbol", "stock", "stock_symbol")
TIMESTAMP_KEYS = ("created_at", "timestamp", "prediction_date", "date")
SOURCE_KEYS = ("source", "run_type", "use_case", "origin")
DIRECTION_KEYS = ("recommendation", "direction", "action", "signal", "prediction")
SECTOR_KEYS = ("sector", "industry")
REASONING_KEYS = ("reasoning", "rationale", "explanation", "ai_reasoning", "notes")

BULLISH_TOKENS = frozenset(
    {"BUY", "STRONG_BUY", "ACCUMULATE", "LONG", "BULLISH", "UP", "POSITIVE"}
)
BEARISH_TOKENS = frozenset(
    {"SELL", "STRONG_SELL", "AVOID", "SHORT", "BEARISH", "DOWN", "NEGATIVE"}
)
NEUTRAL_TOKENS = frozenset({"HOLD", "WATCH", "NEUTRAL", "WAIT", "SIDEWAYS"})

CONFIDENCE_TEXT_MAP = {
    "HIGH": 0.8,
    "STRONG": 0.8,
    "MEDIUM": 0.55,
    "MODERATE": 0.55,
    "LOW": 0.3,
    "WEAK": 0.3,
}

SIGNAL_STACK_FIELDS = (
    "cross_validation",
    "signal_type",
    "prediction_horizon",
    "category",
    "recommendation",
    "target_price",
    "stop_loss",
    "current_price",
    "confidence",
    "entry_price",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def get_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}


def row_to_dict(row: Any) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return {}


def safe_get(row: dict, *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return default


def parse_json_maybe(value: Any) -> dict | list | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(parsed, (dict, list)):
        return parsed
    return None


def normalize_direction(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).strip().upper().replace(" ", "_").replace("-", "_")
    if not token:
        return None
    if token in BULLISH_TOKENS:
        return "BULLISH"
    if token in BEARISH_TOKENS:
        return "BEARISH"
    if token in NEUTRAL_TOKENS:
        return "NEUTRAL"
    for bullish in BULLISH_TOKENS:
        if bullish in token:
            return "BULLISH"
    for bearish in BEARISH_TOKENS:
        if bearish in token:
            return "BEARISH"
    for neutral in NEUTRAL_TOKENS:
        if neutral in token:
            return "NEUTRAL"
    return None


def normalize_confidence(value: Any) -> tuple[float | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, (int, float)):
        try:
            return float(value), None
        except (TypeError, ValueError):
            return None, None
    text = str(value).strip()
    if not text:
        return None, None
    try:
        return float(text), text
    except ValueError:
        pass
    label = text.upper()
    for key, score in CONFIDENCE_TEXT_MAP.items():
        if key in label:
            return score, text
    return None, text


def build_signal_stack(row_dict: dict) -> dict:
    stack: dict[str, Any] = {}
    raw = parse_json_maybe(safe_get(row_dict, "raw_data", "raw_payload"))
    raw_dict = raw if isinstance(raw, dict) else {}

    for field in SIGNAL_STACK_FIELDS:
        val = safe_get(row_dict, field)
        if val is None and raw_dict:
            val = raw_dict.get(field)
        if val is not None:
            stack[field] = val
    return stack


def resolve_source_path() -> Path:
    try:
        from backend.storage.db_finder import resolve_db_path

        resolved = Path(resolve_db_path())
        if resolved.exists():
            return resolved
    except Exception:
        pass
    return FALLBACK_SOURCE


def _first_present(row: dict, keys: tuple[str, ...]) -> Any:
    return safe_get(row, *keys)


def map_prediction_row(row: dict) -> dict | None:
    ticker = _first_present(row, TICKER_KEYS)
    if not ticker or not str(ticker).strip():
        return None

    legacy_id = safe_get(row, "id", "prediction_id")
    timestamp = _first_present(row, TIMESTAMP_KEYS) or _now_iso()
    source = _first_present(row, SOURCE_KEYS) or "internal_ai"
    direction = normalize_direction(_first_present(row, *DIRECTION_KEYS))

    confidence_val, confidence_label = normalize_confidence(safe_get(row, "confidence"))
    raw_data = parse_json_maybe(safe_get(row, "raw_data", "raw_payload"))
    market_regime = safe_get(row, "market_regime")
    if market_regime is None and isinstance(raw_data, dict):
        market_regime = raw_data.get("market_regime")

    payload: dict[str, Any] = {
        "legacy_prediction_id": legacy_id,
        "ticker": str(ticker).strip().upper(),
        "timestamp": str(timestamp),
        "source": str(source),
        "direction": direction,
        "confidence": confidence_val,
        "confidence_label": confidence_label,
        "market_regime": market_regime,
        "sector": _first_present(row, *SECTOR_KEYS),
        "reasoning": _first_present(row, *REASONING_KEYS),
        "signal_stack": build_signal_stack(row),
        "raw_payload": row,
    }
    return payload


def _holding_period_from_row(row: dict) -> str:
    explicit = safe_get(row, "holding_period")
    if explicit:
        return str(explicit)
    if safe_get(row, "price_7d", "change_7d_pct") is not None:
        return "7d"
    if safe_get(row, "price_5d", "change_5d_pct") is not None:
        return "5d"
    if safe_get(row, "price_3d", "change_3d_pct") is not None:
        return "3d"
    if safe_get(row, "price_1d", "change_1d_pct") is not None:
        return "1d"
    return "unknown"


def _resolve_outcome_prediction_id(row: dict) -> str | None:
    source_type = safe_get(row, "source_type")
    source_id = safe_get(row, "source_id")
    if source_id is not None and str(source_type or "").strip().lower() == "prediction":
        return f"legacy:{source_id}"

    prediction_id = safe_get(row, "prediction_id")
    if prediction_id is None:
        return None
    text = str(prediction_id).strip()
    if not text:
        return None
    if text.isdigit():
        return f"legacy:{text}"
    return text


def map_outcome_row(row: dict) -> dict | None:
    prediction_id = _resolve_outcome_prediction_id(row)
    if not prediction_id:
        return None

    actual_move = safe_get(
        row,
        "actual_move",
        "change_7d_pct",
        "change_5d_pct",
        "change_3d_pct",
        "change_1d_pct",
    )

    payload: dict[str, Any] = {
        "prediction_id": prediction_id,
        "actual_move": actual_move,
        "high": safe_get(row, "high", "max_gain_pct", "highest_gain_pct"),
        "low": safe_get(row, "low", "max_loss_pct", "lowest_loss_pct"),
        "expiry_result": safe_get(row, "expiry_result", "result"),
        "resolved_as": safe_get(row, "resolved_as", "verdict", "status", "outcome"),
        "holding_period": _holding_period_from_row(row),
        "market_context": safe_get(row, "market_context"),
        "vix": safe_get(row, "vix"),
        "crude": safe_get(row, "crude"),
        "fii_dii": safe_get(row, "fii_dii"),
        "global_sentiment": safe_get(row, "global_sentiment"),
        "india_sentiment": safe_get(row, "india_sentiment"),
        "sector_strength": safe_get(row, "sector_strength"),
        "market_regime": safe_get(row, "market_regime"),
        "raw_payload": row,
    }
    return payload


def fetch_rows(
    conn: sqlite3.Connection,
    table: str,
    limit: int | None,
) -> list[dict]:
    if not table_exists(conn, table):
        return []
    query = f"SELECT * FROM {table}"
    if limit is not None:
        query += f" LIMIT {int(limit)}"
    conn.row_factory = sqlite3.Row
    return [row_to_dict(row) for row in conn.execute(query).fetchall()]


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    if not table_exists(conn, table):
        return 0
    row = conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()
    return int(row[0]) if row else 0


def reset_test_data(verbose: bool) -> None:
    from backend.storage.market_memory_db import get_connection

    conn = get_connection()
    try:
        conn.execute("DELETE FROM outcomes WHERE prediction_id IN (SELECT prediction_id FROM predictions WHERE ticker = ?)", ("__TEST__",))
        conn.execute("DELETE FROM broker_predictions WHERE ticker = ?", ("__TEST__",))
        conn.execute("DELETE FROM predictions WHERE ticker = ?", ("__TEST__",))
        conn.execute("DELETE FROM predictions WHERE source = ?", ("validate",))
        conn.commit()
        if verbose:
            print("[BACKFILL] reset-test-data: removed __TEST__ and validate rows")
    finally:
        conn.close()


def process_predictions(
    rows: list[dict],
    *,
    dry_run: bool,
    verbose: bool,
    upsert_prediction,
    make_prediction_id,
) -> tuple[int, int]:
    would_write = 0
    written = 0
    skipped = 0

    for row in rows:
        payload = map_prediction_row(row)
        if payload is None:
            skipped += 1
            if verbose:
                print("[BACKFILL] skip prediction: missing ticker", row.get("id"))
            continue

        prediction_id = make_prediction_id(payload)
        payload["prediction_id"] = prediction_id

        if dry_run:
            would_write += 1
            if verbose:
                print(f"[BACKFILL] would upsert prediction {prediction_id} {payload.get('ticker')}")
            continue

        result = upsert_prediction(payload)
        if result:
            written += 1
            if verbose:
                print(f"[BACKFILL] wrote prediction {result}")
        else:
            skipped += 1
            if verbose:
                print(f"[BACKFILL] failed prediction {prediction_id}")

    return would_write, written, skipped


def process_outcomes(
    rows: list[dict],
    *,
    dry_run: bool,
    verbose: bool,
    upsert_outcome,
) -> tuple[int, int, int]:
    would_write = 0
    written = 0
    skipped = 0

    for row in rows:
        payload = map_outcome_row(row)
        if payload is None:
            skipped += 1
            if verbose:
                print("[BACKFILL] skip outcome: no prediction_id link", row.get("id"))
            continue

        if dry_run:
            would_write += 1
            if verbose:
                print(
                    f"[BACKFILL] would upsert outcome {payload['prediction_id']} "
                    f"period={payload['holding_period']}"
                )
            continue

        if upsert_outcome(payload):
            written += 1
            if verbose:
                print(
                    f"[BACKFILL] wrote outcome {payload['prediction_id']} "
                    f"period={payload['holding_period']}"
                )
        else:
            skipped += 1
            if verbose:
                print(
                    f"[BACKFILL] failed outcome {payload['prediction_id']} "
                    f"period={payload['holding_period']}"
                )

    return would_write, written, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill canonical market memory DB")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    parser.add_argument("--limit", type=int, default=None, help="Max rows per table to process")
    parser.add_argument(
        "--reset-test-data",
        action="store_true",
        default=False,
        help="Remove validate/__TEST__ rows from canonical DB before backfill",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose per-row logging")
    args = parser.parse_args()

    from backend.storage.market_memory_db import (
        get_market_memory_path,
        get_market_memory_stats,
        init_market_memory_db,
        make_prediction_id,
        upsert_outcome,
        upsert_prediction,
    )

    source_path = resolve_source_path()
    target_path = get_market_memory_path()

    if not source_path.exists():
        print(f"[BACKFILL] source_db missing: {source_path}", file=sys.stderr)
        return 1

    if not init_market_memory_db():
        print("[BACKFILL] failed to initialize canonical market memory DB", file=sys.stderr)
        return 1

    if args.reset_test_data and not args.dry_run:
        reset_test_data(args.verbose)

    src_conn = sqlite3.connect(str(source_path))
    try:
        predictions_found = count_rows(src_conn, "predictions")
        outcomes_found = count_rows(src_conn, "outcomes")

        pred_rows = fetch_rows(src_conn, "predictions", args.limit)
        out_rows = fetch_rows(src_conn, "outcomes", args.limit)
    finally:
        src_conn.close()

    print(f"[BACKFILL] source_db={source_path}")
    print(f"[BACKFILL] target_db={target_path}")
    print(f"[BACKFILL] predictions_found={predictions_found}")
    print(f"[BACKFILL] outcomes_found={outcomes_found}")

    pred_would, pred_written, pred_skipped = process_predictions(
        pred_rows,
        dry_run=args.dry_run,
        verbose=args.verbose,
        upsert_prediction=upsert_prediction,
        make_prediction_id=make_prediction_id,
    )
    out_would, out_written, out_skipped = process_outcomes(
        out_rows,
        dry_run=args.dry_run,
        verbose=args.verbose,
        upsert_outcome=upsert_outcome,
    )

    if args.dry_run:
        print(f"[BACKFILL] predictions_would_write={pred_would}")
        print(f"[BACKFILL] outcomes_would_write={out_would}")
        print("[BACKFILL] dry_run=True")
        return 0

    print(f"[BACKFILL] predictions_written={pred_written}")
    print(f"[BACKFILL] predictions_skipped={pred_skipped}")
    print(f"[BACKFILL] outcomes_written={out_written}")
    print(f"[BACKFILL] outcomes_skipped={out_skipped}")
    stats = get_market_memory_stats()
    print(f"[BACKFILL] stats={json.dumps(stats, default=str)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
