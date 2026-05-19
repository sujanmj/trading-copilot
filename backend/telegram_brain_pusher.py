"""
telegram_brain_pusher.py - Push full Brain analysis to Telegram
================================================================
Sends the complete unified intelligence to Telegram in formatted chunks.

Telegram has 4096 char limit per message, so splits intelligently.

Usage:
  python telegram_brain_pusher.py          # Send latest brain
  python telegram_brain_pusher.py summary  # Send executive summary only
  python telegram_brain_pusher.py opps     # Send only opportunities
"""

import os
import sys
import json
import requests
from pathlib import Path
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / 'config' / 'keys.env'
    if env_path.exists():
        load_dotenv(env_path, override=False)
except ImportError:
    pass

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR.parent / 'data'

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

MAX_MESSAGE_LENGTH = 4000  # Telegram limit is 4096, leave buffer


def send_telegram_message(text, parse_mode='HTML', disable_preview=True):
    """Send a single Telegram message"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[ERROR] Telegram credentials not set")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': text,
        'parse_mode': parse_mode,
        'disable_web_page_preview': disable_preview
    }
    
    try:
        response = requests.post(url, json=payload, timeout=15)
        if response.status_code == 200:
            return True
        else:
            print(f"[ERROR] Telegram returned {response.status_code}: {response.text[:200]}")
            return False
    except Exception as e:
        print(f"[ERROR] Telegram send failed: {e}")
        return False


def split_into_chunks(text, max_length=MAX_MESSAGE_LENGTH):
    """Split long text into Telegram-sized chunks at sensible boundaries"""
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    
    # Split by sections (## markers) first
    sections = text.split('\n##')
    
    current_chunk = ""
    for i, section in enumerate(sections):
        if i > 0:
            section = '##' + section  # Re-add the ## that was removed
        
        # If single section is too big, split by lines
        if len(section) > max_length:
            lines = section.split('\n')
            for line in lines:
                if len(current_chunk) + len(line) + 1 > max_length:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = line + '\n'
                else:
                    current_chunk += line + '\n'
        else:
            # Try to keep section together
            if len(current_chunk) + len(section) > max_length:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = section
            else:
                current_chunk += '\n' + section
    
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks


def format_for_telegram(text):
    """Convert markdown to Telegram HTML format"""
    # Escape HTML special chars first
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    # Convert markdown bold to HTML
    import re
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    
    # Convert headers
    text = re.sub(r'^### (.+)$', r'<b>📌 \1</b>', text, flags=re.MULTILINE)
    text = re.sub(r'^## (.+)$', r'<b>━━━ \1 ━━━</b>', text, flags=re.MULTILINE)
    text = re.sub(r'^# (.+)$', r'<b>🎯 \1 🎯</b>', text, flags=re.MULTILINE)
    
    # Bullets
    text = re.sub(r'^- ', '• ', text, flags=re.MULTILINE)
    
    return text


def load_intelligence():
    """Load latest unified intelligence"""
    intel_file = DATA_DIR / 'unified_intelligence.json'
    if not intel_file.exists():
        return None
    
    try:
        with open(intel_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to load intelligence: {e}")
        return None


def extract_section(text, section_name):
    """Extract a specific section from the brain analysis"""
    import re
    
    # Find the section
    pattern = rf'## {re.escape(section_name)}.*?(?=\n## |$)'
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    
    if match:
        return match.group(0)
    return None


def send_full_brain():
    """Send the complete brain analysis to Telegram in chunks"""
    intel = load_intelligence()
    if not intel:
        send_telegram_message("⚠️ No intelligence data available yet")
        return False
    
    analysis = intel.get('analysis', '')
    if not analysis:
        send_telegram_message("⚠️ Empty analysis")
        return False
    
    timestamp = intel.get('generation_time', 'unknown')
    sources = intel.get('sources_used', 0)
    market_open = intel.get('market_open', False)
    
    # Header
    header = f"""🧠 <b>BRAIN INTELLIGENCE</b>
🕐 {timestamp}
📊 Sources: {sources}/8 | Market: {'OPEN ✅' if market_open else 'CLOSED ⏸️'}
━━━━━━━━━━━━━━━━━━━━━━━━

"""
    
    # Format for Telegram
    formatted = format_for_telegram(analysis)
    
    # Split into chunks
    chunks = split_into_chunks(formatted, max_length=MAX_MESSAGE_LENGTH - 100)
    
    print(f"[INFO] Sending {len(chunks)} message(s) to Telegram...")
    
    # Send header first
    send_telegram_message(header)
    
    # Send each chunk with footer
    success_count = 0
    for i, chunk in enumerate(chunks, 1):
        prefix = f"<b>📄 Part {i}/{len(chunks)}</b>\n\n" if len(chunks) > 1 else ""
        if send_telegram_message(prefix + chunk):
            success_count += 1
        
        # Small delay to avoid rate limiting
        import time
        time.sleep(0.5)
    
    # Footer with quick actions
    footer = """━━━━━━━━━━━━━━━━━━━━━━━━
