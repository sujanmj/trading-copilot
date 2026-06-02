#!/usr/bin/env python3
"""Unit tests for TV intelligence relevance filtering and schema."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _fail(msg: str) -> int:
    print(f'TV_INTELLIGENCE_TEST_FAIL: {msg}', file=sys.stderr)
    return 1


def main() -> int:
    from backend.collectors import tv_intelligence_collector as tv

    samples = [
        {
            'title': 'NIFTY SENSEX Live | Stock Market Live Today | Closing Bell',
            'channel': 'CNBC-TV18',
            'url': 'https://www.youtube.com/watch?v=abc123',
            'published_at': '2026-05-30T09:00:00Z',
            'is_live': True,
            'description': 'Bank Nifty intraday analysis and stock picks',
        },
        {
            'title': 'Bollywood Movie Review 2026',
            'channel': 'Entertainment Hub',
            'url': 'https://www.youtube.com/watch?v=xyz999',
            'published_at': '2026-05-30T08:00:00Z',
            'is_live': False,
            'description': 'Latest movie trailer',
        },
        {
            'title': 'Election Rally Highlights',
            'channel': 'News Channel',
            'url': 'https://www.youtube.com/watch?v=pol111',
            'published_at': '2026-05-30T07:00:00Z',
            'is_live': False,
            'description': 'Campaign speech only',
        },
    ]

    kept = []
    for sample in samples:
        if not tv.is_market_relevant(sample['title'], sample['channel'], sample['description']):
            continue
        normalized = tv._normalize_video(
            title=sample['title'],
            channel=sample['channel'],
            url=sample['url'],
            published_at=sample['published_at'],
            is_live=sample['is_live'],
            description=sample['description'],
            video_id='test',
        )
        if normalized:
            kept.append(normalized)

    if len(kept) != 1:
        return _fail(f'expected 1 relevant video, got {len(kept)}')

    video = kept[0]
    required = ('title', 'channel', 'url', 'published_at', 'is_live', 'symbols', 'topics', 'relevance_score')
    for key in required:
        if key not in video:
            return _fail(f'missing key in normalized video: {key}')

    if 'NIFTY' not in video['symbols'] and 'SENSEX' not in video['symbols']:
        return _fail('expected market symbols in relevant video')

    if video['relevance_score'] < tv.MIN_RELEVANCE:
        return _fail('relevance score below minimum')

    payload = tv.collect_tv_intelligence(dry_run=True, limit=3, verbose=False)
    for key in ('ok', 'generated_at', 'source', 'videos', 'summary', 'warnings'):
        if key not in payload:
            return _fail(f'missing payload key: {key}')
    summary = payload['summary']
    for key in ('total', 'live_count', 'recent_count', 'top_symbols', 'top_topics'):
        if key not in summary:
            return _fail(f'missing summary key: {key}')

    print('TV_INTELLIGENCE_TEST_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
