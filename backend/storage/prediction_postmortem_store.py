"""Persistent, source-linked postmortems for resolved AstraEdge predictions."""

from __future__ import annotations

import json
from typing import Any

from backend.storage.market_memory_db import get_connection, init_market_memory_db

POSTMORTEM_SCHEMA = """
CREATE TABLE IF NOT EXISTS prediction_postmortems (
    snapshot_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    session_date TEXT NOT NULL,
    snapshot_at TEXT,
    stage TEXT,
    outcome TEXT NOT NULL,
    close_return_pct REAL,
    mfe_pct REAL,
    mae_pct REAL,
    event_type TEXT,
    event_text TEXT,
    verification_status TEXT,
    macro_regime TEXT,
    reason_tags_json TEXT,
    evidence_status TEXT NOT NULL DEFAULT 'PENDING',
    cause_category TEXT,
    cause_summary TEXT,
    explanation_confidence REAL,
    model TEXT,
    provider TEXT,
    context_json TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_postmortem_symbol_date
    ON prediction_postmortems(symbol, session_date DESC);
CREATE INDEX IF NOT EXISTS idx_postmortem_event_date
    ON prediction_postmortems(event_type, session_date DESC);
CREATE INDEX IF NOT EXISTS idx_postmortem_status_date
    ON prediction_postmortems(evidence_status, session_date);

CREATE TABLE IF NOT EXISTS prediction_postmortem_evidence (
    evidence_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL,
    source_name TEXT,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT NOT NULL,
    snippet TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(snapshot_id) REFERENCES prediction_postmortems(snapshot_id)
        ON DELETE CASCADE,
    UNIQUE(snapshot_id, url)
);
CREATE INDEX IF NOT EXISTS idx_postmortem_evidence_snapshot
    ON prediction_postmortem_evidence(snapshot_id);
"""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(',', ':'))


def init_postmortem_store() -> None:
    if not init_market_memory_db():
        raise RuntimeError('canonical market memory database is unavailable')
    conn = get_connection()
    try:
        conn.executescript(POSTMORTEM_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def upsert_postmortem(record: dict[str, Any], evidence: list[dict[str, Any]] | None = None) -> None:
    """Idempotently save a prediction outcome and any source records."""
    snapshot_id = str(record.get('snapshot_id') or '').strip()
    symbol = str(record.get('symbol') or '').strip().upper()
    if not snapshot_id or not symbol:
        raise ValueError('snapshot_id and symbol are required')
    init_postmortem_store()
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO prediction_postmortems (
                snapshot_id, symbol, session_date, snapshot_at, stage, outcome,
                close_return_pct, mfe_pct, mae_pct, event_type, event_text,
                verification_status, macro_regime, reason_tags_json,
                evidence_status, cause_category, cause_summary,
                explanation_confidence, model, provider, context_json,
                attempts, last_error, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(snapshot_id) DO UPDATE SET
                symbol=excluded.symbol,
                session_date=excluded.session_date,
                snapshot_at=excluded.snapshot_at,
                stage=excluded.stage,
                outcome=excluded.outcome,
                close_return_pct=excluded.close_return_pct,
                mfe_pct=excluded.mfe_pct,
                mae_pct=excluded.mae_pct,
                event_type=excluded.event_type,
                event_text=excluded.event_text,
                verification_status=excluded.verification_status,
                macro_regime=excluded.macro_regime,
                reason_tags_json=excluded.reason_tags_json,
                evidence_status=CASE
                    WHEN prediction_postmortems.evidence_status IN ('COMPLETE', 'NO_EVIDENCE')
                    THEN prediction_postmortems.evidence_status
                    ELSE excluded.evidence_status
                END,
                cause_category=COALESCE(excluded.cause_category, prediction_postmortems.cause_category),
                cause_summary=COALESCE(excluded.cause_summary, prediction_postmortems.cause_summary),
                explanation_confidence=COALESCE(excluded.explanation_confidence, prediction_postmortems.explanation_confidence),
                model=COALESCE(excluded.model, prediction_postmortems.model),
                provider=COALESCE(excluded.provider, prediction_postmortems.provider),
                context_json=excluded.context_json,
                attempts=MAX(prediction_postmortems.attempts, excluded.attempts),
                last_error=COALESCE(excluded.last_error, prediction_postmortems.last_error),
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                snapshot_id,
                symbol,
                str(record.get('session_date') or '')[:10],
                record.get('snapshot_at'),
                record.get('stage'),
                str(record.get('outcome') or '').upper(),
                record.get('close_return_pct'),
                record.get('mfe_pct'),
                record.get('mae_pct'),
                record.get('event_type'),
                str(record.get('event_text') or '')[:1000],
                record.get('verification_status'),
                record.get('macro_regime'),
                _json(record.get('reason_tags') or []),
                str(record.get('evidence_status') or 'PENDING').upper(),
                record.get('cause_category'),
                str(record.get('cause_summary') or '')[:1200] or None,
                record.get('explanation_confidence'),
                record.get('model'),
                record.get('provider'),
                _json(record.get('context') or {}),
                int(record.get('attempts') or 0),
                str(record.get('last_error') or '')[:240] or None,
            ),
        )
        for item in evidence or []:
            url = str(item.get('url') or '').strip()
            title = str(item.get('title') or '').strip()
            published_at = str(item.get('published_at') or '').strip()
            if not (url and title and published_at):
                continue
            evidence_id = str(item.get('evidence_id') or '')
            if not evidence_id:
                import hashlib

                evidence_id = hashlib.sha256(
                    f'{snapshot_id}|{url}'.encode('utf-8')
                ).hexdigest()[:32]
            conn.execute(
                """
                INSERT INTO prediction_postmortem_evidence (
                    evidence_id, snapshot_id, source_name, title, url, published_at, snippet
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_id, url) DO UPDATE SET
                    source_name=excluded.source_name,
                    title=excluded.title,
                    published_at=excluded.published_at,
                    snippet=excluded.snippet
                """,
                (
                    evidence_id, snapshot_id, str(item.get('source_name') or '')[:160],
                    title[:500], url[:2000], published_at[:64],
                    str(item.get('snippet') or '')[:1600],
                ),
            )
        conn.commit()
    finally:
        conn.close()


