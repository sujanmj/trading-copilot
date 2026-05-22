"""
AI ROUTER v2 - Smart Multi-AI Routing (Railway-Ready)
Uses gemini-2.0-flash (higher free quota: 1500/day vs 20/day)

v2 Changes:
- Fixed env var loading for Railway/cloud environments
- Reads keys at function call time (not import time)
- override=False to preserve Railway's env vars
"""

import os
from pathlib import Path

# Load .env file ONLY if it exists (local dev)
# On Railway, env vars come from system - don't override them
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / 'config' / 'keys.env'
    if env_path.exists():
        load_dotenv(env_path, override=False)  # CRITICAL: don't override Railway vars
except ImportError:
    pass


def get_anthropic_key():
    """Read Anthropic key at call time (not import time)"""
    return os.environ.get('ANTHROPIC_API_KEY', '').strip()


def get_google_key():
    """Read Google key at call time (not import time)"""
    return os.environ.get('GOOGLE_API_KEY', '').strip()


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
        'model': 'claude-haiku-3-5-20241022',  # ← FIXED
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
        
        # READ KEY AT CALL TIME (fix for Railway)
        api_key = get_anthropic_key()
        
        if not api_key:
            return {
                'success': False, 
                'error': 'ANTHROPIC_API_KEY not set in environment', 
                'model': model_name
            }
        
        # Verify key format
        if not api_key.startswith('sk-ant-'):
            return {
                'success': False,
                'error': f'Invalid ANTHROPIC_API_KEY format (should start with sk-ant-). Got: {api_key[:10]}...',
                'model': model_name
            }
        
        # Pass API key explicitly to avoid env var issues
        client = anthropic.Anthropic(api_key=api_key)
        
        message = client.messages.create(
            model=model_name,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
        return {
            'success': True,
            'text': message.content[0].text,
            'model': model_name,
            'provider': 'anthropic',
            'input_tokens': message.usage.input_tokens,
            'output_tokens': message.usage.output_tokens,
        }
    except Exception as e:
        return {'success': False, 'error': str(e), 'model': model_name}


def call_gemini(model_name, prompt, max_tokens=2500):
    try:
        from google import genai
        from google.genai import types

        # READ KEY AT CALL TIME
        api_key = get_google_key()
        
        if not api_key:
            return {
                'success': False, 
                'error': 'GOOGLE_API_KEY not set in environment', 
                'model': model_name
            }

        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=max_tokens,
                temperature=0.7,
            )
        )

        usage = getattr(response, 'usage_metadata', None)
        input_tokens = getattr(usage, 'prompt_token_count', 0) if usage else 0
        output_tokens = getattr(usage, 'candidates_token_count', 0) if usage else 0

        return {
            'success': True,
            'text': response.text,
            'model': model_name,
            'provider': 'google',
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
        }
    except Exception as e:
        error_str = str(e)

        # If quota exceeded, try fallback model automatically
        if '429' in error_str or 'RESOURCE_EXHAUSTED' in error_str or 'quota' in error_str.lower():
            print(f"  [AI] Gemini quota hit, trying lite model...")
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
                    )
                )
                return {
                    'success': True,
                    'text': response.text,
                    'model': 'gemini-2.0-flash-lite (fallback)',
                    'provider': 'google',
                    'input_tokens': 0,
                    'output_tokens': 0,
                }
            except Exception as e2:
                return {'success': False, 'error': f'Both Gemini models failed: {str(e2)[:200]}', 'model': model_name}

        return {'success': False, 'error': error_str, 'model': model_name}


def ask_ai(prompt, use_case='ask_basic', model_override=None, max_tokens=2500):
    if model_override:
        model_key = model_override
    else:
        model_key = USE_CASE_ROUTING.get(use_case, 'gemini')

    if model_key not in MODELS:
        return {'success': False, 'error': f'Unknown model: {model_key}'}

    model_config = MODELS[model_key]
    print(f"  [AI] Using {model_key.upper()} ({model_config['provider']}) for: {use_case}")

    if model_config['provider'] == 'anthropic':
        result = call_anthropic(model_config['model'], prompt, max_tokens)
    elif model_config['provider'] == 'google':
        result = call_gemini(model_config['model'], prompt, max_tokens)
    else:
        return {'success': False, 'error': f"Unknown provider: {model_config['provider']}"}

    if result['success'] and 'input_tokens' in result:
        input_cost = (result['input_tokens'] / 1000) * model_config['cost_per_1k_input']
        output_cost = (result['output_tokens'] / 1000) * model_config['cost_per_1k_output']
        result['estimated_cost'] = round(input_cost + output_cost, 4)

    return result


def check_keys_status():
    """Diagnostic: returns which keys are loaded"""
    return {
        'anthropic': bool(get_anthropic_key()),
        'google': bool(get_google_key()),
        'anthropic_first_chars': get_anthropic_key()[:15] if get_anthropic_key() else 'MISSING',
        'anthropic_length': len(get_anthropic_key()),
    }


if __name__ == "__main__":
    print("Testing AI Router v2...")
    print("=" * 60)
    
    # Show key status
    status = check_keys_status()
    print(f"\nKey Status:")
    print(f"  Anthropic: {'✅ SET' if status['anthropic'] else '❌ MISSING'}")
    print(f"  Google: {'✅ SET' if status['google'] else '❌ MISSING'}")
    print(f"  Anthropic key starts with: {status['anthropic_first_chars']}")
    print(f"  Anthropic key length: {status['anthropic_length']}")
    print()

    test_prompt = "In one sentence, what is the Indian stock market?"

    for model in ['gemini', 'haiku', 'sonnet']:
        print(f"\nTesting {model.upper()}...")
        result = ask_ai(test_prompt, model_override=model, max_tokens=200)
        if result['success']:
            print(f"  Response: {result['text'][:200]}")
            if 'estimated_cost' in result:
                print(f"  Cost: ${result['estimated_cost']}")
        else:
            print(f"  ERROR: {result.get('error', 'Unknown')[:200]}")

    print("\n" + "=" * 60)
    print("Test complete!")