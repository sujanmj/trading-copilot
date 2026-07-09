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
REGIME_RISK_OFF = 'RISK_OFF'
REGIME_WATCH = 'WATCH MODE'
REGIME_NORMAL = 'NORMAL'

EMERGENCY_FEED_SOURCE = 'emergency_macro'
EMERGENCY_MIN_PERSIST_CONFIDENCE = 0.75

BOND_YIELD_CLUSTERS = (
    'bond yield',
    'bond yields',
    'yields hit',
    'yield spike',
    'ecb rate',
    'rate hike bets',
    'rate hike',
)

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
    'oil surge',
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
    'sensex crashes',
    'nifty crashes',
    'sensex/nifty',
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


def classify_macro_themes(
    text: str,
    *,
    geo_hits: list[str],
    oil_hits: list[str],
    crash_hits: list[str],
    emergency_theme: str = '',
) -> list[str]:
    lower = str(text or '').lower()
    themes: list[str] = []
    if crash_hits or any(k in lower for k in ('sensex', 'nifty', 'selloff', 'gap down', 'gap-down', 'crash', 'risk-off', 'risk off')):
        themes.append(THEME_LABELS['market_crash'])
    if oil_hits or _parse_oil_move_pct(text) or 'oil surge' in lower or 'oil prices' in lower:
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
    if emergency_theme.replace('_', ' ') in ('macro policy', 'macro') or 'bond yield' in lower or 'rate hike' in lower:
        themes.append('macro policy')
    if any(k in lower for k in ('risk-off', 'risk off', 'selloff', 'bond yield', 'oil surge')):
        if 'risk-off' not in themes and 'risk off' not in themes:
            themes.append('risk-off')
    # Preserve order, dedupe.
    seen: set[str] = set()
    ordered: list[str] = []
    for theme in themes:
        key = theme.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(theme)
    return ordered


