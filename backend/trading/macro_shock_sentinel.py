"""
Overnight Macro Shock Sentinel — Phase 4B.18E / AstraEdge 52C.

Detects high-severity geopolitical/oil/index-risk headlines from feeds,
scores severity, stores macro memory, and sends deduped Telegram alerts
before market open. Paper/research only — no LLM calls.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path
from backend.storage.json_io import atomic_write_json

IST = ZoneInfo('Asia/Kolkata')
STAGE = '4B.18E'
STATE_FILE = get_data_path('macro_shock_sentinel_state.json')

SEVERITY_LOW = 'LOW'
SEVERITY_WATCH = 'WATCH'
SEVERITY_HIGH = 'HIGH'
SEVERITY_CRITICAL = 'CRITICAL'

SEVERITY_RANK = {
    SEVERITY_LOW: 0,
    SEVERITY_WATCH: 1,
    SEVERITY_HIGH: 2,
    SEVERITY_CRITICAL: 3,
}

REGIME_RED = 'RED MARKET'
REGIME_WATCH = 'WATCH MODE'
REGIME_NORMAL = 'NORMAL'

GEOPOLITICAL_CLUSTERS = (
    'iran ceasefire over',
    'ceasefire over',
    'ceasefire collapse',
    'us-iran war',
    'us iran war',
    'trump iran',
    'strait of hormuz',
    'hormuz',
    'missile strike',
    'oil tanker attack',
    'tanker attack',
    'middle east escalation',
    'middle east conflict',
    'war risk',
    'sanctions',
    'geopolitical',
)

OIL_CLUSTERS = (
    'brent crude jump',
    'brent jumps',
    'wti jump',
    'wti jumps',
    'crude oil jump',
    'crude jumps',
    'oil up',
    'oil jumps',
    'crude spike',
    'oil spike',
    'supply disruption',
    'hormuz risk',
    'crude surges',
    'oil surges',
)

MARKET_CRASH_CLUSTERS = (
    'sensex gap-down',
    'sensex gap down',
    'nifty gap-down',
    'nifty gap down',
    'gift nifty down',
    'gift nifty',
    'global selloff',
    'risk-off',
    'risk off',
    'inflation shock',
    'oil importer pressure',
    'sensex crash',
    'nifty crash',
    'sensex falls',
    'nifty falls',
    'market selloff',
    'broad-market selloff',
    'broad market selloff',
)

SECONDARY_IMPACT_CLUSTERS = (
    'inr',
    'rupee',
    'inflation',
    'fii',
    'crude',
    'oil importer',
)

MAJOR_SOURCES = (
    'reuters',
    'associated press',
    ' ap ',
    'inshorts',
    'bloomberg',
    'cnbc',
    'bbc',
    'ndtv',
    'moneycontrol',
)

THEME_LABELS = {
    'market_crash': 'market crash',
    'crude_oil': 'crude oil',
    'iran': 'Iran',
    'geopolitics': 'geopolitics',
    'inflation': 'inflation',
    'inr_risk': 'INR risk',
    'fii_risk': 'FII risk',
}


def _now_ist(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(tz=IST)
    if now.tzinfo is None:
        return now.replace(tzinfo=IST)
    return now.astimezone(IST)


def _session_date(now: datetime | None = None) -> str:
    return _now_ist(now).date().isoformat()


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.is_file():
        return {}
    try:
        payload = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    atomic_write_json(STATE_FILE, state)


def _headline_hash(headline: str) -> str:
    norm = re.sub(r'\s+', ' ', str(headline or '').strip().lower())
    return hashlib.sha256(norm.encode('utf-8')).hexdigest()[:16]


def _cluster_hits(text: str, clusters: tuple[str, ...]) -> list[str]:
    lower = str(text or '').lower()
    return [c for c in clusters if c in lower]


def _parse_oil_move_pct(text: str) -> float | None:
    lower = str(text or '').lower()
    if not any(k in lower for k in ('oil', 'crude', 'brent', 'wti', 'petroleum')):
        return None
    best: float | None = None
    for match in re.finditer(r'(\d+(?:\.\d+)?)\s*%', lower):
        try:
            pct = float(match.group(1))
        except ValueError:
            continue
        if best is None or pct > best:
            best = pct
    for match in re.finditer(r'(?:jump|surge|spike|rise|up)\w*\s+(?:nearly\s+)?(\d+(?:\.\d+)?)', lower):
        if 'oil' in lower or 'crude' in lower:
            try:
                pct = float(match.group(1))
            except ValueError:
                continue
            if best is None or pct > best:
                best = pct
    return best


def _detect_source_name(text: str, item: dict[str, Any] | None = None) -> str:
    if item:
        for key in ('source_name', 'detected_source_app', 'source'):
            val = str(item.get(key) or '').strip()
            if val and val not in ('telegram_text', 'gui_text', 'macro_shock_sentinel'):
                return val
    lower = f' {str(text or "").lower()} '
    for src in MAJOR_SOURCES:
        if src.strip() in lower or src in lower:
            return src.strip()
    if 'inshorts' in lower:
        return 'Inshorts'
    return ''


def classify_macro_themes(text: str, *, geo_hits: list[str], oil_hits: list[str], crash_hits: list[str]) -> list[str]:
    lower = str(text or '').lower()
    themes: list[str] = []
    if crash_hits or any(k in lower for k in ('sensex', 'nifty', 'selloff', 'gap down', 'gap-down', 'crash')):
        themes.append(THEME_LABELS['market_crash'])
    if oil_hits or _parse_oil_move_pct(text):
        themes.append(THEME_LABELS['crude_oil'])
    if 'iran' in lower or any('iran' in h for h in geo_hits):
        themes.append(THEME_LABELS['iran'])
    if geo_hits:
        themes.append(THEME_LABELS['geopolitics'])
    if 'inflation' in lower:
        themes.append(THEME_LABELS['inflation'])
    if any(k in lower for k in ('inr', 'rupee')):
        themes.append(THEME_LABELS['inr_risk'])
    if 'fii' in lower:
        themes.append(THEME_LABELS['fii_risk'])
    # Preserve order, dedupe.
    seen: set[str] = set()
    ordered: list[str] = []
    for theme in themes:
        if theme not in seen:
            seen.add(theme)
            ordered.append(theme)
    return ordered


def score_macro_severity(
    text: str,
    *,
    item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return severity assessment for a headline/cluster."""
    headline = str(text or '').strip()
    lower = headline.lower()
    geo_hits = _cluster_hits(lower, GEOPOLITICAL_CLUSTERS)
    oil_hits = _cluster_hits(lower, OIL_CLUSTERS)
    crash_hits = _cluster_hits(lower, MARKET_CRASH_CLUSTERS)
    secondary_hits = _cluster_hits(lower, SECONDARY_IMPACT_CLUSTERS)
    oil_pct = _parse_oil_move_pct(headline)
    source = _detect_source_name(headline, item)
    major_source = bool(source) or any(s.strip() in lower for s in MAJOR_SOURCES)
    themes = classify_macro_themes(headline, geo_hits=geo_hits, oil_hits=oil_hits, crash_hits=crash_hits)

    india_gap_down = any(
        k in lower for k in (
            'gift nifty down', 'sensex gap', 'nifty gap', 'sensex crash', 'nifty crash',
            'sensex falls', 'nifty falls', 'india crash',
        )
    )
    geo_escalation = bool(geo_hits) or ('iran' in lower and any(k in lower for k in ('war', 'ceasefire', 'strike', 'trump')))
    oil_spike = oil_pct is not None and oil_pct >= 4.0
    oil_moderate = oil_pct is not None and oil_pct >= 2.5

    severity = SEVERITY_LOW
    triggers: list[str] = []

    if geo_escalation:
        triggers.append('geopolitical escalation')
    if oil_spike:
        triggers.append(f'oil jump {oil_pct:.1f}%')
    elif oil_moderate:
        triggers.append(f'oil move {oil_pct:.1f}%')
    if india_gap_down:
        triggers.append('India index/futures gap-down risk')
    if crash_hits:
        triggers.append('market crash risk')

    if (geo_escalation and oil_spike) or oil_spike or india_gap_down or (
        major_source and india_gap_down
    ) or (
        major_source and crash_hits and any(k in lower for k in ('sensex', 'nifty', 'gift'))
    ) or (
        geo_escalation and major_source and any(
            k in lower for k in ('ceasefire over', 'ceasefire collapse', 'ceasefire is over')
        ) and 'iran' in lower
    ):
        severity = SEVERITY_CRITICAL
    elif oil_spike or (geo_escalation and oil_moderate) or (
        major_source and len(secondary_hits) >= 2 and (geo_hits or oil_hits or crash_hits)
    ) or (
        len(themes) >= 3 and (geo_hits or oil_hits)
    ):
        severity = SEVERITY_HIGH
    elif geo_hits or oil_hits or crash_hits or oil_moderate:
        severity = SEVERITY_WATCH
    elif secondary_hits:
        severity = SEVERITY_LOW

    regime = REGIME_NORMAL
    gap_down_risk = False
    if severity == SEVERITY_CRITICAL:
        regime = REGIME_RED
        gap_down_risk = True
    elif severity == SEVERITY_HIGH:
        regime = REGIME_RED if india_gap_down or crash_hits else REGIME_WATCH
        gap_down_risk = bool(india_gap_down or crash_hits)

    impact_parts: list[str] = []
    if gap_down_risk or crash_hits:
        impact_parts.append('India risk-off; broad-market selloff risk')
    if oil_spike or oil_hits:
        impact_parts.append('oil-importer pressure')
    if 'inr' in lower or 'rupee' in lower:
        impact_parts.append('INR weakness risk')
    if 'inflation' in lower:
        impact_parts.append('inflation shock risk')
    if not impact_parts:
        impact_parts.append('macro risk — monitor pre-open')

    trigger_text = headline[:240] if headline else 'macro shock detected'
    if triggers:
        trigger_text = ' + '.join(triggers)

    return {
        'severity': severity,
        'regime': regime,
        'gap_down_risk': gap_down_risk,
        'headline': headline,
        'trigger': trigger_text,
        'impact': '; '.join(impact_parts),
        'themes': themes,
        'sources': [source] if source else [],
        'geo_hits': geo_hits,
        'oil_hits': oil_hits,
        'crash_hits': crash_hits,
        'oil_pct': oil_pct,
        'major_source': major_source,
        'detected_at': _now_ist().replace(microsecond=0).isoformat(),
        'session_date': _session_date(),
    }


