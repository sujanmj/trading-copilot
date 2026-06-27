"""
AI provider fallback cascade (Stage 46H).

Claude (quota/rate-limit/fail) → Gemini → Groq → deterministic rules.
Logs use internal tier labels only — never exposed in user-facing alerts.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from backend.storage.data_paths import get_data_path


def _log(msg: str) -> None:
    print(msg, flush=True)


def log_provider_fallback(from_tier: str, to_tier: str, reason: str) -> None:
    reason_clean = re.sub(r'\s+', ' ', str(reason or 'unknown'))[:160]
    _log(f'AI_PROVIDER_FALLBACK from={from_tier} to={to_tier} reason={reason_clean}')


def log_provider_fallback_final() -> None:
    _log('AI_PROVIDER_FALLBACK_FINAL deterministic_rules')


def is_failover_error(error: str) -> bool:
    e = (error or '').lower()
    return (
        '429' in e
        or 'quota' in e
        or 'rate limit' in e
        or 'rate_limit' in e
        or 'resource_exhausted' in e
        or 'overloaded' in e
        or 'too many requests' in e
    )


def _load_intel() -> dict:
    path = get_data_path('unified_intelligence.json')
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def synthesize_deterministic_rules(prompt: str, use_case: str = 'final_synthesis') -> Dict[str, Any]:
    """Rules-only synthesis from cached intelligence — no external AI."""
    intel = _load_intel()
    mood = intel.get('market_mood') or {}
    sectors = intel.get('sector_rotation') or {}
    summary = str(intel.get('executive_summary') or intel.get('analysis') or '')[:1200]
    bullish = ', '.join(str(s) for s in (sectors.get('bullish') or [])[:4]) or '—'
    bearish = ', '.join(str(s) for s in (sectors.get('bearish') or [])[:4]) or '—'

    opps = []
    for row in (intel.get('top_opportunities') or [])[:5]:
        if isinstance(row, dict):
            opps.append(
                f"{row.get('symbol', '?')} {row.get('action', 'WATCH')} — "
                f"{str(row.get('logic', ''))[:80]}"
            )

    risks = []
    for row in (intel.get('risks_and_avoids') or [])[:4]:
        if isinstance(row, dict):
            risks.append(f"{row.get('symbol', '?')} — {str(row.get('logic', ''))[:70]}")

    lines = [
        f'[Deterministic synthesis · {use_case}]',
        f"India outlook: {mood.get('india_outlook') or '—'} | Global: {mood.get('global_mood') or '—'}",
        f'Sectors ↑ {bullish} | ↓ {bearish}',
        '',
        'Summary:',
        summary or 'Cached intelligence summary unavailable.',
        '',
        'Watch:',
        *([f'• {o}' for o in opps] or ['• —']),
        '',
        'Avoid:',
        *([f'• {r}' for r in risks] or ['• —']),
    ]
    if prompt and len(prompt) < 400:
        lines.extend(['', f'Context note: {prompt[:300]}'])

    text = '\n'.join(lines)
    return {
        'success': True,
        'text': text,
        'model': 'deterministic_rules',
        'provider': 'rules',
        'estimated_cost': 0.0,
        'fallback_final': True,
    }


def _invoke_claude(model_name: str, prompt: str, max_tokens: int) -> Dict[str, Any]:
    from backend.ai.ai_router import call_anthropic
    return call_anthropic(model_name, prompt, max_tokens)


def _invoke_gemini(model_name: str, prompt: str, max_tokens: int, *, use_case: str) -> Dict[str, Any]:
    from backend.ai.ai_router import call_gemini
    return call_gemini(model_name, prompt, max_tokens, use_case=use_case)


def _invoke_groq(
    model_name: str,
    prompt: str,
    max_tokens: int,
    *,
    use_case: str,
    allow_gemini_fallback: bool = True,
) -> Dict[str, Any]:
    from backend.ai.ai_router import call_groq
    return call_groq(
        model_name,
        prompt,
        max_tokens,
        use_case=use_case,
        allow_gemini_fallback=allow_gemini_fallback,
    )


def call_strategic_with_cascade(
    prompt: str,
    use_case: str = 'final_synthesis',
    max_tokens: int = 4500,
) -> Dict[str, Any]:
    """Claude → Gemini → Groq → deterministic rules."""
    from backend.ai.ai_router import MODELS

    model_name = MODELS['sonnet']['model']
    raw = _invoke_claude(model_name, prompt, max_tokens)
    if raw.get('success'):
        raw['routing_tier'] = 'strategic'
        return raw

    err = str(raw.get('error') or 'claude_failed')
    reason = 'quota_rate_limit' if is_failover_error(err) else 'claude_failed'

    if use_case == 'fixops_report_analyzer':
        # Keep Gemini last for FixOps because quota exhaustion must not block triage.
        log_provider_fallback('claude', 'groq', reason)

        groq_model = MODELS['groq']['model']
        raw = _invoke_groq(groq_model, prompt, max_tokens, use_case=use_case, allow_gemini_fallback=False)
        if raw.get('success'):
            raw['model'] = f"{raw.get('model', 'groq')} (cascade)"
            raw['routing_tier'] = 'groq'
            return raw

        err2 = str(raw.get('error') or 'groq_failed')
        reason2 = 'quota_rate_limit' if is_failover_error(err2) else 'groq_failed'
        log_provider_fallback('groq', 'gemini', reason2)

        raw = _invoke_gemini('gemini-2.0-flash', prompt, max_tokens, use_case=use_case)
        if raw.get('success'):
            raw['model'] = f"{raw.get('model', 'gemini')} (cascade)"
            raw['routing_tier'] = 'gemini'
            return raw

        log_provider_fallback('gemini', 'deterministic_rules', str(raw.get('error') or 'gemini_failed'))
        log_provider_fallback_final()
        det = synthesize_deterministic_rules(prompt, use_case=use_case)
        det['routing_tier'] = 'deterministic'
        det['error'] = None
        return det

    log_provider_fallback('claude', 'gemini', reason)

    raw = _invoke_gemini('gemini-2.0-flash', prompt, max_tokens, use_case=use_case)
    if raw.get('success'):
        raw['model'] = f"{raw.get('model', 'gemini')} (cascade)"
        raw['routing_tier'] = 'gemini'
        return raw

    err2 = str(raw.get('error') or 'gemini_failed')
    reason2 = 'quota_rate_limit' if is_failover_error(err2) else 'gemini_failed'
    log_provider_fallback('gemini', 'groq', reason2)

    groq_model = MODELS['groq']['model']
    raw = _invoke_groq(groq_model, prompt, max_tokens, use_case=use_case)
    if raw.get('success'):
        raw['model'] = f"{raw.get('model', 'groq')} (cascade)"
        raw['routing_tier'] = 'groq'
        return raw

    log_provider_fallback('groq', 'deterministic_rules', str(raw.get('error') or 'groq_failed'))
    log_provider_fallback_final()
    det = synthesize_deterministic_rules(prompt, use_case=use_case)
    det['routing_tier'] = 'deterministic'
    det['error'] = None
    return det
