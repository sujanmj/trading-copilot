"""Shared test helpers to keep regression runs from writing under data/."""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path
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
