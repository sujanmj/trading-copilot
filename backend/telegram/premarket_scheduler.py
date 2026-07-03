"""
Premarket IST scheduler (Stage 46H + 4B.3 opening workflow).

Silent background builds: 07:45, 08:00, 08:15 (data for 09:00 radar).
Opening rally Telegram alerts: 09:00, 09:20, 09:25, 09:31.
Legacy 08:30/08:45 auto-alerts skipped when opening workflow is enabled.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path

IST = ZoneInfo('Asia/Kolkata')
STATE_FILE = get_data_path('premarket_scheduler_state.json')

# Opening workflow replaces legacy 08:30/08:45 scheduled Telegram alerts.
OPENING_WORKFLOW_ENABLED = True

PREMARKET_SLOTS: dict[str, tuple[int, int]] = {
    'overnight_global': (7, 45),
    'india_digest': (8, 0),
    'scanner_build': (8, 15),
    'premarket_top3': (8, 30),
    'premarket_action': (8, 45),
}

SILENT_BUILD_SLOTS: dict[str, str] = {
    'overnight_global': 'global',
    'india_digest': 'news',
    'scanner_build': 'scanner',
}

OLD_PREMARKET_ALERT_SLOTS: dict[str, str] = {
    'premarket_top3': '0830',
    'premarket_action': '0845',
}

OPENING_MORNING_SLOTS: dict[str, tuple[int, int]] = {
    'radar_armed_0900': (9, 0),
    'opening_radar_0920': (9, 20),
    'early_tradecards_0925': (9, 25),
    'final_confirmation_0931': (9, 31),
}

SCHEDULED_ALERT_NAMES: dict[str, str] = {
    '0900': 'Radar Armed',
    '0920': 'Opening Rally Radar',
    '0925': 'Early Tradecards',
    '0931': 'Final Opening Confirmation',
}

SCHEDULE_DISPLAY_OPENING = [
    '09:00 — Radar Armed',
    '09:20 — Opening Rally Radar',
    '09:25 — Early Tradecards',
    '09:31 — Final Opening Confirmation',
]

OPENING_SCHEDULE_LABELS = list(SCHEDULED_ALERT_NAMES.values())

# Legacy detailed list retained for internal reference/tests (not shown in /schedule).
SCHEDULE_DISPLAY_LEGACY_BUILDS = [
    '07:45 — overnight global + US close + commodities',
    '08:00 — India news + govt + broker digest',
    '08:15 — premarket scanner/watchlist build',
    '08:30 — Telegram premarket top 3 setups',
    '08:45 — final premarket action plan',
]

SCHEDULE_DISPLAY = SCHEDULE_DISPLAY_LEGACY_BUILDS + SCHEDULE_DISPLAY_OPENING


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


def due_opening_morning_slots(now: Optional[datetime] = None) -> list[str]:
    now = now or datetime.now(IST)
    due: list[str] = []
    for slot, (hour, minute) in OPENING_MORNING_SLOTS.items():
        if now.hour == hour and now.minute == minute and not _already_sent(slot, now):
            due.append(slot)
    return due


# Scheduled Telegram alert slots — all suppressed on weekend/holiday/research.
WEEKEND_SUPPRESS_SEND_SLOTS = frozenset({
    'premarket_top3',
    'premarket_action',
    *OPENING_MORNING_SLOTS.keys(),
})


def _is_weekend_research_mode(now: Optional[datetime] = None) -> bool:
    from backend.analytics.market_calendar_router import (
        get_india_telegram_mode,
        is_weekend_holiday_research_telegram_mode,
    )

    now = now or datetime.now(IST)
    mode = get_india_telegram_mode(now.astimezone(ZoneInfo('UTC')))
    return is_weekend_holiday_research_telegram_mode(mode)


def is_opening_workflow_enabled() -> bool:
    return OPENING_WORKFLOW_ENABLED


def run_premarket_slot(
    slot: str,
    *,
    send_fn: Optional[Callable[[str], bool]] = None,
    now: Optional[datetime] = None,
) -> bool:
    from backend.analytics.premarket_conviction import build_premarket_conviction_report, send_scheduled_premarket

    ist_now = now or datetime.now(IST)
    ts = ist_now.replace(microsecond=0).isoformat()

    if slot in SILENT_BUILD_SLOTS:
        stage = SILENT_BUILD_SLOTS[slot]
        try:
            build_premarket_conviction_report(persist=True)
            print(f'[SILENT_PREMARKET_BUILD] time={ts} stage={stage} status=ok', flush=True)
            return True
        except Exception:
            print(f'[SILENT_PREMARKET_BUILD] time={ts} stage={stage} status=fail', flush=True)
            raise

    if slot in OLD_PREMARKET_ALERT_SLOTS:
        if _is_weekend_research_mode(ist_now):
            print(
                'WEEKEND_SCHEDULE_SUPPRESSED premarket_alert reason=weekend_research_mode '
                f'slot={slot}',
                flush=True,
            )
            return False
        if is_opening_workflow_enabled():
            alert = OLD_PREMARKET_ALERT_SLOTS[slot]
            print(
                f'[OLD_PREMARKET_ALERT_SKIPPED] time={ts} alert={alert} '
                'reason=opening_workflow_enabled',
                flush=True,
            )
            return False
        ok = send_scheduled_premarket(slot, send_fn=send_fn)
        print(f'[PREMARKET_SCHED] sent slot={slot} ok={ok}', flush=True)
        return ok

    return False


def run_opening_morning_slot(
    slot: str,
    *,
    now: Optional[datetime] = None,
    send_fn: Optional[Callable[[str], bool]] = None,
) -> bool:
    if slot not in OPENING_MORNING_SLOTS:
        return False
    if _is_weekend_research_mode(now):
        print(
            f'WEEKEND_SCHEDULE_SUPPRESSED opening_morning reason=weekend_research_mode slot={slot}',
            flush=True,
        )
        return False
    try:
        from backend.trading.opening_rally_radar import run_opening_morning_scheduled_slot

        return run_opening_morning_scheduled_slot(slot, now=now, send_fn=send_fn)
    except Exception as exc:
        print(f'[PREMARKET_SCHED] opening_morning slot={slot} failed: {exc}', flush=True)
        return False


def format_schedule_text() -> str:
    lines = [
        '<b>📅 Schedule (IST)</b>',
        '',
        '<b>Background prep:</b>',
        '• Runs silently before market open',
        '',
        '<b>Opening rally workflow</b>',
    ]
    lines.extend(f'• {row}' for row in SCHEDULE_DISPLAY_OPENING)
    lines.extend([
        '',
        '<b>Manual anytime:</b> /radar · /gainers · /tradecards · /tradecard',
        '',
        '<b>Commands:</b> /premarket · /premarket full · /action plan',
    ])
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
                run_premarket_slot(slot, send_fn=send_fn, now=now)
                _mark_sent(slot, now)
            except Exception as exc:
                print(f'[PREMARKET_SCHED] slot={slot} failed: {exc}', flush=True)
        for slot in due_opening_morning_slots(now):
            try:
                run_opening_morning_slot(slot, now=now, send_fn=send_fn)
                _mark_sent(slot, now)
            except Exception as exc:
                print(f'[PREMARKET_SCHED] opening slot={slot} failed: {exc}', flush=True)
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
