"""
Tradecard explain — AstraEdge 52P never-silent hotfix.

`/tradecard explain [SYMBOL]` is a read-mostly explanation command.
It must always return a Telegram-safe response and must not block on
unbounded scanner/price refresh (the production silent-hang root cause).
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable

from backend.utils.safe_stdio import safe_print

EXPLAIN_TOTAL_TIMEOUT_SEC = float(os.environ.get('TRADECARD_EXPLAIN_TIMEOUT_SEC', '25'))
EXPLAIN_REFRESH_TIMEOUT_SEC = float(os.environ.get('TRADECARD_EXPLAIN_REFRESH_TIMEOUT_SEC', '8'))
EXPLAIN_MAX_CHARS = 3900

REASON_CANDIDATE_NOT_FOUND = 'explain_candidate_not_found'
REASON_PAYLOAD_MISSING = 'explain_payload_missing'
REASON_REFRESH_TIMEOUT = 'explain_refresh_timeout'
REASON_EVIDENCE_FAILURE = 'explain_evidence_failure'
REASON_TRACE_FAILURE = 'explain_trace_failure'
REASON_RENDER_FAILURE = 'explain_render_failure'
REASON_LOOKUP_FAILURE = 'explain_lookup_failure'
REASON_TOTAL_TIMEOUT = 'explain_total_timeout'
REASON_UNKNOWN = 'explain_unknown_failure'
REASON_MALFORMED = 'explain_malformed_payload'


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes', 'on')


def explain_allow_bounded_refresh(*, force: bool = False) -> bool:
    """Optional bounded refresh only when force/fresh or explicit env opt-in."""
    if force:
        return True
    return _env_truthy('TRADECARD_EXPLAIN_ALLOW_REFRESH')


def log_explain_reason(code: str, *, ticker: str = '', detail: str = '') -> None:
    sym = str(ticker or '').strip().upper() or '-'
    extra = f' detail={str(detail or "")[:120]}' if detail else ''
    safe_print(f'[TRADECARD_EXPLAIN] reason={code} ticker={sym}{extra}', flush=True)


def format_explain_fallback(
    ticker: object,
    *,
    reason_code: str,
    latest_state: str = '',
    reason_text: str = '',
) -> str:
    """Deterministic user-facing fallback — never silent, never exposes internals."""
    sym = str(ticker or '').strip().upper() or 'UNKNOWN'
    reason_map = {
        REASON_CANDIDATE_NOT_FOUND: 'no matching current-session candidate was found.',
        REASON_PAYLOAD_MISSING: 'candidate explanation payload was missing.',
        REASON_REFRESH_TIMEOUT: 'candidate explanation timed out while reading live data.',
        REASON_TOTAL_TIMEOUT: 'candidate explanation timed out while reading live data.',
        REASON_EVIDENCE_FAILURE: 'evidence matrix was temporarily unavailable.',
        REASON_TRACE_FAILURE: 'decision trace was temporarily unavailable.',
        REASON_RENDER_FAILURE: 'explanation formatting failed.',
        REASON_LOOKUP_FAILURE: 'candidate lookup failed.',
        REASON_MALFORMED: 'stored candidate payload was incomplete.',
        REASON_UNKNOWN: 'explanation temporarily unavailable.',
    }
    reason = str(reason_text or '').strip() or reason_map.get(reason_code, reason_map[REASON_UNKNOWN])
    lines = [
        '<b>Tradecard Explain</b>',
        f'Ticker: <b>{sym}</b>',
        'Explanation temporarily unavailable.',
        f'Reason: {reason}',
    ]
    state = str(latest_state or '').strip()
    if state:
        lines.append(f'Latest known state: {state}')
    lines.extend([
        'No new decision or outcome was created.',
        'Paper only.',
    ])
    return '\n'.join(lines)


def truncate_explain_text(text: str, *, max_chars: int = EXPLAIN_MAX_CHARS) -> str:
    raw = str(text or '')
    if len(raw) <= max_chars:
        return raw
    cut = raw[: max(0, max_chars - 20)].rstrip()
    if '\n' in cut:
        cut = cut.rsplit('\n', 1)[0].rstrip()
    return cut + '\n… (truncated)'


def split_explain_messages(text: str, *, max_chars: int = EXPLAIN_MAX_CHARS) -> list[str]:
    """Split long explain output into Telegram-safe parts (no duplicates of empty parts)."""
    raw = str(text or '').strip()
    if not raw:
        return [format_explain_fallback('UNKNOWN', reason_code=REASON_RENDER_FAILURE)]
    if len(raw) <= max_chars:
        return [raw]
    parts: list[str] = []
    remaining = raw
    while remaining:
        if len(remaining) <= max_chars:
            parts.append(remaining)
            break
        window = remaining[:max_chars]
        split_at = window.rfind('\n\n')
        if split_at < max_chars // 3:
            split_at = window.rfind('\n')
        if split_at < max_chars // 3:
            split_at = max_chars
        chunk = remaining[:split_at].rstrip()
        if not chunk:
            chunk = remaining[:max_chars]
            split_at = len(chunk)
        parts.append(chunk)
        remaining = remaining[split_at:].lstrip()
    return parts or [truncate_explain_text(raw, max_chars=max_chars)]


def freshness_meta_for_explain(
    *,
    force: bool = False,
    chat_id: str | None = None,
) -> dict[str, Any]:
    """
    Read-mostly freshness for explain.

    Does not run unbounded scanner refresh. Optional bounded refresh only when
    force/fresh or TRADECARD_EXPLAIN_ALLOW_REFRESH=1.
    Never resolves journal outcomes.
    """
    from backend.trading.tradecard_refresh import (
        _base_freshness_meta,
        _run_lightweight_refresh,
        _file_age_seconds,
        QUOTE_FILE,
        SCANNER_FILE,
        is_tradecard_data_stale,
    )

    meta = _base_freshness_meta()
    meta['explain_read_mostly'] = True
    meta['scopes_called'] = []
    meta['refresh_skipped'] = True

    if not explain_allow_bounded_refresh(force=force):
        return meta

    from backend.telegram.india_mode_lock import is_live_market_hours_phase

    if not is_live_market_hours_phase() and not force:
        return meta

    try:
        from backend.runtime.global_job_locks import run_with_timeout

        prices_ok, scanner_ok, scopes_called = run_with_timeout(
            _run_lightweight_refresh,
            job='tradecard_explain_refresh',
            timeout=EXPLAIN_REFRESH_TIMEOUT_SEC,
            owner=str(chat_id or 'explain'),
        )
        meta['scopes_called'] = list(scopes_called or [])
        meta['refresh_skipped'] = False
        meta['quote_age_seconds'] = _file_age_seconds(QUOTE_FILE)
        meta['scanner_age_seconds'] = _file_age_seconds(SCANNER_FILE)
        meta['quote_refreshed_now'] = bool(prices_ok)
        meta['scanner_refreshed_now'] = bool(scanner_ok)
        meta['refresh_failed'] = not (prices_ok and scanner_ok)
        meta['data_stale'] = is_tradecard_data_stale(meta)
    except TimeoutError:
        log_explain_reason(REASON_REFRESH_TIMEOUT, ticker='')
        meta['refresh_failed'] = True
        meta['refresh_skipped'] = False
        meta['explain_reason'] = REASON_REFRESH_TIMEOUT
        meta['quote_age_seconds'] = _file_age_seconds(QUOTE_FILE)
        meta['scanner_age_seconds'] = _file_age_seconds(SCANNER_FILE)
        meta['data_stale'] = True
    except Exception as exc:
        log_explain_reason(REASON_REFRESH_TIMEOUT, detail=type(exc).__name__)
        meta['refresh_failed'] = True
        meta['data_stale'] = True
    return meta


def _safe_board_for_explain() -> dict[str, Any]:
    """Build opening board from cached payloads only — no live auto-refresh."""
    from backend.trading.opening_rally_radar import build_opening_rally_board

    return build_opening_rally_board()


def lookup_current_candidate(
    ticker: object,
    *,
    board: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Ticker-bound, session-aware candidate lookup for explain.

    Prefers current-session board row over historical cards.
    Does not create candidates or mutate learning state.
    """
    sym = str(ticker or '').strip().upper()
    result: dict[str, Any] = {
        'ticker': sym,
        'found': False,
        'board_row': None,
        'board': None,
        'state': '',
        'score': 0,
        'session_stale': False,
        'reference_only': False,
        'source': 'none',
    }
    if not sym:
        return result
    try:
        data = board if isinstance(board, dict) else _safe_board_for_explain()
    except Exception as exc:
        log_explain_reason(REASON_LOOKUP_FAILURE, ticker=sym, detail=type(exc).__name__)
        result['reason'] = REASON_LOOKUP_FAILURE
        return result

    result['board'] = data
    result['session_stale'] = bool(data.get('session_stale'))
    result['reference_only'] = bool(data.get('reference_only'))
    ranked = list(data.get('ranked_candidates') or [])
    row = next(
        (
            r for r in ranked
            if isinstance(r, dict) and str(r.get('ticker') or '').strip().upper() == sym
        ),
        None,
    )
    if isinstance(row, dict):
        result['found'] = True
        result['board_row'] = dict(row)
        result['state'] = str(row.get('state') or row.get('status') or '').strip()
        try:
            result['score'] = int(row.get('score') or 0)
        except (TypeError, ValueError):
            result['score'] = 0
        if result['session_stale']:
            result['source'] = 'stale_board'
        elif result['reference_only']:
            result['source'] = 'reference_board'
        else:
            result['source'] = 'opening_board'
        return result

    # Soft historical hint from today's active journal entry (no inventing board rows).
    try:
        from backend.trading.tradecard_journal import get_active_valid_entry

        active = get_active_valid_entry(sym)
        if isinstance(active, dict) and active:
            result['found'] = True
            result['state'] = str(active.get('status') or active.get('state') or '').strip()
            result['source'] = 'journal'
            result['historical'] = dict(active)
            return result
    except Exception:
        pass
    result['reason'] = REASON_CANDIDATE_NOT_FOUND
    return result


