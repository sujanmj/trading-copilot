"""
AstraEdge 52Q — deterministic daily learning truth reconciliation.

Separates observed/qualifying candidates from tracked quality tradecards,
canonical outcomes, genuine winners, and eligible learning-sample mutations.
Read-only: does not resolve outcomes, append samples, or call AI/brokers.
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path

IST = ZoneInfo('Asia/Kolkata')

OUTCOME_WIN = 'WIN'
OUTCOME_LOSS = 'LOSS'
OUTCOME_NEUTRAL = 'NEUTRAL'
OUTCOME_PENDING = 'PENDING_DATA'

MIN_QUALITY_SCORE = 60
PRIMARY_STAGES = frozenset({
    'opening_0920',
    'opening_0925',
    'final_0931',
    'manual_tradecards',
})
# Derived from genuine historical fixture (52O) and the learning-record writer STAGE
# in backend/trading/candidate_outcome_learning.py (4B.18K-A). Do not invent versions.
ACCEPTED_LEGACY_STAGE_VERSIONS = frozenset({
    '52O',
    '4B.18K-A',
})
# Positive allowlist from opening_rally_radar / decision-trace quality fixtures and
# the canonical snapshot state used by 52Q tests (TRADECARD_CANDIDATE).
# build_candidate_snapshot copies row.state; quality tradecards use this state.
ELIGIBLE_QUALITY_STATES = frozenset({
    'TRADECARD_CANDIDATE',
})
INELIGIBLE_OUTCOME_STATES = frozenset({
    'RADAR_ARMED',
    'PULLBACK_ONLY_PLAN',
    'CHASE_RISK',
    'MOMENTUM_ONLY_WATCH',
    'WATCH_ONLY',
    'LOW_CONFIDENCE',
    'REJECTED_LOW_SCORE',
    'BLOCKED_STALE_DATA',
    'REJECTED',
    'PREVIOUS_SESSION_CONTEXT',
    'NO_TRADE',
    'WAIT_LIVE_CONFIRM',
    'WAIT_FOR_PULLBACK',
    'PULLBACK_ONLY',
})
WATCH_ONLY_STATES = frozenset({
    'WATCH_ONLY', 'PULLBACK_ONLY_PLAN', 'PULLBACK_ONLY',
    'MOMENTUM_ONLY_WATCH', 'WAIT_FOR_PULLBACK', 'WAIT_LIVE_CONFIRM',
    'LOW_CONFIDENCE',
})
CANDIDATE_ONLY_STATES = frozenset({
    'RADAR_ARMED', 'CHASE_RISK', 'PREVIOUS_SESSION_CONTEXT',
})


def _now_ist() -> datetime:
    return datetime.now(tz=IST)


def _session_date(now: datetime | None = None) -> str:
    return (now or _now_ist()).astimezone(IST).date().isoformat()


def _normalize_symbol(value: object) -> str:
    return str(value or '').strip().upper()


def _normalize_outcome(value: object) -> str:
    return str(value or '').strip().upper()


def _normalize_text(value: object) -> str:
    return str(value or '').strip()


def _date_prefix(value: object) -> str:
    text = _normalize_text(value)
    if not text:
        return ''
    prefix = text[:10]
    if len(prefix) != 10 or prefix[4] != '-' or prefix[7] != '-':
        return ''
    year, month, day = prefix[0:4], prefix[5:7], prefix[8:10]
    if not (year.isdigit() and month.isdigit() and day.isdigit()):
        return ''
    return prefix


def _safe_int(value: object, default: int | None = None) -> int | None:
    if value is None or isinstance(value, (list, dict, set, tuple)):
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return default
        return int(value)
    text = str(value).strip()
    if not text or text.lower() in ('nan', 'inf', '-inf', '+inf', 'infinity', '-infinity'):
        return default
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return default


def _safe_float(value: object, default: float | None = None) -> float | None:
    if value is None or isinstance(value, (list, dict, set, tuple)):
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        num = float(value)
        if math.isnan(num) or math.isinf(num):
            return default
        return num
    text = str(value).strip()
    if not text or text.lower() in ('nan', 'inf', '-inf', '+inf', 'infinity', '-infinity'):
        return default
    try:
        num = float(text)
    except (TypeError, ValueError):
        return default
    if math.isnan(num) or math.isinf(num):
        return default
    return num


def _strict_nonnegative_int(value: object) -> int | None:
    """Parse a nonnegative integer without truncating fractional values."""
    if value is None or isinstance(value, (list, dict, set, tuple, bool)):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        if value < 0 or value != math.floor(value):
            return None
        return int(value)
    text = str(value).strip()
    if not text or text.lower() in ('nan', 'inf', '-inf', '+inf', 'infinity', '-infinity'):
        return None
    try:
        num = float(text)
    except (TypeError, ValueError):
        return None
    if math.isnan(num) or math.isinf(num):
        return None
    if num < 0 or num != math.floor(num):
        return None
    return int(num)


def _is_eligible_quality_state(value: object) -> bool:
    state = _normalize_text(value).upper()
    if not state:
        return False
    return state in {s.upper() for s in ELIGIBLE_QUALITY_STATES}


def _truthy_flag(value: object) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    if isinstance(value, (list, dict, set, tuple)):
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return False
        return value != 0
    text = str(value).strip().lower()
    return text in ('1', 'true', 'yes', 'y', 'on')


def _load_jsonl(path: Path, *, limit: int | None = None) -> tuple[list[dict[str, Any]], str]:
    """Load JSONL. Returns (rows, status) where status is ok|missing|unreadable|malformed."""
    if not path.is_file():
        return [], 'missing'
    rows: list[dict[str, Any]] = []
    malformed = False
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                malformed = True
                continue
            if isinstance(row, dict):
                rows.append(row)
            else:
                malformed = True
    except OSError:
        return [], 'unreadable'
    status = 'malformed' if malformed else 'ok'
    if limit is not None and limit > 0:
        return rows[-limit:], status
    return rows, status


def _mutations_path() -> Path:
    return get_data_path('candidate_learning_mutations.jsonl')


def _snapshots_path() -> Path:
    return get_data_path('candidate_snapshots.jsonl')


def _outcomes_path() -> Path:
    return get_data_path('candidate_outcomes.jsonl')


def _learning_path() -> Path:
    return get_data_path('candidate_learning_records.jsonl')


def learning_record_dedupe_key(record: dict[str, Any]) -> str:
    """Stable dedupe identity across legacy and modern schemas (no stage_version)."""
    if not isinstance(record, dict):
        return ''
    snapshot_id = _normalize_text(record.get('snapshot_id'))
    outcome = _normalize_outcome(record.get('outcome'))
    if snapshot_id:
        return f'{snapshot_id}|{outcome}'
    return '|'.join([
        _normalize_symbol(record.get('symbol')),
        _date_prefix(record.get('session_date')),
        outcome,
        _normalize_text(record.get('aggregate_key')),
    ])


def is_eligible_historical_learning_sample(record: dict[str, Any]) -> tuple[bool, str]:
    """Conservative eligibility for cumulative historical sample count."""
    if not isinstance(record, dict) or not record:
        return False, 'malformed_payload'
    sym = _normalize_symbol(record.get('symbol'))
    if not sym:
        return False, 'malformed_payload'
    day = _date_prefix(record.get('session_date'))
    if not day:
        return False, 'malformed_payload'
    if _truthy_flag(record.get('reference_only')) or _truthy_flag(record.get('reference_outcome')):
        return False, 'reference_only'
    if (
        _truthy_flag(record.get('captured_only'))
        or _truthy_flag(record.get('candidate_only'))
    ):
        return False, 'candidate_only'
    if (
        _truthy_flag(record.get('test_only'))
        or _truthy_flag(record.get('fake'))
        or _truthy_flag(record.get('is_test'))
    ):
        return False, 'malformed_payload'
    outcome = _normalize_outcome(record.get('outcome'))
    if outcome in ('', OUTCOME_PENDING, 'PENDING', 'UNRESOLVED'):
        return False, 'outcome_unresolved'
    if outcome not in (OUTCOME_WIN, OUTCOME_LOSS, OUTCOME_NEUTRAL):
        return False, 'malformed_payload'
    snapshot_id = _normalize_text(record.get('snapshot_id'))
    aggregate_key = _normalize_text(record.get('aggregate_key'))
    if not snapshot_id and not aggregate_key:
        return False, 'malformed_payload'

    has_stage = record.get('stage') not in (None, '')
    has_score = 'score' in record and record.get('score') is not None
    has_state = record.get('state') not in (None, '')
    is_modern = has_stage or has_score or has_state

    if is_modern:
        if not (has_stage and has_score and has_state):
            return False, 'malformed_payload'
        score = _safe_int(record.get('score'))
        if score is None:
            return False, 'malformed_payload'
        if score < MIN_QUALITY_SCORE:
            return False, 'no_quality_tradecard'
        stage = _normalize_text(record.get('stage'))
        if stage not in PRIMARY_STAGES:
            return False, 'candidate_only'
        if not _is_eligible_quality_state(record.get('state')):
            state = _normalize_text(record.get('state')).upper()
            if state in WATCH_ONLY_STATES:
                return False, 'watch_only'
            if state in INELIGIBLE_OUTCOME_STATES:
                return False, 'candidate_only'
            return False, 'malformed_payload'
        return True, 'ok'

    # Legacy path: aggregate key alone is insufficient — require accepted stage_version.
    if not aggregate_key:
        return False, 'malformed_payload'
    stage_version = _normalize_text(record.get('stage_version'))
    if not stage_version:
        return False, 'malformed_payload'
    accepted = {v.upper() for v in ACCEPTED_LEGACY_STAGE_VERSIONS}
    if stage_version.upper() not in accepted:
        return False, 'malformed_payload'
    return True, 'ok'


def is_canonical_winner_reason_eligible(
    outcome: dict[str, Any] | None,
    *,
    snapshot: dict[str, Any] | None = None,
    session_date: str | None = None,
) -> tuple[bool, str]:
    """Genuine winners require a matching persisted quality snapshot + canonical WIN."""
    if not isinstance(outcome, dict) or not outcome:
        return False, 'malformed_payload'
    day = _date_prefix(session_date) or _session_date()
    if not isinstance(snapshot, dict) or not snapshot:
        return False, 'no_quality_tradecard'

    outcome_sid = _normalize_text(outcome.get('snapshot_id'))
    snap_sid = _normalize_text(snapshot.get('snapshot_id'))
    if not outcome_sid or not snap_sid:
        return False, 'no_quality_tradecard'
    if outcome_sid != snap_sid:
        return False, 'snapshot_id_mismatch'

    outcome_sym = _normalize_symbol(outcome.get('symbol') or outcome.get('ticker'))
    snap_sym = _normalize_symbol(snapshot.get('symbol') or snapshot.get('ticker'))
    if not outcome_sym or not snap_sym:
        return False, 'malformed_payload'
    if outcome_sym != snap_sym:
        return False, 'ticker_mismatch'

    outcome_day = _date_prefix(outcome.get('session_date'))
    snap_day = _date_prefix(snapshot.get('session_date'))
    if not outcome_day or outcome_day != day:
        return False, 'session_mismatch'
    if not snap_day or snap_day != day:
        return False, 'session_mismatch'

    if outcome.get('reference_only') or outcome.get('reference_outcome'):
        return False, 'reference_only'
    if snapshot.get('reference_only') or snapshot.get('reference_outcome'):
        return False, 'reference_only'

    outcome_state = _normalize_outcome(outcome.get('outcome'))
    if not outcome_state:
        return False, 'no_canonical_outcome'
    if outcome_state in (OUTCOME_PENDING, 'PENDING', 'UNRESOLVED'):
        return False, 'outcome_unresolved'
    if outcome_state != OUTCOME_WIN:
        return False, 'outcome_not_won'

    # Quality proof comes ONLY from the persisted snapshot — never outcome copies.
    if _truthy_flag(snapshot.get('captured_only')) or _truthy_flag(snapshot.get('candidate_only')):
        return False, 'candidate_only'
    if _truthy_flag(outcome.get('captured_only')) or _truthy_flag(outcome.get('candidate_only')):
        return False, 'candidate_only'
    if not _is_eligible_quality_state(snapshot.get('state')):
        snap_state = _normalize_text(snapshot.get('state')).upper()
        if snap_state in WATCH_ONLY_STATES:
            return False, 'watch_only'
        if snap_state in CANDIDATE_ONLY_STATES or snap_state in INELIGIBLE_OUTCOME_STATES:
            return False, 'candidate_only' if snap_state in CANDIDATE_ONLY_STATES else 'watch_only'
        return False, 'no_quality_tradecard'

    score = _safe_int(snapshot.get('score'))
    if score is None or score < MIN_QUALITY_SCORE:
        return False, 'no_quality_tradecard'
    stage = _normalize_text(snapshot.get('stage'))
    if stage not in PRIMARY_STAGES:
        return False, 'no_quality_tradecard'
    return True, 'ok'


def record_learning_sample_mutation(
    *,
    action: str,
    sample_id: str,
    symbol: str,
    session_date: str,
    dedupe_key: str,
    recorded_at: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Append canonical mutation provenance for daily-added truth (write path only)."""
    event = {
        'event': 'learning_sample_mutation',
        'action': str(action or 'inserted').lower(),
        'sample_id': str(sample_id or ''),
        'symbol': _normalize_symbol(symbol),
        'session_date': _date_prefix(session_date),
        'dedupe_key': str(dedupe_key or ''),
        'recorded_at': recorded_at or _now_ist().replace(microsecond=0).isoformat(),
    }
    target = path or _mutations_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + '\n')
    return event


