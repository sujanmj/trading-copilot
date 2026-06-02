"""
Tomorrow Watchlist / Final Decision Report — shadow-only daily summary.

Built from final_confidence_report.json. Does not place trades or send alerts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.utils.config import DATA_DIR

SHADOW_MODE = True
DISCLAIMER = 'Shadow watchlist only — not trade execution.'
CONFIDENCE_DISCLAIMER = 'Shadow confidence only — not trade execution.'
FINAL_CONFIDENCE_REPORT_PATH = DATA_DIR / 'final_confidence_report.json'
TOMORROW_WATCHLIST_PATH = DATA_DIR / 'tomorrow_watchlist_report.json'

BUY_CAP_MODES = frozenset({
    'RESEARCH_MODE',
    'INDIA_POSTMARKET_MODE',
    'USA_POSTMARKET_MODE',
})

RISK_NOTE_TOKENS = {
    'market_closed': 'Market is closed — review only, not live entry.',
    'stale_critical_sources': 'Some critical sources are stale.',
    'news_feed_stale': 'News feed may be stale.',
    'runtime_snapshot_stale': 'Runtime snapshot may be stale.',
    'low_sample_size': 'Historical sample size is low for some signals.',
    'suspicious_price_scale': 'Suspicious price scale detected for some tickers.',
    'broker_intelligence_conflict': 'Broker intelligence conflicts with memory.',
    'weak_calibration_signal': 'Calibration sample is weak for some score buckets.',
    'low_simulation_sample': 'Simulation evidence sample is low.',
    'insufficient_evidence': 'Some candidates lack sufficient evidence.',
    'external_negative_stock_news': 'Negative external stock news adds caution.',
    'external_evidence_unavailable': 'External evidence feed unavailable.',
    'broker_prediction_candidate_excluded_from_scoring': 'Broker headline excluded from external score (broker DB handles it).',
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_final_confidence_report(*, limit: int = 50) -> dict[str, Any]:
    """Load cached report or build live."""
    cached = _load_json(FINAL_CONFIDENCE_REPORT_PATH)
    if cached and cached.get('ok') is True:
        rows = cached.get('rows') or []
        if limit and len(rows) > limit:
            payload = dict(cached)
            payload['rows'] = rows[: int(limit)]
            payload['top_candidates'] = (cached.get('top_candidates') or rows[:25])[: min(25, limit)]
            return payload
        return cached

    from backend.analytics.final_confidence_fusion import build_final_confidence_report

    return build_final_confidence_report(limit=limit)


def _market_mode_summary(confidence_report: dict[str, Any]) -> dict[str, Any]:
    router: dict[str, Any] = {}
    try:
        from backend.analytics.market_calendar_router import get_market_router_payload

        router = get_market_router_payload() or {}
    except Exception:
        router = {}

    active_mode = str(
        confidence_report.get('active_mode')
        or router.get('active_mode')
        or 'RESEARCH_MODE',
    )
    return {
        'active_mode': active_mode,
        'active_mode_label': router.get('active_mode_label') or active_mode,
        'india_session': router.get('india_session') or confidence_report.get('india_session'),
        'usa_session': router.get('usa_session') or confidence_report.get('usa_session'),
        'market_closed': bool(
            confidence_report.get('market_closed')
            if confidence_report.get('market_closed') is not None
            else router.get('india_session') == 'closed' and router.get('usa_session') == 'closed'
        ),
        'buy_cap_active': bool(confidence_report.get('buy_cap_active')),
        'next_india_open': router.get('next_india_open'),
        'next_usa_open': router.get('next_usa_open'),
        'routing_reason': router.get('routing_reason'),
    }


DECISION_PRIORITY = {
    'BUY_CANDIDATE': 4,
    'WATCH': 3,
    'AVOID': 2,
    'NO_DECISION': 1,
}


def _normalize_ticker(value: object) -> str:
    return str(value or '').strip().upper()


def _decision_priority(decision: object) -> int:
    return DECISION_PRIORITY.get(str(decision or '').strip().upper(), 0)


def _candidate_timestamp(candidate: dict[str, Any]) -> str:
    for key in ('timestamp', 'prediction_date', 'created_at', 'updated_at'):
        value = candidate.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ''


def _candidate_rank_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    decision = str(candidate.get('decision') or 'NO_DECISION').upper()
    score = int(candidate.get('final_score') or 0)
    timestamp = _candidate_timestamp(candidate)
    hard_count = len(candidate.get('hard_warnings') or [])
    prediction_id = str(candidate.get('prediction_id') or '')
    return (
        _decision_priority(decision),
        score,
        timestamp,
        -hard_count,
        prediction_id,
    )


def dedupe_candidates_by_ticker(
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Keep the best final-confidence candidate per ticker.

    Preserves grouped evidence from duplicate rows on the retained candidate.
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        ticker = _normalize_ticker(candidate.get('ticker'))
        if not ticker:
            continue
        buckets.setdefault(ticker, []).append(candidate)

    deduped: list[dict[str, Any]] = []
    duplicates_removed = 0

    for ticker in sorted(buckets):
        group = buckets[ticker]
        if len(group) > 1:
            duplicates_removed += len(group) - 1

        best = max(group, key=_candidate_rank_key)
        winner = dict(best)
        grouped_prediction_ids = [
            str(item.get('prediction_id') or '').strip()
            for item in group
            if str(item.get('prediction_id') or '').strip()
        ]
        grouped_scores = [
            int(item.get('final_score') or 0)
            for item in group
        ]
        grouped_decisions = [
            str(item.get('decision') or 'NO_DECISION').upper()
            for item in group
        ]

        winner['grouped_prediction_ids'] = grouped_prediction_ids
        winner['grouped_candidate_count'] = len(group)
        winner['grouped_scores'] = grouped_scores
        winner['grouped_decisions'] = grouped_decisions
        if len(group) > 1:
            winner['grouped_evidence_note'] = (
                f'{len(group)} predictions grouped; showing best candidate for {ticker}.'
            )
        deduped.append(winner)

    stats = {
        'raw_candidates': len(candidates),
        'unique_tickers': len(deduped),
        'duplicates_removed': duplicates_removed,
    }
    return deduped, stats


def _dedupe_explained_by_ticker(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Safety pass: ensure user-facing lists never repeat tickers."""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        ticker = _normalize_ticker(item.get('ticker'))
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        unique.append(item)
    return unique


