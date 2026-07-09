"""
Weekly conviction engine — Phase 4B.18M / AstraEdge 52K.

Research-only weekly stock conviction ranking from existing memory.
No LLM calls. No trade execution. No external APIs.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path

IST = ZoneInfo('Asia/Kolkata')
STAGE = '4B.18M'

MIN_CONVICTION_SCORE = 65
MAX_WEEKLY_PICKS = 5

WEIGHT_LONGTERM = 35
WEIGHT_REPEATED = 15
WEIGHT_TREND = 15
WEIGHT_NEWS = 15
WEIGHT_TRADECARD = 10
WEIGHT_OUTCOME = 10
MAX_MACRO_PENALTY = 15


def _now_ist(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(tz=IST)
    if now.tzinfo is None:
        return now.replace(tzinfo=IST)
    return now.astimezone(IST)


def _week_id(now: datetime | None = None) -> str:
    dt = _now_ist(now)
    iso = dt.isocalendar()
    return f'{iso.year}-W{iso.week:02d}'


def _weekly_records_path() -> Path:
    return get_data_path('weekly_pick_records.jsonl')


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


def _safe_float(value: object) -> float | None:
    if value in (None, '', '—', '-', 'NA', 'N/A', 'unknown'):
        return None
    try:
        return float(str(value).replace(',', '').replace('%', '').strip())
    except (TypeError, ValueError):
        return None


def _confidence_band(score: int) -> str:
    if score >= 80:
        return 'HIGH'
    if score >= 70:
        return 'MEDIUM'
    return 'LOW'


def _data_quality_label(available: int, total: int = 6) -> str:
    if available >= 5:
        return 'GOOD'
    if available >= 3:
        return 'PARTIAL'
    return 'LIMITED'


def _candidate_universe() -> dict[str, dict[str, Any]]:
    from backend.trading.longterm_snapshot_memory import _canonicalize_row
    from backend.trading.screener_memory import load_stock_memory, resolve_canonical_screener_symbol

    by_sym: dict[str, dict[str, Any]] = {}
    for row in load_stock_memory(limit=5000):
        sym, company = resolve_canonical_screener_symbol(row)
        if not sym or len(sym) < 2:
            continue
        canon = _canonicalize_row(row)
        canon['symbol'] = sym
        if company:
            canon['company_name'] = company
        score = int(canon.get('longterm_score') or 0)
        prev = by_sym.get(sym)
        if not prev or score > int(prev.get('longterm_score') or 0):
            by_sym[sym] = canon
    return by_sym


def _score_longterm_quality(row: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    score = int(row.get('longterm_score') or 0)
    reasons: list[str] = []
    risks: list[str] = []
    roce = _safe_float(row.get('roce'))
    roe = _safe_float(row.get('roe'))
    debt = _safe_float(row.get('debt_to_equity'))
    if roce is not None and roce >= 30:
        reasons.append(f'Screener quality strong: ROCE {roce:g}%+')
    elif roce is not None and roce >= 20:
        reasons.append(f'ROCE {roce:g}%')
    if roe is not None and roe >= 20:
        reasons.append(f'ROE {roe:g}%+')
    if debt is not None and debt <= 0.5:
        reasons.append('debt low')
    elif debt is not None and debt > 1.5:
        risks.append('elevated debt')
    pe = _safe_float(row.get('pe'))
    if pe is not None and pe >= 50:
        risks.append('valuation stretched')
    verdict = str(row.get('verdict') or '')
    if verdict == 'value_trap_risk':
        risks.append('value trap risk')
    return max(0, min(100, score)), reasons, risks


def _score_repeated_pick(sym: str) -> tuple[int, list[str], bool]:
    from backend.trading.longterm_snapshot_memory import symbol_longterm_memory

    mem = symbol_longterm_memory(sym)
    count = int(mem.get('count') or 0)
    reasons: list[str] = []
    if count >= 3:
        reasons.append(f'appeared in long-term list {count} times')
        return 100, reasons, True
    if count == 2:
        reasons.append(f'appeared in long-term list {count} times')
        return 70, reasons, True
    if count == 1:
        return 40, [], True
    return 0, [], False


def _score_confidence_trend(sym: str) -> tuple[int, list[str], list[str], bool]:
    from backend.trading.longterm_snapshot_memory import symbol_longterm_memory

    mem = symbol_longterm_memory(sym)
    trend = [int(v) for v in (mem.get('confidence_trend') or []) if v is not None]
    reasons: list[str] = []
    risks: list[str] = []
    if len(trend) < 2:
        return 40, reasons, risks, len(trend) >= 1
    newest = trend[0]
    oldest = trend[-1]
    delta = newest - oldest
    if delta >= 5:
        reasons.append(f'confidence trend improving {oldest} → {newest}')
        return 90, reasons, risks, True
    if delta >= 0:
        reasons.append(f'confidence trend stable {oldest} → {newest}')
        return 60, reasons, risks, True
    risks.append('confidence trend declining')
    return 30, reasons, risks, True


def _score_news_catalyst(sym: str, row: dict[str, Any]) -> tuple[int, list[str], list[str], bool]:
    reasons: list[str] = []
    risks: list[str] = []
    score = 0
    has_data = False
    try:
        from backend.intelligence.stock_catalyst_radar import explain_catalyst

        cat = explain_catalyst(sym)
        if cat:
            raw = float(cat.get('score') or 0)
            score = max(0, min(100, int(round(raw / 25.0 * 100))))
            has_data = score > 0
            side = str(cat.get('side') or '').upper()
            if side in ('BEARISH', 'RISK'):
                risks.append('negative catalyst this week')
                score = max(0, score - 25)
            elif score >= 50:
                reasons.append('positive news/catalyst strength this week')
    except Exception:
        pass
    if not has_data:
        ns = str(row.get('news_strength') or '').strip().lower()
        if ns in ('strong', 'high', 'positive'):
            score = 75
            reasons.append('positive news strength in Screener memory')
            has_data = True
        elif ns in ('medium', 'moderate'):
            score = 50
            has_data = True
    return score, reasons, risks, has_data


def _score_tradecard_memory(sym: str) -> tuple[int, list[str], bool]:
    try:
        from backend.trading.tradecard_memory import summarize_symbol_memory

        mem = summarize_symbol_memory(sym)
    except Exception:
        return 0, [], False
    count = int(mem.get('count') or 0)
    if count <= 0:
        return 0, [], False
    best_rank = int(mem.get('best_rank') or 20)
    last_score = int(mem.get('last_score') or 0)
    score = max(0, min(100, 30 + count * 8 + max(0, 20 - best_rank) * 2 + last_score // 10))
    reasons = [f'tradecard memory: {count} sample(s), best rank {best_rank or "—"}']
    return score, reasons, True


def _score_outcome_learning(sym: str) -> tuple[int, list[str], list[str], bool]:
    try:
        from backend.trading.candidate_outcome_learning import (
            OUTCOME_LOSS,
            OUTCOME_NEUTRAL,
            OUTCOME_PENDING,
            OUTCOME_WIN,
        )

        path = get_data_path('candidate_learning_records.jsonl')
        rows = [r for r in _load_jsonl(path) if _normalize_symbol(r.get('symbol')) == sym]
    except Exception:
        return 0, [], [], False
    if not rows:
        return 0, [], [], False
    wins = sum(1 for r in rows if r.get('outcome') == OUTCOME_WIN)
    losses = sum(1 for r in rows if r.get('outcome') == OUTCOME_LOSS)
    neutrals = sum(1 for r in rows if r.get('outcome') == OUTCOME_NEUTRAL)
    pending = sum(1 for r in rows if r.get('outcome') == OUTCOME_PENDING)
    resolved = wins + losses + neutrals
    if resolved <= 0:
        return 45, [f'outcome learning: {len(rows)} sample(s), pending resolution'], [], True
    win_rate = wins / resolved
    score = max(0, min(100, int(round(50 + (win_rate - 0.5) * 80))))
    reasons = [f'outcome learning: W/L/N/P = {wins}/{losses}/{neutrals}/{pending}']
    risks: list[str] = []
    if losses > wins:
        risks.append('weak candidate outcome history')
    return score, reasons, risks, True


def _macro_risk_penalty() -> tuple[int, list[str], bool]:
    try:
        from backend.trading.macro_shock_sentinel import get_active_macro_shock

        active = get_active_macro_shock()
    except Exception:
        return 0, [], False
    if not active:
        return 0, [], False
    severity = str(active.get('severity') or '').upper()
    regime = str(active.get('regime') or '').upper()
    risks: list[str] = []
    if severity == 'HIGH' or regime in ('RED', 'RISK_OFF'):
        risks.append('macro sensitivity high')
        return MAX_MACRO_PENALTY, risks, True
    if severity == 'MEDIUM':
        risks.append('macro sensitivity medium')
        return 8, risks, True
    risks.append('macro sensitivity low')
    return 3, risks, True


def _source_snapshot_ids(sym: str) -> list[str]:
    from backend.trading.longterm_snapshot_memory import symbol_recommendation_history

    ids: list[str] = []
    for row in symbol_recommendation_history(sym, limit=10):
        sid = str(row.get('snapshot_id') or '')
        if sid and sid not in ids:
            ids.append(sid)
    return ids[:10]


def _build_pick_record(
    row: dict[str, Any],
    *,
    rank: int,
    week_id: str,
    run_id: str,
    generated_at: str,
    generated_at_ist: str,
    components: dict[str, Any],
) -> dict[str, Any]:
    sym = _normalize_symbol(row.get('symbol'))
    company = str(row.get('company_name') or row.get('display_name') or sym)
    conviction = int(components['conviction_score'])
    return {
        'record_id': uuid.uuid4().hex[:16],
        'run_id': run_id,
        'week_id': week_id,
        'generated_at': generated_at,
        'generated_at_ist': generated_at_ist,
        'symbol': sym,
        'company_name': company,
        'rank': rank,
        'conviction_score': conviction,
        'confidence_band': _confidence_band(conviction),
        'longterm_score': int(components.get('longterm_score') or 0),
        'screener_quality_score': int(components.get('screener_quality_score') or 0),
        'repeated_pick_score': int(components.get('repeated_pick_score') or 0),
        'confidence_trend_score': int(components.get('confidence_trend_score') or 0),
        'news_strength_score': int(components.get('news_strength_score') or 0),
        'tradecard_memory_score': int(components.get('tradecard_memory_score') or 0),
        'outcome_learning_score': int(components.get('outcome_learning_score') or 0),
        'macro_risk_penalty': int(components.get('macro_risk_penalty') or 0),
        'final_reason_summary': str(components.get('final_reason_summary') or ''),
        'reason_tags': list(components.get('reason_tags') or []),
        'risk_tags': list(components.get('risk_tags') or []),
        'data_quality': str(components.get('data_quality') or 'LIMITED'),
        'source_snapshot_ids': list(components.get('source_snapshot_ids') or []),
        'stage_version': STAGE,
    }


def _score_candidate(row: dict[str, Any], *, macro_penalty: int, macro_risks: list[str]) -> dict[str, Any]:
    sym = _normalize_symbol(row.get('symbol'))
    lt_score, lt_reasons, lt_risks = _score_longterm_quality(row)
    rep_score, rep_reasons, has_rep = _score_repeated_pick(sym)
    trend_score, trend_reasons, trend_risks, has_trend = _score_confidence_trend(sym)
    news_score, news_reasons, news_risks, has_news = _score_news_catalyst(sym, row)
    tc_score, tc_reasons, has_tc = _score_tradecard_memory(sym)
    out_score, out_reasons, out_risks, has_out = _score_outcome_learning(sym)

    conviction = (
        lt_score * WEIGHT_LONGTERM / 100
        + rep_score * WEIGHT_REPEATED / 100
        + trend_score * WEIGHT_TREND / 100
        + news_score * WEIGHT_NEWS / 100
        + tc_score * WEIGHT_TRADECARD / 100
        + out_score * WEIGHT_OUTCOME / 100
        - macro_penalty
    )
    conviction = max(0, min(100, int(round(conviction))))

    reason_tags: list[str] = []
    risk_tags: list[str] = []
    for bucket in (lt_reasons, rep_reasons, trend_reasons, news_reasons, tc_reasons, out_reasons):
        for item in bucket:
            token = str(item).strip()
            if token and token not in reason_tags:
                reason_tags.append(token)
    for bucket in (lt_risks, trend_risks, news_risks, out_risks, macro_risks):
        for item in bucket:
            token = str(item).strip()
            if token and token not in risk_tags:
                risk_tags.append(token)

    available = sum(1 for flag in (lt_score > 0, has_rep, has_trend, has_news, has_tc, has_out) if flag)
    summary_parts = reason_tags[:3]
    if not summary_parts:
        summary_parts = ['Screener fundamentals within weekly threshold']

    return {
        'symbol': sym,
        'row': row,
        'conviction_score': conviction,
        'longterm_score': lt_score,
        'screener_quality_score': lt_score,
        'repeated_pick_score': rep_score,
        'confidence_trend_score': trend_score,
        'news_strength_score': news_score,
        'tradecard_memory_score': tc_score,
        'outcome_learning_score': out_score,
        'macro_risk_penalty': macro_penalty,
        'final_reason_summary': ' · '.join(summary_parts),
        'reason_tags': reason_tags,
        'risk_tags': risk_tags,
        'data_quality': _data_quality_label(available),
        'source_snapshot_ids': _source_snapshot_ids(sym),
    }


def generate_weekly_conviction_picks(
    *,
    persist: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Part G — scheduler-callable weekly conviction generator.
    Scores candidates from existing memory; optionally persists records.
    """
    ist = _now_ist(now)
    week = _week_id(ist)
    run_id = uuid.uuid4().hex[:16]
    generated_at = ist.replace(microsecond=0).isoformat()
    generated_at_ist = ist.strftime('%Y-%m-%d %H:%M')

    universe = _candidate_universe()
    macro_penalty, macro_risks, _ = _macro_risk_penalty()

    scored: list[dict[str, Any]] = []
    for row in universe.values():
        scored.append(_score_candidate(row, macro_penalty=macro_penalty, macro_risks=macro_risks))

    qualified = [s for s in scored if int(s.get('conviction_score') or 0) >= MIN_CONVICTION_SCORE]
    qualified.sort(key=lambda s: int(s.get('conviction_score') or 0), reverse=True)
    picks = qualified[:MAX_WEEKLY_PICKS]

    records: list[dict[str, Any]] = []
    if persist:
        for idx, comp in enumerate(picks, start=1):
            rec = _build_pick_record(
                comp['row'],
                rank=idx,
                week_id=week,
                run_id=run_id,
                generated_at=generated_at,
                generated_at_ist=generated_at_ist,
                components=comp,
            )
            _append_jsonl(_weekly_records_path(), rec)
            records.append(rec)
        if records:
            print(
                f'[WEEKLY_CONVICTION] week={week} run={run_id} picks={len(records)}',
                flush=True,
            )

    return {
        'week_id': week,
        'run_id': run_id,
        'generated_at': generated_at,
        'generated_at_ist': generated_at_ist,
        'picks': picks,
        'records': records,
        'qualified_count': len(qualified),
        'candidates_scored': len(scored),
        'macro_risk_penalty': macro_penalty,
    }


