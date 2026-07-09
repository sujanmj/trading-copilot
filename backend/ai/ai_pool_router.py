"""
Cross-provider AI pool router — Groq / Gemini / Claude key pools with ordered failover.

Sits under existing ask_ai routing; outcome explainer and explicit pooled tasks use this layer.
"""

from __future__ import annotations

import re
from typing import Any, Callable

OUTCOME_EXPLAINER_USE_CASE = 'candidate_outcome_explainer'
OUTCOME_EXPLAINER_ROUTE = ('groq', 'gemini', 'claude')

_GEMINI_DEFAULT_USE_CASES = frozenset({
    'summary',
    'compress',
    'gemini',
    'gemini_lite',
    'ask_deep',
})

_GROQ_DEFAULT_USE_CASES = frozenset({
    'ask_basic',
    'ask_conversational',
    'telegram_ask',
    'ops_assistant',
    'lightweight_summary',
})


def resolve_provider_order(use_case: str, *, prefer: str | None = None) -> tuple[str, ...]:
    """Task-specific provider group order (each group tries all keys before next group)."""
    if prefer in OUTCOME_EXPLAINER_ROUTE:
        primary = prefer
    elif use_case in (OUTCOME_EXPLAINER_USE_CASE, 'candidate_outcome_learning'):
        return OUTCOME_EXPLAINER_ROUTE
    elif use_case in _GEMINI_DEFAULT_USE_CASES:
        primary = 'gemini'
    elif use_case in _GROQ_DEFAULT_USE_CASES:
        primary = 'groq'
    else:
        from backend.ai.ai_router import USE_CASE_ROUTING

        routed = USE_CASE_ROUTING.get(use_case, 'gemini')
        primary = 'groq' if routed == 'groq' else ('claude' if routed in ('sonnet', 'final_synthesis') else 'gemini')
    if primary == 'gemini':
        return ('gemini', 'groq', 'claude')
    if primary == 'groq':
        return ('groq', 'gemini', 'claude')
    return ('claude', 'gemini', 'groq')


def _is_weak_explanation(text: str) -> bool:
    body = str(text or '').strip()
    if len(body) < 35:
        return True
    low = body.lower()
    return any(
        token in low
        for token in (
            'cannot determine',
            'not enough information',
            'insufficient data',
            'unable to explain',
            'temporarily unavailable',
        )
    )


def _invoke_provider(
    provider: str,
    prompt: str,
    *,
    use_case: str,
    max_tokens: int,
) -> dict[str, Any]:
    from backend.ai.ai_router import MODELS, call_anthropic, call_gemini, call_groq

    if provider == 'groq':
        raw = call_groq(
            MODELS['groq']['model'],
            prompt,
            max_tokens,
            use_case=use_case,
            allow_gemini_fallback=False,
        )
    elif provider == 'gemini':
        raw = call_gemini('gemini-2.0-flash-lite', prompt, max_tokens, use_case=use_case)
    elif provider == 'claude':
        raw = call_anthropic(MODELS['sonnet']['model'], prompt, max_tokens)
    else:
        return {'success': False, 'error': f'unknown provider {provider}', 'text': ''}
    pool_meta = raw.pop('_pool_meta', {}) if isinstance(raw, dict) else {}
    slot = raw.get('provider_slot') or pool_meta.get('slot_id') or ''
    return {
        'success': bool(raw.get('success')),
        'text': str(raw.get('text') or '').strip(),
        'error': str(raw.get('error') or ''),
        'model': str(raw.get('model') or ''),
        'provider': str(raw.get('provider') or provider),
        'provider_used': provider,
        'key_slot_used': slot,
        'pool_meta': pool_meta,
    }


def execute_pooled_ai(
    prompt: str,
    *,
    use_case: str = OUTCOME_EXPLAINER_USE_CASE,
    max_tokens: int = 180,
    provider_order: tuple[str, ...] | None = None,
    allow_claude: bool = False,
    weak_check: bool = True,
) -> dict[str, Any]:
    """
    Try provider groups in order; each group uses full in-pool key rotation/failover.
    Returns compact metadata for logging — never raw keys.
    """
    order = tuple(provider_order or resolve_provider_order(use_case))
    if not allow_claude and 'claude' in order:
        order = tuple(p for p in order if p != 'claude')
    last_error = ''
    last_result: dict[str, Any] = {}
    for provider in order:
        result = _invoke_provider(provider, prompt, use_case=use_case, max_tokens=max_tokens)
        last_result = result
        if result.get('success') and result.get('text'):
            if weak_check and _is_weak_explanation(result['text']):
                last_error = 'weak_explanation'
                continue
            result['ai_explain_status'] = 'OK'
            result['explanation_confidence'] = 0.65 if provider != 'claude' else 0.72
            return result
        last_error = str(result.get('error') or 'provider_failed')
    status = 'FAILED' if last_result else 'SKIPPED'
    return {
        'success': False,
        'text': '',
        'ai_explain_status': status,
        'error': last_error or 'all_provider_groups_failed',
        'provider_used': last_result.get('provider_used') or '',
        'key_slot_used': last_result.get('key_slot_used') or '',
        'model': last_result.get('model') or '',
        'explanation_confidence': 0.0,
    }


def should_escalate_outcome_explainer_to_claude(
    snapshot: dict[str, Any],
    outcome_record: dict[str, Any],
    *,
    prior_failed_or_weak: bool,
) -> bool:
    """Claude only for complex loser explanations per 52I-A policy."""
    if str(outcome_record.get('outcome') or '') != 'LOSS':
        return False
    score = int(snapshot.get('confidence') or snapshot.get('score') or 0)
    rank = int(snapshot.get('rank') or 99)
    verify = str(snapshot.get('verification_status') or '').upper()
    macro = str(snapshot.get('macro_regime') or '').upper()
    if score >= 75 or rank <= 3:
        return True
    if verify.startswith('VER') and snapshot.get('news_headline'):
        return True
    if prior_failed_or_weak and ('RED' in macro or snapshot.get('sector_theme')):
        return True
    return False
