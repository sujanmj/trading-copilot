"""
Canonical market snapshot schema — single JSON contract for GUI, API, Telegram.

Computed only by market_snapshot_engine; all other modules are read-only renderers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class MarketSnapshot:
    snapshot_id: str = ''
    generated_at: str = ''
    market_session: str = ''
    lifecycle: Dict[str, Any] = field(default_factory=dict)
    runtime_state: Dict[str, Any] = field(default_factory=dict)
    snapshot_age_sec: Optional[float] = None
    freshness: Dict[str, Any] = field(default_factory=dict)

    regime: Dict[str, Any] = field(default_factory=dict)
    confidence: Any = None
    quality_score: Dict[str, Any] = field(default_factory=dict)

    market_mood: Dict[str, Any] = field(default_factory=dict)
    global_mood: str = ''
    india_bias: str = ''
    retail_sentiment: str = ''

    sector_rotation: Dict[str, Any] = field(default_factory=dict)
    top_opportunities: List[Dict[str, Any]] = field(default_factory=list)
    risk_list: List[Dict[str, Any]] = field(default_factory=list)
    action_plan: str = ''
    elite_summary: Dict[str, Any] = field(default_factory=dict)

    metrics: Dict[str, Any] = field(default_factory=dict)
    providers: Dict[str, Any] = field(default_factory=dict)
    feeds: Dict[str, Any] = field(default_factory=dict)

    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    pipeline_health: Dict[str, Any] = field(default_factory=dict)

    # Intelligence payload (read-only view for renderers)
    intelligence: Dict[str, Any] = field(default_factory=dict)
    calibration: Any = None
    executive_summary: str = ''

    # Observability timestamps
    collector_at: Optional[str] = None
    snapshot_built_at: Optional[str] = None
    published_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> 'MarketSnapshot':
        if not isinstance(data, dict):
            return cls(snapshot_id=str(uuid.uuid4()))
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        kwargs = {k: data[k] for k in known if k in data}
        if not kwargs.get('snapshot_id'):
            kwargs['snapshot_id'] = str(uuid.uuid4())
        return cls(**kwargs)


def new_snapshot_id() -> str:
    return f"snap_{uuid.uuid4().hex[:12]}"
