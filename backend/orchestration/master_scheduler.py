import schedule
import time
import sys
import os
from datetime import datetime
from pathlib import Path
import pytz
from concurrent.futures import ThreadPoolExecutor

from backend.utils.bootstrap import setup_project_path
from backend.utils.config import PROJECT_ROOT
from backend.utils.runner import run_script

setup_project_path()

IST = pytz.timezone('Asia/Kolkata')
PYTHON_EXE = sys.executable


def run_standalone_script(script_name: str):
    timestamp = datetime.now(IST).strftime("%H:%M:%S")
    print(f"[{timestamp}] Running {script_name}...")
    try:
        run_script(script_name, check=True)
    except Exception as e:
        print(f"[!] Deployment Exception executing {script_name}: {str(e)}")

def run_all_collectors_parallel(push_telegram_brain: bool = False, run_analyzer: bool = True):
    from backend.utils.market_hours import get_collection_profile
    profile = get_collection_profile()
    period = profile.get('period', 'unknown')
    print("\n" + "=" * 60)
    print(f"[*] Ingestion Layer | period={period} @ {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    run_standalone_script("collector.py")

    if profile.get('run_parallel_ingestion'):
        ingestion_scripts = [
            "global_collector.py",
            "live_news_tracker.py",
            "nse_announcements.py",
            "inshorts_tracker.py",
            "youtube_tracker.py",
            "govt_tracker.py",
            "telegram_scraper.py",
            "twitter_tracker.py",
            "reddit_tracker.py",
        ]
        with ThreadPoolExecutor(max_workers=len(ingestion_scripts)) as executor:
            executor.map(run_standalone_script, ingestion_scripts)
    else:
        print(f"[COLLECTOR] {period} — skipping parallel news/social ingestion")

    print("[+] Data ingestion complete.")
    if profile.get('run_scanner'):
        run_standalone_script("stock_scanner.py")
    else:
        print(f"[COLLECTOR] {period} — skipping scanner")
    if run_analyzer and profile.get('run_analyzer'):
        run_standalone_script("master_analyzer.py")
    elif not profile.get('run_analyzer'):
        print(f"[COLLECTOR] {period} — skipping analyzer (low-power mode)")
    if push_telegram_brain:
        run_standalone_script("telegram_brain_pusher.py")


def run_collectors_only():
    """After-hours low-power ingestion — no AI synthesis."""
    run_all_collectors_parallel(push_telegram_brain=False, run_analyzer=False)


def run_alert_scheduler_tick():
    from backend.orchestration.alert_scheduler import tick
    try:
        result = tick()
        if result.get('sent'):
            print(f"[ALERTS] tick sent={result['sent']} actions={result.get('actions')}")
    except Exception as e:
        print(f"[!] Alert scheduler tick failed: {e}")

def run_full_cycle(brief_name: str = "Scheduled", push_brain: bool = False):
    """Collect data + optional analyzer; smart alerts handled by alert_scheduler."""
    print(f"\n[*] Full Cycle: {brief_name} @ {datetime.now(IST).strftime('%H:%M:%S IST')}")
    run_all_collectors_parallel(push_telegram_brain=push_brain, run_analyzer=True)

def run_post_market_pipeline():
    print("\n" + "="*60)
    print(f"[*] Post-Market Pipeline: {datetime.now(IST).strftime('%H:%M:%S IST')}")
    print("="*60)
    run_standalone_script("outcome_tracker.py")
    run_standalone_script("stats_exporter.py")
    run_standalone_script("history_exporter.py")
    try:
        from backend.analytics.daily_review_engine import build_daily_review
        build_daily_review()
        print("[DAILY REVIEW] End-of-day snapshot saved")
    except Exception as e:
        print(f"[!] Daily review snapshot failed: {e}")
    run_full_cycle("Post-Market")

# ============================================================
# SCHEDULE — FIXED
# ============================================================

# ── Intraday: every 30 mins during market hours (properly fixed)
intraday_slots = [
    "09:30", "10:00", "10:30", "11:00", "11:30",
    "12:00", "12:30", "13:00", "13:30", "14:00",
    "14:30", "15:00", "15:30"
]

def _schedule_intraday_job(day: str, slot: str):
    getattr(schedule.every(), day).at(slot).do(
        run_full_cycle, brief_name=f"Intraday {slot}"
    )

for slot in intraday_slots:
    for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']:
        _schedule_intraday_job(day, slot)

# ── Post-market settlement
for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']:
    getattr(schedule.every(), day).at("15:45").do(run_post_market_pipeline)

# ── Strategic daily runs
schedule.every().day.at("05:00").do(run_full_cycle, brief_name="Overnight Brief")
schedule.every().day.at("08:00").do(run_standalone_script, script_name="outcome_tracker.py")
schedule.every().day.at("08:45").do(run_full_cycle, brief_name="Pre-Market")
schedule.every().day.at("12:00").do(run_full_cycle, brief_name="Midday")
schedule.every().day.at("23:00").do(run_full_cycle, brief_name="US Pulse")

def run_scheduled_collection():
    """Market-hours-aware scheduled ingestion."""
    from backend.utils.market_hours import get_collection_profile
    profile = get_collection_profile()
    period = profile.get('period')
    if period == 'night':
        print("[COLLECTOR] Night mode — skip scheduled collection")
        return
    if profile.get('lightweight_only'):
        print(f"[COLLECTOR] {period} — lightweight India collector only")
        run_standalone_script("collector.py")
        return
    run_collectors_only()


# ── After-hours / overnight ingestion (market hours use intraday slots below)
schedule.every(30).minutes.do(run_scheduled_collection)

def run_outcome_horizon_tick():
    """Evaluate 15m/1h/intraday signal horizons during market hours."""
    try:
        from backend.utils.market_hours import get_market_period
        from backend.analytics.signal_outcomes import evaluate_due_horizons
        if get_market_period() != 'market':
            return
        result = evaluate_due_horizons()
        if result.get('evaluated'):
            print(f"[OUTCOME LEARN] evaluated {result['evaluated']} horizons")
    except Exception as e:
        print(f"[!] Outcome horizon tick failed: {e}")


# ── Smart Telegram alert scheduler (event-driven, anti-spam)
schedule.every(1).minutes.do(run_alert_scheduler_tick)
schedule.every(15).minutes.do(run_outcome_horizon_tick)

# ============================================================
# BOOT
# ============================================================
def main():
    from backend.utils.process_lock import try_acquire_lock, release_lock

    if not try_acquire_lock('master_scheduler'):
        print("[SKIP] master_scheduler already running")
        print("[SCHEDULER SINGLETON ACTIVE] Guard exit — primary scheduler lock held")
        sys.exit(0)

    print("="*60)
    print("TRADING COPILOT - MASTER ORCHESTRATOR LAUNCHED")
    print(f"Boot Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")
    print("="*60)
    print("[SCHEDULER HEALTHY] Lock acquired — orchestrator running")

    try:
        run_full_cycle("Boot Startup")

        while True:
            schedule.run_pending()
            time.sleep(1)
    finally:
        release_lock('master_scheduler')


if __name__ == "__main__":
    setup_project_path()
    main()