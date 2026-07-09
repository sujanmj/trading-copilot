#!/usr/bin/env python3
"""Phase 4B.18H — User feed remove/restore + memory cleanup (AstraEdge 52H)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

COMPANY_FEED_ID = 'c3d1d89b1874'
COMPANY_TICKER = 'RELIANCE'
COMPANY_HEADLINE = 'RELIANCE Q4 results beat estimates with strong margin expansion'

MACRO_FEED_A = 'aabbccddeeff'
MACRO_FEED_B = '112233445566'
MACRO_HEADLINE_A = (
    'Iran ceasefire collapse sends Brent crude surging 8% overnight; '
    'Sensex gap-down risk rises'
)
MACRO_HEADLINE_B = (
    'Euro zone bond yields hit one-month high as oil surge fuels ECB rate hike bets'
)


def _fail(msg: str) -> int:
    print(f'FEED_REMOVE_4B18H_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


@contextmanager
def _isolated_feed_env():
    import sqlite3

    import backend.my_feed.my_feed_db as db_mod

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / 'my_feed.db'
        state_path = Path(tmp) / 'macro_shock_sentinel_state.json'

        def _test_connect():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            return conn

        with patch.object(db_mod, '_connect', _test_connect), patch.object(
            db_mod, 'get_my_feed_db_path', lambda: db_path
        ), patch('backend.trading.macro_shock_sentinel.STATE_FILE', state_path):
            db_mod.init_my_feed_db()
            yield db_path


def _seed_company_feed(feed_id: str | None = None) -> str:
    """Insert a company feed into the isolated DB and verify it exists."""
    from backend.my_feed.my_feed_db import get_item

    fid = str(feed_id or uuid.uuid4().hex[:12]).strip().lower()
    record = _insert_company_feed(fid)
    seeded = str(record.get('feed_id') or fid).strip().lower()
    if not get_item(seeded):
        raise RuntimeError(f'failed to seed company feed {seeded}')
    return seeded


def _insert_company_feed(feed_id: str = COMPANY_FEED_ID) -> dict:
    from backend.my_feed.my_feed_db import insert_feed_item

    return insert_feed_item({
        'feed_id': feed_id,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'source': 'telegram_text',
        'raw_market_text': COMPANY_HEADLINE,
        'cleaned_summary': COMPANY_HEADLINE,
        'tickers': [COMPANY_TICKER],
        'event_type': 'results',
        'sentiment': 'bullish',
        'impact_score': 75.0,
        'urgency': 'medium',
        'suggested_action': 'STOCK NEWS',
        'confirmation_required': False,
        'status': 'active',
        'payload': {
            'verification_status': 'VERIFIED',
            'verified_headline': COMPANY_HEADLINE,
            'catalyst_eligible': True,
            'active': True,
        },
    })


def _insert_macro_feed(
    feed_id: str,
    headline: str,
    *,
    link_active: bool = True,
) -> dict:
    from backend.my_feed.my_feed_db import insert_feed_item
    from backend.trading.macro_shock_sentinel import _merge_active_state, score_macro_severity

    assessment = score_macro_severity(headline, confidence=0.9, direct_market_impact=True)
    record = insert_feed_item({
        'feed_id': feed_id,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'source': 'telegram_text',
        'raw_market_text': headline,
        'cleaned_summary': headline,
        'tickers': [],
        'sectors': [],
        'themes': list(assessment.get('themes') or []),
        'event_type': 'macro_shock',
        'sentiment': 'bearish',
        'impact_score': 85.0,
        'urgency': 'high',
        'suggested_action': 'MACRO SHOCK ALERT',
        'confirmation_required': True,
        'status': 'active',
        'payload': {
            'feed_type': 'macro_shock',
            'macro_severity': assessment.get('severity'),
            'macro_regime': assessment.get('regime'),
            'macro_trigger': assessment.get('trigger'),
            'macro_impact': assessment.get('impact'),
            'gap_down_risk': bool(assessment.get('gap_down_risk')),
            'verification_status': 'UNVERIFIED',
            'active': True,
        },
    })
    if link_active:
        _merge_active_state(assessment, feed_id=feed_id)
    return record


def _seed_macro_feed(
    feed_id: str,
    headline: str,
    *,
    link_active: bool = True,
) -> str:
    from backend.my_feed.my_feed_db import get_item

    record = _insert_macro_feed(feed_id, headline, link_active=link_active)
    seeded = str(record.get('feed_id') or feed_id).strip().lower()
    if not get_item(seeded):
        raise RuntimeError(f'failed to seed macro feed {seeded}')
    return seeded


def test_remove_marks_removed_by_user() -> int:
    from backend.my_feed.feed_remove import remove_feed_item
    from backend.my_feed.my_feed_db import STATUS_REMOVED_BY_USER, get_item

    with _isolated_feed_env():
        feed_id = _seed_company_feed(COMPANY_FEED_ID)
        result = remove_feed_item(feed_id)
        item = get_item(feed_id)
    if not result.get('ok'):
        return _fail(f'remove failed: {result!r}')
    if 'FEED_REMOVED' not in str(result.get('text') or ''):
        return _fail('missing FEED_REMOVED output')
    if item.get('status') != STATUS_REMOVED_BY_USER:
        return _fail(f'expected REMOVED_BY_USER got {item.get("status")!r}')
    if item.get('active') is not False:
        return _fail(f'expected active=false got {item.get("active")!r}')
    return 0


def test_removed_not_in_myfeed_today() -> int:
    from backend.my_feed.feed_processor import list_feed_items
    from backend.my_feed.feed_remove import remove_feed_item

    with _isolated_feed_env():
        feed_id = _seed_company_feed(COMPANY_FEED_ID)
        remove_feed_item(feed_id)
        rows = list_feed_items(limit=20, today_only=True)
    if any(str(r.get('feed_id')) == COMPANY_FEED_ID for r in rows):
        return _fail('removed feed still in myfeed today')
    return 0


def test_removed_not_in_myfeed_scan() -> int:
    from backend.my_feed.feed_processor import scan_feed_summary
    from backend.my_feed.feed_remove import remove_feed_item

    with _isolated_feed_env():
        feed_id = _seed_company_feed(COMPANY_FEED_ID)
        before = scan_feed_summary(today_only=False)
        remove_feed_item(feed_id)
        after = scan_feed_summary(today_only=False)
    if before.get('total', 0) < 1:
        return _fail('scan had no items before remove')
    if after.get('total', 0) != 0:
        return _fail(f'scan still counts removed feed: {after!r}')
    return 0


def test_removed_company_not_in_catalyst_boost() -> int:
    from backend.intelligence.stock_catalyst_radar import _iter_my_feed_text
    from backend.my_feed.feed_remove import remove_feed_item

    with _isolated_feed_env():
        feed_id = _seed_company_feed(COMPANY_FEED_ID)
        before = _iter_my_feed_text()
        remove_feed_item(feed_id)
        after = _iter_my_feed_text()
    if not any(COMPANY_TICKER in str(i.get('headline') or '') for i in before):
        return _fail('company feed missing from catalyst source before remove')
    if any(COMPANY_TICKER in str(i.get('headline') or '') for i in after):
        return _fail('removed company feed still in catalyst boost source')
    return 0


def test_removed_macro_feed_drops_from_macro_today() -> int:
    from backend.my_feed.feed_remove import remove_feed_item
    from backend.trading.macro_shock_sentinel import format_macro_command_telegram

    with _isolated_feed_env():
        _seed_macro_feed(MACRO_FEED_A, MACRO_HEADLINE_A)
        before = format_macro_command_telegram('today')
        remove_feed_item(MACRO_FEED_A)
        after = format_macro_command_telegram('today')
    if 'iran' not in before.lower() and 'crude' not in before.lower():
        return _fail(f'macro today missing feed A before remove: {before[:200]!r}')
    if 'iran' in after.lower() or 'crude' in after.lower():
        return _fail(f'macro today still shows removed feed: {after[:200]!r}')
    return 0


def test_only_macro_removed_returns_normal() -> int:
    from backend.my_feed.feed_remove import remove_feed_item
    from backend.trading.macro_shock_sentinel import format_macro_command_telegram

    with _isolated_feed_env():
        _seed_macro_feed(MACRO_FEED_A, MACRO_HEADLINE_A)
        remove_feed_item(MACRO_FEED_A)
        text = format_macro_command_telegram('')
    if 'Regime:</b> NORMAL' not in text:
        return _fail(f'/macro not NORMAL after only shock removed: {text[:240]!r}')
    if 'Severity:</b> LOW' not in text and 'Severity:</b> WATCH' in text:
        return _fail(f'/macro severity unexpected: {text[:240]!r}')
    return 0


def test_remove_one_macro_keeps_unrelated() -> int:
    from backend.my_feed.feed_remove import remove_feed_item
    from backend.trading.macro_shock_sentinel import get_active_macro_shock

    with _isolated_feed_env():
        _seed_macro_feed(MACRO_FEED_A, MACRO_HEADLINE_A)
        _seed_macro_feed(MACRO_FEED_B, MACRO_HEADLINE_B, link_active=False)
        remove_feed_item(MACRO_FEED_A)
        active = get_active_macro_shock()
    if not active:
        return _fail('unrelated macro shock cleared when removing feed A')
    if str(active.get('feed_id') or '') != MACRO_FEED_B:
        return _fail(f'expected feed B active got {active.get("feed_id")!r}')
    return 0


def test_restore_reactivates_feed() -> int:
    from backend.my_feed.feed_remove import remove_feed_item, restore_feed_item
    from backend.my_feed.my_feed_db import STATUS_ACTIVE, get_item

    with _isolated_feed_env():
        feed_id = _seed_company_feed(COMPANY_FEED_ID)
        remove_feed_item(feed_id)
        restore = restore_feed_item(feed_id)
        item = get_item(feed_id)
    if not restore.get('ok'):
        return _fail(f'restore failed: {restore!r}')
    if 'FEED_RESTORED' not in str(restore.get('text') or ''):
        return _fail('missing FEED_RESTORED output')
    if item.get('status') != STATUS_ACTIVE:
        return _fail(f'expected active status got {item.get("status")!r}')
    if item.get('active') is not True:
        return _fail(f'expected active=true got {item.get("active")!r}')
    return 0


def test_restored_macro_reenters_memory() -> int:
    from backend.my_feed.feed_remove import remove_feed_item, restore_feed_item
    from backend.trading.macro_shock_sentinel import get_active_macro_shock

    with _isolated_feed_env():
        _seed_macro_feed(MACRO_FEED_A, MACRO_HEADLINE_A)
        remove_feed_item(MACRO_FEED_A)
        restore_feed_item(MACRO_FEED_A)
        active = get_active_macro_shock()
    if not active:
        return _fail('macro shock missing after restore')
    if str(active.get('feed_id') or '') != MACRO_FEED_A:
        return _fail(f'expected feed A active got {active.get("feed_id")!r}')
    return 0


def test_delete_alias_works() -> int:
    from backend.my_feed.my_feed_db import STATUS_REMOVED_BY_USER, get_item
    from backend.telegram.lazy_command_runner import run_feed_text_only

    with _isolated_feed_env():
        delete_id = _seed_company_feed('aabbccdd0011')
        result = run_feed_text_only(f'delete {delete_id}')
        item = get_item(delete_id)
    if not result.get('ok'):
        return _fail(f'delete alias failed: {result!r}')
    if item.get('status') != STATUS_REMOVED_BY_USER:
        return _fail('delete alias did not mark REMOVED_BY_USER')
    return 0


def test_missing_feed_returns_not_found() -> int:
    from backend.my_feed.feed_remove import remove_feed_item

    with _isolated_feed_env():
        result = remove_feed_item('deadbeef0001')
    if result.get('code') != 'FEED_NOT_FOUND':
        return _fail(f'expected FEED_NOT_FOUND got {result.get("code")!r}')
    return 0


def test_help_shows_remove_restore() -> int:
    from backend.telegram.telegram_analysis_bot import HELP_TEXT

    if '/feed remove FEED_ID' not in HELP_TEXT:
        return _fail('help missing /feed remove')
    if '/feed restore FEED_ID' not in HELP_TEXT:
        return _fail('help missing /feed restore')
    return 0


def _run(script: str) -> int:
    env = os.environ.copy()
    env['PYTHONPATH'] = str(PROJECT_ROOT)
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / 'scripts' / script)],
        cwd=str(PROJECT_ROOT),
        env=env,
        check=False,
    ).returncode


def test_regression_feed_ticker_resolver_4b18g() -> int:
    if _run('test_feed_ticker_resolver_4b18g.py') != 0:
        return _fail('52E feed ticker resolver regression failed')
    return 0


def test_regression_macro_emergency_4b18f() -> int:
    if _run('test_macro_emergency_persistence_4b18f.py') != 0:
        return _fail('52D macro emergency persistence regression failed')
    return 0


def test_regression_live_confirmation_guard_4b18d() -> int:
    if _run('test_live_confirmation_guard_4b18d.py') != 0:
        return _fail('52B live confirmation guard regression failed')
    return 0


def test_build_label_52h() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 52H' or ASTRAEDGE_BUILD_STAGE != '52H':
        return _fail(f'expected AstraEdge 52H got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    return 0


def main() -> int:
    tests = [
        test_remove_marks_removed_by_user,
        test_removed_not_in_myfeed_today,
        test_removed_not_in_myfeed_scan,
        test_removed_company_not_in_catalyst_boost,
        test_removed_macro_feed_drops_from_macro_today,
        test_only_macro_removed_returns_normal,
        test_remove_one_macro_keeps_unrelated,
        test_restore_reactivates_feed,
        test_restored_macro_reenters_memory,
        test_delete_alias_works,
        test_missing_feed_returns_not_found,
        test_help_shows_remove_restore,
        test_regression_feed_ticker_resolver_4b18g,
        test_regression_macro_emergency_4b18f,
        test_regression_live_confirmation_guard_4b18d,
        test_build_label_52h,
    ]
    failed = 0
    for test in tests:
        rc = test()
        if rc:
            failed += 1
            print(f'FAIL: {test.__name__}', file=sys.stderr)
        else:
            print(f'OK: {test.__name__}')
    if failed:
        print(f'FAILED: {failed}/{len(tests)}', file=sys.stderr)
        return 1
    print('FEED_REMOVE_4B18H_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
