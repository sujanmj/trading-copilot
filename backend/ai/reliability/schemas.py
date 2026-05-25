"""
Strict Pydantic schemas for AI intelligence outputs and downstream payloads.
Validation-first with safe coercion and bounded confidence fields.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SYMBOL_RE = re.compile(r'^[A-Z][A-Z0-9&.\-]{0,14}$')
CONFIDENCE_FRACTION_RE = re.compile(r'^(\d+(?:\.\d+)?)\s*/\s*10$', re.I)
PERCENT_RE = re.compile(r'(\d+(?:\.\d+)?)\s*%')


class ConfidenceBand(str, Enum):
    LOW = 'LOW'
    MEDIUM = 'MEDIUM'
    HIGH = 'HIGH'
    VERY_HIGH = 'VERY_HIGH'


class MarketMoodLabel(str, Enum):
    BULLISH = 'BULLISH'
    BEARISH = 'BEARISH'
    NEUTRAL = 'NEUTRAL'
    CAUTIOUSLY_BULLISH = 'CAUTIOUSLY BULLISH'
    CAUTIOUSLY_BEARISH = 'CAUTIOUSLY BEARISH'
    MIXED = 'MIXED'
    UNKNOWN = 'UNKNOWN'


class RegimeType(str, Enum):
    BULLISH_TREND = 'bullish_trend'
    BEARISH_TREND = 'bearish_trend'
    SIDEWAYS = 'sideways'
    PANIC_VOLATILE = 'panic_volatile'
    REGIME_TRANSITION = 'regime_transition'
    MACRO_UNCERTAINTY = 'macro_uncertainty'
    UNKNOWN = 'unknown'


class ActionType(str, Enum):
    BUY = 'BUY'
    SELL = 'SELL'
    HOLD = 'HOLD'
    WATCH = 'WATCH'
    AVOID = 'AVOID'


def parse_confidence_fraction(value: Any) -> float:
    """Normalize confidence strings like '6.5/10' or numeric 0–1 / 0–10 to 0–1."""
    if value is None:
        return 0.5
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1.0:
            return min(1.0, v / 10.0)
        return max(0.0, min(1.0, v))
    text = str(value).strip()
    m = CONFIDENCE_FRACTION_RE.match(text)
    if m:
        return max(0.0, min(1.0, float(m.group(1)) / 10.0))
    try:
        v = float(text)
        if v > 1.0:
            return min(1.0, v / 10.0)
        return max(0.0, min(1.0, v))
    except ValueError:
        return 0.5


def normalize_mood_label(value: Any) -> str:
    if value is None:
        return MarketMoodLabel.UNKNOWN.value
    text = str(value).strip().upper()
    aliases = {
        'CAUTIOUS BULLISH': MarketMoodLabel.CAUTIOUSLY_BULLISH.value,
        'CAUTIOUSLY BULLISH': MarketMoodLabel.CAUTIOUSLY_BULLISH.value,
        'CAUTIOUS BEARISH': MarketMoodLabel.CAUTIOUSLY_BEARISH.value,
        'CAUTIOUSLY BEARISH': MarketMoodLabel.CAUTIOUSLY_BEARISH.value,
    }
    return aliases.get(text, text)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='ignore', str_strip_whitespace=True)


class GovernmentImpact(StrictModel):
    summary: str = Field(default='Policy impact unavailable.', min_length=3)
    confidence_score: str = Field(default='5/10')

    @field_validator('confidence_score', mode='before')
    @classmethod
    def _coerce_conf(cls, v: Any) -> str:
        if v is None:
            return '5/10'
        return str(v)


class SectorRotation(StrictModel):
    bullish: List[str] = Field(default_factory=list, max_length=20)
    bearish: List[str] = Field(default_factory=list, max_length=20)


class MarketMood(StrictModel):
    global_mood: str = Field(default=MarketMoodLabel.UNKNOWN.value)
    india_outlook: str = Field(default=MarketMoodLabel.UNKNOWN.value)
    retail_mood: str = Field(default=MarketMoodLabel.NEUTRAL.value)
    confidence_level: str = Field(default='5/10')

    @field_validator('global_mood', 'india_outlook', 'retail_mood', mode='before')
    @classmethod
    def _norm_mood(cls, v: Any) -> str:
        return normalize_mood_label(v)


class OpportunityItem(StrictModel):
    symbol: str = Field(min_length=2, max_length=15)
    action: str = Field(default='WATCH')
    entry_zone: str = Field(default='')
    target: str = Field(default='')
    stop_loss: str = Field(default='')
    confidence: str = Field(default='MEDIUM')
    logic: str = Field(default='No logic provided.', min_length=3)

    @field_validator('symbol', mode='before')
    @classmethod
    def _norm_symbol(cls, v: Any) -> str:
        sym = str(v or '').strip().upper()
        return sym

    @field_validator('action', mode='before')
    @classmethod
    def _norm_action(cls, v: Any) -> str:
        text = str(v or 'WATCH').strip().upper()
        for act in ActionType:
            if act.value in text:
                return act.value
        return 'WATCH'


class RiskItem(StrictModel):
    symbol: str = Field(default='GENERAL', min_length=2, max_length=15)
    logic: str = Field(default='Risk noted.', min_length=3)

    @field_validator('symbol', mode='before')
    @classmethod
    def _norm_symbol(cls, v: Any) -> str:
        return str(v or 'GENERAL').strip().upper()


class IntelligenceOutput(StrictModel):
    executive_summary: str = Field(min_length=10, max_length=4000)
    government_impact: GovernmentImpact
    sector_rotation: SectorRotation
    market_mood: MarketMood
    self_calibration: str = Field(default='Calibration unavailable.', min_length=3)
    top_opportunities: List[OpportunityItem] = Field(min_length=1, max_length=15)
    risks_and_avoids: List[RiskItem] = Field(min_length=1, max_length=15)
    action_plan: str = Field(min_length=5, max_length=4000)

    @model_validator(mode='before')
    @classmethod
    def _fill_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        out.setdefault('government_impact', {'summary': 'Unavailable', 'confidence_score': '5/10'})
        out.setdefault('sector_rotation', {'bullish': [], 'bearish': []})
        out.setdefault('market_mood', {
            'global_mood': 'UNKNOWN',
            'india_outlook': 'UNKNOWN',
            'retail_mood': 'NEUTRAL',
            'confidence_level': '5/10',
        })
        out.setdefault('self_calibration', 'Based on available evidence.')
        out.setdefault('top_opportunities', [])
        out.setdefault('risks_and_avoids', [])
        out.setdefault('action_plan', 'Monitor markets; no actionable plan generated.')
        return out


class RegimeAnalysis(StrictModel):
    regime: RegimeType = RegimeType.UNKNOWN
    volatility_score: float = Field(default=0.5, ge=0.0, le=1.0)
    stability_score: float = Field(default=0.5, ge=0.0, le=1.0)
    transition_detected: bool = False
    summary: str = Field(default='', max_length=500)


class SignalScore(StrictModel):
    ticker: str = Field(min_length=2, max_length=15)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    agreement_score: float = Field(default=0.5, ge=0.0, le=1.0)
    signal_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    impact_score: float = Field(default=0.5, ge=0.0, le=1.0)
    source_count: int = Field(default=1, ge=0, le=50)
    novelty_score: float = Field(default=0.0, ge=0.0, le=10.0)


class ContradictionBlock(StrictModel):
    type: str = Field(default='unknown', max_length=64)
    summary: str = Field(default='', min_length=3, max_length=500)
    disagreement_score: float = Field(default=0.5, ge=0.0, le=1.0)
    severity: Literal['low', 'medium', 'high'] = 'medium'


class QualityMetrics(StrictModel):
    intelligence_quality_score: float = Field(default=0.5, ge=0.0, le=1.0)
    sentiment_diversity_score: float = Field(default=0.5, ge=0.0, le=1.0)
    minority_signal_retention_score: float = Field(default=0.5, ge=0.0, le=1.0)
    truncation_severity: float = Field(default=0.0, ge=0.0, le=1.0)
    novelty_avg_score: float = Field(default=0.0, ge=0.0, le=10.0)
    repetition_suppressed_count: int = Field(default=0, ge=0)


class ConfidenceMetrics(StrictModel):
    ai_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    agreement_score: float = Field(default=0.5, ge=0.0, le=1.0)
    signal_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    contradiction_severity: float = Field(default=0.0, ge=0.0, le=1.0)
    novelty_score: float = Field(default=0.0, ge=0.0, le=10.0)
    regime_stability: float = Field(default=0.5, ge=0.0, le=1.0)
    source_consensus: float = Field(default=0.5, ge=0.0, le=1.0)
    sentiment_diversity: float = Field(default=0.5, ge=0.0, le=1.0)
    calibrated_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reliability_score: float = Field(default=0.5, ge=0.0, le=1.0)
    inflation_penalty: float = Field(default=0.0, ge=0.0, le=1.0)


class PreservedSignal(StrictModel):
    kind: str = Field(default='signal', max_length=32)
    ticker: str = Field(default='', max_length=15)
    impact_score: float = Field(default=0.0, ge=0.0, le=1.0)
    summary: str = Field(default='', max_length=300)


class ScannerSignal(StrictModel):
    ticker: str = Field(min_length=2, max_length=15)
    strength: str = Field(default='NORMAL', max_length=16)
    change_percent: float = Field(default=0.0, ge=-100.0, le=500.0)
    volume_ratio: float = Field(default=1.0, ge=0.0, le=100.0)
    score: float = Field(default=0.0, ge=0.0, le=100.0)


class MarketPriceRow(StrictModel):
    symbol: str = Field(min_length=2, max_length=15)
    price: float = Field(ge=0.0)
    change_percent: Optional[float] = Field(default=None, ge=-100.0, le=500.0)
    source: str = Field(default='unknown', max_length=32)


class TelegramAlertPayload(StrictModel):
    category: str = Field(min_length=3, max_length=64)
    text: str = Field(min_length=10, max_length=8000)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    ticker: str = Field(default='', max_length=15)
    regime: str = Field(default='sideways', max_length=32)
    detail: str = Field(default='', max_length=200)


class OpsDebugPayload(StrictModel):
    cycle_id: Optional[str] = None
    validation_status: Literal['valid', 'degraded', 'failed'] = 'valid'
    hallucination_count: int = Field(default=0, ge=0)
    schema_failures: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    fallback_active: bool = False
    reliability_score: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence_metrics: Optional[ConfidenceMetrics] = None
    quality_metrics: Optional[QualityMetrics] = None


class ReliabilityMeta(StrictModel):
    validated: bool = True
    degraded: bool = False
    fallback_used: bool = False
    hallucinations: List[str] = Field(default_factory=list, max_length=30)
    schema_errors: List[str] = Field(default_factory=list, max_length=30)
    retry_count: int = Field(default=0, ge=0, le=2)
    reliability_score: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: ConfidenceMetrics = Field(default_factory=ConfidenceMetrics)


def validate_intelligence_dict(data: Dict[str, Any]) -> IntelligenceOutput:
    return IntelligenceOutput.model_validate(data)


def intelligence_to_dict(model: IntelligenceOutput) -> Dict[str, Any]:
    return model.model_dump(mode='json')
