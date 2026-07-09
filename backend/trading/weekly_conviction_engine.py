"""
Weekly conviction engine — Phase 4B.18M / AstraEdge 52K.

Multi-source weekly signal ledger + conviction aggregation.
Research only. No LLM. No trade execution.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path

IST = ZoneInfo('Asia/Kolkata')
STAGE = '4B.18M-K'

MIN_CONVICTION_SCORE = 65
MAX_WEEKLY_PICKS = 5
MAX_MACRO_PENALTY = 15

W_FUNDAMENTALS = 25
W_NEWS_FEED_CATALYST = 20
W_TRADECARD = 15
W_PATTERN_CANDLE = 10
W_OUTCOME = 10
W_REPEATED = 10
W_SECTOR = 5
W_INVESTOR = 5

FUNDAMENTAL_SOURCES = frozenset({'SCREENER', 'LONGTERM'})
NEWS_SOURCES = frozenset({'NEWS', 'MY_FEED', 'CATALYST'})
TRADECARD_SOURCES = frozenset({'TRADECARD'})
PATTERN_SOURCES = frozenset({'PATTERN', 'CANDLE'})
OUTCOME_SOURCES = frozenset({'OUTCOME_LEARNING'})
SECTOR_SOURCES = frozenset({'SECTOR_THEME'})
INVESTOR_SOURCES = frozenset({'INVESTOR'})
WEEKLY_EVIDENCE_SOURCES = frozenset({
    'NEWS', 'MY_FEED', 'CATALYST', 'TRADECARD', 'PATTERN', 'CANDLE', 'OUTCOME_LEARNING',
})

DAY_NAMES = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')


def _now_ist(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(tz=IST)
    if now.tzinfo is None:
        return now.replace(tzinfo=IST)
    return now.astimezone(IST)


def current_week_id(now: datetime | None = None) -> str:
    dt = _now_ist(now)
    iso = dt.isocalendar()
    return f'{iso.year}-W{iso.week:02d}'


def week_start_date(now: datetime | None = None) -> str:
    dt = _now_ist(now).date()
    monday = dt - timedelta(days=dt.weekday())
    return monday.isoformat()


def week_end_date(now: datetime | None = None) -> str:
    dt = _now_ist(now).date()
    friday = dt - timedelta(days=dt.weekday()) + timedelta(days=4)
    end = min(dt, friday)
    return end.isoformat()


def _signal_events_path() -> Path:
    return get_data_path('weekly_signal_events.jsonl')


def _weekly_runs_path() -> Path:
    return get_data_path('weekly_pick_runs.jsonl')


def _weekly_records_path() -> Path:
    return get_data_path('weekly_pick_records.jsonl')


def _weekly_evaluations_path() -> Path:
    return get_data_path('weekly_candidate_evaluations.jsonl')


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + '\n')


def _load_jsonl(path: Path, *, limit: int = 50000) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    except OSError:
        return []
    return rows[-limit:]


def _normalize_symbol(value: object) -> str:
    return str(value or '').strip().upper()


def _confidence_band(score: int) -> str:
    if score >= 80:
        return 'HIGH'
    if score >= 70:
        return 'MEDIUM'
    return 'LOW'


def _session_in_week(session_date: str, *, week_id: str, now: datetime | None = None) -> bool:
    day = str(session_date or '')[:10]
    if not day:
        return False
    start = week_start_date(now)
    end = week_end_date(now)
    if current_week_id(now) != week_id:
        try:
            year_s, week_s = week_id.split('-W')
            year_i, week_i = int(year_s), int(week_s)
            from datetime import date as date_cls
            start_d = date_cls.fromisocalendar(year_i, week_i, 1)
            end_d = date_cls.fromisocalendar(year_i, week_i, 5)
            start, end = start_d.isoformat(), end_d.isoformat()
        except Exception:
            pass
    return start <= day <= end


def _coverage_label(now: datetime | None = None) -> str:
    ist = _now_ist(now)
    dt = ist.date()
    weekday = dt.weekday()  # 0=Mon … 4=Fri, 5=Sat, 6=Sun

    if weekday >= 5:
        return 'Mon–Fri / complete week'

    if weekday == 4:
        after_close_review = ist.hour > 15 or (ist.hour == 15 and ist.minute >= 45)
        if after_close_review:
            return 'Mon–Fri / complete week'
        return 'Mon–Fri / in progress — Friday session pending'

    today_name = DAY_NAMES[weekday]
    return f'Mon–{today_name} / partial week'


def capture_weekly_signal_event(
    *,
    symbol: str = '',
    company_name: str = '',
    source_type: str,
    source_command_or_module: str,
    signal_score: int,
    signal_direction: str,
    signal_strength: str,
    reason: str = '',
    reason_tags: list[str] | None = None,
    risk_tags: list[str] | None = None,
    data_quality: str = 'GOOD',
    raw_ref_id: str = '',
    session_date: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Append one weekly signal event to the ledger."""
    ist = _now_ist(now)
    week = current_week_id(ist)
    sym = _normalize_symbol(symbol)
    record = {
        'event_id': uuid.uuid4().hex[:16],
        'week_id': week,
        'session_date': session_date or ist.date().isoformat(),
        'captured_at_ist': ist.strftime('%Y-%m-%d %H:%M'),
        'symbol': sym,
        'company_name': str(company_name or sym or 'Market'),
        'source_type': str(source_type or '').upper(),
        'source_command_or_module': source_command_or_module,
        'signal_score': max(0, min(100, int(signal_score))),
        'signal_direction': str(signal_direction or 'neutral').lower(),
        'signal_strength': str(signal_strength or 'weak').lower(),
        'reason': str(reason or '')[:240],
        'reason_tags': list(reason_tags or [])[:8],
        'risk_tags': list(risk_tags or [])[:6],
        'data_quality': data_quality,
        'raw_ref_id': str(raw_ref_id or ''),
        'stage_version': STAGE,
    }
    _append_jsonl(_signal_events_path(), record)
    return record


