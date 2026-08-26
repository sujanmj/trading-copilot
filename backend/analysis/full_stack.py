"""AstraEdge 53G deterministic full-stack analysis facade.

Delegates once to 53F historical setup evidence. No new analytics.
"""

from __future__ import annotations

from backend.analysis.historical_setup_evidence import analyze_historical_setup_evidence

SCHEMA_VERSION = '53G'

OUTPUT_KEYS = (
    'schema_version',
    'analysis_state',
    'source_historical_setup_evidence',
)


def analyze_full_stack(payload: dict) -> dict:
    """Return the exact 53F source object under a closed 53G envelope."""
    source = analyze_historical_setup_evidence(payload)
    return {
        'schema_version': SCHEMA_VERSION,
        'analysis_state': source['analysis_state'],
        'source_historical_setup_evidence': source,
    }
