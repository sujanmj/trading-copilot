"""
Central configuration — cloud-first (Railway), env-var flexible.
"""

import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent.parent
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

# ── AI cost controls ────────────────────────────────────────────────────────
MAX_DAILY_AI_COST = float(os.environ.get('MAX_DAILY_AI_COST', '1.5'))
MAX_CLAUDE_PROMPT_CHARS = int(os.environ.get('MAX_CLAUDE_PROMPT_CHARS', '28000'))
AI_CACHE_TTL_SECONDS = int(os.environ.get('AI_CACHE_TTL_SECONDS', 21600))
AI_CACHE_DIR = DATA_DIR / 'ai_cache'
ANALYSIS_STATE_FILE = DATA_DIR / 'analysis_state.json'
AI_BUDGET_FILE = DATA_DIR / 'ai_budget.json'
DEBUG_SNAPSHOTS_DIR = DATA_DIR / 'debug_snapshots'
ANALYSIS_EXPLANATIONS_FILE = DATA_DIR / 'analysis_explanations.json'
TELEGRAM_ALERT_STATE_FILE = DATA_DIR / 'telegram_alert_state.json'
TELEGRAM_ALERT_OBS_FILE = DATA_DIR / 'telegram_alert_observability.json'

# Observability thresholds
QUALITY_SCORE_WARN = float(os.environ.get('QUALITY_SCORE_WARN', '0.55'))
CONTRADICTION_RETENTION_WARN = float(os.environ.get('CONTRADICTION_RETENTION_WARN', '0.6'))
COMPRESSION_RATIO_WARN = float(os.environ.get('COMPRESSION_RATIO_WARN', '0.25'))
SENTIMENT_PRESERVATION_WARN = float(os.environ.get('SENTIMENT_PRESERVATION_WARN', '0.55'))
MAX_DEBUG_SNAPSHOTS = int(os.environ.get('MAX_DEBUG_SNAPSHOTS', '25'))


def ensure_dirs():
    """Create runtime folders if missing."""
    for directory in (DATA_DIR, LOGS_DIR, CONFIG_DIR, LOCKS_DIR, AI_CACHE_DIR, DEBUG_SNAPSHOTS_DIR):
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
