"""
Retrieval-first context for /ask — elite, opps, calibration, regime before LLM.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.utils.config import ANALYSIS_STATE_FILE, DATA_DIR

INTEL_FILE = DATA_DIR / 'unified_intelligence.json'
ELITE_FILE = DATA_DIR / 'high_conviction_alerts.json'
STATS_FILE = DATA_DIR / 'stats_data.json'


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _clip(text: str, limit: int) -> str:
    text = (text or '').strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + '...'


def _regime_section(intel: dict) -> str:
    mood = intel.get('market_mood') if isinstance(intel.get('market_mood'), dict) else {}
    india = mood.get('india_outlook') or mood.get('global_mood') or 'unknown'
    conf = mood.get('confidence_level') or 'N/A'
    summary = _clip(intel.get('executive_summary') or '', 400)
    state = _load_json(ANALYSIS_STATE_FILE)
    regime = state.get('last_regime') or ''
    qm = state.get('quality_metrics') or {}
    disagree = qm.get('disagreement_score') or state.get('disagreement_score') or 0
    vol = qm.get('volatility_index') or state.get('volatility_index') or 0
    lines = [
        f"Regime: {regime or india} | Outlook confidence: {conf}",
        f"Contradiction pressure: {disagree} | Volatility index: {vol}",
    ]
    if summary:
        lines.append(f"Executive summary: {summary}")
    rotation = intel.get('sector_rotation') if isinstance(intel.get('sector_rotation'), dict) else {}
    if rotation:
        bull = ', '.join(str(s) for s in (rotation.get('bullish') or [])[:5]) or 'none'
        bear = ', '.join(str(s) for s in (rotation.get('bearish') or [])[:5]) or 'none'
        lines.append(f"Bullish sectors: {bull}")
        lines.append(f"Bearish sectors: {bear}")
    return '\n'.join(lines)


def _elite_section() -> str:
    data = _load_json(ELITE_FILE)
    elite = data.get('elite_signals') or []
    if not elite:
        return (
            "Elite meta-labeler (>72% probability): NONE passed threshold today. "
            "Do not present scanner HIGH signals as elite conviction."
        )
    lines = [f"Elite meta-labeler setups ({len(elite)} verified, >72% ML probability):"]
    for row in elite[:8]:
        sym = row.get('symbol') or row.get('Stock') or '?'
        prob = row.get('ml_confidence') or 'N/A'
        action = row.get('action') or row.get('Action') or 'BUY'
        lines.append(f"  • {sym} [{action}] ML={prob}")
    return '\n'.join(lines)


def _opps_section() -> str:
    try:
        from backend.orchestration.opportunity_filter import rank_opportunities, DEFAULT_OPPS_LIMIT
        opps = rank_opportunities(limit=min(8, DEFAULT_OPPS_LIMIT))
    except Exception:
        opps = []
    if not opps:
        return "Ranked scanner opportunities: none currently pass quality gates."
    lines = [f"Ranked opportunities (top {len(opps)}, elite-aligned labels):"]
    for i, o in enumerate(opps, 1):
        sym = o.get('symbol') or '?'
        label = o.get('display_confidence') or o.get('confidence') or 'MEDIUM'
        note = o.get('confidence_note') or ''
        logic = _clip(o.get('logic') or '', 80)
        suffix = f" ({note})" if note else ''
        lines.append(f"  {i}. {sym} — {label}{suffix} | {logic}")
    return '\n'.join(lines)


def _calibration_section() -> str:
    try:
        from backend.lifecycle.unified_metrics import get_calibration_metrics, get_outcome_metrics
        metrics = get_outcome_metrics('all_time')
        cal = get_calibration_metrics()
    except Exception:
        stats = _load_json(STATS_FILE)
        metrics = stats.get('metrics_all_time') or {}
        cal = stats.get('lifecycle_calibration') or {}
    evaluated = metrics.get('evaluated') or metrics.get('total_evaluated') or cal.get('evaluated') or cal.get('total_evaluated') or 0
    if evaluated == 0:
        return "Calibration: insufficient evaluated sample — post-market EOD builds metrics."
    from backend.metrics.format_helpers import safe_pct
    parts = [
        f"Evaluated outcomes: {evaluated} | Win rate: {safe_pct(metrics.get('win_rate'))}",
        f"Wins: {metrics.get('wins', 0)} | Losses: {metrics.get('losses', 0)} | Pending: {metrics.get('pending', 0)}",
        f"High-conf win rate: {safe_pct(metrics.get('high_conf_win_rate'), fallback='Confidence building')}",
    ]
    try:
        stats = _load_json(STATS_FILE)
        dash = stats.get('calibration_dashboard') or {}
        health = dash.get('health_score') or dash.get('overall_health')
        if health is not None:
            parts.append(f"Calibration health: {health}")
    except Exception:
        pass
    self_cal = _clip(_load_json(INTEL_FILE).get('self_calibration') or '', 300)
    if self_cal:
        parts.append(f"Self-calibration note: {self_cal}")
    return '\n'.join(parts)


def build_ask_context(question: str = '', max_chars: int = 4500) -> str:
    """Assemble engine-grounded context for Ask AI prompts."""
    intel = _load_json(INTEL_FILE)
    sections = [
        "=== REGIME & CONTRADICTION ===",
        _regime_section(intel),
        "",
        "=== ELITE RANKINGS (meta-labeler) ===",
        _elite_section(),
        "",
        "=== RANKED OPPORTUNITIES (scanner, elite-aligned) ===",
        _opps_section(),
        "",
        "=== CALIBRATION ===",
        _calibration_section(),
    ]
    if question:
        sections.extend(["", f"User question focus: {_clip(question, 200)}"])
    return _clip('\n'.join(sections), max_chars)


def build_ask_prompt(question: str) -> str:
    context = build_ask_context(question)
    return f"""You are an Indian equities intelligence assistant for Trading Copilot.

STRICT RULES:
- Answer ONLY from the internal engine data below.
- Do NOT invent tickers or generic market picks (e.g. random Nifty names).
- If elite setups are empty, say no high-conviction elite trades passed the >72% threshold.
- Reference ranked opportunities, regime alignment, contradiction pressure, and calibration when relevant.
- Keep answer to 4-6 sentences, actionable for a retail investor.

INTERNAL ENGINE DATA:
{context}

Question: {question.strip()}

Answer:"""
