#!/usr/bin/env python3
"""Validator — AstraEdge 52P tradecard explain never-silent hotfix."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'ASTRAEDGE_PHASE_52P_TRADECARD_EXPLAIN_NEVER_SILENT_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    if BUILD_STAGE != '52P' or TELEGRAM_BUILD != 'AstraEdge 52P':
        return _fail(f'canonical build must remain 52P, got {BUILD_STAGE!r}')

    explain_src = (PROJECT_ROOT / 'backend/trading/tradecard_explain.py').read_text(encoding='utf-8')
    runner_src = (PROJECT_ROOT / 'backend/telegram/lazy_command_runner.py').read_text(encoding='utf-8')
    for needle in (
        'run_tradecard_explain_safe',
        'freshness_meta_for_explain',
        'explain_read_mostly',
        'REASON_TOTAL_TIMEOUT',
        'format_explain_fallback',
    ):
        if needle not in explain_src:
            return _fail(f'tradecard_explain missing {needle!r}')
    if 'run_tradecard_explain_safe' not in runner_src:
        return _fail('lazy_command_runner must route explain through never-silent helper')
    if 'refresh_tradecard_market_data' in runner_src and 'explain_ticker' in runner_src:
        # Ensure the explain+ticker branch no longer calls unbounded refresh directly.
        explain_branch = runner_src.split('if explain_ticker:', 1)[-1].split('latest = load_latest_tradecard', 1)[0]
        if 'refresh_tradecard_market_data(' in explain_branch:
            return _fail('explain SYMBOL path must not call refresh_tradecard_market_data')

    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / 'scripts/test_tradecard_explain_never_silent_52p.py')],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    out = (proc.stdout or '') + '\n' + (proc.stderr or '')
    if proc.returncode != 0 or 'TRADECARD_EXPLAIN_NEVER_SILENT_52P_PASS' not in out:
        print(out[-4000:], file=sys.stderr)
        return _fail('focused never-silent test did not pass')

    print('ASTRAEDGE_PHASE_52P_TRADECARD_EXPLAIN_NEVER_SILENT_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
