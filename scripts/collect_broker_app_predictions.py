#!/usr/bin/env python3
"""
Collect real broker/app stock picks into broker_app_collector_latest.json cache.

Usage:
  python scripts/collect_broker_app_predictions.py --dry-run --limit 30 --show-items
  python scripts/collect_broker_app_predictions.py --show-context --classification all
  python scripts/collect_broker_app_predictions.py --write-broker-db --update-existing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'BROKER_APP_COLLECT_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description='Collect broker/app predictions from real local sources.')
    parser.add_argument('--dry-run', action='store_true', help='Skip inbox/DB writes (cache still written)')
    parser.add_argument('--limit', type=int, default=50, help='Max normalized items')
    parser.add_argument(
        '--source',
        default='all',
        choices=('all', 'news', 'tv', 'manual', 'angel'),
        help='Collector source channel',
    )
    parser.add_argument(
        '--write-broker-db',
        action='store_true',
        help='Import broker_prediction_candidate rows into broker_predictions table',
    )
    parser.add_argument('--verbose', action='store_true', help='Verbose logging')
    parser.add_argument('--show-items', action='store_true', help='Print sample normalized rows')
    parser.add_argument('--show-context', action='store_true', help='Include market/macro context in output')
    parser.add_argument(
        '--classification',
        default='all',
        choices=('all', 'broker_prediction_candidate', 'stock_news_evidence', 'market_context', 'macro_context'),
        help='Filter external evidence classification bucket',
    )
    parser.add_argument('--min-source-count', type=int, default=0, help='Warn when unique sources below N')
    parser.add_argument('--include-watch', action='store_true', default=True, help='Include WATCH stance rows')
    parser.add_argument('--no-include-watch', dest='include_watch', action='store_false')
    parser.add_argument(
        '--include-stock-news-as-watch',
        action='store_true',
        help='Include stock_news_evidence as WATCH in normalized broker cache',
    )
    parser.add_argument('--exclude-tv', action='store_true', help='Skip TV intelligence source')
    parser.add_argument('--exclude-news', action='store_true', help='Skip news/RSS sources')
    parser.add_argument('--exclude-manual', action='store_true', help='Skip manual inbox source')
    parser.add_argument(
        '--write-review-only',
        action='store_true',
        help='Write broker_db_write_review.json without broker_predictions DB writes',
    )
    args = parser.parse_args()

    from backend.collectors.broker_app_collector import CACHE_FILE, collect_broker_app_predictions

    result = collect_broker_app_predictions(
        limit=args.limit,
        dry_run=args.dry_run,
        source=args.source,
        verbose=args.verbose,
        write_broker_db=args.write_broker_db,
        include_watch=args.include_watch,
        include_stock_news_as_watch=args.include_stock_news_as_watch,
        exclude_tv=args.exclude_tv,
        exclude_news=args.exclude_news,
        exclude_manual=args.exclude_manual,
        min_source_count=args.min_source_count,
        classification=args.classification,
        show_context=args.show_context,
    )

    if result.get('ok') is not True:
        err = str(result.get('error') or 'collect failed')
        if 'BROKER_WRITE_GATE_MISMATCH' in err:
            print(err, file=sys.stderr)
            return _fail(err)
        return _fail(err)

    if args.write_broker_db:
        summary = (result.get('broker_write_review') or {}).get('summary') or {}
        write_safe = int(summary.get('write_safe') or 0)
        written = int(result.get('written_to_db') or 0)
        if written > write_safe:
            msg = (
                f'BROKER_WRITE_GATE_MISMATCH written_to_db={written} '
                f'write_safe={write_safe}'
            )
            print(msg, file=sys.stderr)
            return _fail(msg)
        print(f"[BROKER_WRITE_GATE] candidates={summary.get('total_candidates', 0)}")
        print(f"[BROKER_WRITE_GATE] write_safe={summary.get('write_safe', 0)}")
        print(f"[BROKER_WRITE_GATE] review_only={summary.get('review_only', 0)}")
        print(f"[BROKER_WRITE_GATE] rejected={summary.get('rejected', 0)}")
    elif args.write_review_only:
        from backend.collectors.broker_db_write_gate import (
            build_broker_write_review,
            gather_broker_write_candidates_from_external_evidence,
            write_broker_write_review,
        )

        candidates = gather_broker_write_candidates_from_external_evidence()
        if not candidates:
            for item in result.get('items') or []:
                if not isinstance(item, dict):
                    continue
                raw = item.get('raw_payload') if isinstance(item.get('raw_payload'), dict) else {}
                if str(raw.get('classification') or item.get('classification') or '') != 'broker_prediction_candidate':
                    continue
                candidates.append({
                    'ticker': item.get('ticker'),
                    'title': item.get('headline') or item.get('title'),
                    'source': item.get('broker_source') or item.get('source'),
                    'direction': item.get('stance') or item.get('direction'),
                    'direction_confidence': item.get('direction_confidence') or raw.get('direction_confidence'),
                    'classification': 'broker_prediction_candidate',
                    'classification_reason': item.get('classification_reason') or raw.get('classification_reason'),
                    'raw_payload': raw,
                    'collector_source': raw.get('collector_source'),
                })
        review = build_broker_write_review(candidates)
        write_broker_write_review(review)
        summary = review.get('summary') or {}
        print(f"[BROKER_WRITE_GATE] candidates={summary.get('total_candidates', 0)}")
        print(f"[BROKER_WRITE_GATE] write_safe={summary.get('write_safe', 0)}")
        print(f"[BROKER_WRITE_GATE] review_only={summary.get('review_only', 0)}")
        print(f"[BROKER_WRITE_GATE] rejected={summary.get('rejected', 0)}")
    elif result.get('broker_write_review'):
        summary = (result.get('broker_write_review') or {}).get('summary') or {}
        print(f"[BROKER_WRITE_GATE] candidates={summary.get('total_candidates', 0)}")
        print(f"[BROKER_WRITE_GATE] write_safe={summary.get('write_safe', 0)}")
        print(f"[BROKER_WRITE_GATE] review_only={summary.get('review_only', 0)}")
        print(f"[BROKER_WRITE_GATE] rejected={summary.get('rejected', 0)}")

    counts = result.get('classification_counts') or {}
    print(f"[BROKER_COLLECTOR] source={result.get('source')}")
    print(f"[BROKER_COLLECTOR] collected={result.get('collected', 0)}")
    print(f"[BROKER_COLLECTOR] normalized={result.get('normalized', 0)}")
    print(f"[BROKER_COLLECTOR] rejected={result.get('rejected', 0)}")
    print(f"[BROKER_COLLECTOR] broker_candidates={counts.get('broker_prediction_candidate', 0)}")
    print(f"[BROKER_COLLECTOR] stock_news={counts.get('stock_news_evidence', 0)}")
    print(f"[BROKER_COLLECTOR] market_context={counts.get('market_context', 0)}")
    print(f"[BROKER_COLLECTOR] macro_context={counts.get('macro_context', 0)}")
    print(f"[BROKER_COLLECTOR] rejected={counts.get('rejected', 0)}")
    print(f"[BROKER_COLLECTOR] rejection_reasons={result.get('rejection_reasons') or {}}")
    print(f"[BROKER_COLLECTOR] written_to_db={result.get('written_to_db', 0)}")
    print(f"[BROKER_COLLECTOR] fake_predictions={result.get('fake_predictions', 0)}")

    if args.show_items:
        print('[BROKER_COLLECTOR] accepted_sample:')
        for row in (result.get('items') or [])[: min(args.limit, 20)]:
            line = (
                f"  ACCEPT | {row.get('broker_source', row.get('source', '-'))} | "
                f"{row.get('ticker', '-')} | "
                f"{row.get('stance', row.get('direction', '-'))} | "
                f"{(row.get('headline') or '-')[:80]} | "
                f"{row.get('extraction_method', '-')}"
            )
            print(line)
            raw_payload = row.get('raw_payload') if isinstance(row.get('raw_payload'), dict) else {}
            classification = str(row.get('classification') or raw_payload.get('classification') or '')
            if classification == 'broker_prediction_candidate':
                cls_reason = row.get('classification_reason') or raw_payload.get('classification_reason') or '-'
                dir_reason = row.get('direction_reason') or raw_payload.get('direction_reason') or '-'
                print(f"    classification_reason={cls_reason} | direction_reason={dir_reason}")
        print('[BROKER_COLLECTOR] rejected_sample:')
        for row in (result.get('rejected_items_sample') or [])[: min(args.limit, 20)]:
            print(
                f"  REJECT | reason={row.get('reason', '-')} | "
                f"{row.get('source', '-')} | "
                f"{(row.get('title') or '-')[:80]}"
            )

    if args.show_context:
        ext = result.get('external_evidence') or {}
        summary = ext.get('summary') or result.get('external_evidence_summary') or {}
        print(f"[BROKER_COLLECTOR] external_evidence_accepted={summary.get('accepted', 0)}")
        for bucket, key in (
            ('broker_candidates', 'broker_candidates'),
            ('stock_news', 'stock_news'),
            ('market_context', 'market_context_items'),
            ('macro_context', 'macro_context_items'),
        ):
            rows = ext.get(key) or ext.get(bucket) or []
            if not isinstance(rows, list):
                continue
            if rows:
                print(f'[BROKER_COLLECTOR] {bucket}_sample:')
                for row in rows[:5]:
                    print(
                        f"  {row.get('classification', bucket)} | "
                        f"{row.get('ticker') or '-'} | "
                        f"{row.get('direction', '-')} | "
                        f"{(row.get('title') or '-')[:80]}"
                    )

    if args.verbose:
        print(f'[BROKER_COLLECTOR] cache={CACHE_FILE}')
    print('BROKER_APP_COLLECTOR_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
