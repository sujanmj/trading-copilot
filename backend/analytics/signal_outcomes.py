"""
Signal outcome tracking + confidence calibration evolution.

Lightweight SQLite + JSON statistical memory — no vector DB, no ML training.
Tracks scanner, AI opportunities, Telegram alerts, regime and sector predictions.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.storage.db_manager import get_connection, init_db, upsert_outcome
from backend.storage.json_io import atomic_write_json
from backend.utils.config import ANALYSIS_STATE_FILE, DATA_DIR

INTELLIGENCE_MEMORY_FILE = DATA_DIR / 'intelligence_memory.json'
MARKET_DATA_FILE = DATA_DIR / 'latest_market_data.json'

MIN_SAMPLES_GLOBAL = 12
MIN_SAMPLES_TELEGRAM = 20
MIN_SAMPLES_REGIME = 8
MIN_SAMPLES_CONF_BUCKET = 10

HORIZONS = {
    '15m': 15,
    '1h': 60,
    'intraday': None,
    'next_day': None,
}

_lock = threading.Lock()


def _log(tag: str, msg: str):
    print(f"[{tag}] {msg}")


def _now_iso() -> str:
    return datetime.now().isoformat()


def _today() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def _parse_confidence_band(value: Any) -> Tuple[Optional[float], str]:
    if value is None:
        return None, 'MEDIUM'
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1.0:
            v = v / 10.0
        v = max(0.0, min(1.0, v))
        band = 'HIGH' if v >= 0.75 else ('LOW' if v <= 0.45 else 'MEDIUM')
        return v, band
    text = str(value).upper()
    if 'HIGH' in text or 'VERY' in text:
        return 0.85, 'HIGH'
    if 'LOW' in text:
        return 0.35, 'LOW'
    return 0.55, 'MEDIUM'


def _ensure_tables():
    init_db()


def _insert_event(event: dict) -> Optional[int]:
    _ensure_tables()
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO signal_events (
                event_ts, event_date, signal_type, source, ticker, direction,
                confidence, confidence_band, regime, sector, reasoning_summary,
                contradiction_severity, source_consensus, entry_price, dedupe_key, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.get('event_ts'),
                event.get('event_date'),
                event.get('signal_type'),
                event.get('source'),
                event.get('ticker'),
                event.get('direction'),
                event.get('confidence'),
                event.get('confidence_band'),
                event.get('regime'),
                event.get('sector'),
                event.get('reasoning_summary'),
                event.get('contradiction_severity'),
                event.get('source_consensus'),
                event.get('entry_price'),
                event.get('dedupe_key'),
                json.dumps(event.get('metadata') or {}),
            ),
        )
        conn.commit()
        if cur.lastrowid:
            event_id = cur.lastrowid
        else:
            row = conn.execute(
                "SELECT id FROM signal_events WHERE dedupe_key = ?",
                (event.get('dedupe_key'),),
            ).fetchone()
            event_id = row['id'] if row else None
        if event_id:
            _seed_horizons(conn, event_id, event.get('event_ts'))
        return event_id
    except Exception as e:
        _log('OUTCOME TRACK', f'insert failed: {e}')
        return None
    finally:
        conn.close()


def _seed_horizons(conn: sqlite3.Connection, event_id: int, event_ts: str):
    try:
        base = datetime.fromisoformat(event_ts)
    except ValueError:
        base = datetime.now()
    for horizon in HORIZONS:
        if horizon == '15m':
            due = base + timedelta(minutes=15)
        elif horizon == '1h':
            due = base + timedelta(hours=1)
        elif horizon == 'intraday':
            due = base.replace(hour=15, minute=30, second=0, microsecond=0)
            if due <= base:
                due = due + timedelta(days=1)
        else:
            due = (base + timedelta(days=1)).replace(hour=15, minute=35, second=0, microsecond=0)
        conn.execute(
            """
            INSERT OR IGNORE INTO signal_horizons (event_id, horizon, due_at, hit_miss)
            VALUES (?, ?, ?, 'PENDING')
            """,
            (event_id, horizon, due.isoformat()),
        )
    conn.commit()


def _fetch_current_price(ticker: Optional[str]) -> Optional[float]:
    if not ticker:
        return None
    sym = str(ticker).upper().strip()
    if MARKET_DATA_FILE.exists():
        try:
            with open(MARKET_DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            prices = data.get('prices') or {}
            if sym in prices:
                p = prices[sym]
                if isinstance(p, dict):
                    return float(p.get('ltp') or p.get('price') or 0) or None
                return float(p) if p else None
        except Exception:
            pass
    try:
        from backend.utils.angel_one_client import fetch_ltp
        return fetch_ltp(sym)
    except Exception:
        return None


def _fetch_nifty_change_pct() -> Optional[float]:
    if not MARKET_DATA_FILE.exists():
        return None
    try:
        with open(MARKET_DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for key in ('NIFTY', 'NIFTY 50', 'NIFTY50'):
            if key in (data.get('prices') or {}):
                p = data['prices'][key]
                if isinstance(p, dict):
                    return float(p.get('change_percent') or p.get('pct_change') or 0)
    except Exception:
        pass
    return None


def _classify_hit(direction: str, change_pct: float, horizon: str) -> str:
    d = (direction or 'NEUTRAL').upper()
    threshold = 0.5 if horizon in ('15m', '1h') else 1.0
    if d in ('BULLISH', 'BUY', 'ACCUMULATE'):
        if change_pct >= threshold:
            return 'HIT'
        if change_pct <= -threshold:
            return 'MISS'
        return 'NEUTRAL'
    if d in ('BEARISH', 'SELL', 'AVOID'):
        if change_pct <= -threshold:
            return 'HIT'
        if change_pct >= threshold:
            return 'MISS'
        return 'NEUTRAL'
    if abs(change_pct) < threshold:
        return 'NEUTRAL'
    return 'NEUTRAL'


def track_intelligence_snapshot(intel: dict, analysis_state: Optional[dict] = None) -> int:
    """Track AI opportunities, regime, sector rotation from unified intelligence."""
    if not isinstance(intel, dict):
        return 0
    state = analysis_state or {}
    if not state and ANALYSIS_STATE_FILE.exists():
        try:
            with open(ANALYSIS_STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f) or {}
        except Exception:
            state = {}

    regime = state.get('last_regime') or 'sideways'
    contra = float(state.get('disagreement_score') or 0)
    conf_metrics = intel.get('confidence_metrics') or {}
    source_consensus = float(conf_metrics.get('source_consensus') or conf_metrics.get('agreement_score') or 0.5)
    event_ts = intel.get('timestamp') or _now_iso()
    event_date = event_ts[:10]

    tracked = 0
    mood = intel.get('market_mood') or {}
    india_outlook = str(mood.get('india_outlook') or 'NEUTRAL').upper()
    direction = 'BULLISH' if 'BULL' in india_outlook else ('BEARISH' if 'BEAR' in india_outlook else 'NEUTRAL')
    conf_val, conf_band = _parse_confidence_band(mood.get('confidence_level'))

    if _insert_event({
        'event_ts': event_ts,
        'event_date': event_date,
        'signal_type': 'regime',
        'source': 'master_analyzer',
        'ticker': None,
        'direction': direction,
        'confidence': conf_val,
        'confidence_band': conf_band,
        'regime': regime,
        'sector': None,
        'reasoning_summary': (intel.get('executive_summary') or '')[:240],
        'contradiction_severity': contra,
        'source_consensus': source_consensus,
        'entry_price': _fetch_nifty_change_pct(),
        'dedupe_key': f'regime_{event_date}_{regime}',
        'metadata': {'india_outlook': india_outlook, 'global_mood': mood.get('global_mood')},
    }):
        tracked += 1

    sectors = intel.get('sector_rotation') or {}
    for sector in (sectors.get('bullish') or [])[:4]:
        if _insert_event({
            'event_ts': event_ts,
            'event_date': event_date,
            'signal_type': 'sector',
            'source': 'master_analyzer',
            'ticker': None,
            'direction': 'BULLISH',
            'confidence': conf_val,
            'confidence_band': conf_band,
            'regime': regime,
            'sector': str(sector).upper(),
            'reasoning_summary': f'Bullish sector rotation: {sector}',
            'contradiction_severity': contra,
            'source_consensus': source_consensus,
            'entry_price': None,
            'dedupe_key': f'sector_bull_{event_date}_{sector}',
            'metadata': {'rotation': 'bullish'},
        }):
            tracked += 1

    for sector in (sectors.get('bearish') or [])[:4]:
        if _insert_event({
            'event_ts': event_ts,
            'event_date': event_date,
            'signal_type': 'sector',
            'source': 'master_analyzer',
            'ticker': None,
            'direction': 'BEARISH',
            'confidence': conf_val,
            'confidence_band': conf_band,
            'regime': regime,
            'sector': str(sector).upper(),
            'reasoning_summary': f'Bearish sector rotation: {sector}',
            'contradiction_severity': contra,
            'source_consensus': source_consensus,
            'entry_price': None,
            'dedupe_key': f'sector_bear_{event_date}_{sector}',
            'metadata': {'rotation': 'bearish'},
        }):
            tracked += 1

    for i, opp in enumerate(intel.get('top_opportunities') or [], 1):
        if not isinstance(opp, dict):
            continue
        ticker = str(opp.get('symbol') or '').upper()
        if not ticker or len(ticker) < 2:
            continue
        action = str(opp.get('action') or 'WATCH').upper()
        cval, cband = _parse_confidence_band(opp.get('confidence'))
        entry = _fetch_current_price(ticker)
        if _insert_event({
            'event_ts': event_ts,
            'event_date': event_date,
            'signal_type': 'ai_opportunity',
            'source': 'master_analyzer',
            'ticker': ticker,
            'direction': action if action in ('BUY', 'SELL', 'HOLD', 'WATCH') else 'BUY',
            'confidence': cval,
            'confidence_band': cband,
            'regime': regime,
            'sector': None,
            'reasoning_summary': str(opp.get('logic') or '')[:240],
            'contradiction_severity': contra,
            'source_consensus': source_consensus,
            'entry_price': entry,
            'dedupe_key': f'opp_{event_date}_{ticker}_{i}',
            'metadata': {'rank': i, 'action': action},
        }):
            tracked += 1

    _refresh_intelligence_memory()
    if tracked:
        _log('OUTCOME TRACK', f'tracked {tracked} intelligence events')
    return tracked


def track_scanner_signal(sig: dict, signal_date: Optional[str] = None) -> Optional[int]:
    ticker = str(sig.get('ticker') or '').upper()
    if not ticker:
        return None
    event_date = signal_date or _today()
    cval, cband = _parse_confidence_band(sig.get('strength'))
    return _insert_event({
        'event_ts': _now_iso(),
        'event_date': event_date,
        'signal_type': 'scanner',
        'source': 'stock_scanner',
        'ticker': ticker,
        'direction': str(sig.get('direction') or 'NEUTRAL').upper(),
        'confidence': cval,
        'confidence_band': cband,
        'regime': None,
        'sector': sig.get('sector'),
        'reasoning_summary': f"{sig.get('strength')} {sig.get('direction')} vol={sig.get('volume_ratio')}",
        'contradiction_severity': None,
        'source_consensus': None,
        'entry_price': sig.get('price') or _fetch_current_price(ticker),
        'dedupe_key': f'scanner_{event_date}_{ticker}_{sig.get("strength")}',
        'metadata': {'signal_types': sig.get('signals', [])},
    })


def track_telegram_alert(
    *,
    category: str,
    ticker: str = '',
    confidence: float = 0.5,
    regime: str = 'sideways',
    direction: str = 'NEUTRAL',
    reasoning: str = '',
    contradiction_severity: Optional[float] = None,
) -> Optional[int]:
    event_date = _today()
    cval = max(0.0, min(1.0, float(confidence)))
    cband = 'HIGH' if cval >= 0.75 else ('LOW' if cval <= 0.45 else 'MEDIUM')
    return _insert_event({
        'event_ts': _now_iso(),
        'event_date': event_date,
        'signal_type': 'telegram',
        'source': category,
        'ticker': ticker or None,
        'direction': direction,
        'confidence': cval,
        'confidence_band': cband,
        'regime': regime,
        'sector': None,
        'reasoning_summary': reasoning[:240] if reasoning else category,
        'contradiction_severity': contradiction_severity,
        'source_consensus': None,
        'entry_price': _fetch_current_price(ticker) if ticker else None,
        'dedupe_key': f'tg_{event_date}_{category}_{ticker}',
        'metadata': {'category': category},
    })


def evaluate_due_horizons(limit: int = 80) -> dict:
    """Evaluate pending horizon outcomes using live/cached prices."""
    _ensure_tables()
    now = datetime.now()
    evaluated = 0
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT h.id AS horizon_id, h.horizon, h.due_at, h.mfe_pct, h.mae_pct,
                   e.id AS event_id, e.ticker, e.direction, e.entry_price, e.signal_type, e.regime
            FROM signal_horizons h
            JOIN signal_events e ON e.id = h.event_id
            WHERE h.hit_miss = 'PENDING' AND h.due_at <= ?
            ORDER BY h.due_at ASC
            LIMIT ?
            """,
            (now.isoformat(), limit),
        ).fetchall()

        for row in rows:
            row = dict(row)
            horizon = row['horizon']
            ticker = row['ticker']
            entry = row['entry_price']

            if row['signal_type'] == 'regime' and not ticker:
                change = _fetch_nifty_change_pct()
                if change is None:
                    continue
                hit = _classify_hit(row['direction'], change, horizon)
                conn.execute(
                    """
                    UPDATE signal_horizons SET evaluated_at=?, change_pct=?, hit_miss=?, mfe_pct=?, mae_pct=?
                    WHERE id=?
                    """,
                    (_now_iso(), change, hit, max(0, change), min(0, change), row['horizon_id']),
                )
                evaluated += 1
                continue

            if not ticker or not entry:
                continue

            price = _fetch_current_price(ticker)
            if not price:
                continue

            change_pct = round(((price - entry) / entry) * 100, 3)
            mfe = max(row['mfe_pct'] or change_pct, change_pct)
            mae = min(row['mae_pct'] or change_pct, change_pct)
            hit = _classify_hit(row['direction'], change_pct, horizon)

            conn.execute(
                """
                UPDATE signal_horizons SET evaluated_at=?, price=?, change_pct=?,
                       mfe_pct=?, mae_pct=?, hit_miss=?
                WHERE id=?
                """,
                (_now_iso(), price, change_pct, mfe, mae, hit, row['horizon_id']),
            )
            evaluated += 1

        conn.commit()
    finally:
        conn.close()

    if evaluated:
        _refresh_intelligence_memory()
        _log('OUTCOME EVAL', f'evaluated {evaluated} horizons')
    return {'evaluated': evaluated}


