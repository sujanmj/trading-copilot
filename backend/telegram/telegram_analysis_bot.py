"""
Telegram Analysis Bot — main user-facing interface (Stage 45TG5).

Research-only analysis; trade execution disabled internally.
Marker: TELEGRAM_STAGE_45TG5_OUTPUT_CLEAN_AIHUB_FULL
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

import requests
from dotenv import load_dotenv

from backend.telegram.ai_usage_guard import (
    guarded_ask_ai,
    is_llm_command,
    log_ai_usage,
    run_without_ai,
)
from backend.telegram.lazy_command_runner import (
    STAGE_MARKER,
    run_action_plan_only,
    run_aihub_brain_full_only,
    run_aihub_full_only,
    run_broker_only,
    run_daily_pack_only,
    run_global_only,
    run_market_only,
    run_memory_only,
    run_news_only,
    run_qa_status_only,
    run_scan_only,
)
from backend.telegram.response_format import (
    BLOCKED_TRADE_COMMANDS,
    BLOCKED_TRADE_RESPONSE,
    TRADE_EXECUTION_PERMANENTLY_DISABLED,
    format_aihub_menu,
    format_aihub_payload,
    format_status_text,
    format_stock_decision_telegram,
    format_why_ticker,
    strip_stage_markers,
)
from backend.utils.config import CONFIG_DIR, DATA_DIR

load_dotenv(CONFIG_DIR / 'keys.env', override=False)

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
API_URL = f'https://api.telegram.org/bot{BOT_TOKEN}' if BOT_TOKEN else ''

STATE_FILE = DATA_DIR / '_telegram_analysis_bot_state.json'

HELP_TEXT = """<b>🤖 AstraEdge Telegram</b>

<b>Core:</b>
/status — system status
/memory — market memory
/broker — broker intelligence
/qa — QA status

<b>Action:</b>
/action plan — final action plan
/today — today confluence pick
/tomorrow — tomorrow confluence pick
/why &lt;ticker&gt; — reason/risk/confirmation

<b>AI Hub:</b>
/aihub — tab menu
/aihub full — full AI Hub summary
/aihub brain · govt · scan · market · global · news · tv · reddit · calib · journal
/aihub brain full — full brain details

<b>Briefs:</b>
/news — news only
/morning — pre-market brief
/close — market close summary

