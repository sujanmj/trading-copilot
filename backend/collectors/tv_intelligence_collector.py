"""
TV / YouTube stock-market intelligence collector (Stage 21B).

Collects real recent Indian stock-market videos from trusted channels and search terms.
Writes data/tv_intelligence.json — no fake videos or fabricated live status.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import feedparser
import requests
from dotenv import load_dotenv

from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR

env_path = Path(__file__).resolve().parent.parent.parent / 'config' / 'keys.env'
load_dotenv(env_path)

YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY', '').strip()
OUTPUT_FILE = DATA_DIR / 'tv_intelligence.json'

CHANNEL_HANDLES: dict[str, str] = {
    'CNBC-TV18': '@CNBC-TV18',
    'ET NOW': '@ETNOW',
    'NDTV Profit': '@NDTVProfitIndia',
    'Zee Business': '@ZeeBusiness',
    'Moneycontrol': '@moneycontrol',
    'Business Today': '@businesstoday',
    'ET Markets': '@economictimes',
    'NSE India': '@NSEIndia',
}

# Stable channel IDs for RSS fallback when YouTube API quota/handles fail.
CHANNEL_IDS: dict[str, str] = {
    'CNBC-TV18': 'UCmRbHAgG2k2vDUvb3xsEunQ',
    'ET NOW': 'UCI_mwTKUhicNzFrhm33MzBQ',
    'NDTV Profit': 'UCZFMm1mMw0F81Z37aaEzTUA',
    'Zee Business': 'UCkXopQ3ubd-rnXnStZqCl2w',
    'Moneycontrol': 'UCnhUiJ_-DRTP6w51LCQgJRQ',
    'Business Today': 'UCaPHWiExfUWaKsUtENLCv5w',
    'NSE India': 'UCjDnt2b8-I7bu4MRF9Uwf-A',
}

SEARCH_TERMS = [
    'stock market live india',
    'nifty live',
    'sensex live',
    'CNBC TV18 live stock market',
    'ET Now market live',
    'NDTV Profit market live',
    'Zee Business stock market live',
    'market closing bell india',
    'nifty bank nifty analysis today',
]

SYMBOL_KEYWORDS = [
    'NIFTY', 'SENSEX', 'BANKNIFTY', 'BANK NIFTY', 'NIFTY 50', 'NIFTY50',
    'RELIANCE', 'TCS', 'INFY', 'INFOSYS', 'HDFC', 'HDFCBANK', 'ICICI', 'SBIN',
    'TATA', 'ADANI', 'MARUTI', 'ITC', 'WIPRO', 'AXIS', 'KOTAK', 'BAJAJ',
]

TOPIC_PATTERNS: list[tuple[str, str]] = [
    (r'\bmarket live\b', 'market live'),
    (r'\bclosing bell\b', 'closing bell'),
    (r'\bstock picks?\b', 'stock picks'),
    (r'\bintraday\b', 'intraday'),
    (r'\boption chain\b', 'option chain'),
    (r'\bpre.?market\b', 'pre market'),
    (r'\bpost.?market\b', 'post market'),
    (r'\bstock market\b', 'stock market'),
    (r'\bshare market\b', 'share market'),
    (r'\bmarket analysis\b', 'market analysis'),
    (r'\bsector\b', 'sector'),
    (r'\bipo\b', 'ipo'),
]

RELEVANCE_BOOST = [
    ('nifty', 2.0), ('sensex', 2.0), ('banknifty', 2.0), ('bank nifty', 2.0),
    ('stock market', 2.5), ('share market', 2.0), ('market live', 3.0),
    ('closing bell', 2.5), ('intraday', 1.5), ('option chain', 1.5),
    ('stocks to buy', 2.0), ('nse', 1.0), ('bse', 1.0),
]

REJECT_PATTERNS = [
    r'\b(cricket|ipl|movie|song|trailer|recipe|makeup|vlog)\b',
    r'\b(fashion|celebrity gossip|reality show)\b',
]

POLITICS_UNLESS_MARKET = [
    r'\b(election rally|campaign speech|political debate)\b',
]

MIN_RELEVANCE = 3.0
RECENT_HOURS = 72
LIVE_RECENT_MINUTES = 360


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip().replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _is_likely_english(text: str) -> bool:
    if not text:
        return False
    latin = sum(1 for c in text if c.isascii())
    return (latin / max(len(text), 1)) > 0.65


def _extract_symbols(text: str) -> list[str]:
    upper = (text or '').upper()
    found: list[str] = []
    for sym in SYMBOL_KEYWORDS:
        pattern = r'\b' + re.escape(sym.upper()) + r'\b'
        if re.search(pattern, upper):
            label = sym.replace(' ', '')
            if label not in found:
                found.append(label)
    return found[:8]


def _extract_topics(text: str) -> list[str]:
    lower = (text or '').lower()
    topics: list[str] = []
    for pattern, label in TOPIC_PATTERNS:
        if re.search(pattern, lower) and label not in topics:
            topics.append(label)
    return topics[:6]


def score_relevance(title: str, channel: str, description: str = '') -> float:
    blob = f'{title} {channel} {description}'.lower()
    score = 0.0
    for term, weight in RELEVANCE_BOOST:
        if term in blob:
            score += weight
    if any(name.lower() in blob for name in CHANNEL_HANDLES):
        score += 1.5
    if _extract_symbols(blob):
        score += 1.0
    for pattern in REJECT_PATTERNS:
        if re.search(pattern, blob, re.I):
            score -= 4.0
    for pattern in POLITICS_UNLESS_MARKET:
        if re.search(pattern, blob, re.I) and score < 4:
            score -= 3.0
    return max(0.0, min(10.0, round(score, 2)))


def is_market_relevant(title: str, channel: str, description: str = '', *, min_score: float = MIN_RELEVANCE) -> bool:
    return score_relevance(title, channel, description) >= min_score


def _normalize_video(
    *,
    title: str,
    channel: str,
    url: str,
    published_at: str,
    is_live: bool | None,
    description: str = '',
    video_id: str = '',
) -> dict[str, Any] | None:
    if not url or not title:
        return None
    if 'youtube.com' not in url and 'youtu.be' not in url and 'google.com' not in url:
        return None
    if not _is_likely_english(title):
        return None
    relevance = score_relevance(title, channel, description)
    if relevance < MIN_RELEVANCE:
        return None
    return {
        'title': title.strip(),
        'channel': channel.strip() or 'Unknown',
        'url': url.strip(),
        'published_at': published_at or '',
        'is_live': is_live,
        'symbols': _extract_symbols(f'{title} {description}'),
        'topics': _extract_topics(f'{title} {description}'),
        'relevance_score': relevance,
        'video_id': video_id,
    }


def _dedupe_videos(videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for vid in videos:
        key = vid.get('video_id') or vid.get('url') or vid.get('title')
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(vid)
    out.sort(key=lambda v: (_parse_iso(v.get('published_at')) or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    return out


def _resolve_handle(api_key: str, handle: str) -> tuple[str | None, str | None]:
    try:
        from googleapiclient.discovery import build

        youtube = build('youtube', 'v3', developerKey=api_key)
        response = youtube.channels().list(
            part='id,snippet',
            forHandle=handle.lstrip('@'),
        ).execute()
        items = response.get('items') or []
        if not items:
            return None, None
        return items[0]['id'], items[0]['snippet'].get('title')
    except Exception:
        return None, None


def _fetch_channel_videos_api(api_key: str, channel_id: str, channel_name: str, *, hours_back: int = RECENT_HOURS) -> list[dict[str, Any]]:
    try:
        from googleapiclient.discovery import build

        youtube = build('youtube', 'v3', developerKey=api_key)
        published_after = (_now_utc() - timedelta(hours=hours_back)).strftime('%Y-%m-%dT%H:%M:%SZ')
        response = youtube.search().list(
            part='snippet',
            channelId=channel_id,
            maxResults=15,
            order='date',
            type='video',
            publishedAfter=published_after,
            relevanceLanguage='en',
        ).execute()
        videos: list[dict[str, Any]] = []
        for item in response.get('items') or []:
            snippet = item.get('snippet') or {}
            vid_id = (item.get('id') or {}).get('videoId', '')
            live_flag = snippet.get('liveBroadcastContent', 'none')
            is_live = True if live_flag == 'live' else (False if live_flag == 'none' else None)
            normalized = _normalize_video(
                title=snippet.get('title', ''),
                channel=channel_name,
                url=f'https://www.youtube.com/watch?v={vid_id}',
                published_at=snippet.get('publishedAt', ''),
                is_live=is_live,
                description=snippet.get('description', ''),
                video_id=vid_id,
            )
            if normalized:
                videos.append(normalized)
        return videos
    except Exception:
        return []


def _search_videos_api(api_key: str, query: str, *, max_results: int = 8) -> list[dict[str, Any]]:
    try:
        from googleapiclient.discovery import build

        youtube = build('youtube', 'v3', developerKey=api_key)
        published_after = (_now_utc() - timedelta(hours=RECENT_HOURS)).strftime('%Y-%m-%dT%H:%M:%SZ')
        response = youtube.search().list(
            part='snippet',
            q=query,
            maxResults=max_results,
            order='date',
            type='video',
            publishedAfter=published_after,
            relevanceLanguage='en',
            regionCode='IN',
        ).execute()
        videos: list[dict[str, Any]] = []
        for item in response.get('items') or []:
            snippet = item.get('snippet') or {}
            vid_id = (item.get('id') or {}).get('videoId', '')
            channel = snippet.get('channelTitle', 'Unknown')
            live_flag = snippet.get('liveBroadcastContent', 'none')
            is_live = True if live_flag == 'live' else (False if live_flag == 'none' else None)
            normalized = _normalize_video(
                title=snippet.get('title', ''),
                channel=channel,
                url=f'https://www.youtube.com/watch?v={vid_id}',
                published_at=snippet.get('publishedAt', ''),
                is_live=is_live,
                description=snippet.get('description', ''),
                video_id=vid_id,
            )
            if normalized:
                videos.append(normalized)
        return videos
    except Exception:
        return []


def _collect_via_youtube_api(*, limit: int, verbose: bool = False) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    if not YOUTUBE_API_KEY:
        return [], ['youtube_api_key_missing']
    videos: list[dict[str, Any]] = []
    resolved = 0
    for name, handle in CHANNEL_HANDLES.items():
        channel_id, _title = _resolve_handle(YOUTUBE_API_KEY, handle)
        if not channel_id:
            warnings.append(f'channel_unresolved:{name}')
            continue
        resolved += 1
        batch = _fetch_channel_videos_api(YOUTUBE_API_KEY, channel_id, name)
        videos.extend(batch)
        if verbose:
            print(f'  [youtube] {name}: {len(batch)} videos')
    for term in SEARCH_TERMS[:6]:
        batch = _search_videos_api(YOUTUBE_API_KEY, term, max_results=5)
        videos.extend(batch)
        if verbose:
            print(f'  [youtube-search] {term}: {len(batch)} videos')
    if resolved == 0:
        warnings.append('no_channels_resolved')
    return _dedupe_videos(videos)[:limit], warnings


def _fetch_channel_rss(channel_id: str, channel_name: str) -> list[dict[str, Any]]:
    url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'
    try:
        resp = requests.get(url, timeout=20, headers={'User-Agent': 'TradingCopilot/1.0'})
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception:
        return []
    videos: list[dict[str, Any]] = []
    cutoff = _now_utc() - timedelta(hours=RECENT_HOURS)
    for entry in feed.entries[:20]:
        published = entry.get('published') or entry.get('updated') or ''
        pub_dt = _parse_iso(published)
        if pub_dt and pub_dt < cutoff:
            continue
        link = entry.get('link') or ''
        vid_id = ''
        if 'watch?v=' in link:
            vid_id = link.split('watch?v=')[-1].split('&')[0]
        title = entry.get('title', '')
        desc = entry.get('summary', '') or entry.get('description', '')
        is_live = None
        if 'live' in title.lower() or 'live' in (desc or '').lower()[:120]:
            is_live = None
        normalized = _normalize_video(
            title=title,
            channel=channel_name,
            url=link,
            published_at=published,
            is_live=is_live,
            description=desc,
            video_id=vid_id,
        )
        if normalized:
            videos.append(normalized)
    return videos


def _collect_via_rss(*, limit: int, verbose: bool = False) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    videos: list[dict[str, Any]] = []
    channel_ids: dict[str, str] = dict(CHANNEL_IDS)

    if YOUTUBE_API_KEY:
        for name, handle in CHANNEL_HANDLES.items():
            if name in channel_ids:
                continue
            channel_id, _ = _resolve_handle(YOUTUBE_API_KEY, handle)
            if channel_id:
                channel_ids[name] = channel_id

    for name, channel_id in channel_ids.items():
        batch = _fetch_channel_rss(channel_id, name)
        videos.extend(batch)
        if verbose:
            print(f'  [rss] {name}: {len(batch)} videos')

    if not videos:
        warnings.append('channel_rss_empty')
        for query in SEARCH_TERMS[:4]:
            g_url = (
                'https://news.google.com/rss/search?q='
                + quote_plus(f'{query} site:youtube.com')
                + '&hl=en-IN&gl=IN&ceid=IN:en'
            )
            try:
                feed = feedparser.parse(g_url)
                for entry in feed.entries[:10]:
                    title = entry.get('title', '')
                    link = entry.get('link') or ''
                    if 'youtube' not in title.lower() and 'youtube.com' not in link:
                        continue
                    published = entry.get('published') or entry.get('updated') or ''
                    source = entry.get('source', {}).get('title', 'YouTube')
                    normalized = _normalize_video(
                        title=title,
                        channel=source or 'YouTube',
                        url=link,
                        published_at=published,
                        is_live=None,
                        description=entry.get('summary', ''),
                    )
                    if normalized:
                        videos.append(normalized)
            except Exception as exc:
                warnings.append(f'google_rss_error:{exc}')

    return _dedupe_videos(videos)[:limit], warnings


def _collect_via_ytdlp(*, limit: int, verbose: bool = False) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    ytdlp = shutil.which('yt-dlp')
    if not ytdlp:
        return [], ['yt_dlp_not_installed']
    videos: list[dict[str, Any]] = []
    for query in SEARCH_TERMS[:5]:
        cmd = [
            ytdlp,
            f'ytsearch{min(8, limit)}:{query}',
            '--flat-playlist',
            '--dump-single-json',
            '--skip-download',
            '--no-warnings',
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90, check=False)
            if proc.returncode != 0:
                warnings.append(f'ytdlp_search_failed:{query}')
                continue
            payload = json.loads(proc.stdout or '{}')
            entries = payload.get('entries') or []
            if isinstance(entries, dict):
                entries = [entries]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                url = entry.get('url') or entry.get('webpage_url') or ''
                if url and not url.startswith('http'):
                    url = f'https://www.youtube.com/watch?v={url}'
                normalized = _normalize_video(
                    title=entry.get('title', ''),
                    channel=entry.get('channel') or entry.get('uploader') or 'YouTube',
                    url=url,
                    published_at=entry.get('upload_date', ''),
                    is_live=entry.get('is_live'),
                    description=entry.get('description', ''),
                    video_id=str(entry.get('id') or ''),
                )
                if normalized:
                    videos.append(normalized)
            if verbose:
                print(f'  [yt-dlp] {query}: {len(entries)} raw')
        except Exception as exc:
            warnings.append(f'ytdlp_error:{exc}')
    return _dedupe_videos(videos)[:limit], warnings


def _build_summary(videos: list[dict[str, Any]]) -> dict[str, Any]:
    now = _now_utc()
    recent_cutoff = now - timedelta(minutes=LIVE_RECENT_MINUTES)
    live_count = sum(1 for v in videos if v.get('is_live') is True)
    recent_count = 0
    for v in videos:
        pub = _parse_iso(v.get('published_at'))
        if pub and pub >= recent_cutoff:
            recent_count += 1
    sym_counter: Counter[str] = Counter()
    topic_counter: Counter[str] = Counter()
    for v in videos:
        sym_counter.update(v.get('symbols') or [])
        topic_counter.update(v.get('topics') or [])
    return {
        'total': len(videos),
        'live_count': live_count,
        'recent_count': recent_count,
        'top_symbols': [s for s, _ in sym_counter.most_common(10)],
        'top_topics': [t for t, _ in topic_counter.most_common(10)],
    }


def load_cached_tv_intelligence() -> dict[str, Any]:
    """Read cached TV intelligence from disk; map legacy youtube_feed.json if needed."""
    legacy_file = DATA_DIR / 'youtube_feed.json'
    if not OUTPUT_FILE.is_file():
        if not legacy_file.is_file():
            return {
                'ok': False,
                'generated_at': None,
                'source': 'none',
                'videos': [],
                'summary': {'total': 0, 'live_count': 0, 'recent_count': 0, 'top_symbols': [], 'top_topics': []},
                'warnings': ['file_not_found'],
            }
        try:
            legacy = json.loads(legacy_file.read_text(encoding='utf-8'))
        except Exception as exc:
            return {'ok': False, 'error': str(exc), 'videos': [], 'summary': {}}
        videos = []
        for key in ('live_now', 'recent_videos', 'all_videos'):
            for item in legacy.get(key) or []:
                if isinstance(item, dict):
                    videos.append({
                        'title': item.get('title', ''),
                        'channel': item.get('channel', ''),
                        'url': item.get('url', ''),
                        'published_at': item.get('published_at', ''),
                        'is_live': item.get('live_broadcast') == 'live',
                        'symbols': [],
                        'topics': [],
                        'relevance_score': 5.0,
                    })
        return {
            'ok': True,
            'generated_at': legacy.get('timestamp'),
            'source': 'legacy',
            'videos': videos,
            'summary': {
                'total': len(videos),
                'live_count': legacy.get('live_streams') or 0,
                'recent_count': legacy.get('recent_videos_3h') or 0,
                'top_symbols': list((legacy.get('stock_mentions') or {}).keys())[:10],
                'top_topics': [],
            },
            'warnings': [],
        }
    try:
        data = json.loads(OUTPUT_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {'ok': False, 'videos': [], 'summary': {}}
    except Exception as exc:
        return {'ok': False, 'error': str(exc), 'videos': [], 'summary': {}}


def collect_tv_intelligence(*, dry_run: bool = False, limit: int = 30, verbose: bool = False) -> dict[str, Any]:
    """Collect TV intelligence and write data/tv_intelligence.json."""
    limit = max(1, min(int(limit or 30), 100))
    warnings: list[str] = []
    source = 'none'
    videos: list[dict[str, Any]] = []

    if verbose:
        print('[TV_INTEL] started')

    if YOUTUBE_API_KEY:
        batch, w = _collect_via_youtube_api(limit=limit, verbose=verbose)
        warnings.extend(w)
        if batch:
            videos = batch
            source = 'youtube'

    if not videos:
        batch, w = _collect_via_rss(limit=limit, verbose=verbose)
        warnings.extend(w)
        if batch:
            videos = batch
            source = 'rss' if source == 'none' else source

    if not dry_run and not videos:
        batch, w = _collect_via_ytdlp(limit=limit, verbose=verbose)
        warnings.extend(w)
        if batch:
            videos = batch
            source = 'yt-dlp'

    summary = _build_summary(videos)
    payload: dict[str, Any] = {
        'ok': True,
        'generated_at': _now_utc().isoformat(),
        'source': source if videos else 'none',
        'videos': videos,
        'summary': summary,
        'warnings': warnings,
    }
    if not videos:
        payload['ok'] = True
        if not warnings:
            warnings.append('no_videos_found')

    if verbose:
        print(f'[TV_INTEL] source={payload["source"]}')
        print(f'[TV_INTEL] videos={summary["total"]}')
        print(f'[TV_INTEL] live={summary["live_count"]}')
        print(f'[TV_INTEL] recent={summary["recent_count"]}')
        print(f'[TV_INTEL] output={OUTPUT_FILE}')

    if not dry_run:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_json(OUTPUT_FILE, payload)

    return payload


def run_tv_collector() -> dict[str, Any]:
    """Entry point for refresh-local-intelligence scope=tv."""
    return collect_tv_intelligence(dry_run=False, limit=30, verbose=False)


if __name__ == '__main__':
    result = collect_tv_intelligence(verbose=True)
    print(json.dumps({'source': result.get('source'), 'videos': result.get('summary', {}).get('total')}, indent=2))
