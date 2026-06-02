#!/usr/bin/env python3
"""
Live API + GUI smoke test (Stage 42).

Usage:
  python scripts/live_system_smoke.py
  python scripts/live_system_smoke.py --frontend-mode auto
  python scripts/live_system_smoke.py --frontend-mode electron
  python scripts/live_system_smoke.py --skip-frontend
  python scripts/live_system_smoke.py --api-base http://127.0.0.1:8080 --json

Requires backend running (e.g. python run_local.py). Does not place trades,
send Telegram, mutate Railway, or write canonical outcomes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import urljoin, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

DEFAULT_API_BASE = 'http://127.0.0.1:8080'
DEFAULT_FRONTEND_BASE = 'http://127.0.0.1:5173'
FRONTEND_DIR = PROJECT_ROOT / 'frontend'
FRONTEND_PACKAGE_JSON = FRONTEND_DIR / 'package.json'
FRONTEND_SOURCE_EXTENSIONS = ('.js', '.html', '.jsx', '.ts', '.tsx')

FrontendMode = Literal['auto', 'web', 'electron', 'skip']

CRITICAL_ENDPOINTS = (
    '/api/health',
    '/api/runtime/snapshot',
    '/api/debug/final-confidence',
    '/api/debug/tomorrow-watchlist',
    '/api/debug/daily-report-pack',
)

OPTIONAL_ENDPOINTS = (
    '/api/debug/market-router',
    '/api/debug/source-freshness',
    '/api/debug/market-memory',
    '/api/debug/market-memory/dashboard',
    '/api/debug/broker-intelligence',
    '/api/debug/external-source-coverage',
)

FRONTEND_MARKERS = (
    'Final Confidence',
    'Tomorrow Watchlist',
    'Daily Report Pack',
    'External Evidence',
    'Market Memory',
)

FetchFn = Callable[[str, dict[str, str], float], 'HttpResponse']


@dataclass
class HttpResponse:
    status: int
    body: str
    error: str | None = None

    def json(self) -> dict | list | None:
        try:
            return json.loads(self.body)
        except Exception:
            return None


@dataclass
class SmokeResult:
    backend: str = 'fail'
    runtime_snapshot: str = 'fail'
    final_confidence: str = 'fail'
    tomorrow_watchlist: str = 'fail'
    daily_pack: str = 'fail'
    frontend: str = 'fail'
    frontend_mode: str = 'web'
    electron_package: str = 'skip'
    electron_markers: str = 'skip'
    electron_process: str = 'skip'
    telegram_send_only: str = 'disabled'
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    payloads: dict[str, dict | list | None] = field(default_factory=dict)

    def ok(self) -> bool:
        core = (
            self.backend,
            self.runtime_snapshot,
            self.final_confidence,
            self.tomorrow_watchlist,
            self.daily_pack,
        )
        if any(part != 'ok' for part in core):
            return False
        if self.frontend not in ('ok', 'skipped'):
            return False
        return not self.errors


def _fail_token(msg: str) -> None:
    print(f'LIVE_SYSTEM_SMOKE_FAIL: {msg}', file=sys.stderr)


def _apply_local_defaults() -> None:
    for key, val in {
        'LOCAL_DEV_MODE': '1',
        'LOCAL_ONLY': '1',
        'DISABLE_TELEGRAM': '1',
        'DISABLE_TELEGRAM_LISTENER': '1',
        'DISABLE_TELEGRAM_SENDS': '1',
        'DISABLE_RAILWAY_API': '1',
    }.items():
        os.environ[key] = val


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, '').strip() in ('1', 'true', 'True', 'yes', 'YES')


def _load_api_key() -> str:
    key = os.environ.get('API_KEY', '').strip()
    if key:
        return key
    try:
        from backend.utils.config import get_env, load_env

        load_env()
        return get_env('API_KEY')
    except Exception:
        return ''


def default_fetch(url: str, headers: dict[str, str], timeout: float = 20.0) -> HttpResponse:
    req = urllib.request.Request(url, headers=headers, method='GET')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode('utf-8', errors='replace')
            return HttpResponse(status=int(resp.status), body=body)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode('utf-8', errors='replace')
        except Exception:
            body = ''
        return HttpResponse(status=int(exc.code), body=body, error=f'HTTP {exc.code}')
    except urllib.error.URLError as exc:
        reason = getattr(exc, 'reason', exc)
        return HttpResponse(status=0, body='', error=f'unreachable ({reason})')
    except Exception as exc:
        return HttpResponse(status=0, body='', error=str(exc))


def _api_headers(api_key: str) -> dict[str, str]:
    headers = {'Accept': 'application/json'}
    if api_key:
        headers['X-API-Key'] = api_key
    return headers


def _fetch_json(
    fetch: FetchFn,
    base: str,
    path: str,
    headers: dict[str, str],
    *,
    timeout: float = 20.0,
) -> HttpResponse:
    url = base.rstrip('/') + path
    return fetch(url, headers, timeout)


def _check_telegram_send_only() -> str:
    """ok/warn/disabled — does not require Telegram sends to be enabled."""
    try:
        from backend.notifications.local_telegram_notifier import telegram_notifications_enabled

        status = telegram_notifications_enabled()
        if status.get('enabled'):
            if not status.get('listener_disabled'):
                return 'warn'
            return 'ok'
        if status.get('local_notifications_flag') or status.get('sends_allowed_flag'):
            return 'warn'
        return 'disabled'
    except Exception:
        return 'warn'


def _check_local_safety_env() -> str | None:
    _apply_local_defaults()
    if not (_env_truthy('LOCAL_ONLY') or _env_truthy('LOCAL_DEV_MODE')):
        return 'LOCAL_ONLY and LOCAL_DEV_MODE both unset'
    for flag in ('DISABLE_TELEGRAM', 'DISABLE_TELEGRAM_LISTENER', 'DISABLE_TELEGRAM_SENDS'):
        if not _env_truthy(flag):
            return f'{flag} != 1'
    try:
        from backend.utils import config as cfg
        from backend.utils import telegram_guard as tg

        if not (cfg.LOCAL_ONLY or cfg.IS_LOCAL_DEV):
            return 'config LOCAL_ONLY/IS_LOCAL_DEV not set'
        if tg.is_telegram_send_enabled() or tg.is_telegram_listener_enabled():
            return 'telegram_guard reports Telegram enabled'
        if cfg.IS_RAILWAY:
            return 'IS_RAILWAY unexpectedly True'
    except Exception as exc:
        return f'config import: {exc}'
    return None


def _validate_config_payload(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return 'config response not a dict'
    if payload.get('railway') is True:
        return 'backend reports railway=true'
    if payload.get('local_dev') is not True:
        return 'backend local_dev != true'
    return None


def _validate_health_payload(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return 'health response not a dict'
    status = str(payload.get('status') or '')
    if status not in ('ok', 'degraded'):
        return f'health status={status!r}'
    orchestrator = payload.get('orchestrator') or {}
    if isinstance(orchestrator, dict):
        if orchestrator.get('local_dev') is False and payload.get('railway') is not True:
            return 'health orchestrator.local_dev is false'
    return None


def _validate_runtime_snapshot(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return 'runtime snapshot not a dict'
    if payload.get('ok') is False and payload.get('status') == 'warming_up':
        return 'runtime snapshot warming up'
    return None


def _validate_final_confidence(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return 'final confidence not a dict'
    if payload.get('ok') is not True:
        return payload.get('error') or 'ok != true'
    body = payload.get('report') if isinstance(payload.get('report'), dict) else payload
    active_mode = str(body.get('active_mode') or payload.get('active_mode') or 'RESEARCH_MODE')
    summary = payload.get('summary') or body.get('summary') or {}
    buy = int(summary.get('buy_candidate') or 0)
    if active_mode == 'RESEARCH_MODE' and buy > 0:
        return 'RESEARCH_MODE summary.buy_candidate > 0'
    rows = body.get('rows') or payload.get('rows') or []
    for row in rows:
        if not isinstance(row, dict):
            continue
        decision = str(row.get('decision') or '').upper()
        if active_mode == 'RESEARCH_MODE' and decision == 'BUY_CANDIDATE':
            return f'RESEARCH_MODE row {row.get("ticker")} has BUY_CANDIDATE'
    return None


def _validate_shadow_payload(payload: dict | None, *, label: str) -> str | None:
    if not isinstance(payload, dict):
        return f'{label} not a dict'
    if payload.get('ok') is not True:
        return payload.get('error') or f'{label} ok != true'
    if payload.get('shadow_mode') is not True:
        return f'{label} shadow_mode != true'
    return None


def _collect_frontend_corpus(
    fetch: FetchFn,
    frontend_base: str,
    headers: dict[str, str],
) -> tuple[str, str | None]:
    root_resp = fetch(frontend_base.rstrip('/') + '/', headers, 15.0)
    if root_resp.status == 0:
        return '', root_resp.error or 'frontend unreachable'
    if root_resp.status >= 400:
        return '', f'frontend HTTP {root_resp.status}'

    corpus = root_resp.body
    script_srcs = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', corpus, flags=re.IGNORECASE)
    parsed = urlparse(frontend_base)
    for src in script_srcs:
        if src.startswith('http://') or src.startswith('https://'):
            script_url = src
        else:
            script_url = urljoin(f'{parsed.scheme}://{parsed.netloc}/', src.lstrip('/'))
        script_resp = fetch(script_url, headers, 15.0)
        if script_resp.status and script_resp.status < 400:
            corpus += '\n' + script_resp.body
    return corpus, None


def _check_frontend_markers(corpus: str) -> list[str]:
    missing = [marker for marker in FRONTEND_MARKERS if marker not in corpus]
    return missing


def _frontend_base_reachable(fetch: FetchFn, frontend_base: str) -> bool:
    url = frontend_base.rstrip('/') + '/'
    try:
        resp = fetch(url, {'Accept': 'text/html,application/xhtml+xml'}, 5.0)
        return resp.status == 200
    except Exception:
        return False


def _resolve_auto_frontend_mode(
    *,
    fetch: FetchFn | None = None,
    frontend_base: str = DEFAULT_FRONTEND_BASE,
) -> FrontendMode:
    if fetch and _frontend_base_reachable(fetch, frontend_base):
        return 'web'

    pkg, _err = _load_frontend_package()
    if pkg:
        start = str((pkg.get('scripts') or {}).get('start') or '')
        if 'electron' in start.lower():
            return 'electron'

    raise ValueError('auto frontend mode: web port unreachable and electron package unavailable')


def _resolve_frontend_mode(
    *,
    skip_frontend: bool,
    frontend_mode: str | None,
    fetch: FetchFn | None = None,
    frontend_base: str = DEFAULT_FRONTEND_BASE,
) -> FrontendMode:
    if skip_frontend:
        return 'skip'
    mode = (frontend_mode or 'auto').strip().lower()
    if mode == 'auto':
        return _resolve_auto_frontend_mode(fetch=fetch, frontend_base=frontend_base)
    if mode in ('web', 'electron', 'skip'):
        return mode  # type: ignore[return-value]
    raise ValueError(f'invalid frontend_mode: {frontend_mode!r}')


def _load_frontend_package() -> tuple[dict | None, str | None]:
    if not FRONTEND_PACKAGE_JSON.is_file():
        return None, 'frontend/package.json missing'
    try:
        pkg = json.loads(FRONTEND_PACKAGE_JSON.read_text(encoding='utf-8'))
    except Exception as exc:
        return None, f'package.json parse error: {exc}'
    if not isinstance(pkg, dict):
        return None, 'package.json root is not an object'
    return pkg, None


def _resolve_electron_entry(pkg: dict) -> Path | None:
    main = str(pkg.get('main') or 'main.js').strip() or 'main.js'
    entry = FRONTEND_DIR / main
    if entry.is_file():
        return entry
    fallback = FRONTEND_DIR / 'main.js'
    if fallback.is_file():
        return fallback
    return None


def _scan_electron_source_corpus() -> str:
    parts: list[str] = []
    if not FRONTEND_DIR.is_dir():
        return ''
    for path in sorted(FRONTEND_DIR.rglob('*')):
        if not path.is_file() or path.suffix.lower() not in FRONTEND_SOURCE_EXTENSIONS:
            continue
        try:
            parts.append(path.read_text(encoding='utf-8', errors='replace'))
        except Exception:
            continue
    return '\n'.join(parts)


def _check_electron_process() -> tuple[str, str | None]:
    if sys.platform != 'win32':
        return 'ok', None
    try:
        proc = subprocess.run(
            ['tasklist', '/FI', 'IMAGENAME eq electron.exe', '/NH'],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0 and 'electron.exe' in proc.stdout.lower():
            return 'ok', None
        return 'warn', 'electron process not detected'
    except Exception as exc:
        return 'warn', f'electron process check failed: {exc}'


def _run_electron_frontend_check(result: SmokeResult) -> None:
    result.frontend_mode = 'electron'
    result.electron_package = 'fail'
    result.electron_markers = 'fail'
    result.electron_process = 'skip'

    pkg, pkg_err = _load_frontend_package()
    if pkg_err:
        result.errors.append(f'electron_package: {pkg_err}')
        return

    start = str((pkg.get('scripts') or {}).get('start') or '')
    if 'electron' not in start.lower():
        result.errors.append('electron_package: start script does not contain electron')
        return

    entry = _resolve_electron_entry(pkg)
    if entry is None:
        main = str(pkg.get('main') or 'main.js')
        result.errors.append(f'electron_package: entry file missing ({main})')
        return

    result.electron_package = 'ok'

    corpus = _scan_electron_source_corpus()
    missing = _check_frontend_markers(corpus)
    if missing:
        result.errors.append(f'electron_markers missing: {", ".join(missing)}')
        return

    result.electron_markers = 'ok'

    proc_status, proc_msg = _check_electron_process()
    result.electron_process = proc_status
    if proc_status == 'warn' and proc_msg:
        result.warnings.append(f'electron_process: {proc_msg}')

    result.frontend = 'ok'


def run_live_system_smoke(
    *,
    api_base: str = DEFAULT_API_BASE,
    frontend_base: str = DEFAULT_FRONTEND_BASE,
    skip_frontend: bool = False,
    frontend_mode: str | None = None,
    fetch: FetchFn | None = None,
    api_key: str | None = None,
) -> SmokeResult:
    result = SmokeResult()
    fetch = fetch or default_fetch

    try:
        effective_frontend_mode = _resolve_frontend_mode(
            skip_frontend=skip_frontend,
            frontend_mode=frontend_mode,
            fetch=fetch,
            frontend_base=frontend_base,
        )
    except ValueError as exc:
        result.errors.append(str(exc))
        return result

    result.frontend_mode = effective_frontend_mode

    safety_err = _check_local_safety_env()
    if safety_err:
        result.errors.append(f'local_safety: {safety_err}')
        return result

    result.telegram_send_only = _check_telegram_send_only()
    if result.telegram_send_only == 'ok' and not _env_truthy('DISABLE_TELEGRAM_LISTENER'):
        result.warnings.append('telegram_send_only: listener not explicitly disabled')

    api_key = _load_api_key() if api_key is None else api_key
    headers = _api_headers(api_key)
    plain_headers = {'Accept': 'text/html,application/xhtml+xml'}

    health_resp = _fetch_json(fetch, api_base, '/api/health', headers)
    if health_resp.status == 0:
        result.errors.append(f'backend unreachable: {health_resp.error}')
        return result
    if health_resp.status != 200:
        result.errors.append(f'/api/health HTTP {health_resp.status}')
        return result

    health_payload = health_resp.json()
    result.payloads['/api/health'] = health_payload if isinstance(health_payload, dict) else None
    health_err = _validate_health_payload(health_payload if isinstance(health_payload, dict) else None)
    if health_err:
        result.errors.append(f'health: {health_err}')
        return result

    config_resp = _fetch_json(fetch, api_base, '/api/config', headers)
    if config_resp.status == 200:
        config_payload = config_resp.json()
        result.payloads['/api/config'] = config_payload if isinstance(config_payload, dict) else None
        config_err = _validate_config_payload(config_payload if isinstance(config_payload, dict) else None)
        if config_err:
            result.errors.append(f'config: {config_err}')
            return result
    else:
        result.warnings.append(f'/api/config HTTP {config_resp.status} (optional)')

    result.backend = 'ok'

    snapshot_resp = _fetch_json(fetch, api_base, '/api/runtime/snapshot', headers)
    snapshot_payload = snapshot_resp.json() if snapshot_resp.body else None
    result.payloads['/api/runtime/snapshot'] = snapshot_payload if isinstance(snapshot_payload, dict) else None
    if snapshot_resp.status != 200:
        result.errors.append(f'/api/runtime/snapshot HTTP {snapshot_resp.status}')
    else:
        snap_err = _validate_runtime_snapshot(snapshot_payload if isinstance(snapshot_payload, dict) else None)
        if snap_err:
            result.errors.append(f'runtime_snapshot: {snap_err}')
        else:
            result.runtime_snapshot = 'ok'

    fc_resp = _fetch_json(fetch, api_base, '/api/debug/final-confidence', headers)
    fc_payload = fc_resp.json() if fc_resp.body else None
    result.payloads['/api/debug/final-confidence'] = fc_payload if isinstance(fc_payload, dict) else None
    if fc_resp.status != 200:
        result.errors.append(f'/api/debug/final-confidence HTTP {fc_resp.status}')
    else:
        fc_err = _validate_final_confidence(fc_payload if isinstance(fc_payload, dict) else None)
        if fc_err:
            result.errors.append(f'final_confidence: {fc_err}')
        else:
            result.final_confidence = 'ok'

    tw_resp = _fetch_json(fetch, api_base, '/api/debug/tomorrow-watchlist', headers)
    tw_payload = tw_resp.json() if tw_resp.body else None
    result.payloads['/api/debug/tomorrow-watchlist'] = tw_payload if isinstance(tw_payload, dict) else None
    if tw_resp.status != 200:
        result.errors.append(f'/api/debug/tomorrow-watchlist HTTP {tw_resp.status}')
    else:
        tw_err = _validate_shadow_payload(tw_payload if isinstance(tw_payload, dict) else None, label='tomorrow_watchlist')
        if tw_err:
            result.errors.append(f'tomorrow_watchlist: {tw_err}')
        else:
            result.tomorrow_watchlist = 'ok'

    dp_resp = _fetch_json(fetch, api_base, '/api/debug/daily-report-pack', headers)
    dp_payload = dp_resp.json() if dp_resp.body else None
    result.payloads['/api/debug/daily-report-pack'] = dp_payload if isinstance(dp_payload, dict) else None
    if dp_resp.status != 200:
        result.errors.append(f'/api/debug/daily-report-pack HTTP {dp_resp.status}')
    else:
        dp_err = _validate_shadow_payload(dp_payload if isinstance(dp_payload, dict) else None, label='daily_report_pack')
        if dp_err:
            result.errors.append(f'daily_pack: {dp_err}')
        else:
            result.daily_pack = 'ok'

    for path in OPTIONAL_ENDPOINTS:
        opt_resp = _fetch_json(fetch, api_base, path, headers)
        if opt_resp.status != 200:
            result.warnings.append(f'{path} HTTP {opt_resp.status or opt_resp.error}')

    if effective_frontend_mode == 'skip':
        result.frontend = 'skipped'
    elif effective_frontend_mode == 'electron':
        _run_electron_frontend_check(result)
    else:
        result.frontend_mode = 'web'
        corpus, front_err = _collect_frontend_corpus(fetch, frontend_base, plain_headers)
        if front_err:
            result.errors.append(f'frontend: {front_err}')
        else:
            missing = _check_frontend_markers(corpus)
            if missing:
                result.errors.append(f'frontend missing markers: {", ".join(missing)}')
            else:
                result.frontend = 'ok'

    return result


def print_smoke_result(result: SmokeResult, *, as_json: bool = False) -> None:
    if as_json:
        payload = {
            'backend': result.backend,
            'runtime_snapshot': result.runtime_snapshot,
            'final_confidence': result.final_confidence,
            'tomorrow_watchlist': result.tomorrow_watchlist,
            'daily_pack': result.daily_pack,
            'frontend': result.frontend,
            'frontend_mode': result.frontend_mode,
            'electron_package': result.electron_package,
            'electron_markers': result.electron_markers,
            'electron_process': result.electron_process,
            'telegram_send_only': result.telegram_send_only,
            'ok': result.ok(),
            'errors': result.errors,
            'warnings': result.warnings,
        }
        print(json.dumps(payload, indent=2))
        return

    print(f'[LIVE_SMOKE] backend={result.backend}')
    print(f'[LIVE_SMOKE] runtime_snapshot={result.runtime_snapshot}')
    print(f'[LIVE_SMOKE] final_confidence={result.final_confidence}')
    print(f'[LIVE_SMOKE] tomorrow_watchlist={result.tomorrow_watchlist}')
    print(f'[LIVE_SMOKE] daily_pack={result.daily_pack}')
    if result.frontend_mode == 'electron':
        print(f'[LIVE_SMOKE] frontend_mode=electron')
        print(f'[LIVE_SMOKE] electron_package={result.electron_package}')
        print(f'[LIVE_SMOKE] electron_markers={result.electron_markers}')
        print(f'[LIVE_SMOKE] electron_process={result.electron_process}')
    elif result.frontend_mode != 'skip':
        print(f'[LIVE_SMOKE] frontend_mode={result.frontend_mode}')
    print(f'[LIVE_SMOKE] frontend={result.frontend}')
    print(f'[LIVE_SMOKE] telegram_send_only={result.telegram_send_only}')
    for warning in result.warnings:
        print(f'[LIVE_SMOKE] warn: {warning}', file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Live API + GUI smoke test')
    parser.add_argument('--api-base', default=DEFAULT_API_BASE)
    parser.add_argument('--frontend-base', default=DEFAULT_FRONTEND_BASE)
    parser.add_argument(
        '--frontend-mode',
        choices=('auto', 'web', 'electron', 'skip'),
        default='auto',
        help='auto: detect from frontend/package.json; web: HTTP; electron: desktop GUI files',
    )
    parser.add_argument(
        '--skip-frontend',
        action='store_true',
        help='Skip frontend checks (equivalent to --frontend-mode skip)',
    )
    parser.add_argument('--json', action='store_true', dest='as_json')
    args = parser.parse_args(argv)

    frontend_mode = 'skip' if args.skip_frontend else args.frontend_mode

    result = run_live_system_smoke(
        api_base=args.api_base,
        frontend_base=args.frontend_base,
        skip_frontend=args.skip_frontend,
        frontend_mode=frontend_mode,
    )
    print_smoke_result(result, as_json=args.as_json)

    if result.ok():
        if not args.as_json:
            print('LIVE_SYSTEM_SMOKE_OK')
        return 0

    for err in result.errors:
        _fail_token(err)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
