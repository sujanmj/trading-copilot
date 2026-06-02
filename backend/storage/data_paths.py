"""
Railway-aware data path helper (Stage 46A).

Use get_data_path() for new Railway scripts and cron jobs.
Legacy code may still use backend.utils.config.DATA_DIR directly.
"""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent


def get_data_root() -> Path:
    """Return mounted Railway volume path or repo-local data/."""
    railway_dir = os.environ.get('RAILWAY_DATA_DIR', '').strip()
    if railway_dir:
        return Path(railway_dir)
    return PROJECT_ROOT / 'data'


def get_data_path(relative: str) -> Path:
    """
    Resolve a path under the data root and ensure parent directories exist.

    Example: get_data_path('runtime/current_snapshot.json')
    """
    rel = relative.replace('\\', '/').lstrip('/')
    path = get_data_root() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
