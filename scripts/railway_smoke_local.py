#!/usr/bin/env python3
"""
Local Railway smoke checks without deploying (Stage 46A).

Usage:
  python scripts/railway_smoke_local.py

Prints RAILWAY_SMOKE_LOCAL_OK on success.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

STAGE_MARKER = 'RAILWAY_STAGE_46A_SMOKE_LOCAL'

os.environ.setdefault('RAILWAY_SMOKE_LOCAL', '1')
os.environ.setdefault('LOCAL_DEV_MODE', '1')
os.environ.setdefault('LOCAL_ONLY', '1')
os.environ.setdefault('DISABLE_TRADE_EXECUTION', '1')
os.environ.setdefault('TELEGRAM_TRADE_COMMANDS_ENABLED', '0')
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_LISTENER', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')
os.environ.setdefault('REFRESH_SCANNER_SAFE_SMOKE', '1')
os.environ.setdefault('SAFE_STDIO_FORCE_FD', '1')

from backend.utils.safe_stdio import configure_smoke_stdio, is_stream_usable, safe_print  # noqa: E402

configure_smoke_stdio()

RAILWAY_SCRIPTS = (
    'scripts/run_railway_web.py',
    'scripts/run_railway_telegram_worker.py',
    'scripts/run_railway_morning_brief.py',
    'scripts/run_railway_market_close.py',
    'scripts/run_railway_overnight_brief.py',
)


def _restore_smoke_stdio() -> None:
    if is_stream_usable(getattr(sys, '__stdout__', None)):
        sys.stdout = sys.__stdout__
    if is_stream_usable(getattr(sys, '__stderr__', None)):
        sys.stderr = sys.__stderr__


def _smoke_print(message: str, *, fallback: str = 'stdout') -> bool:
    _restore_smoke_stdio()
    return safe_print(message, fallback=fallback)


def _fail(msg: str) -> int:
    _smoke_print(f'RAILWAY_SMOKE_LOCAL_FAIL: {msg}', fallback='stderr')
    return 1


def _import_module_from_path(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot load {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check_api_server_import() -> str | None:
    try:
        from backend.api import api_server
    except Exception as exc:
        return f'api_server import failed: {exc}'
    if not hasattr(api_server, 'app'):
        return 'api_server.app missing after import'
    route_paths = {getattr(r, 'path', None) for r in api_server.app.routes}
    if '/api/myfeed' not in route_paths:
        return '/api/myfeed route missing after api_server import'
    return None


def _check_runner_imports() -> str | None:
    for rel in RAILWAY_SCRIPTS:
        path = PROJECT_ROOT / rel
        if not path.is_file():
            return f'missing {rel}'
        try:
            _import_module_from_path(f'railway_smoke_{path.stem}', path)
        except Exception as exc:
            return f'import failed {rel}: {exc}'
    return None


def _check_health_route() -> str | None:
    api_src = (PROJECT_ROOT / 'backend/api/api_server.py').read_text(encoding='utf-8')
    if '@app.get("/api/health")' not in api_src and "@app.get('/api/health')" not in api_src:
        return '/api/health route missing in api_server.py'
    return None


def _check_data_path_writable() -> str | None:
    from backend.storage.data_paths import get_data_path

    try:
        probe = get_data_path('.railway_smoke_probe')
        probe.write_text('ok', encoding='utf-8')
        probe.unlink(missing_ok=True)
    except OSError as exc:
        return f'data path not writable: {exc}'
    return None


def _short_reason(value: object, limit: int = 160) -> str:
    text = str(value or '').replace('\r', ' ').replace('\n', ' ').strip()
    if not text:
        return 'unknown'
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + '...'


def _check_scanner_refresh() -> str | None:
    try:
        from scripts.refresh_local_intelligence import SAFE_SMOKE_SCANNER_STATUS, run_refresh_scoped

        result = run_refresh_scoped('scanner', dry_run=False)
    except Exception as exc:
        return _short_reason(exc)

    if not isinstance(result, dict):
        return 'non-dict refresh result'

    status = result.get('scanner')
    if status in ('ok', 'skipped', SAFE_SMOKE_SCANNER_STATUS):
        return None
    if result.get('ok') is True and status is None:
        return 'missing scanner terminal status'
    if result.get('ok') is True and status != 'failed':
        return None
    reason = result.get('reason') or result.get('error') or status or result.get('warnings') or 'scanner refresh failed'
    return _short_reason(reason)


def _check_telegram_dry_run() -> str | None:
    from backend.telegram.telegram_brief_scheduler import (
        build_close_brief_text,
        build_morning_brief_text,
        build_overnight_brief_text,
    )

    for label, builder in (
        ('morning', build_morning_brief_text),
        ('close', build_close_brief_text),
        ('overnight', build_overnight_brief_text),
    ):
        try:
            text = builder()
        except Exception as exc:
            return f'{label} brief dry-run failed: {exc}'
        if not text or not str(text).strip():
            return f'{label} brief dry-run empty'
    return None


def _check_stock_decision_engine() -> str | None:
    from backend.analytics.stock_decision_engine import build_stock_decision

    try:
        payload = build_stock_decision(mode='today')
    except Exception as exc:
        return f'stock decision engine failed: {exc}'
    if not isinstance(payload, dict):
        return 'stock decision engine returned non-dict'
    if payload.get('ok') is not True:
        return f'stock decision engine ok != true: {payload.get("error")}'
    return None


def main() -> int:
    pre_scanner_checks = (
        ('api_server_import', _check_api_server_import),
        ('runner_imports', _check_runner_imports),
        ('health_route', _check_health_route),
        ('data_path_writable', _check_data_path_writable),
    )
    post_scanner_checks = (
        ('telegram_dry_run', _check_telegram_dry_run),
        ('stock_decision_engine', _check_stock_decision_engine),
    )

    for name, fn in pre_scanner_checks:
        err = fn()
        _restore_smoke_stdio()
        status = 'ok' if err is None else 'fail'
        _smoke_print(f'[RAILWAY_SMOKE] {name}={status}')
        if err:
            return _fail(err)

    _restore_smoke_stdio()
    scanner_warning = _check_scanner_refresh()
    _restore_smoke_stdio()
    if scanner_warning:
        _smoke_print(f'[RAILWAY_SMOKE] scanner_refresh=warning {_short_reason(scanner_warning)}')
    else:
        _smoke_print('[RAILWAY_SMOKE] scanner_refresh=ok')

    for name, fn in post_scanner_checks:
        err = fn()
        _restore_smoke_stdio()
        status = 'ok' if err is None else 'fail'
        _smoke_print(f'[RAILWAY_SMOKE] {name}={status}')
        if err:
            return _fail(err)

    _smoke_print(STAGE_MARKER)
    printed_ok = _smoke_print('RAILWAY_SMOKE_LOCAL_OK')
    return 0 if printed_ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
