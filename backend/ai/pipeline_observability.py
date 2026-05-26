"""
AI Pipeline Debug & Observability — snapshots, explainability, quality alerts.

Lightweight JSON-only layer; does not alter AI routing decisions.
"""

from __future__ import annotations

import copy
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.utils.config import (
    ANALYSIS_EXPLANATIONS_FILE,
    ANALYSIS_STATE_FILE,
    AI_CACHE_DIR,
    DEBUG_SNAPSHOTS_DIR,
    COMPRESSION_RATIO_WARN,
    CONTRADICTION_RETENTION_WARN,
    QUALITY_SCORE_WARN,
    SENTIMENT_PRESERVATION_WARN,
    get_env,
)

try:
    from backend.utils.config import MAX_DEBUG_SNAPSHOTS
except ImportError:
    MAX_DEBUG_SNAPSHOTS = 30
else:
    MAX_DEBUG_SNAPSHOTS = int(MAX_DEBUG_SNAPSHOTS or 30)
from backend.storage.json_io import atomic_write_json
from backend.ai.token_optimizer import estimate_tokens

_lock = threading.Lock()
_current_cycle: Dict[str, Any] = {}
_routing_events: List[dict] = []
_cycle_counter = 0

MAX_RAW_SNAPSHOT_CHARS = 48_000
MAX_TEXT_PREVIEW = 8_000
MAX_HISTORY = 50
SECRET_PATTERN = re.compile(
    r'(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*\S+',
    re.IGNORECASE,
)


def _log(tag: str, msg: str):
    print(f"[{tag}] {msg}")


def _now_id() -> str:
    return datetime.now().strftime('%Y%m%d_%H%M%S')


def _redact_text(text: str, max_len: int = MAX_TEXT_PREVIEW) -> str:
    if not text:
        return ''
    cleaned = SECRET_PATTERN.sub(r'\1=***REDACTED***', str(text))
    if len(cleaned) > max_len:
        return cleaned[:max_len] + '\n...[truncated for debug safety]...'
    return cleaned


def _safe_json(obj: Any, max_depth: int = 4) -> Any:
    """Lightweight serializable copy with size caps."""
    if max_depth <= 0:
        return '...[max depth]...'
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    if isinstance(obj, str):
        return _redact_text(obj, 2000)
    if isinstance(obj, list):
        return [_safe_json(x, max_depth - 1) for x in obj[:40]]
    if isinstance(obj, dict):
        out = {}
        for i, (k, v) in enumerate(obj.items()):
            if i >= 60:
                out['_truncated_keys'] = len(obj) - i
                break
            out[str(k)] = _safe_json(v, max_depth - 1)
        return out
    return _redact_text(str(obj), 500)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        import json
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_index() -> dict:
    return _load_json(DEBUG_SNAPSHOTS_DIR / 'index.json')


def _save_index(index: dict):
    atomic_write_json(DEBUG_SNAPSHOTS_DIR / 'index.json', index)


def begin_cycle(trigger: str = 'analysis') -> str:
    """Start observability cycle (thread-safe)."""
    global _cycle_counter
    with _lock:
        _cycle_counter += 1
        cycle_id = f"{_now_id()}_{_cycle_counter:04d}"
        _current_cycle.clear()
        _current_cycle.update({
            'cycle_id': cycle_id,
            'started_at': datetime.now().isoformat(),
            'trigger': trigger,
        })
        _routing_events.clear()
    return cycle_id


def get_current_cycle_id() -> Optional[str]:
    with _lock:
        return _current_cycle.get('cycle_id')


def record_routing_event(event: dict):
    """Append AI routing event for current cycle."""
    with _lock:
        payload = {
            'time': datetime.now().isoformat(),
            **_safe_json(event, max_depth=3),
        }
        _routing_events.append(payload)
        if len(_routing_events) > 30:
            _routing_events.pop(0)