def _render_explain_body(
    ticker: str,
    *,
    freshness_meta: dict[str, Any] | None,
    lookup: dict[str, Any],
) -> str:
    from backend.telegram.response_format import format_tradecard_evidence_explain_telegram

    return format_tradecard_evidence_explain_telegram(
        ticker,
        freshness_meta=freshness_meta,
        board=lookup.get('board') if isinstance(lookup.get('board'), dict) else None,
        board_row=lookup.get('board_row') if isinstance(lookup.get('board_row'), dict) else None,
        lookup=lookup,
    )


def run_tradecard_explain_safe(
    ticker: object,
    *,
    chat_id: str | None = None,
    force: bool = False,
    freshness_meta: dict[str, Any] | None = None,
    board: dict[str, Any] | None = None,
    timeout_sec: float | None = None,
) -> dict[str, Any]:
    """
    Never-silent explain entrypoint.

    Always returns {'text': str, 'texts': list[str], 'reason': str, 'ok': bool}.
    """
    sym = str(ticker or '').strip().upper()
    timeout = float(EXPLAIN_TOTAL_TIMEOUT_SEC if timeout_sec is None else timeout_sec)

    def _work() -> dict[str, Any]:
        if not sym:
            text = format_explain_fallback(
                'UNKNOWN',
                reason_code=REASON_CANDIDATE_NOT_FOUND,
                reason_text='no ticker supplied for tradecard evidence explain.',
            )
            return {
                'ok': False,
                'ticker': '',
                'reason': REASON_CANDIDATE_NOT_FOUND,
                'text': text,
                'texts': [text],
            }

        meta = freshness_meta if isinstance(freshness_meta, dict) else freshness_meta_for_explain(
            force=force,
            chat_id=chat_id,
        )
        try:
            lookup = lookup_current_candidate(sym, board=board)
        except Exception as exc:
            log_explain_reason(REASON_LOOKUP_FAILURE, ticker=sym, detail=type(exc).__name__)
            text = format_explain_fallback(sym, reason_code=REASON_LOOKUP_FAILURE)
            return {'ok': False, 'ticker': sym, 'reason': REASON_LOOKUP_FAILURE, 'text': text, 'texts': [text]}

        try:
            body = _render_explain_body(sym, freshness_meta=meta, lookup=lookup)
        except Exception as exc:
            log_explain_reason(REASON_RENDER_FAILURE, ticker=sym, detail=type(exc).__name__)
            text = format_explain_fallback(
                sym,
                reason_code=REASON_RENDER_FAILURE,
                latest_state=str(lookup.get('state') or ''),
            )
            return {'ok': False, 'ticker': sym, 'reason': REASON_RENDER_FAILURE, 'text': text, 'texts': [text]}

        if not str(body or '').strip():
            log_explain_reason(REASON_PAYLOAD_MISSING, ticker=sym)
            text = format_explain_fallback(
                sym,
                reason_code=REASON_PAYLOAD_MISSING,
                latest_state=str(lookup.get('state') or ''),
            )
            return {'ok': False, 'ticker': sym, 'reason': REASON_PAYLOAD_MISSING, 'text': text, 'texts': [text]}

        try:
            texts = split_explain_messages(body)
        except Exception:
            log_explain_reason(REASON_RENDER_FAILURE, ticker=sym, detail='split_failed')
            texts = [truncate_explain_text(body)]
        if not texts:
            texts = [format_explain_fallback(sym, reason_code=REASON_RENDER_FAILURE)]
        reason = str(meta.get('explain_reason') or '')
        if not lookup.get('found') and 'Trace unavailable' in texts[0]:
            reason = reason or REASON_CANDIDATE_NOT_FOUND
        return {
            'ok': True,
            'ticker': sym,
            'reason': reason or 'ok',
            'text': texts[0],
            'texts': texts,
            'lookup': {
                'found': bool(lookup.get('found')),
                'source': lookup.get('source'),
                'state': lookup.get('state'),
            },
            'freshness': meta,
        }

    started = time.monotonic()
    try:
        from backend.runtime.global_job_locks import run_with_timeout

        result = run_with_timeout(
            _work,
            job='tradecard_explain',
            timeout=timeout,
            owner=str(chat_id or 'explain'),
        )
        if isinstance(result, dict) and result.get('text'):
            result['elapsed_sec'] = round(time.monotonic() - started, 3)
            return result
    except TimeoutError:
        log_explain_reason(REASON_TOTAL_TIMEOUT, ticker=sym)
        text = format_explain_fallback(sym, reason_code=REASON_TOTAL_TIMEOUT)
        return {
            'ok': False,
            'ticker': sym,
            'reason': REASON_TOTAL_TIMEOUT,
            'text': text,
            'texts': [text],
            'elapsed_sec': round(time.monotonic() - started, 3),
        }
    except Exception as exc:
        log_explain_reason(REASON_UNKNOWN, ticker=sym, detail=type(exc).__name__)
        text = format_explain_fallback(sym, reason_code=REASON_UNKNOWN)
        return {
            'ok': False,
            'ticker': sym,
            'reason': REASON_UNKNOWN,
            'text': text,
            'texts': [text],
            'elapsed_sec': round(time.monotonic() - started, 3),
        }

    text = format_explain_fallback(sym, reason_code=REASON_UNKNOWN)
    return {'ok': False, 'ticker': sym, 'reason': REASON_UNKNOWN, 'text': text, 'texts': [text]}


def run_callable_with_explain_timeout(
    fn: Callable[[], Any],
    *,
    ticker: str = '',
    timeout_sec: float | None = None,
) -> Any:
    """Test helper — bounded wrapper matching production timeout behavior."""
    from backend.runtime.global_job_locks import run_with_timeout

    return run_with_timeout(
        fn,
        job='tradecard_explain_probe',
        timeout=float(EXPLAIN_TOTAL_TIMEOUT_SEC if timeout_sec is None else timeout_sec),
        owner='test',
    )
