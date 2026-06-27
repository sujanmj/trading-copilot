"""Analyze the latest FixOps diagnostic report with the Trading Copilot AI router."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


FIXOPS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = FIXOPS_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

INCIDENTS_DIR = FIXOPS_DIR / "incidents"
PROMPT_PATH = FIXOPS_DIR / "prompts" / "report_analysis_system.txt"
DIAGNOSTIC_REPORT_JSON_PATH = INCIDENTS_DIR / "latest_diagnostic_report.json"
FULL_REPORT_JSON_PATH = INCIDENTS_DIR / "latest_full_report.json"
ANALYSIS_JSON_PATH = INCIDENTS_DIR / "latest_gpt_analysis.json"
CODEX_PROMPT_PATH = INCIDENTS_DIR / "latest_codex_prompt.txt"

SAFETY_RULES = [
    "Do not delete files.",
    "Do not run rm/rmdir/del.",
    "Do not change secrets.",
    "Do not modify keys.env or .env files.",
    "Do not deploy.",
    "Do not commit.",
    "Do not push.",
    "Make the smallest safe code fix.",
    "Explain changed files and rollback steps.",
    "Keep Telegram local disabled behavior unchanged unless the report specifically says Telegram is the issue.",
]

ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["FIXED", "BROKEN", "UNCERTAIN"]},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "summary": {"type": "string"},
        "failed_sections": {"type": "array", "items": {"type": "string"}},
        "suspected_root_cause": {"type": "string"},
        "risk_level": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
        "should_run_codex": {"type": "boolean"},
        "codex_prompt": {"type": "string"},
    },
    "required": [
        "status",
        "confidence",
        "summary",
        "failed_sections",
        "suspected_root_cause",
        "risk_level",
        "should_run_codex",
        "codex_prompt",
    ],
}

ANALYSIS_KEYS = [
    "status",
    "confidence",
    "summary",
    "failed_sections",
    "suspected_root_cause",
    "risk_level",
    "should_run_codex",
    "codex_prompt",
]

COUNT_MISMATCH_OVERRIDE = "count_mismatch_observation_only"
CRITICAL_FAILURE_SIGNALS = [
    "State: <code>DEGRADED</code>",
    "pipeline stalled",
    "stalled",
    "Alerts: blocked",
    "SLA exceeded",
    "AI router unavailable",
]

AI_ROUTER_UNAVAILABLE_FALLBACK: dict[str, Any] = {
    "status": "UNCERTAIN",
    "confidence": 0.2,
    "summary": "AI router unavailable. Report captured but not analyzed.",
    "failed_sections": ["AI router unavailable"],
    "suspected_root_cause": "Trading Copilot AI router failed or providers unavailable",
    "risk_level": "MEDIUM",
    "should_run_codex": False,
    "codex_prompt": "",
}


class AnalyzerError(RuntimeError):
    """Raised when FixOps report analysis cannot complete safely."""


def _select_report_path() -> Path:
    if DIAGNOSTIC_REPORT_JSON_PATH.exists():
        return DIAGNOSTIC_REPORT_JSON_PATH
    return FULL_REPORT_JSON_PATH


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise AnalyzerError(
            f"Missing report file: {path}. Run python fixops/internal_diagnostic_runner.py first "
            "or fall back by running python fixops/internal_full_runner.py."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AnalyzerError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise AnalyzerError(f"Report JSON must be an object: {path}")
    return data


def _read_system_prompt() -> str:
    if not PROMPT_PATH.exists():
        raise AnalyzerError(f"Missing system prompt file: {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8")


def _extract_report(data: dict[str, Any]) -> dict[str, Any]:
    messages = data.get("messages", [])
    if not isinstance(messages, list):
        raise AnalyzerError("latest_full_report.json field 'messages' must be a list.")

    extracted_messages: list[dict[str, Any]] = []
    all_text_parts: list[str] = []
    for index, message in enumerate(messages, start=1):
        if isinstance(message, dict):
            text = str(message.get("text", "") or "")
            item = {
                "index": message.get("index", index),
                "timestamp": message.get("timestamp", ""),
                "command": message.get("command", ""),
                "cycle_id": message.get("cycle_id", ""),
                "message_kind": message.get("message_kind", ""),
                "text": text,
            }
        else:
            text = str(message or "")
            item = {
                "index": index,
                "timestamp": "",
                "command": "",
                "cycle_id": "",
                "message_kind": "",
                "text": text,
            }
        extracted_messages.append(item)
        all_text_parts.append(text)

    return {
        "command_set": data.get("command_set", ""),
        "commands": data.get("commands", []),
        "command": data.get("command", ""),
        "started_at": data.get("started_at", ""),
        "finished_at": data.get("finished_at", ""),
        "message_count": data.get("message_count", len(extracted_messages)),
        "messages": extracted_messages,
        "all_message_text": "\n\n".join(all_text_parts),
    }


def _build_router_prompt(system_prompt: str, report: dict[str, Any]) -> str:
    diagnostic_rules = """
