"""
AI ROUTER v3 - Normalized dict responses (never returns plain strings)
Uses gemini-2.0-flash (higher free quota: 1500/day vs 20/day)
"""

import os
from pathlib import Path


def _load_env_files():
    """Load keys.env from Railway or local paths if present (silent if missing)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for env_path in (
        Path('/app/config/keys.env'),
        Path(__file__).parent.parent / 'config' / 'keys.env',
    ):
        if env_path.exists():
            load_dotenv(env_path, override=False)
            return


_load_env_files()


def get_anthropic_key():
    return os.environ.get('ANTHROPIC_API_KEY', '').strip()


def get_google_key():
    return os.environ.get('GOOGLE_API_KEY', '').strip()


def _ai_result(success, text='', model='', provider='', estimated_cost=0, error=None, **extra):
    """Standard response shape — every ask_ai/call_* path must use this."""
    out = {
        'success': bool(success),
        'text': text if text is not None else '',
        'model': model if model is not None else '',
        'provider': provider if provider is not None else '',
        'estimated_cost': estimated_cost if estimated_cost is not None else 0,
        'error': error,
    }
    out.update(extra)
    return out


def _normalize_ai_dict(raw, default_model='', default_provider=''):
    """Coerce any partial/legacy return into the standard dict."""
    if isinstance(raw, str):
        return _ai_result(True, text=raw, model=default_model or 'unknown',
                          provider=default_provider or 'unknown', estimated_cost=0)

    if not isinstance(raw, dict):
        return _ai_result(
            False,
            model=default_model,
            provider=default_provider,
            error=f'Invalid AI response type: {type(raw).__name__}',
        )

    success = bool(raw.get('success'))
    text = raw.get('text', '')
    if text is None:
        text = ''
    if not text and success and raw.get('response'):
        text = str(raw.get('response', ''))
    if not text and success and isinstance(raw.get('content'), str):
        text = raw.get('content', '')

    estimated_cost = raw.get('estimated_cost', 0)
    if estimated_cost is None:
        estimated_cost = 0

    err = raw.get('error')
    if not success and err is None:
        err = 'Unknown AI error'

    result = _ai_result(
        success,
        text=str(text) if text is not None else '',
        model=raw.get('model') or default_model or '',
        provider=raw.get('provider') or default_provider or '',
        estimated_cost=estimated_cost,
        error=err if not success else None,
    )

    if 'input_tokens' in raw:
        result['input_tokens'] = raw['input_tokens']
    if 'output_tokens' in raw:
        result['output_tokens'] = raw['output_tokens']

    return result


MODELS = {
    'sonnet': {
        'provider': 'anthropic',
        'model': 'claude-sonnet-4-5',
        'cost_per_1k_input': 0.003,
        'cost_per_1k_output': 0.015,
        'quality': 'best',
        'speed': 'medium',
    },
    'haiku': {
        'provider': 'anthropic',
        'model': 'claude-haiku-3-5-20241022',
        'cost_per_1k_input': 0.0008,
        'cost_per_1k_output': 0.004,
        'quality': 'good',
        'speed': 'fast',
    },
    'gemini': {
        'provider': 'google',
        'model': 'gemini-2.0-flash',
        'cost_per_1k_input': 0,
        'cost_per_1k_output': 0,
        'quality': 'good',
        'speed': 'fast',
        'daily_limit': 1500,
    },
    'gemini_lite': {
        'provider': 'google',
        'model': 'gemini-2.0-flash-lite',
        'cost_per_1k_input': 0,
        'cost_per_1k_output': 0,
        'quality': 'okay',
        'speed': 'very_fast',
        'daily_limit': 1500,
    },
}

USE_CASE_ROUTING = {
    'overnight_brief':    'sonnet',
    'premarket_brief':    'sonnet',
    'midday_check':       'gemini',
    'post_close':         'haiku',
    'us_check':           'gemini',
    'manual_refresh':     'sonnet',
    'ask_basic':          'gemini',
    'ask_haiku':          'haiku',
    'ask_deep':           'sonnet',
    'stock_scanner':      'gemini',
    'alert_analysis':     'haiku',
    'translate':          'gemini_lite',
    'postmortem':         'sonnet',
}


def call_anthropic(model_name, prompt, max_tokens=2500):
    try:
        import anthropic

        api_key = get_anthropic_key()

        if not api_key:
            return _ai_result(
                False,
                model=model_name,
                provider='anthropic',
                error='ANTHROPIC_API_KEY not set in environment',
            )

        if not api_key.startswith('sk-ant-'):
            return _ai_result(
                False,
                model=model_name,
                provider='anthropic',
                error=f'Invalid ANTHROPIC_API_KEY format. Got: {api_key[:10]}...',
            )

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model_name,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return _ai_result(
            True,
            text=message.content[0].text,
            model=model_name,
            provider='anthropic',
            estimated_cost=0,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )
    except Exception as e:
        return _ai_result(
            False,
            model=model_name,
            provider='anthropic',
            error=str(e),
        )


def call_gemini(model_name, prompt, max_tokens=2500):
    try:
        from google import genai
        from google.genai import types

        api_key = get_google_key()

        if not api_key:
            return _ai_result(
                False,
                model=model_name,
                provider='google',
                error='GOOGLE_API_KEY not set in environment',
            )

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=max_tokens,
                temperature=0.7,
            ),
        )

        usage = getattr(response, 'usage_metadata', None)
        input_tokens = getattr(usage, 'prompt_token_count', 0) if usage else 0
        output_tokens = getattr(usage, 'candidates_token_count', 0) if usage else 0
        text = response.text or ''

        return _ai_result(
            True,
            text=text,
            model=model_name,
            provider='google',
            estimated_cost=0,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    except Exception as e:
        error_str = str(e)

        if '429' in error_str or 'RESOURCE_EXHAUSTED' in error_str or 'quota' in error_str.lower():
            print("  [AI] Gemini quota hit, trying lite model...")
            try:
                from google import genai
                from google.genai import types
                api_key = get_google_key()
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model='gemini-2.0-flash-lite',
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        max_output_tokens=max_tokens,
                        temperature=0.7,
                    ),
                )
                return _ai_result(
                    True,
                    text=response.text or '',
                    model='gemini-2.0-flash-lite (fallback)',
                    provider='google',
                    estimated_cost=0,
                    input_tokens=0,
                    output_tokens=0,
                )
            except Exception as e2:
                return _ai_result(
                    False,
                    model=model_name,
                    provider='google',
                    error=f'Both Gemini models failed: {str(e2)[:200]}',
                )

        return _ai_result(
            False,
            model=model_name,
            provider='google',
            error=error_str,
        )


def ask_ai(prompt, use_case='ask_basic', model_override=None, max_tokens=2500):
    if model_override:
        model_key = model_override
    else:
        model_key = USE_CASE_ROUTING.get(use_case, 'gemini')

    if model_key not in MODELS:
        return _ai_result(False, error=f'Unknown model: {model_key}')

    model_config = MODELS[model_key]
    provider = model_config['provider']
    model_name = model_config['model']
    print(f"  [AI] Using {model_key.upper()} ({provider}) for: {use_case}")

    try:
        if provider == 'anthropic':
            raw = call_anthropic(model_name, prompt, max_tokens)
        elif provider == 'google':
            raw = call_gemini(model_name, prompt, max_tokens)
        else:
            return _ai_result(False, error=f"Unknown provider: {provider}")
    except Exception as e:
        return _ai_result(
            False,
            model=model_name,
            provider=provider,
            error=str(e),
        )

    result = _normalize_ai_dict(raw, default_model=model_name, default_provider=provider)

    if result['success'] and result.get('input_tokens'):
        input_cost = (result['input_tokens'] / 1000) * model_config['cost_per_1k_input']
        output_cost = (result['output_tokens'] / 1000) * model_config['cost_per_1k_output']
        result['estimated_cost'] = round(input_cost + output_cost, 4)

    return result


def check_keys_status():
    return {
        'anthropic': bool(get_anthropic_key()),
        'google': bool(get_google_key()),
        'anthropic_first_chars': get_anthropic_key()[:15] if get_anthropic_key() else 'MISSING',
        'anthropic_length': len(get_anthropic_key()),
    }


if __name__ == "__main__":
    print("Testing AI Router v3...")
    print("=" * 60)

    status = check_keys_status()
    print(f"\nKey Status:")
    print(f"  Anthropic: {'SET' if status['anthropic'] else 'MISSING'}")
    print(f"  Google: {'SET' if status['google'] else 'MISSING'}")

    test_prompt = "In one sentence, what is the Indian stock market?"

    for model in ['gemini', 'haiku', 'sonnet']:
        print(f"\nTesting {model.upper()}...")
        result = ask_ai(test_prompt, model_override=model, max_tokens=200)
        print(f"  type={type(result).__name__} success={result.get('success')}")
        if result['success']:
            print(f"  Response: {result['text'][:200]}")
            print(f"  Cost: ${result.get('estimated_cost', 0)}")
        else:
            print(f"  ERROR: {result.get('error', 'Unknown')[:200]}")

    print("\n" + "=" * 60)
    print("Test complete!")
