"""
Shared Telegram analysis response formatting (Stage 45TG5).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')

RESEARCH_FOOTER = 'Research only. You decide and place trades manually.'
SHADOW_DISCLAIMER = RESEARCH_FOOTER
BLOCKED_TRADE_RESPONSE = (
    "I can't place orders. Try /today, /tomorrow, /aihub scan, or /ask ai <question>."
)
TRADE_EXECUTION_PERMANENTLY_DISABLED = True

_USER_BUY_SELL_RE = re.compile(r'\b(BUY|SELL)\b', re.IGNORECASE)


def sanitize_user_action_label(action: object) -> str:
    """Map internal decision tokens to user-safe labels — never naked BUY/SELL."""
    token = str(action or '').strip().upper().replace(' ', '_')
    if token in ('BUY_CANDIDATE', 'BUY'):
        return 'ENTRY CANDIDATE'
    if token in ('SELL_CANDIDATE', 'SELL'):
        return 'AVOID CANDIDATE'
    if token in ('PULLBACK_WATCH_ONLY', 'ENTRY_MISSED_WATCH'):
        return 'PULLBACK WATCH ONLY'
    if token == 'ENTRY_MISSED':
        return 'ENTRY MISSED — WAIT FOR RESET'
    return str(action or '—').replace('_', ' ')


def user_text_has_naked_buy_sell(text: str) -> bool:
    """True when user-facing text contains naked BUY/SELL outside allowed phrases."""
    cleaned = str(text or '')
    for allowed in (
        'No BUY/SELL',
        'never naked BUY/SELL',
        'not blind BUY/SELL',
        'no blind BUY/SELL',
        'No BUY/SELL — confirm manually',
    ):
        cleaned = cleaned.replace(allowed, '')
    if re.search(r'\bAction:\s*(BUY|SELL)\b', cleaned, re.I):
        return True
    if re.search(r'\b(confirmed|naked|blind)\s+(BUY|SELL)\b', cleaned, re.I):
        return True
    if 'No confirmed BUY candidate' in cleaned:
        return True
    if re.search(r'\b(buy_candidate|sell_candidate)\b', cleaned, re.I):
        return True
    return False

BLOCKED_TRADE_COMMANDS = frozenset({
    'buy', 'sell', 'execute', 'place_order', 'trade', 'auto_trade',
})

_FOOTER_PHRASES = (
    RESEARCH_FOOTER,
    'Shadow mode only — not trade execution.',
    'Shadow mode only - not trade execution.',
    'Trade execution permanently disabled.',
    'Blocked forever.',
)

_STAGE_MARKER_RE = re.compile(
    r'(TELEGRAM_STAGE|GUI_BUILD_STAGE|BACKEND_STAGE|QA_STAGE)[_\w]*',
    re.IGNORECASE,
)

AIHUB_FULL_TABS = (
    'brain', 'govt', 'scan', 'market', 'global', 'news', 'tv', 'calib', 'journal',
)

STALE_CACHE_HOURS = 24
TELEGRAM_INDIA_MODE_LOCK_STAGE = 'TELEGRAM_STAGE_48K_INDIA_MODE_LOCK'
TELEGRAM_FRESHNESS_CONSISTENCY_STAGE = 'TELEGRAM_STAGE_48K_FRESHNESS_CONSISTENCY'
DATA_ACCURACY_STAGE_MARKER = 'TELEGRAM_STAGE_45B4_DATA_ACCURACY_ACTION_PLAN'
ACTION_PLAN_STAGE_MARKER = 'TELEGRAM_STAGE_45B4_DATA_ACCURACY_ACTION_PLAN'
FINAL_POLISH_STAGE_MARKER = 'TELEGRAM_STAGE_45B5_FINAL_MESSAGE_POLISH'
MARKET_SUMMARY_CLARITY_STAGE_MARKER = 'TELEGRAM_STAGE_45B6_MARKET_SUMMARY_CLARITY'

_MARKET_STALE_WARNING_TOKENS = frozenset({
    'market_data_stale',
    'underlying_market_data_stale',
})

_EMPTY_BULLET_VALUES = frozenset({'', '—', '-', '–', 'null', 'none', 'undefined', 'n/a'})


def normalize_bullet_items(value: Any) -> list[str]:
    """Normalize why/wait fields — never iterate strings char-by-char."""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if ';' in text:
            return [part.strip() for part in text.split(';') if part.strip()]
        return [text]
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            out.extend(normalize_bullet_items(item))
        return out
    text = str(value).strip()
    return [text] if text else []


def format_cache_age_label(
    age_minutes: int,
    *,
    timestamp: str | None = None,
    stale_hours: int = STALE_CACHE_HOURS,
) -> str:
    """Human-readable cache age — fresh · Xm / stale · Xh / old cache · last report timestamp."""
    if age_minutes < 0:
        return 'unknown age'
    if age_minutes < 60:
        return f'fresh · {age_minutes}m'
    hours = age_minutes // 60
    return f'stale · {hours}h'


def file_timestamp_iso(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return mtime.replace(microsecond=0).isoformat()
    except OSError:
        return None


def format_memory_outcome_line(row: dict[str, Any]) -> str:
    ticker = str(row.get('ticker') or row.get('symbol') or '?').upper()
    outcome = (
        row.get('resolved_as')
        or row.get('outcome')
        or row.get('result')
        or row.get('status')
        or '—'
    )
    outcome_txt = str(outcome).upper()
    move = row.get('actual_move')
    if move is not None:
        try:
            return f'• {ticker} — {outcome_txt} — {float(move):+.2f}%'
        except (TypeError, ValueError):
            return f'• {ticker} — {outcome_txt} — {move}'
    return f'• {ticker} — {outcome_txt}'


def format_memory_win_rate(overall: dict[str, Any]) -> str:
    wins = int(overall.get('wins') or 0)
    losses = int(overall.get('losses') or 0)
    try:
        from backend.metrics.canonical_metrics import format_win_rate_display

        display = format_win_rate_display(wins, losses, min_sample=1)
        return str(display.get('win_rate_display') or '—')
    except Exception:
        win_rate = overall.get('win_rate')
        if isinstance(win_rate, (int, float)):
            pct = float(win_rate) * 100 if float(win_rate) <= 1 else float(win_rate)
            return f'{pct:.1f}%'
        if wins + losses > 0:
            return f'{(wins / (wins + losses)) * 100:.1f}%'
        return '—'


def resolve_global_risk_text(global_p: dict[str, Any]) -> str:
    summary = global_p.get('summary') or {}
    for key in ('global_risk', 'risk_tone', 'tone'):
        val = summary.get(key)
        if val is not None and str(val).strip() not in ('', '—', '-'):
            return str(val).strip()[:120]

    for row in global_p.get('items') or []:
        if not isinstance(row, dict):
            continue
        if str(row.get('classification') or '') == 'macro_context' and row.get('title'):
            return str(row['title']).strip()[:120]

    commodities = summary.get('commodity_impacts') or summary.get('commodities') or []
    if isinstance(commodities, list):
        parts: list[str] = []
        for row in commodities[:3]:
            if isinstance(row, dict):
                parts.append(f"{row.get('commodity', '?')}: {row.get('stance', 'WATCH')}")
        if parts:
            return ', '.join(parts)
    return 'No major global risk found in cache.'


def _is_empty_bullet_text(text: Any) -> bool:
    stripped = str(text or '').strip().lower()
    if not stripped:
        return True
    if stripped in _EMPTY_BULLET_VALUES:
        return True
    if stripped.startswith('{') or stripped.startswith('['):
        return True
    if "'bucket'" in stripped or '"bucket":' in stripped:
        return True
    return False


def filter_empty_bullets(items: list[str]) -> list[str]:
    """Drop bullets whose text is only dashes, null-like tokens, or raw JSON."""
    return [item for item in items if not _is_empty_bullet_text(item)]


def _market_has_stale_warnings(warnings: list[Any]) -> bool:
    tokens = {str(w).strip().lower() for w in (warnings or [])}
    return bool(tokens & _MARKET_STALE_WARNING_TOKENS)


def _aihub_payload_is_stale(payload: dict[str, Any], *, tab: str = '') -> bool:
    """True when AIHub tab cache should be labeled stale for Telegram."""
    summary = payload.get('summary') or {}
    if summary.get('stale') or summary.get('is_stale') or summary.get('market_stale'):
        return True
    age_sec = int(payload.get('cache_age_seconds') or 0)
    age_min = age_sec // 60
    stale_threshold_min = 1440 if tab in ('brain', 'govt', 'market') else 60
    if age_min >= stale_threshold_min:
        return True
    age_label = format_cache_age_label(age_min)
    return 'stale' in age_label or 'old cache' in age_label


def _aihub_tab_stale_message(tab: str) -> str:
    label = tab.capitalize() if tab != 'govt' else 'Govt'
    return f'{label} cache stale — run /refresh full'


def _stale_aihub_prefix_lines() -> list[str]:
    return [
        'Research cache · stale',
        'Use /refresh full for fresh closed-market research.',
    ]


def _append_manual_refresh_suggestion(lines: list[str]) -> None:
    """Append closed-market refresh hint once — avoids duplicate with stale prefix."""
    from backend.analytics.premarket_conviction import MANUAL_REFRESH_SUGGESTION

    if any(MANUAL_REFRESH_SUGGESTION in line for line in lines):
        return
    try:
        from backend.analytics.market_calendar_router import is_manual_refresh_suggested_mode

        if is_manual_refresh_suggested_mode():
            lines.append(f'<i>{MANUAL_REFRESH_SUGGESTION}</i>')
    except Exception:
        pass


def _aihub_full_calib_lines(
    cal: dict[str, Any],
    cal_summary: dict[str, Any],
) -> list[str]:
    """Calib section lines for /aihub full — never say 'no warnings' when unresolved or warming up."""
    from backend.analytics.unified_decision_engine import calibration_render_lines, get_calibration_mode

    lines = ['<b>📊 Calib</b>']
    mode = get_calibration_mode()
    calib_lines = calibration_render_lines()
    if mode == 'unresolved':
        lines.append('- live resolved: 0')
        lines.append('- historical resolved: 0')
        for line in calib_lines:
            lines.append(f'- {line.lower() if line[0].isupper() else line}')
        return lines
    if mode == 'warmup':
        for line in calib_lines:
            lines.append(f'- {line}')
        return lines
    for line in calib_lines:
        lines.append(f'- {line}')
    return lines


def _after_hours_today_banner() -> str | None:
    try:
        from backend.trading.unified_live_priority_engine import _is_postmarket_mode

        if _is_postmarket_mode():
            return None
    except Exception:
        pass
    from backend.telegram.india_mode_lock import is_after_hours_phase

    if is_after_hours_phase():
        return 'Market closed/after-hours — treat as research watchlist.'
    return None


def _global_item_display_label(row: dict[str, Any]) -> str:
    """Label global items — mark SpaceX/crypto-only noise unless India equity link."""
    title = str(row.get('label') or row.get('name') or row.get('title') or '—')[:120]
    try:
        from backend.orchestration.alert_quality_filters import is_scheduled_macro_noise

        is_noise, _reason = is_scheduled_macro_noise(title, row)
        if is_noise:
            return f'Global/Noise: {title[:100]}'
    except Exception:
        pass
    return title


def _news_item_display_label(row: dict[str, Any]) -> str:
    title = str(row.get('title') or row.get('headline') or '—')[:120]
    try:
        from backend.orchestration.alert_quality_filters import is_scheduled_macro_noise

        is_noise, _reason = is_scheduled_macro_noise(title, row)
        if is_noise:
            return f'Global/Noise: {title[:100]}'
    except Exception:
        pass
    return title


def _load_market_fallback_context() -> dict[str, Any]:
    """Watch/avoid/top-watch/risk counts from daily report pack and final confidence."""
    from backend.utils.config import DATA_DIR
    import json

    from backend.analytics.aihub_tab_payloads import _build_actionable_candidates

    pack_path = DATA_DIR / 'daily_report_pack_latest.json'
    fc_path = DATA_DIR / 'final_confidence_report.json'
    pack: dict[str, Any] = {}
    fc: dict[str, Any] = {}
    if pack_path.is_file():
        try:
            loaded = json.loads(pack_path.read_text(encoding='utf-8'))
            if isinstance(loaded, dict):
                pack = loaded
        except (OSError, json.JSONDecodeError):
            pack = {}
    if fc_path.is_file():
        try:
            loaded = json.loads(fc_path.read_text(encoding='utf-8'))
            if isinstance(loaded, dict):
                fc = loaded
        except (OSError, json.JSONDecodeError):
            fc = {}

    fc_pack = (pack.get('final_confidence') or {}) if pack else {}
    fc_merged = fc_pack if fc_pack else fc
    actionable = _build_actionable_candidates(pack, fc_merged) if pack else _build_actionable_candidates({}, fc_merged)

    tw = (pack.get('tomorrow_watchlist') or {}) if pack else {}
    summary = (pack.get('summary') or {}) if pack else {}

    watch_pool = actionable.get('watch_for_entry') or []
    avoid_pool = actionable.get('avoid') or []
    watch_count = int(tw.get('watch') or summary.get('watch') or fc_merged.get('watch') or len(watch_pool) or 0)
    avoid_count = int(tw.get('avoid') or summary.get('avoid') or fc_merged.get('avoid') or len(avoid_pool) or 0)

    top_watch: list[str] = []
    for row in watch_pool:
        if isinstance(row, dict):
            ticker = str(row.get('ticker') or row.get('symbol') or '').strip().upper()
            if ticker and ticker not in top_watch:
                top_watch.append(ticker)
    if not top_watch:
        for row in tw.get('top_watchlist') or tw.get('raw_candidates') or []:
            if isinstance(row, dict):
                ticker = str(row.get('ticker') or row.get('symbol') or '').strip().upper()
                if ticker and ticker not in top_watch:
                    top_watch.append(ticker)
    watch_split = format_watchlist_with_rejections(top_watch)
    top_watch = watch_split['clean']
    rejected_today = watch_split['rejected']

    risk_notes = pack.get('risk_notes') if pack else []
    risk_count = len(risk_notes) if isinstance(risk_notes, list) else 0

    from backend.telegram.india_mode_lock import resolve_telegram_market_mode

    mode = resolve_telegram_market_mode(
        pack_mode=pack.get('market_mode') if pack else None,
        summary_mode=summary.get('market_mode') if summary else None,
        active_mode=fc_merged.get('active_mode') if fc_merged else None,
        payload_mode=tw.get('market_mode') if tw else None,
    )

    has_data = bool(
        pack
        or fc_merged
        or watch_count
        or avoid_count
        or top_watch
        or risk_count
        or mode
    )
    return {
        'has_data': has_data,
        'mode': mode,
        'watch_count': watch_count,
        'avoid_count': avoid_count,
        'top_watch': top_watch[:5],
        'rejected_today': rejected_today[:5],
        'risk_notes_count': risk_count,
    }


def _market_useful_bullets(summary: dict[str, Any], items: list[Any]) -> list[str]:
    ctx_lines: list[str] = []
    india = summary.get('india_context') or summary.get('context') or {}
    if isinstance(india, dict) and india:
        ctx_lines.append(str(india.get('headline') or india.get('status') or ''))
    us_ctx = summary.get('us_context') or summary.get('global_context') or {}
    if isinstance(us_ctx, dict) and us_ctx:
        ctx_lines.append(str(us_ctx.get('headline') or us_ctx.get('status') or ''))
    bullets = filter_empty_bullets([f'• {txt[:120]}' for txt in ctx_lines if txt])
    if bullets:
        return bullets
    return _bullet_lines_from_rows(items, limit=6)


REJECTED_TODAY_DETAIL = 'live scanner rejection'

_BROKEN_REASON_SUFFIX_RE = re.compile(
    r'(?:\s|[_-])+(?:INFRA|SECTOR|BANK|TECH|AUTO|PHARMA|METAL|FMCG|IT|NBFC)[_\s-]*$',
    re.IGNORECASE,
)
_BROKEN_REASON_TAIL_RE = re.compile(r'(?:\s+\d{1,2}$|\s+[A-Z]{2,8}_$)')


def clean_avoid_reason_text(text: str, max_len: int = 180) -> str:
    """Trim avoid reasons to clean sentence boundaries — no partial words or junk suffixes."""
    raw = str(text or '').strip()
    if not raw:
        return 'Risk flagged'
    cleaned = re.sub(r'\s+', ' ', raw)
    cleaned = _BROKEN_REASON_SUFFIX_RE.sub('', cleaned).strip()
    cleaned = _BROKEN_REASON_TAIL_RE.sub('', cleaned).strip()
    if cleaned.endswith('_') or cleaned.endswith('-'):
        cleaned = cleaned.rstrip('_-').strip()
    if len(cleaned) <= max_len:
        return cleaned
    chunk = cleaned[:max_len]
    if ' ' in chunk:
        chunk = chunk.rsplit(' ', 1)[0]
    elif '.' in chunk:
        chunk = chunk.rsplit('.', 1)[0]
    chunk = chunk.strip(' ,;:-')
    if not chunk:
        chunk = cleaned[: max_len - 1].rsplit(' ', 1)[0].strip()
    return f'{chunk}…' if chunk else '…'


INTRADAY_ACTION_LABELS = frozenset({
    'WATCH FOR CONFIRMATION',
    'WAIT FOR VOLUME',
    'ENTRY MISSED',
    'PULLBACK WATCH',
    'RISK WATCH',
    'IGNORE LOW VOLUME',
    'AVOID',
})


def format_watchlist_with_rejections(
    watchlist: list[Any] | None,
    live_rejection_set: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """Split watchlist tickers into clean vs live-rejected buckets."""
    if live_rejection_set is None:
        from backend.analytics.unified_decision_engine import build_live_rejection_set

        registry = build_live_rejection_set()
    else:
        registry = live_rejection_set
    clean: list[str] = []
    rejected: list[str] = []
    for row in watchlist or []:
        if isinstance(row, dict):
            ticker = str(row.get('ticker') or row.get('symbol') or '').strip().upper()
        else:
            ticker = str(row or '').strip().upper()
        if not ticker or ticker == '?':
            continue
        if ticker in registry:
            if ticker not in rejected:
                rejected.append(ticker)
        elif ticker not in clean:
            clean.append(ticker)
    return {'clean': clean, 'rejected': rejected}


def format_watchlist_summary_lines(
    watchlist: list[Any] | None,
    *,
    top_prefix: str = '- top watchlist: ',
    rejected_prefix: str = '- rejected today: ',
    limit: int = 5,
    live_rejection_set: dict[str, str] | None = None,
) -> list[str]:
    split = format_watchlist_with_rejections(watchlist, live_rejection_set)
    lines = [f"{top_prefix}{', '.join(split['clean'][:limit]) if split['clean'] else '—'}"]
    if split['rejected']:
        lines.append(f"{rejected_prefix}{', '.join(split['rejected'][:limit])}")
    return lines


def format_journal_items_lines(
    items: list[Any] | None,
    *,
    prediction_count: int | None = None,
    item_limit: int = 6,
    live_rejection_set: dict[str, str] | None = None,
) -> list[str]:
    """Journal tab/detail lines — rejected tickers in a separate section."""
    split = format_watchlist_with_rejections(items, live_rejection_set)
    lines: list[str] = []
    if prediction_count is not None:
        lines.append(f'Journal predictions: {prediction_count}')
    for ticker in split['clean'][:item_limit]:
        lines.append(f'• {ticker}')
    if split['rejected']:
        lines.append('Rejected today:')
        for ticker in split['rejected'][:item_limit]:
            lines.append(f'• {ticker} — {REJECTED_TODAY_DETAIL}')
    return lines


def _split_top_watch_by_live_rejection(
    rows: list[Any],
    live_rejection_set: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    split = format_watchlist_with_rejections(rows, live_rejection_set)
    return split['clean'], split['rejected']


def _format_journal_watchlist_lines(
    top_watch: list[Any],
    live_rejection_set: dict[str, str] | None = None,
) -> list[str]:
    return format_watchlist_summary_lines(
        top_watch,
        top_prefix='- top watch: ',
        rejected_prefix='- rejected today: ',
        live_rejection_set=live_rejection_set,
    )


def _append_market_fallback_lines(lines: list[str], fallback: dict[str, Any]) -> None:
    if fallback.get('watch_count') is not None or fallback.get('avoid_count') is not None:
        lines.append(f"Watch: {fallback.get('watch_count', 0)} · Avoid: {fallback.get('avoid_count', 0)}")
    top_rows = fallback.get('top_watch') or []
    if top_rows:
        lines.extend(
            format_watchlist_summary_lines(
                top_rows,
                top_prefix='Top watch: ',
                rejected_prefix='Rejected today: ',
            )
        )
    elif fallback.get('rejected_today'):
        lines.append(f"Rejected today: {', '.join(fallback['rejected_today'])}")
    if fallback.get('risk_notes_count'):
        lines.append(f"Risk notes: {fallback['risk_notes_count']}")


def format_aihub_market_section(payload: dict[str, Any]) -> list[str]:
    """Structured /aihub market body — aligned with unified market freshness."""
    summary = payload.get('summary') or {}
    items = payload.get('items') or []
    warnings = payload.get('warnings') or []
    from backend.telegram.freshness_consistency import get_unified_market_freshness
    from backend.telegram.india_mode_lock import resolve_telegram_market_mode

    mode = resolve_telegram_market_mode(
        payload_mode=payload.get('market_mode'),
        summary_mode=summary.get('market_mode'),
    )
    fallback = _load_market_fallback_context()
    if not fallback.get('mode'):
        fallback = {**fallback, 'mode': mode}

    unified = get_unified_market_freshness()
    useful_bullets = _market_useful_bullets(summary, items)
    lines: list[str] = [unified.get('line', 'Market: unavailable')]

    if unified.get('is_fresh'):
        lines.append(f'Mode: {mode} · fresh')
        if useful_bullets:
            lines.extend(useful_bullets)
        elif fallback.get('has_data'):
            _append_market_fallback_lines(lines, fallback)
        return lines

    stale_warns = _market_has_stale_warnings(warnings) or unified.get('is_stale')
    if stale_warns:
        lines.append(f'Mode: {mode}')
        lines.append('Status: stale market snapshot')
        lines.append(f"Reason: {unified.get('reason') or 'underlying market data is old'}")
        if useful_bullets:
            lines.extend(useful_bullets)
        elif fallback.get('has_data'):
            _append_market_fallback_lines(lines, fallback)
        lines.append('Refresh: /news or scheduled market refresh')
        return lines

    if useful_bullets:
        stale_flag = (
            summary.get('stale')
            or summary.get('is_stale')
            or summary.get('market_stale')
            or summary.get('underlying_data_stale')
        )
        lines.append(f'Mode: {mode} · {"stale" if stale_flag else "fresh"}')
        lines.extend(useful_bullets)
        return lines

    if fallback.get('has_data'):
        lines.append(f'Mode: {mode}')
        _append_market_fallback_lines(lines, fallback)
        lines.append('Refresh: scheduled market refresh or /news')
        return lines

    lines.append('Market payload limited. Use /morning or /aihub full.')
    return lines


def _format_pct_display(val: Any) -> str | None:
    if val is None:
        return None
    try:
        pct = float(val)
        if pct <= 1:
            pct *= 100
        return f'{pct:.1f}%'
    except (TypeError, ValueError):
        return None


def format_calibration_rec_readable(rec: Any) -> str | None:
    """Single-line calibration note — never stringify raw dicts."""
    if isinstance(rec, str):
        txt = rec.strip()
        if _is_empty_bullet_text(txt):
            return None
        return f'• {txt[:120]}'
    if not isinstance(rec, dict):
        return None

    bucket = rec.get('bucket') or rec.get('score_bucket')
    rec_type = str(rec.get('type') or rec.get('action') or '').replace('_', ' ').strip()
    strength = str(rec.get('strength') or '').strip()
    message = rec.get('message') or rec.get('title') or rec.get('rationale') or rec.get('detail')

    if bucket:
        signal_parts = [
            p for p in (strength, rec_type)
            if p and p.lower() not in ('none', 'null', 'undefined')
        ]
        signal = ' '.join(signal_parts) if signal_parts else 'calibration note'
        return f'• {bucket} bucket — {signal} signal'

    if message and not _is_empty_bullet_text(str(message)):
        return f'• {str(message)[:120]}'
    return None


def _format_calibration_rec_detail(rec: Any) -> list[str]:
    """Multi-line calibration recommendation for /aihub calib."""
    if isinstance(rec, str):
        line = format_calibration_rec_readable(rec)
        return [line] if line else []
    if not isinstance(rec, dict):
        return []

    bucket = rec.get('bucket') or rec.get('score_bucket')
    rec_type = str(rec.get('type') or rec.get('action') or '').replace('_', ' ').strip()
    strength = str(rec.get('strength') or '').strip()
    if not bucket and not rec_type and not strength:
        line = format_calibration_rec_readable(rec)
        return [line] if line else []

    header_parts: list[str] = []
    if bucket:
        header_parts.append(f'Bucket {bucket}')
    if rec_type:
        header_parts.append(rec_type)
    if strength:
        header_parts.append(strength)
    lines = [f"• {' — '.join(header_parts)}"]

    win = _format_pct_display(rec.get('win_rate'))
    expected = _format_pct_display(rec.get('expected_win_rate'))
    if win and expected:
        lines.append(f'  Win rate: {win} · Expected: {expected}')
    elif win:
        lines.append(f'  Win rate: {win}')
    elif expected:
        lines.append(f'  Expected: {expected}')

    reason = rec.get('rationale') or rec.get('message') or rec.get('detail') or rec.get('reason')
    if reason and not _is_empty_bullet_text(str(reason)):
        lines.append(f'  Reason: {str(reason)[:100]}')
    return lines


def format_calibration_section_telegram(
    calibration: dict[str, Any] | None = None,
    final_confidence: dict[str, Any] | None = None,
    *,
    summary: dict[str, Any] | None = None,
    recommendations: list[Any] | None = None,
) -> str:
    """Structured calibration block for /aihub calib."""
    cal = calibration if isinstance(calibration, dict) else {}
    fc = final_confidence if isinstance(final_confidence, dict) else {}
    summ = summary if isinstance(summary, dict) else {}

    cal_summary = cal.get('summary') if isinstance(cal.get('summary'), dict) else summ
    live_block = cal.get('live') if isinstance(cal.get('live'), dict) else {}
    hist_block = cal.get('historical') if isinstance(cal.get('historical'), dict) else {}

    live_resolved = (
        cal_summary.get('live_resolved')
        or live_block.get('resolved')
        or cal.get('live_resolved')
    )
    hist_resolved = (
        cal_summary.get('historical_resolved')
        or hist_block.get('resolved')
        or cal.get('historical_resolved')
    )
    watch = fc.get('watch')
    avoid = fc.get('avoid')

    recs = recommendations
    if recs is None:
        recs = cal.get('recommendations') or cal_summary.get('calibration_recommendations') or []

    from backend.analytics.unified_decision_engine import calibration_render_lines, get_calibration_mode

    calib_mode = get_calibration_mode()
    calib_lines = calibration_render_lines()
    lines = ['<b>📊 Calibration</b>']
    if calib_mode == 'unresolved':
        lines.append('Live resolved: 0')
        lines.append('Historical resolved: 0')
        lines.extend(calib_lines)
        return '\n'.join(lines)

    if calib_mode == 'warmup':
        lines.extend(calib_lines)
        return '\n'.join(lines)

    lines.extend(calib_lines)
    if watch is not None:
        lines.append(f'Watch confidence: {watch}')
    if avoid is not None:
        lines.append(f'Avoid confidence: {avoid}')

    detail_lines: list[str] = []
    if isinstance(recs, list):
        for rec in recs[:5]:
            detail_lines.extend(_format_calibration_rec_detail(rec))

    if detail_lines:
        lines.append('Recommendations:')
        lines.extend(detail_lines)

    return '\n'.join(lines)


def _bullet_lines_from_rows(
    rows: list[Any],
    *,
    limit: int = 6,
    label_fn: Callable[[dict[str, Any]], str] | None = None,
) -> list[str]:
    bullets: list[str] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        if label_fn:
            text = label_fn(row)
        else:
            text = str(row.get('label') or row.get('title') or row.get('ticker') or row.get('headline') or '')
        if _is_empty_bullet_text(text):
            continue
        bullets.append(f'• {text[:140]}')
    return bullets


def strip_stage_markers(text: str) -> str:
    """Remove internal stage markers and repeated safety footers from outbound Telegram text."""
    body = str(text or '')
    body = re.sub(r'\uFFFD+', '', body).replace('��', '')
    body = re.sub(
        r'<code>\s*(TELEGRAM_STAGE|GUI_BUILD_STAGE|BACKEND_STAGE|QA_STAGE)[_\w]*\s*</code>\s*',
        '',
        body,
        flags=re.IGNORECASE,
    )
    body = _STAGE_MARKER_RE.sub('', body)
    lines: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append('')
            continue
        lower = stripped.lower()
        if any(phrase.lower() in lower for phrase in _FOOTER_PHRASES):
            continue
        if _STAGE_MARKER_RE.search(stripped):
            continue
        lines.append(line)
    while lines and not lines[-1].strip():
        lines.pop()
    return '\n'.join(lines).strip()


def _latest_tradecard_audit_for_ticker(ticker: object = '') -> dict[str, Any] | None:
    try:
        from backend.trading.tradecard_latest import find_latest_tradecard_audit

        return find_latest_tradecard_audit(ticker=str(ticker or '').strip().upper() or None)
    except Exception:
        return None


def _format_no_active_audit_watch_text(
    *,
    label: str,
    ticker: str,
    no_clean: bool = False,
) -> str:
    sym = str(ticker or '').strip().upper() or '—'
    lines = [f'<b>AstraEdge — {label}</b>', '']
    if no_clean:
        lines.extend([
            'No clean active watch yet.',
            f'Research-only watch: {sym} — confirm next session.',
        ])
    else:
        lines.extend([
            f'{sym} — NEXT-SESSION WATCH ONLY',
            'Reason: no active entry in current mode',
            'Plan: confirm after 09:20 with fresh price + volume',
        ])
    return strip_stage_markers('\n'.join(lines))


def with_shadow_disclaimer(text: str) -> str:
    """Legacy name — sanitizes only; no footer is appended."""
    return strip_stage_markers(text)


def format_blocked_trade_with_symbol(cmd: str, args: str) -> str:
    return BLOCKED_TRADE_RESPONSE


def format_aihub_menu() -> str:
    return (
        '<b>🧭 AI Hub menu</b>\n'
        'Tabs: brain · govt · scan · market · global · news · tv · calib · journal\n'
        'Use /aihub &lt;tab&gt; — e.g. /aihub scan\n'
        'Use /aihub full for the compact all-tabs summary'
    )


def _load_actionable() -> dict[str, Any]:
    from backend.utils.config import DATA_DIR
    import json
    from pathlib import Path

    pack_path = DATA_DIR / 'daily_report_pack_latest.json'
    fc_path = DATA_DIR / 'final_confidence_report.json'
    pack = {}
    fc = {}
    if pack_path.is_file():
        try:
            pack = json.loads(pack_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            pack = {}
    if fc_path.is_file():
        try:
            fc = json.loads(fc_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            fc = {}
    from backend.analytics.aihub_tab_payloads import _build_actionable_candidates

    return _build_actionable_candidates(pack if isinstance(pack, dict) else {}, fc)


def stock_decision_payload_ready(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict) or payload.get('ok') is not True:
        return False
    if payload.get('telegram_message'):
        return True
    top = payload.get('top_pick')
    return isinstance(top, dict) and bool(top.get('ticker'))


def format_stock_decision_payload(
    payload: dict[str, Any],
    mode: str,
    *,
    rebuilt: bool = False,
) -> str:
    from backend.analytics.railway_decision_bootstrap import (
        format_watchlist_fallback_telegram,
        rebuilt_cache_message,
    )

    normalized = 'today' if mode == 'today' else 'tomorrow'
    label = 'Today' if normalized == 'today' else normalized.capitalize()

    decision = payload.get('decision') or 'NO_CLEAN_CANDIDATE'
    top = payload.get('top_pick')
    if isinstance(top, dict):
        audit = _latest_tradecard_audit_for_ticker(top.get('ticker'))
        if audit:
            return _format_no_active_audit_watch_text(
                label=label,
                ticker=str(audit.get('ticker') or top.get('ticker') or ''),
                no_clean=decision == 'NO_CLEAN_CANDIDATE',
            )
    elif decision == 'NO_CLEAN_CANDIDATE':
        audit = _latest_tradecard_audit_for_ticker()
        if audit:
            return _format_no_active_audit_watch_text(
                label=label,
                ticker=str(audit.get('ticker') or ''),
                no_clean=True,
            )
    if decision == 'NO_CLEAN_CANDIDATE' and not top:
        return strip_stage_markers(format_watchlist_fallback_telegram(normalized, rebuilt=rebuilt))

    body = strip_stage_markers(str(payload.get('telegram_message') or ''))
    warnings = payload.get('snapshot_warnings') or []
    if warnings:
        prefix = '\n'.join(str(w) for w in warnings)
        body = f'{prefix}\n\n{body}' if body else prefix
    if normalized == 'today':
        banner = _after_hours_today_banner()
        if banner and banner not in body:
            body = f'{banner}\n\n{body}' if body else banner
    if rebuilt:
        prefix = f'<b>📋 {label}</b>\n\n{rebuilt_cache_message()}'
        if body.startswith('<b>AstraEdge'):
            body = body.split('\n', 1)[-1].lstrip('\n')
        return strip_stage_markers(f'{prefix}\n\n{body}')
    return body


def format_stock_decision_telegram(mode: str) -> str:
    from backend.analytics.railway_decision_bootstrap import (
        format_watchlist_fallback_telegram,
        load_cached_stock_decision,
        no_candidate_message,
        repair_decision_for_telegram,
    )
    from backend.analytics.stock_decision_engine import build_stock_decision

    normalized = 'today' if mode == 'today' else 'tomorrow'
    label = 'Today' if normalized == 'today' else normalized.capitalize()

    cached = load_cached_stock_decision(normalized)
    rebuilt = False
    used_fallback = False
    if cached:
        payload = cached
    else:
        _, rebuilt, used_fallback = repair_decision_for_telegram(normalized)
        if used_fallback:
            return strip_stage_markers(format_watchlist_fallback_telegram(normalized, rebuilt=rebuilt))
        payload = build_stock_decision(mode=normalized)
    try:
        from backend.analytics.unified_decision_engine import apply_live_guard_to_payload

        payload = apply_live_guard_to_payload(payload)
    except Exception:
        pass
    try:
        from backend.trading.unified_live_priority_engine import apply_unified_delegation_if_scanner_fresh

        payload = apply_unified_delegation_if_scanner_fresh(payload, mode=normalized)
    except Exception:
        pass
    if payload.get('ok') is not True:
        retry_cached = load_cached_stock_decision(normalized)
        if retry_cached:
            payload = retry_cached
            rebuilt = True
        else:
            raw = str(payload.get('message') or payload.get('error') or '')
            if 'final_confidence' in raw or 'warming' in raw.lower() or 'rebuilt' in raw.lower():
                from backend.analytics.railway_decision_bootstrap import decision_rebuilding_reply

                return f'<b>📋 {label}</b>\n{decision_rebuilding_reply(normalized)}'
            if rebuilt:
                return strip_stage_markers(format_watchlist_fallback_telegram(normalized, rebuilt=True))
            return f'<b>📋 {label}</b>\n{no_candidate_message()}'

    body = format_stock_decision_payload(payload, normalized, rebuilt=rebuilt)
    try:
        from backend.analytics.unified_decision_engine import (
            get_feed_freshness_meta,
            is_report_display_suppressed,
            stale_report_suppression_lines,
        )

        meta = get_feed_freshness_meta()
        if is_report_display_suppressed(meta=meta):
            prefix = '\n'.join(stale_report_suppression_lines(meta=meta))
            return strip_stage_markers(f'{prefix}\n\n{body}')
    except Exception:
        pass
    return body


def format_today_tomorrow(which: str) -> str:
    mode = 'today' if which == 'today' else 'tomorrow'
    return format_stock_decision_telegram(mode)


def format_why_ticker(ticker: str, *, mode: str = 'today') -> str:
    from backend.analytics.stock_decision_engine import lookup_ticker_in_decision

    result = lookup_ticker_in_decision(ticker, mode=mode)
    if result.get('ok') is not True:
        return f"Why lookup failed — {result.get('error') or result.get('message') or 'unknown'}."
    if not result.get('found'):
        return f"No decision data for <code>{ticker.upper()}</code> in latest {mode} payload."

    row = result.get('breakdown') or {}
    sym = row.get('ticker') or ticker.upper()
    action = sanitize_user_action_label(row.get('action'))
    lines = [
        f'<b>Why {sym}</b> ({mode})',
        f'Action: {action} · Score: {row.get("score", "—")} · Confidence: {row.get("confidence", "—")}',
        '',
        '<b>Why:</b>',
    ]
    for item in normalize_bullet_items(row.get('why')):
        lines.append(f'• {item}')
    if row.get('risk'):
        lines.extend(['', '<b>Risk:</b>'])
        for item in normalize_bullet_items(row.get('risk')):
            lines.append(f'• {item}')
    if row.get('confirmation_needed'):
        lines.extend(['', '<b>Wait for:</b>'])
        for item in normalize_bullet_items(row.get('confirmation_needed')):
            lines.append(f'• {item}')
    if row.get('invalid_if'):
        lines.extend(['', '<b>Invalid if:</b>'])
        for item in normalize_bullet_items(row.get('invalid_if')):
            lines.append(f'• {item}')
    supports = row.get('supports') or []
    if supports:
        lines.extend(['', f"Supports: {', '.join(str(s) for s in supports)}"])
    return strip_stage_markers('\n'.join(lines))


def _ticker_from_row(row: dict[str, Any]) -> str:
    return str(row.get('ticker') or row.get('symbol') or '?').upper()


def format_aihub_payload(tab: str, payload: dict[str, Any]) -> str:
    key = str(tab or '').strip().lower()
    summary = payload.get('summary') or {}
    items = payload.get('items') or []
    stale_cache = _aihub_payload_is_stale(payload, tab=key)
    tab_label = key.capitalize() if key != 'scan' else 'Scan'
    age_mins = int(payload.get('cache_age_seconds') or 0) // 60
    age_line = format_cache_age_label(age_mins)
    lines = [
        f'<b>AI Hub · {key}</b>',
        f"Source: {payload.get('source', '—')} · {tab_label} cache: {age_line}",
    ]
    if stale_cache and key in ('news', 'global', 'brain', 'govt', 'market'):
        lines.append(_aihub_tab_stale_message(key))
        if key in ('brain', 'govt', 'market') and age_mins >= 1440:
            lines.append('<i>Stale cached summary suppressed — refresh for current research.</i>')
            return strip_stage_markers('\n'.join(lines))
        lines.extend(_stale_aihub_prefix_lines()[1:])
    if key == 'brain':
        warn_tokens = {str(w) for w in (payload.get('warnings') or [])}
        if 'Runtime snapshot missing; using report cache.' in warn_tokens:
            lines.append('Runtime snapshot missing; using report cache.')
        _append_manual_refresh_suggestion(lines)
        stock_sd = summary.get('stock_decision_today') or {}
        top_pick = stock_sd.get('top_pick') if isinstance(stock_sd, dict) else None
        if isinstance(top_pick, dict) and top_pick.get('ticker'):
            action = str(top_pick.get('action') or '—').replace('_', ' ')
            lines.append(f"Today pick (cache): {top_pick.get('ticker')} — {action}")
        bullets = _bullet_lines_from_rows(
            items,
            limit=5,
            label_fn=lambda row: str(row.get('title') or row.get('summary') or row.get('text') or ''),
        )
        if bullets:
            lines.extend(bullets)
        else:
            lines.append('No useful cached item found.')
    elif key == 'scan':
        from backend.telegram.freshness_consistency import format_compact_freshness_line, scanner_cache_age_minutes

        scan_age = int(summary.get('scanner_cache_age_minutes') or scanner_cache_age_minutes())
        lines[1] = format_compact_freshness_line('Scanner', scan_age)
        lines.append(
            f"Live: {summary.get('live_scanner_count', 0)} · "
            f"watchlist: {summary.get('watchlist_count', 0)} · "
            f"memory: {summary.get('memory_signal_count', 0)}"
        )
        for row in items[:8]:
            if isinstance(row, dict):
                ticker = row.get('ticker') or '?'
                price = row.get('price')
                if price is not None:
                    try:
                        if float(price) <= 0:
                            continue
                    except (TypeError, ValueError):
                        pass
                lines.append(f"• {ticker} · {row.get('strength') or 'SIGNAL'}")
    elif key in ('news', 'tv'):
        for row in items[:8]:
            if isinstance(row, dict):
                title = _news_item_display_label(row) if key == 'news' else str(
                    row.get('title') or row.get('headline') or '—'
                )[:120]
                lines.append(f"• {title}")
        if not items:
            empty = summary.get('empty_message') or 'No cached items.'
            lines.append(str(empty))
    elif key == 'calib':
        fc = summary.get('final_confidence') or {}
        cal = summary.get('confidence_calibration') or {}
        calib_block = format_calibration_section_telegram(
            cal if isinstance(cal, dict) else {},
            fc if isinstance(fc, dict) else {},
            summary=summary,
            recommendations=summary.get('calibration_recommendations') or cal.get('recommendations'),
        )
        lines = [
            f'<b>AI Hub · {key}</b>',
            f"Source: {payload.get('source', 'cache')} · cache age: "
            f"{format_cache_age_label(int(payload.get('cache_age_seconds') or 0) // 60)}",
            calib_block,
        ]
    elif key == 'market':
        lines.extend(format_aihub_market_section(payload))
    elif key == 'global':
        risk = resolve_global_risk_text(payload)
        if risk and not _is_empty_bullet_text(risk):
            lines.append(f'Risk: {risk}')
        bullets = _bullet_lines_from_rows(
            items,
            limit=6,
            label_fn=lambda row: _global_item_display_label(row) if isinstance(row, dict) else '',
        )
        commodities = summary.get('commodity_impacts') or summary.get('commodities') or []
        if isinstance(commodities, list):
            for row in commodities[:4]:
                if isinstance(row, dict):
                    commodity = row.get('commodity') or row.get('name')
                    stance = row.get('stance') or row.get('impact')
                    if commodity and not _is_empty_bullet_text(str(commodity)):
                        bullets.append(f"• {commodity}: {stance or 'WATCH'}")
        bullets = filter_empty_bullets(bullets)
        if bullets:
            lines.extend(bullets)
        elif not (risk and not _is_empty_bullet_text(risk)):
            lines.append('No useful cached item found.')
    elif key == 'journal':
        hist = summary.get('history') or {}
        prediction_count = hist.get('count', len(items))
        lines.extend(format_journal_items_lines(items, prediction_count=prediction_count))
    else:
        bullets = _bullet_lines_from_rows(items, limit=6)
        if bullets:
            lines.extend(bullets)
        else:
            lines.append('No useful cached item found.')

    warnings = payload.get('warnings') or []
    if warnings:
        if key == 'market' and _market_has_stale_warnings(warnings):
            remaining = [
                w for w in warnings
                if str(w).strip().lower() not in _MARKET_STALE_WARNING_TOKENS
            ]
            warnings = remaining
        if warnings:
            lines.append(f"Warnings: {', '.join(str(w) for w in warnings[:4])}")
    return strip_stage_markers('\n'.join(lines))


def _aihub_full_section_stale(payload: dict[str, Any], tab: str) -> bool:
    return _aihub_payload_is_stale(payload, tab=tab)


def format_aihub_full(payloads: dict[str, dict[str, Any]]) -> str:
    lines = ['<b>🧭 AI Hub Full Summary</b>']

    brain = payloads.get('brain') or {}
    brain_summary = brain.get('summary') or {}
    brain_items = brain.get('items') or []
    actionable = brain_summary.get('actionable_candidates') or {}
    lines.append('<b>🧠 Brain</b>')
    if _aihub_full_section_stale(brain, 'brain'):
        lines.append(f"- {_aihub_tab_stale_message('brain')}")
    elif brain_items:
        row = brain_items[0]
        if isinstance(row, dict):
            sig = str(row.get('title') or row.get('summary') or row.get('text') or '—')[:120]
            lines.append(f'- {sig}')
    else:
        watch_n = len(actionable.get('watch_for_entry') or [])
        lines.append(f'- {watch_n} watch candidates' if watch_n else '- no brain signal cached')

    govt = payloads.get('govt') or {}
    govt_items = govt.get('items') or []
    govt_summary = govt.get('summary') or {}
    lines.append('<b>🏛 Govt</b>')
    if _aihub_full_section_stale(govt, 'govt'):
        lines.append(f"- {_aihub_tab_stale_message('govt')}")
    elif govt_items:
        row = govt_items[0]
        if isinstance(row, dict):
            lines.append(f"- {str(row.get('title') or row.get('headline') or row.get('summary') or '—')[:120]}")
    else:
        risk = govt_summary.get('top_risk') or govt_summary.get('policy_risk') or 'clean / no cached govt items'
        lines.append(f'- {risk}')

    scan = payloads.get('scan') or {}
    scan_summary = scan.get('summary') or {}
    scan_items = scan.get('items') or []
    live_scanner = scan.get('live_scanner') or []
    watchlist = scan.get('watchlist_candidates') or []
    lines.append('<b>📈 Scan</b>')
    lines.append(f"- live count: {scan_summary.get('live_scanner_count', len(live_scanner))}")
    scanner_names = [_ticker_from_row(r) for r in live_scanner[:3] if isinstance(r, dict)]
    if not scanner_names:
        scanner_names = [_ticker_from_row(r) for r in scan_items[:3] if isinstance(r, dict)]
    lines.append(f"- top scanner: {', '.join(scanner_names) if scanner_names else '—'}")
    lines.extend(format_watchlist_summary_lines(watchlist, limit=3))

    market = payloads.get('market') or {}
    market_summary = market.get('summary') or {}
    from backend.telegram.freshness_consistency import get_unified_market_freshness
    from backend.telegram.india_mode_lock import resolve_telegram_market_mode

    mode = resolve_telegram_market_mode(
        payload_mode=market.get('market_mode'),
        summary_mode=market_summary.get('market_mode'),
    )
    unified = get_unified_market_freshness()
    lines.append('<b>📊 Market</b>')
    if _aihub_full_section_stale(market, 'market'):
        lines.append(f"- {_aihub_tab_stale_message('market')}")
    else:
        lines.append(f"- {unified.get('line', 'Market: unavailable')}")
        lines.append(f"- mode: {mode} · {'fresh' if unified.get('is_fresh') else 'stale'}")
        india = market_summary.get('india_context') or market_summary.get('context') or {}
        us_ctx = market_summary.get('us_context') or market_summary.get('global_context') or {}
        if isinstance(india, dict) and india:
            lines.append(f"- India: {str(india.get('headline') or india.get('status') or '—')[:80]}")
        if isinstance(us_ctx, dict) and us_ctx:
            lines.append(f"- US: {str(us_ctx.get('headline') or us_ctx.get('status') or '—')[:80]}")

    global_p = payloads.get('global') or {}
    global_summary = global_p.get('summary') or {}
    lines.append('<b>🌐 Global</b>')
    risk = resolve_global_risk_text(global_p)
    lines.append(f'- top risk: {risk}')
    commodities = global_summary.get('commodity_impacts') or global_summary.get('commodities') or []
    if isinstance(commodities, list) and commodities:
        parts = []
        for row in commodities[:3]:
            if isinstance(row, dict):
                parts.append(f"{row.get('commodity', '?')}: {row.get('stance', 'WATCH')}")
        if parts:
            lines.append(f"- commodities: {', '.join(parts)}")

    news = payloads.get('news') or {}
    news_items = news.get('items') or []
    lines.append('<b>📰 News</b>')
    if news_items:
        for row in news_items[:3]:
            if isinstance(row, dict):
                lines.append(f"- {str(row.get('title') or row.get('headline') or '—')[:100]}")
    else:
        lines.append('- no cached headlines')

    tv = payloads.get('tv') or {}
    tv_items = tv.get('items') or []
    lines.append('<b>📺 TV</b>')
    if tv_items:
        for row in tv_items[:3]:
            if isinstance(row, dict):
                lines.append(f"- {str(row.get('title') or row.get('headline') or '—')[:100]}")
    else:
        lines.append('- empty')

    calib = payloads.get('calib') or {}
    cal_summary = calib.get('summary') or {}
    cal = cal_summary.get('confidence_calibration') or {}
    if isinstance(cal, dict) and cal.get('summary'):
        cal = cal.get('summary') or cal
    lines.extend(_aihub_full_calib_lines(cal if isinstance(cal, dict) else {}, cal_summary))

    journal = payloads.get('journal') or {}
    journal_summary = journal.get('summary') or {}
    journal_items = journal.get('items') or []
    top_watch = journal_summary.get('top_watch') or []
    failed = journal_summary.get('failed_strong_warnings') or []
    lines.append('<b>📜 Journal</b>')
    from backend.telegram.india_mode_lock import resolve_telegram_market_mode

    journal_mode = resolve_telegram_market_mode(
        payload_mode=journal.get('market_mode'),
        summary_mode=journal_summary.get('market_mode'),
    )
    lines.append(f'- mode: {journal_mode}')
    hist = journal_summary.get('history') or {}
    detail_rows = journal_items or top_watch
    if detail_rows:
        lines.extend(format_journal_items_lines(detail_rows, prediction_count=hist.get('count', len(journal_items))))
    else:
        lines.extend(_format_journal_watchlist_lines(top_watch))
    lines.append(f"- risk notes: {len(failed) if isinstance(failed, list) else 0}")

    lines.extend([
        '',
        'Use /today or /tomorrow for the short action list.',
    ])
    return strip_stage_markers('\n'.join(lines))


def _decision_short_instruction(payload: dict[str, Any]) -> str:
    if payload.get('ok') is not True:
        return str(payload.get('message') or 'Refresh reports for latest decision.')
    top = payload.get('top_pick')
    decision = payload.get('decision') or 'NO_CLEAN_CANDIDATE'
    if not top or decision == 'NO_CLEAN_CANDIDATE':
        return 'No clean candidate — review watchlist or wait for confluence.'
    action = sanitize_user_action_label(top.get('action'))
    ticker = top.get('ticker') or '—'
    if decision == 'BUY_CANDIDATE':
        return f'Monitor {ticker} ({action}) — confirm entry signals before acting.'
    return f'Watch {ticker} ({action}) — wait for confirmation, avoid chasing.'


def format_action_plan_telegram() -> str:
    """Compact action plan from stock decisions, brain payload, market/global, calibration."""
    from backend.analytics.aihub_tab_payloads import (
        build_brain_payload,
        build_global_payload,
        build_market_payload,
    )
    from backend.analytics.railway_decision_bootstrap import (
        load_cached_stock_decision,
        repair_decision_for_telegram,
    )
    from backend.analytics.stock_decision_engine import build_stock_decision
    from backend.telegram.lazy_command_runner import DAILY_PACK_FILE, _load_json

    today_payload, _, _ = repair_decision_for_telegram('today')
    tomorrow_payload, _, _ = repair_decision_for_telegram('tomorrow')

    today = today_payload if today_payload else load_cached_stock_decision('today')
    if not today or today.get('ok') is not True:
        today = build_stock_decision(mode='today')
    tomorrow = tomorrow_payload if tomorrow_payload else load_cached_stock_decision('tomorrow')
    if not tomorrow or tomorrow.get('ok') is not True:
        tomorrow = build_stock_decision(mode='tomorrow')

    try:
        from backend.analytics.unified_decision_engine import get_feed_freshness_meta
        from backend.trading.unified_live_priority_engine import apply_unified_delegation_if_scanner_fresh

        freshness_meta = get_feed_freshness_meta()
        today = apply_unified_delegation_if_scanner_fresh(
            today,
            mode='today',
            freshness_meta=freshness_meta,
        )
        tomorrow = apply_unified_delegation_if_scanner_fresh(
            tomorrow,
            mode='tomorrow',
            freshness_meta=freshness_meta,
        )
        freshness_lines = freshness_meta.get('lines') or {}
    except Exception:
        freshness_lines = {}

    brain = build_brain_payload()
    market = build_market_payload(force=False)
    global_p = build_global_payload()
    pack = _load_json(DAILY_PACK_FILE)

    from backend.telegram.india_mode_lock import resolve_telegram_market_mode

    market_summary = (market.get('summary') or {})
    mode = resolve_telegram_market_mode(
        payload_mode=market.get('market_mode'),
        summary_mode=market_summary.get('market_mode'),
        pack_mode=pack.get('market_mode') if pack else None,
        active_mode=(pack.get('final_confidence') or {}).get('active_mode') if pack else None,
    )
    if freshness_lines:
        market_state_lines = [
            'Market state: Research mode',
            freshness_lines.get('report', 'Report: unavailable'),
            freshness_lines.get('scanner', 'Scanner: unavailable'),
            freshness_lines.get('news', 'News: unavailable'),
            'Action: watch only, refresh before live entry.',
        ]
    else:
        stale_flag = market_summary.get('stale') or market_summary.get('is_stale')
        market_state_lines = [
            f'• Mode: {mode}',
            f'• Fresh/Stale: {"Stale" if stale_flag else "Fresh"}',
        ]

    main_risk = resolve_global_risk_text(global_p)

    brain_summary = brain.get('summary') or {}
    from backend.utils.config import DATA_DIR

    calib = {}
    calib_path = DATA_DIR / 'confidence_calibration_report.json'
    if calib_path.is_file():
        import json
        try:
            calib = json.loads(calib_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            calib = {}
    calib_recs = []
    for rec in (calib.get('recommendations') or [])[:3]:
        formatted = format_calibration_rec_readable(rec)
        if formatted:
            calib_recs.append(formatted)

    top = today.get('top_pick') if today.get('ok') else None
    decision = today.get('decision') if today.get('ok') else 'NO_CLEAN_CANDIDATE'
    action_warnings: list[str] = list(today.get('snapshot_warnings') or [])

    try:
        from backend.analytics.unified_decision_engine import note_snapshot_pick

        note_snapshot_pick('action_plan', (top or {}).get('ticker') if isinstance(top, dict) else None)
    except Exception:
        pass

    if (not top or decision == 'NO_CLEAN_CANDIDATE') and pack:
        actionable = (brain.get('summary') or {}).get('actionable_candidates') or {}
        buy_rows = actionable.get('buy_candidate') or []
        watch_rows = actionable.get('watch_for_entry') or actionable.get('watch') or []
        fallback_rows = [r for r in buy_rows + watch_rows if isinstance(r, dict)]
        if fallback_rows:
            from backend.analytics.unified_decision_engine import apply_live_guard_to_payload

            guarded = apply_live_guard_to_payload({
                'ok': True,
                'mode': 'today',
                'ranked_candidates': fallback_rows,
                'decision': decision,
            })
            top = guarded.get('top_pick')
            decision = guarded.get('decision') or decision
            action_warnings.extend(guarded.get('snapshot_warnings') or [])

    lines = [
        '<b>📌 AstraEdge Action Plan</b>',
        '',
    ]
    if action_warnings:
        for warn in dict.fromkeys(action_warnings):
            lines.append(str(warn))
        lines.append('')
    lines.extend([
        '<b>Market state:</b>',
        *market_state_lines,
        f'• Main risk: {main_risk}',
        '',
        '<b>Top candidate:</b>',
    ])

    if top and decision == 'BUY_CANDIDATE':
        action = sanitize_user_action_label(top.get('action'))
        lines.extend([
            f"• Ticker: {top.get('ticker', '—')}",
            f'• Action: {action}',
            f"• Score: {top.get('score', '—')}",
            f"• Confidence: {top.get('confidence', '—')}",
        ])
    elif top:
        action = sanitize_user_action_label(top.get('action') or 'WATCH_FOR_ENTRY')
        lines.append('No confirmed entry candidate. Best watch-for-entry is...')
        lines.extend([
            f"• Ticker: {top.get('ticker', '—')}",
            f'• Action: {action}',
            f"• Score: {top.get('score', '—')}",
            f"• Confidence: {top.get('confidence', '—')}",
        ])
    else:
        lines.extend([
            'No confirmed entry candidate. Best watch-for-entry is...',
            '• Ticker: —',
            '• Action: —',
            '• Score: —',
            '• Confidence: —',
        ])
        if decision == 'NO_CLEAN_CANDIDATE':
            lines.append('• No clean live candidate')

    lines.extend(['', '<b>Why:</b>'])
    why_items = normalize_bullet_items(top.get('why') if top else None)[:4]
    if why_items:
        for item in why_items:
            lines.append(f'• {item}')
    else:
        lines.append('• Review confluence sources before acting')

    lines.extend(['', '<b>Wait for:</b>'])
    wait_items = normalize_bullet_items(top.get('confirmation_needed') if top else None)[:4]
    if not wait_items:
        wait_items = normalize_bullet_items([
            'price confirmation',
            'volume confirmation',
            'market not stale',
        ])[:4]
    for item in wait_items:
        lines.append(f'• {item}')

    avoid_rows = today.get('avoid') or [] if today.get('ok') else []
    actionable = brain_summary.get('actionable_candidates') or {}
    if not avoid_rows:
        avoid_rows = actionable.get('avoid') or []
    lines.extend(['', '<b>Avoid:</b>'])
    if avoid_rows:
        for row in avoid_rows[:5]:
            if not isinstance(row, dict):
                continue
            reason = (row.get('risk') or row.get('why') or ['weak signal'])
            if isinstance(reason, list):
                reason = reason[0] if reason else 'weak signal'
            lines.append(f"• {row.get('ticker', '?')} — {clean_avoid_reason_text(str(reason))}")
    else:
        lines.append('• No avoid candidates flagged')

    lines.extend([
        '',
        '<b>Today:</b>',
        f'• {_decision_short_instruction(today)}',
        '',
        '<b>Tomorrow:</b>',
        f'• {_decision_short_instruction(tomorrow)}',
    ])

    failed = brain_summary.get('failed_strong_warnings') or []
    if calib_recs or failed:
        lines.append('')
        if calib_recs:
            lines.append('<b>Calibration:</b>')
            lines.extend(calib_recs)
        if failed and isinstance(failed[0], dict):
            fw = failed[0]
            lines.append(f"Warning: {fw.get('ticker', '?')} — {str(fw.get('message', ''))[:80]}")

    return strip_stage_markers('\n'.join(lines))


def format_aihub_brain_full() -> str:
    """Full brain view — 10 compact sections from brain payload and stock decision engine."""
    from backend.analytics.aihub_tab_payloads import build_brain_payload
    from backend.analytics.stock_decision_engine import _load_sources, build_stock_decision

    brain = build_brain_payload()
    today = build_stock_decision(mode='today')
    tomorrow = build_stock_decision(mode='tomorrow')
    sources = _load_sources()
    brain_summary = brain.get('summary') or {}

    market = sources.get('market') or {}
    market_summary = market.get('summary') or {}
    from backend.telegram.india_mode_lock import resolve_telegram_market_mode

    mode = resolve_telegram_market_mode(
        payload_mode=market.get('market_mode'),
        summary_mode=market_summary.get('market_mode'),
    )
    stale = 'Stale' if (market_summary.get('stale') or market_summary.get('is_stale')) else 'Fresh'
    global_p = sources.get('global') or {}
    risk = resolve_global_risk_text(global_p)
    intel = brain_summary.get('intelligence') or {}
    exec_summary = intel.get('executive_summary') or intel.get('summary') or ''

    lines = ['<b>🧠 AstraEdge Brain — Full</b>', '']
    _append_manual_refresh_suggestion(lines)
    if lines[-1]:
        lines.append('')

    lines.extend(['<b>1. Market read</b>', f'• Mode: {mode} · {stale}', f'• Risk: {risk}'])
    if exec_summary:
        lines.append(f'• {str(exec_summary)[:180]}')

    actionable = brain_summary.get('actionable_candidates') or {}
    buy_n = len(actionable.get('buy_candidate') or [])
    watch_n = len(actionable.get('watch_for_entry') or [])
    avoid_n = len(actionable.get('avoid') or [])
    fc = sources.get('final_confidence') or {}
    lines.extend([
        '',
        '<b>2. Actionability</b>',
        f'• Entry candidates: {buy_n} · Watch: {watch_n} · Avoid: {avoid_n}',
        f"• Active mode: {fc.get('active_mode') or '—'}",
    ])

    top = today.get('top_pick') if today.get('ok') else None
    lines.extend(['', '<b>3. Top candidate</b>'])
    if top:
        action = sanitize_user_action_label(top.get('action'))
        lines.append(
            f"• {top.get('ticker')} — {action} · score {top.get('score')} · {top.get('confidence')}"
        )
    else:
        lines.append('• No clean candidate in latest today decision')

    ranked = (today.get('ranked_candidates') or [])[:5] if today.get('ok') else []
    lines.extend(['', '<b>4. Ranked candidates</b>'])
    ranked_lines: list[str] = []
    if ranked:
        for row in ranked:
            if isinstance(row, dict):
                action = sanitize_user_action_label(row.get('action'))
                ticker = row.get('ticker')
                score = row.get('score')
                if ticker and not _is_empty_bullet_text(str(ticker)):
                    ranked_lines.append(f"• {ticker} — {action or 'watch'} · {score or '—'}")
    ranked_lines = filter_empty_bullets(ranked_lines)
    if ranked_lines:
        lines.extend(ranked_lines)
    else:
        lines.append('• No ranked candidates in latest today decision')

    lines.extend(['', '<b>5. Reasons/supports</b>'])
    if top:
        for w in normalize_bullet_items(top.get('why'))[:4]:
            lines.append(f'• {w}')
        supports = top.get('supports') or []
        if supports:
            lines.append(f"• Supports: {', '.join(str(s) for s in supports)}")
    else:
        lines.append('• Review /today for breakdown')

    lines.extend(['', '<b>6. Risks/blocks</b>'])
    risk_lines = 0
    if top:
        for r in normalize_bullet_items(top.get('risk'))[:4]:
            lines.append(f'• {r}')
            risk_lines += 1
    for fw in (brain_summary.get('failed_strong_warnings') or [])[:3]:
        if isinstance(fw, dict):
            lines.append(f"• {fw.get('ticker', '?')} — {str(fw.get('message', 'failed strong signal'))[:80]}")
            risk_lines += 1
    if not risk_lines:
        lines.append('• No major blocks flagged')

    calib = sources.get('calibration') or {}
    recs = calib.get('recommendations') or []
    lines.extend(['', '<b>7. Calibration</b>'])
    from backend.analytics.unified_decision_engine import calibration_render_lines, get_calibration_mode

    calib_mode = get_calibration_mode()
    calib_lines = calibration_render_lines()
    if calib_mode in ('unresolved', 'warmup', 'ready'):
        for line in calib_lines:
            lines.append(f'• {line}')
    else:
        lines.append('• Calibration unavailable — outcomes unresolved.')

    memory = sources.get('memory') or {}
    learning = memory.get('learning') or {}
    overall = learning.get('overall') or {}
    stats = memory.get('stats') or {}
    lines.extend([
        '',
        '<b>8. Memory learning</b>',
        f"• Win rate: {format_memory_win_rate(overall)} · W/L: {overall.get('wins', 0)}/{overall.get('losses', 0)}",
        f"• Predictions: {stats.get('predictions') or overall.get('total_predictions') or '—'}",
    ])

    broker = sources.get('broker') or {}
    our_vs = broker.get('our_vs_broker') or {}
    comparisons = our_vs.get('comparisons') or our_vs.get('rows') or []
    agree = sum(1 for r in comparisons if isinstance(r, dict) and r.get('agreement'))
    conflict = sum(1 for r in comparisons if isinstance(r, dict) and r.get('conflict'))
    lines.extend(['', '<b>9. Broker/external confluence</b>', f'• Agreement/conflict: {agree}/{conflict}'])
    shown = 0
    for row in comparisons[:3]:
        if isinstance(row, dict):
            ticker = row.get('ticker') or row.get('symbol') or '?'
            direction = row.get('direction') or row.get('broker_stance') or row.get('stance') or '—'
            lines.append(f'• {ticker} · {direction}')
            shown += 1
    if not shown:
        tw = sources.get('tomorrow_watchlist') or {}
        ext = tw.get('external_evidence') or tw.get('top_watchlist') or []
        for row in (ext if isinstance(ext, list) else [])[:2]:
            if isinstance(row, dict):
                lines.append(f"• {row.get('ticker') or row.get('symbol') or '?'} · external evidence")

    lines.extend(['', '<b>10. Confirmation checklist</b>'])
    if top:
        for c in normalize_bullet_items(top.get('confirmation_needed'))[:5]:
            lines.append(f'• {c}')
    else:
        lines.append('• Price/volume confirmation before entry')
        lines.append('• Market data fresh')

    tom_top = tomorrow.get('top_pick') if tomorrow.get('ok') else None
    if tom_top and tom_top.get('ticker') != (top or {}).get('ticker'):
        lines.append(f"• Tomorrow watch: {tom_top.get('ticker')} ({sanitize_user_action_label(tom_top.get('action'))})")

    return strip_stage_markers('\n'.join(lines))


def _parse_status_timestamp(value: Any) -> Optional[datetime]:
    """Parse ISO timestamps with +05:30, Z, or naive IST."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=IST)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _format_feed_freshness_line(label: str, path: Path, *, timestamp_key: str = '') -> str:
    """Format Latest <label>: timestamp · age <x> · fresh|stale (90m budget threshold)."""
    from backend.storage.data_paths import get_data_path
    from backend.telegram.freshness_consistency import format_budget_feed_freshness_line

    file_path = path if path.is_absolute() else get_data_path(str(path))
    return format_budget_feed_freshness_line(label, file_path, timestamp_key=timestamp_key)


