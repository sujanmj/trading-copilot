"""
Lifecycle rules — horizons, TTL, signal typing, deterministic resolution.
Single source of truth for prediction lifecycle semantics.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

HORIZON_CONFIG = {
    'intraday': {'min_sessions': 0, 'eval_after_sessions': 1},
    'next_day': {'min_sessions': 1, 'eval_after_sessions': 1},
    'swing_3d': {'min_sessions': 3, 'eval_after_sessions': 3},
    'swing_5d': {'min_sessions': 5, 'eval_after_sessions': 5},
}

DEFAULT_HORIZON = 'next_day'

# Hard ceiling for generic pending expiration (days) — signal-type TTL may be shorter.
EXPIRE_AFTER_DAYS = int(os.environ.get('EXPIRE_AFTER_DAYS', '7'))
UNRESOLVED_EXPIRE_DAYS = int(os.environ.get('UNRESOLVED_EXPIRE_DAYS', '5'))

TTL_SESSIONS = {
    'ULTRA scanner': 2,
    'breakout': 1,
    'momentum breakout': 1,
    'gap-up': 1,
    'govt alert': 5,
    'macro alert': 4,
    'regime outlook': 999,
    'contradiction-heavy': 2,
    'Reddit momentum': 2,
    'sector rotation': 3,
    'default': 2,
}

WIN_THRESHOLD_PCT = 2.0
LOSS_THRESHOLD_PCT = -2.0
PARTIAL_MIN_PCT = 0.5

TRADE_STYLES = ('scalp', 'intraday', 'swing')
SCALP_EXPIRE_HOURS = int(os.environ.get('SCALP_EXPIRE_HOURS', '4'))
SWING_HOLD_SESSIONS = {
    'next_day': 2,
    'swing_3d': 4,
    'swing_5d': 6,
}

PENDING_QUALITY_ACTIVE = 'ACTIVE_PENDING'
PENDING_QUALITY_EXPIRED = 'EXPIRED_PENDING'
PENDING_QUALITY_LOW_DATA = 'LOW_DATA_PENDING'

TERMINAL_STATES = frozenset({'WIN', 'LOSS', 'PARTIAL', 'EXPIRED', 'INVALIDATED'})
ACTIVE_STATES = frozenset({'ACTIVE', 'PENDING'})
UNRESOLVED_STATE = 'UNRESOLVED'

ADAPTIVE_MIN_GLOBAL = 30
ADAPTIVE_MIN_REGIME = 10
ADAPTIVE_MIN_SIGNAL = 10


def infer_signal_type(prediction: dict) -> str:
    """Classify prediction for TTL and performance tracking."""
    raw = prediction.get('raw_data')
    if isinstance(raw, str):
        try:
            import json
            raw = json.loads(raw)
        except Exception:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}

    reasoning = ' '.join([
        str(prediction.get('reasoning') or ''),
        str(prediction.get('cross_validation') or ''),
        str(raw.get('logic') or ''),
        str(raw.get('source') or ''),
    ]).upper()

    strength = str(raw.get('strength') or raw.get('signal_strength') or '').upper()
    if strength == 'ULTRA' or 'ULTRA' in reasoning:
        return 'ULTRA scanner'
    if 'GAP' in reasoning or 'GAP-UP' in reasoning:
        return 'gap-up'
    if any(k in reasoning for k in ('GOVT', 'RBI', 'SEBI', 'POLICY', 'BUDGET')):
        return 'govt alert'
    if any(k in reasoning for k in ('MACRO', 'FED', 'INFLATION', 'CRUDE', 'DOLLAR')):
        return 'macro alert'
    if 'REDDIT' in reasoning or 'WSB' in reasoning:
        return 'Reddit momentum'
    if 'SECTOR' in reasoning or 'ROTATION' in reasoning:
        return 'sector rotation'
    if 'CONTRADICT' in reasoning or float(prediction.get('contradiction_severity') or 0) >= 0.45:
        return 'contradiction-heavy'
    if any(k in reasoning for k in ('REGIME', 'OUTLOOK', 'BIAS')):
        return 'regime outlook'
    if any(k in reasoning for k in ('BREAKOUT', 'MOMENTUM', 'VOLUME SPIKE')):
        return 'momentum breakout'
    run_type = str(prediction.get('run_type') or '').lower()
    if run_type in ('post_close', 'overnight_brief', 'premarket'):
        return 'regime outlook'
    return 'breakout'


def infer_prediction_horizon(prediction: dict, signal_type: Optional[str] = None) -> str:
    """Resolve evaluation horizon from explicit field or signal heuristics."""
    explicit = str(prediction.get('prediction_horizon') or '').lower().strip()
    if explicit in HORIZON_CONFIG:
        return explicit

    sig = signal_type or infer_signal_type(prediction)
    if sig in ('ULTRA scanner', 'gap-up', 'momentum breakout'):
        return 'intraday'
    if sig in ('govt alert', 'macro alert', 'regime outlook', 'sector rotation'):
        return 'swing_5d'
    if sig == 'contradiction-heavy':
        return 'swing_3d'
    return DEFAULT_HORIZON


def ttl_sessions(signal_type: str) -> int:
    return TTL_SESSIONS.get(signal_type, TTL_SESSIONS['default'])


def sessions_elapsed(prediction_date: str, today) -> int:
    from datetime import datetime
    try:
        pred = datetime.strptime(prediction_date, '%Y-%m-%d').date()
        return max(0, (today - pred).days)
    except (TypeError, ValueError):
        return 0


def ready_for_evaluation(horizon: str, elapsed_sessions: int) -> bool:
    cfg = HORIZON_CONFIG.get(horizon, HORIZON_CONFIG[DEFAULT_HORIZON])
    return elapsed_sessions >= cfg['eval_after_sessions']


def infer_trade_style(
    prediction: dict,
    signal_type: Optional[str] = None,
    horizon: Optional[str] = None,
) -> str:
    """Classify trade style for expiry windows: scalp | intraday | swing."""
    sig = signal_type or infer_signal_type(prediction)
    hz = horizon or infer_prediction_horizon(prediction, sig)
    reasoning = str(prediction.get('reasoning') or '').upper()
    if 'SCALP' in reasoning or (sig == 'ULTRA scanner' and hz == 'intraday'):
        return 'scalp'
    if hz == 'intraday' or sig in ('gap-up', 'momentum breakout'):
        return 'intraday'
    return 'swing'


def is_past_market_close_for_prediction(prediction_date: str, now=None) -> bool:
    """True when IST session close (15:30) has passed for the prediction date."""
    from datetime import datetime, time
    import pytz

    ist = pytz.timezone('Asia/Kolkata')
    now = now or datetime.now(ist)
    if now.tzinfo is None:
        now = ist.localize(now)
    try:
        pred = datetime.strptime(str(prediction_date)[:10], '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return False
    today = now.astimezone(ist).date()
    if pred < today:
        return True
    if pred == today:
        return now.astimezone(ist).time() >= time(15, 30)
    return False


def swing_hold_sessions(horizon: str) -> int:
    return int(SWING_HOLD_SESSIONS.get(horizon, EXPIRE_AFTER_DAYS))


def should_expire_by_style(
    style: str,
    elapsed_sessions: int,
    verdict: str,
    prediction_date: str,
    *,
    horizon: str = 'next_day',
    now=None,
) -> bool:
    """Style-aware expiry — intraday/scalp at market close; swing after hold period."""
    if verdict not in (None, 'PENDING', 'UNRESOLVED', 'NEUTRAL', 'PARTIAL', 'ACTIVE'):
        return False
    if style in ('intraday', 'scalp'):
        return is_past_market_close_for_prediction(prediction_date, now) or elapsed_sessions >= 1
    if style == 'swing':
        if infer_signal_type({'prediction_horizon': horizon}) == 'regime outlook':
            return elapsed_sessions >= EXPIRE_AFTER_DAYS
        return elapsed_sessions >= swing_hold_sessions(horizon)
    return should_expire('breakout', elapsed_sessions, verdict)


def expiry_verdict_for_style(style: str, *, at_eod: bool = False) -> str:
    """Verdict assigned when a pending trade expires without resolution."""
    if style in ('intraday', 'scalp') and at_eod:
        return 'NEUTRAL'
    if style in ('intraday', 'scalp'):
        return 'NEUTRAL'
    return 'EXPIRED'


def resolve_intraday_eod(
    *,
    category: str,
    change_pct: Optional[float],
    max_gain: Optional[float],
    max_loss: Optional[float],
    target_hit: bool,
    stop_hit: bool,
) -> Tuple[str, bool, bool]:
    """EOD intraday resolution — target WIN, stop LOSS, neither NEUTRAL."""
    if change_pct is None:
        return UNRESOLVED_STATE, target_hit, stop_hit
    if target_hit:
        return 'WIN', target_hit, stop_hit
    if stop_hit:
        return 'LOSS', target_hit, stop_hit
    return 'NEUTRAL', target_hit, stop_hit


def classify_pending_quality(
    prediction: dict,
    *,
    verdict: str,
    today=None,
    now=None,
) -> str:
    """Classify open pending rows for GUI/Telegram transparency."""
    from datetime import datetime

    today = today or datetime.now().date()
    verdict = (verdict or 'PENDING').upper()
    signal_type = infer_signal_type(prediction)
    horizon = infer_prediction_horizon(prediction, signal_type)
    style = infer_trade_style(prediction, signal_type, horizon)
    elapsed = sessions_elapsed(str(prediction.get('prediction_date') or ''), today)

    if verdict == 'UNRESOLVED':
        return PENDING_QUALITY_LOW_DATA
    if should_expire_by_style(
        style,
        elapsed,
        verdict,
        str(prediction.get('prediction_date') or ''),
        horizon=horizon,
        now=now,
    ):
        return PENDING_QUALITY_EXPIRED
    return PENDING_QUALITY_ACTIVE


def should_expire(signal_type: str, elapsed_sessions: int, verdict: str) -> bool:
    if verdict not in (None, 'PENDING', 'UNRESOLVED', 'NEUTRAL', 'PARTIAL', 'ACTIVE'):
        return False
    if signal_type == 'regime outlook':
        return False
    ttl = ttl_sessions(signal_type)
    if verdict == 'UNRESOLVED' and elapsed_sessions >= UNRESOLVED_EXPIRE_DAYS:
        return True
    return elapsed_sessions >= ttl


def confidence_decay_label(original: str, elapsed_sessions: int) -> str:
    """Downgrade displayed confidence on aged unresolved predictions."""
    conf = (original or 'MEDIUM').upper()
    if elapsed_sessions >= 4 and conf in ('HIGH', 'ULTRA'):
        return 'MEDIUM'
    if elapsed_sessions >= 6 and conf == 'MEDIUM':
        return 'LOW'
    if elapsed_sessions >= UNRESOLVED_EXPIRE_DAYS:
        return 'EXPIRED'
    return conf


def resolve_deterministic(
    *,
    category: str,
    change_pct: Optional[float],
    max_gain: Optional[float],
    max_loss: Optional[float],
    target_hit: bool,
    stop_hit: bool,
) -> Tuple[str, bool, bool]:
    """
    Deterministic verdict resolution.
    Priority: target/SL sequence proxy → conservative → PARTIAL on ambiguity.
    """
    if change_pct is None:
        return UNRESOLVED_STATE, target_hit, stop_hit

    cat = (category or 'opportunity').lower()

    if target_hit and stop_hit:
        gain_abs = abs(max_gain or change_pct or 0)
        loss_abs = abs(max_loss or change_pct or 0)
        if loss_abs > gain_abs:
            return 'LOSS', target_hit, stop_hit
        return 'PARTIAL', target_hit, stop_hit

    if target_hit:
        return 'WIN', target_hit, stop_hit
    if stop_hit:
        return 'LOSS', target_hit, stop_hit

    if cat == 'opportunity':
        if change_pct >= WIN_THRESHOLD_PCT:
            return 'WIN', target_hit, stop_hit
        if change_pct <= LOSS_THRESHOLD_PCT:
            return 'LOSS', target_hit, stop_hit
        if change_pct >= PARTIAL_MIN_PCT:
            return 'PARTIAL', target_hit, stop_hit
        return UNRESOLVED_STATE if abs(change_pct) < PARTIAL_MIN_PCT else 'PARTIAL', target_hit, stop_hit

    # risk / AVOID
    if change_pct <= -1.0:
        return 'WIN', target_hit, stop_hit
    if change_pct >= 2.0:
        return 'LOSS', target_hit, stop_hit
    return UNRESOLVED_STATE, target_hit, stop_hit


def infer_failure_reason(
    *,
    verdict: str,
    signal_type: str,
    change_pct: Optional[float],
    max_gain: Optional[float],
    max_loss: Optional[float],
    target_hit: bool,
    stop_hit: bool,
    invalidated: bool = False,
) -> Optional[str]:
    if verdict not in ('LOSS', 'INVALIDATED'):
        return None
    if invalidated or verdict == 'INVALIDATED':
        return 'regime_reversal'

    reasoning_map = {
        'momentum breakout': 'false_breakout',
        'breakout': 'false_breakout',
        'ULTRA scanner': 'false_breakout',
        'gap-up': 'false_breakout',
        'contradiction-heavy': 'contradiction_ignored',
        'govt alert': 'macro_shock',
        'macro alert': 'macro_shock',
        'sector rotation': 'weak_sector_support',
        'Reddit momentum': 'volume_collapse',
    }
    base = reasoning_map.get(signal_type, 'false_breakout')

    if stop_hit and not target_hit:
        return base
    if max_loss is not None and max_loss <= LOSS_THRESHOLD_PCT:
        if max_gain and max_gain > PARTIAL_MIN_PCT and change_pct is not None and change_pct < 0:
            return 'regime_reversal'
        return base
    if change_pct is not None and change_pct <= LOSS_THRESHOLD_PCT:
        return base
    return 'weak_sector_support'


def canonical_regime(raw: Optional[str]) -> str:
    text = (raw or 'unknown').lower().replace('-', '_').replace(' ', '_')
    mapping = {
        'trending_bullish': ('bull', 'bullish', 'uptrend', 'risk_on'),
        'trending_bearish': ('bear', 'bearish', 'downtrend', 'risk_off'),
        'sideways_chop': ('sideways', 'chop', 'range', 'neutral', 'consolidation'),
        'panic_volatile': ('panic', 'volatile', 'crash', 'high_vol', 'vix'),
        'regime_transition': ('transition', 'shift', 'inflection', 'changing'),
    }
    for canon, hints in mapping.items():
        if any(h in text for h in hints):
            return canon
    return 'unknown'
