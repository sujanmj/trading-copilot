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
    FULL_SNAPSHOT_SEQUENCE,
    STAGE_MARKER,
    run_action_plan_only,
    run_aihub_brain_full_only,
    run_aihub_full_only,
    run_broker_only,
    run_daily_pack_only,
    run_global_only,
    run_market_only,
    format_outcomes_status_text,
    run_memory_only,
    run_news_only,
    run_resolve_outcomes_admin,
    run_qa_status_only,
    run_scan_only,
    run_theme_only,
    run_budget_only,
    run_feed_text_only,
    run_myfeed_only,
)
from backend.telegram.response_format import (
    BLOCKED_TRADE_COMMANDS,
    BLOCKED_TRADE_RESPONSE,
    TRADE_EXECUTION_PERMANENTLY_DISABLED,
    format_aihub_menu,
    format_aihub_payload,
    format_status_text,
    format_why_ticker,
    strip_stage_markers,
)
from backend.utils.config import CONFIG_DIR, DATA_DIR

load_dotenv(CONFIG_DIR / 'keys.env', override=False)

def _refresh_telegram_credentials() -> tuple[str, str]:
    """Reload token/chat from env (subprocess tests set vars after import)."""
    global BOT_TOKEN, CHAT_ID, API_URL
    BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    API_URL = f'https://api.telegram.org/bot{BOT_TOKEN}' if BOT_TOKEN else ''
    return BOT_TOKEN, CHAT_ID


BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
API_URL = f'https://api.telegram.org/bot{BOT_TOKEN}' if BOT_TOKEN else ''

STATE_FILE = DATA_DIR / '_telegram_analysis_bot_state.json'

