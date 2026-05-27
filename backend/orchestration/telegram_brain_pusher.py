"""
Telegram Brain Pusher v3 — JSON API Optimized
Reads the structured unified_intelligence.json and pushes the full Brain 
to Telegram in 3 consolidated messages.

Usage:
  python telegram_brain_pusher.py             → Full 3-msg brain
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
import threading
import queue
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

_brain_queue: queue.Queue = queue.Queue()
_brain_worker_lock = threading.Lock()
_brain_worker_started = False
_brain_run_lock = threading.Lock()
_brain_stale_prefix = ''


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
        if message_kind == 'final' and command not in ('', 'status'):
            try:
                from backend.orchestration.alert_deduplication import should_send_telegram_alert
                ok, _reason = should_send_telegram_alert(
                    command or 'brain',
                    text[:200],
                    'NEUTRAL',
                    confidence=0.5,
                )
                if not ok:
                    return False
            except Exception:
                pass
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
            if message_kind == 'final':
                try:
                    from backend.orchestration.alert_deduplication import record_sent
                    record_sent(command or 'brain', text[:200], 'NEUTRAL', confidence=0.5, channel='brain_pusher')
                except Exception:
                    pass
            return True
        return False
    except Exception as e:
        safe_print(f"[TG] Send error: {e}")
        return False

def _snapshot_prefix():
    """Deprecated — use snapshot_stale_notice / session_notice only."""
    try:
        from backend.intelligence.active_snapshot import snapshot_header
        from backend.runtime.market_snapshot_engine import snapshot_stale_notice
        return snapshot_stale_notice() + snapshot_header()
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
    try:
        from backend.telegram.formatting.telegram_formatter import format_for_command
        text = format_for_command(text, command or 'brain')
    except Exception:
        pass
    for chunk in chunk_message(text):
        send_message(chunk, command=command, cycle_id=cycle_id, message_kind=message_kind)
        time.sleep(0.5)

def load_intel():
    """Read-only — canonical intelligence view from market snapshot engine."""
    try:
        from backend.runtime.market_snapshot_engine import get_current_market_snapshot
        snap = get_current_market_snapshot()
        view = snap.intelligence or {}
        if view:
            return view
    except Exception:
        pass
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


def stale_warning(intel=None):
    """Single stale/session notice from committed market snapshot (no duplicate paths)."""
    try:
        from backend.runtime.market_snapshot_engine import snapshot_stale_notice
        notice = snapshot_stale_notice()
        if notice:
            return notice
    except Exception:
        pass
    hours = intel_age_hours(intel) if intel else intel_age_hours(load_intel())
    if hours is not None and hours > 3:
        return f"⚠️ <i>Analysis age {hours:.1f}h — verify before acting</i>\n"
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
        if tier_label and 'ELITE' in str(tier_label).upper():
            try:
                from backend.intelligence.institutional_language import elite_empty_block
                return elite_empty_block()
            except Exception:
                return (
                    '<i>🛡️ No high-conviction opportunities detected. '
                    'Capital preservation mode active.</i>'
                )
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
            "<i>🛡️ Scanner-ranked setups below high-conviction meta-labeler threshold.</i>\n\n"
        )
    elif summary.get('has_elite_verified'):
        header = f"<i>✅ {summary.get('elite_verified_count', 0)} high-conviction verified</i>\n\n"
    res = [header] if header else []
    try:
        from backend.telegram.formatting.telegram_formatter import _single_action_label
        from backend.intelligence.institutional_language import format_signal_status_line, apply_institutional_tone
    except Exception:
        _single_action_label = None  # type: ignore
        format_signal_status_line = None  # type: ignore
        apply_institutional_tone = lambda x: x  # type: ignore

    for i, o in enumerate(opps_list, 1):
        o = _dict(o)
        action = _text(o.get('action'), 'WATCH').upper()
        icon = "🟢" if action == "BUY" else "🟡"
        tier = o.get('display_tier') or ''
        if _single_action_label:
            tier_tag = f" {_single_action_label(o)}"
        else:
            tier_tag = f" [{tier}]" if tier and str(tier).upper() != action else f" [{action}]"
        if format_signal_status_line:
            status_line = format_signal_status_line(o)
        else:
            conf = _text(o.get('display_confidence') or o.get('confidence'), 'MEDIUM').upper()
            status_line = f'Status: Watchlist · Confidence: {conf}'
        note = o.get('confidence_note') or ''
        note_html = f"\n   ⚠️ <i>{apply_institutional_tone(note)}</i>" if note else ""
        ml = o.get('ml_confidence')
        ml_html = f" · ML {ml}" if ml and o.get('elite_verified') else ""
        tier_upper = str(tier).upper()
        is_elite = tier_upper == 'ELITE'
        plan = o.get('elite_plan') or {}
        if is_elite:
            entry = _text(o.get('entry_zone') or plan.get('entry_range'))
            tgt = _text(o.get('target') or plan.get('target_1'))
            tgt2 = plan.get('target_2')
            sl = _text(o.get('stop_loss') or plan.get('stop_loss'))
            rr = plan.get('risk_reward') or o.get('risk_reward')
            rr_html = f" · RR {rr}" if rr else ''
            tgt2_html = f" · T2 {tgt2}" if tgt2 else ''
            inv = plan.get('invalidation') or o.get('invalidation')
            why = plan.get('why_elite') or o.get('why_elite')
            inv_html = f"\n   🛑 <i>{_text(inv)}</i>" if inv and inv != 'N/A' else ''
            why_html = f"\n   💎 <i>{_text(why)}</i>" if why else ''
            levels_html = (
                f"   💰 Entry: {entry} | Tgt: {tgt}{tgt2_html} | SL: {sl}{rr_html}\n"
            )
        else:
            inv_html = ''
            why_html = ''
            watch_note = o.get('watch_note') or note
            levels_html = (
                f"   👀 <i>{_text(watch_note, 'Observation only — no execution targets')}</i>\n"
                if tier_upper in ('WATCH', 'AVOID') else ''
            )
        badge = ''
        try:
            from backend.lifecycle.lifecycle_states import lifecycle_badge
            badge = lifecycle_badge(o.get('lifecycle_state') or o.get('state'))
            if badge:
                badge = f" · {badge}"
        except Exception:
            pass
        res.append(
            f"{i}. {icon} <b>{_text(o.get('symbol'), 'UNKNOWN')}</b>{tier_tag}{badge}\n"
            f"{levels_html}"
            f"   📊 {status_line}{ml_html}{note_html if is_elite else ''}{inv_html}{why_html}\n"
            f"   <i>{apply_institutional_tone(_text(o.get('logic'), 'No rationale provided.'))}</i>"
        )
    return "\n".join(res)


def format_opps_tiered(tiers: dict, *, include_elite: bool = False) -> str:
    """Format ELITE / WATCH / AVOID — compressed institutional tiers."""
    watch = _list((tiers or {}).get('watch'))
    avoid = _list((tiers or {}).get('avoid'))
    elite = _list((tiers or {}).get('elite'))
    compressed = str((tiers or {}).get('watch_compressed') or '').strip()

    if not watch and not avoid and not (include_elite and elite):
        try:
            from backend.orchestration.opportunity_filter import rank_opportunities_tiered
            refill = rank_opportunities_tiered()
            watch = _list(refill.get('watch'))
            avoid = _list(refill.get('avoid'))
            elite = _list(refill.get('elite'))
            compressed = str(refill.get('watch_compressed') or '').strip()
        except Exception:
            pass

    sections = []
    if include_elite:
        block = format_opps(elite, tier_label='🎯 HIGH CONVICTION')
        if block:
            sections.append(block)
    if watch:
        if compressed:
            sections.append(f"👀 <b>WATCH</b>\n<i>{compressed}</i>")
        else:
            block = format_opps(watch, tier_label='👀 WATCH')
            if block:
                sections.append(block)
    if avoid:
        block = format_opps(avoid, tier_label='🔴 AVOID')
        if block:
            sections.append(block)

    if sections:
        return "\n\n".join(sections)
    try:
        from backend.intelligence.institutional_language import elite_empty_block
        return elite_empty_block()
    except Exception:
        return (
            '<i>🛡️ No high-conviction opportunities detected. '
            'Capital preservation mode active.</i>'
        )


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


def build_compressed_summary(intel, *, include_stale: bool = True):
    """Max 5 short sections — readable in under 5 seconds."""
    intel = normalize_intel(intel)
    try:
        from backend.intelligence.institutional_language import (
            apply_institutional_tone,
            format_compressed_leaders,
            format_compressed_risks,
            format_executive_summary,
            institutional_regime_label,
        )
    except Exception:
        apply_institutional_tone = lambda x: x  # type: ignore
        format_compressed_leaders = None  # type: ignore
        format_compressed_risks = None  # type: ignore
        institutional_regime_label = lambda x: x  # type: ignore
        format_executive_summary = None  # type: ignore

    stale = stale_warning(intel) if include_stale else (_brain_stale_prefix or '')
    try:
        from backend.runtime.runtime_state import get_runtime_state
        after_hours = bool((get_runtime_state().get('session') or {}).get('after_hours_mode'))
    except Exception:
        after_hours = False

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

    if format_compressed_leaders:
        leaders = format_compressed_leaders(sectors)
    else:
        leaders = _join_list(sectors.get('bullish'), 'Not identified')
        if len(leaders) > 48:
            leaders = leaders[:45] + '...'

    if format_compressed_risks:
        risks_line = format_compressed_risks(risks)
    else:
        risk_bits = []
        for r in risks[:3]:
            r = _dict(r)
            sym = _text(r.get('symbol'), '')
            logic = _text(r.get('logic'), '')
            bit = sym if sym and sym != 'UNKNOWN' else logic[:40]
            if bit:
                risk_bits.append(bit)
        risks_line = ', '.join(risk_bits) if risk_bits else 'Macro headline risk — monitor liquidity'

    bias = apply_institutional_tone(_text(mood.get('india_outlook') or mood.get('global_mood'), 'Selective'))
    regime = institutional_regime_label(regime)
    conf_raw = mood.get('confidence_level') or mood.get('confidence_score')
    try:
        from backend.metrics.format_helpers import safe_confidence
        conf_line = safe_confidence(conf_raw)
    except Exception:
        conf_line = _text(conf_raw, 'N/A')

    body = format_executive_summary(
        regime=regime,
        leaders=leaders,
        risks=risks_line,
        bias=bias,
        confidence=conf_line,
        after_hours=after_hours,
    ) if format_executive_summary else (
        f"Regime: {regime}\nLeadership: {leaders}\nRisks: {risks_line}\nBias: {bias}\nConfidence: {conf_line}"
    )
    return f"{stale}📋 <b>EXECUTIVE SUMMARY</b>\n{apply_institutional_tone(body)}"


def format_risks(risks_list):
    try:
        from backend.telegram.formatting.telegram_formatter import format_risks as _fmt
        return _fmt(_list(risks_list), max_lines_per_ticker=2)
    except Exception:
        pass
    risks_list = _list(risks_list)
    if not risks_list:
        return "<i>No risks found in analysis.</i>"
    res = []
    for i, r in enumerate(risks_list, 1):
        r = _dict(r)
        logic = _text(r.get('logic'), 'No risk rationale provided.')
        logic_lines = [x.strip() for x in logic.splitlines() if x.strip()][:2]
        logic_block = '\n   '.join(f'<i>{ln[:160]}</i>' for ln in logic_lines)
        res.append(
            f"{i}. 🔴 <b>{_text(r.get('symbol'), 'UNKNOWN')}</b>\n"
            f"   {logic_block}"
        )
    return "\n\n".join(res)

# ============================================================
# MESSAGE BUILDERS
# ============================================================

def build_msg1_header(intel, *, include_prefix: bool = True):
    intel = normalize_intel(intel)
    prefix = ''
    if include_prefix:
        prefix = _brain_stale_prefix or stale_warning(intel)
    ts_str = _text(intel.get('generation_time'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    mood = _dict(intel.get('market_mood'))
    confidence = _text(mood.get('confidence_level'), 'N/A')
    sources_used = intel.get('sources_used')
    sources_total = intel.get('sources_total')
    try:
        from backend.runtime.runtime_state import get_runtime_state
        from backend.runtime.feed_registry import count_fresh_sources, format_sources_display, feed_count_total
        rs = get_runtime_state()
        loaded, total = count_fresh_sources(rs.get('source_freshness'))
        if loaded == 0 and sources_used is not None:
            loaded = min(int(sources_used), sources_total or feed_count_total())
            total = int(sources_total or feed_count_total())
        sources_line = format_sources_display(loaded, total=total)
    except Exception:
        from backend.runtime.feed_registry import format_sources_display, feed_count_total
        sources_line = format_sources_display(
            sources_used,
            total=sources_total if sources_total is not None else feed_count_total(),
        )

    return f"""{prefix}🧠 <b>UNIFIED MARKET INTELLIGENCE</b>
