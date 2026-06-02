"""
Provider usage analytics — SQLite + JSON snapshots for AI runtime observability.

Tracks Gemini / Groq / Claude request metrics without external infrastructure.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.storage.db_manager import get_connection
from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR

ANALYTICS_DIR = DATA_DIR / 'provider_analytics'
TRENDS_FILE = ANALYTICS_DIR / 'trends.json'

_lock = threading.Lock()
_runtime_counters: Dict[str, Any] = {
    'cooldowns': {'gemini': 0, 'groq': 0, 'claude': 0},
    'quota_failures': {'gemini': 0, 'groq': 0, 'claude': 0},
    'degraded_activations': 0,
    'cache_hits': 0,
    'throttle_blocks': 0,
    'fallbacks': {'gemini': 0, 'groq': 0, 'claude': 0},
}

PROVIDER_ANALYTICS_SCHEMA = """
CREATE TABLE IF NOT EXISTS provider_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    request_date DATE NOT NULL,
    request_hour INTEGER NOT NULL,
    provider TEXT NOT NULL,
    use_case TEXT,
    channel TEXT,
    success INTEGER DEFAULT 0,
    latency_ms REAL DEFAULT 0,
    failovers INTEGER DEFAULT 0,
    quota_failure INTEGER DEFAULT 0,
    fallback INTEGER DEFAULT 0,
    cache_hit INTEGER DEFAULT 0,
    degraded INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_pr_date ON provider_requests(request_date);
CREATE INDEX IF NOT EXISTS idx_pr_provider ON provider_requests(provider);
CREATE INDEX IF NOT EXISTS idx_pr_hour ON provider_requests(request_date, request_hour);
"""

_schema_ready = False


def _ensure_schema():
    global _schema_ready
    if _schema_ready:
        return
    ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_connection()
    try:
        conn.executescript(PROVIDER_ANALYTICS_SCHEMA)
        conn.commit()
        _schema_ready = True
    finally:
        conn.close()


def normalize_provider(provider: str, tier: str = '') -> str:
    p = (provider or '').lower().strip()
    if p in ('anthropic', 'claude'):
        return 'claude'
    if p in ('google', 'gemini'):
        return 'gemini'
    if p == 'groq':
        return 'groq'
    if tier == 'strategic':
        return 'claude'
    if tier == 'conversational':
        return 'groq'
    if tier == 'gemini':
        return 'gemini'
    return p or 'unknown'


def record_cooldown(provider: str, slot_id: str = '') -> None:
    prov = normalize_provider(provider)
    with _lock:
        bucket = _runtime_counters['cooldowns']
        bucket[prov] = int(bucket.get(prov, 0)) + 1


def record_throttle_block(reason: str = '') -> None:
    with _lock:
        _runtime_counters['throttle_blocks'] = int(_runtime_counters.get('throttle_blocks', 0)) + 1


def record_provider_request(
    *,
    provider: str,
    use_case: str = '',
    channel: str = 'api',
    success: bool = False,
    latency_ms: float = 0.0,
    failovers: int = 0,
    quota_failure: bool = False,
    fallback: bool = False,
    cache_hit: bool = False,
    degraded: bool = False,
) -> None:
    """Persist one AI request observation."""
    _ensure_schema()
    prov = normalize_provider(provider)
    now = datetime.now()
    req_date = now.strftime('%Y-%m-%d')
    req_hour = now.hour

    with _lock:
        if quota_failure:
            qf = _runtime_counters['quota_failures']
            qf[prov] = int(qf.get(prov, 0)) + 1
        if fallback:
            fb = _runtime_counters['fallbacks']
            fb[prov] = int(fb.get(prov, 0)) + 1
        if cache_hit:
            _runtime_counters['cache_hits'] = int(_runtime_counters.get('cache_hits', 0)) + 1
        if degraded:
            _runtime_counters['degraded_activations'] = int(_runtime_counters.get('degraded_activations', 0)) + 1

    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO provider_requests (
                request_date, request_hour, provider, use_case, channel,
                success, latency_ms, failovers, quota_failure, fallback,
                cache_hit, degraded
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                req_date,
                req_hour,
                prov,
                use_case or '',
                channel or 'api',
                1 if success else 0,
                round(float(latency_ms or 0), 1),
                int(failovers or 0),
                1 if quota_failure else 0,
                1 if fallback else 0,
                1 if cache_hit else 0,
                1 if degraded else 0,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _aggregate_provider(conn, provider: str, req_date: str) -> dict:
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS requests,
            SUM(success) AS successes,
            AVG(latency_ms) AS avg_latency_ms,
            SUM(failovers) AS failovers,
            SUM(quota_failure) AS quota_failures,
            SUM(fallback) AS fallbacks,
            SUM(cache_hit) AS cache_hits,
            SUM(degraded) AS degraded_count
        FROM provider_requests
        WHERE provider = ? AND request_date = ?
        """,
        (provider, req_date),
    ).fetchone()
    requests = int(row['requests'] or 0)
    successes = int(row['successes'] or 0)
    avg_lat = round(float(row['avg_latency_ms'] or 0), 1) if row['avg_latency_ms'] else 0.0
    failovers = int(row['failovers'] or 0)
    quota_failures = int(row['quota_failures'] or 0)
    fallbacks = int(row['fallbacks'] or 0)
    cache_hits = int(row['cache_hits'] or 0)
    degraded_count = int(row['degraded_count'] or 0)
    success_rate = round(100.0 * successes / requests, 1) if requests else 0.0
    uptime_score = round(min(100.0, success_rate * (1.0 - min(0.3, degraded_count / max(1, requests)))), 1)

    hour_rows = conn.execute(
        """
        SELECT request_hour, COUNT(*) AS cnt
        FROM provider_requests
        WHERE provider = ? AND request_date = ?
        GROUP BY request_hour
        ORDER BY request_hour
        """,
        (provider, req_date),
    ).fetchall()
    requests_per_hour = {int(r['request_hour']): int(r['cnt']) for r in hour_rows}

    with _lock:
        cooldowns = int((_runtime_counters.get('cooldowns') or {}).get(provider, 0))

    return {
        'provider': provider,
        'requests_today': requests,
        'requests_per_hour': requests_per_hour,
        'avg_latency_ms': avg_lat,
        'failovers': failovers,
        'cooldown_activations': cooldowns,
        'quota_failures': quota_failures,
        'success_rate_pct': success_rate,
        'degraded_count': degraded_count,
        'fallback_count': fallbacks,
        'cache_hits': cache_hits,
        'uptime_score': uptime_score,
    }


