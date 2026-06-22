#!/usr/bin/env python3
"""Regression test: scanner refresh survives closed stdout/stderr."""

from __future__ import annotations

import io
import os
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

os.environ.setdefault('LOCAL_DEV_MODE', '1')
os.environ.setdefault('LOCAL_ONLY', '1')

from backend.utils.safe_stdio import safe_print  # noqa: E402

MARKER = 'REFRESH_SCANNER_CLOSED_STDERR_SAFE_TEST_OK'


def _fail(msg: str) -> int:
    safe_print(f'REFRESH_SCANNER_CLOSED_STDERR_SAFE_TEST_FAIL: {msg}', fallback='stderr')
    return 1


def main() -> int:
    from scripts import refresh_local_intelligence as refresh

    threads: list[threading.Thread] = []
    late_errors: list[str] = []

    def fake_scanner():
        captured_stdout = sys.stdout
        captured_stderr = sys.stderr

        def late_writer() -> None:
            try:
                time.sleep(0.03)
                captured_stdout.write('late stdout from scanner\n')
                captured_stdout.flush()
                captured_stderr.write('late stderr from scanner\n')
                captured_stderr.flush()
            except Exception as exc:
                late_errors.append(repr(exc))

        thread = threading.Thread(target=late_writer, name='closed-stderr-regression')
        thread.start()
        threads.append(thread)
        print('scanner body output should be swallowed')
        return {'ok': True}

    original_optional = refresh._discover_optional_steps
    original_discovered = refresh._discover_steps
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    closed_stdout = io.StringIO()
    closed_stderr = io.StringIO()
    closed_stdout.close()
    closed_stderr.close()
    result = None
    error = None

    try:
        refresh._discover_optional_steps = lambda: {'scanner': (fake_scanner, None)}
        refresh._discover_steps = lambda: {}
        sys.stdout = closed_stdout
        sys.stderr = closed_stderr
        result = refresh.run_refresh_scoped('scanner', dry_run=False)
        for thread in threads:
            thread.join(timeout=1)
            if thread.is_alive():
                error = 'late scanner writer did not finish'
                break
        if late_errors:
            error = f'late scanner writer failed: {late_errors[0]}'
    except Exception as exc:
        error = repr(exc)
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        refresh._discover_optional_steps = original_optional
        refresh._discover_steps = original_discovered

    if error:
        return _fail(error)
    if not isinstance(result, dict) or result.get('ok') is not True:
        return _fail(f'unexpected refresh result: {result!r}')
    if os.environ.get('TQDM_DISABLE') != '1':
        return _fail('TQDM_DISABLE was not enabled in local refresh mode')

    safe_print(MARKER)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
