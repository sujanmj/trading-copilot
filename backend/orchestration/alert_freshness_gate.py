"""
Alert freshness gate (Stage 47D).

Block actionable alerts when core feeds are stale; attempt safe refresh first.
Hard stale lock during India premarket (07:45–09:15) suppresses live conviction setups.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timezone
from typing import Any, Optional, Tuple
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path

IST = ZoneInfo('Asia/Kolkata')

NEWS_STALE_MARKET_SEC = 90 * 60
SCANNER_MARKET_STALE_SEC = 15 * 60
PREMARKET_STALE_SEC = 30 * 60
MAX_NEWS_AGE_SEC = 48 * 3600

WATCH_ONLY_MESSAGE = 'Data refresh incomplete — watch only.'
PREMARKET_INCOMPLETE_HEADER = '⚠️ DATA REFRESH INCOMPLETE — NO LIVE SETUPS'
PREMARKET_WATCHLIST_ONLY_NOTE = 'Watchlist preparation only'
PREMARKET_OLD_SESSION_NOTE = 'Old scanner/session data detected'
PREMARKET_WAIT_SCANNER_NOTE = 'Wait for fresh scanner after 09:15'
PREMARKET_RISKOFF_HEADER = 'Risk-off premarket'
PREMARKET_SCORE_CAP = 65
PREMARKET_HARD_STALE_SCORE_CAP = 50
PREMARKET_INCOMPLETE_SCORE_CAP = 50

CRITICAL_PREMARKET_KEYS = frozenset({'scanner', 'premarket', 'news'})
CRITICAL_MARKET_HOURS_KEYS = frozenset({'scanner', 'market'})

SOURCE_FILES = {
    'scanner': 'scanner_data.json',
    'market': 'latest_market_data.json',
    'news': 'news_feed.json',
    'intel': 'unified_intelligence.json',
    'watchlist': 'tomorrow_watchlist_report.json',
    'premarket': 'premarket_conviction_report.json',
}


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


def source_age_minutes(name: str) -> int:
    age = _file_age_seconds(name)
    if age is None:
        return -1
    return max(0, age // 60)


def _load_json(name: str) -> dict:
    path = get_data_path(name)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def get_current_india_trading_date(now: Optional[datetime] = None) -> str:
    now = now or _now_ist()
    return now.date().isoformat()


def extract_session_date_from_source(data: dict) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    for key in ('session_date', 'trading_date', 'scan_date', 'date'):
        val = data.get(key)
        if val:
            return str(val).split('T')[0]
    for key in ('last_updated', 'generated_at', 'timestamp', 'updated_at', 'scan_time_local'):
        val = data.get(key)
        ts = _parse_ts(val)
        if ts:
            return ts.astimezone(IST).date().isoformat()
    return None


def is_current_trading_session(session_date: Optional[str], now: Optional[datetime] = None) -> bool:
    if not session_date:
        return False
    return session_date == get_current_india_trading_date(now)


def is_premarket_hard_stale_window(now: Optional[datetime] = None) -> bool:
    """India trading day 07:45–09:15 IST — hard stale lock window."""
    now = now or _now_ist()
    from backend.analytics.market_calendar_router import is_india_market_day

    if not is_india_market_day(now.date()):
        return False
    local_t = now.time().replace(microsecond=0)
    return time(7, 45) <= local_t < time(9, 15)


def _is_market_hours(now: Optional[datetime] = None) -> bool:
    from backend.utils.market_hours import get_market_period
    return get_market_period(now) == 'market'


def _is_premarket_window(now: Optional[datetime] = None) -> bool:
    from backend.utils.market_hours import get_market_period
    return get_market_period(now) in ('pre_market', 'preopen')


def _is_india_market_hours_mode(now: Optional[datetime] = None) -> bool:
    now = now or _now_ist()
    try:
        from backend.analytics.market_calendar_router import get_india_telegram_mode
        mode = str((get_india_telegram_mode() or {}).get('market_mode') or '')
        return 'INDIA_MARKET_HOURS' in mode and now.time() >= time(9, 15)
    except Exception:
        return _is_market_hours(now) and now.time() >= time(9, 15)


def _split_critical_stale_keys(
    stale_keys: list[str],
    *,
    now: Optional[datetime] = None,
) -> tuple[list[str], list[str]]:
    """Return (critical_stale, non_critical_stale) per India session mode."""
    now = now or _now_ist()
    if _is_india_market_hours_mode(now):
        critical_set = CRITICAL_MARKET_HOURS_KEYS
    elif _is_premarket_window(now) or is_premarket_hard_stale_window(now):
        critical_set = CRITICAL_PREMARKET_KEYS
    else:
        critical_set = CRITICAL_PREMARKET_KEYS | CRITICAL_MARKET_HOURS_KEYS
    critical = [k for k in stale_keys if k in critical_set]
    non_critical = [k for k in stale_keys if k not in critical_set]
    return critical, non_critical


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


def is_headline_source_stale(item: Optional[dict] = None) -> bool:
    """True when emergency macro headline comes from stale cache."""
    if item and article_too_old_for_fresh(item):
        return True
    news_age = newest_article_age_seconds(_load_json('news_feed.json'))
    if news_age is None or news_age > PREMARKET_STALE_SEC:
        return True
    govt_age = _file_age_seconds('govt_intelligence.json')
    if govt_age is None or govt_age > PREMARKET_STALE_SEC:
        return True
    return False


def is_riskoff_macro_before_open(
    global_m: Optional[dict] = None,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """Asia/global crash signal before India open."""
    now = now or _now_ist()
    if now.time() >= time(9, 15):
        return False
    global_m = global_m if isinstance(global_m, dict) else _load_json('global_markets.json')
    sentiment = global_m.get('sentiment') or {}
    if isinstance(sentiment, dict):
        for region in ('asia', 'global', 'usa'):
            block = sentiment.get(region) or {}
            if not isinstance(block, dict):
                continue
            mood = str(block.get('mood') or block.get('sentiment') or '').upper()
            chg = float(block.get('average_change') or block.get('change_percent') or 0)
            if 'BEAR' in mood and chg < -1.0:
                return True
    sent = str(global_m.get('sentiment') or global_m.get('overall_sentiment') or '').lower()
    if 'bear' in sent or 'crash' in sent or 'selloff' in sent:
        return True
    return False


def _collect_premarket_stale_keys(now: Optional[datetime] = None) -> list[str]:
    now = now or _now_ist()
    stale_keys: list[str] = []
    market = _is_market_hours(now)
    premarket = _is_premarket_window(now) or is_premarket_hard_stale_window(now)

    news_age = newest_article_age_seconds(_load_json('news_feed.json'))
    if news_age is None:
        if market or premarket:
            stale_keys.append('news')
    elif (market or premarket) and news_age > PREMARKET_STALE_SEC:
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
        for key, fname in (
            ('intel', 'unified_intelligence.json'),
            ('watchlist', 'tomorrow_watchlist_report.json'),
            ('premarket', 'premarket_conviction_report.json'),
        ):
            age = _file_age_seconds(fname)
            if age is None or age > PREMARKET_STALE_SEC:
                stale_keys.append(key)

    return stale_keys


def attempt_safe_refresh(*, dry_run: bool = False) -> bool:
    """Lightweight refresh — no destructive ops."""
    try:
        from backend.telegram.lazy_command_runner import _scoped_refresh
        result = _scoped_refresh('quick', dry_run=dry_run)
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
    stale_keys = _collect_premarket_stale_keys(now)
    critical, non_critical = _split_critical_stale_keys(stale_keys, now=now)

    if not critical:
        return True, '', non_critical

    _log('ALERT_FRESHNESS_STALE', f'category={category} keys={",".join(critical)}')
    if attempt_safe_refresh():
        stale_keys_after = _collect_premarket_stale_keys(now)
        critical_after, non_critical_after = _split_critical_stale_keys(stale_keys_after, now=now)
        if not critical_after:
            _log('ALERT_FRESHNESS_OK', 'refresh recovered stale feeds')
            return True, '', non_critical_after

    return False, WATCH_ONLY_MESSAGE, critical


def premarket_hard_stale_lock(
    *,
    now: Optional[datetime] = None,
    try_refresh: bool = False,
) -> Tuple[bool, str, list[str], bool]:
    """
    Stage 47D hard stale lock.

    Returns (locked, header, stale_keys, riskoff_override).
    """
    now = now or _now_ist()
    if not is_premarket_hard_stale_window(now):
        return False, '', [], False

    if try_refresh:
        attempt_safe_refresh()

    stale_keys = _collect_premarket_stale_keys(now)
    riskoff = is_riskoff_macro_before_open(now=now)
    if not stale_keys and not riskoff:
        return False, '', [], False

    if stale_keys:
        _log('PREMARKET_HARD_STALE_LOCK', f'keys={",".join(stale_keys)} riskoff={riskoff}')
    elif riskoff:
        _log('PREMARKET_HARD_STALE_LOCK', f'riskoff_override=True')

    return True, PREMARKET_INCOMPLETE_HEADER, stale_keys, riskoff


def annotate_candidate_session(
    candidate: dict,
    *,
    source: str,
    source_data: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Attach session provenance fields required by Stage 47D."""
    now = now or _now_ist()
    fname = SOURCE_FILES.get(source, '')
    data = source_data if isinstance(source_data, dict) else (_load_json(fname) if fname else {})
    session_date = extract_session_date_from_source(data)
    age_min = source_age_minutes(fname) if fname else -1
    ts_val = data.get('generated_at') or data.get('last_updated') or data.get('timestamp')
    current = is_current_trading_session(session_date, now)
    row = dict(candidate)
    row['data_timestamp'] = str(ts_val or '')
    row['session_date'] = session_date or ''
    row['source_age_minutes'] = age_min
    row['is_current_trading_session'] = current
    if not current:
        row['previous_session_research'] = True
    return row


