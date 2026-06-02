#!/usr/bin/env python3
"""
Offline-safe validator for live system smoke (Stage 42).

Usage:
  python scripts/validate_live_system_smoke.py

Imports live_system_smoke with mocked HTTP and prints LIVE_SYSTEM_SMOKE_VALIDATE_OK.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'LIVE_SYSTEM_SMOKE_VALIDATE_FAIL: {msg}', file=sys.stderr)
    return 1


def _good_payloads() -> dict[str, dict]:
    return {
        '/api/health': {
            'status': 'ok',
            'railway': False,
            'orchestrator': {'local_dev': True, 'orchestrator_mode': 'LOCAL', 'runtime_healthy': True},
        },
        '/api/config': {
            'railway': False,
            'local_dev': True,
            'auth_required': False,
            'local_auth_bypass': True,
        },
        '/api/runtime/snapshot': {
            'ok': True,
            'status': 'ok',
            'snapshot_id': 'mock_snapshot',
            'generated_at': '2026-05-31T10:00:00',
            'data': {},
        },
        '/api/debug/final-confidence': {
            'ok': True,
            'active_mode': 'RESEARCH_MODE',
            'shadow_mode': True,
            'summary': {'buy_candidate': 0, 'watch': 2, 'avoid': 1, 'no_decision': 0},
            'rows': [
                {'ticker': 'RELIANCE', 'decision': 'WATCH', 'final_score': 62},
            ],
        },
        '/api/debug/tomorrow-watchlist': {
            'ok': True,
            'shadow_mode': True,
            'summary': {'count': 1},
            'top_watchlist': [],
            'avoid': [],
            'no_decision': [],
            'disclaimer': 'shadow only',
        },
        '/api/debug/daily-report-pack': {
            'ok': True,
            'shadow_mode': True,
            'final_confidence': {},
            'tomorrow_watchlist': {},
            'historical_simulation': {},
            'confidence_calibration': {},
        },
        '/api/debug/market-router': {'ok': True},
        '/api/debug/source-freshness': {'ok': True},
        '/api/debug/market-memory': {'ok': True},
        '/api/debug/market-memory/dashboard': {'ok': True, 'stats': {}},
        '/api/debug/broker-intelligence': {'ok': True},
        '/api/debug/external-source-coverage': {'ok': True},
    }


def _mock_fetch(url: str, headers: dict[str, str], timeout: float = 20.0):
    from scripts.live_system_smoke import HttpResponse
    from urllib.parse import urlparse

    path = urlparse(url).path or '/'
    if path == '/':
        html = PROJECT_ROOT / 'frontend' / 'index.html'
        panel = PROJECT_ROOT / 'frontend' / 'components' / 'FinalConfidencePanel.js'
        body = html.read_text(encoding='utf-8')
        if panel.is_file():
            body += '\n' + panel.read_text(encoding='utf-8')
        body += '\n' + (PROJECT_ROOT / 'frontend' / 'components' / 'DailyReportPackPanel.js').read_text(encoding='utf-8')
        return HttpResponse(status=200, body=body)

    if path.startswith('/components/') or path.startswith('/runtime/'):
        rel = path.lstrip('/')
        file_path = PROJECT_ROOT / 'frontend' / rel.replace('/', '\\')
        if not file_path.is_file():
            file_path = PROJECT_ROOT / 'frontend' / rel
        if file_path.is_file():
            return HttpResponse(status=200, body=file_path.read_text(encoding='utf-8'))
        return HttpResponse(status=404, body='')

    payloads = _good_payloads()
    if path in payloads:
        return HttpResponse(status=200, body=json.dumps(payloads[path]))

    return HttpResponse(status=404, body=json.dumps({'ok': False, 'error': 'not found'}))


def main() -> int:
    from scripts.live_system_smoke import run_live_system_smoke

    result = run_live_system_smoke(
        api_base='http://127.0.0.1:8080',
        frontend_base='http://127.0.0.1:5173',
        frontend_mode='auto',
        skip_frontend=False,
        fetch=_mock_fetch,
    )
    if not result.ok():
        return _fail(' | '.join(result.errors) or 'smoke not ok')
    if result.frontend != 'ok':
        return _fail(f'frontend={result.frontend}')

    print('LIVE_SYSTEM_SMOKE_VALIDATE_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
