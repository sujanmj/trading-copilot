"""
Smart Telegram Alert Engine — event-driven intelligence delivery.

Uses cached JSON intelligence (no redundant Claude). Gemini only for optional
compact formatting when explicitly enabled via TELEGRAM_GEMINI_FORMAT=1.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.utils.config import ANALYSIS_STATE_FILE, DATA_DIR
from backend.utils.telegram_bot import send_message_result
from backend.orchestration.alert_filters import (
    EMERGENCY_MACRO_ALERT,
    INTRADAY_EVENT,
    INTRADAY_OPPORTUNITY,
    MARKET_CLOSE_SUMMARY,
    MIDDAY_UPDATE,
    PRE_MARKET,
    get_observability,
    mark_alert_sent,
    should_send_alert,
)

try:
    from backend.orchestration.telegram_listener import is_silenced
except ImportError:
    def is_silenced():
        return False


FILES = {
    'scanner': DATA_DIR / 'scanner_data.json',
    'govt': DATA_DIR / 'govt_intelligence.json',
    'intel': DATA_DIR / 'unified_intelligence.json',
    'stats': DATA_DIR / 'stats_data.json',
    'global': DATA_DIR / 'global_markets.json',
    'india': DATA_DIR / 'latest_market_data.json',
    'news': DATA_DIR / 'news_feed.json',
    'reddit': DATA_DIR / 'reddit_data.json',
}

MACRO_KEYWORDS = (
    'sebi', 'rbi', 'budget', 'rate cut', 'rate hike', 'war', 'sanction',
    'circuit', 'crash', 'emergency', 'fii', 'outflow', 'inflation',
)


def _log(tag: str, msg: str):
    print(f"[{tag}] {msg}")


def _load(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as e:
        _log('ALERT', f'load failed {path.name}: {e}')
        return None


def _load_trusted_intel(category: str = 'intel') -> Optional[dict]:
    """Load intelligence only if reliability gate passes."""
    intel = _load(FILES['intel'])
    if not intel:
        return None
    try:
        from backend.ai.reliability.response_gateway import validate_for_telegram
        from backend.metrics.execution_metrics import record_reliability_event
        ok, reasons = validate_for_telegram(intel)
        if not ok:
            reason = ','.join(reasons)
            _log('ALERT SUPPRESSED', f'untrusted intelligence: {reason}')
            get_observability().record_suppressed(category, 'reliability_gate', reason)
            record_reliability_event('telegram_suppressed', reasons=reason)
            return None
    except Exception as e:
        _log('ALERT', f'reliability gate error: {e}')
        return intel
    return intel


def _load_analysis_state() -> dict:
    return _load(ANALYSIS_STATE_FILE) or {}


def _regime_context(state: dict) -> Tuple[str, float, float]:
    regime = state.get('last_regime') or 'sideways'
    vol = float(state.get('volatility_index') or 0.4)
    disagree = float(state.get('disagreement_score') or 0)
    return regime, vol, disagree


def _parse_confidence(text: str) -> float:
    if not text:
        return 0.5
    import re
    m = re.search(r'(\d+(?:\.\d+)?)\s*/\s*10', str(text))
    if m:
        return float(m.group(1)) / 10.0
    m = re.search(r'(\d+(?:\.\d+)?)', str(text))
    if m:
        v = float(m.group(1))
        return v / 10.0 if v > 1 else v
    return 0.5


def _signal_confidence(signal: dict, intel: dict, state: dict) -> float:
    strength = str(signal.get('strength', '')).upper()
    base = {'ULTRA': 0.88, 'STRONG': 0.78, 'MODERATE': 0.62, 'WEAK': 0.45}.get(strength, 0.5)
    vol_ratio = float(signal.get('volume_ratio') or 1)
    chg = abs(float(signal.get('change_percent') or 0))
    base += min(0.08, vol_ratio * 0.02) + min(0.06, chg / 50)
    regime, vol, disagree = _regime_context(state)
    if disagree > 0.45 and strength != 'ULTRA':
        base -= 0.12
    if regime == 'sideways' and strength not in ('ULTRA', 'STRONG'):
        base -= 0.08
    mood = (intel or {}).get('market_mood') or {}
    conf_text = mood.get('confidence_level') or mood.get('confidence') or ''
    intel_conf = _parse_confidence(str(conf_text))
    return min(0.95, max(0.2, base * 0.7 + intel_conf * 0.3))


def _meaningful_overnight_change(state: dict) -> bool:
    reasons = state.get('last_delta_reasons') or []
    if reasons and reasons != ['initial_run']:
        return True
    metrics = state.get('metrics') or {}
    if abs(float(metrics.get('india_avg_change') or 0)) >= 0.35:
        return True
    if int(metrics.get('govt_high_impact') or 0) >= 2:
        return True
    return False


def _send(text: str) -> dict:
    if is_silenced():
        _log('ALERT SUPPRESSED', 'telegram silenced by user')
        return {'ok': False, 'sent': False, 'skipped': True, 'reason': 'silenced'}
    return send_message_result(text)


def _dispatch(category: str, text: str, confidence: float, detail: str, *,
              ticker: str = '', dedupe_key: str = '', regime: str = 'sideways',
              volatility: float = 0.0, direction: str = 'NEUTRAL',
              disagreement_score: float = 0.0) -> bool:
    try:
        from backend.orchestration.alert_freshness_gate import gate_alert_dispatch
        allow, gate_msg = gate_alert_dispatch(category)
        if not allow and gate_msg:
            _log('ALERT SUPPRESSED', f'freshness gate: {gate_msg}')
            get_observability().record_suppressed(category, 'stale_data', gate_msg)
            text = f'{text}\n\n<i>{gate_msg}</i>'
            confidence = min(confidence, 0.55)
    except Exception as e:
        _log('ALERT', f'freshness gate error: {e}')

    try:
        from backend.intelligence.institutional_language import apply_institutional_tone
        text = apply_institutional_tone(text)
    except Exception:
        pass
    ok, reason = should_send_alert(
        category, confidence, ticker=ticker, dedupe_key=dedupe_key,
        regime=regime, volatility=volatility, disagreement_score=disagreement_score,
        headline=detail, sentiment=direction,
    )
    if not ok:
        return False

    try:
        from backend.analytics.signal_outcomes import get_historical_accuracy_hint
        conf_band = 'HIGH' if confidence >= 0.75 else ('LOW' if confidence <= 0.45 else 'MEDIUM')
        hint = get_historical_accuracy_hint(
            signal_type='telegram',
            direction=direction,
            regime=regime,
            confidence_band=conf_band,
        )
        if hint:
            text = f"{text}\n\n<i>{hint}</i>"
    except Exception:
        pass

    send_result = _send(text)
    if send_result.get('skipped'):
        get_observability().record_suppressed(
            category,
            send_result.get('reason', 'telegram_disabled'),
            detail,
        )
        return False
    if not send_result.get('sent'):
        return False
    mark_alert_sent(
        category, ticker=ticker, dedupe_key=dedupe_key,
        headline=detail, sentiment=direction, confidence=confidence,
    )
    get_observability().record_sent(category, detail, {'confidence': round(confidence, 2)})
    try:
        from backend.orchestration.alert_event_log import log_alert_event
        signal_price = None
        signal_vol = None
        if ticker:
            scanner = _load(FILES['scanner']) or {}
            for sig in scanner.get('top_signals', []) or []:
                if isinstance(sig, dict) and str(sig.get('ticker', '')).upper() == ticker.upper():
                    signal_price = float(sig.get('price') or 0) or None
                    signal_vol = float(sig.get('volume_ratio') or 0) or None
                    break
        log_alert_event(
            category=category,
            tickers=ticker or '',
            direction=direction,
            score=confidence,
            price_at_alert=signal_price,
            volume_at_alert=signal_vol,
            reason=detail,
        )
    except Exception:
        pass
    try:
        from backend.logs.alert_suppression import log_alert_sent
        log_alert_sent(category=category, ticker=ticker, detail=detail, confidence=confidence)
    except Exception:
        pass
    try:
        from backend.metrics.execution_metrics import record_reliability_event
        record_reliability_event('telegram_sent')
    except Exception:
        pass
    try:
        from backend.analytics.signal_outcomes import track_telegram_alert
        state = _load_analysis_state()
        track_telegram_alert(
            category=category,
            ticker=ticker,
            confidence=confidence,
            regime=regime,
            direction=direction,
            reasoning=detail,
            contradiction_severity=float(state.get('disagreement_score') or 0),
        )
    except Exception:
        pass
    return True


def format_pre_market(intel: dict, state: dict, scanner: dict, govt: dict, global_m: dict) -> str:
    regime, vol, _ = _regime_context(state)
    mood = intel.get('market_mood') or {}
    sectors = intel.get('sector_rotation') or {}
    bullish = sectors.get('bullish') or []
    bearish = sectors.get('bearish') or []
    summary = intel.get('executive_summary') or 'Market prep summary unavailable.'
    govt_imp = intel.get('government_impact') or {}
    opps = intel.get('top_opportunities') or []
    watch = []
    for o in opps[:5]:
        if isinstance(o, dict):
            watch.append(f"• {o.get('symbol', '?')} {o.get('action', '')} — {str(o.get('logic', ''))[:60]}")

    ultra = [s for s in (scanner or {}).get('top_signals', []) if s.get('strength') == 'ULTRA'][:3]
    ultra_lines = [
        f"• {s.get('ticker')} {float(s.get('change_percent', 0)):+.1f}% vol {float(s.get('volume_ratio', 0)):.1f}x"
        for s in ultra
    ]

    global_mood = mood.get('global_mood') or mood.get('global') or '?'
    india_out = mood.get('india_outlook') or '?'
    conf = mood.get('confidence_level') or govt_imp.get('confidence_score') or '?'

    return f"""<b>☀️ PRE-MARKET INTEL</b> <code>{regime.replace('_', ' ').upper()}</code>
