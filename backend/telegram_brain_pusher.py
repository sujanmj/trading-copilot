"""
Telegram Brain Pusher v2 — Tuned to actual master_analyzer output
Reads unified_intelligence.json and pushes the full Brain to Telegram
in 6 logical messages matching the GUI Brain tab.

Usage:
  python telegram_brain_pusher.py             → Full 6-msg brain
  python telegram_brain_pusher.py full        → Same
  python telegram_brain_pusher.py summary     → Executive summary only
  python telegram_brain_pusher.py opps        → Top opportunities only
  python telegram_brain_pusher.py risks       → Avoid list only
  python telegram_brain_pusher.py action      → Action plan only
  python telegram_brain_pusher.py calibration → Self-calibration only
  python telegram_brain_pusher.py sectors     → Sector rotation only
  python telegram_brain_pusher.py global      → Global impact only

Called by:
  - master_scheduler.py (auto-push after strategic runs)
  - telegram_listener.py (on /brain command)
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


# ============================================================
# TELEGRAM SEND
# ============================================================

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


# ============================================================
# DATA LOAD & SECTION EXTRACTION
# ============================================================

def load_intel():
    if not INTEL_FILE.exists():
        return None
    try:
        with open(INTEL_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        safe_print(f"[ERROR] Loading intel: {e}")
        return None


def extract_section(text, start_keywords, end_keywords=None):
    """
    Extract section from markdown. Matches headers case-insensitively.
    start_keywords: tuple of possible section names to match
    end_keywords: tuple of keywords that mark the next section (where extraction stops)
    """
    if not text:
        return ""

    upper = text.upper()
    start = -1

    for kw in start_keywords:
        idx = upper.find(kw.upper())
        if idx != -1:
            line_start = text.rfind('\n', 0, idx)
            start = line_start + 1 if line_start != -1 else idx
            break

    if start == -1:
        return ""

    search_from = start + 50
    end_candidates = []

    if end_keywords:
        for kw in end_keywords:
            pos = upper.find(kw.upper(), search_from)
            if pos != -1:
                line_start = text.rfind('\n', 0, pos)
                end_candidates.append(line_start if line_start != -1 else pos)

    end = min(end_candidates) if end_candidates else len(text)
    return text[start:end].strip()


# ============================================================
# SECTION KEYWORDS (matched to your actual brain output)
# ============================================================

KW = {
    'exec_summary':   ('EXECUTIVE SUMMARY',),
    'govt':           ('GOVERNMENT POLICY IMPACT', 'GOVT POLICY IMPACT', 'GOVT IMPACT'),
    'scanner':        ('SCANNER ALERTS',),
    'retail':         ('RETAIL SENTIMENT',),
    'mood':           ('MARKET MOOD',),
    'calibration':    ('SELF-CALIBRATION', 'SELF CALIBRATION'),
    'opps':           ('TOP 10 OPPORTUNITIES', 'TOP OPPORTUNITIES', 'OPPORTUNITIES TODAY'),
    'risks':          ('TOP 10 RISKS', 'AVOID LIST', 'TOP RISKS'),
    'sectors':        ('SECTOR ROTATION',),
    'global':         ('OVERNIGHT GLOBAL IMPACT', 'GLOBAL IMPACT'),
    'scanner_news':   ('SCANNER + NEWS ALERTS', 'SCANNER NEWS'),
    'cross_val':      ('CROSS-VALIDATION SCORE', 'CROSS VALIDATION'),
    'action':         ('ACTION PLAN',),
}


# ============================================================
# OPPORTUNITY/RISK SPLITTERS (split #1-5 vs #6-10)
# ============================================================

def split_numbered_items(section_text, start_num, end_num):
    """
    Given a section like 'TOP 10 OPPORTUNITIES' with numbered items,
    return only items #start_num through #end_num.
    """
    if not section_text:
        return ""

    import re
    # Match patterns like "1. TICKER" or "1) TICKER" at line start
    pattern = re.compile(r'^\s*(\d+)[\.\)]\s', re.MULTILINE)
    matches = list(pattern.finditer(section_text))

    if not matches:
        return section_text  # No numbered items found, return as-is

    selected = []
    for i, m in enumerate(matches):
        num = int(m.group(1))
        if start_num <= num <= end_num:
            start_pos = m.start()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(section_text)
            selected.append(section_text[start_pos:end_pos].strip())

    return "\n\n".join(selected)


# ============================================================
# 6-MESSAGE BUILDERS
# ============================================================

def build_msg1_header(intel):
    timestamp = intel.get('timestamp', 'unknown')
    model = intel.get('model_used', 'unknown')

    try:
        ts = datetime.fromisoformat(timestamp.replace('Z', ''))
        age_min = int((datetime.now() - ts).total_seconds() / 60)
        age_str = f"{age_min}m ago" if age_min < 60 else f"{age_min // 60}h {age_min % 60}m ago"
        ts_str = ts.strftime('%d %b %Y, %H:%M IST')
    except Exception:
        age_str = "just now"
        ts_str = str(timestamp)

    confidence = intel.get('overall_confidence', intel.get('confidence', 'N/A'))
    regime = intel.get('market_regime', intel.get('regime', 'N/A'))

    return f"""🧠 <b>UNIFIED MARKET INTELLIGENCE</b>
