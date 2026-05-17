"""
MASTER SCHEDULER v7.1 - Adds history_exporter to all runs
v7.1 Changes (from v7):
- history_exporter.py runs after stats_exporter on every cycle
- New 'H' command for manual history refresh
"""

import schedule
import time
import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).parent
PYTHON_EXE = sys.executable

# Force UTF-8
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

last_runs = {}


def run_module(module_name, args=None):
    script_path = BACKEND_DIR / f"{module_name}.py"
    if not script_path.exists():
        print(f"  WARN {module_name}.py not found")
        return False

    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Running {module_name}{' ' + ' '.join(args) if args else ''}...")

    child_env = os.environ.copy()
    child_env['PYTHONIOENCODING'] = 'utf-8'
    child_env['PYTHONUTF8'] = '1'

    cmd = [PYTHON_EXE, str(script_path)]
    if args:
        cmd.extend(args)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            encoding='utf-8',
            errors='replace',
            env=child_env,
        )

        if result.returncode == 0:
            lines = [l for l in result.stdout.split('\n') if l.strip()]
            for line in lines[-5:]:
                try:
                    print(f"  {line}")
                except UnicodeEncodeError:
                    print(f"  {line.encode('ascii', errors='replace').decode('ascii')}")
            last_runs[module_name] = datetime.now()
            return True
        else:
            err_preview = result.stderr[:300] if result.stderr else 'no stderr'
            try:
                print(f"  ERROR (returncode={result.returncode}): {err_preview}")
            except UnicodeEncodeError:
                print(f"  ERROR (returncode={result.returncode}): {err_preview.encode('ascii', errors='replace').decode('ascii')}")
            return False

    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT after 10 min")
        return False
    except Exception as e:
        print(f"  EXCEPTION: {e}")
        return False


def overnight_brief():
    print("\n" + "=" * 60)
    print("[5:00 AM] OVERNIGHT BRIEF (SONNET)")
    print("=" * 60)
    os.environ['AI_USE_CASE'] = 'overnight_brief'
    run_module('collector')
    run_module('global_collector')
    run_module('news_aggregator')
    run_module('inshorts_tracker')
    run_module('youtube_tracker')
    run_module('govt_tracker')
    run_module('reddit_tracker')
    run_module('stock_scanner')
    run_module('master_analyzer')
    run_module('prediction_logger')
    run_module('stats_exporter')
    run_module('history_exporter')   # NEW v7.1
    run_module('alert_engine', ['realtime'])
    print("\n*** OVERNIGHT BRIEF READY ***\n")


def premarket_brief():
    print("\n" + "=" * 60)
    print("[8:45 AM] PRE-MARKET BRIEF (SONNET)")
    print("=" * 60)
    os.environ['AI_USE_CASE'] = 'premarket_brief'
    run_module('collector')
    run_module('global_collector')
    run_module('news_aggregator')
    run_module('inshorts_tracker')
    run_module('govt_tracker')
    run_module('reddit_tracker')
    run_module('stock_scanner')
    run_module('master_analyzer')
    run_module('prediction_logger')
    run_module('stats_exporter')
    run_module('history_exporter')   # NEW v7.1
    run_module('alert_engine', ['morning'])
    print("\n*** PRE-MARKET BRIEF READY ***\n")


def midday_check():
    print("\n" + "=" * 60)
    print("[12:00 PM] MIDDAY CHECK (GEMINI - FREE)")
    print("=" * 60)
    os.environ['AI_USE_CASE'] = 'midday_check'
    run_module('collector')
    run_module('news_aggregator')
    run_module('inshorts_tracker')
    run_module('govt_tracker')
    run_module('reddit_tracker')
    run_module('stock_scanner')
    run_module('master_analyzer')
    run_module('prediction_logger')
    run_module('stats_exporter')
    run_module('history_exporter')   # NEW v7.1
    run_module('alert_engine', ['realtime'])
    print("\n*** MIDDAY UPDATE READY ***\n")


