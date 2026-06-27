"""Read-only FixOps probe for runtime/session/snapshot source mismatches."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FIXOPS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = FIXOPS_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
INCIDENTS_DIR = FIXOPS_DIR / "incidents"
JSON_PATH = INCIDENTS_DIR / "latest_runtime_state_probe.json"
TXT_PATH = INCIDENTS_DIR / "latest_runtime_state_probe.txt"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"_exists": False, "_path": str(path)}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data["_exists"] = True
            data["_path"] = str(path)
            return data
        return {"_exists": True, "_path": str(path), "_shape": type(data).__name__, "_value": data}
    except Exception as exc:  # noqa: BLE001 - probe should continue.
        return {"_exists": True, "_path": str(path), "_error": f"{type(exc).__name__}: {exc}"}


def _to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        try:
            return value.to_dict()
        except Exception:
            pass
    return value


def _get(data: Any, *keys: str, default: Any = None) -> Any:
    cur = data
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return default if cur is None else cur


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _age_minutes_from_ts(value: Any) -> int | None:
    dt = _parse_dt(value)
    if dt is None:
        return None
    return max(0, int((datetime.now(timezone.utc) - dt).total_seconds() / 60))


def _age_display(minutes: Any) -> str:
    if minutes is None:
        return "-"
    try:
        mins = int(float(minutes))
    except (TypeError, ValueError):
        return str(minutes)
    if mins < 60:
        return f"{mins}m"
    hours = mins / 60
    if hours < 48:
        return f"{hours:.1f}h"
    return f"{hours / 24:.1f}d"


def _age_from_ts_display(value: Any) -> str | None:
    minutes = _age_minutes_from_ts(value)
    return _age_display(minutes) if minutes is not None else None


def _source_age(data: dict[str, Any]) -> Any:
    freshness = _get(data, "snapshot_freshness", default={}) or _get(data, "freshness", default={}) or {}
    return _first(
        freshness.get("age_display"),
        _age_display(freshness.get("age_minutes")) if freshness.get("age_minutes") is not None else None,
        _age_display(data.get("snapshot_age_sec") / 60) if data.get("snapshot_age_sec") is not None else None,
        _age_from_ts_display(data.get("published_at")),
        _age_from_ts_display(data.get("generated_at")),
        _age_from_ts_display(data.get("updated_at")),
    )


def _scanner_age(data: dict[str, Any]) -> Any:
    rs = data.get("runtime_state") if isinstance(data.get("runtime_state"), dict) else data
    sources = _get(rs, "source_freshness", default={}) or {}
    scanner = sources.get("scanner") if isinstance(sources, dict) else {}
    scanner_health = _get(rs, "scanner_health", default={}) or {}
    return _first(
        _get(scanner, "age_display"),
        _age_display(_get(scanner, "age_minutes")) if _get(scanner, "age_minutes") is not None else None,
        _get(scanner, "status"),
        _get(scanner_health, "age_display"),
        _get(scanner_health, "display"),
    )


def _active_predictions(data: dict[str, Any]) -> Any:
    sections = _first(
        _get(data, "metrics", "sections"),
        _get(data, "metric_sections"),
        _get(data, "runtime_state", "metrics", "sections"),
    ) or {}
    live = sections.get("live_session") if isinstance(sections, dict) else {}
    pending_cls = _first(
        _get(data, "pending_classification"),
        _get(data, "runtime_state", "metrics", "pending_classification"),
    ) or {}
    predictions = data.get("predictions")
    return _first(
        _get(live, "active_predictions"),
        _get(live, "pending"),
        _get(data, "prediction_counts", "pending"),
        _get(data, "runtime_state", "prediction_counts", "pending"),
        _get(data, "count"),
        len(predictions) if isinstance(predictions, list) else None,
        _get(pending_cls, "pending_active"),
        _get(pending_cls, "active_pending"),
        _get(data, "metrics_all_time", "pending"),
    )


def _lifecycle(data: dict[str, Any]) -> tuple[str, str]:
    lc = _first(
        _get(data, "lifecycle"),
        _get(data, "runtime_state", "lifecycle"),
        _get(data, "session"),
    ) or {}
    state = _first(_get(lc, "lifecycle_state"), _get(lc, "session_status"), _get(data, "lifecycle_state"))
    display = _first(_get(lc, "lifecycle_display"), _get(lc, "session_display"), _get(data, "lifecycle_display"))
    if state and display:
        return str(state), str(display)
    if state:
        return str(state), str(state)
    if display:
        return "", str(display)
    return "", "-"


def _pipeline_stalled(data: dict[str, Any]) -> Any:
    pipeline = _first(
        _get(data, "pipeline"),
        _get(data, "pipeline_health"),
        _get(data, "runtime_state", "pipeline"),
        _get(data, "runtime_state", "pipeline_health"),
    ) or {}
    stalled = _get(pipeline, "stalled_stages") or []
    any_stalled = bool(_get(pipeline, "any_stalled")) or bool(stalled)
    return ", ".join(str(s) for s in stalled) if stalled else ("yes" if any_stalled else "none")


def _degraded_reasons(data: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    primary = _get(data, "primary_state") or _get(data, "runtime_state", "primary_state")
    if primary == "DEGRADED":
        reasons.append("primary_state=DEGRADED")

    _state, display = _lifecycle(data)
    if "degraded" in display.lower() or "stale" in display.lower() or "conflicting" in display.lower():
        reasons.append(f"lifecycle_display={display}")

    freshness = _first(_get(data, "snapshot_freshness"), _get(data, "freshness"), _get(data, "runtime_state", "snapshot_freshness")) or {}
    if freshness.get("stale"):
        reasons.append("snapshot_stale")
    if freshness.get("degraded"):
        reasons.append("snapshot_degraded")
    for warning in freshness.get("warnings") or []:
        reasons.append(str(warning))

    secondary = _first(_get(data, "secondary_flags"), _get(data, "runtime_state", "secondary_flags")) or {}
    if isinstance(secondary, dict):
        reasons.extend(str(k) for k, v in secondary.items() if v)

    pipeline_stalled = _pipeline_stalled(data)
    if pipeline_stalled not in ("", "-", "none"):
        reasons.append(f"pipeline_stalled={pipeline_stalled}")

    for key in ("blockers", "warnings"):
        values = data.get(key) or _get(data, "runtime_state", key) or []
        if isinstance(values, list):
            reasons.extend(str(v) for v in values if v)

    if data.get("_error"):
        reasons.append(str(data["_error"]))
    if data.get("_exists") is False:
        reasons.append("file_missing")
    return list(dict.fromkeys(reasons))[:8]


def _row(source: str, data: dict[str, Any]) -> dict[str, Any]:
    state, display = _lifecycle(data)
    lifecycle = f"{state} / {display}" if state and display != state else (display or state or "-")
    active_predictions = _active_predictions(data)
    return {
        "source": source,
        "lifecycle": lifecycle,
        "snapshot_age": _source_age(data) or "-",
        "scanner_age": _scanner_age(data) or "-",
        "active_predictions": active_predictions if active_predictions is not None else "-",
        "pipeline_stalled": _pipeline_stalled(data),
        "degraded_reasons": _degraded_reasons(data),
    }


def _safe_call(label: str, fn: Any) -> dict[str, Any]:
    try:
        value = _to_plain(fn())
        return value if isinstance(value, dict) else {"value": value}
    except Exception as exc:  # noqa: BLE001 - probe should keep going.
        return {"_error": f"{type(exc).__name__}: {exc}"}


def _suppress_runtime_audit_writes() -> None:
    try:
        import backend.debug.runtime_audit as runtime_audit

        runtime_audit.audit_from_runtime_state = lambda _state: None
        runtime_audit.record_audit_event = lambda *_args, **_kwargs: None
        runtime_audit.record_scheduler_drift = lambda *_args, **_kwargs: None
    except Exception:
        pass


def collect_probe() -> dict[str, Any]:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    _suppress_runtime_audit_writes()

    sources: dict[str, dict[str, Any]] = {}

    def runtime_state_call() -> dict[str, Any]:
        from backend.runtime.runtime_state import get_runtime_state

        return get_runtime_state(force_refresh=True)

    def market_snapshot_call() -> dict[str, Any]:
        from backend.runtime.market_snapshot_engine import get_current_market_snapshot

        return _to_plain(get_current_market_snapshot(force_refresh=True))

    sources["runtime_state_api"] = _safe_call("runtime_state_api", runtime_state_call)
    sources["market_snapshot_api"] = _safe_call("market_snapshot_api", market_snapshot_call)

    try:
        from backend.intelligence import active_snapshot

        sources["active_snapshot_meta_api"] = _safe_call("active_snapshot_meta_api", active_snapshot.get_active_snapshot_meta)
        sources["active_snapshot_health_api"] = _safe_call("active_snapshot_health_api", active_snapshot.snapshot_health)
        active_snapshot_path = getattr(active_snapshot, "ACTIVE_SNAPSHOT_FILE", DATA_DIR / "active_snapshot.json")
    except Exception as exc:  # noqa: BLE001
        sources["active_snapshot_meta_api"] = {"_error": f"{type(exc).__name__}: {exc}"}
        sources["active_snapshot_health_api"] = {"_error": f"{type(exc).__name__}: {exc}"}
        active_snapshot_path = DATA_DIR / "active_snapshot.json"

    sources["current_snapshot_file"] = _read_json(DATA_DIR / "runtime" / "current_snapshot.json")
    sources["active_snapshot_file"] = _read_json(Path(active_snapshot_path))
    sources["stats_data_file"] = _read_json(DATA_DIR / "stats_data.json")
    sources["active_predictions_file"] = _read_json(DATA_DIR / "active_predictions.json")

    rows = [_row(name, data) for name, data in sources.items()]
    return {
        "generated_at": _utc_now(),
        "comparison_table": rows,
        "sources": sources,
    }


def _format_table(rows: list[dict[str, Any]]) -> str:
    headers = ["Source", "lifecycle", "snapshot_age", "scanner_age", "active_predictions", "degraded_reasons"]
    rendered = []
    for row in rows:
        rendered.append(
            {
                "Source": row["source"],
                "lifecycle": str(row["lifecycle"]),
                "snapshot_age": str(row["snapshot_age"]),
                "scanner_age": str(row["scanner_age"]),
                "active_predictions": str(row["active_predictions"]),
                "degraded_reasons": "; ".join(row.get("degraded_reasons") or []) or "-",
            }
        )
    widths = {
        header: min(48, max(len(header), *(len(item[header]) for item in rendered))) if rendered else len(header)
        for header in headers
    }

    def _cell(text: str, width: int) -> str:
        text = text if len(text) <= width else text[: width - 1] + "…"
        return text.ljust(width)

    lines = [" | ".join(_cell(header, widths[header]) for header in headers)]
    lines.append("-+-".join("-" * widths[header] for header in headers))
    for item in rendered:
        lines.append(" | ".join(_cell(item[header], widths[header]) for header in headers))
    return "\n".join(lines)


def _save_probe(payload: dict[str, Any]) -> tuple[Path, Path, str]:
    INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)
    table = _format_table(payload["comparison_table"])
    text = f"FixOps Runtime State Probe\nGenerated: {payload['generated_at']}\n\n{table}\n"
    JSON_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    TXT_PATH.write_text(text, encoding="utf-8")
    return JSON_PATH, TXT_PATH, table


def main() -> int:
    try:
        payload = collect_probe()
        json_path, txt_path, table = _save_probe(payload)
        print(table)
        print(f"\nSaved json path: {json_path}")
        print(f"Saved txt path: {txt_path}")
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI should show a clear local error.
        print(f"FixOps runtime state probe error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
