"""
IST scheduled briefs for Telegram Analysis Bot (Stage 45TG3).

Morning 08:00 · Close 16:30 · Overnight 06:30
Optional: pre-market 09:05 · close-watch 15:20

Uses lazy runners only — never full run_local.py.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from backend.utils.config import DATA_DIR

IST = ZoneInfo('Asia/Kolkata')
SENT_STATE_FILE = DATA_DIR / 'telegram_brief_scheduler_state.json'

CORE_SLOTS = {
    'morning': (8, 0),
    'close': (16, 30),
    'overnight': (6, 30),
}
OPTIONAL_SLOTS = {
    'premarket_reminder': (9, 5),
    'close_watch': (15, 20),
}


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


def _load_sent_state() -> dict:
    if not SENT_STATE_FILE.is_file():
        return {}
    try:
        return json.loads(SENT_STATE_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_sent_state(state: dict) -> None:
    SENT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SENT_STATE_FILE.write_text(json.dumps(state, indent=2), encoding='utf-8')


def _slot_key(slot: str, now: datetime) -> str:
    return f"{now.date().isoformat()}:{slot}"


def _already_sent(slot: str, now: datetime) -> bool:
    state = _load_sent_state()
    return state.get(_slot_key(slot, now)) is True


def _mark_sent(slot: str, now: datetime) -> None:
    state = _load_sent_state()
    state[_slot_key(slot, now)] = True
    cutoff = now.date().isoformat()
    cleaned = {k: v for k, v in state.items() if k >= cutoff or ':' not in k}
    _save_sent_state(cleaned)


def build_morning_brief_text() -> str:
    from backend.telegram.lazy_command_runner import run_global_only, run_market_only

    global_res = run_global_only()
    market_res = run_market_only()
    watch_res = _build_today_tomorrow_text('today')

    lines = [
        '<b>☀️ Morning brief</b>',
        global_res.get('text', ''),
        '',
        market_res.get('text', ''),
        '',
        watch_res,
    ]
    from backend.telegram.response_format import strip_stage_markers
    return strip_stage_markers('\n'.join(line for line in lines if line is not None))


def build_close_brief_text() -> str:
    from backend.telegram.lazy_command_runner import run_daily_pack_only, run_memory_only, run_market_only

    pack_res = run_daily_pack_only()
    memory_res = run_memory_only()
    market_res = run_market_only()
    tomorrow = _build_today_tomorrow_text('tomorrow')

    lines = [
        '<b>🔔 Market close summary</b>',
        pack_res.get('text', ''),
        '',
        memory_res.get('text', ''),
        '',
        market_res.get('text', ''),
        '',
        tomorrow,
    ]
    from backend.telegram.response_format import strip_stage_markers
    return strip_stage_markers('\n'.join(lines))


def build_overnight_brief_text() -> str:
    from backend.telegram.lazy_command_runner import run_global_only, run_news_only

    global_res = run_global_only()
    news_res = run_news_only(refresh=False)

    lines = [
        '<b>🌙 Overnight / global brief</b>',
        global_res.get('text', ''),
        '',
        news_res.get('text', ''),
    ]
    from backend.telegram.response_format import strip_stage_markers
    return strip_stage_markers('\n'.join(lines))


def build_premarket_reminder_text() -> str:
    return (
        '<b>⏰ Pre-market reminder</b>\n'
        'India session opening soon — review /today and /aihub scan before entries.'
    )


def build_close_watch_text() -> str:
    return (
        '<b>👀 Close-watch warning</b>\n'
        'Final hour — check /close candidates and avoid chasing late moves.'
    )


def _build_today_tomorrow_text(which: str) -> str:
    from backend.telegram.response_format import format_today_tomorrow

    return format_today_tomorrow(which)


BRIEF_BUILDERS: dict[str, Callable[[], str]] = {
    'morning': build_morning_brief_text,
    'close': build_close_brief_text,
    'overnight': build_overnight_brief_text,
    'premarket_reminder': build_premarket_reminder_text,
    'close_watch': build_close_watch_text,
}


def send_brief(slot: str, *, send_fn: Callable[[str], bool] | None = None) -> bool:
    builder = BRIEF_BUILDERS.get(slot)
    if not builder:
        return False
    from backend.telegram.response_format import strip_stage_markers

    text = strip_stage_markers(builder())
    if send_fn is None:
        from backend.telegram.telegram_analysis_bot import send_analysis_message

        return bool(send_analysis_message(text, command=f'brief_{slot}'))
    return bool(send_fn(text))


def _active_slots() -> dict[str, tuple[int, int]]:
    slots = dict(CORE_SLOTS)
    if _env_truthy('TELEGRAM_BRIEF_OPTIONAL'):
        slots.update(OPTIONAL_SLOTS)
    return slots


def _due_slots(now: datetime) -> list[str]:
    due: list[str] = []
    for slot, (hour, minute) in _active_slots().items():
        if now.hour == hour and now.minute == minute and not _already_sent(slot, now):
            due.append(slot)
    return due


def run_scheduler_loop(*, send_fn: Callable[[str], bool] | None = None, stop_event: threading.Event | None = None) -> None:
    stop = stop_event or threading.Event()
    while not stop.is_set():
        now = datetime.now(IST)
        for slot in _due_slots(now):
            try:
                send_brief(slot, send_fn=send_fn)
                _mark_sent(slot, now)
            except Exception as exc:
                print(f'[TG_BRIEF] {slot} failed: {exc}', flush=True)
        stop.wait(30)


def start_brief_scheduler(*, send_fn: Callable[[str], bool] | None = None) -> threading.Thread:
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_scheduler_loop,
        kwargs={'send_fn': send_fn, 'stop_event': stop_event},
        name='telegram_brief_scheduler',
        daemon=True,
    )
    thread._stop_event = stop_event  # type: ignore[attr-defined]
    thread.start()
    return thread