def _format_static_theme_freshness_line(path: Path) -> str:
    try:
        if path.is_file():
            payload = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(payload, dict) and not payload.get('cache_refreshed_at'):
                return 'Legacy theme cache: static wishlist'
    except Exception:
        pass
    return _format_feed_freshness_line('Legacy theme cache', path)


def _format_aihub_cache_freshness_line(label: str, path: Path) -> str:
    from backend.telegram.freshness_consistency import format_compact_freshness_line

    if not path.is_file():
        return f'{label}: unavailable — cache file missing'
    try:
        age_min = max(0, int((datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) // 60))
    except OSError:
        return f'{label}: unavailable — cache timestamp unreadable'
    return format_compact_freshness_line(label, age_min)


def _format_runtime_snapshot_freshness_line(*, fallback_report_path: Path | None = None) -> str:
    from backend.storage.data_paths import get_data_path
    from backend.telegram.freshness_consistency import (
        compute_feed_age_minutes,
        format_compact_freshness_line,
    )

    candidates = (
        get_data_path('cache/runtime_snapshot.json'),
        get_data_path('runtime/current_snapshot.json'),
    )
    best_age: int | None = None
    for path in candidates:
        age, _ = compute_feed_age_minutes(path)
        if age < 0:
            continue
        if best_age is None or age < best_age:
            best_age = age
    if best_age is not None:
        return format_compact_freshness_line('Runtime snapshot', best_age)

    if fallback_report_path is not None:
        age, _ = compute_feed_age_minutes(fallback_report_path)
        if age >= 0:
            return format_compact_freshness_line('Runtime snapshot/report', age)
    return 'Runtime snapshot: unavailable'


def _format_optional_broker_freshness_line() -> str:
    return 'Broker: optional / not refreshed by full refresh'


def format_status_text() -> str:
    lines = ['<b>📡 Status</b>']
    telegram_enabled = False
    try:
        from backend.config.local_safe_mode import ASTRAEDGE_TELEGRAM_BUILD
        from backend.utils.config import IS_LOCAL_DEV, LOCAL_ONLY
        from backend.utils.telegram_guard import is_telegram_listener_enabled, is_telegram_send_enabled

        mode = 'local' if (LOCAL_ONLY or IS_LOCAL_DEV) else 'railway/production'
        lines.append(f'Mode: <code>{mode}</code>')
        lines.append(f'Telegram build: <code>{ASTRAEDGE_TELEGRAM_BUILD}</code>')
        listener_on = is_telegram_listener_enabled()
        sends_on = is_telegram_send_enabled()
        telegram_enabled = listener_on and sends_on
        lines.append(f'Telegram: {"enabled" if telegram_enabled else "disabled"}')
    except Exception:
        lines.append('Mode: unknown (config unavailable)')
        lines.append('Telegram: unknown')

    try:
        from backend.telegram.lazy_command_runner import DAILY_PACK_FILE, _load_json
        from backend.storage.data_paths import get_data_path

        pack = _load_json(DAILY_PACK_FILE)
        try:
            from backend.analytics.market_calendar_router import get_india_telegram_mode
            india_mode = get_india_telegram_mode()
            market_mode = india_mode.get('market_mode') or '—'
        except Exception:
            market_mode = '—'
        lines.append(f'Market mode: <code>{market_mode}</code>')

        if pack:
            summary = pack.get('summary') or {}
            if market_mode == '—':
                market_mode = (
                    pack.get('market_mode')
                    or summary.get('market_mode')
                    or (pack.get('final_confidence') or {}).get('active_mode')
                    or '—'
                )
                lines[-1] = f'Market mode: <code>{market_mode}</code>'
            lines.append('<b>Core runtime freshness</b>')
            lines.append(_format_runtime_snapshot_freshness_line(fallback_report_path=DAILY_PACK_FILE))
        else:
            lines.append('<b>Core runtime freshness</b>')
            lines.append(_format_runtime_snapshot_freshness_line(fallback_report_path=DAILY_PACK_FILE))

        lines.append(_format_feed_freshness_line('Latest scanner', get_data_path('scanner_data.json')))
        lines.append('<b>Intelligence freshness</b>')
        lines.append(_format_feed_freshness_line('Latest news', get_data_path('news_feed.json')))
        lines.append(_format_feed_freshness_line('Latest budget cache', get_data_path('budget_impact_cache.json')))
        lines.append(_format_feed_freshness_line(
            'Latest budget theme cache',
            get_data_path('budget_impact_cache.json'),
        ))
        legacy_theme_path = get_data_path('theme_baskets.json')
        if legacy_theme_path.is_file():
            lines.append(_format_static_theme_freshness_line(legacy_theme_path))
        lines.append(_format_aihub_cache_freshness_line('AIHub brain cache', get_data_path('cache/aihub_tabs/brain.json')))
        lines.append(_format_aihub_cache_freshness_line('AIHub govt cache', get_data_path('cache/aihub_tabs/govt.json')))
        lines.append(_format_aihub_cache_freshness_line('AIHub market cache', get_data_path('cache/aihub_tabs/market.json')))
        if DAILY_PACK_FILE.is_file():
            lines.append(_format_feed_freshness_line('Legacy report cache', DAILY_PACK_FILE))
        lines.append('<b>Optional</b>')
        lines.append(_format_optional_broker_freshness_line())
    except Exception:
        lines.append('Market mode: unavailable')
        lines.append('Latest report: unavailable')
        lines.append('Latest scanner: unavailable')
        lines.append('Latest news: unavailable')
        lines.append('Latest budget cache: unavailable')
        lines.append('Latest budget theme cache: unavailable')

    try:
        from backend.orchestration.alert_suppression_log import suppression_summary
        from backend.orchestration.alert_filters import get_telegram_alert_obs_summary

        sup = suppression_summary(limit=100)
        obs = get_telegram_alert_obs_summary()
        sent = obs.get('alerts_sent_today', 0) or sup.get('sent_count', 0)
        suppressed = obs.get('suppressed_today', 0) or sup.get('suppression_count', 0)
        alert_state = 'eligible' if telegram_enabled else 'disabled'
        lines.append('<b>Alerts</b>')
        lines.append(f"Alerts: {alert_state} · sent {sent} · suppressed {suppressed}")
        last_reason = sup.get('last_reason') or obs.get('last_suppression_reason')
        if last_reason:
            lines.append(f"Last suppression reason: {last_reason}")
        if sup.get('duplicate_alerts_avoided') or sup.get('ai_calls_avoided'):
            lines.append(
                f"Duplicate alerts avoided: {sup.get('duplicate_alerts_avoided', 0)} · "
                f"AI calls avoided: {sup.get('ai_calls_avoided', 0)}"
            )
    except Exception:
        pass

    try:
        from backend.telegram.lazy_command_runner import (
            E2E_REPORT,
            LIVE_SMOKE_REPORT,
            LOCAL_READINESS_REPORT,
            QA_REPORT_PATH,
            _cache_age_minutes,
            _load_json,
        )

        qa_sources = (
            ('telegram_qa', QA_REPORT_PATH),
            ('live_smoke', LIVE_SMOKE_REPORT),
            ('local_readiness', LOCAL_READINESS_REPORT),
            ('gui_e2e', E2E_REPORT),
        )
        qa_line = 'Last QA: no report cached'
        for label, path in qa_sources:
            qa = _load_json(path)
            if qa:
                status = (
                    'ok'
                    if qa.get('ok') is True or qa.get('ready') is True
                    else str(qa.get('status') or 'unknown')
                )
                age = _cache_age_minutes(path)
                age_txt = format_cache_age_label(age, timestamp=file_timestamp_iso(path))
                qa_line = f'Last QA: <code>{status}</code> · {label} ({age_txt})'
                break
        lines.append(qa_line)
    except Exception:
        lines.append('Last QA: unavailable')

    return strip_stage_markers('\n'.join(lines))


def classify_intraday_action_label(
    signal: dict[str, Any],
    *,
    registry: dict[str, str] | None = None,
) -> str:
    """Map scanner/intraday signal to allowed action label — never naked BUY/SELL."""
    from backend.analytics.unified_decision_engine import is_live_rejected

    ticker = str(signal.get('ticker') or signal.get('symbol') or '').upper()
    if ticker:
        rejected, _ = is_live_rejected(ticker, registry)
        if rejected:
            return 'AVOID'

    vol = float(signal.get('volume_ratio') or signal.get('participation') or 0)
    chg = abs(float(signal.get('change_percent') or 0))
    direction = str(signal.get('direction') or '').upper()

    if direction == 'BEARISH':
        return 'RISK WATCH'
    if vol < 0.5 and chg >= 3.0:
        return 'IGNORE LOW VOLUME'
    if vol < 0.8:
        return 'WAIT FOR VOLUME'
    if chg >= 6.5:
        return 'ENTRY MISSED'
    if chg >= 4.0:
        return 'PULLBACK WATCH'
    return 'WATCH FOR CONFIRMATION'


def format_intraday_anomaly_alert(
    signal: dict[str, Any],
    *,
    confidence: float = 0.0,
    registry: dict[str, str] | None = None,
    entry_status: str = '',
) -> str:
    """Structured intraday anomaly alert — ticker, move, volume, label, reason."""
    ticker = str(signal.get('ticker') or signal.get('symbol') or '?').upper()
    chg = float(signal.get('change_percent') or 0)
    vol = float(signal.get('volume_ratio') or signal.get('participation') or 0)
    label = classify_intraday_action_label(signal, registry=registry)
    conf_pct = f'{max(0.0, min(1.0, confidence)):.0%}' if confidence else '—'
    status = entry_status or label
    reason = clean_avoid_reason_text(
        str(signal.get('reason') or signal.get('detail') or signal.get('setup') or 'Scanner anomaly detected'),
        max_len=160,
    )
    missed_line = ''
    if label == 'ENTRY MISSED' or str(status).upper() == 'ENTRY MISSED':
        missed_line = '\nMissed — no chase. Waiting for pullback/retest.'
    return (
        f'<b>⚡ INTRADAY ALERT</b> <code>{ticker}</code>\n'
        f'<b>Move:</b> {chg:+.2f}%\n'
        f'<b>Volume/participation:</b> {vol:.1f}x\n'
        f'<b>Confidence:</b> {conf_pct}\n'
        f'<b>Action:</b> {label}\n'
        f'<b>Reason:</b> {reason}\n'
        f'<b>Entry status:</b> {status}'
        f'{missed_line}'
    )


def _normalize_tradecard_ticker(value: object) -> str:
    sym = str(value or '').strip().upper()
    if sym in _EMPTY_BULLET_VALUES or sym == 'NONE':
        return ''
    return sym


def _tradecard_unified_today_top() -> tuple[str, str]:
    """Unified /today top pick — tradecard must evaluate this name first."""
    try:
        from backend.trading.unified_live_priority_engine import build_unified_priority

        unified = build_unified_priority(mode='today')
        top = unified.get('top_pick')
        if isinstance(top, dict) and top.get('action') != 'AVOID':
            sym = _normalize_tradecard_ticker(top.get('ticker'))
            if sym:
                return sym, str(top.get('entry_status') or 'NO_ACTIVE_ENTRY')
    except Exception:
        pass
    return '', ''


def _tradecard_reviewed_fallback() -> tuple[str, str]:
    """Best reviewed ticker from unified priority when trade card has none."""
    try:
        from backend.trading.unified_live_priority_engine import build_unified_priority

        unified = build_unified_priority(mode='today')
        for row in (unified.get('missed_candidates') or []) + (unified.get('ranked_candidates') or []):
            if not isinstance(row, dict) or row.get('action') == 'AVOID':
                continue
            sym = _normalize_tradecard_ticker(row.get('ticker'))
            if not sym:
                continue
            if row.get('entry_missed') or row.get('entry_status') == 'ENTRY_MISSED':
                return sym, 'ENTRY_MISSED'
            entry_status = str(row.get('entry_status') or '').strip().upper()
            if entry_status in ('WAIT_FOR_PULLBACK', 'WAIT_FOR_VOLUME', 'NO_ACTIVE_ENTRY'):
                return sym, entry_status
            action = str(row.get('action') or '').strip().upper()
            if action == 'WATCH_FOR_ENTRY':
                return sym, 'WAIT'
            if action == 'BUY_CANDIDATE':
                return sym, 'VALID_ENTRY'
            return sym, 'NO_ACTIVE_ENTRY'
    except Exception:
        pass
    return '', ''


def _tradecard_postmarket_line() -> str:
    try:
        from backend.telegram.india_mode_lock import is_premarket_phase
        from backend.trading.unified_live_priority_engine import _is_postmarket_mode

        if is_premarket_phase():
            return ''
        if _is_postmarket_mode():
            return 'No live entry now. Next-session watch only.'
    except Exception:
        pass
    return ''


def _is_tradecard_premarket_phase() -> bool:
    try:
        from backend.telegram.india_mode_lock import is_premarket_phase

        return is_premarket_phase()
    except Exception:
        return False


def _format_tradecard_premarket_watch(
    ticker: str,
    *,
    explain: bool,
    freshness_meta: dict[str, Any] | None,
    card: dict[str, Any],
    effective_ticker: str,
) -> str:
    from backend.trading.trade_card_engine import resolve_tradecard_source_label
    from backend.trading.tradecard_refresh import format_freshness_line

    lines = [
        '<b>📋 TRADE CARD — PREMARKET WATCH</b>',
        f'<b>{ticker}</b> · <code>NO ACTIVE ENTRY</code>',
        'Reason: market not open for confirmed entry yet',
        'Plan: confirm after 09:20 with fresh price + volume',
    ]
    lines.append(resolve_tradecard_source_label(card, effective_ticker))
    freshness = format_freshness_line(freshness_meta)
    if freshness:
        lines.append(freshness)
    lines.append('Paper only.')
    if explain:
        lines.extend(_tradecard_explain_lines(
            variant='premarket',
            reason='market not open for confirmed entry yet',
        ))
    return strip_stage_markers('\n'.join(lines))


def _tradecard_status_label(status: str) -> str:
    normalized = str(status or 'NO_TRADE').strip().upper()
    if normalized == 'ENTRY_MISSED':
        return 'ENTRY_MISSED'
    if normalized in ('WAIT_FOR_PULLBACK', 'WAIT_FOR_VOLUME'):
        return 'WAIT'
    if normalized in ('NO_TRADE', 'AVOID'):
        return 'NO_ACTIVE_ENTRY'
    return normalized or 'NO_ACTIVE_ENTRY'


def _tradecard_explain_lines(
    *,
    variant: str,
    reason: str = '',
    card: dict[str, Any] | None = None,
) -> list[str]:
    """Standard Explain block — only appended for /tradecard explain."""
    lines = ['', '<b>Explain</b>']
    if variant == 'no_candidate':
        lines.extend([
            'Reason: no fresh candidate with valid entry',
            'Entry logic: no active entry',
            'Risk logic: no capital at risk',
            'Next action: wait for fresh scanner/catalyst',
        ])
    elif variant in ('entry_missed', 'no_active_entry', 'wait'):
        detail = reason or 'Strong move, but do not chase.'
        lines.extend([
            f'Reason: {detail}',
            'Entry logic: no active entry because entry is missed / stop too wide / market closed',
            'Risk logic: no trade until valid entry forms',
            'Next action: wait for pullback/retest or next-session confirmation',
        ])
    elif variant == 'premarket':
        lines.extend([
            'Reason: market not open for confirmed entry yet',
            'Entry logic: no active entry until session open + volume confirmation',
            'Risk logic: premarket levels are research-only',
            'Next action: confirm after 09:20 with fresh price + volume',
        ])
    elif variant == 'no_trade':
        lines.extend([
            f'Reason: {reason or "no valid entry on current card"}',
            'Entry logic: no active entry',
            'Risk logic: no capital at risk',
            'Next action: wait for fresh scanner/catalyst',
        ])
    elif variant == 'stale':
        lines.extend([
            'Reason: card cache stale for this session',
            'Entry logic: no active entry from stale cache',
            'Risk logic: do not act on stale levels',
            'Next action: run /refresh full or wait for fresh scanner',
        ])
    else:
        payload = card if isinstance(card, dict) else {}
        lines.extend([
            f'Reason: {reason or "—"}',
            f"Entry logic: entry zone {payload.get('entry_zone') or '—'} · stop {payload.get('stop_loss') or '—'}",
            f"Risk logic: invalid if {clean_avoid_reason_text(str(payload.get('invalid_if') or ''), max_len=120) or '—'}",
            f"Next action: {payload.get('exit_rule') or 'monitor paper plan manually'}",
        ])
    return lines


def _format_pinned_tradecard_from_latest(
    latest: dict[str, Any],
    *,
    explain: bool,
    freshness_meta: dict[str, Any] | None = None,
) -> str:
    """Format /tradecard explain from stored latest card — ticker/levels never change."""
    from backend.trading.trade_card_engine import resolve_tradecard_source_label
    from backend.trading.tradecard_latest import is_tradecard_audit_status, refresh_pinned_card_price
    from backend.trading.tradecard_refresh import format_freshness_line

    card = latest.get('card') if isinstance(latest.get('card'), dict) else latest
    ticker = str(latest.get('ticker') or card.get('ticker') or '').strip().upper()
    status = str(latest.get('status') or card.get('status') or 'VALID_ENTRY').strip().upper()
    display = refresh_pinned_card_price(card, ticker)
    reason = clean_avoid_reason_text(str(display.get('reason') or ''), max_len=200)
    postmarket_line = _tradecard_postmarket_line()
    audit_only = (
        bool(latest.get('audit_only'))
        or is_tradecard_audit_status(status)
        or str(display.get('entry_zone') or '').strip().upper() == 'NO ACTIVE ENTRY'
    )

    if audit_only:
        title = 'NEXT-SESSION WATCH' if status == 'NEXT_SESSION_WATCH' or display.get('after_hours') else 'NO ACTIVE ENTRY'
        status_label = 'NO ACTIVE ENTRY' if title == 'NEXT-SESSION WATCH' else _tradecard_status_label(status)
        lines = [
            f'<b>📋 TRADE CARD — {title}</b>',
            f'<b>{ticker}</b> · <code>{status_label}</code>',
        ]
        if explain:
            lines.extend([
                '',
                '<b>Explain</b>',
                f'Reason: {reason or "market closed/after-hours or research mode / market not open"}',
                'Entry logic: no active entry generated',
                'Risk logic: wait for next session confirmation after 09:20',
                'Next action: watch only; no paper entry until fresh market-hours confirmation',
            ])
        else:
            lines.extend([
                f'Reason: {reason or "market closed/after-hours or research mode / market not open"}',
                'Plan: confirm after 09:20 with fresh price + volume',
            ])
        if postmarket_line:
            lines.append(postmarket_line)
        lines.append(resolve_tradecard_source_label(display, ticker))
        freshness = format_freshness_line(freshness_meta)
        if freshness:
            lines.append(freshness)
        lines.append('Paper only.')
        return strip_stage_markers('\n'.join(lines))

    lines = [
        '<b>📋 TRADE CARD</b> <i>(paper only — research, not execution)</i>',
        f'<b>{ticker}</b> · <code>{status}</code>',
        f"Price: {display.get('current_price') or '—'}",
        f"Entry zone: {display.get('entry_zone') or '—'}",
        f"Stop: {display.get('stop_loss') or '—'} · T1: {display.get('target_1') or '—'} · T2: {display.get('target_2') or '—'}",
        f"R:R {display.get('risk_reward') or '—'} · Confidence: {display.get('confidence') or '—'}",
        f"Capital plan: {display.get('capital_plan') or 'Paper only.'}",
        f'Reason: {reason or "—"}',
        f"Invalid if: {clean_avoid_reason_text(str(display.get('invalid_if') or ''), max_len=120)}",
    ]
    if explain:
        lines.extend(_tradecard_explain_lines(variant='valid_entry', reason=reason, card=display))
    if postmarket_line:
        lines.append(postmarket_line)
    lines.append(resolve_tradecard_source_label(display, ticker))
    freshness = format_freshness_line(freshness_meta)
    if freshness:
        lines.append(freshness)
    lines.append('Paper only — you decide and place trades manually.')
    return strip_stage_markers('\n'.join(lines))


def format_tradecard_telegram(
    *,
    explain: bool = False,
    freshness_meta: dict[str, Any] | None = None,
    chat_id: str | None = None,
    pinned_latest: dict[str, Any] | None = None,
) -> str:
    """Format paper-only trade card for /tradecard commands."""
    if pinned_latest:
        return _format_pinned_tradecard_from_latest(
            pinned_latest,
            explain=explain,
            freshness_meta=freshness_meta,
        )

    from backend.trading.trade_card_engine import get_trade_card, is_trade_card_stale, resolve_tradecard_source_label
    from backend.trading.tradecard_latest import is_tradecard_audit_status, save_latest_tradecard
    from backend.trading.tradecard_refresh import format_freshness_line, is_tradecard_data_stale

    def _safe_float(value: object) -> float | None:
        try:
            if value in (None, '', '—'):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _persist_tradecard_journal(card_payload: dict[str, Any]) -> None:
        try:
            from backend.trading.tradecard_journal import persist_tradecard_generation

            if card_payload and card_payload.get('ticker'):
                persist_tradecard_generation(
                    card_payload,
                    freshness_meta=freshness_meta or {},
                    source_label=resolve_tradecard_source_label(
                        card_payload,
                        str(card_payload.get('ticker') or ''),
                    ),
                )
        except Exception:
            pass

    def _save_latest(
        card_payload: dict[str, Any],
        *,
        ticker: str,
        status: str,
        audit_only: bool = False,
    ) -> None:
        if chat_id and ticker:
            try:
                payload = dict(card_payload)
                payload['ticker'] = ticker
                payload['status'] = status
                save_latest_tradecard(
                    chat_id,
                    payload,
                    ticker=ticker,
                    status=status,
                    audit_only=audit_only,
                )
            except Exception:
                pass

    card = get_trade_card(rebuild=False)
    stale = is_trade_card_stale(card)
    data_stale = is_tradecard_data_stale(freshness_meta or {})
    postmarket_line = _tradecard_postmarket_line()

    def _append_freshness(lines: list[str]) -> None:
        line = format_freshness_line(freshness_meta)
        if line:
            lines.append(line)

    today_top, today_entry_status = _tradecard_unified_today_top()
    ticker = _normalize_tradecard_ticker(card.get('ticker'))
    if today_top and (not ticker or ticker != today_top):
        ticker = today_top

    fallback_ticker, fallback_status = ('', '')
    if not ticker:
        fallback_ticker, fallback_status = _tradecard_reviewed_fallback()
    elif today_top and ticker == today_top and today_entry_status:
        fallback_status = today_entry_status

    effective_ticker = ticker or fallback_ticker
    reason = clean_avoid_reason_text(str(card.get('reason') or ''), max_len=200)
    status = str(card.get('status') or 'NO_TRADE').strip().upper()
    if today_top and effective_ticker == today_top and today_entry_status:
        if today_entry_status != 'VALID_ENTRY' and today_entry_status in (
            'ENTRY_MISSED', 'WAIT_FOR_VOLUME', 'WAIT_FOR_PULLBACK', 'NO_ACTIVE_ENTRY', 'NO_TRADE',
        ):
            status = today_entry_status
        elif status in ('NO_TRADE', '—', ''):
            if today_entry_status != 'VALID_ENTRY':
                status = today_entry_status
    if not ticker and fallback_ticker and status in ('NO_TRADE', '—', ''):
        status = fallback_status or 'NO_ACTIVE_ENTRY'
    if 'stop too wide' in reason.lower() and status == 'VALID_ENTRY':
        status = 'NO_ACTIVE_ENTRY'

    if not reason and not effective_ticker:
        reason = 'no fresh candidate with valid entry'

    def _append_source(lines: list[str]) -> None:
        if effective_ticker:
            lines.append(resolve_tradecard_source_label(card, effective_ticker))

    if data_stale and effective_ticker:
        stale_reason = reason or 'quote/scanner refresh failed — cache too old for live entry'
        lines = [
            '<b>📋 TRADE CARD — DATA STALE / NO ACTIVE ENTRY</b>',
            f'<b>{effective_ticker}</b> · <code>NO ACTIVE ENTRY</code>',
            f'Reason: {stale_reason}',
            'Plan: wait for fresh quote + scanner before any paper entry',
        ]
        if postmarket_line:
            lines.append(postmarket_line)
        _append_freshness(lines)
        _append_source(lines)
        lines.append('Paper only.')
        if explain:
            lines.extend(_tradecard_explain_lines(variant='stale'))
        stale_card = dict(card)
        stale_card['reason'] = stale_reason
        _save_latest(stale_card, ticker=effective_ticker, status='NO_ACTIVE_ENTRY', audit_only=True)
        return strip_stage_markers('\n'.join(lines))

    if not effective_ticker:
        lines = [
            '<b>📋 TRADE CARD — NO TRADE</b>',
            'Ticker: NONE',
            f'Reason: {reason or "no fresh candidate with valid entry"}',
            'Plan: wait for next fresh scanner/catalyst',
        ]
        if postmarket_line:
            lines.append(postmarket_line)
        lines.append('Paper only.')
        _append_freshness(lines)
        if explain:
            lines.extend(_tradecard_explain_lines(variant='no_candidate'))
        return strip_stage_markers('\n'.join(lines))

    if stale:
        lines = [
            '<b>📋 TRADE CARD — RESEARCH ONLY / STALE</b>',
            f'<b>{effective_ticker}</b> · <code>{_tradecard_status_label(status)}</code>',
            'Card cache is stale for this session.',
            'Run /refresh full or wait for fresh scanner.',
        ]
        if postmarket_line:
            lines.append(postmarket_line)
        _append_source(lines)
        lines.append('Paper only — no order execution.')
        _append_freshness(lines)
        if explain:
            lines.extend(_tradecard_explain_lines(variant='stale'))
        if is_tradecard_audit_status(status):
            _save_latest(card, ticker=effective_ticker, status=status, audit_only=True)
        return strip_stage_markers('\n'.join(lines))

    if card.get('ok') is False and not ticker and fallback_ticker:
        lines = [
            '<b>📋 TRADE CARD — NO TRADE</b>',
            f'Top reviewed: <b>{fallback_ticker}</b>',
            f'Status: {_tradecard_status_label(fallback_status)}',
            f'Reason: {reason or "no valid entry on current card"}',
            'Plan: wait for next fresh scanner/catalyst',
        ]
        if postmarket_line:
            lines.append(postmarket_line)
        _append_source(lines)
        lines.append('Paper only.')
        _append_freshness(lines)
        if explain:
            lines.extend(_tradecard_explain_lines(variant='no_trade', reason=reason))
        return strip_stage_markers('\n'.join(lines))

    if _is_tradecard_premarket_phase() and effective_ticker and status != 'VALID_ENTRY':
        _save_latest(card, ticker=effective_ticker, status='NO_ACTIVE_ENTRY', audit_only=True)
        return _format_tradecard_premarket_watch(
            effective_ticker,
            explain=explain,
            freshness_meta=freshness_meta,
            card=card,
            effective_ticker=effective_ticker,
        )

    if status == 'NEXT_SESSION_WATCH' or (card.get('after_hours') and status != 'VALID_ENTRY'):
        lines = [
            '<b>📋 TRADE CARD — NEXT-SESSION WATCH</b>',
            f'<b>{effective_ticker}</b> · <code>NO ACTIVE ENTRY</code>',
            f"Reason: {reason or 'market closed/after-hours'}",
            'Plan: confirm next session after 09:20 with fresh price + volume',
        ]
        if postmarket_line:
            lines.append(postmarket_line)
        _append_source(lines)
        lines.append('Paper only.')
        _append_freshness(lines)
        if explain:
            lines.extend(_tradecard_explain_lines(variant='entry_missed', reason=reason or 'market closed/after-hours'))
        _save_latest(card, ticker=effective_ticker, status='NEXT_SESSION_WATCH', audit_only=True)
        return strip_stage_markers('\n'.join(lines))

    if status == 'NO_ACTIVE_ENTRY' and 'stop too wide' in reason.lower():
        lines = [
            '<b>📋 TRADE CARD — NO ACTIVE ENTRY</b>',
            f'<b>{effective_ticker}</b> · <code>NO ACTIVE ENTRY</code>',
            'Entry: NO ACTIVE ENTRY',
            f'Reason: {reason}',
            'Plan: wait for tighter setup or no trade.',
        ]
        if postmarket_line:
            lines.append(postmarket_line)
        _append_source(lines)
        lines.append('Paper only.')
        _append_freshness(lines)
        if explain:
            lines.extend(_tradecard_explain_lines(variant='entry_missed', reason=reason))
        _save_latest(card, ticker=effective_ticker, status='NO_ACTIVE_ENTRY', audit_only=True)
        return strip_stage_markers('\n'.join(lines))

    if status == 'ENTRY_MISSED' or status == 'NO_ACTIVE_ENTRY' or str(card.get('entry_zone') or '').strip().upper() == 'NO ACTIVE ENTRY':
        lines = [
            '<b>📋 TRADE CARD — NO ACTIVE ENTRY</b>',
            f'<b>{effective_ticker}</b> · <code>ENTRY_MISSED</code>',
            'Entry: NO ACTIVE ENTRY',
            f"Reason: {reason or 'Strong move, but do not chase.'}",
            'Plan: wait for pullback/retest — no chase.',
        ]
        if postmarket_line:
            lines.append(postmarket_line)
        _append_source(lines)
        lines.append('Paper only.')
        _append_freshness(lines)
        if explain:
            explain_variant = 'wait' if status in ('WAIT_FOR_PULLBACK', 'WAIT_FOR_VOLUME') else 'entry_missed'
            lines.extend(_tradecard_explain_lines(variant=explain_variant, reason=reason))
        audit_status = status if is_tradecard_audit_status(status) else 'NO_ACTIVE_ENTRY'
        _save_latest(card, ticker=effective_ticker, status=audit_status, audit_only=True)
        return strip_stage_markers('\n'.join(lines))

    if status in ('NO_TRADE', 'AVOID') or card.get('ok') is False:
        lines = [
            '<b>📋 TRADE CARD — NO TRADE</b>',
            f'Top reviewed: <b>{effective_ticker}</b>',
            f'Status: {_tradecard_status_label(status)}',
            f'Reason: {reason or "no valid entry on current card"}',
            'Plan: wait for next fresh scanner/catalyst',
        ]
        if postmarket_line:
            lines.append(postmarket_line)
        _append_source(lines)
        lines.append('Paper only.')
        _append_freshness(lines)
        if explain:
            lines.extend(_tradecard_explain_lines(variant='no_trade', reason=reason))
        _persist_tradecard_journal(card)
        return strip_stage_markers('\n'.join(lines))

    if status == 'VALID_ENTRY' and effective_ticker:
        from backend.trading.tradecard_journal import format_active_card_exists, get_active_valid_entry

        active = get_active_valid_entry(effective_ticker)
        if active:
            try:
                from backend.trading.tradecard_journal import get_active_valid_entry as _reload_active
                from backend.trading.tradecard_journal import track_active_tradecard_outcome

                track_active_tradecard_outcome(active, refresh=False, source='quote_refresh')
                active = _reload_active(effective_ticker) or active
            except Exception:
                pass
            active_card = {
                'ticker': effective_ticker,
                'status': 'VALID_ENTRY',
                'current_price': active.get('price_at_signal') or active.get('outcome_price'),
                'entry_zone': (
                    f"{active.get('entry_low')}–{active.get('entry_high')}"
                    if active.get('entry_low') is not None and active.get('entry_high') is not None
                    else '—'
                ),
                'stop_loss': active.get('stop'),
                'target_1': active.get('t1'),
                'target_2': active.get('t2'),
                'reason': active.get('reason') or 'active card tracking',
                'confidence': active.get('confidence') or '—',
            }
            lines = [format_active_card_exists(
                active,
                current_price=_safe_float(card.get('current_price')),
            )]
            _append_freshness(lines)
            _save_latest(active_card, ticker=effective_ticker, status='VALID_ENTRY')
            return strip_stage_markers('\n'.join(lines))

    lines = [
        '<b>📋 TRADE CARD</b> <i>(paper only — research, not execution)</i>',
        f'<b>{effective_ticker}</b> · <code>{status}</code>',
        f"Price: {card.get('current_price') or '—'}",
        f"Entry zone: {card.get('entry_zone') or '—'}",
        f"Stop: {card.get('stop_loss') or '—'} · T1: {card.get('target_1') or '—'} · T2: {card.get('target_2') or '—'}",
        f"R:R {card.get('risk_reward') or '—'} · Confidence: {card.get('confidence') or '—'}",
        f"Capital plan: {card.get('capital_plan') or 'Paper only.'}",
        f'Reason: {reason or "—"}',
        f"Invalid if: {clean_avoid_reason_text(str(card.get('invalid_if') or ''), max_len=120)}",
    ]
    if explain:
        lines.extend(_tradecard_explain_lines(variant='valid_entry', reason=reason, card=card))
    else:
        lines.append('Use /tradecard explain for full plan notes.')
    if postmarket_line:
        lines.append(postmarket_line)
    _append_source(lines)
    _append_freshness(lines)
    lines.append('Paper only — you decide and place trades manually.')
    _persist_tradecard_journal(card)
    journal_card = dict(card)
    journal_card['ticker'] = effective_ticker
    journal_card['status'] = status
    _save_latest(journal_card, ticker=effective_ticker, status=status)
    return strip_stage_markers('\n'.join(lines))
