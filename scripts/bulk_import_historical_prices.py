#!/usr/bin/env python3

"""

Bulk import historical OHLCV for ticker universe in safe batches.



Usage:

  python scripts/bulk_import_historical_prices.py --market INDIA --years 1 --limit 10 --dry-run

  python scripts/bulk_import_historical_prices.py --market INDIA --years 1 --limit 10 --batch-size 5 --resume

"""



from __future__ import annotations



import argparse

import json

import sys

import time

from datetime import datetime, timezone

from pathlib import Path

from typing import Any



PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:

    sys.path.insert(0, str(PROJECT_ROOT))



if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):

    import os



    os.chdir(PROJECT_ROOT)



from backend.analytics.historical_coverage import (

    DEFAULT_PROGRESS_SOURCE,

    VALID_YEARS,

    compute_date_range,

    load_completed_range_keys,

    load_failed_range_keys,

    merge_completed_ranges,

    range_progress_entry,

    should_skip_ticker_import,

)

from backend.utils.config import DATA_DIR



UNIVERSE_PATH = DATA_DIR / 'historical_ticker_universe.json'

PROGRESS_PATH = DATA_DIR / 'historical_import_progress.json'

REPORT_PATH = DATA_DIR / 'historical_import_report.json'





def _fail(msg: str) -> int:

    print(f'BULK_HISTORICAL_IMPORT_FAIL: {msg}', file=sys.stderr)

    return 1





def _load_universe() -> dict[str, Any]:

    if not UNIVERSE_PATH.is_file():

        raise FileNotFoundError(f'missing universe file: {UNIVERSE_PATH}')

    return json.loads(UNIVERSE_PATH.read_text(encoding='utf-8'))





def _write_json(path: Path, payload: dict[str, Any]) -> None:

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')





def _load_progress() -> dict[str, Any]:

    if not PROGRESS_PATH.is_file():

        return {}

    try:

        return json.loads(PROGRESS_PATH.read_text(encoding='utf-8'))

    except (OSError, json.JSONDecodeError):

        return {}





def run_bulk_import(

    *,

    market: str,

    years: int | None = None,

    from_date: str | None = None,

    to_date: str | None = None,

    limit: int | None = None,

    batch_size: int = 10,

    sleep_seconds: float = 2.0,

    dry_run: bool = False,

    resume: bool = False,

    ignore_progress: bool = False,

    force_range_check: bool = False,

    verbose: bool = False,

    progress_source: str = DEFAULT_PROGRESS_SOURCE,

) -> dict[str, Any]:

    from scripts.import_historical_prices import _normalize_ticker, run_import



    universe = _load_universe()

    from_d, to_d = compute_date_range(years=years, from_date=from_date, to_date=to_date)



    entries = universe.get('tickers') or []

    tickers = [

        _normalize_ticker(entry.get('ticker') if isinstance(entry, dict) else entry)

        for entry in entries

    ]

    tickers = [t for t in tickers if t]

    tickers.sort(key=lambda t: next(

        (e.get('priority', 99) for e in entries if isinstance(e, dict) and _normalize_ticker(e.get('ticker')) == t),

        99,

    ))



    if limit is not None and limit > 0:

        tickers = tickers[: int(limit)]



    progress = {} if ignore_progress else _load_progress()

    completed_range_keys = set() if ignore_progress else load_completed_range_keys(progress)

    failed_range_keys = set() if ignore_progress else load_failed_range_keys(progress)

    completed_ranges = list(progress.get('completed_ranges') or [])

    failed_ranges = list(progress.get('failed_ranges') or [])



    report: dict[str, Any] = {

        'market': market,

        'years': years,

        'from_date': from_d,

        'to_date': to_d,

        'dry_run': dry_run,

        'resume': resume,

        'ignore_progress': ignore_progress,

        'force_range_check': force_range_check,

        'tickers_total': len(tickers),

        'tickers_done': 0,

        'rows_written': 0,

        'rows_valid': 0,

        'failed': 0,

        'fake_prices': 0,

        'skipped_resume': 0,

        'already_covered': 0,

        'fetched_missing': 0,

        'skipped_covered': 0,

        'batches': [],

        'failed_tickers': [],

        'generated_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),

    }



    pending: list[str] = []

    for ticker in tickers:

        if resume:

            skip, coverage = should_skip_ticker_import(

                market=market,

                ticker=ticker,

                from_date=from_d,

                to_date=to_d,

                years=years,

                source=progress_source,

                completed_range_keys=completed_range_keys,

                ignore_progress=ignore_progress,

                force_range_check=force_range_check,

            )

            if skip:

                report['skipped_resume'] += 1

                report['already_covered'] += 1

                report['skipped_covered'] += 1

                continue

            if coverage.get('status') != 'fully_covered':

                report['fetched_missing'] += 1

            else:

                report['already_covered'] += 1

        pending.append(ticker)



    batch_size = max(1, int(batch_size))

    for offset in range(0, len(pending), batch_size):

        batch = pending[offset: offset + batch_size]

        if verbose:

            print(f'[BULK_HISTORICAL] batch={offset // batch_size + 1} tickers={",".join(batch)}')



        result = run_import(

            tickers=batch,

            market=market,

            from_date=from_d,

            to_date=to_d,

            dry_run=dry_run,

            verbose=verbose,

        )



        batch_failed = list(result.get('failed_tickers') or [])

        batch_written = int(result.get('rows_written') or 0)

        batch_valid = int(result.get('rows_valid') or 0)

        fake = int(result.get('fake_prices') or 0)



        report['rows_written'] += batch_written

        report['rows_valid'] += batch_valid

        report['fake_prices'] += fake

        report['failed'] += len(batch_failed)

        report['failed_tickers'].extend(batch_failed)



        batch_completed_entries: list[dict[str, Any]] = []

        batch_failed_entries: list[dict[str, Any]] = []

        for ticker in batch:

            entry = range_progress_entry(

                market=market,

                ticker=ticker,

                from_date=from_d,

                to_date=to_d,

                years=years,

                source=progress_source,

            )

            if ticker in batch_failed:

                failed_range_keys.add(entry['key'])

                batch_failed_entries.append(entry)

            else:

                completed_range_keys.add(entry['key'])

                batch_completed_entries.append(entry)



        completed_ranges = merge_completed_ranges(completed_ranges, batch_completed_entries)

        failed_ranges = merge_completed_ranges(failed_ranges, batch_failed_entries)



        report['batches'].append({

            'tickers': batch,

            'rows_written': batch_written,

            'rows_valid': batch_valid,

            'failed_tickers': batch_failed,

        })



        progress_payload = {

            'market': market,

            'years': years,

            'from_date': from_d,

            'to_date': to_d,

            'source': progress_source,

            'completed_ranges': completed_ranges,

            'failed_ranges': failed_ranges,

            'completed_tickers': sorted({

                str(entry.get('ticker') or '')

                for entry in completed_ranges

                if isinstance(entry, dict) and entry.get('ticker')

            }),

            'failed_tickers': sorted({

                str(entry.get('ticker') or '')

                for entry in failed_ranges

                if isinstance(entry, dict) and entry.get('ticker')

            }),

            'rows_written_total': report['rows_written'],

            'updated_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),

        }

        if not dry_run:

            _write_json(PROGRESS_PATH, progress_payload)



        if offset + batch_size < len(pending) and sleep_seconds > 0:

            time.sleep(float(sleep_seconds))



    imported_ok = len([t for t in pending if t not in set(report['failed_tickers'])])
    report['tickers_done'] = report['skipped_covered'] + imported_ok

    _write_json(REPORT_PATH, report)



    return report





