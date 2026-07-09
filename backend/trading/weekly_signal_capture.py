"""
Weekly signal capture hooks — AstraEdge 52K patch.

Lightweight append-only weekly signal events from existing command flows.
No LLM. No external APIs.
"""

from __future__ import annotations

from typing import Any


def _safe_capture(**kwargs: Any) -> None:
    try:
        from backend.trading.weekly_conviction_engine import capture_weekly_signal_event

        capture_weekly_signal_event(**kwargs)
    except Exception:
        pass


def _score_strength(score: int) -> str:
    if score >= 75:
        return 'strong'
    if score >= 50:
        return 'medium'
    return 'weak'


def capture_longterm_pick_signals(
    rows: list[dict[str, Any]],
    snapshots: list[dict[str, Any]] | None = None,
) -> None:
    snap_by_sym = {
        str(s.get('symbol') or '').upper(): s for s in (snapshots or [])
    }
    for row in rows:
        sym = str(row.get('symbol') or row.get('symbol_key') or '').upper()
        if not sym or len(sym) < 2:
            continue
        snap = snap_by_sym.get(sym) or row
        score = int(snap.get('confidence_score') or row.get('longterm_score') or 0)
        if score <= 0:
            continue
        tags: list[str] = []
        for key, label in (('roe', 'ROE'), ('roce', 'ROCE'), ('debt_to_equity', 'debt')):
            val = snap.get(key) or row.get(key)
            if val not in (None, '', '—'):
                tags.append(f'{label} {val}')
        rank = int(row.get('rank') or snap.get('rank') or 0)
        reason = f'/longterm rank {rank}, confidence {score}' if rank else f'/longterm confidence {score}'
        _safe_capture(
            symbol=sym,
            company_name=str(row.get('company_name') or row.get('display_name') or sym),
            source_type='LONGTERM',
            source_command_or_module='/longterm',
            signal_score=score,
            signal_direction='positive',
            signal_strength=_score_strength(score),
            reason=reason,
            reason_tags=tags[:6],
            raw_ref_id=str(snap.get('snapshot_id') or ''),
        )


def capture_screener_import_signals(stocks: list[dict[str, Any]], *, limit: int = 15) -> None:
    ranked = sorted(stocks, key=lambda r: int(r.get('longterm_score') or 0), reverse=True)
    for row in ranked[:limit]:
        score = int(row.get('longterm_score') or 0)
        if score < 50:
            continue
        sym = str(row.get('symbol') or row.get('symbol_key') or '').upper()
        if not sym or len(sym) < 2:
            continue
        _safe_capture(
            symbol=sym,
            company_name=str(row.get('company_name') or row.get('display_name') or sym),
            source_type='SCREENER',
            source_command_or_module='screener_import',
            signal_score=score,
            signal_direction='positive' if score >= 60 else 'neutral',
            signal_strength=_score_strength(score),
            reason=f'Screener import longterm_score {score}',
            reason_tags=list(row.get('reasons') or [])[:4],
            risk_tags=list(row.get('risk_flags') or [])[:3],
            raw_ref_id=str(row.get('import_id') or ''),
        )


def capture_tradecard_signals(candidates: list[dict[str, Any]]) -> None:
    for row in candidates:
        score = int(row.get('score') or 0)
        if score < 60:
            continue
        sym = str(row.get('ticker') or row.get('symbol') or '').upper()
        if not sym:
            continue
        why = ' + '.join(row.get('why') or row.get('reasons') or [])[:120]
        _safe_capture(
            symbol=sym,
            company_name=str(row.get('company') or row.get('name') or sym),
            source_type='TRADECARD',
            source_command_or_module='/tradecards',
            signal_score=score,
            signal_direction='positive',
            signal_strength=_score_strength(score),
            reason=f'tradecard score {score}' + (f' — {why}' if why else ''),
            reason_tags=[str(w) for w in (row.get('why') or row.get('reasons') or [])[:4]],
        )


def capture_outcome_learning_signal(outcome_rec: dict[str, Any]) -> None:
    from backend.trading.candidate_outcome_learning import (
        OUTCOME_LOSS,
        OUTCOME_NEUTRAL,
        OUTCOME_PENDING,
        OUTCOME_WIN,
    )

    sym = str(outcome_rec.get('symbol') or '').upper()
    if not sym:
        return
    outcome = str(outcome_rec.get('outcome') or OUTCOME_PENDING)
    if outcome == OUTCOME_WIN:
        direction, score = 'positive', 80
    elif outcome == OUTCOME_LOSS:
        direction, score = 'negative', 75
    elif outcome == OUTCOME_NEUTRAL:
        direction, score = 'neutral', 45
    else:
        direction, score = 'neutral', 40
    _safe_capture(
        symbol=sym,
        company_name=sym,
        source_type='OUTCOME_LEARNING',
        source_command_or_module='outcome_resolver',
        signal_score=score,
        signal_direction=direction,
        signal_strength=_score_strength(score),
        reason=f'candidate outcome {outcome}',
        reason_tags=list(outcome_rec.get('reason_tags') or [])[:6],
        raw_ref_id=str(outcome_rec.get('outcome_id') or outcome_rec.get('snapshot_id') or ''),
    )