def _pick_explanations(explanations: list[str], prefix: str) -> list[str]:
    token = prefix.strip().upper()
    return [line for line in explanations if str(line).strip().upper().startswith(token)]


def _external_evidence_for_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Attach read-only external stock news summary for watchlist display."""
    attached = candidate.get('external_evidence')
    if isinstance(attached, dict) and attached.get('ok') is True:
        return attached

    ticker = _normalize_ticker(candidate.get('ticker'))
    if not ticker:
        return {
            'ok': False,
            'ticker': None,
            'items': [],
            'counts': {'positive': 0, 'negative': 0, 'watch': 0, 'neutral': 0},
            'score_adjustment': 0,
            'warnings': [],
            'summary_reason': 'missing ticker',
        }

    try:
        from backend.analytics.external_evidence_adapter import get_ticker_external_evidence

        payload = get_ticker_external_evidence(ticker)
        adj = int(candidate.get('external_evidence_adjustment') or 0)
        if adj:
            payload['score_adjustment'] = adj
        return payload
    except Exception:
        return {
            'ok': False,
            'ticker': ticker,
            'items': [],
            'counts': {'positive': 0, 'negative': 0, 'watch': 0, 'neutral': 0},
            'score_adjustment': 0,
            'warnings': ['external_evidence_unavailable'],
            'summary_reason': 'external evidence unavailable',
        }


def explain_watch_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Human-readable evidence breakdown for one scored candidate."""
    explanations = list(candidate.get('explanations') or [])
    warnings = sorted({
        str(item)
        for item in (candidate.get('warnings') or []) + (candidate.get('hard_warnings') or [])
        if str(item).strip()
    })

    memory_lines = _pick_explanations(explanations, 'A:') + _pick_explanations(explanations, 'D:')
    broker_lines = _pick_explanations(explanations, 'B:') + _pick_explanations(explanations, 'C:')
    sim_lines = _pick_explanations(explanations, 'H:')
    ext_lines = _pick_explanations(explanations, 'I:')

    ext_payload = _external_evidence_for_candidate(candidate)
    ext_items = ext_payload.get('items') or []
    ext_titles = [str(item.get('title') or '').strip() for item in ext_items[:3] if item.get('title')]
    ext_counts = ext_payload.get('counts') or {}
    ext_adjustment = int(
        candidate.get('external_evidence_adjustment')
        or ext_payload.get('score_adjustment')
        or 0
    )
    ext_warnings = list(ext_payload.get('warnings') or [])

    hist_sim = candidate.get('historical_simulation') or {}
    sim_summary = {
        'inferred_strategy': hist_sim.get('inferred_strategy'),
        'strategy_win_rate': hist_sim.get('strategy_win_rate'),
        'strategy_expectancy_pct': hist_sim.get('strategy_expectancy_pct'),
        'adjustment': candidate.get('simulation_adjustment', hist_sim.get('confidence_adjustment')),
        'warnings': hist_sim.get('warnings') or [],
        'reasons': hist_sim.get('reasons') or [],
    }

    primary_reason = 'watch candidate'
    decision = str(candidate.get('decision') or '').upper()
    if decision == 'AVOID':
        primary_reason = 'avoid candidate'
    elif decision == 'NO_DECISION':
        primary_reason = 'insufficient evidence'
    elif decision == 'BUY_CANDIDATE':
        primary_reason = 'watch candidate with elevated score (not trade execution)'

    if candidate.get('hard_warnings'):
        primary_reason = 'insufficient evidence — blocking warnings present'
    elif 'insufficient_evidence' in warnings:
        primary_reason = 'insufficient evidence'

    detail_bits: list[str] = []
    if memory_lines:
        detail_bits.append(memory_lines[0].split('=>', 1)[0].strip())
    if broker_lines:
        detail_bits.append(broker_lines[0].split('=>', 1)[0].strip())
    if sim_lines:
        detail_bits.append(sim_lines[0].split('=>', 1)[0].strip())
    if ext_lines:
        detail_bits.append(ext_lines[0].split('=>', 1)[0].strip())

    reason = '; '.join(detail_bits[:3]) if detail_bits else primary_reason

    return {
        'ticker': candidate.get('ticker'),
        'prediction_id': candidate.get('prediction_id'),
        'score': candidate.get('final_score'),
        'pre_calibration_score': candidate.get('pre_calibration_score'),
        'confidence_label': candidate.get('confidence_label'),
        'direction': candidate.get('direction'),
        'signal_type': candidate.get('signal_type'),
        'decision': decision,
        'reason': reason,
        'primary_label': primary_reason,
        'broker_evidence': {
            'summary': broker_lines[0] if broker_lines else 'no broker evidence summary',
            'lines': broker_lines[:4],
        },
        'simulation_evidence': {
            'summary': sim_lines[0] if sim_lines else 'no simulation adjustment',
            'details': sim_summary,
            'lines': sim_lines[:3],
        },
        'memory_evidence': {
            'summary': memory_lines[0] if memory_lines else 'no memory evidence summary',
            'lines': memory_lines[:4],
        },
        'external_evidence_summary': {
            'counts': ext_counts,
            'stock_news_count': sum(int(ext_counts.get(k) or 0) for k in ext_counts),
            'latest_titles': ext_titles,
            'score_adjustment': ext_adjustment,
            'summary_reason': ext_payload.get('summary_reason') or 'no external stock news',
            'warnings': ext_warnings,
            'disclaimer': 'External evidence is read-only and not trade execution.',
        },
        'external_evidence': ext_payload,
        'warnings': warnings,
        'hard_warnings': list(candidate.get('hard_warnings') or []),
        'explanations': explanations[:12],
        'grouped_prediction_ids': list(candidate.get('grouped_prediction_ids') or []),
        'grouped_candidate_count': int(candidate.get('grouped_candidate_count') or 1),
        'grouped_scores': list(candidate.get('grouped_scores') or [candidate.get('final_score')]),
        'grouped_decisions': list(candidate.get('grouped_decisions') or [decision]),
        'grouped_evidence_note': candidate.get('grouped_evidence_note'),
        'shadow_mode': SHADOW_MODE,
    }


