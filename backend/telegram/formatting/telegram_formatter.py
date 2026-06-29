"""
Telegram message formatter — size limits and command-scoped output.

/brain full · /opps opps only · /risks risks only · /action 3-line posture
/sectors rotation only · /status health only
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

MAX_TELEGRAM_CHARS = 3900
DEFAULT_MAX_LINES = 40

COMMAND_LINE_LIMITS: Dict[str, int] = {
    'brain': 120,
    'full': 120,
    'summary': 24,
    'opps': 35,
    'opportunities': 35,
    'risks': 20,
    'action': 6,
    'sectors': 12,
    'status': 48,
    'calibration': 25,
    'global': 35,
    'stats': 20,
    'outcomes': 25,
    'review': 55,
}


def enforce_line_limit(text: str, max_lines: int, *, suffix: str = '…') -> str:
    if not text:
        return text
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    trimmed = lines[:max_lines]
    trimmed.append(suffix)
    return '\n'.join(trimmed)


def enforce_char_limit(text: str, max_chars: int = MAX_TELEGRAM_CHARS) -> str:
    if not text or len(text) <= max_chars:
        return text or ''
    return text[: max_chars - 20] + '\n… (truncated)'


def _sanitize_telegram_text_clean(text: str) -> str:
    body = str(text or '')
    marker = r'(?:\uFFFD+|(?:\u00ef\u00bf\u00bd)+|\?{2,})'
    body = re.sub(rf'^[ \t]*{marker}[ \t]+(?=<|\w)', '', body, flags=re.MULTILINE)
    body = re.sub(rf'(?<=\S)[ \t]*{marker}[ \t]*(?=\S)', ' · ', body)
    body = re.sub(marker, '', body)
    body = re.sub(r'[ \t]+·[ \t]+', ' · ', body)
    body = re.sub(r'[ \t]+\n', '\n', body)
    body = re.sub(r'\n{3,}', '\n\n', body)
    return body.strip()


def sanitize_telegram_text(text: str) -> str:
    body = str(text or '')
    return _sanitize_telegram_text_clean(body)
    body = re.sub(r'\uFFFD+', '', body)
    body = re.sub(r'(?:ï¿½)+', '', body)
    body = re.sub(r'^[ \t]*\?{2,}[ \t]+(?=<)', '', body, flags=re.MULTILINE)
    body = re.sub(r'[ \t]+\n', '\n', body)
    body = re.sub(r'\n{3,}', '\n\n', body)
    return body.strip()


def format_for_command(text: str, command: str) -> str:
    cmd = str(command or 'brain').lower().strip().lstrip('/')
    max_lines = COMMAND_LINE_LIMITS.get(cmd, DEFAULT_MAX_LINES)
    out = enforce_line_limit(text, max_lines)
    out = enforce_char_limit(out)
    out = institutionalize(out)
    try:
        from backend.intelligence.institutional_language import dedupe_session_banners
        out = dedupe_session_banners(out)
    except Exception:
        pass
    return sanitize_telegram_text(out)


def _sanitize_section_line(prefix: str, body: str) -> str:
    """Safe fallback when WATCH:/AVOID: body is empty, null, or None."""
    cleaned = str(body or '').strip()
    if cleaned.lower() in ('', 'none', 'null', 'nan', 'undefined', 'n/a'):
        if prefix.upper().startswith('WATCH'):
            return 'Monitor for confirmation — no active watchlist.'
        if prefix.upper().startswith('AVOID'):
            return 'No elevated risk names flagged.'
        if 'ELITE' in prefix.upper() or 'HIGH CONVICTION' in prefix.upper():
            try:
                from backend.intelligence.institutional_language import EMPTY_ELITE_MESSAGE
                return EMPTY_ELITE_MESSAGE
            except Exception:
                return 'No High Conviction setups — capital preservation mode.'
        return 'No items in this tier.'
    return cleaned


def _parse_action_sections(text: str) -> Dict[str, str]:
    """Parse WATCH / AVOID / HIGH CONVICTION blocks — header may sit on its own line."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    header_map = {
        'WATCH': 'WATCH',
        'AVOID': 'AVOID',
        'ELITE': 'HIGH CONVICTION',
        'HIGH CONVICTION': 'HIGH CONVICTION',
    }
    sections: Dict[str, str] = {}
    current: Optional[str] = None
    body_lines: List[str] = []

    def _flush() -> None:
        nonlocal current, body_lines
        if current is not None:
            sections[current] = '\n'.join(body_lines).strip()
        current = None
        body_lines = []

    for ln in lines:
        upper = ln.upper().strip()
        matched_header = None
        inline_body = ''
        for key, canonical in header_map.items():
            if upper == key or upper == f'{key}:' or upper.startswith(f'{key}:'):
                matched_header = canonical
                if ':' in ln:
                    _, _, inline_body = ln.partition(':')
                    inline_body = inline_body.strip()
                break
        if matched_header:
            _flush()
            current = matched_header
            if inline_body:
                body_lines = [inline_body]
            continue
        if current is not None:
            body_lines.append(ln)
    _flush()
    return sections


