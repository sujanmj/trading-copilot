"""
Adaptive Calibration Engine v1 — bounded, explainable, reversible tuning.

Observes outcomes and applies tiny threshold/confidence adjustments.
Does NOT rewrite prompts, trading logic, or architecture.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from backend.storage.db_manager import get_connection, init_db
from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR

ADAPTIVE_STATE_FILE = DATA_DIR / 'adaptive_state.json'
ENGINE_VERSION = 1

MAX_DELTA_PER_CYCLE = 0.02
MAX_CUMULATIVE = 0.15
ADAPTATION_COOLDOWN_SEC = 86400
MIN_SAMPLES_GLOBAL = 30
MIN_SAMPLES_REGIME = 10
MIN_SAMPLES_SIGNAL = 10
MIN_SAMPLES_TELEGRAM = 8

WINDOWS_DAYS = (7, 14, 30)

BASELINE_THRESHOLDS: Dict[str, float] = {
    'confidence_scale': 1.0,
    'scanner_threshold': 0.65,
    'breakout_threshold': 0.70,
    'suppression_sensitivity': 1.0,
    'contradiction_preservation': 1.0,
    'alert_strictness': 1.0,
    'telegram_cooldown_factor': 1.0,
}

REGIME_CANONICAL = {
    'trending_bullish': ('bull', 'bullish', 'uptrend', 'risk_on'),
    'trending_bearish': ('bear', 'bearish', 'downtrend', 'risk_off'),
    'sideways_chop': ('sideways', 'chop', 'range', 'neutral', 'consolidation'),
    'panic_volatile': ('panic', 'volatile', 'crash', 'high_vol', 'vix'),
    'regime_transition': ('transition', 'shift', 'inflection', 'changing'),
}

SIGNAL_CATEGORY_MATCHERS = [
    ('ULTRA scanner', lambda r: r.get('signal_type') == 'scanner' and 'ULTRA' in str(r.get('reasoning_summary') or '').upper()),
    ('breakout', lambda r: r.get('signal_type') == 'scanner'),
    ('gap-up', lambda r: 'GAP' in str(r.get('reasoning_summary') or '').upper()),
    ('govt alert', lambda r: r.get('signal_type') == 'telegram' and any(k in str(r.get('reasoning_summary') or '').upper() for k in ('GOVT', 'RBI', 'POLICY'))),
    ('macro alert', lambda r: r.get('signal_type') == 'telegram' and 'MACRO' in str(r.get('reasoning_summary') or '').upper()),
    ('Reddit momentum', lambda r: 'REDDIT' in str(r.get('reasoning_summary') or '').upper()),
    ('sector rotation', lambda r: r.get('signal_type') in ('sector', 'regime') or 'SECTOR' in str(r.get('reasoning_summary') or '').upper()),
    ('contradiction-heavy', lambda r: float(r.get('contradiction_severity') or 0) >= 0.45),
    ('telegram', lambda r: r.get('signal_type') == 'telegram'),
]


def _empty_state() -> dict:
    return {
        'version': ENGINE_VERSION,
        'baseline': dict(BASELINE_THRESHOLDS),
        'current': dict(BASELINE_THRESHOLDS),
        'signal_weights': {},
        'regime_weights': {},
        'cumulative_deltas': {k: 0.0 for k in BASELINE_THRESHOLDS},
        'last_applied_at': None,
        'last_cycle_at': None,
        'learning_active': False,
        'operator_override': None,
        'history': [],
        'timeline': [],
        'observations': [],
        'journal_notes': [],
        'windows': {},
        'confidence_realism': {},
        'safety': {
            'max_delta_per_cycle': MAX_DELTA_PER_CYCLE,
            'max_cumulative': MAX_CUMULATIVE,
            'cooldown_hours': ADAPTATION_COOLDOWN_SEC // 3600,
        },
    }


def load_adaptive_state() -> dict:
    if not ADAPTIVE_STATE_FILE.exists():
        return _empty_state()
    try:
        with open(ADAPTIVE_STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty_state()
        for key, val in BASELINE_THRESHOLDS.items():
            data.setdefault('baseline', {})[key] = data.get('baseline', {}).get(key, val)
            data.setdefault('current', {})[key] = data.get('current', {}).get(key, val)
            data.setdefault('cumulative_deltas', {})[key] = data.get('cumulative_deltas', {}).get(key, 0.0)
        data.setdefault('history', [])
        data.setdefault('timeline', [])
        data.setdefault('observations', [])
        data.setdefault('journal_notes', [])
        data.setdefault('signal_weights', {})
        data.setdefault('regime_weights', {})
        return data
    except Exception:
        return _empty_state()


def save_adaptive_state(state: dict) -> None:
    ADAPTIVE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(ADAPTIVE_STATE_FILE, state)


def reset_adaptive_baseline(*, reason: str = 'operator_reset') -> dict:
    state = _empty_state()
    state['history'].append({
        'at': datetime.now().isoformat(),
        'action': 'reset',
        'reason': reason,
        'detail': 'All adaptive thresholds restored to baseline defaults.',
    })
    save_adaptive_state(state)
    return state


def get_active_thresholds() -> dict:
    """Read hook for runtime — returns current bounded thresholds."""
    state = load_adaptive_state()
    if state.get('operator_override'):
        merged = dict(state.get('baseline') or BASELINE_THRESHOLDS)
        merged.update(state['operator_override'])
        return merged
    return dict(state.get('current') or BASELINE_THRESHOLDS)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _canonical_regime(raw: Optional[str]) -> str:
    text = (raw or 'unknown').lower().replace('-', '_').replace(' ', '_')
    for canon, hints in REGIME_CANONICAL.items():
        if any(h in text for h in hints):
            return canon
    return 'unknown'


def _categorize_signal(row: dict) -> str:
    for label, matcher in SIGNAL_CATEGORY_MATCHERS:
        try:
            if matcher(row):
                return label
        except Exception:
            continue
    return row.get('signal_type') or 'unknown'


def _query_window_rows(days: int) -> List[dict]:
    init_db()
    conn = get_connection()
    try:
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        rows = conn.execute(
            """
            SELECT e.event_date, e.signal_type, e.direction, e.confidence, e.confidence_band,
                   e.regime, e.reasoning_summary, e.contradiction_severity, e.metadata,
                   h.hit_miss, h.change_pct, h.horizon
            FROM signal_horizons h
            JOIN signal_events e ON e.id = h.event_id
            WHERE h.hit_miss IN ('HIT', 'MISS')
              AND e.event_date >= ?
            """,
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _normalize_confidence(value) -> Optional[float]:
    if value is None:
        return None
    try:
        c = float(value)
        if c > 1.0:
            c /= 10.0
        return max(0.0, min(1.0, c))
    except (TypeError, ValueError):
        return None


def _window_stats(rows: List[dict]) -> dict:
    hits = sum(1 for r in rows if r.get('hit_miss') == 'HIT')
    evaluated = len(rows)
    high_conf = [r for r in rows if (_normalize_confidence(r.get('confidence')) or 0) >= 0.8]
    hc_hits = sum(1 for r in high_conf if r.get('hit_miss') == 'HIT')
    hc_eval = len(high_conf)
    predicted_high = 0.85
    actual_high = (hc_hits / hc_eval) if hc_eval else None
    inflation = None
    if actual_high is not None and hc_eval >= 5:
        inflation = round(predicted_high - actual_high, 3)

    by_regime: Dict[str, dict] = defaultdict(lambda: {'hit': 0, 'miss': 0})
    by_signal: Dict[str, dict] = defaultdict(lambda: {'hit': 0, 'miss': 0})
    by_regime_signal: Dict[Tuple[str, str], dict] = defaultdict(lambda: {'hit': 0, 'miss': 0})
    tg = {'hit': 0, 'miss': 0}

    for r in rows:
        regime = _canonical_regime(r.get('regime'))
        cat = _categorize_signal(r)
        if r.get('hit_miss') == 'HIT':
            by_regime[regime]['hit'] += 1
            by_signal[cat]['hit'] += 1
            by_regime_signal[(regime, cat)]['hit'] += 1
            if r.get('signal_type') == 'telegram':
                tg['hit'] += 1
        else:
            by_regime[regime]['miss'] += 1
            by_signal[cat]['miss'] += 1
            by_regime_signal[(regime, cat)]['miss'] += 1
            if r.get('signal_type') == 'telegram':
                tg['miss'] += 1

    def _acc(stats: dict) -> Optional[float]:
        total = stats['hit'] + stats['miss']
        return round(stats['hit'] / total * 100, 1) if total else None

    return {
        'evaluated': evaluated,
        'accuracy_pct': round(hits / evaluated * 100, 1) if evaluated else None,
        'confidence_inflation': inflation,
        'high_conf_samples': hc_eval,
        'high_conf_accuracy_pct': round(hc_hits / hc_eval * 100, 1) if hc_eval else None,
        'regimes': {k: {'samples': v['hit'] + v['miss'], 'accuracy_pct': _acc(v)} for k, v in by_regime.items()},
        'signal_types': {k: {'samples': v['hit'] + v['miss'], 'accuracy_pct': _acc(v)} for k, v in by_signal.items()},
        'regime_signal': {
            f"{rg}|{sg}": {'samples': v['hit'] + v['miss'], 'accuracy_pct': _acc(v)}
            for (rg, sg), v in by_regime_signal.items()
        },
        'telegram': {
            'samples': tg['hit'] + tg['miss'],
            'accuracy_pct': _acc(tg),
        },
    }


def _propose_adjustments(window_14: dict, window_30: dict) -> Tuple[List[dict], List[str]]:
    """Return (adjustment_records, observation_strings)."""
    adjustments: List[dict] = []
    observations: List[str] = []

    inflation = window_14.get('confidence_inflation')
    hc_acc = window_14.get('high_conf_accuracy_pct')
    if inflation is not None and window_14.get('high_conf_samples', 0) >= MIN_SAMPLES_SIGNAL:
        if inflation > 0.08:
            delta = -_clamp(inflation * 0.15, 0.005, MAX_DELTA_PER_CYCLE)
            adjustments.append({
                'key': 'confidence_scale',
                'delta': round(delta, 4),
                'reason': (
                    f"High-confidence signals ({hc_acc}% win) underperform implied calibration "
                    f"(inflation {round(inflation * 100, 1)}%) — reducing confidence scale."
                ),
            })
            observations.append(f"Confidence inflation reduced by {abs(round(delta * 100))}%.")
        elif inflation < -0.08:
            delta = _clamp(abs(inflation) * 0.1, 0.005, MAX_DELTA_PER_CYCLE)
            adjustments.append({
                'key': 'confidence_scale',
                'delta': round(delta, 4),
                'reason': f"High-confidence signals outperform implied calibration — slight scale increase.",
            })
            observations.append("Confidence deflation corrected with slight scale increase.")

    regimes = window_14.get('regimes') or {}
    rs = window_14.get('regime_signal') or {}
    chop_breakout = rs.get('sideways_chop|breakout') or rs.get('sideways_chop|ULTRA scanner')
    if chop_breakout and chop_breakout.get('samples', 0) >= MIN_SAMPLES_REGIME:
        acc = chop_breakout.get('accuracy_pct') or 100
        if acc < 45:
            adjustments.append({
                'key': 'breakout_threshold',
                'delta': round(min(MAX_DELTA_PER_CYCLE, 0.015), 4),
                'reason': (
                    f"Breakout signals underperforming in sideways_chop ({acc}% accuracy, "
                    f"n={chop_breakout['samples']}) — tightening threshold."
                ),
            })
            observations.append("Breakout signals weakened during sideways regime.")

    panic_anomaly = rs.get('panic_volatile|breakout') or rs.get('panic_volatile|ULTRA scanner')
    if panic_anomaly and panic_anomaly.get('samples', 0) >= MIN_SAMPLES_REGIME:
        acc = panic_anomaly.get('accuracy_pct') or 0
        if acc >= 60:
            adjustments.append({
                'key': 'scanner_threshold',
                'delta': round(-min(MAX_DELTA_PER_CYCLE, 0.01), 4),
                'reason': f"Scanner/anomaly signals strong in panic volatility ({acc}%) — slight threshold ease.",
            })

    contra = window_14.get('signal_types', {}).get('contradiction-heavy')
    if contra and contra.get('samples', 0) >= MIN_SAMPLES_SIGNAL:
        acc = contra.get('accuracy_pct') or 0
        if acc >= 58:
            adjustments.append({
                'key': 'contradiction_preservation',
                'delta': round(min(MAX_DELTA_PER_CYCLE, 0.012), 4),
                'reason': f"Contradiction-heavy signals outperformed baseline ({acc}%) — preserving more evidence.",
            })
            observations.append("Contradiction-heavy signals outperformed baseline.")

    tg = window_14.get('telegram') or {}
    if tg.get('samples', 0) >= MIN_SAMPLES_TELEGRAM:
        acc = tg.get('accuracy_pct') or 50
        if acc < 40:
            adjustments.append({
                'key': 'suppression_sensitivity',
                'delta': round(min(MAX_DELTA_PER_CYCLE, 0.015), 4),
                'reason': f"Telegram alerts noisy ({acc}% useful) — increasing suppression sensitivity.",
            })
            adjustments.append({
                'key': 'telegram_cooldown_factor',
                'delta': round(min(MAX_DELTA_PER_CYCLE, 0.01), 4),
                'reason': "Repeated low-value Telegram alerts — slightly stricter cooldown.",
            })
        elif acc >= 65:
            adjustments.append({
                'key': 'alert_strictness',
                'delta': round(-min(MAX_DELTA_PER_CYCLE, 0.008), 4),
                'reason': f"Telegram alerts correlate with wins ({acc}%) — slightly relaxed strictness for non-critical.",
            })

    sideways = regimes.get('sideways_chop')
    if sideways and sideways.get('samples', 0) >= MIN_SAMPLES_REGIME:
        acc = sideways.get('accuracy_pct') or 50
        if acc < 42:
            observations.append(f"Overall accuracy weak in sideways_chop ({acc}%).")

    return adjustments, observations


def _apply_adjustments(state: dict, proposals: List[dict]) -> dict:
    baseline = state.get('baseline') or BASELINE_THRESHOLDS
    current = dict(state.get('current') or baseline)
    cumulative = dict(state.get('cumulative_deltas') or {k: 0.0 for k in baseline})
    applied = []

    merged: Dict[str, float] = {}
    for p in proposals:
        merged[p['key']] = merged.get(p['key'], 0.0) + float(p['delta'])

    for key, raw_delta in merged.items():
        if key not in baseline:
            continue
        delta = _clamp(raw_delta, -MAX_DELTA_PER_CYCLE, MAX_DELTA_PER_CYCLE)
        old_cum = float(cumulative.get(key, 0.0))
        new_cum = _clamp(old_cum + delta, -MAX_CUMULATIVE, MAX_CUMULATIVE)
        actual_delta = new_cum - old_cum
        if abs(actual_delta) < 0.0001:
            continue
        old_val = current.get(key, baseline[key])
        cumulative[key] = round(new_cum, 4)
        current[key] = round(baseline[key] + new_cum, 4)
        reasons = [p['reason'] for p in proposals if p['key'] == key]
        applied.append({
            'key': key,
            'delta': round(actual_delta, 4),
            'cumulative_delta': cumulative[key],
            'old_value': old_val,
            'new_value': current[key],
            'reason': ' '.join(reasons)[:400],
            'pct_display': f"{round(cumulative[key] * 100):+d}%",
        })

    if applied:
        state['current'] = current
        state['cumulative_deltas'] = cumulative
        state['last_applied_at'] = datetime.now().isoformat()
        state['history'] = (state.get('history') or [])[-49:] + [{
            'at': state['last_applied_at'],
            'adjustments': applied,
        }]
        state['timeline'] = (state.get('timeline') or [])[-29:] + [{
            'date': datetime.now().strftime('%Y-%m-%d'),
            'adjustments': applied,
        }]

    return state


def _detect_current_regime() -> str:
    try:
        from backend.lifecycle.lifecycle_evaluator import _load_current_regime
        return _load_current_regime()
    except Exception:
        return 'unknown'


def run_adaptive_calibration_cycle(*, force: bool = False, dry_run: bool = False) -> dict:
    """
    Analyze recent outcomes and apply bounded calibration if safety rules allow.
    """
    state = load_adaptive_state()
    now = datetime.now()
    state['last_cycle_at'] = now.isoformat()

    windows = {}
    total_evaluated = 0
    for days in WINDOWS_DAYS:
        rows = _query_window_rows(days)
        stats = _window_stats(rows)
        windows[f'{days}d'] = stats
        if days == 14:
            total_evaluated = stats.get('evaluated') or 0
    state['windows'] = windows

    w14 = windows.get('14d') or {}
    w30 = windows.get('30d') or {}
    state['confidence_realism'] = {
        'score': round(max(0.0, 1.0 - abs(w14.get('confidence_inflation') or 0)) * 100, 1),
        'inflation': w14.get('confidence_inflation'),
        'high_conf_accuracy_pct': w14.get('high_conf_accuracy_pct'),
        'high_conf_samples': w14.get('high_conf_samples'),
        'windows': {k: v.get('accuracy_pct') for k, v in windows.items()},
    }

    learning_ok = total_evaluated >= MIN_SAMPLES_GLOBAL
    state['learning_active'] = learning_ok

    last_applied = state.get('last_applied_at')
    cooldown_active = False
    if last_applied and not force:
        try:
            last_dt = datetime.fromisoformat(last_applied)
            cooldown_active = (now - last_dt).total_seconds() < ADAPTATION_COOLDOWN_SEC
        except Exception:
            cooldown_active = False

    proposals, observations = _propose_adjustments(w14, w30)
    state['observations'] = observations[:8]

    if not learning_ok:
        state['status'] = 'collecting'
        state['status_message'] = f'Awaiting evaluated prediction sample size ({total_evaluated}/{MIN_SAMPLES_GLOBAL}).'
        if not dry_run:
            save_adaptive_state(state)
        return _build_cycle_result(state, applied=[], skipped='insufficient_samples')

    current_regime = _detect_current_regime()
    if current_regime == 'panic_volatile' and not force:
        state['status'] = 'blocked'
        state['status_message'] = 'Adaptive calibration paused during panic_volatile regime.'
        if not dry_run:
            save_adaptive_state(state)
        return _build_cycle_result(state, applied=[], skipped='panic_regime')

    if cooldown_active and not force:
        state['status'] = 'cooldown'
        state['status_message'] = 'Adaptation cooldown active — max one change set per day.'
        if not dry_run:
            save_adaptive_state(state)
        return _build_cycle_result(state, applied=[], skipped='cooldown')

    if not proposals:
        state['status'] = 'stable'
        state['status_message'] = 'No bounded adjustments warranted this cycle.'
        if not dry_run:
            save_adaptive_state(state)
        return _build_cycle_result(state, applied=[], skipped='no_adjustments')

    if dry_run:
        return _build_cycle_result(state, applied=proposals, skipped=None, dry_run=True)

    before = dict(state.get('current') or {})
    state = _apply_adjustments(state, proposals)
    applied = (state.get('history') or [])[-1].get('adjustments') if state.get('history') else []
    state['journal_notes'] = observations[:5]
    state['status'] = 'adapted'
    state['status_message'] = f"Applied {len(applied)} bounded adjustment(s)."
    save_adaptive_state(state)
    return _build_cycle_result(state, applied=applied, skipped=None)


def _build_cycle_result(state: dict, applied: list, skipped: Optional[str], dry_run: bool = False) -> dict:
    return {
        'status': state.get('status', 'ok'),
        'message': state.get('status_message'),
        'learning_active': state.get('learning_active'),
        'skipped': skipped,
        'dry_run': dry_run,
        'applied': applied,
        'observations': state.get('observations') or [],
        'current': state.get('current'),
        'cumulative_deltas': state.get('cumulative_deltas'),
        'confidence_realism': state.get('confidence_realism'),
    }


def get_adaptive_dashboard_payload() -> dict:
    state = load_adaptive_state()
    current = get_active_thresholds()
    baseline = state.get('baseline') or BASELINE_THRESHOLDS
    cumulative = state.get('cumulative_deltas') or {}

    realism = state.get('confidence_realism') or {}
    windows = state.get('windows') or {}

    curves = []
    for label, lo, hi in [('0.8-1.0', 0.8, 1.0), ('0.6-0.8', 0.6, 0.8), ('0.4-0.6', 0.4, 0.6)]:
        curves.append({
            'bucket': label,
            'expected_mid': round((lo + hi) / 2, 2),
            'actual_accuracy_pct': realism.get('high_conf_accuracy_pct') if lo >= 0.8 else None,
        })

    drift = []
    for key in BASELINE_THRESHOLDS:
        cum = cumulative.get(key, 0.0)
        if abs(cum) >= 0.005:
            drift.append({
                'parameter': key,
                'baseline': baseline.get(key),
                'current': current.get(key),
                'cumulative_delta_pct': round(cum * 100, 1),
            })

    return {
        'status': state.get('status') or ('collecting' if not state.get('learning_active') else 'ok'),
        'version': ENGINE_VERSION,
        'learning_active': state.get('learning_active', False),
        'status_message': state.get('status_message'),
        'confidence_realism': realism,
        'confidence_realism_curves': curves,
        'regime_win_rates': (windows.get('14d') or {}).get('regimes') or {},
        'signal_type_reliability': (windows.get('14d') or {}).get('signal_types') or {},
        'active_adjustments': drift,
        'timeline': (state.get('timeline') or [])[-14:],
        'calibration_drift': drift,
        'current_thresholds': current,
        'baseline_thresholds': baseline,
        'safety': state.get('safety') or {},
        'observations': state.get('observations') or [],
        'last_applied_at': state.get('last_applied_at'),
        'last_cycle_at': state.get('last_cycle_at'),
    }


def get_adaptive_ops_payload() -> dict:
    dash = get_adaptive_dashboard_payload()
    cumulative = load_adaptive_state().get('cumulative_deltas') or {}
    tuning_lines = []
    for key, val in cumulative.items():
        if abs(val) >= 0.003:
            tuning_lines.append(f"{key} {round(val * 100):+d}%")

    inflation = (dash.get('confidence_realism') or {}).get('inflation')
    realism_line = 'stable'
    if inflation is not None:
        if inflation > 0.05:
            realism_line = f"slight inflation detected ({round(inflation * 100, 1)}%)"
        elif inflation < -0.05:
            realism_line = f"slight deflation detected ({round(abs(inflation) * 100, 1)}%)"

    return {
        'status': dash.get('status'),
        'learning_active': dash.get('learning_active'),
        'confidence_realism_line': realism_line,
        'confidence_realism_score': (dash.get('confidence_realism') or {}).get('score'),
        'regime_learning': (dash.get('observations') or [])[:3],
        'signal_type_learning': list((dash.get('signal_type_reliability') or {}).items())[:4],
        'active_adjustments': dash.get('active_adjustments') or [],
        'adaptive_tuning': tuning_lines,
        'safety_caps': dash.get('safety') or {},
        'last_applied_at': dash.get('last_applied_at'),
        'timeline': (dash.get('timeline') or [])[-5:],
    }


def get_adaptive_journal_notes(review_date: Optional[str] = None) -> List[str]:
    state = load_adaptive_state()
    notes = list(state.get('journal_notes') or [])
    if notes:
        return notes[:5]
    observations = state.get('observations') or []
    if observations:
        return [f"Adaptive: {o}" for o in observations[:5]]
    if not state.get('learning_active'):
        return ['Adaptive calibration collecting samples before tuning activates.']
    return ['Adaptive calibration stable — no threshold changes today.']
