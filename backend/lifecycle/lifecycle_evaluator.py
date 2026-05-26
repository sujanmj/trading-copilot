"""
Lifecycle prediction evaluator — horizon-aware evaluation, backfill, failure reasons.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from backend.lifecycle.lifecycle_rules import (
    UNRESOLVED_STATE,
    infer_failure_reason,
    infer_prediction_horizon,
    infer_signal_type,
    ready_for_evaluation,
    resolve_deterministic,
    sessions_elapsed,
    should_expire,
)
from backend.storage.db_manager import get_connection, init_db
from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR

LIFECYCLE_STATE_FILE = DATA_DIR / 'lifecycle_state.json'


def _now_iso() -> str:
    return datetime.now().isoformat()


def _log(msg: str):
    print(f"[LIFECYCLE-EVAL] {msg}")


def _ensure_prediction_columns(conn):
    """Lightweight migration for lifecycle fields."""
    cols = {row[1] for row in conn.execute('PRAGMA table_info(predictions)').fetchall()}
    migrations = [
        ('prediction_horizon', 'TEXT'),
        ('signal_type', 'TEXT'),
        ('failure_reason', 'TEXT'),
    ]
    for name, col_type in migrations:
        if name not in cols:
            conn.execute(f'ALTER TABLE predictions ADD COLUMN {name} {col_type}')


def _backfill_prediction_metadata(conn, prediction: dict) -> dict:
    pid = prediction['id']
    signal_type = prediction.get('signal_type') or infer_signal_type(prediction)
    horizon = infer_prediction_horizon(prediction, signal_type)
    if not prediction.get('signal_type') or not prediction.get('prediction_horizon'):
        conn.execute(
            'UPDATE predictions SET signal_type = ?, prediction_horizon = ? WHERE id = ?',
            (signal_type, horizon, pid),
        )
    prediction['signal_type'] = signal_type
    prediction['prediction_horizon'] = horizon
    return prediction


def evaluate_lifecycle_predictions(*, verbose: bool = True, backfill: bool = True) -> dict:
    """
    Horizon-aware prediction evaluation with deterministic resolution.
    Does not prematurely evaluate swing horizons.
    """
    from backend.analyzers.outcome_tracker import (
        add_nse_suffix,
        calculate_change_pct,
        fetch_price_for_date,
    )

    init_db()
    conn = get_connection()
    stats = {
        'evaluated': 0,
        'wins': 0,
        'losses': 0,
        'partials': 0,
        'expired': 0,
        'invalidated': 0,
        'unresolved': 0,
        'skipped_horizon': 0,
        'backfilled_days': 0,
    }

    try:
        _ensure_prediction_columns(conn)
        today = datetime.now().date()

        rows = conn.execute("""
            SELECT
                p.*,
                o.id as outcome_id, o.verdict, o.entry_price as outcome_entry,
                o.change_1d_pct, o.max_gain_pct, o.max_loss_pct,
                o.target_hit, o.stop_loss_hit
            FROM predictions p
            INNER JOIN outcomes o ON o.source_type = 'prediction' AND o.source_id = p.id
            WHERE o.verdict IS NULL OR o.verdict IN ('PENDING', 'UNRESOLVED', 'NEUTRAL', 'PARTIAL')
            ORDER BY p.prediction_date ASC
        """).fetchall()

        intel_regime = _load_current_regime()

        for row in rows:
            pred = _backfill_prediction_metadata(conn, dict(row))
            outcome_id = pred['outcome_id']
            ticker = pred.get('ticker')
            pred_date_str = pred.get('prediction_date')
            if not ticker or not pred_date_str:
                continue

            try:
                pred_date = datetime.strptime(pred_date_str, '%Y-%m-%d').date()
            except ValueError:
                continue

            elapsed = sessions_elapsed(pred_date_str, today)
            horizon = pred.get('prediction_horizon') or 'next_day'
            signal_type = pred.get('signal_type') or 'breakout'

            if should_expire(signal_type, elapsed, pred.get('verdict') or 'PENDING'):
                conn.execute(
                    "UPDATE outcomes SET verdict = 'EXPIRED', last_checked = ? WHERE id = ?",
                    (_now_iso(), outcome_id),
                )
                stats['expired'] += 1
                continue

            if not ready_for_evaluation(horizon, elapsed):
                stats['skipped_horizon'] += 1
                continue

            entry = pred.get('entry_price') or pred.get('outcome_entry')
            if not entry:
                entry, _ = fetch_price_for_date(ticker, pred_date)
                if entry:
                    conn.execute('UPDATE outcomes SET entry_price = ? WHERE id = ?', (entry, outcome_id))

            price_1d, _ = fetch_price_for_date(ticker, pred_date + timedelta(days=1))
            price_3d, _ = (fetch_price_for_date(ticker, pred_date + timedelta(days=3)) if elapsed >= 3 else (None, None))
            price_7d, _ = (fetch_price_for_date(ticker, pred_date + timedelta(days=7)) if elapsed >= 7 else (None, None))

            change_1d = calculate_change_pct(entry, price_1d) if price_1d and entry else None
            change_3d = calculate_change_pct(entry, price_3d) if price_3d and entry else None
            change_7d = calculate_change_pct(entry, price_7d) if price_7d and entry else None

            if horizon == 'swing_3d' and change_3d is None:
                stats['skipped_horizon'] += 1
                continue
            if horizon == 'swing_5d' and elapsed < 5:
                stats['skipped_horizon'] += 1
                continue

            change_pct = change_7d if change_7d is not None else (change_3d if change_3d is not None else change_1d)
            all_prices = [p for p in [price_1d, price_3d, price_7d] if p]
            if all_prices and entry:
                max_gain = round(((max(all_prices) - entry) / entry) * 100, 2)
                max_loss = round(((min(all_prices) - entry) / entry) * 100, 2)
            else:
                max_gain = max_loss = None

            if change_pct is None:
                conn.execute(
                    "UPDATE outcomes SET verdict = ?, last_checked = ? WHERE id = ?",
                    (UNRESOLVED_STATE, _now_iso(), outcome_id),
                )
                stats['unresolved'] += 1
                continue

            target = pred.get('target_price')
            stop_loss = pred.get('stop_loss')
            target_hit = 0
            stop_hit = 0
            if target and entry and target > entry and max_gain is not None:
                need = ((target - entry) / entry) * 100
                if max_gain >= need:
                    target_hit = 1
            if stop_loss and entry and stop_loss < entry and max_loss is not None:
                need = ((stop_loss - entry) / entry) * 100
                if max_loss <= need:
                    stop_hit = 1

            invalidated = _regime_invalidates(pred, intel_regime)
            if invalidated:
                verdict = 'INVALIDATED'
                target_hit = stop_hit = 0
                failure = 'regime_reversal'
            else:
                verdict, target_hit, stop_hit = resolve_deterministic(
                    category=pred.get('category'),
                    change_pct=change_pct,
                    max_gain=max_gain,
                    max_loss=max_loss,
                    target_hit=bool(target_hit),
                    stop_hit=bool(stop_hit),
                )
                failure = infer_failure_reason(
                    verdict=verdict,
                    signal_type=signal_type,
                    change_pct=change_pct,
                    max_gain=max_gain,
                    max_loss=max_loss,
                    target_hit=bool(target_hit),
                    stop_hit=bool(stop_hit),
                    invalidated=False,
                )

            from backend.storage.db_manager import _normalize_sqlite_value
            price_1d = _normalize_sqlite_value(price_1d)
            change_1d = _normalize_sqlite_value(change_1d)
            price_3d = _normalize_sqlite_value(price_3d)
            change_3d = _normalize_sqlite_value(change_3d)
            price_7d = _normalize_sqlite_value(price_7d)
            change_7d = _normalize_sqlite_value(change_7d)
            max_gain = _normalize_sqlite_value(max_gain, 'max_gain_pct')
            max_loss = _normalize_sqlite_value(max_loss, 'max_loss_pct')
            target_hit = _normalize_sqlite_value(target_hit, 'target_hit')
            stop_hit = _normalize_sqlite_value(stop_hit, 'stop_loss_hit')
            verdict = _normalize_sqlite_value(verdict, 'verdict')

            conn.execute("""
                UPDATE outcomes SET
                    price_1d = ?, change_1d_pct = ?,
                    price_3d = ?, change_3d_pct = ?,
                    price_7d = ?, change_7d_pct = ?,
                    max_gain_pct = ?, max_loss_pct = ?,
                    target_hit = ?, stop_loss_hit = ?,
                    verdict = ?, last_checked = ?
                WHERE id = ?
            """, (
                price_1d, change_1d,
                price_3d, change_3d,
                price_7d, change_7d,
                max_gain, max_loss,
                target_hit, stop_hit,
                verdict, _now_iso(),
                outcome_id,
            ))
            if failure:
                conn.execute('UPDATE predictions SET failure_reason = ? WHERE id = ?', (failure, pred['id']))

            stats['evaluated'] += 1
            key = verdict.lower()
            if key in stats:
                stats[key] += 1
            elif verdict == UNRESOLVED_STATE:
                stats['unresolved'] += 1

            if verbose:
                _log(f"{ticker} [{horizon}] → {verdict} ({change_pct:+.2f}%)")

        conn.commit()
    finally:
        conn.close()

    if backfill:
        stats['backfilled_days'] = backfill_missed_evaluation_days()
    return stats


def backfill_missed_evaluation_days() -> int:
    """Retro-evaluate if lifecycle missed prior sessions."""
    state = {}
    try:
        import json
        from backend.lifecycle.prediction_lifecycle_engine import load_lifecycle_state, save_lifecycle_state
        state = load_lifecycle_state()
        last_date = state.get('last_eod_cycle_date')
        today = datetime.now().strftime('%Y-%m-%d')
        if last_date and last_date < today:
            gap = (datetime.strptime(today, '%Y-%m-%d') - datetime.strptime(last_date, '%Y-%m-%d')).days
            if gap > 0:
                _log(f"Backfill gap detected: {gap} day(s) since last EOD cycle")
                result = evaluate_lifecycle_predictions(verbose=False, backfill=False)
                state['backfill_at'] = _now_iso()
                state['backfill_gap_days'] = gap
                save_lifecycle_state(state)
                return gap
    except Exception as e:
        _log(f"Backfill skipped: {e}")
    return 0


def _load_current_regime() -> str:
    from backend.lifecycle.lifecycle_rules import canonical_regime
    try:
        import json
        from backend.utils.config import DATA_DIR
        path = DATA_DIR / 'unified_intelligence.json'
        if not path.exists():
            return 'unknown'
        with open(path, 'r', encoding='utf-8') as f:
            intel = json.load(f)
        mood = intel.get('market_mood') or {}
        raw = mood.get('india_outlook') or mood.get('global_mood') or intel.get('market_bias')
        return canonical_regime(raw)
    except Exception:
        return 'unknown'


def _regime_invalidates(prediction: dict, current_regime: str) -> bool:
    if prediction.get('category') != 'opportunity':
        return False
    if current_regime not in ('trending_bearish', 'panic_volatile'):
        return False
    signal_type = prediction.get('signal_type') or infer_signal_type(prediction)
    if signal_type == 'regime outlook':
        return False
    conf = str(prediction.get('confidence') or '').upper()
    return conf in ('HIGH', 'MEDIUM')


def build_signal_type_performance() -> dict:
    init_db()
    conn = get_connection()
    try:
        _ensure_prediction_columns(conn)
        rows = conn.execute("""
            SELECT p.signal_type, o.verdict, o.max_gain_pct, o.max_loss_pct, p.confidence
            FROM predictions p
            INNER JOIN outcomes o ON o.source_type='prediction' AND o.source_id=p.id
            WHERE o.verdict IN ('WIN','LOSS','PARTIAL','NEUTRAL')
        """).fetchall()
    finally:
        conn.close()

    buckets: Dict[str, dict] = {}
    for row in rows:
        st = row['signal_type'] or 'breakout'
        b = buckets.setdefault(st, {'samples': 0, 'wins': 0, 'losses': 0, 'gains': [], 'false_positives': 0})
        b['samples'] += 1
        v = (row['verdict'] or '').upper()
        if v in ('NEUTRAL',):
            v = 'PARTIAL'
        if v == 'WIN':
            b['wins'] += 1
        elif v == 'LOSS':
            b['losses'] += 1
            if str(row['confidence'] or '').upper() in ('HIGH', 'MEDIUM'):
                b['false_positives'] += 1
        if row['max_gain_pct'] is not None:
            b['gains'].append(float(row['max_gain_pct']))

    categories = []
    for name, b in sorted(buckets.items(), key=lambda x: -x[1]['samples']):
        n = b['samples']
        wins = b['wins']
        losses = b['losses']
        avg_gain = round(sum(b['gains']) / len(b['gains']), 2) if b['gains'] else 0
        avg_loss_vals = [abs(x) for x in b['gains'] if x < 0]
        pf = round(avg_gain / (sum(avg_loss_vals) / len(avg_loss_vals)), 2) if avg_loss_vals else 0
        categories.append({
            'signal_type': name,
            'samples': n,
            'win_rate': round(wins / n * 100, 1) if n else 0,
            'avg_gain_pct': avg_gain,
            'false_positive_rate': round(b['false_positives'] / n * 100, 1) if n else 0,
            'reliability': round(wins / max(1, wins + losses) * 100, 1),
            'profit_factor': pf,
        })
    return {'categories': categories, 'min_samples_signal': 10}


def build_regime_performance() -> dict:
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT e.regime, e.signal_type, h.hit_miss, e.confidence, e.contradiction_severity
            FROM signal_horizons h
            JOIN signal_events e ON e.id = h.event_id
            WHERE h.hit_miss IN ('HIT','MISS')
        """).fetchall()
    finally:
        conn.close()

    from backend.lifecycle.lifecycle_rules import canonical_regime
    regimes: Dict[str, dict] = {}
    for row in rows:
        regime = canonical_regime(row['regime'])
        r = regimes.setdefault(regime, {
            'samples': 0, 'hits': 0, 'high_conf_hits': 0, 'high_conf_total': 0,
            'contradiction_misses': 0, 'contradiction_total': 0,
        })
        r['samples'] += 1
        if row['hit_miss'] == 'HIT':
            r['hits'] += 1
        conf = row['confidence']
        try:
            c = float(conf) if conf else 0
            if c > 1:
                c /= 10
        except (TypeError, ValueError):
            c = 0
        if c >= 0.8:
            r['high_conf_total'] += 1
            if row['hit_miss'] == 'HIT':
                r['high_conf_hits'] += 1
        if float(row['contradiction_severity'] or 0) >= 0.45:
            r['contradiction_total'] += 1
            if row['hit_miss'] == 'MISS':
                r['contradiction_misses'] += 1

    out = []
    for regime, r in regimes.items():
        n = r['samples']
        out.append({
            'regime': regime,
            'samples': n,
            'alert_precision_pct': round(r['hits'] / n * 100, 1) if n else 0,
            'confidence_realism_pct': round(r['high_conf_hits'] / r['high_conf_total'] * 100, 1) if r['high_conf_total'] else None,
            'contradiction_miss_rate': round(r['contradiction_misses'] / r['contradiction_total'] * 100, 1) if r['contradiction_total'] else None,
        })
    return {'regimes': sorted(out, key=lambda x: -x['samples']), 'min_samples_regime': 10}


