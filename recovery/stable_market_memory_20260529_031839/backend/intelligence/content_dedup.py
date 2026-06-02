"""Lightweight content overlap detection for intelligence fields."""

from __future__ import annotations

import re
from typing import Dict, List, Tuple


def _token_set(text: str) -> set:
    if not text:
        return set()
    tokens = re.findall(r'[a-z0-9]{4,}', str(text).lower())
    return set(tokens)


def overlap_ratio(a: str, b: str) -> float:
    ta, tb = _token_set(a), _token_set(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / max(len(ta), len(tb))


def deduplicate_intelligence_fields(intel: dict, *, threshold: float = 0.70) -> dict:
    """Rewrite overlapping fields so executive summary, brief, and govt stay distinct."""
    if not isinstance(intel, dict):
        return intel
    out = dict(intel)
    summary = str(out.get('executive_summary') or '').strip()
    action = str(out.get('action_plan') or '').strip()
    govt = out.get('government_impact') if isinstance(out.get('government_impact'), dict) else {}
    govt_summary = str(govt.get('summary') or '').strip()

    if summary and govt_summary and overlap_ratio(summary, govt_summary) >= threshold:
        govt = dict(govt)
        govt['summary'] = (
            govt_summary.split('.')[0][:180] + '. '
            'See executive summary for macro view; this block tracks policy catalysts only.'
        )
        out['government_impact'] = govt

    if summary and action and overlap_ratio(summary, action) >= threshold:
        out['action_plan'] = (
            'Positioning follows ranked opportunities only. '
            + (action.split('\n')[0][:220] if action else '')
        )

    mood = out.get('market_mood') if isinstance(out.get('market_mood'), dict) else {}
    india = str(mood.get('india_outlook') or '')
    if summary and india and overlap_ratio(summary, india) >= threshold:
        mood = dict(mood)
        mood['india_outlook'] = 'Mixed — refer to executive summary for directional bias.'
        out['market_mood'] = mood

    return out
