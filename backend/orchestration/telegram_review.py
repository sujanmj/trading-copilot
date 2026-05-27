"""
Telegram /review — consolidated institutional intelligence (cache-only).

Never triggers scanner refresh, synthesis, AI providers, or pipeline execution.
"""

from __future__ import annotations

import json
import time

from backend.orchestration.telegram_brain_pusher import send_chunked, safe_print
from backend.runtime.market_snapshot import MarketSnapshot
from backend.utils.config import DATA_DIR

INTEL_FILE = DATA_DIR / 'unified_intelligence.json'


def load_review_snapshot() -> MarketSnapshot | None:
    """Load committed snapshot only — no force_refresh, no build_market_snapshot."""
    try:
        from backend.runtime.market_snapshot_engine import load_committed_snapshot
        snap = load_committed_snapshot()
        if snap and (snap.executive_summary or snap.top_opportunities or snap.intelligence):
            return snap
        if snap:
            return snap
    except Exception as exc:
        safe_print(f"[REVIEW] committed snapshot load failed: {exc}")

    if not INTEL_FILE.exists():
        return None
    try:
        raw = json.loads(INTEL_FILE.read_text(encoding='utf-8'))
        intel = raw.get('data', raw) if isinstance(raw, dict) else {}
        if not isinstance(intel, dict):
            return None
        return MarketSnapshot(
            snapshot_id='review_intel_file',
            generated_at=intel.get('generated_at') or intel.get('timestamp') or '',
            intelligence=intel,
            executive_summary=str(intel.get('executive_summary') or intel.get('analysis') or ''),
            top_opportunities=intel.get('top_opportunities') or intel.get('opportunities') or [],
            risk_list=intel.get('risks_and_avoids') or intel.get('risks') or [],
            sector_rotation=intel.get('sector_rotation') or {},
            market_mood=intel.get('market_mood') or {},
            action_plan=str(intel.get('action_plan') or ''),
            calibration=intel.get('self_calibration'),
            warnings=['review_intel_export_fallback'],
        )
    except Exception as exc:
        safe_print(f"[REVIEW] intel file fallback failed: {exc}")
        return None


def push_review(*, command: str = 'review', cycle_id: str = '') -> bool:
    """Send 3-message institutional review from cache."""
    from backend.telegram.formatting.review_formatter import render_review_messages

    snap = load_review_snapshot()
    if not snap:
        send_chunked(
            '❌ No cached intelligence available. Run /refresh when pipelines are idle.',
            command=command,
            cycle_id=cycle_id,
        )
        return False

    sections = render_review_messages(snap)
    safe_print(f"[REVIEW] Sending {len(sections)} grouped messages (cache-only)")
    for label, text in sections:
        send_chunked(text, command=command, cycle_id=cycle_id)
        time.sleep(0.6)
    return True
