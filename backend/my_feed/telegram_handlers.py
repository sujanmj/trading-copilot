"""Telegram formatters for My Feed commands (Stage 50A)."""

from __future__ import annotations

from typing import Any

from backend.my_feed.feed_processor import sanitize_item_for_api, scan_feed_summary


def format_myfeed_list(items: list[dict[str, Any]], *, title: str = 'My Feed') -> str:
    lines = [f'<b>📥 {title}</b>']
    if not items:
        lines.append('No active feed items.')
        return '\n'.join(lines)
    for item in items[:12]:
        row = sanitize_item_for_api(item)
        tickers = ', '.join(row.get('tickers') or []) or '—'
        status = str(row.get('verification_status') or 'UNVERIFIED').upper()
        status_tag = status.replace('_', ' ')
        lines.append(
            f"• <code>{row.get('feed_id', '—')}</code> "
            f"{row.get('suggested_action', 'NEWS ONLY')} | impact {row.get('impact_score', 0)} | {status_tag}"
        )
        headline = str(row.get('verified_headline') or row.get('cleaned_summary') or '')[:140]
        lines.append(f"  {tickers} · {headline}")
    return '\n'.join(lines)


def format_myfeed_scan(summary: dict[str, Any]) -> str:
    lines = [
        '<b>📥 My Feed scan</b>',
        f"Active: {summary.get('total', 0)}",
        f"Verified catalyst-eligible: {summary.get('verified', 0)}",
        f"Unverified: {summary.get('unverified', 0)}",
        f"High impact: {summary.get('high_impact', 0)}",
        f"Risk alerts: {summary.get('risk_alerts', 0)}",
        f"Watch for confirmation: {summary.get('watch_items', 0)}",
    ]
    for item in (summary.get('items') or [])[:6]:
        row = sanitize_item_for_api(item)
        tickers = ', '.join(row.get('tickers') or []) or '—'
        status = str(row.get('verification_status') or 'UNVERIFIED').upper()
        lines.append(
            f"• {tickers} — {row.get('suggested_action', 'NEWS ONLY')} "
            f"({row.get('impact_score', 0)}) · {status.replace('_', ' ')}"
        )
    return '\n'.join(lines)