def store_macro_shock_memory(assessment: dict[str, Any], *, original_source: str = '') -> dict[str, Any]:
    """Persist macro shock into my_feed with source macro_shock_sentinel."""
    from backend.my_feed.my_feed_db import insert_feed_item

    headline = str(assessment.get('headline') or assessment.get('trigger') or 'Macro shock')
    themes = list(assessment.get('themes') or [])
    severity = str(assessment.get('severity') or SEVERITY_WATCH)
    impact = float({'LOW': 40, 'WATCH': 62, 'HIGH': 82, 'CRITICAL': 95}.get(severity, 60))

    record = insert_feed_item({
        'source': 'macro_shock_sentinel',
        'raw_market_text': headline,
        'cleaned_summary': headline,
        'detected_source_app': original_source or (assessment.get('sources') or [''])[0],
        'tickers': [],
        'sectors': [],
        'themes': themes,
        'event_type': 'macro_shock',
        'sentiment': 'bearish',
        'impact_score': impact,
        'urgency': 'high' if severity in (SEVERITY_HIGH, SEVERITY_CRITICAL) else 'medium',
        'suggested_action': 'MACRO SHOCK ALERT',
        'confirmation_required': True,
        'status': 'active',
        'payload': {
            'macro_severity': severity,
            'macro_regime': assessment.get('regime'),
            'macro_trigger': assessment.get('trigger'),
            'macro_impact': assessment.get('impact'),
            'gap_down_risk': bool(assessment.get('gap_down_risk')),
            'original_source': original_source,
            'original_headline': headline,
            'original_timestamp': assessment.get('detected_at'),
        },
    })
    return record


