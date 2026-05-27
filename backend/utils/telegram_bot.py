"""
Telegram Bot v1 - Path G
Core bot for sending alerts to your phone

Usage:
  from telegram_bot import send_alert, send_morning_brief, send_outcome_report
  send_alert("Hello world!")

Test:
  python telegram_bot.py
"""

import os
os.environ['PYTHONIOENCODING'] = 'utf-8'

import sys
import json
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


from backend.utils.config import CONFIG_DIR, DATA_DIR, DB_PATH

load_dotenv(CONFIG_DIR / 'keys.env')


BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Track sent alerts to avoid duplicates (in-memory + file-backed)
SENT_LOG_FILE = DATA_DIR / '_telegram_sent.json'


# ============================================================
# CORE SEND FUNCTION
# ============================================================

def send_message(text, parse_mode='HTML', disable_preview=True):
    """Send a message to your Telegram chat
    
    parse_mode: 'HTML' (recommended) or 'Markdown'
    """
    if not BOT_TOKEN or not CHAT_ID:
        safe_print("[TG ERROR] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return False
    
    # Telegram limit: 4096 chars
    if len(text) > 4000:
        text = text[:3950] + "\n\n... (truncated)"
    
    try:
        response = requests.post(
            f"{API_URL}/sendMessage",
            json={
                'chat_id': CHAT_ID,
                'text': text,
                'parse_mode': parse_mode,
                'disable_web_page_preview': disable_preview,
            },
            timeout=10
        )
        
        if response.status_code == 200:
            return True
        else:
            err = response.json().get('description', 'unknown')
            safe_print(f"[TG ERROR] {response.status_code}: {err}")
            return False
    
    except requests.Timeout:
        safe_print("[TG ERROR] Timeout")
        return False
    except Exception as e:
        safe_print(f"[TG ERROR] {e}")
        return False


# ============================================================
# DEDUPE LOGIC (Don't spam the same alert)
# ============================================================

def load_sent_log():
    """Load previously sent alerts (to avoid duplicates)"""
    if not SENT_LOG_FILE.exists():
        return {}
    try:
        with open(SENT_LOG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Clean up entries older than 7 days
        cutoff = datetime.now().timestamp() - (7 * 86400)
        cleaned = {k: v for k, v in data.items() if v.get('timestamp', 0) > cutoff}
        return cleaned
    except Exception:
        return {}


def save_sent_log(log):
    SENT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(SENT_LOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(log, f, indent=2)
    except Exception as e:
        safe_print(f"[TG WARN] Failed to save sent log: {e}")


def already_sent(alert_key):
    """Check if we already sent this alert recently"""
    log = load_sent_log()
    return alert_key in log


def mark_as_sent(alert_key):
    log = load_sent_log()
    log[alert_key] = {'timestamp': datetime.now().timestamp()}
    save_sent_log(log)


# ============================================================
# HIGH-LEVEL ALERT FUNCTIONS
# ============================================================

def send_alert(text, alert_key=None):
    """Send a generic alert with optional dedupe key"""
    if alert_key and already_sent(alert_key):
        safe_print(f"[TG] Skipped duplicate: {alert_key}")
        return False
    
    success = send_message(text)
    if success and alert_key:
        mark_as_sent(alert_key)
    return success


def send_ultra_signal(signal):
    """Send alert for ULTRA scanner signal"""
    ticker = signal.get('ticker', '?')
    sector = signal.get('sector', '?')
    direction = signal.get('direction', '?')
    change = signal.get('change_percent', 0)
    volume_ratio = signal.get('volume_ratio', 0)
    price = signal.get('price', 0)
    signals = signal.get('signals', [])
    
    # Dedupe: same ticker + direction within 4 hours
    today = datetime.now().date().isoformat()
    hour_block = datetime.now().hour // 4  # 0,1,2,3,4,5
    alert_key = f"ultra_{ticker}_{direction}_{today}_{hour_block}"
    
    if already_sent(alert_key):
        return False
    
    emoji = "🚀" if direction == 'BULLISH' else "💥"
    sign = "+" if change >= 0 else ""
    
    text = f"""<b>{emoji} ULTRA ALERT</b>
<b>{ticker}</b> ({sector})
{sign}{change:.2f}% | <b>{volume_ratio:.1f}x avg volume</b>
Price: Rs.{price:,.2f}

<b>Signals:</b> {' + '.join(signals)}
<b>Direction:</b> {direction}

<i>Multiple strong signals stacked - act with conviction</i>"""
    
    success = send_message(text)
    if success:
        mark_as_sent(alert_key)
    return success


def send_govt_alert(item):
    """Send alert for high-impact govt announcement"""
    score = item.get('impact_score', 0)
    direction = item.get('direction', 'NEUTRAL')
    headline = item.get('english_headline', item.get('title', ''))[:200]
    source = item.get('source', '?')
    stocks = item.get('affected_stocks', [])
    relevance = item.get('market_relevance', '')
    link = item.get('link', '')
    
    # Dedupe by headline
    alert_key = f"govt_{headline[:60]}"
    if already_sent(alert_key):
        return False
    
    # Only alert on score >= 7
    if score < 7:
        return False
    
    emoji = "📈" if direction == 'BULLISH' else "📉" if direction == 'BEARISH' else "🏛️"
    
    text = f"""<b>{emoji} GOVT POLICY ALERT</b>
<b>{score}/10 {direction}</b> | {source}

{headline}

<b>Affected:</b> {', '.join(stocks[:6]) if stocks else 'Sector-wide'}
<b>Relevance:</b> {relevance}"""
    
    if link:
        text += f"\n\n<a href='{link}'>Read full announcement</a>"
    
    success = send_message(text, disable_preview=False)
    if success:
        mark_as_sent(alert_key)
    return success


def send_morning_brief(intel_data):
    """Send daily morning brief at 8:45 AM"""
    if not intel_data:
        return False
    
    analysis = intel_data.get('analysis', '')
    timestamp = intel_data.get('timestamp', '')
    today = timestamp[:10] if timestamp else datetime.now().date().isoformat()
    
    alert_key = f"morning_brief_{today}"
    if already_sent(alert_key):
        return False
    
    # Extract key sections
    import re
    
    # Conviction
    conv_match = re.search(r'Overall conviction[:\s]+(\d+)/10', analysis, re.IGNORECASE)
    conviction = int(conv_match.group(1)) if conv_match else 0
    
    # Executive summary
    exec_match = re.search(r'#{1,3}[^\n]*EXECUTIVE SUMMARY[^\n]*\n(.+?)(?=\n#{1,3}|\Z)', 
                           analysis, re.IGNORECASE | re.DOTALL)
    exec_summary = exec_match.group(1).strip()[:500] if exec_match else ""
    
    # Top 5 opportunities (just headers)
    opp_match = re.search(r'#{1,3}[^\n]*OPPORTUNITIES[^\n]*\n(.+?)(?=\n#{1,3}|\Z)', 
                          analysis, re.IGNORECASE | re.DOTALL)
    top_opps = []
    if opp_match:
        opp_text = opp_match.group(1)
        opp_lines = re.findall(r'\n\s*(\d{1,2})\.\s+([^\n]+)', opp_text)
        for rank, line in opp_lines[:5]:
            # Clean up
            cleaned = line.replace('**', '').strip()[:100]
            top_opps.append(f"{rank}. {cleaned}")
    
    # Top 5 risks
    risk_match = re.search(r'#{1,3}[^\n]*RISKS[^\n]*\n(.+?)(?=\n#{1,3}|\Z)', 
                           analysis, re.IGNORECASE | re.DOTALL)
    top_risks = []
    if risk_match:
        risk_text = risk_match.group(1)
        risk_lines = re.findall(r'\n\s*(\d{1,2})\.\s+([^\n]+)', risk_text)
        for rank, line in risk_lines[:5]:
            cleaned = line.replace('**', '').strip()[:80]
            top_risks.append(f"{rank}. {cleaned}")
    
    # Build message
    stars = '⭐' * (conviction // 2)
    text = f"""<b>☀️ MORNING BRIEF</b>
<b>Date:</b> {today}
<b>Conviction:</b> {conviction}/10 {stars}

<b>📋 SUMMARY:</b>
<i>{exec_summary[:400]}{'...' if len(exec_summary) > 400 else ''}</i>

<b>🎯 TOP OPPORTUNITIES:</b>
{chr(10).join(top_opps) if top_opps else 'None detected'}

<b>⚠️ TOP RISKS:</b>
{chr(10).join(top_risks) if top_risks else 'None detected'}

<i>Open Trading Copilot for full analysis</i>"""
    
    success = send_message(text)
    if success:
        mark_as_sent(alert_key)
    return success


def send_outcome_report(metrics, top_winners=None, top_losers=None):
    """Send daily outcome report at 8 AM"""
    if not metrics:
        return False
    
    today = datetime.now().date().isoformat()
    alert_key = f"outcome_report_{today}"
    if already_sent(alert_key):
        return False
    
    win_rate = metrics.get('win_rate', 0)
    wins = metrics.get('wins', 0)
    losses = metrics.get('losses', 0)
    neutral = metrics.get('neutral', 0)
    pending = metrics.get('pending', 0)
    avg_gain = metrics.get('avg_gain_pct', 0)
    avg_loss = metrics.get('avg_loss_pct', 0)
    profit_factor = metrics.get('profit_factor', 0)
    
    # Skip if no evaluated outcomes
    evaluated = metrics.get('evaluated') or metrics.get('total_evaluated', 0)
    if evaluated == 0 and (wins + losses + neutral) == 0:
        return False
    
    # Emoji based on win rate
    if win_rate >= 65:
        emoji = "🏆"
    elif win_rate >= 50:
        emoji = "✅"
    else:
        emoji = "⚠️"
    
    text = f"""<b>{emoji} DAILY OUTCOME REPORT</b>
<b>Date:</b> {today}

<b>📊 STATS:</b>
Win Rate: <b>{win_rate:.1f}%</b>
✅ Wins: {wins}  |  ❌ Losses: {losses}
○ Neutral: {neutral}  |  ⏳ Pending: {pending}

<b>💰 PERFORMANCE:</b>
Avg Win: +{avg_gain:.2f}%
Avg Loss: -{avg_loss:.2f}%
Profit Factor: {profit_factor:.2f}"""
    
    if top_winners:
        text += "\n\n<b>🏆 TOP WINNERS:</b>"
        for w in top_winners[:3]:
            ticker = w.get('ticker', '?')
            gain = w.get('max_gain_pct', 0)
            text += f"\n• {ticker} +{gain:.2f}%"
    
    if top_losers:
        text += "\n\n<b>📉 LESSONS LEARNED:</b>"
        for l in top_losers[:3]:
            ticker = l.get('ticker', '?')
            loss = l.get('max_loss_pct', 0)
            text += f"\n• {ticker} {loss:.2f}%"
    
    success = send_message(text)
    if success:
        mark_as_sent(alert_key)
    return success


# ============================================================
# TEST FUNCTION
# ============================================================

def run_test():
    safe_print("=" * 60)
    safe_print("TELEGRAM BOT TEST")
    safe_print("=" * 60)
    
    if not BOT_TOKEN:
        safe_print("[ERROR] TELEGRAM_BOT_TOKEN not found in keys.env")
        return False
    if not CHAT_ID:
        safe_print("[ERROR] TELEGRAM_CHAT_ID not found in keys.env")
        return False
    
    safe_print(f"[INFO] Bot token: {BOT_TOKEN[:10]}...{BOT_TOKEN[-4:]}")
    safe_print(f"[INFO] Chat ID: {CHAT_ID}")
    
    # Test 1: Simple message
    safe_print("\n[TEST 1] Sending hello message...")
    success = send_message("""<b>🎉 Trading Copilot Connected!</b>

Your trading copilot is now connected to Telegram.

You'll receive alerts for:
• 🚀 ULTRA scanner signals
• 🏛️ High-impact govt announcements
• ☀️ Morning brief (8:45 AM)
• 📊 Outcome reports (8 AM)

<i>This is a test message - the system is working correctly.</i>""")
    
    if success:
        safe_print("[OK] Test message sent! Check your Telegram now.")
    else:
        safe_print("[FAIL] Could not send message")
        return False
    
    # Test 2: Mock ULTRA signal
    safe_print("\n[TEST 2] Sending mock ULTRA signal...")
    mock_signal = {
        'ticker': 'TATACONSUM',
        'sector': 'FMCG',
        'direction': 'BULLISH',
        'change_percent': 8.06,
        'volume_ratio': 12.3,
        'price': 1015.50,
        'signals': ['VOLUME_SPIKE', 'BREAKOUT', 'GAP_UP'],
    }
    success = send_ultra_signal(mock_signal)
    if success:
        safe_print("[OK] Mock signal sent!")
    
    safe_print("\n" + "=" * 60)
    safe_print("TEST COMPLETE - Check your Telegram chat")
    safe_print("=" * 60)
    return True


if __name__ == "__main__":
    run_test()