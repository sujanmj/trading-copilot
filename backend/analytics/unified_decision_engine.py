"""
Unified live decision snapshot — Stage 48Q.

Single guard for today/tomorrow/action plan/morning/close inside one /full run.
Rejects live avoid / strong bearish tickers from stale report picks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.utils.config import DATA_DIR

LIVE_REJECTION_MSG = 'Rejected by live scanner / bearish confirmation'
SNAPSHOT_CONFLICT_WARNING = (
    'Snapshot warning: stale report conflicts with live scanner. '
    'Trust live scanner for intraday.'
)
STALE_REPORT_CONTEXT = 'Stale previous report context — not intraday live pick'

INTEL_FILE = DATA_DIR / 'intelligence.json'
SCANNER_FILE = DATA_DIR / 'scanner_data.json'

_snapshot_active = False
_snapshot_cache: dict[str, dict[str, Any]] = {}
_snapshot_picks: dict[str, str | None] = {}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def begin_unified_snapshot() -> None:
    global _snapshot_active
    _snapshot_active = True
    _snapshot_cache.clear()
    _snapshot_picks.clear()


def end_unified_snapshot() -> None:
    global _snapshot_active
    _snapshot_active = False


def is_unified_snapshot_active() -> bool:
    return _snapshot_active


def get_snapshot_cached_decision(mode: str) -> dict[str, Any] | None:
    key = 'today' if mode == 'today' else 'tomorrow' if mode == 'tomorrow' else str(mode)
    return _snapshot_cache.get(key)


def load_live_avoid_registry() -> dict[str, str]:
    from backend.analytics.premarket_conviction import _build_avoid_list

    intel = _load_json(INTEL_FILE)
    scanner = _load_json(SCANNER_FILE)
    registry: dict[str, str] = {}
    for row in _build_avoid_list(intel, scanner):
        ticker = str(row.get('ticker') or '').strip().upper()
        if not ticker or ticker == '?':
            continue
        registry[ticker] = str(row.get('reason') or 'Risk flagged')[:120]
    return registry


def is_live_rejected(ticker: str, registry: dict[str, str] | None = None) -> tuple[bool, str]:
    sym = str(ticker or '').strip().upper()
    reg = registry if registry is not None else load_live_avoid_registry()
    if sym in reg:
        return True, reg[sym]
    return False, ''


def get_feed_freshness_meta() -> dict[str, Any]:
    from backend.storage.data_paths import get_data_path
    from backend.telegram.freshness_consistency import (
        classify_budget_cache_freshness,
        compute_feed_age_minutes,
        format_compact_freshness_line,
    )
    from backend.telegram.lazy_command_runner import DAILY_PACK_FILE

    report_age, _ = compute_feed_age_minutes(DAILY_PACK_FILE)
    scanner_age, _ = compute_feed_age_minutes(get_data_path('scanner_data.json'))
    news_age, _ = compute_feed_age_minutes(get_data_path('news_feed.json'))
    report_status = classify_budget_cache_freshness(report_age)
    scanner_status = classify_budget_cache_freshness(scanner_age)
    news_status = classify_budget_cache_freshness(news_age)
    return {
        'report_age_min': report_age,
        'scanner_age_min': scanner_age,
        'news_age_min': news_age,
        'report_status': report_status,
        'scanner_status': scanner_status,
        'news_status': news_status,
        'scanner_fresh': scanner_status == 'fresh',
        'report_stale': report_status == 'stale',
        'lines': {
            'report': format_compact_freshness_line('Report', report_age),
            'scanner': format_compact_freshness_line('Scanner', scanner_age),
            'news': format_compact_freshness_line('News', news_age),
        },
    }


def apply_live_guard_to_ranked(
    ranked: list[dict[str, Any]],
    *,
    mode: str,
    registry: dict[str, str] | None = None,
    freshness_meta: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[str], str]:
    reg = registry if registry is not None else load_live_avoid_registry()
    meta = freshness_meta if freshness_meta is not None else get_feed_freshness_meta()
    warnings: list[str] = []

    updated: list[dict[str, Any]] = []
    for row in ranked:
        item = dict(row)
        rejected, reason = is_live_rejected(str(item.get('ticker') or ''), reg)
        if rejected:
            item['action'] = 'AVOID'
            item['score'] = min(int(item.get('score') or 0), 25)
            risks = [str(r) for r in (item.get('risk') or [])]
            if LIVE_REJECTION_MSG not in risks:
                risks.insert(0, LIVE_REJECTION_MSG)
            item['risk'] = risks[:6]
            why = [str(w) for w in (item.get('why') or [])]
            why.append(f'Live avoid flagged: {reason[:80]}')
            item['why'] = why[:6]
        updated.append(item)

    buy_rows = [r for r in updated if r.get('action') == 'BUY_CANDIDATE']
    watch_rows = [r for r in updated if r.get('action') == 'WATCH_FOR_ENTRY']
    avoid_rows = [r for r in updated if r.get('action') == 'AVOID']

    top_pick: dict[str, Any] | None = None
    decision = 'NO_CLEAN_CANDIDATE'
    if buy_rows:
        top_pick = buy_rows[0]
        decision = 'BUY_CANDIDATE'
    elif watch_rows:
        top_pick = watch_rows[0]
        decision = 'WATCH_FOR_ENTRY'
    elif updated and int(updated[0].get('score') or 0) >= 40 and updated[0].get('action') != 'AVOID':
        top_pick = updated[0]
        decision = str(top_pick.get('action') or 'WATCH_FOR_ENTRY')

    stale_report_top = next(
        (r for r in ranked if r.get('ticker') and not (r.get('supports') or [])),
        None,
    )
    if meta.get('report_stale') and meta.get('scanner_fresh'):
        if top_pick and stale_report_top and top_pick.get('ticker') == stale_report_top.get('ticker'):
            if not top_pick.get('supports'):
                warnings.append(SNAPSHOT_CONFLICT_WARNING)
        if mode == 'tomorrow' and top_pick:
            rejected, _ = is_live_rejected(str(top_pick.get('ticker') or ''), reg)
            if rejected:
                warnings.append(
                    f'Tomorrow research note: {top_pick.get("ticker")} conflicts with live rejection.'
                )

    if is_unified_snapshot_active() and top_pick:
        _snapshot_picks[mode] = str(top_pick.get('ticker') or '').upper() or None

    return updated, top_pick, warnings, decision


def apply_live_guard_to_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get('ok') is not True:
        return payload
    mode = str(payload.get('mode') or 'today')
    ranked = list(payload.get('ranked_candidates') or [])
    if not ranked:
        return payload

    meta = get_feed_freshness_meta()
    updated, top_pick, warnings, decision = apply_live_guard_to_ranked(
        ranked,
        mode=mode,
        freshness_meta=meta,
    )

    from backend.analytics.stock_decision_engine import _build_telegram_message

    out = dict(payload)
    out['ranked_candidates'] = updated
    out['top_pick'] = top_pick
    out['decision'] = decision
    out['avoid'] = [r for r in updated if r.get('action') == 'AVOID'][:10]
    out['watch_for_entry'] = [r for r in updated if r.get('action') == 'WATCH_FOR_ENTRY'][:10]
    out['snapshot_warnings'] = list(warnings)
    out['freshness_meta'] = meta

    msg_parts: list[str] = []
    if warnings:
        msg_parts.extend(warnings)
        msg_parts.append('')
    msg_parts.append(
        _build_telegram_message(
            mode=mode,
            decision=decision,
            top_pick=top_pick,
            avoid=out['avoid'],
        )
    )
    out['telegram_message'] = '\n'.join(msg_parts)

    if is_unified_snapshot_active():
        key = 'today' if mode == 'today' else 'tomorrow' if mode == 'tomorrow' else mode
        _snapshot_cache[key] = out
    return out


def note_snapshot_pick(source: str, ticker: str | None) -> None:
    _snapshot_picks[str(source)] = str(ticker or '').upper() or None


def snapshot_consistency_warnings() -> list[str]:
    if not _snapshot_picks:
        return []
    warnings: list[str] = []
    today = _snapshot_picks.get('today')
    action = _snapshot_picks.get('action_plan')
    morning = _snapshot_picks.get('morning')
    picks = {p for p in (today, action, morning) if p}
    if len(picks) > 1:
        warnings.append(SNAPSHOT_CONFLICT_WARNING)
    tomorrow = _snapshot_picks.get('tomorrow')
    close = _snapshot_picks.get('close')
    if tomorrow and close and tomorrow != close:
        warnings.append('Snapshot warning: tomorrow research candidate differs from close brief pick.')
    return warnings


def memory_outcome_warning(stats: dict[str, Any], overall: dict[str, Any]) -> str | None:
    predictions = int(stats.get('predictions') or overall.get('total_predictions') or 0)
    outcomes = int(stats.get('outcomes') or overall.get('resolved_outcomes') or 0)
    if predictions > 0 and outcomes == 0:
        return (
            'Outcome resolver not active yet or awaiting close data. '
            'Do not trust win-rate/calibration until outcomes resolve.'
        )
    return None


def calibration_unresolved_message(stats: dict[str, Any] | None = None, overall: dict[str, Any] | None = None) -> str | None:
    stats = stats or {}
    overall = overall or {}
    predictions = int(stats.get('predictions') or overall.get('total_predictions') or 0)
    outcomes = int(stats.get('outcomes') or overall.get('resolved_outcomes') or 0)
    if predictions > 0 and outcomes == 0:
        return 'Calibration unavailable — outcomes unresolved.'
    return None
