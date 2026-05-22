"""
YOUTUBE TRACKER (v2)
Auto-resolves channel handles to IDs
Monitors financial news channels for new videos
"""

import os
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv
from collections import Counter
import re

env_path = Path(__file__).parent.parent / 'config' / 'keys.env'
load_dotenv(env_path)

YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')

# ─────────────────────────────────────
# CHANNELS - Using @handles (auto-resolved)
# ─────────────────────────────────────
CHANNEL_HANDLES = {
    'NDTV Profit':     '@NDTVProfitIndia',
    'ET Now':          '@ETNOW',
    'CNBC-TV18':       'UC-xhdmIqKKDVpW1FzRXbFkA',
    'CNBC Awaaz':      '@CNBCAwaaz',
    'Moneycontrol':    '@moneycontrol',
    'Zee Business':    '@ZeeBusiness',
    'Bloomberg':       '@markets',
    'CNBC':            '@CNBC',
    'Yahoo Finance':   '@YahooFinance',
}

STOCK_KEYWORDS = [
    'RELIANCE', 'TCS', 'INFOSYS', 'INFY', 'HDFC', 'ICICI', 'SBI', 'AXIS',
    'KOTAK', 'BAJAJ', 'WIPRO', 'HCLTECH', 'TATA STEEL', 'TATA MOTORS',
    'MARUTI', 'ADANI', 'ASIAN PAINTS', 'NESTLE', 'HUL', 'ITC', 'TITAN',
    'SUN PHARMA', 'BHARTI AIRTEL', 'VEDANTA', 'NIFTY', 'SENSEX', 'BANK NIFTY',
    'APPLE', 'NVIDIA', 'TESLA', 'GOOGLE', 'MICROSOFT', 'META', 'AMAZON',
    'GOLD', 'SILVER', 'CRUDE', 'OIL', 'BITCOIN', 'IPO', 'FED', 'RBI'
]


def resolve_handle_to_channel_id(api_key, handle):
    """Convert @handle to channel ID using search"""
    try:
        from googleapiclient.discovery import build

        youtube = build('youtube', 'v3', developerKey=api_key)

        # Use forHandle parameter (newer method)
        request = youtube.channels().list(
            part='id,snippet',
            forHandle=handle.lstrip('@')
        )
        response = request.execute()

        if response.get('items'):
            channel_id = response['items'][0]['id']
            channel_title = response['items'][0]['snippet']['title']
            return channel_id, channel_title
        return None, None
    except Exception as e:
        print(f"  WARN handle resolve {handle}: {str(e)[:60]}")
        return None, None


def fetch_channel_videos(api_key, channel_id, channel_name, hours_back=48):
    """Fetch recent videos from a channel"""
    try:
        from googleapiclient.discovery import build

        youtube = build('youtube', 'v3', developerKey=api_key)

        # Timezone-aware UTC time
        published_after = (
            datetime.now(timezone.utc) - timedelta(hours=hours_back)
        ).strftime('%Y-%m-%dT%H:%M:%SZ')

        request = youtube.search().list(
            part='snippet',
            channelId=channel_id,
            maxResults=20,
            order='date',
            type='video',
            publishedAfter=published_after,
            relevanceLanguage='en',  # Prefer English videos
        )
        response = request.execute()

        videos = []
        for item in response.get('items', []):
            snippet = item.get('snippet', {})
            title = snippet.get('title', '')

            # Skip non-English videos (basic filter)
            if not is_likely_english(title):
                continue

            videos.append({
                'channel': channel_name,
                'video_id': item.get('id', {}).get('videoId', ''),
                'title': title,
                'description': snippet.get('description', '')[:300],
                'published_at': snippet.get('publishedAt', ''),
                'url': f"https://www.youtube.com/watch?v={item.get('id', {}).get('videoId', '')}",
                'live_broadcast': snippet.get('liveBroadcastContent', 'none'),
            })

        return videos

    except Exception as e:
        print(f"  WARN {channel_name}: {str(e)[:80]}")
        return []


def is_likely_english(text):
    """Basic check - skip videos with too many non-Latin characters"""
    if not text:
        return False
    latin_chars = sum(1 for c in text if c.isascii())
    total_chars = len(text)
    if total_chars == 0:
        return False
    return (latin_chars / total_chars) > 0.7


def detect_video_topics(videos):
    stock_mentions = Counter()
    channel_stocks = {}

    for vid in videos:
        text = (vid.get('title', '') + ' ' + vid.get('description', '')).upper()
        channel = vid.get('channel', 'Unknown')

        if channel not in channel_stocks:
            channel_stocks[channel] = set()

        for stock in STOCK_KEYWORDS:
            pattern = r'\b' + re.escape(stock) + r'\b'
            if re.search(pattern, text):
                stock_mentions[stock] += 1
                channel_stocks[channel].add(stock)

    return stock_mentions, channel_stocks


