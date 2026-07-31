"""Shared test helpers to keep regression runs from writing under data/."""

from __future__ import annotations

import tempfile
from contextlib import ExitStack, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator
from unittest.mock import patch


@contextmanager
def isolated_ai_usage_log():
    """Redirect telegram AI usage log to a temp file for the active test."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / 'telegram_ai_usage_log.jsonl'
        with patch('backend.telegram.ai_usage_guard.AI_USAGE_LOG', path):
            yield path


@contextmanager
def isolated_opening_workflow_dir():
    """Redirect opening-workflow accounting summaries to a temp directory."""
    with tempfile.TemporaryDirectory() as td:
        summary_dir = Path(td) / 'opening_workflow'
        summary_dir.mkdir(parents=True, exist_ok=True)
        with patch('backend.trading.opening_workflow_accounting.SUMMARY_DIR', summary_dir):
            yield summary_dir


@contextmanager
def isolated_aihub_tab_cache():
    """Redirect AIHub tab cache writes away from data/cache/aihub_tabs."""
    with tempfile.TemporaryDirectory() as td:
        cache_dir = Path(td) / 'aihub_tabs'
        cache_dir.mkdir(parents=True, exist_ok=True)
        with patch('backend.analytics.aihub_tab_payloads.AIHUB_TAB_CACHE_DIR', cache_dir):
            yield cache_dir


@contextmanager
def isolated_premarket_report():
    """Redirect premarket conviction report writes to a temp file."""
    with tempfile.TemporaryDirectory() as td:
        report_path = Path(td) / 'premarket_conviction_report.json'
        with patch('backend.analytics.premarket_conviction.REPORT_FILE', report_path):
            yield report_path


def repo_data_root() -> Path:
    """Canonical repository data/ directory (never mutate during tests)."""
    return Path(__file__).resolve().parent.parent / 'data'


def snapshot_data_tree(root: Path | None = None) -> dict[str, tuple[int, int]]:
    """Map relative path -> (size, mtime_ns) for files under the data root."""
    base = root or repo_data_root()
    out: dict[str, tuple[int, int]] = {}
    if not base.is_dir():
        return out
    for path in base.rglob('*'):
        if path.is_file():
            st = path.stat()
            out[str(path.relative_to(base)).replace('\\', '/')] = (st.st_size, st.st_mtime_ns)
    return out


@contextmanager
def isolated_premarket_data_root() -> Iterator[dict]:
    """
    Redirect get_data_root / DATA_DIR / REPORT_FILE / AI usage log to a temp tree.

    Blocks get_data_path resolution that would land under the real repository data/.
    """
    real_root = repo_data_root().resolve()
    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td) / 'data'
        temp_root.mkdir(parents=True, exist_ok=True)
        report_path = temp_root / 'premarket_conviction_report.json'
        ai_log = temp_root / 'telegram_ai_usage_log.jsonl'

        def _temp_data_path(relative: str) -> Path:
            rel = str(relative or '').replace('\\', '/').lstrip('/')
            path = temp_root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            return path

        def _guarded_get_data_path(relative: str) -> Path:
            path = _temp_data_path(relative).resolve()
            try:
                path.relative_to(real_root)
            except ValueError:
                return path
            raise RuntimeError(f'repo data path leak blocked: {relative}')

        with ExitStack() as stack:
            stack.enter_context(
                patch('backend.storage.data_paths.get_data_root', return_value=temp_root)
            )
            stack.enter_context(
                patch('backend.storage.data_paths.get_data_path', side_effect=_guarded_get_data_path)
            )
            stack.enter_context(patch('backend.utils.config.DATA_DIR', temp_root))
            stack.enter_context(patch('backend.telegram.ai_usage_guard.AI_USAGE_LOG', ai_log))
            stack.enter_context(
                patch.dict('os.environ', {'RAILWAY_DATA_DIR': str(temp_root)}, clear=False)
            )
            stack.enter_context(
                patch('backend.analytics.premarket_conviction.REPORT_FILE', report_path)
            )
            yield {
                'temp_root': temp_root,
                'report_path': report_path,
                'real_root': real_root,
                'ai_log': ai_log,
            }


@contextmanager
def premarket_clock_at(moment: datetime) -> Iterator[datetime]:
    """
    Freeze backend.analytics.premarket_conviction.datetime.now to ``moment``.

    That module's imported ``datetime`` drives title/slot/after-open/live routing
    for /premarket formatting. The passed moment must control rendered mode labels.
    """
    if moment.tzinfo is None:
        raise ValueError('premarket_clock_at requires a timezone-aware datetime')

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz is None:
                return moment.replace(tzinfo=None)
            return moment.astimezone(tz)

    with patch('backend.analytics.premarket_conviction.datetime', _FrozenDateTime):
        yield moment


def synced_tradecard_stub(
    ticker: str,
    *,
    state: str = 'TRADECARD_CANDIDATE',
    score: int = 80,
    status_override: str = '',
) -> dict:
    """Fixture sync result that bypasses live session-stale board rewrites."""
    sym = str(ticker or '').strip().upper()
    return {
        'tradecards_best': sym,
        'selected': sym,
        'source': 'radar',
        'reason': 'test fixture sync',
        'status_override': status_override,
        'state': state,
        'score': score,
        'board': {'ok': True, 'session_date': '2099-01-01'},
        'session_stale': False,
        'reference_only': False,
    }
