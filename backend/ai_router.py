"""
AI ROUTER v4 - Guaranteed dict responses via response_validator
Uses gemini-2.0-flash (higher free quota: 1500/day vs 20/day)
"""

import os
from pathlib import Path

from response_validator import validate_ai_response


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


def _ai_result(success, text='', model='', provider='', estimated_cost=0.0, error=None):
    """Build standard dict — always pass through validate_ai_response before returning to callers."""
    return validate_ai_response(
        {
            'success': bool(success),
            'text': text if text is not None else '',
            'model': model if model is not None else '',
            'provider': provider if provider is not None else '',
            'estimated_cost': float(estimated_cost or 0),
            'error': error if not success else None,
        },
        source=provider or 'ai_router',
    )


def _safe_return(text, model, provider, cost=0.0):
    """Final safety wrapper — never return a plain string from ask_ai()."""
    if isinstance(text, dict):
        return validate_ai_response(text, source=provider or 'ai_router')
    return validate_ai_response(
        {
            'success': bool(text),
            'text': str(text) if text else '',
            'model': model or 'unknown',
            'provider': provider or 'unknown',
            'estimated_cost': float(cost or 0),
            'error': None if text else 'Empty response',
        },
        source=provider or 'ai_router',
    )


def _extract_gemini_text(response):
    """Extract text from Gemini response object without returning a bare string upstream."""
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
    provider = 'anthropic'
    try:
        import anthropic

        api_key = get_anthropic_key()
        if not api_key:
            return _ai_result(False, model=model_name, provider=provider,
                              error='ANTHROPIC_API_KEY not set in environment')
        if not api_key.startswith('sk-ant-'):
            return _ai_result(False, model=model_name, provider=provider,
                              error=f'Invalid ANTHROPIC_API_KEY format. Got: {api_key[:10]}...')

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


def call_gemini(model_name, prompt, max_tokens=2500):
    provider = 'google'
    try:
        from google import genai
        from google.genai import types

        api_key = get_google_key()
        if not api_key:
            return _ai_result(False, model=model_name, provider=provider,
                              error='GOOGLE_API_KEY not set in environment')

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
        text = _extract_gemini_text(response)

        raw = {
            'success': bool(text),
            'text': text,
            'model': model_name,
            'provider': provider,
            'estimated_cost': 0.0,
            'error': None if text else 'Empty Gemini response',
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
        }
        return validate_ai_response(raw, source=provider)
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
                text = _extract_gemini_text(response)
                raw = {
                    'success': bool(text),
                    'text': text,
                    'model': 'gemini-2.0-flash-lite (fallback)',
                    'provider': provider,
                    'estimated_cost': 0.0,
                    'error': None if text else 'Empty Gemini lite response',
                    'input_tokens': 0,
                    'output_tokens': 0,
                }
                return validate_ai_response(raw, source=provider)
            except Exception as e2:
                return _ai_result(
                    False,
                    model=model_name,
                    provider=provider,
                    error=f'Both Gemini models failed: {str(e2)[:200]}',
                )

        return _ai_result(False, model=model_name, provider=provider, error=error_str)


def ask_ai(prompt, use_case='ask_basic', model_override=None, max_tokens=2500):
    if model_override:
        model_key = model_override
    else:
        model_key = USE_CASE_ROUTING.get(use_case, 'gemini')

    if model_key not in MODELS:
        return validate_ai_response(
            {'success': False, 'error': f'Unknown model: {model_key}', 'text': ''},
            source='ai_router',
        )

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
            raw = _ai_result(False, error=f"Unknown provider: {provider}", provider=provider)
    except Exception as e:
        raw = _ai_result(False, model=model_name, provider=provider, error=str(e))

    result = validate_ai_response(raw, source=f'{provider}/{model_name}')

    if result['success'] and isinstance(raw, dict):
        input_tokens = raw.get('input_tokens', 0) or 0
        output_tokens = raw.get('output_tokens', 0) or 0
        if input_tokens or output_tokens:
            input_cost = (input_tokens / 1000) * model_config['cost_per_1k_input']
            output_cost = (output_tokens / 1000) * model_config['cost_per_1k_output']
            result['estimated_cost'] = round(input_cost + output_cost, 4)

    return _safe_return(result, model_name, provider, result.get('estimated_cost', 0))


def check_keys_status():
    return {
        'anthropic': bool(get_anthropic_key()),
        'google': bool(get_google_key()),
        'anthropic_first_chars': get_anthropic_key()[:15] if get_anthropic_key() else 'MISSING',
        'anthropic_length': len(get_anthropic_key()),
    }


if __name__ == "__main__":
    print("Testing AI Router v4...")
    test_prompt = "In one sentence, what is the Indian stock market?"
    for model in ['gemini', 'haiku', 'sonnet']:
        result = ask_ai(test_prompt, model_override=model, max_tokens=200)
        assert isinstance(result, dict), f"ask_ai returned {type(result)}"
        assert 'success' in result and 'text' in result
        print(f"{model}: type={type(result).__name__} success={result['success']}")