def record_compression_stage(
    *,
    decision: dict,
    preservation: dict,
    section_stats: dict,
    raw_blob: str,
    compressed_bulk: str,
    final_context: str,
    quality: dict,
    gemini_meta: dict,
    input_summary: dict,
):
    """Store in-memory compression observability for snapshot write."""
    orig_chars = len(raw_blob or '')
    bulk_chars = len(compressed_bulk or '')
    final_chars = len(final_context or '')
    orig_tok = estimate_tokens(raw_blob or '')
    final_tok = estimate_tokens(final_context or '')
    reduction = round((1 - (final_tok / max(orig_tok, 1))) * 100, 2) if orig_tok else 0.0

    preserved_chars = (
        len(preservation.get('raw_evidence_block') or '')
        + len(preservation.get('contradictions_block') or '')
        + len(preservation.get('regime_block') or '')
        + len(preservation.get('scored_signals_block') or '')
    )

    discarded_estimate = max(0, orig_chars - bulk_chars)

    compression_obs = {
        'original_chars': orig_chars,
        'compressed_bulk_chars': bulk_chars,
        'final_context_chars': final_chars,
        'preserved_block_chars': preserved_chars,
        'discarded_chars_estimate': discarded_estimate,
        'original_tokens': orig_tok,
        'final_tokens': final_tok,
        'token_reduction_pct': reduction,
        'sections': section_stats,
        'gemini': gemini_meta,
        'sections_compressed': [k for k, v in section_stats.items() if v.get('compressed_chars', 0) < v.get('original_chars', 0)],
        'sections_expanded': [k for k, v in section_stats.items() if v.get('protected')],
        'preservation_reasoning': _build_preservation_reasoning(preservation, section_stats),
    }

    with _lock:
        _current_cycle['decision'] = _safe_json(decision)
        _current_cycle['preservation'] = _safe_json(preservation, max_depth=5)
        _current_cycle['compression'] = compression_obs
        _current_cycle['quality'] = _safe_json(quality)
        _current_cycle['input_summary'] = _safe_json(input_summary)
        _current_cycle['raw_blob_preview'] = _redact_text(raw_blob, MAX_TEXT_PREVIEW)
        _current_cycle['compressed_bulk_preview'] = _redact_text(compressed_bulk, MAX_TEXT_PREVIEW)
        _current_cycle['final_context_preview'] = _redact_text(final_context, MAX_TEXT_PREVIEW)


def record_reuse_cycle(decision: dict, intel_age_seconds: Optional[int] = None):
    """Record observability when intelligence is reused (Claude skipped)."""
    explanations = {
        'why_claude_ran': 'Claude skipped — reused prior unified_intelligence.json (no meaningful delta).',
        'why_gemini_used': 'Gemini skipped — no new compression cycle.',
        'why_cache_skipped': 'N/A — analysis short-circuited at reuse gate.',
        'why_regime_changed': 'Not evaluated — reuse path.',
        'why_signal_preserved': 'Prior cycle preservation still valid.',
        'why_signal_compressed': 'No new compression performed.',
    }
    with _lock:
        cycle_id = _current_cycle.get('cycle_id') or begin_cycle('reuse')
        _current_cycle['reuse'] = True
        _current_cycle['intel_age_seconds'] = intel_age_seconds
        _current_cycle['decision'] = _safe_json(decision)
        _current_cycle['explanations'] = explanations
        _current_cycle['claude'] = {
            'ran': False,
            'skipped_reason': 'reuse_previous_intelligence',
            'model': None,
        }

    _increment_stale_reuse()
    _save_cycle_snapshots(reuse=True)
    _persist_explanations(explanations, quality={}, warnings=[])


def record_claude_decision(
    *,
    ran: bool,
    skipped_reason: Optional[str],
    model: Optional[str],
    provider: Optional[str],
    cache_hit: bool,
    prompt_tokens: int,
    force: bool,
    budget: dict,
):
    """Finalize Claude/Gemini synthesis routing observability."""
    why_claude = ''
    if ran:
        why_claude = f"Claude synthesis executed ({model or 'unknown'}) — meaningful change detected."
        if force:
            why_claude += ' Forced via manual_refresh / force_claude.'
    else:
        why_claude = skipped_reason or 'Claude not invoked.'

    with _lock:
        _current_cycle['claude'] = {
            'ran': ran,
            'skipped_reason': skipped_reason,
            'model': model,
            'provider': provider,
            'cache_hit': cache_hit,
            'prompt_tokens': prompt_tokens,
            'force': force,
            'budget_at_call': _safe_json(budget),
        }
        explanations = _current_cycle.get('explanations') or build_explanations(
            decision=_current_cycle.get('decision') or {},
            preservation=_current_cycle.get('preservation') or {},
            compression=_current_cycle.get('compression') or {},
            claude=_current_cycle['claude'],
            routing=_routing_events,
        )
        explanations['why_claude_ran'] = why_claude
        _current_cycle['explanations'] = explanations