HELP_TEXT = """<b>🤖 AstraEdge Telegram</b>

<b>Core:</b>
/status — system status
/health — runtime health
/schedule — premarket + brief schedule
/memory — market memory
/broker — broker intelligence
/qa — QA status

<b>Action:</b>
/action plan — final action plan
/bootstrap — rebuild cached reports (background)
/today — today confluence pick
/tomorrow — tomorrow confluence pick
/why &lt;ticker&gt; — reason/risk/confirmation
/premarket — premarket top setups
/premarket full — full premarket brief

<b>Refresh:</b>
/refresh — quick scoped refresh
/refresh quick — quick scoped refresh
/refresh full — full closed-market refresh

<b>AI Hub:</b>
/aihub — tab menu
/aihub full — full AI Hub summary
/aihub brain · govt · scan · market · global · news · tv · calib · journal
/aihub brain full — full brain details

<b>My Feed:</b>
/feed &lt;market news text&gt; — save text to My Feed
/myfeed list — latest saved feed
/myfeed today — today's feed
/myfeed scan — tickers/themes impact
/myfeed clean-old — archive dirty image/OCR rows (admin)

<b>Catalyst Radar:</b>
/catalysts — stock-specific catalyst radar
/catalysts today — today's catalyst priority list
/catalysts explain &lt;ticker&gt; — catalyst reason for ticker

<b>Trade Card:</b>
/tradecard — one-stock paper trade card
/tradecard today — today's trade card
/tradecard explain — full trade card plan notes

<b>Briefs:</b>
/news — news only
/morning — pre-market brief
/close — market close summary

<b>Snapshot:</b>
/full — run all read-only AstraEdge commands one by one

<b>Theme Wishlist:</b>
/theme — overview · list · search · category
/theme &lt;basket&gt; · news · scan · budget · refresh

<b>Budget Impact:</b>
/budget — overview · theme &lt;basket&gt; · analyze &lt;text&gt;

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
    from backend.telegram.telegram_command_normalize import normalize_slash_command

    raw_input = str(text or '').strip()
    if not raw_input:
        return '', ''
    if not raw_input.startswith('/'):
        return '', ''
    raw = normalize_slash_command(raw_input)
    if not raw:
        return '', ''
    lower = raw.lower()
    if lower == 'resolve outcomes':
        return 'resolve', 'outcomes'
    if lower == 'outcomes':
        return 'outcomes', ''
    if lower == 'feed':
        return 'feed', ''
    if lower in ('feed news', 'myfeed add', 'myfeed news'):
        return 'removed_feed_alias', raw
    if lower.startswith('feed news ') or lower.startswith('myfeed add ') or lower.startswith('myfeed news '):
        return 'removed_feed_alias', raw
    if lower.startswith('feed '):
        return 'feed', raw[5:].strip()
    if lower == 'myfeed':
        return 'myfeed', ''
    if lower == 'myfeed list':
        return 'myfeed', 'list'
    if lower == 'myfeed today':
        return 'myfeed', 'today'
    if lower == 'myfeed scan':
        return 'myfeed', 'scan'
    if lower == 'myfeed clean-old' or lower == 'myfeed clean old':
        return 'myfeed', 'clean-old'
    if lower == 'myfeed reprocess':
        return 'myfeed', 'reprocess'
    if lower.startswith('myfeed archive'):
        return 'myfeed', raw[len('myfeed archive'):].strip()
    parts = raw.split(maxsplit=1)
    cmd = parts[0].lower() if parts else ''
    args = parts[1] if len(parts) > 1 else ''
    return cmd, args


def _is_telegram_admin(from_user: str) -> bool:
    """Optional TELEGRAM_ADMIN_USER narrowing; chat is already gated by CHAT_ID."""
    admin_user = os.environ.get('TELEGRAM_ADMIN_USER', '').strip()
    if not admin_user:
        return True
    user = str(from_user or '').strip().lower().lstrip('@')
    return user == admin_user.lower().lstrip('@')


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


def handle_telegram_update(
    message: dict[str, Any],
    from_user: str = 'unknown',
    *,
    dry_run: bool = False,
    chat_id: str | None = None,
) -> list[dict[str, Any]]:
    return handle_incoming_telegram_message(
        message,
        from_user,
        dry_run=dry_run,
        chat_id=chat_id,
    )


def handle_incoming_telegram_message(
    message: dict[str, Any],
    from_user: str = 'unknown',
    *,
    dry_run: bool = False,
    chat_id: str | None = None,
) -> list[dict[str, Any]]:
    from backend.telegram.my_feed_intake import format_feed_text_only_image_reply, message_has_image

    if message_has_image(message):
        return [send_analysis_message(
            format_feed_text_only_image_reply(),
            command='feed',
            dry_run=dry_run,
        )]

    msg_text = str(message.get('text') or '').strip()
    if not msg_text:
        return []

    return handle_message(
        msg_text,
        from_user,
        dry_run=dry_run,
        chat_id=chat_id or str((message.get('chat') or {}).get('id') or 'default'),
    )


def handle_message(
    text: str,
    from_user: str = 'unknown',
    *,
    dry_run: bool = False,
    chat_id: str | None = None,
) -> list[dict[str, Any]]:
    """Process one Telegram message — supports up to 3 slash commands per message."""
    commands = _split_multiline_commands(text)
    if commands is None:
        return handle_analysis_command(text, from_user, dry_run=dry_run, chat_id=chat_id)
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
        results.extend(handle_analysis_command(command, from_user, dry_run=dry_run, chat_id=chat_id))
    return results


def _handle_aihub(args: str) -> str:
    from backend.telegram.telegram_command_normalize import (
        format_unknown_aihub_tab,
        normalize_aihub_tab,
    )

    tab = normalize_aihub_tab(args)
    if not tab:
        return format_aihub_menu()
    if tab == 'brain full':
        result = run_without_ai(run_aihub_brain_full_only, command='aihub_brain_full')
        return result.get('text') or 'AI Hub brain full unavailable.'
    if tab in ('full', 'all'):
        result = run_without_ai(run_aihub_full_only, command='aihub_full')
        return result.get('text') or 'AI Hub full summary unavailable.'
    from backend.analytics.aihub_tab_payloads import TAB_ALIASES, VALID_TABS, build_aihub_tab_payload

    canonical = TAB_ALIASES.get(tab, tab)
    if canonical not in VALID_TABS and tab not in ('scanner', 'mkt', 'stats', 'history', 'rdt'):
        return format_unknown_aihub_tab(tab)
    tab = canonical

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
        answer = str(result.get('text') or '').strip()[:3500]
        return (
            f'<b>🤖 AI answer</b>\n'
            f'<i>Context: {context_note}</i>\n\n{answer}'
        )
    fallback = result.get('text') or result.get('user_message') or 'AI temporarily unavailable.'
    return f'{fallback}\n<i>Context attempted: {context_note}</i>'


def _handle_premarket(full: bool = False) -> str:
    from backend.analytics.premarket_conviction import format_premarket_telegram

    return format_premarket_telegram(full=full)


def _handle_refresh(scope: str) -> str:
    from backend.telegram.lazy_command_runner import _scoped_refresh

    scope_norm = (scope or 'quick').strip().lower()
    if scope_norm in ('', 'refresh'):
        scope_norm = 'quick'
    if scope_norm == 'quick':
        result = _scoped_refresh('runtime')
        news = _scoped_refresh('news')
        result['news'] = news.get('news', news.get('ok'))
        lines = [
            '<b>🔄 Quick refresh started</b>',
            f"Runtime: {result.get('runtime', '—')}",
            f"News: {news.get('news', '—')}",
            '<i>Scoped refresh only — no restart or redeploy.</i>',
        ]
        return '\n'.join(lines)
    if scope_norm == 'full':
        result = _scoped_refresh('closed-market')
        lines = [
            '<b>🔄 Full refresh started</b>',
            f"Status: {'ok' if result.get('ok') else 'partial'}",
            f"Daily pack: {result.get('daily_pack', '—')}",
            '<i>Background refresh — DB and /app/data preserved.</i>',
        ]
        return '\n'.join(lines)
    result = _scoped_refresh(scope_norm)
    return (
        f"<b>🔄 Refresh ({scope_norm})</b>\n"
        f"Status: {'ok' if result.get('ok') else 'partial'}\n"
        f"<i>No restart or redeploy.</i>"
    )


def _handle_health() -> str:
    lines = ['<b>🩺 Health</b>']
    try:
        from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD
        from backend.storage.data_paths import data_preserved, get_data_root
        from backend.utils.telegram_guard import is_telegram_listener_enabled, is_telegram_send_enabled

        root = get_data_root()
        lines.append(f"Data root: <code>{root.as_posix()}</code>")
        lines.append(f"Data preserved: {'yes' if data_preserved() else 'check'}")
        lines.append(
            f"Telegram listener/sends: "
            f"{'on' if is_telegram_listener_enabled() and is_telegram_send_enabled() else 'off'}"
        )
    except Exception as exc:
        lines.append(f'Status: degraded ({str(exc)[:80]})')
    try:
        from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD

        lines.append(f'Telegram build: <code>{ASTRAEDGE_TELEGRAM_BUILD}</code>')
    except Exception:
        lines.append('Telegram build: <code>AstraEdge 50C</code>')
    return '\n'.join(lines)


def _handle_schedule() -> str:
    from backend.telegram.premarket_scheduler import format_schedule_text

    return format_schedule_text()


def _handle_morning() -> str:
    from backend.telegram.telegram_brief_scheduler import build_morning_brief_text

    return build_morning_brief_text()


def _handle_close() -> str:
    from backend.telegram.telegram_brief_scheduler import build_close_brief_text

    return build_close_brief_text()


def _handle_stock_decision_command(mode: str, *, cache_only: bool = False) -> str:
    """Shared /today and /tomorrow handler — same path for direct and /full steps."""
    from backend.analytics.railway_decision_bootstrap import decision_rebuilding_reply
    from backend.analytics.stock_decision_engine import build_stock_decision
    from backend.telegram.response_format import (
        format_stock_decision_payload,
        stock_decision_payload_ready,
    )

    normalized = 'today' if mode == 'today' else 'tomorrow'
    payload = build_stock_decision(mode=normalized)
    if stock_decision_payload_ready(payload):
        return format_stock_decision_payload(payload, normalized)
    if cache_only:
        return decision_rebuilding_reply(normalized)

    from backend.analytics.railway_decision_bootstrap import start_background_bootstrap_reports

    start_background_bootstrap_reports(force=True, railway_only=False)
    return decision_rebuilding_reply(normalized)


def _sanitize_full_snapshot_error(reason: str) -> str:
    text = str(reason or 'unknown error')[:120]
    for token in (
        'TELEGRAM_BOT_TOKEN',
        'TELEGRAM_CHAT_ID',
        'OPENAI',
        'ANTHROPIC',
        'GROQ',
        'anthropic',
        'openai',
        'groq',
        'claude',
        'sonnet',
    ):
        text = text.replace(token, 'redacted')
    return text


def _full_snapshot_step_prefix(step: int, total: int, command: str) -> str:
    return f'📦 AstraEdge Full\nStep {step:02d}/{total:02d} — {command}'


def _handle_full_snapshot(*, dry_run: bool = False) -> list[dict[str, Any]]:
    """Run read-only snapshot sequence — one prefix + output per command."""
    from backend.analytics.unified_decision_engine import begin_unified_snapshot, end_unified_snapshot

    begin_unified_snapshot()
    try:
        return _handle_full_snapshot_steps(dry_run=dry_run)
    finally:
        end_unified_snapshot()


def _handle_full_snapshot_steps(*, dry_run: bool = False) -> list[dict[str, Any]]:
    """Run read-only snapshot sequence — one prefix + output per command."""
    total = len(FULL_SNAPSHOT_SEQUENCE)
    results: list[dict[str, Any]] = []
    for step, command_text in enumerate(FULL_SNAPSHOT_SEQUENCE, start=1):
        if step == 2:
            try:
                from backend.analytics.unified_decision_engine import full_snapshot_consistency_warning

                warn = full_snapshot_consistency_warning()
                if warn:
                    results.append(send_analysis_message(warn, command='full', dry_run=dry_run))
            except Exception:
                pass
        prefix = _full_snapshot_step_prefix(step, total, command_text)
        results.append(send_analysis_message(prefix, command='full', dry_run=dry_run))
        try:
            step_results = handle_analysis_command(
                command_text,
                from_user='full_snapshot',
                dry_run=dry_run,
                in_full_snapshot=True,
            )
            if step_results:
                results.extend(step_results)
            else:
                results.append(send_analysis_message(
                    f'{prefix}\nSection unavailable: no response',
                    command='full',
                    dry_run=dry_run,
                ))
        except Exception as exc:
            safe_reason = _sanitize_full_snapshot_error(str(exc))
            results.append(send_analysis_message(
                f'{prefix}\nSection unavailable: {safe_reason}',
                command='full',
                dry_run=dry_run,
            ))
    return results


def handle_analysis_command(
    text: str,
    from_user: str = 'unknown',
    *,
    dry_run: bool = False,
    in_full_snapshot: bool = False,
    chat_id: str | None = None,
) -> list[dict[str, Any]]:
    """Process one command; returns list of send results (supports dry_run)."""
    from backend.telegram.telegram_command_normalize import (
        format_unknown_command_response,
        normalize_parsed_command,
        resolve_natural_command,
    )

    natural = resolve_natural_command(text)
    if natural:
        cmd, args = normalize_parsed_command(*natural)
    else:
        cmd, args = normalize_parsed_command(*parse_command(text))
    if not cmd:
        return []

    safe_print(f'[TG_ANALYSIS] @{from_user}: /{cmd} {args[:60]}')

    if cmd in BLOCKED_TRADE_COMMANDS:
        trade_text = BLOCKED_TRADE_RESPONSE
        return [send_analysis_message(trade_text, command=cmd, dry_run=dry_run)]

    if cmd == 'removed_feed_alias':
        from backend.telegram.my_feed_intake import FEED_TEXT_ONLY_USAGE

        response_text = FEED_TEXT_ONLY_USAGE
        return [send_analysis_message(response_text, command='feed', dry_run=dry_run)]

    if cmd == 'full' and not in_full_snapshot:
        return _handle_full_snapshot(dry_run=dry_run)

    response_text = ''
    if cmd in ('start', 'help', 'h', 'commands'):
        response_text = HELP_TEXT
    elif cmd == 'status':
        result = run_without_ai(lambda: {'text': format_status_text()}, command='status')
        response_text = result.get('text') or format_status_text()
    elif cmd == 'memory':
        result = run_without_ai(run_memory_only, command='memory')
        response_text = result.get('text') or 'Memory unavailable.'
    elif cmd == 'outcomes':
        response_text = format_outcomes_status_text()
    elif cmd == 'resolve':
        if (args or '').strip().lower() != 'outcomes':
            response_text = format_unknown_command_response(cmd, args)
        elif not _is_telegram_admin(from_user):
            response_text = 'Unauthorized — outcome resolver is admin-only.'
        else:
            result = run_without_ai(run_resolve_outcomes_admin, command='resolve_outcomes')
            response_text = result.get('text') or 'Outcome resolver failed.'
    elif cmd == 'broker':
        refresh_broker = str(args or '').strip().lower() == 'refresh'
        result = run_without_ai(
            lambda: run_broker_only(refresh=refresh_broker, args=args),
            command='broker',
        )
        response_text = result.get('text') or 'Broker intelligence unavailable.'
    elif cmd == 'aihub':
        response_text = run_without_ai(lambda: {'text': _handle_aihub(args)}, command='aihub').get('text') or _handle_aihub(args)
    elif cmd == 'news':
        refresh_news = not in_full_snapshot
        result = run_without_ai(lambda: run_news_only(refresh=refresh_news), command='news')
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
                    '<b>🤖 AI answer</b>\n'
                    '<i>Context: cached payloads.</i>\n\nSimulated AI response for dry-run.'
                )
            else:
                response_text = _handle_ask(args)
    elif cmd == 'morning':
        response_text = run_without_ai(_handle_morning, command='morning').get('text') or _handle_morning()
    elif cmd == 'close':
        response_text = run_without_ai(_handle_close, command='close').get('text') or _handle_close()
    elif cmd == 'bootstrap':
        from backend.analytics.railway_decision_bootstrap import (
            bootstrap_started_reply,
            start_background_bootstrap_reports,
        )

        start_background_bootstrap_reports(force=True, railway_only=False)
        response_text = bootstrap_started_reply()
    elif cmd == 'today':
        response_text = _handle_stock_decision_command('today', cache_only=in_full_snapshot)
    elif cmd == 'tomorrow':
        response_text = _handle_stock_decision_command('tomorrow', cache_only=in_full_snapshot)
    elif cmd == 'why':
        if not args.strip():
            response_text = 'Usage: /why &lt;ticker&gt;\nExample: /why TATASTEEL'
        else:
            response_text = format_why_ticker(args.strip(), mode='today')
    elif cmd == 'action':
        result = run_without_ai(run_action_plan_only, command='action_plan')
        response_text = result.get('text') or 'Action plan unavailable.'
    elif cmd == 'premarket':
        full = (args or '').strip().lower() == 'full'
        response_text = run_without_ai(lambda: {'text': _handle_premarket(full=full)}, command='premarket').get('text') or _handle_premarket(full=full)
    elif cmd == 'refresh':
        response_text = run_without_ai(lambda: {'text': _handle_refresh(args or 'quick')}, command='refresh').get('text') or _handle_refresh(args or 'quick')
    elif cmd == 'health':
        response_text = run_without_ai(lambda: {'text': _handle_health()}, command='health').get('text') or _handle_health()
    elif cmd == 'schedule':
        response_text = run_without_ai(lambda: {'text': _handle_schedule()}, command='schedule').get('text') or _handle_schedule()
    elif cmd == 'theme':
        response_text = run_without_ai(lambda: run_theme_only(args), command='theme').get('text') or run_theme_only(args).get('text') or 'Theme baskets unavailable.'
    elif cmd == 'feed':
        from backend.telegram.my_feed_intake import FEED_TEXT_ONLY_USAGE

        text_blob = str(args or '').strip()
        if not text_blob:
            response_text = FEED_TEXT_ONLY_USAGE
        else:
            result = run_without_ai(lambda: run_feed_text_only(args), command='feed_text')
            response_text = result.get('text') or 'MY_FEED_NEEDS_TEXT'
    elif cmd == 'myfeed':
        from backend.telegram.my_feed_intake import MYFEED_SUBCOMMAND_USAGE

        sub = (args or '').strip().lower()
        if sub == 'reprocess':
            if not _is_telegram_admin(from_user):
                response_text = 'Unauthorized — My Feed reprocess is admin-only.'
            else:
                from backend.my_feed.feed_reprocessor import format_reprocess_reply, reprocess_my_feed_items

                result = run_without_ai(
                    lambda: {'text': format_reprocess_reply(reprocess_my_feed_items(apply=True))},
                    command='myfeed_reprocess',
                )
                response_text = result.get('text') or 'MYFEED_REPROCESS_OK'
        elif sub in ('clean-old', 'clean old'):
            if not _is_telegram_admin(from_user):
                response_text = 'Unauthorized — My Feed clean-old is admin-only.'
            else:
                from backend.my_feed.clean_old import clean_old_my_feed_items, format_clean_old_reply

                result = run_without_ai(
                    lambda: {'text': format_clean_old_reply(clean_old_my_feed_items(apply=True))},
                    command='myfeed_clean_old',
                )
                response_text = result.get('text') or 'MYFEED_CLEAN_OLD_OK'
        elif sub in ('list', 'today', 'scan'):
            result = run_without_ai(lambda: run_myfeed_only(sub), command='myfeed')
            response_text = result.get('text') or 'My Feed unavailable.'
        else:
            response_text = MYFEED_SUBCOMMAND_USAGE
    elif cmd == 'budget':
        response_text = run_without_ai(lambda: run_budget_only(args), command='budget').get('text') or run_budget_only(args).get('text') or 'Budget impact unavailable.'
    elif cmd == 'tradecard':
        from backend.telegram.lazy_command_runner import run_tradecard_only

        result = run_without_ai(
            lambda: run_tradecard_only(args, chat_id=chat_id),
            command='tradecard',
        )
        response_text = result.get('text') or 'Trade card unavailable.'
    elif cmd == 'catalysts':
        from backend.telegram.lazy_command_runner import run_catalysts_only

        result = run_without_ai(lambda: run_catalysts_only(args), command='catalysts')
        response_text = result.get('text') or 'Catalyst radar unavailable.'
    else:
        response_text = format_unknown_command_response(cmd, args)

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
    from backend.config.local_safe_mode import is_railway_telegram_start_dry_run
    from backend.utils.telegram_guard import is_telegram_listener_enabled

    if is_railway_telegram_start_dry_run():
        safe_print('[TG_ANALYSIS] dry-run — listener loop not started')
        return
    _refresh_telegram_credentials()
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
                from_user = str((message.get('from') or {}).get('username') or 'unknown')
                handle_incoming_telegram_message(message, from_user, chat_id=msg_chat_id)
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


_astraedge_telegram_started = False
_astraedge_telegram_lock = threading.Lock()


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


def should_start_astraedge_telegram() -> bool:
    """True when Railway monolith should run the AstraEdge analysis bot."""
    from backend.config.local_safe_mode import is_legacy_telegram_listener_disabled, is_railway_mode

    if not is_railway_mode():
        return False
    if not _env_truthy('TELEGRAM_COMMANDS_ENABLED'):
        return False
    if _env_truthy('DISABLE_TELEGRAM_LISTENER'):
        return False
    if not is_legacy_telegram_listener_disabled():
        return False
    return True


def is_astraedge_telegram_started() -> bool:
    return _astraedge_telegram_started


def ensure_astraedge_telegram_started() -> bool:
    """Start the analysis bot once; safe to call from multiple startup paths."""
    global _astraedge_telegram_started
    if not should_start_astraedge_telegram():
        return False

    from backend.config.local_safe_mode import is_railway_telegram_start_dry_run
    from backend.utils.telegram_guard import is_telegram_listener_enabled

    if is_railway_telegram_start_dry_run():
        with _astraedge_telegram_lock:
            if _astraedge_telegram_started:
                return True
            print('ASTRAEDGE_TELEGRAM_ANALYSIS_BOT_STARTED_DRY_RUN', flush=True)
            _astraedge_telegram_started = True
            return True

    if not is_telegram_listener_enabled():
        return False
    token, chat_id = _refresh_telegram_credentials()
    if not token or not chat_id:
        safe_print('[TG_ANALYSIS] missing credentials — listener not started')
        return False

    with _astraedge_telegram_lock:
        if _astraedge_telegram_started:
            return True
        start_listener_thread()
        try:
            from backend.telegram.premarket_scheduler import start_premarket_scheduler
            start_premarket_scheduler()
        except Exception as exc:
            safe_print(f'[TG_ANALYSIS] premarket scheduler failed: {exc}')
        print('ASTRAEDGE_TELEGRAM_ANALYSIS_BOT_STARTED', flush=True)
        _astraedge_telegram_started = True
        return True