💬 <b>Quick Commands:</b>
/brain - Get full brain again
/summary - Executive summary only  
/opps - Top opportunities only
/risks - Top risks only
/scan - Latest scanner signals
/ask &lt;question&gt; - Ask AI anything
/status - System status

📱 Trading Copilot 24/7"""
    
    send_telegram_message(footer)
    
    print(f"[OK] Sent {success_count}/{len(chunks)} chunks successfully")
    return success_count == len(chunks)


def send_executive_summary():
    """Send only the executive summary"""
    intel = load_intelligence()
    if not intel:
        send_telegram_message("⚠️ No intelligence data available")
        return
    
    analysis = intel.get('analysis', '')
    section = extract_section(analysis, 'EXECUTIVE SUMMARY')
    
    if not section:
        # Try to extract first 1000 chars as summary
        section = analysis[:1500]
    
    timestamp = intel.get('generation_time', 'unknown')
    
    header = f"""🧠 <b>EXECUTIVE SUMMARY</b>
🕐 {timestamp}
━━━━━━━━━━━━━━━━━━━━━━━━

"""
    
    formatted = format_for_telegram(section)
    send_telegram_message(header + formatted)


def send_opportunities():
    """Send only TOP 10 OPPORTUNITIES section"""
    intel = load_intelligence()
    if not intel:
        send_telegram_message("⚠️ No intelligence data available")
        return
    
    analysis = intel.get('analysis', '')
    section = extract_section(analysis, 'TOP 10 OPPORTUNITIES')
    
    if not section:
        send_telegram_message("⚠️ Opportunities section not found")
        return
    
    header = "🏆 <b>TOP OPPORTUNITIES</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    formatted = format_for_telegram(section)
    chunks = split_into_chunks(formatted, max_length=MAX_MESSAGE_LENGTH - 200)
    
    for i, chunk in enumerate(chunks, 1):
        prefix = header if i == 1 else f"<b>(continued {i}/{len(chunks)})</b>\n\n"
        send_telegram_message(prefix + chunk)
        import time
        time.sleep(0.5)


def send_risks():
    """Send only TOP 10 RISKS section"""
    intel = load_intelligence()
    if not intel:
        send_telegram_message("⚠️ No intelligence data available")
        return
    
    analysis = intel.get('analysis', '')
    section = extract_section(analysis, 'TOP 10 RISKS')
    
    if not section:
        send_telegram_message("⚠️ Risks section not found")
        return
    
    header = "📉 <b>TOP RISKS / AVOID</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    formatted = format_for_telegram(section)
    chunks = split_into_chunks(formatted, max_length=MAX_MESSAGE_LENGTH - 200)
    
    for i, chunk in enumerate(chunks, 1):
        prefix = header if i == 1 else f"<b>(continued {i}/{len(chunks)})</b>\n\n"
        send_telegram_message(prefix + chunk)
        import time
        time.sleep(0.5)


def send_action_plan():
    """Send only ACTION PLAN section"""
    intel = load_intelligence()
    if not intel:
        send_telegram_message("⚠️ No intelligence data available")
        return
    
    analysis = intel.get('analysis', '')
    section = extract_section(analysis, 'ACTION PLAN')
    
    if not section:
        send_telegram_message("⚠️ Action plan section not found")
        return
    
    header = "🎯 <b>ACTION PLAN</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    formatted = format_for_telegram(section)
    chunks = split_into_chunks(formatted, max_length=MAX_MESSAGE_LENGTH - 200)
    
    for i, chunk in enumerate(chunks, 1):
        prefix = header if i == 1 else f"<b>(continued {i}/{len(chunks)})</b>\n\n"
        send_telegram_message(prefix + chunk)
        import time
        time.sleep(0.5)


def send_self_calibration():
    """Send the SELF-CALIBRATION section (memory-aware AI)"""
    intel = load_intelligence()
    if not intel:
        return
    
    analysis = intel.get('analysis', '')
    section = extract_section(analysis, 'SELF-CALIBRATION')
    
    if not section:
        return
    
    header = "🤖 <b>AI SELF-CALIBRATION</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    formatted = format_for_telegram(section)
    send_telegram_message(header + formatted)


if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN:
        print("[ERROR] TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)
    
    mode = sys.argv[1] if len(sys.argv) > 1 else 'full'
    
    print("=" * 60)
    print(f"TELEGRAM BRAIN PUSHER - Mode: {mode}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    if mode == 'full' or mode == 'brain':
        send_full_brain()
    elif mode == 'summary':
        send_executive_summary()
    elif mode == 'opps' or mode == 'opportunities':
        send_opportunities()
    elif mode == 'risks':
        send_risks()
    elif mode == 'action':
        send_action_plan()
    elif mode == 'calibration':
        send_self_calibration()
    else:
        print(f"Unknown mode: {mode}")
        print("Usage: python telegram_brain_pusher.py [full|summary|opps|risks|action|calibration]")