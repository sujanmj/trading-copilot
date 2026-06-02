#!/usr/bin/env python3
"""
Safe manual post-market / EOD catch-up without faking predictions or outcomes.

Reuses existing local export, outcome, and market-memory paths only.
Does not call Telegram, place trades, or run full scheduler/collector cycles.

Usage:
  python scripts/post_market_catchup.py [--dry-run] [--skip-eod] [--capture-only] [--limit N]
"""

from __future__ import annotations

import argparse
import importlib
import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pytz

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

IST = pytz.timezone('Asia/Kolkata')

StepFn = Callable[[], Any]


def _now_ist() -> str:
    return datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')


def _memory_counts() -> tuple[int, int]:
    from backend.storage.market_memory_db import get_market_memory_stats, init_market_memory_db

    init_market_memory_db()
    stats = get_market_memory_stats()
    return int(stats.get('predictions') or 0), int(stats.get('outcomes') or 0)


def validate_db_routing() -> tuple[bool, str]:
    """Run validate_db_routing.main(); return (ok, detail)."""
    try:
        import scripts.validate_db_routing as vdr
    except Exception as exc:
        return False, f'import failed: {exc}'

    buf = io.StringIO()
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            code = int(vdr.main())
    except SystemExit as exc:
        code = int(exc.code) if exc.code is not None else 1
    except Exception as exc:
        return False, str(exc)

    output = buf.getvalue()
    if code == 0 and 'DB_ROUTING_OK' in output:
        return True, 'ok'
    detail = output.strip().splitlines()[-1] if output.strip() else f'exit={code}'
    return False, detail


def _try_import_callable(module: str, attr: str) -> tuple[StepFn | None, str | None]:
    try:
        mod = importlib.import_module(module)
        fn = getattr(mod, attr, None)
        if fn is None or not callable(fn):
            return None, f'{module}.{attr} not callable'
        return fn, None
    except Exception as exc:
        return None, str(exc)


def _outcome_tracker_via_runner() -> StepFn:
    def _run() -> Any:
        from backend.utils.runner import run_script

        proc = run_script('outcome_tracker.py', check=False)
        if proc.returncode != 0:
            raise RuntimeError(f'outcome_tracker.py exited {proc.returncode}')
        return proc

    return _run


def discover_eod_steps() -> tuple[dict[str, StepFn], dict[str, str]]:
    """
    Detect safe post-market step callables (individual exports — not full EOD pipeline).

    Full run_end_of_day_cycle is detected but intentionally excluded (Telegram/collectors).
    """
    available: dict[str, StepFn] = {}
    skipped: dict[str, str] = {}

    specs: list[tuple[str, str, str, Callable[[StepFn], StepFn] | None]] = [
        (
            'outcome_tracker',
            'backend.analyzers.outcome_tracker',
            'evaluate_pending_outcomes',
            lambda fn: (lambda: fn(verbose=False)),
        ),
        ('stats_export', 'backend.storage.stats_exporter', 'export_stats', None),
        ('history_export', 'backend.storage.history_exporter', 'export_history', None),
        (
            'calibration_export',
            'backend.lifecycle.prediction_lifecycle_engine',
            'build_calibration_snapshot',
            None,
        ),
        (
            'snapshot_export',
            'backend.runtime.snapshot_orchestrator',
            'run_snapshot_cycle',
            lambda fn: (lambda: fn(trigger='post_market_catchup', force_refresh=False)),
        ),
    ]

    for name, module, attr, wrapper in specs:
        fn, err = _try_import_callable(module, attr)
        if fn is None and name == 'outcome_tracker':
            available[name] = _outcome_tracker_via_runner()
            print(
                f'[POST_MARKET_CATCHUP] wired {name} via runner '
                f'(direct import failed: {err})'
            )
            continue
        if fn is None:
            skipped[name] = err or 'unavailable'
            continue
        available[name] = wrapper(fn) if wrapper else fn

    eod_fn, eod_err = _try_import_callable(
        'backend.lifecycle.prediction_lifecycle_engine',
        'run_end_of_day_cycle',
    )
    if eod_fn is None:
        skipped['eod_lifecycle'] = eod_err or 'run_end_of_day_cycle unavailable'
    else:
        skipped['eod_lifecycle'] = (
            'full pipeline excluded (Telegram/collectors); use individual steps above'
        )

    return available, skipped


