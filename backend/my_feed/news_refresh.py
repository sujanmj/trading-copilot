"""
Lightweight news-only refresh + cache age helpers (Phase 4B.18G / AstraEdge 52E).

/news refresh and /news refresh SYMBOL refresh news caches only —
never scanner, prices, screener, broker, or memory.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.storage.data_paths import get_data_path

NEWS_CACHE_FILES = (
    'news_feed.json',
    'live_news_feed.json',
    'inshorts_feed.json',
)

AUTO_REFRESH_IF_OLDER_MIN = 60
SKIP_AUTO_REFRESH_IF_NEWER_MIN = 30


def _parse_iso(ts: str) -> datetime | None:
    text = str(ts or '').strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def news_cache_age_minutes(*, data_dir: Path | None = None) -> int | None:
    """Youngest mtime / generated_at across news caches, in minutes. None if missing."""
    ages: list[int] = []
    now = datetime.now(timezone.utc)
    for name in NEWS_CACHE_FILES:
        path = Path(data_dir) / name if data_dir is not None else get_data_path(name)
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            payload = {}
        stamped = None
        if isinstance(payload, dict):
            for key in ('generated_at', 'updated_at', 'fetched_at', 'timestamp'):
                stamped = _parse_iso(str(payload.get(key) or ''))
                if stamped:
                    break
        if stamped is None:
            try:
                stamped = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
        ages.append(max(0, int((now - stamped).total_seconds() // 60)))
    if not ages:
        return None
    return min(ages)


def should_auto_refresh_news_for_feed(*, data_dir: Path | None = None) -> tuple[bool, str, int | None]:
    """
    Auto-refresh rules for /feed verification:
    - age > 60m → refresh once
    - age <= 30m → do not refresh
    - 30 < age <= 60 → optional/no (prefer no auto spam); return False
    """
    age = news_cache_age_minutes(data_dir=data_dir)
    if age is None:
        return True, 'missing_cache', None
    if age > AUTO_REFRESH_IF_OLDER_MIN:
        return True, f'cache_age_{age}m', age
    if age <= SKIP_AUTO_REFRESH_IF_NEWER_MIN:
        return False, f'cache_fresh_{age}m', age
    return False, f'cache_mid_{age}m', age


def run_news_cache_refresh(
    *,
    symbol: str = '',
    company: str = '',
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Refresh news collectors only (scoped news). Optionally stamp symbol filter metadata.
    Does not touch scanner/price/screener/broker/memory.
    """
    sym = str(symbol or '').strip().upper()
    if sym == 'SBI':
        sym = 'SBIN'
    company_name = str(company or '').strip()
    if not company_name and sym == 'SBIN':
        company_name = 'State Bank of India'

    result: dict[str, Any] = {
        'ok': False,
        'scope': 'news',
        'symbol': sym,
        'company': company_name,
        'items_found': 0,
        'cache_age_minutes': None,
        'sources': [],
        'refresh': None,
    }

    if dry_run:
        result['ok'] = True
        result['refresh'] = {'ok': True, 'scope': 'news', 'dry_run': True, 'news': 'ok'}
        result['cache_age_minutes'] = 0
        return result

    try:
        from scripts.refresh_local_intelligence import run_refresh_scoped

        refresh = run_refresh_scoped('news', dry_run=False)
    except Exception as exc:
        result['error'] = str(exc)[:200]
        return result

    result['refresh'] = refresh
    result['ok'] = bool(refresh.get('ok')) and str(refresh.get('news') or '') != 'failed'

    # Count matching items after refresh for symbol context.
    items_found = 0
    sources: list[str] = []
    try:
        from backend.my_feed.feed_verification import iter_verification_source_articles

        articles = iter_verification_source_articles()
        needle = (sym or company_name).lower()
        aliases = {sym.lower(), company_name.lower()} if (sym or company_name) else set()
        if sym == 'SBIN':
            aliases.update({'sbin', 'sbi', 'state bank of india', 'state bank'})
        for art in articles:
            if not isinstance(art, dict):
                continue
            blob = ' '.join([
                str(art.get('title') or ''),
                str(art.get('headline') or ''),
                str(art.get('summary') or ''),
                ' '.join(str(t) for t in (art.get('tickers') or art.get('symbols') or [])),
            ]).lower()
            if aliases and not any(a and a in blob for a in aliases):
                if needle and needle not in blob:
                    continue
            items_found += 1
            src = str(art.get('source') or art.get('source_name') or art.get('_cache_bucket') or '').strip()
            if src and src not in sources:
                sources.append(src)
    except Exception:
        pass

    age = news_cache_age_minutes()
    result['items_found'] = items_found
    result['sources'] = sources[:8]
    result['cache_age_minutes'] = 0 if result['ok'] else age
    return result


def format_news_refresh_telegram(result: dict[str, Any]) -> str:
    sym = str(result.get('symbol') or '').strip().upper() or '—'
    company = str(result.get('company') or '').strip() or '—'
    age = result.get('cache_age_minutes')
    age_disp = '0m' if age in (0, '0') else (f'{age}m' if age is not None else '—')
    sources = result.get('sources') or []
    sources_disp = ', '.join(str(s) for s in sources[:5]) if sources else 'news_cache'
    status = 'NEWS_REFRESH_DONE' if result.get('ok') else 'NEWS_REFRESH_PARTIAL'
    lines = [
        status,
        f'symbol={sym}',
        f'company={company}',
        f'items_found={int(result.get("items_found") or 0)}',
        f'cache_age={age_disp}',
        f'sources={sources_disp}',
    ]
    if result.get('error'):
        lines.append(f'error={result.get("error")}')
    return '\n'.join(lines)
