"""
Auto-capture active_predictions from runtime/active snapshots into canonical_market_memory.db.

Non-fatal; gated by ENABLE_MARKET_MEMORY_AUTO_CAPTURE. Hooks run only on snapshot write paths.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from backend.storage.market_memory_capture import capture_predictions
from backend.storage.market_memory_db import init_market_memory_db
from backend.storage.runtime_snapshot_capture import (
    SOURCE_HINT,
    apply_snapshot_timestamps,
    extract_runtime_snapshot_predictions,
    extract_snapshot_published_at,
)
from backend.utils.config import DATA_DIR, ENABLE_MARKET_MEMORY_AUTO_CAPTURE

ACTIVE_PREDICTIONS_FILE = DATA_DIR / 'active_predictions.json'
ACTIVE_SNAPSHOT_FILE = DATA_DIR / 'active_snapshot.json'


def _empty_summary(*, ok: bool = True, disabled: bool = False) -> dict:
    out = {
        'ok': ok,
        'candidates_found': 0,
        'captured': 0,
        'skipped': 0,
        'failed': 0,
    }
    if disabled:
        out['disabled'] = True
    return out


def _load_json_dict(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_file_snapshot() -> dict:
    try:
        from backend.intelligence.active_snapshot import load_active_snapshot

        snap = load_active_snapshot()
        return snap if isinstance(snap, dict) else {}
    except Exception:
        return _load_json_dict(ACTIVE_SNAPSHOT_FILE)


def assemble_capture_snapshot(
    *,
    file_snapshot: dict | None = None,
    active_predictions: dict | None = None,
) -> dict:
    """Build runtime-snapshot-shaped dict for extraction (exports/data paths)."""
    ap = active_predictions if isinstance(active_predictions, dict) else _load_json_dict(
        ACTIVE_PREDICTIONS_FILE
    )
    fs = file_snapshot if isinstance(file_snapshot, dict) else _load_file_snapshot()
    published_at = (
        fs.get('published_at')
        or fs.get('intelligence_timestamp')
        or fs.get('generated_at')
    )
    return {
        'data': {'active_predictions': ap},
        'exports': {'active_predictions': ap},
        'snapshot_published_at': published_at,
        'published_at': published_at,
        'generated_at': published_at,
    }


def capture_active_predictions_from_snapshot(
    snapshot: dict,
    source_name: str = 'runtime_snapshot_auto',
) -> dict:
    """
    Extract and upsert active predictions from a snapshot payload.

    Returns summary: ok, candidates_found, captured, skipped, failed.
    """
    if not ENABLE_MARKET_MEMORY_AUTO_CAPTURE:
        return _empty_summary(disabled=True)

    if not isinstance(snapshot, dict):
        return _empty_summary(ok=False)

    try:
        file_snapshot = _load_file_snapshot()
        candidates, candidate_source = extract_runtime_snapshot_predictions(
            snapshot,
            file_snapshot=file_snapshot,
        )
        snapshot_ts = extract_snapshot_published_at(snapshot) or extract_snapshot_published_at(
            file_snapshot
        )
        prepared = apply_snapshot_timestamps(candidates, snapshot_ts)

        candidates_found = len(candidates)
        if not prepared:
            summary = _empty_summary()
            summary['candidate_source'] = candidate_source
            summary['capture_source'] = source_name
            return summary

        if not init_market_memory_db():
            summary = _empty_summary(ok=False)
            summary['error'] = 'init_market_memory_db failed'
            return summary

        batch = capture_predictions(prepared, source_hint=SOURCE_HINT)
        captured = int(batch.get('captured') or 0)
        skipped = int(batch.get('skipped') or 0)
        attempted = int(batch.get('attempted') or 0)
        failed = max(0, attempted - captured - skipped)

        return {
            'ok': True,
            'candidates_found': candidates_found,
            'captured': captured,
            'skipped': skipped,
            'failed': failed,
            'candidate_source': candidate_source,
            'capture_source': source_name,
        }
    except Exception as exc:
        print(f'[MARKET_MEMORY_AUTO] non-fatal error ({source_name}): {exc}', file=sys.stderr)
        return {
            'ok': False,
            'candidates_found': 0,
            'captured': 0,
            'skipped': 0,
            'failed': 0,
            'error': str(exc)[:200],
            'capture_source': source_name,
        }


def capture_active_predictions_from_file(path: str | Path) -> dict:
    """Load JSON snapshot from disk and capture active predictions."""
    p = Path(path)
    if not p.is_file():
        return {**_empty_summary(ok=False), 'error': 'missing file', 'path': str(p)}
    try:
        payload = json.loads(p.read_text(encoding='utf-8'))
    except Exception as exc:
        return {**_empty_summary(ok=False), 'error': str(exc)[:200], 'path': str(p)}
    if not isinstance(payload, dict):
        return {**_empty_summary(ok=False), 'error': 'invalid JSON object', 'path': str(p)}
    return capture_active_predictions_from_snapshot(
        payload,
        source_name=f'file:{p.name}',
    )


def capture_after_snapshot_publish(
    *,
    file_snapshot: dict | None = None,
    source_name: str = 'snapshot_export',
) -> dict:
    """Convenience entry for post-write hooks — assembles disk state then captures."""
    snapshot = assemble_capture_snapshot(file_snapshot=file_snapshot)
    return capture_active_predictions_from_snapshot(snapshot, source_name=source_name)
