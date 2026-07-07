"""Alert quality controls for scheduled Telegram alerts.

The goal here is operational discipline: send the first useful watchlist,
then suppress repeats unless the scanner state actually changed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path
from backend.storage.json_io import atomic_write_json

IST = ZoneInfo('Asia/Kolkata')
STATE_FILE = get_data_path('alert_quality_state.json')
MISSED_FILE = get_data_path('missed_opportunities.jsonl')

SCORE_DELTA_MIN = 15.0
VOLUME_REL_DELTA_MIN = 0.50
TOP_N = 3
LIVE_SLOTS = {'live_validation', 'open_confirmation'}
TEXT_ALERT_COMMANDS = {
    'premarket',
    'premarket_full',
    'morning',
    'today',
    'tomorrow',
    'brief_morning',
    'brief_premarket_reminder',
    'brief_close_watch',
    'intraday_batch',
}


def _now() -> datetime:
    return datetime.now(IST)


def _today(now: datetime | None = None) -> str:
    return (now or _now()).date().isoformat()


def _load_json(path, default):
    try:
        if not path.is_file():
            return default
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, type(default)) else default
    except Exception:
        return default


def _save_state(state: dict[str, Any]) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(STATE_FILE, state)
    except Exception:
        pass


def _load_state() -> dict[str, Any]:
    state = _load_json(STATE_FILE, {})
    if state.get('date') != _today():
        return {
            'date': _today(),
            'premarket_last_signature': {},
            'live_stale_warning_sent': {},
            'missed_first_seen': {},
        }
    state.setdefault('premarket_last_signature', {})
    state.setdefault('live_stale_warning_sent', {})
    state.setdefault('missed_first_seen', {})
    return state


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _norm_text(value: Any, limit: int = 120) -> str:
    return ' '.join(str(value or '').strip().split())[:limit]


def _report_market_mode(report: dict[str, Any]) -> str:
    mode = report.get('market_mode')
    if isinstance(mode, dict):
        mode = mode.get('market_mode') or mode.get('phase') or mode.get('status')
    return str(mode or '').strip().upper()


def normalize_action(value: Any) -> str:
    raw = str(value or '').strip().upper().replace('_', ' ')
    if 'ENTRY MISSED' in raw or 'MISSED' in raw or 'EXTENDED' in raw:
        return 'ENTRY MISSED'
    if 'CONFIRM' in raw or 'VALID' in raw or 'ACTIVE' in raw:
        return 'CONFIRMED'
    if 'REJECT' in raw:
        return 'REJECTED'
    if 'PULLBACK' in raw or 'RETEST' in raw:
        return 'PULLBACK WATCH'
    if 'AVOID' in raw or 'RISK' in raw:
        return 'AVOID'
    if 'VOLUME' in raw:
        return 'WATCH'
    return 'WATCH'


def _row_action(row: dict[str, Any]) -> str:
    for key in ('action', 'entry_status', 'trade_status', 'status', 'setup', 'reason'):
        action = normalize_action(row.get(key))
        if action != 'WATCH' or key in ('action', 'entry_status', 'trade_status', 'status'):
            return action
    return 'WATCH'


def _row_catalyst(row: dict[str, Any]) -> str:
    for key in ('fresh_catalyst', 'catalyst', 'catalyst_note', 'news', 'trigger'):
        value = row.get(key)
        if value:
            return _norm_text(value)
    reasons = row.get('reasons')
    if isinstance(reasons, list):
        for item in reasons:
            text = _norm_text(item)
            if any(word in text.lower() for word in ('news', 'catalyst', 'order', 'result', 'policy')):
                return text
    return ''


def _row_reason(row: dict[str, Any]) -> str:
    reasons = row.get('reasons')
    if isinstance(reasons, list) and reasons:
        return _norm_text(reasons[0])
    return _norm_text(row.get('reason') or row.get('setup') or row.get('detail'))


def _row_risk(row: dict[str, Any]) -> str:
    return _norm_text(
        row.get('risk')
        or row.get('risk_reason')
        or row.get('avoid_reason')
        or row.get('rejection_reason')
        or row.get('tier_cap')
    )


def premarket_signature(report: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for row in (report.get('top_setups') or [])[:TOP_N]:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get('ticker') or row.get('symbol') or '').strip().upper()
        if not ticker:
            continue
        rows.append({
            'ticker': ticker,
            'action': _row_action(row),
            'score': round(_safe_float(row.get('score') or row.get('final_score')), 2),
            'volume': round(_safe_float(
                row.get('volume_ratio')
                or row.get('participation')
                or row.get('volume_multiplier')
                or row.get('vol_r')
            ), 2),
            'reason': _row_reason(row),
            'risk': _row_risk(row),
            'catalyst': _row_catalyst(row),
        })
    return {
        'market_mode': _report_market_mode(report),
        'freshness_ok': bool(report.get('freshness_ok')),
        'hard_stale_lock': bool(report.get('hard_stale_lock')),
        'rows': rows,
    }


def _scanner_fresh_for_live(report: dict[str, Any]) -> bool:
    return bool(report.get('freshness_ok')) and not bool(report.get('hard_stale_lock'))


def _delta_reasons(prev: dict[str, Any], current: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    prev_rows = {row.get('ticker'): row for row in prev.get('rows') or [] if row.get('ticker')}
    cur_rows = {row.get('ticker'): row for row in current.get('rows') or [] if row.get('ticker')}
    prev_top = list(prev_rows.keys())[:TOP_N]
    cur_top = list(cur_rows.keys())[:TOP_N]
    if prev_top != cur_top:
        added = [t for t in cur_top if t not in prev_rows]
        removed = [t for t in prev_top if t not in cur_rows]
        if added:
            reasons.append('new_ticker_top3')
        if removed:
            reasons.append('ticker_left_top3')
    for ticker, row in cur_rows.items():
        old = prev_rows.get(ticker)
        if not old:
            continue
        if row.get('action') != old.get('action'):
            reasons.append(f'action_changed:{ticker}')
        if abs(_safe_float(row.get('score')) - _safe_float(old.get('score'))) >= SCORE_DELTA_MIN:
            reasons.append(f'score_delta:{ticker}')
        old_vol = _safe_float(old.get('volume'))
        new_vol = _safe_float(row.get('volume'))
        if old_vol > 0 and abs(new_vol - old_vol) / old_vol >= VOLUME_REL_DELTA_MIN:
            reasons.append(f'volume_delta:{ticker}')
        elif old_vol == 0 and new_vol >= 3.0:
            reasons.append(f'volume_delta:{ticker}')
        if row.get('catalyst') and row.get('catalyst') != old.get('catalyst'):
            reasons.append(f'fresh_catalyst:{ticker}')
        if row.get('risk') != old.get('risk'):
            reasons.append(f'risk_changed:{ticker}')
    if (
        str(prev.get('market_mode') or '').upper() == 'PREMARKET'
        and str(current.get('market_mode') or '').upper() == 'MARKET_HOURS'
        and current.get('freshness_ok')
    ):
        reasons.append('market_open_live_confirmation')
    return list(dict.fromkeys(reasons))


def _record_suppression(category: str, reason: str, detail: str = '') -> None:
    try:
        from backend.orchestration.alert_filters import get_observability

        get_observability().record_suppressed(category, reason, detail)
    except Exception:
        try:
            from backend.orchestration.alert_suppression_log import log_suppression

            log_suppression(reason=reason, category=category, detail=detail, stage='alert_quality')
        except Exception:
            pass


def _record_sent(category: str, detail: str, meta: dict[str, Any] | None = None) -> None:
    try:
        from backend.orchestration.alert_filters import get_observability

        get_observability().record_sent(category, detail, meta or {})
    except Exception:
        pass
    try:
        from backend.orchestration.alert_suppression_log import log_alert_sent

        log_alert_sent(category=category, detail=detail, extra=meta or {})
    except Exception:
        pass


def _fingerprint_text(text: str) -> str:
    body = ' '.join(str(text or '').split()).lower()
    return hashlib.sha256(body.encode('utf-8', errors='ignore')).hexdigest()[:24]


def _command_category(command: str) -> str:
    cmd = str(command or '').strip().lower().lstrip('/').replace(' ', '_')
    if cmd == 'intraday_batch':
        return 'INTRADAY_EVENT'
    return 'PRE_MARKET'


def evaluate_text_alert(command: str, text: str) -> dict[str, Any]:
    """Gate alert-like command output before Telegram send."""
    cmd = str(command or '').strip().lower().lstrip('/').replace(' ', '_')
    if cmd not in TEXT_ALERT_COMMANDS:
        return {'send': True, 'reason': 'not_tracked'}
    if 'ENTRY MISSED' in str(text or '').upper():
        _record_suppression(_command_category(cmd), 'entry_missed_log_only', cmd)
        return {'send': False, 'reason': 'entry_missed_log_only'}
    fp = _fingerprint_text(text)
    state = _load_state()
    sent = state.setdefault('text_alerts', {})
    prev = sent.get(cmd)
    if prev and prev.get('fingerprint') == fp:
        reason = 'duplicate_premarket' if cmd.startswith('premarket') else 'no_meaningful_delta'
        _record_suppression(_command_category(cmd), reason, cmd)
        return {'send': False, 'reason': reason, 'fingerprint': fp}
    return {'send': True, 'reason': 'meaningful_or_first_text', 'fingerprint': fp, 'command': cmd}


def record_text_alert_sent(command: str, decision: dict[str, Any]) -> None:
    cmd = str(command or '').strip().lower().lstrip('/').replace(' ', '_')
    fp = decision.get('fingerprint')
    if not fp:
        return
    state = _load_state()
    state.setdefault('text_alerts', {})[cmd] = {
        'fingerprint': fp,
        'sent_at': _now().isoformat(),
        'reason': decision.get('reason') or 'sent',
    }
    _save_state(state)
    _record_sent(_command_category(cmd), f'text_alert command={cmd}', {'reason': decision.get('reason')})


def evaluate_scheduled_premarket_alert(
    slot: str,
    report: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _now()
    day = _today(now)
    state = _load_state()
    signature = premarket_signature(report)
    signature['slot'] = slot
    signature['date'] = day

    if slot in LIVE_SLOTS and not _scanner_fresh_for_live(report):
        warn_key = f'{day}:live_stale_warning'
        if state.get('live_stale_warning_sent', {}).get(warn_key):
            _record_suppression('PRE_MARKET', 'stale_scanner_repeat', slot)
            return {
                'send': False,
                'reason': 'stale_scanner_repeat',
                'signature': signature,
                'deltas': [],
            }
        state.setdefault('live_stale_warning_sent', {})[warn_key] = True
        _save_state(state)
        return {
            'send': True,
            'warning_only': True,
            'warning_text': 'No fresh live setups yet — waiting for scanner.',
            'reason': 'stale_live_scanner_warning',
            'signature': signature,
            'deltas': ['stale_live_scanner_warning'],
        }

    last = state.get('premarket_last_signature') or {}
    if not last:
        return {
            'send': True,
            'reason': 'initial_watchlist',
            'signature': signature,
            'deltas': ['initial_watchlist'],
        }

    deltas = _delta_reasons(last, signature)
    if not deltas:
        _record_suppression('PRE_MARKET', 'duplicate_premarket', slot)
        return {
            'send': False,
            'reason': 'duplicate_premarket',
            'signature': signature,
            'deltas': [],
        }

    if slot == 'open_confirmation':
        prev_rows = {
            row.get('ticker'): row
            for row in (last.get('rows') or [])
            if isinstance(row, dict) and row.get('ticker')
        }
        live_action_delta = False
        for row in signature.get('rows') or []:
            ticker = row.get('ticker')
            if row.get('action') in ('CONFIRMED', 'REJECTED'):
                old_action = (prev_rows.get(ticker) or {}).get('action')
                if old_action != row.get('action'):
                    live_action_delta = True
                    break
        if not live_action_delta:
            _record_suppression('PRE_MARKET', 'no_meaningful_delta', slot)
            return {
                'send': False,
                'reason': 'no_meaningful_delta',
                'signature': signature,
                'deltas': deltas,
            }

    if all(row.get('action') == 'ENTRY MISSED' for row in signature.get('rows') or []) and signature.get('rows'):
        for row in signature.get('rows') or []:
            log_missed_opportunity(row, source=f'premarket_{slot}', reason='entry_missed_log_only')
        _record_suppression('PRE_MARKET', 'entry_missed_log_only', slot)
        return {
            'send': False,
            'reason': 'entry_missed_log_only',
            'signature': signature,
            'deltas': deltas,
        }

    return {
        'send': True,
        'reason': 'meaningful_delta',
        'signature': signature,
        'deltas': deltas,
    }


def record_scheduled_premarket_sent(slot: str, decision: dict[str, Any]) -> None:
    state = _load_state()
    signature = decision.get('signature') or {}
    if not decision.get('warning_only') and signature:
        state['premarket_last_signature'] = signature
        _save_state(state)
    _record_sent(
        'PRE_MARKET',
        f"slot={slot} reason={decision.get('reason') or 'sent'}",
        {'deltas': decision.get('deltas') or []},
    )


def _read_missed_today(day: str | None = None) -> list[dict[str, Any]]:
    day = day or _today()
    if not MISSED_FILE.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in MISSED_FILE.read_text(encoding='utf-8').splitlines()[-500:]:
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict) and row.get('date') == day:
                out.append(row)
    except Exception:
        return []
    return out


def log_missed_opportunity(
    signal: dict[str, Any],
    *,
    source: str = 'intraday',
    reason: str = 'entry_missed_log_only',
    alert_allowed: bool = False,
) -> None:
    ticker = str(signal.get('ticker') or signal.get('symbol') or '').strip().upper()
    if not ticker:
        return
    entry = {
        'time': _now().isoformat(),
        'date': _today(),
        'ticker': ticker,
        'source': source,
        'reason': reason,
        'score': _safe_float(signal.get('score') or signal.get('confidence') or signal.get('final_score')),
        'volume': _safe_float(signal.get('volume_ratio') or signal.get('participation') or signal.get('volume')),
        'move_pct': _safe_float(signal.get('change_percent') or signal.get('move_pct')),
        'message': 'Missed — no chase. Waiting for pullback/retest.',
        'alert_allowed': bool(alert_allowed),
    }
    try:
        MISSED_FILE.parent.mkdir(parents=True, exist_ok=True)
        with MISSED_FILE.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, separators=(',', ':')) + '\n')
    except Exception:
        pass


def _missed_seen_today(ticker: str) -> bool:
    ticker = ticker.upper()
    return any(row.get('ticker') == ticker for row in _read_missed_today())


def _score_0_100(signal: dict[str, Any], confidence: float = 0.0) -> float:
    raw = _safe_float(signal.get('score') or signal.get('final_score') or signal.get('confidence'))
    if raw <= 1.0 and raw > 0:
        raw *= 100.0
    if confidence and confidence <= 1.0:
        raw = max(raw, confidence * 100.0)
    elif confidence:
        raw = max(raw, confidence)
    return raw


def _has_useful_missed_context(signal: dict[str, Any]) -> bool:
    text = ' '.join(str(signal.get(k) or '') for k in ('reason', 'detail', 'setup', 'catalyst', 'news'))
    return any(word in text.lower() for word in ('catalyst', 'volume', 'breakout', 'fresh', 'result', 'policy'))


def should_suppress_entry_missed_intraday(ev: dict[str, Any]) -> bool:
    signal = ev.get('signal') if isinstance(ev.get('signal'), dict) else ev
    if not isinstance(signal, dict):
        return False
    try:
        from backend.telegram.response_format import classify_intraday_action_label

        label = classify_intraday_action_label(signal)
    except Exception:
        label = normalize_action(signal.get('entry_status') or signal.get('action') or signal.get('setup'))
    if label != 'ENTRY MISSED':
        return False

    ticker = str(signal.get('ticker') or signal.get('symbol') or ev.get('ticker') or '').upper()
    score = _score_0_100(signal, _safe_float(ev.get('confidence')))
    volume = _safe_float(signal.get('volume_ratio') or signal.get('participation'))
    first_today = bool(ticker) and not _missed_seen_today(ticker)
    exceptional = first_today and score >= 90.0 and volume >= 3.0 and _has_useful_missed_context(signal)
    log_missed_opportunity(
        signal,
        source='intraday',
        reason='entry_missed_exception_alert' if exceptional else 'entry_missed_log_only',
        alert_allowed=exceptional,
    )
    if exceptional:
        return False
    _record_suppression('INTRADAY_EVENT', 'entry_missed_log_only', ticker)
    return True


def missed_opportunities_summary(*, limit: int = 10) -> dict[str, Any]:
    rows = _read_missed_today()
    return {
        'date': _today(),
        'count': len(rows),
        'rows': rows[-max(1, limit):],
    }


def format_missed_opportunities(*, limit: int = 10) -> str:
    summary = missed_opportunities_summary(limit=limit)
    rows = summary.get('rows') or []
    lines = ['<b>Missed opportunities</b>', f"Today: {summary.get('count', 0)}"]
    if not rows:
        lines.append('No missed-entry setups logged today.')
        return '\n'.join(lines)
    for row in rows:
        ticker = row.get('ticker') or '?'
        move = _safe_float(row.get('move_pct'))
        vol = _safe_float(row.get('volume'))
        lines.append(f"{ticker} — ENTRY MISSED · move {move:+.1f}% · volume {vol:.1f}x")
        lines.append('Missed — no chase. Waiting for pullback/retest.')
    return '\n'.join(lines)


def daily_review_quality_buckets(
    *,
    alert_summary: dict[str, Any] | None = None,
    tradecard_counts: dict[str, Any] | None = None,
    actual_learning_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tradecard_counts_provided = tradecard_counts is not None
    if alert_summary is None:
        try:
            from backend.orchestration.alert_filters import get_telegram_alert_obs_summary

            alert_summary = get_telegram_alert_obs_summary()
        except Exception:
            alert_summary = {}
    sent_rows = alert_summary.get('recent_sent') or []
    research_watchlist = sum(1 for row in sent_rows if row.get('category') == 'PRE_MARKET')
    missed = missed_opportunities_summary(limit=200).get('count', 0)
    try:
        from backend.trading.opening_workflow_accounting import summarize_opening_workflow_accounting

        today = datetime.now(IST).date().isoformat()
        opening_workflow = summarize_opening_workflow_accounting(today)
    except Exception:
        try:
            from backend.orchestration.alert_event_log import summarize_opening_workflow_for_date

            today = datetime.now(IST).date().isoformat()
            opening_workflow = summarize_opening_workflow_for_date(today)
        except Exception:
            opening_workflow = {}
    if tradecard_counts is None:
        try:
            from backend.trading.tradecard_journal import summarize_today_outcomes

            tradecard_counts = (summarize_today_outcomes().get('counts') or {})
        except Exception:
            tradecard_counts = {}
    generated = int(tradecard_counts.get('generated') or 0)
    filled = int(tradecard_counts.get('filled') or 0)
    resolved = int(tradecard_counts.get('T1') or 0) + int(tradecard_counts.get('T2') or 0) + int(tradecard_counts.get('SL') or 0)
    opening_confirmed = int(opening_workflow.get('confirmed') or 0)
    live_confirmed = max(int(tradecard_counts.get('valid_entry') or 0), opening_confirmed)
    if actual_learning_summary is None and not tradecard_counts_provided:
        try:
            from backend.analytics.actual_learning_resolver import load_latest_actual_learning_summary

            actual_learning_summary = load_latest_actual_learning_summary()
        except Exception:
            actual_learning_summary = {}
    actual = actual_learning_summary if isinstance(actual_learning_summary, dict) else {}
    watch = actual.get('watchlist') if isinstance(actual.get('watchlist'), dict) else {}
    avoid = actual.get('avoid') if isinstance(actual.get('avoid'), dict) else {}
    tradecard_actual = actual.get('tradecard') if isinstance(actual.get('tradecard'), dict) else {}
    learning_sample_updated = int(actual.get('sample_updated') or resolved)
    pending_data = int(actual.get('pending_data') or 0)
    pending_reasons = actual.get('pending_reasons') if isinstance(actual.get('pending_reasons'), dict) else {}
    return {
        'research_watchlist_sent': research_watchlist,
        'live_confirmed_setups': live_confirmed,
        'rejected_setups': 0,
        'missed_opportunities': int(missed),
        'tradecards_generated': generated,
        'tradecards_filled': filled,
        'tradecards_resolved': resolved,
        'tradecard_wins': int(tradecard_counts.get('T1') or 0) + int(tradecard_counts.get('T2') or 0),
        'tradecard_losses': int(tradecard_counts.get('SL') or 0),
        'tradecard_neutral': int(tradecard_counts.get('no_fill') or 0),
        'tradecard_pending': int(tradecard_counts.get('pending') or 0),
        'learning_sample_updated': learning_sample_updated,
        'watchlist_win': int(watch.get('win') or 0),
        'watchlist_loss': int(watch.get('loss') or 0),
        'watchlist_neutral': int(watch.get('neutral') or 0),
        'avoid_success': int(avoid.get('success') or 0),
        'avoid_fail': int(avoid.get('fail') or 0),
        'tradecard_actual_resolved': int(tradecard_actual.get('resolved') or resolved),
        'tradecard_actual_no_fill': int(tradecard_actual.get('no_fill') or tradecard_counts.get('no_fill') or 0),
        'pending_data': pending_data,
        'pending_reasons': pending_reasons,
        'opening_workflow': opening_workflow,
    }


def format_daily_review_quality_lines(
    *,
    alert_summary: dict[str, Any] | None = None,
    tradecard_counts: dict[str, Any] | None = None,
    actual_learning_summary: dict[str, Any] | None = None,
) -> list[str]:
    b = daily_review_quality_buckets(
        alert_summary=alert_summary,
        tradecard_counts=tradecard_counts,
        actual_learning_summary=actual_learning_summary,
    )
    opening = b.get('opening_workflow') if isinstance(b.get('opening_workflow'), dict) else {}
    learning_candidates = opening.get('learning_candidates') if isinstance(opening.get('learning_candidates'), list) else []
    learning_candidate_text = ', '.join(learning_candidates[:6]) if learning_candidates else '-'
    pending_reasons = b.get('pending_reasons') if isinstance(b.get('pending_reasons'), dict) else {}
    reason_text = ', '.join(f'{k} {v}' for k, v in sorted(pending_reasons.items())) or 'none'
    lines = [
        f"Research watchlist sent: {b['research_watchlist_sent']}",
        f"Live confirmed setups: {b['live_confirmed_setups']}",
        f"Rejected setups: {b['rejected_setups']}",
        f"Missed opportunities: {b['missed_opportunities']}",
        "Opening workflow:",
        f"Radar armed: {int(opening.get('radar_armed') or 0)}",
        f"Opening radar: {int(opening.get('opening_radar') or 0)}",
        f"Early tradecards generated: {int(opening.get('early_tradecards_generated') or 0)}",
        f"Final confirmation generated: {int(opening.get('final_confirmation_generated') or 0)}",
        f"Early tradecard best: {opening.get('early_tradecard_best') or '-'}",
        f"Final confirmation best: {opening.get('final_confirmation_best') or '-'}",
        (
            "Final state: "
            f"confirmed {int(opening.get('confirmed') or 0)} · "
            f"rejected {int(opening.get('rejected') or 0)} · "
            f"wait {int(opening.get('wait_pullback') or 0)} · "
            f"pullback {int(opening.get('pullback_only') or 0)}"
        ),
        f"Learning candidate captured: {learning_candidate_text}",
        (
            "Tradecards generated/filled/resolved W/L/N/P: "
            f"{b['tradecards_generated']}/{b['tradecards_filled']}/{b['tradecards_resolved']} "
            f"{b['tradecard_wins']}/{b['tradecard_losses']}/{b['tradecard_neutral']}/{b['tradecard_pending']}"
        ),
        (
            'Watchlist resolved: '
            f"{b['watchlist_win']}/{b['watchlist_loss']}/{b['watchlist_neutral']}"
        ),
        (
            'Avoid resolved: '
            f"success {b['avoid_success']} / fail {b['avoid_fail']}"
        ),
        f"Pending data: {b['pending_data']}",
        f"Pending data reasons: {reason_text}",
        (
            'Tradecard resolved/no-fill: '
            f"{b['tradecard_actual_resolved']}/{b['tradecard_actual_no_fill']}"
        ),
        f"Actual learning sample updated: {b['learning_sample_updated']}",
    ]
    if b['tradecards_filled'] <= 0:
        lines.append('No tradecard fills today. Watchlist accuracy only.')
    return lines
