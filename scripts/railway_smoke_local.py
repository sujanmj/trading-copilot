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

os.environ.setdefault('LOCAL_DEV_MODE', '1')
os.environ.setdefault('LOCAL_ONLY', '1')
os.environ.setdefault('DISABLE_TRADE_EXECUTION', '1')
os.environ.setdefault('TELEGRAM_TRADE_COMMANDS_ENABLED', '0')
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_LISTENER', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')

RAILWAY_SCRIPTS = (
    'scripts/run_railway_web.py',
    'scripts/run_railway_telegram_worker.py',
    'scripts/run_railway_morning_brief.py',
    'scripts/run_railway_market_close.py',
    'scripts/run_railway_overnight_brief.py',
)


def _fail(msg: str) -> int:
    print(f'RAILWAY_SMOKE_LOCAL_FAIL: {msg}', file=sys.stderr)
    return 1


def _import_module_from_path(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot load {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    checks = (
        ('runner_imports', _check_runner_imports),
        ('health_route', _check_health_route),
        ('data_path_writable', _check_data_path_writable),
        ('telegram_dry_run', _check_telegram_dry_run),
        ('stock_decision_engine', _check_stock_decision_engine),
    )

    for name, fn in checks:
        err = fn()
        status = 'ok' if err is None else 'fail'
        print(f'[RAILWAY_SMOKE] {name}={status}')
        if err:
            return _fail(err)

    print(STAGE_MARKER)
    print('RAILWAY_SMOKE_LOCAL_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