def format_action_plan(raw: str, *, max_lines: int = 3) -> str:
    """Compress action plan to posture lines (WATCH / AVOID / posture)."""
    fallback = (
        '🛡️ <b>POSTURE</b>\n'
        'Capital preservation — monitor watchlist for confirmation.\n'
        'No tactical entries until regime clarity improves.'
    )
    text = str(raw or '').strip()
    if not text or text.lower() in ('none', 'null', 'nan', 'n/a'):
        return fallback

    sections = _parse_action_sections(text)
    order = ('WATCH', 'AVOID', 'HIGH CONVICTION')
    picked: List[str] = []
    for key in order:
        if key not in sections:
            continue
        sanitized = _sanitize_section_line(key, sections[key])
        if sanitized and sanitized != '…':
            picked.append(f'{key}: {sanitized}')
        if len(picked) >= max_lines:
            break

    if not picked:
        lines = [ln for ln in text.splitlines() if ln.strip() and ln.strip() != '…']
        picked = lines[:max_lines]

    if not picked:
        return fallback
    body = '\n'.join(picked[:max_lines])
    if body.strip() in ('…', '...'):
        return fallback
    return f'🛡️ <b>POSTURE</b>\n{body}'


def format_sectors(sectors: dict) -> str:
    s = sectors if isinstance(sectors, dict) else {}
    bullish = ', '.join(s.get('bullish') or []) or 'Not identified'
    bearish = ', '.join(s.get('bearish') or []) or 'Not identified'
    strength = s.get('rotation_strength') or '—'
    return (
        f'🔄 <b>SECTOR ROTATION</b>\n'
        f'<i>Strength: {strength}</i>\n\n'
        f'🟢 <b>Bullish:</b> {bullish}\n'
        f'🔴 <b>Bearish:</b> {bearish}'
    )


def format_risks(risks: list, *, max_lines_per_ticker: int = 2) -> str:
    items = risks if isinstance(risks, list) else []
    if not items:
        return '<i>No risks identified in current analysis.</i>'
    try:
        from backend.intelligence.institutional_language import compress_risk_logic
    except Exception:
        compress_risk_logic = None  # type: ignore
    rows = []
    for i, r in enumerate(items[:8], 1):
        r = r if isinstance(r, dict) else {}
        sym = r.get('symbol') or 'UNKNOWN'
        if compress_risk_logic:
            logic = compress_risk_logic(str(r.get('logic') or ''), max_lines=max_lines_per_ticker)
        else:
            logic = institutionalize(str(r.get('logic') or 'No rationale').strip())
            logic_lines = [x.strip() for x in logic.splitlines() if x.strip()][:max_lines_per_ticker]
            logic = '\n   '.join(f'<i>{ln[:140]}</i>' for ln in logic_lines)
        if compress_risk_logic:
            logic_lines = [x.strip() for x in logic.splitlines() if x.strip()][:max_lines_per_ticker]
            if not logic_lines:
                logic_lines = ['No rationale']
            logic_block = '\n   '.join(f'<i>{ln[:140]}</i>' for ln in logic_lines)
        else:
            logic_block = logic
        rows.append(f'{i}. 🔴 <b>{sym}</b>\n   {logic_block}')
    return '\n'.join(rows)


