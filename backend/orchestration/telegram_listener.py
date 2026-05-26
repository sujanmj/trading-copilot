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

def send_message(text, parse_mode='HTML'):
    if not BOT_TOKEN or not CHAT_ID:
        return False

    if len(text) > 4000:
        text = text[:3950] + "\n... (truncated)"

    try:
        response = requests.post(
            f"{API_URL}/sendMessage",
            json={
                'chat_id': CHAT_ID,
                'text': text,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True,
            },
            timeout=10
        )
        return response.status_code == 200
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

def _do_refresh():
    """Heavy lifting for /refresh — runs in background thread."""
    modules = [
        ('collector', None),
        ('global_collector', None),
        ('news_aggregator', None),
        ('inshorts_tracker', None),
        ('govt_tracker', None),
        ('reddit_tracker', None),
        ('stock_scanner', None),
        ('meta_labeler', '🤖 Running Meta-Labeling Guards...'),
        ('master_analyzer', '🧠 AI analysis (slowest step)...'),
        ('prediction_logger', None),
        ('history_exporter', None),
        ('stats_exporter', None),
    ]

    for module, status in modules:
        run_module(module, status)

    # Push fresh brain to Telegram
    run_module_with_arg('telegram_brain_pusher', 'full', timeout=120)
    
    run_module('alert_engine')
    send_message("✅ <b>Refresh complete!</b>\n\nFull brain sent above. Use /elite for filtered opportunities or /scan for raw signals.")

def cmd_refresh():
    send_message("🔄 <b>Starting full refresh</b>\nThis takes 3-5 minutes. Brain will be pushed when done.\n<i>(Other commands still work during refresh)</i>")
    run_in_background(_do_refresh)

