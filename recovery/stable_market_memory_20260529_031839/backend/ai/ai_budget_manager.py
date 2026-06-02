"""Daily AI spend tracking and budget protection."""

import os
from datetime import datetime, timezone
from typing import Optional

from backend.utils.config import AI_BUDGET_FILE, MAX_DAILY_AI_COST, get_env
from backend.storage.json_io import atomic_write_json

_low_cost_mode = False
_budget_warned_today = False


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _load_budget() -> dict:
    if not AI_BUDGET_FILE.exists():
        return {'date': _today_key(), 'total_cost': 0.0, 'calls': [], 'low_cost_mode': False}
    try:
        import json
        with open(AI_BUDGET_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError('invalid budget file')
        if data.get('date') != _today_key():
            return {'date': _today_key(), 'total_cost': 0.0, 'calls': [], 'low_cost_mode': False}
        return data
    except Exception as e:
        print(f"[AI COST] Corrupt budget file reset: {e}")
        return {'date': _today_key(), 'total_cost': 0.0, 'calls': [], 'low_cost_mode': False}


def _save_budget(data: dict):
    atomic_write_json(AI_BUDGET_FILE, data)


def get_today_spend() -> float:
    return float(_load_budget().get('total_cost') or 0.0)


def is_budget_exceeded() -> bool:
    return get_today_spend() >= MAX_DAILY_AI_COST


def is_low_cost_mode() -> bool:
    global _low_cost_mode
    if _low_cost_mode:
        return True
    data = _load_budget()
    return bool(data.get('low_cost_mode')) or is_budget_exceeded()


def is_claude_allowed(force: bool = False) -> bool:
    if force:
        return not is_budget_exceeded()
    if is_low_cost_mode():
        print('[LOW COST MODE] Claude disabled — budget protection active')
        return False
    return not is_budget_exceeded()


def record_cost(amount: float, model: str, use_case: str, provider: str = ''):
    """Record estimated cost and flip low-cost mode if needed."""
    global _low_cost_mode, _budget_warned_today
    amount = float(amount or 0)
    data = _load_budget()
    data['total_cost'] = round(float(data.get('total_cost') or 0) + amount, 4)
    calls = data.get('calls') or []
    calls.append({
        'time': datetime.now(timezone.utc).isoformat(),
        'model': model,
        'use_case': use_case,
        'provider': provider,
        'cost': round(amount, 4),
    })
    data['calls'] = calls[-100:]

    if data['total_cost'] >= MAX_DAILY_AI_COST:
        data['low_cost_mode'] = True
        _low_cost_mode = True
        print(f"[LOW COST MODE] Daily budget ${MAX_DAILY_AI_COST:.2f} exceeded "
              f"(spent ${data['total_cost']:.2f})")
        if not _budget_warned_today:
            _send_budget_telegram(
                f"Daily AI budget ${MAX_DAILY_AI_COST:.2f} exceeded. "
                f"Spent ${data['total_cost']:.2f}. Gemini-only mode until UTC midnight."
            )
            _budget_warned_today = True
    else:
        print(f"[AI COST] +${amount:.4f} ({model}/{use_case}) "
              f"today=${data['total_cost']:.4f}/${MAX_DAILY_AI_COST:.2f}")

    _save_budget(data)


def budget_status() -> dict:
    data = _load_budget()
    return {
        'date': data.get('date'),
        'spent': round(float(data.get('total_cost') or 0), 4),
        'limit': MAX_DAILY_AI_COST,
        'remaining': round(max(0, MAX_DAILY_AI_COST - float(data.get('total_cost') or 0)), 4),
        'low_cost_mode': is_low_cost_mode(),
        'claude_allowed': is_claude_allowed(),
    }


def _send_budget_telegram(message: str):
    from backend.utils.telegram_guard import guard_telegram_send
    if not guard_telegram_send('ai_budget_manager'):
        return

    token = get_env('TELEGRAM_BOT_TOKEN')
    chat_id = get_env('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        return
    try:
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(
            url,
            json={'chat_id': chat_id, 'text': f'⚠️ AI BUDGET: {message}'},
            timeout=10,
        )
    except Exception as e:
        print(f"[AI COST] Telegram alert failed: {e}")