def score_macro_severity(
    text: str,
    *,
    item: dict[str, Any] | None = None,
    confidence: float | None = None,
    direct_market_impact: bool = False,
    emergency_theme: str = '',
) -> dict[str, Any]:
    """Return severity assessment for a headline/cluster."""
    headline = str(text or '').strip()
    lower = headline.lower()
    geo_hits = _cluster_hits(lower, GEOPOLITICAL_CLUSTERS)
    oil_hits = _cluster_hits(lower, OIL_CLUSTERS)
    if 'oil surge' in lower or 'fuels' in lower and 'oil' in lower:
        if 'oil surge' not in oil_hits:
            oil_hits = list(oil_hits) + ['oil surge']
    crash_hits = _cluster_hits(lower, MARKET_CRASH_CLUSTERS)
    bond_hits = _cluster_hits(lower, BOND_YIELD_CLUSTERS)
    secondary_hits = _cluster_hits(lower, SECONDARY_IMPACT_CLUSTERS)
    oil_pct = _parse_oil_move_pct(headline)
    source = _detect_source_name(headline, item)
    major_source = bool(source) or any(s.strip() in lower for s in MAJOR_SOURCES)
    themes = classify_macro_themes(
        headline,
        geo_hits=geo_hits,
        oil_hits=oil_hits,
        crash_hits=crash_hits,
        emergency_theme=emergency_theme,
    )

    india_gap_down = any(
        k in lower for k in (
            'gift nifty down', 'sensex gap', 'nifty gap', 'sensex crash', 'nifty crash',
            'sensex falls', 'nifty falls', 'india crash',
        )
    )
    geo_escalation = bool(geo_hits) or ('iran' in lower and any(k in lower for k in ('war', 'ceasefire', 'strike', 'trump')))
    oil_spike = oil_pct is not None and oil_pct >= 4.0
    oil_moderate = oil_pct is not None and oil_pct >= 2.5
    oil_surge = bool(oil_hits) or 'oil surge' in lower
    bond_shock = bool(bond_hits)

    severity = SEVERITY_LOW
    triggers: list[str] = []

    if geo_escalation:
        triggers.append('geopolitical escalation')
    if oil_spike:
        triggers.append(f'oil jump {oil_pct:.1f}%')
    elif oil_surge:
        triggers.append('oil surge')
    elif oil_moderate:
        triggers.append(f'oil move {oil_pct:.1f}%')
    if bond_shock:
        triggers.append('bond yield shock')
    if india_gap_down:
        triggers.append('India index/futures gap-down risk')
    if crash_hits:
        triggers.append('market crash risk')

    conf = float(confidence) if confidence is not None else None

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
    elif oil_spike or oil_surge or bond_shock or (geo_escalation and oil_moderate) or (
        major_source and len(secondary_hits) >= 2 and (geo_hits or oil_hits or crash_hits)
    ) or (
        len(themes) >= 3 and (geo_hits or oil_hits)
    ) or (geo_escalation and crash_hits):
        severity = SEVERITY_HIGH
    elif geo_hits or oil_hits or crash_hits or oil_moderate or bond_hits:
        severity = SEVERITY_WATCH
    elif secondary_hits:
        severity = SEVERITY_LOW

    # Emergency Macro path: direct impact + high confidence floors severity to HIGH.
    if direct_market_impact and conf is not None and conf >= 0.90:
        if SEVERITY_RANK.get(severity, 0) < SEVERITY_RANK[SEVERITY_HIGH]:
            severity = SEVERITY_HIGH
            if 'direct market impact' not in triggers:
                triggers.append('direct market impact')
    elif direct_market_impact and conf is not None and conf >= EMERGENCY_MIN_PERSIST_CONFIDENCE:
        if SEVERITY_RANK.get(severity, 0) < SEVERITY_RANK[SEVERITY_WATCH]:
            severity = SEVERITY_WATCH

    regime = REGIME_NORMAL
    gap_down_risk = False
    if severity == SEVERITY_CRITICAL:
        regime = REGIME_RED
        gap_down_risk = True
    elif severity == SEVERITY_HIGH:
        if india_gap_down or crash_hits:
            regime = REGIME_RED
            gap_down_risk = True
        else:
            regime = REGIME_RISK_OFF
            gap_down_risk = False

    impact_parts: list[str] = []
    if direct_market_impact:
        impact_parts.append('direct market impact')
    if gap_down_risk or crash_hits:
        impact_parts.append('India risk-off; broad-market selloff risk')
    if oil_spike or oil_hits or oil_surge:
        impact_parts.append('oil-importer pressure')
    if bond_shock:
        impact_parts.append('global yield / rate-hike risk-off')
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
        'bond_hits': bond_hits,
        'oil_pct': oil_pct,
        'major_source': major_source,
        'confidence': conf,
        'direct_market_impact': bool(direct_market_impact),
        'emergency_theme': emergency_theme or '',
        'detected_at': _now_ist().replace(microsecond=0).isoformat(),
        'session_date': _session_date(),
    }


def store_macro_shock_memory(
    assessment: dict[str, Any],
    *,
    original_source: str = '',
    feed_source: str = 'macro_shock_sentinel',
) -> dict[str, Any]:
    """Persist macro shock into my_feed (dedupe same headline within session)."""
    from backend.my_feed.my_feed_db import find_recent_duplicate, insert_feed_item

    headline = str(assessment.get('headline') or assessment.get('trigger') or 'Macro shock')
    themes = list(assessment.get('themes') or [])
    severity = str(assessment.get('severity') or SEVERITY_WATCH)
    impact = float({'LOW': 40, 'WATCH': 62, 'HIGH': 82, 'CRITICAL': 95}.get(severity, 60))
    src = feed_source or 'macro_shock_sentinel'

    duplicate = find_recent_duplicate(headline, hours=18)
    if duplicate and str(duplicate.get('event_type') or '') == 'macro_shock':
        # Update active state pointer only — do not insert a second feed row.
        return duplicate

    record = insert_feed_item({
        'source': src,
        'raw_market_text': headline,
        'cleaned_summary': headline,
        'detected_source_app': original_source or (assessment.get('sources') or [''])[0] or src,
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
            'feed_type': 'macro_shock',
            'macro_severity': severity,
            'macro_regime': assessment.get('regime'),
            'macro_trigger': assessment.get('trigger'),
            'macro_impact': assessment.get('impact'),
            'gap_down_risk': bool(assessment.get('gap_down_risk')),
            'original_source': original_source or src,
            'original_headline': headline,
            'original_timestamp': assessment.get('detected_at'),
            'confidence': assessment.get('confidence'),
            'direct_market_impact': bool(assessment.get('direct_market_impact')),
            'emergency_theme': assessment.get('emergency_theme') or '',
            'catalyst_eligible': False,
            'macro_regime_only': True,
        },
    })
    return record


