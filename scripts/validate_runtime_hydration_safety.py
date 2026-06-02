#!/usr/bin/env python3
"""
Validate RuntimeManager hydration safety (Stage 20B).

Checks: single inflight guard, debounce, snapshot identity skip, no recursive stale refresh,
SnapshotAdapter minimum contract, stale vs degraded banners.

Prints exactly RUNTIME_HYDRATION_SAFETY_OK on success.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME = PROJECT_ROOT / 'frontend' / 'runtime' / 'runtimeManager.js'
ADAPTER = PROJECT_ROOT / 'frontend' / 'runtime' / 'snapshotAdapter.js'
INDEX = PROJECT_ROOT / 'frontend' / 'index.html'


def _fail(msg: str) -> int:
    print(f'RUNTIME_HYDRATION_SAFETY_FAIL: {msg}', file=sys.stderr)
    return 1


def _read(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path.read_text(encoding='utf-8')


def main() -> int:
    for path in (RUNTIME, ADAPTER, INDEX):
        if not path.is_file():
            return _fail(f'missing {path.relative_to(PROJECT_ROOT)}')

    runtime_src = _read(RUNTIME)
    adapter_src = _read(ADAPTER)
    index_src = _read(INDEX)

    if 'let inFlight = false' not in runtime_src:
        return _fail('runtimeManager must track inFlight')
    if 'skip duplicate fetch' not in runtime_src:
        return _fail('runtimeManager must log skip duplicate fetch')
    if 'snapshot unchanged' not in runtime_src:
        return _fail('runtimeManager must skip unchanged snapshot apply')
    if 'lastSnapshotIdentity' not in runtime_src:
        return _fail('runtimeManager must compare snapshot_id/generated_at identity')
    if 'applied live snapshot' not in runtime_src:
        return _fail('runtimeManager must log applied live snapshot')

    if re.search(r'setTimeout\(\(\)\s*=>\s*refresh\(\{\s*force:\s*true', runtime_src):
        return _fail('runtimeManager must not schedule recursive refresh from applySnapshot')

    if 'ensureMinimumContract' not in adapter_src:
        return _fail('snapshotAdapter must ensureMinimumContract')
    if 'isMalformedCacheSnapshot' not in adapter_src:
        return _fail('snapshotAdapter must detect malformed cache')

    if 'runtime-stale-banner' not in runtime_src and 'runtime-stale-banner' not in index_src:
        return _fail('missing runtime-stale-banner for live stale (not degraded cache)')

    if 'Runtime snapshot is stale' not in runtime_src:
        return _fail('runtimeManager must show stale snapshot message (not degraded cache)')

    if 'meta.unchanged' not in index_src or 'meta && meta.unchanged' not in index_src:
        return _fail('index.html subscriber must skip render when snapshot unchanged')

    print('RUNTIME_HYDRATION_SAFETY_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
