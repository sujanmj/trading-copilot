"""Post-market actual learning resolver.

Uses stored EOD/latest prices only. Does not call external AI providers.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path
from backend.storage.market_memory_outcomes import lookup_latest_price, load_latest_market_data
from backend.storage.outcome_resolver import (
    BEARISH_HIT_PCT,
    BEARISH_MISS_PCT,
    BULLISH_HIT_PCT,
    BULLISH_MISS_PCT,
    refresh_memory_dashboard_cache,
)
from backend.utils.safe_stdio import safe_print

IST = ZoneInfo('Asia/Kolkata')
HOLDING_PERIOD = 'actual_learning'
RESOLVER_VERSION = '4A'

STATE_FILE_NAME = 'actual_learning_last_run.json'

WIN = 'WIN'
LOSS = 'LOSS'
NEUTRAL = 'NEUTRAL'
NO_FILL = 'NO_FILL'
AVOID_SUCCESS = 'AVOID_SUCCESS'
AVOID_FAIL = 'AVOID_FAIL'
MISSED_OPPORTUNITY = 'MISSED_OPPORTUNITY'

NON_WL_OUTCOMES = frozenset({NO_FILL, MISSED_OPPORTUNITY})


def _now_ist() -> datetime:
    return datetime.now(IST)


def _today() -> str:
    return _now_ist().date().isoformat()


def _state_path() -> Path:
    return get_data_path(STATE_FILE_NAME)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ''):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _ticker(row: dict[str, Any]) -> str:
    return str(row.get('ticker') or row.get('symbol') or row.get('name') or '').strip().upper()


def _timestamp(row: dict[str, Any], session_date: str) -> str:
    for key in ('timestamp', 'generated_at', 'created_at', 'sampled_at', 'date'):
        value = row.get(key)
        if value:
            return str(value)
    return f'{session_date}T15:30:00+05:30'


def _signal_price(row: dict[str, Any]) -> float | None:
    for key in (
        'signal_price',
        'price_at_signal',
        'entry_price',
        'current_price',
        'price',
        'ltp',
        'last_price',
        'close',
    ):
        val = _safe_float(row.get(key))
        if val is not None and val > 0:
            return val
    return None


def _score(row: dict[str, Any]) -> float | None:
    for key in ('score', 'final_score', 'confidence'):
        val = _safe_float(row.get(key))
        if val is not None:
            return val
    return None


def _category_from_row(row: dict[str, Any], default: str) -> str:
    explicit = str(row.get('learning_category') or row.get('category') or '').strip().lower()
    if explicit in ('tradecard', 'top_watch', 'watchlist', 'scanner_watch', 'avoid', 'missed'):
        return 'top_watch' if explicit == 'watchlist' else explicit
    action = str(row.get('action') or row.get('status') or row.get('entry_status') or '').upper()
    if 'MISSED' in action:
        return 'missed'
    if 'AVOID' in action or 'REJECT' in action or 'BEARISH' in action:
        return 'avoid'
    return default


def _is_next_session_only(row: dict[str, Any]) -> bool:
    text = ' '.join(str(row.get(k) or '') for k in ('action', 'status', 'reason', 'path_note', 'entry_status'))
    upper = text.upper()
    return (
        'NEXT-SESSION WATCH' in upper
        or 'NEXT_SESSION_WATCH' in upper
        or 'NO ACTIVE ENTRY' in upper
        or str(row.get('carry_forward_next_session') or '').strip().lower() in ('1', 'true', 'yes', 'on')
    )


def _candidate(
    row: dict[str, Any],
    *,
    category: str,
    session_date: str,
    source: str,
) -> dict[str, Any] | None:
    sym = _ticker(row)
    if not sym or _is_next_session_only(row):
        return None
    direction = 'BEARISH' if category == 'avoid' else 'BULLISH'
    if str(row.get('direction') or '').strip().upper() == 'BEARISH':
        direction = 'BEARISH'
    return {
        'ticker': sym,
        'category': category,
        'source': source,
        'timestamp': _timestamp(row, session_date),
        'direction': direction,
        'signal_price': _signal_price(row),
        'score': _score(row),
        'raw': dict(row),
    }


def _tradecard_candidates(session_date: str) -> list[dict[str, Any]]:
    try:
        from backend.trading.tradecard_journal import summarize_today_outcomes

        rows = summarize_today_outcomes(session_date=session_date).get('rows') or []
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get('status') or '').upper() != 'VALID_ENTRY':
            continue
        if _is_next_session_only(row):
            continue
        sym = _ticker(row)
        if not sym:
            continue
        out.append({
            'ticker': sym,
            'category': 'tradecard',
            'source': 'tradecard_journal',
            'timestamp': str(row.get('created_at') or row.get('generated_at') or f'{session_date}T15:30:00+05:30'),
            'direction': 'BULLISH',
            'signal_price': _safe_float(row.get('price_at_signal')),
            'score': None,
            'raw': dict(row),
        })
    return out


def _missed_candidates(session_date: str) -> list[dict[str, Any]]:
    try:
        from backend.orchestration.alert_quality_engine import missed_opportunities_summary

        rows = missed_opportunities_summary(limit=200).get('rows') or []
    except Exception:
        rows = []
    out = []
    for row in rows:
        item = _candidate(row, category='missed', session_date=session_date, source='missed_opportunities')
        if item:
            out.append(item)
    return out


def _rows_from_payload(payload: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in keys:
        val = payload.get(key)
        if isinstance(val, list):
            rows.extend([r for r in val if isinstance(r, dict)])
        elif isinstance(val, dict):
            rows.append(val)
    return rows


def _source_candidates(session_date: str, sources: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if sources is None:
        sources = {
            'stock_today': _load_json(get_data_path('stock_decision_today.json')),
            'daily_pack': _load_json(get_data_path('daily_report_pack_latest.json')),
            'final_confidence': _load_json(get_data_path('final_confidence_report.json')),
            'tomorrow_watchlist': _load_json(get_data_path('tomorrow_watchlist_report.json')),
            'scanner': _load_json(get_data_path('scanner_data.json')),
        }

    candidates: list[dict[str, Any]] = []
    for row in sources.get('tradecards') or []:
        if isinstance(row, dict):
            item = _candidate(row, category='tradecard', session_date=session_date, source='tradecard_test')
            if item:
                candidates.append(item)
    if 'tradecards' not in sources:
        candidates.extend(_tradecard_candidates(session_date))

    for source_name, payload in (
        ('stock_today', sources.get('stock_today') or {}),
        ('final_confidence', sources.get('final_confidence') or {}),
    ):
        if isinstance(payload, dict):
            for row in _rows_from_payload(payload, 'top_pick', 'ranked_candidates', 'top_candidates', 'rows'):
                category = _category_from_row(row, 'top_watch')
                item = _candidate(row, category=category, session_date=session_date, source=source_name)
                if item:
                    candidates.append(item)

    pack = sources.get('daily_pack') or {}
    if isinstance(pack, dict):
        tw = pack.get('tomorrow_watchlist') if isinstance(pack.get('tomorrow_watchlist'), dict) else {}
        for row in _rows_from_payload(tw, 'top_watchlist', 'raw_candidates'):
            item = _candidate(row, category='top_watch', session_date=session_date, source='daily_pack_watchlist')
            if item:
                candidates.append(item)
        for row in _rows_from_payload(tw, 'avoid'):
            item = _candidate(row, category='avoid', session_date=session_date, source='daily_pack_avoid')
            if item:
                candidates.append(item)

    tw_report = sources.get('tomorrow_watchlist') or {}
    if isinstance(tw_report, dict):
        for row in _rows_from_payload(tw_report, 'top_watchlist', 'raw_candidates'):
            item = _candidate(row, category='top_watch', session_date=session_date, source='watchlist_report')
            if item:
                candidates.append(item)
        for row in _rows_from_payload(tw_report, 'avoid'):
            item = _candidate(row, category='avoid', session_date=session_date, source='watchlist_report')
            if item:
                candidates.append(item)

    scanner = sources.get('scanner') or {}
    if isinstance(scanner, dict):
        for row in _rows_from_payload(scanner, 'top_signals', 'signals'):
            category = _category_from_row(row, 'scanner_watch')
            item = _candidate(row, category=category, session_date=session_date, source='scanner_data')
            if item:
                candidates.append(item)

    for row in sources.get('missed') or []:
        if isinstance(row, dict):
            item = _candidate(row, category='missed', session_date=session_date, source='missed_test')
            if item:
                candidates.append(item)
    if 'missed' not in sources:
        candidates.extend(_missed_candidates(session_date))

    return _dedupe_candidates(candidates)


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority = {
        'tradecard': 0,
        'top_watch': 1,
        'scanner_watch': 2,
        'avoid': 3,
        'missed': 4,
    }
    picked: dict[tuple[str, str], dict[str, Any]] = {}
    for item in candidates:
        group = item.get('category')
        if group in ('top_watch', 'scanner_watch'):
            group = 'bullish_watch'
        key = (str(item.get('ticker') or ''), str(group or ''))
        existing = picked.get(key)
        if existing is None or priority.get(str(item.get('category')), 99) < priority.get(str(existing.get('category')), 99):
            picked[key] = item
    return list(picked.values())


def _latest_price_entry(market_data: dict[str, Any], ticker: str) -> dict[str, Any]:
    prices = market_data.get('prices') if isinstance(market_data, dict) else {}
    if not isinstance(prices, dict):
        return {}
    for key, val in prices.items():
        if str(key).strip().upper() == ticker and isinstance(val, dict):
            return val
    return {}


def _actual_move(signal_price: float | None, latest_price: float | None) -> float | None:
    if signal_price is None or latest_price is None or signal_price <= 0:
        return None
    return round(((latest_price - signal_price) / signal_price) * 100.0, 4)


def _tradecard_outcome(item: dict[str, Any]) -> tuple[str | None, str | None, float | None]:
    raw = item.get('raw') if isinstance(item.get('raw'), dict) else {}
    outcome = str(raw.get('outcome_status') or '').upper()
    if outcome in ('T1_HIT', 'T2_HIT'):
        return WIN, outcome, _actual_move(item.get('signal_price'), _safe_float(raw.get('outcome_price')))
    if outcome in ('SL_HIT', 'AMBIGUOUS'):
        return LOSS, outcome, _actual_move(item.get('signal_price'), _safe_float(raw.get('outcome_price')))
    if outcome == 'NO_FILL':
        return NO_FILL, NO_FILL, None
    if outcome == 'EXPIRED':
        return NEUTRAL, 'EXPIRED', _actual_move(item.get('signal_price'), _safe_float(raw.get('outcome_price')))
    return None, 'pending_data', None


def _classify_item(item: dict[str, Any], market_data: dict[str, Any] | None) -> dict[str, Any]:
    category = str(item.get('category') or '')
    if category == 'tradecard':
        resolved_as, expiry_result, move = _tradecard_outcome(item)
        if resolved_as is None:
            return {'status': 'pending_data', 'reason': expiry_result or 'tradecard pending'}
        return {'status': 'resolved', 'resolved_as': resolved_as, 'expiry_result': expiry_result, 'actual_move': move}

    if not market_data:
        return {'status': 'pending_data', 'reason': 'missing_market_data'}

    ticker = str(item.get('ticker') or '')
    latest = lookup_latest_price(market_data, ticker)
    signal = _safe_float(item.get('signal_price'))
    if signal is None or signal <= 0:
        return {'status': 'pending_data', 'reason': 'missing_signal_price'}
    if latest is None or latest <= 0:
        return {'status': 'pending_data', 'reason': 'missing_latest_price'}
    move = _actual_move(signal, latest)
    if move is None:
        return {'status': 'pending_data', 'reason': 'missing_price_move'}

    if category == 'avoid':
        if move <= BEARISH_HIT_PCT:
            return {'status': 'resolved', 'resolved_as': AVOID_SUCCESS, 'expiry_result': AVOID_SUCCESS, 'actual_move': move}
        if move >= BEARISH_MISS_PCT:
            return {'status': 'resolved', 'resolved_as': AVOID_FAIL, 'expiry_result': AVOID_FAIL, 'actual_move': move}
        return {'status': 'resolved', 'resolved_as': NEUTRAL, 'expiry_result': NEUTRAL, 'actual_move': move}
    if category == 'missed':
        return {'status': 'resolved', 'resolved_as': MISSED_OPPORTUNITY, 'expiry_result': MISSED_OPPORTUNITY, 'actual_move': move}

    if move >= BULLISH_HIT_PCT:
        return {'status': 'resolved', 'resolved_as': WIN, 'expiry_result': WIN, 'actual_move': move}
    if move <= BULLISH_MISS_PCT:
        return {'status': 'resolved', 'resolved_as': LOSS, 'expiry_result': LOSS, 'actual_move': move}
    return {'status': 'resolved', 'resolved_as': NEUTRAL, 'expiry_result': NEUTRAL, 'actual_move': move}


def _prediction_payload(item: dict[str, Any], session_date: str) -> dict[str, Any]:
    source = f"actual_learning:{item.get('category')}"
    raw = {
        **(item.get('raw') if isinstance(item.get('raw'), dict) else {}),
        'actual_learning_category': item.get('category'),
        'source': source,
        'prediction_date': session_date,
        'run_type': 'actual_learning',
        'signal_price': item.get('signal_price'),
    }
    return {
        'ticker': item.get('ticker'),
        'timestamp': item.get('timestamp') or f'{session_date}T15:30:00+05:30',
        'source': source,
        'direction': item.get('direction') or 'BULLISH',
        'confidence': item.get('score'),
        'confidence_label': None,
        'reasoning': f"actual learning {item.get('category')}",
        'raw_payload': raw,
        'signal_stack': {
            'signal_type': item.get('category'),
            'prediction_horizon': 'intraday',
        },
    }


def _outcome_exists(prediction_id: str) -> bool:
    try:
        from backend.storage import market_memory_db as mmdb

        mmdb.init_market_memory_db()
        conn = mmdb.get_connection()
        try:
            row = conn.execute(
                'SELECT 1 FROM outcomes WHERE prediction_id = ? AND holding_period = ? LIMIT 1',
                (prediction_id, HOLDING_PERIOD),
            ).fetchone()
            return row is not None
        finally:
            conn.close()
    except Exception:
        return False


def _write_state(summary: dict[str, Any], *, state_path: Path | None = None) -> None:
    try:
        path = state_path or _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, indent=2, default=str), encoding='utf-8')
    except Exception:
        pass


def load_latest_actual_learning_summary(*, state_path: Path | None = None) -> dict[str, Any]:
    return _load_json(state_path or _state_path())


def _empty_summary(session_date: str) -> dict[str, Any]:
    return {
        'ok': True,
        'resolver': 'actual_learning',
        'version': RESOLVER_VERSION,
        'session_date': session_date,
        'started_at': _now_ist().isoformat(),
        'finished_at': '',
        'candidates': 0,
        'predictions_tracked': 0,
        'sample_updated': 0,
        'written': 0,
        'already_resolved': 0,
        'pending_data': 0,
        'errors': 0,
        'watchlist': {'win': 0, 'loss': 0, 'neutral': 0},
        'avoid': {'success': 0, 'fail': 0, 'neutral': 0},
        'tradecard': {'resolved': 0, 'no_fill': 0},
        'missed_opportunities': 0,
        'latest_outcomes': [],
        'pending_items': [],
        'market_memory': {
            'predictions_tracked': 0,
            'resolved_outcomes': 0,
            'pending_outcomes': 0,
            'hit_rate': None,
            'bullish_hit_rate': None,
            'avoid_rejection_hit_rate': None,
            'last_resolved_timestamp': None,
        },
        'explanation': {
            'best_signal_today': 'No resolved signal yet.',
            'worst_signal_today': 'No resolved loss signal yet.',
            'trust_tomorrow': 'Require fresh price and volume confirmation.',
            'reduce_tomorrow': 'Reduce stale or unresolved setups.',
        },
    }


def _record_bucket(summary: dict[str, Any], item: dict[str, Any], result: dict[str, Any]) -> None:
    category = str(item.get('category') or '')
    resolved_as = str(result.get('resolved_as') or '').upper()
    if category in ('top_watch', 'scanner_watch'):
        key = 'neutral'
        if resolved_as == WIN:
            key = 'win'
        elif resolved_as == LOSS:
            key = 'loss'
        summary['watchlist'][key] += 1
    elif category == 'avoid':
        if resolved_as == AVOID_SUCCESS:
            summary['avoid']['success'] += 1
        elif resolved_as == AVOID_FAIL:
            summary['avoid']['fail'] += 1
        else:
            summary['avoid']['neutral'] += 1
    elif category == 'tradecard':
        if resolved_as == NO_FILL:
            summary['tradecard']['no_fill'] += 1
        else:
            summary['tradecard']['resolved'] += 1
    elif category == 'missed':
        summary['missed_opportunities'] += 1


def _counts_as_learning_sample(resolved_as: str) -> bool:
    token = str(resolved_as or '').upper()
    return token not in NON_WL_OUTCOMES


def _build_explanation(outcomes: list[dict[str, Any]]) -> dict[str, str]:
    scored = [row for row in outcomes if isinstance(row.get('actual_move'), (int, float))]
    best = max(scored, key=lambda r: float(r.get('actual_move') or 0), default=None)
    worst = min(scored, key=lambda r: float(r.get('actual_move') or 0), default=None)
    winners = [row for row in outcomes if str(row.get('resolved_as') or '').upper() in (WIN, AVOID_SUCCESS)]
    losers = [row for row in outcomes if str(row.get('resolved_as') or '').upper() in (LOSS, AVOID_FAIL)]
    return {
        'best_signal_today': (
            f"{best.get('ticker')} {best.get('resolved_as')} {float(best.get('actual_move') or 0):+.2f}%"
            if best else 'No resolved signal yet.'
        ),
        'worst_signal_today': (
            f"{worst.get('ticker')} {worst.get('resolved_as')} {float(worst.get('actual_move') or 0):+.2f}%"
            if worst else 'No resolved loss signal yet.'
        ),
        'trust_tomorrow': (
            f"Trust {winners[0].get('category')} setups with fresh price/volume confirmation."
            if winners else 'Trust only setups with fresh price and volume confirmation.'
        ),
        'reduce_tomorrow': (
            f"Reduce {losers[0].get('category')} patterns that failed today."
            if losers else 'Reduce stale or unresolved setups.'
        ),
    }


def _attach_market_memory_summary(summary: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        summary['market_memory'] = {
            'predictions_tracked': int(summary.get('candidates') or 0),
            'resolved_outcomes': len(summary.get('latest_outcomes') or []),
            'pending_outcomes': int(summary.get('pending_data') or 0),
            'hit_rate': None,
            'bullish_hit_rate': None,
            'avoid_rejection_hit_rate': None,
            'last_resolved_timestamp': summary.get('finished_at'),
        }
        return
    try:
        from backend.storage.outcome_resolver import get_canonical_outcome_stats

        stats = get_canonical_outcome_stats()
        summary['market_memory'] = {
            'predictions_tracked': int(stats.get('predictions_tracked') or 0),
            'resolved_outcomes': int(stats.get('resolved_total') or 0),
            'pending_outcomes': int(stats.get('pending_total') or 0),
            'hit_rate': stats.get('hit_rate'),
            'bullish_hit_rate': stats.get('bullish_hit_rate'),
            'avoid_rejection_hit_rate': stats.get('bearish_hit_rate'),
            'last_resolved_timestamp': stats.get('last_resolved_at'),
        }
    except Exception:
        summary['market_memory'] = {
            'predictions_tracked': int(summary.get('predictions_tracked') or 0),
            'resolved_outcomes': len(summary.get('latest_outcomes') or []),
            'pending_outcomes': int(summary.get('pending_data') or 0),
            'hit_rate': None,
            'bullish_hit_rate': None,
            'avoid_rejection_hit_rate': None,
            'last_resolved_timestamp': summary.get('finished_at'),
        }


def run_actual_learning_resolver(
    *,
    session_date: str | None = None,
    market_data: dict[str, Any] | None = None,
    sources: dict[str, Any] | None = None,
    dry_run: bool = False,
    refresh_cache: bool = True,
    state_path: Path | None = None,
) -> dict[str, Any]:
    """Resolve today's actual-learning samples. Idempotent per symbol/date/category."""
    from backend.storage import market_memory_db as mmdb

    day = session_date or _today()
    summary = _empty_summary(day)
    data = market_data if market_data is not None else load_latest_market_data()
    candidates = _source_candidates(day, sources=sources)
    summary['candidates'] = len(candidates)
    if not dry_run:
        mmdb.init_market_memory_db()

    for item in candidates:
        try:
            prediction = _prediction_payload(item, day)
            prediction_id = mmdb.make_canonical_prediction_id(prediction, source_hint=prediction.get('source'))
            prediction['prediction_id'] = prediction_id
            result = _classify_item(item, data)
            if result.get('status') == 'pending_data':
                summary['pending_data'] += 1
                summary['pending_items'].append({
                    'ticker': item.get('ticker'),
                    'category': item.get('category'),
                    'reason': result.get('reason'),
                })
                if not dry_run:
                    mmdb.upsert_prediction(prediction)
                    summary['predictions_tracked'] += 1
                continue
            resolved_as = str(result.get('resolved_as') or '').upper()
            if not dry_run and _outcome_exists(prediction_id):
                summary['already_resolved'] += 1
                if _counts_as_learning_sample(resolved_as):
                    summary['sample_updated'] += 1
                _record_bucket(summary, item, result)
                summary['latest_outcomes'].append({
                    'ticker': item.get('ticker'),
                    'category': item.get('category'),
                    'resolved_as': resolved_as,
                    'actual_move': result.get('actual_move'),
                })
                continue
            outcome = {
                'prediction_id': prediction_id,
                'actual_move': result.get('actual_move'),
                'high': _latest_price_entry(data or {}, str(item.get('ticker') or '')).get('high') if data else None,
                'low': _latest_price_entry(data or {}, str(item.get('ticker') or '')).get('low') if data else None,
                'expiry_result': result.get('expiry_result'),
                'resolved_as': result.get('resolved_as'),
                'holding_period': HOLDING_PERIOD,
                'raw_payload': {
                    'source': 'actual_learning_resolver',
                    'resolver_version': RESOLVER_VERSION,
                    'category': item.get('category'),
                    'ticker': item.get('ticker'),
                    'session_date': day,
                    'signal_price': item.get('signal_price'),
                    'result': result,
                },
            }
            if not dry_run:
                pid = mmdb.upsert_prediction(prediction)
                if not pid:
                    summary['errors'] += 1
                    continue
                if not mmdb.upsert_outcome(outcome):
                    summary['errors'] += 1
                    continue
                summary['written'] += 1
                summary['predictions_tracked'] += 1
            if _counts_as_learning_sample(resolved_as):
                summary['sample_updated'] += 1
            _record_bucket(summary, item, result)
            summary['latest_outcomes'].append({
                'ticker': item.get('ticker'),
                'category': item.get('category'),
                'resolved_as': resolved_as,
                'actual_move': result.get('actual_move'),
            })
        except Exception:
            summary['errors'] += 1

    summary['explanation'] = _build_explanation(summary['latest_outcomes'])
    summary['finished_at'] = _now_ist().isoformat()
    _attach_market_memory_summary(summary, dry_run=dry_run)
    if not dry_run:
        _write_state(summary, state_path=state_path)
        if refresh_cache and (summary['written'] > 0 or summary['pending_data'] > 0):
            refresh_memory_dashboard_cache()
    safe_print(
        f"[ACTUAL_LEARNING_RESOLVER] date={day} sample_updated={summary['sample_updated']} "
        f"watchlist={summary['watchlist']} avoid={summary['avoid']} "
        f"pending_data={summary['pending_data']} errors={summary['errors']}",
        flush=True,
    )
    return summary


