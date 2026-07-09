"""
Lightweight news-only refresh + cache age helpers (Phase 4B.18G + 4B.18J unified sources).

/news refresh and /news refresh SYMBOL refresh all enabled news providers —
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

# Provider-name tokens that must not be treated as /news refresh SYMBOL targets.
_RESERVED_REFRESH_TOKENS = frozenset({
    'mint', 'markets', 'companies', 'news', 'industry', 'money',
    'business', 'standard', 'nse', 'bse', 'rbi', 'sebi', 'pib', 'mcx',
    'investing', 'et', 'ndtv', 'epaper', 'upload', 'import',
})


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
            for key in ('generated_at', 'updated_at', 'fetched_at', 'timestamp', 'last_updated'):
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


def _is_provider_token(symbol: str) -> bool:
    token = str(symbol or '').strip().lower()
    if not token:
        return False
    if token in _RESERVED_REFRESH_TOKENS:
        return True
    if re.match(r'^mint[\s_/]', token):
        return True
    return False


def run_news_cache_refresh(
    *,
    symbol: str = '',
    company: str = '',
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Refresh all enabled news providers (unified registry).
    Optionally stamp symbol filter metadata for /news refresh SYMBOL.
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
        'new_items': 0,
        'sources_checked': 0,
        'errors': [],
        'error_count': 0,
        'cache_age_minutes': None,
        'sources': [],
        'refresh': None,
    }

    if dry_run:
        result['ok'] = True
        result['refresh'] = {'ok': True, 'scope': 'news', 'dry_run': True, 'news': 'ok'}
        result['cache_age_minutes'] = 0
        result['sources_checked'] = len(_enabled_provider_names())
        return result

    if sym and _is_provider_token(sym):
        result['error'] = 'use /news refresh without provider name — all sources refresh together'
        return result

    try:
        from backend.collectors.news_provider_registry import run_unified_news_refresh

        unified = run_unified_news_refresh(send_macro_alerts=False)
        result['refresh'] = {'ok': unified.get('ok'), 'scope': 'news', 'news': 'ok' if unified.get('ok') else 'partial'}
        result['ok'] = bool(unified.get('ok'))
        result['partial'] = bool(unified.get('partial'))
        result['sources_checked'] = int(unified.get('sources_checked') or 0)
        result['items_found'] = int(unified.get('items_found') or 0)
        result['new_items'] = int(unified.get('new_items') or 0)
        result['errors'] = list(unified.get('errors') or [])
        result['error_count'] = int(unified.get('error_count') or 0)
        result['sources'] = list(unified.get('sources') or [])
        result['provider_status'] = unified.get('provider_status') or {}
    except Exception as exc:
        result['error'] = str(exc)[:200]
        return result

    # Count matching items after refresh for symbol context.
    if sym or company_name:
        match_count = 0
        match_sources: list[str] = []
        try:
            from backend.my_feed.feed_verification import iter_verification_source_articles

            articles = iter_verification_source_articles()
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
                    str(art.get('description') or ''),
                    ' '.join(str(t) for t in (art.get('tickers') or art.get('symbols') or [])),
                ]).lower()
                if aliases and not any(a and a in blob for a in aliases):
                    continue
                match_count += 1
                src = str(art.get('source') or art.get('source_name') or '').strip()
                if src and src not in match_sources:
                    match_sources.append(src)
            result['items_found'] = match_count
            if match_sources:
                result['sources'] = match_sources[:12]
        except Exception:
            pass

    age = news_cache_age_minutes()
    result['cache_age_minutes'] = 0 if result['ok'] else age
    return result


def _enabled_provider_names() -> list[str]:
    try:
        from backend.collectors.news_provider_registry import get_enabled_providers

        return [str(p.get('source_name') or '') for p in get_enabled_providers()]
    except Exception:
        return []


def format_news_refresh_telegram(result: dict[str, Any]) -> str:
    sym = str(result.get('symbol') or '').strip().upper() or '—'
    company = str(result.get('company') or '').strip() or '—'
    age = result.get('cache_age_minutes')
    age_disp = '0m' if age in (0, '0') else (f'{age}m' if age is not None else '—')
    sources = result.get('sources') or []
    sources_disp = ', '.join(str(s) for s in sources[:10]) if sources else '—'
    status = 'NEWS_REFRESH_DONE' if result.get('ok') and not result.get('partial') else (
        'NEWS_REFRESH_DONE' if result.get('ok') else 'NEWS_REFRESH_PARTIAL'
    )
    if result.get('partial'):
        status = 'NEWS_REFRESH_PARTIAL'
    lines = [
        status,
        f'sources_checked={int(result.get("sources_checked") or 0)}',
        f'items_found={int(result.get("items_found") or 0)}',
        f'new_items={int(result.get("new_items") or 0)}',
        f'errors={int(result.get("error_count") or 0)}',
        f'sources={sources_disp}',
    ]
    if sym != '—':
        lines.insert(1, f'symbol={sym}')
        lines.insert(2, f'company={company}')
    if result.get('error'):
        lines.append(f'error={result.get("error")}')
    elif result.get('errors'):
        lines.append(f'error_detail={"; ".join(str(e) for e in (result.get("errors") or [])[:2])}')
    lines.append(f'cache_age={age_disp}')
    return '\n'.join(lines)
