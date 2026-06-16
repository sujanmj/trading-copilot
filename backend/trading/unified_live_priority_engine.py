"""
Unified live priority engine — Stage 50P.

Single ranking path for /today, /tomorrow, /premarket, /catalysts, /tradecard.

Decision order: catalyst → scanner → volume → sector → freshness → avoid → entry → tradecard
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.utils.config import DATA_DIR

IST = ZoneInfo('Asia/Kolkata')
STAGE = '50P'
SCANNER_FILE = DATA_DIR / 'scanner_data.json'
FINAL_CONF_FILE = DATA_DIR / 'final_confidence_report.json'

VALID_MODES = frozenset({'today', 'tomorrow', 'premarket'})


def _now_iso() -> str:
    return datetime.now(IST).replace(microsecond=0).isoformat()


def _normalize_ticker(value: object) -> str:
    return str(value or '').strip().upper()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _freshness_meta() -> dict[str, Any]:
    try:
        from backend.analytics.unified_decision_engine import get_feed_freshness_meta

        return get_feed_freshness_meta() or {}
    except Exception:
        return {}


def _live_registry() -> dict[str, str]:
    try:
        from backend.analytics.unified_decision_engine import build_live_rejection_set

        return build_live_rejection_set() or {}
    except Exception:
        return {}


def _scanner_signals() -> list[dict[str, Any]]:
    scanner = _load_json(SCANNER_FILE)
    out: list[dict[str, Any]] = []
    for sig in (scanner or {}).get('top_signals') or (scanner or {}).get('signals') or []:
        if isinstance(sig, dict):
            out.append(sig)
    return out


def _catalyst_priority_map() -> dict[str, dict[str, Any]]:
    try:
        from backend.intelligence.stock_catalyst_radar import get_clean_catalyst_radar

        radar = get_clean_catalyst_radar()
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in radar.get('priority_list') or radar.get('items') or []:
        if not isinstance(row, dict):
            continue
        sym = _normalize_ticker(row.get('ticker'))
        if sym and sym not in out:
            out[sym] = row
    return out


def _sector_support(sym: str) -> float:
    intel = _load_json(DATA_DIR / 'intelligence.json')
    sectors = (intel or {}).get('sector_rotation') or {}
    bullish = {_normalize_ticker(s) for s in (sectors.get('bullish') or [])}
    bearish = {_normalize_ticker(s) for s in (sectors.get('bearish') or [])}
    if sym in bullish:
        return 10.0
    if sym in bearish:
        return 2.0
    return 5.0


def _entry_status(sym: str, scanner_row: dict[str, Any]) -> tuple[str, bool]:
    """Return trade-card style entry status and whether entry is missed."""
    try:
        from backend.trading.trade_card_engine import MIN_RR, MIN_VOLUME_RATIO, detect_entry_missed, _compute_plan

        plan = _compute_plan(scanner_row)
        missed, _ = detect_entry_missed(
            price=plan['price'],
            change_pct=plan['change_pct'],
            volume_ratio=plan['volume_ratio'],
            day_high=plan.get('day_high'),
            vwap=plan.get('vwap'),
            open_price=plan.get('open_price'),
            risk_reward=plan['risk_reward'],
            sl_pct=plan['sl_pct'],
        )
        if missed:
            return 'ENTRY_MISSED', True
        if plan['sl_pct'] > 1.2:
            return 'NO_ACTIVE_ENTRY', True
        if plan['risk_reward'] < MIN_RR:
            return 'NO_TRADE', True
        if plan['volume_ratio'] < MIN_VOLUME_RATIO:
            return 'WAIT_FOR_VOLUME', False
        return 'VALID_ENTRY', False
    except Exception:
        return 'NO_TRADE', False


def _unified_score(
    sym: str,
    *,
    catalyst: Optional[dict[str, Any]],
    scanner_row: Optional[dict[str, Any]],
    meta: dict[str, Any],
    registry: dict[str, str],
    fc_only: bool,
) -> dict[str, Any]:
    score = 0.0
    why: list[str] = []
    risk: list[str] = []
    supports: set[str] = set()

    if sym in registry:
        return {
            'ticker': sym,
            'unified_score': 0,
            'action': 'AVOID',
            'why': [f"Live avoid: {registry[sym][:80]}"],
            'risk': risk,
            'supports': [],
            'entry_status': 'AVOID',
            'entry_missed': False,
            'fc_only': fc_only,
        }

    if catalyst:
        supports.add('catalyst')
        cat_score = float(catalyst.get('score') or 0)
        score += min(40.0, cat_score * 0.45)
        why.append(f"Fresh catalyst: {str(catalyst.get('catalyst_type') or '').replace('_', ' ').lower()}")
        side = str(catalyst.get('side') or 'NEUTRAL').upper()
        if side in ('BEARISH', 'RISK'):
            score -= 25.0
            risk.append('Bearish catalyst side')

    if scanner_row:
        supports.add('scanner')
        chg = abs(_safe_float(scanner_row.get('change_percent')))
        vol = _safe_float(scanner_row.get('volume_ratio'), 1.0)
        strength = str(scanner_row.get('strength') or '').upper()
        score += min(35.0, chg * 2.5 + vol * 6.0 + (8.0 if strength == 'ULTRA' else 0.0))
        why.append('Live scanner confirmation')
        if vol >= 1.0:
            score += 6.0
            why.append(f'Volume participation {vol:.1f}x')
        if vol < 0.8:
            risk.append('Volume below participation threshold')

    sector = _sector_support(sym)
    score += sector * 0.8
    if sector >= 10:
        supports.add('sector')
        why.append('Sector support aligned')

    if meta.get('scanner_fresh') and meta.get('report_stale'):
        if fc_only and not scanner_row and not catalyst:
            score -= 40.0
            risk.append('Stale report-only name — excluded from live priority')
        elif scanner_row or catalyst:
            score += 8.0
            why.append('Live scanner fresh — prioritized over stale report')

    entry_status = 'NO_TRADE'
    entry_missed = False
    if scanner_row:
        entry_status, entry_missed = _entry_status(sym, scanner_row)
        if entry_missed:
            score -= 12.0
            risk.append('Entry missed on live move')

    action = 'WATCH_FOR_ENTRY'
    if entry_status == 'AVOID' or sym in registry:
        action = 'AVOID'
    elif score >= 68 and len(supports) >= 2 and not entry_missed and entry_status == 'VALID_ENTRY':
        action = 'BUY_CANDIDATE'
    elif entry_missed or entry_status in ('NO_TRADE', 'NO_ACTIVE_ENTRY'):
        action = 'WATCH_FOR_ENTRY'

    return {
        'ticker': sym,
        'unified_score': max(0, int(round(score))),
        'action': action,
        'why': why[:5] or ['Live priority candidate'],
        'risk': risk[:4],
        'supports': sorted(supports),
        'entry_status': entry_status,
        'entry_missed': entry_missed,
        'fc_only': fc_only,
        'catalyst': catalyst,
        'scanner_row': scanner_row,
    }


def build_unified_priority(mode: str = 'today') -> dict[str, Any]:
    """Build unified ranked priority payload for today/tomorrow/premarket."""
    normalized = str(mode or 'today').strip().lower()
    if normalized not in VALID_MODES:
        normalized = 'today'

    meta = _freshness_meta()
    registry = _live_registry()
    catalyst_map = _catalyst_priority_map()
    scanner_rows = _scanner_signals()
    scanner_index = {
        _normalize_ticker(r.get('ticker') or r.get('symbol')): r
        for r in scanner_rows
        if _normalize_ticker(r.get('ticker') or r.get('symbol'))
    }

    fc = _load_json(FINAL_CONF_FILE)
    fc_tickers = {
        _normalize_ticker(r.get('ticker'))
        for r in (fc.get('top_candidates') or fc.get('rows') or [])
        if isinstance(r, dict) and _normalize_ticker(r.get('ticker'))
    }

    live_confirmed = set(catalyst_map.keys()) | set(scanner_index.keys())
    universe: set[str] = set(live_confirmed)

    if not (meta.get('scanner_fresh') and meta.get('report_stale')):
        universe |= fc_tickers
    else:
        # Stale report names only when also live-confirmed.
        universe |= (fc_tickers & live_confirmed)

    ranked: list[dict[str, Any]] = []
    for sym in universe:
        if not sym:
            continue
        catalyst = catalyst_map.get(sym)
        scanner_row = scanner_index.get(sym)
        fc_only = sym in fc_tickers and sym not in live_confirmed
        if fc_only and meta.get('scanner_fresh') and meta.get('report_stale'):
            continue
        row = _unified_score(
            sym,
            catalyst=catalyst,
            scanner_row=scanner_row,
            meta=meta,
            registry=registry,
            fc_only=fc_only,
        )
        ranked.append(row)

    ranked.sort(
        key=lambda r: (
            0 if r.get('action') == 'AVOID' else 1,
            int(r.get('unified_score') or 0),
        ),
        reverse=True,
    )

    top_pick: dict[str, Any] | None = None
    decision = 'NO_CLEAN_CANDIDATE'
    for row in ranked:
        if row.get('action') == 'AVOID':
            continue
        top_pick = row
        decision = str(row.get('action') or 'WATCH_FOR_ENTRY')
        break

    missed = [r for r in ranked if r.get('entry_missed') and r.get('action') != 'AVOID']
    valid = [r for r in ranked if r.get('entry_status') == 'VALID_ENTRY' and r.get('action') != 'AVOID']

    return {
        'ok': True,
        'stage': STAGE,
        'mode': normalized,
        'generated_at': _now_iso(),
        'freshness_meta': meta,
        'ranked_candidates': ranked[:25],
        'top_pick': top_pick,
        'decision': decision,
        'all_entry_missed': bool(missed) and not valid,
        'missed_candidates': missed[:8],
        'live_confirmed': sorted(live_confirmed),
    }


def format_today_unified(payload: Optional[dict[str, Any]] = None) -> str:
    """Telegram body for /today using unified live priority."""
    data = payload or build_unified_priority(mode='today')
    lines = ['<b>AstraEdge — Today</b>', '']

    top = data.get('top_pick')
    decision = data.get('decision') or 'NO_CLEAN_CANDIDATE'
    missed = data.get('missed_candidates') or []

    if data.get('all_entry_missed') and missed:
        names = '/'.join(str(r.get('ticker') or '?') for r in missed[:5])
        lines.extend([
            '<b>NO VALID ENTRY NOW</b>',
            f'Top missed: {names}',
            'Next action: wait pullback or tomorrow catalyst watch.',
        ])
        return '\n'.join(lines)

    if top and decision != 'NO_CLEAN_CANDIDATE':
        action = str(top.get('action') or 'WATCH_FOR_ENTRY').replace('_', ' ')
        lines.extend([
            '<b>Top candidate:</b>',
            f"{top.get('ticker')} — {action}",
            f"Score: {top.get('unified_score', '—')}",
            '',
            '<b>Why:</b>',
        ])
        for item in top.get('why') or []:
            lines.append(f'• {item}')
        if top.get('risk'):
            lines.extend(['', '<b>Risk:</b>'])
            for item in top.get('risk') or []:
                lines.append(f'• {item}')
    else:
        lines.extend([
            '<b>No clean candidate</b>',
            'Nothing meets live catalyst/scanner confluence yet.',
            'Review watch names or refresh when scanner updates.',
        ])

    avoid = [r for r in (data.get('ranked_candidates') or []) if r.get('action') == 'AVOID']
    if avoid:
        lines.extend(['', '<b>Avoid:</b>'])
        for row in avoid[:5]:
            reason = (row.get('risk') or row.get('why') or ['weak signal'])[0]
            lines.append(f"• {row.get('ticker')} — {reason}")

    return '\n'.join(lines)


def apply_unified_priority_to_ranked(
    ranked: list[dict[str, Any]],
    *,
    mode: str,
    sources: dict[str, Any],
) -> list[dict[str, Any]]:
    """Re-order stock decision ranked rows using unified live priority when scanner fresh."""
    meta = sources.get('_freshness_meta') or _freshness_meta()
    if not (meta.get('scanner_fresh') and meta.get('report_stale')):
        return ranked

    unified = build_unified_priority(mode=mode if mode in VALID_MODES else 'today')
    order = {
        _normalize_ticker(r.get('ticker')): idx
        for idx, r in enumerate(unified.get('ranked_candidates') or [])
    }
    live_set = set(unified.get('live_confirmed') or [])

    filtered: list[dict[str, Any]] = []
    for row in ranked:
        sym = _normalize_ticker(row.get('ticker'))
        supports = set(row.get('supports') or [])
        fc_only = 'final_confidence' in supports and 'scanner' not in supports and sym not in live_set
        if fc_only:
            continue
        filtered.append(row)

    if not filtered:
        filtered = list(ranked)

    def sort_key(row: dict[str, Any]) -> tuple[int, int, int]:
        sym = _normalize_ticker(row.get('ticker'))
        u_idx = order.get(sym, 999)
        u_score = 0
        for ur in unified.get('ranked_candidates') or []:
            if _normalize_ticker(ur.get('ticker')) == sym:
                u_score = int(ur.get('unified_score') or 0)
                break
        priority = {'BUY_CANDIDATE': 4, 'WATCH_FOR_ENTRY': 3, 'AVOID': 1}
        return (
            0 if u_idx == 999 else 1,
            u_score,
            priority.get(str(row.get('action') or ''), 0),
            int(row.get('score') or 0),
        )

    return sorted(filtered, key=sort_key, reverse=True)


def pick_tradecard_candidate(
    *,
    registry: Optional[dict[str, str]] = None,
    scanner: Optional[dict[str, Any]] = None,
) -> tuple[Optional[str], str]:
    """
    Pick best trade-card ticker using unified priority.

    Order: catalyst+scanner confirmed → scanner-only → stale report last (skipped when live fresh).
    """
    reg = registry if registry is not None else _live_registry()
    scan = scanner if scanner is not None else _load_json(SCANNER_FILE)
    scan_index = {
        _normalize_ticker(r.get('ticker') or r.get('symbol')): r
        for r in (scan or {}).get('top_signals') or (scan or {}).get('signals') or []
        if isinstance(r, dict) and _normalize_ticker(r.get('ticker') or r.get('symbol'))
    }

    unified = build_unified_priority(mode='today')
    for row in unified.get('ranked_candidates') or []:
        sym = _normalize_ticker(row.get('ticker'))
        if not sym or sym in reg:
            continue
        if row.get('action') == 'AVOID':
            continue
        if row.get('entry_status') == 'AVOID':
            continue
        if row.get('supports') and 'catalyst' in (row.get('supports') or []) and sym in scan_index:
            return sym, 'unified_catalyst_scanner'
        if sym in scan_index:
            return sym, 'unified_scanner'

    for row in unified.get('ranked_candidates') or []:
        sym = _normalize_ticker(row.get('ticker'))
        if sym and sym not in reg and row.get('action') != 'AVOID' and sym in scan_index:
            return sym, 'unified_fallback_scanner'

    try:
        from backend.intelligence.stock_catalyst_radar import pick_catalyst_tradecard_candidate

        return pick_catalyst_tradecard_candidate(registry=reg)
    except Exception:
        return None, 'no_unified_candidate'
