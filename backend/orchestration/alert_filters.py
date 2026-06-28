"""Telegram alert filters — cooldowns, confidence, dedupe, observability."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple

from backend.utils.config import TELEGRAM_ALERT_OBS_FILE, TELEGRAM_ALERT_STATE_FILE
from backend.storage.json_io import atomic_write_json

PRE_MARKET = 'PRE_MARKET'
INTRADAY_OPPORTUNITY = 'INTRADAY_OPPORTUNITY'
MIDDAY_UPDATE = 'MIDDAY_UPDATE'
MARKET_CLOSE_SUMMARY = 'MARKET_CLOSE_SUMMARY'
EMERGENCY_MACRO_ALERT = 'EMERGENCY_MACRO_ALERT'
INTRADAY_EVENT = 'INTRADAY_EVENT'

CATEGORY_COOLDOWNS_SEC = {
    PRE_MARKET: 20 * 3600,
    INTRADAY_OPPORTUNITY: 45 * 60,
    MIDDAY_UPDATE: 6 * 3600,
    MARKET_CLOSE_SUMMARY: 20 * 3600,
    EMERGENCY_MACRO_ALERT: 30 * 60,
    INTRADAY_EVENT: 20 * 60,
}

TICKER_COOLDOWNS_SEC = {
    INTRADAY_OPPORTUNITY: 3 * 3600,
    INTRADAY_EVENT: 2 * 3600,
    EMERGENCY_MACRO_ALERT: 4 * 3600,
}

DEFAULT_CONFIDENCE = {
    PRE_MARKET: 0.45,
    INTRADAY_OPPORTUNITY: 0.78,
    MIDDAY_UPDATE: 0.55,
    MARKET_CLOSE_SUMMARY: 0.40,
    EMERGENCY_MACRO_ALERT: 0.65,
    INTRADAY_EVENT: 0.72,
}

REGIME_CONFIDENCE_BONUS = {
    'sideways': 0.08,
    'bullish_trend': 0.0,
    'panic_volatile': -0.18,
    'macro_uncertainty': -0.08,
    'regime_transition': -0.10,
}


def _log(tag: str, msg: str):
    print(f"[{tag}] {msg}")


def _today_key() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def _load_json(path, default):
    if not path.exists():
        return default
    try:
        import json
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, type(default)) else default
    except Exception:
        return default


def _save_json(path, data):
    atomic_write_json(path, data)


class AlertObservability:
    def __init__(self):
        self._data = _load_json(TELEGRAM_ALERT_OBS_FILE, {
            'date': _today_key(),
            'sent_today': [],
            'suppressed_today': [],
            'duplicate_blocks': [],
            'cooldown_blocks': [],
            'low_confidence_skips': [],
            'emergency_triggers': [],
        })
        if self._data.get('date') != _today_key():
            self._data = {
                'date': _today_key(),
                'sent_today': [],
                'suppressed_today': [],
                'duplicate_blocks': [],
                'cooldown_blocks': [],
                'low_confidence_skips': [],
                'emergency_triggers': [],
            }

    def persist(self):
        _save_json(TELEGRAM_ALERT_OBS_FILE, self._data)

    def record_sent(self, category: str, detail: str, meta: Optional[dict] = None):
        entry = {
            'time': datetime.now().isoformat(),
            'category': category,
            'detail': detail[:200],
            'meta': meta or {},
        }
        self._data.setdefault('sent_today', []).append(entry)
        self._data['sent_today'] = self._data['sent_today'][-80:]
        _log('TELEGRAM ALERT', f'{category} — {detail[:100]}')
        self.persist()

    def record_suppressed(self, category: str, reason: str, detail: str = ''):
        entry = {
            'time': datetime.now().isoformat(),
            'category': category,
            'reason': reason,
            'detail': detail[:160],
        }
        self._data.setdefault('suppressed_today', []).append(entry)
        self._data['suppressed_today'] = self._data['suppressed_today'][-120:]
        if reason == 'duplicate':
            _log('DUPLICATE BLOCKED', f'{category} {detail[:80]}')
            self._data.setdefault('duplicate_blocks', []).append(entry)
        elif reason == 'cooldown':
            _log('ALERT SUPPRESSED', f'cooldown {category}')
            self._data.setdefault('cooldown_blocks', []).append(entry)
        elif reason == 'low_confidence':
            _log('LOW CONFIDENCE SKIP', f'{category} {detail[:80]}')
            self._data.setdefault('low_confidence_skips', []).append(entry)
        else:
            _log('ALERT SUPPRESSED', f'{reason} {category}')
        self._data['duplicate_blocks'] = self._data['duplicate_blocks'][-60:]
        self._data['cooldown_blocks'] = self._data['cooldown_blocks'][-60:]
        self._data['low_confidence_skips'] = self._data['low_confidence_skips'][-60:]
        self.persist()
        try:
            from backend.orchestration.alert_suppression_log import log_suppression
            log_suppression(
                reason=reason,
                category=category,
                detail=detail,
                stage='alert_filter',
            )
        except Exception:
            pass

    def record_emergency(self, detail: str):
        entry = {'time': datetime.now().isoformat(), 'detail': detail[:200]}
        self._data.setdefault('emergency_triggers', []).append(entry)
        self._data['emergency_triggers'] = self._data['emergency_triggers'][-30:]
        _log('EMERGENCY ALERT', detail[:120])
        self.persist()

    def summary(self) -> dict:
        recent_suppressed = (self._data.get('suppressed_today') or [])[-8:]
        last_suppressed = recent_suppressed[-1] if recent_suppressed else {}
        return {
            'date': self._data.get('date'),
            'alerts_sent_today': len(self._data.get('sent_today') or []),
            'suppressed_today': len(self._data.get('suppressed_today') or []),
            'duplicate_blocks': len(self._data.get('duplicate_blocks') or []),
            'cooldown_blocks': len(self._data.get('cooldown_blocks') or []),
            'low_confidence_skips': len(self._data.get('low_confidence_skips') or []),
            'emergency_triggers': len(self._data.get('emergency_triggers') or []),
            'recent_sent': (self._data.get('sent_today') or [])[-8:],
            'recent_suppressed': recent_suppressed,
            'last_suppression_reason': last_suppressed.get('reason') or '',
            'last_suppression_detail': last_suppressed.get('detail') or '',
            'ai_calls_avoided': len(self._data.get('suppressed_today') or []),
        }


class AlertState:
    def __init__(self):
        self._data = _load_json(TELEGRAM_ALERT_STATE_FILE, {
            'date': _today_key(),
            'category_last_sent': {},
            'category_sent_today': {},
            'ticker_last_sent': {},
            'dedupe_keys': {},
        })
        if self._data.get('date') != _today_key():
            self._data = {
                'date': _today_key(),
                'category_last_sent': {},
                'category_sent_today': {},
                'ticker_last_sent': {},
                'dedupe_keys': {},
            }

    def persist(self):
        _save_json(TELEGRAM_ALERT_STATE_FILE, self._data)

    def category_sent_today(self, category: str) -> bool:
        return bool((self._data.get('category_sent_today') or {}).get(category))

    def mark_category_sent(self, category: str):
        now = datetime.now().timestamp()
        self._data.setdefault('category_last_sent', {})[category] = now
        self._data.setdefault('category_sent_today', {})[category] = True
        self.persist()

    def check_category_cooldown(self, category: str) -> Tuple[bool, str]:
        last = (self._data.get('category_last_sent') or {}).get(category)
        if not last:
            return True, ''
        elapsed = datetime.now().timestamp() - float(last)
        need = CATEGORY_COOLDOWNS_SEC.get(category, 3600)
        if elapsed < need:
            return False, f'category cooldown {int(need - elapsed)}s remaining'
        return True, ''

    def check_ticker_cooldown(self, category: str, ticker: str) -> Tuple[bool, str]:
        if not ticker:
            return True, ''
        key = f'{category}:{ticker.upper()}'
        last = (self._data.get('ticker_last_sent') or {}).get(key)
        if not last:
            return True, ''
        elapsed = datetime.now().timestamp() - float(last)
        need = TICKER_COOLDOWNS_SEC.get(category, 7200)
        if elapsed < need:
            return False, f'ticker {ticker} cooldown'
        return True, ''

    def mark_ticker_sent(self, category: str, ticker: str):
        if not ticker:
            return
        key = f'{category}:{ticker.upper()}'
        self._data.setdefault('ticker_last_sent', {})[key] = datetime.now().timestamp()
        self.persist()

    def check_dedupe_key(self, dedupe_key: str) -> bool:
        if not dedupe_key:
            return True
        ts = (self._data.get('dedupe_keys') or {}).get(dedupe_key)
        if not ts:
            return True
        return datetime.now().timestamp() - float(ts) >= 86400

    def mark_dedupe_key(self, dedupe_key: str):
        if not dedupe_key:
            return
        self._data.setdefault('dedupe_keys', {})[dedupe_key] = datetime.now().timestamp()
        self.persist()


_obs = AlertObservability()
_state = AlertState()


def get_observability() -> AlertObservability:
    return _obs


def get_state() -> AlertState:
    return _state


def effective_confidence_threshold(category: str, regime: str, volatility: float = 0.0) -> float:
    base = DEFAULT_CONFIDENCE.get(category, 0.6)
    base += REGIME_CONFIDENCE_BONUS.get(regime or 'sideways', 0)
    if volatility > 0.65:
        base += 0.08
    if regime in ('panic_volatile', 'macro_uncertainty', 'regime_transition'):
        base += 0.04
    return max(0.35, min(0.92, base))


def should_send_alert(
    category: str,
    confidence: float,
    *,
    ticker: str = '',
    dedupe_key: str = '',
    regime: str = 'sideways',
    volatility: float = 0.0,
    disagreement_score: float = 0.0,
    headline: str = '',
    sentiment: str = 'NEUTRAL',
    force_priority: bool = False,
) -> Tuple[bool, str]:
    try:
        from backend.runtime.runtime_state import get_runtime_state
        rs = get_runtime_state()
        fresh = rs.get('snapshot_freshness') or {}
        if fresh.get('stale'):
            detail = f'age={fresh.get("age_display")}'
            _obs.record_suppressed(category, 'stale_snapshot', detail)
            try:
                from backend.orchestration.alert_suppression_log import log_dispatch_debug
                log_dispatch_debug(
                    ticker=ticker or category,
                    reason='stale_snapshot',
                    category=category,
                    detail=detail,
                )
            except Exception:
                pass
            return False, 'stale_snapshot'
        session = rs.get('session') or {}
        if session.get('after_hours_mode') and category in (INTRADAY_OPPORTUNITY, INTRADAY_EVENT):
            _obs.record_suppressed(category, 'after_hours_block', category)
            return False, 'after_hours_block'
        lc = rs.get('lifecycle') or {}
        if lc.get('lifecycle_state') == 'DEGRADED' and not force_priority:
            _obs.record_suppressed(category, 'lifecycle_mismatch', lc.get('lifecycle_state', ''))
            return False, 'lifecycle_mismatch'
        intel = rs.get('intelligence_status') or {}
        if intel.get('elite_blocked') and category == INTRADAY_OPPORTUNITY and confidence < 0.85:
            _obs.record_suppressed(category, 'missing_ai_confirmation', f'conf={confidence:.2f}')
            return False, 'missing_ai_confirmation'
    except Exception:
        pass

    try:
        from backend.orchestration.alert_priority import evaluate_priority_gate
        allow_pri, pri_reason, _priority = evaluate_priority_gate(
            category, confidence, force=force_priority,
        )
        if not allow_pri:
            _obs.record_suppressed(category, pri_reason, f'priority={_priority}')
            return False, pri_reason
    except Exception:
        pass

    try:
        from backend.orchestration.alert_deduplication import check_duplicate
        detail = headline or dedupe_key or category
        ok_dedupe, dedupe_reason, _ = check_duplicate(
            ticker or '', detail, sentiment, confidence=confidence,
        )
        if not ok_dedupe:
            _obs.record_suppressed(category, 'duplicate', dedupe_reason)
            return False, 'duplicate'
    except Exception:
        pass

    threshold = effective_confidence_threshold(category, regime, volatility)
    if disagreement_score >= 0.55 and category == INTRADAY_OPPORTUNITY:
        threshold += 0.06
    if confidence < threshold:
        _obs.record_suppressed(category, 'low_confidence', f'conf={confidence:.2f}<{threshold:.2f}')
        return False, 'low_confidence'

    if category in (PRE_MARKET, MIDDAY_UPDATE, MARKET_CLOSE_SUMMARY):
        if _state.category_sent_today(category):
            _obs.record_suppressed(category, 'already_sent_today', category)
            return False, 'already_sent_today'

    ok, reason = _state.check_category_cooldown(category)
    if not ok:
        _obs.record_suppressed(category, 'cooldown', reason)
        return False, 'cooldown'

    if ticker:
        ok, reason = _state.check_ticker_cooldown(category, ticker)
        if not ok:
            _obs.record_suppressed(category, 'cooldown', reason)
            return False, 'cooldown'

    if dedupe_key and not _state.check_dedupe_key(dedupe_key):
        _obs.record_suppressed(category, 'duplicate', dedupe_key)
        return False, 'duplicate'

    return True, ''


def mark_alert_sent(
    category: str,
    ticker: str = '',
    dedupe_key: str = '',
    *,
    headline: str = '',
    sentiment: str = 'NEUTRAL',
    confidence: float = 0.0,
):
    _state.mark_category_sent(category)
    if ticker:
        _state.mark_ticker_sent(category, ticker)
    if dedupe_key:
        _state.mark_dedupe_key(dedupe_key)
    try:
        from backend.orchestration.alert_deduplication import record_sent
        record_sent(
            ticker or '',
            headline or dedupe_key or category,
            sentiment,
            confidence=confidence,
            category=category,
        )
    except Exception:
        pass


def get_telegram_alert_obs_summary() -> dict:
    return _obs.summary()
