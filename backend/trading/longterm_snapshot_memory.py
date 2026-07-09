"""
Long-term Screener + /longterm snapshot memory — Phase 4B.18L / AstraEdge 52J.

Dated import and recommendation snapshots for research memory only.
No LLM calls. No trade execution.
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
STAGE = '4B.18L'

FUNDAMENTAL_COMPARE_FIELDS = (
    'roe', 'roce', 'debt_to_equity', 'sales_growth', 'profit_growth',
    'market_cap', 'promoter_holding',
)


def _now_ist(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(tz=IST)
    if now.tzinfo is None:
        return now.replace(tzinfo=IST)
    return now.astimezone(IST)


def _session_date(now: datetime | None = None) -> str:
    return _now_ist(now).date().isoformat()


def _screener_snapshots_path() -> Path:
    return get_data_path('screener_import_snapshots.jsonl')


def _longterm_snapshots_path() -> Path:
    return get_data_path('longterm_recommendation_snapshots.jsonl')


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


def _tradecard_memory_signal(symbol: str) -> str | None:
    try:
        from backend.trading.tradecard_memory import summarize_symbol_memory

        mem = summarize_symbol_memory(symbol)
        if not int(mem.get('count') or 0):
            return None
        parts = [f"tradecard samples={mem.get('count')}"]
        if mem.get('best_rank'):
            parts.append(f"best_rank={mem.get('best_rank')}")
        if mem.get('last_score'):
            parts.append(f"last_score={mem.get('last_score')}")
        return ' · '.join(parts)
    except Exception:
        return None


def capture_screener_import_snapshot(
    import_result: dict[str, Any],
    *,
    source_file_name: str = '',
) -> dict[str, Any]:
    """Part A — dated Screener import snapshot."""
    imp = import_result.get('import') if isinstance(import_result.get('import'), dict) else {}
    ist = _now_ist()
    stored = import_result.get('stored_stocks') or []
    top_symbols = []
    for r in stored[:15]:
        try:
            from backend.trading.screener_memory import resolve_canonical_screener_symbol

            sym, _ = resolve_canonical_screener_symbol(r)
        except Exception:
            sym = _normalize_symbol(r.get('symbol'))
        if sym and len(sym) >= 2:
            top_symbols.append(sym)
    record = {
        'snapshot_id': uuid.uuid4().hex[:16],
        'import_id': str(imp.get('import_id') or ''),
        'session_date': _session_date(ist),
        'imported_at_ist': ist.strftime('%H:%M'),
        'imported_at': str(imp.get('imported_at') or ist.replace(microsecond=0).isoformat()),
        'source_file_name': str(source_file_name or imp.get('filename') or ''),
        'rows_imported': int(imp.get('row_count') or len(stored)),
        'columns_detected': list(imp.get('normalized_columns') or []),
        'top_symbols': top_symbols,
        'rejected_rows': int(import_result.get('skipped') or 0),
        'stored_count': int(import_result.get('stored_count') or len(stored)),
        'screen_name': str(imp.get('screen_name') or ''),
        'stage_version': STAGE,
    }
    _append_jsonl(_screener_snapshots_path(), record)
    print(
        f'[SCREENER_IMPORT_SNAPSHOT] import_id={record.get("import_id")} '
        f'rows={record.get("rows_imported")} stored={record.get("stored_count")}',
        flush=True,
    )
    return record


def _screener_snapshot_exists(import_id: str) -> bool:
    if not import_id:
        return False
    return any(
        str(r.get('import_id') or '') == import_id
        for r in _load_jsonl(_screener_snapshots_path())
    )


def ensure_screener_snapshot_for_import(import_id: str) -> dict[str, Any] | None:
    """Backfill lightweight screener snapshot when /longterm uses a pre-52J import."""
    if not import_id or _screener_snapshot_exists(import_id):
        return None
    try:
        from backend.trading.screener_memory import (
            load_screener_imports,
            load_stock_memory,
            resolve_canonical_screener_symbol,
        )
    except Exception:
        return None

    imp = next((r for r in load_screener_imports(limit=200) if str(r.get('import_id') or '') == import_id), None)
    if not imp:
        return None

    stocks = [
        r for r in load_stock_memory(limit=5000)
        if str(r.get('import_id') or '') == import_id
    ]
    top_symbols: list[str] = []
    for row in sorted(stocks, key=lambda r: int(r.get('longterm_score') or 0), reverse=True)[:15]:
        sym, _ = resolve_canonical_screener_symbol(row)
        if sym and len(sym) >= 2:
            top_symbols.append(sym)

    imported_at = str(imp.get('imported_at') or '')
    ist = _now_ist()
    imported_ist = ''
    try:
        if imported_at:
            imported_ist = _now_ist(datetime.fromisoformat(imported_at.replace('Z', '+00:00'))).strftime('%H:%M')
    except Exception:
        imported_ist = ist.strftime('%H:%M')

    record = {
        'snapshot_id': uuid.uuid4().hex[:16],
        'import_id': import_id,
        'session_date': str(imp.get('imported_at') or '')[:10] or _session_date(ist),
        'imported_at_ist': imported_ist or ist.strftime('%H:%M'),
        'imported_at': imported_at or ist.replace(microsecond=0).isoformat(),
        'source_file_name': str(imp.get('filename') or ''),
        'rows_imported': int(imp.get('row_count') or len(stocks)),
        'columns_detected': list(imp.get('normalized_columns') or []),
        'top_symbols': top_symbols,
        'rejected_rows': max(0, int(imp.get('row_count') or 0) - len(stocks)),
        'stored_count': len(stocks),
        'screen_name': str(imp.get('screen_name') or ''),
        'snapshot_origin': 'backfilled_from_existing_import',
        'stage_version': STAGE,
    }
    _append_jsonl(_screener_snapshots_path(), record)
    print(
        f'[SCREENER_IMPORT_SNAPSHOT] backfill import_id={import_id} stored={len(stocks)}',
        flush=True,
    )
    return record


def _canonicalize_row(row: dict[str, Any]) -> dict[str, Any]:
    from backend.trading.screener_memory import resolve_canonical_screener_symbol

    sym, company = resolve_canonical_screener_symbol(row)
    out = dict(row)
    if sym:
        out['symbol'] = sym
        out['symbol_key'] = sym
    if company:
        out['company_name'] = company
        out['display_name'] = company
    return out


def longterm_history_display_label(record: dict[str, Any]) -> str:
    """Human-readable label for /longterm history — never one-letter symbols."""
    from backend.trading.screener_memory import _collapse_spaced_acronym

    company = str(record.get('company_name') or '').strip()
    sym = _normalize_symbol(record.get('symbol'))
    if len(sym) <= 1 and company:
        collapsed = _collapse_spaced_acronym(company)
        return collapsed if collapsed and len(collapsed) >= 2 else company
    if company and _collapse_spaced_acronym(company) and sym and len(sym) >= 2:
        return sym
    if company and company.upper() != sym:
        return company
    if sym and len(sym) >= 2:
        return sym
    return company or sym or '—'


def _build_recommendation_record(
    row: dict[str, Any],
    *,
    rank: int,
    import_id: str,
    batch_id: str,
    generated_at: str,
    generated_at_ist: str,
    session_date: str,
    change_flags: list[str] | None = None,
    change_notes: list[str] | None = None,
) -> dict[str, Any]:
    canon = _canonicalize_row(row)
    sym = _normalize_symbol(canon.get('symbol') or canon.get('symbol_key'))
    company = str(canon.get('company_name') or canon.get('display_name') or sym)
    reasons = list(canon.get('reasons') or row.get('reasons') or [])
    risks = list(canon.get('risk_flags') or row.get('risk_flags') or [])
    return {
        'snapshot_id': uuid.uuid4().hex[:16],
        'batch_id': batch_id,
        'session_date': session_date,
        'generated_at_ist': generated_at_ist,
        'generated_at': generated_at,
        'symbol': sym,
        'company_name': company,
        'rank': rank,
        'confidence_score': int(canon.get('longterm_score') or row.get('longterm_score') or 0),
        'recommendation_reason': ' · '.join(reasons[:4]) or 'screener fundamentals',
        'screener_score': int(canon.get('longterm_score') or row.get('longterm_score') or 0),
        'valuation_score': canon.get('valuation_score') or row.get('valuation_score'),
        'quality_score': canon.get('quality_score') or row.get('quality_score'),
        'growth_score': canon.get('growth_score') or row.get('growth_score'),
        'debt_score': canon.get('debt_score') or row.get('debt_score'),
        'roe': canon.get('roe') or row.get('roe'),
        'roce': canon.get('roce') or row.get('roce'),
        'debt_to_equity': canon.get('debt_to_equity') or row.get('debt_to_equity'),
        'sales_growth': canon.get('sales_growth') or row.get('sales_growth'),
        'profit_growth': canon.get('profit_growth') or row.get('profit_growth'),
        'market_cap': canon.get('market_cap') or row.get('market_cap'),
        'promoter_holding': canon.get('promoter_holding') or row.get('promoter_holding'),
        'fii_holding': row.get('fii_holding'),
        'dii_holding': row.get('dii_holding'),
        'news_strength': row.get('news_strength'),
        'tradecard_memory_signal': _tradecard_memory_signal(sym),
        'risks': risks[:6],
        'source_import_id': import_id,
        'change_flags': list(change_flags or []),
        'change_notes': list(change_notes or []),
        'verdict': str(row.get('verdict') or 'unknown'),
        'stage_version': STAGE,
    }


def _previous_batch_records(batch_id: str) -> list[dict[str, Any]]:
    rows = _load_jsonl(_longterm_snapshots_path())
    batches = sorted({str(r.get('batch_id') or '') for r in rows if r.get('batch_id')}, reverse=True)
    prev_id = ''
    for bid in batches:
        if bid and bid != batch_id:
            prev_id = bid
            break
    if not prev_id:
        return []
    return [r for r in rows if str(r.get('batch_id') or '') == prev_id]


def detect_longterm_changes(
    current: list[dict[str, Any]],
    previous: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Part C — per-symbol change flags vs previous /longterm batch."""
    prev_by_sym = {_normalize_symbol(r.get('symbol')): r for r in previous}
    curr_syms = {_normalize_symbol(r.get('symbol')) for r in current}
    out: dict[str, dict[str, Any]] = {}

    for row in current:
        sym = _normalize_symbol(row.get('symbol'))
        if not sym:
            continue
        prev = prev_by_sym.get(sym)
        flags: list[str] = []
        notes: list[str] = []
        if not prev:
            flags.append('new_entry')
            notes.append('New long-term entry')
        else:
            old_rank = int(prev.get('rank') or 0)
            new_rank = int(row.get('rank') or 0)
            if old_rank and new_rank and new_rank < old_rank:
                flags.append('rank_up')
                notes.append(f'Rank change: {old_rank} → {new_rank}')
            elif old_rank and new_rank and new_rank > old_rank:
                flags.append('rank_down')
                notes.append(f'Rank change: {old_rank} → {new_rank}')
            old_conf = int(prev.get('confidence_score') or 0)
            new_conf = int(row.get('confidence_score') or 0)
            if new_conf > old_conf + 2:
                flags.append('confidence_up')
                notes.append(f'Confidence change: {old_conf} → {new_conf}')
            elif new_conf < old_conf - 2:
                flags.append('confidence_down')
                notes.append(f'Confidence change: {old_conf} → {new_conf}')
            for field in FUNDAMENTAL_COMPARE_FIELDS:
                old_v = _safe_float(prev.get(field))
                new_v = _safe_float(row.get(field))
                if old_v is not None and new_v is not None and abs(old_v - new_v) > 0.01:
                    flags.append('fundamentals_changed')
                    notes.append(f'{field.replace("_", " ")} changed')
                    break
            old_news = str(prev.get('news_strength') or '')
            new_news = str(row.get('news_strength') or '')
            if old_news and new_news and old_news != new_news:
                flags.append('news_strength_changed')
                notes.append('News strength changed')
        out[sym] = {'change_flags': flags, 'change_notes': notes}

    for sym, prev in prev_by_sym.items():
        if sym and sym not in curr_syms:
            out[sym] = {
                'change_flags': ['dropped_out'],
                'change_notes': [f'Dropped out (was rank {prev.get("rank")})'],
                'dropped': True,
            }
    return out