def get_weekly_signal_events(week_id: str | None = None, *, now: datetime | None = None) -> list[dict[str, Any]]:
    week = week_id or current_week_id(now)
    rows = _load_jsonl(_signal_events_path())
    return [r for r in rows if str(r.get('week_id') or '') == week]


def backfill_partial_longterm_signals_for_week(*, week_id: str | None = None, now: datetime | None = None) -> int:
    """
    If current week has no LONGTERM events, backfill from longterm snapshots
    whose session_date falls in the same ISO week. Marked PARTIAL_BACKFILL.
    """
    week = week_id or current_week_id(now)
    existing = get_weekly_signal_events(week, now=now)
    if any(str(e.get('source_type') or '') == 'LONGTERM' for e in existing):
        return 0
    try:
        from backend.trading.longterm_snapshot_memory import _load_jsonl, _longterm_snapshots_path
    except Exception:
        return 0
    added = 0
    for row in _load_jsonl(_longterm_snapshots_path()):
        sym = _normalize_symbol(row.get('symbol'))
        if not sym or len(sym) < 2:
            continue
        if not _session_in_week(str(row.get('session_date') or ''), week_id=week, now=now):
            continue
        score = int(row.get('confidence_score') or row.get('screener_score') or 0)
        if score <= 0:
            continue
        capture_weekly_signal_event(
            symbol=sym,
            company_name=str(row.get('company_name') or sym),
            source_type='LONGTERM',
            source_command_or_module='longterm_snapshot_backfill',
            signal_score=score,
            signal_direction='positive',
            signal_strength='medium',
            reason='partial backfill from longterm snapshot in current week',
            reason_tags=['PARTIAL_BACKFILL'],
            data_quality='PARTIAL_BACKFILL',
            raw_ref_id=str(row.get('snapshot_id') or ''),
            session_date=str(row.get('session_date') or '')[:10],
            now=now,
        )
        added += 1
    return added


def _event_component_score(events: list[dict[str, Any]], source_types: frozenset[str]) -> tuple[int, bool]:
    relevant = [e for e in events if str(e.get('source_type') or '') in source_types]
    if not relevant:
        return 0, False
    scores: list[int] = []
    for e in relevant:
        base = int(e.get('signal_score') or 0)
        direction = str(e.get('signal_direction') or 'neutral').lower()
        if direction == 'negative':
            base = max(0, 100 - base)
        elif direction == 'neutral':
            base = min(base, 50)
        scores.append(base)
    return int(round(sum(scores) / len(scores))), True


def _repeated_source_score(events: list[dict[str, Any]]) -> tuple[int, int, list[str]]:
    positive_types = {
        str(e.get('source_type') or '')
        for e in events
        if str(e.get('signal_direction') or '') == 'positive' and _normalize_symbol(e.get('symbol'))
    }
    positive_types.discard('')
    positive_types.discard('MARKET')
    count = len(positive_types)
    score = min(100, count * 18)
    reasons = []
    if count >= 2:
        reasons.append(f'multi-source weekly evidence ({count} sources)')
    elif count == 1:
        reasons.append('single weekly evidence source only')
    return score, count, reasons