def build_confidence_realism_curve() -> dict:
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT p.confidence, o.verdict
            FROM predictions p
            INNER JOIN outcomes o ON o.source_type='prediction' AND o.source_id=p.id
            WHERE o.verdict IN ('WIN','LOSS','PARTIAL','NEUTRAL')
        """).fetchall()
    finally:
        conn.close()

    bands = {'HIGH': {'n': 0, 'wins': 0}, 'MEDIUM': {'n': 0, 'wins': 0}, 'LOW': {'n': 0, 'wins': 0}}
    for row in rows:
        band = str(row['confidence'] or 'MEDIUM').upper()
        if band not in bands:
            band = 'MEDIUM'
        bands[band]['n'] += 1
        if (row['verdict'] or '').upper() == 'WIN':
            bands[band]['wins'] += 1

    curve = []
    expected = {'HIGH': 0.75, 'MEDIUM': 0.55, 'LOW': 0.35}
    inflation_total = 0.0
    for band, b in bands.items():
        if not b['n']:
            continue
        actual = b['wins'] / b['n']
        exp = expected[band]
        inflation = round((actual - exp) * 100, 1)
        inflation_total += abs(actual - exp)
        curve.append({
            'confidence_band': band,
            'samples': b['n'],
            'actual_win_rate_pct': round(actual * 100, 1),
            'expected_win_rate_pct': round(exp * 100, 1),
            'inflation_pct': inflation,
        })

    global_n = sum(b['n'] for b in bands.values())
    return {
        'bands': curve,
        'global_samples': global_n,
        'realism_score': round(max(0, 1 - inflation_total / max(1, len(curve))) * 100, 1),
        'adaptive_ready': global_n >= 30,
        'message': (
            'Awaiting evaluated prediction sample size.'
            if global_n < 30
            else 'Confidence realism tracking active.'
        ),
    }