def detect_cross_channel_buzz(channel_stocks):
    stock_to_channels = {}
    for channel, stocks in channel_stocks.items():
        for stock in stocks:
            if stock not in stock_to_channels:
                stock_to_channels[stock] = []
            stock_to_channels[stock].append(channel)

    cross_buzz = []
    for stock, channels in stock_to_channels.items():
        if len(channels) >= 2:
            cross_buzz.append({
                'stock': stock,
                'channel_count': len(channels),
                'channels': channels,
                'signal_strength': 'STRONG' if len(channels) >= 3 else 'MEDIUM'
            })

    cross_buzz.sort(key=lambda x: x['channel_count'], reverse=True)
    return cross_buzz


def detect_live_streams(videos):
    return [v for v in videos if v.get('live_broadcast') == 'live']


def detect_recent_videos(videos, minutes=180):  # last 3 hours
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    recent = []
    for vid in videos:
        try:
            pub_str = vid.get('published_at', '').replace('Z', '+00:00')
            pub_time = datetime.fromisoformat(pub_str)
            if pub_time > cutoff:
                recent.append(vid)
        except:
            pass
    return recent


def collect_all_youtube():
    print("\n" + "=" * 60)
    print("YOUTUBE TRACKER v2 - STARTED")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if not YOUTUBE_API_KEY:
        print("ERROR: YOUTUBE_API_KEY not found in keys.env")
        return None

    # ─── Step 1: Resolve all handles to channel IDs ───
    print("\n[STEP 1] Resolving channel handles to IDs...")
    print("-" * 60)

    resolved_channels = {}
    for name, handle in CHANNEL_HANDLES.items():
        channel_id, channel_title = resolve_handle_to_channel_id(YOUTUBE_API_KEY, handle)
        if channel_id:
            resolved_channels[name] = {
                'id': channel_id,
                'handle': handle,
                'actual_title': channel_title
            }
            print(f"  OK   {name:18s} -> {channel_id} ({channel_title})")
        else:
            print(f"  FAIL {name:18s} could not resolve {handle}")

    if not resolved_channels:
        print("\nERROR: No channels could be resolved")
        return None

    # ─── Step 2: Fetch videos from each ───
    print(f"\n[STEP 2] Fetching videos (last 48 hours, English only)...")
    print("-" * 60)

    all_videos = []
    for name, info in resolved_channels.items():
        videos = fetch_channel_videos(YOUTUBE_API_KEY, info['id'], name)
        print(f"  {name:18s} {len(videos):3d} videos")
        all_videos.extend(videos)

    print(f"\n[TOTAL] Videos fetched: {len(all_videos)}")

    if not all_videos:
        print("\nWARN: No videos fetched.")
        return None

    # ─── Step 3: Analyze ───
    stock_mentions, channel_stocks = detect_video_topics(all_videos)
    cross_buzz = detect_cross_channel_buzz(channel_stocks)
    live_streams = detect_live_streams(all_videos)
    recent_videos = detect_recent_videos(all_videos, minutes=180)

    # ─── Print summary ───
    print("\n" + "=" * 60)
    print("YOUTUBE INTELLIGENCE SUMMARY")
    print("=" * 60)

    if live_streams:
        print(f"\nLIVE NOW ({len(live_streams)}):")
        for v in live_streams[:5]:
            print(f"  [{v['channel']}] {v['title'][:65]}")
    else:
        print("\nNo live streams currently active")

    print(f"\nRECENT VIDEOS (last 3 hours): {len(recent_videos)}")
    for v in recent_videos[:8]:
        print(f"  [{v['channel'][:15]:15s}] {v['title'][:60]}")

    print(f"\nTOP MENTIONED STOCKS ON TV:")
    if stock_mentions:
        for stock, count in stock_mentions.most_common(15):
            print(f"  {stock:20s} {count} videos")
    else:
        print("  No stocks mentioned in titles/descriptions")

    if cross_buzz:
        print(f"\nCROSS-CHANNEL BUZZ:")
        for cb in cross_buzz[:10]:
            channels_str = ', '.join(cb['channels'][:3])
            print(f"  [{cb['signal_strength']}] {cb['stock']:15s} on {cb['channel_count']} channels ({channels_str})")
    else:
        print("\nNo cross-channel buzz detected yet")

    # ─── Save ───
    output = {
        'timestamp': datetime.now().isoformat(),
        'collection_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'resolved_channels': {k: v['actual_title'] for k, v in resolved_channels.items()},
        'total_videos': len(all_videos),
        'live_streams': len(live_streams),
        'recent_videos_3h': len(recent_videos),
        'stock_mentions': dict(stock_mentions.most_common(20)),
        'cross_channel_buzz': cross_buzz,
        'live_now': live_streams[:10],
        'recent_videos': recent_videos[:25],
        'all_videos': all_videos[:50]
    }

    data_dir = Path(__file__).parent.parent / 'data'
    data_dir.mkdir(exist_ok=True)
    output_file = data_dir / 'youtube_feed.json'

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, default=str, ensure_ascii=True)

    print(f"\nSaved to: {output_file}")
    print("=" * 60 + "\n")

    return output


if __name__ == "__main__":
    print("Starting YouTube tracker v2...")
    try:
        collect_all_youtube()
        print("Done!")
    except Exception as e:
        import traceback
        print(f"ERROR: {e}")
        traceback.print_exc()