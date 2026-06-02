#!/usr/bin/env python3
"""
Seed canonical market memory with context snapshots from data/ JSON files.

Usage:
  python scripts/seed_market_context_memory.py [--dry-run] [--verbose]
"""

from __future__ import annotations

import argparse
import json
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

DATA_DIR = PROJECT_ROOT / "data"

REQUIRED_FILES = (
    "latest_market_data.json",
    "global_markets.json",
    "govt_intelligence.json",
    "india_next_open.json",
    "market_source_status.json",
    "analysis_state.json",
    "orchestrator_state.json",
)

OPTIONAL_FILES = (
    "live_news_feed.json",
    "news_feed.json",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_get(data: dict | None, *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _load_json_file(path: Path) -> dict | list | None:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except (OSError, json.JSONDecodeError):
        return None


def _collect_source_files(verbose: bool) -> tuple[list[str], dict[str, Any]]:
    files_used: list[str] = []
    sources: dict[str, Any] = {}

    for name in REQUIRED_FILES + OPTIONAL_FILES:
        path = DATA_DIR / name
        if not path.is_file():
            if verbose:
                print(f"[SEED_CONTEXT] missing {name}")
            continue
        parsed = _load_json_file(path)
        if parsed is None:
            if verbose:
                print(f"[SEED_CONTEXT] unreadable {name}")
            continue
        files_used.append(name)
        sources[name] = parsed
        if verbose:
            print(f"[SEED_CONTEXT] loaded {name}")

    return files_used, sources


def _extract_vix(sources: dict[str, Any]) -> float | None:
    candidates: list[Any] = [
        _safe_get(sources.get("global_markets.json"), "markets", "USA_INDICES", "VIX", "price"),
        _safe_get(sources.get("global_markets.json"), "markets", "USA_INDICES", "VIX", "latest_price"),
        _safe_get(sources.get("global_markets.json"), "flat_markets", "VIX", "price"),
        _safe_get(sources.get("global_markets.json"), "flat_markets", "VIX", "latest_price"),
    ]
    for value in candidates:
        parsed = _safe_float(value)
        if parsed is not None:
            return parsed
    return None


def _extract_crude(sources: dict[str, Any]) -> float | None:
    candidates: list[Any] = [
        _safe_get(sources.get("global_markets.json"), "markets", "GLOBAL_MACRO", "CRUDE_OIL", "price"),
        _safe_get(sources.get("global_markets.json"), "markets", "GLOBAL_MACRO", "CRUDE_OIL", "latest_price"),
        _safe_get(sources.get("global_markets.json"), "flat_markets", "CRUDE_OIL", "price"),
        _safe_get(sources.get("global_markets.json"), "flat_markets", "CRUDE_OIL", "latest_price"),
    ]
    for value in candidates:
        parsed = _safe_float(value)
        if parsed is not None:
            return parsed
    return None


def _extract_market_regime(sources: dict[str, Any]) -> str | None:
    candidates: list[Any] = [
        _safe_get(sources.get("analysis_state.json"), "last_regime"),
        _safe_get(sources.get("analysis_state.json"), "quality_metrics", "primary_regime"),
        _safe_get(sources.get("india_next_open.json"), "india_outlook"),
        _safe_get(sources.get("india_next_open.json"), "expected_gap_behavior"),
    ]
    for value in candidates:
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str, ensure_ascii=False)


def _extract_global_sentiment(sources: dict[str, Any]) -> str | None:
    candidates: list[Any] = [
        _safe_get(sources.get("global_markets.json"), "sentiment"),
        _safe_get(sources.get("india_next_open.json"), "global_sentiment"),
        _safe_get(sources.get("global_markets.json"), "sentiment", "global", "mood"),
    ]
    for value in candidates:
        text = _json_text(value)
        if text:
            return text
    return None


def _extract_india_sentiment(sources: dict[str, Any]) -> str | None:
    candidates: list[Any] = [
        {
            "india_outlook": _safe_get(sources.get("india_next_open.json"), "india_outlook"),
            "india_open_bias": _safe_get(sources.get("india_next_open.json"), "india_open_bias"),
            "india_avg_change": _safe_get(sources.get("analysis_state.json"), "metrics", "india_avg_change"),
        },
        _safe_get(sources.get("india_next_open.json"), "india_outlook"),
        _safe_get(sources.get("india_next_open.json"), "india_open_bias"),
    ]
    for value in candidates:
        if isinstance(value, dict):
            cleaned = {k: v for k, v in value.items() if v is not None}
            if cleaned:
                return _json_text(cleaned)
        text = _json_text(value)
        if text:
            return text
    return None


def _extract_fii_dii(sources: dict[str, Any]) -> str | None:
    for source_name, data in sources.items():
        if not isinstance(data, dict):
            continue
        for key in ("fii_dii", "fii", "dii", "fii_dii_flow"):
            if key in data and data[key] is not None:
                return _json_text(data[key])
    return None


def _extract_sector_strength(sources: dict[str, Any]) -> str | None:
    india = sources.get("india_next_open.json")
    if isinstance(india, dict):
        payload = {
            "bullish_sectors": _safe_get(india, "india_impact", "bullish_sectors")
            or _safe_get(india, "sectors_supported"),
            "risk_sectors": _safe_get(india, "india_impact", "risk_sectors")
            or _safe_get(india, "sectors_at_risk"),
            "sectors_affected": _safe_get(india, "india_impact", "sectors_affected"),
        }
        cleaned = {k: v for k, v in payload.items() if v}
        if cleaned:
            return _json_text(cleaned)
    return None


def build_snapshot_payload(files_used: list[str], sources: dict[str, Any]) -> dict[str, Any]:
    timestamp = _now_iso()
    market_regime = _extract_market_regime(sources)
    return {
        "timestamp": timestamp,
        "market_regime": market_regime,
        "vix": _extract_vix(sources),
        "crude": _extract_crude(sources),
        "fii_dii": _extract_fii_dii(sources),
        "global_sentiment": _extract_global_sentiment(sources),
        "india_sentiment": _extract_india_sentiment(sources),
        "sector_strength": _extract_sector_strength(sources),
        "raw_payload": {
            "files_used": files_used,
            "sources": sources,
        },
    }


def _print_snapshot_summary(payload: dict[str, Any], *, context_id: str | None = None) -> None:
    if context_id:
        print(f"[SEED_CONTEXT] context_id={context_id}")
    print(f"[SEED_CONTEXT] timestamp={payload.get('timestamp')}")
    print(f"[SEED_CONTEXT] market_regime={payload.get('market_regime')}")
    print(f"[SEED_CONTEXT] vix={payload.get('vix')}")
    print(f"[SEED_CONTEXT] crude={payload.get('crude')}")
    print(f"[SEED_CONTEXT] global_sentiment={payload.get('global_sentiment')}")
    print(f"[SEED_CONTEXT] india_sentiment={payload.get('india_sentiment')}")
    print(f"[SEED_CONTEXT] sector_strength={payload.get('sector_strength')}")
    print(f"[SEED_CONTEXT] fii_dii={payload.get('fii_dii')}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed market context snapshots from data/ JSON files"
    )
    parser.add_argument("--dry-run", action="store_true", help="Build snapshot without writing")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    from backend.storage.market_memory_db import (
        get_market_memory_path,
        get_market_memory_stats,
        init_market_memory_db,
        insert_market_context_snapshot,
    )

    print(f"[SEED_CONTEXT] data_dir={DATA_DIR}")
    print(f"[SEED_CONTEXT] target_db={get_market_memory_path()}")

    files_used, sources = _collect_source_files(args.verbose)
    print(f"[SEED_CONTEXT] files_found={len(files_used)}")
    print(f"[SEED_CONTEXT] files_used={json.dumps(files_used, default=str)}")

    if not files_used:
        print("[SEED_CONTEXT] no JSON source files found; nothing to seed")
        return 0

    if not init_market_memory_db():
        print("[SEED_CONTEXT] failed to initialize canonical market memory DB", file=sys.stderr)
        return 1

    payload = build_snapshot_payload(files_used, sources)

    if args.dry_run:
        print("[SEED_CONTEXT] would_insert=true")
        _print_snapshot_summary(payload)
        print("[SEED_CONTEXT] dry_run=True")
        return 0

    inserted_id = insert_market_context_snapshot(payload)
    if not inserted_id:
        print("[SEED_CONTEXT] insert failed", file=sys.stderr)
        return 1

    print("[SEED_CONTEXT] inserted=true")
    _print_snapshot_summary(payload, context_id=inserted_id)
    stats = get_market_memory_stats()
    print(f"[SEED_CONTEXT] stats={json.dumps(stats, default=str)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
