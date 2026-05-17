"""
Alert Engine v1 - Path G
Reads latest data files and triggers Telegram alerts when conditions are met

Logic:
- ULTRA scanner signals → instant alert
- High-impact (7+/10) govt announcements → instant alert
- Morning brief at 8:45 AM (called by scheduler)
- Outcome report at 8:00 AM (called by scheduler)

All alerts are deduped to avoid spam.
"""

import os
os.environ['PYTHONIOENCODING'] = 'utf-8'

import sys
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from telegram_bot import (
    send_ultra_signal,
    send_govt_alert,
    send_morning_brief,
    send_outcome_report,
    send_message,
    safe_print,
)


# ============================================================
# CONFIGURATION
# ============================================================

DATA_DIR = Path(__file__).parent.parent / 'data'

FILES = {
    'scanner': DATA_DIR / 'scanner_data.json',
    'govt': DATA_DIR / 'govt_intelligence.json',
    'intelligence': DATA_DIR / 'unified_intelligence.json',
    'stats': DATA_DIR / 'stats_data.json',
}


def load_json(filepath):
    try:
        if not filepath.exists():
            return None
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        safe_print(f"[WARN] Failed to load {filepath.name}: {e}")
        return None


# ============================================================
# ALERT TRIGGERS
# ============================================================

def check_ultra_signals():
    """Check scanner for ULTRA signals and send alerts"""
    data = load_json(FILES['scanner'])
    if not data:
        return 0
    
    top_signals = data.get('top_signals', [])
    ultra_signals = [s for s in top_signals if s.get('strength') == 'ULTRA']
    
    if not ultra_signals:
        safe_print("[ALERT] No ULTRA signals to alert")
        return 0
    
    safe_print(f"[ALERT] Found {len(ultra_signals)} ULTRA signals")
    
    sent = 0
    for signal in ultra_signals[:5]:  # Max 5 alerts per run
        if send_ultra_signal(signal):
            sent += 1
            safe_print(f"  [SENT] {signal.get('ticker')} ({signal.get('direction')})")
    
    return sent


def check_govt_alerts():
    """Check govt intelligence for high-impact items"""
    data = load_json(FILES['govt'])
    if not data:
        return 0
    
    high_impact = data.get('high_impact_items', [])
    
    if not high_impact:
        safe_print("[ALERT] No high-impact govt items")
        return 0
    
    sent = 0
    for item in high_impact[:3]:  # Max 3 alerts per run
        score = item.get('impact_score', 0)
        if score >= 7:
            if send_govt_alert(item):
                sent += 1
                safe_print(f"  [SENT] Govt: {item.get('english_headline', '')[:60]}")
    
    if sent == 0:
        safe_print("[ALERT] No 7+/10 govt items to alert")
    
    return sent


def send_morning_brief_alert():
    """Send morning brief from latest intelligence"""
    data = load_json(FILES['intelligence'])
    if not data:
        safe_print("[ALERT] No intelligence file for morning brief")
        return 0
    
    if send_morning_brief(data):
        safe_print("[ALERT] Morning brief sent")
        return 1
    return 0


def send_outcome_report_alert():
    """Send daily outcome report from stats"""
    data = load_json(FILES['stats'])
    if not data:
        safe_print("[ALERT] No stats file for outcome report")
        return 0
    
    metrics = data.get('metrics_all_time', {})
    top_winners = data.get('top_winners', [])
    top_losers = data.get('top_losers', [])
    
    if send_outcome_report(metrics, top_winners, top_losers):
        safe_print("[ALERT] Outcome report sent")
        return 1
    return 0


# ============================================================
# MAIN ENTRY POINTS
# ============================================================

def run_realtime_alerts():
    """
    Called after scanner/govt updates - sends instant alerts for new signals
    """
    safe_print("=" * 60)
    safe_print("ALERT ENGINE - Real-time check")
    safe_print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    safe_print("=" * 60)
    
    total = 0
    
    safe_print("\n[STEP 1] Checking scanner ULTRA signals...")
    total += check_ultra_signals()
    
    safe_print("\n[STEP 2] Checking govt high-impact alerts...")
    total += check_govt_alerts()
    
    safe_print(f"\n[INFO] Total alerts sent: {total}")
    safe_print("=" * 60)
    return total


def run_morning_alerts():
    """Called at 8:45 AM - sends comprehensive brief"""
    safe_print("=" * 60)
    safe_print("ALERT ENGINE - Morning brief")
    safe_print("=" * 60)
    
    # Send brief
    sent = send_morning_brief_alert()
    
    # Also send realtime alerts (in case ULTRA signals exist)
    sent += check_ultra_signals()
    sent += check_govt_alerts()
    
    safe_print(f"\n[INFO] Total alerts sent: {sent}")
    return sent


def run_outcome_alerts():
    """Called at 8:00 AM after outcome_tracker - sends yesterday's results"""
    safe_print("=" * 60)
    safe_print("ALERT ENGINE - Daily outcome report")
    safe_print("=" * 60)
    
    sent = send_outcome_report_alert()
    safe_print(f"\n[INFO] Outcome alerts sent: {sent}")
    return sent


def run_test_alerts():
    """Test all alert types - useful for verification"""
    safe_print("=" * 60)
    safe_print("ALERT ENGINE - TEST ALL ALERTS")
    safe_print("=" * 60)
    
    safe_print("\n[1/3] Testing ULTRA signal alerts...")
    n1 = check_ultra_signals()
    safe_print(f"      Sent: {n1}")
    
    safe_print("\n[2/3] Testing govt alerts...")
    n2 = check_govt_alerts()
    safe_print(f"      Sent: {n2}")
    
    safe_print("\n[3/3] Testing morning brief...")
    n3 = send_morning_brief_alert()
    safe_print(f"      Sent: {n3}")
    
    total = n1 + n2 + n3
    safe_print(f"\n[TOTAL] {total} alerts sent")
    safe_print("=" * 60)


# ============================================================
# CLI ENTRY
# ============================================================

if __name__ == "__main__":
    # Allow different modes via command line
    mode = sys.argv[1] if len(sys.argv) > 1 else 'realtime'
    
    if mode == 'realtime':
        run_realtime_alerts()
    elif mode == 'morning':
        run_morning_alerts()
    elif mode == 'outcome':
        run_outcome_alerts()
    elif mode == 'test':
        run_test_alerts()
    else:
        safe_print(f"Unknown mode: {mode}")
        safe_print("Usage: python alert_engine.py [realtime|morning|outcome|test]")