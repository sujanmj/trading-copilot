"""
Telegram Command Listener v3 - Path H (Railway-Optimized + Brain Commands)
Polls Telegram for incoming messages and executes commands

Commands supported:
  ANALYSIS:
    refresh       → Run full analysis pipeline
    scan          → Quick scanner only
    brief         → Send latest morning brief
    outcomes      → Send daily outcome report
    history       → Refresh GUI history export
  
  BRAIN (NEW v3):
    brain         → Full 6-message brain analysis
    summary       → Executive summary + Govt
    opps          → Top opportunities
    risks         → Avoid list
    action        → Action plan
    calibration   → Self-calibration / memory
    sectors       → Sector rotation
    global        → Overnight global impact
    ask <q>       → Ask AI a question
    elite         → Show ML-Filtered High Conviction setups (NEW)
  
  INFO:
    status        → System health check
    stats         → Quick accuracy stats
  
  CONTROL:
    silence <min> → Mute alerts for X minutes
    unsilence     → Resume alerts
    help          → Show command list

v4 Changes:
  - Added /elite command to integrate XGBoost/Heuristic Meta-Labeling
"""

import os
os.environ['PYTHONIOENCODING'] = 'utf-8'

import sys
import json
import time
import threading
import requests
import subprocess
from datetime import datetime, timedelta
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

from backend.utils.config import CONFIG_DIR, DATA_DIR
from backend.utils.runner import run_script_capture

load_dotenv(CONFIG_DIR / 'keys.env', override=False)

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# State files
STATE_FILE = DATA_DIR / '_telegram_listener_state.json'
SILENCE_FILE = DATA_DIR / '_telegram_silence_until.json'


# ============================================================
# PUBLIC HELPER (importable by alert_engine, master_scheduler)
# ============================================================

def is_silenced():
    """Check if alerts are currently muted. Other modules import this."""
    if not SILENCE_FILE.exists():
        return False
    try:
        with open(SILENCE_FILE, 'r') as f:
            until = datetime.fromisoformat(json.load(f).get('until', ''))
        if datetime.now() < until:
            return True
        SILENCE_FILE.unlink()
        return False
    except Exception:
        return False


# ============================================================
# TELEGRAM IO
# ============================================================

def send_message(
    text,
    parse_mode='HTML',
    *,
    command='',
    cycle_id='',
    message_kind='final',
):
    if not BOT_TOKEN or not CHAT_ID:
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
            response = requests.post(
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
            if response.status_code == 200:
                record_outbound(
                    prep['msg_hash'],
                    command=command,
                    message_kind='loading',
                    message_id=prep['message_id'],
                    text=text,
                )
                return True
            return False

        response = requests.post(
            f"{API_URL}/sendMessage",
            json={
                'chat_id': CHAT_ID,
                'text': text,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True,
            },
            timeout=10,
        )
        if response.status_code == 200:
            message_id = None
            try:
                message_id = response.json().get('result', {}).get('message_id')
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

def get_updates(offset=0):
    """Long-poll Telegram for new messages"""
    try:
        response = requests.get(
            f"{API_URL}/getUpdates",
            params={
                'offset': offset,
                'timeout': 25,
                'allowed_updates': '["message"]',
            },
            timeout=30
        )
        if response.status_code == 200:
            return response.json().get('result', [])
    except requests.Timeout:
        return []
    except Exception as e:
        safe_print(f"[TG] Poll error: {e}")
        return []
    return []


# ============================================================
# STATE MANAGEMENT
# ============================================================

def load_offset():
    if not STATE_FILE.exists():
        return 0
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f).get('offset', 0)
    except Exception:
        return 0

def save_offset(offset):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump({'offset': offset, 'updated': datetime.now().isoformat()}, f)


# ============================================================
# THREADING HELPER
# ============================================================

def run_in_background(target, *args, **kwargs):
    """Spawn a daemon thread so the listener stays responsive."""
    t = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
    t.start()
    return t


# ============================================================
# MODULE EXECUTION
# ============================================================