def build_explanations(
    *,
    decision: dict,
    preservation: dict,
    compression: dict,
    claude: dict,
    routing: List[dict],
) -> dict:
    regime = preservation.get('regime') or {}
    profile = preservation.get('compression_profile') or {}
    gemini = compression.get('gemini') or {}
    contradictions = preservation.get('contradictions') or {}

    why_gemini = gemini.get('decision_reason') or 'Gemini not used.'
    why_cache = 'No cache events recorded.'
    cache_events = [e for e in routing if 'cache' in str(e.get('event', '')).lower()]
    if cache_events:
        last = cache_events[-1]
        why_cache = f"{last.get('event')}: {last.get('reason', '')}"

    regime_shift = regime.get('regime_shift')
    why_regime = (
        f"Regime shift {regime.get('previous_regime')} -> {regime.get('primary_regime')}"
        if regime_shift
        else f"Stable regime: {regime.get('primary_regime', 'unknown')}"
    )

    bypass = preservation.get('scored_signals', {}).get('bypass_items') or []
    if bypass:
        why_preserved = f"{len(bypass)} high-impact signals bypass heavy compression (ULTRA/macro/SEBI)."
    else:
        why_preserved = 'No bypass triggers — standard preservation blocks applied.'

    if profile.get('skip_gemini'):
        why_compressed = 'Bulk sections token-truncated only — Gemini skipped due to volatile/contradictory regime.'
    elif gemini.get('used'):
        why_compressed = f"Bulk sections Gemini-compressed (aggressiveness={profile.get('compression_aggressiveness', '?')})."
    else:
        why_compressed = 'Bulk sections lightly compressed — input below Gemini threshold.'

    return {
        'why_claude_ran': claude.get('skipped_reason') if not claude.get('ran') else f"Claude ran via {claude.get('model')}",
        'why_gemini_used': why_gemini,
        'why_cache_skipped': why_cache,
        'why_regime_changed': why_regime,
        'why_signal_preserved': why_preserved,
        'why_signal_compressed': why_compressed,
        'contradiction_count': contradictions.get('count', 0),
        'disagreement_score': contradictions.get('overall_disagreement_score'),
    }


def _build_preservation_reasoning(preservation: dict, section_stats: dict) -> List[str]:
    reasons = []
    regime = preservation.get('regime') or {}
    profile = preservation.get('compression_profile') or {}
    bypass = preservation.get('scored_signals', {}).get('bypass_items') or []

    reasons.append(
        f"Regime={regime.get('primary_regime')} volatility={regime.get('volatility_index')} "
        f"compression_mode={'PRESERVE' if profile.get('skip_gemini') else 'COMPRESS'}"
    )
    for item in bypass[:8]:
        reasons.append(f"Bypass: {item.get('kind')} {item.get('ticker')} impact={item.get('impact_score')}")
    for name, stats in section_stats.items():
        if stats.get('protected'):
            reasons.append(f"Section '{name}' expanded limit ({stats.get('limit_chars')} chars)")
    return reasons


def build_input_summary(all_data: dict, decision: dict) -> dict:
    """Compact input fingerprint — not full raw JSON."""
    summary = {
        'source_keys': sorted((all_data or {}).keys()),
        'source_hashes': decision.get('source_hashes') or {},
        'metrics': decision.get('metrics') or {},
    }
    for key, val in (all_data or {}).items():
        if not isinstance(val, dict):
            summary[f'{key}_type'] = type(val).__name__
            continue
        counts = {}
        for field in ('articles', 'top_signals', 'high_impact_items', 'prices', 'tweets'):
            if isinstance(val.get(field), (list, dict)):
                counts[field] = len(val.get(field) or [])
        if counts:
            summary[f'{key}_counts'] = counts
    raw = str(summary)
    if len(raw) > MAX_RAW_SNAPSHOT_CHARS:
        summary['_note'] = 'summary capped'
    return summary


