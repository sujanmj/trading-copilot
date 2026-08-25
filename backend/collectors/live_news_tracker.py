"""
LIVE NEWS TRACKER — unified provider registry (AstraEdge 52H).

Delegates to news_provider_registry for all enabled RSS/official sources.
Writes news_feed.json and live_news_feed.json.
"""

from __future__ import annotations

import time
from datetime import datetime

from backend.collectors.news_provider_registry import run_unified_news_refresh


def run_live_news_tracker():
    print('=' * 60)
    print('LIVE NEWS TRACKER — Unified Provider Registry')
    print(f'Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 60)

    run_started_ns = time.time_ns()
    try:
        from backend.news.news_pipeline_reliability import record_news_pipeline_attempt

        record_news_pipeline_attempt(run_started_ns)
    except Exception:
        pass

    result = None
    step1_exc = None
    try:
        result = run_unified_news_refresh(send_macro_alerts=False, ingest_discovery=True)
        print(f"Sources checked: {result.get('sources_checked')}")
        print(f"Items found: {result.get('items_found')}")
        print(f"New items: {result.get('new_items')}")
        print(f"Errors: {result.get('error_count')}")
        if result.get('errors'):
            for err in (result.get('errors') or [])[:5]:
                print(f'  [WARN] {err}')

        try:
            from backend.news.automatic_primary_verification import run_automatic_primary_verification

            verification = run_automatic_primary_verification()
        except Exception as exc:
            print(
                f'[PRIMARY_VERIFICATION] isolated failure: {type(exc).__name__}',
                flush=True,
            )
            verification = {
                'ok': False,
                'error_type': type(exc).__name__,
                'attempted': 0,
                'verified': 0,
                'failed': 1,
            }
        result['primary_verification'] = verification
        print(
            'Primary verification: '
            f"scanned={verification.get('scanned')} "
            f"attempted={verification.get('attempted')} "
            f"verified={verification.get('verified')} "
            f"skipped={verification.get('skipped')} "
            f"failed={verification.get('failed')}"
        )

        try:
            from backend.news.verified_intelligence_classifier import (
                run_verified_intelligence_classification,
            )

            classification = run_verified_intelligence_classification()
        except Exception as exc:
            print(
                f'[VERIFIED_INTELLIGENCE] isolated failure: {type(exc).__name__}',
                flush=True,
            )
            classification = {
                'ok': False,
                'error_type': type(exc).__name__,
                'eligible_seen': 0,
                'attempted': 0,
                'inserted': 0,
                'idempotent': 0,
                'skipped': 0,
                'version_conflicts': 0,
                'lock_contended': 0,
                'failed': 1,
                'bounded': False,
                'store_health': None,
            }
        result['verified_intelligence'] = classification
        print(
            '[VERIFIED_INTELLIGENCE] '
            f"eligible={classification.get('eligible_seen')} "
            f"attempted={classification.get('attempted')} "
            f"inserted={classification.get('inserted')} "
            f"idempotent={classification.get('idempotent')} "
            f"skipped={classification.get('skipped')} "
            f"conflicts={classification.get('version_conflicts')} "
            f"failed={classification.get('failed')} "
            f"bounded={classification.get('bounded')} "
            f"store_health={classification.get('store_health')}",
            flush=True,
        )
        print('=' * 60)
        return result
    except Exception as exc:
        if result is None:
            step1_exc = exc
        raise
    finally:
        try:
            from backend.news.news_pipeline_reliability import finalize_news_pipeline_run

            finalize_news_pipeline_run(
                run_started_ns,
                result,
                step1_exception=step1_exc,
            )
        except Exception:
            pass


if __name__ == '__main__':
    try:
        run_live_news_tracker()
    except Exception as e:
        print(f'[FATAL] live_news_tracker crashed: {e}')
        import traceback
        traceback.print_exc()