📅 <i>{ts_str}</i> · Confidence <b>{confidence}</b> · Sources <b>{sources_line}</b>"""


def build_msg2_summary_govt(intel):
    return build_compressed_summary(intel, include_stale=False)


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

    return f"🎯 <b>SELF-CALIBRATION</b>\n\n{cal}\n\n💎 <b>TOP OPPORTUNITIES</b>\n\n{opps_text}"


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
    action = ''
    try:
        from backend.runtime.market_snapshot_engine import get_current_market_snapshot
        snap = get_current_market_snapshot()
        action = _text(snap.action_plan or intel.get('action_plan'), 'No action plan provided.')
    except Exception:
        action = _text(intel.get('action_plan'), 'No action plan provided.')

    parts = [
        "🔄 <b>SECTOR ROTATION</b>",
        f"🟢 <b>Bullish:</b> {bullish}",
        f"🔴 <b>Bearish:</b> {bearish}",
        "━━━━━━━━━━━━━━━━━━━━",
        "🚀 <b>ACTION PLAN</b>",
        action,
        "━━━━━━━━━━━━━━━━━━━━",
        "📌 <b>QUICK COMMANDS</b>\n\n/brain — Full brain\n/elite — High-conviction setups\n/opps — Opportunities\n/risks — Avoid list\n/action — Action plan\n/sectors — Sector rotation\n\n<i>Brain auto-pushes after each strategic run.</i>",
    ]
    return "\n\n".join(parts)


def probe_intel_file_stale(max_age_hours=2):
    """Return (is_stale, age_hours) without sending Telegram notices."""
    if not INTEL_FILE.exists():
        try:
            from backend.utils.market_hours import get_operational_status
            if get_operational_status().get('expect_quiet_collectors'):
                return False, None
        except Exception:
            pass
        return True, None

    file_age_hours = (time.time() - INTEL_FILE.stat().st_mtime) / 3600
    try:
        from backend.utils.market_hours import get_operational_status, get_watchdog_config
        op = get_operational_status()
        if op.get('expect_quiet_collectors'):
            return False, file_age_hours
        wd = get_watchdog_config()
        max_age_hours = max(max_age_hours, float(wd.get('stale_threshold_seconds') or 7200) / 3600.0)
        if not op.get('market_hours'):
            return False, file_age_hours
    except Exception:
        pass

    if file_age_hours > max_age_hours:
        return True, file_age_hours
    return False, file_age_hours


def check_intel_file_stale(max_age_hours=2, *, notify: bool = True):
    """Return (is_stale, age_hours). Optionally notify user (legacy callers)."""
    is_stale, age = probe_intel_file_stale(max_age_hours=max_age_hours)
    if not notify or not is_stale:
        return is_stale, age
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
    if age is not None:
        safe_print(f"[WARN] Intelligence is {age:.1f}h old - sending stale warning")
        send_message(
            f"⚠️ Market intelligence is stale ({age:.1f}h old). "
            "Expected cycle missed during market session — run /refresh or check Railway logs."
        )
    return True, age


def _brain_worker_loop():
    while True:
        job = _brain_queue.get()
        if job is None:
            break
        try:
            job()
        except Exception as e:
            safe_print(f"[BRAIN] queued job failed: {e}")
        finally:
            _brain_queue.task_done()


def _ensure_brain_worker():
    global _brain_worker_started
    with _brain_worker_lock:
        if _brain_worker_started:
            return
        t = threading.Thread(target=_brain_worker_loop, name='telegram-brain-queue', daemon=True)
        t.start()
        _brain_worker_started = True


def _enqueue_brain_push(work_fn):
    _ensure_brain_worker()
    _brain_queue.put(work_fn)


def render_brain_messages(intel: dict, *, snap=None) -> list:
    """Single render pass — 3 consolidated brain messages for Telegram queue."""
    from backend.lifecycle.unified_metrics import format_calibration_telegram
    from backend.intelligence.institutional_language import apply_institutional_tone, institutional_regime_label
    from backend.telegram.formatting.telegram_formatter import format_action_plan, format_sectors

    intel = normalize_intel(intel) or {}
    prefix = _brain_stale_prefix or stale_warning(intel)
    mood = _dict(intel.get('market_mood'))
    sectors = _dict(intel.get('sector_rotation'))

    regime = 'VOLATILE'
    try:
        from backend.utils.config import ANALYSIS_STATE_FILE
        if ANALYSIS_STATE_FILE.exists():
            state = json.loads(ANALYSIS_STATE_FILE.read_text(encoding='utf-8'))
            regime = institutional_regime_label(str(state.get('last_regime') or 'volatile'))
    except Exception:
        regime = institutional_regime_label('volatile')

    macro_line = apply_institutional_tone(
        _text(mood.get('global_mood') or mood.get('overnight_narrative'), 'Macro context pending')
    )

    # Message 1: executive summary + market mood + regime + macro overview
    summary_body = build_compressed_summary(intel, include_stale=False)
    sentiment_block = (
        "<b>MARKET MOOD</b>\n"
        f"Global: {apply_institutional_tone(_text(mood.get('global_mood'), 'Unknown'))}\n"
        f"India: {apply_institutional_tone(_text(mood.get('india_outlook'), 'Unknown'))}\n"
        f"Retail: {apply_institutional_tone(_text(mood.get('retail_mood'), 'Unknown'))}\n"
        f"Regime: {regime}\n"
        f"Macro: {macro_line[:180]}"
    )
    msg1 = (
        f"{prefix}{build_msg1_header(intel, include_prefix=False)}\n"
        f"{summary_body}\n"
        f"{sentiment_block}"
    )

    # Message 2: opportunities + risks + sector rotation
    opps = get_opportunities(intel)
    opps_text = format_opps(opps[:10]) if opps else ''
    if not opps_text:
        try:
            from backend.orchestration.opportunity_filter import rank_opportunities_tiered
            opps_text = format_opps_tiered(rank_opportunities_tiered(intel), include_elite=True)
        except Exception:
            opps_text = '<i>Monitoring for ranked setups.</i>'
    risks = _list(intel.get('risks_and_avoids'))
    sector_block = format_sectors(sectors).replace('🔄 <b>SECTOR ROTATION</b>\n', '<b>SECTOR ROTATION</b>\n')
    msg2 = (
        f"<b>OPPORTUNITIES</b>\n{opps_text}\n"
        f"<b>TOP RISKS</b>\n{format_risks(risks)}\n"
        f"{sector_block}"
    )

    # Message 3: calibration + lifecycle + positioning guidance
    cal_intel = _professionalize_calibration_text(intel.get('self_calibration'))
    cal_metrics = format_calibration_telegram()
    action = ''
    if snap is not None and getattr(snap, 'action_plan', None):
        action = _text(snap.action_plan, '')
    if not action.strip():
        action = _text(intel.get('action_plan'), '')
    posture = format_action_plan(action)
    msg3 = (
        f"<b>CALIBRATION</b>\n{cal_intel}\n{cal_metrics}\n"
        f"<b>POSITIONING</b>\n{posture}"
    )

    return [
        ('Executive summary', msg1),
        ('Opportunities & risks', msg2),
        ('Calibration & positioning', msg3),
    ]


def _prepare_intel_from_snapshot(snap):
    """Hydrate intel view from canonical MarketSnapshot — single read pass."""
    raw_intel = load_intel()
    intel = normalize_intel(raw_intel) or {}
    if snap is None:
        return intel, raw_intel
    if snap.action_plan:
        intel['action_plan'] = snap.action_plan
    if snap.sector_rotation:
        intel['sector_rotation'] = snap.sector_rotation
    if snap.top_opportunities:
        intel['top_opportunities'] = snap.top_opportunities
        intel['opportunities'] = snap.top_opportunities
    if snap.intelligence:
        merged = normalize_intel(snap.intelligence) or {}
        for key in (
            'executive_summary', 'market_mood', 'risks_and_avoids',
            'self_calibration', 'government_impact',
        ):
            if merged.get(key):
                intel[key] = merged[key]
    return intel, raw_intel


def _push_full_brain_impl(*, command='full', cycle_id=''):
    global _brain_stale_prefix
    cycle_id = _bind_snapshot_cycle(cycle_id)

    from backend.runtime.market_snapshot_engine import get_current_market_snapshot
    snap = get_current_market_snapshot(force_refresh=True)
    intel, raw_intel = _prepare_intel_from_snapshot(snap)

    is_stale, age = probe_intel_file_stale()
    if is_stale and not INTEL_FILE.exists() and not intel:
        safe_print(f"[BRAIN] Blocked push — intel file stale or missing (age={age})")
        check_intel_file_stale(notify=True)
        return False

    debug_intel_fields(raw_intel or intel)
    if not intel:
        send_message("❌ No brain data yet. Run /refresh first.", command=command, cycle_id=cycle_id)
        return False

    try:
        from backend.orchestration.opportunity_filter import rank_opportunities_tiered, DEFAULT_OPPS_LIMIT
        tiers = rank_opportunities_tiered(raw_intel or intel, limit=DEFAULT_OPPS_LIMIT)
        ranked = tiers.get('all') or []
        intel['top_opportunities'] = ranked
        intel['opportunities'] = ranked
    except Exception as e:
        safe_print(f"[WARN] opportunity rank failed: {e}")

    _brain_stale_prefix = stale_warning(raw_intel or intel)

    sections = render_brain_messages(intel, snap=snap)
    safe_print(f"[BRAIN] Pushing {len(sections)}-message brain to Telegram (3-message consolidated)...")
    for label, text in sections:
        try:
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
    _brain_stale_prefix = ''
    return True


def _bind_snapshot_cycle(cycle_id: str = '') -> str:
    try:
        from backend.intelligence.active_snapshot import get_active_snapshot_meta
        meta = get_active_snapshot_meta()
        ver = int(meta.get('snapshot_version') or 0)
        cid = meta.get('cycle_id') or cycle_id or 'snap'
        return f"{cid}:v{ver}"
    except Exception:
        return cycle_id or 'snap'


def push_full_brain(*, command='full', cycle_id='', sync: bool = False):
    """Single orchestrator queue — ordered brain pushes, one stale notice per run."""

    def _job():
        with _brain_run_lock:
            return _push_full_brain_impl(command=command, cycle_id=cycle_id)

    if sync or threading.current_thread().name == 'telegram-brain-queue':
        return _job()
    _enqueue_brain_push(_job)
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
    from backend.telegram.formatting.telegram_formatter import format_opps_tiered as fmt_opps, session_notice
    from backend.runtime.market_snapshot_engine import get_current_market_snapshot
    snap = get_current_market_snapshot()
    raw = snap.intelligence or load_intel()
    debug_intel_fields(raw)
    intel = normalize_intel(raw)
    if not intel:
        send_message('❌ No opportunities data. Run /refresh first.', command=command, cycle_id=cycle_id)
        return
    try:
        tiers = rank_opportunities_tiered(raw, limit=DEFAULT_OPPS_LIMIT)
    except Exception as e:
        safe_print(f"[WARN] opportunity filter failed: {e}")
        tiers = {'watch': get_opportunities(intel)[:DEFAULT_OPPS_LIMIT], 'avoid': [], 'elite': []}
    notice = session_notice(snap.runtime_state)
    body = fmt_opps(tiers, include_elite=True)
    send_chunked(
        f"{notice}💎 <b>SIGNAL OPPORTUNITIES</b>\n\n{body}",
        command=command,
        cycle_id=cycle_id,
    )


def push_risks(*, command='risks', cycle_id=''):
    from backend.telegram.formatting.telegram_formatter import format_risks as fmt_risks
    intel = normalize_intel(load_intel())
    if not intel:
        send_message('❌ No risk data. Run /refresh first.', command=command, cycle_id=cycle_id)
        return
    risks = _list(intel.get('risks_and_avoids'))
    send_chunked(
        f"⚠️ <b>TOP RISKS / AVOID LIST</b>\n\n{fmt_risks(risks)}",
        command=command,
        cycle_id=cycle_id,
    )


def push_action(*, command='action', cycle_id=''):
    from backend.telegram.formatting.telegram_formatter import format_action_plan, snapshot_meta_line
    from backend.runtime.market_snapshot_engine import get_current_market_snapshot
    snap = get_current_market_snapshot()
    action = _text(snap.action_plan, '')
    intel = normalize_intel(load_intel())
    if not action.strip() and intel:
        action = _text(intel.get('action_plan'), '')
    prefix = snapshot_meta_line(snap.runtime_state)
    send_chunked(f"{prefix}{format_action_plan(action)}", command=command, cycle_id=cycle_id)


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
    from backend.telegram.formatting.telegram_formatter import format_sectors, snapshot_meta_line
    from backend.runtime.market_snapshot_engine import get_current_market_snapshot
    snap = get_current_market_snapshot()
    intel = snap.intelligence or normalize_intel(load_intel())
    if not intel and not snap.sector_rotation:
        send_message('❌ No sector data. Run /refresh first.', command=command, cycle_id=cycle_id)
        return
    sectors = _dict(snap.sector_rotation or intel.get('sector_rotation'))
    send_chunked(
        f"{snapshot_meta_line(snap.runtime_state)}{format_sectors(sectors)}",
        command=command,
        cycle_id=cycle_id,
    )


def push_global(*, command='global', cycle_id=''):
    """Overnight global impact — US→Asia→India transmission summary."""
    raw = load_intel()
    intel = normalize_intel(raw)
    stale = stale_warning(raw)
    mood = _dict(intel.get('market_mood')) if intel else {}
    report = {}
    gm = {}
    try:
        from backend.intelligence.global_intelligence_engine import get_overnight_global_impact
        from backend.intelligence.india_next_open_engine import build_india_next_open_report
        report = get_overnight_global_impact().get('india_next_open') or {}
        if not report:
            report = build_india_next_open_report()
    except Exception:
        report = raw.get('overnight_impact') if isinstance(raw, dict) else {}
    global_path = DATA_DIR / 'global_markets.json'
    if global_path.exists():
        try:
            gm = json.loads(global_path.read_text(encoding='utf-8'))
        except Exception:
            gm = {}

    def _move(name):
        flat = gm.get('flat_markets') or {}
        if name in flat:
            return flat[name].get('change_percent') or flat[name].get('change_pct')
        for grp in (gm.get('markets') or {}).values():
            if isinstance(grp, dict) and name in grp:
                return grp[name].get('change_percent') or grp[name].get('change_pct')
        return None

    lines = []
    for label, key in (
        ('Nasdaq', 'NASDAQ'), ('S&P500', 'S&P_500'), ('VIX', 'VIX'),
        ('Gold', 'GOLD'), ('Oil', 'CRUDE_OIL'), ('DXY', 'DXY'),
    ):
        ch = _move(key)
        if ch is not None:
            lines.append(f"• {label}: {float(ch):+.2f}%")

    geo = gm.get('geopolitics') or gm.get('alerts') or []
    geo_line = ''
    if geo:
        geo_line = f"\n⚠️ <i>{_text(geo[0].get('message'), '')[:140]}</i>"

    gs = report.get('global_snapshot') or {}
    india_impact = report.get('india_impact') or {}
    gap = report.get('gap_probability') or {}
    body = (
        f"{stale}{_snapshot_prefix()}🌍 <b>OVERNIGHT GLOBAL IMPACT</b>\n\n"
        f"<b>GLOBAL SNAPSHOT</b>\n"
    )
    for line in (gs.get('lines') or [])[:4]:
        body += f"• {line}\n"
    body += (
        f"\n<b>INDIA IMPACT</b>\n"
        f"Bias: {_text(report.get('india_open_bias') or mood.get('global_mood'), 'Unknown')}\n"
        f"Outlook: {_text(report.get('india_outlook') or mood.get('india_outlook'), 'Unknown')}\n"
    )
    if india_impact.get('bullish_sectors'):
        body += f"Bullish sectors: {_join_list(india_impact.get('bullish_sectors'))}\n"
    if india_impact.get('risk_sectors'):
        body += f"Risk sectors: {_join_list(india_impact.get('risk_sectors'))}\n"
    if report.get('risk_score'):
        body += f"<b>RISK SCORE:</b> {report.get('risk_score')}\n"
    if gap:
        body += (
            f"<b>GAP PROBABILITY:</b> up {gap.get('gap_up_probability', 0):.0%} · "
            f"down {gap.get('gap_down_probability', 0):.0%} "
            f"({gap.get('gap_probability_label', '')})\n"
        )
    if lines:
        body += f"\n<b>Macro:</b>\n" + "\n".join(lines) + "\n"
    narrative = report.get('narrative') or mood.get('overnight_narrative') or ''
    if narrative:
        body += f"\n<i>{_text(narrative)[:500]}</i>"
    if report.get('sectors_at_risk'):
        body += f"\n\n🔴 <b>At risk:</b> {_join_list(report.get('sectors_at_risk'))}"
    if report.get('sectors_supported'):
        body += f"\n🟢 <b>Supported:</b> {_join_list(report.get('sectors_supported'))}"
    body += geo_line
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
        if func is push_full_brain:
            push_full_brain(command=mode, sync=True)
        else:
            func()
    else:
        safe_print(f"[ERROR] Unknown mode: {mode}")
        safe_print(f"Valid: {', '.join(dispatch.keys())}")
        sys.exit(1)