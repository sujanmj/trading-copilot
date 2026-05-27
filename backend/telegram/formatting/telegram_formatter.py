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
    'action': 3,
    'sectors': 12,
    'status': 30,
    'calibration': 25,
    'global': 35,
    'stats': 20,
    'outcomes': 25,
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


def format_for_command(text: str, command: str) -> str:
    cmd = str(command or 'brain').lower().strip().lstrip('/')
    max_lines = COMMAND_LINE_LIMITS.get(cmd, DEFAULT_MAX_LINES)
    out = enforce_line_limit(text, max_lines)
    return enforce_char_limit(out)


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


def format_action_plan(raw: str, *, max_lines: int = 3) -> str:
    """Compress action plan to posture lines (WATCH / AVOID / posture)."""
    text = str(raw or '').strip()
    if not text:
        return (
            '🛡️ <b>POSTURE</b>\n'
            'Capital preservation — monitor watchlist for confirmation.\n'
            'No tactical entries until regime clarity improves.'
        )
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    picked: List[str] = []
    for ln in lines:
        upper = ln.upper()
        for tag in ('WATCH:', 'AVOID:', 'ELITE:', 'HIGH CONVICTION:'):
            if tag in upper:
                head, _, body = ln.partition(':')
                picked.append(f'{head}: {_sanitize_section_line(head, body)}')
                break
        else:
            if any(k in upper for k in ('POSTURE:', 'CAPITAL')):
                picked.append(ln)
        if len(picked) >= max_lines:
            break
    if not picked:
        picked = lines[:max_lines]
    body = '\n'.join(picked[:max_lines])
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
    rows = []
    for i, r in enumerate(items[:8], 1):
        r = r if isinstance(r, dict) else {}
        sym = r.get('symbol') or 'UNKNOWN'
        logic = str(r.get('logic') or 'No rationale').strip()
        logic_lines = [x.strip() for x in logic.splitlines() if x.strip()][:max_lines_per_ticker]
        if not logic_lines:
            logic_lines = ['No rationale']
        logic_block = '\n   '.join(f'<i>{ln[:160]}</i>' for ln in logic_lines[:max_lines_per_ticker])
        rows.append(f'{i}. 🔴 <b>{sym}</b>\n   {logic_block}')
    return '\n\n'.join(rows)


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
    conf = o.get('display_confidence') or o.get('confidence') or 'MEDIUM'
    logic = str(o.get('logic') or '')[:180]
    label = _single_action_label(o)
    return f'• <b>{sym}</b> {label} · {conf}\n  <i>{logic}</i>'


def format_opps_tiered(tiers: dict, *, include_elite: bool = True) -> str:
    tiers = tiers if isinstance(tiers, dict) else {}
    sections = []
    if include_elite:
        elite = tiers.get('elite') or []
        if elite:
            blocks = [format_opportunity(o) for o in elite[:5]]
            sections.append('🎯 <b>ELITE</b>\n' + '\n\n'.join(blocks))
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

    lines = [
        '<b>📡 System Status</b>',
        f"Lifecycle: <code>{lc.get('lifecycle_state') or '—'}</code>",
        f"Session: {session.get('session_display') or '—'}",
    ]
    age = fresh.get('age_display') or 'freshness unavailable'
    tier = fresh.get('health_tier') or ('stale' if fresh.get('stale') else 'healthy')
    lines.append(f"Snapshot: {age} ({tier})")
    lines.append(scanner.get('display') or 'Scanner: —')
    stalled = pipeline.get('stalled_stages') or []
    if stalled:
        lines.append(f"Pipeline stalled: {', '.join(stalled[:4])}")
    elif pipeline.get('last_stage'):
        lines.append(f"Pipeline: last {pipeline.get('last_stage')}")
    if sched.get('phase'):
        lines.append(f"Scheduler: {sched.get('phase')}")
    lines.append(f"AI: {ai.get('status', 'unknown')}")
    wr_disp = wr.get('win_rate_display') or '—'
    lines.append(
        f"Metrics: resolved {counts.get('resolved', 0)} "
        f"({counts.get('wins', 0)}W/{counts.get('losses', 0)}L) · WR {wr_disp}"
    )
    lines.append(
        f"Alerts today: sent {tg.get('alerts_sent_today', 0)} · "
        f"suppressed {tg.get('suppressed_today', 0)}"
    )
    if session.get('after_hours_mode'):
        lines.append('<i>After-hours: refresh active · execution alerts suppressed</i>')
    if alert.get('block_reasons'):
        lines.append(f"Alert blocks: {', '.join(alert.get('block_reasons')[:3])}")
    return '\n'.join(lines)


def format_confidence(value: Any) -> str:
    if value is None:
        return 'N/A'
    try:
        n = float(str(value).replace('/10', '').strip())
        return f'{n:.1f}/10'
    except (TypeError, ValueError):
        return str(value)


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


def confirmation_phrase(kind: str = 'processing') -> str:
    phrases = {
        'processing': '⏳ Processing — one moment…',
        'queued': '📋 Queued — duplicate request ignored.',
    }
    return phrases.get(kind, phrases['processing'])


def session_notice(runtime_state: Optional[dict] = None) -> str:
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
