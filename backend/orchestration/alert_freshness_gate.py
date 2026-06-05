"""
Alert freshness gate (Stage 46H).

Block actionable alerts when core feeds are stale; attempt safe refresh first.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Tuple
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path

IST = ZoneInfo('Asia/Kolkata')

NEWS_STALE_MARKET_SEC = 90 * 60
SCANNER_MARKET_STALE_SEC = 15 * 60
PREMARKET_STALE_SEC = 30 * 60
MAX_NEWS_AGE_SEC = 48 * 3600

WATCH_ONLY_MESSAGE = 'Data refresh incomplete — watch only.'
PREMARKET_INCOMPLETE_HEADER = '⚠️ DATA REFRESH INCOMPLETE — WATCH ONLY'
PREMARKET_WATCHLIST_ONLY_NOTE = 'Watchlist preparation only — not conviction.'
PREMARKET_SCORE_CAP = 65


def _log(tag: str, msg: str) -> None:
    print(f'[{tag}] {msg}', flush=True)


def _now_ist() -> datetime:
    return datetime.now(IST)


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _file_age_seconds(name: str) -> Optional[int]:
    path = get_data_path(name)
    if not path.is_file():
        return None
    try:
        return int(datetime.now(timezone.utc).timestamp() - path.stat().st_mtime)
    except OSError:
        return None


def _load_json(name: str) -> dict:
    path = get_data_path(name)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _is_market_hours(now: Optional[datetime] = None) -> bool:
    from backend.utils.market_hours import get_market_period
    return get_market_period(now) == 'market'


def _is_premarket_window(now: Optional[datetime] = None) -> bool:
    from backend.utils.market_hours import get_market_period
    return get_market_period(now) in ('pre_market', 'preopen')


def newest_article_age_seconds(news: dict) -> Optional[int]:
    articles = news.get('articles') or []
    newest: Optional[datetime] = None
    for art in articles[:40]:
        if not isinstance(art, dict):
            continue
        ts = _parse_ts(art.get('published_at') or art.get('published') or art.get('date'))
        if ts and (newest is None or ts > newest):
            newest = ts
    file_ts = _parse_ts(news.get('updated_at') or news.get('timestamp') or news.get('generated_at'))
    if file_ts and (newest is None or file_ts > newest):
        newest = file_ts
    if newest is None:
        return _file_age_seconds('news_feed.json')
    return int((datetime.now(timezone.utc) - newest).total_seconds())


def article_too_old_for_fresh(article: dict) -> bool:
    ts = _parse_ts(article.get('published_at') or article.get('published') or article.get('date'))
    if not ts:
        return False
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    return age > MAX_NEWS_AGE_SEC


def attempt_safe_refresh() -> bool:
    """Lightweight refresh — no destructive ops."""
    try:
        from backend.telegram.lazy_command_runner import _scoped_refresh
        result = _scoped_refresh('quick', dry_run=False)
        return bool(result.get('ok'))
    except Exception as exc:
        _log('FRESHNESS_REFRESH', f'safe refresh failed: {exc}')
        return False


def check_core_freshness(
    *,
    category: str = '',
    now: Optional[datetime] = None,
) -> Tuple[bool, str, list[str]]:
    """
    Returns (ok, user_message, stale_keys).
    ok=False means gate blocked — user_message is watch-only text.
    """
    now = now or _now_ist()
    stale_keys: list[str] = []
    market = _is_market_hours(now)
    premarket = _is_premarket_window(now)

    news_age = newest_article_age_seconds(_load_json('news_feed.json'))
    if news_age is None and market:
        stale_keys.append('news')
    elif news_age is not None and market and news_age > NEWS_STALE_MARKET_SEC:
        stale_keys.append('news')

    for key, fname, limit in (
        ('scanner', 'scanner_data.json', SCANNER_MARKET_STALE_SEC),
        ('market', 'latest_market_data.json', SCANNER_MARKET_STALE_SEC),
    ):
        age = _file_age_seconds(fname)
        if age is None:
            if market or premarket:
                stale_keys.append(key)
        elif (market or premarket) and age > limit:
            stale_keys.append(key)

    if premarket:
        for key, fname in (('intel', 'unified_intelligence.json'), ('watchlist', 'tomorrow_watchlist_report.json')):
            age = _file_age_seconds(fname)
            if age is None or age > PREMARKET_STALE_SEC:
                stale_keys.append(key)

    if not stale_keys:
        return True, '', []

    _log('ALERT_FRESHNESS_STALE', f'category={category} keys={",".join(stale_keys)}')
    if attempt_safe_refresh():
        stale_keys_after: list[str] = []
        news_age2 = newest_article_age_seconds(_load_json('news_feed.json'))
        if market and news_age2 is not None and news_age2 > NEWS_STALE_MARKET_SEC:
            stale_keys_after.append('news')
        for key, fname, limit in (
            ('scanner', 'scanner_data.json', SCANNER_MARKET_STALE_SEC),
            ('market', 'latest_market_data.json', SCANNER_MARKET_STALE_SEC),
        ):
            age = _file_age_seconds(fname)
            if (market or premarket) and age is not None and age > limit:
                stale_keys_after.append(key)
        if not stale_keys_after:
            _log('ALERT_FRESHNESS_OK', 'refresh recovered stale feeds')
            return True, '', []

    return False, WATCH_ONLY_MESSAGE, stale_keys


def gate_alert_dispatch(category: str) -> Tuple[bool, str]:
    """Returns (allow_send, prefix_message_if_blocked)."""
    ok, msg, _keys = check_core_freshness(category=category)
    if ok:
        return True, ''
    return False, msg


def premarket_freshness_state(*, now: Optional[datetime] = None, try_refresh: bool = False) -> Tuple[bool, str, list[str]]:
    """
    Premarket freshness check with optional safe refresh (Stage 46I).

    Returns (ok, header_or_message, stale_keys).
    """
    if try_refresh:
        attempt_safe_refresh()
    ok, msg, keys = check_core_freshness(category='PRE_MARKET', now=now)
    if ok:
        return True, '', []
    return False, PREMARKET_INCOMPLETE_HEADER, keys


def cap_premarket_scores(setups: list[dict], *, cap: int = PREMARKET_SCORE_CAP) -> list[dict]:
    """Cap top setup scores when freshness is incomplete."""
    capped: list[dict] = []
    for setup in setups:
        row = dict(setup)
        row['score'] = min(int(row.get('score', 50)), cap)
        row['freshness_capped'] = True
        capped.append(row)
    return capped
