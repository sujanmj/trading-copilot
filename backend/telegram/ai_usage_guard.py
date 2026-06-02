"""
AI usage guard for Telegram Analysis Bot (Stage 45TG3).

Default commands use cached/deterministic summaries.
LLM only for /ask ai or TELEGRAM_ALLOW_AI_SUMMARY=1.
Prefer Groq/fast first; Claude only if TELEGRAM_ALLOW_CLAUDE=1.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from backend.utils.config import DATA_DIR

AI_USAGE_LOG = DATA_DIR / 'telegram_ai_usage_log.jsonl'


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


def allow_ai_summary() -> bool:
    return _env_truthy('TELEGRAM_ALLOW_AI_SUMMARY')


def allow_claude() -> bool:
    return _env_truthy('TELEGRAM_ALLOW_CLAUDE')


def is_llm_command(command: str, args: str = '') -> bool:
    cmd = str(command or '').strip().lower().lstrip('/')
    arg_text = str(args or '').strip().lower()
    if cmd in ('ask', 'q', 'question'):
        return arg_text.startswith('ai ') or arg_text == 'ai'
    return False


def llm_allowed(command: str, args: str = '') -> bool:
    if is_llm_command(command, args):
        return True
    return allow_ai_summary()


def choose_provider(*, command: str = '', use_case: str = 'telegram_ask') -> str:
    if allow_claude() and use_case in ('final_synthesis', 'postmortem'):
        return 'sonnet'
    if allow_claude() and _env_truthy('TELEGRAM_FORCE_CLAUDE'):
        return 'sonnet'
    return 'groq'


def log_ai_usage(
    *,
    command: str,
    provider: str,
    model: str = '',
    used_llm: bool,
    reason: str = '',
    extra: dict | None = None,
) -> None:
    AI_USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
    row = {
        'at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'command': command,
        'provider': provider,
        'model': model,
        'used_llm': bool(used_llm),
        'reason': reason,
        'allow_claude': allow_claude(),
        'allow_ai_summary': allow_ai_summary(),
    }
    if extra:
        row.update(extra)
    try:
        with AI_USAGE_LOG.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row, default=str) + '\n')
    except OSError:
        pass


def guarded_ask_ai(
    prompt: str,
    *,
    command: str = 'ask',
    question: str = '',
    use_case: str = 'telegram_ask',
    max_tokens: int = 600,
) -> dict[str, Any]:
    if not llm_allowed(command, question):
        log_ai_usage(
            command=command,
            provider='none',
            used_llm=False,
            reason='llm_not_allowed_for_command',
        )
        return {
            'success': False,
            'text': 'LLM is disabled for this command. Use /ask ai <question> for AI answers.',
            'provider': 'none',
            'used_llm': False,
        }

    provider_override = choose_provider(command=command, use_case=use_case)
    if provider_override == 'sonnet' and not allow_claude():
        provider_override = 'groq'

    from backend.ai.ai_router import ask_ai

    result = ask_ai(
        prompt,
        use_case=use_case,
        model_override=provider_override if provider_override != 'groq' else 'groq',
        max_tokens=max_tokens,
        channel='telegram',
    )
    used = bool(result.get('success'))
    provider = str(result.get('provider') or provider_override or 'groq')
    if provider.lower().startswith('anthropic') and not allow_claude():
        log_ai_usage(
            command=command,
            provider='blocked_claude',
            model=str(result.get('model') or ''),
            used_llm=False,
            reason='claude_blocked_by_guard',
        )
        return {
            'success': False,
            'text': 'Claude is disabled for Telegram. Set TELEGRAM_ALLOW_CLAUDE=1 to enable fallback.',
            'provider': 'blocked_claude',
            'used_llm': False,
        }

    log_ai_usage(
        command=command,
        provider=provider,
        model=str(result.get('model') or ''),
        used_llm=used,
        reason='ask_ai',
        extra={'estimated_cost': result.get('estimated_cost', 0)},
    )
    result['used_llm'] = used
    return result


def run_without_ai(
    fn: Callable[[], dict[str, Any]],
    *,
    command: str,
    fallback_text: str = '',
) -> dict[str, Any]:
    """Execute deterministic handler; never invokes LLM."""
    log_ai_usage(
        command=command,
        provider='none',
        used_llm=False,
        reason='deterministic_handler',
    )
    try:
        result = fn()
    except Exception as exc:
        result = {'ok': False, 'text': fallback_text or str(exc)[:200]}
    if isinstance(result, dict):
        result.setdefault('used_llm', False)
    return result if isinstance(result, dict) else {'text': str(result), 'used_llm': False}
