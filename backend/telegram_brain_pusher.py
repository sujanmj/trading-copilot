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
from datetime import datetime, timezone
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


def _text(value, default='N/A'):
    if value is None:
        return default
    text = str(value).strip()
    if not text or text.lower() == 'none':
        return default
    return text


def _list(value):
    return value if isinstance(value, list) else []


def _dict(value):
    return value if isinstance(value, dict) else {}


def _join_list(items, default='Not identified'):
    if not isinstance(items, list):
        return default
    cleaned = [_text(x, '') for x in items]
    cleaned = [x for x in cleaned if x and x != 'N/A']
    return ', '.join(cleaned) if cleaned else default


def get_opportunities(intel):
    """Read opportunities from either field name used by analyzer versions."""
    if not isinstance(intel, dict):
        return []
    opps = intel.get('top_opportunities')
    if opps is None:
        opps = intel.get('opportunities')
    if not isinstance(opps, list):
        return []
    return opps


def debug_intel_fields(intel):
    """Log field types/counts to diagnose empty Telegram buy/sell lists."""
    if not isinstance(intel, dict):
        safe_print(f"[DEBUG] intel is {type(intel).__name__}, not dict")
        return
    safe_print(f"[DEBUG] top_opportunities type: {type(intel.get('top_opportunities'))}")
    safe_print(f"[DEBUG] top_opportunities count: {len(intel.get('top_opportunities') or [])}")
    safe_print(f"[DEBUG] opportunities type: {type(intel.get('opportunities'))}")
    safe_print(f"[DEBUG] opportunities count: {len(intel.get('opportunities') or [])}")
    opps = get_opportunities(intel)
    safe_print(f"[BRAIN PUSH] Sending {len(opps)} opportunities to Telegram")


def intel_age_hours(intel):
    """Return hours since last intel update, or None if unknown."""
    if not isinstance(intel, dict):
        return None
    ts = intel.get('timestamp') or intel.get('generation_time')
    if not ts:
        return None
    try:
        if isinstance(ts, str) and 'T' in ts:
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        else:
            dt = datetime.strptime(str(ts)[:19], '%Y-%m-%d %H:%M:%S')
            dt = dt.replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - dt
        return age.total_seconds() / 3600
    except Exception:
        return None


def stale_warning(intel):
    hours = intel_age_hours(intel)
    if hours is not None and hours > 2:
        return f"⚠️ Analysis may be stale — last updated {hours:.1f} hours ago\n\n"
    return ''


def normalize_intel(intel):
    """Map old and new unified_intelligence.json field names to canonical keys."""
    if not intel or intel.get('error'):
        return {}

    mood = _dict(intel.get('market_mood'))
    if intel.get('market_bias') and not mood.get('global_mood'):
        mood['global_mood'] = intel.get('market_bias')
    if intel.get('confidence_score') and not mood.get('confidence_level'):
        mood['confidence_level'] = intel.get('confidence_score')

    summary = intel.get('executive_summary')
    if summary is None:
        summary = intel.get('analysis')

    opps = get_opportunities(intel)
    risks = intel.get('risks_and_avoids')
    if risks is None:
        risks = intel.get('risks')

    return {
        'timestamp': intel.get('timestamp'),
        'generation_time': intel.get('generation_time') or intel.get('timestamp'),
        'sources_used': intel.get('sources_used'),
        'executive_summary': summary,
        'government_impact': _dict(intel.get('government_impact')),
        'market_mood': mood,
        'sector_rotation': _dict(intel.get('sector_rotation')),
        'action_plan': intel.get('action_plan'),
        'self_calibration': intel.get('self_calibration'),
        'top_opportunities': _list(opps),
        'risks_and_avoids': _list(risks),
        'opportunities': _list(opps),
    }

# ============================================================
# FORMATTING HELPERS FOR JSON
# ============================================================

