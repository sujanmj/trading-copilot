#!/usr/bin/env python3
"""Stage 51A/51C — production analysis bot canonical command routing (filename kept for compatibility)."""

from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')


def _fail(msg: str) -> int:
    print(f'TELEGRAM_STAGE_51A_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.analytics.budget_impact import CACHE_FILE as BUDGET_CACHE_FILE, refresh_budget_intel
    from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD, get_astraedge_build_stage
    from backend.intelligence.stock_catalyst_radar import CACHE_FILE as CATALYST_CACHE_FILE, build_catalyst_radar
    from backend.telegram.lazy_command_runner import STAGE_MARKER, run_budget_only, run_catalysts_only
    from backend.telegram.telegram_analysis_bot import handle_analysis_command

    if STAGE_MARKER != 'TELEGRAM_STAGE_51A_CANONICAL_REFRESH_STATUS':
        return _fail(f'unexpected STAGE_MARKER: {STAGE_MARKER!r}')
    build_stage = get_astraedge_build_stage()
    if build_stage not in ('51A', '51B', '51C', '51D', '51E', '51G', '51H', '51I', '51J', '51K', '51L', '51M', '51N', '51O', '51P', '51Q', '51R', '51S', '51T', '51U', '51V', '51W', '51X', '51Y', '51Z', '52A', '52B', '52C'):
        return _fail(f'unexpected build stage: {build_stage!r}')
    if not ASTRAEDGE_TELEGRAM_BUILD.startswith('AstraEdge '):
        return _fail(f'unexpected build label: {ASTRAEDGE_TELEGRAM_BUILD!r}')
    if ASTRAEDGE_TELEGRAM_BUILD != f'AstraEdge {build_stage}':
        return _fail(
            f'build label {ASTRAEDGE_TELEGRAM_BUILD!r} != stage {build_stage!r}'
        )

    bot_src = (PROJECT_ROOT / 'backend/telegram/telegram_analysis_bot.py').read_text(encoding='utf-8')
    if 'run_canonical_full_refresh' not in bot_src:
        return _fail('telegram_analysis_bot must wire run_canonical_full_refresh')
    if 'format_canonical_status_text' not in bot_src:
        return _fail('telegram_analysis_bot must wire format_canonical_status_text')
    if '_scoped_refresh(\'closed-market\')' in bot_src:
        return _fail('/refresh full must not use closed-market scoped refresh')

    refresh_src = inspect.getsource(refresh_budget_intel)
    if 'CACHE_FILE' not in refresh_src:
        return _fail('refresh_budget_intel must write CACHE_FILE')
    if str(BUDGET_CACHE_FILE).endswith('budget_impact_cache.json'):
        pass
    else:
        return _fail(f'unexpected budget cache path: {BUDGET_CACHE_FILE}')
    budget_overview_src = inspect.getsource(
        __import__('backend.analytics.budget_impact', fromlist=['get_budget_overview']).get_budget_overview
    )
    if 'CACHE_FILE' not in budget_overview_src and '_load_cache' not in budget_overview_src:
        return _fail('get_budget_overview must read canonical budget cache')
    listener_src = (
        PROJECT_ROOT / 'backend/orchestration/telegram_listener.py'
    ).read_text(encoding='utf-8')
    if 'refresh_budget_intel' not in listener_src:
        return _fail('telegram_listener full refresh must call refresh_budget_intel')
    if 'build_catalyst_radar' not in listener_src:
        return _fail('telegram_listener full refresh must call build_catalyst_radar')

    catalyst_build_src = inspect.getsource(build_catalyst_radar)
    if 'CACHE_FILE' not in catalyst_build_src:
        return _fail('build_catalyst_radar must persist via CACHE_FILE')

    mock_caches = [
        {'cache': 'runtime_snapshot', 'status': 'rebuilt'},
        {'cache': 'latest_news', 'status': 'rebuilt'},
        {'cache': 'budget', 'status': 'rebuilt'},
        {'cache': 'theme_catalyst', 'status': 'rebuilt'},
        {'cache': 'catalyst_radar', 'status': 'rebuilt'},
        {'cache': 'aihub_brain', 'status': 'rebuilt'},
        {'cache': 'aihub_govt', 'status': 'rebuilt'},
        {'cache': 'aihub_market', 'status': 'rebuilt'},
        {'cache': 'broker', 'status': 'skipped'},
    ]
    with patch(
        'backend.telegram.telegram_analysis_bot.run_canonical_full_refresh',
        return_value={
            'text': (
                '<b>✅ Full refresh complete</b>\n'
                '• Runtime snapshot: rebuilt/fresh\n'
                '• News: rebuilt/fresh\n'
                '• Budget: rebuilt/fresh\n'
                '• Theme catalysts: rebuilt/fresh\n'
                '• Catalysts: rebuilt/fresh\n'
                '• AIHub brain: rebuilt/fresh\n'
                '• AIHub govt: rebuilt/fresh\n'
                '• AIHub market: rebuilt/fresh\n'
                '• Broker (optional/skipped): skipped'
            ),
            'payload': {'caches': mock_caches},
        },
    ) as mock_full:
        results = handle_analysis_command('/refresh full', 'test', dry_run=True)
        mock_full.assert_called_once()

    refresh_text = str(results[0].get('text', '')) if results else ''
    for label in (
        'Runtime snapshot',
        'News',
        'Budget',
        'Theme catalysts',
        'Catalysts',
        'AIHub brain',
        'AIHub govt',
        'AIHub market',
        'Broker',
    ):
        if label not in refresh_text:
            return _fail(f'/refresh full response missing cache label: {label}')

    canonical_status = (
        '<b>📡 System Status</b>\n'
        'State: <code>OPEN</code>\n'
        f'Telegram build: <code>{ASTRAEDGE_TELEGRAM_BUILD}</code>'
    )
    with patch(
        'backend.telegram.telegram_analysis_bot.format_canonical_status_text',
        return_value=canonical_status,
    ) as mock_status:
        with patch('backend.telegram.response_format.format_status_text') as legacy_status:
            status_results = handle_analysis_command('/status', 'test', dry_run=True)
            mock_status.assert_called_once()
            legacy_status.assert_not_called()

    status_text = str(status_results[0].get('text', ''))
    if '📡 System Status' not in status_text:
        return _fail('/status must use canonical runtime status formatter')
    if ASTRAEDGE_TELEGRAM_BUILD not in status_text:
        return _fail(f'/status missing {ASTRAEDGE_TELEGRAM_BUILD} build line')

    health = handle_analysis_command('/health', 'test', dry_run=True)
    health_text = str(health[0].get('text', ''))
    if 'Active bot: <code>telegram_analysis_bot</code>' not in health_text:
        return _fail('/health missing active bot label')
    if 'Command router: <code>canonical</code>' not in health_text:
        return _fail('/health missing canonical router label')
    if ASTRAEDGE_TELEGRAM_BUILD not in health_text:
        return _fail(f'/health missing {ASTRAEDGE_TELEGRAM_BUILD}')

    budget_runner_src = inspect.getsource(run_budget_only)
    if 'handle_budget_command' not in budget_runner_src:
        return _fail('run_budget_only must delegate to handle_budget_command')
    catalyst_runner_src = inspect.getsource(run_catalysts_only)
    if 'format_catalyst_radar_telegram' not in catalyst_runner_src:
        return _fail('run_catalysts_only must delegate to format_catalyst_radar_telegram')

    if BUDGET_CACHE_FILE.name != 'budget_impact_cache.json':
        return _fail('budget cache file name mismatch')
    if run_budget_only.__module__ != 'backend.telegram.lazy_command_runner':
        return _fail('budget command must route through lazy_command_runner.run_budget_only')
    if CATALYST_CACHE_FILE.name != 'stock_catalyst_radar_latest.json':
        return _fail('catalyst cache file name mismatch')

    radar_text = (
        '<b>OPENING RALLY RADAR</b>\n'
        '1. RAILTEL — VOLUME IGNITION\n'
        '   Score: 78'
    )
    tradecards_text = (
        '<b>TRADECARDS — TOP CANDIDATES</b>\n'
        '1. RAILTEL — MOMENTUM-ONLY WATCH — Score 78\n'
        '2. RVNL — WAIT FOR VOLUME — Score 68'
    )
    tradecard_text = '<b>Trade Card</b>\nRAILTEL — selected best single candidate'
    with patch(
        'backend.telegram.lazy_command_runner.run_radar_only',
        return_value={'text': radar_text},
    ) as mock_radar:
        radar_results = handle_analysis_command('/radar', 'test', dry_run=True)
        mock_radar.assert_called_once()
    if 'Opening Rally Radar' not in str(radar_results[0].get('text', '')) and 'OPENING RALLY RADAR' not in str(radar_results[0].get('text', '')):
        return _fail('/radar must route to opening rally radar formatter')

    with patch('backend.telegram.lazy_command_runner.run_radar_only') as mock_opening_only:
        opening_only = handle_analysis_command('/opening', 'test', dry_run=True)
        mock_opening_only.assert_not_called()
    if 'Use /radar for opening rally candidates.' not in str(opening_only[0].get('text', '')):
        return _fail('/opening must return redirect to /radar')

    with patch('backend.telegram.lazy_command_runner.run_radar_only') as mock_opening_radar:
        opening_radar_results = handle_analysis_command('/opening radar', 'test', dry_run=True)
        mock_opening_radar.assert_not_called()
    if 'Use /radar for opening rally candidates.' not in str(opening_radar_results[0].get('text', '')):
        return _fail('/opening radar must return redirect to /radar')

    from backend.telegram.telegram_analysis_bot import HELP_TEXT, TELEGRAM_BOT_COMMANDS, register_telegram_bot_commands

    for token in ('/radar', '/tradecards', '/tradecard'):
        if token not in HELP_TEXT:
            return _fail(f'help text missing {token}')
    if '/opening' in HELP_TEXT.lower() and 'same as /radar' in HELP_TEXT.lower():
        return _fail('help must not advertise /opening alias')
    cmd_names = {row.get('command') for row in TELEGRAM_BOT_COMMANDS}
    for name in ('radar', 'tradecards', 'tradecard'):
        if name not in cmd_names:
            return _fail(f'TELEGRAM_BOT_COMMANDS missing /{name}')
    if 'opening' in cmd_names:
        return _fail('TELEGRAM_BOT_COMMANDS must not register /opening (use /radar only)')
    with patch('backend.telegram.telegram_analysis_bot.requests.post') as mock_post:
        mock_post.return_value.status_code = 200
        if not register_telegram_bot_commands():
            return _fail('register_telegram_bot_commands must succeed with mocked API')

    with patch(
        'backend.telegram.lazy_command_runner.run_tradecards_only',
        return_value={'text': tradecards_text},
    ) as mock_tradecards:
        tradecards_results = handle_analysis_command('/tradecards', 'test', dry_run=True)
        mock_tradecards.assert_called_once()
    tradecards_out = str(tradecards_results[0].get('text', ''))
    if 'TRADECARDS' not in tradecards_out:
        return _fail('/tradecards must show tradecards board header')
    if tradecards_out.count('Score') < 2:
        return _fail('/tradecards must show multiple candidates')

    with patch(
        'backend.telegram.lazy_command_runner.run_tradecard_only',
        return_value={'text': tradecard_text},
    ) as mock_tradecard:
        tradecard_results = handle_analysis_command('/tradecard', 'test', dry_run=True)
        mock_tradecard.assert_called_once()
    if 'Trade Card' not in str(tradecard_results[0].get('text', '')):
        return _fail('/tradecard must still route to single best tradecard runner')

    print('TELEGRAM_STAGE_51A_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
