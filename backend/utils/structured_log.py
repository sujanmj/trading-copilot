"""
Lightweight structured logging — JSON-like payloads with readable console output.
No ELK / distributed tracing; preserves existing tag visibility.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from backend.metrics.execution_metrics import record_log_event


def rel_log(
    event: str,
    *,
    tag: str = 'RELIABILITY',
    cycle_id: Optional[str] = None,
    console_tag: Optional[str] = None,
    **fields: Any,
) -> Dict[str, Any]:
    """Emit a structured reliability log line and optionally persist a sample."""
    payload: Dict[str, Any] = {
        'event': event,
        'timestamp': datetime.now().isoformat(),
    }
    if cycle_id:
        payload['cycle_id'] = cycle_id
    for key, value in fields.items():
        if value is not None:
            payload[key] = value

    line = json.dumps(payload, default=str, ensure_ascii=False)
    display_tag = console_tag or tag.upper().replace(' ', '_')
    print(f"[{display_tag}] {line}")

    try:
        record_log_event(payload)
    except Exception:
        pass

    return payload


def pipeline_log(event: str, **fields: Any) -> Dict[str, Any]:
    """Structured log for pipeline / cache / routing events."""
    return rel_log(event, tag='PIPELINE', **fields)
