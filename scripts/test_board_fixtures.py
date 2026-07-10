#!/usr/bin/env python3
"""Shared opening-board fixtures for live /tradecards and /radar display tests."""

from __future__ import annotations

from typing import Any


def current_live_freshness_policy() -> dict[str, Any]:
    """Policy blob that bypasses prepare_board_for_live_command in display helpers."""
    return {
        'market_lifecycle': 'MARKET_ACTIVE',
        'scanner_stale': False,
        'live_ready': True,
        'quality_tradecard_blocked': False,
        'live_confirmation_blocked': False,
        'requires_auto_refresh': False,
        'allows_quality_tradecard': True,
    }


def current_live_board_overlay() -> dict[str, Any]:
    """Metadata for a CURRENT scanner board used by formatter tests."""
    return {
        'session_stale': False,
        'reference_only': False,
        'no_current_entry': False,
        'data_status': 'current',
        'scanner_freshness_status': 'CURRENT',
        'live_scanner_ready': True,
        'scanner_stale': False,
        'quality_tradecard_blocked': False,
        'live_confirmation_blocked': False,
        'stale_after_auto_refresh': False,
        'live_freshness_policy': current_live_freshness_policy(),
    }


def apply_live_board_overlay(board: dict[str, Any]) -> dict[str, Any]:
    """Return board copy marked CURRENT so formatters skip auto-refresh guard."""
    data = dict(board or {})
    data.update(current_live_board_overlay())
    return data


def quality_ranked_candidate(
    *,
    ticker: str,
    score: int = 72,
    state: str = 'TRADECARD_CANDIDATE',
    why: list[str] | None = None,
    gainer_bucket: str = '',
    **extra: Any,
) -> dict[str, Any]:
    """Minimal ranked candidate that passes the score>=60 quality gate."""
    row: dict[str, Any] = {
        'ticker': ticker,
        'score': score,
        'state': state,
        'why': why or ['volume confirmation'],
    }
    if gainer_bucket:
        row['gainer_bucket'] = gainer_bucket
    row.update(extra)
    return row