def format_opps(opps_list):
    opps_list = _list(opps_list)
    if not opps_list:
        return "<i>📊 Scanner running — no high conviction signals right now</i>"
    res = []
    for i, o in enumerate(opps_list, 1):
        o = _dict(o)
        action = _text(o.get('action'), 'WATCH').upper()
        icon = "🟢" if action == "BUY" else "🟡"
        res.append(
            f"{i}. {icon} <b>{_text(o.get('symbol'), 'UNKNOWN')}</b> [{action}]\n"
            f"   💰 Entry: {_text(o.get('entry_zone'))} | Tgt: {_text(o.get('target'))} | SL: {_text(o.get('stop_loss'))}\n"
            f"   📊 Conf: <b>{_text(o.get('confidence'), 'MEDIUM')}</b>\n"
            f"   <i>{_text(o.get('logic'), 'No rationale provided.')}</i>"
        )
    return "\n\n".join(res)


def format_risks(risks_list):
    risks_list = _list(risks_list)
    if not risks_list:
        return "<i>No risks found in analysis.</i>"
    res = []
    for i, r in enumerate(risks_list, 1):
        r = _dict(r)
        res.append(
            f"{i}. 🔴 <b>{_text(r.get('symbol'), 'UNKNOWN')}</b>\n"
            f"   <i>{_text(r.get('logic'), 'No risk rationale provided.')}</i>"
        )
    return "\n\n".join(res)

# ============================================================
# MESSAGE BUILDERS
# ============================================================