def record_learning_resolve_provenance(
    *,
    session_date: str,
    inserted: int,
    deduplicated: int,
    sample_ids: list[str] | None = None,
    resolve_id: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Mark that a resolve/mutation pass completed for the session (proves zero)."""
    inserted_n = _strict_nonnegative_int(inserted)
    deduped_n = _strict_nonnegative_int(deduplicated)
    if inserted_n is None or deduped_n is None:
        raise ValueError('resolve provenance inserted/deduplicated must be strict nonnegative integers')
    if sample_ids is not None and not isinstance(sample_ids, list):
        raise ValueError('resolve provenance sample_ids must be a list')
    rid = _normalize_text(resolve_id) or uuid.uuid4().hex
    unique_ids: list[str] = []
    seen_ids: set[str] = set()
    for raw in list(sample_ids or []):
        sid = _normalize_text(raw)
        if not sid or sid in seen_ids:
            continue
        seen_ids.add(sid)
        unique_ids.append(sid)
    if len(unique_ids) != inserted_n:
        raise ValueError('resolve provenance inserted must equal unique sample_ids count')
    event = {
        'event': 'resolve_complete',
        'resolve_id': rid,
        'session_date': _date_prefix(session_date),
        'inserted': inserted_n,
        'deduplicated': deduped_n,
        'sample_ids': unique_ids,
        'recorded_at': _now_ist().replace(microsecond=0).isoformat(),
        'provenance_complete': True,
    }
    target = path or _mutations_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + '\n')
    return event


def _qualification_status_label(row: dict[str, Any], *, winner: bool) -> str:
    if winner:
        return 'canonical won outcome'
    state = _normalize_text(row.get('state')).upper()
    outcome = _normalize_outcome(row.get('outcome'))
    score = _safe_int(row.get('score'), 0) or 0
    if state in INELIGIBLE_OUTCOME_STATES:
        if state in ('PULLBACK_ONLY_PLAN', 'PULLBACK_ONLY', 'WAIT_FOR_PULLBACK'):
            return 'pullback-only watch; outcome learning ineligible'
        if state in ('WATCH_ONLY', 'MOMENTUM_ONLY_WATCH', 'RADAR_ARMED'):
            return 'candidate captured; no quality tradecard/outcome'
        return f'{state.lower().replace("_", "-")}; not a canonical winner'
    if outcome in (OUTCOME_PENDING, 'PENDING', ''):
        if score >= MIN_QUALITY_SCORE and _normalize_text(row.get('stage')) in PRIMARY_STAGES:
            return 'qualifying candidate; unresolved'
        return 'candidate captured; no quality tradecard/outcome'
    if outcome == OUTCOME_LOSS:
        return 'canonical loss; not a winner reason'
    if outcome == OUTCOME_NEUTRAL:
        return 'canonical neutral; not a winner reason'
    if score < MIN_QUALITY_SCORE or not row.get('snapshot_id'):
        return 'scanner/catalyst qualification; no tracked quality tradecard or canonical outcome'
    return 'qualifying candidate; unresolved'


def _reason_text_for_row(row: dict[str, Any]) -> str:
    tags = row.get('reason_tags') or []
    if isinstance(tags, list) and tags:
        return ', '.join(str(t) for t in tags[:4])
    for key in ('reason_summary', 'ai_reason_summary', 'reason_text', 'why'):
        val = row.get(key)
        if isinstance(val, list) and val:
            return ' + '.join(str(x) for x in val[:3])
        text = str(val or '').strip()
        if text and text != '—':
            return text[:160]
    bits = []
    if row.get('has_catalyst'):
        bits.append('catalyst match')
    vol = _safe_float(row.get('volume_participation'))
    if vol is not None and vol >= 2:
        bits.append('volume ignition')
    score = _safe_int(row.get('score'))
    if score is not None and score >= MIN_QUALITY_SCORE:
        bits.append(f'score {score}')
    return ' + '.join(bits) if bits else 'qualification evidence'


def _outcome_canonical_identity(row: dict[str, Any]) -> str:
    """Canonical outcome identity, or empty when the row is not canonical."""
    oid = _normalize_text(row.get('outcome_id'))
    if oid:
        return f'oid:{oid}'
    sid = _normalize_text(row.get('snapshot_id'))
    if not sid:
        return ''
    outcome = _normalize_outcome(row.get('outcome'))
    day = _date_prefix(row.get('session_date'))
    if not outcome or not day:
        return ''
    return f'snap:{sid}|{outcome}|{day}'


def _outcome_dedupe_key(row: dict[str, Any]) -> str:
    """Canonical dedupe key, or empty when the outcome lacks canonical identity."""
    return _outcome_canonical_identity(row)


def _noncanonical_outcome_fingerprint(row: dict[str, Any]) -> str:
    """Deterministic fingerprint for noncanonical qualification display/dedupe."""
    status_sig = _normalize_text(
        row.get('status')
        or row.get('pending_reason')
        or row.get('reason_summary')
        or row.get('reason_text')
        or ''
    )[:80]
    return '|'.join([
        _normalize_symbol(row.get('symbol') or row.get('ticker')),
        _date_prefix(row.get('session_date')),
        _normalize_outcome(row.get('outcome')),
        status_sig,
    ])


def _winner_identity(outcome: dict[str, Any], snapshot: dict[str, Any] | None) -> str:
    sid = _normalize_text(outcome.get('snapshot_id') or (snapshot or {}).get('snapshot_id'))
    if sid:
        return f'snap:{sid}'
    oid = _normalize_text(outcome.get('outcome_id'))
    if oid:
        return f'oid:{oid}'
    return ''


def _normalize_sample_id_list(raw: object) -> list[str] | None:
    """Return unique normalized sample IDs, or None when the payload is malformed."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        return None
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, (list, dict, set, tuple)):
            return None
        sid = _normalize_text(item)
        if not sid:
            continue
        if sid in seen:
            continue
        seen.add(sid)
        out.append(sid)
    return out


