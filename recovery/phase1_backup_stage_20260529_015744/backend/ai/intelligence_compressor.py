"""
Intelligence compression pipeline + change detection.
Raw sources → dedupe → rank → preservation layer → token optimize → Gemini compress → Claude synthesis input.
"""

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from backend.utils.config import ANALYSIS_STATE_FILE, DATA_DIR, ensure_dirs
from backend.storage.json_io import atomic_write_json
from backend.ai.deduplicator import deduplicate_all
from backend.ai.signal_ranker import extract_key_metrics, format_ranked_summary
from backend.ai.token_optimizer import build_sections_blob, cap_prompt_preserving_blocks, compress_section, estimate_tokens
from backend.ai.ai_pipeline_router import call_cheap, pipeline_status
from backend.ai.intelligence_preservation import (
    adaptive_compress_sections,
    build_preservation_layer,
    evaluate_compression_quality,
    format_preservation_for_claude,
    should_block_stale_reuse,
)
from backend.ai.pipeline_observability import (
    begin_cycle,
    build_input_summary,
    record_compression_stage,
    record_reuse_cycle,
    save_compression_snapshot,
)

ensure_dirs()

INTEL_FILE = DATA_DIR / 'unified_intelligence.json'

# Change thresholds
MARKET_MOVE_THRESHOLD = float(os.environ.get('MARKET_MOVE_THRESHOLD', '0.35'))
NEWS_DELTA_THRESHOLD = int(os.environ.get('NEWS_DELTA_THRESHOLD', '8'))
SCANNER_TICKER_CHANGE = True
MAX_REUSE_AGE_SECONDS = int(os.environ.get('MAX_REUSE_AGE_SECONDS', '14400'))


def _log(tag: str, msg: str):
    print(f"[{tag}] {msg}")


def _fingerprint_blob(obj: Any) -> str:
    try:
        raw = json.dumps(obj, sort_keys=True, default=str)
    except Exception:
        raw = str(obj)
    return hashlib.sha256(raw.encode('utf-8', errors='replace')).hexdigest()[:20]


def compute_source_hashes(all_data: Dict[str, Any]) -> Dict[str, str]:
    """Full source fingerprints — kept for debug/audit."""
    hashes = {}
    for key, value in (all_data or {}).items():
        if value is None:
            hashes[key] = 'empty'
        else:
            hashes[key] = _fingerprint_blob(value)
    hashes['composite'] = _fingerprint_blob(hashes)
    return hashes


def compute_semantic_state_hash(all_data: Dict[str, Any]) -> str:
    """
    Semantic hash — ignores timestamps, ordering noise, collector metadata.
    Only meaningful signal state invalidates reuse.
    """
    metrics = extract_key_metrics(all_data)
    semantic = {
        'india_avg_change': round(float(metrics.get('india_avg_change') or 0), 2),
        'news_count_bucket': int(metrics.get('news_count') or 0) // 5,
        'govt_high_impact': int(metrics.get('govt_high_impact') or 0),
        'scanner_signals_bucket': int(metrics.get('scanner_signals') or 0) // 3,
        'scanner_signature': metrics.get('scanner_signature') or [],
        'top_news_titles': metrics.get('top_news_titles') or [],
        'reddit_sentiment': metrics.get('reddit_sentiment'),
        'reddit_confidence_bucket': int(metrics.get('reddit_confidence') or 0) // 10,
    }
    digest = _fingerprint_blob(semantic)
    _log('CACHE HASH NORMALIZED', f'semantic_state={digest}')
    return digest