def _conversational_load(conn, req_date: str) -> dict:
    rows = conn.execute(
        """
        SELECT provider, COUNT(*) AS cnt
        FROM provider_requests
        WHERE request_date = ?
          AND use_case IN (
            'ask_basic', 'ask_conversational', 'telegram_ask', 'ops_assistant',
            'lightweight_summary', 'ask_haiku', 'alert_analysis'
          )
          AND cache_hit = 0
        GROUP BY provider
        """,
        (req_date,),
    ).fetchall()
    counts = {r['provider']: int(r['cnt']) for r in rows}
    total = sum(counts.values()) or 0
    denom = total or 1
    return {
        'counts': counts,
        'pct': {k: round(100.0 * v / denom, 1) for k, v in counts.items()},
        'total': total,
    }


def _claude_strategic_count(conn, req_date: str) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS cnt FROM provider_requests
        WHERE provider = 'claude' AND request_date = ?
          AND use_case IN (
            'final_synthesis', 'manual_refresh', 'overnight_brief', 'premarket_brief',
            'postmortem', 'ask_deep', 'sonnet'
          )
        """,
        (req_date,),
    ).fetchone()
    return int(row['cnt'] or 0)


def get_runtime_ops_summary() -> dict:
    """Live OPS panel payload."""
    _ensure_schema()
    today = datetime.now().strftime('%Y-%m-%d')
    conn = get_connection()
    try:
        providers = {}
        for name in ('gemini', 'groq', 'claude'):
            providers[name] = _aggregate_provider(conn, name, today)

        conv = _conversational_load(conn, today)
        claude_strategic = _claude_strategic_count(conn, today)

        try:
            from backend.ai.provider_manager import get_provider_ops_summary
            pool = get_provider_ops_summary()
        except Exception:
            pool = {}

        degraded_mode = (pool.get('degraded') or {}).get('mode', 'normal')
        active = {
            'gemini': (pool.get('providers') or {}).get('gemini', {}).get('active_slot'),
            'groq': (pool.get('providers') or {}).get('groq', {}).get('active_slot'),
            'claude': (pool.get('providers') or {}).get('claude', {}).get('active_slot') or 'standby',
        }

        with _lock:
            throttle_blocks = int(_runtime_counters.get('throttle_blocks', 0))
            cache_hits = int(_runtime_counters.get('cache_hits', 0))

        total_requests = sum(p['requests_today'] for p in providers.values())
        total_success = sum(
            int(conn.execute(
                "SELECT SUM(success) FROM provider_requests WHERE provider = ? AND request_date = ?",
                (n, today),
            ).fetchone()[0] or 0)
            for n in ('gemini', 'groq', 'claude')
        )
        ai_uptime_pct = round(100.0 * total_success / max(1, total_requests), 1)

        return {
            'status': 'ok',
            'date': today,
            'updated_at': datetime.now().isoformat(),
            'degraded_mode': degraded_mode,
            'active_providers': active,
            'providers': providers,
            'conversational_load': conv,
            'claude_strategic_runs': claude_strategic,
            'throttle_blocks_today': throttle_blocks,
            'cache_hits_today': cache_hits,
            'ai_uptime_pct': ai_uptime_pct,
            'summary_lines': _format_ops_lines(providers, claude_strategic),
        }
    finally:
        conn.close()


def _format_ops_lines(providers: dict, claude_strategic: int) -> List[str]:
    lines = []
    for name, label in (('gemini', 'Gemini'), ('groq', 'Groq'), ('claude', 'Claude')):
        p = providers.get(name) or {}
        req = p.get('requests_today', 0)
        if name == 'claude':
            lat_s = round((p.get('avg_latency_ms') or 0) / 1000.0, 1)
            lines.append(
                f"{label}: {claude_strategic} strategic runs · avg {lat_s}s"
                if req or claude_strategic
                else f"{label}: standby"
            )
            continue
        lat_s = round((p.get('avg_latency_ms') or 0) / 1000.0, 1)
        lines.append(
            f"{label}: {req} requests · {p.get('failovers', 0)} failovers · avg {lat_s}s"
        )
    return lines


def get_ai_runtime_stats_payload() -> dict:
    """Stats tab AI Runtime section."""
    ops = get_runtime_ops_summary()
    trends = _load_trends(limit=14)
    providers = ops.get('providers') or {}

    quota_pressure = {}
    for name, p in providers.items():
        qf = int(p.get('quota_failures') or 0)
        req = int(p.get('requests_today') or 0)
        quota_pressure[name] = round(100.0 * qf / max(1, req), 1)

    conv = ops.get('conversational_load') or {}
    return {
        'status': 'ok',
        'date': ops.get('date'),
        'ai_uptime_pct': ops.get('ai_uptime_pct'),
        'provider_reliability': {
            name: {
                'uptime_score': p.get('uptime_score'),
                'success_rate_pct': p.get('success_rate_pct'),
                'failovers': p.get('failovers'),
            }
            for name, p in providers.items()
        },
        'provider_efficiency': {
            name: {
                'requests_today': p.get('requests_today'),
                'avg_latency_ms': p.get('avg_latency_ms'),
                'cache_hits': p.get('cache_hits'),
            }
            for name, p in providers.items()
        },
        'quota_stability': {
            'pressure_pct': quota_pressure,
            'cooldowns': {n: p.get('cooldown_activations') for n, p in providers.items()},
        },
        'fallback_trends': trends.get('fallback_daily') or [],
        'conversational_load_trends': trends.get('conversational_pct_daily') or [],
        'conversational_load_pct': conv.get('pct') or {},
        'degraded_mode': ops.get('degraded_mode'),
        'cache_hits_today': ops.get('cache_hits_today'),
        'throttle_blocks_today': ops.get('throttle_blocks_today'),
        'providers': providers,
        'claude_strategic_runs': ops.get('claude_strategic_runs'),
    }


def build_daily_runtime_notes(review_date: Optional[str] = None) -> List[str]:
    """Narrative bullets for Hist journal cards."""
    _ensure_schema()
    day = review_date or datetime.now().strftime('%Y-%m-%d')
    snap_path = ANALYTICS_DIR / f'daily_{day}.json'
    if snap_path.exists():
        try:
            with open(snap_path, 'r', encoding='utf-8') as f:
                snap = json.load(f)
            return list(snap.get('runtime_notes') or [])
        except Exception:
            pass

    conn = get_connection()
    try:
        notes = []
        providers = {n: _aggregate_provider(conn, n, day) for n in ('gemini', 'groq', 'claude')}
        conv = _conversational_load(conn, day)
        claude_n = _claude_strategic_count(conn, day)
        degraded = sum(p.get('degraded_count', 0) for p in providers.values())

        gem = providers['gemini']
        groq = providers['groq']
        if gem['quota_failures'] > 0:
            notes.append(f"Gemini quota pressure: {gem['quota_failures']} quota events on {day}.")
        elif gem['failovers'] > 0:
            notes.append(f"Gemini had {gem['failovers']} failover(s); pool remained operational.")

        conv_pct = conv.get('pct') or {}
        if conv_pct.get('groq'):
            notes.append(f"Groq handled {conv_pct['groq']:.0f}% of conversational requests.")
        elif groq['requests_today']:
            notes.append(f"Groq served {groq['requests_today']} conversational requests.")

        if degraded == 0:
            notes.append("No degraded-mode activations recorded.")
        else:
            notes.append(f"Degraded mode triggered {degraded} time(s).")

        if claude_n:
            notes.append(f"Claude used for {claude_n} strategic synthesis run(s) only.")
        else:
            notes.append("Claude reserved — no strategic synthesis runs.")

        throttle = 0
        with _lock:
            if day == datetime.now().strftime('%Y-%m-%d'):
                throttle = int(_runtime_counters.get('throttle_blocks', 0))
        if throttle:
            notes.append(f"Telegram throttling blocked {throttle} abusive/repeated ask(s).")

        return notes[:8]
    finally:
        conn.close()


def get_daily_runtime_notes(review_date: str) -> List[str]:
    return build_daily_runtime_notes(review_date)


def _load_trends(limit: int = 14) -> dict:
    if not TRENDS_FILE.exists():
        return {'fallback_daily': [], 'conversational_pct_daily': []}
    try:
        with open(TRENDS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {'fallback_daily': [], 'conversational_pct_daily': []}
        for key in ('fallback_daily', 'conversational_pct_daily'):
            data[key] = (data.get(key) or [])[-limit:]
        return data
    except Exception:
        return {'fallback_daily': [], 'conversational_pct_daily': []}


def snapshot_daily(review_date: Optional[str] = None) -> dict:
    """Persist daily JSON snapshot + update trend index."""
    _ensure_schema()
    day = review_date or datetime.now().strftime('%Y-%m-%d')
    ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    try:
        providers = {n: _aggregate_provider(conn, n, day) for n in ('gemini', 'groq', 'claude')}
        conv = _conversational_load(conn, day)
        claude_n = _claude_strategic_count(conn, day)
        notes = build_daily_runtime_notes(day)

        total_req = sum(p['requests_today'] for p in providers.values())
        total_ok = sum(
            int(conn.execute(
                "SELECT SUM(success) FROM provider_requests WHERE request_date = ? AND provider = ?",
                (day, n),
            ).fetchone()[0] or 0)
            for n in ('gemini', 'groq', 'claude')
        )

        payload = {
            'date': day,
            'generated_at': datetime.now().isoformat(),
            'providers': providers,
            'conversational_load': conv,
            'claude_strategic_runs': claude_n,
            'runtime_notes': notes,
            'ai_uptime_pct': round(100.0 * total_ok / max(1, total_req), 1),
            'total_requests': total_req,
        }

        atomic_write_json(ANALYTICS_DIR / f'daily_{day}.json', payload)
        _update_trends(payload)
        _prune_old_rows(days=45)
        return payload
    finally:
        conn.close()


def _update_trends(snapshot: dict) -> None:
    trends = _load_trends(limit=30)
    day = snapshot['date']
    fb_entry = {'date': day, 'total': sum(p.get('fallback_count', 0) for p in snapshot['providers'].values())}
    conv_entry = {'date': day, 'pct': (snapshot.get('conversational_load') or {}).get('pct') or {}}

    def _upsert(series, entry):
        out = [e for e in series if e.get('date') != day]
        out.append(entry)
        return sorted(out, key=lambda x: x.get('date', ''))[-30:]

    trends['fallback_daily'] = _upsert(trends.get('fallback_daily') or [], fb_entry)
    trends['conversational_pct_daily'] = _upsert(trends.get('conversational_pct_daily') or [], conv_entry)
    atomic_write_json(TRENDS_FILE, trends)


def _prune_old_rows(days: int = 45) -> None:
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    conn = get_connection()
    try:
        conn.execute("DELETE FROM provider_requests WHERE request_date < ?", (cutoff,))
        conn.commit()
    finally:
        conn.close()
