#!/usr/bin/env python3
"""Validate railway smoke closed-stdio regression coverage."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

from backend.utils.safe_stdio import safe_print  # noqa: E402

TEST_MARKER = 'RAILWAY_SMOKE_LOCAL_NO_CLOSED_STDERR_CRASH_TEST_OK'
MARKER = 'RAILWAY_SMOKE_LOCAL_NO_CLOSED_STDERR_CRASH_OK'


def _fail(msg: str) -> int:
    safe_print(f'RAILWAY_SMOKE_LOCAL_NO_CLOSED_STDERR_CRASH_FAIL: {msg}', fallback='stderr')
    return 1


def main() -> int:
    smoke_src = (PROJECT_ROOT / 'scripts/railway_smoke_local.py').read_text(encoding='utf-8')
    router_src = (PROJECT_ROOT / 'backend/ai/ai_router.py').read_text(encoding='utf-8')
    logging_src = (PROJECT_ROOT / 'backend/utils/local_logging.py').read_text(encoding='utf-8')
    runner_src = (PROJECT_ROOT / 'backend/utils/runner.py').read_text(encoding='utf-8')

    for token in ('RAILWAY_SMOKE_LOCAL', 'configure_smoke_stdio', 'safe_print'):
        if token not in smoke_src:
            return _fail(f'railway_smoke_local.py missing {token}')
    for token in ('warnings.catch_warnings', "warnings.simplefilter('ignore', FutureWarning)"):
        if token not in router_src:
            return _fail(f'ai_router.py missing {token}')
    if 'SafeStreamProxy' not in logging_src:
        return _fail('local_logging.py must use SafeStreamProxy')
    if "safe_stream('stderr'" not in runner_src or "safe_stream('stdout'" not in runner_src:
        return _fail('runner.py must guard subprocess stdout/stderr')

    env = os.environ.copy()
    env.setdefault('RAILWAY_SMOKE_LOCAL', '1')
    env.setdefault('LOCAL_DEV_MODE', '1')
    env.setdefault('LOCAL_ONLY', '1')
    env.setdefault('PYTHONIOENCODING', 'utf-8')
    proc = subprocess.run(
        [sys.executable, 'scripts/test_railway_smoke_local_no_closed_stderr_crash.py'],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = (proc.stdout or '') + (proc.stderr or '')
    if proc.returncode != 0:
        return _fail(f'test failed rc={proc.returncode}: {output[-500:]}')
    if TEST_MARKER not in output:
        return _fail('test marker missing')

    safe_print(MARKER)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
