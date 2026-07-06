"""
Lazy command runners for Telegram Analysis Bot (Stage 45TG3).

Each runner touches only its scope — never invokes the full local pipeline.
Uses cached payloads, scoped refresh helpers, and aihub_tab_payloads builders.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.storage.data_paths import get_data_path
from backend.utils.config import DATA_DIR

STAGE_MARKER = 'TELEGRAM_STAGE_51A_CANONICAL_REFRESH_STATUS'

CANONICAL_FULL_REFRESH_CACHE_LABELS: dict[str, str] = {
    'runtime_snapshot': 'Runtime snapshot',
    'latest_news': 'News',
    'budget': 'Budget',
    'theme_catalyst': 'Theme catalysts',
    'catalyst_radar': 'Catalysts',
    'aihub_brain': 'AIHub brain',
    'aihub_govt': 'AIHub govt',
    'aihub_market': 'AIHub market',
    'broker': 'Broker (optional/skipped)',
}

FULL_SNAPSHOT_SEQUENCE: tuple[str, ...] = (
    '/status',
    '/health',
    '/schedule',
    '/memory',
    '/broker',
    '/qa',
    '/news',
    '/catalysts today',
    '/radar',
    '/tradecards',
    '/tradecard',
    '/close',
)

FULL_SNAPSHOT_EXCLUDED: frozenset[str] = frozenset({
    '/bootstrap',
    '/refresh',
    '/refresh quick',
    '/refresh full',
    '/theme refresh',
    '/broker refresh',
})

FULL_SNAPSHOT_FORBIDDEN_ALIASES: frozenset[str] = frozenset({
    'full compact',
    '/full compact',
    'full refresh',
    '/full refresh',
    'snapshot full',
    '/snapshot full',
})

QA_REPORT_PATH = DATA_DIR / 'telegram_qa_status_latest.json'
LIVE_SMOKE_REPORT = DATA_DIR / 'live_system_smoke_latest.json'
LOCAL_READINESS_REPORT = DATA_DIR / 'local_system_readiness_latest.json'
E2E_REPORT = DATA_DIR / 'gui_e2e_latest.json'
DAILY_PACK_FILE = DATA_DIR / 'daily_report_pack_latest.json'
MEMORY_CACHE_FILE = get_data_path('market_memory_dashboard_cache.json')


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _cache_age_minutes(path: Path) -> int:
    if not path.is_file():
        return -1
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - mtime).total_seconds() // 60))
    except OSError:
        return -1


def _scoped_refresh(scope: str, *, dry_run: bool = False) -> dict[str, Any]:
    try:
        from scripts.refresh_local_intelligence import run_refresh_scoped

        return run_refresh_scoped(scope, dry_run=dry_run)
    except Exception as exc:
        return {'ok': False, 'scope': scope, 'error': str(exc)[:200]}


def _runner_result(scope: str, *, text: str = '', payload: dict | None = None, **extra: Any) -> dict[str, Any]:
    return {
        'ok': True,
        'scope': scope,
        'stage_marker': STAGE_MARKER,
        'generated_at': _now_iso(),
        'text': text,
        'payload': payload or {},
        **extra,
    }


def run_news_only(*, refresh: bool = True) -> dict[str, Any]:
    from backend.telegram.freshness_consistency import get_news_freshness_dual

    refresh_result = None
    if refresh:
        refresh_result = _scoped_refresh('news')

    from backend.analytics.aihub_tab_payloads import build_news_payload

    payload = build_news_payload()
    items = payload.get('items') or []
    dual = get_news_freshness_dual()
    lines = [
        '<b>📰 News summary</b>',
        dual.get('latest_line', 'Latest news cache: unavailable'),
        dual.get('report_line', 'Report news cache: unavailable'),
        f'Items: {len(items)}',
    ]
    for row in items[:8]:
        if isinstance(row, dict):
            title = str(row.get('title') or row.get('headline') or '—')[:120]
            source = str(row.get('source') or '—')
            lines.append(f"• {title} ({source})")
    if not items:
        lines.append('No cached news items — run scoped news refresh when collectors are available.')
    if refresh_result and not refresh_result.get('ok'):
        lines.append(f"Refresh note: {refresh_result.get('error') or refresh_result.get('news', 'partial')}")
    return _runner_result('news', text='\n'.join(lines), payload=payload, refresh=refresh_result)


def run_scan_only() -> dict[str, Any]:
    from backend.analytics.aihub_tab_payloads import build_scan_payload

    payload = build_scan_payload()
    summary = payload.get('summary') or {}
    lines = [
        '<b>📊 Scan payload</b>',
        f"Live scanner: {summary.get('live_scanner_count', 0)} · "
        f"watchlist: {summary.get('watchlist_count', 0)} · "
        f"memory: {summary.get('memory_signal_count', 0)}",
    ]
    for row in (payload.get('items') or [])[:8]:
        if not isinstance(row, dict):
            continue
        ticker = row.get('ticker') or '?'
        price = row.get('price')
        if price is not None:
            try:
                if float(price) <= 0:
                    continue
            except (TypeError, ValueError):
                pass
        direction = row.get('direction') or 'NEUTRAL'
        strength = row.get('strength') or 'SIGNAL'
        lines.append(f"• {ticker} · {strength} · {direction}")
    return _runner_result('scan', text='\n'.join(lines), payload=payload)


def run_market_only(*, force: bool = False, freshness_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    from backend.analytics.aihub_tab_payloads import build_market_payload

    from backend.telegram.india_mode_lock import resolve_telegram_market_mode

    payload = build_market_payload(force=force)
    summary = payload.get('summary') or {}
    mode = resolve_telegram_market_mode(
        payload_mode=payload.get('market_mode'),
        summary_mode=summary.get('market_mode'),
    )
    age_min = int(payload.get('cache_age_seconds') or 0) // 60
    if freshness_meta is None:
        from backend.analytics.unified_decision_engine import get_feed_freshness_meta

        meta = get_feed_freshness_meta()
    else:
        meta = freshness_meta
    freshness_lines = meta.get('lines') or {}
    lines = [
        '<b>📈 Market payload</b>',
        f'Mode: <code>{mode}</code>',
    ]
    for key in ('report', 'scanner', 'news'):
        line = freshness_lines.get(key)
        if line:
            lines.append(line)
    if not any(freshness_lines.get(k) for k in ('report', 'scanner', 'news')):
        from backend.telegram.response_format import format_cache_age_label

        lines.append(format_cache_age_label(age_min))
    ctx = summary.get('india_context') or summary.get('context') or {}
    if isinstance(ctx, dict) and ctx:
        lines.append(f"India: {str(ctx.get('headline') or ctx.get('status') or '—')[:120]}")
    us_ctx = summary.get('us_context') or summary.get('global_context') or {}
    if isinstance(us_ctx, dict) and us_ctx:
        lines.append(f"US/Global: {str(us_ctx.get('headline') or us_ctx.get('status') or '—')[:120]}")
    return _runner_result('market', text='\n'.join(lines), payload=payload)


def run_global_only() -> dict[str, Any]:
    from backend.analytics.aihub_tab_payloads import build_global_payload

    from backend.telegram.india_mode_lock import resolve_telegram_market_mode

    payload = build_global_payload()
    summary = payload.get('summary') or {}
    mode = resolve_telegram_market_mode(payload_mode=payload.get('market_mode'))
    lines = [
        '<b>🌍 Global / overnight</b>',
        f'Mode: {mode}',
    ]
    risk = summary.get('global_risk') or summary.get('risk_tone') or summary.get('tone')
    if risk:
        lines.append(f"Risk tone: {risk}")
    for row in (payload.get('items') or [])[:6]:
        if isinstance(row, dict):
            label = str(row.get('label') or row.get('name') or row.get('title') or '—')[:80]
            change = row.get('change_pct') or row.get('change_percent')
            if change is not None:
                lines.append(f"• {label}: {change}%")
            else:
                lines.append(f"• {label}")
    commodities = summary.get('commodity_impacts') or summary.get('commodities') or []
    if isinstance(commodities, list):
        for row in commodities[:4]:
            if isinstance(row, dict):
                lines.append(
                    f"• {row.get('commodity', '?')}: {row.get('stance', 'WATCH')}"
                )
    return _runner_result('global', text='\n'.join(lines), payload=payload)


def run_daily_pack_only() -> dict[str, Any]:
    from backend.analytics.unified_decision_engine import (
        get_feed_freshness_meta,
        is_report_display_suppressed,
        stale_report_suppression_lines,
    )

    meta = get_feed_freshness_meta()
    if is_report_display_suppressed(meta=meta):
        lines = ['<b>📦 Daily report pack</b>', *stale_report_suppression_lines(meta=meta)]
        return _runner_result('daily_pack', text='\n'.join(lines), payload={}, ok=False)

    pack = _load_json(DAILY_PACK_FILE)
    if not pack:
        return _runner_result(
            'daily_pack',
            text='No daily report pack cached. Run closed-market refresh or wait for scheduler.',
            payload={},
            ok=False,
        )
    from backend.telegram.india_mode_lock import resolve_telegram_market_mode

    generated = pack.get('generated_at') or pack.get('package_generated_at') or 'unknown'
    summary = pack.get('summary') or {}
    mode = resolve_telegram_market_mode(
        pack_mode=pack.get('market_mode'),
        summary_mode=summary.get('market_mode'),
        active_mode=(pack.get('final_confidence') or {}).get('active_mode'),
    )
    lines = [
        '<b>📦 Daily report pack</b>',
        f"Generated: {generated}",
        f'Market mode: {mode}',
    ]
    fc = pack.get('final_confidence') or {}
    if isinstance(fc, dict):
        lines.append(
            f"Final confidence — watch: {fc.get('watch', '?')} · "
            f"avoid: {fc.get('avoid', '?')} · entry_candidates: {fc.get('buy_candidate', '?')}"
        )
    return _runner_result('daily_pack', text='\n'.join(lines), payload=pack)


def run_memory_only(args: str = '') -> dict[str, Any]:
    raw = str(args or '').strip()
    lower = raw.lower()
    if lower.startswith('stock '):
        from backend.telegram.response_format import format_tradecard_memory_stock_telegram

        sym = raw.split(None, 1)[1].strip() if ' ' in raw else ''
        text = format_tradecard_memory_stock_telegram(sym)
        return _runner_result('memory', text=text, mode='tradecard_stock')
    if lower == 'latest':
        from backend.telegram.response_format import format_tradecard_memory_latest_telegram

        text = format_tradecard_memory_latest_telegram(limit=5)
        return _runner_result('memory', text=text, mode='tradecard_latest')
    if lower == 'stats':
        from backend.telegram.response_format import format_tradecard_memory_stats_telegram

        text = format_tradecard_memory_stats_telegram()
        return _runner_result('memory', text=text, mode='tradecard_stats')

    from backend.telegram.response_format import (
        format_cache_age_label,
        format_memory_outcome_line,
        format_memory_win_rate,
        file_timestamp_iso,
    )

    dashboard: dict[str, Any] = {}
    source = 'live'
    cached = _load_json(MEMORY_CACHE_FILE)
    if cached.get('ok') is True:
        dashboard = cached
        source = 'cache'
    else:
        try:
            from backend.analytics.market_memory_dashboard import get_market_memory_dashboard

            dashboard = get_market_memory_dashboard(limit=20)
        except Exception as exc:
            return _runner_result(
                'memory',
                text=f'Market memory unavailable: {str(exc)[:160]}',
                payload={},
                ok=False,
            )

    stats = dashboard.get('stats') or {}
    learning = dashboard.get('learning') or {}
    overall = learning.get('overall') or {}
    latest_outcomes = dashboard.get('latest_outcomes') or []
    try:
        from backend.analytics.market_memory_dashboard import filter_latest_outcomes_for_display

        latest_outcomes = filter_latest_outcomes_for_display(latest_outcomes, limit=20)
    except Exception:
        latest_outcomes = [row for row in latest_outcomes if isinstance(row, dict)]
    from backend.analytics.unified_decision_engine import get_calibration_mode
    from backend.storage.outcome_resolver import get_canonical_outcome_stats

    canonical = get_canonical_outcome_stats()
    predictions = int(canonical.get('predictions_tracked') or 0)
    outcomes = int(canonical.get('resolved_total') or 0)
    unresolved = int(canonical.get('pending_total') or 0)
    if predictions <= 0:
        predictions = int(stats.get('predictions') or overall.get('total_predictions') or 0)
    if unresolved <= 0 and predictions > outcomes:
        unresolved = predictions - outcomes
    cache_age_txt = format_cache_age_label(
        _cache_age_minutes(MEMORY_CACHE_FILE),
        timestamp=file_timestamp_iso(MEMORY_CACHE_FILE),
    )

    calib_mode = get_calibration_mode()
    sq_metrics = canonical
    lines = ['<b>🧠 Market memory</b>']
    if calib_mode == 'unresolved':
        from backend.analytics.unified_decision_engine import memory_outcome_status_lines, memory_outcome_warning

        resolver_lines = memory_outcome_status_lines(stats, overall)
        trust_line = memory_outcome_warning(stats, overall)
        block = [
            f'Predictions tracked: {predictions}',
            'Outcomes resolved: 0',
            f'Pending resolution: {unresolved if unresolved > 0 else predictions}',
        ]
        block.extend(resolver_lines)
        if trust_line:
            block.append(trust_line)
        elif not resolver_lines:
            block.append('Reason: awaiting close-price/outcome resolver or next market session')
        block.extend([
            'Source: cloud/runtime cache',
            f'Cache age: {cache_age_txt}',
            '',
            '<b>Latest outcomes:</b>',
            '• None resolved yet — memory is tracking predictions for the next session.',
        ])
        lines.extend(block)
    elif calib_mode == 'warmup':
        pending = int(sq_metrics.get('pending_total') or unresolved)
        lines.extend([
            f'Predictions tracked: {predictions}',
            'Calibration warming up — sample too small.',
            f'Resolved outcomes: {outcomes}',
            f'Pending outcomes: {pending}',
            'Hit rate: early sample only, do not trust yet.',
            f'Source: {source} · cache age: {cache_age_txt}',
            '',
            '<b>Latest outcomes:</b>',
        ])
        if latest_outcomes:
            for row in latest_outcomes[:3]:
                if isinstance(row, dict):
                    lines.append(format_memory_outcome_line(row))
        else:
            lines.append('• No recent outcomes in cache.')
    else:
        pending = int(sq_metrics.get('pending_total') or unresolved)
        hit_rate = sq_metrics.get('hit_rate')
        bull_rate = sq_metrics.get('bullish_hit_rate')
        bear_rate = sq_metrics.get('bearish_hit_rate')
        neutral = int(sq_metrics.get('neutral') or 0)
        last_resolved = sq_metrics.get('last_resolved_at') or '—'

        def _pct(val: float | None) -> str:
            if val is None:
                return '—'
            return f'{val * 100:.1f}'

        lines.extend([
            f'Predictions tracked: {predictions}',
            f'Resolved outcomes: {outcomes}',
            f'Pending outcomes: {pending}',
            f'Hit rate: {_pct(hit_rate)}%',
            f'Bullish hit rate: {_pct(bull_rate)}%',
            f'Avoid/rejection hit rate: {_pct(bear_rate)}%',
            f'Neutral count: {neutral}',
            f'Last resolved: {last_resolved}',
            f'Source: {source} · cache age: {cache_age_txt}',
            '',
            '<b>Latest outcomes:</b>',
        ])
        if latest_outcomes:
            for row in latest_outcomes[:3]:
                if isinstance(row, dict):
                    lines.append(format_memory_outcome_line(row))
        else:
            lines.append('• No recent outcomes in cache.')
    return _runner_result('memory', text='\n'.join(lines), payload=dashboard)


def format_outcomes_status_text() -> str:
    from backend.storage.outcome_resolver import get_canonical_outcome_stats

    stats = get_canonical_outcome_stats()
    last_run = stats.get('last_run') or 'none'
    return '\n'.join([
        '<b>Outcome resolver status</b>',
        f"resolved_total={int(stats.get('resolved_total') or 0)}",
        f"pending_total={int(stats.get('pending_total') or 0)}",
        f"skipped_missing_reference={int(stats.get('skipped_missing_reference') or 0)}",
        f"skipped_missing_evaluation={int(stats.get('skipped_missing_evaluation') or 0)}",
        f'last_run={last_run}',
        f"errors={int(stats.get('errors') or 0)}",
        f"data_root={stats.get('data_root') or 'unknown'}",
    ])


def run_resolve_outcomes_admin() -> dict[str, Any]:
    from backend.storage.outcome_resolver import run_outcome_resolver_once

    try:
        summary = run_outcome_resolver_once(refresh_cache=True)
    except Exception as exc:
        return _runner_result(
            'resolve_outcomes',
            text=(
                'OUTCOME_RESOLVER_RUN_OK\n'
                'pending_before=0\n'
                'resolved_new=0\n'
                'pending_after=0\n'
                'skipped_missing_reference=0\n'
                'skipped_missing_evaluation=0\n'
                f'errors=1\n'
                f'error_detail={str(exc)[:160]}'
            ),
            payload={},
            ok=False,
        )

    lines = [
        'OUTCOME_RESOLVER_RUN_OK',
        f"pending_before={int(summary.get('pending_before') or 0)}",
        f"resolved_new={int(summary.get('resolved_new') or 0)}",
        f"pending_after={int(summary.get('pending_after') or 0)}",
        f"skipped_missing_reference={int(summary.get('skipped_missing_reference') or 0)}",
        f"skipped_missing_evaluation={int(summary.get('skipped_missing_evaluation') or 0)}",
        f"errors={int(summary.get('errors') or 0)}",
    ]
    return _runner_result(
        'resolve_outcomes',
        text='\n'.join(lines),
        payload=summary,
        ok=int(summary.get('errors') or 0) == 0,
    )


def run_broker_only(*, refresh: bool = False, args: str = '') -> dict[str, Any]:
    refresh_result = None
    if refresh:
        refresh_result = _scoped_refresh('brokers')

    from backend.analytics.broker_prediction_intelligence import get_top_broker_display_candidates

    try:
        from backend.analytics.broker_intelligence import handle_broker_command

        if refresh and str(args or '').strip().lower() == 'refresh':
            from backend.analytics.broker_intelligence import refresh_broker_intelligence

            refresh_broker_intelligence(persist=True)
            text = handle_broker_command('refresh')
        elif args and str(args).strip():
            text = handle_broker_command(str(args).strip())
        else:
            text = handle_broker_command('')
    except Exception as exc:
        return _runner_result(
            'broker',
            text=f'Broker intelligence unavailable: {str(exc)[:160]}',
            payload={},
            ok=False,
        )

    display = get_top_broker_display_candidates(limit=8)
    pick_count = int(display.get('pick_count') or len(display.get('candidates') or []))
    payload = {
        'stats': {
            'picks_tracked': pick_count,
            'broker_predictions': pick_count,
            'display_origin': display.get('origin'),
        },
        'display': display,
    }

    if refresh_result and not refresh_result.get('ok') and 'Refresh note' not in text:
        text = f'{text}\nRefresh note: {refresh_result.get("error") or "partial"}'
    return _runner_result('broker', text=text, payload=payload, refresh=refresh_result)


def _read_qa_report(path: Path, label: str) -> dict[str, Any]:
    data = _load_json(path)
    if not data:
        return {
            'label': label,
            'status': 'no_report',
            'age_minutes': -1,
            'hint': f'Run QA and save report to {path.name}',
        }
    status = 'ok' if data.get('ok') is True or data.get('ready') is True else str(data.get('status') or 'unknown')
    return {
        'label': label,
        'status': status,
        'age_minutes': _cache_age_minutes(path),
        'detail': data.get('errors') or data.get('failures') or data.get('sections') or {},
    }


def run_qa_only(args: str = '') -> dict[str, Any]:
    from backend.qa.qa_runner import (
        explain_qa,
        format_qa_result,
        get_qa_status,
        load_last_qa_result,
        run_qa_full,
        run_qa_smoke,
    )

    raw = str(args or '').strip().lower()
    payload: dict[str, Any] = {}

    if raw == 'smoke':
        payload = run_qa_smoke()
        text = format_qa_result(payload)
    elif raw == 'full':
        payload = run_qa_full()
        text = format_qa_result(payload)
    elif raw == 'last':
        payload = load_last_qa_result() or {}
        if not payload:
            text = 'No QA run stored yet. Try /qa smoke or /qa full.'
        else:
            text = format_qa_result(payload, detail='last')
    elif raw == 'explain':
        text = explain_qa()
    elif raw:
        text = (
            'Unknown /qa subcommand.\n\n'
            f'{get_qa_status()}'
        )
    else:
        text = get_qa_status()

    return _runner_result('qa', text=text, payload=payload)


def run_qa_status_only() -> dict[str, Any]:
    """Backward-compatible alias for canonical /qa menu."""
    return run_qa_only('')


def run_aihub_full_only() -> dict[str, Any]:
    from backend.analytics.aihub_tab_payloads import build_aihub_tab_payload
    from backend.telegram.response_format import AIHUB_FULL_TABS, format_aihub_full

    payloads: dict[str, dict[str, Any]] = {}
    for tab in AIHUB_FULL_TABS:
        try:
            payloads[tab] = build_aihub_tab_payload(tab, force_refresh=False)
        except Exception as exc:
            payloads[tab] = {
                'ok': False,
                'tab': tab,
                'items': [],
                'summary': {},
                'warnings': [str(exc)[:120]],
            }
    text = format_aihub_full(payloads)
    return _runner_result('aihub_full', text=text, payload=payloads)


def run_action_plan_only() -> dict[str, Any]:
    from backend.telegram.response_format import ACTION_PLAN_STAGE_MARKER, format_action_plan_telegram

    text = format_action_plan_telegram()
    return _runner_result(
        'action_plan',
        text=text,
        stage_marker=ACTION_PLAN_STAGE_MARKER,
    )


def run_aihub_brain_full_only() -> dict[str, Any]:
    from backend.telegram.response_format import ACTION_PLAN_STAGE_MARKER, format_aihub_brain_full

    text = format_aihub_brain_full()
    return _runner_result(
        'aihub_brain_full',
        text=text,
        stage_marker=ACTION_PLAN_STAGE_MARKER,
    )


def run_theme_only(args: str = '') -> dict[str, Any]:
    from backend.analytics.theme_baskets import handle_theme_command

    text = handle_theme_command(args)
    return _runner_result('theme', text=text)


def run_budget_only(args: str = '') -> dict[str, Any]:
    from backend.analytics.budget_impact import handle_budget_command

    text = handle_budget_command(args)
    return _runner_result('budget', text=text)


def run_feed_text_only(args: str = '') -> dict[str, Any]:
    from backend.my_feed.feed_processor import ingest_text

    text_blob = str(args or '').strip()
    result = ingest_text(text_blob, source='telegram_text')
    return _runner_result('feed_text', text=result.get('reply') or 'MY_FEED_NEEDS_TEXT', payload=result)


def run_tradecard_only(args: str = '', *, chat_id: str | None = None) -> dict[str, Any]:
    from backend.telegram.response_format import format_tradecard_evidence_explain_telegram, format_tradecard_telegram
    from backend.trading.tradecard_journal import format_tradecard_journal_telegram, format_tradecard_outcome_telegram
    from backend.trading.tradecard_latest import (
        NO_LATEST_MESSAGE,
        is_latest_tradecard_expired,
        load_latest_tradecard,
    )
    from backend.trading.tradecard_refresh import (
        parse_tradecard_args,
        parse_tradecard_explain_ticker,
        refresh_tradecard_market_data,
    )

    force, explain, mode = parse_tradecard_args(args)
    explain_ticker = parse_tradecard_explain_ticker(args)
    effective_chat_id = chat_id or 'default'
    if mode == 'journal':
        text = format_tradecard_journal_telegram()
        return _runner_result('tradecard_journal', text=text)
    if mode == 'outcome':
        text = format_tradecard_outcome_telegram()
        return _runner_result('tradecard_outcome', text=text)
    if explain:
        if explain_ticker:
            freshness = refresh_tradecard_market_data(
                effective_chat_id,
                force=force,
                skip_card_rebuild=True,
            )
            text = format_tradecard_evidence_explain_telegram(
                explain_ticker,
                freshness_meta=freshness,
            )
            return _runner_result(
                'tradecard',
                text=text,
                payload={'freshness': freshness, 'ticker': explain_ticker},
                mode='explain',
            )
        latest = load_latest_tradecard(effective_chat_id)
        if not latest or is_latest_tradecard_expired(latest):
            return _runner_result('tradecard', text=NO_LATEST_MESSAGE, mode='explain')
        freshness = refresh_tradecard_market_data(
            effective_chat_id,
            force=force,
            skip_card_rebuild=True,
        )
        text = format_tradecard_telegram(
            explain=True,
            freshness_meta=freshness,
            pinned_latest=latest,
        )
        return _runner_result('tradecard', text=text, payload={'freshness': freshness}, mode='explain')
    freshness = refresh_tradecard_market_data(effective_chat_id, force=force)
    text = format_tradecard_telegram(
        explain=False,
        freshness_meta=freshness,
        chat_id=effective_chat_id,
    )
    return _runner_result('tradecard', text=text, payload={'freshness': freshness})


def run_radar_only(args: str = '') -> dict[str, Any]:
    from backend.telegram.response_format import format_opening_radar_telegram

    text = format_opening_radar_telegram()
    return _runner_result('radar', text=text)


def run_gainers_only(args: str = '') -> dict[str, Any]:
    from backend.telegram.response_format import format_all_cap_gainers_telegram

    text = format_all_cap_gainers_telegram()
    return _runner_result('gainers', text=text)


def run_tradecards_only(args: str = '') -> dict[str, Any]:
    from backend.telegram.response_format import format_tradecards_telegram

    text = format_tradecards_telegram()
    return _runner_result('tradecards', text=text)


def run_screener_only(args: str = '') -> dict[str, Any]:
    from backend.telegram.response_format import (
        format_screener_import_telegram,
        format_screener_latest_telegram,
        format_screener_status_telegram,
    )

    raw = str(args or '').strip().lower()
    if raw == 'status' or not raw:
        text = format_screener_status_telegram()
        return _runner_result('screener', text=text, mode='status')
    if raw == 'latest':
        text = format_screener_latest_telegram()
        return _runner_result('screener', text=text, mode='latest')
    if raw.startswith('import'):
        text = format_screener_import_telegram(str(args or '').strip())
        return _runner_result('screener', text=text, mode='import')
    text = format_screener_status_telegram()
    return _runner_result('screener', text=text, mode='status')


def run_longterm_only(args: str = '') -> dict[str, Any]:
    from backend.telegram.response_format import format_longterm_explain_telegram, format_longterm_telegram

    raw = str(args or '').strip()
    lower = raw.lower()
    if lower.startswith('explain '):
        sym = raw.split(None, 1)[1].strip() if ' ' in raw else ''
        text = format_longterm_explain_telegram(sym)
        return _runner_result('longterm', text=text, mode='explain')
    text = format_longterm_telegram()
    return _runner_result('longterm', text=text)


def run_patterns_only(args: str = '') -> dict[str, Any]:
    from backend.telegram.response_format import format_patterns_telegram

    sym = str(args or '').strip()
    text = format_patterns_telegram(sym)
    return _runner_result('patterns', text=text, mode='symbol' if sym else 'usage')


def run_candles_only(args: str = '') -> dict[str, Any]:
    from backend.telegram.response_format import format_candles_telegram

    sym = str(args or '').strip()
    text = format_candles_telegram(sym)
    return _runner_result('candles', text=text, mode='symbol' if sym else 'usage')


def run_catalysts_only(args: str = '') -> dict[str, Any]:
    from backend.intelligence.stock_catalyst_radar import format_catalyst_radar_telegram

    raw = str(args or '').strip()
    lower = raw.lower()
    if lower.startswith('explain '):
        ticker = raw.split(None, 1)[1].strip() if ' ' in raw else ''
        text = format_catalyst_radar_telegram(explain_ticker=ticker or None)
    elif lower in ('today',):
        text = format_catalyst_radar_telegram(today_only=True)
    else:
        text = format_catalyst_radar_telegram(today_only=False)
    return _runner_result('catalysts', text=text)


def run_myfeed_only(args: str = '') -> dict[str, Any]:
    from backend.my_feed.cache_invalidation import load_myfeed_items_for_telegram
    from backend.my_feed.feed_processor import archive_feed_item, scan_feed_summary
    from backend.my_feed.telegram_handlers import format_myfeed_list, format_myfeed_scan

    sub = str(args or '').strip().lower()
    if sub in ('', 'list'):
        items = load_myfeed_items_for_telegram(limit=12, force_refresh=True)
        text = format_myfeed_list(items, title='My Feed (latest)')
    elif sub == 'list all':
        items = load_myfeed_items_for_telegram(
            limit=12, force_refresh=True, include_archived=True,
        )
        text = format_myfeed_list(items, title='My Feed (all incl. archived)')
    elif sub == 'list verified':
        items = load_myfeed_items_for_telegram(
            limit=12, force_refresh=True, verification_filter='verified',
        )
        text = format_myfeed_list(items, title='My Feed (verified)')
    elif sub == 'list unverified':
        items = load_myfeed_items_for_telegram(
            limit=12, force_refresh=True, verification_filter='unverified',
        )
        text = format_myfeed_list(items, title='My Feed (unverified)')
    elif sub == 'today':
        from backend.my_feed.feed_processor import list_feed_items, sanitize_item_for_api

        items = [
            sanitize_item_for_api(row)
            for row in list_feed_items(limit=12, today_only=True)
        ]
        text = format_myfeed_list(items, title='My Feed (today)')
    elif sub == 'scan':
        summary = scan_feed_summary(today_only=False)
        text = format_myfeed_scan(summary)
    elif sub in ('clean-old', 'clean old'):
        from backend.my_feed.clean_old import clean_old_my_feed_items, format_clean_old_reply

        text = format_clean_old_reply(clean_old_my_feed_items(apply=True))
    elif sub.startswith('archive'):
        feed_id = sub.replace('archive', '', 1).strip()
        if not feed_id:
            text = 'Usage: /myfeed archive <feed_id>'
        elif archive_feed_item(feed_id):
            text = f'My Feed item archived: <code>{feed_id}</code>'
        else:
            text = f'My Feed item not found: <code>{feed_id}</code>'
    else:
        text = 'Usage: /myfeed list · /myfeed list verified · /myfeed list unverified · /myfeed list all · /myfeed today · /myfeed scan'
    return _runner_result('myfeed', text=text)


def format_canonical_status_text() -> str:
    """Canonical /status — same path as telegram_listener._cmd_status_body."""
    try:
        from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD
        from backend.runtime.runtime_state import get_runtime_state
        from backend.telegram.formatting.telegram_formatter import format_for_command, format_status
        from backend.trading.ist_clock import format_clock_status_lines

        rs = get_runtime_state(force_refresh=True)
        msg = format_for_command(format_status(rs), 'status')
        clock_block = '\n'.join(format_clock_status_lines())
        return f'{msg}\n\n<b>Clock</b>\n{clock_block}\nTelegram build: <code>{ASTRAEDGE_TELEGRAM_BUILD}</code>'
    except Exception as exc:
        from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD
        from backend.trading.ist_clock import format_clock_status_lines

        clock_block = '\n'.join(format_clock_status_lines())
        return (
            '<b>📡 System Status</b>\n'
            f'<i>Runtime state unavailable ({str(exc)[:80]})</i>\n\n'
            f'<b>Clock</b>\n{clock_block}\n'
            f'Telegram build: <code>{ASTRAEDGE_TELEGRAM_BUILD}</code>'
        )


def _format_cache_refresh_lines(cache_results: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for row in cache_results:
        if not isinstance(row, dict):
            continue
        name = str(row.get('cache') or '')
        label = CANONICAL_FULL_REFRESH_CACHE_LABELS.get(
            name,
            name.replace('_', ' ').title() or 'Cache',
        )
        status = str(row.get('status') or 'unknown')
        if status == 'rebuilt':
            status = 'rebuilt/fresh'
        lines.append(f'• {label}: {status}')
    return lines


def run_canonical_full_refresh(*, timeout_sec: int | None = None) -> dict[str, Any]:
    """Canonical /refresh full — intelligence cache refresh from telegram_listener."""
    import os
    import time

    timeout = timeout_sec or int(os.environ.get('TELEGRAM_REFRESH_TIMEOUT', '600'))
    started = time.time()
    deadline = started + timeout
    cache_results: list[dict[str, Any]] = []
    try:
        from backend.orchestration import telegram_listener as listener

        if hasattr(listener, '_invalidate_runtime_cache'):
            listener._invalidate_runtime_cache('telegram_analysis_refresh')
        cache_results = listener._refresh_intelligence_caches_for_full_refresh(deadline)
    except Exception as exc:
        cache_results = [{'cache': 'refresh', 'status': 'skipped', 'detail': str(exc)[:120]}]
    try:
        from backend.runtime.runtime_state import build_runtime_state

        build_runtime_state(force_refresh=True)
    except Exception:
        pass
    elapsed = int(time.time() - started)
    header = (
        '<b>✅ Full refresh complete</b>'
        if elapsed < timeout and cache_results
        else '<b>⏱️ Full refresh partial</b>'
    )
    lines = [
        header,
        f'Finished in {elapsed}s · canonical cache refresh',
        '',
        '<b>Caches</b>',
        *_format_cache_refresh_lines(cache_results),
        '<i>No restart or redeploy.</i>',
    ]
    return _runner_result(
        'refresh_full',
        text='\n'.join(lines),
        payload={'caches': cache_results, 'elapsed_sec': elapsed},
    )


def format_canonical_health_text() -> str:
    """Canonical /health for production analysis bot."""
    from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD
    from backend.trading.ist_clock import format_clock_status_lines

    lines = [
        '<b>🩺 Health</b>',
        'Active bot: <code>telegram_analysis_bot</code>',
        'Command router: <code>canonical</code>',
    ]
    try:
        from backend.storage.data_paths import data_preserved, get_data_root

        root = get_data_root()
        lines.append(f'Data root: <code>{root.as_posix()}</code>')
        lines.append(f"Data preserved: {'yes' if data_preserved() else 'check'}")
    except Exception as exc:
        lines.append(f'Status: degraded ({str(exc)[:80]})')
    lines.append(f'Telegram build: <code>{ASTRAEDGE_TELEGRAM_BUILD}</code>')
    lines.extend(['', '<b>Clock</b>'])
    lines.extend(format_clock_status_lines())
    return '\n'.join(lines)
