"""Telegram formatters for My Feed commands (Stage 50A / 50X visibility)."""

from __future__ import annotations

from typing import Any

from backend.my_feed.feed_processor import sanitize_item_for_api, scan_feed_summary
from backend.my_feed.feed_verification import item_verification_status


def _display_headline(row: dict[str, Any]) -> str:
    status = item_verification_status(row)
    if status in ('VERIFIED', 'PARTIALLY_VERIFIED') and row.get('verified_headline'):
        return str(row.get('verified_headline') or '')[:140]
    return str(row.get('cleaned_summary') or row.get('raw_user_text') or '')[:140]


def format_myfeed_list(items: list[dict[str, Any]], *, title: str = 'My Feed') -> str:
    lines = [f'<b>📥 {title}</b>']
    if not items:
        lines.append('No feed items match this filter.')
        return '\n'.join(lines)
    for item in items[:12]:
        row = sanitize_item_for_api(item)
        tickers = ', '.join(row.get('tickers') or []) or '—'
        status = item_verification_status(row)
        status_tag = status.replace('_', ' ')
        archived = str(row.get('status') or '').lower() == 'archived'
        archived_note = ' · archived' if archived else ''
        lines.append(
            f"• <code>{row.get('feed_id', '—')}</code> "
            f"{row.get('suggested_action', 'NEWS ONLY')} | impact {row.get('impact_score', 0)} | "
            f"{status_tag}{archived_note}"
        )
        lines.append(f"  {tickers} · {_display_headline(row)}")
    return '\n'.join(lines)


def format_myfeed_scan(summary: dict[str, Any]) -> str:
    lines = [
        '<b>📥 My Feed scan</b>',
        f"Active: {summary.get('total', 0)}",
        f"Verified catalyst-eligible: {summary.get('verified', 0)}",
        f"Unverified active: {summary.get('unverified', 0)}",
        f"Contradicted: {summary.get('contradicted', 0)}",
        f"Archived dirty: {summary.get('archived_dirty', 0)}",
        f"High impact: {summary.get('high_impact', 0)}",
        f"Risk alerts: {summary.get('risk_alerts', 0)}",
        f"Watch for confirmation: {summary.get('watch_items', 0)}",
    ]
    for item in (summary.get('items') or [])[:6]:
        row = sanitize_item_for_api(item)
        tickers = ', '.join(row.get('tickers') or []) or '—'
        status = item_verification_status(row)
        lines.append(
            f"• {tickers} — {row.get('suggested_action', 'NEWS ONLY')} "
            f"({row.get('impact_score', 0)}) · {status.replace('_', ' ')}"
        )
    return '\n'.join(lines)