def _run_optional_step(name: str, fn: StepFn, *, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        print(f'[POST_MARKET_CATCHUP] dry-run skip write: {name}')
        return {'name': name, 'status': 'dry_run_skipped'}

    try:
        result = fn()
        print(f'[POST_MARKET_CATCHUP] step ok: {name}')
        return {'name': name, 'status': 'ok', 'result': result}
    except Exception as exc:
        print(f'[POST_MARKET_CATCHUP] step failed: {name} error={exc}', file=sys.stderr)
        return {'name': name, 'status': 'error', 'error': str(exc)}


def _run_memory_capture(*, limit: int, dry_run: bool) -> dict[str, Any]:
    from backend.storage.market_memory_capture import capture_predictions, normalize_prediction_payload
    from backend.storage.market_memory_db import init_market_memory_db
    from backend.storage.runtime_snapshot_capture import (
        SOURCE_HINT,
        apply_snapshot_timestamps,
        extract_runtime_snapshot_predictions,
        extract_snapshot_published_at,
    )
    from scripts.capture_runtime_snapshot_predictions import (
        _count_normalizable,
        _load_api_key,
        _load_json_file,
        _maybe_upgrade_to_cache_snapshot,
        _resolve_snapshots,
        _sample_tickers,
    )

    try:
        from backend.utils.config import RUNTIME_SNAPSHOT_CACHE
    except Exception:
        RUNTIME_SNAPSHOT_CACHE = PROJECT_ROOT / 'data' / 'cache' / 'runtime_snapshot.json'

    api_key = _load_api_key()
    try:
        api_snapshot, file_snapshot, load_source = _resolve_snapshots('auto', api_key)
    except RuntimeError as exc:
        return {'status': 'error', 'error': str(exc)}

    candidates, candidate_source = extract_runtime_snapshot_predictions(
        api_snapshot,
        file_snapshot=file_snapshot,
    )
    api_snapshot, load_source, candidates, candidate_source = _maybe_upgrade_to_cache_snapshot(
        api_snapshot,
        file_snapshot,
        load_source,
        candidates,
        candidate_source,
    )
    if candidate_source is None:
        candidate_source = 'none'

    snapshot_for_ts = api_snapshot or file_snapshot or {}
    snapshot_ts = extract_snapshot_published_at(snapshot_for_ts)
    prepared = apply_snapshot_timestamps(candidates, snapshot_ts)
    if limit > 0:
        prepared = prepared[:limit]

    source_label = f'{load_source}:{candidate_source}'
    normalizable = _count_normalizable(prepared)
    if normalizable == 0:
        cache_snapshot, _cache_err = _load_json_file(Path(RUNTIME_SNAPSHOT_CACHE))
        if cache_snapshot is not None:
            cache_candidates, cache_source = extract_runtime_snapshot_predictions(
                cache_snapshot,
                file_snapshot=file_snapshot,
            )
            if cache_candidates:
                cache_ts = extract_snapshot_published_at(cache_snapshot) or snapshot_ts
                cache_prepared = apply_snapshot_timestamps(cache_candidates, cache_ts)
                if limit > 0:
                    cache_prepared = cache_prepared[:limit]
                if _count_normalizable(cache_prepared) > 0:
                    prepared = cache_prepared
                    candidates = cache_candidates
                    source_label = f'file:cache/runtime_snapshot.json:{cache_source}'
                    normalizable = _count_normalizable(prepared)

    sample = _sample_tickers(prepared)

    if dry_run:
        would_capture = normalizable
        print(
            f'[POST_MARKET_CATCHUP] memory_capture dry-run source={source_label} '
            f'candidates={len(candidates)} would_capture={would_capture} sample={sample}'
        )
        return {
            'status': 'dry_run',
            'source': source_label,
            'candidates_found': len(candidates),
            'would_capture': would_capture,
            'sample_tickers': sample,
        }

    if not init_market_memory_db():
        return {'status': 'error', 'error': 'init_market_memory_db failed'}

    summary = capture_predictions(prepared, source_hint=SOURCE_HINT)
    captured = int(summary.get('captured') or 0)
    skipped = int(summary.get('skipped') or 0)
    print(
        f'[POST_MARKET_CATCHUP] memory_capture source={source_label} '
        f'captured={captured} skipped={skipped}'
    )
    return {
        'status': 'ok',
        'source': source_label,
        'candidates_found': len(candidates),
        'captured': captured,
        'skipped': skipped,
        'summary': summary,
    }


def _run_payload_outcomes(*, limit: int, dry_run: bool) -> dict[str, Any]:
    from backend.storage.market_memory_db import init_market_memory_db
    from backend.storage.market_memory_outcomes import resolve_outcomes_from_payloads

    if not init_market_memory_db():
        return {'status': 'error', 'error': 'init_market_memory_db failed'}

    summary = resolve_outcomes_from_payloads(
        limit=limit,
        dry_run=dry_run,
        verbose=False,
    )
    print(
        f'[POST_MARKET_CATCHUP] payload_outcomes checked={summary.get("predictions_checked", 0)} '
        f'resolved={summary.get("resolved", 0)} written={summary.get("written", 0)} '
        f'dry_run={dry_run}'
    )
    return {'status': 'dry_run' if dry_run else 'ok', 'summary': summary}


def run_catchup(
    *,
    dry_run: bool = False,
    skip_eod: bool = False,
    capture_only: bool = False,
    limit: int = 500,
) -> int:
    print(f'[POST_MARKET_CATCHUP] ist_now={_now_ist()}')

    routing_ok, routing_detail = validate_db_routing()
    if not routing_ok:
        print(f'[POST_MARKET_CATCHUP] db_routing=fail detail={routing_detail}', file=sys.stderr)
        return 1
    print('[POST_MARKET_CATCHUP] db_routing=ok')

    available, skipped = discover_eod_steps()
    for name, reason in sorted(skipped.items()):
        print(f'[POST_MARKET_CATCHUP] skipped detect: {name} reason={reason}')

    preds_before, outcomes_before = _memory_counts()
    steps_run: list[str] = []

    if not capture_only and not skip_eod:
        for name in (
            'outcome_tracker',
            'stats_export',
            'history_export',
            'calibration_export',
            'snapshot_export',
        ):
            fn = available.get(name)
            if fn is None:
                print(
                    f'[POST_MARKET_CATCHUP] skip step: {name} '
                    f'reason={skipped.get(name, "not discovered")}'
                )
                continue
            _run_optional_step(name, fn, dry_run=dry_run)
            steps_run.append(name)
    elif skip_eod:
        print('[POST_MARKET_CATCHUP] --skip-eod: skipping export/outcome EOD steps')
    elif capture_only:
        print('[POST_MARKET_CATCHUP] --capture-only: skipping export/outcome EOD steps')

    capture_result = _run_memory_capture(limit=limit, dry_run=dry_run)
    if capture_result.get('status') in ('ok', 'dry_run'):
        steps_run.append('memory_capture')
    else:
        print(
            f'[POST_MARKET_CATCHUP] memory_capture error={capture_result.get("error")}',
            file=sys.stderr,
        )

    outcome_result = _run_payload_outcomes(limit=limit, dry_run=dry_run)
    if outcome_result.get('status') in ('ok', 'dry_run'):
        steps_run.append('payload_outcomes')
    else:
        print(
            f'[POST_MARKET_CATCHUP] payload_outcomes error={outcome_result.get("error")}',
            file=sys.stderr,
        )

    preds_after, outcomes_after = _memory_counts()

    print(f'[POST_MARKET_CATCHUP] steps_run={steps_run}')
    print(f'[POST_MARKET_CATCHUP] memory_predictions_before={preds_before}')
    print(f'[POST_MARKET_CATCHUP] memory_predictions_after={preds_after}')
    print(f'[POST_MARKET_CATCHUP] outcomes_before={outcomes_before}')
    print(f'[POST_MARKET_CATCHUP] outcomes_after={outcomes_after}')

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Safe manual post-market catch-up.')
    parser.add_argument('--dry-run', action='store_true', help='No DB writes for capture/outcomes/EOD steps')
    parser.add_argument('--skip-eod', action='store_true', help='Skip export/outcome EOD steps')
    parser.add_argument(
        '--capture-only',
        action='store_true',
        help='Only memory capture + payload outcome resolution',
    )
    parser.add_argument('--limit', type=int, default=500, help='Max predictions to process (default 500)')
    args = parser.parse_args()

    if args.skip_eod and args.capture_only:
        print('[POST_MARKET_CATCHUP] note: both --skip-eod and --capture-only set', file=sys.stderr)

    return run_catchup(
        dry_run=args.dry_run,
        skip_eod=args.skip_eod,
        capture_only=args.capture_only,
        limit=max(0, int(args.limit)),
    )


if __name__ == '__main__':
    raise SystemExit(main())