FixOps diagnostic interpretation rules:
- Prefer latest_diagnostic_report.json when present because it captures /status, /stats, /elite, /opps, /risks, /calibration, and /review.
- /review is the same cache-only master desk review as /full. It is expected to say cache-only or no pipelines executed.
- Do not mark cache-only/no pipelines executed as BROKEN when it appears only in /review output.
- Mark BROKEN when /status or runtime health says degraded, stale, conflicting, recovering without progress, failed, or otherwise unhealthy.
- Mark BROKEN when important diagnostic commands fail unexpectedly or emit command errors.
- Empty opportunities alone should not be BROKEN when market state, freshness, or risk posture reasonably explains it.
- Stale/conflicting runtime health is BROKEN.
""".strip()
    return (
        f"{system_prompt.strip()}\n\n"
        f"{diagnostic_rules}\n\n"
        "Analyze this captured Trading Copilot FixOps report. "
        "Return only strict JSON with exactly these keys: "
        f"{', '.join(ANALYSIS_KEYS)}.\n\n"
        f"{json.dumps(report, indent=2, ensure_ascii=False)}"
    )


def _parse_analysis(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    try:
        analysis = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise AnalyzerError(f"AI analysis was not valid JSON: {exc}") from exc
    if not isinstance(analysis, dict):
        raise AnalyzerError("AI analysis must be a JSON object.")
    return analysis


def _validate_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    required = set(ANALYSIS_SCHEMA["required"])
    missing = sorted(required - set(analysis.keys()))
    if missing:
        raise AnalyzerError(f"AI analysis missing required field(s): {', '.join(missing)}")

    if analysis["status"] not in {"FIXED", "BROKEN", "UNCERTAIN"}:
        raise AnalyzerError("AI analysis field 'status' must be FIXED, BROKEN, or UNCERTAIN.")
    if analysis["risk_level"] not in {"LOW", "MEDIUM", "HIGH"}:
        raise AnalyzerError("AI analysis field 'risk_level' must be LOW, MEDIUM, or HIGH.")
    if not isinstance(analysis["should_run_codex"], bool):
        raise AnalyzerError("AI analysis field 'should_run_codex' must be boolean.")
    if not isinstance(analysis["failed_sections"], list) or not all(
        isinstance(item, str) for item in analysis["failed_sections"]
    ):
        raise AnalyzerError("AI analysis field 'failed_sections' must be a list of strings.")

    try:
        confidence = float(analysis["confidence"])
    except (TypeError, ValueError) as exc:
        raise AnalyzerError("AI analysis field 'confidence' must be numeric.") from exc
    analysis["confidence"] = max(0.0, min(1.0, confidence))

    for key in ("summary", "suspected_root_cause", "codex_prompt"):
        if not isinstance(analysis[key], str):
            raise AnalyzerError(f"AI analysis field '{key}' must be a string.")

    if analysis["should_run_codex"]:
        analysis["codex_prompt"] = _ensure_safety_rules(analysis["codex_prompt"])

    return {key: analysis[key] for key in ANALYSIS_KEYS}


def _is_count_mismatch_section(section: Any) -> bool:
    text = str(section or "").lower()
    return (
        "mismatch" in text
        and "prediction" in text
        and "count" in text
        and ("/status" in text or "status" in text)
        and ("/review" in text or "review" in text)
    )


def _only_prediction_count_mismatch(failed_sections: Any) -> bool:
    if not isinstance(failed_sections, list) or not failed_sections:
        return False
    return all(_is_count_mismatch_section(section) for section in failed_sections)


def _has_stale_snapshot_line(report_text: str) -> bool:
    for line in report_text.splitlines():
        if "Snapshot:" in line and "(stale)" in line:
            return True
    return False


def _has_critical_failure_signal(report_text: str) -> bool:
    if "State: <code>DEGRADED</code>" in report_text:
        return True
    if _has_stale_snapshot_line(report_text):
        return True
    lowered = report_text.lower()
    for signal in CRITICAL_FAILURE_SIGNALS:
        if signal == "State: <code>DEGRADED</code>":
            continue
        if signal.lower() in lowered:
            return True
    return False


def _apply_fixops_postprocessing(analysis: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """Deterministic guardrails after AI JSON parsing."""
    failed_sections = analysis.get("failed_sections") or []

    def _is_prediction_count_issue(value: Any) -> bool:
        text = str(value or "").lower()
        return "prediction" in text and "count" in text and (
            "mismatch" in text
            or "inconsisten" in text
            or "discrepanc" in text
            or "/status" in text
            or "/review" in text
        )

    if isinstance(failed_sections, list) and failed_sections and all(_is_prediction_count_issue(x) for x in failed_sections):
        analysis = dict(analysis)
        analysis["status"] = "UNCERTAIN"
        analysis["risk_level"] = "LOW"
        analysis["should_run_codex"] = False
        analysis["suspected_root_cause"] = COUNT_MISMATCH_OVERRIDE
        analysis["codex_prompt"] = ""
        analysis["fixops_override"] = COUNT_MISMATCH_OVERRIDE

    return analysis

def _ensure_safety_rules(prompt: str) -> str:
    prompt = prompt.strip()
    missing = [rule for rule in SAFETY_RULES if rule not in prompt]
    if not missing:
        return prompt

    safety_block = "Safety rules:\n" + "\n".join(f"- {rule}" for rule in SAFETY_RULES)
    if prompt:
        return safety_block + "\n\n" + prompt
    return safety_block


def _router_unavailable_fallback() -> dict[str, Any]:
    return dict(AI_ROUTER_UNAVAILABLE_FALLBACK)


def _extract_router_text(result: dict[str, Any]) -> str:
    text = result.get("text")
    if isinstance(text, str) and text.strip():
        return text
    raise AnalyzerError("AI router returned success=true without analysis text.")


def _analyze_with_router(prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        from backend.ai.ai_router import ask_ai

        result = ask_ai(
            prompt,
            use_case="fixops_report_analyzer",
            max_tokens=2500,
            channel="fixops",
        )
    except Exception:
        return _router_unavailable_fallback(), {}

    if not isinstance(result, dict):
        return _router_unavailable_fallback(), {}

    meta = {
        "provider": result.get("provider", ""),
        "model": result.get("model", ""),
    }
    if not result.get("success"):
        return _router_unavailable_fallback(), meta

    analysis_text = _extract_router_text(result)
    return _validate_analysis(_parse_analysis(analysis_text)), meta


def _save_outputs(analysis: dict[str, Any]) -> tuple[Path, Path]:
    INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)
    ANALYSIS_JSON_PATH.write_text(json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8")
    CODEX_PROMPT_PATH.write_text(analysis.get("codex_prompt", ""), encoding="utf-8")
    return ANALYSIS_JSON_PATH, CODEX_PROMPT_PATH


def run_analysis() -> tuple[dict[str, Any], dict[str, Any], Path]:
    report_path = _select_report_path()
    report_data = _read_json(report_path)
    report = _extract_report(report_data)
    system_prompt = _read_system_prompt()
    prompt = _build_router_prompt(system_prompt, report)
    analysis, meta = _analyze_with_router(prompt)
    analysis = _apply_fixops_postprocessing(analysis, report)
    return analysis, meta, report_path


def _print_summary(
    analysis: dict[str, Any],
    meta: dict[str, Any],
    report_path: Path,
    analysis_path: Path,
    codex_prompt_path: Path,
) -> None:
    print(f"report file analyzed: {report_path}")
    if meta.get("provider"):
        print(f"provider: {meta['provider']}")
    if meta.get("model"):
        print(f"model: {meta['model']}")
    print(f"status: {analysis['status']}")
    print(f"confidence: {analysis['confidence']}")
    print(f"failed_sections: {analysis['failed_sections']}")
    print(f"suspected_root_cause: {analysis['suspected_root_cause']}")
    print(f"should_run_codex: {analysis['should_run_codex']}")
    if analysis.get("fixops_override"):
        print(f"fixops_override: {analysis['fixops_override']}")
    print(f"saved analysis path: {analysis_path}")
    print(f"saved codex prompt path: {codex_prompt_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze the latest FixOps diagnostic report with the AI router.")
    parser.parse_args(argv)

    try:
        analysis, meta, report_path = run_analysis()
        analysis_path, codex_prompt_path = _save_outputs(analysis)
        _print_summary(analysis, meta, report_path, analysis_path, codex_prompt_path)
        return 0
    except AnalyzerError as exc:
        print(f"FixOps GPT analyzer error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