def check_quality_alerts(quality: dict, reuse: bool = False) -> List[dict]:
    """Return warning dicts and emit logs."""
    warnings = []
    if reuse:
        return warnings

    iq = float(quality.get('intelligence_quality_score') or 0)
    contra = float(quality.get('contradiction_retention_score') or 0)
    ratio = float(quality.get('compression_ratio') or 0)
    sentiment = float(quality.get('sentiment_preservation_score') or 0)

    if iq < QUALITY_SCORE_WARN:
        warnings.append({'code': 'low_intelligence_quality', 'value': iq, 'threshold': QUALITY_SCORE_WARN})
        _log('QUALITY WARNING', f'intelligence_quality_score={iq:.2f} < {QUALITY_SCORE_WARN}')

    if contra < CONTRADICTION_RETENTION_WARN:
        warnings.append({'code': 'contradiction_retention_drop', 'value': contra, 'threshold': CONTRADICTION_RETENTION_WARN})
        _log('PRESERVATION FAILURE', f'contradiction_retention={contra:.2f}')

    if ratio < COMPRESSION_RATIO_WARN and iq < 0.7:
        warnings.append({'code': 'overcompression_risk', 'value': ratio, 'threshold': COMPRESSION_RATIO_WARN})
        _log('OVERCOMPRESSION RISK', f'compression_ratio={ratio:.2f} with IQ={iq:.2f}')

    if sentiment < SENTIMENT_PRESERVATION_WARN:
        warnings.append({'code': 'weak_sentiment_preservation', 'value': sentiment, 'threshold': SENTIMENT_PRESERVATION_WARN})
        _log('QUALITY WARNING', f'sentiment_preservation={sentiment:.2f}')

    truncation = float(quality.get('truncation_severity') or quality.get('compression_ratio') or 0)
    regime = str(quality.get('primary_regime') or '')
    if truncation < COMPRESSION_RATIO_WARN and iq < 0.65:
        if regime not in ('panic_volatile', 'macro_uncertainty', 'regime_transition'):
            warnings.append({'code': 'overtruncation_risk', 'value': truncation, 'threshold': COMPRESSION_RATIO_WARN})
            _log('OVERTRUNCATION RISK', f'truncation={truncation:.2f} IQ={iq:.2f}')

    novelty = float(quality.get('novelty_avg_score') or 0)
    if novelty > 0 and novelty < 3.0:
        warnings.append({'code': 'low_novelty', 'value': novelty, 'threshold': 3.0})
        _log('LOW NOVELTY', f'avg_novelty={novelty:.2f}')

    diversity = float(quality.get('sentiment_diversity_score') or 0)
    minority = float(quality.get('minority_signal_retention_score') or 0)
    if diversity < 0.45 and sentiment < 0.65:
        warnings.append({'code': 'sentiment_collapse_risk', 'value': diversity, 'threshold': 0.45})
        _log('SENTIMENT COLLAPSE RISK', f'diversity={diversity:.2f} minority={minority:.2f}')

    if warnings:
        _maybe_telegram_quality_alert(warnings, quality)
    return warnings


def _maybe_telegram_quality_alert(warnings: List[dict], quality: dict):
    """Telegram alert only for severe multi-signal degradation — routed via severity policy."""
    severe = [w for w in warnings if w['code'] in ('low_intelligence_quality', 'overcompression_risk')]
    if len(severe) < 2:
        return
    try:
        from backend.utils.alert_routing import HIGH, emit_operational_alert
        from backend.utils.market_hours import get_market_period
        iq = quality.get('intelligence_quality_score', '?')
        msg = (
            f"AI quality degradation: IQ={iq}, warnings={len(warnings)} — "
            + ', '.join(w['code'] for w in warnings[:4])
        )
        emit_operational_alert(
            'ai_quality_degradation',
            HIGH,
            msg,
            period=get_market_period(),
            meta={'quality_iq': iq, 'warning_count': len(warnings)},
        )
    except Exception as e:
        _log('QUALITY WARNING', f'Telegram alert failed: {e}')


def save_compression_snapshot(quality: dict):
    """Persist compression-stage snapshot (before Claude). Thread-safe."""
    warnings = check_quality_alerts(quality)
    with _lock:
        if not _current_cycle.get('cycle_id'):
            return
        explanations = build_explanations(
            decision=_current_cycle.get('decision') or {},
            preservation=_current_cycle.get('preservation') or {},
            compression=_current_cycle.get('compression') or {},
            claude={},
            routing=list(_routing_events),
        )
        _current_cycle['explanations'] = explanations
        _current_cycle['quality_warnings'] = warnings
    _save_cycle_snapshots(reuse=False)
    _persist_explanations(explanations, quality=quality, warnings=warnings)


def finalize_cycle(*, quality: dict, force_save: bool = True) -> Optional[str]:
    """Write snapshots + explanations after full pipeline."""
    with _lock:
        if not _current_cycle.get('cycle_id'):
            return None
        explanations = build_explanations(
            decision=_current_cycle.get('decision') or {},
            preservation=_current_cycle.get('preservation') or {},
            compression=_current_cycle.get('compression') or {},
            claude=_current_cycle.get('claude') or {},
            routing=list(_routing_events),
        )
        _current_cycle['explanations'] = explanations
        _current_cycle['routing_events'] = list(_routing_events)
        _current_cycle['finished_at'] = datetime.now().isoformat()

    warnings = check_quality_alerts(quality)
    with _lock:
        _current_cycle['quality_warnings'] = warnings
    if force_save:
        _save_cycle_snapshots(reuse=False)
        _persist_explanations(explanations, quality=quality, warnings=warnings)
    return _current_cycle.get('cycle_id')


