"""AI confirmation gate for live alerts.

This module only decides whether an AI confirmation is warranted. It never calls
Claude, Gemini, Groq, or any provider.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

from backend.storage.data_paths import get_data_path
from backend.storage.json_io import atomic_write_json

STATE_FILE = get_data_path('ai_confirmation_gate_state.json')
DEFAULT_COOLDOWN_SECONDS = int(os.environ.get('AI_CONFIRMATION_MIN_COOLDOWN_SECONDS', '900'))


def _now_iso() -> str:
    return datetime.now().isoformat()


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.is_file():
        return {'last': {}, 'updated_at': None}
    try:
        import json

        data = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {'last': {}, 'updated_at': None}
    except Exception:
        return {'last': {}, 'updated_at': None}


def _save_state(state: dict[str, Any]) -> None:
    state['updated_at'] = _now_iso()
    atomic_write_json(STATE_FILE, state)


def _timestamp_unix(value: object) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return dt.timestamp()
    except Exception:
        return 0.0


def _ticker(value: object) -> str:
    return str(value or '').strip().upper()


def _score(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _has_direct_catalyst(event: dict[str, Any]) -> bool:
    if event.get('direct_catalyst') or event.get('fresh_news_match'):
        return True
    for key in ('news', 'my_feed', 'broker', 'direct_confirms'):
        rows = event.get(key) or []
        if isinstance(rows, dict):
            rows = [rows]
        if isinstance(rows, list) and rows:
            return True
    return False


def evaluate_ai_confirmation_gate(
    event: dict[str, Any] | None,
    *,
    cooldown_seconds: int | None = None,
    urgent: bool = False,
    record: bool = True,
) -> dict[str, Any]:
    """Return a decision for whether AI confirmation should run."""
    ev = event if isinstance(event, dict) else {}
    ticker = _ticker(ev.get('ticker') or ev.get('symbol') or ev.get('top_ticker'))
    cooldown = int(cooldown_seconds if cooldown_seconds is not None else DEFAULT_COOLDOWN_SECONDS)
    state = _load_state()
    last_all = state.setdefault('last', {})
    prev = last_all.get(ticker or 'global') or {}
    now = time.time()

    material_reasons: list[str] = []
    prev_ticker = _ticker(prev.get('ticker'))
    if ticker and ticker != prev_ticker:
        material_reasons.append('new_top_candidate')

    prev_score = _score(prev.get('score'))
    score = _score(ev.get('score') or ev.get('confidence_score') or ev.get('confidence'))
    if abs(score - prev_score) >= 10:
        material_reasons.append('score_delta')

    direct_now = _has_direct_catalyst(ev)
    direct_prev = bool(prev.get('direct_catalyst'))
    if direct_now and not direct_prev:
        material_reasons.append('new_direct_catalyst')

    avoid_now = bool(ev.get('avoid') or ev.get('avoid_flip') or str(ev.get('action') or '').upper() == 'AVOID')
    avoid_prev = bool(prev.get('avoid'))
    if avoid_now != avoid_prev:
        material_reasons.append('avoid_flip')

    if ev.get('fresh_news_match'):
        material_reasons.append('fresh_news_match')

    material = bool(material_reasons)
    last_ai_at = _timestamp_unix(
        prev.get('last_ai_confirmation_unix')
        or prev.get('last_ai_confirmation_at')
    )
    elapsed = now - last_ai_at if last_ai_at else None
    if material and not urgent and elapsed is not None and elapsed < cooldown:
        reason = 'cooldown'
        print(f'[AI_CONFIRMATION_GATE] skipped reason={reason}', flush=True)
        return {
            'should_run_ai': False,
            'skipped': True,
            'reason': reason,
            'material_change': True,
            'material_reasons': material_reasons,
            'cooldown_seconds': cooldown,
            'elapsed_seconds': int(elapsed),
        }

    if not material:
        reason = 'no_material_change'
        print(f'[AI_CONFIRMATION_GATE] skipped reason={reason}', flush=True)
        if record and ticker:
            last_all[ticker] = {
                **prev,
                'ticker': ticker,
                'score': score,
                'direct_catalyst': direct_now,
                'avoid': avoid_now,
                'last_seen_at': _now_iso(),
            }
            _save_state(state)
        return {
            'should_run_ai': False,
            'skipped': True,
            'reason': reason,
            'material_change': False,
            'material_reasons': [],
            'cooldown_seconds': cooldown,
        }

    if record and ticker:
        last_all[ticker] = {
            'ticker': ticker,
            'score': score,
            'direct_catalyst': direct_now,
            'avoid': avoid_now,
            'last_seen_at': _now_iso(),
            'last_ai_confirmation_at': _now_iso(),
            'last_ai_confirmation_unix': now,
            'last_material_reasons': material_reasons,
        }
        _save_state(state)
    return {
        'should_run_ai': True,
        'skipped': False,
        'reason': 'material_change',
        'material_change': True,
        'material_reasons': material_reasons,
        'cooldown_seconds': cooldown,
    }