def _single_action_label(item: dict) -> str:
    """One user-facing label — avoid duplicate [WATCH] [WATCH]."""
    o = item if isinstance(item, dict) else {}
    action = str(o.get('action') or 'WATCH').upper().strip()
    tier = str(o.get('display_tier') or '').upper().strip()
    try:
        from backend.intelligence.institutional_language import tier_display_label
        tier_label = tier_display_label(tier) if tier else ''
    except Exception:
        tier_label = tier.replace('_', ' ').title() if tier else ''
    if tier_label and tier_label.upper() == action:
        return f'[{tier_label}]'
    if tier_label:
        return f'[{tier_label}]'
    return f'[{action}]'


def format_opportunity(item: dict) -> str:
    o = item if isinstance(item, dict) else {}
    sym = o.get('symbol') or '?'
    logic = institutionalize(str(o.get('logic') or '')[:180])
    label = _single_action_label(o)
    try:
        from backend.intelligence.institutional_language import format_signal_status_line
        status_line = format_signal_status_line(o)
    except Exception:
        conf = o.get('display_confidence') or o.get('confidence') or 'MEDIUM'
        status_line = f'{label} · {conf}'
    return f'• <b>{sym}</b> {label}\n  {status_line}\n  <i>{logic}</i>'


def format_opps_tiered(tiers: dict, *, include_elite: bool = True) -> str:
    tiers = tiers if isinstance(tiers, dict) else {}
    sections = []
    if include_elite:
        elite = tiers.get('elite') or []
        if elite:
            blocks = [format_opportunity(o) for o in elite[:5]]
            sections.append('🎯 <b>HIGH CONVICTION</b>\n' + '\n\n'.join(blocks))
    watch = tiers.get('watch') or []
    if watch:
        compressed = tiers.get('watch_compressed')
        if compressed:
            sections.append(f'👀 <b>WATCH</b>\n<i>{compressed}</i>')
        else:
            blocks = [format_opportunity(o) for o in watch[:6]]
            sections.append('👀 <b>WATCH</b>\n' + '\n\n'.join(blocks))
    avoid = tiers.get('avoid') or []
    if avoid:
        blocks = [format_opportunity(o) for o in avoid[:4]]
        sections.append('🔴 <b>AVOID</b>\n' + '\n\n'.join(blocks))
    if sections:
        return '\n\n'.join(sections)
    try:
        from backend.intelligence.institutional_language import elite_empty_block
        return elite_empty_block()
    except Exception:
        return '<i>No ranked setups — capital preservation mode.</i>'


def _status_stale_suffix(stale: bool) -> str:
    return ' ⚠️' if stale else ''


def _status_feed_line(label: str, row: Optional[dict]) -> str:
    row = row if isinstance(row, dict) else {}
    age = row.get('age_display') or row.get('status') or '—'
    stale = bool(row.get('stale')) or row.get('status') in ('stale', 'missing')
    return f"{label}: {age}{_status_stale_suffix(stale)}"


def _status_cache_line(label: str, row: Optional[dict]) -> str:
    row = row if isinstance(row, dict) else {}
    status = str(row.get('status') or 'missing')
    if status == 'static_wishlist':
        return f"{label}: static wishlist"
    if status == 'optional':
        reason = row.get('reason') or 'not refreshed by full refresh'
        return f"{label}: optional / {reason}"
    age = row.get('age_display') or status or '-'
    stale = bool(row.get('stale')) or status in ('stale', 'missing')
    suffix = _status_stale_suffix(stale)
    reason = row.get('reason')
    if stale and reason:
        return f"{label}: {age} ({status}){suffix} — {reason}"
    return f"{label}: {age} ({status}){suffix}"