def weekly_memory_stats() -> dict[str, int]:
    rows = _load_jsonl(_weekly_records_path())
    runs = {str(r.get('run_id') or '') for r in rows if r.get('run_id')}
    symbols = {_normalize_symbol(r.get('symbol')) for r in rows if _normalize_symbol(r.get('symbol'))}
    return {
        'weekly_pick_runs': len(runs),
        'weekly_pick_records': len(rows),
        'weekly_symbols_tracked': len(symbols),
    }


def recent_weekly_runs(*, limit: int = 5) -> list[dict[str, Any]]:
    rows = _load_jsonl(_weekly_records_path())
    by_run: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        rid = str(row.get('run_id') or '')
        if rid:
            by_run.setdefault(rid, []).append(row)
    runs = []
    for rid, items in by_run.items():
        items.sort(key=lambda r: int(r.get('rank') or 99))
        first = items[0]
        runs.append({
            'run_id': rid,
            'week_id': first.get('week_id'),
            'generated_at': first.get('generated_at'),
            'generated_at_ist': first.get('generated_at_ist'),
            'count': len(items),
            'top_symbols': [_normalize_symbol(r.get('symbol')) for r in items[:5]],
            'top_labels': [
                str(r.get('company_name') or r.get('symbol') or '')
                for r in items[:5]
            ],
        })
    runs.sort(key=lambda r: str(r.get('generated_at') or ''), reverse=True)
    return runs[:limit]