def capture_longterm_recommendation_snapshots(
    stocks: list[dict[str, Any]],
    *,
    import_id: str = '',
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Part B — store /longterm recommendation batch."""
    if import_id:
        ensure_screener_snapshot_for_import(import_id)
    ist = _now_ist()
    batch_id = uuid.uuid4().hex[:16]
    generated_at = ist.replace(microsecond=0).isoformat()
    session = _session_date(ist)
    ranked = sorted(stocks, key=lambda r: int(r.get('longterm_score') or 0), reverse=True)[:limit]

    draft: list[dict[str, Any]] = []
    for idx, row in enumerate(ranked, start=1):
        canon = _canonicalize_row(row)
        sym = _normalize_symbol(canon.get('symbol') or canon.get('symbol_key'))
        if not sym or len(sym) < 2:
            continue
        draft.append({
            **canon,
            'symbol': sym,
            'rank': idx,
            'confidence_score': int(canon.get('longterm_score') or 0),
        })

    previous = _previous_batch_records(batch_id)
    changes = detect_longterm_changes(draft, previous)
    stored: list[dict[str, Any]] = []
    for row in draft:
        sym = _normalize_symbol(row.get('symbol'))
        ch = changes.get(sym) or {}
        rec = _build_recommendation_record(
            row,
            rank=int(row.get('rank') or 0),
            import_id=import_id,
            batch_id=batch_id,
            generated_at=generated_at,
            generated_at_ist=ist.strftime('%H:%M'),
            session_date=session,
            change_flags=ch.get('change_flags'),
            change_notes=ch.get('change_notes'),
        )
        _append_jsonl(_longterm_snapshots_path(), rec)
        stored.append(rec)
    print(
        f'[LONGTERM_SNAPSHOT] batch={batch_id} count={len(stored)} session={session}',
        flush=True,
    )
    return stored


def symbol_recommendation_history(symbol: str, *, limit: int = 20) -> list[dict[str, Any]]:
    sym = _normalize_symbol(symbol)
    rows = [r for r in _load_jsonl(_longterm_snapshots_path()) if _normalize_symbol(r.get('symbol')) == sym]
    rows.sort(key=lambda r: str(r.get('generated_at') or ''), reverse=True)
    return rows[:limit]


def symbol_longterm_memory(symbol: str) -> dict[str, Any]:
    sym = _normalize_symbol(symbol)
    rows = symbol_recommendation_history(sym, limit=500)
    if not rows:
        return {'symbol': sym, 'count': 0}
    ranks = [int(r.get('rank') or 0) for r in rows if int(r.get('rank') or 0) > 0]
    confs = [int(r.get('confidence_score') or 0) for r in rows]
    return {
        'symbol': sym,
        'company_name': str(rows[0].get('company_name') or sym),
        'count': len(rows),
        'first_seen': str(rows[-1].get('session_date') or ''),
        'last_seen': str(rows[0].get('session_date') or ''),
        'best_rank': min(ranks) if ranks else 0,
        'latest_rank': int(rows[0].get('rank') or 0),
        'latest_confidence': int(rows[0].get('confidence_score') or 0),
        'confidence_trend': confs[:5],
        'reason_history': [str(r.get('recommendation_reason') or '') for r in rows[:5]],
        'risk_history': [list(r.get('risks') or []) for r in rows[:3]],
        'latest_fundamentals': {
            'roe': rows[0].get('roe'),
            'roce': rows[0].get('roce'),
            'debt_to_equity': rows[0].get('debt_to_equity'),
            'sales_growth': rows[0].get('sales_growth'),
            'profit_growth': rows[0].get('profit_growth'),
        },
    }


def recent_longterm_batches(*, limit: int = 5) -> list[dict[str, Any]]:
    rows = _load_jsonl(_longterm_snapshots_path())
    by_batch: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        bid = str(row.get('batch_id') or '')
        if bid:
            by_batch.setdefault(bid, []).append(row)
    batches = []
    for bid, items in by_batch.items():
        items.sort(key=lambda r: int(r.get('rank') or 99))
        first = items[0]
        batches.append({
            'batch_id': bid,
            'session_date': first.get('session_date'),
            'generated_at': first.get('generated_at'),
            'generated_at_ist': first.get('generated_at_ist'),
            'count': len(items),
            'top_symbols': [_normalize_symbol(r.get('symbol')) for r in items[:5] if len(_normalize_symbol(r.get('symbol'))) >= 2],
            'top_display_labels': [longterm_history_display_label(r) for r in items[:5]],
        })
    batches.sort(key=lambda b: str(b.get('generated_at') or ''), reverse=True)
    return batches[:limit]


def longterm_memory_stats() -> dict[str, int]:
    screener = _load_jsonl(_screener_snapshots_path())
    longterm = _load_jsonl(_longterm_snapshots_path())
    symbols = {_normalize_symbol(r.get('symbol')) for r in longterm if _normalize_symbol(r.get('symbol'))}
    return {
        'screener_snapshots': len(screener),
        'longterm_recommendation_snapshots': len(longterm),
        'longterm_symbols_tracked': len(symbols),
    }


def build_weekly_longterm_foundation(*, trading_days: int = 5) -> dict[str, Any]:
    """
    Part E — weekly foundation helper (no scheduled alert yet).
    Reads last N trading-day recommendation batches.
    """
    rows = _load_jsonl(_longterm_snapshots_path())
    if not rows:
        return {'batches': 0, 'repeated_symbols': [], 'confidence_trends': {}}
    cutoff = (_now_ist() - timedelta(days=max(7, trading_days * 2))).date().isoformat()
    recent = [r for r in rows if str(r.get('session_date') or '') >= cutoff]
    by_sym: dict[str, list[dict[str, Any]]] = {}
    for row in recent:
        sym = _normalize_symbol(row.get('symbol'))
        if sym:
            by_sym.setdefault(sym, []).append(row)
    repeated = []
    trends: dict[str, list[int]] = {}
    for sym, items in by_sym.items():
        items.sort(key=lambda r: str(r.get('generated_at') or ''))
        if len(items) >= 2:
            repeated.append({
                'symbol': sym,
                'appearances': len(items),
                'avg_confidence': round(sum(int(i.get('confidence_score') or 0) for i in items) / len(items), 1),
                'latest_rank': int(items[-1].get('rank') or 0),
            })
            trends[sym] = [int(i.get('confidence_score') or 0) for i in items[-5:]]
    repeated.sort(key=lambda r: (r['appearances'], r['avg_confidence']), reverse=True)
    batch_ids = sorted({str(r.get('batch_id') or '') for r in recent if r.get('batch_id')}, reverse=True)
    return {
        'batches': len(batch_ids[:trading_days]),
        'repeated_symbols': repeated[:10],
        'confidence_trends': trends,
        'trading_days_window': trading_days,
    }


def _fmt_pct(value: object) -> str:
    val = _safe_float(value)
    if val is None:
        return ''
    return f'{val:g}%'


def format_change_lines(change_notes: list[str], memory: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    count = int(memory.get('count') or 0)
    if count >= 2:
        lines.append(f'Repeated pick: seen {count} times')
    for note in change_notes or []:
        if note.startswith('Rank change'):
            lines.append(note.replace('Rank change:', 'Rank change:'))
        elif note.startswith('Confidence change'):
            lines.append(note.replace('Confidence change:', 'Confidence change:'))
        else:
            lines.append(note)
    return lines


def format_longterm_stock_block(
    row: dict[str, Any],
    *,
    snapshot: dict[str, Any] | None = None,
    memory: dict[str, Any] | None = None,
) -> list[str]:
    """Part F — rich /longterm stock block with why/risk/memory."""
    canon = _canonicalize_row(row)
    sym = _normalize_symbol(canon.get('symbol') or row.get('symbol') or row.get('symbol_key'))
    label = str(canon.get('display_name') or canon.get('company_name') or sym)
    conf = int(row.get('longterm_score') or row.get('confidence_score') or 0)
    rank = int((snapshot or {}).get('rank') or row.get('rank') or 0)
    lines = [f'{rank}. <b>{label}</b> — Confidence {conf}' if rank else f'<b>{label}</b> — Confidence {conf}']
    why: list[str] = []
    if row.get('roce') not in (None, ''):
        why.append(f"ROCE {_fmt_pct(row.get('roce'))}".strip())
    if row.get('roe') not in (None, ''):
        why.append(f"ROE {_fmt_pct(row.get('roe'))}".strip())
    debt = _safe_float(row.get('debt_to_equity'))
    if debt is not None and debt <= 0.25:
        why.append(f'low debt-to-equity {debt:g}')
    for reason in row.get('reasons') or []:
        token = str(reason).strip()
        if token and token not in why:
            why.append(token)
    mem = memory or symbol_longterm_memory(sym)
    if int(mem.get('count') or 0) >= 2:
        why.append(f'appeared in long-term list {mem.get("count")} times')
    if snapshot and snapshot.get('news_strength'):
        why.append(f'news strength: {snapshot.get("news_strength")}')
    if why:
        lines.append('Why:')
        for item in why[:6]:
            lines.append(f'- {item}')
    risks = list(row.get('risk_flags') or row.get('risks') or [])
    if risks:
        lines.append('Risk:')
        for risk in risks[:3]:
            lines.append(f'- {risk}')
    if int(mem.get('count') or 0):
        trend = mem.get('confidence_trend') or []
        trend_txt = ' → '.join(str(c) for c in reversed(trend[:3])) if trend else str(conf)
        lines.append(
            f'Memory: Seen {mem.get("count")} times · best rank {mem.get("best_rank") or "—"} · '
            f'confidence trend {trend_txt}'
        )
    change_notes = list((snapshot or {}).get('change_notes') or [])
    if change_notes:
        lines.append('Long-term memory:')
        for note in format_change_lines(change_notes, mem)[:4]:
            lines.append(f'- {note}')
    lines.append('')
    return lines


def format_longterm_history_telegram(symbol: str = '', *, limit: int = 5) -> str:
    from backend.trading.screener_memory import strip_screener_query

    sym = strip_screener_query(symbol)
    if sym:
        rows = symbol_recommendation_history(sym, limit=10)
        if not rows:
            return f'<b>/longterm history {sym}</b>\n\nNo long-term recommendation history for {sym}.'
        lines = [f'<b>/longterm history {sym}</b>', '']
        for row in rows:
            lines.append(
                f'• {row.get("session_date")} rank {row.get("rank")} · '
                f'conf {row.get("confidence_score")} — {row.get("recommendation_reason") or "—"}'
            )
        return '\n'.join(lines)

    batches = recent_longterm_batches(limit=limit)
    lines = ['<b>/longterm history</b>', '<i>Recent long-term recommendation snapshots</i>', '']
    if not batches:
        lines.append('No long-term recommendation snapshots yet. Run /longterm after a Screener import.')
        return '\n'.join(lines)
    for batch in batches:
        labels = batch.get('top_display_labels') or batch.get('top_symbols') or []
        label_txt = ', '.join(labels) or '—'
        lines.append(
            f'• {batch.get("session_date")} {batch.get("generated_at_ist")} — '
            f'{batch.get("count")} picks — {label_txt}'
        )
    return '\n'.join(lines)


def format_longterm_memory_symbol_telegram(symbol: str) -> str:
    from backend.trading.screener_memory import strip_screener_query

    sym = strip_screener_query(symbol)
    if not sym:
        return 'Supply a symbol: /longterm memory SYMBOL'
    mem = symbol_longterm_memory(sym)
    if not int(mem.get('count') or 0):
        return f'<b>/longterm memory {sym}</b>\n\nNo stored long-term thesis memory for {sym}.'
    fund = mem.get('latest_fundamentals') or {}
    lines = [
        f'<b>/longterm memory {mem.get("symbol") or sym}</b>',
        f'Company: {mem.get("company_name") or sym}',
        '',
        f'First seen: {mem.get("first_seen") or "—"}',
        f'Last seen: {mem.get("last_seen") or "—"}',
        f'Times recommended: {mem.get("count") or 0}',
        f'Best rank: {mem.get("best_rank") or "—"}',
        f'Latest rank: {mem.get("latest_rank") or "—"}',
        f'Latest confidence: {mem.get("latest_confidence") or 0}',
        '',
        '<b>Reason history:</b>',
    ]
    for reason in mem.get('reason_history') or []:
        lines.append(f'- {reason or "—"}')
    lines.extend([
        '',
        '<b>Key fundamentals (latest):</b>',
        f'ROCE: {fund.get("roce") if fund.get("roce") not in (None, "") else "Unknown"}',
        f'ROE: {fund.get("roe") if fund.get("roe") not in (None, "") else "Unknown"}',
        f'Debt/Equity: {fund.get("debt_to_equity") if fund.get("debt_to_equity") not in (None, "") else "Unknown"}',
        f'Sales growth: {fund.get("sales_growth") if fund.get("sales_growth") not in (None, "") else "Unknown"}',
        f'Profit growth: {fund.get("profit_growth") if fund.get("profit_growth") not in (None, "") else "Unknown"}',
    ])
    risks = mem.get('risk_history') or []
    if risks:
        lines.extend(['', '<b>Risk history:</b>'])
        for group in risks[:2]:
            lines.append(f'- {" · ".join(group) if group else "—"}')
    trend = mem.get('confidence_trend') or []
    if trend:
        lines.append('')
        lines.append(f'Confidence trend: {" → ".join(str(c) for c in reversed(trend[:5]))}')
    try:
        from backend.trading.investor_intelligence import format_investor_summary_lines, latest_investor_record

        lines.extend(format_investor_summary_lines(latest_investor_record(str(mem.get('symbol') or sym))))
    except Exception:
        pass
    lines.append('')
    lines.append('<i>Long-term research memory only — not intraday tradecard</i>')
    return '\n'.join(lines)