def _save_cycle_snapshots(reuse: bool = False):
    with _lock:
        cycle = copy.deepcopy(_current_cycle)
        routing = list(_routing_events)

    cycle_id = cycle.get('cycle_id')
    if not cycle_id:
        return

    cycle_dir = DEBUG_SNAPSHOTS_DIR / cycle_id
    cycle_dir.mkdir(parents=True, exist_ok=True)

    atomic_write_json(cycle_dir / 'raw_input_snapshot.json', cycle.get('input_summary') or {'reuse': reuse})
    atomic_write_json(cycle_dir / 'compressed_snapshot.json', {
        'compression': cycle.get('compression'),
        'raw_blob_preview': cycle.get('raw_blob_preview'),
        'compressed_bulk_preview': cycle.get('compressed_bulk_preview'),
        'final_context_preview': cycle.get('final_context_preview'),
    })
    preservation = cycle.get('preservation') or {}
    atomic_write_json(cycle_dir / 'preserved_signals.json', {
        'raw_evidence_block': preservation.get('raw_evidence_block'),
        'scored_signals': preservation.get('scored_signals'),
        'bypass_items': (preservation.get('scored_signals') or {}).get('bypass_items'),
        'preservation_reasoning': (cycle.get('compression') or {}).get('preservation_reasoning'),
        'regime': preservation.get('regime'),
        'compression_profile': preservation.get('compression_profile'),
    })
    atomic_write_json(cycle_dir / 'contradictions.json', preservation.get('contradictions') or {})
    atomic_write_json(cycle_dir / 'routing_decision.json', {
        'claude': cycle.get('claude'),
        'routing_events': routing,
        'decision': cycle.get('decision'),
        'reuse': cycle.get('reuse', False),
    })
    atomic_write_json(cycle_dir / 'quality_metrics.json', {
        'quality': cycle.get('quality'),
        'warnings': cycle.get('quality_warnings'),
        'explanations': cycle.get('explanations'),
    })

    index = _load_index()
    cycles = index.get('cycles') or []
    cycles = [c for c in cycles if c.get('id') != cycle_id]
    cycles.insert(0, {'id': cycle_id, 'ts': cycle.get('finished_at') or cycle.get('started_at'), 'reuse': reuse})
    cycles = cycles[:MAX_DEBUG_SNAPSHOTS]
    index['cycles'] = cycles
    index['latest_cycle_id'] = cycle_id
    _save_index(index)

    _prune_old_snapshots(cycles)


def _prune_old_snapshots(cycles: List[dict]):
    keep = {c['id'] for c in cycles[:MAX_DEBUG_SNAPSHOTS]}
    for path in DEBUG_SNAPSHOTS_DIR.iterdir():
        if path.is_dir() and path.name not in keep and path.name != '__pycache__':
            try:
                for f in path.glob('*.json'):
                    f.unlink(missing_ok=True)
                path.rmdir()
            except OSError:
                pass


def _persist_explanations(explanations: dict, quality: dict, warnings: List[dict]):
    store = _load_json(ANALYSIS_EXPLANATIONS_FILE)
    store['latest'] = {
        'updated_at': datetime.now().isoformat(),
        'cycle_id': _current_cycle.get('cycle_id'),
        'explanations': explanations,
        'quality': quality,
        'warnings': warnings,
    }
    history = store.get('quality_history') or []
    if quality:
        history.insert(0, {
            'cycle_id': _current_cycle.get('cycle_id'),
            'ts': datetime.now().isoformat(),
            **quality,
        })
    store['quality_history'] = history[:MAX_HISTORY]
    store['quality_warnings'] = (store.get('quality_warnings') or [])[-20:] + warnings
    store['quality_warnings'] = store['quality_warnings'][-40:]
    atomic_write_json(ANALYSIS_EXPLANATIONS_FILE, store)


def _increment_stale_reuse():
    store = _load_json(ANALYSIS_EXPLANATIONS_FILE)
    store['stale_reuse_count'] = int(store.get('stale_reuse_count') or 0) + 1
    count = store['stale_reuse_count']
    if count >= 5 and count % 5 == 0:
        _log('QUALITY WARNING', f'too many stale reuses: {count}')
    atomic_write_json(ANALYSIS_EXPLANATIONS_FILE, store)


def _load_cycle_files(cycle_id: Optional[str] = None) -> dict:
    index = _load_index()
    cid = cycle_id or index.get('latest_cycle_id')
    if not cid:
        return {'cycle_id': None, 'files': {}}
    cycle_dir = DEBUG_SNAPSHOTS_DIR / cid
    if not cycle_dir.exists():
        return {'cycle_id': cid, 'files': {}, 'error': 'snapshot not found'}
    files = {}
    for name in (
        'raw_input_snapshot.json',
        'compressed_snapshot.json',
        'preserved_signals.json',
        'contradictions.json',
        'routing_decision.json',
        'quality_metrics.json',
    ):
        loaded = _load_json(cycle_dir / name)
        files[name.replace('.json', '')] = loaded if isinstance(loaded, dict) else {}
    return {'cycle_id': cid, 'files': files, 'index': index}


def _as_dict(value: Any, default: Optional[dict] = None) -> dict:
    if isinstance(value, dict):
        return value
    return dict(default or {})


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return []


