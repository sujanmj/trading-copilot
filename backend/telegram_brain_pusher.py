"""
Telegram Brain Pusher v3 — JSON API Optimized
Reads the structured unified_intelligence.json and pushes the full Brain 
to Telegram in 6 logical messages.

Usage:
  python telegram_brain_pusher.py             → Full 6-msg brain
  python telegram_brain_pusher.py summary     → Executive summary only
  python telegram_brain_pusher.py opps        → Top opportunities only
  python telegram_brain_pusher.py risks       → Avoid list only
  python telegram_brain_pusher.py action      → Action plan only
  python telegram_brain_pusher.py calibration → Self-calibration only
  python telegram_brain_pusher.py sectors     → Sector rotation only
"""

import os
os.environ['PYTHONIOENCODING'] = 'utf-8'

import sys
import json
import time
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

def safe_print(text):
    try:
        print(text)
    except (UnicodeEncodeError, ValueError):
        try:
            print(text.encode('ascii', errors='replace').decode('ascii'))
        except Exception:
            pass

env_path = Path(__file__).parent.parent / 'config' / 'keys.env'
load_dotenv(env_path, override=False)

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

DATA_DIR = Path(__file__).parent.parent / 'data'
INTEL_FILE = DATA_DIR / 'unified_intelligence.json'


