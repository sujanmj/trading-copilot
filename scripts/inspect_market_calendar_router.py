#!/usr/bin/env python3
"""
Compact CLI for market session router.

Usage:
  python scripts/inspect_market_calendar_router.py
  python scripts/inspect_market_calendar_router.py --now 2026-06-02T05:00:00+00:00
  python scripts/inspect_market_calendar_router.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    import os

    os.chdir(PROJECT_ROOT)


def _parse_now(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description='Inspect market session router (read-only)')
    parser.add_argument('--now', help='ISO timestamp (UTC) to evaluate')
    parser.add_argument('--json', action='store_true', help='Print full JSON payload')
    args = parser.parse_args()

    from backend.analytics.market_calendar_router import get_market_router_payload

    now_utc = _parse_now(args.now)
    payload = get_market_router_payload(now_utc)

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return 0

    india = payload.get('india') or {}
    usa = payload.get('usa') or {}
    next_in = payload.get('next_india_open') or {}
    next_us = payload.get('next_usa_open') or {}

    print(f"[MARKET_ROUTER] active_mode={payload.get('active_mode')}")
    print(f"[MARKET_ROUTER] india_session={payload.get('india_session')} ({payload.get('india_session_label')})")
    print(f"[MARKET_ROUTER] usa_session={payload.get('usa_session')} ({payload.get('usa_session_label')})")
    print(f"[MARKET_ROUTER] recommended_focus={payload.get('recommended_focus')}")
    print(f"[MARKET_ROUTER] next_india_open={next_in.get('next_open_local') or next_in.get('next_open_utc')}")
    print(f"[MARKET_ROUTER] next_usa_open={next_us.get('next_open_local') or next_us.get('next_open_utc')}")
    print(f"[MARKET_ROUTER] india_local={india.get('local_time')}")
    print(f"[MARKET_ROUTER] usa_local={usa.get('local_time')}")
    warnings = payload.get('warnings') or []
    print(f"[MARKET_ROUTER] warnings={warnings}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
