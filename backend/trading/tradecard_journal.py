"""
Tradecard journal — outcome sequencing and active trade lock (Stage 50Z).

Paper-only tracking. Never places orders.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from backend.utils.config import DATA_DIR

IST = __import__('zoneinfo').ZoneInfo('Asia/Kolkata')

JOURNAL_FILE = DATA_DIR / 'tradecard_journal.jsonl'
PATH_SAMPLES_FILE = DATA_DIR / 'tradecard_path_samples.jsonl'

OUTCOME_PENDING = 'PENDING'
OUTCOME_NO_FILL = 'NO_FILL'
OUTCOME_T1_HIT = 'T1_HIT'
OUTCOME_T2_HIT = 'T2_HIT'
OUTCOME_SL_HIT = 'SL_HIT'
OUTCOME_EXPIRED = 'EXPIRED'
OUTCOME_AMBIGUOUS = 'AMBIGUOUS'

TERMINAL_OUTCOMES = frozenset({
    OUTCOME_T1_HIT, OUTCOME_T2_HIT, OUTCOME_SL_HIT, OUTCOME_NO_FILL,
    OUTCOME_EXPIRED, OUTCOME_AMBIGUOUS,
})
ACTIVE_OUTCOMES = frozenset({OUTCOME_PENDING, OUTCOME_NO_FILL})

RESOLVE_COOLDOWN_MINUTES = 30


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _today() -> str:
    return datetime.now(IST).strftime('%Y-%m-%d')


def _parse_ts(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    except ValueError:
        return None


def parse_entry_bounds(entry_zone: object) -> tuple[float | None, float | None]:
    raw = str(entry_zone or '').replace('–', '-').replace('—', '-').strip()
    if not raw or 'NO ACTIVE' in raw.upper():
        return None, None
    if '-' in raw:
        parts = [p.strip() for p in raw.split('-', 1)]
        try:
            return float(parts[0]), float(parts[1])
        except (TypeError, ValueError, IndexError):
            return None, None
    try:
        val = float(raw)
        return val, val
    except (TypeError, ValueError):
        return None, None


def _safe_float(value: object) -> float | None:
    try:
        if value in (None, '', '—', '-'):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_journal() -> list[dict[str, Any]]:
    if not JOURNAL_FILE.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in JOURNAL_FILE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except json.JSONDecodeError:
            continue
    return rows


def _write_journal(rows: list[dict[str, Any]]) -> None:
    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL_FILE.open('w', encoding='utf-8') as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')


def _append_path_sample_line(sample: dict[str, Any]) -> dict[str, Any]:
    PATH_SAMPLES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PATH_SAMPLES_FILE.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(sample, ensure_ascii=False) + '\n')
    return sample


def append_path_sample(
    *,
    tradecard_id: str,
    ticker: str,
    price: float,
    high: float | None = None,
    low: float | None = None,
    volume: float | None = None,
    participation: str | None = None,
    source: str = 'quote_refresh',
    sampled_at: str | None = None,
) -> dict[str, Any]:
    """Append one post-signal quote/candle sample for outcome path tracking."""
    sample = {
        'tradecard_id': str(tradecard_id),
        'ticker': str(ticker or '').strip().upper(),
        'sampled_at': sampled_at or _now_iso(),
        'price': round(float(price), 4),
        'high': round(float(high if high is not None else price), 4),
        'low': round(float(low if low is not None else price), 4),
        'volume': volume,
        'participation': participation,
        'source': source,
    }
    return _append_path_sample_line(sample)


def load_path_samples(tradecard_id: str) -> list[dict[str, Any]]:
    tid = str(tradecard_id or '').strip()
    if not tid or not PATH_SAMPLES_FILE.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in PATH_SAMPLES_FILE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or str(row.get('tradecard_id') or '') != tid:
            continue
        rows.append(row)
    rows.sort(key=lambda r: str(r.get('sampled_at') or ''))
    return rows


def _price_entry_for_ticker(market_data: dict[str, Any], ticker: str) -> dict[str, Any] | None:
    prices = market_data.get('prices') if isinstance(market_data, dict) else None
    if not isinstance(prices, dict):
        return None
    sym = str(ticker or '').strip().upper()
    if sym in prices and isinstance(prices[sym], dict):
        return prices[sym]
    for key, val in prices.items():
        if str(key).strip().upper() == sym and isinstance(val, dict):
            return val
    return None


def build_quote_path_sample(
    record: dict[str, Any],
    market_data: dict[str, Any] | None,
    *,
    source: str = 'quote_refresh',
) -> dict[str, Any] | None:
    """Build and append a path sample from latest quote data."""
    from backend.storage.market_memory_outcomes import lookup_latest_price

    ticker = str(record.get('ticker') or '').strip().upper()
    record_id = str(record.get('id') or '')
    if not ticker or not record_id or not market_data:
        return None
    price = lookup_latest_price(market_data, ticker)
    if price is None:
        return None
    entry = _price_entry_for_ticker(market_data, ticker) or {}
    high = _safe_float(entry.get('high')) or price
    low = _safe_float(entry.get('low')) or price
    volume = _safe_float(entry.get('volume'))
    participation = str(entry.get('participation') or entry.get('volume_status') or '').strip() or None
    return append_path_sample(
        tradecard_id=record_id,
        ticker=ticker,
        price=price,
        high=high,
        low=low,
        volume=volume,
        participation=participation,
        source=source,
    )


def samples_to_resolver_path(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    path: list[dict[str, Any]] = []
    for sample in samples:
        path.append({
            'ts': sample.get('sampled_at'),
            'price': sample.get('price'),
            'high': sample.get('high', sample.get('price')),
            'low': sample.get('low', sample.get('price')),
        })
    return path


def _format_sample_time(sampled_at: object) -> str:
    dt = _parse_ts(sampled_at)
    if dt is None:
        return '—'
    return dt.strftime('%H:%M')


def _format_outcome_result_lines(row: dict[str, Any]) -> list[str]:
    samples = load_path_samples(str(row.get('id') or ''))
    outcome = str(row.get('outcome_status') or OUTCOME_PENDING).upper()
    signal = _safe_float(row.get('price_at_signal'))
    note = str(row.get('path_note') or '').strip()

    if not samples:
        if outcome in TERMINAL_OUTCOMES or (note and note not in ('', 'no after-signal path')):
            if outcome == OUTCOME_AMBIGUOUS:
                label = f'{OUTCOME_AMBIGUOUS} / {row.get("conservative_result") or OUTCOME_SL_HIT}'
                detail = note or label
                return [f'   Result: {label} — {detail}']
            detail = note or outcome.lower().replace('_', ' ')
            return [f'   Result: {outcome} — {detail}']
        return [
            '   Result: pending — no post-signal quote sample yet',
            '   Plan: refresh outcome again after next price update',
        ]

    latest = samples[-1]
    latest_price = _safe_float(latest.get('price'))
    latest_time = _format_sample_time(latest.get('sampled_at'))
    path_line = (
        f'   Path: signal {signal or "—"} → latest {latest_price or "—"} at {latest_time}'
    )

    if outcome == OUTCOME_AMBIGUOUS:
        label = f'{OUTCOME_AMBIGUOUS} / {row.get("conservative_result") or OUTCOME_SL_HIT}'
        result = f'   Result: {label}'
        if note:
            result = f'   Result: {label} — {note}'
    elif outcome == OUTCOME_PENDING:
        detail = note or 'awaiting SL/T1/T2 after fill'
        result = f'   Result: {OUTCOME_PENDING} — {detail}'
    else:
        detail = note or outcome.lower().replace('_', ' ')
        result = f'   Result: {outcome} — {detail}'

    return [result, path_line]


def _load_market_data_with_optional_refresh(*, refresh: bool) -> dict[str, Any] | None:
    if refresh:
        try:
            from backend.trading.tradecard_refresh import _run_lightweight_refresh

            _run_lightweight_refresh()
        except Exception:
            pass
    try:
        from backend.storage.market_memory_outcomes import load_latest_market_data

        return load_latest_market_data()
    except Exception:
        return None


def track_active_tradecard_outcome(
    active: dict[str, Any],
    *,
    refresh: bool = False,
    source: str = 'quote_refresh',
) -> dict[str, Any] | None:
    """Append latest quote sample for an active card and re-run resolver."""
    market_data = _load_market_data_with_optional_refresh(refresh=refresh)
    if market_data:
        build_quote_path_sample(active, market_data, source=source)
    samples = load_path_samples(str(active.get('id') or ''))
    return apply_path_to_journal_record(active, samples_to_resolver_path(samples))


def sample_and_resolve_pending_tradecards(
    *,
    session_date: str | None = None,
    expire_at_close: bool = False,
    refresh: bool = True,
) -> dict[str, Any]:
    """Refresh quotes for active tradecards, append path samples, then resolve outcomes."""
    day = session_date or _today()
    summary: dict[str, Any] = {'checked': 0, 'sampled': 0, 'updated': 0, 'errors': 0}
    pending_rows: list[dict[str, Any]] = []
    for row in _read_journal():
        if str(row.get('session_date') or '') != day:
            continue
        if str(row.get('status') or '').upper() != 'VALID_ENTRY':
            continue
        prior = str(row.get('outcome_status') or OUTCOME_PENDING).upper()
        if prior not in ACTIVE_OUTCOMES:
            continue
        pending_rows.append(row)

    market_data = _load_market_data_with_optional_refresh(refresh=refresh and bool(pending_rows))

    for row in pending_rows:
        summary['checked'] += 1
        prior = str(row.get('outcome_status') or OUTCOME_PENDING).upper()
        try:
            if market_data:
                sample = build_quote_path_sample(row, market_data, source='quote_refresh')
                if sample:
                    summary['sampled'] += 1
            samples = load_path_samples(str(row.get('id') or ''))
            updated = apply_path_to_journal_record(
                row,
                samples_to_resolver_path(samples),
                expire_at_close=expire_at_close,
            )
            if updated and str(updated.get('outcome_status') or '').upper() != prior:
                summary['updated'] += 1
        except Exception:
            summary['errors'] += 1
    return summary


def journal_record_from_card(
    card: dict[str, Any],
    *,
    freshness_meta: dict[str, Any] | None = None,
    source_label: str = '',
) -> dict[str, Any]:
    meta = freshness_meta or {}
    entry_low, entry_high = parse_entry_bounds(card.get('entry_zone'))
    return {
        'id': uuid.uuid4().hex[:12],
        'created_at': str(card.get('generated_at') or _now_iso()),
        'session_date': str(card.get('session_date') or _today()),
        'ticker': str(card.get('ticker') or '').strip().upper(),
        'status': str(card.get('status') or 'NO_TRADE').upper(),
        'source_label': source_label or str(card.get('source_label') or ''),
        'freshness': meta,
        'price_at_signal': _safe_float(card.get('current_price')),
        'entry_low': entry_low,
        'entry_high': entry_high,
        'stop': _safe_float(card.get('stop_loss')),
        't1': _safe_float(card.get('target_1')),
        't2': _safe_float(card.get('target_2')),
        'confidence': str(card.get('confidence') or ''),
        'reason': str(card.get('reason') or '')[:240],
        'market_mode': meta.get('market_mode') or '',
        'scanner_age': meta.get('scanner_age_seconds'),
        'quote_age': meta.get('quote_age_seconds'),
        'outcome_status': OUTCOME_PENDING if card.get('status') == 'VALID_ENTRY' else '',
        'outcome_time': '',
        'outcome_price': None,
        'path_note': '',
        'filled_at': '',
        'conservative_result': '',
    }


def append_journal_record(record: dict[str, Any]) -> dict[str, Any]:
    rows = _read_journal()
    rows.append(record)
    _write_journal(rows)
    return record


def update_journal_record(record_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    rows = _read_journal()
    updated: dict[str, Any] | None = None
    for idx, row in enumerate(rows):
        if str(row.get('id')) != str(record_id):
            continue
        merged = {**row, **patch}
        rows[idx] = merged
        updated = merged
        break
    if updated:
        _write_journal(rows)
    return updated


def get_active_valid_entry(ticker: str, *, session_date: str | None = None) -> dict[str, Any] | None:
    sym = str(ticker or '').strip().upper()
    if not sym:
        return None
    day = session_date or _today()
    for row in reversed(_read_journal()):
        if str(row.get('session_date') or '') != day:
            continue
        if str(row.get('ticker') or '').upper() != sym:
            continue
        if str(row.get('status') or '').upper() != 'VALID_ENTRY':
            continue
        outcome = str(row.get('outcome_status') or OUTCOME_PENDING).upper()
        if outcome in ACTIVE_OUTCOMES:
            return row
    return None


def can_issue_new_valid_entry(ticker: str, *, card: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
    active = get_active_valid_entry(ticker)
    if active:
        return False, active
    sym = str(ticker or '').strip().upper()
    day = _today()
    cooldown = timedelta(minutes=RESOLVE_COOLDOWN_MINUTES)
    now = datetime.now(IST)
    entry_low, entry_high = parse_entry_bounds(card.get('entry_zone'))
    for row in reversed(_read_journal()):
        if str(row.get('ticker') or '').upper() != sym:
            continue
        if str(row.get('session_date') or '') != day:
            continue
        if str(row.get('status') or '').upper() != 'VALID_ENTRY':
            continue
        outcome = str(row.get('outcome_status') or '').upper()
        if outcome not in TERMINAL_OUTCOMES:
            continue
        resolved_at = _parse_ts(row.get('outcome_time') or row.get('created_at'))
        if resolved_at and now - resolved_at < cooldown:
            return False, row
        old_low = _safe_float(row.get('entry_low'))
        old_high = _safe_float(row.get('entry_high'))
        if (
            entry_low is not None and entry_high is not None
            and old_low is not None and old_high is not None
            and abs(entry_low - old_low) < 0.05
            and abs(entry_high - old_high) < 0.05
        ):
            return False, row
    return True, None


def resolve_outcome_sequence(
    *,
    entry_low: float,
    entry_high: float,
    stop: float,
    t1: float,
    t2: float,
    path: list[dict[str, Any]],
    signal_time: str | None = None,
    expire_at_close: bool = False,
) -> dict[str, Any]:
    """Resolve outcome using quotes/candles after signal time only."""
    signal_dt = _parse_ts(signal_time) or _parse_ts(path[0].get('ts') if path else None)
    ordered: list[dict[str, Any]] = []
    for pt in path:
        ts = _parse_ts(pt.get('ts'))
        if signal_dt and ts and ts < signal_dt:
            continue
        ordered.append({
            'ts': ts or datetime.now(IST),
            'price': _safe_float(pt.get('price')),
            'high': _safe_float(pt.get('high', pt.get('price'))),
            'low': _safe_float(pt.get('low', pt.get('price'))),
        })
    ordered.sort(key=lambda x: x['ts'])

    if not ordered:
        return {
            'outcome_status': OUTCOME_PENDING,
            'path_note': 'no after-signal path',
            'conservative_result': '',
        }

    filled_at: datetime | None = None
    for pt in ordered:
        high = pt['high'] if pt['high'] is not None else pt['price']
        low = pt['low'] if pt['low'] is not None else pt['price']
        if high is None or low is None:
            continue
        if filled_at is None:
            if low <= entry_high and high >= entry_low:
                filled_at = pt['ts']
                touches = []
                if low <= stop:
                    touches.append('SL')
                if high >= t2:
                    touches.append('T2')
                elif high >= t1:
                    touches.append('T1')
                if len(touches) > 1:
                    return {
                        'outcome_status': OUTCOME_AMBIGUOUS,
                        'outcome_time': pt['ts'].isoformat(),
                        'outcome_price': stop,
                        'path_note': 'same candle ambiguity',
                        'conservative_result': OUTCOME_SL_HIT,
                        'filled_at': filled_at.isoformat(),
                    }
                if touches == ['SL']:
                    return _outcome(OUTCOME_SL_HIT, pt, stop, filled_at, 'stop touched on fill bar')
                if touches == ['T2']:
                    return _outcome(OUTCOME_T2_HIT, pt, t2, filled_at, 'T2 touched on fill bar')
                if touches == ['T1']:
                    return _outcome(OUTCOME_T1_HIT, pt, t1, filled_at, 'T1 touched on fill bar')
            continue

        if filled_at is not None:
            hit_sl = low is not None and low <= stop
            hit_t2 = high is not None and high >= t2
            hit_t1 = (not hit_t2) and high is not None and high >= t1
            if sum((hit_sl, hit_t2, hit_t1)) > 1:
                return {
                    'outcome_status': OUTCOME_AMBIGUOUS,
                    'outcome_time': pt['ts'].isoformat(),
                    'outcome_price': stop,
                    'path_note': 'same candle ambiguity',
                    'conservative_result': OUTCOME_SL_HIT,
                    'filled_at': filled_at.isoformat(),
                }
            if hit_sl:
                return _outcome(OUTCOME_SL_HIT, pt, stop, filled_at, 'stop touched after fill')
            if hit_t2:
                return _outcome(OUTCOME_T2_HIT, pt, t2, filled_at, 'T2 hit after signal')
            if hit_t1:
                return _outcome(OUTCOME_T1_HIT, pt, t1, filled_at, 'T1 hit after signal')

    if filled_at is None:
        return {
            'outcome_status': OUTCOME_NO_FILL if expire_at_close else OUTCOME_PENDING,
            'path_note': 'price never entered entry zone after signal',
            'conservative_result': '',
            'filled_at': '',
        }
    if expire_at_close:
        return {
            'outcome_status': OUTCOME_EXPIRED,
            'outcome_time': ordered[-1]['ts'].isoformat(),
            'outcome_price': ordered[-1]['price'],
            'path_note': 'expired at close without SL/T1/T2',
            'conservative_result': '',
            'filled_at': filled_at.isoformat(),
        }
    return {
        'outcome_status': OUTCOME_PENDING,
        'path_note': 'filled, awaiting SL/T1/T2',
        'conservative_result': '',
        'filled_at': filled_at.isoformat(),
    }


def _outcome(status: str, pt: dict[str, Any], price: float, filled_at: datetime, note: str) -> dict[str, Any]:
    return {
        'outcome_status': status,
        'outcome_time': pt['ts'].isoformat(),
        'outcome_price': price,
        'path_note': note,
        'conservative_result': '',
        'filled_at': filled_at.isoformat(),
    }


def _quote_path_point(market_data: dict[str, Any], ticker: str) -> dict[str, Any] | None:
    from backend.storage.market_memory_outcomes import lookup_latest_price

    price = lookup_latest_price(market_data, ticker)
    if price is None:
        return None
    entry = _price_entry_for_ticker(market_data, ticker) or {}
    high = _safe_float(entry.get('high')) or price
    low = _safe_float(entry.get('low')) or price
    return {
        'ts': _now_iso(),
        'price': price,
        'high': high,
        'low': low,
    }


def resolve_pending_tradecard_outcomes(
    *,
    session_date: str | None = None,
    expire_at_close: bool = False,
    refresh: bool = True,
) -> dict[str, Any]:
    """Apply accumulated path samples to pending VALID_ENTRY journal rows."""
    return sample_and_resolve_pending_tradecards(
        session_date=session_date,
        expire_at_close=expire_at_close,
        refresh=refresh,
    )


def apply_path_to_journal_record(record: dict[str, Any], path: list[dict[str, Any]], *, expire_at_close: bool = False) -> dict[str, Any]:
    entry_low = _safe_float(record.get('entry_low'))
    entry_high = _safe_float(record.get('entry_high'))
    stop = _safe_float(record.get('stop'))
    t1 = _safe_float(record.get('t1'))
    t2 = _safe_float(record.get('t2'))
    if None in (entry_low, entry_high, stop, t1, t2):
        return record
    resolved = resolve_outcome_sequence(
        entry_low=entry_low,
        entry_high=entry_high,
        stop=stop,
        t1=t1,
        t2=t2,
        path=path,
        signal_time=str(record.get('created_at') or ''),
        expire_at_close=expire_at_close,
    )
    patch = {**resolved}
    if path:
        latest = path[-1]
        patch['latest_sample_price'] = _safe_float(latest.get('price'))
        patch['latest_sample_at'] = str(latest.get('ts') or '')
        patch['path_sample_count'] = len(path)
    if resolved.get('outcome_status') == OUTCOME_AMBIGUOUS:
        patch['outcome_status'] = OUTCOME_AMBIGUOUS
    return update_journal_record(str(record.get('id')), patch) or {**record, **patch}


def persist_tradecard_generation(
    card: dict[str, Any],
    *,
    freshness_meta: dict[str, Any] | None = None,
    source_label: str = '',
) -> dict[str, Any] | None:
    """Store every generated tradecard; return journal row for VALID_ENTRY."""
    if not card or not card.get('ticker'):
        return None
    from backend.trading.trade_card_engine import resolve_tradecard_source_label

    label = source_label or resolve_tradecard_source_label(card, str(card.get('ticker') or ''))
    record = journal_record_from_card(card, freshness_meta=freshness_meta, source_label=label)
    status = str(card.get('status') or '').upper()
    if status != 'VALID_ENTRY':
        return None
    ok, _blocked = can_issue_new_valid_entry(str(card.get('ticker')), card=card)
    if not ok:
        return None
    append_journal_record(record)
    return record


def summarize_today_outcomes(*, session_date: str | None = None) -> dict[str, Any]:
    day = session_date or _today()
    rows = [r for r in _read_journal() if str(r.get('session_date') or '') == day]
    counts = {
        'generated': 0,
        'valid_entry': 0,
        'filled': 0,
        'T1': 0,
        'T2': 0,
        'SL': 0,
        'no_fill': 0,
        'pending': 0,
        'expired': 0,
        'ambiguous': 0,
    }
    best: list[dict[str, Any]] = []
    worst: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get('status') or '').upper() == 'VALID_ENTRY':
            counts['valid_entry'] += 1
            counts['generated'] += 1
        outcome = str(row.get('outcome_status') or '').upper()
        if row.get('filled_at'):
            counts['filled'] += 1
        if outcome == OUTCOME_T1_HIT:
            counts['T1'] += 1
        elif outcome == OUTCOME_T2_HIT:
            counts['T2'] += 1
        elif outcome == OUTCOME_SL_HIT:
            counts['SL'] += 1
        elif outcome == OUTCOME_NO_FILL:
            counts['no_fill'] += 1
        elif outcome == OUTCOME_PENDING:
            counts['pending'] += 1
        elif outcome == OUTCOME_EXPIRED:
            counts['expired'] += 1
        elif outcome == OUTCOME_AMBIGUOUS:
            counts['ambiguous'] += 1
        move = _move_pct(row)
        if outcome in (OUTCOME_T1_HIT, OUTCOME_T2_HIT) and move is not None:
            best.append({'ticker': row.get('ticker'), 'outcome': outcome, 'pct': move})
        if outcome in (OUTCOME_SL_HIT, OUTCOME_AMBIGUOUS) and move is not None:
            worst.append({'ticker': row.get('ticker'), 'outcome': outcome, 'pct': move})
    best.sort(key=lambda x: x.get('pct') or 0, reverse=True)
    worst.sort(key=lambda x: x.get('pct') or 0)
    return {'date': day, 'counts': counts, 'rows': rows, 'best': best[:3], 'worst': worst[:3]}


def _move_pct(row: dict[str, Any]) -> float | None:
    start = _safe_float(row.get('price_at_signal'))
    end = _safe_float(row.get('outcome_price'))
    if start and end:
        return round((end - start) / start * 100, 2)
    return None


def format_tradecard_review_section(
    *,
    session_date: str | None = None,
    provisional: bool = False,
) -> str:
    summary = summarize_today_outcomes(session_date=session_date)
    c = summary.get('counts') or {}
    if provisional:
        lines = [
            '<b>Tradecards: provisional intraday review</b>',
            'Final EOD resolution will run after market close.',
        ]
    else:
        lines = ['<b>Tradecards:</b>']
    lines.extend([
        f"Generated: {c.get('generated', 0)}",
        f"Filled: {c.get('filled', 0)}",
        f"T1: {c.get('T1', 0)} · T2: {c.get('T2', 0)} · SL: {c.get('SL', 0)}",
        f"No fill: {c.get('no_fill', 0)} · Pending: {c.get('pending', 0)} · Expired: {c.get('expired', 0)}",
    ])
    best = summary.get('best') or []
    worst = summary.get('worst') or []
    if best:
        b = best[0]
        lines.append(f"Best: {b.get('ticker')} — {b.get('outcome')} ({b.get('pct')}%)")
    if worst:
        w = worst[0]
        lines.append(f"Worst: {w.get('ticker')} — {w.get('outcome')} ({w.get('pct')}%)")
    return '\n'.join(lines)


def format_active_card_exists(active: dict[str, Any], *, current_price: float | None = None) -> str:
    ticker = str(active.get('ticker') or '—')
    entry_low = active.get('entry_low')
    entry_high = active.get('entry_high')
    entry = f'{entry_low}–{entry_high}' if entry_low and entry_high else '—'
    outcome = str(active.get('outcome_status') or OUTCOME_PENDING).lower().replace('_', ' ')
    price_txt = f'{current_price:.2f}' if current_price is not None else '—'
    return '\n'.join([
        '<b>📋 TRADE CARD — ACTIVE CARD EXISTS</b>',
        f'<b>{ticker}</b> · <code>TRACKING</code>',
        f'Original entry: {entry}',
        f"SL: {active.get('stop')} · T1: {active.get('t1')} · T2: {active.get('t2')}",
        f'Current: {price_txt}',
        f'Outcome: {outcome}',
        'Plan: wait for resolution, no duplicate card.',
        'Paper only.',
    ])


def format_tradecard_journal_telegram(*, session_date: str | None = None, limit: int = 8) -> str:
    summary = summarize_today_outcomes(session_date=session_date)
    day = summary.get('date') or _today()
    lines = ['<b>📘 Tradecard Journal</b>', f'Today ({day}):']
    valid_rows = [
        r for r in (summary.get('rows') or [])
        if str(r.get('status') or '').upper() == 'VALID_ENTRY'
    ]
    if not valid_rows:
        lines.append('No tradecards recorded today.')
        return '\n'.join(lines)
    for idx, row in enumerate(valid_rows[:limit], 1):
        ticker = row.get('ticker') or '—'
        outcome = str(row.get('outcome_status') or OUTCOME_PENDING).upper()
        if outcome == OUTCOME_AMBIGUOUS:
            label = f"{OUTCOME_AMBIGUOUS} / {row.get('conservative_result') or OUTCOME_SL_HIT}"
        else:
            label = outcome
        entry = f"{row.get('entry_low')}–{row.get('entry_high')}"
        lines.append(f'{idx}. <b>{ticker}</b> — {label}')
        lines.append(
            f"   Entry: {entry} · SL: {row.get('stop')} · "
            f"T1: {row.get('t1')} · T2: {row.get('t2')}"
        )
        lines.extend(_format_outcome_result_lines(row))
    return '\n'.join(lines)


def format_tradecard_outcome_telegram(*, session_date: str | None = None) -> str:
    sample_and_resolve_pending_tradecards(session_date=session_date, refresh=True)
    return format_tradecard_journal_telegram(session_date=session_date)