━━━━━━━━━━━━━━━━━━━━

📅 <i>{ts_str}</i>
⏱️ Generated: <i>{age_str}</i>
🤖 Model: <code>{model}</code>
📊 Confidence: <b>{confidence}</b>
🌐 Regime: <b>{regime}</b>

<i>📨 Sending 6 messages with full analysis...</i>"""


def build_msg2_summary_govt(intel):
    text = intel.get('analysis', '')
    summary = extract_section(text, KW['exec_summary'], KW['govt'] + KW['scanner'])
    govt = extract_section(text, KW['govt'], KW['scanner'] + KW['retail'])

    parts = []
    if summary:
        parts.append(f"📋 <b>EXECUTIVE SUMMARY</b>\n\n{summary}")
    if govt:
        parts.append(f"🏛️ <b>GOVERNMENT POLICY IMPACT</b>\n\n{govt}")

    if not parts:
        return "📋 <b>SUMMARY & GOVT</b>\n\n<i>Section not found in analysis.</i>"
    return "\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(parts)


def build_msg3_scanner_sentiment(intel):
    text = intel.get('analysis', '')
    scanner = extract_section(text, KW['scanner'], KW['retail'] + KW['mood'])
    retail = extract_section(text, KW['retail'], KW['mood'] + KW['calibration'])
    mood = extract_section(text, KW['mood'], KW['calibration'] + KW['opps'])

    parts = []
    if scanner:
        parts.append(f"📡 <b>SCANNER ALERTS</b>\n\n{scanner}")
    if retail:
        parts.append(f"🤖 <b>RETAIL SENTIMENT</b>\n\n{retail}")
    if mood:
        parts.append(f"💬 <b>MARKET MOOD</b>\n\n{mood}")

    if not parts:
        return "📡 <b>SCANNER & SENTIMENT</b>\n\n<i>Section not found.</i>"
    return "\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(parts)


def build_msg4_calibration_opps_top5(intel):
    text = intel.get('analysis', '')
    cal = extract_section(text, KW['calibration'], KW['opps'])
    opps_full = extract_section(text, KW['opps'], KW['risks'])
    opps_1_5 = split_numbered_items(opps_full, 1, 5)

    parts = []
    if cal:
        parts.append(f"🎯 <b>SELF-CALIBRATION</b>\n\n{cal}")
    if opps_1_5:
        parts.append(f"💎 <b>TOP OPPORTUNITIES (1-5)</b>\n\n{opps_1_5}")

    if not parts:
        return "🎯 <b>CALIBRATION & OPPS</b>\n\n<i>Section not found.</i>"
    return "\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(parts)


def build_msg5_opps_top10_risks(intel):
    text = intel.get('analysis', '')
    opps_full = extract_section(text, KW['opps'], KW['risks'])
    opps_6_10 = split_numbered_items(opps_full, 6, 10)
    risks = extract_section(text, KW['risks'], KW['sectors'] + KW['global'])

    parts = []
    if opps_6_10:
        parts.append(f"💎 <b>TOP OPPORTUNITIES (6-10)</b>\n\n{opps_6_10}")
    if risks:
        parts.append(f"⚠️ <b>TOP RISKS / AVOID LIST</b>\n\n{risks}")

    if not parts:
        return "💎 <b>OPPS & RISKS</b>\n\n<i>Section not found.</i>"
    return "\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(parts)


def build_msg6_sectors_global_action(intel):
    text = intel.get('analysis', '')
    sectors = extract_section(text, KW['sectors'], KW['global'] + KW['scanner_news'])
    global_impact = extract_section(text, KW['global'], KW['scanner_news'] + KW['cross_val'])
    cross_val = extract_section(text, KW['cross_val'], KW['action'])
    action = extract_section(text, KW['action'], None)  # to end

    parts = []
    if sectors:
        parts.append(f"🔄 <b>SECTOR ROTATION</b>\n\n{sectors}")
    if global_impact:
        parts.append(f"🌍 <b>OVERNIGHT GLOBAL IMPACT</b>\n\n{global_impact}")
    if cross_val:
        parts.append(f"✅ <b>CROSS-VALIDATION</b>\n\n{cross_val}")
    if action:
        parts.append(f"🚀 <b>ACTION PLAN</b>\n\n{action}")

    footer = """━━━━━━━━━━━━━━━━━━━━