def _active_book_count_label() -> str:
    try:
        from backend.lifecycle.prediction_lifecycle_engine import get_active_predictions_payload

        payload = get_active_predictions_payload()
        count = payload.get('count')
        if count is None:
            preds = payload.get('predictions') or []
            count = len(preds) if isinstance(preds, list) else 0
        source = payload.get('source') or 'active_predictions'
        return f"active_book {int(count)} ({source})"
    except Exception:
        return "active_book unavailable"


def _status_runtime_snapshot_line(row: Optional[dict]) -> str:
    row = row if isinstance(row, dict) else {}
    age = row.get('age_display') or 'freshness unavailable'
    stale = bool(row.get('stale'))
    if row.get('live_lite_snapshot') or row.get('source') == 'live_lite_scanner':
        return f"Runtime snapshot: {age} (fresh/lite from scanner)"
    tier = str(row.get('health_tier') or '').lower()
    status = 'stale' if stale else 'fresh'
    if tier and tier not in ('healthy', 'fresh'):
        status = tier
    return f"Runtime snapshot: {age} ({status}){_status_stale_suffix(stale)}"


def format_status(runtime_state: dict) -> str:
    rs = runtime_state if isinstance(runtime_state, dict) else {}
    lc = rs.get('lifecycle') or {}
    session = rs.get('session') or {}
    fresh = rs.get('snapshot_freshness') or {}
    tg = rs.get('telegram_metrics') or {}
    ai = rs.get('provider_health') or {}
    sched = rs.get('scheduler') or {}
    scanner = rs.get('scanner_health') or {}
    pipeline = rs.get('pipeline') or {}
    counts = rs.get('prediction_counts') or {}
    wr = rs.get('win_rate') or {}
    alert = rs.get('alert_eligibility') or {}
    sources = rs.get('source_freshness') or {}
    brain = rs.get('brain_age') or {}
    intel = ((rs.get('intelligence_freshness') or {}).get('rows') or {})
    primary = rs.get('primary_state') or '—'
    secondary = rs.get('secondary_flags') or {}
    flags = [k for k, v in secondary.items() if v]
    flag_text = ', '.join(flags) if flags else 'none'

    lines = [
        '<b>📡 System Status</b>',
        '<b>Header</b>',
        f"State: <code>{primary}</code> · Lifecycle: <code>{lc.get('lifecycle_state') or '—'}</code>",
        f"Session: {session.get('session_display') or '—'}",
    ]
    age = fresh.get('age_display') or 'freshness unavailable'
    tier = fresh.get('health_tier') or ('stale' if fresh.get('stale') else 'healthy')
    lines.append(f"Snapshot: {age} ({tier}){_status_stale_suffix(bool(fresh.get('stale')))}")
    lines.append(scanner.get('display') or 'Scanner: —')
    alert_line = 'eligible' if alert.get('eligible') else 'blocked'
    if alert.get('execution_eligible') is False and alert.get('eligible') and not alert.get('watchlist_only'):
        alert_line = 'intel-only'
    suppressed_today = alert.get('suppression_count') or tg.get('suppressed_today', 0)
    lines.append(
        f"Alerts: {alert_line} · sent {tg.get('alerts_sent_today', 0)} · "
        f"suppressed {suppressed_today}"
    )
    if alert.get('last_suppression_reason'):
        lines.append(f"Last suppression reason: {alert.get('last_suppression_reason')}")
    if alert.get('duplicate_alerts_avoided') or alert.get('ai_calls_avoided'):
        lines.append(
            f"Duplicate alerts avoided: {alert.get('duplicate_alerts_avoided', 0)} · "
            f"AI calls avoided: {alert.get('ai_calls_avoided', 0)}"
        )

    lines.append('<b>Core runtime freshness</b>')
    lines.append(_status_runtime_snapshot_line(fresh))
    lines.append(_status_feed_line('Scanner', sources.get('scanner')))

    lines.append('<b>Intelligence freshness</b>')
    lines.append(_status_cache_line('News', intel.get('news') or sources.get('news')))
    lines.append(_status_cache_line('Budget', intel.get('budget')))
    lines.append(_status_cache_line('Theme catalysts', intel.get('theme')))
    lines.append(_status_cache_line('Catalysts', intel.get('catalysts')))
    lines.append(_status_cache_line('AIHub brain', intel.get('aihub_brain') or brain))
    lines.append(_status_cache_line('AIHub govt', intel.get('aihub_govt')))
    lines.append(_status_cache_line('AIHub market', intel.get('aihub_market')))

    lines.append('<b>Optional</b>')
    lines.append(_status_cache_line('Legacy report cache', intel.get('legacy_report')))
    lines.append(_status_cache_line('Broker', intel.get('broker')))
    lines.append('<b>Runtime</b>')
    if sched.get('phase'):
        lines.append(f"Scheduler: {sched.get('phase')}")
    lines.append(f"DB: {rs.get('db_size_display') or '—'}")
    lines.append(f"Flags: {flag_text}")

    stalled = pipeline.get('stalled_stages') or []
    stage_rows = pipeline.get('stages') or {}
    if stalled:
        parts = []
        for name in stalled[:4]:
            row = stage_rows.get(name) or {}
            age_m = row.get('age_minutes')
            parts.append(f"{name} {age_m}m" if age_m is not None else name)
        lines.append(f"Pipeline stalled: {', '.join(parts)}")
    elif pipeline.get('last_stage'):
        lines.append(f"Pipeline: last {pipeline.get('last_stage')}")

    lines.append(f"AI providers: {ai.get('status', 'unknown')}")
    wr_disp = wr.get('win_rate_display') or 'Awaiting statistical confidence'
    if wr_disp in ('—', '—%', 'None', 'null', 'unknown'):
        wr_disp = 'Awaiting statistical confidence'
    sections = (rs.get('metrics') or {}).get('sections') or {}
    live = sections.get('live_session') or {}
    hist = sections.get('historical_calibration') or {}
    archived = sections.get('archived') or {}
    if sections:
        lines.append('<b>Metrics</b>')
        active_book_label = _active_book_count_label()
        live_pending = live.get('active_predictions', counts.get('pending', 0))
        lines.append(
            f"LIVE: {active_book_label} · live_session_pending {live_pending} · "
            f"resolved today {live.get('resolved_today', 0)}"
        )
        lines.append(
            f"CALIBRATION: sample {hist.get('evaluated_sample', counts.get('evaluated', 0))} · "
            f"{hist.get('wins', counts.get('wins', 0))}W/{hist.get('losses', counts.get('losses', 0))}L · "
            f"WR {hist.get('win_rate_display') or wr_disp}"
        )
        lines.append(
            f"ARCHIVED: expired {archived.get('expired', counts.get('expired', 0))} · "
            f"neutralized {archived.get('neutralized', counts.get('neutralized', 0))}"
        )
    else:
        lines.append(
            f"Metrics: resolved {counts.get('resolved', 0)} "
            f"({counts.get('wins', 0)}W/{counts.get('losses', 0)}L/{counts.get('partials', 0)}P) · "
            f"pending {counts.get('pending', 0)} · WR {wr_disp}"
        )

    blockers = list(alert.get('block_reasons') or [])
    if secondary.get('stale_snapshot') and 'stale_snapshot' not in blockers:
        blockers.append('stale_snapshot')
    if secondary.get('scanner_stalled') and 'scanner_stalled' not in blockers:
        blockers.append('scanner_stalled')
    if blockers:
        lines.append(f"<b>Blockers</b>: {', '.join(blockers[:6])}")
    if session.get('after_hours_mode'):
        lines.append('<i>After-hours: execution alerts suppressed</i>')
    return '\n'.join(lines)