def _merge_active_state(assessment: dict[str, Any], *, feed_id: str = '') -> dict[str, Any]:
    state = _load_state()
    prev = state.get('active') if isinstance(state.get('active'), dict) else {}
    prev_rank = SEVERITY_RANK.get(str(prev.get('severity') or ''), -1)
    new_rank = SEVERITY_RANK.get(str(assessment.get('severity') or ''), 0)

    sources = list(prev.get('sources') or [])
    for src in assessment.get('sources') or []:
        if src and src not in sources:
            sources.append(src)

    active = {
        **assessment,
        'sources': sources or list(assessment.get('sources') or []),
        'feed_id': feed_id or prev.get('feed_id') or '',
        'updated_at': _now_ist().replace(microsecond=0).isoformat(),
    }
    if new_rank < prev_rank and prev.get('session_date') == _session_date():
        # Keep higher severity for the session unless explicitly upgraded.
        active['severity'] = prev.get('severity')
        active['regime'] = prev.get('regime') or active.get('regime')
        active['gap_down_risk'] = bool(prev.get('gap_down_risk') or active.get('gap_down_risk'))

    state['active'] = active
    _save_state(state)
    return active


def get_active_macro_shock(*, now: datetime | None = None) -> dict[str, Any] | None:
    state = _load_state()
    active = state.get('active')
    if not isinstance(active, dict) or not active:
        return None
    session = str(active.get('session_date') or '')[:10]
    if session and session != _session_date(now):
        return None
    severity = str(active.get('severity') or SEVERITY_LOW)
    if SEVERITY_RANK.get(severity, 0) < SEVERITY_RANK[SEVERITY_WATCH]:
        return None
    return active