<b>Mood:</b> Global {global_mood} | India {india_out}
<b>Confidence:</b> {conf}

<b>Summary</b>
{summary[:650]}

<b>Sectors</b> ↑ {', '.join(bullish[:4]) or '—'} | ↓ {', '.join(bearish[:4]) or '—'}

<b>Watchlist</b>
{chr(10).join(watch) if watch else '—'}

<b>High Conviction Scanner</b>
{chr(10).join(ultra_lines) if ultra_lines else 'Awaiting evaluation sample'}

<i>Regime {regime} · vol {vol:.2f}</i>"""


def try_pre_market() -> int:
    state = _load_analysis_state()
    if not _meaningful_overnight_change(state):
        get_observability().record_suppressed(PRE_MARKET, 'no_overnight_delta', 'skip pre-market')
        return 0

    intel = _load_trusted_intel(PRE_MARKET)
    if not intel:
        get_observability().record_suppressed(PRE_MARKET, 'no_intelligence', '')
        return 0

    regime, vol, _ = _regime_context(state)
    mood = intel.get('market_mood') or {}
    confidence = _parse_confidence(str(mood.get('confidence_level', '5/10')))
    confidence = max(confidence, 0.55 if _meaningful_overnight_change(state) else 0.45)

    text = format_pre_market(
        intel, state,
        _load(FILES['scanner']),
        _load(FILES['govt']),
        _load(FILES['global']),
    )
    dedupe = f"pre_market_{datetime.now().strftime('%Y-%m-%d')}"
    if _dispatch(PRE_MARKET, text, confidence, 'pre-market brief', dedupe_key=dedupe, regime=regime, volatility=vol):
        return 1
    return 0


def format_opportunity(signal: dict, intel: dict, state: dict) -> str:
    regime, _, _ = _regime_context(state)
    base_conf = _signal_confidence(signal, intel, state)
    from backend.orchestration.alert_quality_filters import format_open_setup_alert
    text, _, _ = format_open_setup_alert(signal, intel, state, base_conf, regime)
    return text


def try_open_opportunity() -> int:
    scanner = _load(FILES['scanner'])
    intel = _load_trusted_intel(INTRADAY_OPPORTUNITY) or {}
    state = _load_analysis_state()
    regime, vol, disagree = _regime_context(state)

    if not scanner:
        return 0

    sent = 0
    max_alerts = 2 if regime in ('panic_volatile', 'macro_uncertainty', 'regime_transition') else 3
    for signal in scanner.get('top_signals', [])[:8]:
        if signal.get('strength') != 'ULTRA':
            continue
        vol_r = float(signal.get('volume_ratio') or 0)
        chg = abs(float(signal.get('change_percent') or 0))
        if vol_r < 2.2 and chg < 3.0:
            continue
        if regime in ('panic_volatile', 'macro_uncertainty') and vol_r < 3.5:
            get_observability().record_suppressed(
                INTRADAY_OPPORTUNITY, 'panic_volatility_filter', signal.get('ticker', ''))
            continue
        if disagree > 0.45 and vol_r < 3.5:
            get_observability().record_suppressed(
                INTRADAY_OPPORTUNITY, 'unresolved_contradiction', signal.get('ticker', ''))
            continue

        base_conf = _signal_confidence(signal, intel, state)
        from backend.orchestration.alert_quality_filters import adjust_open_setup_confidence
        confidence, _, watch_only, _ = adjust_open_setup_confidence(signal, base_conf, intel, state)
        if watch_only and confidence > 0.65:
            confidence = 0.65
        ticker = str(signal.get('ticker', ''))
        dedupe = f"open_{ticker}_{signal.get('direction')}_{datetime.now().strftime('%Y-%m-%d')}"
        text = format_opportunity(signal, intel, state)
        if _dispatch(
            INTRADAY_OPPORTUNITY, text, confidence, f'open {ticker}',
            ticker=ticker, dedupe_key=dedupe, regime=regime, volatility=vol,
            direction=str(signal.get('direction') or 'NEUTRAL'),
            disagreement_score=disagree,
        ):
            sent += 1
            if sent >= max_alerts:
                break
    return sent


def _detect_intraday_events(state: dict, scanner: dict, govt: dict, intel: dict) -> List[dict]:
    events = []
    regime, vol, disagree = _regime_context(state)
    reasons = state.get('last_delta_reasons') or []

    if 'regime' in str(state.get('last_regime', '')) or any('sentiment' in r for r in reasons):
        events.append({
            'type': 'regime_shift',
            'confidence': 0.72,
            'detail': f"Regime {regime} · delta {', '.join(reasons[:3])}",
            'dedupe': f"event_regime_{regime}_{datetime.now().strftime('%Y-%m-%d-%H')}",
        })

    for signal in (scanner or {}).get('top_signals', [])[:5]:
        if signal.get('strength') != 'ULTRA':
            continue
        chg = abs(float(signal.get('change_percent') or 0))
        if chg >= 4.5 or float(signal.get('volume_ratio') or 0) >= 3.5:
            ticker = signal.get('ticker', '?')
            events.append({
                'type': 'scanner_anomaly',
                'ticker': ticker,
                'confidence': _signal_confidence(signal, intel, state),
                'detail': f"Anomaly {ticker} {chg:+.1f}%",
                'dedupe': f"anomaly_{ticker}_{datetime.now().strftime('%Y-%m-%d')}",
                'signal': signal,
            })

    for item in (govt or {}).get('high_impact_items', [])[:3]:
        score = float(item.get('impact_score') or 0)
        headline = str(item.get('english_headline', item.get('title', '')))
        if score >= 8 or any(k in headline.lower() for k in MACRO_KEYWORDS):
            events.append({
                'type': 'govt_breaking',
                'confidence': min(0.92, score / 10.0),
                'detail': headline[:120],
                'dedupe': f"govt_{headline[:40]}",
                'item': item,
            })

    if disagree >= 0.85:
        events.append({
            'type': 'sentiment_reversal',
            'confidence': min(0.92, 0.75 + disagree * 0.15),
            'detail': f'Severe sentiment instability {disagree:.2f}',
            'dedupe': f"sentiment_{datetime.now().strftime('%Y-%m-%d-%H')}",
        })
    elif disagree >= 0.65:
        try:
            from backend.utils.alert_routing import MEDIUM, record_operational_event
            record_operational_event(
                'contradiction_elevated',
                MEDIUM,
                f'Elevated contradictions {disagree:.2f} — logged for OPS, Telegram suppressed',
                meta={'contradiction_score': disagree},
                telegram_decision='below_telegram_threshold',
            )
        except Exception:
            pass

    return events


def try_intraday_events() -> int:
    state = _load_analysis_state()
    scanner = _load(FILES['scanner'])
    govt = _load(FILES['govt'])
    intel = _load_trusted_intel(INTRADAY_EVENT) or {}
    regime, vol, _ = _regime_context(state)

    events = _detect_intraday_events(state, scanner, govt, intel)
    if not events:
        return 0

    from backend.orchestration.intraday_alert_state import (
        filter_intraday_events,
        format_intraday_batch,
        record_intraday_sent,
    )

    eligible = []
    for ev in events[:6]:
        ok, _ = should_send_alert(
            INTRADAY_EVENT, ev['confidence'],
            ticker=ev.get('ticker', ''),
            dedupe_key=ev.get('dedupe', ''),
            regime=regime, volatility=vol,
        )
        if ok:
            eligible.append(ev)

    partition = filter_intraday_events(eligible, regime)
    to_send = (partition.get('new') or []) + (partition.get('changed') or [])
    if not to_send:
        return 0

    sent = 0
    if len(to_send) == 1 and not (partition.get('new') and partition.get('changed')):
        ev = to_send[0]
        if ev.get('type') == 'scanner_anomaly' and ev.get('signal'):
            from backend.telegram.response_format import format_intraday_anomaly_alert
            text = format_intraday_anomaly_alert(
                ev['signal'],
                confidence=float(ev.get('confidence') or 0),
            )
        else:
            text = f"<b>⚡ INTRADAY EVENT</b> <code>{ev['type'].upper()}</code>\n{ev['detail']}\n<b>Conf:</b> {ev['confidence']:.0%}"
        if _dispatch(INTRADAY_EVENT, text, ev['confidence'], ev['detail'],
                     ticker=ev.get('ticker', ''), dedupe_key=ev.get('dedupe', ''),
                     regime=regime, volatility=vol):
            record_intraday_sent(ev)
            sent += 1
    else:
        conf = max(e['confidence'] for e in to_send)
        text = format_intraday_batch(partition, regime)
        dedupe = f"batch_{datetime.now().strftime('%Y-%m-%d-%H')}"
        if _dispatch(INTRADAY_EVENT, text, conf, 'intraday batch', dedupe_key=dedupe, regime=regime, volatility=vol):
            for ev in to_send:
                record_intraday_sent(ev)
            sent += 1
    return sent


def _significant_since_open(state: dict) -> bool:
    reasons = set(state.get('last_delta_reasons') or [])
    triggers = {'market_move', 'news_delta', 'govt_change', 'scanner_opportunities_changed',
                'reddit_sentiment_change', 'reddit_sentiment_spike', 'preservation_safety_block'}
    return bool(reasons & triggers)


def try_midday_update() -> int:
    state = _load_analysis_state()
    if not _significant_since_open(state):
        get_observability().record_suppressed(MIDDAY_UPDATE, 'no_significant_change', '')
        return 0

    intel = _load_trusted_intel(MIDDAY_UPDATE)
    if not intel:
        return 0

    regime, vol, _ = _regime_context(state)
    mood = intel.get('market_mood') or {}
    confidence = max(_parse_confidence(str(mood.get('confidence_level', '5/10'))), 0.58)
    summary = intel.get('executive_summary') or ''
    opps = intel.get('top_opportunities') or []
    top = opps[0] if opps and isinstance(opps[0], dict) else {}
    text = f"""<b>🕐 MIDDAY UPDATE</b> <code>{regime.replace('_', ' ').upper()}</code>
{summary[:500]}

