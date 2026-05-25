"""
Execution metrics engine — SQLite-free JSON counters and rolling windows.
Tracks AI latency, cache, retries, hallucinations, confidence distribution.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR

METRICS_FILE = DATA_DIR / 'execution_metrics.json'
_lock = threading.Lock()

MAX_LATENCY_SAMPLES = 80
MAX_LOG_SAMPLES = 40
MAX_CONFIDENCE_SAMPLES = 100

_DEFAULT: Dict[str, Any] = {
    'updated_at': None,
    'counters': {
        'ai_calls': 0,
        'ai_latency_ms_total': 0,
        'cache_hits': 0,
        'cache_misses': 0,
        'compression_ratio_sum': 0.0,
        'compression_ratio_count': 0,
        'validation_retries': 0,
        'hallucination_detections': 0,
        'schema_failures': 0,
        'safe_fallbacks': 0,
        'telegram_suppressed': 0,
        'telegram_sent': 0,
        'stale_detector_triggers': 0,
        'regime_transitions': 0,
        'signal_survival_ok': 0,
        'signal_survival_fail': 0,
    },
    'rolling': {
        'ai_latency_ms': [],
        'compression_ratios': [],
        'confidence_scores': [],
    },
    'confidence_histogram': {
        '0.0-0.2': 0,
        '0.2-0.4': 0,
        '0.4-0.6': 0,
        '0.6-0.8': 0,
        '0.8-1.0': 0,
    },
    'recent_logs': [],
    'last_reliability_score': None,
}


def _load() -> dict:
    if not METRICS_FILE.exists():
        return json.loads(json.dumps(_DEFAULT))
    try:
        with open(METRICS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return json.loads(json.dumps(_DEFAULT))
        for key, val in _DEFAULT.items():
            if key not in data:
                data[key] = val
        return data
    except Exception:
        return json.loads(json.dumps(_DEFAULT))


def _save(data: dict):
    data['updated_at'] = datetime.now().isoformat()
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(METRICS_FILE, data)


def _append_roll(deq_list: List[float], value: float, max_len: int):
    deq_list.append(round(float(value), 2))
    while len(deq_list) > max_len:
        deq_list.pop(0)


def _bucket_confidence(score: float):
    if score < 0.2:
        return '0.0-0.2'
    if score < 0.4:
        return '0.2-0.4'
    if score < 0.6:
        return '0.4-0.6'
    if score < 0.8:
        return '0.6-0.8'
    return '0.8-1.0'


def record_reliability_event(event: str, **fields):
    with _lock:
        data = _load()
        counters = data['counters']
        if event == 'hallucination_detected':
            counters['hallucination_detections'] = counters.get('hallucination_detections', 0) + int(fields.get('count', 1))
        elif event == 'schema_failure':
            counters['schema_failures'] = counters.get('schema_failures', 0) + int(fields.get('count', 1))
        elif event == 'validation_retry':
            counters['validation_retries'] = counters.get('validation_retries', 0) + 1
        elif event == 'safe_fallback':
            counters['safe_fallbacks'] = counters.get('safe_fallbacks', 0) + 1
        elif event == 'telegram_suppressed':
            counters['telegram_suppressed'] = counters.get('telegram_suppressed', 0) + 1
        elif event == 'telegram_sent':
            counters['telegram_sent'] = counters.get('telegram_sent', 0) + 1
        elif event == 'stale_detector':
            counters['stale_detector_triggers'] = counters.get('stale_detector_triggers', 0) + 1
        elif event == 'regime_transition':
            counters['regime_transitions'] = counters.get('regime_transitions', 0) + 1
        elif event == 'signal_survival':
            if fields.get('ok'):
                counters['signal_survival_ok'] = counters.get('signal_survival_ok', 0) + 1
            else:
                counters['signal_survival_fail'] = counters.get('signal_survival_fail', 0) + 1

        score = fields.get('reliability_score')
        if score is not None:
            data['last_reliability_score'] = round(float(score), 3)
            _append_roll(data['rolling']['confidence_scores'], float(score), MAX_CONFIDENCE_SAMPLES)
            bucket = _bucket_confidence(float(score))
            hist = data['confidence_histogram']
            hist[bucket] = hist.get(bucket, 0) + 1

        _save(data)


def record_ai_call(
    *,
    latency_ms: float,
    use_case: str = '',
    cache_hit: bool = False,
    success: bool = True,
    compression_ratio: Optional[float] = None,
):
    with _lock:
        data = _load()
        c = data['counters']
        c['ai_calls'] = c.get('ai_calls', 0) + 1
        c['ai_latency_ms_total'] = c.get('ai_latency_ms_total', 0) + int(latency_ms)
        if cache_hit:
            c['cache_hits'] = c.get('cache_hits', 0) + 1
        else:
            c['cache_misses'] = c.get('cache_misses', 0) + 1
        if compression_ratio is not None:
            c['compression_ratio_sum'] = c.get('compression_ratio_sum', 0.0) + float(compression_ratio)
            c['compression_ratio_count'] = c.get('compression_ratio_count', 0) + 1
            _append_roll(data['rolling']['compression_ratios'], float(compression_ratio), 40)
        _append_roll(data['rolling']['ai_latency_ms'], latency_ms, MAX_LATENCY_SAMPLES)
        _save(data)


def record_log_event(payload: dict):
    with _lock:
        data = _load()
        logs: List[dict] = data.get('recent_logs') or []
        logs.append({
            'event': payload.get('event'),
            'timestamp': payload.get('timestamp'),
            'cycle_id': payload.get('cycle_id'),
        })
        data['recent_logs'] = logs[-MAX_LOG_SAMPLES:]
        _save(data)


def get_execution_summary() -> dict:
    with _lock:
        data = _load()
    c = data.get('counters') or {}
    rolling = data.get('rolling') or {}
    latencies = rolling.get('ai_latency_ms') or []
    ratios = rolling.get('compression_ratios') or []
    confidences = rolling.get('confidence_scores') or []
    ai_calls = max(1, c.get('ai_calls', 0))
    cache_total = c.get('cache_hits', 0) + c.get('cache_misses', 0)
    ratio_count = max(1, c.get('compression_ratio_count', 0))
    survival_ok = c.get('signal_survival_ok', 0)
    survival_fail = c.get('signal_survival_fail', 0)
    survival_total = max(1, survival_ok + survival_fail)
    tg_sent = c.get('telegram_sent', 0)
    tg_sup = c.get('telegram_suppressed', 0)
    tg_total = max(1, tg_sent + tg_sup)

    return {
        'updated_at': data.get('updated_at'),
        'avg_ai_latency_ms': round(sum(latencies) / len(latencies), 1) if latencies else None,
        'cache_hit_rate': round(c.get('cache_hits', 0) / cache_total, 3) if cache_total else None,
        'avg_compression_ratio': round(c.get('compression_ratio_sum', 0) / ratio_count, 3) if ratio_count else None,
        'retry_counts': c.get('validation_retries', 0),
        'hallucination_detections': c.get('hallucination_detections', 0),
        'schema_failures': c.get('schema_failures', 0),
        'safe_fallbacks': c.get('safe_fallbacks', 0),
        'signal_survival_rate': round(survival_ok / survival_total, 3),
        'telegram_suppression_rate': round(tg_sup / tg_total, 3),
        'stale_detector_triggers': c.get('stale_detector_triggers', 0),
        'regime_transition_frequency': c.get('regime_transitions', 0),
        'confidence_distribution': data.get('confidence_histogram') or {},
        'last_reliability_score': data.get('last_reliability_score'),
        'alert_precision_proxy': round(tg_sent / tg_total, 3) if tg_total else None,
        'counters': c,
    }


def get_reliability_debug() -> dict:
    try:
        summary = get_execution_summary()
        with _lock:
            data = _load()
        return {
            'status': 'ok',
            'execution': summary,
            'recent_logs': (data.get('recent_logs') or [])[-15:],
            'confidence_histogram': data.get('confidence_histogram') or {},
            'validation_status': 'operational',
            'ai_reliability_score': summary.get('last_reliability_score'),
        }
    except Exception as e:
        return {
            'status': 'degraded',
            'reason': str(e),
            'execution': {},
            'recent_logs': [],
            'confidence_histogram': {},
            'validation_status': 'degraded',
            'ai_reliability_score': None,
        }
