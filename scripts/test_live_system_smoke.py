#!/usr/bin/env python3
"""
Unit tests for live system smoke (Stage 42) with mocked HTTP.

Usage:
  python scripts/test_live_system_smoke.py

Prints LIVE_SYSTEM_SMOKE_TEST_OK on success.
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
    print(f'LIVE_SYSTEM_SMOKE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def _good_payloads() -> dict[str, dict]:
    from scripts.validate_live_system_smoke import _good_payloads as base

    return dict(base())


def _route_fetch(payloads: dict[str, dict], *, frontend_html: str = ''):
    from scripts.live_system_smoke import HttpResponse
    from urllib.parse import urlparse

    def _fetch(url: str, headers: dict[str, str], timeout: float = 20.0) -> HttpResponse:
        path = urlparse(url).path or '/'
        if path == '/':
            return HttpResponse(status=200, body=frontend_html or _frontend_corpus())
        if path in payloads:
            return HttpResponse(status=200, body=json.dumps(payloads[path]))
        return HttpResponse(status=404, body='')

    return _fetch


def _frontend_corpus() -> str:
    parts = [
        (PROJECT_ROOT / 'frontend' / 'index.html').read_text(encoding='utf-8'),
        (PROJECT_ROOT / 'frontend' / 'components' / 'FinalConfidencePanel.js').read_text(encoding='utf-8'),
        (PROJECT_ROOT / 'frontend' / 'components' / 'DailyReportPackPanel.js').read_text(encoding='utf-8'),
        (PROJECT_ROOT / 'frontend' / 'components' / 'MarketMemoryPanel.js').read_text(encoding='utf-8'),
    ]
    return '\n'.join(parts)


def main() -> int:
    from scripts.live_system_smoke import run_live_system_smoke

    good = _good_payloads()

    # All pass (web mode with mocked HTTP frontend)
    all_pass = run_live_system_smoke(
        frontend_mode='web',
        skip_frontend=False,
        fetch=_route_fetch(good),
    )
    if not all_pass.ok():
        return _fail(f'all-pass: {" | ".join(all_pass.errors)}')
    if all_pass.frontend != 'ok':
        return _fail(f'all-pass frontend={all_pass.frontend}')

    # Electron mode passes without web port
    electron = run_live_system_smoke(
        frontend_mode='electron',
        skip_frontend=False,
        fetch=_route_fetch(good),
    )
    if not electron.ok():
        return _fail(f'electron mode: {" | ".join(electron.errors)}')
    if electron.frontend != 'ok':
        return _fail(f'electron mode frontend={electron.frontend}')
    if electron.frontend_mode != 'electron':
        return _fail(f'electron mode frontend_mode={electron.frontend_mode}')
    if electron.electron_package != 'ok' or electron.electron_markers != 'ok':
        return _fail('electron mode package/markers not ok')

    def _frontend_down_fetch(url: str, headers: dict[str, str], timeout: float = 20.0):
        from scripts.live_system_smoke import HttpResponse
        from urllib.parse import urlparse

        path = urlparse(url).path or '/'
        if path == '/':
            return HttpResponse(status=0, body='', error='connection refused')
        if path in good:
            return HttpResponse(status=200, body=json.dumps(good[path]))
        return HttpResponse(status=404, body='')

    # Auto detects web when frontend port reachable
    auto_web = run_live_system_smoke(
        frontend_mode='auto',
        skip_frontend=False,
        fetch=_route_fetch(good),
    )
    if not auto_web.ok():
        return _fail(f'auto web mode: {" | ".join(auto_web.errors)}')
    if auto_web.frontend_mode != 'web':
        return _fail(f'auto should detect web when port reachable, got {auto_web.frontend_mode}')

    # Auto detects electron when web port unreachable
    auto_electron = run_live_system_smoke(
        frontend_mode='auto',
        skip_frontend=False,
        fetch=_frontend_down_fetch,
    )
    if not auto_electron.ok():
        return _fail(f'auto electron mode: {" | ".join(auto_electron.errors)}')
    if auto_electron.frontend_mode != 'electron':
        return _fail(f'auto should detect electron when web down, got {auto_electron.frontend_mode}')

    # Web mode fails if frontend port unreachable
    web_down = run_live_system_smoke(
        frontend_mode='web',
        skip_frontend=False,
        fetch=_frontend_down_fetch,
    )
    if web_down.ok():
        return _fail('web mode with unreachable frontend should fail')
    if web_down.frontend != 'fail':
        return _fail('web mode unreachable should leave frontend=fail')
    if not any('frontend' in err for err in web_down.errors):
        return _fail('web mode unreachable missing frontend error')

    # Backend down
    def _down_fetch(url: str, headers: dict[str, str], timeout: float = 20.0):
        from scripts.live_system_smoke import HttpResponse

        return HttpResponse(status=0, body='', error='connection refused')

    down = run_live_system_smoke(skip_frontend=True, fetch=_down_fetch)
    if down.ok():
        return _fail('backend down should fail')
    if down.backend != 'fail':
        return _fail('backend down should leave backend=fail')
    if not any('unreachable' in err for err in down.errors):
        return _fail('backend down missing unreachable error')

    # BUY in RESEARCH_MODE
    bad_fc = dict(good)
    bad_fc['/api/debug/final-confidence'] = {
        'ok': True,
        'active_mode': 'RESEARCH_MODE',
        'shadow_mode': True,
        'summary': {'buy_candidate': 2, 'watch': 0, 'avoid': 0, 'no_decision': 0},
        'rows': [{'ticker': 'TCS', 'decision': 'BUY_CANDIDATE', 'final_score': 88}],
    }
    buy_fail = run_live_system_smoke(skip_frontend=True, fetch=_route_fetch(bad_fc))
    if buy_fail.ok():
        return _fail('BUY in RESEARCH_MODE should fail')
    if buy_fail.final_confidence != 'fail':
        return _fail('BUY in RESEARCH_MODE should leave final_confidence=fail')
    if not any('RESEARCH_MODE' in err for err in buy_fail.errors):
        return _fail('BUY in RESEARCH_MODE missing RESEARCH_MODE error')

    # Frontend skipped passes without frontend HTTP
    skipped = run_live_system_smoke(
        skip_frontend=True,
        frontend_mode='skip',
        fetch=_route_fetch(good),
    )
    if not skipped.ok():
        return _fail(f'skip-frontend: {" | ".join(skipped.errors)}')
    if skipped.frontend != 'skipped':
        return _fail('skip-frontend should set frontend=skipped')

    print('LIVE_SYSTEM_SMOKE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