📌 <b>QUICK COMMANDS</b>

/brain — Full brain
/summary — Executive summary
/opps — Opportunities
/risks — Avoid list
/action — Action plan
/calibration — Self-calibration
/sectors — Sector rotation
/global — Global impact
/ask &lt;Q&gt; — Ask AI

<i>Brain auto-pushes after each strategic run.</i>"""

    parts.append(footer)
    return "\n\n".join(parts)


# ============================================================
# DISPATCHERS
# ============================================================

def push_full_brain():
    intel = load_intel()
    if not intel:
        send_message("❌ No brain data yet. Run /refresh first.")
        return False

    builders = [
        ('1/6 Header',                 build_msg1_header),
        ('2/6 Summary + Govt',         build_msg2_summary_govt),
        ('3/6 Scanner + Sentiment',    build_msg3_scanner_sentiment),
        ('4/6 Calibration + Opps1-5',  build_msg4_calibration_opps_top5),
        ('5/6 Opps6-10 + Risks',       build_msg5_opps_top10_risks),
        ('6/6 Sectors+Global+Action',  build_msg6_sectors_global_action),
    ]

    safe_print("[BRAIN] Pushing 6-message brain to Telegram...")
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


def push_summary():
    intel = load_intel()
    if not intel:
        send_message("❌ No brain data yet.")
        return
    send_chunked(build_msg2_summary_govt(intel))


def push_opps():
    intel = load_intel()
    if not intel:
        send_message("❌ No brain data yet.")
        return
    text = intel.get('analysis', '')
    full = extract_section(text, KW['opps'], KW['risks'])
    if not full:
        send_message("💎 <b>OPPORTUNITIES</b>\n\n<i>Section not found.</i>")
        return
    send_chunked(f"💎 <b>TOP OPPORTUNITIES</b>\n\n{full}")


def push_risks():
    intel = load_intel()
    if not intel:
        send_message("❌ No brain data yet.")
        return
    text = intel.get('analysis', '')
    risks = extract_section(text, KW['risks'], KW['sectors'] + KW['global'])
    if not risks:
        send_message("⚠️ <b>RISKS</b>\n\n<i>Section not found.</i>")
        return
    send_chunked(f"⚠️ <b>TOP RISKS / AVOID LIST</b>\n\n{risks}")


def push_action():
    intel = load_intel()
    if not intel:
        send_message("❌ No brain data yet.")
        return
    text = intel.get('analysis', '')
    action = extract_section(text, KW['action'], None)
    if not action:
        send_message("🚀 <b>ACTION PLAN</b>\n\n<i>Section not found.</i>")
        return
    send_chunked(f"🚀 <b>ACTION PLAN</b>\n\n{action}")


def push_calibration():
    intel = load_intel()
    if not intel:
        send_message("❌ No brain data yet.")
        return
    text = intel.get('analysis', '')
    cal = extract_section(text, KW['calibration'], KW['opps'])
    if not cal:
        send_message("🎯 <b>SELF-CALIBRATION</b>\n\n<i>Need 10+ evaluated predictions for memory to populate.</i>")
        return
    send_chunked(f"🎯 <b>SELF-CALIBRATION</b>\n\n{cal}")


def push_sectors():
    intel = load_intel()
    if not intel:
        send_message("❌ No brain data yet.")
        return
    text = intel.get('analysis', '')
    sectors = extract_section(text, KW['sectors'], KW['global'] + KW['scanner_news'])
    if not sectors:
        send_message("🔄 <b>SECTORS</b>\n\n<i>Section not found.</i>")
        return
    send_chunked(f"🔄 <b>SECTOR ROTATION</b>\n\n{sectors}")


def push_global():
    intel = load_intel()
    if not intel:
        send_message("❌ No brain data yet.")
        return
    text = intel.get('analysis', '')
    g = extract_section(text, KW['global'], KW['scanner_news'] + KW['cross_val'])
    if not g:
        send_message("🌍 <b>GLOBAL</b>\n\n<i>Section not found.</i>")
        return
    send_chunked(f"🌍 <b>OVERNIGHT GLOBAL IMPACT</b>\n\n{g}")


# ============================================================
# CLI
# ============================================================

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
        'global': push_global,
    }

    func = dispatch.get(mode)
    if func:
        func()
    else:
        safe_print(f"[ERROR] Unknown mode: {mode}")
        safe_print(f"Valid: {', '.join(dispatch.keys())}")
        sys.exit(1)