<b>AI:</b>
/ask ai &lt;question&gt;"""


def safe_print(text: str) -> None:
    try:
        print(text)
    except (UnicodeEncodeError, ValueError):
        try:
            print(text.encode('ascii', errors='replace').decode('ascii'))
        except Exception:
            pass


def send_analysis_message(
    text: str,
    *,
    parse_mode: str = 'HTML',
    command: str = '',
    dry_run: bool = False,
) -> dict[str, Any]:
    message = strip_stage_markers(text)
    if dry_run:
        return {'ok': True, 'sent': False, 'dry_run': True, 'text': message}

    from backend.config.local_safe_mode import local_telegram_send_dry_run
    from backend.utils.config import DISABLE_TELEGRAM, DISABLE_TELEGRAM_SENDS
    from backend.utils.telegram_guard import (
        is_telegram_send_enabled,
        telegram_send_dry_run,
        telegram_send_skipped,
    )

    if local_telegram_send_dry_run():
        return telegram_send_dry_run('telegram_analysis_bot.send_analysis_message', text=message)

    if not is_telegram_send_enabled() or DISABLE_TELEGRAM or DISABLE_TELEGRAM_SENDS:
        skipped = telegram_send_skipped('telegram_analysis_bot.send_analysis_message')
        skipped['text'] = message
        return skipped

    if not BOT_TOKEN or not CHAT_ID:
        safe_print('[TG_ANALYSIS] Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID')
        return {'ok': False, 'sent': False, 'reason': 'missing_credentials', 'text': message}

    if len(message) > 4000:
        message = message[:3950] + '\n… (truncated)'

    try:
        response = requests.post(
            f"{API_URL}/sendMessage",
            json={
                'chat_id': CHAT_ID,
                'text': message,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True,
            },
            timeout=10,
        )
        ok = response.status_code == 200
        if not ok:
            safe_print(f'[TG_ANALYSIS] send failed cmd={command} status={response.status_code}')
        return {'ok': ok, 'sent': ok, 'text': message}
    except Exception as exc:
        safe_print(f'[TG_ANALYSIS] send error: {exc}')
        return {'ok': False, 'sent': False, 'error': str(exc)[:120], 'text': message}


def parse_command(text: str) -> tuple[str, str]:
    raw = str(text or '').strip()
    if not raw:
        return '', ''
    if raw.startswith('/'):
        raw = raw[1:]
    parts = raw.split(maxsplit=1)
    cmd = parts[0].lower() if parts else ''
    args = parts[1] if len(parts) > 1 else ''
    return cmd, args


def _split_multiline_commands(text: str) -> list[str] | None:
    """Return slash-prefixed lines when every non-empty line is a command."""
    raw = str(text or '').strip()
    if not raw:
        return None
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) <= 1:
        return None
    if not all(ln.startswith('/') for ln in lines):
        return None
    return lines


def handle_message(
    text: str,
    from_user: str = 'unknown',
    *,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Process one Telegram message — supports up to 3 slash commands per message."""
    commands = _split_multiline_commands(text)
    if commands is None:
        return handle_analysis_command(text, from_user, dry_run=dry_run)
    if len(commands) > 3:
        return [
            send_analysis_message(
                'Multiple commands detected. Send one command at a time.',
                command='multiline',
                dry_run=dry_run,
            )
        ]
    results: list[dict[str, Any]] = []
    for command in commands:
        results.extend(handle_analysis_command(command, from_user, dry_run=dry_run))
    return results


def _handle_aihub(args: str) -> str:
    tab = (args or '').strip().lower()
    if not tab:
        return format_aihub_menu()
    if tab == 'brain full':
        result = run_without_ai(run_aihub_brain_full_only, command='aihub_brain_full')
        return result.get('text') or 'AI Hub brain full unavailable.'
    if tab in ('full', 'all'):
        result = run_without_ai(run_aihub_full_only, command='aihub_full')
        return result.get('text') or 'AI Hub full summary unavailable.'
    from backend.analytics.aihub_tab_payloads import VALID_TABS, build_aihub_tab_payload

    if tab not in VALID_TABS and tab not in ('scanner', 'markets', 'mkt', 'stats', 'history', 'rdt'):
        return f'Unknown AI Hub tab: <code>{tab}</code>\n{format_aihub_menu()}'

    if tab in ('scan', 'scanner'):
        result = run_without_ai(run_scan_only, command='aihub_scan')
        payload = result.get('payload') or {}
        return format_aihub_payload('scan', payload)

    if tab == 'news':
        result = run_without_ai(lambda: run_news_only(refresh=False), command='aihub_news')
        payload = result.get('payload') or {}
        return format_aihub_payload('news', payload)

    if tab == 'market':
        result = run_without_ai(lambda: run_market_only(force=False), command='aihub_market')
        payload = result.get('payload') or {}
        return format_aihub_payload('market', payload)

    if tab == 'global':
        result = run_without_ai(run_global_only, command='aihub_global')
        payload = result.get('payload') or {}
        return format_aihub_payload('global', payload)

    payload = build_aihub_tab_payload(tab, force_refresh=False)
    return format_aihub_payload(tab, payload)