def _bump_duplicate_meta(assessment: dict[str, Any]) -> dict[str, Any]:
    """On same-headline revisit, bump source_count / updated_at in active state."""
    state = _load_state()
    active = state.get('active') if isinstance(state.get('active'), dict) else {}
    h_hash = _headline_hash(str(assessment.get('headline') or ''))
    count = int(active.get('source_count') or 1)
    if _headline_hash(str(active.get('headline') or '')) == h_hash:
        count += 1
    else:
        count = max(count, 1)
    sources = list(active.get('sources') or [])
    for src in assessment.get('sources') or []:
        if src and src not in sources:
            sources.append(src)
    merged = {
        **active,
        **assessment,
        'sources': sources or list(assessment.get('sources') or []),
        'source_count': count,
        'updated_at': _now_ist().replace(microsecond=0).isoformat(),
    }
    # Keep higher severity for the session.
    prev_rank = SEVERITY_RANK.get(str(active.get('severity') or ''), -1)
    new_rank = SEVERITY_RANK.get(str(assessment.get('severity') or ''), 0)
    if prev_rank > new_rank and active.get('session_date') == _session_date():
        merged['severity'] = active.get('severity')
        merged['regime'] = active.get('regime') or merged.get('regime')
        merged['gap_down_risk'] = bool(active.get('gap_down_risk') or merged.get('gap_down_risk'))
    state['active'] = merged
    _save_state(state)
    return merged


def persist_emergency_macro_to_sentinel(
    headline: str,
    *,
    confidence: float = 0.0,
    theme: str = '',
    source: str = 'emergency_macro',
    summary: str = '',
    timestamp: str = '',
    item: dict[str, Any] | None = None,
    direct_market_impact: bool = True,
) -> dict[str, Any]:
    """
    Persist a sent Emergency Macro alert into macro shock state + my_feed.

    Called after Telegram emergency macro is successfully sent.
    Does not send another Telegram alert (already delivered upstream).
    """
    text = str(headline or summary or '').strip()
    if not text:
        return {'ok': False, 'reason': 'empty', 'persisted': False}

    conf = float(confidence or 0)
    if conf < EMERGENCY_MIN_PERSIST_CONFIDENCE and not direct_market_impact:
        return {'ok': True, 'reason': 'below_persist_threshold', 'persisted': False}

    assessment = score_macro_severity(
        text,
        item=item,
        confidence=conf,
        direct_market_impact=direct_market_impact,
        emergency_theme=str(theme or ''),
    )
    if timestamp:
        assessment['detected_at'] = str(timestamp)
    if source:
        sources = list(assessment.get('sources') or [])
        if source not in sources:
            sources.insert(0, source)
        assessment['sources'] = sources
    assessment['emergency_theme'] = str(theme or assessment.get('emergency_theme') or '')
    assessment['confidence'] = conf
    assessment['direct_market_impact'] = bool(direct_market_impact)

    severity = str(assessment.get('severity') or SEVERITY_LOW)
    if SEVERITY_RANK.get(severity, 0) < SEVERITY_RANK[SEVERITY_WATCH]:
        return {'ok': True, 'assessment': assessment, 'persisted': False, 'reason': 'low_severity'}

    state = _load_state()
    prev = state.get('active') if isinstance(state.get('active'), dict) else {}
    same_headline = (
        prev.get('session_date') == _session_date()
        and _headline_hash(str(prev.get('headline') or '')) == _headline_hash(text)
    )

    if same_headline:
        active = _bump_duplicate_meta(assessment)
        feed_id = str(active.get('feed_id') or '')
        print(
            f'[MACRO_SHOCK_PERSIST] emergency_macro duplicate severity={severity} '
            f'source_count={active.get("source_count")}',
            flush=True,
        )
        return {
            'ok': True,
            'assessment': active,
            'persisted': True,
            'duplicate': True,
            'feed_id': feed_id,
            'reason': 'duplicate_updated',
        }

    record = store_macro_shock_memory(
        assessment,
        original_source=source or EMERGENCY_FEED_SOURCE,
        feed_source=EMERGENCY_FEED_SOURCE,
    )
    feed_id = str(record.get('feed_id') or '')
    # If find_recent_duplicate returned an older row, still merge into active state.
    active = _merge_active_state(assessment, feed_id=feed_id)
    print(
        f'[MACRO_SHOCK_PERSIST] emergency_macro severity={severity} feed_id={feed_id}',
        flush=True,
    )
    return {
        'ok': True,
        'assessment': active,
        'persisted': True,
        'duplicate': bool(record.get('feed_id') and same_headline),
        'feed_id': feed_id,
        'reason': 'persisted',
    }


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
    if active.get('removed') or active.get('inactive'):
        return None
    session = str(active.get('session_date') or '')[:10]
    if session and session != _session_date(now):
        return None
    severity = str(active.get('severity') or SEVERITY_LOW)
    if SEVERITY_RANK.get(severity, 0) < SEVERITY_RANK[SEVERITY_WATCH]:
        return None
    return active


