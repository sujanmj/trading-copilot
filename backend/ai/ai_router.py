"""
AI ROUTER v5 — Tiered orchestration via provider pools (Gemini / Groq / Claude).
"""

import os
import time
import warnings

import requests

from backend.ai.response_validator import validate_ai_response

try:
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', FutureWarning)
        import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    genai = None
    GENAI_AVAILABLE = False


def _load_env_files():
    from backend.utils.config import load_env
    load_env()


_load_env_files()


def get_anthropic_key():
    return os.environ.get('ANTHROPIC_API_KEY', '').strip()


def _ai_result(success, text='', model='', provider='', estimated_cost=0.0, error=None, **extra):
    payload = {
        'success': bool(success),
        'text': text if text is not None else '',
        'model': model if model is not None else '',
        'provider': provider if provider is not None else '',
        'estimated_cost': float(estimated_cost or 0),
        'error': error if not success else None,
    }
    payload.update(extra)
    return validate_ai_response(payload, source=provider or 'ai_router')


def _safe_return(result, model, provider, cost=0.0):
    if isinstance(result, dict):
        return validate_ai_response(result, source=provider or 'ai_router')
    return validate_ai_response(
        {
            'success': bool(result),
            'text': str(result) if result else '',
            'model': model or 'unknown',
            'provider': provider or 'unknown',
            'estimated_cost': float(cost or 0),
            'error': None if result else 'Empty response',
        },
        source=provider or 'ai_router',
    )


def _extract_gemini_text(response):
    text = ''
    try:
        text = getattr(response, 'text', None) or ''
    except Exception:
        text = ''
    if text:
        return str(text)
    try:
        candidates = getattr(response, 'candidates', None) or []
        if candidates:
            content = getattr(candidates[0], 'content', None)
            parts = getattr(content, 'parts', None) or []
            if parts:
                part_text = getattr(parts[0], 'text', None)
                if part_text:
                    return str(part_text)
    except Exception:
        pass
    try:
        if isinstance(response, dict):
            return str(
                response.get('candidates', [{}])[0]
                .get('content', {})
                .get('parts', [{}])[0]
                .get('text', '')
            )
    except Exception:
        pass
    return ''


MODELS = {
    'sonnet': {
        'provider': 'anthropic',
        'model': 'claude-sonnet-4-5',
        'cost_per_1k_input': 0.003,
        'cost_per_1k_output': 0.015,
    },
    'haiku': {
        'provider': 'anthropic',
        'model': 'claude-haiku-3-5-20241022',
        'cost_per_1k_input': 0.0008,
        'cost_per_1k_output': 0.004,
    },
    'gemini': {
        'provider': 'google',
        'model': 'gemini-2.0-flash',
        'cost_per_1k_input': 0,
        'cost_per_1k_output': 0,
    },
    'gemini_lite': {
        'provider': 'google',
        'model': 'gemini-2.0-flash-lite',
        'cost_per_1k_input': 0,
        'cost_per_1k_output': 0,
    },
    'groq': {
        'provider': 'groq',
        'model': os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile'),
        'cost_per_1k_input': 0,
        'cost_per_1k_output': 0,
    },
    'final_synthesis': {
        'provider': 'anthropic',
        'model': 'claude-sonnet-4-5',
        'cost_per_1k_input': 0.003,
        'cost_per_1k_output': 0.015,
    },
}

USE_CASE_ROUTING = {
    'overnight_brief': 'final_synthesis',
    'premarket_brief': 'final_synthesis',
    'midday_check': 'gemini',
    'post_close': 'gemini',
    'us_check': 'gemini',
    'manual_refresh': 'final_synthesis',
    'final_synthesis': 'final_synthesis',
    'compress': 'gemini',
    'gemini_synthesis': 'gemini',
    'ask_basic': 'groq',
    'ask_conversational': 'groq',
    'telegram_ask': 'groq',
    'ops_assistant': 'groq',
    'lightweight_summary': 'groq',
    'ask_haiku': 'groq',
    'ask_deep': 'sonnet',
    'stock_scanner': 'gemini',
    'alert_analysis': 'groq',
    'translate': 'gemini_lite',
    'postmortem': 'sonnet',
    'watchdog_refresh': 'gemini',
    'fixops_report_analyzer': 'final_synthesis',
}

