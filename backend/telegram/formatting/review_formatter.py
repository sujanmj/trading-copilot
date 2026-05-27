"""
Institutional /review formatter — cache-only, 3 grouped messages.

Reads committed MarketSnapshot fields only; never triggers pipelines or AI.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from backend.runtime.market_snapshot import MarketSnapshot


def _rs(snap: MarketSnapshot) -> dict:
    return snap.runtime_state if isinstance(snap.runtime_state, dict) else {}


def _tier_bucket(opportunities: List[dict]) -> Dict[str, List[dict]]:
    elite: List[dict] = []
    watch: List[dict] = []
    avoid: List[dict] = []
    for item in opportunities or []:
        if not isinstance(item, dict):
            continue
        tier = str(item.get('display_tier') or item.get('tier') or '').upper()
        action = str(item.get('action') or '').upper()
        if tier == 'ELITE' or 'HIGH CONVICTION' in tier or action == 'BUY':
            elite.append(item)
        elif tier == 'AVOID' or action in ('AVOID', 'SELL'):
            avoid.append(item)
        else:
            watch.append(item)
    return {'elite': elite, 'watch': watch, 'avoid': avoid}


def _format_market_intelligence(snap: MarketSnapshot) -> str:
    from backend.intelligence.institutional_language import (
        apply_institutional_tone,
        canonical_session_prefix,
        institutional_regime_label,
    )
    from backend.metrics.format_helpers import safe_pct

    rs = _rs(snap)
    fresh = snap.freshness or rs.get('snapshot_freshness') or {}
    lc = snap.lifecycle or rs.get('lifecycle') or {}
    mood = snap.market_mood if isinstance(snap.market_mood, dict) else {}
    govt = {}
    intel = snap.intelligence if isinstance(snap.intelligence, dict) else {}
    govt = intel.get('government_impact') if isinstance(intel.get('government_impact'), dict) else {}

    regime_raw = (snap.regime or {}).get('regime') or (snap.regime or {}).get('label')
    regime = institutional_regime_label(str(regime_raw or 'volatile'))

    age = fresh.get('age_display') or 'freshness unavailable'
    tier = fresh.get('health_tier') or ('stale' if fresh.get('stale') else 'healthy')
    primary = rs.get('primary_state') or '—'

    rotation = snap.sector_rotation if isinstance(snap.sector_rotation, dict) else {}
    bullish = rotation.get('bullish') or []
    bearish = rotation.get('bearish') or []
    leaders = ', '.join(str(s) for s in bullish[:5]) or 'No clear leadership cluster'

    summary = apply_institutional_tone(str(snap.executive_summary or intel.get('executive_summary') or ''))
    if len(summary) > 520:
        summary = summary[:500].rsplit(' ', 1)[0] + '…'

    govt_summary = apply_institutional_tone(str(govt.get('summary') or 'No government impact data'))
    govt_conf = govt.get('confidence_score') or govt.get('confidence') or 'N/A'

    quality = (snap.quality_score or rs.get('quality_score') or {})
    q_score = quality.get('quality_score') if isinstance(quality, dict) else quality

    conf = snap.confidence
    if conf is None and isinstance(mood, dict):
        conf = mood.get('confidence_level') or mood.get('confidence')

    warnings = list(snap.warnings or [])[:4]
    blockers = list(snap.blockers or [])[:3]
    warn_line = ''
    if warnings or blockers or fresh.get('stale') or fresh.get('degraded'):
        parts = []
        if fresh.get('stale'):
            parts.append('snapshot stale')
        if fresh.get('degraded'):
            parts.append('degraded')
        parts.extend(blockers[:2])
        parts.extend(warnings[:2])
        warn_line = f"\n<b>Warnings</b>: {', '.join(dict.fromkeys(parts))}"

    prefix = canonical_session_prefix(rs)

    lines = [
        prefix.rstrip(),
        '<b>📋 INSTITUTIONAL REVIEW</b> · Market intelligence',
        f"State: <code>{primary}</code> · Lifecycle: <code>{lc.get('lifecycle_state') or '—'}</code>",
        f"Snapshot: {age} ({tier}) · Regime: {regime}",
        f"Conviction: {apply_institutional_tone(str(conf or 'Monitoring'))} · "
        f"Quality: {q_score if q_score is not None else '—'}",
        '',
        '<b>Market mood</b>',
        f"Global: {apply_institutional_tone(str(snap.global_mood or mood.get('global_mood') or '—'))}",
        f"India: {apply_institutional_tone(str(snap.india_bias or mood.get('india_outlook') or '—'))}",
        f"Retail: {apply_institutional_tone(str(snap.retail_sentiment or mood.get('retail_mood') or '—'))}",
        f"AI confidence: {apply_institutional_tone(str(conf or 'Awaiting evaluation sample'))}",
        '',
        f"<b>Leadership sectors</b>: {apply_institutional_tone(leaders)}",
        f"<b>Macro</b>: {summary or '<i>Awaiting next desk note.</i>'}",
        f"<b>Govt impact</b>: {govt_summary} "
        f"(confidence: {govt_conf})",
        f"<b>Volatility</b>: {regime}",
        warn_line,
    ]
    return '\n'.join(ln for ln in lines if ln is not None)


def _format_opportunities_risks(snap: MarketSnapshot) -> str:
    from backend.intelligence.institutional_language import apply_institutional_tone
    from backend.telegram.formatting.telegram_formatter import (
        format_opportunity,
        format_opps_tiered,
        format_risks,
    )

    opps = list(snap.top_opportunities or [])
    risks = list(snap.risk_list or [])
    intel = snap.intelligence if isinstance(snap.intelligence, dict) else {}
    if not opps and intel.get('top_opportunities'):
        opps = list(intel.get('top_opportunities') or [])
    if not risks and intel.get('risks_and_avoids'):
        risks = list(intel.get('risks_and_avoids') or [])

    buckets = _tier_bucket(opps)
    tier_text = format_opps_tiered(buckets, include_elite=True)
    if not tier_text.strip():
        tier_text = '<i>No ranked setups in cache — capital preservation posture.</i>'

    rotation = snap.sector_rotation if isinstance(snap.sector_rotation, dict) else {}
    bearish = rotation.get('bearish') or []
    weakness = ', '.join(str(s) for s in bearish[:6]) or 'None flagged'

    rs = _rs(snap)
    scanner = rs.get('scanner_health') or {}
    scanner_note = apply_institutional_tone(str(scanner.get('display') or 'Scanner status unavailable'))

    risk_block = format_risks(risks, max_lines_per_ticker=2)
    avoid_items = buckets.get('avoid') or []
    avoid_extra = ''
    if avoid_items:
        avoid_extra = '\n<b>Avoid concentration</b>\n' + '\n'.join(
            format_opportunity(o) for o in avoid_items[:4]
        )

    return (
        '<b>📋 INSTITUTIONAL REVIEW</b> · Opportunities & risks\n\n'
        f"{tier_text}\n\n"
        f"<b>Risk list</b>\n{risk_block}\n"
        f"{avoid_extra}\n"
        f"<b>Sector weakness</b>: {weakness}\n"
        f"<b>Scanner posture</b>: {scanner_note}"
    )


def _format_system_calibration(snap: MarketSnapshot) -> str:
    from backend.metrics.format_helpers import safe_pct

    rs = _rs(snap)
    lc = rs.get('lifecycle') or snap.lifecycle or {}
    sched = rs.get('scheduler') or {}
    scanner = rs.get('scanner_health') or {}
    ai = rs.get('provider_health') or rs.get('ai_state') or {}
    alert = rs.get('alert_eligibility') or {}
    tg = rs.get('telegram_metrics') or {}
    pipeline = rs.get('pipeline') or snap.pipeline_health or {}
    metrics = snap.metrics if isinstance(snap.metrics, dict) else rs.get('metrics') or {}
    sections = metrics.get('sections') or {}
    live = sections.get('live_session') or {}
    hist = sections.get('historical_calibration') or {}
    archived = sections.get('archived') or {}

    wr_disp = hist.get('win_rate_display') or safe_pct(hist.get('win_rate'))
    if wr_disp in ('—', '—%', None, ''):
        wr_disp = 'Awaiting statistical confidence'

    blockers = list(snap.blockers or []) + list(alert.get('block_reasons') or [])
    blockers = list(dict.fromkeys(str(b) for b in blockers if b))[:6]

    stalled = pipeline.get('stalled_stages') or []
    stall_txt = ', '.join(stalled[:4]) if stalled else 'none'

    cal_text = snap.calibration or (snap.intelligence or {}).get('self_calibration') if isinstance(
        snap.intelligence, dict
    ) else snap.calibration
    cal_line = str(cal_text or hist.get('calibration_confidence') or 'Calibration building from historical sample.')
    if len(cal_line) > 280:
        cal_line = cal_line[:260].rsplit(' ', 1)[0] + '…'

    alert_state = 'eligible' if alert.get('eligible') else 'blocked'
    suppress = alert.get('suppression_count') or tg.get('suppressed_today') or 0

    return (
        '<b>📋 INSTITUTIONAL REVIEW</b> · System & calibration\n\n'
        f"<b>Lifecycle</b>: {lc.get('lifecycle_display') or lc.get('lifecycle_state') or '—'}\n"
        f"<b>Scheduler</b>: {sched.get('phase') or '—'}\n"
        f"<b>Scanner</b>: {scanner.get('display') or '—'}\n"
        f"<b>AI providers</b>: {ai.get('status') or ai.get('state') or 'unknown'}\n"
        f"<b>Pipeline stalled</b>: {stall_txt}\n"
        f"<b>Blockers</b>: {', '.join(blockers) if blockers else 'none'}\n\n"
        f"<b>LIVE SESSION</b>\n"
        f"Active: {live.get('active_predictions', live.get('pending', metrics.get('pending', 0)))} · "
        f"Resolved today: {live.get('resolved_today', 0)}\n\n"
        f"<b>HISTORICAL CALIBRATION</b>\n"
        f"Sample: {hist.get('evaluated_sample', metrics.get('evaluated', 0))} · "
        f"{hist.get('wins', metrics.get('wins', 0))}W/"
        f"{hist.get('losses', metrics.get('losses', 0))}L · WR {wr_disp}\n"
        f"Pending: {live.get('pending', metrics.get('pending', 0))}\n"
        f"<i>{cal_line}</i>\n\n"
        f"<b>ARCHIVED</b>\n"
        f"Expired: {archived.get('expired', metrics.get('expired', 0))} · "
        f"Neutralized: {archived.get('neutralized', metrics.get('neutralized', 0))}\n\n"
        f"<b>Alerts</b>: {alert_state} · suppressions {suppress}"
    )


def render_review_messages(snap: MarketSnapshot) -> List[Tuple[str, str]]:
    """Return exactly 3 grouped review messages (safe — never raises)."""
    builders = (
        ('Market intelligence', _format_market_intelligence),
        ('Opportunities & risks', _format_opportunities_risks),
        ('System & calibration', _format_system_calibration),
    )
    out: List[Tuple[str, str]] = []
    for label, fn in builders:
        try:
            text = fn(snap)
            out.append((label, text or f'<i>{label} unavailable in cache.</i>'))
        except Exception as exc:
            out.append((label, f'⚠ {label} unavailable ({str(exc)[:80]})'))
    return out[:3]