def _safe_join(items: Any, sep: str = ', ') -> str:
    return sep.join(str(x) for x in _as_list(items) if x is not None)


def _safe_delta(metrics: dict, prev_metrics: dict, key: str, cast=float):
    try:
        current = cast(metrics.get(key, 0) or 0)
        previous = cast(prev_metrics.get(key, 0) or 0)
        return round(current - previous, 4)
    except (TypeError, ValueError):
        return None


def _debug_degraded(endpoint: str, reason: str, **extra: Any) -> dict:
    payload = {
        'status': 'degraded',
        'reason': reason,
        'endpoint': endpoint,
    }
    payload.update(extra)
    return payload


def get_observability_summary() -> dict:
    """Compact summary for /api/health."""
    index = _load_index()
    explanations = _load_json(ANALYSIS_EXPLANATIONS_FILE)
    state = _load_json(ANALYSIS_STATE_FILE)
    latest = explanations.get('latest') or {}
    quality = latest.get('quality') or state.get('quality_metrics') or {}
    expl = latest.get('explanations') or {}

    regime = state.get('last_regime', 'unknown')
    compression_mode = 'preserve_detail'
    if regime in ('sideways', 'bullish_trend'):
        compression_mode = 'aggressive_ok'
    elif regime in ('panic_volatile', 'regime_transition', 'macro_uncertainty'):
        compression_mode = 'preserve_detail'

    try:
        from backend.ai.ai_budget_manager import budget_status
        budget = budget_status()
        remaining = budget.get('remaining', 0)
    except Exception:
        remaining = None

    try:
        from backend.utils.config import MARKET_SOURCE_STATUS_FILE
        market_source = _load_json(MARKET_SOURCE_STATUS_FILE)
    except Exception:
        market_source = {}

    try:
        from backend.utils.market_hours import get_watchdog_config
        wd = get_watchdog_config()
    except Exception:
        wd = {'mode': 'UNKNOWN', 'stale_threshold_seconds': None, 'night_mode': False}

    try:
        from backend.metrics.execution_metrics import get_execution_summary
        reliability = get_execution_summary()
    except Exception:
        reliability = {}

    return {
        'market_regime': regime,
        'compression_mode': compression_mode,
        'ai_budget_remaining': remaining,
        'last_quality_score': quality.get('intelligence_quality_score'),
        'last_claude_reason': expl.get('why_claude_ran') or state.get('last_claude_reason'),
        'delta_trigger_reason': ', '.join(state.get('last_delta_reasons') or []) or 'none',
        'latest_cycle_id': index.get('latest_cycle_id'),
        'snapshot_count': len(index.get('cycles') or []),
        'stale_reuse_count': explanations.get('stale_reuse_count', 0),
        'watchdog_mode': wd.get('mode'),
        'watchdog_stale_threshold_seconds': wd.get('stale_threshold_seconds'),
        'sentiment_diversity_score': quality.get('sentiment_diversity_score'),
        'minority_signal_retention_score': quality.get('minority_signal_retention_score'),
        'truncation_severity': quality.get('truncation_severity'),
        'novelty_avg_score': quality.get('novelty_avg_score'),
        'repetition_suppressed_count': quality.get('repetition_suppressed_count'),
        'semantic_hash': state.get('semantic_hash'),
        'market_active_source': market_source.get('active_source'),
        'market_angel_count': market_source.get('angel_one_count'),
        'market_yahoo_fallback_count': market_source.get('yahoo_fallback_count'),
        'market_source_degraded': market_source.get('degraded'),
        'market_period': market_source.get('market_period'),
        'hallucination_detections': reliability.get('hallucination_detections'),
        'schema_failures': reliability.get('schema_failures'),
        'validation_retries': reliability.get('retry_counts'),
        'safe_fallbacks': reliability.get('safe_fallbacks'),
        'ai_reliability_score': reliability.get('last_reliability_score'),
        'confidence_distribution': reliability.get('confidence_distribution'),
        'avg_ai_latency_ms': reliability.get('avg_ai_latency_ms'),
        'cache_hit_rate': reliability.get('cache_hit_rate'),
        'telegram_suppression_rate': reliability.get('telegram_suppression_rate'),
    }


# ── Debug API payload builders ────────────────────────────────────────────────

