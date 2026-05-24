import schedule
import time
import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path
import pytz
from concurrent.futures import ThreadPoolExecutor

IST = pytz.timezone('Asia/Kolkata')
BACKEND_DIR = Path(__file__).resolve().parent
PYTHON_EXE = sys.executable

def run_standalone_script(script_name: str):
    timestamp = datetime.now(IST).strftime("%H:%M:%S")
    print(f"[{timestamp}] Running {script_name}...")
    try:
        script_path = BACKEND_DIR / script_name
        subprocess.run([PYTHON_EXE, str(script_path)], check=True)
    except Exception as e:
        print(f"[!] Deployment Exception executing {script_name}: {str(e)}")

def run_all_collectors_parallel():
    print("\n" + "="*60)
    print(f"[*] Launching Parallel Ingestion Layer: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    ingestion_scripts = [
        "global_collector.py",
        "live_news_tracker.py",
        "nse_announcements.py",
        "inshorts_tracker.py",
        "youtube_tracker.py",
        "govt_tracker.py",
        "telegram_scraper.py",
        "twitter_tracker.py",
        "reddit_tracker.py"
    ]

    run_standalone_script("collector.py")

    with ThreadPoolExecutor(max_workers=len(ingestion_scripts)) as executor:
        executor.map(run_standalone_script, ingestion_scripts)

    print("[+] Parallel data ingestion complete.")
    run_standalone_script("stock_scanner.py")
    run_standalone_script("master_analyzer.py")
    run_standalone_script("telegram_brain_pusher.py")

def run_full_cycle(brief_name: str = "Scheduled"):
    """Collect data + run analyzer + push to Telegram"""
    print(f"\n[*] Full Cycle: {brief_name} @ {datetime.now(IST).strftime('%H:%M:%S IST')}")
    run_all_collectors_parallel()

def run_post_market_pipeline():
    print("\n" + "="*60)
    print(f"[*] Post-Market Pipeline: {datetime.now(IST).strftime('%H:%M:%S IST')}")
    print("="*60)
    run_standalone_script("outcome_tracker.py")
    run_standalone_script("stats_exporter.py")
    run_standalone_script("history_exporter.py")
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

# ── Overnight data collection every 30 mins (collect + analyze + push)
schedule.every(30).minutes.do(run_all_collectors_parallel)

# ============================================================
# BOOT
# ============================================================
if __name__ == "__main__":
    print("="*60)
    print("TRADING COPILOT - MASTER ORCHESTRATOR LAUNCHED")
    print(f"Boot Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")
    print("="*60)

    # On boot: collect + analyze immediately
    run_full_cycle("Boot Startup")

    while True:
        schedule.run_pending()
        time.sleep(1)