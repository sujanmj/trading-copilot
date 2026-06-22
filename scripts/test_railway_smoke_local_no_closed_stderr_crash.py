#!/usr/bin/env python3
"""Regression test: railway_smoke_local survives closed stdout/stderr."""

from __future__ import annotations

import importlib
import io
import os
import sys
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

os.environ.setdefault('RAILWAY_SMOKE_LOCAL', '1')
os.environ.setdefault('LOCAL_DEV_MODE', '1')
os.environ.setdefault('LOCAL_ONLY', '1')

from backend.utils.safe_stdio import safe_print  # noqa: E402

MARKER = 'RAILWAY_SMOKE_LOCAL_NO_CLOSED_STDERR_CRASH_TEST_OK'


def _fail(msg: str) -> int:
    safe_print(f'RAILWAY_SMOKE_LOCAL_NO_CLOSED_STDERR_CRASH_TEST_FAIL: {msg}', fallback='stderr')
    return 1


def _assert_generativeai_future_warning_safe() -> str | None:
    try:
        import backend.ai.ai_router as ai_router
        with warnings.catch_warnings():
            warnings.simplefilter('error', FutureWarning)
            importlib.reload(ai_router)
    except FutureWarning as exc:
        return f'google.generativeai FutureWarning escaped: {exc}'
    except Exception:
        return None
    return None


def main() -> int:
    warning_err = _assert_generativeai_future_warning_safe()
    if warning_err:
        return _fail(warning_err)

    import scripts.railway_smoke_local as smoke

    check_names = (
        '_check_api_server_import',
        '_check_runner_imports',
        '_check_health_route',
        '_check_data_path_writable',
        '_check_telegram_dry_run',
        '_check_stock_decision_engine',
    )
    originals = {name: getattr(smoke, name) for name in check_names}
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    closed_stdout = io.StringIO()
    closed_stderr = io.StringIO()
    closed_stdout.close()
    closed_stderr.close()
    code = None
    error = None

    try:
        for name in check_names:
            setattr(smoke, name, lambda: None)
        sys.stdout = closed_stdout
        sys.stderr = closed_stderr
        code = smoke.main()
    except Exception as exc:
        error = repr(exc)
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        for name, fn in originals.items():
            setattr(smoke, name, fn)

    if error:
        return _fail(error)
    if code != 0:
        return _fail(f'railway_smoke_local returned {code!r}')

    safe_print(MARKER)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
