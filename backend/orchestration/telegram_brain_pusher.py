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

env_path = Path(__file__).resolve().parent.parent.parent / 'config' / 'keys.env'
load_dotenv(env_path, override=False)

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'
INTEL_FILE = DATA_DIR / 'unified_intelligence.json'


def send_message(text, parse_mode='HTML', *, command='', cycle_id='', message_kind='final'):
    if not BOT_TOKEN or not CHAT_ID:
        safe_print("[ERROR] Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return False
    if len(text) > 4000:
        text = text[:3950] + "\n... (truncated)"
    try:
        from backend.orchestration.telegram_outbound_guard import (
            get_cycle_id,
            prepare_send,
            record_outbound,
        )
        prep = prepare_send(
            text,
            command=command,
            cycle_id=cycle_id or get_cycle_id(command),
            message_kind=message_kind,
        )
        if prep.get('action') == 'skip':
            return False
        if prep.get('action') == 'edit':
            r = requests.post(
                f"{API_URL}/editMessageText",
                json={
                    'chat_id': CHAT_ID,
                    'message_id': prep['message_id'],
                    'text': text,
                    'parse_mode': parse_mode,
                    'disable_web_page_preview': True,
                },
                timeout=10,
            )
            if r.status_code == 200:
                record_outbound(
                    prep['msg_hash'],
                    command=command,
                    message_kind='loading',
                    message_id=prep['message_id'],
                    text=text,
                )
                return True
            return False
        r = requests.post(
            f"{API_URL}/sendMessage",
            json={
                'chat_id': CHAT_ID,
                'text': text,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True,
            },
            timeout=10,
        )
        if r.status_code == 200:
            message_id = None
            try:
                message_id = r.json().get('result', {}).get('message_id')
            except Exception:
                pass
            record_outbound(
                prep['msg_hash'],
                command=command,
                message_kind=message_kind,
                message_id=message_id,
                text=text,
            )
            return True
        return False
    except Exception as e:
        safe_print(f"[TG] Send error: {e}")
        return False

def _snapshot_prefix():
    try:
        from backend.intelligence.active_snapshot import snapshot_header, snapshot_stale_warning
        return snapshot_stale_warning() + snapshot_header()
    except Exception:
        return ''


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

def send_chunked(text, *, command='', cycle_id='', message_kind='final'):
    for chunk in chunk_message(text):
        send_message(chunk, command=command, cycle_id=cycle_id, message_kind=message_kind)
        time.sleep(0.5)

def load_intel():
    try:
        from backend.intelligence.active_snapshot import get_canonical_intelligence
        return get_canonical_intelligence()
    except Exception:
        pass
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
    try:
        from backend.utils.market_hours import get_operational_status
        op = get_operational_status()
        if op.get('expect_quiet_collectors'):
            return "🌙 <i>Night mode — awaiting pre-market intelligence cycle</i>\n\n"
    except Exception:
        pass
    hours = intel_age_hours(intel)
    if hours is not None and hours > 2:
        try:
            from backend.utils.market_hours import get_operational_status, get_watchdog_config
            op = get_operational_status()
            if not op.get('market_hours'):
                return "🌙 <i>Night mode — awaiting pre-market intelligence cycle</i>\n\n"
            wd = get_watchdog_config()
            threshold_h = float(wd.get('stale_threshold_seconds') or 7200) / 3600.0
            if hours <= threshold_h:
                return ''
        except Exception:
            pass
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

def format_opps(opps_list, *, tier_label=None):
    opps_list = _list(opps_list)
    if not opps_list:
        return None
    try:
        from backend.orchestration.opportunity_filter import elite_alignment_summary
        summary = elite_alignment_summary(opps_list)
    except Exception:
        summary = {}
    header = ""
    if tier_label:
        header = f"<b>{tier_label}</b>\n"
    elif summary.get('all_below_elite'):
        header = (
            "<i>🛡️ Scanner-ranked setups below elite meta-labeler threshold.</i>\n\n"
        )
    elif summary.get('has_elite_verified'):
        header = f"<i>✅ {summary.get('elite_verified_count', 0)} elite-verified</i>\n\n"
    res = [header] if header else []
    for i, o in enumerate(opps_list, 1):
        o = _dict(o)
        action = _text(o.get('action'), 'WATCH').upper()
        icon = "🟢" if action == "BUY" else "🟡"
        tier = o.get('display_tier') or ''
        tier_tag = f" [{tier}]" if tier else ''
        conf = _text(o.get('display_confidence') or o.get('confidence'), 'MEDIUM').upper()
        note = o.get('confidence_note') or ''
        note_html = f"\n   ⚠️ <i>{note}</i>" if note else ""
        ml = o.get('ml_confidence')
        ml_html = f" · ML {ml}" if ml and o.get('elite_verified') else ""
        res.append(
            f"{i}. {icon} <b>{_text(o.get('symbol'), 'UNKNOWN')}</b>{tier_tag} [{action}]\n"
            f"   💰 Entry: {_text(o.get('entry_zone'))} | Tgt: {_text(o.get('target'))} | SL: {_text(o.get('stop_loss'))}\n"
            f"   📊 Conf: <b>{conf}</b>{ml_html}{note_html}\n"
            f"   <i>{_text(o.get('logic'), 'No rationale provided.')}</i>"
        )
    return "\n\n".join(res)


def format_opps_tiered(tiers: dict, *, include_elite: bool = False) -> str:
    """Format ELITE / TACTICAL / WATCHLIST — never false-empty when scanner ULTRA exists."""
    tactical = _list((tiers or {}).get('tactical'))
    watchlist = _list((tiers or {}).get('watchlist'))
    elite = _list((tiers or {}).get('elite'))

    if not tactical and not watchlist and not (include_elite and elite):
        try:
            from backend.orchestration.opportunity_filter import rank_opportunities_tiered
            refill = rank_opportunities_tiered()
            tactical = _list(refill.get('tactical'))
            watchlist = _list(refill.get('watchlist'))
            elite = _list(refill.get('elite'))
        except Exception:
            pass

    sections = []
    if include_elite and elite:
        block = format_opps(elite, tier_label='🎯 ELITE')
        if block:
            sections.append(block)
    if tactical:
        block = format_opps(tactical, tier_label='⚡ TACTICAL')
        if block:
            sections.append(block)
    if watchlist:
        block = format_opps(watchlist, tier_label='👀 WATCHLIST')
        if block:
            sections.append(block)

    if sections:
        return "\n\n".join(sections)
    return "<i>📊 Scanner active — monitoring for fresh anomalies</i>"


def _professionalize_calibration_text(raw: str) -> str:
    text = _text(raw, '')
    if not text or text == 'No calibration data available.':
        return (
            '<i>Adaptive learning still collecting statistically meaningful samples.</i>'
        )
    lowered = text.lower()
    if '100%' in text and ('1/1' in text or '1-1' in lowered):
        return '<i>Early positive sample detected.</i>'
    if 'awaiting evaluated' in lowered or 'insufficient_data' in lowered:
        return '<i>Adaptive learning still collecting statistically meaningful samples.</i>'
    if 'win rate' in lowered and any(x in text for x in ('1/', '2/', '3/', '4/')):
        return '<i>Low-confidence calibration — sample still developing.</i>'
    return text[:1200]


def build_compressed_summary(intel):
    """Max 5 short sections — readable in under 5 seconds."""
    intel = normalize_intel(intel)
    stale = stale_warning(intel)
    mood = _dict(intel.get('market_mood'))
    sectors = _dict(intel.get('sector_rotation'))
    risks = _list(intel.get('risks_and_avoids'))

    regime = 'VOLATILE'
    try:
        from backend.utils.config import ANALYSIS_STATE_FILE
        if ANALYSIS_STATE_FILE.exists():
            state = json.loads(ANALYSIS_STATE_FILE.read_text(encoding='utf-8'))
            regime = str(state.get('last_regime') or 'volatile').replace('_', ' ').upper()
    except Exception:
        pass

    leaders = _join_list(sectors.get('bullish'), 'Not identified')
    if len(leaders) > 48:
        leaders = leaders[:45] + '...'

    risk_bits = []
    for r in risks[:3]:
        r = _dict(r)
        sym = _text(r.get('symbol'), '')
        logic = _text(r.get('logic'), '')
        bit = sym if sym and sym != 'UNKNOWN' else logic[:40]
        if bit:
            risk_bits.append(bit)
    risks_line = ', '.join(risk_bits) if risk_bits else 'Macro headline risk — monitor liquidity'

    bias = _text(mood.get('india_outlook') or mood.get('global_mood'), 'Selective')
    conf_raw = mood.get('confidence_level') or mood.get('confidence_score')
    try:
        conf_num = float(str(conf_raw).replace('/10', '').strip())
        conf_line = f"{conf_num:.1f}/10"
    except (TypeError, ValueError):
        conf_line = _text(conf_raw, 'N/A')

    return (
        f"{stale}📋 <b>EXECUTIVE SUMMARY</b>\n\n"
        f"<b>MARKET REGIME:</b>\n{regime}\n\n"
        f"<b>LEADERS:</b>\n{leaders}\n\n"
        f"<b>RISKS:</b>\n{risks_line}\n\n"
        f"<b>TACTICAL BIAS:</b>\n{bias}\n\n"
        f"<b>CONFIDENCE:</b>\n{conf_line}"
    )


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
    return build_compressed_summary(intel)


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
    cal = _professionalize_calibration_text(intel.get('self_calibration'))
    opps = get_opportunities(intel)
    opps_text = format_opps(opps[:5])
    if not opps_text:
        try:
            from backend.orchestration.opportunity_filter import rank_opportunities_tiered
            opps_text = format_opps_tiered(rank_opportunities_tiered(intel), include_elite=True)
        except Exception:
            opps_text = "<i>Monitoring for ranked setups.</i>"

    return f"🎯 <b>SELF-CALIBRATION</b>\n\n{cal}\n\n━━━━━━━━━━━━━━━━━━━━\n\n💎 <b>TOP OPPORTUNITIES (1-5)</b>\n\n{opps_text}"


def build_msg5_opps_top10_risks(intel):
    intel = normalize_intel(intel)
    opps = get_opportunities(intel)
    risks = _list(intel.get('risks_and_avoids'))

    opps_text = format_opps(opps[5:10]) if len(opps) > 5 else None
    if not opps_text:
        opps_text = "<i>No additional opportunities.</i>"
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
    """Return (is_stale, age_hours). Market-aware — idle overnight is NOT stale."""
    if not INTEL_FILE.exists():
        safe_print("[WARN] unified_intelligence.json missing")
        try:
            from backend.utils.market_hours import get_operational_status
            if get_operational_status().get('expect_quiet_collectors'):
                send_message(
                    "🌙 <b>Night mode</b>\n\n"
                    "Intelligence idle until pre-market cycle. Use /refresh during market hours if needed."
                )
                return True, None
        except Exception:
            pass
        send_message("⚠️ Market intelligence file missing. Run /refresh to generate analysis.")
        return True, None

    file_age_hours = (time.time() - INTEL_FILE.stat().st_mtime) / 3600
    try:
        from backend.utils.market_hours import get_operational_status, get_watchdog_config
        op = get_operational_status()
        if op.get('expect_quiet_collectors'):
            safe_print(f"[BRAIN] Night/idle mode — intel age {file_age_hours:.1f}h accepted")
            return False, file_age_hours
        wd = get_watchdog_config()
        max_age_hours = max(max_age_hours, float(wd.get('stale_threshold_seconds') or 7200) / 3600.0)
        if not op.get('market_hours'):
            return False, file_age_hours
    except Exception:
        pass

    if file_age_hours > max_age_hours:
        safe_print(f"[WARN] Intelligence is {file_age_hours:.1f}h old - sending stale warning")
        send_message(
            f"⚠️ Market intelligence is stale ({file_age_hours:.1f}h old). "
            "Expected cycle missed during market session — run /refresh or check Railway logs."
        )
        return True, file_age_hours
    return False, file_age_hours


def push_full_brain(*, command='full', cycle_id=''):
    is_stale, age = check_intel_file_stale()
    if is_stale:
        safe_print(f"[BRAIN] Blocked push — intel file stale or missing (age={age})")
        return False

    raw_intel = load_intel()
    debug_intel_fields(raw_intel)
    intel = normalize_intel(raw_intel)
    if not intel:
        send_message("❌ No brain data yet. Run /refresh first.", command=command, cycle_id=cycle_id)
        return False

    try:
        from backend.orchestration.opportunity_filter import rank_opportunities_tiered, DEFAULT_OPPS_LIMIT
        tiers = rank_opportunities_tiered(raw_intel, limit=DEFAULT_OPPS_LIMIT)
        ranked = tiers.get('all') or []
        intel['top_opportunities'] = ranked
        intel['opportunities'] = ranked
    except Exception as e:
        safe_print(f"[WARN] opportunity rank failed: {e}")

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
            send_chunked(text, command=command, cycle_id=cycle_id)
            safe_print(f"  ✓ {label}")
            time.sleep(0.8)
        except Exception as e:
            safe_print(f"[ERROR] {label}: {e}")
            send_message(
                f"❌ Error in {label}: {str(e)[:150]}",
                command=command,
                cycle_id=cycle_id,
            )
    safe_print("[BRAIN] Done.")
    return True

# ============================================================
# COMMAND DISPATCHERS
# ============================================================

def push_summary(*, command='summary', cycle_id=''):
    intel = normalize_intel(load_intel())
    if intel:
        send_chunked(build_compressed_summary(intel), command=command, cycle_id=cycle_id)


def push_opps(*, command='opps', cycle_id=''):
    from backend.orchestration.opportunity_filter import rank_opportunities_tiered, DEFAULT_OPPS_LIMIT
    raw = load_intel()
    debug_intel_fields(raw)
    intel = normalize_intel(raw)
    if intel:
        try:
            tiers = rank_opportunities_tiered(raw, limit=DEFAULT_OPPS_LIMIT)
            tactical_n = len(tiers.get('tactical') or [])
            watch_n = len(tiers.get('watchlist') or [])
            safe_print(f"[BRAIN PUSH] Tactical={tactical_n} Watchlist={watch_n}")
        except Exception as e:
            safe_print(f"[WARN] opportunity filter failed: {e}")
            tiers = {'tactical': get_opportunities(intel)[:DEFAULT_OPPS_LIMIT], 'watchlist': []}
        stale = stale_warning(raw)
        body = format_opps_tiered(tiers, include_elite=False)
        send_chunked(
            f"{stale}{_snapshot_prefix()}💎 <b>TACTICAL OPPORTUNITIES</b>\n"
            f"<i>Tactical scanner plays · /elite for ML-validated only</i>\n\n{body}",
            command=command,
            cycle_id=cycle_id,
        )


def push_risks(*, command='risks', cycle_id=''):
    intel = normalize_intel(load_intel())
    if intel:
        risks = _list(intel.get('risks_and_avoids'))
        send_chunked(
            f"⚠️ <b>TOP RISKS / AVOID LIST</b>\n\n{format_risks(risks)}",
            command=command,
            cycle_id=cycle_id,
        )


def push_action(*, command='action', cycle_id=''):
    intel = normalize_intel(load_intel())
    if intel:
        action = _text(intel.get('action_plan'), 'Maintain capital preservation — await tactical confirmation.')
        send_chunked(
            f"{_snapshot_prefix()}🛡️ <b>ACTION</b>\n\n{action[:2400]}",
            command=command,
            cycle_id=cycle_id,
        )


def push_calibration(*, command='calibration', cycle_id=''):
    intel = normalize_intel(load_intel())
    if intel:
        from backend.lifecycle.unified_metrics import format_calibration_telegram
        cal_text = _professionalize_calibration_text(intel.get('self_calibration'))
        send_chunked(
            f"🎯 <b>CALIBRATION</b>\n"
            f"<i>AI learning state only · resolved metrics via /outcomes</i>\n\n"
            f"{cal_text}\n\n━━━━━━━━━━━━━━━━━━━━\n\n{format_calibration_telegram()}",
            command=command,
            cycle_id=cycle_id,
        )


def push_sectors(*, command='sectors', cycle_id=''):
    intel = normalize_intel(load_intel())
    if intel:
        sectors = _dict(intel.get('sector_rotation'))
        bullish = _join_list(sectors.get('bullish'))
        bearish = _join_list(sectors.get('bearish'))
        send_chunked(
            f"{_snapshot_prefix()}🔄 <b>SECTOR ROTATION</b>\n"
            f"<i>Strength: {sectors.get('rotation_strength', '—')}</i>\n\n"
            f"🟢 <b>Bullish:</b> {bullish}\n🔴 <b>Bearish:</b> {bearish}",
            command=command,
            cycle_id=cycle_id,
        )


def push_global(*, command='global', cycle_id=''):
    """Overnight global impact — mood + indices from latest intel/global feed."""
    raw = load_intel()
    intel = normalize_intel(raw)
    if not intel:
        send_message(
            "❌ No intelligence yet. Run /refresh or wait for US Pulse cycle.",
            command=command,
            cycle_id=cycle_id,
        )
        return
    mood = _dict(intel.get('market_mood'))
    stale = stale_warning(raw)
    global_path = DATA_DIR / 'global_markets.json'
    indices_text = ''
    if global_path.exists():
        try:
            gm = json.loads(global_path.read_text(encoding='utf-8'))
            indices = gm.get('indices') or gm.get('markets') or []
            if isinstance(indices, list) and indices:
                lines = []
                for row in indices[:6]:
                    if isinstance(row, dict):
                        name = _text(row.get('name') or row.get('symbol'), '?')
                        ch = row.get('change_percent') or row.get('change_pct') or 0
                        lines.append(f"• {name}: {ch:+.2f}%" if isinstance(ch, (int, float)) else f"• {name}")
                if lines:
                    indices_text = "\n".join(lines)
        except Exception:
            pass
    body = (
        f"{stale}🌍 <b>OVERNIGHT GLOBAL IMPACT</b>\n\n"
        f"<b>Global mood:</b> {_text(mood.get('global_mood'), 'Unknown')}\n"
        f"<b>India outlook:</b> {_text(mood.get('india_outlook'), 'Unknown')}\n"
    )
    if indices_text:
        body += f"\n<b>Key indices:</b>\n{indices_text}\n"
    summary = _text(intel.get('executive_summary'), '')[:600]
    if summary and summary != 'N/A':
        body += f"\n<i>{summary}</i>"
    send_chunked(body, command=command, cycle_id=cycle_id)


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
        'world': push_global,
        'overnight': push_global,
    }

    func = dispatch.get(mode)
    if func:
        func()
    else:
        safe_print(f"[ERROR] Unknown mode: {mode}")
        safe_print(f"Valid: {', '.join(dispatch.keys())}")
        sys.exit(1)