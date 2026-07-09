"""
Investor / shareholding intelligence — Phase 4B.18N / AstraEdge 52L.

Research-only shareholding memory from Screener imports.
No LLM. No external scraping.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path

IST = ZoneInfo('Asia/Kolkata')
STAGE = '4B.18N'

INVESTOR_CORE_FIELDS = (
    'promoter_holding',
    'promoter_pledge',
    'fii_holding',
    'dii_holding',
    'mutual_fund_holding',
    'public_holding',
    'retail_holding',
)

INVESTOR_ALL_FIELDS = INVESTOR_CORE_FIELDS + (
    'promoter_holding_change_qoq',
    'promoter_pledge_change_qoq',
    'fii_holding_change_qoq',
    'dii_holding_change_qoq',
    'govt_holding',
    'insurance_holding',
    'number_of_shareholders',
)


def _records_path() -> Path:
    return get_data_path('investor_shareholding_records.jsonl')


def _now_ist() -> datetime:
    return datetime.now(tz=IST)


def _normalize_symbol(value: object) -> str:
    return str(value or '').strip().upper()


def _safe_float(value: object) -> float | None:
    if value in (None, '', '—', '-', 'NA', 'N/A', 'unknown', 'nan'):
        return None
    try:
        return float(str(value).replace(',', '').replace('%', '').strip())
    except (TypeError, ValueError):
        return None


def _fmt_pct(value: object) -> str:
    val = _safe_float(value)
    if val is None:
        return '—'
    return f'{val:g}%'


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


def _assess_data_quality(present: int, total: int = len(INVESTOR_CORE_FIELDS)) -> str:
    if present <= 0:
        return 'MISSING'
    if present >= 4:
        return 'GOOD'
    return 'LIMITED'


def _investor_band(score: int) -> str:
    if score >= 80:
        return 'STRONG'
    if score >= 65:
        return 'GOOD'
    if score >= 45:
        return 'NEUTRAL'
    if score >= 30:
        return 'WEAK'
    return 'RISKY'


def score_investor_record(record: dict[str, Any]) -> dict[str, Any]:
    """Deterministic investor score out of 100."""
    missing_fields: list[str] = []
    reason_tags: list[str] = []
    risk_tags: list[str] = []

    def _field(name: str) -> float | None:
        val = _safe_float(record.get(name))
        if val is None:
            missing_fields.append(name)
        return val

    promoter = _field('promoter_holding')
    pledge = _safe_float(record.get('promoter_pledge'))
    if pledge is None:
        pledge = _safe_float(record.get('pledged_percent'))
    if pledge is None:
        missing_fields.append('promoter_pledge')
    fii = _field('fii_holding')
    dii = _field('dii_holding')
    mf = _safe_float(record.get('mutual_fund_holding'))
    if mf is None:
        missing_fields.append('mutual_fund_holding')
    public = _safe_float(record.get('public_holding'))
    retail = _safe_float(record.get('retail_holding'))

    present_core = sum(
        1 for name in INVESTOR_CORE_FIELDS
        if _safe_float(record.get(name)) is not None
        or (name == 'promoter_pledge' and pledge is not None)
    )
    data_quality = _assess_data_quality(present_core)

    if present_core <= 0:
        return {
            'investor_score': 50,
            'investor_band': 'NEUTRAL',
            'investor_reason_tags': [],
            'investor_risk_tags': [],
            'investor_summary': 'No shareholding data available',
            'data_quality': 'MISSING',
            'missing_fields': list(INVESTOR_CORE_FIELDS),
        }

    score = 50.0

    if promoter is not None:
        prom_chg = _safe_float(record.get('promoter_holding_change_qoq'))
        if promoter >= 50:
            score += 12
            reason_tags.append('promoter holding stable/high')
        elif promoter >= 35:
            score += 4
        else:
            score -= 4
        if prom_chg is not None:
            if prom_chg >= 1:
                score += 6
                reason_tags.append('promoter holding increasing')
            elif prom_chg <= -5:
                score -= 14
                risk_tags.append('promoter holding falling sharply')

    if pledge is not None:
        if pledge <= 0.5:
            score += 12
            reason_tags.append('pledge low')
        elif pledge <= 10:
            score += 4
        elif pledge >= 25:
            score -= 22
            risk_tags.append('high promoter pledge')
        elif pledge >= 15:
            score -= 10
            risk_tags.append('elevated promoter pledge')

    inst = dii
    if mf is not None:
        inst = (inst or 0) + mf if inst is not None else mf
    if inst is not None and inst >= 8:
        score += 10
        reason_tags.append('DII/MF holding supportive')
    elif inst is not None and inst >= 3:
        score += 4

    dii_chg = _safe_float(record.get('dii_holding_change_qoq'))
    fii_chg = _safe_float(record.get('fii_holding_change_qoq'))
    if dii_chg is not None and fii_chg is not None and dii_chg < 0 and fii_chg < 0:
        score -= 12
        risk_tags.append('DII/FII both falling')

    macro_risk_off = False
    try:
        from backend.trading.macro_shock_sentinel import get_active_macro_shock

        active = get_active_macro_shock()
        if active:
            regime = str(active.get('regime') or '').upper()
            severity = str(active.get('severity') or '').upper()
            macro_risk_off = regime in ('RED', 'RISK_OFF') or severity == 'HIGH'
    except Exception:
        pass

    if fii is not None:
        if fii_chg is not None and fii_chg < -3:
            score -= 10
            if macro_risk_off:
                score -= 6
                risk_tags.append('FII selling during global risk-off')
            else:
                risk_tags.append('FII holding falling')
        elif fii_chg is not None and fii_chg >= 1:
            score += 5
            reason_tags.append('FII holding increasing')

    pub = public if public is not None else retail
    if pub is not None and pub >= 50 and (inst or 0) < 5:
        score -= 6
        risk_tags.append('high public holding with weak institutions')

    score_int = max(0, min(100, int(round(score))))
    band = _investor_band(score_int)

    summary_parts = reason_tags[:2] or (risk_tags[:1] if risk_tags else ['shareholding data limited'])
    return {
        'investor_score': score_int,
        'investor_band': band,
        'investor_reason_tags': reason_tags,
        'investor_risk_tags': risk_tags,
        'investor_summary': ' · '.join(summary_parts),
        'data_quality': data_quality,
        'missing_fields': sorted(set(missing_fields)),
    }


def build_investor_record(
    *,
    symbol: str,
    company_name: str = '',
    source_type: str = 'UNKNOWN',
    source_import_id: str = '',
    session_date: str | None = None,
    fields: dict[str, Any] | None = None,
    notes: str = '',
) -> dict[str, Any]:
    ist = _now_ist()
    base = {
        'record_id': uuid.uuid4().hex[:16],
        'symbol': _normalize_symbol(symbol),
        'company_name': str(company_name or symbol).strip(),
        'session_date': session_date or ist.date().isoformat(),
        'captured_at_ist': ist.strftime('%Y-%m-%d %H:%M'),
        'source_type': source_type,
        'source_import_id': source_import_id,
        'notes': notes,
        'stage_version': STAGE,
    }
    for key in INVESTOR_ALL_FIELDS:
        val = (fields or {}).get(key)
        if val not in (None, ''):
            base[key] = val
    if (fields or {}).get('pledged_percent') is not None and base.get('promoter_pledge') is None:
        base['promoter_pledge'] = fields.get('pledged_percent')
    scored = score_investor_record(base)
    base.update(scored)
    return base


def append_investor_record(record: dict[str, Any]) -> dict[str, Any]:
    _append_jsonl(_records_path(), record)
    return record


def load_investor_records(symbol: str | None = None, *, limit: int = 200) -> list[dict[str, Any]]:
    sym = _normalize_symbol(symbol) if symbol else ''
    rows = _load_jsonl(_records_path())
    rows.sort(key=lambda r: str(r.get('captured_at_ist') or r.get('session_date') or ''), reverse=True)
    if sym:
        rows = [r for r in rows if _normalize_symbol(r.get('symbol')) == sym]
    return rows[:limit]


def latest_investor_record(symbol: str) -> dict[str, Any] | None:
    rows = load_investor_records(symbol, limit=1)
    return rows[0] if rows else None


def extract_investor_fields_from_stock_row(stock_row: dict[str, Any]) -> dict[str, Any]:
    """Map screener stock row fields to investor record fields."""
    fields: dict[str, Any] = {}
    mapping = {
        'promoter_holding': 'promoter_holding',
        'promoter_pledge': 'pledged_percent',
        'fii_holding': 'fii_holding',
        'dii_holding': 'dii_holding',
        'mutual_fund_holding': 'mutual_fund_holding',
        'public_holding': 'public_holding',
        'retail_holding': 'retail_holding',
        'govt_holding': 'govt_holding',
        'insurance_holding': 'insurance_holding',
        'number_of_shareholders': 'number_of_shareholders',
        'promoter_holding_change_qoq': 'promoter_holding_change_qoq',
        'promoter_pledge_change_qoq': 'promoter_pledge_change_qoq',
        'fii_holding_change_qoq': 'fii_holding_change_qoq',
        'dii_holding_change_qoq': 'dii_holding_change_qoq',
    }
    for inv_key, stock_key in mapping.items():
        val = stock_row.get(stock_key)
        if val not in (None, '', '—'):
            fields[inv_key] = val
    return fields


def capture_investor_from_screener_stocks(
    stocks: list[dict[str, Any]],
    *,
    import_id: str = '',
    imported_at: str = '',
) -> list[dict[str, Any]]:
    """Part B — capture investor records from Screener import rows."""
    stored: list[dict[str, Any]] = []
    session = str(imported_at or '')[:10] or _now_ist().date().isoformat()
    for row in stocks:
        sym = _normalize_symbol(row.get('symbol') or row.get('symbol_key'))
        if not sym or len(sym) < 2:
            continue
        fields = extract_investor_fields_from_stock_row(row)
        rec = build_investor_record(
            symbol=sym,
            company_name=str(row.get('company_name') or row.get('display_name') or sym),
            source_type='SCREENER_IMPORT',
            source_import_id=import_id,
            session_date=session,
            fields=fields,
        )
        append_investor_record(rec)
        stored.append(rec)
        try:
            from backend.trading.weekly_signal_capture import capture_investor_weekly_signal

            capture_investor_weekly_signal(rec)
        except Exception:
            pass
    if stored:
        print(
            f'[INVESTOR_MEMORY] import_id={import_id} records={len(stored)}',
            flush=True,
        )
    return stored


def investor_memory_stats() -> dict[str, int]:
    rows = _load_jsonl(_records_path())
    symbols = {_normalize_symbol(r.get('symbol')) for r in rows if _normalize_symbol(r.get('symbol'))}
    good = sum(1 for r in rows if str(r.get('data_quality') or '') == 'GOOD')
    missing = sum(1 for r in rows if str(r.get('data_quality') or '') == 'MISSING')
    return {
        'investor_records': len(rows),
        'investor_symbols_tracked': len(symbols),
        'investor_good_quality_records': good,
        'investor_missing_records': missing,
    }


def format_investor_summary_lines(record: dict[str, Any] | None) -> list[str]:
    if not record:
        return []
    lines = [
        '',
        '<b>Investor:</b>',
        f'Promoter: {_fmt_pct(record.get("promoter_holding"))}',
        f'Pledge: {_fmt_pct(record.get("promoter_pledge") or record.get("pledged_percent"))}',
        f'FII: {_fmt_pct(record.get("fii_holding"))}',
        f'DII/MF: {_fmt_pct(_safe_float(record.get("dii_holding")) or _safe_float(record.get("mutual_fund_holding")))}',
    ]
    pub = record.get('public_holding') or record.get('retail_holding')
    if pub not in (None, ''):
        lines.append(f'Public/Retail: {_fmt_pct(pub)}')
    score = int(record.get('investor_score') or 0)
    band = str(record.get('investor_band') or 'NEUTRAL')
    lines.append(f'Investor score: {score} {band}')
    for tag in (record.get('investor_risk_tags') or [])[:2]:
        lines.append(f'Risk: {tag}')
    lines.append(f'Data quality: {record.get("data_quality") or "MISSING"}')
    return lines


def format_investor_symbol_telegram(symbol: str) -> str:
    from backend.trading.screener_memory import resolve_screener_query, strip_screener_query

    raw = strip_screener_query(symbol)
    if not raw:
        return 'Supply a symbol: /investor SYMBOL'
    match = resolve_screener_query(raw)
    sym = _normalize_symbol((match or {}).get('symbol') or (match or {}).get('symbol_key') or raw)
    rec = latest_investor_record(sym)
    if not rec:
        return f'<b>INVESTOR INTELLIGENCE — {sym}</b>\n\nNo investor/shareholding record for {sym} yet.\nImport Screener CSV with shareholding columns.'

    company = str(rec.get('company_name') or sym)
    lines = [
        f'<b>INVESTOR INTELLIGENCE — {sym}</b>',
        f'{company}',
        '<i>Research only — not trade execution</i>',
        '',
        '<b>Shareholding:</b>',
        f'Promoter: {_fmt_pct(rec.get("promoter_holding"))}',
        f'Pledge: {_fmt_pct(rec.get("promoter_pledge"))}',
        f'FII: {_fmt_pct(rec.get("fii_holding"))}',
        f'DII/MF: {_fmt_pct(_safe_float(rec.get("dii_holding")) or _safe_float(rec.get("mutual_fund_holding")))}',
    ]
    pub = rec.get('public_holding') or rec.get('retail_holding')
    if pub not in (None, ''):
        lines.append(f'Public/Retail: {_fmt_pct(pub)}')
    lines.extend([
        '',
        f'Investor score: {rec.get("investor_score") or 0} {rec.get("investor_band") or "NEUTRAL"}',
        '<b>Why:</b>',
    ])
    reasons = rec.get('investor_reason_tags') or []
    if reasons:
        for tag in reasons[:5]:
            lines.append(f'- {tag}')
    else:
        lines.append('- —')
    lines.append('<b>Risks:</b>')
    risks = rec.get('investor_risk_tags') or []
    if risks:
        for tag in risks[:5]:
            lines.append(f'- {tag}')
    else:
        missing = rec.get('missing_fields') or []
        if missing:
            lines.append(f'- {missing[0].replace("_", " ")} trend missing')
        else:
            lines.append('- —')
    src = rec.get('source_type') or 'UNKNOWN'
    src_date = rec.get('session_date') or '—'
    lines.extend([
        '',
        f'Data quality: {rec.get("data_quality") or "MISSING"}',
        f'Source: {src.replace("_", " ").title()} {src_date}',
    ])
    return '\n'.join(lines)


def format_investor_weekly_telegram() -> str:
    from backend.trading.weekly_conviction_engine import aggregate_weekly_conviction, current_week_id

    agg = aggregate_weekly_conviction(current_week_id())
    candidates = (agg.get('qualified') or agg.get('candidates') or [])[:5]
    if not candidates:
        candidates = (agg.get('candidates') or [])[:5]
    lines = [
        '<b>/investor weekly</b>',
        '<i>Investor signals for current weekly candidates</i>',
        f'Week: {current_week_id()}',
        '',
    ]
    if not candidates:
        lines.append('No weekly candidates evaluated yet. Run /weekly picks.')
        return '\n'.join(lines)
    for cand in candidates:
        sym = _normalize_symbol(cand.get('symbol'))
        rec = latest_investor_record(sym)
        if rec and str(rec.get('data_quality') or '') != 'MISSING':
            lines.append(
                f'• <b>{sym}</b> — score {rec.get("investor_score")} {rec.get("investor_band")} '
                f'({rec.get("data_quality")})'
            )
        else:
            lines.append(f'• <b>{sym}</b> — investor data missing')
    return '\n'.join(lines)


def format_investor_memory_telegram(symbol: str) -> str:
    from backend.trading.screener_memory import strip_screener_query

    raw = strip_screener_query(symbol)
    if not raw:
        return 'Supply a symbol: /investor memory SYMBOL'
    sym = _normalize_symbol(raw)
    rows = load_investor_records(sym, limit=10)
    if not rows:
        return f'<b>/investor memory {sym}</b>\n\nNo investor history for {sym}.'
    lines = [f'<b>/investor memory {sym}</b>', '']
    for row in rows[:5]:
        lines.append(
            f'• {row.get("session_date") or "—"} — score {row.get("investor_score")} '
            f'{row.get("investor_band")} · promoter {_fmt_pct(row.get("promoter_holding"))} '
            f'· pledge {_fmt_pct(row.get("promoter_pledge"))} · {row.get("source_type")}'
        )
    return '\n'.join(lines)
