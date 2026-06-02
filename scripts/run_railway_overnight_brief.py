#!/usr/bin/env python3
"""Railway cron: overnight/global brief — one shot, exit (Stage 46A)."""

from __future__ import annotations

import os
import sys

_RAILWAY_CRON_DEFAULTS = {
    'LOCAL_DEV_MODE': '0',
    'LOCAL_ONLY': '0',
    'APP_MODE': 'railway',
    'TZ': 'Asia/Kolkata',
    'DISABLE_TRADE_EXECUTION': '1',
    'TELEGRAM_TRADE_COMMANDS_ENABLED': '0',
}
for _key, _val in _RAILWAY_CRON_DEFAULTS.items():
    os.environ.setdefault(_key, _val)

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(Path.cwd().resolve()) != str(PROJECT_ROOT.resolve()):
    os.chdir(PROJECT_ROOT)

from backend.utils.bootstrap import setup_project_path

setup_project_path()


def main() -> int:
    from backend.storage.data_paths import get_data_root
    from backend.telegram.telegram_brief_scheduler import build_overnight_brief_text, send_brief

    token_set = bool(os.environ.get('TELEGRAM_BOT_TOKEN', '').strip())
    chat_set = bool(os.environ.get('TELEGRAM_CHAT_ID', '').strip())
    print('[RAILWAY_CRON] job=overnight_brief', flush=True)
    print(f'[RAILWAY_CRON] data_root={get_data_root()}', flush=True)
    print(f'[RAILWAY_CRON] credentials_present token={token_set} chat={chat_set}', flush=True)

    if not token_set or not chat_set:
        preview = build_overnight_brief_text()
        print(f'[RAILWAY_CRON] dry_run_chars={len(preview)}', flush=True)
        print('[RAILWAY_CRON] skipped_send=missing_credentials', flush=True)
        return 0

    ok = send_brief('overnight')
    print(f'[RAILWAY_CRON] sent={"yes" if ok else "no"}', flush=True)
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
