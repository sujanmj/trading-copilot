"""
Railway-aware data path helper (Stage 46E).

Use get_data_path() for new Railway scripts and cron jobs.
Legacy code may still use backend.utils.config.DATA_DIR directly.
"""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_RAILWAY_DATA_DIR = Path('/app/data')

PROTECTED_DB_NAMES = (
    'trading_history.db',
    'canonical_market_memory.db',
    'historical_market_memory.db',
)


def is_railway_data_mode() -> bool:
    """True when data should resolve under the Railway volume."""
    if os.environ.get('RAILWAY_DATA_DIR', '').strip():
        return True
    if os.environ.get('APP_MODE', '').strip().lower() == 'railway':
        return True
    if os.environ.get('RAILWAY_ENVIRONMENT', '').strip():
        return True
    return False


def get_data_root() -> Path:
    """Return mounted Railway volume path or repo-local data/."""
    railway_dir = os.environ.get('RAILWAY_DATA_DIR', '').strip()
    if railway_dir:
        return Path(railway_dir)
    if is_railway_data_mode():
        return DEFAULT_RAILWAY_DATA_DIR
    return PROJECT_ROOT / 'data'


def ensure_data_root_safe() -> Path:
    """Create data root if missing; never delete or overwrite existing DB files."""
    root = get_data_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / 'backups').mkdir(parents=True, exist_ok=True)
    return root


def data_preserved() -> bool:
    """True when the data root exists and existing files were not reset."""
    root = get_data_root()
    if not root.is_dir():
        return False
    for name in PROTECTED_DB_NAMES:
        db_path = root / name
        if db_path.is_file() and db_path.stat().st_size > 0:
            return True
    if any(root.glob('*.json')):
        return True
    if (root / 'reports').is_dir() and any((root / 'reports').iterdir()):
        return True
    return root.is_dir()


def log_data_startup() -> None:
    """Log data root and preservation status on startup."""
    root = ensure_data_root_safe()
    print(f'[DATA_ROOT] {root.as_posix()}', flush=True)
    print('[DATA_PRESERVE] existing data preserved', flush=True)


def get_data_path(relative: str) -> Path:
    """
    Resolve a path under the data root and ensure parent directories exist.

    Never deletes or truncates an existing DB file at the resolved path.
    """
    rel = relative.replace('\\', '/').lstrip('/')
    path = get_data_root() / rel
    if path.name.endswith('.db') and path.is_file() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
