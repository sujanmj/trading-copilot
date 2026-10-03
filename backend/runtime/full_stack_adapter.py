"""Network-free 54B bridge into the frozen 53G facade. No runtime side effects."""
from __future__ import annotations

from copy import deepcopy
from backend.analysis.full_stack import analyze_full_stack
from backend.runtime.full_stack_contract import SCALAR_KEYS, validate_bundle

OUTCOME_HORIZON = 'INTRADAY_EOD'


def adapt_full_stack(bundle):
    identity = bundle if isinstance(bundle, dict) else {}
    reasons = validate_bundle(bundle)
    result = {
        'schema_version': '54B', 'adapter_state': 'INPUT_NOT_READY' if reasons else 'OK',
        'symbol': identity.get('symbol'), 'session_date': identity.get('session_date'),
        'observation_cutoff': identity.get('observation_cutoff'), 'missing_inputs': reasons,
        'source_state': identity.get('source_state', 'INPUT_NOT_READY'), 'full_stack_result': None,
    }
    if reasons:
        return result
    snapshot = {key: bundle[key] for key in SCALAR_KEYS}
    snapshot['frames'] = deepcopy(bundle['frames'])
    try:
        result['full_stack_result'] = analyze_full_stack({
            'current_snapshot': snapshot, 'history': [], 'outcome_horizon': OUTCOME_HORIZON,
        })
    except Exception:
        result['adapter_state'] = 'ERROR'
        result['missing_inputs'] = ['ANALYSIS_ERROR']
    return result
