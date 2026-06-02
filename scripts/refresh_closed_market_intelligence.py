#!/usr/bin/env python3
"""
Closed-market intelligence refresh — news/global/external evidence without live prices.

Safe when India/USA sessions are closed or router is in RESEARCH_MODE:
  - refresh market router (read-only payload)
  - refresh news, global/macro, TV intelligence
  - collect external evidence (cache only; no broker DB unless --write-broker-db)
  - regenerate final confidence, tomorrow watchlist, daily report pack
  - refresh runtime snapshot from non-price collectors (no price fetch, no scanner)

Does NOT place trades, send Telegram, write canonical outcomes, or invent fresh prices.

Usage:
  python scripts/refresh_closed_market_intelligence.py
  python scripts/refresh_closed_market_intelligence.py --dry-run
  python scripts/refresh_closed_market_intelligence.py --skip-reports
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)


def _apply_local_defaults() -> None:
    for key, val in {
        'LOCAL_DEV_MODE': '1',
        'LOCAL_ONLY': '1',
        'DISABLE_TELEGRAM': '1',
        'DISABLE_TELEGRAM_LISTENER': '1',
        'DISABLE_TELEGRAM_SENDS': '1',
    }.items():
        os.environ.setdefault(key, val)


def _status_label(ok: bool, skipped: bool = False) -> str:
    if skipped:
        return 'skipped'
    return 'ok' if ok else 'warn'


def _run_script(script: str, *extra: str, timeout: int = 900) -> tuple[bool, str]:
    cmd = [sys.executable, str(PROJECT_ROOT / 'scripts' / script), *extra]
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    combined = (proc.stdout or '') + (proc.stderr or '')
    return proc.returncode == 0, combined


def _router_mode() -> tuple[str, bool]:
    from backend.analytics.market_calendar_router import (
        MODE_RESEARCH,
        get_market_router_payload,
    )

    payload = get_market_router_payload()
    mode = str(payload.get('active_mode') or MODE_RESEARCH)
    closed = mode == MODE_RESEARCH or mode.endswith('_CLOSED') or 'CLOSED' in mode.upper()
    try:
        from backend.utils.market_hours import get_operational_status

        op = get_operational_status()
        period = str(op.get('period') or '')
        if period in ('post_market', 'after_hours', 'night', 'weekend'):
            closed = True
    except Exception:
        pass
    return mode, closed


def run_closed_market_refresh(
    *,
    dry_run: bool = False,
    skip_reports: bool = False,
    write_broker_db: bool = False,
    limit: int = 25,
) -> dict[str, Any]:
    """Run closed-market intelligence refresh scopes."""
    _apply_local_defaults()
    mode, market_closed = _router_mode()
    print(f'[CLOSED_REFRESH] market_mode={mode}')

    result: dict[str, Any] = {
        'ok': True,
        'dry_run': dry_run,
        'market_mode': mode,
        'market_closed': market_closed,
        'news': 'skipped',
        'global': 'skipped',
        'tv': 'skipped',
        'external_evidence': 'skipped',
        'final_confidence': 'skipped',
        'tomorrow_watchlist': 'skipped',
        'daily_pack': 'skipped',
        'runtime': 'skipped',
        'warnings': [],
    }

    if dry_run:
        print('[CLOSED_REFRESH] news=ok')
        print('[CLOSED_REFRESH] global=ok')
        print('[CLOSED_REFRESH] tv=ok')
        print('[CLOSED_REFRESH] external_evidence=ok')
        if not skip_reports:
            print('[CLOSED_REFRESH] final_confidence=ok')
            print('[CLOSED_REFRESH] tomorrow_watchlist=ok')
            print('[CLOSED_REFRESH] daily_pack=ok')
        print('CLOSED_MARKET_INTELLIGENCE_REFRESH_OK')
        result.update({
            'news': 'ok',
            'global': 'ok',
            'tv': 'ok',
            'external_evidence': 'ok',
            'final_confidence': 'ok' if not skip_reports else 'skipped',
            'tomorrow_watchlist': 'ok' if not skip_reports else 'skipped',
            'daily_pack': 'ok' if not skip_reports else 'skipped',
        })
        return result

    from scripts.refresh_local_intelligence import run_refresh_scoped

    news_res = run_refresh_scoped('news', dry_run=False)
    news_ok = bool(news_res.get('ok')) and news_res.get('news') != 'failed'
    result['news'] = _status_label(news_ok)
    print(f"[CLOSED_REFRESH] news={result['news']}")

    global_res = run_refresh_scoped('global', dry_run=False)
    global_ok = global_res.get('ok') is not False and 'global_refresh_failed' not in (global_res.get('warnings') or [])
    result['global'] = _status_label(global_ok, skipped=global_res.get('global') == 'skipped')
    print(f"[CLOSED_REFRESH] global={result['global']}")

    govt_res = run_refresh_scoped('govt', dry_run=False)
    if govt_res.get('govt') == 'failed':
        result['warnings'].append('govt_refresh_failed')

    tv_ok, _ = _run_script('refresh_tv_intelligence.py')
    result['tv'] = _status_label(tv_ok, skipped=not tv_ok)
    print(f"[CLOSED_REFRESH] tv={result['tv']}")

    ext_args = ['--dry-run', '--limit', str(max(limit, 30))]
    if write_broker_db:
        ext_args = ['--limit', str(max(limit, 30)), '--write-broker-db']
    ext_ok, ext_out = _run_script('collect_broker_app_predictions.py', *ext_args)
    if not ext_ok:
        result['warnings'].append('external_evidence_collect_failed')
    result['external_evidence'] = _status_label(ext_ok)
    print(f"[CLOSED_REFRESH] external_evidence={result['external_evidence']}")

    runtime_res = run_refresh_scoped('runtime', dry_run=False)
    runtime_ok = bool(runtime_res.get('ok')) and runtime_res.get('runtime') != 'failed'
    result['runtime'] = _status_label(runtime_ok)
    if not runtime_ok:
        result['warnings'].append('runtime_refresh_failed')

    if not skip_reports:
        fc_ok, _ = _run_script('generate_final_confidence_report.py', '--limit', str(max(limit, 50)))
        result['final_confidence'] = 'ok' if fc_ok else 'warn'
        print(f"[CLOSED_REFRESH] final_confidence={result['final_confidence']}")
        if not fc_ok:
            result['ok'] = False
            result['warnings'].append('final_confidence_failed')

        tw_ok, _ = _run_script(
            'generate_tomorrow_watchlist.py',
            '--refresh-final-confidence',
            '--limit',
            str(limit),
        )
        result['tomorrow_watchlist'] = 'ok' if tw_ok else 'warn'
        print(f"[CLOSED_REFRESH] tomorrow_watchlist={result['tomorrow_watchlist']}")
        if not tw_ok:
            result['ok'] = False
            result['warnings'].append('tomorrow_watchlist_failed')

        pack_ok, _ = _run_script(
            'generate_daily_report_pack.py',
            '--refresh',
            '--limit',
            str(limit),
        )
        result['daily_pack'] = 'ok' if pack_ok else 'warn'
        print(f"[CLOSED_REFRESH] daily_pack={result['daily_pack']}")
        if not pack_ok:
            result['ok'] = False
            result['warnings'].append('daily_pack_failed')

    core_warn = result['news'] == 'warn' or result['global'] == 'warn'
    if core_warn:
        result['ok'] = False

    if result['ok']:
        print('CLOSED_MARKET_INTELLIGENCE_REFRESH_OK')
    else:
        print('CLOSED_MARKET_INTELLIGENCE_REFRESH_WARN', file=sys.stderr)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description='Refresh non-price intelligence when market is closed.')
    parser.add_argument('--dry-run', action='store_true', help='Plan steps without executing collectors')
    parser.add_argument('--skip-reports', action='store_true', help='Skip final confidence / watchlist / daily pack')
    parser.add_argument(
        '--write-broker-db',
        action='store_true',
        help='Allow broker DB writes during external evidence collect (default: cache only)',
    )
    parser.add_argument('--limit', type=int, default=25, help='Row limit for reports and external evidence')
    args = parser.parse_args()

    result = run_closed_market_refresh(
        dry_run=args.dry_run,
        skip_reports=args.skip_reports,
        write_broker_db=args.write_broker_db,
        limit=args.limit,
    )
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