<b>Lead idea:</b> {top.get('symbol', '—')} {top.get('action', '')} ({top.get('confidence', '')})
<i>Material change since open</i>"""
    dedupe = f"midday_{datetime.now().strftime('%Y-%m-%d')}"
    if _dispatch(MIDDAY_UPDATE, text, confidence, 'midday update', dedupe_key=dedupe, regime=regime, volatility=vol):
        return 1
    return 0


def format_close_summary(intel: dict, stats: dict, scanner: dict, state: dict) -> str:
    regime, vol, _ = _regime_context(state)
    mood = intel.get('market_mood') or {}
    sectors = intel.get('sector_rotation') or {}
    opps = intel.get('top_opportunities') or []
    risks = intel.get('risks_and_avoids') or []
    action = intel.get('action_plan') or ''

    metrics = (stats or {}).get('metrics_all_time') or {}
    win_rate = metrics.get('win_rate', 0)

    opp_lines = []
    for o in opps[:4]:
        if isinstance(o, dict):
            opp_lines.append(f"• {o.get('symbol')} {o.get('action')} → {o.get('target', '?')}")

    risk_lines = []
    for r in risks[:3]:
        if isinstance(r, dict):
            risk_lines.append(f"• {r.get('symbol')} — {str(r.get('logic', ''))[:50]}")

    ultra = [s.get('ticker') for s in (scanner or {}).get('top_signals', []) if s.get('strength') == 'ULTRA'][:4]

    from backend.metrics.format_helpers import safe_pct
    wr_display = safe_pct(win_rate, decimals=0)

    return f"""<b>🏁 MARKET CLOSE</b> <code>{regime.replace('_', ' ').upper()}</code>