def _query_horizon_stats(where_sql: str = '', params: tuple = ()) -> List[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT e.signal_type, e.regime, e.confidence_band, e.direction,
                   h.horizon, h.hit_miss, h.change_pct, e.contradiction_severity
            FROM signal_horizons h
            JOIN signal_events e ON e.id = h.event_id
            WHERE h.hit_miss IN ('HIT', 'MISS', 'NEUTRAL') {where_sql}
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_confidence_calibration(min_samples: int = MIN_SAMPLES_CONF_BUCKET) -> dict:
    rows = _query_horizon_stats()
    buckets: Dict[str, dict] = defaultdict(lambda: {'hit': 0, 'miss': 0, 'neutral': 0, 'moves': []})

    for r in rows:
        band = r.get('confidence_band') or 'UNKNOWN'
        conf_key = f"{band}"
        if r['hit_miss'] == 'HIT':
            buckets[conf_key]['hit'] += 1
        elif r['hit_miss'] == 'MISS':
            buckets[conf_key]['miss'] += 1
        else:
            buckets[conf_key]['neutral'] += 1
        if r.get('change_pct') is not None:
            buckets[conf_key]['moves'].append(float(r['change_pct']))

    calibration = []
    for band, stats in buckets.items():
        total = stats['hit'] + stats['miss']
        if total < min_samples:
            continue
        precision = round(stats['hit'] / total * 100, 1) if total else 0
        avg_move = round(sum(stats['moves']) / len(stats['moves']), 2) if stats['moves'] else 0
        false_positive_rate = round(stats['miss'] / total * 100, 1) if total else 0
        calibration.append({
            'confidence_band': band,
            'samples': total,
            'precision_pct': precision,
            'avg_move_pct': avg_move,
            'false_positive_rate_pct': false_positive_rate,
            'statistically_meaningful': total >= min_samples,
        })

    numeric_buckets: Dict[str, dict] = defaultdict(lambda: {'hit': 0, 'total': 0})
    for r in rows:
        if r['hit_miss'] not in ('HIT', 'MISS'):
            continue
        bucket = 'high' if (r.get('confidence_band') or '') == 'HIGH' else (
            'low' if (r.get('confidence_band') or '') == 'LOW' else 'medium'
        )
        numeric_buckets[bucket]['total'] += 1
        if r['hit_miss'] == 'HIT':
            numeric_buckets[bucket]['hit'] += 1

    return {
        'bands': sorted(calibration, key=lambda x: x['confidence_band']),
        'summary': {
            k: {
                'samples': v['total'],
                'hit_rate_pct': round(v['hit'] / v['total'] * 100, 1) if v['total'] >= min_samples else None,
                'meaningful': v['total'] >= min_samples,
            }
            for k, v in numeric_buckets.items()
        },
        'min_samples_required': min_samples,
    }


def get_regime_performance(min_samples: int = MIN_SAMPLES_REGIME) -> dict:
    rows = _query_horizon_stats("AND e.signal_type IN ('regime', 'telegram', 'ai_opportunity', 'scanner')")
    regimes: Dict[str, dict] = defaultdict(lambda: {'hit': 0, 'miss': 0, 'total': 0, 'telegram': 0, 'tg_hit': 0})

    for r in rows:
        regime = r.get('regime') or 'unknown'
        if r['hit_miss'] in ('HIT', 'MISS'):
            regimes[regime]['total'] += 1
            if r['hit_miss'] == 'HIT':
                regimes[regime]['hit'] += 1
            else:
                regimes[regime]['miss'] += 1
        if r.get('signal_type') == 'telegram' and r['hit_miss'] in ('HIT', 'MISS'):
            regimes[regime]['telegram'] += 1
            if r['hit_miss'] == 'HIT':
                regimes[regime]['tg_hit'] += 1

    table = []
    for regime, stats in regimes.items():
        if stats['total'] < min_samples:
            continue
        table.append({
            'regime': regime,
            'samples': stats['total'],
            'alert_precision_pct': round(stats['hit'] / stats['total'] * 100, 1),
            'telegram_precision_pct': (
                round(stats['tg_hit'] / stats['telegram'] * 100, 1)
                if stats['telegram'] >= min_samples else None
            ),
            'statistically_meaningful': stats['total'] >= min_samples,
        })

    return {'regimes': sorted(table, key=lambda x: x['samples'], reverse=True), 'min_samples_required': min_samples}


def get_signal_quality_scores() -> dict:
    rows = _query_horizon_stats()
    by_type: Dict[str, dict] = defaultdict(lambda: {'hit': 0, 'miss': 0, 'neutral': 0})
    contra: Dict[str, dict] = defaultdict(lambda: {'hit': 0, 'total': 0})

    for r in rows:
        st = r.get('signal_type') or 'unknown'
        by_type[st][r['hit_miss'].lower()] = by_type[st].get(r['hit_miss'].lower(), 0) + 1
        if r.get('contradiction_severity') is not None and r['hit_miss'] in ('HIT', 'MISS'):
            bucket = 'high_contra' if float(r['contradiction_severity']) >= 0.45 else 'low_contra'
            contra[bucket]['total'] += 1
            if r['hit_miss'] == 'HIT':
                contra[bucket]['hit'] += 1

    signal_types = []
    for st, stats in by_type.items():
        evaluated = stats.get('hit', 0) + stats.get('miss', 0)
        if evaluated < 5:
            continue
        signal_types.append({
            'signal_type': st,
            'samples': evaluated,
            'precision_pct': round(stats.get('hit', 0) / evaluated * 100, 1),
            'survival_rate_pct': round(
                (stats.get('hit', 0) + stats.get('neutral', 0)) / max(1, sum(stats.values())) * 100, 1
            ),
        })

    contra_value = []
    for bucket, stats in contra.items():
        if stats['total'] < MIN_SAMPLES_GLOBAL:
            continue
        contra_value.append({
            'bucket': bucket,
            'samples': stats['total'],
            'predictive_value_pct': round(stats['hit'] / stats['total'] * 100, 1),
        })

    return {
        'signal_types': sorted(signal_types, key=lambda x: x['precision_pct'], reverse=True),
        'contradiction_usefulness': contra_value,
        'overall_precision_pct': _overall_precision(rows),
    }


def _overall_precision(rows: List[dict]) -> Optional[float]:
    hits = sum(1 for r in rows if r.get('hit_miss') == 'HIT')
    evaluated = sum(1 for r in rows if r.get('hit_miss') in ('HIT', 'MISS'))
    if evaluated < MIN_SAMPLES_GLOBAL:
        return None
    return round(hits / evaluated * 100, 1)


def _refresh_intelligence_memory():
    """Lightweight statistical memory — JSON only, no vector DB."""
    rows = _query_horizon_stats()
    if len(rows) < 5:
        return

    wins = [r for r in rows if r.get('hit_miss') == 'HIT']
    losses = [r for r in rows if r.get('hit_miss') == 'MISS']

    high_conf_misses = [
        r for r in losses
        if (r.get('confidence_band') or '') == 'HIGH'
    ]
    high_conf_hits = [
        r for r in wins
        if (r.get('confidence_band') or '') == 'HIGH'
    ]

    patterns_success = []
    patterns_fail = []
    if len(high_conf_hits) >= 5:
        patterns_success.append('HIGH confidence setups showing measurable edge')
    if len(high_conf_misses) >= 5:
        patterns_fail.append('HIGH confidence false positives — deflate displayed confidence')

    payload = {
        'updated_at': _now_iso(),
        'successful_patterns': patterns_success[:10],
        'failed_patterns': patterns_fail[:10],
        'high_performing_setups': get_signal_quality_scores().get('signal_types', [])[:5],
        'weak_confidence_false_positives': [
            {'confidence_band': 'HIGH', 'misses': len(high_conf_misses)}
        ] if len(high_conf_misses) >= MIN_SAMPLES_CONF_BUCKET else [],
        'calibration_notes': [
            f"Overall precision { _overall_precision(rows) or 'insufficient data'}% "
            f"(min samples {MIN_SAMPLES_GLOBAL})"
        ],
    }
    atomic_write_json(INTELLIGENCE_MEMORY_FILE, payload)


def get_historical_accuracy_hint(
    *,
    signal_type: str = 'telegram',
    direction: str = 'NEUTRAL',
    regime: str = 'sideways',
    confidence_band: str = 'MEDIUM',
) -> Optional[str]:
    """Return Telegram append text only when statistically meaningful."""
    rows = _query_horizon_stats(
        "AND e.signal_type = ? AND e.regime = ? AND e.confidence_band = ?",
        (signal_type, regime, confidence_band),
    )
    hits = sum(1 for r in rows if r.get('hit_miss') == 'HIT')
    evaluated = sum(1 for r in rows if r.get('hit_miss') in ('HIT', 'MISS'))
    if evaluated < MIN_SAMPLES_TELEGRAM:
        return None
    rate = round(hits / evaluated * 100)
    if rate < 45 or rate > 85:
        return None
    return f"Similar setups historically successful {rate}% (n={evaluated})"


def get_ops_calibration_payload() -> dict:
    try:
        quality = get_signal_quality_scores()
        calibration = get_confidence_calibration()
        regimes = get_regime_performance()
        memory = {}
        if INTELLIGENCE_MEMORY_FILE.exists():
            try:
                with open(INTELLIGENCE_MEMORY_FILE, 'r', encoding='utf-8') as f:
                    memory = json.load(f)
            except Exception:
                memory = {}

        return {
            'status': 'ok',
            'signal_accuracy_pct': quality.get('overall_precision_pct'),
            'confidence_calibration': calibration,
            'regime_performance': regimes,
            'signal_quality': quality,
            'intelligence_memory': memory,
            'telegram_precision_proxy': _telegram_precision(),
            'min_samples_global': MIN_SAMPLES_GLOBAL,
            'min_samples_telegram': MIN_SAMPLES_TELEGRAM,
        }
    except Exception as e:
        return {
            'status': 'degraded',
            'reason': str(e),
            'signal_accuracy_pct': None,
            'confidence_calibration': {'bands': []},
            'regime_performance': {'regimes': []},
            'signal_quality': {'signal_types': []},
        }


def _telegram_precision() -> Optional[float]:
    rows = _query_horizon_stats("AND e.signal_type = 'telegram'")
    hits = sum(1 for r in rows if r.get('hit_miss') == 'HIT')
    evaluated = sum(1 for r in rows if r.get('hit_miss') in ('HIT', 'MISS'))
    if evaluated < MIN_SAMPLES_TELEGRAM:
        return None
    return round(hits / evaluated * 100, 1)


def create_pending_outcome_for_signal(signal_id: int, ticker: str, signal_date: str, entry_price: Optional[float]):
    """Bridge legacy outcomes table for scanner signals."""
    upsert_outcome({
        'source_type': 'signal',
        'source_id': signal_id,
        'ticker': ticker,
        'prediction_date': signal_date,
        'entry_price': entry_price,
        'verdict': 'PENDING',
    })