def group_by_decision(candidates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Split explained candidates by final decision."""
    grouped: dict[str, list[dict[str, Any]]] = {
        'BUY_CANDIDATE': [],
        'WATCH': [],
        'AVOID': [],
        'NO_DECISION': [],
    }
    for candidate in candidates:
        explained = explain_watch_candidate(candidate)
        token = str(explained.get('decision') or 'NO_DECISION').upper()
        if token not in grouped:
            token = 'NO_DECISION'
        grouped[token].append(explained)
    for bucket in grouped.values():
        bucket.sort(key=lambda item: (-(item.get('score') or 0), str(item.get('ticker') or '')))
    return grouped


def _collect_risk_notes(
    *,
    mode_summary: dict[str, Any],
    grouped: dict[str, list[dict[str, Any]]],
) -> list[str]:
    notes: list[str] = []
    if mode_summary.get('market_closed'):
        notes.append(RISK_NOTE_TOKENS['market_closed'])
    if mode_summary.get('buy_cap_active'):
        notes.append('Active mode caps BUY to WATCH — shadow watchlist only.')

    seen_tokens: set[str] = set()
    for bucket in grouped.values():
        for item in bucket:
            for warning in item.get('warnings') or []:
                key = str(warning).strip()
                if not key or key in seen_tokens:
                    continue
                seen_tokens.add(key)
                if key in RISK_NOTE_TOKENS:
                    notes.append(RISK_NOTE_TOKENS[key])
                elif 'stale' in key.lower():
                    notes.append(f'Source freshness warning: {key.replace("_", " ")}.')
                elif 'conflict' in key.lower():
                    notes.append(f'Broker conflict warning: {key.replace("_", " ")}.')
                elif 'low_sample' in key.lower():
                    notes.append(f'Low sample warning: {key.replace("_", " ")}.')

    if not notes:
        notes.append('Review shadow scores before any manual action — not trade execution.')

    try:
        from backend.analytics.external_evidence_adapter import get_market_context_summary

        context = get_market_context_summary(limit=5)
        if context.get('ok') is True:
            mc = int(context.get('market_context_count') or 0)
            mac = int(context.get('macro_context_count') or 0)
            if mc or mac:
                notes.append(
                    f'External market/macro context: {mc} market + {mac} macro headline(s) (risk notes only).',
                )
            for warning in context.get('warnings') or []:
                token = str(warning).strip()
                if token and token not in seen_tokens:
                    seen_tokens.add(token)
                    notes.append(token)
    except Exception:
        pass

    return notes


def _allows_buy_candidates(mode_summary: dict[str, Any]) -> bool:
    if mode_summary.get('buy_cap_active'):
        return False
    active_mode = str(mode_summary.get('active_mode') or '')
    if active_mode in BUY_CAP_MODES:
        return False
    if mode_summary.get('market_closed'):
        return False
    return True


def generate_tomorrow_watchlist(*, limit: int = 25) -> dict[str, Any]:
    """Build tomorrow watchlist report from final confidence data."""
    confidence = load_final_confidence_report(limit=max(limit, 50))
    if confidence.get('ok') is not True:
        return {
            'ok': False,
            'error': confidence.get('error') or 'final confidence report unavailable',
            'shadow_mode': SHADOW_MODE,
            'disclaimer': DISCLAIMER,
        }

    rows = list(confidence.get('rows') or [])
    deduped_rows, dedupe_stats = dedupe_candidates_by_ticker(rows)
    mode_summary = _market_mode_summary(confidence)
    grouped = group_by_decision(deduped_rows)

    buy_allowed = _allows_buy_candidates(mode_summary)
    buy_candidates = grouped['BUY_CANDIDATE'] if buy_allowed else []

    watch_pool = list(grouped['WATCH'])
    if buy_allowed:
        watch_pool = buy_candidates + watch_pool

    top_watchlist = _dedupe_explained_by_ticker(watch_pool)[: int(limit)]
    avoid_list = _dedupe_explained_by_ticker(grouped['AVOID'])[: int(limit)]
    no_decision_list = _dedupe_explained_by_ticker(grouped['NO_DECISION'])[: int(limit)]

    list_title = 'Tomorrow Watchlist'
    if not buy_allowed:
        list_title = 'Tomorrow Watchlist'

    summary = {
        'watch': len(_dedupe_explained_by_ticker(watch_pool)),
        'avoid': len(_dedupe_explained_by_ticker(grouped['AVOID'])),
        'no_decision': len(_dedupe_explained_by_ticker(grouped['NO_DECISION'])),
        'buy_candidates': len(buy_candidates),
        'checked': len(rows),
        'raw_candidates': dedupe_stats['raw_candidates'],
        'unique_tickers': dedupe_stats['unique_tickers'],
        'duplicates_removed': dedupe_stats['duplicates_removed'],
        'list_title': list_title,
    }

    risk_notes = _collect_risk_notes(mode_summary=mode_summary, grouped=grouped)

    return {
        'ok': True,
        'generated_at': _now_iso(),
        'shadow_mode': SHADOW_MODE,
        'market_mode': mode_summary.get('active_mode'),
        'market_mode_summary': mode_summary,
        'summary': summary,
        'top_watchlist': top_watchlist,
        'avoid': avoid_list,
        'no_decision': no_decision_list,
        'risk_notes': risk_notes,
        'disclaimer': DISCLAIMER,
        'confidence_disclaimer': CONFIDENCE_DISCLAIMER,
        'source_report': str(FINAL_CONFIDENCE_REPORT_PATH.name),
        'dedupe': dedupe_stats,
    }


def get_top_watchlist_dashboard(*, limit: int = 25) -> dict[str, Any]:
    """API/dashboard payload — load cached watchlist or generate fresh."""
    cached = _load_json(TOMORROW_WATCHLIST_PATH)
    if cached and cached.get('ok') is True:
        return {**cached, 'dashboard': True, 'cached': True}

    report = generate_tomorrow_watchlist(limit=limit)
    report['dashboard'] = True
    report['cached'] = False
    return report


def write_tomorrow_watchlist_report(*, limit: int = 25) -> dict[str, Any]:
    """Generate and persist tomorrow watchlist JSON."""
    report = generate_tomorrow_watchlist(limit=limit)
    if report.get('ok') is True:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        TOMORROW_WATCHLIST_PATH.write_text(
            json.dumps(report, indent=2, default=str, ensure_ascii=False),
            encoding='utf-8',
        )
    report['output_path'] = str(TOMORROW_WATCHLIST_PATH)
    return report
