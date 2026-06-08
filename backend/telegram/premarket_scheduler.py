"""
Premarket IST scheduler (Stage 46H).

Slots: 07:45, 08:00, 08:15, 08:30, 08:45, 09:10, 09:20, 09:30
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path

IST = ZoneInfo('Asia/Kolkata')
STATE_FILE = get_data_path('premarket_scheduler_state.json')

PREMARKET_SLOTS: dict[str, tuple[int, int]] = {
    'overnight_global': (7, 45),
    'india_digest': (8, 0),
    'scanner_build': (8, 15),
    'premarket_top3': (8, 30),
    'premarket_action': (8, 45),
    'preopen_watch': (9, 10),
    'live_validation': (9, 20),
    'open_confirmation': (9, 30),
}

SCHEDULE_DISPLAY = [
    '07:45 — overnight global + US close + commodities',
    '08:00 — India news + govt + broker digest',
    '08:15 — premarket scanner/watchlist build',
    '08:30 — Telegram premarket top 3 setups',
    '08:45 — final premarket action plan',
    '09:10 — pre-open watch',
    '09:20 — first live validation',
    '09:30 — confirmation/rejection alert',
]


def _load_state() -> dict:
    if not STATE_FILE.is_file():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding='utf-8')


def _slot_key(slot: str, now: datetime) -> str:
    return f"{now.date().isoformat()}:{slot}"


def _already_sent(slot: str, now: datetime) -> bool:
    return _load_state().get(_slot_key(slot, now)) is True


def _mark_sent(slot: str, now: datetime) -> None:
    state = _load_state()
    state[_slot_key(slot, now)] = True
    cutoff = now.date().isoformat()
    cleaned = {k: v for k, v in state.items() if k >= cutoff or ':' not in k}
    _save_state(cleaned)


def due_premarket_slots(now: Optional[datetime] = None) -> list[str]:
    now = now or datetime.now(IST)
    due: list[str] = []
    for slot, (hour, minute) in PREMARKET_SLOTS.items():
        if now.hour == hour and now.minute == minute and not _already_sent(slot, now):
            due.append(slot)
    return due


# Scheduled Telegram alert slots — all suppressed on weekend/holiday/research.
WEEKEND_SUPPRESS_SEND_SLOTS = frozenset({
    'premarket_top3',
    'premarket_action',
    'preopen_watch',
    'live_validation',
    'open_confirmation',
})


def _is_weekend_research_mode(now: Optional[datetime] = None) -> bool:
    from backend.analytics.market_calendar_router import (
        get_india_telegram_mode,
        is_weekend_holiday_research_telegram_mode,
    )

    now = now or datetime.now(IST)
    mode = get_india_telegram_mode(now.astimezone(ZoneInfo('UTC')))
    return is_weekend_holiday_research_telegram_mode(mode)


def run_premarket_slot(slot: str, *, send_fn: Optional[Callable[[str], bool]] = None) -> bool:
    from backend.analytics.premarket_conviction import build_premarket_conviction_report, send_scheduled_premarket

    build_slots = {'overnight_global', 'india_digest', 'scanner_build'}
    send_slots = {'premarket_top3', 'premarket_action', 'preopen_watch', 'live_validation', 'open_confirmation'}

    if slot in build_slots:
        build_premarket_conviction_report(persist=True)
        print(f'[PREMARKET_SCHED] built report slot={slot}', flush=True)
        return True

    if slot in send_slots:
        if _is_weekend_research_mode():
            print(
                'WEEKEND_SCHEDULE_SUPPRESSED premarket_alert reason=weekend_research_mode '
                f'slot={slot}',
                flush=True,
            )
            return False
        ok = send_scheduled_premarket(slot, send_fn=send_fn)
        print(f'[PREMARKET_SCHED] sent slot={slot} ok={ok}', flush=True)
        return ok

    return False


def format_schedule_text() -> str:
    lines = ['<b>📅 Premarket schedule (IST)</b>', '']
    lines.extend(f'• {row}' for row in SCHEDULE_DISPLAY)
    lines.extend(['', '<b>Commands:</b> /premarket · /premarket full'])
    return '\n'.join(lines)


def run_premarket_scheduler_loop(
    *,
    send_fn: Optional[Callable[[str], bool]] = None,
    stop_event: Optional[threading.Event] = None,
) -> None:
    stop = stop_event or threading.Event()
    while not stop.is_set():
        now = datetime.now(IST)
        for slot in due_premarket_slots(now):
            try:
                run_premarket_slot(slot, send_fn=send_fn)
                _mark_sent(slot, now)
            except Exception as exc:
                print(f'[PREMARKET_SCHED] slot={slot} failed: {exc}', flush=True)
        stop.wait(30)


def start_premarket_scheduler(*, send_fn: Optional[Callable[[str], bool]] = None) -> threading.Thread:
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_premarket_scheduler_loop,
        kwargs={'send_fn': send_fn, 'stop_event': stop_event},
        name='premarket_scheduler',
        daemon=True,
    )
    thread._stop_event = stop_event  # type: ignore[attr-defined]
    thread.start()
    return thread
