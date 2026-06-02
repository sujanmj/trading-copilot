#!/usr/bin/env python3
"""
Manual local intelligence refresh — safe collectors/exporters only.

Does not call Telegram, write outcomes, or alter prediction logic.

Usage:
  python scripts/refresh_local_intelligence.py --dry-run --all
  python scripts/refresh_local_intelligence.py --news --global --prices --memory
"""

from __future__ import annotations

import argparse
import importlib
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

StepFn = Callable[[], Any]
StepResult = str  # ok | skipped | failed


def _try_import_callable(module: str, attr: str) -> tuple[StepFn | None, str | None]:
    try:
        mod = importlib.import_module(module)
        fn = getattr(mod, attr, None)
        if fn is None or not callable(fn):
            return None, f'{module}.{attr} not callable'
        return fn, None
    except Exception as exc:
        return None, str(exc)


def _run_step(name: str, fn: StepFn) -> StepResult:
    buf = io.StringIO()
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            fn()
        return 'ok'
    except Exception as exc:
        print(f'[REFRESH_LOCAL] {name}_error={exc}', file=sys.stderr)
        return 'failed'


def _discover_steps() -> dict[str, tuple[StepFn | None, str | None]]:
    specs: dict[str, tuple[str, str, Callable[[StepFn], StepFn] | None]] = {
        'news': ('backend.collectors.live_news_tracker', 'run_live_news_tracker', None),
        'global': ('backend.collectors.global_collector', 'fetch_global_sentiment', None),
        'govt': ('backend.collectors.govt_tracker', 'collect_govt_intelligence', None),
        'prices': ('backend.collectors.collector', 'collect_india_market_data', lambda fn: (lambda: fn(force=True))),
        'snapshot': (
            'backend.runtime.snapshot_orchestrator',
            'run_snapshot_cycle',
            lambda fn: (lambda: fn(trigger='local_refresh', force_refresh=True)),
        ),
    }

    discovered: dict[str, tuple[StepFn | None, str | None]] = {}
    for name, (module, attr, wrapper) in specs.items():
        fn, err = _try_import_callable(module, attr)
        if fn is None:
            discovered[name] = (None, err)
            continue
        discovered[name] = (wrapper(fn) if wrapper else fn, None)
    return discovered


def _refresh_memory_step() -> StepResult:
    try:
        from backend.analytics.market_memory_advisor import get_advisor_batch_report
        from backend.utils.config import DATA_DIR

        report = get_advisor_batch_report()
        output_path = DATA_DIR / 'market_memory_advisor_report.json'
        output_path.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')

        try:
            from backend.analytics.market_memory_dashboard import get_market_memory_dashboard

            dashboard = get_market_memory_dashboard(limit=50)
            dash_path = DATA_DIR / 'market_memory_dashboard_cache.json'
            dash_path.write_text(json.dumps(dashboard, indent=2, default=str), encoding='utf-8')
        except Exception:
            pass

        return 'ok'
    except Exception as exc:
        print(f'[REFRESH_LOCAL] memory_error={exc}', file=sys.stderr)
        return 'failed'


def _count_enriched_symbols() -> tuple[int, int]:
    """Return (current_symbol_count, peak_symbol_count) from enriched price file."""
    try:
        from backend.utils.config import DATA_DIR

        path = DATA_DIR / 'latest_market_data_memory_enriched.json'
        if not path.is_file():
            return 0, 0
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return 0, 0
    if not isinstance(data, dict):
        return 0, 0
    prices = data.get('prices')
    current = len(prices) if isinstance(prices, dict) else 0
    meta = data.get('enrichment_meta')
    peak = current
    if isinstance(meta, dict) and meta.get('peak_symbols') is not None:
        try:
            peak = max(int(meta['peak_symbols']), current)
        except (TypeError, ValueError):
            pass
    return current, peak


