#!/usr/bin/env python3
"""Ensure unauthenticated health summaries omit provider credentials/errors."""

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


def main() -> int:
    from backend.api import api_server

    secret = 'AIzaSyTEST_EXAMPLE_SECRET'
    payload = {
        'status': 'ok',
        'operational': {'market_hours': True},
        'provider_analytics': {
            'providers': {'gemini': {'status': 'degraded', 'last_error': f'https://example.test/?key={secret}'}},
            'requests_today': 12,
        },
        'provider_ops': {'env_diagnostics': {'masked': f'...{secret[-4:]}'}, 'degraded': True},
        'provider_message': f'upstream URL https://example.test/?key={secret}',
        'nested': [{'error': f'provider returned key={secret}', 'healthy': False}],
    }

    original_builder = api_server._build_health_payload
    try:
        api_server._build_health_payload = lambda: payload
        result = api_server.health()
    finally:
        api_server._build_health_payload = original_builder
    serialized = repr(result)
    assert result['status'] == 'ok'
    assert result['operational']['market_hours'] is True
    assert result['provider_analytics']['providers']['gemini']['status'] == 'degraded'
    assert result['provider_analytics']['requests_today'] == 12
    assert 'last_error' not in result['provider_analytics']['providers']['gemini']
    assert 'env_diagnostics' not in result['provider_ops']
    assert secret not in result['provider_message']
    assert '[REDACTED]' in result['provider_message']
    assert 'error' not in result['nested'][0]
    assert secret not in serialized
    print('PUBLIC_HEALTH_REDACTION_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
