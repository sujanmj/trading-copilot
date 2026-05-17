import schedule
import time
import subprocess
from datetime import datetime
from pathlib import Path

def run_collector():
    print(f"\n⏰ [{datetime.now().strftime('%H:%M:%S')}] Running data collector...")
    collector_path = Path(__file__).parent / 'collector.py'
    subprocess.run(['python', str(collector_path)])

def run_analyzer():
    print(f"\n🤖 [{datetime.now().strftime('%H:%M:%S')}] Running AI analyzer...")
    analyzer_path = Path(__file__).parent / 'analyzer.py'
    subprocess.run(['python', str(analyzer_path)])

def run_full_cycle():
    run_collector()
    run_analyzer()

def morning_brief():
    print("\n" + "="*50)
    print("🌅 MORNING BRIEF — PRE MARKET ANALYSIS")
    print("="*50)
    run_full_cycle()

# Schedule
schedule.every(5).minutes.do(run_full_cycle)
schedule.every().day.at("08:45").do(morning_brief)
schedule.every(30).minutes.do(run_collector)

if __name__ == "__main__":
    print("🚀 Trading Copilot Scheduler Started")
    print("📅 Every 5 mins = full analysis")
    print("📅 8:45 AM = morning brief")
    print("📅 Every 30 mins = overnight data")
    print("\n⏳ Running first cycle now...")
    print("Press Ctrl+C anytime to stop\n")
    run_full_cycle()
    while True:
        schedule.run_pending()
        time.sleep(30)