def _feed_item_to_assessment(item: dict[str, Any]) -> dict[str, Any]:
    payload = item.get('payload') if isinstance(item.get('payload'), dict) else {}
    headline = str(
        item.get('cleaned_summary')
        or item.get('raw_market_text')
        or payload.get('original_headline')
        or ''
    ).strip()
    severity = str(
        payload.get('macro_severity')
        or item.get('macro_severity')
        or SEVERITY_WATCH
    )
    return {
        'severity': severity,
        'regime': payload.get('macro_regime') or item.get('macro_regime') or REGIME_WATCH,
        'gap_down_risk': bool(payload.get('gap_down_risk') or item.get('gap_down_risk')),
        'headline': headline,
        'trigger': payload.get('macro_trigger') or headline,
        'impact': payload.get('macro_impact') or 'macro shock from feed memory',
        'themes': list(item.get('themes') or payload.get('themes') or []),
        'sources': [str(item.get('source') or item.get('detected_source_app') or '')],
        'feed_id': str(item.get('feed_id') or ''),
        'session_date': _session_date(),
        'detected_at': str(item.get('created_at') or _now_ist().replace(microsecond=0).isoformat()),
    }


def _is_active_macro_feed_row(item: dict[str, Any]) -> bool:
    if str(item.get('status') or '').upper() == 'REMOVED_BY_USER':
        return False
    if str(item.get('event_type') or '') == 'macro_shock':
        return True
    if str(item.get('source') or '') in ('macro_shock_sentinel', EMERGENCY_FEED_SOURCE):
        return True
    payload = item.get('payload') if isinstance(item.get('payload'), dict) else {}
    return str(payload.get('feed_type') or '') == 'macro_shock'


def recalculate_macro_regime_from_feeds() -> dict[str, Any]:
    """Rebuild active macro shock from remaining active macro feed rows."""
    from backend.my_feed.feed_processor import list_feed_items

    rows = list_feed_items(limit=50, today_only=True, status='active')
    macro_rows = [row for row in rows if _is_active_macro_feed_row(row)]
    best: dict[str, Any] | None = None
    best_rank = -1
    best_feed_id = ''
    for row in macro_rows:
        assessment = _feed_item_to_assessment(row)
        rank = SEVERITY_RANK.get(str(assessment.get('severity') or ''), 0)
        if rank > best_rank:
            best = assessment
            best_rank = rank
            best_feed_id = str(row.get('feed_id') or '')

    state = _load_state()
    if best and best_rank >= SEVERITY_RANK[SEVERITY_WATCH]:
        active = _merge_active_state(best, feed_id=best_feed_id)
        return {'ok': True, 'recalculated': True, 'active': active}
    state['active'] = {}
    _save_state(state)
    return {'ok': True, 'recalculated': True, 'active': None}


def deactivate_macro_shock_for_feed(feed_id: str) -> dict[str, Any]:
    """Remove linked macro shock when user removes the source feed."""
    fid = str(feed_id or '').strip()
    if not fid:
        return {'ok': False, 'reason': 'empty_feed_id'}

    state = _load_state()
    active = state.get('active') if isinstance(state.get('active'), dict) else {}
    removed_this = False
    if str(active.get('feed_id') or '') == fid:
        removed = list(state.get('removed_shocks') or [])
        removed.append({
            **active,
            'removed_at': _now_ist().replace(microsecond=0).isoformat(),
            'removed_reason': 'user_removed',
            'source_feed_id': fid,
            'inactive': True,
        })
        state['removed_shocks'] = removed[-30:]
        state['active'] = {}
        _save_state(state)
        removed_this = True

    recalc = recalculate_macro_regime_from_feeds()
    return {
        'ok': True,
        'removed_linked_shock': removed_this,
        'feed_id': fid,
        'recalc': recalc,
    }