CONVERSATIONAL_USE_CASES = frozenset({
    'ask_basic', 'ask_conversational', 'telegram_ask', 'ops_assistant',
    'lightweight_summary', 'ask_haiku', 'alert_analysis',
})

GROQ_FIRST_USE_CASES = frozenset({
    'telegram_ask', 'ask_basic', 'ops_assistant', 'ask_haiku', 'alert_analysis',
})


def _log_route(use_case: str, target: str, detail: str = ''):
    line = f"{use_case} → {target}"
    if detail:
        line = f"{line} ({detail})"
    print(f"  [AI ROUTE] {line}")


def call_anthropic(model_name, prompt, max_tokens=2500):
    provider = 'anthropic'
    try:
        import anthropic

        api_key = get_anthropic_key()
        if not api_key:
            return _ai_result(False, model=model_name, provider=provider,
                              error='ANTHROPIC_API_KEY not set in environment')
        if not api_key.startswith('sk-ant-'):
            return _ai_result(False, model=model_name, provider=provider,
                              error='Invalid ANTHROPIC_API_KEY format')

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model_name,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = {
            'success': True,
            'text': message.content[0].text,
            'model': model_name,
            'provider': provider,
            'estimated_cost': 0.0,
            'error': None,
            'input_tokens': message.usage.input_tokens,
            'output_tokens': message.usage.output_tokens,
        }
        return validate_ai_response(raw, source=provider)
    except Exception as e:
        return _ai_result(False, model=model_name, provider=provider, error=str(e))


def _call_gemini_rest(api_key, model_name, prompt, max_tokens=2500):
    provider = 'google'
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.7,
        },
    }
    try:
        response = requests.post(url, json=payload, timeout=45)
        response.raise_for_status()
        data = response.json()
        text = _extract_gemini_text(data)
        usage = data.get('usageMetadata') or {}
        raw = {
            'success': bool(text),
            'text': text,
            'model': model_name,
            'provider': provider,
            'estimated_cost': 0.0,
            'error': None if text else 'Empty Gemini REST response',
            'input_tokens': usage.get('promptTokenCount', 0),
            'output_tokens': usage.get('candidatesTokenCount', 0),
        }
        return validate_ai_response(raw, source=provider)
    except requests.HTTPError as e:
        detail = ''
        try:
            detail = e.response.text[:300] if e.response is not None else ''
        except Exception:
            pass
        err = f"{e} {detail}".strip()
        return _ai_result(False, model=model_name, provider=provider, error=err)
    except Exception as e:
        return _ai_result(False, model=model_name, provider=provider, error=str(e))


