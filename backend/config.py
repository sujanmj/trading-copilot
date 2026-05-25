"""
Central configuration — cloud-first (Railway), env-var flexible.
"""

import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = PROJECT_ROOT / 'data'
LOGS_DIR = PROJECT_ROOT / 'logs'
CONFIG_DIR = PROJECT_ROOT / 'config'
LOCKS_DIR = DATA_DIR / '.locks'

DB_PATH = DATA_DIR / 'trading_history.db'

# ── Deployment detection ────────────────────────────────────────────────────
IS_RAILWAY = bool(
    os.environ.get('RAILWAY_ENVIRONMENT')
    or os.environ.get('RAILWAY_PROJECT_ID')
    or os.environ.get('RAILWAY_SERVICE_NAME')
)

# ── API (Railway sets PORT; bind 0.0.0.0 in production) ───────────────────
API_PORT = int(os.environ.get('PORT', 8000))
API_HOST = os.environ.get('HOST', '0.0.0.0')
API_BASE_URL = os.environ.get('API_BASE_URL', '').rstrip('/')

# ── Watchdog ────────────────────────────────────────────────────────────────
STALE_THRESHOLD_SECONDS = int(os.environ.get('STALE_THRESHOLD_SECONDS', 7200))
WATCHDOG_CHECK_INTERVAL = int(os.environ.get('WATCHDOG_CHECK_INTERVAL', 300))
WATCHDOG_TRIGGER_COOLDOWN = int(os.environ.get('WATCHDOG_TRIGGER_COOLDOWN', 1800))


def ensure_dirs():
    """Create runtime folders if missing."""
    for directory in (DATA_DIR, LOGS_DIR, CONFIG_DIR, LOCKS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def load_env():
    """Load env files — Railway vars take precedence (override=False)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    for env_path in (
        Path('/app/config/keys.env'),
        CONFIG_DIR / 'keys.env',
        PROJECT_ROOT / '.env',
    ):
        if env_path.exists():
            load_dotenv(env_path, override=False)


def get_env(key, default=''):
    return os.environ.get(key, default).strip()


# Bootstrap on import
ensure_dirs()
load_env()
