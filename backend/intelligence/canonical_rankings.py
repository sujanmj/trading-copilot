"""
Canonical ranked opportunity feed — single source for Brain, Action Plan, and /opps.

All recommendation surfaces derive from rank_opportunities() plus elite watchlist.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set

from backend.orchestration.opportunity_filter import (
    DEFAULT_OPPS_LIMIT,
    ELITE_ALERTS_FILE,
    rank_opportunities,
    rank_opportunities_tiered,
)

ACTION_PLAN_SYMBOL = re.compile(r'\*\*([A-Z][A-Z0-9&.-]{2,14})\*\*')

GENERIC_WORDS = frozenset({
    'NIFTY', 'BANKNIFTY', 'SENSEX', 'INDIA', 'MARKET', 'INDEX', 'CASH', 'BUY', 'SELL',
    'FOCUS', 'WATCH', 'AVOID', 'HOLD', 'IST', 'EOD', 'AI', 'OPS', 'HTTP', 'THE', 'AND',
    'FOR', 'WITH', 'FROM', 'NEXT', 'DAY', 'RISK', 'SIZE', 'STOP', 'LOSS', 'TARGET',
})


def get_top_ranked_signals(
    intel: Optional[dict] = None,
    *,
    limit: int = DEFAULT_OPPS_LIMIT,
) -> List[dict]:
    """Top-N ranked scanner/lifecycle opportunities (same feed as Telegram /opps)."""
    return rank_opportunities(intel, limit=limit)


def get_elite_rankings(*, limit: int = 10) -> List[dict]:
    """Elite meta-labeler watchlist entries."""
    if not ELITE_ALERTS_FILE.exists():
        return []
    try:
        data = json.loads(ELITE_ALERTS_FILE.read_text(encoding='utf-8'))
    except Exception:
        return []
    out: List[dict] = []
    for row in data.get('elite_signals') or []:
        if not isinstance(row, dict):
            continue
        sym = str(row.get('symbol') or row.get('Stock') or row.get('ticker') or '').upper()
        if not sym:
            continue
        out.append({**row, 'symbol': sym})
        if len(out) >= limit:
            break
    return out


def get_ranked_symbol_set(intel: Optional[dict] = None, *, limit: int = DEFAULT_OPPS_LIMIT) -> Set[str]:
    symbols: Set[str] = set()
    for item in get_top_ranked_signals(intel, limit=limit):
        sym = str(item.get('symbol') or item.get('ticker') or '').upper()
        if sym:
            symbols.add(sym)
    for item in get_elite_rankings(limit=limit):
        sym = str(item.get('symbol') or '').upper()
        if sym:
            symbols.add(sym)
    return symbols


def get_action_plan_symbols(intel: Optional[dict] = None, *, limit: int = 5) -> List[str]:
    """Ordered unique symbols for action-plan synthesis (ranked first, then elite)."""
    symbols: List[str] = []
    seen: Set[str] = set()
    for item in get_top_ranked_signals(intel, limit=limit):
        sym = str(item.get('symbol') or item.get('ticker') or '').upper()
        if sym and sym not in seen:
            symbols.append(sym)
            seen.add(sym)
    for item in get_elite_rankings(limit=limit):
        sym = str(item.get('symbol') or '').upper()
        if sym and sym not in seen:
            symbols.append(sym)
            seen.add(sym)
    return symbols[:limit]


def extract_symbols_from_text(text: str) -> List[str]:
    """Parse explicit **TICKER** markers from canonical action-plan lines."""
    if not text:
        return []
    found: List[str] = []
    seen: Set[str] = set()
    for match in ACTION_PLAN_SYMBOL.finditer(str(text)):
        sym = match.group(1).upper()
        if sym in GENERIC_WORDS or sym in seen:
            continue
        seen.add(sym)
        found.append(sym)
    return found


def validate_action_plan_symbols(action_plan: str, allowed: Set[str]) -> List[str]:
    """Symbols referenced in action_plan that are not in the ranked/elite pool."""
    unknown: List[str] = []
    for sym in extract_symbols_from_text(action_plan):
        if sym not in allowed:
            unknown.append(sym)
    return unknown


def build_action_plan_text(symbols: List[str], ranked: List[dict], intel: Optional[dict] = None) -> str:
    intel = intel if isinstance(intel, dict) else {}
    tiers = rank_opportunities_tiered(intel)
    elite = tiers.get('elite') or get_elite_rankings(limit=5)
    watch = tiers.get('watch') or []
    avoid_tier = tiers.get('avoid') or []

    def _syms(items: List[dict], limit: int = 4) -> str:
        out = []
        for item in items[:limit]:
            sym = str(item.get('symbol') or item.get('ticker') or '').upper()
            if sym:
                out.append(sym)
        return ', '.join(out) if out else 'None flagged'

    watch_syms = _syms(watch or ranked[:4])
    elite_syms = _syms(elite)

    sectors = intel.get('sector_rotation') if isinstance(intel.get('sector_rotation'), dict) else {}
    risks = intel.get('risks_and_avoids') if isinstance(intel.get('risks_and_avoids'), list) else []
    avoid_items = [str(o.get('symbol') or '').upper() for o in avoid_tier[:4] if o.get('symbol')]
    for r in risks[:4]:
        if isinstance(r, dict):
            sym = str(r.get('symbol') or '').upper()
            if sym and sym not in ('UNKNOWN', 'MACRO', 'NEWS') and sym not in avoid_items:
                avoid_items.append(sym)
    if not avoid_items:
        bearish = sectors.get('bearish') if isinstance(sectors.get('bearish'), list) else []
        avoid_items = [str(s).upper() for s in bearish[:3]]
    avoid = ', '.join(avoid_items) or 'Extended momentum without volume confirmation'

    watch_line = (
        f"Monitor for confirmation: {watch_syms}."
        if watch_syms != 'None flagged'
        else 'No active watchlist — await scanner confirmation.'
    )
    try:
        from backend.intelligence.institutional_language import EMPTY_ELITE_MESSAGE
        empty_elite = EMPTY_ELITE_MESSAGE
    except Exception:
        empty_elite = (
            'No high-conviction opportunities detected. Capital preservation mode active.'
        )
    elite_line = (
        f"High-conviction swing setups: {elite_syms}."
        if elite_syms != 'None flagged'
        else empty_elite
    )

    if symbols:
        primary = []
        for idx, sym in enumerate(symbols[:3], 1):
            item = next(
                (x for x in ranked if str(x.get('symbol') or x.get('ticker') or '').upper() == sym),
                {},
            )
            conf = item.get('display_confidence') or item.get('confidence') or 'MEDIUM'
            primary.append(f"**{sym}** ({conf})")
        watch_syms = ', '.join(symbols[:4]) if symbols else watch_syms

    return (
        f"WATCH:\n{watch_line}\n\n"
        f"AVOID:\n{avoid}\n\n"
        f"ELITE:\n{elite_line}"
    )


def _strip_internal_keys(items: List[dict]) -> List[dict]:
    clean: List[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        clean.append({k: v for k, v in item.items() if not str(k).startswith('_')})
    return clean


def align_intelligence(intel: dict, *, limit: int = DEFAULT_OPPS_LIMIT, cycle_id: Optional[str] = None) -> dict:
    """Rewrite top_opportunities and action_plan from canonical ranked feed."""
    if not isinstance(intel, dict):
        return intel
    from backend.intelligence.sector_consistency import stabilize_sector_rotation

    out = dict(intel)
    out['sector_rotation'] = stabilize_sector_rotation(out)
    ranked = get_top_ranked_signals(out, limit=limit)
    clean_ranked = _strip_internal_keys(ranked)
    out['top_opportunities'] = clean_ranked
    symbols = get_action_plan_symbols(out, limit=5)
    out['action_plan'] = build_action_plan_text(symbols, ranked, out)
    out['canonical_opportunity_feed'] = {
        'source': 'canonical_rankings',
        'symbols': symbols,
        'top_count': len(clean_ranked),
        'elite_count': sum(1 for o in clean_ranked if o.get('elite_verified')),
    }
    try:
        from backend.intelligence.active_snapshot import begin_publish_job, publish_active_snapshot
        job = begin_publish_job(source='align_intelligence', cycle_id=cycle_id)
        publish_active_snapshot(
            out,
            cycle_id=cycle_id,
            source='align_intelligence',
            publish_token=job.get('publish_token'),
            expected_version=job.get('expected_version'),
        )
    except Exception:
        pass
    return out
