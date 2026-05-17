"""
AI ROUTER - Smart Multi-AI Routing
Uses gemini-2.0-flash (higher free quota: 1500/day vs 20/day)
"""

import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / 'config' / 'keys.env'
load_dotenv(env_path)

ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')


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
        'model': 'claude-haiku-4-5',
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
    'translate':          'gemini_lite',  # Lighter model for translations
}


def call_anthropic(model_name, prompt, max_tokens=2500):
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
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

        client = genai.Client(api_key=GOOGLE_API_KEY)

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
                client = genai.Client(api_key=GOOGLE_API_KEY)
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


if __name__ == "__main__":
    print("Testing AI Router...")
    print("=" * 60)

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