def _call_groq_rest(api_key, model_name, prompt, max_tokens=2500):
    provider = 'groq'
    url = 'https://api.groq.com/openai/v1/chat/completions'
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    payload = {
        'model': model_name,
        'messages': [{'role': 'user', 'content': prompt}],
        'max_tokens': max_tokens,
        'temperature': 0.6,
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        text = ''
        try:
            text = data['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError):
            text = ''
        usage = data.get('usage') or {}
        raw = {
            'success': bool(text),
            'text': text or '',
            'model': model_name,
            'provider': provider,
            'estimated_cost': 0.0,
            'error': None if text else 'Empty Groq response',
            'input_tokens': usage.get('prompt_tokens', 0),
            'output_tokens': usage.get('completion_tokens', 0),
        }
        return validate_ai_response(raw, source=provider)
    except requests.HTTPError as e:
        detail = ''
        try:
            detail = e.response.text[:300] if e.response is not None else ''
        except Exception:
            pass
        return _ai_result(False, model=model_name, provider=provider, error=f"{e} {detail}".strip())
    except Exception as e:
        return _ai_result(False, model=model_name, provider=provider, error=str(e))


def call_gemini(model_name, prompt, max_tokens=2500, *, use_case: str = ''):
    from backend.ai.provider_manager import get_gemini_pool

    pool = get_gemini_pool()
    if use_case:
        _log_route(use_case, 'gemini_pool', pool._state.get('active_slot') or 'gemini-1')

    def _invoke(api_key: str, slot_id: str):
        t0 = time.time()
        result = _call_gemini_rest(api_key, model_name, prompt, max_tokens)
        latency = (time.time() - t0) * 1000
        if result.get('success'):
            return result, latency
        err = str(result.get('error') or '')
        if '429' in err or 'quota' in err.lower() or 'resource_exhausted' in err.lower():
            lite = _call_gemini_rest(api_key, 'gemini-2.0-flash-lite', prompt, max_tokens)
            if lite.get('success'):
                lite['model'] = 'gemini-2.0-flash-lite (lite)'
                return lite, (time.time() - t0) * 1000
            result = lite
        return result, latency

    result, meta = pool.execute_with_failover(_invoke, model_label=model_name)
    result['_pool_meta'] = meta
    if meta.get('slot_id'):
        result['provider_slot'] = meta['slot_id']
    if meta.get('degraded') and not result.get('success'):
        result.setdefault('user_message', meta.get('user_message'))
        try:
            from backend.ai.provider_manager import ENRICHMENT_UNAVAILABLE_MSG
            result['user_message'] = ENRICHMENT_UNAVAILABLE_MSG
        except Exception:
            pass
    return result


def call_groq(model_name, prompt, max_tokens=2500, *, use_case: str = '', allow_gemini_fallback: bool = True):
    from backend.ai.provider_manager import get_gemini_pool, get_groq_pool, ENRICHMENT_UNAVAILABLE_MSG

    pool = get_groq_pool()
    _log_route(use_case or 'conversational', 'groq_pool', pool._state.get('active_slot') or 'groq-1')

    def _invoke(api_key: str, slot_id: str):
        t0 = time.time()
        result = _call_groq_rest(api_key, model_name, prompt, max_tokens)
        return result, (time.time() - t0) * 1000

    result, meta = pool.execute_with_failover(_invoke, model_label=model_name)
    result['_pool_meta'] = meta
    if result.get('success'):
        return result

    # Conversational fallback → Gemini pool
    if allow_gemini_fallback and not get_gemini_pool().is_degraded():
        print('  [AI] Groq pool exhausted — falling back to Gemini for conversational request')
        _log_route(use_case or 'conversational', 'gemini_pool', 'groq-fallback')
        gem = call_gemini('gemini-2.0-flash-lite', prompt, max_tokens, use_case=use_case)
        if gem.get('success'):
            gem['model'] = f"{gem.get('model', 'gemini')} (groq-fallback)"
            gem['provider'] = 'google'
            gem['fallback_from'] = 'groq'
            return gem

    result['user_message'] = ENRICHMENT_UNAVAILABLE_MSG
    return result


def _is_quota_error_text(err: str) -> bool:
    e = (err or '').lower()
    return '429' in e or 'quota' in e or 'rate limit' in e or 'resource_exhausted' in e


def resolve_conversational_priority(use_case: str, prompt: str) -> str:
    """Route trivial asks to Groq; deeper contextual asks to Gemini.

    Telegram / operator chat always uses Groq first — prompt length includes
    intelligence context and must not force Gemini routing.
    """
    if use_case in GROQ_FIRST_USE_CASES:
        return 'groq'
    if use_case == 'ask_deep':
        return 'gemini'
    question_len = len(prompt or '')
    if 'Question:' in (prompt or ''):
        question_len = len((prompt or '').split('Question:')[-1])
    deep_markers = (
        'analyze', 'analysis', 'strategy', 'strategic', 'compare', 'contrast',
        'deep dive', 'explain in detail', 'why did', 'root cause', 'implications',
        'market situation', 'sector rotation', 'macro',
    )
    pl = (prompt or '').lower()
    qpart = pl.split('question:')[-1] if 'question:' in pl else pl
    if question_len > 800 or (question_len > 300 and any(m in qpart for m in deep_markers)):
        return 'gemini'
    return 'groq'


def ask_ai(
    prompt,
    use_case='ask_basic',
    model_override=None,
    max_tokens=2500,
    channel='api',
    skip_cache=False,
):
    from backend.ai.provider_manager import resolve_use_case_tier, get_degraded_status, get_groq_pool
    from backend.ai.conversational_cache import get_cached, set_cached, should_use_cache
    from backend.analytics.provider_analytics import normalize_provider, record_provider_request

    if model_override:
        model_key = model_override
    else:
        model_key = USE_CASE_ROUTING.get(use_case, 'gemini')

    tier = resolve_use_case_tier(use_case)
    if model_override == 'groq' or model_key == 'groq':
        tier = 'conversational'
    elif model_override in ('sonnet', 'final_synthesis') or model_key in ('sonnet', 'final_synthesis', 'postmortem'):
        tier = 'strategic'
    elif model_override in ('gemini', 'gemini_lite') or model_key in ('gemini', 'gemini_lite', 'compress'):
        tier = 'gemini'

    if tier == 'conversational' and not model_override:
        priority = resolve_conversational_priority(use_case, prompt)
        if priority == 'gemini':
            model_key = 'gemini'
            tier = 'gemini'
            _log_route(use_case, 'gemini', 'deep contextual')
        else:
            model_key = 'groq'
            _log_route(use_case, 'groq_pool', 'conversational-first')

    if model_key not in MODELS and model_key != 'groq':
        if tier == 'conversational':
            model_key = 'groq'
        elif tier == 'strategic':
            model_key = 'sonnet'
        else:
            model_key = 'gemini'

    if not skip_cache and should_use_cache(use_case, tier):
        cached = get_cached(use_case, prompt)
        if cached:
            record_provider_request(
                provider=normalize_provider(cached.get('provider', 'groq'), tier),
                use_case=use_case,
                channel=channel,
                success=True,
                latency_ms=0.0,
                cache_hit=True,
            )
            out = validate_ai_response(cached, source='conversational_cache')
            out['routing_tier'] = tier
            out['cache_hit'] = True
            return out

    model_config = MODELS.get(model_key, MODELS['gemini'])
    provider = model_config['provider']
    model_name = model_config['model']
    t0 = time.time()
    pool_meta = {}
    fallback_used = False
    quota_failure = False

    if tier == 'conversational' or model_key == 'groq':
        provider = 'groq'
        model_name = MODELS['groq']['model']
        print(f"  [AI] Using GROQ ({model_name}) for: {use_case}")
        raw = call_groq(model_name, prompt, max_tokens, use_case=use_case)
        pool_meta = raw.pop('_pool_meta', {}) or {}
        if raw.get('fallback_from') == 'groq':
            fallback_used = True
    elif tier == 'gemini' and use_case in CONVERSATIONAL_USE_CASES:
        print(f"  [AI] Using GEMINI pool ({model_name}) for: {use_case}")
        raw = call_gemini(model_name, prompt, max_tokens, use_case=use_case)
        pool_meta = raw.pop('_pool_meta', {}) or {}
        if not raw.get('success') and not get_groq_pool().is_degraded():
            print('  [AI] Gemini conversational path failed — falling back to Groq')
            _log_route(use_case, 'groq_pool', 'gemini-fallback')
            raw = call_groq(MODELS['groq']['model'], prompt, max_tokens, use_case=use_case)
            pool_meta = raw.pop('_pool_meta', {}) or {}
            fallback_used = True
    elif tier == 'strategic' or provider == 'anthropic':
        from backend.ai.ai_provider_fallback import call_strategic_with_cascade
        print(f'  [AI] Strategic provider cascade for: {use_case}')
        raw = call_strategic_with_cascade(prompt, use_case=use_case, max_tokens=max_tokens)
        pool_meta = raw.pop('_pool_meta', {}) or {}
        fallback_used = bool(raw.get('fallback_final') or 'cascade' in str(raw.get('model', '')))
    elif provider == 'google':
        print(f"  [AI] Using GEMINI pool ({model_name}) for: {use_case}")
        raw = call_gemini(model_name, prompt, max_tokens, use_case=use_case)
        pool_meta = raw.pop('_pool_meta', {}) or {}
    else:
        raw = _ai_result(False, error=f"Unknown provider: {provider}", provider=provider)

    latency_ms = (time.time() - t0) * 1000
    err_text = str(raw.get('error') or '')
    quota_failure = _is_quota_error_text(err_text)
    degraded = bool(pool_meta.get('degraded')) or get_degraded_status().get('mode') not in (None, 'normal', '')

    result = validate_ai_response(raw, source=f'{raw.get("provider", provider)}/{model_name}')
    result['routing_tier'] = tier
    result['degraded_mode'] = get_degraded_status().get('mode')
    result['cache_hit'] = False

    if result['success'] and isinstance(raw, dict):
        input_tokens = raw.get('input_tokens', 0) or 0
        output_tokens = raw.get('output_tokens', 0) or 0
        if input_tokens or output_tokens:
            cfg = MODELS.get(model_key, MODELS['gemini'])
            input_cost = (input_tokens / 1000) * cfg['cost_per_1k_input']
            output_cost = (output_tokens / 1000) * cfg['cost_per_1k_output']
            result['estimated_cost'] = round(input_cost + output_cost, 4)

    record_provider_request(
        provider=normalize_provider(result.get('provider', provider), tier),
        use_case=use_case,
        channel=channel,
        success=bool(result.get('success')),
        latency_ms=latency_ms,
        failovers=int(pool_meta.get('failovers') or 0),
        quota_failure=quota_failure,
        fallback=fallback_used,
        cache_hit=False,
        degraded=degraded,
    )

    if result.get('success') and should_use_cache(use_case, tier):
        set_cached(use_case, prompt, result)

    return _safe_return(result, result.get('model', model_name), result.get('provider', provider), result.get('estimated_cost', 0))


def check_keys_status():
    try:
        from backend.ai.provider_manager import get_provider_ops_summary
        ops = get_provider_ops_summary()
        gem = ops.get('providers', {}).get('gemini', {})
        groq = ops.get('providers', {}).get('groq', {})
        claude = ops.get('providers', {}).get('claude', {})
        return {
            'anthropic': bool(get_anthropic_key()),
            'google': not gem.get('degraded', True),
            'groq': not groq.get('degraded', True),
            'gemini_active_slot': gem.get('active_slot'),
            'groq_active_slot': groq.get('active_slot'),
            'degraded_mode': ops.get('degraded', {}).get('mode'),
            'anthropic_first_chars': get_anthropic_key()[:15] if get_anthropic_key() else 'MISSING',
        }
    except Exception:
        return {
            'anthropic': bool(get_anthropic_key()),
            'google': bool(os.environ.get('GOOGLE_API_KEY') or os.environ.get('GOOGLE_API_KEY_1')),
            'groq': bool(os.environ.get('GROQ_API_KEY_1') or os.environ.get('GROQ_API_KEY')),
        }


if __name__ == "__main__":
    print("Testing AI Router v5...")
    test_prompt = "In one sentence, what is the Indian stock market?"
    for model in ['groq', 'gemini']:
        result = ask_ai(test_prompt, model_override=model, max_tokens=200)
        print(f"{model}: success={result.get('success')} provider={result.get('provider')}")