def format_confidence(value: Any) -> str:
    from backend.metrics.format_helpers import safe_confidence
    return safe_confidence(value)


def safe_pct(value: Any, *, decimals: int = 1, fallback: str = 'Awaiting statistical confidence') -> str:
    from backend.metrics.format_helpers import safe_pct as _safe_pct
    return _safe_pct(value, decimals=decimals, fallback=fallback)


def safe_num(value: Any, *, fmt: str = '.1f', fallback: str = 'N/A') -> str:
    from backend.metrics.format_helpers import safe_num as _safe_num
    return _safe_num(value, fmt=fmt, fallback=fallback)


def format_ticker_line(ticker: str, change: Any = None, note: str = '') -> str:
    ch = ''
    if change is not None:
        try:
            ch = f' {float(change):+.2f}%'
        except (TypeError, ValueError):
            pass
    extra = f' — {note}' if note else ''
    return f'• <b>{ticker}</b>{ch}{extra}'


def institutionalize(text: str) -> str:
    try:
        from backend.intelligence.institutional_language import apply_institutional_tone
        return apply_institutional_tone(text)
    except Exception:
        return text


def confirmation_phrase(kind: str = 'processing', *, command: str = '') -> str:
    cmd = str(command or '').lower().strip().lstrip('/')
    if kind == 'in_flight':
        if cmd in ('calibration', 'cal'):
            return '⏳ Calibration request already processing...'
        if cmd in ('brain', 'full', 'all'):
            return '🧠 Analysis already running...'
        if cmd in ('review',):
            return '⏳ Review request already processing...'
        if cmd == 'action':
            return '⏳ Action plan request already processing...'
    phrases = {
        'processing': '⏳ Processing — one moment…',
        'queued': '📋 Queued — duplicate request ignored.',
        'in_flight': '⏳ Command already processing...',
    }
    return phrases.get(kind, phrases['processing'])