def _handle_ask(args: str) -> str:
    question = str(args or '').strip()
    if not question.lower().startswith('ai'):
        return 'Usage: /ask ai &lt;your question&gt;\nExample: /ask ai what changed overnight?'
    question = question[2:].strip() if question.lower().startswith('ai') else question
    if not question:
        return 'Usage: /ask ai &lt;your question&gt;'

    context_note = 'Cached intelligence + report pack context.'
    try:
        from backend.ai.ask_context_builder import build_ask_prompt

        prompt = build_ask_prompt(question)
        context_note = 'ask_context_builder (cached payloads).'
    except Exception:
        intel_path = DATA_DIR / 'unified_intelligence.json'
        context = ''
        if intel_path.is_file():
            try:
                intel = json.loads(intel_path.read_text(encoding='utf-8'))
                context = str(intel.get('analysis') or '')[:2500]
            except (OSError, json.JSONDecodeError):
                pass
        prompt = (
            'You are an Indian stock market analyst. Answer briefly (4-6 sentences).\n\n'
            f'Context:\n{context}\n\nQuestion: {question}'
        )

    result = guarded_ask_ai(
        prompt,
        command='ask',
        question=f'ai {question}',
        use_case='telegram_ask',
    )
    if result.get('success'):
        provider = result.get('provider') or 'groq'
        answer = str(result.get('text') or '').strip()[:3500]
        return (
            f'<b>🤖 AI answer</b> ({provider})\n'
            f'<i>Context: {context_note}</i>\n\n{answer}'
        )
    fallback = result.get('text') or result.get('user_message') or 'AI temporarily unavailable.'
    return f'{fallback}\n<i>Context attempted: {context_note}</i>'


def _handle_morning() -> str:
    from backend.telegram.telegram_brief_scheduler import build_morning_brief_text

    return build_morning_brief_text()


def _handle_close() -> str:
    from backend.telegram.telegram_brief_scheduler import build_close_brief_text

    return build_close_brief_text()