def restore_macro_shock_for_feed(feed_id: str, item: dict[str, Any]) -> dict[str, Any]:
    """Re-enter macro memory when a macro-relevant feed is restored."""
    fid = str(feed_id or '').strip()
    headline = str(
        item.get('cleaned_summary')
        or item.get('raw_market_text')
        or ''
    ).strip()
    if not headline:
        return {'ok': False, 'reason': 'empty_headline'}
    result = classify_manual_feed_macro(
        headline,
        source=str(item.get('source') or 'telegram_text'),
        item=item,
        timestamp=str(item.get('created_at') or ''),
    )
    return {
        'ok': bool(result.get('classified')),
        'feed_id': fid,
        'result': result,
    }


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
            'tighten confirmation; no stale catalyst-only confirmations; '
            'no fresh longs before 09:20 live confirmation'
        )
    if severity == SEVERITY_HIGH:
        return 'tighten confirmation; no stale catalyst-only confirmations'
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
            if str(row.get('source') or '') in ('macro_shock_sentinel', EMERGENCY_FEED_SOURCE)
               or str(row.get('event_type') or '') == 'macro_shock'
               or str((row.get('payload') or {}).get('feed_type') if isinstance(row.get('payload'), dict) else '') == 'macro_shock'
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
        lines.append(f'<b>Action:</b> {_trading_guard_text(active)}')
        lines.append(f'<b>Trading guard:</b> {_trading_guard_text(active)}')
        if active.get('gap_down_risk') or summary.get('regime') in (REGIME_RED, REGIME_RISK_OFF):
            if active.get('gap_down_risk'):
                lines.append('<b>Risk:</b> RED MARKET / GAP-DOWN RISK')
            else:
                lines.append(f'<b>Risk:</b> {summary.get("regime")}')
    else:
        lines.append('No active macro shock — overnight sentinel armed.')
    lines.append('<i>Paper/research only</i>')
    try:
        from backend.trading.weekly_signal_capture import capture_macro_market_signal

        capture_macro_market_signal(active)
    except Exception:
        pass
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


STOCK_SPECIFIC_NEWS_PATTERNS = (
    r'\b(order win|wins order|bag(s|ged)? order|contract win)\b',
    r'\b(q[1-4]\s*(results?|earnings)|earnings beat|results beat)\b',
    r'\b(board approves|preferential allotment|buyback|demerger|fund raise)\b',
    r'\b(shares (surge|jump|rally|plunge)|stock (surges|jumps))\b',
)


def is_stock_specific_feed_news(text: str, *, item: dict[str, Any] | None = None) -> bool:
    """True for normal company/stock news that should NOT become macro shock."""
    lower = str(text or '').lower()
    if not lower:
        return False
    # Broad market / geo / oil / yields always win over stock-specific heuristics.
    if any(k in lower for k in (
        'iran', 'ceasefire', 'strait of hormuz', 'hormuz', 'crude', 'oil surge', 'oil jump',
        'sensex', 'nifty', 'gift nifty', 'risk-off', 'risk off', 'bond yield', 'sanctions',
        'war ', ' inflation', 'global selloff', 'market crash',
    )):
        return False
    tickers = []
    if item:
        tickers = list(item.get('tickers') or [])
    if not tickers and re.search(r'\b[A-Z]{3,12}\b', str(text or '')):
        # Heuristic: upper tickers alone are weak; require stock pattern.
        pass
    if any(re.search(pat, lower) for pat in STOCK_SPECIFIC_NEWS_PATTERNS):
        return True
    event_type = str((item or {}).get('event_type') or '').lower()
    if event_type in ('results', 'corporate_action') and not any(
        k in lower for k in ('crude', 'oil', 'iran', 'sensex', 'nifty', 'war', 'sanction')
    ):
        return True
    return False


