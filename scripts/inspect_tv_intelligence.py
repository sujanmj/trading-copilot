#!/usr/bin/env python3
"""Inspect cached TV intelligence file."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)

from backend.utils.config import DATA_DIR

OUTPUT = DATA_DIR / 'tv_intelligence.json'


def main() -> int:
    exists = OUTPUT.is_file()
    print(f'[TV_INTEL] exists={exists}')
    if not exists:
        return 0
    data = json.loads(OUTPUT.read_text(encoding='utf-8'))
    videos = data.get('videos') or []
    summary = data.get('summary') or {}
    channels = Counter(v.get('channel') or 'Unknown' for v in videos if isinstance(v, dict))
    symbols = summary.get('top_symbols') or []
    print(f'[TV_INTEL] videos={summary.get("total", len(videos))}')
    print(f'[TV_INTEL] live={summary.get("live_count", 0)}')
    print(f'[TV_INTEL] recent={summary.get("recent_count", 0)}')
    print(f'[TV_INTEL] top_channels={list(channels.most_common(5))}')
    print(f'[TV_INTEL] top_symbols={symbols[:10]}')
    print(f'[TV_INTEL] source={data.get("source")}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
