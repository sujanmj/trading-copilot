"""
Central AI reliability firewall — all synthesis outputs pass through here.
Validation → hallucination checks → calibration → retry/fallback.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from backend.ai.reliability.confidence import apply_confidence_to_output, calibrate_confidence
from backend.ai.reliability.hallucination import (
    detect_hallucinations,
    extract_json_object,
    is_blocking_issue,
    validate_schema,
)
from backend.ai.reliability.schemas import intelligence_to_dict
from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR
from backend.utils.structured_log import rel_log

MAX_VALIDATION_RETRIES = 1
INTEL_FILE = DATA_DIR / 'unified_intelligence.json'
LAST_VALID_FILE = DATA_DIR / 'last_valid_intelligence.json'

SIMPLIFIED_RETRY_SUFFIX = """

RELIABILITY RETRY — output ONLY compact valid JSON with these keys:
executive_summary, government_impact, sector_rotation, market_mood,
self_calibration, top_opportunities (5 items max), risks_and_avoids (5 items max), action_plan.
Use ONLY tickers from the SCORED SIGNALS / scanner context. No markdown.
"""


@dataclass
class GatewayResult:
    success: bool
    data: Optional[Dict[str, Any]] = None
    meta: Dict[str, Any] = field(default_factory=dict)
    used_fallback: bool = False
    hallucinations: List[str] = field(default_factory=list)
    schema_errors: List[str] = field(default_factory=list)
    retry_count: int = 0


def load_last_valid_intelligence() -> Optional[Dict[str, Any]]:
    for path in (LAST_VALID_FILE, INTEL_FILE):
        if not path.exists():
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get('executive_summary'):
                return data
        except Exception:
            continue
    return None


def save_last_valid_intelligence(payload: Dict[str, Any]) -> None:
    """Persist stripped intelligence core for safe fallback."""
    core = {
        k: payload[k]
        for k in (
            'executive_summary', 'government_impact', 'sector_rotation',
            'market_mood', 'self_calibration', 'top_opportunities',
            'risks_and_avoids', 'action_plan', 'confidence_metrics',
        )
        if k in payload
    }
    if core.get('executive_summary'):
        atomic_write_json(LAST_VALID_FILE, core)


def _record_gateway_metrics(event: str, **kwargs):
    try:
        from backend.metrics.execution_metrics import record_reliability_event
        record_reliability_event(event, **kwargs)
    except Exception:
        pass


def _build_meta(
    *,
    validated: bool,
    degraded: bool,
    fallback: bool,
    hallucinations: List[str],
    schema_errors: List[str],
    retry_count: int,
    reliability_score: float,
    confidence_metrics: Optional[dict] = None,
) -> Dict[str, Any]:
    return {
        'reliability': {
            'validated': validated,
            'degraded': degraded,
            'fallback_used': fallback,
            'hallucinations': hallucinations[:20],
            'schema_errors': schema_errors[:20],
            'retry_count': retry_count,
            'reliability_score': round(reliability_score, 3),
            'validation_status': 'degraded' if degraded else ('failed' if not validated else 'valid'),
        },
        'confidence_metrics': confidence_metrics or {},
    }


def _validate_parsed(
    parsed: Dict[str, Any],
    *,
    context: Optional[dict] = None,
) -> GatewayResult:
    ctx = context or {}
    model, schema_errors = validate_schema(parsed)

    if schema_errors:
        rel_log(
            'schema_failure',
            console_tag='SCHEMA FAILURE',
            issues=schema_errors[:5],
            cycle_id=ctx.get('cycle_id'),
        )
        _record_gateway_metrics('schema_failure', count=len(schema_errors))

    if model is None or is_blocking_issue(schema_errors):
        return GatewayResult(
            success=False,
            hallucinations=[],
            schema_errors=schema_errors,
        )

    metrics = calibrate_confidence(model, context=ctx)
    intel_dict = intelligence_to_dict(model)
    from backend.intelligence.canonical_rankings import align_intelligence

    intel_dict = align_intelligence(intel_dict)
    hallucinations = detect_hallucinations(intel_dict, context=ctx)

    if hallucinations:
        rel_log(
            'hallucination_detected',
            console_tag='HALLUCINATION DETECTED',
            issues=hallucinations[:8],
            cycle_id=ctx.get('cycle_id'),
        )
        _record_gateway_metrics('hallucination_detected', count=len(hallucinations))

    all_issues = hallucinations + schema_errors
    if is_blocking_issue(all_issues):
        return GatewayResult(
            success=False,
            hallucinations=hallucinations,
            schema_errors=schema_errors,
        )

    if len(hallucinations) >= 4:
        return GatewayResult(
            success=False,
            hallucinations=hallucinations,
            schema_errors=schema_errors,
        )

    intel_dict = apply_confidence_to_output(intel_dict, metrics)

    degraded = bool(hallucinations)
    meta = _build_meta(
        validated=True,
        degraded=degraded,
        fallback=False,
        hallucinations=hallucinations,
        schema_errors=schema_errors,
        retry_count=0,
        reliability_score=metrics.reliability_score,
        confidence_metrics=intel_dict.get('confidence_metrics'),
    )
    intel_dict['reliability_meta'] = meta['reliability']

    return GatewayResult(
        success=True,
        data=intel_dict,
        meta=meta,
        hallucinations=hallucinations,
        schema_errors=schema_errors,
    )


def process_intelligence_synthesis(
    ai_text: str,
    *,
    context: Optional[dict] = None,
    retry_callback: Optional[Callable[[], Optional[str]]] = None,
) -> GatewayResult:
    """
    Central gateway for Claude/Gemini synthesis JSON.
    Max 1 validation-aware retry via retry_callback returning new raw text.
    """
    ctx = dict(context or {})
    parsed, parse_err = extract_json_object(ai_text)
    if parsed is None:
        rel_log('schema_failure', console_tag='SCHEMA FAILURE', error=parse_err, cycle_id=ctx.get('cycle_id'))
        _record_gateway_metrics('schema_failure', error=parse_err)
        retry_count = 0
        if retry_callback and retry_count < MAX_VALIDATION_RETRIES:
            rel_log('validation_retry', console_tag='VALIDATION RETRY', attempt=1, cycle_id=ctx.get('cycle_id'))
            _record_gateway_metrics('validation_retry')
            retry_count = 1
            retry_text = retry_callback()
            if retry_text:
                parsed, parse_err = extract_json_object(retry_text)
        if parsed is None:
            return _safe_fallback(ctx, parse_err or 'parse_failed', retry_count)

    result = _validate_parsed(parsed, context=ctx)
    if result.success:
        if result.data:
            save_last_valid_intelligence(result.data)
        return result

    retry_count = 0
    if retry_callback and retry_count < MAX_VALIDATION_RETRIES:
        rel_log(
            'validation_retry',
            console_tag='VALIDATION RETRY',
            attempt=1,
            issues=(result.hallucinations + result.schema_errors)[:6],
            cycle_id=ctx.get('cycle_id'),
        )
        _record_gateway_metrics('validation_retry')
        retry_count = 1
        retry_text = retry_callback()
        if retry_text:
            reparsed, _ = extract_json_object(retry_text)
            if reparsed:
                retry_result = _validate_parsed(reparsed, context=ctx)
                retry_result.retry_count = retry_count
                if retry_result.success and retry_result.data:
                    save_last_valid_intelligence(retry_result.data)
                    return retry_result

    return _safe_fallback(
        ctx,
        'validation_failed',
        retry_count,
        hallucinations=result.hallucinations,
        schema_errors=result.schema_errors,
    )


def _safe_fallback(
    ctx: dict,
    reason: str,
    retry_count: int,
    *,
    hallucinations: Optional[List[str]] = None,
    schema_errors: Optional[List[str]] = None,
) -> GatewayResult:
    last = load_last_valid_intelligence()
    rel_log(
        'safe_fallback',
        console_tag='SAFE FALLBACK',
        reason=reason,
        has_last_valid=bool(last),
        cycle_id=ctx.get('cycle_id'),
    )
    _record_gateway_metrics('safe_fallback', reason=reason)

    if not last:
        return GatewayResult(
            success=False,
            meta={'reliability': {'validation_status': 'failed', 'fallback_used': False}},
            hallucinations=hallucinations or [],
            schema_errors=schema_errors or [],
            retry_count=retry_count,
        )

    payload = dict(last)
    payload['reliability_meta'] = {
        'validated': False,
        'degraded': True,
        'fallback_used': True,
        'hallucinations': (hallucinations or [])[:10],
        'schema_errors': (schema_errors or [])[:10],
        'retry_count': retry_count,
        'reliability_score': float((payload.get('confidence_metrics') or {}).get('reliability_score') or 0.4),
        'validation_status': 'degraded',
        'fallback_reason': reason,
    }
    return GatewayResult(
        success=True,
        data=payload,
        used_fallback=True,
        meta={'reliability': payload['reliability_meta']},
        hallucinations=hallucinations or [],
        schema_errors=schema_errors or [],
        retry_count=retry_count,
    )


def validate_for_telegram(intel: Dict[str, Any]) -> tuple[bool, List[str]]:
    """Block Telegram dispatch when intelligence is untrusted."""
    if not isinstance(intel, dict):
        return False, ['invalid_payload']
    meta = intel.get('reliability_meta') or {}
    if meta.get('validation_status') == 'failed':
        return False, ['validation_failed']
    if meta.get('fallback_used') and float(meta.get('reliability_score') or 0) < 0.35:
        return False, ['fallback_low_reliability']
    if not str(intel.get('executive_summary') or '').strip():
        return False, ['empty_summary']
    conf = (intel.get('confidence_metrics') or {}).get('calibrated_confidence')
    if conf is not None and float(conf) < 0.15:
        return False, ['confidence_too_low']
    return True, []


def validate_for_persistence(intel: Dict[str, Any]) -> tuple[bool, Dict[str, Any]]:
    """Ensure JSON writes are structurally safe."""
    if not isinstance(intel, dict):
        return False, {}
    try:
        json.dumps(intel, default=str)
    except (TypeError, ValueError):
        return False, {}
    if not intel.get('executive_summary'):
        return False, {}
    return True, intel


def process_generic_ai_output(
    ai_text: str,
    *,
    use_case: str = 'generic',
    context: Optional[dict] = None,
) -> GatewayResult:
    """Lightweight validation for non-synthesis AI outputs."""
    ctx = context or {}
    if use_case in ('final_synthesis', 'gemini_synthesis'):
        return process_intelligence_synthesis(ai_text, context=ctx)

    if not str(ai_text or '').strip():
        return GatewayResult(success=False, schema_errors=['empty_text'])

    parsed, err = extract_json_object(ai_text)
    if parsed is None:
        return GatewayResult(success=True, data={'text': ai_text}, meta={'parse': 'text_only'})
    return GatewayResult(success=True, data=parsed, meta={'parse': 'json'})


def build_retry_prompt(original_prompt: str) -> str:
    return original_prompt + SIMPLIFIED_RETRY_SUFFIX