def macro_shock_active_for_trading(*, now: datetime | None = None) -> bool:
    active = get_active_macro_shock(now=now)
    if not active:
        return False
    return str(active.get('severity') or '') in (SEVERITY_HIGH, SEVERITY_CRITICAL)


def macro_regime_summary(*, now: datetime | None = None) -> dict[str, Any]:
    active = get_active_macro_shock(now=now)
    if not active:
        return {
            'regime': REGIME_NORMAL,
            'severity': SEVERITY_LOW,
            'gap_down_risk': False,
            'active': False,
        }
    return {
        'regime': active.get('regime') or REGIME_WATCH,
        'severity': active.get('severity') or SEVERITY_WATCH,
        'gap_down_risk': bool(active.get('gap_down_risk')),
        'active': True,
        'latest_shock': active,
    }


def _trading_guard_text(active: dict[str, Any] | None) -> str:
    if not active:
        return 'Normal macro guard — follow standard opening workflow.'
    severity = str(active.get('severity') or '')
    if severity == SEVERITY_CRITICAL:
        return (
            'no fresh longs before 09:20 live confirmation; '
            'stale catalyst/watchlist names cannot be CONFIRMED today'
        )
    if severity == SEVERITY_HIGH:
        return 'tighten entries; require live scanner + positive relative strength'
    return 'monitor headlines; avoid blind catalyst-only longs'


def format_macro_shock_alert_telegram(
    assessment: dict[str, Any],
    *,
    slot: str = 'immediate',
) -> str:
    severity = str(assessment.get('severity') or SEVERITY_HIGH)
    regime = str(assessment.get('regime') or REGIME_WATCH)
    gap = bool(assessment.get('gap_down_risk'))
    title = '🚨 MACRO SHOCK — GAP-DOWN RISK' if gap or severity == SEVERITY_CRITICAL else '🚨 MACRO SHOCK ALERT'
    lines = [
        f'<b>{title}</b>',
        f'<i>Macro Shock Sentinel · {slot.replace("_", " ")} · paper/research only</i>',
        '',
        f'<b>Trigger:</b> {assessment.get("trigger") or assessment.get("headline") or "—"}',
        f'<b>Impact:</b> {assessment.get("impact") or "—"}',
        f'<b>Mode:</b> {regime}',
        f'<b>Severity:</b> {severity}',
    ]
    sources = assessment.get('sources') or []
    if sources:
        lines.append(f'<b>Sources:</b> {", ".join(str(s) for s in sources[:4])}')
    themes = assessment.get('themes') or []
    if themes:
        lines.append(f'<b>Themes:</b> {", ".join(themes)}')
    lines.extend([
        '',
        f'<b>Action:</b> {_trading_guard_text(assessment)}',
        '<b>Guard:</b> stale catalyst/watchlist names cannot be CONFIRMED today'
        if severity in (SEVERITY_HIGH, SEVERITY_CRITICAL)
        else '<b>Guard:</b> wait for live confirmation before entries',
    ])
    return '\n'.join(lines)