def post_close_analysis():
    print("\n" + "=" * 60)
    print("[3:35 PM] POST-CLOSE (HAIKU)")
    print("=" * 60)
    os.environ['AI_USE_CASE'] = 'post_close'
    run_module('collector')
    run_module('news_aggregator')
    run_module('inshorts_tracker')
    run_module('youtube_tracker')
    run_module('govt_tracker')
    run_module('reddit_tracker')
    run_module('stock_scanner')
    run_module('master_analyzer')
    run_module('prediction_logger')
    run_module('stats_exporter')
    run_module('history_exporter')   # NEW v7.1
    run_module('alert_engine', ['realtime'])
    print("\n*** POST-CLOSE READY ***\n")


def us_market_check():
    print("\n" + "=" * 60)
    print("[11:00 PM] US CHECK (GEMINI - FREE)")
    print("=" * 60)
    os.environ['AI_USE_CASE'] = 'us_check'
    run_module('global_collector')
    run_module('news_aggregator')
    run_module('inshorts_tracker')
    run_module('reddit_tracker')
    run_module('master_analyzer')
    run_module('prediction_logger')
    run_module('stats_exporter')
    run_module('history_exporter')   # NEW v7.1
    print("\n*** US UPDATE READY ***\n")


def intraday_scanner_check():
    """Lightweight intraday scan during market hours (every 30 min)"""
    now = datetime.now()
    if now.weekday() >= 5:
        return
    
    print("\n" + "=" * 60)
    print(f"[{now.strftime('%H:%M')}] INTRADAY SCAN (GEMINI - FREE)")
    print("=" * 60)
    os.environ['AI_USE_CASE'] = 'midday_check'
    run_module('collector')
    run_module('stock_scanner')
    run_module('reddit_tracker')
    run_module('master_analyzer')
    run_module('prediction_logger')
    run_module('stats_exporter')
    run_module('history_exporter')   # NEW v7.1
    run_module('alert_engine', ['realtime'])
    print(f"\n*** INTRADAY SCAN COMPLETE @ {now.strftime('%H:%M')} ***\n")


def daily_outcome_check():
    """Daily outcome evaluation at 8 AM"""
    now = datetime.now()
    if now.weekday() >= 5:
        return
    
    print("\n" + "=" * 60)
    print(f"[{now.strftime('%H:%M')}] DAILY OUTCOME CHECK")
    print("=" * 60)
    print("Evaluating past predictions against actual market moves...")
    run_module('outcome_tracker')
    run_module('stats_exporter')
    run_module('history_exporter')   # NEW v7.1
    run_module('alert_engine', ['outcome'])
    print("\n*** OUTCOME CHECK COMPLETE ***\n")


def manual_refresh():
    print("\n" + "=" * 60)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] MANUAL REFRESH (SONNET)")
    print("=" * 60)
    os.environ['AI_USE_CASE'] = 'manual_refresh'
    run_module('collector')
    run_module('global_collector')
    run_module('news_aggregator')
    run_module('inshorts_tracker')
    run_module('youtube_tracker')
    run_module('govt_tracker')
    run_module('reddit_tracker')
    run_module('stock_scanner')
    run_module('master_analyzer')
    run_module('prediction_logger')
    run_module('stats_exporter')
    run_module('history_exporter')   # NEW v7.1
    print("\n*** MANUAL REFRESH COMPLETE ***\n")


def setup_schedule():
    # Strategic AI runs
    schedule.every().day.at("05:00").do(overnight_brief)
    schedule.every().day.at("08:45").do(premarket_brief)
    schedule.every().day.at("12:00").do(midday_check)
    schedule.every().day.at("15:35").do(post_close_analysis)
    schedule.every().day.at("23:00").do(us_market_check)
    
    # Daily outcome check at 8 AM
    schedule.every().day.at("08:00").do(daily_outcome_check)
    
    # Intraday scanner (every 30 min during market hours)
    intraday_times = [
        "09:30", "10:00", "10:30", "11:00", "11:30",
        "12:30", "13:00", "13:30", "14:00", "14:30", "15:00",
    ]
    for t in intraday_times:
        schedule.every().day.at(t).do(intraday_scanner_check)


