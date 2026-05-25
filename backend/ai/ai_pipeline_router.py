"""
AI pipeline router — cheap tier (Gemini Flash) vs expensive tier (Claude).
Includes prompt-hash caching and budget integration.
"""

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

from backend.utils.config import AI_CACHE_DIR, AI_CACHE_TTL_SECONDS, MAX_CLAUDE_PROMPT_CHARS, ensure_dirs
from backend.storage.json_io import atomic_write_json
from backend.ai.token_optimizer import cap_prompt, estimate_tokens
from backend.ai.ai_budget_manager import is_claude_allowed, is_low_cost_mode, is_budget_exceeded, record_cost

ensure_dirs()

MAX_AI_RETRIES = 1


def _log(tag: str, msg: str):
    print(f"[{tag}] {msg}")


_CACHE_NORM_RE = [
    (re.compile(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?'), ''),
    (re.compile(r'\bage=\d+s\b', re.I), ''),
    (re.compile(r'\bupdated_at[^\n]*', re.I), ''),
    (re.compile(r'\bgenerated_at[^\n]*', re.I), ''),
    (re.compile(r'\btimestamp[^\n]*', re.I), ''),
    (re.compile(r'\bcycle_id[^\n]*', re.I), ''),
]


def normalize_prompt_for_cache(text: str) -> str:
    """Strip volatile metadata so semantically identical prompts share cache keys."""
    if not text:
        return ''
    out = text
    for pattern, repl in _CACHE_NORM_RE:
        out = pattern.sub(repl, out)
    out = re.sub(r'[ \t]+', ' ', out)
    out = re.sub(r'\n{3,}', '\n\n', out)
    return out.strip()


def hash_prompt(prompt: str, use_case: str = '') -> str:
    normalized = normalize_prompt_for_cache(prompt)
    blob = f"{use_case}|{normalized}".encode('utf-8', errors='replace')
    digest = hashlib.sha256(blob).hexdigest()
    _log('CACHE HASH NORMALIZED', f'{use_case} key={digest[:12]} len={len(normalized)}')
    return digest


def _cache_path(key: str) -> Path:
    return AI_CACHE_DIR / f"{key[:32]}.json"


def get_cached(key: str) -> Optional[Dict[str, Any]]:
    path = _cache_path(key)
    if not path.exists():
        _log('SEMANTIC CACHE MISS', key[:12])
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict) or 'result' not in data:
            path.unlink(missing_ok=True)
            _log('SEMANTIC CACHE MISS', 'corrupt entry removed')
            return None
        age = time.time() - float(data.get('ts', 0))
        if age > AI_CACHE_TTL_SECONDS:
            path.unlink(missing_ok=True)
            _log('SEMANTIC CACHE MISS', f'expired ({int(age)}s)')
            return None
        _log('SEMANTIC CACHE HIT', f"{key[:12]} age={int(age)}s")
        result = dict(data.get('result') or {})
        result['_from_cache'] = True
        return result
    except Exception as e:
        _log('SEMANTIC CACHE MISS', f'read error: {e}')
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def set_cached(key: str, result: Dict[str, Any], use_case: str = ''):
    if not result or not result.get('success'):
        return
    payload = {
        'ts': time.time(),
        'use_case': use_case,
        'result': {
            'success': result.get('success'),
            'text': result.get('text', ''),
            'model': result.get('model', ''),
            'provider': result.get('provider', ''),
            'estimated_cost': result.get('estimated_cost', 0),
        },
    }
    atomic_write_json(_cache_path(key), payload)


def call_cheap(prompt: str, use_case: str = 'compress', max_tokens: int = 2000) -> Dict[str, Any]:
    """Gemini Flash — summarization, compression, classification."""
    from backend.ai.ai_router import ask_ai
    from backend.ai.pipeline_observability import record_routing_event

    prompt = cap_prompt(prompt, MAX_CLAUDE_PROMPT_CHARS)
    cache_key = hash_prompt(prompt, use_case)
    cached = get_cached(cache_key)
    if cached:
        record_routing_event({
            'tier': 'cheap',
            'use_case': use_case,
            'event': 'cache_hit',
            'reason': f'prompt hash {cache_key[:12]}',
            'model': cached.get('model', 'gemini'),
        })
        return cached

    record_routing_event({
        'tier': 'cheap',
        'use_case': use_case,
        'event': 'cache_miss',
        'reason': 'no valid cache entry',
        'estimated_input_tokens': estimate_tokens(prompt),
    })

    _log('COMPRESSOR', f"Gemini {use_case} ~{estimate_tokens(prompt)} tok")
    result = None
    for attempt in range(MAX_AI_RETRIES + 1):
        result = ask_ai(prompt, use_case='compress', model_override='gemini', max_tokens=max_tokens)
        if isinstance(result, dict) and result.get('success'):
            break
    if not isinstance(result, dict):
        result = {'success': False, 'text': '', 'error': 'invalid response'}

    cost = float(result.get('estimated_cost') or 0)
    record_cost(cost, result.get('model', 'gemini'), use_case, result.get('provider', 'google'))
    record_routing_event({
        'tier': 'cheap',
        'use_case': use_case,
        'event': 'api_call',
        'model': result.get('model', 'gemini'),
        'provider': result.get('provider', 'google'),
        'success': bool(result.get('success')),
        'estimated_cost': cost,
    })
    if result.get('success'):
        set_cached(cache_key, result, use_case)
    return result


def call_expensive(
    prompt: str,
    use_case: str = 'final_synthesis',
    max_tokens: int = 4500,
    force: bool = False,
) -> Dict[str, Any]:
    """Claude Sonnet for final synthesis — budget-gated with Gemini fallback."""
    from backend.ai.ai_router import ask_ai
    from backend.ai.pipeline_observability import record_routing_event

    prompt = cap_prompt(prompt, MAX_CLAUDE_PROMPT_CHARS)
    cache_key = hash_prompt(prompt, use_case)
    cached = get_cached(cache_key)
    if cached:
        record_routing_event({
            'tier': 'expensive',
            'use_case': use_case,
            'event': 'cache_hit',
            'reason': f'prompt hash {cache_key[:12]}',
            'model': cached.get('model'),
        })
        return cached

    if not is_claude_allowed(force=force):
        reason = 'budget exceeded' if is_budget_exceeded() else 'low_cost_mode active'
        record_routing_event({
            'tier': 'expensive',
            'use_case': use_case,
            'event': 'claude_blocked',
            'reason': reason,
            'fallback': 'gemini_synthesis',
        })
        _log('CLAUDE SKIPPED', 'budget/low-cost — falling back to Gemini synthesis')
        fallback_prompt = (
            "Produce ONLY valid JSON matching the schema in the user message. "
            "Be concise but complete.\n\n" + prompt
        )
        return call_cheap(fallback_prompt, use_case='gemini_synthesis', max_tokens=max_tokens)

    record_routing_event({
        'tier': 'expensive',
        'use_case': use_case,
        'event': 'cache_miss',
        'reason': 'claude allowed — calling API',
        'estimated_input_tokens': estimate_tokens(prompt),
        'force': force,
    })

    _log('AI COST', f"Claude {use_case} ~{estimate_tokens(prompt)} tok")
    result = None
    for attempt in range(MAX_AI_RETRIES + 1):
        result = ask_ai(
            prompt,
            use_case=use_case,
            model_override='sonnet',
            max_tokens=max_tokens,
        )
        if isinstance(result, dict) and result.get('success'):
            break

    if not isinstance(result, dict):
        result = {'success': False, 'text': '', 'error': 'invalid response'}

    if not result.get('success'):
        record_routing_event({
            'tier': 'expensive',
            'use_case': use_case,
            'event': 'claude_failed',
            'reason': str(result.get('error', 'unknown')),
            'fallback': 'gemini_synthesis',
        })
        _log('CLAUDE SKIPPED', f"failed: {result.get('error')} — Gemini fallback")
        return call_cheap(prompt, use_case='gemini_synthesis', max_tokens=max_tokens)

    cost = float(result.get('estimated_cost') or 0)
    record_cost(cost, result.get('model', 'sonnet'), use_case, result.get('provider', 'anthropic'))
    record_routing_event({
        'tier': 'expensive',
        'use_case': use_case,
        'event': 'api_call',
        'model': result.get('model', 'sonnet'),
        'provider': result.get('provider', 'anthropic'),
        'success': True,
        'estimated_cost': cost,
    })
    set_cached(cache_key, result, use_case)
    return result


def pipeline_status() -> dict:
    from backend.ai.ai_budget_manager import budget_status
    status = budget_status()
    status['low_cost_mode'] = is_low_cost_mode()
    return status
