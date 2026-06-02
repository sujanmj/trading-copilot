"""
Confidence calibration — normalize, bound, and deflate inflated AI confidence.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.ai.reliability.schemas import (
    ConfidenceMetrics,
    IntelligenceOutput,
    parse_confidence_fraction,
)


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _avg(values: List[float]) -> float:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else 0.5


def calibrate_confidence(
    intel: IntelligenceOutput,
    *,
    context: Optional[dict] = None,
) -> ConfidenceMetrics:
    ctx = context or {}
    mood = intel.market_mood
    govt = intel.government_impact

    ai_confidence = _clamp(parse_confidence_fraction(mood.confidence_level))
    govt_conf = _clamp(parse_confidence_fraction(govt.confidence_score))
    ai_confidence = _clamp((ai_confidence + govt_conf) / 2.0)

    opp_confidences = []
    for opp in intel.top_opportunities:
        band = str(opp.confidence or '').upper()
        if 'HIGH' in band or 'VERY' in band:
            opp_confidences.append(0.85)
        elif 'LOW' in band:
            opp_confidences.append(0.35)
        else:
            opp_confidences.append(0.55)
    signal_strength = _clamp(_avg(opp_confidences))

    preservation = ctx.get('preservation') or {}
    scored = preservation.get('scored_signals') or {}
    signals = scored.get('signals') or []
    agreement_vals = [
        float(s.get('agreement_score', 0.5))
        for s in signals
        if isinstance(s, dict)
    ]
    agreement_score = _clamp(_avg(agreement_vals) if agreement_vals else 0.5)

    contra = preservation.get('contradictions') or {}
    contradiction_severity = _clamp(float(contra.get('overall_disagreement_score') or 0.0))

    novelty_score = float(ctx.get('novelty_avg_score') or preservation.get('novelty_avg_score') or 0.0)
    novelty_score = _clamp(novelty_score, 0.0, 10.0)

    regime = str(ctx.get('regime') or preservation.get('regime') or 'sideways')
    regime_stability = 0.75
    if regime in ('panic_volatile', 'regime_transition', 'macro_uncertainty'):
        regime_stability = 0.35
    elif regime == 'sideways':
        regime_stability = 0.55

    source_consensus = agreement_score
    sentiment_diversity = _clamp(float(ctx.get('sentiment_diversity_score') or 0.5))

    inflation_penalty = 0.0
    if ai_confidence >= 0.85 and contradiction_severity >= 0.45:
        inflation_penalty += 0.15
    if ai_confidence >= 0.9 and regime_stability < 0.5:
        inflation_penalty += 0.12
    if signal_strength >= 0.85 and agreement_score < 0.45:
        inflation_penalty += 0.1
    inflation_penalty = _clamp(inflation_penalty, 0.0, 0.35)

    raw_calibrated = (
        ai_confidence * 0.28
        + agreement_score * 0.18
        + signal_strength * 0.12
        + source_consensus * 0.12
        + sentiment_diversity * 0.1
        + regime_stability * 0.12
        + (1.0 - contradiction_severity) * 0.08
    )
    calibrated_confidence = _clamp(raw_calibrated - inflation_penalty)

    if calibrated_confidence > ai_confidence + 0.05:
        calibrated_confidence = _clamp(ai_confidence - 0.05)

    reliability_score = _clamp(
        calibrated_confidence * 0.55
        + (1.0 - contradiction_severity) * 0.2
        + regime_stability * 0.15
        + sentiment_diversity * 0.1
    )

    return ConfidenceMetrics(
        ai_confidence=round(ai_confidence, 3),
        agreement_score=round(agreement_score, 3),
        signal_strength=round(signal_strength, 3),
        contradiction_severity=round(contradiction_severity, 3),
        novelty_score=round(novelty_score, 3),
        regime_stability=round(regime_stability, 3),
        source_consensus=round(source_consensus, 3),
        sentiment_diversity=round(sentiment_diversity, 3),
        calibrated_confidence=round(calibrated_confidence, 3),
        reliability_score=round(reliability_score, 3),
        inflation_penalty=round(inflation_penalty, 3),
    )


def apply_confidence_to_output(
    intel_dict: Dict[str, Any],
    metrics: ConfidenceMetrics,
) -> Dict[str, Any]:
    """Attach calibrated confidence block; cap displayed mood confidence."""
    out = dict(intel_dict)
    mood = dict(out.get('market_mood') or {})
    capped = metrics.calibrated_confidence * 10.0
    mood['confidence_level'] = f'{capped:.1f}/10'
    out['market_mood'] = mood
    out['confidence_metrics'] = metrics.model_dump(mode='json')
    return out