def latest_weekly_pick(symbol: str) -> dict[str, Any] | None:
    sym = _normalize_symbol(symbol)
    rows = [r for r in _load_jsonl(_weekly_records_path()) if _normalize_symbol(r.get('symbol')) == sym]
    if not rows:
        return None
    rows.sort(key=lambda r: str(r.get('generated_at') or ''), reverse=True)
    return rows[0]


def format_weekly_picks_telegram() -> str:
    result = generate_weekly_conviction_picks(persist=True)
    week = result.get('week_id') or _week_id()
    generated = result.get('generated_at_ist') or _now_ist().strftime('%Y-%m-%d %H:%M')
    picks = result.get('records') or []

    lines = [
        '<b>WEEKLY CONVICTION PICKS</b>',
        '<i>Research only — not trade execution</i>',
        f'Week: {week}',
        f'Generated: {generated} IST',
        '',
    ]
    if not picks:
        lines.extend([
            '<b>NO WEEKLY HIGH-CONVICTION PICK</b>',
            'Reason: no candidate met weekly conviction threshold.',
        ])
        return '\n'.join(lines)

    for rec in picks:
        sym = _normalize_symbol(rec.get('symbol'))
        company = str(rec.get('company_name') or sym)
        score = int(rec.get('conviction_score') or 0)
        band = str(rec.get('confidence_band') or 'LOW')
        rank = int(rec.get('rank') or 0)
        lines.append(f'<b>{rank}. {sym} / {company} — Conviction {score} {band}</b>')
        lines.append('<b>Why:</b>')
        for tag in rec.get('reason_tags') or []:
            lines.append(f'- {tag}')
        if not rec.get('reason_tags'):
            lines.append(f'- {rec.get("final_reason_summary") or "Screener fundamentals"}')
        risks = list(rec.get('risk_tags') or [])
        if int(rec.get('macro_risk_penalty') or 0) > 0 and not any('macro' in r.lower() for r in risks):
            risks.append('macro risk environment')
        lines.append('<b>Risk:</b>')
        if risks:
            for tag in risks[:4]:
                lines.append(f'- {tag}')
        else:
            lines.append('- no major risk flags in memory')
        lines.append(f'Data quality: {rec.get("data_quality") or "LIMITED"}')
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
        labels = run.get('top_labels') or run.get('top_symbols') or []
        label_txt = ', '.join(labels) or '—'
        gen = str(run.get('generated_at_ist') or '')[:16]
        lines.append(
            f'• {run.get("week_id")} — {run.get("count")} picks — {label_txt}'
            + (f' ({gen})' if gen else '')
        )
    return '\n'.join(lines)


