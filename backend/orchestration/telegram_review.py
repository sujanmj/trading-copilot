"""
Telegram /review — consolidated institutional intelligence (cache-only).

Never triggers scanner refresh, synthesis, AI providers, or pipeline execution.
"""

from __future__ import annotations

import json
import time
import traceback

from backend.orchestration.telegram_brain_pusher import safe_print
from backend.runtime.market_snapshot import MarketSnapshot
from backend.utils.config import DATA_DIR

INTEL_FILE = DATA_DIR / 'unified_intelligence.json'
MAX_REVIEW_MESSAGES = 3
FAILSAFE_TEXT = (
    '⚠ <b>Review temporarily unavailable</b>\n'
    'Using degraded cache state.\n\n'
    'Try again shortly or use /status for system health.'
)


def load_review_snapshot() -> MarketSnapshot | None:
    """Load committed snapshot only — no force_refresh, no build_market_snapshot."""
    try:
        from backend.runtime.market_snapshot_engine import load_committed_snapshot
        snap = load_committed_snapshot()
        if snap:
            safe_print('[REVIEW] cache loaded from committed snapshot')
            return snap
    except Exception as exc:
        safe_print(f'[REVIEW] committed snapshot load failed: {exc}')

    if not INTEL_FILE.exists():
        safe_print('[REVIEW] cache missing — no unified_intelligence.json')
        return None
    try:
        raw = json.loads(INTEL_FILE.read_text(encoding='utf-8'))
        intel = raw.get('data', raw) if isinstance(raw, dict) else {}
        if not isinstance(intel, dict):
            safe_print('[REVIEW] intel file invalid shape')
            return None
        safe_print('[REVIEW] cache loaded from unified_intelligence.json fallback')
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
        safe_print(f'[REVIEW] intel file fallback failed: {exc}')
        return None


def normalize_review_snapshot(snap: MarketSnapshot | None) -> MarketSnapshot | None:
    """Safe field normalization — no nested assumptions."""
    if snap is None:
        return None
    try:
        intel = snap.intelligence if isinstance(snap.intelligence, dict) else {}
        rotation = snap.sector_rotation if isinstance(snap.sector_rotation, dict) else {}
        mood = snap.market_mood if isinstance(snap.market_mood, dict) else {}
        rs = snap.runtime_state if isinstance(snap.runtime_state, dict) else {}

        summary = str(
            snap.executive_summary
            or intel.get('executive_summary')
            or intel.get('analysis')
            or 'Unavailable'
        )
        action = str(snap.action_plan or intel.get('action_plan') or 'Awaiting next cycle')

        return MarketSnapshot(
            snapshot_id=snap.snapshot_id or 'review_cache',
            generated_at=snap.generated_at or intel.get('generated_at') or '',
            intelligence=intel,
            executive_summary=summary,
            top_opportunities=list(snap.top_opportunities or intel.get('top_opportunities') or []),
            risk_list=list(snap.risk_list or intel.get('risks_and_avoids') or intel.get('risks') or []),
            sector_rotation={
                'bullish': list(rotation.get('bullish') or []),
                'bearish': list(rotation.get('bearish') or []),
            },
            market_mood=dict(mood),
            action_plan=action,
            calibration=snap.calibration or intel.get('self_calibration'),
            global_mood=snap.global_mood or mood.get('global_mood'),
            india_bias=snap.india_bias or mood.get('india_outlook'),
            retail_sentiment=snap.retail_sentiment or mood.get('retail_mood'),
            regime=snap.regime if isinstance(snap.regime, dict) else {},
            lifecycle=snap.lifecycle if isinstance(snap.lifecycle, dict) else rs.get('lifecycle') or {},
            freshness=snap.freshness if isinstance(snap.freshness, dict) else {},
            metrics=snap.metrics if isinstance(snap.metrics, dict) else {},
            runtime_state=rs,
            blockers=list(snap.blockers or []),
            warnings=list(snap.warnings or []),
            quality_score=snap.quality_score,
            confidence=snap.confidence or mood.get('confidence_level'),
            pipeline_health=snap.pipeline_health if isinstance(snap.pipeline_health, dict) else {},
        )
    except Exception as exc:
        safe_print(f'[REVIEW] normalize_review_snapshot failed: {exc}')
        return snap


def _chunk_review_text(text: str, max_len: int = 3900) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        split_at = remaining.rfind('\n\n', 0, max_len)
        if split_at < max_len // 2:
            split_at = remaining.rfind('\n', 0, max_len)
        if split_at < max_len // 2:
            split_at = max_len
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip()
    return chunks


def _send_review_text(text: str, *, command: str, cycle_id: str) -> bool:
    """Send via listener path — avoids brain_pusher alert dedupe swallowing review."""
    from backend.orchestration.telegram_listener import send_message

    sent_any = False
    for chunk in _chunk_review_text(text):
        ok = send_message(chunk, command=command, cycle_id=cycle_id, message_kind='final')
        safe_print(f'[REVIEW] send complete ok={ok} bytes={len(chunk)}')
        sent_any = sent_any or bool(ok)
        time.sleep(0.35)
    return sent_any


def push_review(*, command: str = 'review', cycle_id: str = '') -> bool:
    """Send up to 3 grouped institutional review messages from cache."""
    safe_print(f'[REVIEW] command received cycle={cycle_id or "-"}')

    snap = load_review_snapshot()
    if not snap:
        safe_print('[REVIEW] aggregation skipped — no cache')
        _send_review_text(
            '❌ No cached intelligence available. Run /refresh when pipelines are idle.',
            command=command,
            cycle_id=cycle_id,
        )
        return False

    snap = normalize_review_snapshot(snap)
    safe_print('[REVIEW] aggregation started')

    try:
        from backend.telegram.formatting.review_formatter import render_review_messages
        sections = render_review_messages(snap)
    except Exception as exc:
        safe_print(f'[REVIEW] aggregation exception: {exc}')
        safe_print(traceback.format_exc())
        _send_review_text(FAILSAFE_TEXT, command=command, cycle_id=cycle_id)
        return False

    sections = list(sections or [])[:MAX_REVIEW_MESSAGES]
    safe_print(f'[REVIEW] message grouped count={len(sections)}')

    if not sections:
        safe_print('[REVIEW] aggregation produced no sections')
        _send_review_text(FAILSAFE_TEXT, command=command, cycle_id=cycle_id)
        return False

    sent = 0
    for label, text in sections:
        safe_print(f'[REVIEW] sending section={label}')
        if _send_review_text(str(text or ''), command=command, cycle_id=cycle_id):
            sent += 1
        time.sleep(0.6)

    if sent == 0:
        safe_print('[REVIEW] all sends failed — emitting failsafe')
        _send_review_text(FAILSAFE_TEXT, command=command, cycle_id=cycle_id)
        return False

    safe_print(f'[REVIEW] send complete sent={sent}/{len(sections)}')
    return True