def get_pending_postmortems(
    *, limit: int = 20, session_date: str | None = None, stage: str | None = None,
) -> list[dict[str, Any]]:
    init_postmortem_store()
    conn = get_connection()
    try:
        clauses = ["evidence_status = 'PENDING'", "outcome = 'LOSS'"]
        params: list[Any] = []
        if session_date:
            clauses.append('session_date = ?')
            params.append(str(session_date)[:10])
        if stage:
            clauses.append('stage = ?')
            params.append(str(stage))
        params.append(max(0, int(limit)))
        rows = conn.execute(
            f"""SELECT * FROM prediction_postmortems
                WHERE {' AND '.join(clauses)}
                ORDER BY session_date ASC, created_at ASC LIMIT ?""",
            params,
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            try:
                item['context'] = json.loads(item.pop('context_json') or '{}')
            except (json.JSONDecodeError, TypeError):
                item['context'] = {}
                item.pop('context_json', None)
            try:
                item['reason_tags'] = json.loads(item.pop('reason_tags_json') or '[]')
            except (json.JSONDecodeError, TypeError):
                item['reason_tags'] = []
                item.pop('reason_tags_json', None)
            ev_rows = conn.execute(
                """SELECT source_name, title, url, published_at, snippet
                   FROM prediction_postmortem_evidence
                   WHERE snapshot_id = ? ORDER BY published_at ASC""",
                (item['snapshot_id'],),
            ).fetchall()
            item['evidence'] = [dict(ev) for ev in ev_rows]
            output.append(item)
        return output
    finally:
        conn.close()


def get_postmortems(
    *, symbol: str | None = None, session_date: str | None = None,
    outcome: str | None = None, stage: str | None = None,
    limit: int = 5, offset: int = 0,
) -> list[dict[str, Any]]:
    init_postmortem_store()
    clauses = []
    params: list[Any] = []
    if symbol:
        clauses.append('UPPER(symbol) = ?')
        params.append(str(symbol).strip().upper())
    if session_date:
        clauses.append('session_date = ?')
        params.append(str(session_date)[:10])
    if outcome:
        clauses.append('outcome = ?')
        params.append(str(outcome).strip().upper())
    if stage:
        clauses.append('stage = ?')
        params.append(str(stage).strip())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
    params.append(max(0, int(limit)))
    params.append(max(0, int(offset)))
    conn = get_connection()
    try:
        rows = conn.execute(
            f"""SELECT snapshot_id, symbol, session_date, stage, outcome,
                       close_return_pct, event_type, event_text, verification_status,
                       macro_regime, reason_tags_json, evidence_status, cause_category,
                       cause_summary, explanation_confidence, provider, model
                FROM prediction_postmortems {where}
                ORDER BY session_date DESC, updated_at DESC LIMIT ? OFFSET ?""",
            params,
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            try:
                item['reason_tags'] = json.loads(item.pop('reason_tags_json') or '[]')
            except (json.JSONDecodeError, TypeError):
                item['reason_tags'] = []
            ev = conn.execute(
                """SELECT source_name, title, url, published_at, snippet
                   FROM prediction_postmortem_evidence
                   WHERE snapshot_id = ? ORDER BY published_at ASC""",
                (item['snapshot_id'],),
            ).fetchall()
            item['evidence'] = [dict(source) for source in ev]
            output.append(item)
        return output
    finally:
        conn.close()


def update_postmortem_status(
    snapshot_id: str,
    *,
    status: str,
    attempts: int,
    cause_category: str | None = None,
    cause_summary: str | None = None,
    explanation_confidence: float | None = None,
    model: str | None = None,
    provider: str | None = None,
    error: str | None = None,
) -> None:
    init_postmortem_store()
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE prediction_postmortems SET evidence_status = ?, attempts = ?,
                   cause_category = COALESCE(?, cause_category),
                   cause_summary = COALESCE(?, cause_summary),
                   explanation_confidence = COALESCE(?, explanation_confidence),
                   model = COALESCE(?, model), provider = COALESCE(?, provider),
                   last_error = ?, updated_at = CURRENT_TIMESTAMP
               WHERE snapshot_id = ?""",
            (
                str(status).upper(), int(attempts), cause_category,
                str(cause_summary or '')[:1200] or None, explanation_confidence,
                model, provider, str(error or '')[:240] or None, snapshot_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_event_outcomes(*, event_type: str, limit: int = 2000) -> list[dict[str, Any]]:
    init_postmortem_store()
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT symbol, session_date, outcome, close_return_pct, event_type,
                      event_text, cause_category, cause_summary, reason_tags_json
               FROM prediction_postmortems
               WHERE UPPER(event_type) = UPPER(?)
               ORDER BY session_date DESC LIMIT ?""",
            (str(event_type).strip(), max(0, int(limit))),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item['reason_tags'] = json.loads(item.pop('reason_tags_json') or '[]')
            except (json.JSONDecodeError, TypeError):
                item['reason_tags'] = []
            result.append(item)
        return result
    finally:
        conn.close()