def debug_preservation(cycle_id: Optional[str] = None) -> dict:
    try:
        snap = _load_cycle_files(cycle_id)
        files = _as_dict(snap.get('files'))
        preserved = _as_dict(files.get('preserved_signals'))
        contradictions = _as_dict(files.get('contradictions'))
        quality = _as_dict(files.get('quality_metrics'))
        return {
            'status': 'ok',
            'cycle_id': snap.get('cycle_id'),
            'snapshot_error': snap.get('error'),
            'raw_signals_preserved': preserved.get('raw_evidence_block'),
            'contradiction_blocks': contradictions,
            'regime': preserved.get('regime'),
            'compression_profile': preserved.get('compression_profile'),
            'confidence_scores': preserved.get('scored_signals'),
            'bypassed_compression_items': preserved.get('bypass_items'),
            'quality_metrics': quality.get('quality'),
            'preservation_reasoning': preserved.get('preservation_reasoning'),
            'explanations': quality.get('explanations'),
        }
    except Exception as e:
        _log('DEBUG DEGRADED', f'preservation: {e}')
        return _debug_degraded('preservation', str(e), cycle_id=cycle_id)


def debug_compression(cycle_id: Optional[str] = None) -> dict:
    snap = _load_cycle_files(cycle_id)
    comp = (snap.get('files') or {}).get('compressed_snapshot') or {}
    compression = comp.get('compression') or {}
    return {
        'cycle_id': snap.get('cycle_id'),
        'original_prompt_size': compression.get('original_chars'),
        'compressed_size': compression.get('compressed_bulk_chars'),
        'final_context_size': compression.get('final_context_chars'),
        'preserved_block_chars': compression.get('preserved_block_chars'),
        'discarded_chars_estimate': compression.get('discarded_chars_estimate'),
        'token_reduction_pct': compression.get('token_reduction_pct'),
        'original_tokens': compression.get('original_tokens'),
        'final_tokens': compression.get('final_tokens'),
        'sections_compressed': compression.get('sections_compressed'),
        'sections_expanded': compression.get('sections_expanded'),
        'section_details': compression.get('sections'),
        'gemini_decision': compression.get('gemini'),
        'previews': {
            'raw_blob': comp.get('raw_blob_preview'),
            'compressed_bulk': comp.get('compressed_bulk_preview'),
            'final_context': comp.get('final_context_preview'),
        },
    }


def debug_ai_routing(cycle_id: Optional[str] = None) -> dict:
    snap = _load_cycle_files(cycle_id)
    routing = (snap.get('files') or {}).get('routing_decision') or {}
    try:
        from backend.ai.ai_budget_manager import budget_status, is_low_cost_mode
        from backend.ai.ai_pipeline_router import pipeline_status
        budget = budget_status()
        pipe = pipeline_status()
    except Exception:
        budget = {}
        pipe = {}
        is_low_cost_mode = lambda: False  # noqa: E731

    cache_stats = _cache_directory_stats()
    events = routing.get('routing_events') or []
    claude = routing.get('claude') or {}

    gemini_events = [e for e in events if 'gemini' in str(e.get('tier', '')).lower() or e.get('tier') == 'cheap']
    claude_events = [e for e in events if e.get('tier') == 'expensive']

    payload = {
        'cycle_id': snap.get('cycle_id'),
        'claude_decision': claude,
        'routing_events': events[-20:],
        'why_gemini_or_claude': {
            'claude_ran': claude.get('ran'),
            'claude_model': claude.get('model'),
            'skipped_reason': claude.get('skipped_reason'),
            'gemini_calls': len(gemini_events),
            'claude_calls': len(claude_events),
        },
        'cache': cache_stats,
        'budget': budget,
        'low_cost_mode': is_low_cost_mode() if callable(is_low_cost_mode) else pipe.get('low_cost_mode'),
        'pipeline_status': pipe,
        'last_expensive_call_reason': claude_events[-1] if claude_events else None,
    }
    try:
        from backend.ai.provider_manager import get_provider_ops_summary
        payload['providers'] = get_provider_ops_summary()
    except Exception as e:
        payload['providers'] = {'status': 'degraded', 'reason': str(e)}
    return payload


