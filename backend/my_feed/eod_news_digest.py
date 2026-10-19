"""Daily close-of-day trusted-news collection and Telegram digest."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
MAX_DIGEST_STORIES = 12


def _published_ist_date(value: object) -> date | None:
    text = str(value or '').strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(IST).date()


def format_eod_news_digest(
    *,
    day: date,
    sources_checked: int,
    inserted_count: int,
    stories: list[dict[str, Any]],
    failed_sources: list[str] | None = None,
) -> str:
    """Create a short plain-text Telegram digest from newly stored same-day stories."""
    lines = [f'📰 AstraEdge EOD News — {day.strftime("%d %b %Y")}']
    lines.append(f'Sources checked: {sources_checked} · New stories saved: {inserted_count}')
    if stories:
        lines.append('')
        for index, story in enumerate(stories[:MAX_DIGEST_STORIES], start=1):
            title = ' '.join(str(story.get('title') or '').split())
            source = ' '.join(str(story.get('source_name') or 'Publisher').split())
            url = str(story.get('source_url') or '').strip()
            tickers = story.get('tickers') or []
            ticker_text = f" ({', '.join(str(t).upper() for t in tickers[:4])})" if tickers else ''
            lines.append(f'{index}. {title}{ticker_text}\n   {source} · {url}')
        if len(stories) > MAX_DIGEST_STORIES:
            lines.append(f'…and {len(stories) - MAX_DIGEST_STORIES} more saved today in /myfeed today.')
    elif failed_sources and len(failed_sources) >= sources_checked:
        lines.extend(['', 'News collection could not reach any enabled source. My Feed was not changed.'])
    else:
        lines.extend(['', 'No new, timestamped stories from today were added to the feed.'])
    if failed_sources:
        lines.append(f'Unavailable sources: {", ".join(failed_sources[:5])}')
    lines.extend(['', 'Stories are source-linked and remain UNVERIFIED until checked.'])
    return '\n'.join(lines)


def run_eod_news_digest(*, now: datetime | None = None, send_fn=None) -> dict[str, Any]:
    """Refresh trusted sources, persist news, and send only newly saved stories dated today IST."""
    from backend.collectors.news_provider_registry import run_unified_news_refresh
    from backend.my_feed.news_ingestion import ingest_provider_articles

    current = now or datetime.now(IST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    today = current.astimezone(IST).date()

    refresh = run_unified_news_refresh(hours_back=36, send_macro_alerts=False)
    articles = ((refresh.get('output') or {}).get('articles') or [])
    ingestion = ingest_provider_articles(articles)
    new_today = [
        item for item in ingestion.get('inserted_items', [])
        if _published_ist_date(item.get('published_at')) == today
    ]
    provider_status = refresh.get('provider_status') or refresh.get('provider_registry') or {}
    failed_sources = [
        str(source_id) for source_id, status in provider_status.items()
        if isinstance(status, dict) and status.get('freshness_status') in {'STALE', 'MISSING'}
    ]
    message = format_eod_news_digest(
        day=today,
        sources_checked=int(refresh.get('sources_checked') or 0),
        inserted_count=len(new_today),
        stories=new_today,
        failed_sources=failed_sources,
    )
    if send_fn is None:
        from backend.telegram.telegram_analysis_bot import send_analysis_message

        send_fn = send_analysis_message
    sent = send_fn(message, command='eod_news_digest', parse_mode='')
    result = {
        'ok': bool(refresh.get('ok')) and bool(ingestion.get('ok')),
        'day_ist': today.isoformat(),
        'sources_checked': int(refresh.get('sources_checked') or 0),
        'articles_received': int(ingestion.get('received') or 0),
        'articles_inserted': int(ingestion.get('inserted') or 0),
        'new_stories_today': len(new_today),
        'failed_sources': failed_sources,
        'telegram': sent,
        'message': message,
    }
    print(
        f"[EOD_NEWS_DIGEST] day={today.isoformat()} sources={result['sources_checked']} "
        f"inserted={result['articles_inserted']} today={result['new_stories_today']} "
        f"telegram_sent={bool((sent or {}).get('sent'))}",
        flush=True,
    )
    return result
