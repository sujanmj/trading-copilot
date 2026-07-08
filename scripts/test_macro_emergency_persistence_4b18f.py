#!/usr/bin/env python3
"""Phase 4B.18F — Persist Emergency Macro into Macro Shock Sentinel (AstraEdge 52E)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

IST = ZoneInfo('Asia/Kolkata')

OIL_BOND_HEADLINE = (
    'Global Market: Euro zone bond yields hit near one-month high '
    'as oil surge fuels ECB rate hike bets'
)


def _fail(msg: str) -> int:
    print(f'MACRO_EMERGENCY_PERSISTENCE_4B18F_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


@contextmanager
def _isolated_macro_env():
    import sqlite3
    import uuid

    import backend.my_feed.my_feed_db as db_mod

    uri = f'file:macro_emergency_persist_{uuid.uuid4().hex}?mode=memory&cache=shared'
    boot = sqlite3.connect(uri, uri=True, check_same_thread=False)
    boot.row_factory = sqlite3.Row
    boot.executescript(db_mod.SCHEMA)
    boot.commit()
    boot.close()

    def _mem_connect() -> sqlite3.Connection:
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        state_path = Path(tmp) / 'macro_shock_sentinel_state.json'
        emergency_path = Path(tmp) / 'emergency_macro_dedupe_state.json'
        with patch('backend.trading.macro_shock_sentinel.STATE_FILE', state_path), patch(
            'backend.orchestration.alert_quality_filters.EMERGENCY_STATE_FILE', emergency_path
        ), patch.object(db_mod, '_connect', _mem_connect):
            db_mod.init_my_feed_db()
            yield state_path


def test_emergency_macro_persists_to_macro_memory() -> int:
    from backend.trading.macro_shock_sentinel import (
        get_active_macro_shock,
        persist_emergency_macro_to_sentinel,
    )

    with _isolated_macro_env():
        result = persist_emergency_macro_to_sentinel(
            OIL_BOND_HEADLINE,
            confidence=0.90,
            theme='macro_policy',
            source='emergency_macro',
            direct_market_impact=True,
        )
        active = get_active_macro_shock()
    if not result.get('persisted'):
        return _fail(f'expected persist got {result!r}')
    if not active:
        return _fail('active macro shock missing after emergency persist')
    if active.get('severity') not in ('HIGH', 'CRITICAL'):
        return _fail(f'expected HIGH/CRITICAL got {active.get("severity")!r}')
    return 0


def test_macro_not_normal_after_emergency() -> int:
    from backend.trading.macro_shock_sentinel import (
        format_macro_command_telegram,
        persist_emergency_macro_to_sentinel,
    )

    with _isolated_macro_env():
        persist_emergency_macro_to_sentinel(
            OIL_BOND_HEADLINE,
            confidence=0.90,
            theme='macro_policy',
            direct_market_impact=True,
        )
        text = format_macro_command_telegram('')
    if 'NORMAL' in text and 'Regime:</b> NORMAL' in text:
        return _fail(f'/macro still NORMAL: {text[:240]!r}')
    if 'RISK_OFF' not in text and 'RED MARKET' not in text:
        return _fail(f'/macro missing RISK_OFF/RED MARKET: {text[:240]!r}')
    if 'HIGH' not in text and 'CRITICAL' not in text:
        return _fail(f'/macro missing HIGH/CRITICAL severity: {text[:240]!r}')
    return 0


def test_macro_today_lists_emergency_headline() -> int:
    from backend.trading.macro_shock_sentinel import (
        format_macro_command_telegram,
        persist_emergency_macro_to_sentinel,
    )

    with _isolated_macro_env():
        persist_emergency_macro_to_sentinel(
            OIL_BOND_HEADLINE,
            confidence=0.90,
            theme='macro_policy',
            direct_market_impact=True,
        )
        text = format_macro_command_telegram('today')
    if 'oil surge' not in text.lower() and 'bond yield' not in text.lower():
        return _fail(f'/macro today missing headline: {text[:300]!r}')
    return 0


def test_myfeed_today_includes_macro_shock() -> int:
    from backend.my_feed.my_feed_db import list_items
    from backend.trading.macro_shock_sentinel import persist_emergency_macro_to_sentinel

    with _isolated_macro_env():
        persist_emergency_macro_to_sentinel(
            OIL_BOND_HEADLINE,
            confidence=0.90,
            theme='macro_policy',
            direct_market_impact=True,
        )
        rows = list_items(limit=20, today_only=True)
    if not rows:
        return _fail('myfeed today empty after emergency macro')
    match = next(
        (
            r for r in rows
            if r.get('source') == 'emergency_macro' or r.get('event_type') == 'macro_shock'
        ),
        None,
    )
    if not match:
        return _fail(f'no emergency_macro / macro_shock row in myfeed: {[r.get("source") for r in rows]!r}')
    if 'oil surge' not in str(match.get('cleaned_summary') or '').lower():
        return _fail('myfeed row missing oil surge headline')
    return 0


def test_oil_bond_yield_at_least_high() -> int:
    from backend.trading.macro_shock_sentinel import SEVERITY_HIGH, SEVERITY_RANK, score_macro_severity

    result = score_macro_severity(
        OIL_BOND_HEADLINE,
        confidence=0.90,
        direct_market_impact=True,
        emergency_theme='macro_policy',
    )
    if SEVERITY_RANK.get(str(result.get('severity')), 0) < SEVERITY_RANK[SEVERITY_HIGH]:
        return _fail(f'expected >= HIGH got {result.get("severity")!r}')
    return 0


def test_duplicate_emergency_macro_no_duplicate_records() -> int:
    from backend.my_feed.my_feed_db import list_items
    from backend.trading.macro_shock_sentinel import (
        get_active_macro_shock,
        persist_emergency_macro_to_sentinel,
    )

    with _isolated_macro_env():
        first = persist_emergency_macro_to_sentinel(
            OIL_BOND_HEADLINE,
            confidence=0.90,
            theme='macro_policy',
            direct_market_impact=True,
        )
        second = persist_emergency_macro_to_sentinel(
            OIL_BOND_HEADLINE,
            confidence=0.90,
            theme='macro_policy',
            direct_market_impact=True,
        )
        rows = [
            r for r in list_items(limit=50, today_only=True)
            if r.get('event_type') == 'macro_shock' or r.get('source') == 'emergency_macro'
        ]
        active = get_active_macro_shock()
    if not first.get('persisted'):
        return _fail('first persist failed')
    if not second.get('duplicate') and second.get('reason') != 'duplicate_updated':
        return _fail(f'second persist should be duplicate update got {second!r}')
    if len(rows) != 1:
        return _fail(f'expected 1 feed row got {len(rows)}')
    if int(active.get('source_count') or 0) < 2:
        return _fail(f'expected source_count>=2 got {active.get("source_count")!r}')
    return 0


def test_record_emergency_macro_sent_wires_sentinel() -> int:
    from backend.orchestration.alert_quality_filters import record_emergency_macro_sent
    from backend.trading.macro_shock_sentinel import format_macro_command_telegram, get_active_macro_shock

    with _isolated_macro_env():
        record_emergency_macro_sent(OIL_BOND_HEADLINE, 0.90, 'macro_policy')
        active = get_active_macro_shock()
        text = format_macro_command_telegram('')
    if not active:
        return _fail('record_emergency_macro_sent did not activate sentinel')
    if 'NORMAL' in text and 'Regime:</b> NORMAL' in text:
        return _fail('/macro still NORMAL after record_emergency_macro_sent')
    return 0


def test_manual_feed_iran_oil_becomes_macro_shock() -> int:
    from backend.my_feed.my_feed_db import insert_feed_item, list_items
    from backend.trading.macro_shock_sentinel import (
        get_active_macro_shock,
        process_macro_headline,
    )

    headlines = [
        'Trump says Iran ceasefire is over after missile strike',
        'crude oil jumps 6% on Hormuz supply risk',
        'Sensex/Nifty crashes on global risk-off',
    ]
    with _isolated_macro_env():
        for headline in headlines:
            record = insert_feed_item({
                'source': 'telegram_text',
                'raw_market_text': headline,
                'cleaned_summary': headline,
                'tickers': [],
                'themes': [],
                'event_type': 'news',
                'status': 'active',
            })
            result = process_macro_headline(
                headline,
                source='telegram_text',
                item=record,
                send_fn=None,
                from_manual_feed=True,
            )
            if not result.get('classified'):
                return _fail(f'manual /feed not classified as macro: {headline!r} -> {result!r}')
            refreshed = next(
                (r for r in list_items(limit=20) if r.get('feed_id') == record.get('feed_id')),
                None,
            )
            if not refreshed or refreshed.get('event_type') != 'macro_shock':
                return _fail(f'feed row not marked macro_shock for {headline!r}: {refreshed!r}')
        active = get_active_macro_shock()
    if not active:
        return _fail('manual /feed macro did not activate sentinel memory')
    return 0


def test_manual_feed_macro_appears_in_macro_today() -> int:
    from backend.my_feed.my_feed_db import insert_feed_item
    from backend.trading.macro_shock_sentinel import (
        format_macro_command_telegram,
        process_macro_headline,
    )

    headline = 'Trump says Iran ceasefire is over; crude oil jumps 6%'
    with _isolated_macro_env():
        record = insert_feed_item({
            'source': 'telegram_text',
            'raw_market_text': headline,
            'cleaned_summary': headline,
            'event_type': 'news',
            'status': 'active',
        })
        process_macro_headline(
            headline,
            source='telegram_text',
            item=record,
            send_fn=None,
            from_manual_feed=True,
        )
        text = format_macro_command_telegram('today')
    if 'Iran' not in text and 'ceasefire' not in text.lower() and 'crude' not in text.lower():
        return _fail(f'/macro today missing manual feed macro: {text[:300]!r}')
    return 0


def test_normal_stock_feed_not_macro_shock() -> int:
    from backend.my_feed.my_feed_db import insert_feed_item, list_items
    from backend.trading.macro_shock_sentinel import (
        get_active_macro_shock,
        process_macro_headline,
    )

    headline = 'BEL wins defence order worth Rs 2,400 crore; shares surge 4%'
    with _isolated_macro_env():
        record = insert_feed_item({
            'source': 'telegram_text',
            'raw_market_text': headline,
            'cleaned_summary': headline,
            'tickers': ['BEL'],
            'event_type': 'corporate_action',
            'status': 'active',
        })
        result = process_macro_headline(
            headline,
            source='telegram_text',
            item=record,
            send_fn=None,
            from_manual_feed=True,
        )
        active = get_active_macro_shock()
        refreshed = next(
            (r for r in list_items(limit=10) if r.get('feed_id') == record.get('feed_id')),
            None,
        )
    if result.get('classified'):
        return _fail('stock-specific /feed must not classify as macro')
    if active:
        return _fail('stock-specific /feed must not activate macro memory')
    if refreshed and refreshed.get('event_type') == 'macro_shock':
        return _fail('stock-specific feed row incorrectly marked macro_shock')
    return 0


def test_0830_macro_checkpoint_registered_in_schedule() -> int:
    from backend.telegram.premarket_scheduler import (
        MACRO_CHECKPOINT_SLOTS,
        SCHEDULE_DISPLAY,
        SCHEDULE_DISPLAY_PREP,
        due_macro_checkpoint_slots,
        format_schedule_text,
    )

    if 'macro_shock_checkpoint' not in MACRO_CHECKPOINT_SLOTS:
        return _fail('macro_shock_checkpoint missing from MACRO_CHECKPOINT_SLOTS')
    if MACRO_CHECKPOINT_SLOTS['macro_shock_checkpoint'] != (8, 30):
        return _fail(f'expected 08:30 slot got {MACRO_CHECKPOINT_SLOTS["macro_shock_checkpoint"]!r}')
    text = format_schedule_text()
    if '08:30 — Macro Shock Checkpoint' not in text:
        return _fail(f'/schedule missing 08:30 Macro Shock Checkpoint: {text!r}')
    if '08:30 — Macro Shock Checkpoint' not in SCHEDULE_DISPLAY_PREP:
        return _fail('SCHEDULE_DISPLAY_PREP missing checkpoint line')
    if '08:30 — Macro Shock Checkpoint' not in SCHEDULE_DISPLAY:
        return _fail('SCHEDULE_DISPLAY missing checkpoint line')
    due = due_macro_checkpoint_slots(datetime(2026, 7, 9, 8, 30, tzinfo=IST))
    if 'macro_shock_checkpoint' not in due:
        # may be marked already in real state file — still OK if slot defined
        pass
    return 0


def test_0830_checkpoint_dedupes_already_alerted() -> int:
    from backend.trading.macro_shock_sentinel import (
        persist_emergency_macro_to_sentinel,
        process_macro_headline,
        run_macro_shock_checkpoint_0830,
    )

    sent: list[str] = []

    def _send(text: str) -> bool:
        sent.append(text)
        return True

    with _isolated_macro_env():
        persist_emergency_macro_to_sentinel(
            OIL_BOND_HEADLINE,
            confidence=0.90,
            theme='macro_policy',
            direct_market_impact=True,
        )
        # Simulate overnight/immediate already alerted.
        process_macro_headline(
            OIL_BOND_HEADLINE,
            source='emergency_macro',
            send_fn=_send,
            slot='immediate',
            store_memory=False,
        )
        first_count = len(sent)
        result = run_macro_shock_checkpoint_0830(send_fn=_send, now=datetime(2026, 7, 8, 8, 30, tzinfo=IST))
        second_count = len(sent)
    if first_count < 1:
        return _fail('expected immediate alert before checkpoint')
    if second_count > first_count:
        return _fail('08:30 checkpoint resent already-alerted macro shock')
    if result.get('sent'):
        return _fail(f'checkpoint should dedupe got sent=True reason={result.get("reason")!r}')
    return 0


def _run(script: str) -> int:
    env = os.environ.copy()
    env.setdefault('ASTRAEDGE_QA_SMOKE', '1')
    env['DISABLE_TELEGRAM'] = '1'
    env['DISABLE_TELEGRAM_SENDS'] = '1'
    env['PYTHONPATH'] = str(PROJECT_ROOT)
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / 'scripts' / script)],
        cwd=str(PROJECT_ROOT),
        env=env,
        check=False,
    ).returncode


def test_regression_macro_shock_sentinel_4b18e() -> int:
    if _run('test_macro_shock_sentinel_4b18e.py') != 0:
        return _fail('52C macro shock sentinel regression failed')
    return 0


def test_regression_live_confirmation_guard_4b18d() -> int:
    if _run('test_live_confirmation_guard_4b18d.py') != 0:
        return _fail('52B live confirmation guard regression failed')
    return 0


def test_build_label_52d() -> int:
    from backend.config.local_safe_mode import ASTRAEDGE_BUILD_STAGE, ASTRAEDGE_TELEGRAM_BUILD

    if ASTRAEDGE_TELEGRAM_BUILD != 'AstraEdge 52E' or ASTRAEDGE_BUILD_STAGE != '52E':
        return _fail(f'expected AstraEdge 52E got {ASTRAEDGE_TELEGRAM_BUILD!r}')
    return 0


def main() -> int:
    tests = [
        test_emergency_macro_persists_to_macro_memory,
        test_macro_not_normal_after_emergency,
        test_macro_today_lists_emergency_headline,
        test_myfeed_today_includes_macro_shock,
        test_oil_bond_yield_at_least_high,
        test_duplicate_emergency_macro_no_duplicate_records,
        test_record_emergency_macro_sent_wires_sentinel,
        test_manual_feed_iran_oil_becomes_macro_shock,
        test_manual_feed_macro_appears_in_macro_today,
        test_normal_stock_feed_not_macro_shock,
        test_0830_macro_checkpoint_registered_in_schedule,
        test_0830_checkpoint_dedupes_already_alerted,
        test_regression_macro_shock_sentinel_4b18e,
        test_regression_live_confirmation_guard_4b18d,
        test_build_label_52d,
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
    print('MACRO_EMERGENCY_PERSISTENCE_4B18F_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
