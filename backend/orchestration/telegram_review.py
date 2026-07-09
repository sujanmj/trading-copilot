"""
Telegram /review — consolidated institutional intelligence (cache-only).

Never triggers scanner refresh, synthesis, AI providers, or pipeline execution.
"""

from __future__ import annotations

import json
import time
import traceback
from datetime import datetime
from typing import Optional

from backend.orchestration.telegram_brain_pusher import safe_print
from backend.runtime.market_snapshot import MarketSnapshot
from backend.utils.config import DATA_DIR

INTEL_FILE = DATA_DIR / 'unified_intelligence.json'
ACTIVE_SNAPSHOT_FILE = DATA_DIR / 'active_snapshot.json'
MAX_REVIEW_MESSAGES = 3
FAILSAFE_TEXT = (
    '⚠ <b>Review temporarily unavailable</b>\n'
    'Using degraded cache state.\n\n'
    'Try again shortly or use /status for system health.'
)


def _parse_snapshot_epoch(value: object) -> Optional[float]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return dt.timestamp()
    except Exception:
        return None


def _snapshot_epoch(snap: MarketSnapshot) -> Optional[float]:
    for value in (snap.published_at, snap.snapshot_built_at, snap.generated_at):
        parsed = _parse_snapshot_epoch(value)
        if parsed is not None:
            return parsed
    return None


def _latest_source_mtime() -> Optional[float]:
    mtimes = []
    for path in (INTEL_FILE, ACTIVE_SNAPSHOT_FILE):
        try:
            if path.exists():
                mtimes.append(path.stat().st_mtime)
        except OSError:
            pass
    return max(mtimes) if mtimes else None


def _committed_snapshot_stale(snap: MarketSnapshot) -> bool:
    snap_ts = _snapshot_epoch(snap)
    source_ts = _latest_source_mtime()
    if snap_ts is None or source_ts is None:
        return False
    return source_ts - snap_ts > 60


def _build_readonly_current_snapshot() -> MarketSnapshot | None:
    """Compose a cache-only view from current exports; do not run pipelines."""
    try:
        from backend.runtime.market_snapshot_engine import build_market_snapshot

        safe_print('[REVIEW] committed snapshot stale; composing read-only current cache view')
        return build_market_snapshot(force_refresh=True)
    except Exception as exc:
        safe_print(f'[REVIEW] read-only current cache view failed: {exc}')
        return None


def load_review_snapshot() -> MarketSnapshot | None:
    """Load committed snapshot only — no force_refresh, no build_market_snapshot."""
    try:
        from backend.runtime.market_snapshot_engine import load_committed_snapshot
        snap = load_committed_snapshot()
        if snap:
            if _committed_snapshot_stale(snap):
                current = _build_readonly_current_snapshot()
                if current:
                    return current
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


def _current_runtime_blockers(runtime_state: dict) -> list[str]:
    alert = runtime_state.get('alert_eligibility') or {}
    secondary = runtime_state.get('secondary_flags') or {}
    blockers = [str(r) for r in (alert.get('block_reasons') or []) if r]
    if secondary.get('stale_snapshot') and 'stale_snapshot' not in blockers:
        blockers.append('stale_snapshot')
    if secondary.get('scanner_stalled') and 'scanner_stalled' not in blockers:
        blockers.append('scanner_stalled')
    return blockers


def _current_runtime_warnings(runtime_state: dict) -> list[str]:
    warnings: list[str] = []
    intel = runtime_state.get('intelligence_status') or {}
    if intel.get('degraded') and intel.get('message'):
        warnings.append(str(intel['message']))
    stall = runtime_state.get('stall_watchdog') or {}
    for issue in (stall.get('issues') or [])[:4]:
        tag = str(issue)
        if tag not in warnings:
            warnings.append(tag)
    return warnings


def overlay_current_runtime_health(snap: MarketSnapshot) -> MarketSnapshot:
    """Keep review intelligence cache-only, but never reuse stale embedded health."""
    try:
        from backend.runtime.runtime_state import build_runtime_state

        runtime_state = build_runtime_state(force_refresh=True)
    except Exception as exc:
        safe_print(f'[REVIEW] current runtime health overlay failed: {exc}')
        return snap

    pipeline = runtime_state.get('pipeline') or {}
    fresh = runtime_state.get('snapshot_freshness') or {}
    snap.runtime_state = runtime_state
    snap.lifecycle = runtime_state.get('lifecycle') or {}
    snap.freshness = fresh
    snap.metrics = runtime_state.get('metrics') or snap.metrics
    snap.quality_score = runtime_state.get('quality_score') or snap.quality_score
    snap.pipeline_health = {
        'stages': pipeline.get('stages') or {},
        'stalled_stages': pipeline.get('stalled_stages') or [],
        'any_stalled': bool(pipeline.get('any_stalled')),
        'last_stage': pipeline.get('last_stage'),
        'freshness_tier': fresh.get('health_tier'),
        'snapshot_stale': bool(fresh.get('stale')),
        'collectors_active': (runtime_state.get('collector_activity') or {}).get('collectors_active'),
    }
    snap.blockers = _current_runtime_blockers(runtime_state)
    snap.warnings = list(dict.fromkeys(list(snap.warnings or []) + _current_runtime_warnings(runtime_state)))
    return snap


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

        normalized = MarketSnapshot(
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
        return overlay_current_runtime_health(normalized)
    except Exception as exc:
        safe_print(f'[REVIEW] normalize_review_snapshot failed: {exc}')
        return overlay_current_runtime_health(snap)


def _prepare_daily_review_learning() -> dict:
    """Run cheap post-close learning before daily review formatting."""
    try:
        from backend.telegram.india_mode_lock import is_live_market_hours_phase, is_premarket_phase

        if is_live_market_hours_phase() or is_premarket_phase():
            return {'skipped': True, 'reason': 'market_not_closed'}
    except Exception:
        pass

    summary: dict = {}
    try:
        from backend.trading.tradecard_journal import resolve_close_pending_tradecards

        resolve_close_pending_tradecards(refresh=True)
    except Exception as exc:
        summary['tradecard_error'] = str(exc)[:120]
    try:
        from backend.trading.candidate_outcome_learning import resolve_candidate_outcomes

        col = resolve_candidate_outcomes(run_ai=True)
        summary['candidate_outcomes_resolved'] = len(col.get('resolved') or [])
        summary['candidate_ai_used'] = col.get('ai_used', 0)
    except Exception as exc:
        summary['candidate_outcome_error'] = str(exc)[:120]
    try:
        from backend.analytics.actual_learning_resolver import run_actual_learning_resolver

        learning_summary = run_actual_learning_resolver(refresh_cache=True)
        if isinstance(learning_summary, dict):
            learning_summary.update(summary)
            summary = learning_summary
    except Exception as exc:
        if not summary:
            summary = {'sample_updated': 0, 'pending_data': 0, 'errors': 1, 'error': str(exc)[:120]}
        else:
            summary['actual_learning_error'] = str(exc)[:120]
    try:
        from backend.storage.outcome_resolver import refresh_memory_dashboard_cache

        refresh_memory_dashboard_cache()
    except Exception:
        pass
    safe_print(
        '[DAILY_REVIEW_LEARNING] '
        f"ran_before_send=true sample_updated={summary.get('sample_updated', 0)} "
        f"pending_data={summary.get('pending_data', 0)}"
    )
    return summary


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
    _prepare_daily_review_learning()

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