def apply_hard_stale_lock_to_setups(
    setups: list[dict],
    *,
    locked: bool = False,
    riskoff: bool = False,
) -> tuple[list[dict], list[dict]]:
    """Suppress live conviction setups under hard stale lock."""
    if not locked:
        return setups, []

    live: list[dict] = []
    previous_session: list[dict] = []

    for setup in setups:
        row = dict(setup)
        setup_text = str(row.get('setup', ''))
        lower = setup_text.lower()
        is_prev = bool(row.get('previous_session_research')) or not row.get('is_current_trading_session', True)

        if is_prev:
            row['setup'] = 'Previous-session research'
            row['score'] = min(int(row.get('score', 50)), PREMARKET_HARD_STALE_SCORE_CAP)
            row['hard_stale_capped'] = True
            previous_session.append(row)
            continue

        if (
            'bullish' in lower
            or 'scanner signal' in lower
            or 'high conviction' in lower
            or 'ultra' in lower
            or 'strong' in lower
            or int(row.get('score', 50)) > PREMARKET_HARD_STALE_SCORE_CAP
        ):
            row['setup'] = 'Previous-session research'
            row['score'] = min(int(row.get('score', 50)), PREMARKET_HARD_STALE_SCORE_CAP)
            row['hard_stale_capped'] = True
            previous_session.append(row)
            continue

        row['score'] = min(int(row.get('score', 50)), PREMARKET_HARD_STALE_SCORE_CAP)
        row['hard_stale_capped'] = True
        live.append(row)

    if riskoff:
        for row in live + previous_session:
            if 'bullish' in str(row.get('setup', '')).lower():
                row['setup'] = 'Previous-session research'
                row['score'] = min(int(row.get('score', 50)), PREMARKET_HARD_STALE_SCORE_CAP)

    return live, previous_session


