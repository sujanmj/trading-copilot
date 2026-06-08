"""
Alert Engine — backward-compatible facade for smart Telegram alert system.

Legacy modes:
  realtime  → intraday event check only (no spam ULTRA loop)
  morning   → pre-market intelligence
  outcome   → daily outcome report
  close     → market close summary
  test      → verification
"""

import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'

from datetime import datetime

from backend.utils.bootstrap import setup_project_path

setup_project_path()

from backend.orchestration.alert_scheduler import get_scheduler_status, tick
from backend.orchestration import telegram_alert_engine as engine
from backend.orchestration.alert_filters import get_telegram_alert_obs_summary


def safe_print(text):
    try:
        print(text)
    except (UnicodeEncodeError, ValueError):
        print(str(text).encode('ascii', errors='replace').decode('ascii'))


def run_realtime_alerts():
    """Event-driven intraday check — replaces old ULTRA spam loop."""
    safe_print('=' * 60)
    safe_print('SMART ALERTS - Intraday event check')
    safe_print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    safe_print('=' * 60)
    total = engine.try_intraday_events() + engine.try_emergency_macro(scheduled=True)[0]
    safe_print(f'\n[INFO] Alerts sent: {total}')
    return total


def run_morning_alerts():
    safe_print('=' * 60)
    safe_print('SMART ALERTS - Pre-market')
    safe_print('=' * 60)
    sent = engine.try_pre_market()
    safe_print(f'\n[INFO] Alerts sent: {sent}')
    return sent


def run_outcome_alerts():
    safe_print('=' * 60)
    safe_print('SMART ALERTS - Outcome report')
    safe_print('=' * 60)
    sent = engine.run_outcome_report()
    safe_print(f'\n[INFO] Outcome alerts sent: {sent}')
    return sent


def run_close_alerts():
    safe_print('=' * 60)
    safe_print('SMART ALERTS - Market close')
    safe_print('=' * 60)
    sent = engine.try_close_summary()
    safe_print(f'\n[INFO] Close alerts sent: {sent}')
    return sent


def run_test_alerts():
    safe_print('=' * 60)
    safe_print('SMART ALERTS - TEST')
    safe_print('=' * 60)
    status = get_scheduler_status()
    safe_print(f"Mode: night={status['night_mode']} after_hours={status['after_hours']}")
    n = engine.try_pre_market() + engine.try_open_opportunity()
    safe_print(f'[TEST] sent={n}')
    safe_print('=' * 60)
    return n


def run_scheduler_tick():
    return tick()


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'realtime'
    modes = {
        'realtime': run_realtime_alerts,
        'morning': run_morning_alerts,
        'outcome': run_outcome_alerts,
        'close': run_close_alerts,
        'test': run_test_alerts,
        'tick': run_scheduler_tick,
        'status': lambda: safe_print(get_scheduler_status()),
    }
    fn = modes.get(mode)
    if fn:
        fn()
    else:
        safe_print(f'Unknown mode: {mode}')
        safe_print('Usage: alert_engine.py [realtime|morning|outcome|close|test|tick|status]')
