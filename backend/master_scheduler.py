import schedule
import time
import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path
import pytz
from concurrent.futures import ThreadPoolExecutor

# Force IST timezone for all scheduling operations
IST = pytz.timezone('Asia/Kolkata')

# Resolve runtime environment context
BACKEND_DIR = Path(__file__).resolve().parent
PYTHON_EXE = sys.executable

def run_standalone_script(script_name: str):
    """Safely executes an isolated backend module as an internal subprocess."""
    timestamp = datetime.now(IST).strftime("%H:%M:%S")
    print(f"[{timestamp}] Running {script_name}...")
    try:
        script_path = BACKEND_DIR / script_name
        subprocess.run([PYTHON_EXE, str(script_path)], check=True)
    except Exception as e:
        print(f"[!] Deployment Exception executing {script_name}: {str(e)}")

def run_all_collectors_parallel():
    """
    Executes all independent 8-tier tracking layers asynchronously 
    to prevent thread starvation and clear the Railway execution queue.
    """
    print("\n" + "="*60)
    print(f"[*] Launching Parallel Ingestion Layer: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    ingestion_scripts = [
        "global_collector.py",
        "news_aggregator.py",
        "inshorts_tracker.py",
        "youtube_tracker.py",
        "govt_tracker.py",
        "reddit_tracker.py"
    ]
    
    # Fire the live local stock data scraper first
    run_standalone_script("collector.py")
    
    # Run the remaining 6 global sentiment and policy collectors concurrently
    with ThreadPoolExecutor(max_workers=len(ingestion_scripts)) as executor:
        executor.map(run_standalone_script, ingestion_scripts)
        
    print("[+] Continuous parallel data ingestion complete.")
    
    # Immediately feed the updated data files into the technical scanner
    print("[*] Handing off refreshed vectors to the technical scanning core...")
    run_standalone_script("stock_scanner.py")

def run_post_market_pipeline():
    """
    Automated closing sequence executed at 3:45 PM IST.
    Resolves trade calculations, triggers UI synchronization, and generates brain briefs.
    """
    print("\n" + "="*60)
    print(f"[*] Initiating Post-Market Settlement Pipeline: {datetime.now(IST)}")
    print("="*60)
    
    # 1. Process pending trade performance metrics using final Angel One LTPs
    print("[*] Phase 1/3: Computing definitive win/loss outcomes...")
    run_standalone_script("outcome_tracker.py")
    
    # 2. Re-export updated statistics dataset snapshots for the Electron Dashboard
    print("[*] Phase 2/3: Refreshing system visualization files...")
    run_standalone_script("history_exporter.py")
    
    # 3. Fire the core multi-model AI analyzer for end-of-day brief delivery
    print("[*] Phase 3/3: Executing Master AI Strategy Engine [HAIKU]...")
    run_standalone_script("master_analyzer.py")
    
    print("[+] Post-market settlement phase closed successfully.")

def run_strategic_brief(brief_name: str):
    """Executes general master analyzer and brain push phases."""
    print(f"[*] Launching Strategic Brief Run: {brief_name}")
    run_standalone_script("master_analyzer.py")

# ============================================================================
# SCHEDULE ARCHITECTURE DECLARATION
# ============================================================================

# Intraday Iterative Scans (Mon-Fri, every 30 minutes during market activity)
intraday_slots = [
    "09:30", "10:00", "10:30", "11:00", "11:30",
    "12:30", "13:00", "13:30", "14:00", "14:30", "15:00"
]
for slot in intraday_slots:
    schedule.every().monday.to(.friday).at(slot).do(run_all_collectors_parallel)

# Strategic Core Runs & Automation Pipelines
schedule.every().day.at("05:00").do(run_strategic_brief, brief_name="Overnight Brief")
schedule.every().day.at("08:00").do(run_standalone_script, script_name="outcome_tracker.py")
schedule.every().day.at("08:45").do(run_strategic_brief, brief_name="Pre-Market Execution")
schedule.every().day.at("12:00").do(run_strategic_brief, brief_name="Midday Evaluation")
schedule.every().day.at("23:00").do(run_strategic_brief, brief_name="US/Global Pulse")

# The newly integrated, instant-update post-close settlement script
schedule.every().monday.to(.friday).at("15:45").do(run_post_market_pipeline)

# ============================================================================
# ORCHESTRATION BOOT ENTRY POINT
# ============================================================================
if __name__ == "__main__":
    print("="*60)
    print("TRADING COPILOT - MULTI-THREADED MASTER ORCHESTRATOR LAUNCHED")
    print(f"Boot Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")
    print("="*60)
    
    # Execute a clean sequential pipeline sync instantly on container startup
    run_all_collectors_parallel()
    
    # Service Runtime Event Loop
    while True:
        schedule.run_pending()
        time.sleep(1)