def run_module(module_name, status_msg=None):
    """Run a backend module in subprocess. Blocks until complete."""
    if status_msg:
        send_message(status_msg)

    try:
        captured = run_script_capture(f'{module_name}.py', timeout=300)
        return captured.get('success', False)
    except FileNotFoundError:
        send_message(f"❌ Module not found: {module_name}")
        return False
    except subprocess.TimeoutExpired:
        send_message(f"⏱️ {module_name} timed out (5 min)")
        return False
    except Exception as e:
        send_message(f"❌ Error running {module_name}: {str(e)[:200]}")
        return False


def run_module_with_arg(module_name, arg, timeout=120):
    """Run module with a CLI argument."""
    try:
        captured = run_script_capture(f'{module_name}.py', timeout=timeout, args=[arg])
        return captured.get('success', False)
    except Exception as e:
        safe_print(f"[ERROR] {module_name} {arg}: {e}")
        return False


# ============================================================
# COMMAND HANDLERS (long-running ones spawn threads)
# ============================================================

REFRESH_TIMEOUT_SEC = int(os.environ.get('TELEGRAM_REFRESH_TIMEOUT', '600'))


def _invalidate_runtime_cache(reason: str = 'telegram_refresh') -> None:
    """Signal GUI/API cache bust — RuntimeManager.invalidateCache on next fetch."""
    flag = DATA_DIR / '_runtime_cache_invalidate.flag'
    try:
        flag.write_text(
            json.dumps({'at': datetime.now().isoformat(), 'reason': reason}),
            encoding='utf-8',
        )
    except Exception:
        pass