def session_notice(runtime_state: Optional[dict] = None) -> str:
    try:
        from backend.intelligence.institutional_language import canonical_session_prefix
        return canonical_session_prefix(runtime_state)
    except Exception:
        pass
    try:
        if runtime_state is None:
            from backend.runtime.runtime_state import get_runtime_state
            runtime_state = get_runtime_state()
        session = (runtime_state or {}).get('session') or {}
        if session.get('after_hours_mode'):
            msg = session.get('session_message') or 'After-hours intelligence mode active'
            return f'🌙 <i>{msg}</i>\n'
        fresh = (runtime_state or {}).get('snapshot_freshness') or {}
        if fresh.get('stale'):
            age = fresh.get('age_display') or 'freshness unavailable'
            return f'⚠️ <i>Snapshot stale — {age}</i>\n'
    except Exception:
        pass
    return ''


def snapshot_meta_line(runtime_state: Optional[dict] = None) -> str:
    try:
        fresh = ((runtime_state or {}).get('snapshot_freshness') or {})
        ver = fresh.get('snapshot_version')
        age = fresh.get('age_display')
        if ver is not None and age:
            stale = ' ⚠️' if fresh.get('stale') else ''
            return f'<i>Snapshot v{ver} · {age}{stale}</i>\n\n'
    except Exception:
        pass
    return ''


def maybe_delayed_loading(command: str) -> Optional[str]:
    """Deprecated immediate loading hint — use delayed_loading.run_with_delayed_loading."""
    return None


def format_elite_response(items: list) -> str:
    if not items:
        try:
            from backend.intelligence.institutional_language import elite_empty_block
            return elite_empty_block()
        except Exception:
            return '<i>No elite setups — capital preservation mode.</i>'
    return format_opps_tiered({'elite': items}, include_elite=True)


class ResponseBuilder:
    """Fluent builder with command-aware limits."""

    def __init__(self, command: str = 'brain'):
        self.command = command
        self._parts: List[str] = []

    def add(self, text: str) -> 'ResponseBuilder':
        if text:
            self._parts.append(text)
        return self

    def build(self) -> str:
        body = '\n\n'.join(self._parts)
        return format_for_command(body, self.command)