def _marker_fingerprint(marker: dict[str, Any]) -> tuple[Any, ...]:
    ids = _normalize_sample_id_list(marker.get('sample_ids')) or []
    return (
        _strict_nonnegative_int(marker.get('inserted')),
        _strict_nonnegative_int(marker.get('deduplicated')),
        tuple(ids),
        _date_prefix(marker.get('session_date')),
        bool(marker.get('provenance_complete') is True),
    )


def _classify_resolve_markers(
    day_mutations: list[dict[str, Any]],
    day: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Return (valid_markers, invalid_same_session_marker_present)."""
    valid: list[dict[str, Any]] = []
    invalid_present = False
    for m in day_mutations:
        if not isinstance(m, dict):
            continue
        if m.get('event') != 'resolve_complete':
            continue
        if _date_prefix(m.get('session_date')) != day:
            continue
        if m.get('provenance_complete') is not True:
            invalid_present = True
            continue
        inserted = _strict_nonnegative_int(m.get('inserted'))
        deduped = _strict_nonnegative_int(m.get('deduplicated'))
        if inserted is None or deduped is None:
            invalid_present = True
            continue
        sample_ids = _normalize_sample_id_list(m.get('sample_ids'))
        if sample_ids is None:
            invalid_present = True
            continue
        resolve_id = _normalize_text(m.get('resolve_id'))
        if not resolve_id:
            # Legacy fixtures: only proven-zero markers without resolve_id are accepted.
            if inserted > 0:
                invalid_present = True
                continue
            if sample_ids and len(sample_ids) != inserted:
                invalid_present = True
                continue
        else:
            if len(sample_ids) != inserted:
                invalid_present = True
                continue
        valid.append({
            **m,
            'inserted': inserted,
            'deduplicated': deduped,
            'sample_ids': sample_ids,
            'resolve_id': resolve_id,
        })
    return valid, invalid_present


def _valid_resolve_markers(day_mutations: list[dict[str, Any]], day: str) -> list[dict[str, Any]]:
    valid, _invalid = _classify_resolve_markers(day_mutations, day)
    return valid


def _matched_daily_insertions(
    day_mutations: list[dict[str, Any]],
    *,
    day: str,
    eligible_by_key: dict[str, dict[str, Any]],
    eligible_by_sample_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[str], bool]:
    """Match insert events to eligible records. Returns (events, sample_ids, inconsistent)."""
    matched: list[dict[str, Any]] = []
    matched_sample_ids: set[str] = set()
    seen_identities: set[str] = set()
    inconsistent = False

    for ev in day_mutations:
        if not isinstance(ev, dict):
            continue
        if ev.get('event') != 'learning_sample_mutation':
            continue
        if str(ev.get('action') or '').lower() != 'inserted':
            continue
        if _date_prefix(ev.get('session_date')) != day:
            continue

        # Every current-session inserted event must fully reconcile — never ignore orphans.
        dedupe_key = _normalize_text(ev.get('dedupe_key'))
        sample_id = _normalize_text(ev.get('sample_id'))
        ev_sym = _normalize_symbol(ev.get('symbol'))
        if not dedupe_key or not sample_id or not ev_sym:
            inconsistent = True
            continue

        key_rec = eligible_by_key.get(dedupe_key)
        sid_rec = eligible_by_sample_id.get(sample_id)
        if key_rec is None or sid_rec is None:
            inconsistent = True
            continue
        if learning_record_dedupe_key(key_rec) != learning_record_dedupe_key(sid_rec):
            inconsistent = True
            continue

        record = key_rec
        record_key = learning_record_dedupe_key(record)
        if not record_key:
            inconsistent = True
            continue
        if record_key != dedupe_key:
            inconsistent = True
            continue
        rec_sid = _normalize_text(record.get('sample_id'))
        if rec_sid != sample_id:
            inconsistent = True
            continue
        if _date_prefix(record.get('session_date')) != day:
            inconsistent = True
            continue
        ok, _reason = is_eligible_historical_learning_sample(record)
        if not ok:
            inconsistent = True
            continue
        rec_sym = _normalize_symbol(record.get('symbol'))
        if ev_sym != rec_sym:
            inconsistent = True
            continue

        if record_key in seen_identities:
            continue
        seen_identities.add(record_key)
        matched.append(ev)
        matched_sample_ids.add(sample_id)

    return matched, matched_sample_ids, inconsistent


def _derive_daily_added_from_markers(
    markers: list[dict[str, Any]],
    *,
    matched_count: int,
    matched_sample_ids: set[str],
) -> tuple[int | None, bool, str]:
    """
    Derive daily-added count from resolve markers.

    Returns (count_or_none, available, reason_code_or_empty).
    """
    if not markers:
        return None, False, ''

    modern = [m for m in markers if _normalize_text(m.get('resolve_id'))]
    legacy = [m for m in markers if not _normalize_text(m.get('resolve_id'))]

    if modern and legacy:
        return None, False, 'daily_provenance_inconsistent'

    if modern:
        by_resolve: dict[str, list[dict[str, Any]]] = {}
        for m in modern:
            rid = _normalize_text(m.get('resolve_id'))
            by_resolve.setdefault(rid, []).append(m)

        ownership: dict[str, str] = {}
        per_pass_counts: list[int] = []
        union_ids: set[str] = set()
        for rid, group in by_resolve.items():
            fps = {_marker_fingerprint(m) for m in group}
            if len(fps) > 1:
                return None, False, 'daily_provenance_inconsistent'
            marker = group[0]
            sample_ids = _normalize_sample_id_list(marker.get('sample_ids'))
            if sample_ids is None:
                return None, False, 'daily_provenance_inconsistent'
            inserted = _strict_nonnegative_int(marker.get('inserted'))
            if inserted is None:
                return None, False, 'daily_provenance_inconsistent'
            if len(sample_ids) != inserted:
                return None, False, 'daily_provenance_inconsistent'
            for sid in sample_ids:
                owner = ownership.get(sid)
                if owner is not None and owner != rid:
                    return None, False, 'daily_provenance_inconsistent'
                ownership[sid] = rid
            per_pass_counts.append(len(sample_ids))
            union_ids.update(sample_ids)

        if sum(per_pass_counts) != len(union_ids):
            return None, False, 'daily_provenance_inconsistent'
        marker_total = len(union_ids)
        if marker_total != matched_count:
            return None, False, 'daily_provenance_inconsistent'
        if union_ids and matched_sample_ids and union_ids != matched_sample_ids:
            return None, False, 'daily_provenance_inconsistent'
        return marker_total, True, ''

    # Legacy markers without resolve_id — accept only one semantic marker or exact duplicates.
    fps = {_marker_fingerprint(m) for m in legacy}
    if len(fps) > 1:
        return None, False, 'daily_provenance_inconsistent'
    marker = legacy[0]
    sample_ids = _normalize_sample_id_list(marker.get('sample_ids'))
    if sample_ids is None:
        return None, False, 'daily_provenance_inconsistent'
    inserted = _strict_nonnegative_int(marker.get('inserted'))
    if inserted is None:
        return None, False, 'daily_provenance_inconsistent'
    if sample_ids and len(sample_ids) != inserted:
        return None, False, 'daily_provenance_inconsistent'
    if inserted != matched_count:
        return None, False, 'daily_provenance_inconsistent'
    return inserted, True, ''


def _same_day_recorded_orphans(
    eligible_historical: list[dict[str, Any]],
    *,
    day: str,
    matched_sample_ids: set[str],
    matched_keys: set[str],
) -> bool:
    """True when a same-session eligible sample lacks matching insertion provenance."""
    for row in eligible_historical:
        if _date_prefix(row.get('session_date')) != day:
            continue
        key = learning_record_dedupe_key(row)
        sid = _normalize_text(row.get('sample_id'))
        if (key and key in matched_keys) or (sid and sid in matched_sample_ids):
            continue
        raw_recorded = row.get('recorded_at')
        if raw_recorded in (None, ''):
            # Missing timestamp on same-session record is not proven historical.
            return True
        recorded_day = _date_prefix(raw_recorded)
        if not recorded_day:
            # Malformed recorded_at cannot prove historical backfill.
            return True
        if recorded_day != day:
            continue
        return True
    return False


def reconcile_daily_learning_truth(
    *,
    session_date: str | None = None,
    snapshots: list[dict[str, Any]] | None = None,
    outcomes: list[dict[str, Any]] | None = None,
    learning_records: list[dict[str, Any]] | None = None,
    mutations: list[dict[str, Any]] | None = None,
    observed_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Deterministic reconciliation payload for daily/close learning truth."""
    try:
        return _reconcile_daily_learning_truth_impl(
            session_date=session_date,
            snapshots=snapshots,
            outcomes=outcomes,
            learning_records=learning_records,
            mutations=mutations,
            observed_candidates=observed_candidates,
        )
    except Exception as exc:
        day = _date_prefix(session_date) or _session_date()
        return {
            'session_date': day,
            'candidate_observed_count': None,
            'candidate_qualifying_count': None,
            'quality_tradecards_tracked_count': None,
            'canonical_outcomes_recorded_count': None,
            'eligible_learning_samples_added_today': None,
            'eligible_learning_samples_total': None,
            'daily_added_provenance_available': False,
            'historical_total_available': False,
            'reason_sections_available': False,
            'learning_store_status': 'error',
            'source_errors': [f'reconciliation_exception:{type(exc).__name__}'],
            'qualification_reasons': [],
            'winner_reasons': [],
            'unresolved_candidates': [],
            'reference_only_candidates': [],
            'deduped_sample_ids': [],
            'source_files': [
                'candidate_snapshots.jsonl',
                'candidate_outcomes.jsonl',
                'candidate_learning_records.jsonl',
                'candidate_learning_mutations.jsonl',
            ],
            'reason_codes': ['reconciliation_failed'],
            'reconciliation_ok': False,
        }


def _reconcile_daily_learning_truth_impl(
    *,
    session_date: str | None = None,
    snapshots: list[dict[str, Any]] | None = None,
    outcomes: list[dict[str, Any]] | None = None,
    learning_records: list[dict[str, Any]] | None = None,
    mutations: list[dict[str, Any]] | None = None,
    observed_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Deterministic reconciliation payload for daily/close learning truth."""
    day = _date_prefix(session_date) or _session_date()
    source_errors: list[str] = []

    if snapshots is not None:
        snap_rows = [r for r in snapshots if isinstance(r, dict)]
        snap_status = 'ok'
    else:
        snap_rows, snap_status = _load_jsonl(_snapshots_path())
        if snap_status == 'unreadable':
            source_errors.append('snapshots_unreadable')
        elif snap_status == 'malformed':
            source_errors.append('snapshots_malformed')

    if outcomes is not None:
        outcome_rows = [r for r in outcomes if isinstance(r, dict)]
        outcome_status = 'ok'
    else:
        outcome_rows, outcome_status = _load_jsonl(_outcomes_path())
        if outcome_status == 'unreadable':
            source_errors.append('outcomes_unreadable')
        elif outcome_status == 'malformed':
            source_errors.append('outcomes_malformed')

    if learning_records is not None:
        learn_rows = [r for r in learning_records if isinstance(r, dict)]
        learning_store_status = 'ok'
    else:
        # Full scan for cumulative historical counting — no silent 50k truncation.
        learn_rows, learning_store_status = _load_jsonl(_learning_path(), limit=None)
        if learning_store_status == 'unreadable':
            source_errors.append('learning_unreadable')
        elif learning_store_status == 'malformed':
            source_errors.append('learning_malformed')

    if mutations is not None:
        mut_rows = [r for r in mutations if isinstance(r, dict)]
        mut_status = 'ok'
    else:
        mut_rows, mut_status = _load_jsonl(_mutations_path())
        if mut_status == 'unreadable':
            source_errors.append('mutations_unreadable')
        elif mut_status == 'malformed':
            source_errors.append('mutations_malformed')

    observed_extra = [r for r in (observed_candidates or []) if isinstance(r, dict)]

    day_snaps_raw = [r for r in snap_rows if _date_prefix(r.get('session_date')) == day]
    day_outcomes_raw = [r for r in outcome_rows if _date_prefix(r.get('session_date')) == day]

    # Deduplicate snapshots by snapshot_id (keep first).
    snap_by_id: dict[str, dict[str, Any]] = {}
    day_snaps: list[dict[str, Any]] = []
    for r in day_snaps_raw:
        sid = _normalize_text(r.get('snapshot_id'))
        if sid:
            if sid in snap_by_id:
                continue
            snap_by_id[sid] = r
        day_snaps.append(r)

    # Deduplicate outcomes by canonical identity, or deterministic noncanonical fingerprint.
    seen_outcome_keys: set[str] = set()
    day_outcomes: list[dict[str, Any]] = []
    for r in day_outcomes_raw:
        canon = _outcome_canonical_identity(r)
        if canon:
            key = canon
        else:
            key = f'noncanon:{_noncanonical_outcome_fingerprint(r)}'
        if not key or key in ('noncanon:|||', 'noncanon:'):
            key = f'noncanon:{_noncanonical_outcome_fingerprint(r)}'
        if key in seen_outcome_keys:
            continue
        seen_outcome_keys.add(key)
        day_outcomes.append(r)

    observed_syms: set[str] = set()
    for row in day_snaps + day_outcomes + observed_extra:
        sym = _normalize_symbol(row.get('symbol') or row.get('ticker'))
        if sym:
            observed_syms.add(sym)

    qualifying_syms: set[str] = set()
    for row in day_snaps + observed_extra:
        sym = _normalize_symbol(row.get('symbol') or row.get('ticker'))
        if not sym or sym in qualifying_syms:
            continue
        score = _safe_int(row.get('score'), 0) or 0
        why = row.get('why') or row.get('reason_text') or row.get('reason_tags')
        if score >= MIN_QUALITY_SCORE or why:
            qualifying_syms.add(sym)

    quality_tracked: list[dict[str, Any]] = []
    seen_quality_ids: set[str] = set()
    for r in day_snaps:
        sid = _normalize_text(r.get('snapshot_id'))
        if not sid:
            continue
        if sid in seen_quality_ids:
            continue
        stage = _normalize_text(r.get('stage'))
        score = _safe_int(r.get('score'))
        if stage not in PRIMARY_STAGES:
            continue
        if score is None or score < MIN_QUALITY_SCORE:
            continue
        if not _is_eligible_quality_state(r.get('state')):
            continue
        if _truthy_flag(r.get('reference_only')) or _truthy_flag(r.get('reference_outcome')):
            continue
        if _truthy_flag(r.get('captured_only')) or _truthy_flag(r.get('candidate_only')):
            continue
        seen_quality_ids.add(sid)
        quality_tracked.append(r)

    canonical_outcomes: list[dict[str, Any]] = []
    for r in day_outcomes:
        if not _outcome_canonical_identity(r):
            continue
        outcome = _normalize_outcome(r.get('outcome'))
        if outcome not in (OUTCOME_WIN, OUTCOME_LOSS, OUTCOME_NEUTRAL):
            continue
        if _truthy_flag(r.get('reference_only')) or _truthy_flag(r.get('reference_outcome')):
            continue
        canonical_outcomes.append(r)

    # Historical eligible samples (full store when loaded from disk).
    historical_total_available = learning_store_status in ('ok', 'missing')
    reason_sections_available = True
    if snap_status in ('unreadable', 'malformed') or outcome_status in ('unreadable', 'malformed'):
        reason_sections_available = False
    if learning_store_status in ('unreadable', 'malformed'):
        historical_total_available = False
        reason_sections_available = False

    eligible_historical: list[dict[str, Any]] = []
    deduped_sample_ids: list[str] = []
    seen_keys: set[str] = set()
    eligible_by_key: dict[str, dict[str, Any]] = {}
    eligible_by_sample_id: dict[str, dict[str, Any]] = {}
    if learning_store_status not in ('unreadable', 'malformed'):
        for row in learn_rows:
            ok, _reason = is_eligible_historical_learning_sample(row)
            if not ok:
                continue
            key = learning_record_dedupe_key(row)
            if not key or key in seen_keys:
                if key:
                    deduped_sample_ids.append(key)
                continue
            seen_keys.add(key)
            eligible_historical.append(row)
            eligible_by_key[key] = row
            sid = _normalize_text(row.get('sample_id'))
            if sid and sid not in eligible_by_sample_id:
                eligible_by_sample_id[sid] = row

    # Daily-added provenance: require valid resolve_complete + matched persisted inserts.
    day_mutations = [m for m in mut_rows if _date_prefix(m.get('session_date')) == day]
    markers, invalid_markers_present = _classify_resolve_markers(day_mutations, day)
    matched_inserts, matched_sample_ids, match_inconsistent = _matched_daily_insertions(
        day_mutations,
        day=day,
        eligible_by_key=eligible_by_key,
        eligible_by_sample_id=eligible_by_sample_id,
    )
    matched_keys: set[str] = set()
    for ev in matched_inserts:
        dk = _normalize_text(ev.get('dedupe_key'))
        sid = _normalize_text(ev.get('sample_id'))
        if dk:
            matched_keys.add(dk)
        if sid and sid in eligible_by_sample_id:
            matched_keys.add(learning_record_dedupe_key(eligible_by_sample_id[sid]))

    reason_codes: set[str] = set()
    daily_added_provenance_available = False
    eligible_learning_samples_added_today: int | None = None

    if learning_store_status in ('unreadable', 'malformed'):
        reason_codes.add('learning_store_unavailable')
        daily_added_provenance_available = False
        eligible_learning_samples_added_today = None
        historical_total_available = False
        reason_sections_available = False
    elif mut_status in ('unreadable', 'malformed'):
        reason_codes.add('daily_provenance_unreadable' if mut_status == 'unreadable' else 'daily_provenance_malformed')
        daily_added_provenance_available = False
        eligible_learning_samples_added_today = None
    elif invalid_markers_present:
        reason_codes.add('daily_provenance_inconsistent')
        daily_added_provenance_available = False
        eligible_learning_samples_added_today = None
    elif match_inconsistent:
        reason_codes.add('daily_provenance_inconsistent')
        daily_added_provenance_available = False
        eligible_learning_samples_added_today = None
    elif markers:
        count, available, code = _derive_daily_added_from_markers(
            markers,
            matched_count=len(matched_inserts),
            matched_sample_ids=matched_sample_ids,
        )
        if available and not _same_day_recorded_orphans(
            eligible_historical,
            day=day,
            matched_sample_ids=matched_sample_ids,
            matched_keys=matched_keys,
        ):
            daily_added_provenance_available = True
            eligible_learning_samples_added_today = count
        else:
            reason_codes.add(code or 'daily_provenance_inconsistent')
            daily_added_provenance_available = False
            eligible_learning_samples_added_today = None
    else:
        # No valid resolve_complete → cannot prove zero or positive.
        daily_added_provenance_available = False
        eligible_learning_samples_added_today = None
        if _same_day_recorded_orphans(
            eligible_historical,
            day=day,
            matched_sample_ids=matched_sample_ids,
            matched_keys=matched_keys,
        ):
            reason_codes.add('daily_provenance_inconsistent')

    winner_reasons: list[dict[str, Any]] = []
    qualification_reasons: list[dict[str, Any]] = []
    unresolved_candidates: list[str] = []
    reference_only_candidates: list[str] = []
    winner_ids: set[str] = set()
    outcome_snapshot_ids: set[str] = set()

    for outcome in day_outcomes:
        sym = _normalize_symbol(outcome.get('symbol'))
        if not sym:
            continue
        if _truthy_flag(outcome.get('reference_only')) or _truthy_flag(outcome.get('reference_outcome')):
            reference_only_candidates.append(sym)
            continue
        canon_id = _outcome_canonical_identity(outcome)
        sid = _normalize_text(outcome.get('snapshot_id'))
        if sid:
            outcome_snapshot_ids.add(sid)

        if not canon_id:
            label = _qualification_status_label(outcome, winner=False)
            reason = _reason_text_for_row(outcome)
            identity = f'noncanon:{_noncanonical_outcome_fingerprint(outcome)}'
            qualification_reasons.append({
                'symbol': sym,
                'snapshot_id': sid,
                'identity': identity,
                'status': label,
                'reason': reason,
                'reason_code': 'no_canonical_outcome',
                'text': f'{sym} — {reason}; {label}',
            })
            reason_codes.add('no_canonical_outcome')
            continue

        snap = snap_by_id.get(sid) if sid else None
        eligible, code = is_canonical_winner_reason_eligible(
            outcome, snapshot=snap, session_date=day,
        )
        status_src = {**(snap or {}), **outcome}
        label = _qualification_status_label(status_src, winner=eligible)
        reason = _reason_text_for_row(status_src)
        identity = _winner_identity(outcome, snap) or canon_id
        entry = {
            'symbol': sym,
            'snapshot_id': sid,
            'identity': identity,
            'status': label,
            'reason': reason,
            'reason_code': code,
            'text': f'{sym} — {reason}; {label}' if not eligible else f'{sym}: {reason}',
        }
        if eligible:
            if identity not in winner_ids:
                winner_reasons.append(entry)
                winner_ids.add(identity)
        else:
            reason_codes.add(code)
            if _normalize_outcome(outcome.get('outcome')) in (OUTCOME_PENDING, '', 'PENDING'):
                unresolved_candidates.append(sym)
            qualification_reasons.append(entry)

    # Snapshots without a matching outcome identity remain independently countable.
    for snap in day_snaps:
        sym = _normalize_symbol(snap.get('symbol'))
        sid = _normalize_text(snap.get('snapshot_id'))
        if not sym:
            continue
        if sid and sid in outcome_snapshot_ids:
            continue
        if snap.get('reference_only'):
            reference_only_candidates.append(sym)
            continue
        label = _qualification_status_label(snap, winner=False)
        reason = _reason_text_for_row(snap)
        qualification_reasons.append({
            'symbol': sym,
            'snapshot_id': sid,
            'identity': f'snap:{sid}' if sid else f'sym:{sym}',
            'status': label,
            'reason': reason,
            'reason_code': 'candidate_only',
            'text': f'{sym} — {reason}; {label}',
        })
        unresolved_candidates.append(sym)

    covered_ids = {
        str(r.get('identity') or r.get('symbol'))
        for r in qualification_reasons + winner_reasons
    }
    for row in observed_extra:
        sym = _normalize_symbol(row.get('symbol') or row.get('ticker'))
        identity = f'obs:{sym}'
        if not sym or identity in covered_ids or any(
            w.get('symbol') == sym for w in winner_reasons
        ):
            continue
        label = _qualification_status_label(row, winner=False)
        reason = _reason_text_for_row(row)
        qualification_reasons.append({
            'symbol': sym,
            'snapshot_id': '',
            'identity': identity,
            'status': label,
            'reason': reason,
            'reason_code': 'candidate_only',
            'text': f'{sym} — {reason}; {label}',
        })
        covered_ids.add(identity)

    seen_q: set[str] = set()
    uniq_q: list[dict[str, Any]] = []
    for item in qualification_reasons:
        ident = str(item.get('identity') or item.get('symbol') or '')
        if ident in seen_q:
            continue
        seen_q.add(ident)
        uniq_q.append(item)

    total_value: int | None
    if historical_total_available:
        total_value = len(eligible_historical)
    else:
        total_value = None

    reconciliation_ok = True
    if source_errors and any(
        err.endswith('_unreadable') or err.endswith('_malformed') or err.startswith('reconciliation_')
        for err in source_errors
    ):
        # Source integrity failures do not invent success; counts may still be partial.
        pass

    return {
        'session_date': day,
        'candidate_observed_count': len(observed_syms),
        'candidate_qualifying_count': len(qualifying_syms),
        'quality_tradecards_tracked_count': len(quality_tracked),
        'canonical_outcomes_recorded_count': len(canonical_outcomes),
        'eligible_learning_samples_added_today': eligible_learning_samples_added_today,
        'eligible_learning_samples_total': total_value,
        'daily_added_provenance_available': daily_added_provenance_available,
        'historical_total_available': historical_total_available,
        'reason_sections_available': reason_sections_available,
        'learning_store_status': learning_store_status,
        'snapshot_store_status': snap_status,
        'outcome_store_status': outcome_status,
        'mutation_store_status': mut_status,
        'source_errors': sorted(set(source_errors)),
        'qualification_reasons': uniq_q if reason_sections_available else [],
        'winner_reasons': winner_reasons if reason_sections_available else [],
        'unresolved_candidates': sorted(set(unresolved_candidates)),
        'reference_only_candidates': sorted(set(reference_only_candidates)),
        'deduped_sample_ids': deduped_sample_ids,
        'source_files': [
            'candidate_snapshots.jsonl',
            'candidate_outcomes.jsonl',
            'candidate_learning_records.jsonl',
            'candidate_learning_mutations.jsonl',
        ],
        'reason_codes': sorted(reason_codes - {''}),
        'reconciliation_ok': reconciliation_ok,
    }


def _format_unavailable_truth_lines(*, include_reason_sections: bool = True) -> list[str]:
    lines = [
        '<b>Daily learning truth</b>',
        'Eligible learning samples added today: unavailable',
        'Total eligible historical samples: unavailable',
    ]
    if include_reason_sections:
        lines.extend([
            'Candidate qualification reasons:',
            '• unavailable',
            'Winner reasons:',
            '• unavailable',
        ])
    return lines


def _count_availability_malformed(data: dict[str, Any]) -> bool:
    daily = data.get('daily_added_provenance_available')
    hist = data.get('historical_total_available')
    ok = data.get('reconciliation_ok')
    if ok not in (True, False):
        return True
    if daily not in (True, False):
        return True
    if hist not in (True, False):
        return True
    return False


def _reason_availability_malformed(data: dict[str, Any]) -> bool:
    return data.get('reason_sections_available') not in (True, False)


def format_daily_learning_truth_lines(
    truth: dict[str, Any] | None = None,
    *,
    session_date: str | None = None,
    include_reason_sections: bool = True,
) -> list[str]:
    """Telegram/report lines for Daily learning truth (read-only)."""
    try:
        if isinstance(truth, dict) and truth.get('reconciliation_ok') is False:
            return _format_unavailable_truth_lines(include_reason_sections=include_reason_sections)
        if isinstance(truth, dict) and _count_availability_malformed(truth):
            return _format_unavailable_truth_lines(include_reason_sections=include_reason_sections)
        data = truth if isinstance(truth, dict) else reconcile_daily_learning_truth(session_date=session_date)
        if data.get('reconciliation_ok') is False or _count_availability_malformed(data):
            return _format_unavailable_truth_lines(include_reason_sections=include_reason_sections)
    except Exception:
        return _format_unavailable_truth_lines(include_reason_sections=include_reason_sections)

    added = data.get('eligible_learning_samples_added_today')
    if data.get('daily_added_provenance_available') is True and isinstance(added, int):
        added_text = str(added)
    else:
        added_text = 'unavailable'

    if data.get('historical_total_available') is not True:
        total_text = 'unavailable'
    else:
        total = _safe_int(data.get('eligible_learning_samples_total'))
        total_text = 'unavailable' if total is None else str(total)

    lines = [
        '<b>Daily learning truth</b>',
        f'Eligible learning samples added today: {added_text}',
        f'Total eligible historical samples: {total_text}',
    ]
    if not include_reason_sections:
        return lines

    reason_ok = data.get('reason_sections_available')
    if reason_ok is not True or _reason_availability_malformed(data) or data.get('reconciliation_ok') is False:
        lines.extend([
            'Candidate qualification reasons:',
            '• unavailable',
            'Winner reasons:',
            '• unavailable',
        ])
        return lines

    lines.append('Candidate qualification reasons:')
    quals = list(data.get('qualification_reasons') or [])
    if quals:
        for item in quals[:8]:
            text = str(item.get('text') or '').strip()
            if text:
                lines.append(f'• {text}')
    else:
        lines.append('• None recorded today')

    lines.append('Winner reasons:')
    winners = list(data.get('winner_reasons') or [])
    if winners:
        for item in winners[:8]:
            text = str(item.get('text') or '').strip()
            if text:
                lines.append(f'• {text}')
    else:
        lines.append('• None recorded today')
    return lines


def format_learning_sample_count_lines(
    truth: dict[str, Any] | None = None,
    *,
    session_date: str | None = None,
) -> list[str]:
    """Compact count lines used by daily review / close."""
    unavailable = [
        'Eligible learning samples added today: unavailable',
        'Total eligible historical samples: unavailable',
    ]
    try:
        if isinstance(truth, dict) and (
            truth.get('reconciliation_ok') is False or _count_availability_malformed(truth)
        ):
            return list(unavailable)
        data = truth if isinstance(truth, dict) else reconcile_daily_learning_truth(session_date=session_date)
        if data.get('reconciliation_ok') is False or _count_availability_malformed(data):
            return list(unavailable)
    except Exception:
        return list(unavailable)
    added = data.get('eligible_learning_samples_added_today')
    if data.get('daily_added_provenance_available') is True and isinstance(added, int):
        added_text = str(added)
    else:
        added_text = 'unavailable'
    if data.get('historical_total_available') is not True:
        total_text = 'unavailable'
    else:
        total = _safe_int(data.get('eligible_learning_samples_total'))
        total_text = 'unavailable' if total is None else str(total)
    return [
        f'Eligible learning samples added today: {added_text}',
        f'Total eligible historical samples: {total_text}',
    ]


def unavailable_learning_truth_fallback_lines() -> list[str]:
    """Shared formatter fallback when reconciliation itself fails."""
    return [
        'Eligible learning samples added today: unavailable',
        'Total eligible historical samples: unavailable',
        'Candidate qualification reasons:',
        '• unavailable',
        'Winner reasons:',
        '• unavailable',
    ]