def format_macro_command_telegram(args: str = '') -> str:
    sub = str(args or '').strip().lower()
    active = get_active_macro_shock()
    summary = macro_regime_summary()

    if sub == 'explain':
        if not active:
            return (
                '<b>/macro explain</b>\n'
                'No active macro shock for today.\n'
                'Sentinel watches overnight geopolitical, oil, and India gap-down headlines.'
            )
        lines = [
            '<b>/macro explain</b>',
            f'<b>Regime:</b> {active.get("regime") or REGIME_NORMAL}',
            f'<b>Severity:</b> {active.get("severity")}',
            f'<b>Trigger:</b> {active.get("trigger") or active.get("headline")}',
            f'<b>Impact:</b> {active.get("impact")}',
            f'<b>Gap-down risk:</b> {"yes" if active.get("gap_down_risk") else "no"}',
        ]
        if active.get('themes'):
            lines.append(f'<b>Themes:</b> {", ".join(active.get("themes") or [])}')
        if active.get('sources'):
            lines.append(f'<b>Sources:</b> {", ".join(active.get("sources") or [])}')
        lines.extend([
            '',
            f'<b>Trading guard:</b> {_trading_guard_text(active)}',
            '<i>Paper/research only — no trade execution.</i>',
        ])
        return '\n'.join(lines)

    if sub == 'today':
        from backend.my_feed.feed_processor import list_feed_items, sanitize_item_for_api

        rows = [
            sanitize_item_for_api(row)
            for row in list_feed_items(limit=20, today_only=True)
            if str(row.get('source') or '') == 'macro_shock_sentinel'
               or str(row.get('event_type') or '') == 'macro_shock'
        ]
        lines = [
            '<b>/macro today</b>',
            f'<b>Regime:</b> {summary.get("regime")} · severity {summary.get("severity")}',
        ]
        if active:
            lines.append(f'<b>Latest:</b> {active.get("headline") or active.get("trigger")}')
        else:
            lines.append('No active macro shock stored for today.')
        if rows:
            lines.extend(['', '<b>Macro memory (today):</b>'])
            for row in rows[:6]:
                lines.append(
                    f'• {row.get("cleaned_summary", "")[:100]} '
                    f'[{row.get("urgency", "—")}]'
                )
        return '\n'.join(lines)

    lines = [
        '<b>/macro</b>',
        f'<b>Regime:</b> {summary.get("regime")}',
        f'<b>Severity:</b> {summary.get("severity")}',
    ]
    if active:
        lines.extend([
            f'<b>Latest shock:</b> {active.get("headline") or active.get("trigger")}',
            f'<b>Market impact:</b> {active.get("impact") or "—"}',
        ])
        if active.get('sources'):
            lines.append(f'<b>Sources:</b> {", ".join(active.get("sources") or [])}')
        lines.append(f'<b>Trading guard:</b> {_trading_guard_text(active)}')
        if active.get('gap_down_risk'):
            lines.append('<b>Risk:</b> RED MARKET / GAP-DOWN RISK')
    else:
        lines.append('No active macro shock — overnight sentinel armed.')
    lines.append('<i>Paper/research only</i>')
    return '\n'.join(lines)


def format_macro_memory_snippet() -> list[str]:
    active = get_active_macro_shock()
    if not active:
        return []
    return [
        '',
        '<b>Macro shock (today):</b>',
        f'• {active.get("regime")} · {active.get("severity")} — {active.get("trigger") or active.get("headline")}',
    ]