def annotate_feed_item_as_macro_shock(
    feed_id: str,
    assessment: dict[str, Any],
) -> bool:
    """Mark an existing /feed row as macro_shock so /myfeed today + /macro today see it."""
    if not feed_id:
        return False
    try:
        from backend.my_feed.my_feed_db import merge_feed_item_payload, update_feed_item_metadata

        themes = list(assessment.get('themes') or [])
        if 'macro policy' not in themes and assessment.get('emergency_theme'):
            themes.append(str(assessment.get('emergency_theme')).replace('_', ' '))
        severity = str(assessment.get('severity') or SEVERITY_WATCH)
        meta_ok = bool(update_feed_item_metadata(feed_id, {
            'event_type': 'macro_shock',
            'themes': themes,
            'urgency': 'high' if severity in (SEVERITY_HIGH, SEVERITY_CRITICAL) else 'medium',
            'suggested_action': 'MACRO SHOCK ALERT',
            'confirmation_required': True,
            'impact_score': float(
                {'LOW': 40, 'WATCH': 62, 'HIGH': 82, 'CRITICAL': 95}.get(severity, 60)
            ),
            'sentiment': 'bearish',
        }))
        payload_ok = merge_feed_item_payload(feed_id, {
            'feed_type': 'macro_shock',
            'active': True,
            'source_feed_id': str(feed_id),
            'macro_severity': severity,
            'macro_regime': assessment.get('regime'),
            'macro_trigger': assessment.get('trigger'),
            'macro_impact': assessment.get('impact'),
            'gap_down_risk': bool(assessment.get('gap_down_risk')),
            'catalyst_eligible': False,
            'macro_regime_only': True,
        })
        return meta_ok and payload_ok
    except Exception:
        return False


def classify_manual_feed_macro(
    headline: str,
    *,
    source: str = '',
    item: dict[str, Any] | None = None,
    timestamp: str = '',
) -> dict[str, Any]:
    """
    Classify a manual /feed item into macro shock memory when macro-relevant.
    Does not send Telegram (user already posted). Updates /macro + /myfeed visibility.
    """
    text = str(headline or '').strip()
    if not text:
        return {'ok': False, 'reason': 'empty', 'classified': False}
    if is_stock_specific_feed_news(text, item=item):
        return {'ok': True, 'reason': 'stock_specific', 'classified': False}

    assessment = score_macro_severity(text, item=item)
    if timestamp:
        assessment['detected_at'] = str(timestamp)
    if source:
        sources = list(assessment.get('sources') or [])
        if source not in sources:
            sources.insert(0, source)
        assessment['sources'] = sources

    severity = str(assessment.get('severity') or SEVERITY_LOW)
    if SEVERITY_RANK.get(severity, 0) < SEVERITY_RANK[SEVERITY_WATCH]:
        return {'ok': True, 'assessment': assessment, 'classified': False, 'reason': 'low_severity'}

    feed_id = str((item or {}).get('feed_id') or '')
    annotated = False
    if feed_id:
        annotated = annotate_feed_item_as_macro_shock(feed_id, assessment)
    else:
        try:
            record = store_macro_shock_memory(
                assessment,
                original_source=source or 'telegram_text',
                feed_source='telegram_text',
            )
            feed_id = str(record.get('feed_id') or '')
            annotated = bool(feed_id)
        except Exception:
            pass

    active = _merge_active_state(assessment, feed_id=feed_id)
    print(
        f'[MACRO_SHOCK_FEED] classified=yes severity={severity} feed_id={feed_id}',
        flush=True,
    )
    return {
        'ok': True,
        'assessment': active,
        'classified': True,
        'annotated': annotated,
        'feed_id': feed_id,
        'reason': 'macro_shock',
    }


