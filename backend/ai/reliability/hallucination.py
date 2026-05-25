"""
Lightweight hallucination detection for AI synthesis outputs.
No external models — rule-based checks only.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from pydantic import ValidationError

from backend.ai.reliability.schemas import (
    PERCENT_RE,
    SYMBOL_RE,
    IntelligenceOutput,
    parse_confidence_fraction,
)

GENERIC_SYMBOLS = frozenset({
    'NIFTY', 'BANKNIFTY', 'SENSEX', 'INDIA', 'GENERAL', 'MARKET', 'INDEX',
})

ABSURD_PERCENT_THRESHOLD = 250.0
MIN_EXECUTIVE_SUMMARY_LEN = 10


def extract_json_object(text: str) -> tuple[Optional[dict], Optional[str]]:
    """Parse JSON from AI text; return (dict, error_message)."""
    if not text or not str(text).strip():
        return None, 'empty_response'

    clean = str(text).strip()
    if '```json' in clean:
        clean = clean.split('```json', 1)[1].split('```', 1)[0].strip()
    elif '```' in clean:
        parts = clean.split('```')
        if len(parts) >= 2:
            clean = parts[1].split('```', 1)[0].strip()

    import json
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError as e:
        return None, f'malformed_json:{e.msg}'

    if not isinstance(parsed, dict):
        return None, 'root_not_object'
    return parsed, None


def _collect_known_tickers(context: Optional[dict]) -> Set[str]:
    known: Set[str] = set(GENERIC_SYMBOLS)
    if not context:
        return known
    for key in ('known_tickers', 'scanner_tickers', 'valid_symbols'):
        vals = context.get(key) or []
        for v in vals:
            sym = str(v).strip().upper()
            if sym:
                known.add(sym)
    scanner = context.get('scanner') or {}
    for sig in scanner.get('top_signals') or []:
        if isinstance(sig, dict):
            t = str(sig.get('ticker') or '').strip().upper()
            if t:
                known.add(t)
    return known


def _find_absurd_percentages(text: str) -> List[str]:
    issues = []
    for m in PERCENT_RE.finditer(text or ''):
        try:
            val = float(m.group(1))
        except ValueError:
            continue
        if val > ABSURD_PERCENT_THRESHOLD or val < -100:
            issues.append(f'absurd_percentage:{val}%')
    return issues


def detect_hallucinations(
    raw: Dict[str, Any],
    *,
    context: Optional[dict] = None,
) -> List[str]:
    """Return list of hallucination / quality violation codes."""
    issues: List[str] = []
    ctx = context or {}
    known = _collect_known_tickers(ctx)

    summary = str(raw.get('executive_summary') or '').strip()
    if len(summary) < MIN_EXECUTIVE_SUMMARY_LEN:
        issues.append('empty_executive_summary')

    mood = raw.get('market_mood') or {}
    if isinstance(mood, dict):
        conf_raw = mood.get('confidence_level')
        conf = parse_confidence_fraction(conf_raw)
        if conf > 1.0 or conf < 0.0:
            issues.append('impossible_confidence_value')
        if conf >= 0.95 and ctx.get('contradiction_severity', 0) >= 0.6:
            issues.append('overconfident_with_contradictions')

    govt = raw.get('government_impact') or {}
    if isinstance(govt, dict):
        gconf = parse_confidence_fraction(govt.get('confidence_score'))
        if gconf > 1.0 or gconf < 0.0:
            issues.append('invalid_government_confidence')

    opps = raw.get('top_opportunities') or []
    risks = raw.get('risks_and_avoids') or []
    if not isinstance(opps, list):
        issues.append('top_opportunities_not_list')
        opps = []
    if not isinstance(risks, list):
        issues.append('risks_not_list')
        risks = []

    seen_symbols: Set[str] = set()
    duplicate_symbols: Set[str] = set()
    fake_symbols: List[str] = []
    buy_count = sell_count = 0

    for item in opps:
        if not isinstance(item, dict):
            issues.append('malformed_opportunity')
            continue
        sym = str(item.get('symbol') or '').strip().upper()
        if not sym:
            issues.append('missing_opportunity_symbol')
            continue
        if sym in seen_symbols:
            duplicate_symbols.add(sym)
        seen_symbols.add(sym)
        if not SYMBOL_RE.match(sym):
            issues.append(f'invalid_symbol_format:{sym}')
        elif sym not in known and len(known) > 5:
            fake_symbols.append(sym)
        action = str(item.get('action') or '').upper()
        if 'BUY' in action:
            buy_count += 1
        if 'SELL' in action:
            sell_count += 1
        logic = str(item.get('logic') or '')
        issues.extend(_find_absurd_percentages(logic))

    if duplicate_symbols:
        issues.append(f'duplicated_opportunities:{",".join(sorted(duplicate_symbols)[:5])}')

    strict_fake = ctx.get('strict_symbol_check', False)
    if fake_symbols and (strict_fake or len(fake_symbols) >= 3):
        issues.append(f'fake_symbols:{",".join(fake_symbols[:5])}')

    india = str((mood or {}).get('india_outlook') or '').upper()
    global_m = str((mood or {}).get('global_mood') or '').upper()
    if india == 'BEARISH' and buy_count >= max(3, len(opps) - 1) and len(opps) >= 3:
        issues.append('contradictory_regime:bearish_outlook_many_buys')
    if global_m == 'BEARISH' and india == 'BULLISH' and ctx.get('regime') == 'panic_volatile':
        issues.append('contradictory_regime:panic_bullish_divergence')

    for item in risks:
        if isinstance(item, dict):
            issues.extend(_find_absurd_percentages(str(item.get('logic') or '')))

    plan = str(raw.get('action_plan') or '').strip()
    if len(plan) < 5:
        issues.append('empty_action_plan')

    return issues


def validate_schema(raw: Dict[str, Any]) -> tuple[Optional[IntelligenceOutput], List[str]]:
    """Pydantic schema validation; returns model or None with error strings."""
    try:
        model = IntelligenceOutput.model_validate(raw)
        return model, []
    except ValidationError as e:
        errors = []
        for err in e.errors():
            loc = '.'.join(str(x) for x in err.get('loc', ()))
            errors.append(f'schema:{loc}:{err.get("msg", "invalid")}')
        return None, errors


def is_blocking_issue(issues: List[str]) -> bool:
    """Whether issues should block downstream delivery without retry/fallback."""
    blocking_prefixes = (
        'malformed_json',
        'root_not_object',
        'empty_response',
        'top_opportunities_not_list',
        'risks_not_list',
    )
    for issue in issues:
        if any(issue.startswith(p) for p in blocking_prefixes):
            return True
        if issue.startswith('schema:'):
            return True
    return len(issues) >= 8
