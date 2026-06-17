"""
Unified live decision snapshot — Stage 48Q / 48R.

Hard live rejection override: tickers in live_rejection_set cannot be intraday top picks.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend.utils.config import DATA_DIR

HARD_REJECTION_MSG = 'Rejected by live scanner: strong bearish / breakdown'
LIVE_REJECTION_MSG = HARD_REJECTION_MSG
SNAPSHOT_CONFLICT_WARNING = (
    'Snapshot warning: stale report conflicts with live scanner. '
    'Trust live scanner for intraday.'
)
FULL_SNAPSHOT_CONSISTENCY_WARNING = (
    'Snapshot consistency warning: stale report conflicts with live scanner. '
    'Live scanner overrides stale candidates.'
)
TOMORROW_LIVE_REJECTION_WARNING = (
    'Live scanner rejected this ticker today; keep tomorrow as research only until fresh close data.'
)
STALE_CLOSE_REPORT_NOTE = (
    'Close report is previous-session cache; not live intraday confirmation.'
)
NO_CLEAN_LIVE_CANDIDATE = 'No clean live candidate'

LIVE_STRICT_MODES = frozenset({'today', 'intraday', 'postmarket', 'morning', 'close', 'action_plan'})

REJECTION_TEXT_TOKENS = (
    'STRONG BEARISH',
    'BEARISH',
    'SHORT',
    'BREAKDOWN',
    'AVOID',
    'REJECT',
    'BIG_MOVE',
)

INTEL_FILE = DATA_DIR / 'intelligence.json'
SCANNER_FILE = DATA_DIR / 'scanner_data.json'
FINAL_CONF_FILE = DATA_DIR / 'final_confidence_report.json'
WATCHLIST_FILE = DATA_DIR / 'tomorrow_watchlist_report.json'

_rejection_cache: dict[str, str] | None = None
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


def _normalize_ticker(value: object) -> str:
    return str(value or '').strip().upper()


def _reason_matches_rejection(text: str) -> bool:
    upper = str(text or '').upper()
    if not upper.strip():
        return False
    if any(token in upper for token in REJECTION_TEXT_TOKENS):
        return True
    if re.search(r'\bBEAR(ISH)?\b', upper):
        return True
    return False


def _register(registry: dict[str, str], ticker: str, reason: str) -> None:
    sym = _normalize_ticker(ticker)
    if not sym or sym == '?':
        return
    reason_txt = str(reason or 'Live rejection').strip()[:120]
    if sym not in registry or _reason_matches_rejection(reason_txt):
        registry[sym] = reason_txt


def build_live_rejection_set(*, force_refresh: bool = False) -> dict[str, str]:
    """Single live rejection registry from scanner, premarket, intel, avoid lists."""
    global _rejection_cache
    if _rejection_cache is not None and not force_refresh:
        return dict(_rejection_cache)

    registry: dict[str, str] = {}
    intel = _load_json(INTEL_FILE)
    scanner = _load_json(SCANNER_FILE)
    final_conf = _load_json(FINAL_CONF_FILE)
    watchlist = _load_json(WATCHLIST_FILE)

    try:
        from backend.analytics.premarket_conviction import _build_avoid_list

        for row in _build_avoid_list(intel, scanner):
            _register(registry, row.get('ticker') or '', row.get('reason') or 'Avoid list')
    except Exception:
        pass

    for row in (intel or {}).get('risks_and_avoids') or []:
        if not isinstance(row, dict):
            continue
        logic = str(row.get('logic') or row.get('reason') or '')
        ticker = row.get('symbol') or row.get('ticker')
        if _reason_matches_rejection(logic):
            _register(registry, ticker or '', logic)

    for key in ('rejected', 'rejected_candidates', 'rejected_tickers'):
        for row in (intel or {}).get(key) or []:
            if isinstance(row, dict):
                _register(
                    registry,
                    row.get('symbol') or row.get('ticker') or '',
                    row.get('logic') or row.get('reason') or 'Rejected list',
                )
            elif isinstance(row, str):
                _register(registry, row, 'Rejected list')

    for sig in (scanner or {}).get('top_signals') or (scanner or {}).get('signals') or []:
        if not isinstance(sig, dict):
            continue
        ticker = sig.get('ticker') or sig.get('symbol')
        direction = str(sig.get('direction') or 'NEUTRAL').upper()
        strength = str(sig.get('strength') or sig.get('signal_type') or '').upper()
        setup = str(sig.get('setup') or sig.get('label') or sig.get('category') or '')
        blob = f'{setup} {direction} {strength}'.upper()
        try:
            chg = float(sig.get('change_percent') or 0)
        except (TypeError, ValueError):
            chg = 0.0
        if direction == 'BEARISH' or _reason_matches_rejection(blob):
            _register(registry, ticker or '', blob[:120] or 'Bearish scanner signal')
        elif 'BIG_MOVE' in strength and chg < 0:
            _register(registry, ticker or '', f'BIG_MOVE negative {chg:+.1f}%')

    try:
        from backend.analytics.premarket_conviction import (
            _build_setup_candidates,
            _live_setup_status,
            _negative_move_label,
        )

        setups = _build_setup_candidates(scanner, watchlist, final_conf, intel)
        for setup in setups:
            ticker = setup.get('ticker')
            setup_text = str(setup.get('setup') or '')
            direction = str(setup.get('direction') or '').upper()
            if _live_setup_status(setup) == 'Rejected':
                _register(registry, ticker or '', setup_text or 'Live setup rejected')
            try:
                chg = float(setup.get('change_percent') or 0)
            except (TypeError, ValueError):
                chg = 0.0
            neg = _negative_move_label(chg, direction)
            if neg and _reason_matches_rejection(neg):
                _register(registry, ticker or '', neg)
    except Exception:
        pass

    _rejection_cache = dict(registry)
    return dict(registry)


def load_live_avoid_registry() -> dict[str, str]:
    return build_live_rejection_set()


def clear_live_rejection_cache() -> None:
    global _rejection_cache
    _rejection_cache = None


def is_live_rejected(ticker: str, registry: dict[str, str] | None = None) -> tuple[bool, str]:
    sym = _normalize_ticker(ticker)
    reg = registry if registry is not None else build_live_rejection_set()
    if sym in reg:
        return True, reg[sym]
    return False, ''


def is_avoid_or_rejected(ticker: str, registry: dict[str, str] | None = None) -> bool:
    """True when ticker is in live avoid/rejection registry."""
    rejected, _ = is_live_rejected(ticker, registry)
    return rejected


def filter_ticker_list_exclude_avoid(
    tickers: list[Any] | None,
    registry: dict[str, str] | None = None,
) -> list[str]:
    """Remove avoid/rejected tickers from watch display lists."""
    reg = registry if registry is not None else build_live_rejection_set()
    out: list[str] = []
    for item in tickers or []:
        if isinstance(item, dict):
            sym = _normalize_ticker(item.get('ticker') or item.get('symbol'))
        else:
            sym = _normalize_ticker(item)
        if not sym or sym == '?' or sym in reg:
            continue
        if sym not in out:
            out.append(sym)
    return out


def filter_rows_exclude_avoid(
    rows: list[dict[str, Any]] | None,
    registry: dict[str, str] | None = None,
    *,
    ticker_key: str = 'ticker',
) -> list[dict[str, Any]]:
    """Drop setup/watch rows whose ticker is on avoid/rejection list."""
    reg = registry if registry is not None else build_live_rejection_set()
    kept: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        sym = _normalize_ticker(row.get(ticker_key) or row.get('symbol'))
        if sym and sym in reg:
            continue
        kept.append(row)
    return kept


def begin_unified_snapshot() -> None:
    global _snapshot_active
    _snapshot_active = True
    _snapshot_cache.clear()
    _snapshot_picks.clear()
    clear_live_rejection_cache()


def end_unified_snapshot() -> None:
    global _snapshot_active
    _snapshot_active = False


def is_unified_snapshot_active() -> bool:
    return _snapshot_active


def get_snapshot_cached_decision(mode: str) -> dict[str, Any] | None:
    key = 'today' if mode == 'today' else 'tomorrow' if mode == 'tomorrow' else str(mode)
    return _snapshot_cache.get(key)


def cache_snapshot_decision(mode: str, payload: dict[str, Any]) -> None:
    """Store today/tomorrow payload once fully unified — never mid-pipeline."""
    if not is_unified_snapshot_active() or not isinstance(payload, dict):
        return
    key = 'today' if mode == 'today' else 'tomorrow' if mode == 'tomorrow' else str(mode)
    _snapshot_cache[key] = payload


def get_feed_freshness_meta() -> dict[str, Any]:
    from backend.storage.data_paths import get_data_path
    from backend.telegram.freshness_consistency import (
        classify_budget_cache_freshness,
        compute_feed_age_minutes,
        format_compact_freshness_line,
        get_news_freshness_dual,
        get_unified_market_freshness,
    )
    from backend.telegram.lazy_command_runner import DAILY_PACK_FILE

    report_age, _ = compute_feed_age_minutes(DAILY_PACK_FILE)
    scanner_age, _ = compute_feed_age_minutes(get_data_path('scanner_data.json'))
    news_dual = get_news_freshness_dual()
    market_fresh = get_unified_market_freshness()
    report_status = classify_budget_cache_freshness(report_age)
    scanner_status = classify_budget_cache_freshness(scanner_age)
    return {
        'report_age_min': report_age,
        'scanner_age_min': scanner_age,
        'news_age_min': news_dual.get('latest_age_min', -1),
        'report_status': report_status,
        'scanner_status': scanner_status,
        'news_status': news_dual.get('latest_status', 'cache_missing'),
        'scanner_fresh': scanner_status == 'fresh',
        'report_stale': report_status == 'stale',
        'market_fresh': market_fresh.get('is_fresh', False),
        'market_stale': market_fresh.get('is_stale', False),
        'market_reason': market_fresh.get('reason', ''),
        'lines': {
            'report': format_compact_freshness_line('Report', report_age),
            'scanner': format_compact_freshness_line('Scanner', scanner_age),
            'news': news_dual.get('latest_line', 'News: unavailable'),
            'report_news': news_dual.get('report_line', 'Report news cache: unavailable'),
            'market': market_fresh.get('line', 'Market: unavailable'),
        },
        'news_dual': news_dual,
        'market': market_fresh,
    }


def pick_live_safe_top(
    ranked: list[dict[str, Any]],
    registry: dict[str, str],
    *,
    mode: str,
) -> tuple[dict[str, Any] | None, str, list[str]]:
    """Hard override — never return a live-rejected ticker for strict intraday modes."""
    priority = {'BUY_CANDIDATE': 4, 'WATCH_FOR_ENTRY': 3, 'AVOID': 1}
    ordered = sorted(
        ranked,
        key=lambda row: (priority.get(str(row.get('action') or ''), 0), int(row.get('score') or 0)),
        reverse=True,
    )
    warnings: list[str] = []
    strict = mode in LIVE_STRICT_MODES or mode == 'today'

    for row in ordered:
        if str(row.get('action') or '') == 'AVOID':
            continue
        ticker = _normalize_ticker(row.get('ticker'))
        if not ticker:
            continue
        rejected, reason = is_live_rejected(ticker, registry)
        if rejected and strict:
            continue
        if rejected and mode == 'tomorrow':
            continue
        decision = str(row.get('action') or 'WATCH_FOR_ENTRY')
        if decision not in ('BUY_CANDIDATE', 'WATCH_FOR_ENTRY'):
            decision = 'WATCH_FOR_ENTRY'
        return row, decision, warnings

    if mode == 'tomorrow':
        for row in ordered:
            ticker = _normalize_ticker(row.get('ticker'))
            if not ticker:
                continue
            rejected, _ = is_live_rejected(ticker, registry)
            if not rejected:
                continue
            warnings.append(TOMORROW_LIVE_REJECTION_WARNING)
            decision = str(row.get('action') or 'WATCH_FOR_ENTRY')
            if decision == 'AVOID':
                decision = 'WATCH_FOR_ENTRY'
            return row, decision, warnings

    return None, 'NO_CLEAN_CANDIDATE', warnings


def apply_live_guard_to_ranked(
    ranked: list[dict[str, Any]],
    *,
    mode: str,
    registry: dict[str, str] | None = None,
    freshness_meta: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[str], str]:
    reg = registry if registry is not None else build_live_rejection_set()
    meta = freshness_meta if freshness_meta is not None else get_feed_freshness_meta()
    warnings: list[str] = []
    from backend.telegram.response_format import normalize_bullet_items

    updated: list[dict[str, Any]] = []
    for row in ranked:
        item = dict(row)
        rejected, reason = is_live_rejected(str(item.get('ticker') or ''), reg)
        if rejected:
            item['action'] = 'AVOID'
            item['score'] = min(int(item.get('score') or 0), 20)
            risks = [str(r) for r in (item.get('risk') or [])]
            if HARD_REJECTION_MSG not in risks:
                risks.insert(0, HARD_REJECTION_MSG)
            item['risk'] = risks[:6]
            why = normalize_bullet_items(item.get('why'))
            why.append(f'Live rejection: {reason[:80]}')
            item['why'] = why[:6]
        updated.append(item)

    top_pick, decision, pick_warnings = pick_live_safe_top(updated, reg, mode=mode)
    warnings.extend(pick_warnings)

    if top_pick is None and decision == 'NO_CLEAN_CANDIDATE':
        if mode in LIVE_STRICT_MODES or mode == 'today':
            warnings.append(NO_CLEAN_LIVE_CANDIDATE)
    elif top_pick:
        rejected, _ = is_live_rejected(str(top_pick.get('ticker') or ''), reg)
        if rejected and (mode in LIVE_STRICT_MODES or mode == 'today'):
            top_pick = None
            decision = 'NO_CLEAN_CANDIDATE'
            warnings.append(NO_CLEAN_LIVE_CANDIDATE)

    if meta.get('report_stale') and meta.get('scanner_fresh') and top_pick:
        fc_only = not (top_pick.get('supports') or [])
        if fc_only:
            warnings.append(SNAPSHOT_CONFLICT_WARNING)

    if is_unified_snapshot_active() and top_pick:
        _snapshot_picks[mode] = _normalize_ticker(top_pick.get('ticker')) or None

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
    out['avoid'] = [r for r in updated if r.get('action') == 'AVOID'][:12]
    out['watch_for_entry'] = [r for r in updated if r.get('action') == 'WATCH_FOR_ENTRY'][:10]
    out['snapshot_warnings'] = list(dict.fromkeys(warnings))
    out['freshness_meta'] = meta
    out['live_rejection_set'] = sorted(build_live_rejection_set().keys())

    msg_parts: list[str] = []
    if warnings:
        msg_parts.extend(out['snapshot_warnings'])
        msg_parts.append('')
    if payload.get('unified_priority') and mode in ('today', 'tomorrow'):
        try:
            from backend.trading.unified_live_priority_engine import build_unified_priority, format_decision_unified

            unified = build_unified_priority(mode=mode)
            body = format_decision_unified(unified, mode=mode)
            out['telegram_message'] = '\n'.join(msg_parts + [body]) if msg_parts else body
        except Exception:
            msg_parts.append(
                _build_telegram_message(
                    mode=mode,
                    decision=decision,
                    top_pick=top_pick,
                    avoid=out['avoid'],
                )
            )
            out['telegram_message'] = '\n'.join(msg_parts)
    else:
        msg_parts.append(
            _build_telegram_message(
                mode=mode,
                decision=decision,
                top_pick=top_pick,
                avoid=out['avoid'],
            )
        )
        out['telegram_message'] = '\n'.join(msg_parts)
    return out


MYFEED_DECISION_LAYER_ORDER: tuple[str, ...] = (
    'market_mode_time_safety',
    'freshness',
    'scanner_price_volume',
    'watchlist_report_candidates',
    'news_govt_global_broker_myfeed_catalysts',
    'memory_calibration',
    'avoid_rejection_filters',
    'final_score',
    'watch_for_entry_avoid_wait',
)

MY_FEED_SCORE_BUMP_CAP = 8
MY_FEED_MAX_SCORE = 60


def apply_my_feed_evidence(
    ranked: list[dict[str, Any]],
    registry: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """
    My Feed evidence only — catalyst/risk notes and small watch-priority bump.

    Layer order (see MYFEED_DECISION_LAYER_ORDER): market safety → freshness → scanner →
    watchlist → catalysts (incl. My Feed) → memory → avoid filters → final score → WATCH/AVOID/WAIT.

    Never creates BUY/SELL alone; never overrides live rejection or stale safety.
    """
    try:
        from backend.my_feed.my_feed_db import active_items_for_tickers
    except Exception:
        return ranked

    reg = registry if registry is not None else build_live_rejection_set()
    tickers = [_normalize_ticker(row.get('ticker')) for row in ranked if row.get('ticker')]
    feed_items = active_items_for_tickers(tickers)
    if not feed_items:
        return ranked

    from backend.my_feed.feed_verification import is_catalyst_eligible_item

    feed_items = [f for f in feed_items if is_catalyst_eligible_item(f)]
    if not feed_items:
        return ranked

    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for feed in feed_items:
        for sym in feed.get('tickers') or []:
            key = _normalize_ticker(sym)
            if key:
                by_ticker.setdefault(key, []).append(feed)

    from backend.telegram.response_format import normalize_bullet_items
    updated: list[dict[str, Any]] = []
    for row in ranked:
        item = dict(row)
        ticker = _normalize_ticker(item.get('ticker'))
        matches = by_ticker.get(ticker) or []
        if not matches:
            updated.append(item)
            continue

        rejected, reject_reason = is_live_rejected(ticker, reg)
        for feed in matches[:2]:
            summary = str(feed.get('verified_headline') or feed.get('cleaned_summary') or '')[:120]
            action = str(feed.get('suggested_action') or 'NEWS ONLY')
            if action in ('WATCH FOR CONFIRMATION', 'WAIT FOR CONFIRMATION'):
                why = [str(w) for w in normalize_bullet_items(item.get('why'))]
                note = f'user_feed catalyst: {summary}' if summary else 'user_feed catalyst noted'
                if note not in why:
                    why.insert(0, note)
                item['why'] = why[:6]
            elif action in (
                'RISK ALERT', 'AVOID', 'MARKET RISK ALERT', 'RISK WATCH',
                'AVOID / RISK WATCH', 'COMMODITY RISK ALERT', 'OIL RISK WATCH',
            ):
                risk = [str(r) for r in normalize_bullet_items(item.get('risk'))]
                note = f'user_feed risk: {summary}' if summary else f'user_feed {action.lower()}'
                if note not in risk:
                    risk.insert(0, note)
                item['risk'] = risk[:6]
            elif action == 'WAIT FOR CONFIRMATION':
                confirm = [str(c) for c in normalize_bullet_items(item.get('confirmation_needed'))]
                confirm.append('My Feed suggests waiting for confirmation')
                item['confirmation_needed'] = confirm[:5]

        if rejected:
            item['why'] = list(dict.fromkeys(
                [*normalize_bullet_items(item.get('why')),
                 f'My Feed noted but live scanner rejected: {reject_reason[:80]}']
            ))[:6]
            updated.append(item)
            continue

        if item.get('action') == 'AVOID':
            updated.append(item)
            continue

        bump = min(
            MY_FEED_SCORE_BUMP_CAP,
            max(1, int(float(matches[0].get('impact_score') or 0) // 12)),
        )
        current_score = int(item.get('score') or 0)
        item['score'] = min(MY_FEED_MAX_SCORE, current_score + bump)

        supports = set(item.get('supports') or [])
        if item.get('action') == 'BUY_CANDIDATE' and 'my_feed' not in supports:
            pass
        elif item.get('action') not in ('BUY_CANDIDATE', 'AVOID'):
            item['action'] = 'WATCH_FOR_ENTRY'

        evidence = [str(e) for e in (item.get('evidence_notes') or [])]
        if 'user_feed' not in evidence:
            evidence.append('user_feed')
        item['evidence_notes'] = evidence[:4]
        updated.append(item)
    return updated


def guard_action_plan_top(top: dict[str, Any] | None, decision: str) -> tuple[dict[str, Any] | None, str, list[str]]:
    if not top:
        return None, 'NO_CLEAN_CANDIDATE', []
    payload = apply_live_guard_to_payload({
        'ok': True,
        'mode': 'today',
        'ranked_candidates': [top],
        'decision': decision,
        'top_pick': top,
    })
    return payload.get('top_pick'), str(payload.get('decision') or 'NO_CLEAN_CANDIDATE'), list(payload.get('snapshot_warnings') or [])


def note_snapshot_pick(source: str, ticker: str | None) -> None:
    _snapshot_picks[str(source)] = _normalize_ticker(ticker) or None


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


def full_snapshot_consistency_warning() -> str | None:
    meta = get_feed_freshness_meta()
    if meta.get('report_stale') and meta.get('scanner_fresh'):
        return FULL_SNAPSHOT_CONSISTENCY_WARNING
    if snapshot_consistency_warnings():
        return FULL_SNAPSHOT_CONSISTENCY_WARNING
    return None


def _canonical_outcome_stats() -> dict[str, Any]:
    from backend.storage.outcome_resolver import get_canonical_outcome_stats

    return get_canonical_outcome_stats()


def memory_outcome_warning(stats: dict[str, Any], overall: dict[str, Any]) -> str | None:
    canonical = _canonical_outcome_stats()
    resolved_total = int(canonical.get('resolved_total') or 0)
    predictions_tracked = int(canonical.get('predictions_tracked') or 0)
    if predictions_tracked <= 0:
        predictions_tracked = int(stats.get('predictions') or overall.get('total_predictions') or 0)
    if predictions_tracked > 0 and resolved_total == 0:
        return 'Do not trust win-rate/calibration until outcomes resolve.'
    return None


def memory_outcome_status_lines(stats: dict[str, Any], overall: dict[str, Any]) -> list[str]:
    """Resolver status lines for /memory when outcomes are still unresolved."""
    canonical = _canonical_outcome_stats()
    resolved_total = int(canonical.get('resolved_total') or 0)
    predictions_tracked = int(canonical.get('predictions_tracked') or 0)
    if predictions_tracked <= 0:
        predictions_tracked = int(stats.get('predictions') or overall.get('total_predictions') or 0)
    if predictions_tracked <= 0 or resolved_total > 0:
        return []
    from backend.storage.outcome_resolver import format_outcome_resolver_status_lines

    return format_outcome_resolver_status_lines()


def calibration_outcomes_unresolved(
    stats: dict[str, Any] | None = None,
    overall: dict[str, Any] | None = None,
) -> bool:
    del stats, overall
    return int(_canonical_outcome_stats().get('resolved_total') or 0) == 0


def calibration_unresolved_message(stats: dict[str, Any] | None = None, overall: dict[str, Any] | None = None) -> list[str]:
    if not calibration_outcomes_unresolved(stats, overall):
        return []
    from backend.storage.outcome_resolver import format_outcome_resolver_status_lines

    lines = ['Calibration unavailable — outcomes unresolved.']
    lines.extend(format_outcome_resolver_status_lines())
    lines.append('Do not trust win-rate until outcome resolver completes.')
    return lines


def get_calibration_resolved_count(
    stats: dict[str, Any] | None = None,
    overall: dict[str, Any] | None = None,
) -> int:
    del stats, overall
    return int(_canonical_outcome_stats().get('resolved_total') or 0)


def get_calibration_mode(
    stats: dict[str, Any] | None = None,
    overall: dict[str, Any] | None = None,
) -> str:
    """Return unresolved | warmup | ready."""
    from backend.storage.outcome_resolver import CALIBRATION_MIN_SAMPLE

    resolved = get_calibration_resolved_count(stats, overall)
    if resolved == 0:
        return 'unresolved'
    if resolved < CALIBRATION_MIN_SAMPLE:
        return 'warmup'
    return 'ready'


def _format_pct(value: float | None) -> str:
    if value is None:
        return '—'
    return f'{value * 100:.1f}'


def calibration_warmup_message(
    stats: dict[str, Any] | None = None,
    overall: dict[str, Any] | None = None,
) -> list[str]:
    del stats, overall
    canonical = _canonical_outcome_stats()
    resolved = int(canonical.get('resolved_total') or 0)
    pending = int(canonical.get('pending_total') or 0)
    return [
        'Calibration warming up — sample too small.',
        f'Resolved outcomes: {resolved}',
        f'Pending outcomes: {pending}',
        'Do not trust win-rate yet.',
    ]


def calibration_ready_message(
    stats: dict[str, Any] | None = None,
    overall: dict[str, Any] | None = None,
) -> list[str]:
    del stats, overall
    canonical = _canonical_outcome_stats()
    resolved = int(canonical.get('resolved_total') or 0)
    pending = int(canonical.get('pending_total') or 0)
    lines = [
        f'Resolved outcomes: {resolved}',
        f'Pending outcomes: {pending}',
        f'Hit rate: {_format_pct(canonical.get("hit_rate"))}%',
        f'Bullish hit rate: {_format_pct(canonical.get("bullish_hit_rate"))}%',
        f'Bearish/rejection hit rate: {_format_pct(canonical.get("bearish_hit_rate"))}%',
        f'Neutral count: {int(canonical.get("neutral") or 0)}',
    ]
    last_resolved = canonical.get('last_resolved_at')
    if last_resolved:
        lines.append(f'Last resolved: {last_resolved}')
    return lines


def calibration_render_lines(
    stats: dict[str, Any] | None = None,
    overall: dict[str, Any] | None = None,
) -> list[str]:
    mode = get_calibration_mode(stats, overall)
    if mode == 'unresolved':
        return calibration_unresolved_message(stats, overall)
    if mode == 'warmup':
        return calibration_warmup_message(stats, overall)
    return calibration_ready_message(stats, overall)