def format_actual_learning_close_lines(summary: dict[str, Any] | None = None) -> list[str]:
    data = summary if isinstance(summary, dict) else load_latest_actual_learning_summary()
    if not data:
        return ['Actual learning sample updated: 0']
    watch = data.get('watchlist') or {}
    avoid = data.get('avoid') or {}
    tradecard = data.get('tradecard') or {}
    explanation = data.get('explanation') or {}
    return [
        f"Actual learning sample updated: {int(data.get('sample_updated') or 0)}",
        (
            'Watchlist resolved: '
            f"{int(watch.get('win') or 0)}/{int(watch.get('loss') or 0)}/{int(watch.get('neutral') or 0)}"
        ),
        (
            'Avoid resolved: '
            f"success {int(avoid.get('success') or 0)} / fail {int(avoid.get('fail') or 0)}"
        ),
        (
            'Tradecard resolved/no-fill: '
            f"{int(tradecard.get('resolved') or 0)}/{int(tradecard.get('no_fill') or 0)}"
        ),
        f"Best signal today: {explanation.get('best_signal_today') or 'No resolved signal yet.'}",
        f"Worst signal today: {explanation.get('worst_signal_today') or 'No resolved loss signal yet.'}",
        f"What to trust tomorrow: {explanation.get('trust_tomorrow') or 'Fresh price + volume confirmation.'}",
        f"What to reduce tomorrow: {explanation.get('reduce_tomorrow') or 'Stale or unresolved setups.'}",
    ]