def debug_delta_analysis(cycle_id: Optional[str] = None) -> dict:
    try:
        snap = _load_cycle_files(cycle_id)
        files = _as_dict(snap.get('files'))
        routing = _as_dict(files.get('routing_decision'))
        raw = _as_dict(files.get('raw_input_snapshot'))
        decision = _as_dict(routing.get('decision'))
        state = _as_dict(_load_json(ANALYSIS_STATE_FILE))
        metrics = _as_dict(
            decision.get('metrics') or raw.get('metrics') or state.get('metrics')
        )
        prev_metrics = _as_dict(state.get('metrics'))
        source_hashes = _as_dict(decision.get('source_hashes'))
        prev_source_hashes = _as_dict(state.get('source_hashes'))
        delta_reasons = _as_list(decision.get('delta_reasons'))
        reuse = bool(routing.get('reuse', False))

        if snap.get('error'):
            return {
                'status': 'degraded',
                'reason': snap.get('error'),
                'cycle_id': snap.get('cycle_id'),
                'deltas': delta_reasons,
                'analysis_ran': False,
                'reuse_previous': reuse,
            }

        return {
            'status': 'ok',
            'cycle_id': snap.get('cycle_id'),
            'analysis_ran': not reuse,
            'reuse_previous': reuse,
            'why_ran_or_skipped': (
                'Reused prior intelligence — no meaningful delta'
                if reuse
                else _safe_join(delta_reasons) or 'hash or delta change'
            ),
            'hash_changed': decision.get('hash_changed'),
            'delta_reasons': delta_reasons,
            'deltas': delta_reasons,
            'source_hashes': {
                'current_composite': source_hashes.get('composite'),
                'previous_composite': prev_source_hashes.get('composite'),
                'current_semantic': decision.get('semantic_hash') or state.get('semantic_hash'),
                'previous_semantic': state.get('semantic_hash'),
                'semantic_changed': decision.get('semantic_changed'),
            },
            'market_movement_pct_delta': _safe_delta(metrics, prev_metrics, 'india_avg_change'),
            'news_count_delta': _safe_delta(metrics, prev_metrics, 'news_count', int),
            'scanner_signals_delta': _safe_delta(metrics, prev_metrics, 'scanner_signals', int),
            'reddit_sentiment_change': metrics.get('reddit_sentiment') != prev_metrics.get('reddit_sentiment'),
            'reddit_confidence_delta': _safe_delta(metrics, prev_metrics, 'reddit_confidence', int),
            'current_metrics': metrics,
            'previous_metrics': prev_metrics,
        }
    except Exception as e:
        _log('DEBUG DEGRADED', f'delta-analysis: {e}')
        return _debug_degraded(
            'delta-analysis',
            str(e),
            cycle_id=cycle_id,
            deltas=[],
            analysis_ran=False,
            reuse_previous=False,
        )


def debug_quality(cycle_id: Optional[str] = None) -> dict:
    try:
        snap = _load_cycle_files(cycle_id)
        quality_file = _as_dict(_as_dict(snap.get('files')).get('quality_metrics'))
        store = _as_dict(_load_json(ANALYSIS_EXPLANATIONS_FILE))
        state = _as_dict(_load_json(ANALYSIS_STATE_FILE))
        latest = _as_dict(store.get('latest'))
        q = _as_dict(
            quality_file.get('quality') or latest.get('quality') or state.get('quality_metrics')
        )
        return {
            'status': 'ok',
            'cycle_id': snap.get('cycle_id'),
            'snapshot_error': snap.get('error'),
            'information_retention_score': q.get('information_retention_score'),
            'contradiction_retention_score': q.get('contradiction_retention_score'),
            'sentiment_preservation_score': q.get('sentiment_preservation_score'),
            'intelligence_quality_score': q.get('intelligence_quality_score'),
            'compression_ratio': q.get('compression_ratio'),
            'truncation_severity': q.get('truncation_severity'),
            'sentiment_diversity_score': q.get('sentiment_diversity_score'),
            'minority_signal_retention_score': q.get('minority_signal_retention_score'),
            'novelty_avg_score': q.get('novelty_avg_score'),
            'repetition_suppressed_count': q.get('repetition_suppressed_count'),
            'cache_normalization': {
                'semantic_hash': state.get('semantic_hash'),
                'full_hash': _as_dict(state.get('source_hashes')).get('composite'),
            },
            'quality_history': _as_list(store.get('quality_history'))[:25],
            'recent_warnings': _as_list(store.get('quality_warnings'))[-10:],
            'thresholds': {
                'quality_score_warn': QUALITY_SCORE_WARN,
                'contradiction_retention_warn': CONTRADICTION_RETENTION_WARN,
                'compression_ratio_warn': COMPRESSION_RATIO_WARN,
                'sentiment_preservation_warn': SENTIMENT_PRESERVATION_WARN,
            },
        }
    except Exception as e:
        _log('DEBUG DEGRADED', f'quality: {e}')
        return _debug_degraded('quality', str(e), cycle_id=cycle_id)


def _cache_directory_stats() -> dict:
    if not AI_CACHE_DIR.exists():
        return {'entries': 0, 'recent_hits': 'see routing_events'}
    entries = list(AI_CACHE_DIR.glob('*.json'))
    return {
        'entries': len(entries),
        'cache_dir': str(AI_CACHE_DIR),
        'note': 'Per-call hit/miss recorded in routing_events',
    }


def list_snapshots() -> dict:
    index = _load_index()
    return {
        'latest_cycle_id': index.get('latest_cycle_id'),
        'cycles': index.get('cycles') or [],
        'max_snapshots': MAX_DEBUG_SNAPSHOTS,
    }