def print_schedule():
    print("\n" + "=" * 60)
    print("SMART SCHEDULE v7.1 - Full Pipeline + History Exporter")
    print("=" * 60)
    print("STRATEGIC RUNS (Full pipeline + DB + Stats + History + Telegram):")
    print("  05:00 AM - Overnight brief [SONNET] + alerts")
    print("  08:00 AM - DAILY OUTCOME CHECK + Telegram report")
    print("  08:45 AM - Pre-market brief [SONNET] + Morning brief")
    print("  12:00 PM - Midday check [GEMINI FREE] + alerts")
    print("  03:35 PM - Post-close [HAIKU] + alerts")
    print("  11:00 PM - US check [GEMINI FREE]")
    print()
    print("INTRADAY SCANNER (every 30 min, Mon-Fri) + ULTRA alerts:")
    print("  09:30, 10:00, 10:30, 11:00, 11:30")
    print("  12:30, 13:00, 13:30, 14:00, 14:30, 15:00")
    print()
    print("Sources: India + Global + News + Inshorts + YouTube + Govt + Reddit + Scanner")
    print("Database: SQLite (predictions, signals, outcomes, snapshots, accuracy)")
    print("Stats:    Auto-exported to data/stats_data.json")
    print("History:  Auto-exported to data/history_data.json")
    print("Alerts:   Telegram bot @Sujan_trading_bot")
    print("Cost:     ~$10-12/month")
    print("=" * 60)


def status_check():
    now = datetime.now()
    print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S')}] Scheduler running")
    next_run = schedule.next_run()
    if next_run:
        mins = int((next_run - now).total_seconds() / 60)
        print(f"Next run in: {mins//60}h {mins%60}m at {next_run.strftime('%H:%M')}")
    if last_runs:
        print("Last runs:")
        for module, t in last_runs.items():
            mins_ago = int((now - t).total_seconds() / 60)
            print(f"  {module:25s} {mins_ago} min ago")


def listen_for_manual_trigger():
    import threading
    def input_listener():
        while True:
            try:
                cmd = input().strip().upper()
                if cmd == 'R':
                    manual_refresh()
                elif cmd == 'S':
                    status_check()
                elif cmd == 'I':
                    intraday_scanner_check()
                elif cmd == 'L':
                    print("\n[MANUAL] Running prediction_logger + history...")
                    run_module('prediction_logger')
                    run_module('stats_exporter')
                    run_module('history_exporter')
                elif cmd == 'O':
                    print("\n[MANUAL] Running outcome_tracker + history...")
                    run_module('outcome_tracker')
                    run_module('stats_exporter')
                    run_module('history_exporter')
                    run_module('alert_engine', ['outcome'])
                elif cmd == 'X':
                    print("\n[MANUAL] Refreshing stats + history...")
                    run_module('stats_exporter')
                    run_module('history_exporter')
                elif cmd == 'H':
                    # NEW v7.1: history exporter only
                    print("\n[MANUAL] Refreshing history only...")
                    run_module('history_exporter')
                elif cmd == 'T':
                    print("\n[MANUAL] Sending Telegram alerts (realtime mode)...")
                    run_module('alert_engine', ['realtime'])
                elif cmd == 'M':
                    print("\n[MANUAL] Sending morning brief to Telegram...")
                    run_module('alert_engine', ['morning'])
                elif cmd == 'Q':
                    print("Stopping...")
                    os._exit(0)
            except EOFError:
                break
    thread = threading.Thread(target=input_listener, daemon=True)
    thread.start()


if __name__ == "__main__":
    print("=" * 60)
    print("TRADING COPILOT - SCHEDULER v7.1 (Full Stack + History)")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    setup_schedule()
    print_schedule()

    print("\n[STARTUP] Initial refresh...")
    manual_refresh()

    print("\n[STARTUP] Running outcome tracker for any existing predictions...")
    run_module('outcome_tracker')
    run_module('stats_exporter')
    run_module('history_exporter')

    print("\n" + "=" * 60)
    print("SCHEDULER ACTIVE")
    print("Commands:")
    print("  R = full refresh   |  I = intraday scan")
    print("  L = log predictions|  O = check outcomes + telegram")
    print("  X = refresh stats  |  H = refresh history only")
    print("  T = test telegram  |  M = morning brief")
    print("  S = status         |  Q = quit")
    print("=" * 60)

    listen_for_manual_trigger()
    last_status_print = datetime.now()

    try:
        while True:
            schedule.run_pending()
            now = datetime.now()
            if (now - last_status_print).total_seconds() > 3600:
                status_check()
                last_status_print = now
            time.sleep(30)
    except KeyboardInterrupt:
        print("\n\nStopped by user")
        status_check()