def send_message(text, parse_mode='HTML'):
    if not BOT_TOKEN or not CHAT_ID:
        safe_print("[ERROR] Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return False
    if len(text) > 4000:
        text = text[:3950] + "\n... (truncated)"
    try:
        r = requests.post(
            f"{API_URL}/sendMessage",
            json={
                'chat_id': CHAT_ID,
                'text': text,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True,
            },
            timeout=10
        )
        return r.status_code == 200
    except Exception as e:
        safe_print(f"[TG] Send error: {e}")
        return False

def chunk_message(text, max_len=3900):
    if len(text) <= max_len:
        return [text]
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        split_at = remaining.rfind('\n\n', 0, max_len)
        if split_at < max_len // 2:
            split_at = remaining.rfind('\n', 0, max_len)
        if split_at < max_len // 2:
            split_at = max_len
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip()
    return chunks

def send_chunked(text):
    for chunk in chunk_message(text):
        send_message(chunk)
        time.sleep(0.5)

def load_intel():
    if not INTEL_FILE.exists():
        return {}
    try:
        with open(INTEL_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        safe_print(f"[ERROR] Loading intel: {e}")
        return {}

# ============================================================
# FORMATTING HELPERS FOR JSON
# ============================================================

def format_opps(opps_list):
    if not opps_list:
        return "<i>No opportunities found in analysis.</i>"
    res = []
    for i, o in enumerate(opps_list, 1):
        icon = "🟢" if str(o.get('action', '')).upper() == "BUY" else "🟡"
        res.append(f"{i}. {icon} <b>{o.get('symbol', 'UNKNOWN')}</b> [{o.get('action', 'WATCH')}]\n"
                   f"   💰 Entry: {o.get('entry_zone', 'N/A')} | Tgt: {o.get('target', 'N/A')} | SL: {o.get('stop_loss', 'N/A')}\n"
                   f"   📊 Conf: <b>{o.get('confidence', 'MEDIUM')}</b>\n"
                   f"   <i>{o.get('logic', '')}</i>")
    return "\n\n".join(res)

def format_risks(risks_list):
    if not risks_list:
        return "<i>No risks found in analysis.</i>"
    res = []
    for i, r in enumerate(risks_list, 1):
        res.append(f"{i}. 🔴 <b>{r.get('symbol', 'UNKNOWN')}</b>\n   <i>{r.get('logic', '')}</i>")
    return "\n\n".join(res)

# ============================================================
# MESSAGE BUILDERS
# ============================================================

def build_msg1_header(intel):
    ts_str = intel.get('generation_time', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    mood = intel.get('market_mood', {})
    confidence = mood.get('confidence_level', 'N/A')
    
    return f"""🧠 <b>UNIFIED MARKET INTELLIGENCE</b>
━━━━━━━━━━━━━━━━━━━━

📅 <i>{ts_str}</i>
📊 System Confidence: <b>{confidence}</b>
📡 Sources Parsed: <b>{intel.get('sources_used', 8)}/8</b>

<i>📨 Sending full JSON-parsed analysis...</i>"""

def build_msg2_summary_govt(intel):
    summary = intel.get('executive_summary', 'No summary available.')
    govt = intel.get('government_impact', {})
    
    govt_text = f"<b>Impact:</b> {govt.get('summary', 'None')}\n"
    govt_text += f"<b>Confidence:</b> {govt.get('confidence_score', 'N/A')}"
    
    return f"📋 <b>EXECUTIVE SUMMARY</b>\n\n{summary}\n\n━━━━━━━━━━━━━━━━━━━━\n\n🏛️ <b>GOVT POLICY IMPACT</b>\n\n{govt_text}"

def build_msg3_scanner_sentiment(intel):
    mood = intel.get('market_mood', {})
    
    parts = [
        "💬 <b>MARKET MOOD & SENTIMENT</b>",
        f"🌍 <b>Global:</b> {mood.get('global_mood', 'N/A')}",
        f"🇮🇳 <b>India:</b> {mood.get('india_outlook', 'N/A')}",
        f"🛒 <b>Retail:</b> {mood.get('retail_mood', 'N/A')}"
    ]
    return "\n\n".join(parts)

def build_msg4_calibration_opps_top5(intel):
    cal = intel.get('self_calibration', 'No calibration data available.')
    opps = intel.get('top_opportunities', [])
    
    opps_text = format_opps(opps[:5])
    
    return f"🎯 <b>SELF-CALIBRATION</b>\n\n{cal}\n\n━━━━━━━━━━━━━━━━━━━━\n\n💎 <b>TOP OPPORTUNITIES (1-5)</b>\n\n{opps_text}"

def build_msg5_opps_top10_risks(intel):
    opps = intel.get('top_opportunities', [])
    risks = intel.get('risks_and_avoids', [])
    
    opps_text = format_opps(opps[5:10]) if len(opps) > 5 else "<i>No additional opportunities.</i>"
    risks_text = format_risks(risks)
    
    return f"💎 <b>TOP OPPORTUNITIES (6-10)</b>\n\n{opps_text}\n\n━━━━━━━━━━━━━━━━━━━━\n\n⚠️ <b>TOP RISKS / AVOID LIST</b>\n\n{risks_text}"

def build_msg6_sectors_global_action(intel):
    sectors = intel.get('sector_rotation', {})
    bullish = ", ".join(sectors.get('bullish', ['None']))
    bearish = ", ".join(sectors.get('bearish', ['None']))
    action = intel.get('action_plan', 'No action plan provided.')
    
    parts = [
        "🔄 <b>SECTOR ROTATION</b>",
        f"🟢 <b>Bullish:</b> {bullish}",
        f"🔴 <b>Bearish:</b> {bearish}",
        "━━━━━━━━━━━━━━━━━━━━",
        "🚀 <b>ACTION PLAN</b>",
        action,
        "━━━━━━━━━━━━━━━━━━━━",
        "📌 <b>QUICK COMMANDS</b>\n\n/brain — Full brain\n/elite — ML Filtered Setups\n/opps — Opportunities\n/risks — Avoid list\n/action — Action plan\n/sectors — Sector rotation\n\n<i>Brain auto-pushes after each strategic run.</i>"
    ]
    return "\n\n".join(parts)


def push_full_brain():
    intel = load_intel()
    if not intel:
        send_message("❌ No brain data yet. Run /refresh first.")
        return False
    
    builders = [
        ('1/6 Header',                 build_msg1_header),
        ('2/6 Summary + Govt',         build_msg2_summary_govt),
        ('3/6 Sentiment',              build_msg3_scanner_sentiment),
        ('4/6 Calibration + Opps1-5',  build_msg4_calibration_opps_top5),
        ('5/6 Opps6-10 + Risks',       build_msg5_opps_top10_risks),
        ('6/6 Sectors + Action',       build_msg6_sectors_global_action),
    ]
    safe_print("[BRAIN] Pushing 6-message JSON brain to Telegram...")
    for label, builder in builders:
        try:
            text = builder(intel)
            send_chunked(text)
            safe_print(f"  ✓ {label}")
            time.sleep(0.8)
        except Exception as e:
            safe_print(f"[ERROR] {label}: {e}")
            send_message(f"❌ Error in {label}: {str(e)[:150]}")
    safe_print("[BRAIN] Done.")
    return True

# ============================================================
# COMMAND DISPATCHERS
# ============================================================

def push_summary():
    intel = load_intel()
    if intel: send_chunked(build_msg2_summary_govt(intel))

def push_opps():
    intel = load_intel()
    if intel: 
        opps = intel.get('top_opportunities', [])
        send_chunked(f"💎 <b>TOP OPPORTUNITIES</b>\n\n{format_opps(opps)}")

def push_risks():
    intel = load_intel()
    if intel: 
        risks = intel.get('risks_and_avoids', [])
        send_chunked(f"⚠️ <b>TOP RISKS / AVOID LIST</b>\n\n{format_risks(risks)}")

def push_action():
    intel = load_intel()
    if intel: send_chunked(f"🚀 <b>ACTION PLAN</b>\n\n{intel.get('action_plan', 'No plan found.')}")

def push_calibration():
    intel = load_intel()
    if intel: send_chunked(f"🎯 <b>SELF-CALIBRATION</b>\n\n{intel.get('self_calibration', 'No calibration data.')}")

def push_sectors():
    intel = load_intel()
    if intel: 
        sectors = intel.get('sector_rotation', {})
        bullish = ", ".join(sectors.get('bullish', ['None']))
        bearish = ", ".join(sectors.get('bearish', ['None']))
        send_chunked(f"🔄 <b>SECTOR ROTATION</b>\n\n🟢 <b>Bullish:</b> {bullish}\n🔴 <b>Bearish:</b> {bearish}")


if __name__ == "__main__":
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else 'full'
    safe_print(f"[telegram_brain_pusher] Mode: {mode}")

    dispatch = {
        'full': push_full_brain,
        'brain': push_full_brain,
        'all': push_full_brain,
        'summary': push_summary,
        'opps': push_opps,
        'opportunities': push_opps,
        'risks': push_risks,
        'action': push_action,
        'calibration': push_calibration,
        'cal': push_calibration,
        'sectors': push_sectors,
    }

    func = dispatch.get(mode)
    if func:
        func()
    else:
        safe_print(f"[ERROR] Unknown mode: {mode}")
        safe_print(f"Valid: {', '.join(dispatch.keys())}")
        sys.exit(1)