def _macro_penalty_from_events(events: list[dict[str, Any]]) -> tuple[int, list[str], bool]:
    macro_events = [e for e in events if str(e.get('source_type') or '') == 'MACRO']
    if not macro_events:
        try:
            from backend.trading.macro_shock_sentinel import get_active_macro_shock
            from backend.trading.weekly_signal_capture import capture_macro_market_signal

            active = get_active_macro_shock()
            if active:
                capture_macro_market_signal(active)
                week = str((events[0].get('week_id') if events else '') or current_week_id())
                macro_events = [
                    e for e in get_weekly_signal_events(week)
                    if str(e.get('source_type') or '') == 'MACRO'
                ]
        except Exception:
            pass
    if not macro_events:
        return 0, [], False
    latest = sorted(macro_events, key=lambda e: str(e.get('captured_at_ist') or ''))[-1]
    direction = str(latest.get('signal_direction') or 'neutral').lower()
    raw = int(latest.get('signal_score') or 0)
    if direction != 'negative':
        return 0, ['macro risk acceptable'], True
    if raw >= 75:
        return MAX_MACRO_PENALTY, ['macro sensitivity high'], True
    if raw >= 50:
        return 8, ['macro sensitivity medium'], True
    return 3, ['macro sensitivity low'], True


def _missing_evidence(source_types: set[str]) -> list[str]:
    missing: list[str] = []
    if not source_types & NEWS_SOURCES:
        missing.append('news/feed/catalyst')
    if not source_types & TRADECARD_SOURCES:
        missing.append('tradecard')
    if not source_types & PATTERN_SOURCES:
        missing.append('pattern/candle')
    if not source_types & OUTCOME_SOURCES:
        missing.append('outcome learning')
    if not source_types & INVESTOR_SOURCES:
        missing.append('investor')
    if not source_types & SECTOR_SOURCES:
        missing.append('sector/theme')
    if not source_types & FUNDAMENTAL_SOURCES:
        missing.append('screener/longterm')
    return missing


def _fundamentals_only_penalty(source_types: set[str]) -> int:
    weekly = source_types & WEEKLY_EVIDENCE_SOURCES
    if weekly:
        return 0
    if source_types & FUNDAMENTAL_SOURCES:
        return 12
    return 0


def _data_quality_from_events(events: list[dict[str, Any]], *, partial_backfill: bool) -> str:
    if partial_backfill:
        return 'PARTIAL_BACKFILL'
    types = {str(e.get('source_type') or '') for e in events}
    types.discard('MACRO')
    types.discard('')
    if len(types) >= 5:
        return 'GOOD'
    if len(types) >= 3:
        return 'PARTIAL'
    return 'LIMITED'


