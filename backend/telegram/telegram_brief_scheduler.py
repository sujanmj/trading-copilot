"""
IST scheduled briefs for Telegram Analysis Bot (Stage 45TG3).

Morning 08:00 · Close 16:30 · Overnight 06:30
Optional: pre-market 09:05 · close-watch 15:20

Uses lazy runners only — never full run_local.py.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from backend.utils.config import DATA_DIR

IST = ZoneInfo('Asia/Kolkata')
SENT_STATE_FILE = DATA_DIR / 'telegram_brief_scheduler_state.json'

CORE_SLOTS = {
    'morning': (8, 0),
    'close': (16, 30),
    'overnight': (6, 30),
}
OPTIONAL_SLOTS = {
    'premarket_reminder': (9, 5),
    'close_watch': (15, 20),
}


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


def _load_sent_state() -> dict:
    if not SENT_STATE_FILE.is_file():
        return {}
    try:
        return json.loads(SENT_STATE_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_sent_state(state: dict) -> None:
    SENT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SENT_STATE_FILE.write_text(json.dumps(state, indent=2), encoding='utf-8')


def _slot_key(slot: str, now: datetime) -> str:
    return f"{now.date().isoformat()}:{slot}"


def _already_sent(slot: str, now: datetime) -> bool:
    state = _load_sent_state()
    return state.get(_slot_key(slot, now)) is True


def _mark_sent(slot: str, now: datetime) -> None:
    state = _load_sent_state()
    state[_slot_key(slot, now)] = True
    cutoff = now.date().isoformat()
    cleaned = {k: v for k, v in state.items() if k >= cutoff or ':' not in k}
    _save_sent_state(cleaned)


def build_morning_brief_text() -> str:
    from backend.telegram.lazy_command_runner import run_global_only, run_market_only

    global_res = run_global_only()
    market_res = run_market_only()
    watch_res = _build_today_tomorrow_text('today')

    lines = [
        '<b>☀️ Morning brief</b>',
    ]
    try:
        from backend.telegram.india_mode_lock import resolve_telegram_market_phase

        lines.append(f'Market mode: <code>{resolve_telegram_market_phase()}</code>')
    except Exception:
        pass
    try:
        from backend.analytics.unified_decision_engine import get_feed_freshness_meta, note_snapshot_pick

        meta = get_feed_freshness_meta()
        for key in ('report', 'scanner', 'news'):
            line = (meta.get('lines') or {}).get(key)
            if line:
                lines.append(line)
    except Exception:
        pass
    lines.extend([
        global_res.get('text', ''),
        '',
        market_res.get('text', ''),
        '',
        watch_res,
    ])
    try:
        from backend.analytics.unified_decision_engine import note_snapshot_pick
        from backend.analytics.railway_decision_bootstrap import load_cached_stock_decision

        today = load_cached_stock_decision('today') or {}
        from backend.analytics.unified_decision_engine import apply_live_guard_to_payload

        guarded = apply_live_guard_to_payload(today) if today.get('ok') else today
        note_snapshot_pick('morning', (guarded.get('top_pick') or {}).get('ticker'))
    except Exception:
        pass
    from backend.telegram.response_format import strip_stage_markers
    return strip_stage_markers('\n'.join(line for line in lines if line is not None))


def build_premarket_close_unavailable_text() -> str:
    from backend.telegram.india_mode_lock import resolve_telegram_market_phase
    from backend.trading.tradecard_journal import summarize_today_outcomes

    phase = resolve_telegram_market_phase()
    counts = summarize_today_outcomes().get('counts') or {}
    generated = int(counts.get('generated') or 0)
    return '\n'.join([
        '<b>🔔 Close summary not available yet</b>',
        f'Market mode: <code>{phase}</code>',
        'Reason: market has not completed today.',
        'Use /premarket or /today after 09:20.',
        f'Tradecards today: {generated}',
        'No final EOD resolution yet.',
    ])


def _build_research_mode_close_brief_text() -> str:
    try:
        from backend.analytics.unified_decision_engine import get_feed_freshness_meta

        meta = get_feed_freshness_meta()
    except Exception:
        meta = {'lines': {}}

    lines = [
        '<b>🔔 Research-mode summary</b>',
        'Market mode: <code>RESEARCH_MODE</code>',
    ]
    freshness_lines = meta.get('lines') if isinstance(meta, dict) else {}
    for key in ('report', 'scanner', 'news'):
        line = (freshness_lines or {}).get(key)
        if line:
            lines.append(str(line))
    if not any((freshness_lines or {}).get(k) for k in ('report', 'scanner', 'news')):
        lines.extend([
            'Report: unavailable',
            'Scanner: unavailable',
            'Latest news cache: unavailable',
        ])
    lines.append('No live intraday/EOD confirmation available in research mode.')

    report_stale = bool((meta or {}).get('report_stale') or (meta or {}).get('report_suppressed'))
    try:
        from backend.analytics.unified_decision_engine import is_report_display_suppressed

        report_stale = report_stale or is_report_display_suppressed(meta=meta)
    except Exception:
        pass
    if report_stale:
        lines.extend([
            '',
            'Report cache stale — not using old daily pack as current.',
            'Use /refresh full after market close or wait for scheduled report.',
        ])

    try:
        from backend.trading.tradecard_journal import summarize_today_outcomes
        from backend.trading.tradecard_latest import (
            find_latest_tradecard_audit,
            summarize_latest_tradecard_audits,
        )

        counts = summarize_today_outcomes().get('counts') or {}
        audits = summarize_latest_tradecard_audits()
        audit_count = int(audits.get('count') or 0)
        lines.extend([
            '',
            '<b>Tradecards:</b>',
            f"Generated: {int(counts.get('generated') or 0)}",
            f"Pending: {int(counts.get('pending') or 0)}",
            f'Audit-only: {audit_count}',
        ])
        latest_audit = find_latest_tradecard_audit()
        if latest_audit:
            ticker = str(latest_audit.get('ticker') or '').strip().upper()
            lines.extend([
                '',
                f'{ticker} — NEXT-SESSION WATCH ONLY',
                'Reason: no active entry in current mode',
                'Plan: confirm after 09:20 with fresh price + volume',
            ])
        else:
            lines.extend([
                '',
                'No clean active watch yet.',
            ])
    except Exception:
        lines.extend([
            '',
            '<b>Tradecards:</b>',
            'Generated: 0',
            'Pending: 0',
            'Audit-only: 0',
        ])

    from backend.telegram.response_format import strip_stage_markers
    return strip_stage_markers('\n'.join(lines))


def _now_ist() -> datetime:
    return datetime.now(IST)


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _daily_pack_path() -> Path:
    try:
        from backend.telegram import lazy_command_runner

        return Path(lazy_command_runner.DAILY_PACK_FILE)
    except Exception:
        return DATA_DIR / 'daily_report_pack_latest.json'


def _canonical_refresh_state_path() -> Path:
    return DATA_DIR / 'runtime' / 'canonical_refresh_state.json'


def _learning_pack_version() -> str:
    try:
        from backend.analytics.actual_learning_resolver import LEARNING_PACK_VERSION

        return LEARNING_PACK_VERSION
    except Exception:
        return '4A3_price_bridge'


def mark_canonical_refresh_complete(*, source: str = 'telegram_refresh') -> dict[str, Any]:
    """Record the latest full canonical refresh for close-pack invalidation."""
    ts = _now_ist().isoformat()
    payload = {
        'ok': True,
        'last_canonical_refresh_at': ts,
        'source': source,
    }
    try:
        path = _canonical_refresh_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, default=str), encoding='utf-8')
    except Exception:
        pass
    return payload


def _last_canonical_refresh_at() -> datetime | None:
    state = _load_json_file(_canonical_refresh_state_path())
    return _parse_dt_ist(state.get('last_canonical_refresh_at'))


def _parse_dt_ist(value: Any) -> datetime | None:
    if value in (None, ''):
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    except Exception:
        return None


def _age_minutes(generated_at: datetime | None, now: datetime | None = None) -> int | None:
    if generated_at is None:
        return None
    now = now or _now_ist()
    return max(0, int((now - generated_at).total_seconds() // 60))


def _age_label(age_min: int | None) -> str:
    if age_min is None:
        return 'unknown'
    if age_min < 60:
        return f'{age_min}m'
    hours, minutes = divmod(age_min, 60)
    if minutes:
        return f'{hours}h {minutes}m'
    return f'{hours}h'


def _pack_generated_at(pack: dict[str, Any]) -> datetime | None:
    return _parse_dt_ist(pack.get('generated_at') or pack.get('package_generated_at'))


def _safe_log(line: str) -> None:
    try:
        from backend.utils.safe_stdio import safe_print

        safe_print(line, flush=True)
    except Exception:
        pass


def _is_fresh_postmarket_pack(pack: dict[str, Any], *, now: datetime | None = None) -> bool:
    if not pack or pack.get('ok') is not True:
        return False
    now = now or _now_ist()
    generated = _pack_generated_at(pack)
    if generated is None or generated.date() != now.date():
        return False
    age = _age_minutes(generated, now)
    if age is None or age > 24 * 60:
        return False
    pack_mode = str(pack.get('pack_mode') or pack.get('package_mode') or '').strip().lower()
    if pack_mode == 'postmarket':
        return True
    return (generated.hour, generated.minute) >= (15, 30)


def _postmarket_pack_cache_decision(
    pack: dict[str, Any],
    *,
    now: datetime | None = None,
    force_rebuild: bool = False,
    force_reason: str = 'force_learning_refresh',
) -> dict[str, Any]:
    now = now or _now_ist()
    generated = _pack_generated_at(pack)
    if force_rebuild:
        return {'action': 'rebuild', 'reason': force_reason, 'generated_at': generated}
    if not _is_fresh_postmarket_pack(pack, now=now):
        return {'action': 'rebuild', 'reason': 'not_fresh', 'generated_at': generated}
    refresh_at = _last_canonical_refresh_at()
    if (
        refresh_at is not None
        and generated is not None
        and refresh_at.astimezone(IST) > generated.astimezone(IST)
    ):
        return {
            'action': 'rebuild',
            'reason': 'refresh_after_pack',
            'generated_at': generated,
            'last_canonical_refresh_at': refresh_at,
        }
    current_version = _learning_pack_version()
    cached_version = str(pack.get('learning_pack_version') or '').strip()
    if cached_version != current_version:
        return {
            'action': 'reuse',
            'reason': 'version_changed',
            'generated_at': generated,
            'cached_learning_pack_version': cached_version,
            'learning_pack_version': current_version,
        }
    return {'action': 'reuse', 'reason': 'fresh', 'generated_at': generated}


def _format_pack_summary(pack: dict[str, Any]) -> list[str]:
    from backend.telegram.india_mode_lock import resolve_telegram_market_mode

    generated = pack.get('generated_at') or pack.get('package_generated_at') or 'unknown'
    summary = pack.get('summary') or {}
    mode = resolve_telegram_market_mode(
        pack_mode=pack.get('market_mode'),
        summary_mode=summary.get('market_mode'),
        active_mode=(pack.get('final_confidence') or {}).get('active_mode'),
    )
    lines = [
        '<b>Daily report pack</b>',
        f'Generated: {generated}',
        f'Market mode: {mode}',
    ]
    fc = pack.get('final_confidence') or {}
    if isinstance(fc, dict):
        lines.append(
            f"Final confidence - watch: {fc.get('watch', '?')} \u00b7 "
            f"avoid: {fc.get('avoid', '?')} \u00b7 entry_candidates: {fc.get('buy_candidate', '?')}"
        )
    return lines


def _fresh_postmarket_meta(pack: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    now = now or _now_ist()
    generated = _pack_generated_at(pack)
    age = _age_minutes(generated, now)
    report_line = f'Report: fresh \u00b7 {_age_label(age)}'
    try:
        from backend.analytics.unified_decision_engine import get_feed_freshness_meta

        current = get_feed_freshness_meta()
    except Exception:
        current = {'lines': {}}
    current_lines = current.get('lines') if isinstance(current, dict) else {}
    return {
        **(current if isinstance(current, dict) else {}),
        'report_age_min': age,
        'report_status': 'fresh',
        'report_stale': False,
        'report_suppressed': False,
        'lines': {
            **(current_lines if isinstance(current_lines, dict) else {}),
            'report': report_line,
        },
    }


def _run_safe_postmarket_pack_catchup_once() -> dict[str, Any]:
    try:
        from backend.scheduler.daily_report_pack_job import run_daily_report_pack_job

        result = run_daily_report_pack_job(
            mode='postmarket',
            limit=25,
            allow_runtime=True,
        )
        if result.get('generated') is True:
            return {'ok': True, 'method': 'daily_report_pack_job', 'result': result}
        warnings = result.get('warnings') or []
        reason = '; '.join(str(w) for w in warnings[:3]) or 'postmarket pack not generated'
        return {'ok': False, 'method': 'daily_report_pack_job', 'reason': reason, 'result': result}
    except Exception as exc:
        return {'ok': False, 'method': 'daily_report_pack_job', 'reason': str(exc)[:180]}


def _postmarket_close_pack_lines(
    *,
    force_rebuild: bool = False,
    force_reason: str = 'force_learning_refresh',
) -> tuple[list[str], bool, dict[str, Any]]:
    from backend.analytics.unified_decision_engine import (
        STALE_CLOSE_REPORT_NOTE,
        get_feed_freshness_meta,
        is_report_display_suppressed,
        stale_report_suppression_lines,
    )

    now = _now_ist()
    path = _daily_pack_path()
    pack = _load_json_file(path)
    previous_generated = _pack_generated_at(pack)
    catchup: dict[str, Any] = {}
    decision = _postmarket_pack_cache_decision(
        pack,
        now=now,
        force_rebuild=force_rebuild,
        force_reason=force_reason,
    )
    _safe_log(
        f"[CLOSE_PACK_CACHE] action={decision.get('action')} reason={decision.get('reason')}"
    )
    if decision.get('action') == 'rebuild':
        catchup = _run_safe_postmarket_pack_catchup_once()
        pack = _load_json_file(path)
    forced_rebuild_still_old = False
    if decision.get('reason') == 'force_after_hours_close':
        rebuilt_generated = _pack_generated_at(pack)
        forced_rebuild_still_old = (
            rebuilt_generated is None
            or (
                previous_generated is not None
                and rebuilt_generated.astimezone(IST) <= previous_generated.astimezone(IST)
            )
        )

    if _is_fresh_postmarket_pack(pack, now=now) and not forced_rebuild_still_old:
        generated = _pack_generated_at(pack)
        age = _age_minutes(generated, now)
        generated_label = generated.strftime('%Y-%m-%d %H:%M IST') if generated else 'unknown'
        generated_raw = generated.isoformat() if generated else str(pack.get('generated_at') or 'unknown')
        meta = _fresh_postmarket_meta(pack, now=now)
        _safe_log(f'[POSTMARKET_CLOSE_PACK] source=fresh generated_at={generated_raw}')
        lines = [
            f'Report: fresh \u00b7 {_age_label(age)}',
            f'Post-market pack generated at {generated_label}',
            *_format_pack_summary(pack),
            '',
        ]
        return lines, False, {
            'fresh': True,
            'pack': pack,
            'generated_at': generated_raw,
            'age_min': age,
            'freshness_meta': meta,
            'cache_action': decision.get('action'),
            'cache_reason': decision.get('reason'),
            'learning_pack_version': _learning_pack_version(),
        }

    try:
        meta = get_feed_freshness_meta()
    except Exception:
        meta = {'lines': {}}

    lines: list[str] = []
    if is_report_display_suppressed(meta=meta):
        lines.extend(stale_report_suppression_lines(meta=meta))
    else:
        report_line = (meta.get('lines') or {}).get('report')
        if report_line:
            lines.append(str(report_line))

    generated = _pack_generated_at(pack)
    pack_age = _age_minutes(generated, now)
    if pack_age is not None:
        lines.append(f'Report: stale \u00b7 {_age_label(pack_age)}')
    else:
        lines.append('Report: unavailable')
    lines.append(STALE_CLOSE_REPORT_NOTE)
    reason = str(catchup.get('reason') or 'fresh post-market pack not available')
    if forced_rebuild_still_old:
        reason = 'force_after_hours_close rebuild did not produce a newer pack'
    lines.append(f'Post-market pack unavailable - {reason}')
    lines.append('')
    _safe_log(f'[POSTMARKET_CLOSE_PACK] source=stale generated_at={pack.get("generated_at") or "unknown"}')
    return lines, True, {
        'fresh': False,
        'pack': pack,
        'freshness_meta': meta,
        'cache_action': decision.get('action'),
        'cache_reason': decision.get('reason'),
        'learning_pack_version': _learning_pack_version(),
    }


def _tradecard_resolution_line(counts: dict[str, Any]) -> str:
    resolved = (
        int(counts.get('T1') or 0)
        + int(counts.get('T2') or 0)
        + int(counts.get('SL') or 0)
        + int(counts.get('expired') or 0)
        + int(counts.get('ambiguous') or 0)
    )
    return (
        f"Tradecard resolution: no fill {int(counts.get('no_fill') or 0)} / "
        f"pending {int(counts.get('pending') or 0)} / resolved {resolved}"
    )


def _run_close_learning_refresh() -> dict[str, Any]:
    try:
        from backend.analytics.actual_learning_resolver import run_actual_learning_resolver
        from backend.storage.outcome_resolver import refresh_memory_dashboard_cache

        summary = run_actual_learning_resolver(refresh_cache=True)
        try:
            refresh_memory_dashboard_cache()
        except Exception:
            pass
    except Exception:
        summary = {
            'sample_updated': 0,
            'pending_data': 0,
            'pending_reasons': {'learning_refresh_error': 1},
        }
    reasons = summary.get('pending_reasons') if isinstance(summary.get('pending_reasons'), dict) else {}
    reason_summary = ','.join(f'{key}:{val}' for key, val in sorted(reasons.items())) or '-'
    _safe_log(
        f"[CLOSE_LEARNING_REFRESH] sample_updated={int(summary.get('sample_updated') or 0)} "
        f"pending_data={int(summary.get('pending_data') or 0)} reasons={reason_summary}"
    )
    return summary


def build_close_brief_text() -> str:
    from backend.telegram.india_mode_lock import (
        is_after_hours_phase,
        is_premarket_phase,
        resolve_telegram_market_phase,
    )

    if is_premarket_phase():
        return build_premarket_close_unavailable_text()
    market_phase = 'RESEARCH_MODE'
    try:
        market_phase = resolve_telegram_market_phase()
        if market_phase == 'RESEARCH_MODE':
            return _build_research_mode_close_brief_text()
    except Exception:
        pass

    from backend.telegram.lazy_command_runner import run_memory_only, run_market_only

    provisional = False
    try:
        from backend.telegram.india_mode_lock import is_live_market_hours_phase
        from backend.trading.unified_live_priority_engine import format_intraday_provisional_unified

        provisional = is_live_market_hours_phase()
        if provisional:
            tomorrow = format_intraday_provisional_unified()
        else:
            tomorrow = _build_today_tomorrow_text('tomorrow')
    except Exception:
        tomorrow = _build_today_tomorrow_text('tomorrow')

    lines = [
        '<b>🔔 Market close summary</b>',
    ]
    lines.append(f'Market mode: <code>{market_phase}</code>')
    close_resolution: dict[str, Any] = {}
    if not provisional:
        try:
            from backend.trading.tradecard_journal import resolve_close_pending_tradecards

            close_resolution = resolve_close_pending_tradecards(refresh=True)
        except Exception:
            close_resolution = {}
    learning_summary: dict[str, Any] = {}
    if not provisional:
        learning_summary = _run_close_learning_refresh()
    force_after_hours_close = (not provisional) and is_after_hours_phase(market_phase)

    pack_info: dict[str, Any] = {}
    if provisional:
        from backend.telegram.lazy_command_runner import run_daily_pack_only

        pack_res = run_daily_pack_only()
        report_suppressed = False
        try:
            from backend.analytics.unified_decision_engine import (
                STALE_CLOSE_REPORT_NOTE,
                get_feed_freshness_meta,
                is_report_display_suppressed,
                stale_report_suppression_lines,
            )

            meta = get_feed_freshness_meta()
            report_suppressed = is_report_display_suppressed(meta=meta)
            if report_suppressed:
                lines.extend(stale_report_suppression_lines(meta=meta))
                lines.append('')
            else:
                for key in ('report', 'scanner', 'news'):
                    line = (meta.get('lines') or {}).get(key)
                    if line:
                        lines.append(line)
                if meta.get('report_stale'):
                    lines.append(STALE_CLOSE_REPORT_NOTE)
        except Exception:
            report_suppressed = False

        if not report_suppressed:
            lines.extend([
                pack_res.get('text', ''),
                '',
            ])
    else:
        force_pack_rebuild = force_after_hours_close or int(close_resolution.get('updated') or 0) > 0
        force_reason = 'force_after_hours_close' if force_after_hours_close else 'force_learning_refresh'
        if force_after_hours_close:
            _safe_log('[TELEGRAM_CLOSE_FORCE_REBUILD] true reason=after_hours_close')
        pack_lines, _report_suppressed, pack_info = _postmarket_close_pack_lines(
            force_rebuild=force_pack_rebuild,
            force_reason=force_reason,
        )
        if force_after_hours_close:
            lines.append('Close cache: rebuilt \u00b7 reason=force_after_hours_close')
            lines.append(f'Learning version: {_learning_pack_version()}')
        lines.extend(pack_lines)
    try:
        from backend.trading.tradecard_journal import (
            format_tradecard_review_section,
            sample_and_resolve_pending_tradecards,
            summarize_today_outcomes,
        )

        if provisional:
            sample_and_resolve_pending_tradecards(
                expire_at_close=False,
                refresh=True,
            )
        lines.append(format_tradecard_review_section(provisional=provisional))
        if not provisional:
            counts = summarize_today_outcomes().get('counts') or {}
            lines.append(_tradecard_resolution_line(counts))
        lines.append('')
    except Exception:
        pass
    if not provisional:
        try:
            from backend.analytics.actual_learning_resolver import format_actual_learning_close_lines

            lines.extend(format_actual_learning_close_lines(learning_summary))
            lines.append('')
        except Exception:
            lines.append('Actual learning sample updated: 0')
            lines.append('')
    memory_res = run_memory_only()
    market_kwargs: dict[str, Any] = {}
    if not provisional and (pack_info.get('freshness_meta') or {}).get('lines'):
        market_kwargs['freshness_meta'] = pack_info.get('freshness_meta')
    try:
        market_res = run_market_only(**market_kwargs)
    except TypeError:
        market_res = run_market_only()
    market_text = market_res.get('text', '')
    stale_embedded = 'Report: stale' in str(market_text)
    top_source = 'fresh' if pack_info.get('fresh') else 'stale' if pack_info else 'live'
    internal_source = 'stale' if stale_embedded else 'fresh' if pack_info.get('fresh') else 'live'
    if not provisional:
        _safe_log(
            f'[CLOSE_PAYLOAD_SOURCE] top={top_source} internal={internal_source} '
            f'stale_embedded={str(stale_embedded).lower()}'
        )
    lines.extend([
        memory_res.get('text', ''),
        '',
        market_text,
        '',
        tomorrow,
    ])
    from backend.telegram.response_format import strip_stage_markers
    return strip_stage_markers('\n'.join(lines))


def build_overnight_brief_text() -> str:
    from backend.telegram.lazy_command_runner import run_global_only, run_news_only

    global_res = run_global_only()
    news_res = run_news_only(refresh=False)

    lines = [
        '<b>🌙 Overnight / global brief</b>',
        global_res.get('text', ''),
        '',
        news_res.get('text', ''),
    ]
    from backend.telegram.response_format import strip_stage_markers
    return strip_stage_markers('\n'.join(lines))


def build_premarket_reminder_text() -> str:
    return (
        '<b>⏰ Pre-market reminder</b>\n'
        'India session opening soon — review /today and /aihub scan before entries.'
    )


def build_close_watch_text() -> str:
    return (
        '<b>👀 Close-watch warning</b>\n'
        'Final hour — check /close candidates and avoid chasing late moves.'
    )


def _build_today_tomorrow_text(which: str) -> str:
    from backend.telegram.response_format import format_today_tomorrow

    return format_today_tomorrow(which)


BRIEF_BUILDERS: dict[str, Callable[[], str]] = {
    'morning': build_morning_brief_text,
    'close': build_close_brief_text,
    'overnight': build_overnight_brief_text,
    'premarket_reminder': build_premarket_reminder_text,
    'close_watch': build_close_watch_text,
}


def send_brief(slot: str, *, send_fn: Callable[[str], bool] | None = None) -> bool:
    builder = BRIEF_BUILDERS.get(slot)
    if not builder:
        return False
    from backend.telegram.response_format import strip_stage_markers

    text = strip_stage_markers(builder())
    try:
        from backend.orchestration.alert_quality_engine import evaluate_text_alert, record_text_alert_sent

        gate = evaluate_text_alert(f'brief_{slot}', text)
        if not gate.get('send'):
            return False
        record_text_alert_sent(f'brief_{slot}', gate)
    except Exception:
        pass
    if send_fn is None:
        from backend.telegram.telegram_analysis_bot import send_analysis_message

        return bool(send_analysis_message(text, command=f'brief_{slot}').get('sent'))
    return bool(send_fn(text))


def _active_slots() -> dict[str, tuple[int, int]]:
    slots = dict(CORE_SLOTS)
    if _env_truthy('TELEGRAM_BRIEF_OPTIONAL'):
        slots.update(OPTIONAL_SLOTS)
    return slots


def _due_slots(now: datetime) -> list[str]:
    due: list[str] = []
    for slot, (hour, minute) in _active_slots().items():
        if now.hour == hour and now.minute == minute and not _already_sent(slot, now):
            due.append(slot)
    return due


def _maybe_run_after_close_outcome_resolver(now: datetime) -> None:
    """Safe once-per-day resolver hook after Indian market close."""
    try:
        from datetime import timezone

        from backend.storage.outcome_resolver import run_after_close_outcome_resolver_if_due

        summary = run_after_close_outcome_resolver_if_due(now=now.astimezone(timezone.utc))
        if not summary.get('skipped'):
            print(
                '[TG_BRIEF] outcome_resolver '
                f"resolved_new={summary.get('resolved_new', 0)} "
                f"pending_after={summary.get('pending_after', 0)} "
                f"errors={summary.get('errors', 0)}",
                flush=True,
            )
        try:
            from backend.analytics.actual_learning_resolver import run_actual_learning_resolver

            learning = run_actual_learning_resolver(refresh_cache=True)
            print(
                '[TG_BRIEF] actual_learning '
                f"sample_updated={learning.get('sample_updated', 0)} "
                f"pending_data={learning.get('pending_data', 0)} "
                f"errors={learning.get('errors', 0)}",
                flush=True,
            )
        except Exception as exc:
            print(f'[TG_BRIEF] actual_learning hook failed: {exc}', flush=True)
    except Exception as exc:
        print(f'[TG_BRIEF] outcome_resolver hook failed: {exc}', flush=True)


def run_scheduler_loop(*, send_fn: Callable[[str], bool] | None = None, stop_event: threading.Event | None = None) -> None:
    stop = stop_event or threading.Event()
    while not stop.is_set():
        now = datetime.now(IST)
        for slot in _due_slots(now):
            try:
                send_brief(slot, send_fn=send_fn)
                _mark_sent(slot, now)
                if slot == 'close':
                    _maybe_run_after_close_outcome_resolver(now)
            except Exception as exc:
                print(f'[TG_BRIEF] {slot} failed: {exc}', flush=True)
        stop.wait(30)


def start_brief_scheduler(*, send_fn: Callable[[str], bool] | None = None) -> threading.Thread:
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_scheduler_loop,
        kwargs={'send_fn': send_fn, 'stop_event': stop_event},
        name='telegram_brief_scheduler',
        daemon=True,
    )
    thread._stop_event = stop_event  # type: ignore[attr-defined]
    thread.start()
    return thread