def load_analysis_state() -> dict:
    if not ANALYSIS_STATE_FILE.exists():
        return {}
    try:
        with open(ANALYSIS_STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        _log('COMPRESSOR', f'analysis_state reset: {e}')
        return {}


def save_analysis_state(state: dict):
    atomic_write_json(ANALYSIS_STATE_FILE, state)


def _metrics_delta(old: dict, new: dict) -> List[str]:
    reasons = []
    if not old:
        return ['initial_run']

    if abs(float(new.get('india_avg_change', 0)) - float(old.get('india_avg_change', 0))) >= MARKET_MOVE_THRESHOLD:
        reasons.append('market_move')

    news_delta = abs(int(new.get('news_count', 0)) - int(old.get('news_count', 0)))
    if news_delta >= NEWS_DELTA_THRESHOLD:
        reasons.append('news_delta')

    if int(new.get('govt_high_impact', 0)) != int(old.get('govt_high_impact', 0)):
        reasons.append('govt_change')

    if int(new.get('scanner_signals', 0)) != int(old.get('scanner_signals', 0)):
        reasons.append('scanner_count_change')

    old_tickers = old.get('top_scanner_tickers') or []
    new_tickers = new.get('top_scanner_tickers') or []
    if old_tickers != new_tickers:
        reasons.append('scanner_opportunities_changed')

    if str(new.get('reddit_sentiment')) != str(old.get('reddit_sentiment')):
        reasons.append('reddit_sentiment_change')

    conf_delta = abs(int(new.get('reddit_confidence', 0)) - int(old.get('reddit_confidence', 0)))
    if conf_delta >= 15:
        reasons.append('reddit_sentiment_spike')

    return reasons


def should_run_analysis(
    all_data: Dict[str, Any],
    force: bool = False,
) -> Dict[str, Any]:
    """
    Decide whether to run expensive synthesis or reuse prior intelligence.
    Returns decision dict with reuse/skip flags and delta reasons.
    """
    state = load_analysis_state()
    hashes = compute_source_hashes(all_data)
    semantic_hash = compute_semantic_state_hash(all_data)
    metrics = extract_key_metrics(all_data)
    prev_hashes = state.get('source_hashes') or {}
    prev_metrics = state.get('metrics') or {}
    prev_semantic = state.get('semantic_hash')

    hash_changed = hashes.get('composite') != prev_hashes.get('composite')
    semantic_changed = semantic_hash != prev_semantic
    delta_reasons = _metrics_delta(prev_metrics, metrics)

    decision = {
        'force': force,
        'hash_changed': hash_changed,
        'semantic_changed': semantic_changed,
        'semantic_hash': semantic_hash,
        'delta_reasons': delta_reasons,
        'metrics': metrics,
        'source_hashes': hashes,
        'reuse_previous': False,
        'skip_claude': False,
        'meaningful_change': bool(delta_reasons) or semantic_changed,
    }

    if force:
        decision['meaningful_change'] = True
        _log('DELTA DETECTED', 'forced refresh')
        return decision

    if not semantic_changed and not delta_reasons:
        if INTEL_FILE.exists():
            age = datetime.now().timestamp() - INTEL_FILE.stat().st_mtime
            if age < MAX_REUSE_AGE_SECONDS:
                if should_block_stale_reuse(all_data, state):
                    decision['meaningful_change'] = True
                    decision['delta_reasons'] = delta_reasons or ['preservation_safety_block']
                    _log('DELTA DETECTED', 'preservation layer blocked stale reuse')
                    return decision
                decision['reuse_previous'] = True
                _log('CLAUDE SKIPPED', f'no meaningful change — reusing intel ({int(age)}s old)')
                return decision

    if delta_reasons:
        _log('DELTA DETECTED', ', '.join(delta_reasons))
    elif semantic_changed:
        _log('DELTA DETECTED', 'semantic state changed')
    elif hash_changed:
        _log('DELTA DETECTED', 'full source hash changed (non-semantic noise)')

    return decision


def load_previous_intelligence() -> Optional[dict]:
    if not INTEL_FILE.exists():
        return None
    try:
        with open(INTEL_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            data['timestamp'] = datetime.now().isoformat()
            data['generation_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            data['reused'] = True
            data['reuse_reason'] = 'no_meaningful_change'
            return data
    except Exception as e:
        _log('COMPRESSOR', f'failed to load previous intel: {e}')
    return None


def gemini_compress_intelligence(raw_context: str, profile: Optional[dict] = None) -> tuple:
    """Cheap-tier compression of bulk formatted sections — preservation-aware.

    Returns (compressed_text, gemini_meta).
    """
    profile = profile or {}
    max_prompt = int(profile.get('max_prompt_chars') or 45000)
    word_cap = int(profile.get('gemini_word_cap') or 1800)
    meta = {
        'used': False,
        'skipped': False,
        'passthrough': False,
        'decision_reason': '',
        'input_tokens': estimate_tokens(raw_context or ''),
    }

    raw_context = cap_prompt_preserving_blocks(raw_context, max_prompt)
    if estimate_tokens(raw_context) < 800:
        meta['passthrough'] = True
        meta['decision_reason'] = 'Bulk input under 800 tokens — no Gemini compression'
        return raw_context, meta

    if profile.get('skip_gemini'):
        meta['skipped'] = True
        meta['decision_reason'] = 'Volatile/contradictory regime — Gemini skipped, token-truncated bulk'
        _log('COMPRESSOR', meta['decision_reason'])
        out = compress_section(raw_context, int(profile.get('max_per_section') or 12000) * 2)
        meta['output_tokens'] = estimate_tokens(out)
        return out, meta

    prompt = (
        "You are a market data compressor for Indian equities. Summarize the following intelligence "
        f"into a DENSE briefing under {word_cap} words.\n"
        "CRITICAL RULES:\n"
        "- Keep exact NSE tickers, prices, % changes, ULTRA/STRONG scanner signals\n"
        "- If sources disagree, state BOTH sides — never flatten contradictions\n"
        "- Preserve minority/outlier signals and unusual anomalies\n"
        "- Keep govt/SEBI/RBI/macro policy items verbatim where possible\n"
        "- Do NOT invent data or normalize sentiment to neutral\n"
        "- Remove duplicates and filler only\n"
        "Use bullet points.\n\n"
        f"{raw_context}"
    )
    result = call_cheap(prompt, use_case='compress', max_tokens=2500)
    text = (result.get('text') or '').strip()
    if text:
        meta['used'] = True
        meta['decision_reason'] = 'Gemini Flash compression applied to bulk sections'
        meta['output_tokens'] = estimate_tokens(text)
        meta['from_cache'] = bool(result.get('_from_cache'))
        _log(
            'COMPRESSOR',
            f'Gemini compressed {meta["input_tokens"]} -> {meta["output_tokens"]} tok '
            f"(aggr={profile.get('compression_aggressiveness', '?')})",
        )
        return text, meta
    meta['skipped'] = True
    meta['decision_reason'] = 'Gemini failed — fallback token truncation'
    _log('COMPRESSOR', 'Gemini compression failed — using token-optimized raw context')
    out = compress_section(raw_context, int(profile.get('max_per_section') or 12000) * 2)
    meta['output_tokens'] = estimate_tokens(out)
    return out, meta


def prepare_intelligence_pipeline(
    all_data: Dict[str, Any],
    section_builder: Callable[[Dict[str, Any]], Dict[str, str]],
    force: bool = False,
) -> Dict[str, Any]:
    """
    Full pre-processing pipeline before Claude synthesis.
    section_builder: callable that returns {section_name: formatted_str}
    """
    begin_cycle('prepare_intelligence_pipeline')
    state = load_analysis_state()
    decision = should_run_analysis(all_data, force=force)
    if decision.get('reuse_previous'):
        prev = load_previous_intelligence()
        if prev:
            age = None
            if INTEL_FILE.exists():
                age = int(datetime.now().timestamp() - INTEL_FILE.stat().st_mtime)
            record_reuse_cycle(decision, intel_age_seconds=age)
            return {
                'decision': decision,
                'reuse_intel': prev,
                'compressed_context': None,
                'pipeline_status': pipeline_status(),
                'observability_reuse': True,
            }

    cleaned = deduplicate_all(all_data)
    preservation = build_preservation_layer(cleaned, previous_state=state)
    profile = preservation['compression_profile']

    sections = section_builder(cleaned)
    section_stats = {
        name: {'original_chars': len(str(body or '')), 'compressed_chars': 0, 'discarded_chars': 0}
        for name, body in sections.items()
    }
    ranked = format_ranked_summary(cleaned)
    sections['ranked_signals'] = ranked
    section_stats['ranked_signals'] = {
        'original_chars': len(ranked),
        'compressed_chars': 0,
        'discarded_chars': 0,
    }

    max_per = int(profile.get('max_per_section') or 2800)
    bypass_kinds = {s.get('kind') for s in (preservation['scored_signals'].get('bypass_items') or [])}
    protected = set()
    if 'govt' in bypass_kinds or profile.get('volatility_index', 0) > 0.5:
        protected.add('govt')
    if 'scanner' in bypass_kinds or profile.get('disagreement_score', 0) > 0.35:
        protected.add('scanner')
    if float(profile.get('news_shock_intensity') or 0) > 0.3:
        protected.add('news')

    sections = adaptive_compress_sections(sections, profile, preservation['scored_signals'])
    for name, body in sections.items():
        stats = section_stats.setdefault(name, {'original_chars': 0})
        stats['compressed_chars'] = len(str(body or ''))
        stats['discarded_chars'] = max(0, stats.get('original_chars', 0) - stats['compressed_chars'])
        stats['protected'] = name in protected
        stats['limit_chars'] = int(max_per * 1.45) if name in protected else max_per

    raw_blob = build_sections_blob(sections, max_per_section=max_per)
    compressed_bulk, gemini_meta = gemini_compress_intelligence(raw_blob, profile=profile)

    final_context = format_preservation_for_claude(
        raw_evidence=preservation['raw_evidence_block'],
        contradictions_block=preservation['contradictions_block'],
        regime_block=preservation['regime_block'],
        scored_block=preservation['scored_signals_block'],
        compressed_summary=compressed_bulk,
    )
    final_context = cap_prompt_preserving_blocks(final_context, int(profile.get('max_prompt_chars') or 28000) + 8000)

    quality = evaluate_compression_quality(raw_blob, final_context, preservation, all_data=cleaned)
    input_summary = build_input_summary(all_data, decision)

    record_compression_stage(
        decision=decision,
        preservation=preservation,
        section_stats=section_stats,
        raw_blob=raw_blob,
        compressed_bulk=compressed_bulk,
        final_context=final_context,
        quality=quality,
        gemini_meta=gemini_meta,
        input_summary=input_summary,
    )
    save_compression_snapshot(quality)

    return {
        'decision': decision,
        'reuse_intel': None,
        'compressed_context': final_context,
        'cleaned_data': cleaned,
        'preservation': preservation,
        'quality_metrics': quality,
        'pipeline_status': pipeline_status(),
        'gemini_meta': gemini_meta,
        'section_stats': section_stats,
    }


def persist_analysis_state(decision: dict, preservation: Optional[dict] = None, quality: Optional[dict] = None):
    regime = (preservation or {}).get('regime') or {}
    state = {
        'updated_at': datetime.now().isoformat(),
        'source_hashes': decision.get('source_hashes') or {},
        'semantic_hash': decision.get('semantic_hash'),
        'metrics': decision.get('metrics') or {},
        'last_delta_reasons': decision.get('delta_reasons') or [],
        'last_regime': regime.get('primary_regime'),
        'regime_since': regime.get('regime_since'),
        'volatility_index': regime.get('volatility_index'),
        'disagreement_score': (preservation or {}).get('contradictions', {}).get('overall_disagreement_score'),
        'quality_metrics': quality or {},
        'pipeline_status': pipeline_status(),
    }
    save_analysis_state(state)