def _refresh_prices_step(base_fn: StepFn | None, *, limit: int | None = None) -> StepResult:
    if base_fn is None:
        return 'skipped'
    result = _run_step('prices_collect', base_fn)
    if result != 'ok':
        return result

    try:
        from scripts.enrich_market_memory_prices import run_enrichment

        _, before_peak = _count_enriched_symbols()
        enrich_result = run_enrichment(
            dry_run=False,
            limit=limit,
            promote=False,
            verbose=False,
        )
        after_symbols = int(enrich_result.get('final_symbols') or 0)
        if before_peak and after_symbols < before_peak:
            print('[PRICE_ENRICH] coverage_below_previous_peak')
        return 'ok'
    except Exception as exc:
        print(f'[REFRESH_LOCAL] prices_enrich_error={exc}', file=sys.stderr)
        return 'failed' if result == 'ok' else result


def _publish_runtime_wrapper(*, reason: str = 'local_refresh_runtime') -> tuple[StepResult, dict[str, Any]]:
    try:
        from backend.runtime.runtime_snapshot_publisher import publish_runtime_snapshot_wrapper

        publish_result = publish_runtime_snapshot_wrapper(reason=reason)
        if publish_result.get('ok'):
            return 'ok', publish_result
        return 'failed', publish_result
    except Exception as exc:
        print(f'[REFRESH_LOCAL] runtime_publish_error={exc}', file=sys.stderr)
        return 'failed', {'ok': False, 'error': str(exc)}


def _refresh_runtime_step(discovered: dict[str, tuple[StepFn | None, str | None]]) -> tuple[StepResult, dict[str, Any]]:
    fn, _ = discovered.get('snapshot', (None, None))
    result = 'skipped'
    if fn is not None:
        result = _run_step('snapshot', fn)
    publish_status, publish_result = _publish_runtime_wrapper(reason='local_refresh_runtime')
    if publish_status == 'failed' and result != 'failed':
        result = 'failed'
    elif publish_status == 'ok' and result == 'skipped':
        result = 'ok'
    try:
        from backend.utils.config import DATA_DIR

        flag = DATA_DIR / '_runtime_cache_invalidate.flag'
        flag.write_text(
            json.dumps({'at': __import__('datetime').datetime.now().isoformat(), 'reason': 'local_refresh_runtime'}),
            encoding='utf-8',
        )
    except Exception:
        pass
    if result == 'skipped' and fn is None and publish_status == 'ok':
        result = 'ok'
    return result, publish_result


def _discover_optional_steps() -> dict[str, tuple[StepFn | None, str | None]]:
    """Optional per-tab collectors (skip safely when unavailable)."""
    specs: dict[str, tuple[str, str, Callable[[StepFn], StepFn] | None]] = {
        'govt': ('backend.collectors.govt_tracker', 'collect_govt_intelligence', None),
        'scanner': ('backend.analyzers.stock_scanner', 'run_scanner', None),
        'tv': ('backend.collectors.tv_intelligence_collector', 'run_tv_collector', None),
        'reddit': ('backend.collectors.reddit_tracker', 'run_reddit_tracker', None),
        'brokers': ('backend.collectors.broker_app_collector', 'run_broker_app_collector', None),
        'calibration': ('backend.storage.stats_exporter', 'export_stats', None),
        'journal': ('backend.storage.history_exporter', 'export_history', None),
    }
    discovered: dict[str, tuple[StepFn | None, str | None]] = {}
    for name, (module, attr, wrapper) in specs.items():
        fn, err = _try_import_callable(module, attr)
        if fn is None:
            discovered[name] = (None, err)
            continue
        discovered[name] = (wrapper(fn) if wrapper else fn, None)
    return discovered