def print_bulk_summary(report: dict[str, Any]) -> None:

    print(f'[BULK_HISTORICAL] market={report["market"]}')

    years = report.get('years')

    print(f'[BULK_HISTORICAL] years={years if years is not None else "custom"}')

    print(f'[BULK_HISTORICAL] requested_from={report.get("from_date")}')

    print(f'[BULK_HISTORICAL] requested_to={report.get("to_date")}')

    print(f'[BULK_HISTORICAL] tickers_total={report["tickers_total"]}')

    print(f'[BULK_HISTORICAL] tickers_done={report["tickers_done"]}')

    print(f'[BULK_HISTORICAL] already_covered={report.get("already_covered", 0)}')

    print(f'[BULK_HISTORICAL] fetched_missing={report.get("fetched_missing", 0)}')

    print(f'[BULK_HISTORICAL] skipped_covered={report.get("skipped_covered", 0)}')

    print(f'[BULK_HISTORICAL] rows_written={report["rows_written"]}')

    print(f'[BULK_HISTORICAL] failed={report["failed"]}')

    print(f'[BULK_HISTORICAL] fake_prices={report["fake_prices"]}')





def main() -> int:

    parser = argparse.ArgumentParser(description='Bulk import historical OHLCV prices.')

    parser.add_argument('--market', required=True, choices=('INDIA', 'USA'))

    parser.add_argument('--years', type=int, choices=VALID_YEARS, default=None)

    parser.add_argument('--from', dest='from_date', help='Start date YYYY-MM-DD')

    parser.add_argument('--to', dest='to_date', help='End date YYYY-MM-DD')

    parser.add_argument('--limit', type=int, default=None)

    parser.add_argument('--batch-size', type=int, default=10)

    parser.add_argument('--sleep-seconds', type=float, default=2.0)

    parser.add_argument('--dry-run', action='store_true')

    parser.add_argument('--resume', action='store_true')

    parser.add_argument('--ignore-progress', action='store_true')

    parser.add_argument('--force-range-check', action='store_true')

    parser.add_argument('--verbose', action='store_true')

    args = parser.parse_args()



    if not args.years and not (args.from_date and args.to_date):

        args.years = 1



    if not UNIVERSE_PATH.is_file():

        return _fail(f'missing {UNIVERSE_PATH.name}; run build_historical_ticker_universe.py first')



    try:

        report = run_bulk_import(

            market=args.market,

            years=args.years,

            from_date=args.from_date,

            to_date=args.to_date,

            limit=args.limit,

            batch_size=args.batch_size,

            sleep_seconds=args.sleep_seconds,

            dry_run=args.dry_run,

            resume=args.resume,

            ignore_progress=args.ignore_progress,

            force_range_check=args.force_range_check,

            verbose=args.verbose,

        )

    except Exception as exc:

        return _fail(str(exc))



    print_bulk_summary(report)



    if report['fake_prices'] != 0:

        return _fail('fake_prices must be 0')



    print('BULK_HISTORICAL_IMPORT_OK')

    return 0





if __name__ == '__main__':

    raise SystemExit(main())