def build_msg1_header(intel):
    intel = normalize_intel(intel)
    stale = stale_warning(intel)
    ts_str = _text(intel.get('generation_time'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    mood = _dict(intel.get('market_mood'))
    confidence = _text(mood.get('confidence_level'), 'N/A')
    sources_used = intel.get('sources_used')
    sources_text = str(sources_used) if sources_used is not None else '8'

    return f"""{stale}🧠 <b>UNIFIED MARKET INTELLIGENCE</b>
━━━━━━━━━━━━━━━━━━━━

📅 <i>{ts_str}</i>
📊 System Confidence: <b>{confidence}</b>
📡 Sources Parsed: <b>{sources_text}/8</b>

<i>📨 Sending full JSON-parsed analysis...</i>"""


def build_msg2_summary_govt(intel):
    intel = normalize_intel(intel)
    summary = _text(intel.get('executive_summary'), 'Analysis pending...')
    govt = _dict(intel.get('government_impact'))

    govt_text = f"<b>Impact:</b> {_text(govt.get('summary'), 'No government impact data available.')}\n"
    govt_text += f"<b>Confidence:</b> {_text(govt.get('confidence_score'), 'N/A')}"

    return f"📋 <b>EXECUTIVE SUMMARY</b>\n\n{summary}\n\n━━━━━━━━━━━━━━━━━━━━\n\n🏛️ <b>GOVT POLICY IMPACT</b>\n\n{govt_text}"


def build_msg3_scanner_sentiment(intel):
    intel = normalize_intel(intel)
    mood = _dict(intel.get('market_mood'))

    parts = [
        "💬 <b>MARKET MOOD & SENTIMENT</b>",
        f"🌍 <b>Global:</b> {_text(mood.get('global_mood'), 'Unknown')}",
        f"🇮🇳 <b>India:</b> {_text(mood.get('india_outlook'), 'Unknown')}",
        f"🛒 <b>Retail:</b> {_text(mood.get('retail_mood'), 'Unknown')}",
    ]
    return "\n\n".join(parts)

def build_msg4_calibration_opps_top5(intel):
    intel = normalize_intel(intel)
    cal = _text(intel.get('self_calibration'), 'No calibration data available.')
    opps = get_opportunities(intel)

    opps_text = format_opps(opps[:5])

    return f"🎯 <b>SELF-CALIBRATION</b>\n\n{cal}\n\n━━━━━━━━━━━━━━━━━━━━\n\n💎 <b>TOP OPPORTUNITIES (1-5)</b>\n\n{opps_text}"


def build_msg5_opps_top10_risks(intel):
    intel = normalize_intel(intel)
    opps = get_opportunities(intel)
    risks = _list(intel.get('risks_and_avoids'))

    opps_text = format_opps(opps[5:10]) if len(opps) > 5 else "<i>No additional opportunities.</i>"
    risks_text = format_risks(risks)

    return f"💎 <b>TOP OPPORTUNITIES (6-10)</b>\n\n{opps_text}\n\n━━━━━━━━━━━━━━━━━━━━\n\n⚠️ <b>TOP RISKS / AVOID LIST</b>\n\n{risks_text}"


def build_msg6_sectors_global_action(intel):
    intel = normalize_intel(intel)
    sectors = _dict(intel.get('sector_rotation'))
    bullish = _join_list(sectors.get('bullish'))
    bearish = _join_list(sectors.get('bearish'))
    action = _text(intel.get('action_plan'), 'No action plan provided.')

    parts = [
        "🔄 <b>SECTOR ROTATION</b>",
        f"🟢 <b>Bullish:</b> {bullish}",
        f"🔴 <b>Bearish:</b> {bearish}",
        "━━━━━━━━━━━━━━━━━━━━",
        "🚀 <b>ACTION PLAN</b>",
        action,
        "━━━━━━━━━━━━━━━━━━━━",
        "📌 <b>QUICK COMMANDS</b>\n\n/brain — Full brain\n/elite — ML Filtered Setups\n/opps — Opportunities\n/risks — Avoid list\n/action — Action plan\n/sectors — Sector rotation\n\n<i>Brain auto-pushes after each strategic run.</i>",
    ]
    return "\n\n".join(parts)


def check_intel_file_stale(max_age_hours=2):
    """Return (is_stale, age_hours). Sends Telegram warning and blocks push if stale."""
    if not INTEL_FILE.exists():
        safe_print("[WARN] unified_intelligence.json missing")
        send_message("⚠️ Market intelligence file missing. Run /refresh to generate analysis.")
        return True, None

    file_age_hours = (time.time() - INTEL_FILE.stat().st_mtime) / 3600
    if file_age_hours > max_age_hours:
        safe_print(f"[WARN] Intelligence is {file_age_hours:.1f}h old - sending stale warning")
        send_message(
            f"⚠️ Market intelligence is stale ({file_age_hours:.1f}h old). "
            "Analyzer may have issues — run /refresh or check Railway logs."
        )
        return True, file_age_hours
    return False, file_age_hours


def push_full_brain():
    is_stale, age = check_intel_file_stale()
    if is_stale:
        safe_print(f"[BRAIN] Blocked push — intel file stale or missing (age={age})")
        return False

    raw_intel = load_intel()
    debug_intel_fields(raw_intel)
    intel = normalize_intel(raw_intel)
    if not intel:
        send_message("❌ No brain data yet. Run /refresh first.")
        return False

    opps = get_opportunities(intel)
    if not opps:
        safe_print("[BRAIN] No opportunities in intel — pushing analysis with scanner notice")
    
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
    intel = normalize_intel(load_intel())
    if intel:
        send_chunked(build_msg2_summary_govt(intel))


def push_opps():
    raw = load_intel()
    debug_intel_fields(raw)
    intel = normalize_intel(raw)
    if intel:
        opps = get_opportunities(intel)
        send_chunked(f"💎 <b>TOP OPPORTUNITIES</b>\n\n{format_opps(opps)}")


def push_risks():
    intel = normalize_intel(load_intel())
    if intel:
        risks = _list(intel.get('risks_and_avoids'))
        send_chunked(f"⚠️ <b>TOP RISKS / AVOID LIST</b>\n\n{format_risks(risks)}")


def push_action():
    intel = normalize_intel(load_intel())
    if intel:
        send_chunked(f"🚀 <b>ACTION PLAN</b>\n\n{_text(intel.get('action_plan'), 'No action plan provided.')}")


def push_calibration():
    intel = normalize_intel(load_intel())
    if intel:
        send_chunked(f"🎯 <b>SELF-CALIBRATION</b>\n\n{_text(intel.get('self_calibration'), 'No calibration data available.')}")


def push_sectors():
    intel = normalize_intel(load_intel())
    if intel:
        sectors = _dict(intel.get('sector_rotation'))
        bullish = _join_list(sectors.get('bullish'))
        bearish = _join_list(sectors.get('bearish'))
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