def run_refresh_scoped(scope: str = 'all', *, dry_run: bool = False) -> dict[str, Any]:
    """Run refresh for a single scope (runtime, news, prices, memory, govt, scanner, …)."""
    scope_norm = (scope or 'all').strip().lower()
    allowed = {
        'runtime', 'news', 'prices', 'memory', 'all',
        'govt', 'scanner', 'global', 'tv', 'reddit', 'brokers', 'calibration', 'journal',
        'intelligence', 'closed-market',
    }
    base_result: dict[str, Any] = {
        'ok': False,
        'scope': scope_norm,
        'dry_run': dry_run,
        'runtime': 'skipped',
        'news': 'skipped',
        'prices': 'skipped',
        'memory': 'skipped',
        'warnings': [],
        'partial': False,
    }
    optional_scopes = {'govt', 'scanner', 'global', 'tv', 'reddit', 'brokers', 'calibration', 'journal'}
    if scope_norm not in allowed:
        base_result['warnings'] = [f'invalid_scope:{scope_norm}']
        base_result['error'] = f'invalid scope: {scope_norm}'
        return base_result

    if scope_norm in ('intelligence', 'closed-market'):
        from scripts.refresh_closed_market_intelligence import run_closed_market_refresh

        closed_result = run_closed_market_refresh(dry_run=dry_run, skip_reports=False)
        return {
            'ok': bool(closed_result.get('ok')),
            'scope': scope_norm,
            'dry_run': dry_run,
            'runtime': closed_result.get('runtime', 'skipped'),
            'news': closed_result.get('news', 'skipped'),
            'prices': 'skipped',
            'memory': 'skipped',
            'global': closed_result.get('global', 'skipped'),
            'tv': closed_result.get('tv', 'skipped'),
            'external_evidence': closed_result.get('external_evidence', 'skipped'),
            'final_confidence': closed_result.get('final_confidence', 'skipped'),
            'tomorrow_watchlist': closed_result.get('tomorrow_watchlist', 'skipped'),
            'daily_pack': closed_result.get('daily_pack', 'skipped'),
            'warnings': closed_result.get('warnings') or [],
            'market_mode': closed_result.get('market_mode'),
        }

    do_news = scope_norm in ('news', 'all')
    do_prices = scope_norm in ('prices', 'all')
    do_memory = scope_norm in ('memory', 'all')
    do_runtime = scope_norm in ('runtime', 'all')
    do_govt = scope_norm in ('govt', 'all')
    do_scanner = scope_norm in ('scanner', 'all')
    do_global = scope_norm in ('global', 'all')
    do_tv = scope_norm in ('tv', 'all')
    do_reddit = scope_norm in ('reddit', 'all')
    do_brokers = scope_norm in ('brokers', 'all')
    do_calibration = scope_norm in ('calibration', 'all')
    do_journal = scope_norm in ('journal', 'all')

    discovered: dict[str, tuple[StepFn | None, str | None]] | None = None
    optional: dict[str, tuple[StepFn | None, str | None]] | None = None

    def _get_discovered() -> dict[str, tuple[StepFn | None, str | None]]:
        nonlocal discovered
        if discovered is None:
            discovered = _discover_steps()
        return discovered

    def _get_optional() -> dict[str, tuple[StepFn | None, str | None]]:
        nonlocal optional
        if optional is None:
            optional = _discover_optional_steps()
        return optional

    results: dict[str, StepResult] = {
        'runtime': 'skipped',
        'news': 'skipped',
        'prices': 'skipped',
        'memory': 'skipped',
    }
    warnings: list[str] = []

    print(f'[REFRESH_LOCAL] scope={scope_norm} started')

    if dry_run:
        if do_news:
            fn, _ = _get_discovered().get('news', (None, None))
            results['news'] = 'ok' if fn is not None else 'skipped'
        if do_prices:
            fn, _ = _get_discovered().get('prices', (None, None))
            results['prices'] = 'ok' if fn is not None else 'skipped'
        if do_memory:
            results['memory'] = 'ok'
        if do_runtime:
            fn, _ = _get_discovered().get('snapshot', (None, None))
            results['runtime'] = 'ok' if fn is not None else 'skipped'
        print('[REFRESH_LOCAL] done (dry-run)')
        return {
            'ok': True,
            'scope': scope_norm,
            'dry_run': dry_run,
            'runtime': results['runtime'],
            'news': results['news'],
            'prices': results['prices'],
            'memory': results['memory'],
            'warnings': warnings,
        }

    if do_news:
        fn, err = _get_discovered().get('news', (None, None))
        if fn is None:
            results['news'] = 'skipped'
            if err:
                warnings.append(f'news_unavailable:{err}')
        else:
            results['news'] = _run_step('news', fn)
        print(f"[REFRESH_LOCAL] news={results['news']}")

    scope_results: dict[str, StepResult] = {}

    if do_global:
        fn, err = _get_discovered().get('global', (None, None))
        if fn is None:
            scope_results['global'] = 'skipped'
            if err:
                warnings.append(f'global_unavailable:{err}')
        else:
            global_result = _run_step('global', fn)
            scope_results['global'] = global_result
            if global_result == 'failed':
                warnings.append('global_refresh_failed')

    if do_govt:
        fn, err = _get_discovered().get('govt', (None, None)) or _get_optional().get('govt', (None, None))
        if fn is None:
            scope_results['govt'] = 'skipped'
            if err:
                warnings.append(f'govt_unavailable:{err}')
        else:
            govt_result = _run_step('govt', fn)
            scope_results['govt'] = govt_result
            if govt_result == 'failed':
                warnings.append('govt_refresh_failed')

    if do_scanner:
        fn, err = _get_optional().get('scanner', (None, None))
        if fn is None:
            scope_results['scanner'] = 'skipped'
            if err:
                warnings.append(f'scanner_unavailable:{err}')
        else:
            scanner_result = _run_step('scanner', fn)
            scope_results['scanner'] = scanner_result
            if scanner_result == 'failed':
                warnings.append('scanner_refresh_failed')

    if do_tv:
        fn, err = _get_optional().get('tv', (None, None))
        if fn is None:
            scope_results['tv'] = 'skipped'
            if err:
                warnings.append(f'tv_unavailable:{err}')
        else:
            tv_result = _run_step('tv', fn)
            scope_results['tv'] = tv_result
            if tv_result == 'failed':
                warnings.append('tv_refresh_failed')

    if do_reddit:
        fn, err = _get_optional().get('reddit', (None, None))
        if fn is None:
            scope_results['reddit'] = 'skipped'
            if err:
                warnings.append(f'reddit_unavailable:{err}')
        else:
            reddit_result = _run_step('reddit', fn)
            scope_results['reddit'] = reddit_result
            if reddit_result == 'failed':
                warnings.append('reddit_refresh_failed')

    if do_brokers:
        fn, err = _get_optional().get('brokers', (None, None))
        if fn is None:
            scope_results['brokers'] = 'skipped'
            if err:
                warnings.append(f'brokers_unavailable:{err}')
        else:
            brokers_result = _run_step('brokers', fn)
            scope_results['brokers'] = brokers_result
            if brokers_result == 'failed':
                warnings.append('brokers_refresh_failed')

    if do_calibration:
        fn, err = _get_optional().get('calibration', (None, None))
        if fn is None:
            scope_results['calibration'] = 'skipped'
            if err:
                warnings.append(f'calibration_unavailable:{err}')
        else:
            cal_result = _run_step('calibration', fn)
            scope_results['calibration'] = cal_result
            if cal_result == 'failed':
                warnings.append('calibration_refresh_failed')

    if do_journal:
        fn, err = _get_optional().get('journal', (None, None))
        if fn is None:
            scope_results['journal'] = 'skipped'
            if err:
                warnings.append(f'journal_unavailable:{err}')
        else:
            journal_result = _run_step('journal', fn)
            scope_results['journal'] = journal_result
            if journal_result == 'failed':
                warnings.append('journal_refresh_failed')

    if do_prices:
        fn, err = _get_discovered().get('prices', (None, None))
        if fn is None:
            results['prices'] = 'skipped'
            if err:
                warnings.append(f'prices_unavailable:{err}')
        else:
            results['prices'] = _refresh_prices_step(fn)
        print(f"[REFRESH_LOCAL] prices={results['prices']}")

    if do_memory:
        results['memory'] = _refresh_memory_step()
        print(f"[REFRESH_LOCAL] memory={results['memory']}")

    publish_meta: dict[str, Any] = {}
    if do_runtime:
        runtime_result, publish_meta = _refresh_runtime_step(_get_discovered())
        results['runtime'] = runtime_result
        print(f"[REFRESH_LOCAL] runtime={results['runtime']}")

    failed = [key for key, status in results.items() if status == 'failed']
    if failed:
        warnings.extend([f'{key}_failed' for key in failed])

    core_failed = [key for key in failed if key in ('runtime', 'news', 'prices', 'memory')]
    partial = False
    reason = None
    if scope_norm in optional_scopes:
        scope_status = scope_results.get(scope_norm) or results.get(scope_norm)
        if scope_status == 'failed':
            partial = True
            reason = f'{scope_norm}_collector_failed'
            warnings.append(reason)

    if partial and not core_failed:
        ok = True
    else:
        ok = not failed

    print('[REFRESH_LOCAL] done')
    response: dict[str, Any] = {
        'ok': ok,
        'scope': scope_norm,
        'dry_run': dry_run,
        'runtime': results['runtime'],
        'news': results['news'],
        'prices': results['prices'],
        'memory': results['memory'],
        'warnings': warnings,
        'partial': partial,
    }
    if partial:
        response['reason'] = reason
        response[scope_norm] = scope_results.get(scope_norm, 'failed')
    if publish_meta:
        response['runtime_publish'] = publish_meta
    return response