def aggregate_weekly_conviction(
    week_id: str | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate current week's signal events into per-symbol conviction scores."""
    week = week_id or current_week_id(now)
    events = get_weekly_signal_events(week, now=now)
    partial_backfill = any(str(e.get('data_quality') or '') == 'PARTIAL_BACKFILL' for e in events)

    by_sym: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        sym = _normalize_symbol(e.get('symbol'))
        if not sym or sym == 'MARKET':
            continue
        by_sym.setdefault(sym, []).append(e)

    try:
        from backend.trading.screener_memory import load_stock_memory, resolve_canonical_screener_symbol

        for row in load_stock_memory(limit=5000):
            sym, company = resolve_canonical_screener_symbol(row)
            if sym and len(sym) >= 2 and sym not in by_sym:
                by_sym.setdefault(sym, [])
    except Exception:
        pass

    macro_penalty, macro_risks, has_macro = _macro_penalty_from_events(events)
    candidates: list[dict[str, Any]] = []

    for sym, sym_events in by_sym.items():
        company = ''
        for e in sym_events:
            if e.get('company_name'):
                company = str(e.get('company_name'))
                break
        if not company:
            company = sym

        fund_s, has_fund = _event_component_score(sym_events, FUNDAMENTAL_SOURCES)
        news_s, has_news = _event_component_score(sym_events, NEWS_SOURCES)
        tc_s, has_tc = _event_component_score(sym_events, TRADECARD_SOURCES)
        pat_s, has_pat = _event_component_score(sym_events, PATTERN_SOURCES)
        out_s, has_out = _event_component_score(sym_events, OUTCOME_SOURCES)
        sec_s, has_sec = _event_component_score(sym_events, SECTOR_SOURCES)
        inv_s, has_inv = _event_component_score(sym_events, INVESTOR_SOURCES)
        rep_s, rep_count, rep_reasons = _repeated_source_score(sym_events)

        source_types = {str(e.get('source_type') or '') for e in sym_events}
        fund_only_penalty = _fundamentals_only_penalty(source_types)

        conviction = (
            fund_s * W_FUNDAMENTALS / 100
            + news_s * W_NEWS_FEED_CATALYST / 100
            + tc_s * W_TRADECARD / 100
            + pat_s * W_PATTERN_CANDLE / 100
            + out_s * W_OUTCOME / 100
            + rep_s * W_REPEATED / 100
            + sec_s * W_SECTOR / 100
            + inv_s * W_INVESTOR / 100
            - macro_penalty
            - fund_only_penalty
        )
        conviction = max(0, min(100, int(round(conviction))))

        reason_tags: list[str] = []
        risk_tags: list[str] = list(macro_risks)
        for e in sym_events:
            for tag in e.get('reason_tags') or []:
                t = str(tag).strip()
                if t and t not in reason_tags and t != 'PARTIAL_BACKFILL':
                    reason_tags.append(t)
            for tag in e.get('risk_tags') or []:
                t = str(tag).strip()
                if t and t not in risk_tags:
                    risk_tags.append(t)
        reason_tags.extend(rep_reasons)

        why_summary: list[str] = []
        if has_fund and fund_s >= 60:
            why_summary.append('strong Screener/longterm quality')
        if has_tc:
            why_summary.append('appeared in tradecards this week')
        if has_news:
            why_summary.append('verified news/feed/catalyst positive')
        if has_pat:
            why_summary.append('pattern/candle readiness supportive')
        if has_macro and macro_penalty <= 5:
            why_summary.append('macro risk acceptable')

        missing = _missing_evidence(source_types)
        dq = _data_quality_from_events(sym_events, partial_backfill=partial_backfill)

        candidates.append({
            'symbol': sym,
            'company_name': company,
            'conviction_score': conviction,
            'confidence_band': _confidence_band(conviction),
            'component_scores': {
                'fundamentals': fund_s,
                'news_feed_catalyst': news_s,
                'tradecard': tc_s,
                'pattern_candle': pat_s,
                'outcome_learning': out_s,
                'repeated_sources': rep_s,
                'sector_theme': sec_s,
                'investor': inv_s,
                'macro_penalty': macro_penalty,
                'fundamentals_only_penalty': fund_only_penalty,
            },
            'source_types': sorted(source_types - {'', 'MARKET'}),
            'reason_tags': reason_tags[:8],
            'risk_tags': risk_tags[:6],
            'why_summary': why_summary,
            'missing_evidence': missing,
            'data_quality': dq,
            'signal_count': len(sym_events),
            'source_type_count': rep_count,
        })

    candidates.sort(key=lambda c: int(c.get('conviction_score') or 0), reverse=True)
    qualified = [c for c in candidates if int(c.get('conviction_score') or 0) >= MIN_CONVICTION_SCORE]

    return {
        'week_id': week,
        'signals_scanned': len(events),
        'symbols_evaluated': len(candidates),
        'candidates': candidates,
        'qualified': qualified,
        'macro_penalty': macro_penalty,
        'partial_backfill': partial_backfill,
        'coverage': _coverage_label(now),
    }


def _persist_weekly_run(
    *,
    run_id: str,
    week_id: str,
    generated_at: str,
    generated_at_ist: str,
    aggregation: dict[str, Any],
    picks: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    best = (aggregation.get('candidates') or [{}])[0] if aggregation.get('candidates') else {}
    best_score = int(best.get('conviction_score') or 0)
    run = {
        'run_id': run_id,
        'week_id': week_id,
        'generated_at': generated_at,
        'generated_at_ist': generated_at_ist,
        'pick_count': len(records),
        'candidates_evaluated': int(aggregation.get('symbols_evaluated') or 0),
        'signals_scanned': int(aggregation.get('signals_scanned') or 0),
        'coverage': aggregation.get('coverage') or '',
        'no_pick_reason': (
            ''
            if records
            else 'no candidate had enough multi-source weekly confirmation'
        ),
        'best_candidate_symbol': str(best.get('symbol') or ''),
        'best_candidate_name': str(best.get('company_name') or ''),
        'best_score': best_score,
        'missing_evidence': list(best.get('missing_evidence') or [])[:6],
        'data_quality': str(best.get('data_quality') or 'LIMITED'),
        'partial_backfill': bool(aggregation.get('partial_backfill')),
        'stage_version': STAGE,
    }
    _append_jsonl(_weekly_runs_path(), run)
    return run


def _persist_candidate_evaluations(
    *,
    run_id: str,
    week_id: str,
    candidates: list[dict[str, Any]],
    selected_symbols: set[str],
) -> None:
    for cand in candidates:
        sym = _normalize_symbol(cand.get('symbol'))
        rec = {
            'eval_id': uuid.uuid4().hex[:16],
            'run_id': run_id,
            'week_id': week_id,
            'symbol': sym,
            'company_name': cand.get('company_name') or sym,
            'conviction_score': int(cand.get('conviction_score') or 0),
            'confidence_band': cand.get('confidence_band') or 'LOW',
            'data_quality': cand.get('data_quality') or 'LIMITED',
            'source_types_present': list(cand.get('source_types') or []),
            'missing_evidence': list(cand.get('missing_evidence') or []),
            'component_scores': dict(cand.get('component_scores') or {}),
            'selected': sym in selected_symbols,
            'stage_version': STAGE,
        }
        _append_jsonl(_weekly_evaluations_path(), rec)


def _build_pick_record(
    cand: dict[str, Any],
    *,
    rank: int,
    week_id: str,
    run_id: str,
    generated_at: str,
    generated_at_ist: str,
) -> dict[str, Any]:
    sym = _normalize_symbol(cand.get('symbol'))
    conviction = int(cand.get('conviction_score') or 0)
    comps = cand.get('component_scores') or {}
    return {
        'record_id': uuid.uuid4().hex[:16],
        'run_id': run_id,
        'week_id': week_id,
        'generated_at': generated_at,
        'generated_at_ist': generated_at_ist,
        'symbol': sym,
        'company_name': str(cand.get('company_name') or sym),
        'rank': rank,
        'conviction_score': conviction,
        'confidence_band': _confidence_band(conviction),
        'longterm_score': int(comps.get('fundamentals') or 0),
        'screener_quality_score': int(comps.get('fundamentals') or 0),
        'repeated_pick_score': int(comps.get('repeated_sources') or 0),
        'confidence_trend_score': 0,
        'news_strength_score': int(comps.get('news_feed_catalyst') or 0),
        'tradecard_memory_score': int(comps.get('tradecard') or 0),
        'outcome_learning_score': int(comps.get('outcome_learning') or 0),
        'macro_risk_penalty': int(comps.get('macro_penalty') or 0),
        'final_reason_summary': ' · '.join(cand.get('why_summary') or []) or 'weekly multi-source evidence',
        'reason_tags': list(cand.get('reason_tags') or []),
        'risk_tags': list(cand.get('risk_tags') or []),
        'data_quality': str(cand.get('data_quality') or 'LIMITED'),
        'source_types': list(cand.get('source_types') or []),
        'missing_evidence': list(cand.get('missing_evidence') or []),
        'stage_version': STAGE,
    }


def generate_weekly_conviction_picks(
    *,
    persist: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Scheduler-callable weekly conviction generator."""
    ist = _now_ist(now)
    week = current_week_id(ist)
    run_id = uuid.uuid4().hex[:16]
    generated_at = ist.replace(microsecond=0).isoformat()
    generated_at_ist = ist.strftime('%Y-%m-%d %H:%M')

    backfill_partial_longterm_signals_for_week(week_id=week, now=ist)
    aggregation = aggregate_weekly_conviction(week, now=ist)
    qualified = aggregation.get('qualified') or []
    picks_data = qualified[:MAX_WEEKLY_PICKS]

    records: list[dict[str, Any]] = []
    if persist:
        selected_syms = {_normalize_symbol(p.get('symbol')) for p in picks_data}
        for idx, cand in enumerate(picks_data, start=1):
            rec = _build_pick_record(
                cand,
                rank=idx,
                week_id=week,
                run_id=run_id,
                generated_at=generated_at,
                generated_at_ist=generated_at_ist,
            )
            _append_jsonl(_weekly_records_path(), rec)
            records.append(rec)
        _persist_candidate_evaluations(
            run_id=run_id,
            week_id=week,
            candidates=aggregation.get('candidates') or [],
            selected_symbols=selected_syms,
        )
        run_rec = _persist_weekly_run(
            run_id=run_id,
            week_id=week,
            generated_at=generated_at,
            generated_at_ist=generated_at_ist,
            aggregation=aggregation,
            picks=picks_data,
            records=records,
        )
        print(
            f'[WEEKLY_CONVICTION] week={week} run={run_id} picks={len(records)} '
            f'signals={aggregation.get("signals_scanned")} symbols={aggregation.get("symbols_evaluated")}',
            flush=True,
        )
    else:
        run_rec = {}

    best = (aggregation.get('candidates') or [{}])[0] if aggregation.get('candidates') else {}

    return {
        'week_id': week,
        'run_id': run_id,
        'generated_at': generated_at,
        'generated_at_ist': generated_at_ist,
        'picks': picks_data,
        'records': records,
        'run': run_rec,
        'aggregation': aggregation,
        'qualified_count': len(qualified),
        'signals_scanned': aggregation.get('signals_scanned') or 0,
        'symbols_evaluated': aggregation.get('symbols_evaluated') or 0,
        'coverage': aggregation.get('coverage') or '',
        'best_candidate': best,
        'partial_backfill': aggregation.get('partial_backfill'),
    }


def weekly_memory_stats() -> dict[str, int]:
    events = _load_jsonl(_signal_events_path())
    runs = _load_jsonl(_weekly_runs_path())
    picks = _load_jsonl(_weekly_records_path())
    evals = _load_jsonl(_weekly_evaluations_path())
    symbols = {_normalize_symbol(r.get('symbol')) for r in picks if _normalize_symbol(r.get('symbol'))}
    symbols |= {_normalize_symbol(r.get('symbol')) for r in evals if _normalize_symbol(r.get('symbol'))}
    return {
        'weekly_signal_events': len(events),
        'weekly_pick_runs': len(runs),
        'weekly_pick_records': len(picks),
        'weekly_candidate_evaluations': len(evals),
        'weekly_symbols_tracked': len(symbols),
    }


def recent_weekly_runs(*, limit: int = 5) -> list[dict[str, Any]]:
    runs = _load_jsonl(_weekly_runs_path())
    runs.sort(key=lambda r: str(r.get('generated_at') or ''), reverse=True)
    out: list[dict[str, Any]] = []
    for run in runs[:limit]:
        pick_count = int(run.get('pick_count') or 0)
        if pick_count > 0:
            rows = [
                r for r in _load_jsonl(_weekly_records_path())
                if str(r.get('run_id') or '') == str(run.get('run_id') or '')
            ]
            rows.sort(key=lambda r: int(r.get('rank') or 99))
            labels = [str(r.get('company_name') or r.get('symbol') or '') for r in rows[:5]]
        else:
            best_name = str(run.get('best_candidate_name') or run.get('best_candidate_symbol') or '')
            best_score = int(run.get('best_score') or 0)
            missing = ', '.join(run.get('missing_evidence') or [])[:80]
            labels = [f'best {best_name} {best_score}']
            if missing:
                labels.append(f'missing {missing}')
        out.append({
            **run,
            'count': pick_count,
            'top_labels': labels,
            'top_symbols': [
                str(run.get('best_candidate_symbol') or '')
            ] if pick_count <= 0 else [
                _normalize_symbol(r.get('symbol'))
                for r in _load_jsonl(_weekly_records_path())
                if str(r.get('run_id') or '') == str(run.get('run_id') or '')
            ][:5],
        })
    return out


def _lookup_symbol_evaluation(sym: str, *, week_id: str | None = None) -> dict[str, Any] | None:
    week = week_id or current_week_id()
    rows = [
        r for r in _load_jsonl(_weekly_evaluations_path())
        if _normalize_symbol(r.get('symbol')) == sym and str(r.get('week_id') or '') == week
    ]
    if not rows:
        return None
    rows.sort(key=lambda r: str(r.get('eval_id') or ''), reverse=True)
    return rows[0]


def _resolve_symbol_context(raw: str) -> tuple[str, str, dict[str, Any] | None]:
    from backend.trading.longterm_snapshot_memory import symbol_longterm_memory
    from backend.trading.screener_memory import resolve_screener_query, strip_screener_query

    query = strip_screener_query(raw)
    row = resolve_screener_query(query) if query else None
    sym = _normalize_symbol(
        (row or {}).get('symbol')
        or (row or {}).get('symbol_key')
        or query
    )
    mem = symbol_longterm_memory(sym) if sym else {'count': 0}
    if not sym and mem.get('count'):
        sym = _normalize_symbol(mem.get('symbol'))
    company = str(
        (row or {}).get('company_name')
        or (row or {}).get('display_name')
        or mem.get('company_name')
        or sym
    )
    return sym, company, row


def format_weekly_picks_telegram() -> str:
    result = generate_weekly_conviction_picks(persist=True)
    week = result.get('week_id') or current_week_id()
    generated = result.get('generated_at_ist') or _now_ist().strftime('%Y-%m-%d %H:%M')
    picks = result.get('records') or []
    agg = result.get('aggregation') or {}
    best = result.get('best_candidate') or {}

    lines = [
        '<b>WEEKLY CONVICTION PICKS</b>',
        '<i>Research only — not trade execution</i>',
        f'Week: {week}',
        f'Coverage: {result.get("coverage") or agg.get("coverage") or "—"}',
        f'Signals scanned: {result.get("signals_scanned") or 0}',
        f'Symbols evaluated: {result.get("symbols_evaluated") or 0}',
        f'Generated: {generated} IST',
        '',
    ]
    if agg.get('partial_backfill'):
        lines.append('<i>Note: partial longterm backfill only — not full weekly evidence</i>')
        lines.append('')

    if not picks:
        lines.extend([
            '<b>NO WEEKLY HIGH-CONVICTION PICK</b>',
            'Reason: no candidate had enough multi-source weekly confirmation.',
        ])
        if best:
            lines.append(
                f'Best candidate: {best.get("company_name") or best.get("symbol")} '
                f'score {best.get("conviction_score") or 0}'
            )
            missing = best.get('missing_evidence') or []
            if missing:
                lines.append(f'Missing evidence: {", ".join(missing)}')
        lines.append('/weekly history · /weekly explain SYMBOL')
        return '\n'.join(lines)

    for rec in picks:
        sym = _normalize_symbol(rec.get('symbol'))
        company = str(rec.get('company_name') or sym)
        score = int(rec.get('conviction_score') or 0)
        band = str(rec.get('confidence_band') or 'LOW')
        rank = int(rec.get('rank') or 0)
        lines.append(f'<b>{rank}. {sym} / {company} — Conviction {score} {band}</b>')
        lines.append('<b>Why:</b>')
        for item in (rec.get('reason_tags') or [])[:5]:
            lines.append(f'- {item}')
        for item in str(rec.get('final_reason_summary') or '').split(' · '):
            if item and item not in (rec.get('reason_tags') or []):
                lines.append(f'- {item}')
        lines.append('<b>Risk:</b>')
        risks = list(rec.get('risk_tags') or [])
        for item in (rec.get('missing_evidence') or [])[:3]:
            if 'investor' in item:
                risks.append('investor data missing')
        if risks:
            for tag in risks[:4]:
                lines.append(f'- {tag}')
        else:
            lines.append('- no major risk flags in memory')
        lines.append(f'Data quality: {rec.get("data_quality") or "LIMITED"}')
        sources = rec.get('source_types') or []
        if sources:
            lines.append(f'Sources: {", ".join(sources)}')
        lines.append('')

    lines.append('/weekly history · /weekly explain SYMBOL')
    return '\n'.join(lines).rstrip()


def format_weekly_history_telegram(*, limit: int = 5) -> str:
    runs = recent_weekly_runs(limit=limit)
    lines = [
        '<b>/weekly history</b>',
        '<i>Recent weekly conviction generations</i>',
        '',
    ]
    if not runs:
        lines.append('No weekly conviction runs yet. Try /weekly picks.')
        return '\n'.join(lines)
    for run in runs:
        pick_count = int(run.get('pick_count') or run.get('count') or 0)
        if pick_count > 0:
            labels = run.get('top_labels') or []
            label_txt = ', '.join(labels) or '—'
            lines.append(f'• {run.get("week_id")} — {pick_count} picks — {label_txt}')
        else:
            best = run.get('best_candidate_name') or run.get('best_candidate_symbol') or '—'
            score = int(run.get('best_score') or 0)
            missing = ', '.join(run.get('missing_evidence') or [])[:60]
            suffix = f' — missing {missing}' if missing else ''
            lines.append(f'• {run.get("week_id")} — 0 picks — best {best} {score}{suffix}')
    return '\n'.join(lines)


def format_weekly_explain_telegram(symbol: str) -> str:
    from backend.trading.longterm_snapshot_memory import symbol_longterm_memory
    from backend.trading.screener_memory import strip_screener_query, summarize_symbol_screener

    raw = strip_screener_query(symbol)
    if not raw:
        return 'Supply a symbol: /weekly explain SYMBOL'

    sym, company, screener_row = _resolve_symbol_context(raw)
    if not sym:
        return f'No weekly or memory context for {raw}.'

    week = current_week_id()
    events = [e for e in get_weekly_signal_events(week) if _normalize_symbol(e.get('symbol')) == sym]
    latest_pick = None
    for r in reversed(_load_jsonl(_weekly_records_path())):
        if _normalize_symbol(r.get('symbol')) == sym:
            latest_pick = r
            break
    evaluation = _lookup_symbol_evaluation(sym, week_id=week)
    mem = symbol_longterm_memory(sym)
    sc = summarize_symbol_screener(sym) if sym else {}

    if evaluation:
        score = int(evaluation.get('conviction_score') or 0)
        selected = bool(evaluation.get('selected'))
    elif events:
        agg = aggregate_weekly_conviction(week)
        cand = next((c for c in agg.get('candidates') or [] if c.get('symbol') == sym), None)
        score = int((cand or {}).get('conviction_score') or 0)
        selected = bool(latest_pick)
        evaluation = cand
    else:
        score = 0
        selected = bool(latest_pick)

    status = 'SELECTED' if selected else 'NOT_SELECTED'
    dq = str((evaluation or latest_pick or {}).get('data_quality') or 'LIMITED')

    lines = [
        f'<b>WEEKLY EXPLAIN — {sym}</b>',
        f'Company: {company}',
        f'Weekly status: {status}',
        f'Weekly score: {score}',
        f'Threshold: {MIN_CONVICTION_SCORE}',
        f'Data quality: {dq}',
        '',
        '<b>Signals this week:</b>',
    ]

    by_type: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        st = str(e.get('source_type') or '')
        by_type.setdefault(st, []).append(e)

    def _signal_line(source: str, detail: str) -> None:
        lines.append(f'- {source}: {detail}')

    lt_events = by_type.get('LONGTERM', [])
    if lt_events:
        e = lt_events[-1]
        _signal_line('LONGTERM', f"confidence {e.get('signal_score')}, {e.get('reason', '')[:80]}")
    elif int(mem.get('count') or 0) > 0:
        fund = mem.get('latest_fundamentals') or {}
        _signal_line(
            'LONGTERM',
            f"memory only (not this week) — ROCE {fund.get('roce', '—')}, "
            f"ROE {fund.get('roe', '—')}, debt {fund.get('debt_to_equity', '—')}",
        )
    else:
        _signal_line('LONGTERM', 'missing')

    for src, label in (
        ('NEWS', 'NEWS'),
        ('MY_FEED', 'MY_FEED'),
        ('CATALYST', 'CATALYST'),
        ('TRADECARD', 'TRADECARD'),
        ('PATTERN', 'PATTERN'),
        ('CANDLE', 'CANDLE'),
        ('OUTCOME_LEARNING', 'OUTCOME_LEARNING'),
        ('INVESTOR', 'INVESTOR'),
    ):
        if src == 'INVESTOR':
            try:
                from backend.trading.investor_intelligence import latest_investor_record

                inv = latest_investor_record(sym)
            except Exception:
                inv = None
            if src in by_type:
                e = by_type[src][-1]
                band = str((inv or {}).get('investor_band') or '')
                _signal_line(
                    label,
                    f"score {e.get('signal_score')} {band} — {str(e.get('reason') or '')[:50]}",
                )
            elif inv and str(inv.get('data_quality') or '') != 'MISSING':
                _signal_line(
                    label,
                    f"score {inv.get('investor_score')} {inv.get('investor_band')} — "
                    f"{str(inv.get('investor_summary') or '')[:50]}",
                )
                for tag in (inv.get('investor_reason_tags') or [])[:2]:
                    lines.append(f'  · {tag}')
                for tag in (inv.get('investor_risk_tags') or [])[:2]:
                    lines.append(f'  · risk: {tag}')
            else:
                _signal_line(label, 'missing')
            continue
        if src in by_type:
            e = by_type[src][-1]
            _signal_line(label, f"{e.get('signal_direction')} {e.get('signal_score')} — {str(e.get('reason') or '')[:60]}")
        else:
            _signal_line(label, 'missing')

    macro_events = by_type.get('MACRO', [])
    if macro_events:
        e = macro_events[-1]
        _signal_line('MACRO', f"{e.get('signal_direction')} — {str(e.get('reason') or '')[:60]}")
    else:
        _signal_line('MACRO', 'neutral/risk not captured this week')

    if sc.get('longterm_score'):
        lines.extend(['', '<b>Screener memory:</b>', f'longterm_score: {sc.get("longterm_score")}'])

    lines.extend(['', '<b>Reason:</b>'])
    missing = list((evaluation or {}).get('missing_evidence') or [])
    if score >= MIN_CONVICTION_SCORE:
        lines.append(f'{company} qualifies with multi-source weekly conviction score {score}.')
    elif int(mem.get('count') or 0) > 0 or sc.get('longterm_score'):
        lines.append(
            f'{company} has strong longterm/Screener fundamentals but did not qualify as weekly '
            f'high-conviction because it lacked fresh weekly news/tradecard/pattern confirmation.'
        )
        if missing:
            lines.append(f'Missing evidence: {", ".join(missing)}')
    else:
        lines.append(f'Limited weekly and memory evidence for {company}.')
        if missing:
            lines.append(f'Missing evidence: {", ".join(missing)}')

    return '\n'.join(lines)