def _should_send_alert(
    assessment: dict[str, Any],
    *,
    slot: str = 'immediate',
) -> tuple[bool, str]:
    severity = str(assessment.get('severity') or SEVERITY_LOW)
    if SEVERITY_RANK.get(severity, 0) < SEVERITY_RANK[SEVERITY_HIGH]:
        return False, 'below_high_threshold'

    state = _load_state()
    last = state.get('last_alert') if isinstance(state.get('last_alert'), dict) else {}
    headline = str(assessment.get('headline') or '')
    h_hash = _headline_hash(headline)
    prev_severity = str(last.get('severity') or '')
    prev_rank = SEVERITY_RANK.get(prev_severity, -1)
    new_rank = SEVERITY_RANK.get(severity, 0)

    if last.get('headline_hash') == h_hash and prev_rank >= new_rank:
        return False, 'duplicate_headline'

    sent_at = str(last.get('sent_at') or '')
    if sent_at and slot == 'immediate':
        try:
            prev_dt = datetime.fromisoformat(sent_at)
            if prev_dt.tzinfo is None:
                prev_dt = prev_dt.replace(tzinfo=IST)
            if _now_ist() - prev_dt.astimezone(IST) < timedelta(minutes=45):
                if new_rank <= prev_rank and last.get('headline_hash') == h_hash:
                    return False, 'dedupe_window'
        except ValueError:
            pass

    # Scheduled slot dedupe — one per slot per day.
    slot_key = f"{_session_date()}:{slot}"
    sent_slots = state.get('sent_slots') if isinstance(state.get('sent_slots'), dict) else {}
    if slot != 'immediate' and sent_slots.get(slot_key):
        if new_rank <= prev_rank:
            return False, f'slot_already_sent:{slot}'

    # Stronger source can update.
    if new_rank > prev_rank:
        return True, 'severity_increased'
    if last.get('headline_hash') != h_hash and assessment.get('major_source'):
        return True, 'new_confirmation'
    if not last:
        return True, 'first_alert'
    if slot != 'immediate' and not sent_slots.get(slot_key):
        return True, f'scheduled:{slot}'
    return False, 'dedupe'


def _record_alert_sent(assessment: dict[str, Any], *, slot: str = 'immediate') -> None:
    state = _load_state()
    state['last_alert'] = {
        'severity': assessment.get('severity'),
        'headline_hash': _headline_hash(str(assessment.get('headline') or '')),
        'sent_at': _now_ist().replace(microsecond=0).isoformat(),
        'slot': slot,
    }
    sent_slots = state.get('sent_slots') if isinstance(state.get('sent_slots'), dict) else {}
    if slot != 'immediate':
        sent_slots[f"{_session_date()}:{slot}"] = True
    state['sent_slots'] = sent_slots
    _save_state(state)


def process_macro_headline(
    headline: str,
    *,
    source: str = '',
    item: dict[str, Any] | None = None,
    send_fn: Callable[[str], bool] | None = None,
    slot: str = 'immediate',
    store_memory: bool = True,
) -> dict[str, Any]:
    """
    Analyze headline, optionally store memory, optionally send Telegram alert.
    Returns result dict with keys: ok, assessment, sent, reason.
    """
    text = str(headline or '').strip()
    if not text:
        return {'ok': False, 'reason': 'empty', 'sent': False}

    assessment = score_macro_severity(text, item=item)
    severity = str(assessment.get('severity') or SEVERITY_LOW)
    if SEVERITY_RANK.get(severity, 0) < SEVERITY_RANK[SEVERITY_WATCH]:
        return {'ok': True, 'assessment': assessment, 'sent': False, 'reason': 'low_severity'}

    feed_id = ''
    if store_memory and severity in (SEVERITY_WATCH, SEVERITY_HIGH, SEVERITY_CRITICAL):
        try:
            record = store_macro_shock_memory(assessment, original_source=source)
            feed_id = str(record.get('feed_id') or '')
        except Exception:
            pass

    active = _merge_active_state(assessment, feed_id=feed_id)
    assessment = active

    should_send, reason = _should_send_alert(assessment, slot=slot)
    sent = False
    if should_send and send_fn is not None and severity in (SEVERITY_HIGH, SEVERITY_CRITICAL):
        text_out = format_macro_shock_alert_telegram(assessment, slot=slot)
        try:
            sent = bool(send_fn(text_out))
        except Exception:
            sent = False
        if sent:
            _record_alert_sent(assessment, slot=slot)
            print(
                f'[MACRO_SHOCK_SENT] severity={severity} slot={slot} reason={reason}',
                flush=True,
            )
        else:
            print(
                f'[MACRO_SHOCK_SKIPPED] severity={severity} slot={slot} reason=send_failed',
                flush=True,
            )
    elif not should_send:
        print(
            f'[MACRO_SHOCK_DEDUPED] severity={severity} slot={slot} reason={reason}',
            flush=True,
        )

    return {
        'ok': True,
        'assessment': assessment,
        'sent': sent,
        'reason': reason,
        'feed_id': feed_id,
    }


