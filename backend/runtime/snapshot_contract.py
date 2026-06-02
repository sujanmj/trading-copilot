"""Frontend runtime snapshot API contract normalization."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


STALE_HOURS = 2.0


def _parse_iso(raw: object) -> Optional[datetime]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _age_hours_from_iso(iso: str) -> Optional[float]:
    dt = _parse_iso(iso)
    if dt is None:
        return None
    delta = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
    return round(max(0.0, delta.total_seconds()) / 3600.0, 2)


def runtime_snapshot_age_hours(payload: dict, generated_at: str) -> Optional[float]:
    """Underlying data age in hours (data_as_of preferred over package time)."""
    fresh = payload.get('freshness') if isinstance(payload.get('freshness'), dict) else {}
    if fresh.get('age_hours') is not None:
        try:
            return round(max(0.0, float(fresh['age_hours'])), 2)
        except (TypeError, ValueError):
            pass

    data_as_of = payload.get('data_as_of')
    if data_as_of:
        age = _age_hours_from_iso(str(data_as_of))
        if age is not None:
            return age

    ms = payload.get('market_snapshot') if isinstance(payload.get('market_snapshot'), dict) else {}
    snap_health = payload.get('snapshot_health') if isinstance(payload.get('snapshot_health'), dict) else {}
    ms_fresh = ms.get('freshness') if isinstance(ms.get('freshness'), dict) else {}
    fresh_state = payload.get('freshness_state') if isinstance(payload.get('freshness_state'), dict) else {}
    age_minutes = (
        snap_health.get('age_minutes')
        or ms_fresh.get('age_minutes')
        or fresh_state.get('age_minutes')
    )
    if age_minutes is not None:
        try:
            return round(max(0.0, float(age_minutes) / 60.0), 2)
        except (TypeError, ValueError):
            pass
    if not generated_at:
        return None
    return _age_hours_from_iso(generated_at)


def package_age_hours(payload: dict, package_generated_at: str) -> Optional[float]:
    fresh = payload.get('freshness') if isinstance(payload.get('freshness'), dict) else {}
    if fresh.get('package_age_hours') is not None:
        try:
            return round(max(0.0, float(fresh['package_age_hours'])), 2)
        except (TypeError, ValueError):
            pass
    if not package_generated_at:
        return None
    return _age_hours_from_iso(package_generated_at)


def _market_status_from_payload(payload: dict) -> str:
    explicit = payload.get('market_status')
    if explicit in ('open', 'closed', 'unknown'):
        return str(explicit)
    try:
        from backend.utils.market_hours import get_operational_status

        op = get_operational_status()
        period = str(op.get('period') or '')
        if op.get('market_hours') or period == 'pre_market':
            return 'open'
        if period in ('post_market', 'after_hours', 'night', 'weekend'):
            return 'closed'
    except Exception:
        pass
    operational = payload.get('operational') if isinstance(payload.get('operational'), dict) else {}
    if operational.get('market_hours') is True:
        return 'open'
    if operational.get('after_hours_mode') or operational.get('market_hours') is False:
        return 'closed'
    return 'unknown'


def wrap_runtime_snapshot_for_frontend(
    payload: dict,
    *,
    cache_path: Optional[Path] = None,
) -> dict:
    """Normalize cache/build payloads for RuntimeManager + SnapshotAdapter contract."""
    if not isinstance(payload, dict):
        return payload

    out = dict(payload)
    ms = out.get('market_snapshot') if isinstance(out.get('market_snapshot'), dict) else {}
    exports = out.get('exports') if isinstance(out.get('exports'), dict) else {}
    data = out.get('data') if isinstance(out.get('data'), dict) else {}

    if not exports and data:
        exports = dict(data)
        out['exports'] = exports
    elif exports and not data:
        out['data'] = dict(exports)
    elif exports and data:
        merged_exports = dict(exports)
        for key, val in data.items():
            merged_exports.setdefault(key, val)
        out['exports'] = merged_exports
        out['data'] = dict(merged_exports)

    package_generated_at = out.get('package_generated_at') or out.get('generated_at') or ms.get('generated_at')
    if not package_generated_at and cache_path and cache_path.is_file():
        try:
            package_generated_at = datetime.fromtimestamp(cache_path.stat().st_mtime).isoformat()
        except Exception:
            pass
    if not package_generated_at:
        package_generated_at = datetime.now().isoformat()
    out['package_generated_at'] = package_generated_at
    out['generated_at'] = package_generated_at

    data_as_of = out.get('data_as_of')
    if not data_as_of:
        data_as_of = (
            ms.get('intelligence_timestamp')
            or ms.get('snapshot_published_at')
            or out.get('snapshot_published_at')
            or out.get('intelligence_timestamp')
        )
    if data_as_of:
        out['data_as_of'] = data_as_of

    market_status = _market_status_from_payload(out)
    out['market_status'] = market_status
    market_closed = market_status == 'closed'

    snap_id = out.get('snapshot_id') or out.get('active_snapshot_id') or ms.get('snapshot_id')
    if snap_id:
        out['snapshot_id'] = snap_id

    action_plan = out.get('action_plan') or ms.get('action_plan') or ''
    if not action_plan:
        intel_src = exports.get('intelligence') or data.get('intelligence') or ms.get('intelligence') or {}
        if isinstance(intel_src, dict):
            action_plan = intel_src.get('action_plan') or intel_src.get('actionPlan') or ''
    out['action_plan'] = action_plan

    intelligence = out.get('intelligence')
    if not intelligence:
        intelligence = exports.get('intelligence') or data.get('intelligence') or ms.get('intelligence') or {}
    out['intelligence'] = intelligence if isinstance(intelligence, dict) else {}

    data_age_hours = runtime_snapshot_age_hours(out, str(data_as_of or package_generated_at))
    pkg_age_hours = package_age_hours(out, str(package_generated_at))

    snap_health = out.get('snapshot_health') if isinstance(out.get('snapshot_health'), dict) else {}
    ms_fresh = ms.get('freshness') if isinstance(ms.get('freshness'), dict) else {}
    fresh_state = out.get('freshness_state') if isinstance(out.get('freshness_state'), dict) else {}

    underlying_stale = bool(
        data_age_hours is not None
        and float(data_age_hours) > STALE_HOURS
        and not market_closed
    )
    if not underlying_stale:
        underlying_stale = bool(
            snap_health.get('stale')
            or ms_fresh.get('stale')
            or fresh_state.get('export_stale')
        ) and not market_closed

    if out.get('status') == 'warming_up':
        underlying_stale = False

    out['freshness'] = {
        'age_hours': data_age_hours,
        'package_age_hours': pkg_age_hours if pkg_age_hours is not None else 0.0,
        'stale': underlying_stale,
        'source': 'runtime_snapshot',
    }

    warnings = list(out.get('validation_warnings') or [])
    if market_closed and data_as_of and 'market_closed_data_as_of' not in warnings:
        warnings.append('market_closed_data_as_of')
    out['validation_warnings'] = warnings

    if out.get('status') != 'warming_up':
        out['ok'] = True

    return out