def handle_analysis_command(
    text: str,
    from_user: str = 'unknown',
    *,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Process one command; returns list of send results (supports dry_run)."""
    cmd, args = parse_command(text)
    if not cmd:
        return []

    safe_print(f'[TG_ANALYSIS] @{from_user}: /{cmd} {args[:60]}')

    if cmd in BLOCKED_TRADE_COMMANDS:
        trade_text = BLOCKED_TRADE_RESPONSE
        return [send_analysis_message(trade_text, command=cmd, dry_run=dry_run)]

    response_text = ''
    if cmd in ('start', 'help', 'h', 'commands'):
        response_text = HELP_TEXT
    elif cmd == 'status':
        result = run_without_ai(lambda: {'text': format_status_text()}, command='status')
        response_text = result.get('text') or format_status_text()
    elif cmd == 'memory':
        result = run_without_ai(run_memory_only, command='memory')
        response_text = result.get('text') or 'Memory unavailable.'
    elif cmd == 'broker':
        result = run_without_ai(lambda: run_broker_only(refresh=False), command='broker')
        response_text = result.get('text') or 'Broker intelligence unavailable.'
    elif cmd == 'aihub':
        response_text = run_without_ai(lambda: {'text': _handle_aihub(args)}, command='aihub').get('text') or _handle_aihub(args)
    elif cmd == 'news':
        result = run_without_ai(lambda: run_news_only(refresh=True), command='news')
        response_text = result.get('text') or 'News unavailable.'
    elif cmd == 'qa':
        result = run_without_ai(run_qa_status_only, command='qa')
        response_text = result.get('text') or 'QA status unavailable.'
    elif cmd in ('ask', 'q', 'question'):
        if dry_run and not is_llm_command(cmd, args):
            response_text = 'Use /ask ai <question> for LLM.'
        else:
            if dry_run:
                log_ai_usage(command='ask', provider='dry_run', used_llm=True, reason='dry_run_simulation')
                response_text = (
                    '<b>🤖 AI answer</b> (dry_run/groq)\n'
                    '<i>Context: cached payloads.</i>\n\nSimulated AI response for dry-run.'
                )
            else:
                response_text = _handle_ask(args)
    elif cmd == 'morning':
        response_text = run_without_ai(_handle_morning, command='morning').get('text') or _handle_morning()
    elif cmd == 'close':
        response_text = run_without_ai(_handle_close, command='close').get('text') or _handle_close()
    elif cmd == 'today':
        response_text = format_stock_decision_telegram('today')
    elif cmd == 'tomorrow':
        response_text = format_stock_decision_telegram('tomorrow')
    elif cmd == 'why':
        if not args.strip():
            response_text = 'Usage: /why &lt;ticker&gt;\nExample: /why TATASTEEL'
        else:
            response_text = format_why_ticker(args.strip(), mode='today')
    elif cmd == 'action' and (args or '').strip().lower() == 'plan':
        result = run_without_ai(run_action_plan_only, command='action_plan')
        response_text = result.get('text') or 'Action plan unavailable.'
    else:
        response_text = f'Unknown command: <code>{cmd}</code>\nType /help for allowed commands.'

    if not response_text:
        response_text = 'No response generated.'
    return [send_analysis_message(response_text, command=cmd, dry_run=dry_run)]


def load_offset() -> int:
    if not STATE_FILE.is_file():
        return 0
    try:
        return int(json.loads(STATE_FILE.read_text(encoding='utf-8')).get('offset', 0))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return 0


def save_offset(offset: int) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({'offset': offset, 'updated': datetime.now().isoformat()}, indent=2),
        encoding='utf-8',
    )


def get_updates(offset: int = 0) -> list[dict]:
    from backend.utils.telegram_guard import guard_telegram_poll

    if not guard_telegram_poll('telegram_analysis_bot.get_updates'):
        return []
    if not BOT_TOKEN:
        return []
    try:
        response = requests.get(
            f'{API_URL}/getUpdates',
            params={'offset': offset, 'timeout': 25, 'allowed_updates': '["message"]'},
            timeout=30,
        )
        if response.status_code == 200:
            return response.json().get('result') or []
    except requests.Timeout:
        return []
    except Exception as exc:
        safe_print(f'[TG_ANALYSIS] poll error: {exc}')
    return []


def listen_forever(*, on_command: Callable[[str, str], None] | None = None) -> None:
    from backend.utils.telegram_guard import is_telegram_listener_enabled

    if not is_telegram_listener_enabled():
        safe_print('[TG_ANALYSIS] listener disabled')
        return
    if not BOT_TOKEN or not CHAT_ID:
        safe_print('[TG_ANALYSIS] missing credentials — listener not started')
        return

    safe_print('[TG_ANALYSIS] Telegram Analysis Bot starting')
    safe_print(f'[TG_ANALYSIS] trade_execution_disabled={TRADE_EXECUTION_PERMANENTLY_DISABLED}')
    safe_print(f'[TG_ANALYSIS] stage_marker={STAGE_MARKER}')
    send_analysis_message(
        '<b>Telegram Analysis Bot online</b>\n'
        'Type /help for commands.',
        command='startup',
    )

    offset = load_offset()
    while True:
        try:
            updates = get_updates(offset)
            for update in updates:
                update_id = int(update.get('update_id') or 0)
                offset = update_id + 1
                save_offset(offset)
                message = update.get('message') or {}
                msg_chat_id = str((message.get('chat') or {}).get('id', ''))
                if msg_chat_id != str(CHAT_ID):
                    safe_print(f'[TG_ANALYSIS] ignored chat {msg_chat_id}')
                    continue
                msg_text = str(message.get('text') or '').strip()
                from_user = str((message.get('from') or {}).get('username') or 'unknown')
                if not msg_text:
                    continue
                if on_command:
                    on_command(msg_text, from_user)
                else:
                    handle_message(msg_text, from_user)
            if not updates:
                time.sleep(1)
        except KeyboardInterrupt:
            safe_print('[TG_ANALYSIS] stopped')
            send_analysis_message('🔴 <i>Analysis bot offline</i>', command='shutdown')
            break
        except Exception as exc:
            safe_print(f'[TG_ANALYSIS] loop error: {exc}')
            time.sleep(5)


def start_listener_thread() -> threading.Thread:
    thread = threading.Thread(target=listen_forever, name='telegram_analysis_bot', daemon=True)
    thread.start()
    return thread
