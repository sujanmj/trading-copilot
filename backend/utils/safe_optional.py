"""Safe optional dependency helpers — optional modules must not crash core pipelines."""

from __future__ import annotations

import traceback
from typing import Any, Callable, Optional


def try_import(module: str, names: list):
    """Return dict of imported names or empty dict on failure."""
    try:
        mod = __import__(module, fromlist=names)
        return {n: getattr(mod, n) for n in names}
    except Exception:
        return {}


def run_optional(label: str, fn: Callable[[], Any], *, log=None) -> dict:
    """Run optional step; return status dict without raising."""
    try:
        result = fn()
        return {'status': 'ok', 'label': label, 'result': result}
    except Exception as e:
        msg = f"{label} skipped (optional): {e}"
        if log:
            log(msg)
        else:
            print(f"[OPTIONAL] {msg}", flush=True)
        return {
            'status': 'skipped',
            'label': label,
            'reason': str(e),
            'traceback': traceback.format_exc()[-1500:],
        }
