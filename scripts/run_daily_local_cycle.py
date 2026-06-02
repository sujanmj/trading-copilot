#!/usr/bin/env python3

"""

Manual one-command local daily cycle — startup check, router, refresh, reports, validators.



Usage:

  python scripts/run_daily_local_cycle.py --dry-run --skip-api

  python scripts/run_daily_local_cycle.py --market-aware --skip-refresh

  python scripts/run_daily_local_cycle.py --closed-market-refresh



Does not place trades, send Telegram, or write outcomes (except validator smoke tests).

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

    defaults = {

        'LOCAL_DEV_MODE': '1',

        'LOCAL_ONLY': '1',

        'DISABLE_TELEGRAM': '1',

        'DISABLE_TELEGRAM_LISTENER': '1',

        'DISABLE_TELEGRAM_SENDS': '1',

    }

    for key, val in defaults.items():

        os.environ.setdefault(key, val)





def _run_script(script: str, *extra: str, timeout: int = 600) -> tuple[int, str]:

    cmd = [sys.executable, str(PROJECT_ROOT / 'scripts' / script), *extra]

    proc = subprocess.run(

        cmd,

        cwd=str(PROJECT_ROOT),

        capture_output=True,

        text=True,

        timeout=timeout,

    )

    combined = (proc.stdout or '') + (proc.stderr or '')

    return proc.returncode, combined





def _print_step(label: str, code: int, output: str) -> None:

    status = 'ok' if code == 0 else 'fail'

    print(f'[DAILY_CYCLE] {label}={status}')

    if code != 0 and output.strip():

        tail = output.strip().splitlines()[-3:]

        for line in tail:

            print(f'[DAILY_CYCLE] {label}_detail={line}')





def _is_closed_market_context() -> tuple[bool, str]:

    from backend.analytics.market_calendar_router import (

        MODE_RESEARCH,

        get_market_router_payload,

    )



    payload = get_market_router_payload()

    mode = str(payload.get('active_mode') or MODE_RESEARCH)

    closed = mode == MODE_RESEARCH

    try:

        from backend.utils.market_hours import get_operational_status



        op = get_operational_status()

        period = str(op.get('period') or '')

        if period in ('post_market', 'after_hours', 'night', 'weekend'):

            closed = True

    except Exception:

        pass

    return closed, mode





def _resolve_refresh_scopes(*, market_aware: bool) -> list[str]:

    if not market_aware:

        return ['memory']



    closed, mode = _is_closed_market_context()

    print(f'[DAILY_CYCLE] market_mode={mode} closed={closed}')



    if closed:

        return []



    from backend.analytics.market_calendar_router import get_market_router_payload



    payload = get_market_router_payload()

    mode = str(payload.get('active_mode') or mode)



    if mode.startswith('INDIA'):

        return ['prices', 'news', 'memory']

    if mode.startswith('USA'):

        return ['global', 'news', 'memory']

    return ['memory', 'global', 'news', 'brokers']





def _run_refresh_scopes(scopes: list[str], *, dry_run: bool) -> bool:

    from scripts.refresh_local_intelligence import run_refresh_scoped



    ok = True

    for scope in scopes:

        result: dict[str, Any] = run_refresh_scoped(scope, dry_run=dry_run)

        scope_ok = bool(result.get('ok'))

        print(f"[DAILY_CYCLE] refresh_{scope}={'ok' if scope_ok else 'fail'}")

        if not scope_ok:

            ok = False

    return ok





def _run_closed_market_refresh(*, dry_run: bool) -> bool:

    from scripts.refresh_closed_market_intelligence import run_closed_market_refresh



    result = run_closed_market_refresh(dry_run=dry_run, skip_reports=dry_run)

    ok = bool(result.get('ok'))

    print(f"[DAILY_CYCLE] closed_market_refresh={'ok' if ok else 'fail'}")

    return ok





def run_daily_local_cycle(

    *,

    dry_run: bool = False,

    skip_refresh: bool = False,

    skip_api: bool = False,

    market_aware: bool = True,

    generate_report_pack: bool = False,

    write_report_pack: bool = False,

    closed_market_refresh: bool | None = None,

    skip_closed_market_refresh: bool = False,

) -> bool:

    _apply_local_defaults()

    all_ok = True



    startup_args = ['--skip-api'] if skip_api else []

    code, out = _run_script('daily_startup_check.py', *startup_args)

    _print_step('startup_check', code, out)

    if code != 0:

        all_ok = False



    code, out = _run_script('inspect_market_calendar_router.py')

    _print_step('market_router', code, out)

    if code != 0:

        all_ok = False



    closed_ctx, mode = _is_closed_market_context()

    use_closed_refresh = closed_market_refresh

    if use_closed_refresh is None:

        use_closed_refresh = closed_ctx and market_aware



    if not skip_refresh:

        if use_closed_refresh and not skip_closed_market_refresh:

            print('[DAILY_CYCLE] refresh_mode=closed_market_intelligence')

            if not _run_closed_market_refresh(dry_run=dry_run):

                all_ok = False

        else:

            scopes = _resolve_refresh_scopes(market_aware=market_aware)

            if scopes:

                print(f'[DAILY_CYCLE] refresh_scopes={",".join(scopes)} dry_run={dry_run}')

                if not _run_refresh_scopes(scopes, dry_run=dry_run):

                    all_ok = False

            elif closed_ctx:

                print('[DAILY_CYCLE] refresh=skipped (market closed; use --closed-market-refresh)')

            else:

                print('[DAILY_CYCLE] refresh=skipped (no scopes)')

    else:

        print('[DAILY_CYCLE] refresh=skipped')



    if dry_run:

        print('[DAILY_CYCLE] report_steps=skipped (dry-run)')

    elif use_closed_refresh and not skip_closed_market_refresh:

        print('[DAILY_CYCLE] report_steps=included_in_closed_refresh')

    else:

        for script in (

            'generate_final_confidence_report.py',

            'inspect_final_confidence.py',

            'validate_market_memory.py',

            'validate_historical_market_memory.py',

        ):

            code, out = _run_script(script)

            _print_step(script.replace('.py', ''), code, out)

            if code != 0:

                all_ok = False



        if closed_ctx or mode.endswith('RESEARCH') or 'RESEARCH' in mode:

            code, out = _run_script(

                'generate_tomorrow_watchlist.py',

                '--refresh-final-confidence',

                '--limit',

                '25',

            )

            _print_step('tomorrow_watchlist', code, out)

            if code != 0:

                all_ok = False



    if generate_report_pack:

        if dry_run and not write_report_pack:

            print('[DAILY_CYCLE] report_pack=skipped (dry-run; pass --write-report-pack to write)')

        else:

            pack_args = ['--refresh', '--limit', '25']

            code, out = _run_script('generate_daily_report_pack.py', *pack_args, timeout=900)

            _print_step('daily_report_pack', code, out)

            if code != 0:

                all_ok = False



    return all_ok





def main() -> int:

    parser = argparse.ArgumentParser(description='Run local daily intelligence cycle.')

    parser.add_argument('--dry-run', action='store_true', help='Plan only; skip report generation')

    parser.add_argument('--skip-refresh', action='store_true', help='Skip refresh_local_intelligence steps')

    parser.add_argument('--skip-api', action='store_true', help='Pass --skip-api to startup check')

    parser.add_argument(

        '--market-aware',

        action='store_true',

        default=True,

        help='Choose refresh scopes from market router (default: on)',

    )

    parser.add_argument(

        '--no-market-aware',

        action='store_true',

        help='Use memory-only refresh scope',

    )

    parser.add_argument(

        '--closed-market-refresh',

        action='store_true',

        help='Force closed-market intelligence refresh (news/global/external; no live prices)',

    )

    parser.add_argument(

        '--skip-closed-market-refresh',

        action='store_true',

        help='Skip automatic closed-market refresh even when market is closed',

    )

    parser.add_argument(

        '--generate-report-pack',

        action='store_true',

        help='Generate daily report pack after cycle steps',

    )

    parser.add_argument(

        '--write-report-pack',

        action='store_true',

        help='Allow writing report pack during dry-run',

    )

    args = parser.parse_args()



    market_aware = not args.no_market_aware

    closed_refresh = True if args.closed_market_refresh else None



    ok = run_daily_local_cycle(

        dry_run=args.dry_run,

        skip_refresh=args.skip_refresh,

        skip_api=args.skip_api,

        market_aware=market_aware,

        generate_report_pack=args.generate_report_pack,

        write_report_pack=args.write_report_pack,

        closed_market_refresh=closed_refresh,

        skip_closed_market_refresh=args.skip_closed_market_refresh,

    )



    if ok:

        print('DAILY_LOCAL_CYCLE_OK')

        return 0



    print('DAILY_LOCAL_CYCLE_FAIL', file=sys.stderr)

    return 1





if __name__ == '__main__':

    raise SystemExit(main())