def _do_scan():
    run_module('stock_scanner')

    scanner_file = DATA_DIR / 'scanner_data.json'
    if not scanner_file.exists():
        send_message("❌ No scanner data")
        return

    with open(scanner_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    top = data.get('top_signals', [])
    ultra = [s for s in top if s.get('strength') == 'ULTRA']
    strong = [s for s in top if s.get('strength') == 'STRONG'][:5]

    msg = f"📊 <b>Scanner Results</b>\n"
    msg += f"Scanned: {data.get('total_scanned', 0)} stocks\n"
    msg += f"Total signals: {data.get('total_signals', 0)}\n\n"

    if ultra:
        msg += "💎 <b>ULTRA SIGNALS:</b>\n"
        for s in ultra[:5]:
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
    data_path = DATA_DIR / "high_conviction_alerts.json"
    
    if not data_path.exists():
        send_message("⚠️ <b>ML ENGINE OFFLINE</b>\nMeta-Labeler data not found. Run /refresh first.")
        return
        
    try:
        with open(data_path, "r", encoding='utf-8') as f:
            data = json.load(f)
            
        elite_signals = data.get("elite_signals", [])
        engine = data.get("engine_mode", "Initializing...")
        
        if not elite_signals:
            msg = "🛡️ <b>META-LABELER GUARDRAILS ACTIVE</b>\n\nNo high-conviction trades passed the >72% probability threshold today. The AI recommends protecting capital. Cash is a position."
            send_message(msg)
            return
            
        msg = f"🎯 <b>ELITE SETUPS ({len(elite_signals)} found)</b>\n"
        msg += f"🧠 <b>Engine:</b> <code>{engine}</code>\n"
        msg += "═" * 24 + "\n\n"
        
        for stock in elite_signals:
            symbol = stock.get("symbol", stock.get("Stock", "UNKNOWN"))
            action = stock.get("action", stock.get("Action", "BUY")).upper()
            prob = stock.get("ml_confidence", "N/A")
            entry = stock.get("entry", "Market")
            
            icon = "🟢 BUY" if action == "BUY" else "🔴 SELL/AVOID"
            msg += f"{icon} | <b>{symbol}</b>\n"
            msg += f"📊 ML Win Probability: <b>{prob}</b>\n"
            msg += f"💰 Target Entry: <code>{entry}</code>\n\n"
            
        send_message(msg)
        
    except Exception as e:
        send_message(f"❌ Error reading elite signals: {str(e)[:200]}")


def cmd_brief():
    send_message("📋 Generating morning brief...")
    run_in_background(run_module_with_arg, 'alert_engine', 'morning', 120)

def cmd_outcomes():
    send_message("📊 Generating outcome report...")
    run_in_background(run_module_with_arg, 'alert_engine', 'outcome', 120)

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
    """Trigger telegram_brain_pusher.py with given mode in background thread."""
    if status_msg:
        send_message(status_msg)
    run_in_background(run_module_with_arg, 'telegram_brain_pusher', mode, 120)

def cmd_status():
    files_to_check = [
        ('unified_intelligence.json', 'AI Brain'),
        ('high_conviction_alerts.json', 'ML Core'),
        ('scanner_data.json', 'Scanner'),
        ('reddit_data.json', 'Reddit'),
        ('govt_intelligence.json', 'Govt'),
        ('news_feed.json', 'News'),
        ('global_markets.json', 'Global'),
        ('latest_market_data.json', 'India'),
        ('stats_data.json', 'Stats'),
        ('history_data.json', 'History'),
    ]

    msg = f"<b>📡 System Status</b>\n<i>{datetime.now().strftime('%H:%M:%S')}</i>\n\n"
    now = datetime.now()

    for filename, label in files_to_check:
        path = DATA_DIR / filename
        if path.exists():
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            age_min = int((now - mtime).total_seconds() / 60)

            if age_min < 60:
                emoji = "✅"
                age_str = f"{age_min}m ago"
            elif age_min < 360:
                emoji = "⚠️"
                age_str = f"{age_min // 60}h ago"
            else:
                emoji = "❌"
                age_str = f"{age_min // 60}h ago"

            msg += f"{emoji} {label}: {age_str}\n"
        else:
            msg += f"❌ {label}: MISSING\n"

    db_file = DATA_DIR / 'trading_history.db'
    if db_file.exists():
        size_kb = db_file.stat().st_size / 1024
        msg += f"\n💾 Database: {size_kb:.1f} KB"

    if is_silenced():
        try:
            with open(SILENCE_FILE, 'r') as f:
                until = datetime.fromisoformat(json.load(f).get('until', ''))
            msg += f"\n🔕 Alerts muted until {until.strftime('%H:%M')}"
        except Exception:
            pass

    send_message(msg)

def cmd_stats():
    stats_file = DATA_DIR / 'stats_data.json'
    if not stats_file.exists():
        send_message("❌ No stats yet")
        return

    with open(stats_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    metrics = data.get('metrics_all_time', {})
    db_stats = data.get('db_stats', {})

    msg = "<b>📊 Trading Copilot Stats</b>\n\n"
    msg += f"<b>Predictions:</b> {db_stats.get('total_predictions', 0)}\n"
    msg += f"<b>Evaluated:</b> {metrics.get('total_evaluated', 0)}\n"

    if metrics.get('total_evaluated', 0) > 0:
        msg += f"<b>Win Rate:</b> {metrics.get('win_rate', 0):.1f}%\n"
        msg += f"  Wins: {metrics.get('wins', 0)}\n"
        msg += f"  Losses: {metrics.get('losses', 0)}\n"
        msg += f"<b>Avg Gain:</b> +{metrics.get('avg_gain_pct', 0):.2f}%\n"
        msg += f"<b>Avg Loss:</b> -{metrics.get('avg_loss_pct', 0):.2f}%\n"
        msg += f"<b>Profit Factor:</b> {metrics.get('profit_factor', 0):.2f}\n"
    else:
        msg += "\n<i>⏳ Outcomes evaluate at 8 AM daily</i>"

    send_message(msg)

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
        cmd_brain_pusher('full', '🧠 Sending full brain analysis...')
    elif cmd in ('summary', 'sum', 'exec'):
        cmd_brain_pusher('summary', '📋 Sending executive summary...')
    elif cmd in ('opps', 'opportunities', 'picks'):
        cmd_brain_pusher('opps', '💎 Sending opportunities...')
    elif cmd in ('risks', 'risk', 'avoid', 'warnings'):
        cmd_brain_pusher('risks', '⚠️ Sending risk warnings...')
    elif cmd in ('action', 'plan', 'actionplan'):
        cmd_brain_pusher('action', '🚀 Sending action plan...')
    elif cmd in ('calibration', 'cal', 'memory'):
        cmd_brain_pusher('calibration', '🎯 Sending self-calibration...')
    elif cmd in ('sectors', 'sector', 'rotation'):
        cmd_brain_pusher('sectors', '🔄 Sending sector rotation...')
    elif cmd in ('global', 'world', 'overnight'):
        cmd_brain_pusher('global', '🌍 Sending global impact...')
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