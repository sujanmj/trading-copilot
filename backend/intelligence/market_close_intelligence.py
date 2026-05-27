"""
Market close intelligence — institutional EOD summary (no ticker spam).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz

from backend.intelligence.cross_market_correlation import evaluate_cross_market_correlations
from backend.intelligence.institutional_language import apply_institutional_tone, institutional_regime_label
from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR

IST = pytz.timezone('Asia/Kolkata')
OUTPUT_FILE = DATA_DIR / 'market_close_intelligence.json'


def _load_intel() -> dict:
    path = DATA_DIR / 'unified_intelligence.json'
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _load_global() -> dict:
    path = DATA_DIR / 'global_markets.json'
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def build_market_close_report(
    intel: Optional[dict] = None,
    *,
    persist: bool = True,
) -> Dict[str, Any]:
    """Institutional summary at Indian market close — sectors, flows, rotations."""
    intel = intel if isinstance(intel, dict) else _load_intel()
    global_data = _load_global()
    correlation = evaluate_cross_market_correlations(global_data)

    sectors = intel.get('sector_rotation') if isinstance(intel.get('sector_rotation'), dict) else {}
    bullish = sectors.get('bullish') or []
    bearish = sectors.get('bearish') or []
    mood = intel.get('market_mood') if isinstance(intel.get('market_mood'), dict) else {}

    try:
        from backend.utils.config import ANALYSIS_STATE_FILE
        regime = 'sideways'
        if ANALYSIS_STATE_FILE.exists():
            state = json.loads(ANALYSIS_STATE_FILE.read_text(encoding='utf-8'))
            regime = str(state.get('last_regime') or 'sideways')
    except Exception:
        regime = 'sideways'

    failed_breakouts: List[str] = []
    overnight_risks: List[str] = []
    for sig in correlation.get('signals') or []:
        narrative = sig.get('narrative') or ''
        if 'weakness' in narrative.lower() or 'headwind' in narrative.lower():
            failed_breakouts.append(narrative[:100])
        if 'volatility' in narrative.lower() or 'stress' in narrative.lower():
            overnight_risks.append(narrative[:100])

    if correlation.get('risk_level') in ('HIGH', 'PANIC'):
        overnight_risks.append(
            f"Overnight risk score {correlation.get('risk_level')} — monitor US futures and Asia open"
        )

    dominant = bullish[:3] if bullish else ['No clear leadership concentration']
    distribution = bearish[:3] if bearish else ['No dominant distribution theme']

    narrative_parts = [
        f"Dominant sectors: {', '.join(dominant)}.",
        f"Risk rotation: {', '.join(distribution)}.",
        institutional_regime_label(regime).capitalize() + ' regime into close.',
    ]
    if correlation.get('signals'):
        narrative_parts.append(correlation['signals'][0].get('narrative', ''))

    report = {
        'generated_at': datetime.now(IST).isoformat(),
        'session': 'india_close',
        'dominant_sectors': dominant,
        'distribution_sectors': distribution,
        'flow_summary': apply_institutional_tone(
            f"India outlook {mood.get('india_outlook', 'NEUTRAL')} — "
            f"global {mood.get('global_mood', 'NEUTRAL')}"
        ),
        'risk_rotations': distribution,
        'failed_breakouts': failed_breakouts[:4] or ['No major failed breakout cluster flagged'],
        'overnight_watch_risks': overnight_risks[:5] or ['Standard overnight headline risk'],
        'regime': regime,
        'correlation': correlation,
        'narrative': apply_institutional_tone(' '.join(narrative_parts))[:600],
    }

    if persist:
        atomic_write_json(OUTPUT_FILE, report)
    return report


def format_telegram_close_summary(report: Optional[dict] = None) -> str:
    report = report or build_market_close_report(persist=False)
    regime = institutional_regime_label(report.get('regime', 'sideways'))
    lines = [
        f"<b>🏁 MARKET CLOSE — INSTITUTIONAL VIEW</b> <code>{regime.upper()}</code>",
        f"<b>Leadership:</b> {', '.join(report.get('dominant_sectors') or [])}",
        f"<b>Distribution:</b> {', '.join(report.get('distribution_sectors') or [])}",
        f"<b>Flows:</b> {report.get('flow_summary', '')[:200]}",
        f"<b>Overnight watch:</b>",
    ]
    for risk in (report.get('overnight_watch_risks') or [])[:3]:
        lines.append(f"• {apply_institutional_tone(str(risk))[:120]}")
    lines.append(f"\n<i>{report.get('narrative', '')[:400]}</i>")
    return '\n'.join(lines)
