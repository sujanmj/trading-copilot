#!/usr/bin/env python3
"""Validate configured provider model migrations without making network calls."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_LISTENER', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')
os.environ.setdefault('DISABLE_TRADE_EXECUTION', '1')
os.environ['GROQ_MODEL'] = 'llama-3.3-70b-versatile'


def main() -> int:
    from backend.ai.ai_router import MODELS, _gemini_generation_config
    from backend.ai.model_config import (
        GROQ_COST_PER_1K_INPUT,
        GROQ_COST_PER_1K_OUTPUT,
        GEMINI_LITE_MODEL,
        GEMINI_PRIMARY_MODEL,
        GROQ_DEFAULT_MODEL,
        resolve_groq_model,
    )
    from backend.ai.provider_manager import GROQ_DEFAULT_MODEL as PROVIDER_MANAGER_MODEL

    assert GEMINI_PRIMARY_MODEL == 'gemini-3.6-flash'
    assert GEMINI_LITE_MODEL == 'gemini-3.5-flash-lite'
    assert MODELS['gemini']['model'] == GEMINI_PRIMARY_MODEL
    assert MODELS['gemini_lite']['model'] == GEMINI_LITE_MODEL
    assert GROQ_DEFAULT_MODEL == 'openai/gpt-oss-20b'
    assert resolve_groq_model('llama-3.3-70b-versatile') == GROQ_DEFAULT_MODEL
    assert MODELS['groq']['model'] == GROQ_DEFAULT_MODEL
    assert MODELS['groq']['cost_per_1k_input'] == GROQ_COST_PER_1K_INPUT
    assert MODELS['groq']['cost_per_1k_output'] == GROQ_COST_PER_1K_OUTPUT
    assert PROVIDER_MANAGER_MODEL == GROQ_DEFAULT_MODEL
    assert resolve_groq_model('custom/model') == 'custom/model'
    assert resolve_groq_model(None) == GROQ_DEFAULT_MODEL
    assert _gemini_generation_config(GEMINI_PRIMARY_MODEL, 128) == {'maxOutputTokens': 128}
    assert _gemini_generation_config(GEMINI_LITE_MODEL, 128) == {'maxOutputTokens': 128}
    assert _gemini_generation_config('gemini-2.5-flash', 128) == {
        'maxOutputTokens': 128, 'temperature': 0.7,
    }
    for module in ('ai_router.py', 'ai_pool_router.py', 'ai_provider_fallback.py'):
        source = (ROOT / 'backend/ai' / module).read_text(encoding='utf-8')
        assert 'gemini-2.0-flash' not in source, f'retired Gemini ID remains in {module}'
    print('AI_MODEL_CONFIG_PASS network_calls=0')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
