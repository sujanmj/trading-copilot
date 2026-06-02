"""
Institutional /review formatter — cache-only MASTER DESK REVIEW (3 messages).

Read-only aggregation from committed MarketSnapshot + export files.
Never triggers pipelines, scanner, synthesis, or AI providers.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from backend.runtime.market_snapshot import MarketSnapshot
from backend.utils.config import DATA_DIR

REVIEW_HEADER = (
    '<b>📋 MASTER DESK REVIEW</b>\n'
    '<i>Cache-only institutional intelligence snapshot</i>'
)
MAX_MSG_CHARS = 3800


def _rs(snap: MarketSnapshot) -> dict:
    return snap.runtime_state if isinstance(snap.runtime_state, dict) else {}


def _intel(snap: MarketSnapshot) -> dict:
    return snap.intelligence if isinstance(snap.intelligence, dict) else {}


def _tone(text: Any, fallback: str = '—') -> str:
    from backend.intelligence.institutional_language import apply_institutional_tone
    raw = str(text or '').strip()
    if not raw or raw.lower() in ('none', 'null', 'unknown', 'n/a'):
        return fallback
    return apply_institutional_tone(raw)


def _truncate(text: str, max_chars: int = 480) -> str:
    t = (text or '').strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1].rsplit(' ', 1)[0] + '…'


def _cap_message(text: str, max_chars: int = MAX_MSG_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20].rsplit('\n', 1)[0] + '\n… (truncated)'


def _section_header(title: str) -> str:
    return f'\n<b>{title}</b>'


def _load_json_cache(name: str) -> dict:
    path = DATA_DIR / name
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(raw, dict) and 'data' in raw and isinstance(raw['data'], dict):
            return raw['data']
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _enrich_review_context(snap: MarketSnapshot) -> dict:
    """Read-only cache enrichment — no pipelines."""
    ctx: Dict[str, Any] = {
        'stats_export': _load_json_cache('stats_data.json'),
        'scanner_export': _load_json_cache('scanner_data.json'),
        'active_payload': {},
        'active_list': [],
    }
    try:
        from backend.lifecycle.prediction_lifecycle_engine import get_active_predictions_payload
        payload = get_active_predictions_payload()
        if isinstance(payload, dict):
            ctx['active_payload'] = payload
            preds = payload.get('predictions') or []
            ctx['active_list'] = preds if isinstance(preds, list) else []
    except Exception:
        pass
    return ctx


def _metrics_sections(snap: MarketSnapshot, ctx: dict) -> dict:
    rs = _rs(snap)
    metrics = snap.metrics if isinstance(snap.metrics, dict) else {}
    if not metrics.get('sections') and isinstance(rs.get('metrics'), dict):
        metrics = rs['metrics']
    if not metrics.get('sections'):
        export = ctx.get('stats_export') or {}
        if export.get('metric_sections'):
            metrics = {'sections': export['metric_sections'], **export}
        elif export.get('metrics_all_time'):
            try:
                from backend.metrics.canonical_metrics import build_metric_sections
                metrics = {
                    'sections': build_metric_sections(
                        all_time=export.get('metrics_all_time') or {},
                        daily=export.get('metrics_daily') or {},
                        pending_classification=export.get('pending_classification'),
                        calibration=export.get('lifecycle_calibration') or export.get('calibration'),
                    )
                }
            except Exception:
                pass
    return metrics.get('sections') or {}


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


def _format_overnight(snap: MarketSnapshot) -> str:
    rs = _rs(snap)
    intel = _intel(snap)
    overnight = rs.get('overnight_posture') or intel.get('overnight_impact') or {}
    if not isinstance(overnight, dict):
        return 'Overnight scan unavailable in cache.'
    parts = []
    for key in ('summary', 'headline', 'us_close', 'asia_open', 'india_bias', 'impact'):
        val = overnight.get(key)
        if val:
            parts.append(f"{key.replace('_', ' ').title()}: {_truncate(str(val), 120)}")
    india = overnight.get('india_next_open') or {}
    if isinstance(india, dict) and india.get('summary'):
        parts.append(f"India open: {_truncate(str(india.get('summary')), 140)}")
    return ' · '.join(parts[:4]) if parts else 'No overnight macro shift flagged in cache.'


def _format_market_intelligence(snap: MarketSnapshot, ctx: dict) -> str:
    from backend.intelligence.institutional_language import (
        canonical_session_prefix,
        institutional_regime_label,
    )

    rs = _rs(snap)
    intel = _intel(snap)
    fresh = snap.freshness or rs.get('snapshot_freshness') or {}
    lc = snap.lifecycle or rs.get('lifecycle') or {}
    mood = snap.market_mood if isinstance(snap.market_mood, dict) else {}
    govt = intel.get('government_impact') if isinstance(intel.get('government_impact'), dict) else {}

    regime_raw = (snap.regime or {}).get('regime') or (snap.regime or {}).get('label')
    regime = institutional_regime_label(str(regime_raw or 'volatile'))

    age = fresh.get('age_display') or 'freshness unavailable'
    tier = fresh.get('health_tier') or ('stale' if fresh.get('stale') else 'healthy')
    primary = rs.get('primary_state') or '—'
    lc_state = lc.get('lifecycle_state') or lc.get('lifecycle_display') or '—'

    quality = snap.quality_score or rs.get('quality_score') or {}
    q_score = quality.get('quality_score') if isinstance(quality, dict) else quality

    conf = snap.confidence
    if conf is None and isinstance(mood, dict):
        conf = mood.get('confidence_level') or mood.get('confidence')

    summary = _tone(snap.executive_summary or intel.get('executive_summary') or intel.get('analysis'), '')
    summary = _truncate(summary, 520) if summary != '—' else 'Awaiting next desk note.'

    govt_summary = _tone(govt.get('summary'), 'No government impact data')
    govt_conf = govt.get('confidence_score') or govt.get('confidence') or 'N/A'

    rotation = snap.sector_rotation if isinstance(snap.sector_rotation, dict) else {}
    try:
        from backend.telegram.formatting.telegram_formatter import format_sectors
        sector_block = format_sectors(rotation)
    except Exception:
        bullish = ', '.join(str(s) for s in (rotation.get('bullish') or [])[:6]) or 'None'
        bearish = ', '.join(str(s) for s in (rotation.get('bearish') or [])[:6]) or 'None'
        sector_block = f'Bullish: {bullish}\nBearish: {bearish}'

    secondary = rs.get('secondary_flags') or {}
    flag_parts = [k for k, v in secondary.items() if v][:4]
    stale_note = ''
    if fresh.get('stale') or fresh.get('degraded') or flag_parts:
        bits = []
        if fresh.get('stale'):
            bits.append('snapshot stale')
        if fresh.get('degraded'):
            bits.append('degraded')
        bits.extend(flag_parts[:3])
        stale_note = f"\n<b>State flags</b>: {', '.join(dict.fromkeys(bits))}"

    prefix = canonical_session_prefix(rs).rstrip()
    overnight_line = _format_overnight(snap)

    lines = [
        prefix,
        REVIEW_HEADER,
        f"<b>Message 1/3</b> · Market + macro intelligence",
        '',
        f"<b>Runtime</b>: <code>{primary}</code> · Lifecycle: <code>{lc_state}</code>",
        f"<b>Snapshot</b>: {age} ({tier}) · <b>Regime</b>: {regime}",
        f"<b>AI confidence</b>: {_tone(conf, 'Monitoring')} · <b>Quality</b>: {q_score if q_score is not None else '—'}",
        '',
        '<b>Market mood</b>',
        f"Global: {_tone(snap.global_mood or mood.get('global_mood'))}",
        f"India: {_tone(snap.india_bias or mood.get('india_outlook'))}",
        f"Retail: {_tone(snap.retail_sentiment or mood.get('retail_mood'))}",
        '',
        f"<b>Macro summary</b>\n{summary}",
        f"<b>Government impact</b>\n{govt_summary} (confidence: {govt_conf})",
        sector_block,
        f"<b>Volatility posture</b>: {regime}",
        f"<b>Overnight / global</b>\n{overnight_line}",
        stale_note,
    ]
    return _cap_message('\n'.join(ln for ln in lines if ln is not None))


def _format_positioning_opportunities(snap: MarketSnapshot, ctx: dict) -> str:
    from backend.telegram.formatting.telegram_formatter import (
        format_action_plan,
        format_opportunity,
        format_opps_tiered,
        format_risks,
    )

    intel = _intel(snap)
    opps = list(snap.top_opportunities or intel.get('top_opportunities') or [])
    risks = list(snap.risk_list or intel.get('risks_and_avoids') or intel.get('risks') or [])
    buckets = _tier_bucket(opps)

    tier_text = format_opps_tiered(buckets, include_elite=True)
    if not tier_text.strip():
        tier_text = '<i>Capital preservation mode — no ranked setups in cache.</i>'

    action_raw = snap.action_plan or intel.get('action_plan') or ''
    posture = format_action_plan(str(action_raw), max_lines=4)

    risk_block = format_risks(risks, max_lines_per_ticker=2)

    rotation = snap.sector_rotation if isinstance(snap.sector_rotation, dict) else {}
    weakness = ', '.join(str(s) for s in (rotation.get('bearish') or [])[:8]) or 'None flagged'

    rs = _rs(snap)
    scanner = rs.get('scanner_health') or {}
    scanner_export = ctx.get('scanner_export') or {}
    scanner_summary = scanner.get('display') or scanner_export.get('summary') or 'Unavailable'
    anomalies: List[str] = []
    for sig in (scanner_export.get('top_signals') or scanner_export.get('ultra_signals') or [])[:4]:
        if isinstance(sig, dict):
            anomalies.append(
                f"{sig.get('ticker') or sig.get('symbol') or '?'} "
                f"({sig.get('direction') or sig.get('strength') or 'signal'})"
            )
    anomaly_line = ', '.join(anomalies) if anomalies else 'No scanner anomalies flagged'

    avoid_items = buckets.get('avoid') or []
    avoid_extra = ''
    if avoid_items:
        avoid_extra = '\n<b>Risk concentration (avoid tier)</b>\n' + '\n'.join(
            format_opportunity(o) for o in avoid_items[:4]
        )

    elite_n = len(buckets.get('elite') or [])
    watch_n = len(buckets.get('watch') or [])
    preserve = 'Active' if elite_n == 0 else 'Selective deployment'
    tactical = _tone(intel.get('tactical_posture') or posture.split('\n')[0] if posture else '', preserve)

    lines = [
        REVIEW_HEADER,
        '<b>Message 2/3</b> · Positioning + opportunities',
        '',
        tier_text,
        '',
        f"<b>Tactical posture</b>: {tactical}",
        posture,
        '',
        f"<b>Opportunity set</b>: {len(opps)} cached · Elite {elite_n} · Watch {watch_n}",
        '',
        '<b>Avoid list</b>',
        risk_block,
        avoid_extra,
        '',
        f"<b>Sector weakness</b>: {weakness}",
        f"<b>Scanner health</b>: {_tone(scanner_summary)}",
        f"<b>Scanner anomalies</b>: {anomaly_line}",
        f"<b>Capital preservation</b>: {preserve}",
        f"<b>Execution posture</b>: {_truncate(str(action_raw).replace(chr(10), ' · '), 360) or 'Monitor — no aggressive deployment.'}",
    ]
    return _cap_message('\n'.join(ln for ln in lines if ln is not None))


def _format_active_predictions_block(ctx: dict) -> str:
    payload = ctx.get('active_payload') or {}
    active = ctx.get('active_list') or []
    count = payload.get('count') or len(active)
    if not active:
        return f"Active predictions: {count} · none listed in cache"
    rows = []
    for p in active[:6]:
        if not isinstance(p, dict):
            continue
        sym = p.get('symbol') or p.get('ticker') or '?'
        state = p.get('state') or p.get('status') or 'ACTIVE'
        cat = p.get('category') or 'opportunity'
        rows.append(f"• <b>{sym}</b> · {state} · {cat}")
    body = '\n'.join(rows) if rows else 'None detailed'
    return f"Active predictions: {count}\n{body}"


def _format_system_calibration(snap: MarketSnapshot, ctx: dict) -> str:
    from backend.metrics.format_helpers import safe_pct

    rs = _rs(snap)
    intel = _intel(snap)
    sections = _metrics_sections(snap, ctx)
    live = sections.get('live_session') or {}
    hist = sections.get('historical_calibration') or {}
    archived = sections.get('archived') or {}

    lc = snap.lifecycle or rs.get('lifecycle') or {}
    sched = rs.get('scheduler') or {}
    scanner = rs.get('scanner_health') or {}
    ai = rs.get('provider_health') or rs.get('ai_state') or {}
    alert = rs.get('alert_eligibility') or {}
    tg = rs.get('telegram_metrics') or {}
    pipeline = rs.get('pipeline') or snap.pipeline_health or {}
    fresh = snap.freshness or rs.get('snapshot_freshness') or {}
    secondary = rs.get('secondary_flags') or {}

    wr_disp = hist.get('win_rate_display') or safe_pct(hist.get('win_rate'))
    if wr_disp in ('—', '—%', None, ''):
        wr_disp = 'Awaiting statistical confidence'

    blockers = list(snap.blockers or []) + list(alert.get('block_reasons') or [])
    blockers = list(dict.fromkeys(str(b) for b in blockers if b))[:8]

    stalled = pipeline.get('stalled_stages') or []
    stall_txt = ', '.join(stalled[:4]) if stalled else 'none'

    cal_text = snap.calibration or intel.get('self_calibration')
    cal_line = _truncate(
        str(cal_text or hist.get('calibration_confidence') or 'Calibration building from historical sample.'),
        300,
    )

    alert_state = 'eligible' if alert.get('eligible') else 'blocked'
    suppress = alert.get('suppression_count') or tg.get('suppressed_today') or 0
    sent_today = tg.get('alerts_sent_today') or 0

    flags = [k for k, v in secondary.items() if v]
    health_flags = ', '.join(flags[:5]) if flags else 'none'
    stale_line = 'stale' if fresh.get('stale') else ('degraded' if fresh.get('degraded') else 'nominal')

    metrics = snap.metrics if isinstance(snap.metrics, dict) else rs.get('metrics') or {}
    pending = live.get('pending', metrics.get('pending', 0))
    resolved_today = live.get('resolved_today', 0)
    wins_today = live.get('wins_today', 0)
    losses_today = live.get('losses_today', 0)

    active_block = _format_active_predictions_block(ctx)

    lines = [
        REVIEW_HEADER,
        '<b>Message 3/3</b> · System + calibration + lifecycle',
        '',
        '<b>Runtime health</b>',
        f"Lifecycle: {lc.get('lifecycle_display') or lc.get('lifecycle_state') or '—'}",
        f"Scheduler: {sched.get('phase') or sched.get('display') or '—'}",
        f"Scanner: {scanner.get('display') or '—'}",
        f"Pipeline stalled: {stall_txt}",
        f"AI providers: {ai.get('status') or ai.get('state') or 'unknown'}",
        f"Freshness: {stale_line} · flags: {health_flags}",
        f"Blockers: {', '.join(blockers) if blockers else 'none'}",
        '',
        '<b>Active book</b>',
        active_block,
        '',
        '<b>Live session</b>',
        f"Pending: {pending} · Resolved today: {resolved_today}",
        f"Today outcomes: {wins_today}W / {losses_today}L",
        '',
        '<b>Historical calibration</b>',
        f"Sample: {hist.get('evaluated_sample', metrics.get('evaluated', 0))} · "
        f"{hist.get('wins', metrics.get('wins', 0))}W / "
        f"{hist.get('losses', metrics.get('losses', 0))}L · WR {wr_disp}",
        f"<i>{cal_line}</i>",
        '',
        '<b>Archived</b>',
        f"Expired: {archived.get('expired', metrics.get('expired', 0))} · "
        f"Neutralized: {archived.get('neutralized', metrics.get('neutralized', 0))} · "
        f"Partials: {metrics.get('partials', hist.get('partials', 0))}",
        '',
        '<b>Alerts & suppression</b>',
        f"State: {alert_state} · sent today {sent_today} · suppressions {suppress}",
        '',
        '<i>End of master desk review — cache-only, no pipelines executed.</i>',
    ]
    return _cap_message('\n'.join(ln for ln in lines if ln is not None))


def render_review_messages(snap: MarketSnapshot) -> List[Tuple[str, str]]:
    """Return exactly 3 grouped master desk review messages (never raises)."""
    ctx = _enrich_review_context(snap)
    builders = (
        ('Market + macro', lambda: _format_market_intelligence(snap, ctx)),
        ('Positioning + opportunities', lambda: _format_positioning_opportunities(snap, ctx)),
        ('System + calibration', lambda: _format_system_calibration(snap, ctx)),
    )
    out: List[Tuple[str, str]] = []
    for label, fn in builders:
        try:
            text = fn()
            out.append((label, text or f'<i>{label} unavailable in cache.</i>'))
        except Exception as exc:
            out.append((label, f'⚠ {label} unavailable ({str(exc)[:80]})'))
    return out[:3]
