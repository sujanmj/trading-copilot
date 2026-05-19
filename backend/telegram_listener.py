"""
Telegram Command Listener v2 - Path H (Railway-Optimized)
Polls Telegram for incoming messages and executes commands

Commands supported:
  refresh       → Run full analysis pipeline (now non-blocking)
  scan          → Quick scanner only
  brief         → Send latest morning brief
  outcomes      → Send daily outcome report
  status        → System health check
  stats         → Quick accuracy stats
  ask <q>       → Ask AI a question (direct import, no subprocess)
  history       → Refresh GUI history export
  help          → Show command list
  silence <min> → Mute alerts for X minutes
  unsilence     → Resume alerts

v2 Changes:
  - Long-running commands run in daemon threads (listener stays responsive)
  - cmd_ask() uses direct import (no subprocess injection risk, 2s faster)
  - Added is_silenced() helper for other modules to import
  - Added /history command for GUI refresh on demand
  - Removed duplicate alert_engine call in /brief
  - Auto-restart wrapper safe for Railway background thread spawning
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


# Load credentials (override=False so Railway env vars win)
env_path = Path(__file__).parent.parent / 'config' / 'keys.env'
load_dotenv(env_path, override=False)

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

BACKEND_DIR = Path(__file__).parent
DATA_DIR = Path(__file__).parent.parent / 'data'

# Make backend importable for direct ai_router calls
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

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
        # Expired — clean up
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
    """Run a Python module in subprocess. Blocks until complete."""
    if status_msg:
        send_message(status_msg)

    script_path = BACKEND_DIR / f"{module_name}.py"
    if not script_path.exists():
        send_message(f"❌ Module not found: {module_name}")
        return False

    child_env = os.environ.copy()
    child_env['PYTHONIOENCODING'] = 'utf-8'
    child_env['PYTHONUTF8'] = '1'

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=300,
            encoding='utf-8',
            errors='replace',
            env=child_env,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        send_message(f"⏱️ {module_name} timed out (5 min)")
        return False
    except Exception as e:
        send_message(f"❌ Error running {module_name}: {str(e)[:200]}")
        return False


def run_module_with_arg(module_name, arg, timeout=60):
    """Run module with a CLI argument."""
    script_path = BACKEND_DIR / f"{module_name}.py"
    if not script_path.exists():
        return False

    child_env = os.environ.copy()
    child_env['PYTHONIOENCODING'] = 'utf-8'
    child_env['PYTHONUTF8'] = '1'

    try:
        subprocess.run(
            [sys.executable, str(script_path), arg],
            capture_output=True, text=True, timeout=timeout,
            encoding='utf-8', errors='replace',
            env=child_env,
        )
        return True
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
        ('master_analyzer', '🧠 AI analysis (slowest step)...'),
        ('prediction_logger', None),
        ('history_exporter', None),
        ('stats_exporter', None),
    ]

    for module, status in modules:
        run_module(module, status)

    run_module('alert_engine')
    send_message("✅ <b>Refresh complete!</b>\n\nUse /brief for analysis or /scan for top signals.")


def cmd_refresh():
    send_message("🔄 <b>Starting full refresh</b>\nThis takes 3-5 minutes. I'll ping you when done.\n<i>(Other commands still work during refresh)</i>")
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


def cmd_brief():
    send_message("📋 Generating morning brief...")
    run_in_background(run_module_with_arg, 'alert_engine', 'morning')


def cmd_outcomes():
    send_message("📊 Generating outcome report...")
    run_in_background(run_module_with_arg, 'alert_engine', 'outcome')


def cmd_history():
    """Refresh GUI history export on demand."""
    send_message("📜 Refreshing history export...")

    def _do():
        ok = run_module('history_exporter')
        send_message("✅ History refreshed in GUI" if ok else "❌ History export failed")

    run_in_background(_do)


def cmd_status():
    files_to_check = [
        ('unified_intelligence.json', 'AI Brain'),
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


def _do_ask(question):
    """Direct import call to ai_router — no subprocess, no injection risk."""
    try:
        from ai_router import ask_ai
    except Exception as e:
        send_message(f"❌ Could not load ai_router: {str(e)[:200]}")
        return

    # Load latest intelligence as context
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
        result = ask_ai(prompt, use_case='ask_basic', max_tokens=600)
        if result.get('success'):
            answer = result.get('text', '').strip() or "No response"
            send_message(f"<b>🤖 AI Answer:</b>\n\n{answer[:3500]}")
        else:
            send_message(f"❌ AI error: {str(result.get('error', 'unknown'))[:200]}")
    except Exception as e:
        send_message(f"❌ Error: {str(e)[:200]}")


def cmd_ask(question):
    if not question.strip():
        send_message("❓ Usage: /ask <your question>\nExample: /ask should I buy Reliance?")
        return

    send_message(f"🤔 <b>Thinking about:</b>\n<i>{question[:200]}</i>")
    run_in_background(_do_ask, question)


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

<b>📊 ANALYSIS:</b>
/refresh - Full analysis (3-5 min, non-blocking)
/scan - Quick scanner only (30s)
/brief - Latest morning brief
/outcomes - Daily outcome report
/history - Refresh GUI history

<b>📈 INFO:</b>
/status - System health check
/stats - Trading accuracy stats
/ask &lt;question&gt; - Ask AI anything

<b>🔧 CONTROL:</b>
/silence &lt;min&gt; - Mute alerts (e.g. /silence 60)
/unsilence - Resume alerts
/help - Show this menu

<i>You can type without the / too. Examples:
• "scan"
• "ask should I buy ITC?"
• "stats"</i>"""
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

    if cmd in ('refresh', 'r'):
        cmd_refresh()
    elif cmd in ('scan', 's'):
        cmd_scan()
    elif cmd in ('brief', 'b', 'morning'):
        cmd_brief()
    elif cmd in ('outcomes', 'outcome', 'o'):
        cmd_outcomes()
    elif cmd in ('history', 'export'):
        cmd_history()
    elif cmd in ('status', 'health'):
        cmd_status()
    elif cmd in ('stats', 'accuracy'):
        cmd_stats()
    elif cmd in ('ask', 'q', 'question'):
        cmd_ask(args)
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
    safe_print("TELEGRAM LISTENER v2 - Path H (Railway-Optimized)")
    safe_print(f"Bot: @{os.environ.get('BOT_USERNAME', 'sujan_trading_bot')}")
    safe_print(f"Chat ID: {CHAT_ID}")
    safe_print("=" * 60)

    if not BOT_TOKEN or not CHAT_ID:
        safe_print("[ERROR] Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return

    send_message("""<b>🤖 Command Bot Online!</b>

You can now control Trading Copilot from Telegram.

Type /help to see all commands.

<i>Quick examples:</i>
• /scan - Quick scanner
• /brief - Latest brief
• /ask should I buy ITC?
• /status - Health check""")

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

                # Security: only accept from your chat ID
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
            # If listen_forever returns (e.g., missing creds), don't infinite loop
            safe_print("[WARN] Listener exited cleanly. Sleeping 30s before restart.")
            time.sleep(30)
        except Exception as e:
            safe_print(f"[CRITICAL] Listener crashed: {e}. Restarting in 10s.")
            time.sleep(10)


if __name__ == "__main__":
    listen_forever()