def capture_my_feed_signal(
    *,
    symbol: str,
    company_name: str = '',
    verification_status: str,
    feed_id: str = '',
    reason: str = '',
) -> None:
    status = str(verification_status or '').upper()
    if status in ('REMOVED', 'DELETED', 'UNVERIFIED', 'FAILED'):
        return
    if status in ('VERIFIED', 'CONFIRMED'):
        score, direction, strength = 78, 'positive', 'strong'
    elif status in ('PARTIAL', 'PARTIALLY_VERIFIED', 'PARTIAL_MATCH'):
        score, direction, strength = 58, 'positive', 'medium'
    else:
        return
    sym = str(symbol or '').upper()
    if not sym:
        return
    _safe_capture(
        symbol=sym,
        company_name=company_name or sym,
        source_type='MY_FEED',
        source_command_or_module='/feed verify',
        signal_score=score,
        signal_direction=direction,
        signal_strength=strength,
        reason=reason or f'feed verification {status.lower()}',
        raw_ref_id=feed_id,
    )


def capture_news_signal(
    *,
    symbol: str,
    company_name: str = '',
    refresh_ok: bool = True,
    item_count: int = 0,
) -> None:
    sym = str(symbol or '').upper()
    if not sym or not refresh_ok:
        return
    score = min(85, 45 + min(item_count, 8) * 5)
    _safe_capture(
        symbol=sym,
        company_name=company_name or sym,
        source_type='NEWS',
        source_command_or_module='/news refresh',
        signal_score=score,
        signal_direction='positive' if item_count > 0 else 'neutral',
        signal_strength=_score_strength(score),
        reason=f'news refresh mapped to {sym}, items={item_count}',
    )


def capture_macro_market_signal(active: dict[str, Any] | None) -> None:
    if not active:
        return
    severity = str(active.get('severity') or '').upper()
    regime = str(active.get('regime') or '').upper()
    if severity == 'HIGH' or regime in ('RED', 'RISK_OFF'):
        score, direction, strength = 85, 'negative', 'strong'
    elif severity == 'MEDIUM':
        score, direction, strength = 60, 'negative', 'medium'
    else:
        score, direction, strength = 35, 'neutral', 'weak'
    headline = str(active.get('headline') or active.get('trigger') or 'macro shock')[:120]
    _safe_capture(
        symbol='MARKET',
        company_name='Market',
        source_type='MACRO',
        source_command_or_module='/macro',
        signal_score=score,
        signal_direction=direction,
        signal_strength=strength,
        reason=headline,
        risk_tags=[regime] if regime else [],
    )


def capture_catalyst_signal(symbol: str, row: dict[str, Any] | None) -> None:
    if not row:
        return
    sym = str(symbol or row.get('ticker') or '').upper()
    if not sym:
        return
    raw = float(row.get('score') or 0)
    score = max(0, min(100, int(round(raw / 25.0 * 100))))
    if score <= 0:
        return
    side = str(row.get('side') or '').upper()
    if side in ('BEARISH', 'RISK'):
        direction = 'negative'
    elif side == 'BULLISH' or score >= 50:
        direction = 'positive'
    else:
        direction = 'neutral'
    _safe_capture(
        symbol=sym,
        company_name=str(row.get('company') or row.get('name') or sym),
        source_type='CATALYST',
        source_command_or_module='/catalysts',
        signal_score=score,
        signal_direction=direction,
        signal_strength=_score_strength(score),
        reason=str(row.get('headline') or row.get('catalyst_type') or 'catalyst radar')[:120],
        reason_tags=[str(row.get('catalyst_type') or '')] if row.get('catalyst_type') else [],
    )


def capture_pattern_signal(symbol: str, pattern: dict[str, Any] | None, *, source: str = '/pattern') -> None:
    if not pattern:
        return
    sym = str(symbol or '').upper()
    if not sym:
        return
    conf = int(pattern.get('confidence') or pattern.get('pattern_confidence') or 0)
    label = str(pattern.get('pattern') or pattern.get('label') or pattern.get('chart_pattern') or '')
    if not label and conf <= 0:
        return
    score = max(conf, 55) if label else conf
    if score <= 0:
        return
    _safe_capture(
        symbol=sym,
        company_name=sym,
        source_type='PATTERN',
        source_command_or_module=source,
        signal_score=min(100, score),
        signal_direction='positive',
        signal_strength=_score_strength(score),
        reason=f'pattern {label}' if label else 'pattern detected',
        reason_tags=[label] if label else [],
    )


def capture_candle_signal(symbol: str, readiness: dict[str, Any] | None) -> None:
    if not readiness:
        return
    sym = str(symbol or '').upper()
    if not sym:
        return
    if not readiness.get('pattern_ready') and not readiness.get('candle_ready'):
        return
    derived = int(readiness.get('derived_count') or 0)
    score = min(100, 40 + derived * 4)
    _safe_capture(
        symbol=sym,
        company_name=sym,
        source_type='CANDLE',
        source_command_or_module='/candles',
        signal_score=score,
        signal_direction='positive' if readiness.get('pattern_ready') else 'neutral',
        signal_strength=_score_strength(score),
        reason=f'candle readiness snapshots={readiness.get("snapshot_count")} derived={derived}',
    )


def capture_catalyst_radar_batch(radar: dict[str, Any], *, limit: int = 12) -> None:
    rows = list(radar.get('priority_list') or []) + list(radar.get('items') or [])
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get('ticker') or '').upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        capture_catalyst_signal(sym, row)
        if len(seen) >= limit:
            break
