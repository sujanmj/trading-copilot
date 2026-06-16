"""
Stock Confluence Decision Engine — shadow-only multi-source confluence (Stage 45B).

Combines final confidence, watchlist, scanner, broker, external evidence, AI Hub
payloads, market memory, and simulation into one ranked decision payload.
Never places trades or forces BUY without independent confluence.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.utils.config import DATA_DIR

STOCK_STAGE_45B_CONFLUENCE_DECISION_ENGINE = True

VALID_MODES = frozenset({'today', 'tomorrow', 'intraday', 'postmarket'})
SHADOW_MODE = True
DISCLAIMER = 'Shadow confluence decision only — not trade execution.'

FINAL_CONFIDENCE_PATH = DATA_DIR / 'final_confidence_report.json'
TOMORROW_WATCHLIST_PATH = DATA_DIR / 'tomorrow_watchlist_report.json'
CALIBRATION_PATH = DATA_DIR / 'confidence_calibration_report.json'
MEMORY_CACHE_PATH = DATA_DIR / 'market_memory_dashboard_cache.json'

BUY_INDEPENDENT_SUPPORTS = frozenset({
    'final_confidence',
    'scanner',
    'broker',
    'external',
    'global_sector',
    'memory',
    'simulation',
})

CONFIRMATION_DEFAULTS = (
    'price strength above recent support',
    'volume support on entry window',
    'market data not stale',
)

INVALID_IF_DEFAULTS = (
    'opens weak below support',
    'sector or global context turns negative',
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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


def _clamp_score(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _score_from_row(row: dict[str, Any]) -> float:
    for key in ('score', 'final_score', 'watchlist_score', 'confidence_score'):
        val = row.get(key)
        try:
            if val is not None:
                return float(val)
        except (TypeError, ValueError):
            continue
    label = str(row.get('confidence_label') or '').upper()
    if label == 'HIGH':
        return 72.0
    if label == 'MEDIUM':
        return 55.0
    if label == 'LOW':
        return 38.0
    return 40.0


def _decision_token(row: dict[str, Any]) -> str:
    return str(row.get('decision') or row.get('action') or row.get('display_tier') or '').upper()


def _confidence_label(score: int) -> str:
    if score >= 75:
        return 'HIGH'
    if score >= 55:
        return 'MEDIUM'
    return 'LOW'


def _safe_build_scan_payload() -> dict[str, Any]:
    try:
        from backend.analytics.aihub_tab_payloads import build_scan_payload

        return build_scan_payload() or {}
    except Exception:
        return {}


def _safe_build_market_payload() -> dict[str, Any]:
    try:
        from backend.analytics.aihub_tab_payloads import build_market_payload

        return build_market_payload(force=False) or {}
    except Exception:
        return {}


def _safe_build_global_payload() -> dict[str, Any]:
    try:
        from backend.analytics.aihub_tab_payloads import build_global_payload

        return build_global_payload() or {}
    except Exception:
        return {}


def _safe_broker_dashboard() -> dict[str, Any]:
    try:
        from backend.analytics.broker_prediction_intelligence import get_broker_intelligence_dashboard

        return get_broker_intelligence_dashboard() or {}
    except Exception:
        return {}


def _safe_memory_dashboard() -> dict[str, Any]:
    cached = _load_json(MEMORY_CACHE_PATH)
    if cached.get('ok') is True:
        return cached
    try:
        from backend.analytics.market_memory_dashboard import get_market_memory_dashboard

        return get_market_memory_dashboard(limit=30) or {}
    except Exception:
        return {}


def _load_sources() -> dict[str, Any]:
    fc = _load_json(FINAL_CONFIDENCE_PATH)
    if not fc.get('ok'):
        try:
            from backend.analytics.final_confidence_report_loader import load_cached_final_confidence_report

            wrapped = load_cached_final_confidence_report(limit=50)
            if wrapped.get('ok'):
                fc = wrapped.get('report') if isinstance(wrapped.get('report'), dict) else wrapped
        except Exception:
            pass

    tw = _load_json(TOMORROW_WATCHLIST_PATH)
    calib = _load_json(CALIBRATION_PATH)
    scan = _safe_build_scan_payload()
    market = _safe_build_market_payload()
    global_p = _safe_build_global_payload()
    broker = _safe_broker_dashboard()
    memory = _safe_memory_dashboard()

    return {
        'final_confidence': fc,
        'tomorrow_watchlist': tw,
        'calibration': calib,
        'scan': scan,
        'market': market,
        'global': global_p,
        'broker': broker,
        'memory': memory,
    }


def _broker_cache_stale(sources: dict[str, Any]) -> bool:
    broker = sources.get('broker') or {}
    if broker.get('stale') is True or broker.get('stale_reason'):
        return True
    try:
        from backend.analytics.broker_intelligence import get_broker_intel_overview

        overview = get_broker_intel_overview(cache_only=True, lite=True) or {}
        return bool(overview.get('stale') or overview.get('stale_reason'))
    except Exception:
        return False


def _budget_cache_stale(sources: dict[str, Any]) -> bool:
    try:
        from backend.analytics.budget_impact import compute_freshness_panel

        panel = compute_freshness_panel() or {}
        return str(panel.get('status') or '').lower() == 'stale'
    except Exception:
        return False


def _calibration_bucket_ok(calib: dict[str, Any], score: float) -> tuple[bool, bool]:
    """Return (acceptable, weak_sample)."""
    if not calib:
        return True, False
    recs = calib.get('recommendations') or []
    if not isinstance(recs, list):
        return True, False
    weak = False
    for rec in recs:
        if not isinstance(rec, dict):
            continue
        if rec.get('low_sample') is True or rec.get('strength') == 'weak':
            weak = True
        bucket = rec.get('bucket') or rec.get('score_bucket')
        if bucket and isinstance(bucket, str):
            try:
                lo, hi = bucket.replace('%', '').split('-', 1)
                if float(lo) <= score <= float(hi) and rec.get('low_sample'):
                    weak = True
            except (TypeError, ValueError):
                pass
    return not weak, weak


def _collect_universe(sources: dict[str, Any]) -> dict[str, dict[str, Any]]:
    universe: dict[str, dict[str, Any]] = {}

    def _ensure(ticker: str) -> dict[str, Any]:
        if ticker not in universe:
            universe[ticker] = {
                'ticker': ticker,
                'fc_row': None,
                'wl_row': None,
                'scanner_rows': [],
                'broker_rows': [],
                'external_rows': [],
                'global_sectors': set(),
                'memory_rows': [],
                'sources_seen': set(),
            }
        return universe[ticker]

    fc = sources.get('final_confidence') or {}
    for row in fc.get('top_candidates') or fc.get('rows') or []:
        if not isinstance(row, dict):
            continue
        ticker = _normalize_ticker(row.get('ticker'))
        if not ticker:
            continue
        entry = _ensure(ticker)
        entry['fc_row'] = row
        entry['sources_seen'].add('final_confidence')

    tw = sources.get('tomorrow_watchlist') or {}
    for row in tw.get('top_watchlist') or tw.get('raw_candidates') or []:
        if not isinstance(row, dict):
            continue
        ticker = _normalize_ticker(row.get('ticker'))
        if not ticker:
            continue
        entry = _ensure(ticker)
        entry['wl_row'] = row
        entry['sources_seen'].add('tomorrow_watchlist')

    scan = sources.get('scan') or {}
    for bucket in ('live_scanner', 'watchlist_candidates', 'memory_signals', 'items'):
        for row in scan.get(bucket) or []:
            if not isinstance(row, dict):
                continue
            ticker = _normalize_ticker(row.get('ticker') or row.get('symbol'))
            if not ticker:
                continue
            entry = _ensure(ticker)
            entry['scanner_rows'].append(row)
            entry['sources_seen'].add('scanner')

    broker = sources.get('broker') or {}
    our_vs = broker.get('our_vs_broker') or {}
    for row in our_vs.get('comparisons') or our_vs.get('rows') or our_vs.get('top_broker_candidates') or []:
        if not isinstance(row, dict):
            continue
        ticker = _normalize_ticker(row.get('ticker') or row.get('symbol'))
        if not ticker:
            continue
        entry = _ensure(ticker)
        entry['broker_rows'].append(row)
        entry['sources_seen'].add('broker')

    global_p = sources.get('global') or {}
    sector_mapping = (global_p.get('summary') or {}).get('sector_mapping') or {}
    supported = sector_mapping.get('supported_sectors') or []
    for row in sector_mapping.get('commodity_impacts') or []:
        if not isinstance(row, dict):
            continue
        for sym in row.get('symbols') or []:
            ticker = _normalize_ticker(sym)
            if not ticker:
                continue
            entry = _ensure(ticker)
            entry['global_sectors'].add(str(row.get('commodity') or 'sector'))
            entry['sources_seen'].add('global_sector')

    memory = sources.get('memory') or {}
    for row in memory.get('latest_predictions') or memory.get('active_predictions') or []:
        if not isinstance(row, dict):
            continue
        ticker = _normalize_ticker(row.get('ticker') or row.get('symbol'))
        if not ticker:
            continue
        entry = _ensure(ticker)
        entry['memory_rows'].append(row)
        entry['sources_seen'].add('memory')

    for row in (fc.get('top_candidates') or [])[:50]:
        if not isinstance(row, dict):
            continue
        ext = row.get('external_evidence') or {}
        ticker = _normalize_ticker(row.get('ticker'))
        if not ticker:
            continue
        counts = ext.get('counts') if isinstance(ext, dict) else {}
        if isinstance(counts, dict) and int(counts.get('positive') or 0) > 0:
            entry = _ensure(ticker)
            entry['external_rows'].append(ext)
            entry['sources_seen'].add('external')

    return universe


def _broker_agrees(rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        if row.get('agreement') is True:
            return True
        stance = str(row.get('broker_stance') or row.get('stance') or row.get('action') or '').upper()
        if stance in ('BUY', 'BULLISH', 'ACCUMULATE', 'OUTPERFORM', 'LONG'):
            return True
    return False


def _broker_conflict(rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        if row.get('conflict') is True:
            return True
        stance = str(row.get('broker_stance') or row.get('stance') or '').upper()
        if stance in ('SELL', 'BEARISH', 'REDUCE', 'UNDERPERFORM', 'SHORT'):
            return True
    return False


def _simulation_positive(fc_row: dict[str, Any] | None) -> bool:
    if not fc_row:
        return False
    sim = fc_row.get('historical_simulation') or {}
    if not isinstance(sim, dict) or sim.get('ok') is not True:
        return False
    adj = sim.get('confidence_adjustment')
    try:
        return float(adj or 0) > 0
    except (TypeError, ValueError):
        return False


def _failed_strong_signal(fc_row: dict[str, Any] | None, ticker: str, sources: dict[str, Any]) -> bool:
    warnings: list[str] = []
    if fc_row:
        warnings.extend(fc_row.get('hard_warnings') or [])
        warnings.extend(fc_row.get('warnings') or [])
    for token in warnings:
        if 'fail' in str(token).lower() or 'weaken' in str(token).lower():
            return True
    try:
        from backend.analytics.aihub_tab_payloads import _detect_failed_strong_warnings

        pack = {'tomorrow_watchlist': sources.get('tomorrow_watchlist') or {}}
        for row in _detect_failed_strong_warnings({}, pack, sources.get('final_confidence')):
            if isinstance(row, dict) and _normalize_ticker(row.get('ticker')) == ticker:
                return True
    except Exception:
        pass
    return False


def _score_candidate(
    ticker: str,
    entry: dict[str, Any],
    sources: dict[str, Any],
    *,
    mode: str,
) -> dict[str, Any]:
    fc_row = entry.get('fc_row')
    wl_row = entry.get('wl_row')
    calib = sources.get('calibration') or {}
    market = sources.get('market') or {}
    market_summary = market.get('summary') or {}
    stale_market = bool(market_summary.get('stale') or market_summary.get('is_stale'))

    fc_score = _score_from_row(fc_row) if fc_row else 0.0
    wl_score = _score_from_row(wl_row) if wl_row else 0.0
    base = fc_score * 0.55 + wl_score * 0.25
    if mode == 'tomorrow' and wl_score:
        base = fc_score * 0.4 + wl_score * 0.4
    if mode == 'intraday' and entry.get('scanner_rows'):
        base += 8.0
    if mode == 'postmarket':
        base = fc_score * 0.45 + wl_score * 0.35

    boost = 0.0
    penalty = 0.0
    why: list[str] = []
    risk: list[str] = []
    confirmation: list[str] = list(CONFIRMATION_DEFAULTS)
    invalid_if: list[str] = list(INVALID_IF_DEFAULTS)
    supports: set[str] = set()

    fc_decision = _decision_token(fc_row) if fc_row else ''
    broker_stale = _broker_cache_stale(sources)
    budget_stale = _budget_cache_stale(sources)
    if broker_stale:
        risk.append('Broker cache stale — research only')
        confirmation.append('refresh broker cache before acting on broker evidence')
    if budget_stale:
        penalty += 6.0
        risk.append('Budget/theme cache stale — research only')
        confirmation.append('refresh budget cache before theme-driven entries')

    if fc_row and fc_decision in ('BUY_CANDIDATE', 'BUY', 'WATCH'):
        supports.add('final_confidence')
        why.append('Final confidence report includes this name')
        if fc_decision in ('BUY_CANDIDATE', 'BUY'):
            boost += 6.0
    elif fc_row and fc_score >= 43:
        supports.add('final_confidence')
        why.append('Final confidence score supports review')

    if wl_row:
        why.append('Already in AstraEdge watchlist')
        if wl_score >= 50:
            boost += 4.0

    if entry.get('scanner_rows'):
        supports.add('scanner')
        boost += 8.0
        why.append('Live scanner or scan payload supports ticker')
        strongest = max(entry['scanner_rows'], key=lambda r: _score_from_row(r))
        strength = str(strongest.get('strength') or strongest.get('signal_type') or 'SIGNAL')
        if 'ULTRA' in strength.upper() or 'STRONG' in strength.upper():
            boost += 4.0

    if not broker_stale and _broker_agrees(entry.get('broker_rows') or []):
        supports.add('broker')
        boost += 10.0
        why.append('Broker/external evidence supports same ticker')
    if not broker_stale and _broker_conflict(entry.get('broker_rows') or []):
        penalty += 12.0
        risk.append('Broker stance conflicts with our signal')

    if entry.get('external_rows'):
        supports.add('external')
        boost += 6.0
        why.append('External stock evidence is positive')

    if entry.get('global_sectors'):
        supports.add('global_sector')
        sectors = ', '.join(sorted(entry['global_sectors']))
        boost += 5.0
        why.append(f'Global/sector context supportive ({sectors})')

    if entry.get('memory_rows'):
        supports.add('memory')
        boost += 5.0
        why.append('Active market memory prediction supports ticker')

    if _simulation_positive(fc_row):
        supports.add('simulation')
        boost += 4.0
        why.append('Historical simulation expectancy is positive')

    learning = (sources.get('memory') or {}).get('learning') or {}
    overall = learning.get('overall') or {}
    win_rate = overall.get('win_rate')
    if isinstance(win_rate, (int, float)) and win_rate >= 55 and supports:
        boost += 3.0

    cal_ok, cal_weak = _calibration_bucket_ok(calib, fc_score or wl_score or base)
    if cal_ok:
        boost += 2.0
    if cal_weak:
        penalty += 6.0
        risk.append('Calibration sample weak for score bucket')

    if fc_decision == 'AVOID' or 'AVOID' in fc_decision:
        penalty += 35.0
        risk.append('Final confidence marked AVOID')

    if _failed_strong_signal(fc_row, ticker, sources):
        penalty += 18.0
        risk.append('Recent failed or weakened strong signal')

    live_avoid = sources.get('_live_avoid') or {}
    sym = _normalize_ticker(ticker)
    if sym and sym in live_avoid:
        penalty += 100.0
        risk.append('Rejected by live scanner: strong bearish / breakdown')
        why.append(f'Live rejection: {str(live_avoid[sym])[:80]}')

    freshness_meta = sources.get('_freshness_meta') or {}
    if freshness_meta.get('scanner_fresh') and freshness_meta.get('report_stale'):
        if fc_row and not entry.get('scanner_rows'):
            penalty += 12.0
            risk.append('Stale overnight report context only')
        if entry.get('scanner_rows') and not fc_row:
            boost += 6.0
            why.append('Live scanner fresh — prioritized over stale report')

    if stale_market:
        penalty += 8.0
        risk.append('Market context stale')
        confirmation.append('refresh market snapshot before entry')

    if fc_row:
        warnings = fc_row.get('warnings') or []
        if 'suspicious_price_scale' in warnings:
            penalty += 20.0
            risk.append('Suspicious price scale detected')
        if 'low_sample_size' in warnings:
            penalty += 5.0
            risk.append('Low historical sample size')

    global_summary = (sources.get('global') or {}).get('summary') or {}
    at_risk = global_summary.get('sector_mapping', {}).get('at_risk_sectors') or []
    if at_risk and entry.get('global_sectors'):
        penalty += 4.0
        risk.append('Global risk flags some related sectors')

    if not supports or (supports == {'tomorrow_watchlist'}):
        penalty += 10.0
        risk.append('No confirmation signal from independent sources')
        confirmation.append('wait for a second independent support')

    confluence = _clamp_score(base + boost - penalty)

    independent = supports & BUY_INDEPENDENT_SUPPORTS
    can_buy = False
    if confluence >= 68 and len(independent) >= 2:
        if independent == {'broker'}:
            can_buy = False
        elif independent == {'external'}:
            can_buy = False
        elif 'tomorrow_watchlist' in entry.get('sources_seen', set()) and len(independent) == 1:
            can_buy = False
        elif fc_decision == 'AVOID' or 'AVOID' in fc_decision:
            can_buy = False
        elif penalty >= 30 and 'AVOID' not in fc_decision:
            can_buy = False
        else:
            non_broker = independent - {'broker'}
            if len(non_broker) >= 1 and len(independent) >= 2:
                can_buy = True
            elif len(independent) >= 3 and 'broker' in independent:
                can_buy = True

    fc = sources.get('final_confidence') or {}
    buy_cap = bool(fc.get('buy_cap_active'))
    if buy_cap and can_buy:
        can_buy = False
        risk.append('Active mode caps BUY to watch/research only')

    if can_buy:
        action = 'BUY_CANDIDATE'
    elif fc_decision == 'AVOID' or penalty >= 35 or confluence < 35:
        action = 'AVOID'
    elif confluence >= 45 or supports:
        action = 'WATCH_FOR_ENTRY'
    else:
        action = 'AVOID'

    if not why:
        why.append('Listed in candidate universe — review context before acting')

    return {
        'ticker': ticker,
        'action': action,
        'score': confluence,
        'confidence': _confidence_label(confluence),
        'why': why[:6],
        'confirmation_needed': confirmation[:5],
        'risk': risk[:5],
        'invalid_if': invalid_if[:4],
        'supports': sorted(independent),
        'boost': round(boost, 1),
        'penalty': round(penalty, 1),
        'base_score': round(base, 1),
        'fc_decision': fc_decision or None,
    }


def _rank_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority = {'BUY_CANDIDATE': 4, 'WATCH_FOR_ENTRY': 3, 'AVOID': 1}
    return sorted(
        candidates,
        key=lambda row: (priority.get(row.get('action'), 0), row.get('score', 0)),
        reverse=True,
    )


def _build_telegram_message(
    *,
    mode: str,
    decision: str,
    top_pick: dict[str, Any] | None,
    avoid: list[dict[str, Any]],
) -> str:
    label = mode.capitalize()
    lines = [f'<b>AstraEdge — {label}</b>', '']
    from backend.telegram.response_format import normalize_bullet_items

    if top_pick and decision != 'NO_CLEAN_CANDIDATE':
        action = str(top_pick.get('action') or 'WATCH_FOR_ENTRY').replace('_', ' ')
        lines.extend([
            '<b>Top candidate:</b>',
            f"{top_pick.get('ticker')} — {action}",
            f"Score: {top_pick.get('score', '—')}",
            '',
            '<b>Why:</b>',
        ])
        for item in normalize_bullet_items(top_pick.get('why')):
            lines.append(f'• {item}')
        try:
            from backend.analytics.broker_intelligence import broker_decision_bullets

            for bullet in broker_decision_bullets(str(top_pick.get('ticker') or ''), mode=mode):
                lines.append(f'• {bullet}')
        except Exception:
            pass
        lines.extend(['', '<b>Wait for:</b>'])
        for item in normalize_bullet_items(top_pick.get('confirmation_needed') or CONFIRMATION_DEFAULTS):
            lines.append(f'• {item}')
        if top_pick.get('risk'):
            lines.extend(['', '<b>Risk:</b>'])
            for item in normalize_bullet_items(top_pick.get('risk')):
                lines.append(f'• {item}')
    else:
        lines.extend([
            '<b>No clean candidate</b>',
            'Nothing meets confluence rules for a confident pick.',
            'Review watch-for-entry names below or refresh reports.',
        ])

    if avoid:
        lines.extend(['', '<b>Avoid:</b>'])
        for row in avoid[:5]:
            reason = (row.get('risk') or row.get('why') or ['weak signal'])[0]
            if isinstance(reason, list):
                reason = reason[0] if reason else 'weak signal'
            lines.append(f"• {row.get('ticker')} — {reason}")
            try:
                from backend.analytics.broker_intelligence import broker_decision_bullets

                for bullet in broker_decision_bullets(str(row.get('ticker') or ''), mode=mode):
                    if 'conflict' in bullet.lower() or 'risk' in bullet.lower():
                        lines.append(f'• {bullet}')
            except Exception:
                pass

    return '\n'.join(lines)


def build_stock_decision(mode: str = 'today') -> dict[str, Any]:
    """Build shadow confluence decision payload for the requested mode."""
    normalized_mode = str(mode or 'today').strip().lower()
    if normalized_mode not in VALID_MODES:
        return {
            'ok': False,
            'error': 'invalid_mode',
            'message': f'mode must be one of: {", ".join(sorted(VALID_MODES))}',
            'stage_marker': 'STOCK_STAGE_45B_CONFLUENCE_DECISION_ENGINE',
        }

    sources = _load_sources()
    try:
        from backend.analytics.unified_decision_engine import (
            build_live_rejection_set,
            get_feed_freshness_meta,
            get_snapshot_cached_decision,
            is_unified_snapshot_active,
        )

        if is_unified_snapshot_active():
            cached = get_snapshot_cached_decision(normalized_mode)
            if cached:
                return cached
        sources['_freshness_meta'] = get_feed_freshness_meta()
        sources['_live_avoid'] = build_live_rejection_set()
    except Exception:
        sources['_freshness_meta'] = {}
        sources['_live_avoid'] = {}
    fc = sources.get('final_confidence') or {}
    if not fc.get('ok') and not fc.get('top_candidates'):
        return {
            'ok': False,
            'error': 'final_confidence_missing',
            'message': 'Decision cache is warming. Try again in 1–2 minutes.',
            'mode': normalized_mode,
            'stage_marker': 'STOCK_STAGE_45B_CONFLUENCE_DECISION_ENGINE',
        }

    universe = _collect_universe(sources)
    scored = [
        _score_candidate(ticker, entry, sources, mode=normalized_mode)
        for ticker, entry in universe.items()
    ]
    ranked = _rank_candidates(scored)
    try:
        from backend.analytics.unified_decision_engine import apply_my_feed_evidence, build_live_rejection_set
        from backend.trading.unified_live_priority_engine import apply_unified_priority_to_ranked

        ranked = apply_my_feed_evidence(ranked, build_live_rejection_set())
        ranked = apply_unified_priority_to_ranked(ranked, mode=normalized_mode, sources=sources)
    except Exception:
        pass
    watch_rows = [r for r in ranked if r.get('action') == 'WATCH_FOR_ENTRY']
    avoid_rows = [r for r in ranked if r.get('action') == 'AVOID']
    buy_rows = [r for r in ranked if r.get('action') == 'BUY_CANDIDATE']

    top_pick: dict[str, Any] | None = None
    decision = 'NO_CLEAN_CANDIDATE'

    if buy_rows:
        top_pick = buy_rows[0]
        decision = 'BUY_CANDIDATE'
    elif watch_rows:
        top_pick = watch_rows[0]
        decision = 'WATCH_FOR_ENTRY'
    elif ranked and ranked[0].get('score', 0) >= 40:
        top_pick = ranked[0]
        if top_pick.get('action') == 'AVOID':
            decision = 'NO_CLEAN_CANDIDATE'
        else:
            decision = str(top_pick.get('action') or 'WATCH_FOR_ENTRY')

    telegram_message = _build_telegram_message(
        mode=normalized_mode,
        decision=decision,
        top_pick=top_pick,
        avoid=avoid_rows,
    )
    if normalized_mode == 'today':
        try:
            from backend.trading.unified_live_priority_engine import build_unified_priority, format_today_unified

            unified = build_unified_priority(mode='today')
            meta = sources.get('_freshness_meta') or {}
            if meta.get('scanner_fresh'):
                telegram_message = format_today_unified(unified)
        except Exception:
            pass

    payload = {
        'ok': True,
        'mode': normalized_mode,
        'generated_at': _now_iso(),
        'shadow_mode': SHADOW_MODE,
        'disclaimer': DISCLAIMER,
        'stage_marker': 'STOCK_STAGE_45B_CONFLUENCE_DECISION_ENGINE',
        'decision': decision,
        'top_pick': top_pick,
        'ranked_candidates': ranked[:25],
        'watch_for_entry': watch_rows[:10],
        'avoid': avoid_rows[:10],
        'telegram_message': telegram_message,
        'summary': {
            'universe_size': len(universe),
            'buy_candidate': len(buy_rows),
            'watch_for_entry': len(watch_rows),
            'avoid': len(avoid_rows),
            'active_mode': fc.get('active_mode'),
            'buy_cap_active': fc.get('buy_cap_active'),
        },
    }

    try:
        from backend.analytics.unified_decision_engine import apply_live_guard_to_payload

        payload = apply_live_guard_to_payload(payload)
    except Exception:
        pass

    return payload


def lookup_ticker_in_decision(ticker: str, *, mode: str = 'today') -> dict[str, Any]:
    """Return per-ticker breakdown from latest decision payload."""
    query = _normalize_ticker(ticker)
    if not query:
        return {'ok': False, 'error': 'ticker is required'}

    payload = build_stock_decision(mode=mode)
    if payload.get('ok') is not True:
        return payload

    for row in payload.get('ranked_candidates') or []:
        if not isinstance(row, dict):
            continue
        sym = _normalize_ticker(row.get('ticker'))
        if sym == query or sym.startswith(query):
            return {
                'ok': True,
                'mode': mode,
                'found': True,
                'ticker': sym,
                'query': query,
                'breakdown': row,
                'decision': payload.get('decision'),
                'generated_at': payload.get('generated_at'),
            }

    return {
        'ok': True,
        'mode': mode,
        'found': False,
        'ticker': query,
        'query': query,
        'message': 'ticker not in latest decision universe',
        'generated_at': payload.get('generated_at'),
    }