def run_refresh(
    *,
    dry_run: bool = False,
    news: bool = False,
    global_markets: bool = False,
    prices: bool = False,
    memory: bool = False,
    run_all: bool = False,
) -> dict[str, StepResult]:
    selected = {
        'news': run_all or news,
        'global': run_all or global_markets,
        'prices': run_all or prices,
        'memory': run_all or memory,
    }
    include_govt = run_all
    include_snapshot = run_all

    discovered = _discover_steps()
    results: dict[str, StepResult] = {
        'news': 'skipped',
        'global': 'skipped',
        'prices': 'skipped',
        'memory': 'skipped',
    }

    print('[REFRESH_LOCAL] started')

    if dry_run:
        for key in ('news', 'global', 'prices', 'memory'):
            if not selected[key]:
                results[key] = 'skipped'
            elif key == 'memory':
                results[key] = 'ok'
            else:
                fn, _ = discovered.get(key, (None, None))
                results[key] = 'ok' if fn is not None else 'skipped'
            print(f'[REFRESH_LOCAL] {key}={results[key]}')
        print('[REFRESH_LOCAL] done')
        return results

    if selected['news']:
        fn, err = discovered.get('news', (None, None))
        if fn is None:
            results['news'] = 'skipped'
        else:
            results['news'] = _run_step('news', fn)
        print(f"[REFRESH_LOCAL] news={results['news']}")

    if selected['global']:
        fn, err = discovered.get('global', (None, None))
        if fn is None:
            results['global'] = 'skipped'
        else:
            results['global'] = _run_step('global', fn)
        print(f"[REFRESH_LOCAL] global={results['global']}")

    if include_govt:
        fn, err = discovered.get('govt', (None, None))
        if fn is not None:
            _run_step('govt', fn)

    if selected['prices']:
        fn, err = discovered.get('prices', (None, None))
        if fn is None:
            results['prices'] = 'skipped'
        else:
            results['prices'] = _refresh_prices_step(fn)
        print(f"[REFRESH_LOCAL] prices={results['prices']}")

    if selected['memory']:
        results['memory'] = _refresh_memory_step()
        print(f"[REFRESH_LOCAL] memory={results['memory']}")

    if include_snapshot:
        fn, err = discovered.get('snapshot', (None, None))
        if fn is not None:
            _run_step('snapshot', fn)
        _publish_runtime_wrapper(reason='local_refresh')
        try:
            from backend.utils.config import DATA_DIR

            flag = DATA_DIR / '_runtime_cache_invalidate.flag'
            flag.write_text(
                json.dumps({'at': __import__('datetime').datetime.now().isoformat(), 'reason': 'local_refresh'}),
                encoding='utf-8',
            )
        except Exception:
            pass

    print('[REFRESH_LOCAL] done')
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description='Refresh local intelligence collectors (safe/manual)')
    parser.add_argument('--dry-run', action='store_true', help='Report planned steps without executing')
    parser.add_argument('--news', action='store_true', help='Refresh news feeds')
    parser.add_argument('--global', dest='global_markets', action='store_true', help='Refresh global markets')
    parser.add_argument('--prices', action='store_true', help='Refresh India prices + memory enrichment')
    parser.add_argument('--memory', action='store_true', help='Refresh market memory advisor/dashboard cache')
    parser.add_argument('--all', action='store_true', help='Run all safe refresh steps')
    args = parser.parse_args()

    if not any((args.news, args.global_markets, args.prices, args.memory, args.all)):
        parser.error('Specify at least one of --news, --global, --prices, --memory, or --all')

    results = run_refresh(
        dry_run=args.dry_run,
        news=args.news,
        global_markets=args.global_markets,
        prices=args.prices,
        memory=args.memory,
        run_all=args.all,
    )
    failed = [key for key, status in results.items() if status == 'failed']
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