def poll_recent_feeds_for_macro_shock(
    *,
    send_fn: Callable[[str], bool] | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    """Scan recent my_feed items for macro shock headlines."""
    from backend.my_feed.my_feed_db import list_items

    best: dict[str, Any] | None = None
    for row in list_items(limit=limit, today_only=True):
        summary = str(row.get('cleaned_summary') or row.get('raw_market_text') or '')
        if not summary:
            continue
        if str(row.get('source') or '') == 'macro_shock_sentinel':
            continue
        assessment = score_macro_severity(summary, item=row)
        if SEVERITY_RANK.get(str(assessment.get('severity') or ''), 0) < SEVERITY_RANK[SEVERITY_HIGH]:
            continue
        if best is None or SEVERITY_RANK.get(str(assessment.get('severity')), 0) > SEVERITY_RANK.get(str(best.get('severity')), 0):
            best = assessment
            best['_source'] = str(row.get('detected_source_app') or row.get('source') or '')
    if not best:
        return {'ok': True, 'processed': False}
    return process_macro_headline(
        str(best.get('headline') or ''),
        source=str(best.get('_source') or ''),
        send_fn=send_fn,
        slot='immediate',
    )


def run_scheduled_macro_shock_check(
    slot: str,
    *,
    send_fn: Callable[[str], bool] | None = None,
    now: datetime | None = None,
) -> bool:
    """Run macro shock reminder at 07:45 / 08:00 / 09:00 pre-open slots."""
    active = get_active_macro_shock(now=now)
    if not active:
        polled = poll_recent_feeds_for_macro_shock(send_fn=send_fn)
        active = get_active_macro_shock(now=now)
        if polled.get('sent'):
            return True
        if not active:
            return False

    severity = str(active.get('severity') or '')
    if severity not in (SEVERITY_HIGH, SEVERITY_CRITICAL):
        return False

    result = process_macro_headline(
        str(active.get('headline') or active.get('trigger') or ''),
        source=str((active.get('sources') or [''])[0]),
        send_fn=send_fn,
        slot=slot,
        store_memory=False,
    )
    return bool(result.get('sent'))


def apply_macro_shock_to_board(board: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Attach macro shock regime fields used by radar/tradecard workflow."""
    data = dict(board or {})
    active = get_active_macro_shock(now=now)
    summary = macro_regime_summary(now=now)
    data['macro_shock'] = summary
    if active:
        severity = str(active.get('severity') or '')
        if severity in (SEVERITY_HIGH, SEVERITY_CRITICAL):
            data['emergency_macro'] = True
            data['macro_crash'] = bool(active.get('gap_down_risk'))
            data['crash_mode'] = bool(active.get('gap_down_risk'))
            data['macro_penalty'] = max(float(data.get('macro_penalty') or 0), 15.0)
            data['macro_regime'] = active.get('regime') or REGIME_RED
            data['macro_severity'] = severity
            data['gap_down_risk'] = bool(active.get('gap_down_risk'))
    return data


def macro_risk_penalty() -> float:
    """Penalty applied to opening rally scores during macro shock."""
    active = get_active_macro_shock()
    if not active:
        return 0.0
    severity = str(active.get('severity') or '')
    if severity == SEVERITY_CRITICAL:
        return 15.0
    if severity == SEVERITY_HIGH:
        return 12.0
    if severity == SEVERITY_WATCH:
        return 6.0
    return 0.0
