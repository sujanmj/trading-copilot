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
    if symbols:
        lines: List[str] = []
        for idx, sym in enumerate(symbols[:5], 1):
            item = next(
                (x for x in ranked if str(x.get('symbol') or x.get('ticker') or '').upper() == sym),
                {},
            )
            conf = item.get('display_confidence') or item.get('confidence') or 'MEDIUM'
            action = str(item.get('action') or 'WATCH').upper()
            entry = item.get('entry_zone') or item.get('entry_price') or '—'
            logic = str(item.get('logic') or '').strip()
            if len(logic) > 90:
                logic = logic[:87] + '...'
            detail = f"{idx}. **{sym}** ({action}, {conf}) — entry ₹{entry}."
            if logic:
                detail += f" {logic}"
            lines.append(detail)
        return '\n'.join(lines)

    intel = intel if isinstance(intel, dict) else {}
    sectors = intel.get('sector_rotation') if isinstance(intel.get('sector_rotation'), dict) else {}
    bullish = sectors.get('bullish') if isinstance(sectors.get('bullish'), list) else []
    bearish = sectors.get('bearish') if isinstance(sectors.get('bearish'), list) else []
    risks = intel.get('risks_and_avoids') if isinstance(intel.get('risks_and_avoids'), list) else []

    focus = ', '.join(str(s).upper() for s in bullish[:3]) or 'Defensive leaders with volume confirmation'
    avoid_items = []
    for r in risks[:4]:
        if isinstance(r, dict):
            sym = str(r.get('symbol') or '').upper()
            if sym and sym not in ('UNKNOWN', 'MACRO', 'NEWS'):
                avoid_items.append(sym)
    if not avoid_items and bearish:
        avoid_items = [str(s).upper() for s in bearish[:3]]
    avoid = ', '.join(avoid_items) or 'Extended momentum without volume confirmation'

    return (
        "No elite setups currently.\n"
        f"Focus sectors: {focus}.\n"
        f"Avoid: {avoid}.\n"
        "Wait for scanner confirmation before aggressive entries."
    )


def _strip_internal_keys(items: List[dict]) -> List[dict]:
    clean: List[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        clean.append({k: v for k, v in item.items() if not str(k).startswith('_')})
    return clean


def align_intelligence(intel: dict, *, limit: int = DEFAULT_OPPS_LIMIT) -> dict:
    """Rewrite top_opportunities and action_plan from canonical ranked feed."""
    if not isinstance(intel, dict):
        return intel
    out = dict(intel)
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
    return out
