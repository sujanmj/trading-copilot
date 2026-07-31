#!/usr/bin/env python3
"""Unit tests for premarket alerts — isolated session-mode coverage (pre-open / live / after-hours)."""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

FORBIDDEN = ('buy now', 'invest now', 'guaranteed')
REQUIRED_ALWAYS = ('no blind entry', 'watch for entry')
IST = ZoneInfo('Asia/Kolkata')
SESSION_DATE = '2099-07-28'  # Tuesday

# Representative IST session times on the same weekday.
PREOPEN_NOW = datetime(2099, 7, 28, 8, 30, 0, tzinfo=IST)
MARKET_HOURS_NOW = datetime(2099, 7, 28, 10, 30, 0, tzinfo=IST)
AFTER_HOURS_NOW = datetime(2099, 7, 28, 17, 0, 0, tzinfo=IST)

# Production market-mode codes/labels from market_calendar_router + premarket_conviction.
MODE_PREMARKET = {
    'market_mode': 'INDIA_PREMARKET_MODE',
    'mode_code': 'INDIA_PREMARKET_MODE',
}
MODE_MARKET_HOURS = {
    'market_mode': 'INDIA_MARKET_HOURS',
    'mode_code': 'INDIA_MARKET_HOURS',
}
MODE_AFTER_HOURS = {
    'market_mode': 'INDIA_AFTER_HOURS',
    'mode_code': 'INDIA_AFTER_HOURS_MODE',
}

TITLE_PREMARKET = 'PREMARKET TOP SETUPS'
TITLE_PREMARKET_FULL = 'PREMARKET FULL BRIEF'
TITLE_LIVE_WATCH = 'LIVE MARKET WATCH'
TITLE_LIVE_BRIEF = 'LIVE MARKET BRIEF'
TITLE_AFTER_HOURS = 'AFTER-HOURS WATCH'
TITLE_AFTER_HOURS_FULL = 'AFTER-HOURS FULL BRIEF'

PASS_MARKERS: list[str] = []