def format_weekly_explain_telegram(symbol: str) -> str:
    from backend.trading.longterm_snapshot_memory import symbol_longterm_memory
    from backend.trading.screener_memory import resolve_screener_query, strip_screener_query

    raw = strip_screener_query(symbol)
    if not raw:
        return 'Supply a symbol: /weekly explain SYMBOL'

    row = resolve_screener_query(raw)
    sym = _normalize_symbol((row or {}).get('symbol') or (row or {}).get('symbol_key') or raw)
    latest = latest_weekly_pick(sym)

    if not row and not latest:
        return f'No weekly conviction or Screener memory for {raw}.'

    if not latest and row:
        macro_penalty, macro_risks, _ = _macro_risk_penalty()
        comp = _score_candidate(row, macro_penalty=macro_penalty, macro_risks=macro_risks)
        latest = _build_pick_record(
            row,
            rank=0,
            week_id=_week_id(),
            run_id='preview',
            generated_at=_now_ist().replace(microsecond=0).isoformat(),
            generated_at_ist=_now_ist().strftime('%Y-%m-%d %H:%M'),
            components=comp,
        )
        preview = True
    else:
        preview = False

    mem = symbol_longterm_memory(sym)
    lines = [
        f'<b>/weekly explain {sym}</b>',
        '',
        f'Latest rank: {latest.get("rank") or "—"}{" (preview)" if preview else ""}',
        f'Latest conviction: {latest.get("conviction_score") or 0} {latest.get("confidence_band") or ""}',
        f'Week: {latest.get("week_id") or "—"}',
        '',
        '<b>Score components:</b>',
        f'longterm/screener: {latest.get("screener_quality_score") or 0}',
        f'repeated pick: {latest.get("repeated_pick_score") or 0}',
        f'confidence trend: {latest.get("confidence_trend_score") or 0}',
        f'news/catalyst: {latest.get("news_strength_score") or 0}',
        f'tradecard memory: {latest.get("tradecard_memory_score") or 0}',
        f'outcome learning: {latest.get("outcome_learning_score") or 0}',
        f'macro penalty: -{latest.get("macro_risk_penalty") or 0}',
        '',
        '<b>Long-term appearances:</b>',
        f'count: {mem.get("count") or 0} · best rank: {mem.get("best_rank") or "—"}',
    ]
    trend = mem.get('confidence_trend') or []
    if trend:
        lines.append(f'confidence trend: {" → ".join(str(v) for v in trend[:5])}')
    fund = mem.get('latest_fundamentals') or {}
    if any(fund.values()):
        lines.append('')
        lines.append('<b>Screener fundamentals:</b>')
        for key in ('roe', 'roce', 'debt_to_equity', 'sales_growth', 'profit_growth'):
            val = fund.get(key)
            if val not in (None, '', '—'):
                lines.append(f'{key.replace("_", " ")}: {val}')
    lines.append('')
    lines.append('<b>Why tags:</b>')
    for tag in latest.get('reason_tags') or []:
        lines.append(f'- {tag}')
    if not latest.get('reason_tags'):
        lines.append('- —')
    lines.append('')
    lines.append('<b>Risks:</b>')
    for tag in latest.get('risk_tags') or []:
        lines.append(f'- {tag}')
    if not latest.get('risk_tags'):
        lines.append('- —')
    missing: list[str] = []
    if int(latest.get('repeated_pick_score') or 0) <= 0:
        missing.append('repeated /longterm appearances')
    if int(latest.get('news_strength_score') or 0) <= 0:
        missing.append('news/catalyst')
    if int(latest.get('tradecard_memory_score') or 0) <= 0:
        missing.append('tradecard memory')
    if int(latest.get('outcome_learning_score') or 0) <= 0:
        missing.append('outcome learning')
    if missing:
        lines.append('')
        lines.append('<b>Missing data:</b>')
        for item in missing:
            lines.append(f'- {item}')
    lines.append(f'\nData quality: {latest.get("data_quality") or "LIMITED"}')
    return '\n'.join(lines)