<b>Mood:</b> {mood.get('india_outlook', '?')} | AI WR {wr_display}

<b>Sectors</b> ↑ {', '.join((sectors.get('bullish') or [])[:4]) or '—'}
↓ {', '.join((sectors.get('bearish') or [])[:4]) or '—'}

<b>Top setups</b>
{chr(10).join(opp_lines) or '—'}

<b>Avoid</b>
{chr(10).join(risk_lines) or '—'}

<b>High Conviction today:</b> {', '.join(ultra) or '—'}

<b>Tomorrow</b>
{str(action)[:400]}

<i>Regime outlook: {regime}</i>"""


def try_close_summary() -> int:
    intel = _load_trusted_intel(MARKET_CLOSE_SUMMARY)
    if not intel:
        get_observability().record_suppressed(MARKET_CLOSE_SUMMARY, 'no_intelligence', '')
        return 0

    state = _load_analysis_state()
    regime, vol, _ = _regime_context(state)
    mood = intel.get('market_mood') or {}
    confidence = max(_parse_confidence(str(mood.get('confidence_level', '6/10'))), 0.5)

    try:
        from backend.intelligence.market_close_intelligence import (
            build_market_close_report,
            format_telegram_close_summary,
        )
        report = build_market_close_report(intel)
        text = format_telegram_close_summary(report)
        metrics = (_load(FILES['stats']) or {}).get('metrics_all_time') or {}
        from backend.lifecycle.win_rate_engine import win_rate_from_metrics
        from backend.metrics.format_helpers import safe_pct
        wr = win_rate_from_metrics(metrics)
        text += f"\n\n<b>Resolved WR:</b> {safe_pct(wr)} <i>(WIN/(WIN+LOSS))</i>"
    except Exception:
        text = format_close_summary(intel, _load(FILES['stats']), _load(FILES['scanner']), state)

    dedupe = f"close_{datetime.now().strftime('%Y-%m-%d')}"
    if _dispatch(MARKET_CLOSE_SUMMARY, text, confidence, 'market close', dedupe_key=dedupe, regime=regime, volatility=vol):
        return 1
    return 0


_MACRO_STALE_RESEARCH_SENT: dict[str, float] = {}
MACRO_STALE_RESEARCH_THROTTLE_SEC = 90 * 60


def _normalize_macro_headline_key(headline: str) -> str:
    import re
    return re.sub(r'[^a-z0-9]+', ' ', str(headline or '').lower()).strip()[:160]


def _should_send_macro_stale_research(headline: str) -> bool:
    """Throttle stale macro research to once per headline per 90 minutes."""
    key = _normalize_macro_headline_key(headline)
    if not key:
        return True
    now = time.time()
    last = _MACRO_STALE_RESEARCH_SENT.get(key, 0.0)
    if last and (now - last) < MACRO_STALE_RESEARCH_THROTTLE_SEC:
        _log('MACRO_STALE_RESEARCH_SUPPRESSED', 'duplicate_headline')
        return False
    _MACRO_STALE_RESEARCH_SENT[key] = now
    return True


def try_emergency_macro(scheduled: bool = True) -> tuple[int, int]:
    """Returns (sent, skipped). Emergency may be detected when skipped."""
    from backend.orchestration.alert_quality_filters import (
        evaluate_emergency_macro,
        is_research_only_macro_item,
        record_emergency_macro_sent,
    )

    govt = _load(FILES['govt'])
    news = _load(FILES['news'])
    state = _load_analysis_state()
    regime, vol, _ = _regime_context(state)

    candidates = []
    for item in (govt or {}).get('high_impact_items', [])[:8]:
        score = float(item.get('impact_score') or 0)
        headline = str(item.get('english_headline', item.get('title', '')))
        if score >= 9 or any(k in headline.lower() for k in ('sebi', 'rbi', 'crash', 'emergency', 'war')):
            candidates.append((score / 10.0, headline, item))

    for art in (news or {}).get('articles', [])[:15]:
        title = str(art.get('title', ''))
        lower = title.lower()
        if any(k in lower for k in MACRO_KEYWORDS) and any(w in lower for w in ('breaking', 'crash', 'halt', 'ban', 'probe')):
            candidates.append((0.75, title, art))

    if not candidates:
        return 0, 0

    candidates.sort(key=lambda x: x[0], reverse=True)
    conf, headline, item = candidates[0]
    from backend.orchestration.alert_freshness_gate import is_headline_source_stale

    stale_source = is_headline_source_stale(item)
    research_only = is_research_only_macro_item(item)
    cache_stale_flag = bool(item and item.get('cache_stale'))
    if stale_source or research_only or cache_stale_flag:
        stale_reason = (
            'research_only' if research_only else
            'cache_stale' if cache_stale_flag else
            'stale_cache'
        )
        _log('EMERGENCY_MACRO_SKIPPED', f'reason={stale_reason} headline_source_stale')
        get_observability().record_suppressed(
            EMERGENCY_MACRO_ALERT, 'stale_cache', headline[:120],
        )
        if scheduled:
            _log('TELEGRAM_MACRO_STALE_SUPPRESSED', f'reason={stale_reason} headline={headline[:120]}')
            return 0, 1
        if is_silenced():
            return 0, 1
        if not _should_send_macro_stale_research(headline):
            return 0, 1
        research_text = (
            '<b>Macro research only — stale cache</b>\n'
            f'{headline[:900]}\n'
            '<i>Headline source stale — not Emergency Macro. Run /refresh quick.</i>'
        )
        _send(research_text)
        return 0, 1

    should_send, skip_reason, theme = evaluate_emergency_macro(
        headline, conf, item=item, scheduled=scheduled,
    )
    if not should_send:
        if skip_reason in ('duplicate_headline', 'theme_repeat'):
            return 0, 1
        return 0, 0

    dedupe = f"emergency_{headline[:50]}"
    text = f"""<b>🚨 Emergency Macro</b>
{headline[:900]}
<b>Confidence:</b> {conf:.0%}
<i>Direct market impact · theme {theme.replace('_', ' ')}</i>"""

    ok, _ = should_send_alert(
        EMERGENCY_MACRO_ALERT, conf, dedupe_key=dedupe, regime=regime, volatility=vol,
    )
    if not ok:
        return 0, 0
    send_result = _send(text)
    if send_result.get('skipped'):
        get_observability().record_emergency(headline[:120])
        get_observability().record_suppressed(
            EMERGENCY_MACRO_ALERT,
            send_result.get('reason', 'telegram_disabled'),
            headline[:120],
        )
        return 0, 1
    if not send_result.get('sent'):
        return 0, 0
    mark_alert_sent(
        EMERGENCY_MACRO_ALERT, dedupe_key=dedupe,
        headline=headline, sentiment='NEUTRAL', confidence=conf,
    )
    record_emergency_macro_sent(headline, conf, theme)
    get_observability().record_emergency(headline[:120])
    get_observability().record_sent(EMERGENCY_MACRO_ALERT, headline[:100], {'confidence': conf})
    try:
        from backend.orchestration.alert_event_log import log_alert_event
        log_alert_event(
            category=EMERGENCY_MACRO_ALERT,
            tickers=[],
            direction='NEUTRAL',
            score=conf,
            reason=headline,
        )
    except Exception:
        pass
    return 1, 0


def run_outcome_report() -> int:
    """8 AM outcome — uses existing telegram_bot helper."""
    from backend.utils.telegram_bot import send_outcome_report
    stats = _load(FILES['stats'])
    if not stats:
        return 0
    metrics = stats.get('metrics_all_time') or {}
    if send_outcome_report(metrics, stats.get('top_winners'), stats.get('top_losers')):
        get_observability().record_sent('OUTCOME_REPORT', 'daily outcomes')
        return 1
    return 0