def process_macro_headline(
    headline: str,
    *,
    source: str = '',
    item: dict[str, Any] | None = None,
    send_fn: Callable[[str], bool] | None = None,
    slot: str = 'immediate',
    store_memory: bool = True,
    from_manual_feed: bool = False,
) -> dict[str, Any]:
    """
    Analyze headline, optionally store memory, optionally send Telegram alert.
    Returns result dict with keys: ok, assessment, sent, reason.
    """
    text = str(headline or '').strip()
    if not text:
        return {'ok': False, 'reason': 'empty', 'sent': False}

    if from_manual_feed or str(source or '') in ('telegram_text', 'gui_text', 'my_feed'):
        classified = classify_manual_feed_macro(
            text,
            source=source,
            item=item,
            timestamp=str((item or {}).get('created_at') or ''),
        )
        # Manual /feed: classify/memory only unless a send_fn is explicitly provided
        # for HIGH/CRITICAL (rare). Do not auto-spam Telegram.
        if send_fn is None:
            return {
                'ok': True,
                'assessment': classified.get('assessment'),
                'sent': False,
                'reason': classified.get('reason') or 'manual_feed',
                'feed_id': classified.get('feed_id') or '',
                'classified': bool(classified.get('classified')),
            }
        if not classified.get('classified'):
            return {
                'ok': True,
                'assessment': classified.get('assessment'),
                'sent': False,
                'reason': classified.get('reason') or 'not_macro',
                'feed_id': '',
                'classified': False,
            }
        # Fall through with assessment for optional alerting.
        assessment = classified.get('assessment') or score_macro_severity(text, item=item)
    else:
        if is_stock_specific_feed_news(text, item=item):
            return {'ok': True, 'assessment': None, 'sent': False, 'reason': 'stock_specific'}
        assessment = score_macro_severity(text, item=item)

    severity = str((assessment or {}).get('severity') or SEVERITY_LOW)
    if SEVERITY_RANK.get(severity, 0) < SEVERITY_RANK[SEVERITY_WATCH]:
        return {'ok': True, 'assessment': assessment, 'sent': False, 'reason': 'low_severity'}

    feed_id = str((assessment or {}).get('feed_id') or (item or {}).get('feed_id') or '')
    if store_memory and not from_manual_feed and severity in (SEVERITY_WATCH, SEVERITY_HIGH, SEVERITY_CRITICAL):
        try:
            record = store_macro_shock_memory(assessment, original_source=source)
            feed_id = str(record.get('feed_id') or '') or feed_id
        except Exception:
            pass

    active = _merge_active_state(assessment or {}, feed_id=feed_id)
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
        'classified': True,
    }


def run_macro_shock_checkpoint_0830(
    *,
    send_fn: Callable[[str], bool] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    08:30 IST Macro Shock Checkpoint:
    scan latest my_feed / news-style items, update sentinel memory,
    send one Telegram alert only if HIGH/CRITICAL and not already alerted.
    """
    ist_now = _now_ist(now)
    polled = poll_recent_feeds_for_macro_shock(send_fn=None, limit=40)
    # Also scan known global/news json caches when present.
    try:
        from backend.storage.data_paths import get_data_path
        import json as _json

        for name in ('news_latest.json', 'govt_latest.json', 'global_markets_latest.json'):
            path = get_data_path(name)
            if not path.is_file():
                continue
            try:
                payload = _json.loads(path.read_text(encoding='utf-8'))
            except (OSError, _json.JSONDecodeError):
                continue
            candidates: list[str] = []
            if isinstance(payload, dict):
                for art in (payload.get('articles') or [])[:12]:
                    if isinstance(art, dict):
                        candidates.append(str(art.get('title') or art.get('headline') or ''))
                for item in (payload.get('high_impact_items') or [])[:8]:
                    if isinstance(item, dict):
                        candidates.append(str(item.get('english_headline') or item.get('title') or ''))
            for title in candidates:
                if not title.strip():
                    continue
                process_macro_headline(title, source=name, send_fn=None, slot='0830_scan', store_memory=True)
    except Exception:
        pass

    active = get_active_macro_shock(now=ist_now)
    if not active:
        print('[MACRO_SHOCK_CHECKPOINT] slot=0830 status=no_active_shock', flush=True)
        return {'ok': True, 'sent': False, 'reason': 'no_active_shock', 'polled': polled}

    severity = str(active.get('severity') or '')
    if severity not in (SEVERITY_HIGH, SEVERITY_CRITICAL):
        print(f'[MACRO_SHOCK_CHECKPOINT] slot=0830 status=below_alert severity={severity}', flush=True)
        return {'ok': True, 'sent': False, 'reason': 'below_alert', 'assessment': active}

    result = process_macro_headline(
        str(active.get('headline') or active.get('trigger') or ''),
        source=str((active.get('sources') or ['checkpoint'])[0]),
        send_fn=send_fn,
        slot='0830',
        store_memory=False,
    )
    print(
        f'[MACRO_SHOCK_CHECKPOINT] slot=0830 sent={bool(result.get("sent"))} '
        f'reason={result.get("reason")}',
        flush=True,
    )
    return result


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
        if str(row.get('source') or '') in ('macro_shock_sentinel', EMERGENCY_FEED_SOURCE):
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