def _rebuild_canonical_snapshot() -> bool:
    """align_intelligence + publish_active_snapshot + export refresh."""
    from backend.utils.config import DATA_DIR
    intel_path = DATA_DIR / 'unified_intelligence.json'
    if not intel_path.exists():
        return False
    try:
        with open(intel_path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        from backend.intelligence.canonical_rankings import align_intelligence
        cycle_id = f"refresh_{int(time.time())}"
        align_intelligence(raw if isinstance(raw, dict) else {}, cycle_id=cycle_id)
        from backend.runtime.pipeline_stage_log import pipeline_stage_log
        pipeline_stage_log('snapshot_export', status='ok', detail=cycle_id)
        return True
    except Exception as e:
        safe_print(f"[REFRESH] snapshot rebuild failed: {e}")
        return False


def _do_refresh():
    """Heavy lifting for /refresh — force scanner, invalidate cache, rebuild snapshot."""
    started = time.time()
    deadline = started + REFRESH_TIMEOUT_SEC

    def _timed_out() -> bool:
        return time.time() >= deadline

    try:
        from backend.runtime.pipeline_stage_log import pipeline_stage_log
        pipeline_stage_log('cache', status='start', detail='telegram_refresh')
    except Exception:
        pass

    _invalidate_runtime_cache('telegram_refresh')

    if not _timed_out():
        run_module('stock_scanner', '⚡ Forcing scanner refresh...')
        try:
            from backend.runtime.pipeline_stage_log import pipeline_stage_log
            pipeline_stage_log('scanner', status='ok', detail='manual_refresh')
        except Exception:
            pass

    collectors = [
        ('collector', None),
        ('global_collector', None),
        ('news_aggregator', None),
        ('inshorts_tracker', None),
        ('govt_tracker', None),
        ('reddit_tracker', None),
    ]
    for module, status in collectors:
        if _timed_out():
            break
        run_module(module, status)

    if not _timed_out():
        run_module('meta_labeler', '🤖 Running Meta-Labeling Guards...')
    if not _timed_out():
        run_module('master_analyzer', '🧠 AI analysis (slowest step)...')
        try:
            from backend.runtime.pipeline_stage_log import pipeline_stage_log
            pipeline_stage_log('synthesis', status='ok', detail='master_analyzer')
        except Exception:
            pass

    if not _timed_out():
        _rebuild_canonical_snapshot()

    if not _timed_out():
        try:
            from backend.runtime.snapshot_orchestrator import run_snapshot_cycle
            run_snapshot_cycle(trigger='telegram_refresh')
        except Exception as e:
            safe_print(f"[REFRESH] snapshot orchestrator: {e}")

    for module, status in (
        ('prediction_logger', None),
        ('history_exporter', None),
        ('stats_exporter', None),
    ):
        if _timed_out():
            break
        run_module(module, status)

    if not _timed_out():
        try:
            from backend.runtime.pipeline_stage_log import pipeline_stage_log
            pipeline_stage_log('cache', status='ok', detail='exports')
            from backend.runtime.runtime_state import build_runtime_state
            build_runtime_state(force_refresh=True)
        except Exception:
            pass

    if not _timed_out():
        run_module_with_arg('telegram_brain_pusher', 'full', timeout=min(120, REFRESH_TIMEOUT_SEC))
        try:
            from backend.runtime.pipeline_stage_log import pipeline_stage_log
            pipeline_stage_log('telegram', status='ok', detail='brain_push')
        except Exception:
            pass

    if not _timed_out():
        run_module('alert_engine')

    elapsed = int(time.time() - started)
    if _timed_out():
        send_message(
            f"⏱️ <b>Refresh timed out</b> ({REFRESH_TIMEOUT_SEC // 60} min cap).\n"
            "Partial updates may have landed — check /status."
        )
    else:
        send_message(
            "✅ <b>Refresh complete!</b>\n\n"
            f"Finished in {elapsed}s. Brain pushed above.\n"
            "<i>/elite · /scan · /status</i>"
        )

def cmd_refresh():
    from backend.orchestration.telegram_command_guard import begin_command, duplicate_command_message, finish_command
    skip, reason, key = begin_command('refresh', '', CHAT_ID)
    if skip:
        send_message(duplicate_command_message(reason))
        return
    send_message("🔄 <b>Starting full refresh</b>\nThis takes 3-5 minutes. Brain will be pushed when done.\n<i>(Other commands still work during refresh)</i>")

    def _wrapped():
        try:
            from backend.orchestration.delayed_loading import run_with_delayed_loading
            run_with_delayed_loading(
                send_fn=send_message,
                loading_text='🔄 <b>Refresh in progress</b> — this may take several minutes…',
                command='refresh',
                work_fn=_do_refresh,
            )
        finally:
            finish_command(key)

    run_in_background(_wrapped)

def _do_scan():
    run_module('stock_scanner')

    scanner_file = DATA_DIR / 'scanner_data.json'
    if not scanner_file.exists():
        send_message("❌ No scanner data")
        return

    with open(scanner_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    top = data.get('top_signals', [])
    from backend.intelligence.institutional_language import is_high_conviction_strength
    high_conv = [s for s in top if is_high_conviction_strength(s.get('strength'))]
    strong = [s for s in top if s.get('strength') == 'STRONG'][:5]

    msg = f"📊 <b>Scanner Results</b>\n"
    msg += f"Scanned: {data.get('total_scanned', 0)} stocks\n"
    msg += f"Total signals: {data.get('total_signals', 0)}\n\n"

    if high_conv:
        msg += "💎 <b>High Conviction Signals:</b>\n"
        for s in high_conv[:5]:
            sign = '+' if s.get('change_percent', 0) >= 0 else ''
            msg += f"• {s.get('ticker')} ({s.get('direction')}): {sign}{s.get('change_percent', 0):.2f}%, vol {s.get('volume_ratio', 0):.1f}x\n"
        msg += "\n"

    if strong:
        msg += "🔥 <b>STRONG SIGNALS:</b>\n"
        for s in strong:
            sign = '+' if s.get('change_percent', 0) >= 0 else ''
            msg += f"• {s.get('ticker')} ({s.get('direction')}): {sign}{s.get('change_percent', 0):.2f}%\n"

    send_message(msg)

def cmd_scan():
    send_message("⚡ <b>Quick scan</b> (30 sec)")
    run_in_background(_do_scan)

def cmd_elite():
    """Reads the ML Meta-Labeler output and formats it for Telegram."""
    from backend.orchestration.telegram_command_guard import begin_command, duplicate_command_message, finish_command
    skip, reason, key = begin_command('elite', '', CHAT_ID)
    if skip:
        send_message(duplicate_command_message(reason), command='elite')
        return
    try:
        _cmd_elite_body()
    finally:
        finish_command(key)


def _cmd_elite_body():
    data = {}
    try:
        from backend.runtime.market_snapshot_engine import get_current_market_snapshot
        snap = get_current_market_snapshot()
        data = snap.elite_summary if isinstance(snap.elite_summary, dict) else {}
    except Exception:
        pass
    if not data:
        data_path = DATA_DIR / "high_conviction_alerts.json"
        if not data_path.exists():
            send_message("⚠️ <b>ML ENGINE OFFLINE</b>\nMeta-Labeler data not found. Run /refresh first.")
            return
        try:
            with open(data_path, "r", encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            send_message(f"❌ Error reading elite signals: {str(e)[:200]}")
            return

    try:
        elite_signals = data.get("elite_signals", [])
        engine = data.get("engine_mode", "Initializing...")
        
        if not elite_signals:
            watch_note = ''
            try:
                from backend.orchestration.opportunity_filter import rank_opportunities_tiered
                tiers = rank_opportunities_tiered()
                if tiers.get('watch') or tiers.get('avoid'):
                    syms = [
                        str(o.get('symbol') or '').upper()
                        for o in (tiers.get('watch') or [])[:3]
                        if o.get('symbol')
                    ]
                    watch_note = (
                        "\n\n👀 Scanner momentum detected — ML confirmation pending (>72%)."
                    )
                    if syms:
                        watch_note += f"\nWatch list: {', '.join(syms)} · use /opps"
            except Exception:
                pass
            try:
                from backend.intelligence.institutional_language import EMPTY_ELITE_MESSAGE
                empty_msg = EMPTY_ELITE_MESSAGE
            except Exception:
                empty_msg = (
                    'No high-conviction opportunities detected. '
                    'Capital preservation mode active.'
                )
            msg = (
                "🛡️ <b>ELITE</b>\n\n"
                f"{empty_msg}"
                f"{watch_note}"
            )
            send_message(msg, command='elite')
            return
            
        msg = f"🎯 <b>ELITE SETUPS ({len(elite_signals)})</b> · HIGH conviction\n"
        msg += f"🧠 Engine: <code>{engine}</code>\n\n"
        
        for stock in elite_signals:
            symbol = stock.get("symbol", stock.get("Stock", "UNKNOWN"))
            action = stock.get("action", stock.get("Action", "BUY")).upper()
            prob = stock.get("ml_confidence", "N/A")
            entry = stock.get("entry", "Market")
            
            icon = "🟢" if action == "BUY" else "🔴"
            msg += f"{icon} <b>{symbol}</b> [{action}] · ML {prob}\n"
            msg += f"   Entry: <code>{entry}</code>\n\n"
            
        send_message(msg)
        
    except Exception as e:
        send_message(f"❌ Error reading elite signals: {str(e)[:200]}")


def cmd_brief():
    from backend.orchestration.telegram_command_guard import begin_command, duplicate_command_message, finish_command
    skip, reason, key = begin_command('brief', '', CHAT_ID)
    if skip:
        send_message(duplicate_command_message(reason), command='brief')
        return

    def _do():
        try:
            from backend.orchestration.telegram_outbound_guard import bind_cycle, new_cycle_id
            cycle_id = new_cycle_id('brief')
            bind_cycle('brief', cycle_id)
            send_message(
                '📊 Building market brief...',
                command='brief',
                cycle_id=cycle_id,
                message_kind='loading',
            )
            run_module_with_arg('alert_engine', 'morning', 120)
        finally:
            finish_command(key)

    run_in_background(_do)

def cmd_outcomes():
    """Live outcome summary from SQLite — refreshes stats export snapshot."""

    def _do():
        guard_key = None
        try:
            from backend.orchestration.telegram_command_guard import begin_command, finish_command
            skip, _, guard_key = begin_command('outcomes', '', CHAT_ID)
            if skip:
                return
            from backend.lifecycle.unified_metrics import format_outcomes_telegram
            from backend.storage.stats_exporter import export_stats
            from backend.utils.telegram_bot import send_outcome_report
            from backend.runtime.market_snapshot_engine import get_current_market_snapshot
            output = export_stats()
            snap = get_current_market_snapshot(force_refresh=True)
            metrics = snap.metrics or {}
            if not send_outcome_report(metrics, output.get('top_winners'), output.get('top_losers')):
                send_message(format_outcomes_telegram(metrics))
        except Exception as e:
            send_message(f"❌ Outcome report failed: {str(e)[:200]}")
        finally:
            if guard_key:
                from backend.orchestration.telegram_command_guard import finish_command
                finish_command(guard_key)

    run_in_background(_do)

def cmd_history():
    """Refresh GUI history export on demand."""
    send_message("📜 Refreshing history export...")

    def _do():
        ok = run_module('history_exporter')
        send_message("✅ History refreshed in GUI" if ok else "❌ History export failed")

    run_in_background(_do)

# ============================================================
# BRAIN COMMANDS (NEW v3) - delegate to telegram_brain_pusher.py
# ============================================================

def cmd_brain_pusher(mode, status_msg=None):
    """Run brain pusher in-process with debounce guard (no duplicate status spam)."""

    def _do():
        guard_key = None
        cycle_id = None
        try:
            from backend.orchestration.telegram_command_guard import begin_command, finish_command
            from backend.orchestration.telegram_outbound_guard import bind_cycle, clear_loading, new_cycle_id
            skip, _, guard_key = begin_command(mode, '', CHAT_ID)
            if skip:
                from backend.orchestration.telegram_command_guard import duplicate_command_message
                send_message(duplicate_command_message('in_flight'), command=mode)
                return
            cycle_id = new_cycle_id(mode)
            bind_cycle(mode, cycle_id)
            from backend.orchestration import telegram_brain_pusher as tbp
            dispatch = {
                'full': tbp.push_full_brain,
                'brain': tbp.push_full_brain,
                'all': tbp.push_full_brain,
                'summary': tbp.push_summary,
                'opps': tbp.push_opps,
                'opportunities': tbp.push_opps,
                'risks': tbp.push_risks,
                'action': tbp.push_action,
                'calibration': tbp.push_calibration,
                'cal': tbp.push_calibration,
                'sectors': tbp.push_sectors,
                'global': tbp.push_global,
                'world': tbp.push_global,
                'overnight': tbp.push_global,
            }
            fn = dispatch.get(mode)
            if fn:
                from backend.orchestration.delayed_loading import run_with_delayed_loading

                def _brain_work():
                    if fn:
                        fn(command=mode, cycle_id=cycle_id)

                if status_msg:
                    run_with_delayed_loading(
                        send_fn=send_message,
                        loading_text=status_msg,
                        command=mode,
                        cycle_id=cycle_id or '',
                        work_fn=_brain_work,
                    )
                else:
                    _brain_work()
            else:
                send_message(
                    f"❌ Unknown brain mode: <code>{mode}</code>",
                    command=mode,
                    cycle_id=cycle_id,
                )
        except Exception as e:
            send_message(
                f"❌ Brain push failed: {str(e)[:200]}",
                command=mode,
                cycle_id=cycle_id or '',
            )
        finally:
            clear_loading(mode)
            if guard_key:
                from backend.orchestration.telegram_command_guard import finish_command
                finish_command(guard_key)

    run_in_background(_do)

def cmd_status():
    from backend.orchestration.telegram_command_guard import begin_command, duplicate_command_message, finish_command
    skip, reason, key = begin_command('status', '', CHAT_ID)
    if skip:
        send_message(duplicate_command_message(reason), command='status')
        return
    try:
        _cmd_status_body()
    finally:
        finish_command(key)


def _cmd_status_body():
    """Health-only status from canonical runtime_state."""
    try:
        from backend.runtime.runtime_state import get_runtime_state
        from backend.telegram.formatting.telegram_formatter import format_status, format_for_command
        rs = get_runtime_state(force_refresh=True)
        msg = format_for_command(format_status(rs), 'status')
        send_message(msg, command='status')
        return
    except Exception:
        pass

    msg = f"<b>📡 System Status</b>\n<i>{datetime.now().strftime('%H:%M:%S')}</i>\n\n"
    now = datetime.now()
    quiet_mode = False
    try:
        from backend.utils.market_hours import get_operational_status
        op = get_operational_status(now)
        quiet_mode = bool(op.get('expect_quiet_collectors'))
        lifecycle = op.get('lifecycle_state') or op.get('operational_mode')
        msg += f"<b>{op.get('display_status', 'OPERATIONAL')}</b>\n"
        msg += f"<i>{op.get('display_message', '')}</i>\n"
        msg += f"Lifecycle: <code>{lifecycle}</code>\n\n"
    except Exception:
        op = {}

    try:
        from backend.intelligence.active_snapshot import get_active_snapshot_meta, snapshot_health
        snap = get_active_snapshot_meta()
        health = snapshot_health()
        if snap.get('active_snapshot_id'):
            msg += f"📸 Snapshot: <code>{snap['active_snapshot_id'][-8:]}</code> · health {health.get('score', 0)}\n"
        if health.get('stale'):
            msg += f"⚠️ <i>Snapshot stale ({health.get('age_minutes')}m)</i>\n"
    except Exception:
        pass

    send_message(msg + '\n<i>Runtime state unavailable — partial fallback.</i>', command='status')

def cmd_stats():
    from backend.orchestration.telegram_command_guard import begin_command, duplicate_command_message, finish_command
    skip, reason, key = begin_command('stats', '', CHAT_ID)
    if skip:
        send_message(duplicate_command_message(reason), command='stats')
        return
    try:
        from backend.lifecycle.unified_metrics import format_stats_telegram
        from backend.storage.stats_exporter import export_stats
        from backend.runtime.market_snapshot_engine import get_current_market_snapshot
        export_stats()
        snap = get_current_market_snapshot(force_refresh=True)
        metrics = snap.metrics or {}
        send_message(format_stats_telegram(metrics, session='today'), command='stats')
    except Exception as e:
        send_message(f"❌ Stats failed: {str(e)[:200]}", command='stats')
    finally:
        finish_command(key)

def _do_ask(question, user_id='unknown'):
    """Direct import call to ai_router — no subprocess, no injection risk."""
    try:
        from backend.ai.conversational_throttle import check_telegram_ask
        from backend.ai.ai_router import ask_ai
    except Exception as e:
        send_message(f"❌ Could not load ai_router: {str(e)[:200]}")
        return

    gate = check_telegram_ask(user_id, question)
    if not gate.get('allowed'):
        cached = gate.get('cached_response')
        if cached and cached.get('text'):
            send_message(f"<b>🤖 AI Answer (cached):</b>\n\n{cached['text'][:3500]}")
        elif not gate.get('suppress'):
            send_message(f"⏳ {gate.get('reason', 'Please wait before asking again.')}")
        try:
            from backend.analytics.provider_analytics import record_throttle_block
            record_throttle_block(gate.get('reason') or 'blocked')
        except Exception:
            pass
        return

    if gate.get('cached_response') and gate['cached_response'].get('text'):
        answer = gate['cached_response']['text'].strip()
        send_message(f"<b>🤖 AI Answer (cached):</b>\n\n{answer[:3500]}")
        return

    intel_file = DATA_DIR / 'unified_intelligence.json'
    try:
        from backend.ai.ask_context_builder import build_ask_prompt
        prompt = build_ask_prompt(question)
    except Exception:
        context = ""
        if intel_file.exists():
            try:
                with open(intel_file, 'r', encoding='utf-8') as f:
                    intel = json.load(f)
                context = intel.get('analysis', '')[:3000]
            except Exception:
                pass
        prompt = f"""You are an Indian stock market expert. Answer briefly (4-6 sentences).

Recent intelligence context:
{context}

Question: {question}

Give specific, actionable advice for an Indian retail investor."""

    try:
        result = ask_ai(prompt, use_case='telegram_ask', max_tokens=600, channel='telegram')
        if result.get('success'):
            answer = result.get('text', '').strip() or "No response"
            send_message(f"<b>🤖 AI Answer:</b>\n\n{answer[:3500]}")
        else:
            friendly = result.get('user_message') or ''
            if friendly:
                send_message(friendly)
            else:
                send_message(
                    "⚠ AI enrichment temporarily unavailable.\n"
                    "Core intelligence systems remain operational."
                )
    except Exception as e:
        send_message(f"❌ Error: {str(e)[:200]}")

def cmd_ask(question, from_user='unknown'):
    if not question.strip():
        send_message("❓ Usage: /ask <your question>\nExample: /ask should I buy Reliance?")
        return

    send_message(f"🤔 <b>Thinking about:</b>\n<i>{question[:200]}</i>")
    run_in_background(_do_ask, question, from_user)

def cmd_silence(arg):
    try:
        minutes = int(arg.strip())
        if minutes <= 0 or minutes > 1440:
            send_message("❓ Usage: /silence <1-1440 minutes>")
            return

        until = datetime.now() + timedelta(minutes=minutes)
        SILENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SILENCE_FILE, 'w') as f:
            json.dump({'until': until.isoformat()}, f)

        send_message(f"🔕 Alerts muted until {until.strftime('%H:%M')} ({minutes} min)")
    except ValueError:
        send_message("❓ Usage: /silence <minutes>\nExample: /silence 60")

def cmd_unsilence():
    if SILENCE_FILE.exists():
        SILENCE_FILE.unlink()
    send_message("🔔 Alerts resumed")

def cmd_help():
    msg = """<b>🤖 Trading Copilot Commands</b>

<b>🧠 BRAIN & ML:</b>
/elite - Show ML-Filtered High Conviction setups (NEW)
/brain - Full 6-message brain analysis
/summary - Executive summary + Govt impact
/opps - Top opportunities
/risks - Avoid list / risk warnings
/action - Action plan
/calibration - Self-calibration / memory
/sectors - Sector rotation
/global - Overnight global impact
/ask &lt;question&gt; - Ask AI anything

<b>📊 PIPELINES:</b>
/refresh - Full pipeline (3-5 min, non-blocking)
/scan - Quick scanner only (30s)
/brief - Latest morning brief
/outcomes - Daily outcome report
/history - Refresh GUI history

<b>📈 INFO:</b>
/status - System health check
/stats - Trading accuracy stats

<b>🔧 CONTROL:</b>
/silence &lt;min&gt; - Mute alerts (e.g. /silence 60)
/unsilence - Resume alerts
/help - Show this menu

<i>Examples:
• /elite — see top ML picks
• /ask How is metals sector?
• /brain — full analysis on demand</i>"""
    send_message(msg)

# ============================================================
# COMMAND PARSER
# ============================================================

def parse_command(text):
    text = text.strip()
    if not text:
        return None, None

    if text.startswith('/'):
        text = text[1:]

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower() if parts else ''
    args = parts[1] if len(parts) > 1 else ''

    return cmd, args

def handle_command(text, from_user):
    cmd, args = parse_command(text)

    if not cmd:
        return

    safe_print(f"[CMD] @{from_user}: /{cmd} {args[:50]}")

    # ML Commands
    if cmd in ('elite', 'e'):
        cmd_elite()
    # Brain commands (NEW v3)
    elif cmd in ('brain', 'analysis', 'ai'):
        cmd_brain_pusher('full', '🧠 Building full analysis...')
    elif cmd in ('summary', 'sum', 'exec'):
        cmd_brain_pusher('summary', '📋 Building summary...')
    elif cmd in ('opps', 'opportunities', 'picks'):
        cmd_brain_pusher('opps', '💎 Loading opportunities...')
    elif cmd in ('risks', 'risk', 'avoid', 'warnings'):
        cmd_brain_pusher('risks', '⚠️ Loading risks...')
    elif cmd in ('action', 'plan', 'actionplan'):
        cmd_brain_pusher('action', '🛡️ Loading action plan...')
    elif cmd in ('calibration', 'cal', 'memory'):
        cmd_brain_pusher('calibration', '🎯 Loading calibration...')
    elif cmd in ('sectors', 'sector', 'rotation'):
        cmd_brain_pusher('sectors', '🔄 Loading sectors...')
    elif cmd in ('global', 'world', 'overnight'):
        cmd_brain_pusher('global', '🌍 Loading global impact...')
    # Pipelines
    elif cmd in ('refresh', 'r'):
        cmd_refresh()
    elif cmd in ('scan', 's'):
        cmd_scan()
    elif cmd in ('brief', 'b', 'morning'):
        cmd_brief()
    elif cmd in ('outcomes', 'outcome', 'o'):
        cmd_outcomes()
    elif cmd in ('history', 'export'):
        cmd_history()
    # Info
    elif cmd in ('status', 'health'):
        cmd_status()
    elif cmd in ('stats', 'accuracy'):
        cmd_stats()
    elif cmd in ('ask', 'q', 'question'):
        cmd_ask(args, from_user)
    # Control
    elif cmd in ('silence', 'mute'):
        cmd_silence(args)
    elif cmd in ('unsilence', 'unmute'):
        cmd_unsilence()
    elif cmd in ('help', 'h', 'commands', 'start'):
        cmd_help()
    else:
        send_message(f"❓ Unknown command: <code>{cmd}</code>\nType /help for available commands.")

# ============================================================
# MAIN LOOP
# ============================================================

def listen_forever():
    safe_print("=" * 60)
    safe_print("TELEGRAM LISTENER v4 - ML Elite Integration")
    safe_print(f"Bot: @{os.environ.get('BOT_USERNAME', 'sujan_trading_bot')}")
    safe_print(f"Chat ID: {CHAT_ID}")
    try:
        from backend.ai.provider_manager import log_provider_startup_diagnostics
        log_provider_startup_diagnostics(force=True)
    except Exception as e:
        safe_print(f"[AI PROVIDERS] WARN diagnostics failed: {e}")
    safe_print("=" * 60)

    if not BOT_TOKEN or not CHAT_ID:
        safe_print("[ERROR] Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return

    send_message("""<b>🤖 Command Bot Online!</b>

You can now control Trading Copilot from Telegram.

Type /help to see all commands.

<i>NEW Brain & ML Commands:</i>
• /elite - Show ML-Filtered setups
• /brain - Full analysis (6 messages)
• /opps - Top opportunities
• /risks - Avoid list

<i>Existing:</i>
• /scan - Quick scanner
• /status - Health check
• /ask &lt;question&gt;""")

    offset = load_offset()
    safe_print(f"[INFO] Starting from offset: {offset}")
    safe_print("[INFO] Listening for commands... (Ctrl+C to stop)")

    while True:
        try:
            updates = get_updates(offset)

            for update in updates:
                update_id = update.get('update_id', 0)
                offset = update_id + 1
                save_offset(offset)

                message = update.get('message', {})
                if not message:
                    continue

                msg_chat_id = str(message.get('chat', {}).get('id', ''))
                if msg_chat_id != str(CHAT_ID):
                    safe_print(f"[SECURITY] Ignored message from chat {msg_chat_id}")
                    continue

                text = message.get('text', '').strip()
                from_user = message.get('from', {}).get('username', 'unknown')

                if text:
                    try:
                        handle_command(text, from_user)
                    except Exception as e:
                        safe_print(f"[ERROR] Command failed: {e}")
                        send_message(f"❌ Command error: {str(e)[:200]}")

            if not updates:
                time.sleep(1)

        except KeyboardInterrupt:
            safe_print("\n[STOP] Shutting down listener")
            send_message("🔴 <i>Command bot offline</i>")
            break
        except Exception as e:
            safe_print(f"[ERROR] Main loop: {e}")
            time.sleep(5)

def listen_forever_resilient():
    """Wrapper for Railway: auto-restarts on unexpected exits."""
    while True:
        try:
            listen_forever()
            safe_print("[WARN] Listener exited cleanly. Sleeping 30s before restart.")
            time.sleep(30)
        except Exception as e:
            safe_print(f"[CRITICAL] Listener crashed: {e}. Restarting in 10s.")
            time.sleep(10)

if __name__ == "__main__":
    from backend.utils.bootstrap import setup_project_path

    setup_project_path()
    listen_forever()