def gate_alert_dispatch(category: str) -> Tuple[bool, str]:
    """Returns (allow_send, prefix_message_if_blocked)."""
    ok, msg, _keys = check_core_freshness(category=category)
    if ok:
        return True, ''
    return False, msg


def premarket_freshness_state(
    *,
    now: Optional[datetime] = None,
    try_refresh: bool = False,
) -> Tuple[bool, str, list[str], list[str]]:
    """
    Premarket freshness check with optional safe refresh (Stage 47F).

    Returns (ok, header_or_message, critical_stale_keys, non_critical_stale_keys).
    """
    now = now or _now_ist()
    locked, header, keys, _riskoff = premarket_hard_stale_lock(now=now, try_refresh=try_refresh)
    if locked:
        return False, header, keys, []
    if try_refresh:
        attempt_safe_refresh()
    ok, _msg, keys = check_core_freshness(category='PRE_MARKET', now=now)
    all_stale = _collect_premarket_stale_keys(now)
    critical, non_critical = _split_critical_stale_keys(all_stale, now=now)
    if ok:
        return True, '', [], non_critical
    return False, PREMARKET_INCOMPLETE_HEADER, critical or keys, non_critical


def cap_premarket_scores(
    setups: list[dict],
    *,
    cap: int = PREMARKET_INCOMPLETE_SCORE_CAP,
) -> list[dict]:
    """Cap and relabel setups when freshness is incomplete."""
    capped: list[dict] = []
    for setup in setups:
        row = dict(setup)
        setup_text = str(row.get('setup', '')).lower()
        if (
            'bullish' in setup_text
            or 'scanner signal' in setup_text
            or 'high conviction' in setup_text
            or 'ultra' in setup_text
            or 'strong' in setup_text
        ):
            row['setup'] = 'stale research only'
        row['score'] = min(int(row.get('score', 50)), cap)
        row['freshness_capped'] = True
        row['tier_cap'] = 'not_top3'
        capped.append(row)
    return capped