def _fail(msg: str) -> int:
    print(f'PREMARKET_ALERTS_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _pass(marker: str) -> None:
    if marker not in PASS_MARKERS:
        PASS_MARKERS.append(marker)
    print(marker)


def _safe_trunc(text: str, limit: int = 240) -> str:
    blob = str(text or '').replace('\n', '\\n')
    if len(blob) > limit:
        return blob[: limit - 3] + '...'
    return blob


def _command_fail(msg: str, results: Any) -> int:
    if isinstance(results, list) and results:
        last = results[-1] if isinstance(results[-1], dict) else {}
        last_text = last.get('text', '') if isinstance(last, dict) else ''
        detail = (
            f'{msg} | command_result_type={type(results).__name__} '
            f'command_result_repr={_safe_trunc(repr(results), 180)} '
            f'captured_messages={len(results)} '
            f'last_message={_safe_trunc(last_text)}'
        )
    else:
        detail = (
            f'{msg} | command_result_type={type(results).__name__} '
            f'command_result_repr={_safe_trunc(repr(results), 180)} '
            f'captured_messages={0 if not results else "n/a"} '
            f'last_message='
        )
    return _fail(detail)


def _setup(ticker: str, score: int) -> dict[str, Any]:
    return {
        'ticker': ticker,
        'score': score,
        'setup': 'WATCH',
        'reasons': [
            f'{ticker} fixture scanner move +5.0% · vol 2.0x',
            'Confirm only if price strength + volume + sector support',
        ],
        'source': 'scanner',
        'direction': 'BULLISH',
    }


def _base_report(*, moment: datetime, mode_info: dict[str, Any], market_status: str) -> dict[str, Any]:
    return {
        'stage': '46H-ISOLATED',
        'session_date': SESSION_DATE,
        'date': SESSION_DATE,
        'generated_at': moment.isoformat(),
        'market_bias': 'Neutral',
        'top_setups': [
            _setup('ALPHA', 82),
            _setup('BETA', 78),
            _setup('GAMMA', 74),
        ],
        'deferred_weak_volume': [],
        'avoid': [],
        'market_mode': dict(mode_info),
        'freshness_ok': True,
        'freshness_header': '',
        'stale_keys': [],
        'non_critical_stale_keys': [],
        'hard_stale_lock': False,
        'riskoff_premarket': False,
        'weekend_research_mode': False,
        'previous_session_movers': [],
        'cache_age_hours': 0.5,
        'cache_stale_message': '',
        'overnight_global': {
            'sentiment': {'summary': 'Neutral', 'bias': 'Cautious'},
            'sentiment_formatted': 'Neutral · Cautious',
            'us_close': 'flat fixture close',
        },
        'sector_cues': {'bullish': ['IT'], 'bearish': ['Metals']},
        'india_news_count': 0,
        'govt_high_impact': 0,
        'broker_sentiment': 'Neutral fixture',
        'scanner_status': 'fresh',
        'market_status': market_status,
    }


def preopen_fixture_report() -> dict[str, Any]:
    return _base_report(moment=PREOPEN_NOW, mode_info=MODE_PREMARKET, market_status='pre_open')


def market_hours_fixture_report() -> dict[str, Any]:
    return _base_report(
        moment=MARKET_HOURS_NOW,
        mode_info=MODE_MARKET_HOURS,
        market_status='market_hours',
    )


def after_hours_fixture_report() -> dict[str, Any]:
    return _base_report(
        moment=AFTER_HOURS_NOW,
        mode_info=MODE_AFTER_HOURS,
        market_status='after_hours',
    )


def stale_fixture_report() -> dict[str, Any]:
    """Stale-lock at deterministic pre-open — independent of after-hours wording."""
    report = preopen_fixture_report()
    report['freshness_ok'] = False
    report['freshness_header'] = 'STALE FEEDS — PREMARKET WATCHLIST ONLY'
    report['hard_stale_lock'] = True
    report['stale_keys'] = ['scanner']
    report['cache_age_hours'] = 18.0
    report['cache_stale_message'] = 'Cache is stale — run /refresh full for updated research.'
    report['previous_session_movers'] = deepcopy(report['top_setups'])
    report['scanner_status'] = 'stale'
    return report


@contextmanager
def _premarket_clock_at(moment: datetime) -> Iterator[datetime]:
    from scripts._test_runtime_isolation import premarket_clock_at

    with premarket_clock_at(moment) as frozen:
        yield frozen


@contextmanager
def _repo_data_read_guard(real_root: Path) -> Iterator[list[str]]:
    leaks: list[str] = []
    real_resolved = real_root.resolve()
    original_read_text = Path.read_text
    original_read_bytes = Path.read_bytes
    original_open = Path.open

    def _is_repo_data(path: Path) -> bool:
        try:
            path.resolve().relative_to(real_resolved)
            return True
        except (ValueError, OSError):
            return False

    def _guard_read_text(self, *args, **kwargs):
        if _is_repo_data(self):
            leaks.append(str(self))
            raise RuntimeError(f'repo data read blocked: {self}')
        return original_read_text(self, *args, **kwargs)

    def _guard_read_bytes(self, *args, **kwargs):
        if _is_repo_data(self):
            leaks.append(str(self))
            raise RuntimeError(f'repo data read blocked: {self}')
        return original_read_bytes(self, *args, **kwargs)

    def _guard_open(self, *args, **kwargs):
        if _is_repo_data(self):
            leaks.append(str(self))
            raise RuntimeError(f'repo data open blocked: {self}')
        return original_open(self, *args, **kwargs)

    with patch.object(Path, 'read_text', _guard_read_text), patch.object(
        Path, 'read_bytes', _guard_read_bytes
    ), patch.object(Path, 'open', _guard_open):
        yield leaks


@contextmanager
def _send_boundary_recorder(send_fn: Callable[..., dict]) -> Iterator[list[dict]]:
    captured: list[dict] = []

    def _wrapped(text: str, *args, **kwargs) -> dict:
        result = send_fn(text, *args, **kwargs)
        captured.append(
            {
                'text': text,
                'result': result,
                'dry_run': kwargs.get('dry_run'),
                'command': kwargs.get('command'),
            }
        )
        return result

    with patch(
        'backend.telegram.telegram_analysis_bot.send_analysis_message',
        side_effect=_wrapped,
    ):
        yield captured


def _assert_no_forbidden(text: str) -> str | None:
    lower = str(text or '').lower()
    for bad in FORBIDDEN:
        if bad in lower:
            return f'forbidden phrase in message: {bad}'
    if 'no blind entry' not in lower:
        return 'missing required phrase: no blind entry'
    if 'watch for entry' not in lower and 'wait for volume' not in lower:
        return 'missing watch/wait entry phrasing'
    return None


def test_command_result_contract(results: Any) -> int:
    if not isinstance(results, list):
        return _command_fail('handler must return list', results)
    if len(results) != 1:
        return _command_fail(f'expected exactly 1 logical response, got {len(results)}', results)
    item = results[0]
    if not isinstance(item, dict):
        return _command_fail('handler list item must be dict', results)
    for key in ('ok', 'sent', 'dry_run', 'text'):
        if key not in item:
            return _command_fail(f'missing contract field {key!r}', results)
    if item.get('ok') is not True:
        return _command_fail('ok must be True for dry_run success', results)
    if item.get('dry_run') is not True:
        return _command_fail('dry_run must be True in focused test', results)
    if item.get('sent') is not False:
        return _command_fail('sent must be False in dry_run', results)
    if not isinstance(item.get('text'), str) or not str(item.get('text')).strip():
        return _command_fail('text must be non-empty str', results)
    _pass('PREMARKET_COMMAND_CONTRACT_OK')
    return 0


def test_send_stub_contract(captured: list[dict], *, expected: int = 1) -> int:
    if len(captured) != expected:
        return _fail(f'send stub expected {expected} message(s), got {len(captured)}')
    for row in captured:
        result = row.get('result') or {}
        if not isinstance(result, dict):
            return _fail(f'send stub must return dict, got {type(result).__name__}')
        if result.get('ok') is not True:
            return _fail('send stub ok must be True')
        if result.get('dry_run') is not True:
            return _fail('send stub dry_run must be True')
        if result.get('sent') is not False:
            return _fail('send stub sent must be False')
        if not isinstance(result.get('text'), str):
            return _fail('send stub text must be str')
    _pass('PREMARKET_SEND_STUB_CONTRACT_OK')
    return 0


def _run_isolated_command(
    command: str,
    *,
    report: dict[str, Any],
    moment: datetime,
) -> tuple[int, Any, list[dict], str]:
    from backend.telegram.telegram_analysis_bot import handle_analysis_command, send_analysis_message

    with _premarket_clock_at(moment), patch(
        'backend.analytics.premarket_conviction.build_premarket_conviction_report',
        return_value=report,
    ), _send_boundary_recorder(send_analysis_message) as captured:
        results = handle_analysis_command(command, 'test', dry_run=True)
        rc = test_command_result_contract(results)
        if rc:
            return rc, results, captured, ''
        rc = test_send_stub_contract(captured, expected=1)
        if rc:
            return rc, results, captured, ''
        text = str(results[0]['text'])
        err = _assert_no_forbidden(text)
        if err:
            return _command_fail(err, results), results, captured, text
        return 0, results, captured, text


def test_premarket_preopen_command_isolated() -> int:
    rc, results, _captured, text = _run_isolated_command(
        '/premarket',
        report=preopen_fixture_report(),
        moment=PREOPEN_NOW,
    )
    if rc:
        return rc
    upper = text.upper()
    if TITLE_PREMARKET not in upper:
        return _command_fail(f'pre-open missing title {TITLE_PREMARKET!r}', results)
    if TITLE_AFTER_HOURS in upper or TITLE_LIVE_WATCH in upper:
        return _command_fail('pre-open must not use live/after-hours title', results)
    if '08:30' not in text:
        return _command_fail('pre-open clock must render 08:30 slot label', results)
    if 'ALPHA' not in text or 'BETA' not in text or 'GAMMA' not in text:
        return _command_fail('pre-open response missing fixture setups', results)
    _pass('PREMARKET_PREOPEN_COMMAND_ISOLATED_OK')
    return 0


def test_premarket_full_preopen_command_isolated() -> int:
    rc, results, _captured, text = _run_isolated_command(
        '/premarket full',
        report=preopen_fixture_report(),
        moment=PREOPEN_NOW,
    )
    if rc:
        return rc
    upper = text.upper()
    if TITLE_PREMARKET_FULL not in upper:
        return _command_fail(f'pre-open full missing title {TITLE_PREMARKET_FULL!r}', results)
    if 'US/global context only' not in text:
        return _command_fail('pre-open full missing US/global context-only label', results)
    if '{' in text and '}' in text and "'summary'" in text:
        return _command_fail('premarket full must not contain raw dict', results)
    _pass('PREMARKET_FULL_PREOPEN_COMMAND_ISOLATED_OK')
    return 0


def test_premarket_market_hours_command_isolated() -> int:
    rc, results, _captured, text = _run_isolated_command(
        '/premarket',
        report=market_hours_fixture_report(),
        moment=MARKET_HOURS_NOW,
    )
    if rc:
        return rc
    upper = text.upper()
    if TITLE_LIVE_WATCH not in upper:
        return _command_fail(f'market-hours missing title {TITLE_LIVE_WATCH!r}', results)
    if TITLE_PREMARKET in upper or TITLE_AFTER_HOURS in upper:
        return _command_fail('market-hours must not use premarket/after-hours title', results)
    if '10:30' not in text:
        return _command_fail('market-hours clock must render 10:30 slot label', results)
    _pass('PREMARKET_MARKET_HOURS_COMMAND_ISOLATED_OK')
    return 0


def test_premarket_full_market_hours_command_isolated() -> int:
    rc, results, _captured, text = _run_isolated_command(
        '/premarket full',
        report=market_hours_fixture_report(),
        moment=MARKET_HOURS_NOW,
    )
    if rc:
        return rc
    upper = text.upper()
    if TITLE_LIVE_BRIEF not in upper:
        return _command_fail(f'market-hours full missing title {TITLE_LIVE_BRIEF!r}', results)
    if 'US/global context only' not in text:
        return _command_fail('market-hours full missing US/global context-only label', results)
    _pass('PREMARKET_FULL_MARKET_HOURS_COMMAND_ISOLATED_OK')
    return 0


def test_premarket_after_hours_command_isolated() -> int:
    rc, results, _captured, text = _run_isolated_command(
        '/premarket',
        report=after_hours_fixture_report(),
        moment=AFTER_HOURS_NOW,
    )
    if rc:
        return rc
    upper = text.upper()
    if TITLE_AFTER_HOURS not in upper:
        return _command_fail(f'after-hours missing title {TITLE_AFTER_HOURS!r}', results)
    if TITLE_PREMARKET in upper:
        return _command_fail('after-hours must not use PREMARKET TOP title', results)
    if TITLE_LIVE_WATCH in upper:
        return _command_fail('after-hours must not use LIVE MARKET WATCH title', results)
    if '17:00' not in text:
        return _command_fail('after-hours clock must render 17:00 slot label', results)
    _pass('PREMARKET_AFTER_HOURS_COMMAND_ISOLATED_OK')
    return 0


def test_premarket_full_after_hours_command_isolated() -> int:
    rc, results, _captured, text = _run_isolated_command(
        '/premarket full',
        report=after_hours_fixture_report(),
        moment=AFTER_HOURS_NOW,
    )
    if rc:
        return rc
    upper = text.upper()
    if TITLE_AFTER_HOURS_FULL not in upper:
        return _command_fail(
            f'after-hours full missing title {TITLE_AFTER_HOURS_FULL!r}',
            results,
        )
    if 'US/global context only' not in text:
        return _command_fail('after-hours full missing US/global context-only label', results)
    _pass('PREMARKET_FULL_AFTER_HOURS_COMMAND_ISOLATED_OK')
    return 0


def test_session_clock_patch_changes_rendered_mode() -> int:
    """Prove 08:30 / 10:30 / 17:00 clocks + matching fixtures yield distinct mode titles."""
    cases = (
        (PREOPEN_NOW, preopen_fixture_report(), TITLE_PREMARKET),
        (MARKET_HOURS_NOW, market_hours_fixture_report(), TITLE_LIVE_WATCH),
        (AFTER_HOURS_NOW, after_hours_fixture_report(), TITLE_AFTER_HOURS),
    )
    texts: list[str] = []
    for moment, report, expected in cases:
        rc, results, _captured, text = _run_isolated_command(
            '/premarket',
            report=report,
            moment=moment,
        )
        if rc:
            return rc
        if expected not in text.upper():
            return _command_fail(f'session transition missing {expected!r}', results)
        texts.append(text)

    preopen_text, market_text, after_hours_text = texts
    if preopen_text == market_text:
        return _fail('pre-open and market-hours texts must differ')
    if market_text == after_hours_text:
        return _fail('market-hours and after-hours texts must differ')
    if preopen_text == after_hours_text:
        return _fail('pre-open and after-hours texts must differ')
    if TITLE_PREMARKET not in preopen_text.upper():
        return _fail('pre-open transition text missing PREMARKET title')
    if TITLE_LIVE_WATCH not in market_text.upper():
        return _fail('market-hours transition text missing LIVE MARKET WATCH')
    if TITLE_AFTER_HOURS not in after_hours_text.upper():
        return _fail('after-hours transition text missing AFTER-HOURS WATCH')
    _pass('PREMARKET_SESSION_MODE_TRANSITION_OK')
    return 0


def test_premarket_stale_command_isolated() -> int:
    rc, results, _captured, text = _run_isolated_command(
        '/premarket',
        report=stale_fixture_report(),
        moment=PREOPEN_NOW,
    )
    if rc:
        return rc
    upper = text.upper()
    if 'STALE' not in upper and 'PREMARKET WATCHLIST' not in upper:
        return _command_fail('stale path missing stale-lock wording', results)
    if 'PREMARKET' not in upper:
        return _command_fail('stale path must still expose PREMARKET token', results)
    if TITLE_AFTER_HOURS in upper:
        return _command_fail('stale pre-open fixture must not render after-hours title', results)
    _pass('PREMARKET_STALE_COMMAND_ISOLATED_OK')
    return 0


def test_formatter_and_scheduler_invariants() -> int:
    from backend.analytics.premarket_conviction import (
        _apply_conflict_guard,
        _apply_volume_caps,
        _format_sentiment_value,
        format_premarket_telegram,
    )
    from backend.telegram.premarket_scheduler import (
        OPENING_MORNING_SLOTS,
        OPENING_SCHEDULE_LABELS,
        PREMARKET_SLOTS,
        SCHEDULE_DISPLAY,
    )
    from backend.telegram.telegram_analysis_bot import HELP_TEXT

    report = preopen_fixture_report()
    with _premarket_clock_at(PREOPEN_NOW):
        text = format_premarket_telegram(full=False, report=report)
        lower = text.lower()
        for phrase in REQUIRED_ALWAYS:
            if phrase not in lower:
                return _fail(f'missing required phrase: {phrase}')
        if 'confirm after 9:15' not in lower:
            return _fail('missing confirm after 9:15 before market open')
        for bad in FORBIDDEN:
            if bad in lower:
                return _fail(f'forbidden phrase in message: {bad}')

        full = format_premarket_telegram(full=True, report=report)
        if TITLE_PREMARKET_FULL not in full.upper():
            return _fail('full premarket format missing PREMARKET FULL marker')
        if '{' in full and '}' in full and "'summary'" in full:
            return _fail('premarket full must not contain raw dict')
        if 'US/global context only' not in full:
            return _fail('full premarket missing US/global context-only label')

    sent = _format_sentiment_value({'summary': 'Neutral', 'bias': 'Cautious'})
    if '{' in sent:
        return _fail('sentiment formatter leaked dict')

    capped, deferred_low = _apply_volume_caps(
        [{'ticker': 'ABC', 'score': 80, 'setup': 'WATCH', 'reasons': []}],
        {'top_signals': [{'ticker': 'ABC', 'volume_ratio': 0.25}]},
        {},
    )
    if not deferred_low and (not capped or capped[0].get('tier_cap') != 'not_top3'):
        return _fail('vol<0.3 should cap top3 or defer')
    _capped2, deferred = _apply_volume_caps(
        [{'ticker': 'ABC', 'score': 80, 'setup': 'WATCH', 'reasons': []}],
        {'top_signals': [{'ticker': 'ABC', 'volume_ratio': 0.25}]},
        {},
    )
    if not deferred:
        return _fail('vol<0.3 should defer from top watch')

    conflicted = _apply_conflict_guard(
        [{'ticker': 'XYZ', 'score': 70, 'setup': 'WATCH'}],
        [{'ticker': 'XYZ', 'reason': 'weak'}],
    )
    if conflicted and conflicted[0].get('setup') != 'Conflict/Wait':
        return _fail('top watch + avoid should be Conflict/Wait')

    expected_times = {(7, 45), (8, 0), (8, 15), (8, 30), (8, 45)}
    slot_times = set(PREMARKET_SLOTS.values())
    if not expected_times.issubset(slot_times):
        return _fail(f'scheduler missing build slots: {expected_times - slot_times}')
    if (9, 10) in slot_times:
        return _fail('09:10 pre-open alert must not exist')
    opening_times = set(OPENING_MORNING_SLOTS.values())
    if opening_times != {(9, 0), (9, 20), (9, 25), (9, 31)}:
        return _fail(f'unexpected opening morning slots: {opening_times}')
    if len(OPENING_SCHEDULE_LABELS) != 4:
        return _fail('opening schedule labels incomplete')
    if len(SCHEDULE_DISPLAY) < 9:
        return _fail('schedule display incomplete')
    if '/premarket' not in HELP_TEXT:
        return _fail('/premarket missing from help')
    if '/premarket full' not in HELP_TEXT.lower() and 'premarket full' not in HELP_TEXT.lower():
        return _fail('/premarket full missing from help')
    return 0


def test_actual_repository_data_not_read(real_root: Path) -> int:
    from backend.telegram.telegram_analysis_bot import handle_analysis_command, send_analysis_message

    report = after_hours_fixture_report()
    with _repo_data_read_guard(real_root) as leaks, _premarket_clock_at(AFTER_HOURS_NOW), patch(
        'backend.analytics.premarket_conviction.build_premarket_conviction_report',
        return_value=report,
    ), _send_boundary_recorder(send_analysis_message):
        results = handle_analysis_command('/premarket', 'test', dry_run=True)
        if not results:
            return _fail('guarded /premarket produced no results')
        if TITLE_AFTER_HOURS not in str(results[0].get('text', '')).upper():
            return _fail('guarded after-hours path missing AFTER-HOURS title')
        if leaks:
            return _fail(f'repository data read attempted: {leaks[:5]}')
    _pass('PREMARKET_REPO_DATA_NOT_READ_OK')
    return 0


def test_actual_repository_data_not_mutated(
    before: dict[str, tuple[int, int]],
    after: dict[str, tuple[int, int]],
    git_before: str,
    git_after: str,
) -> int:
    if git_before != git_after:
        return _fail(
            'git status --short -- data changed during focused test '
            f'before={git_before!r} after={git_after!r}'
        )
    if before != after:
        changed = sorted(set(before) | set(after))
        diffs = [p for p in changed if before.get(p) != after.get(p)]
        return _fail(f'repository data tree mutated: {diffs[:8]}')
    _pass('PREMARKET_REPO_DATA_NOT_MUTATED_OK')
    return 0


def test_repeated_runs_deterministic() -> int:
    from backend.telegram.telegram_analysis_bot import handle_analysis_command

    report = after_hours_fixture_report()
    texts: list[str] = []
    with _premarket_clock_at(AFTER_HOURS_NOW), patch(
        'backend.analytics.premarket_conviction.build_premarket_conviction_report',
        return_value=report,
    ):
        for _ in range(3):
            results = handle_analysis_command('/premarket', 'test', dry_run=True)
            if not results:
                return _fail('deterministic run produced no results')
            texts.append(results[0]['text'])
    if len(set(texts)) != 1:
        return _fail('repeated /premarket runs are not deterministic')
    if TITLE_AFTER_HOURS not in texts[0].upper():
        return _fail('deterministic after-hours runs missing AFTER-HOURS title')
    _pass('PREMARKET_REPEATED_RUNS_DETERMINISTIC_OK')
    return 0


def _git_data_status() -> str:
    proc = subprocess.run(
        ['git', 'status', '--short', '--', 'data'],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    return (proc.stdout or '').strip()


def main() -> int:
    from scripts._test_runtime_isolation import (
        isolated_premarket_data_root,
        snapshot_data_tree,
    )

    git_before = _git_data_status()
    before = snapshot_data_tree()

    with isolated_premarket_data_root() as iso:
        real_root = Path(iso['real_root'])

        rc = test_formatter_and_scheduler_invariants()
        if rc:
            return rc

        for fn in (
            test_premarket_preopen_command_isolated,
            test_premarket_full_preopen_command_isolated,
            test_premarket_market_hours_command_isolated,
            test_premarket_full_market_hours_command_isolated,
            test_premarket_after_hours_command_isolated,
            test_premarket_full_after_hours_command_isolated,
            test_session_clock_patch_changes_rendered_mode,
            test_premarket_stale_command_isolated,
            test_repeated_runs_deterministic,
        ):
            rc = fn()
            if rc:
                return rc

        rc = test_actual_repository_data_not_read(real_root)
        if rc:
            return rc

    after = snapshot_data_tree()
    git_after = _git_data_status()
    rc = test_actual_repository_data_not_mutated(before, after, git_before, git_after)
    if rc:
        return rc

    required = {
        'PREMARKET_PREOPEN_COMMAND_ISOLATED_OK',
        'PREMARKET_FULL_PREOPEN_COMMAND_ISOLATED_OK',
        'PREMARKET_MARKET_HOURS_COMMAND_ISOLATED_OK',
        'PREMARKET_FULL_MARKET_HOURS_COMMAND_ISOLATED_OK',
        'PREMARKET_AFTER_HOURS_COMMAND_ISOLATED_OK',
        'PREMARKET_FULL_AFTER_HOURS_COMMAND_ISOLATED_OK',
        'PREMARKET_SESSION_MODE_TRANSITION_OK',
        'PREMARKET_STALE_COMMAND_ISOLATED_OK',
        'PREMARKET_COMMAND_CONTRACT_OK',
        'PREMARKET_SEND_STUB_CONTRACT_OK',
        'PREMARKET_REPO_DATA_NOT_READ_OK',
        'PREMARKET_REPO_DATA_NOT_MUTATED_OK',
        'PREMARKET_REPEATED_RUNS_DETERMINISTIC_OK',
    }
    missing = sorted(required - set(PASS_MARKERS))
    if missing:
        return _fail(f'missing pass markers: {missing}')

    _pass('PREMARKET_ISOLATION_OK')
    print('PREMARKET_ALERTS_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
