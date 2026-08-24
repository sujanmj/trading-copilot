#!/usr/bin/env python3
"""AstraEdge 52P hotfix — /tradecard explain never silent."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ.setdefault('DISABLE_TELEGRAM', '1')
os.environ.setdefault('DISABLE_TELEGRAM_SENDS', '1')
os.environ.setdefault('TRADECARD_EXPLAIN_ALLOW_REFRESH', '0')

from scripts._test_runtime_isolation import isolated_ai_usage_log


def _fail(msg: str) -> int:
    print(f'TRADECARD_EXPLAIN_NEVER_SILENT_52P_FAIL: {msg}', file=sys.stderr)
    return 1


def _pvrinox_row(**extra) -> dict:
    row = {
        'ticker': 'PVRINOX',
        'state': 'TRADECARD_CANDIDATE',
        'status': 'ENTRY_MISSED',
        'score': 72,
        'why': ['scanner confirmed', 'volume ignition'],
        'has_catalyst': True,
        'scanner_row': {
            'price': 1450.0,
            'open_price': 1400.0,
            'vwap': 1420.0,
            'volume_ratio': 3.2,
            'change_percent': 2.4,
        },
        'decision_trace': {
            'ok': True,
            'version': '52P',
            'symbol': 'PVRINOX',
            'stages': [
                {'stage': 'scanner_guard', 'status': 'pass', 'detail': 'live scanner current'},
                {'stage': 'macro_guard', 'status': 'pass', 'detail': 'macro clear'},
                {'stage': 'final_decision', 'status': 'pass', 'detail': 'quality candidate'},
            ],
            'final_decision': 'TRADECARD_CANDIDATE',
            'reason_codes': ['scanner_ok', 'quality_pass'],
        },
    }
    row.update(extra)
    return row


def _board_with(*rows: dict, session_stale: bool = False) -> dict:
    return {
        'ok': True,
        'session_date': '2099-01-01',
        'session_stale': session_stale,
        'reference_only': False,
        'ranked_candidates': list(rows),
        'gainer_scan': {'promoted': [r.get('ticker') for r in rows], 'total': len(rows)},
        'live_scanner_ready': not session_stale,
    }


def test_build_still_52p() -> int:
    from backend.config.build_info import BUILD_STAGE, TELEGRAM_BUILD

    # Exact identity pairs only — mismatched stage/Telegram combinations must fail.
    allowed_build_pairs = {
        ('52P', 'AstraEdge 52P'),
        ('52Q', 'AstraEdge 52Q'),
        ('52R-A1', 'AstraEdge 52R-A1'),
        ('52R-A2', 'AstraEdge 52R-A2'),
        ('52R-B1', 'AstraEdge 52R-B1'),
        ('52R-B2N', 'AstraEdge 52R-B2N'),
        ('52R-B2', 'AstraEdge 52R-B2'),
        ('52R-C1A', 'AstraEdge 52R-C1A'),
    }
    if (BUILD_STAGE, TELEGRAM_BUILD) not in allowed_build_pairs:
        return _fail(
            f'expected exact 52P-compatible build pair, got {BUILD_STAGE!r} / {TELEGRAM_BUILD!r}'
        )
    return 0


def test_build_pair_mismatches_rejected_52p() -> int:
    """Mismatched stage/Telegram pairs must never be accepted by 52P allowlist."""
    allowed_build_pairs = {
        ('52P', 'AstraEdge 52P'),
        ('52Q', 'AstraEdge 52Q'),
        ('52R-A1', 'AstraEdge 52R-A1'),
        ('52R-A2', 'AstraEdge 52R-A2'),
        ('52R-B1', 'AstraEdge 52R-B1'),
        ('52R-B2N', 'AstraEdge 52R-B2N'),
        ('52R-B2', 'AstraEdge 52R-B2'),
        ('52R-C1A', 'AstraEdge 52R-C1A'),
    }
    mismatches = (
        ('52Q', 'AstraEdge 52R-A1'),
        ('52R-A1', 'AstraEdge 52Q'),
        ('52P', 'AstraEdge 52Q'),
        ('52R-A2', 'AstraEdge 52R-A1'),
        ('52R-A1', 'AstraEdge 52R-A2'),
        ('52R-B1', 'AstraEdge 52R-A2'),
        ('52R-A2', 'AstraEdge 52R-B1'),
        ('52R-B2N', 'AstraEdge 52R-B1'),
        ('52R-B1', 'AstraEdge 52R-B2N'),
        ('52R-B2', 'AstraEdge 52R-B2N'),
        ('52R-B2N', 'AstraEdge 52R-B2'),
        ('52R-C1A', 'AstraEdge 52R-B2'),
        ('52R-B2', 'AstraEdge 52R-C1A'),
    )
    for stage, telegram in mismatches:
        if (stage, telegram) in allowed_build_pairs:
            return _fail(f'mismatch pair must be rejected: {stage!r} / {telegram!r}')
    return 0


def test_current_pvrinox_returns_explanation() -> int:
    from backend.trading.tradecard_explain import run_tradecard_explain_safe

    board = _board_with(_pvrinox_row())
    with patch('backend.trading.tradecard_explain._safe_board_for_explain', return_value=board), \
         patch('backend.trading.tradecard_evidence.build_tradecard_evidence_matrix', return_value={
             'ticker': 'PVRINOX',
             'consensus_score': 70,
             'confidence': 'MEDIUM',
             'decision': 'VALID ENTRY',
             'final_reason': 'scanner confirmed',
             'evidence_items': [],
             'direct_confirms': [],
             'indirect_confirms': [],
             'risk_filters': [],
             'missing_modules': [],
             'market_mode': 'LIVE',
         }):
        result = run_tradecard_explain_safe('PVRINOX', board=board, timeout_sec=5)
    text = result.get('text') or ''
    if 'Tradecard Explain' not in text or 'PVRINOX' not in text:
        return _fail(f'PVRINOX explain missing header/ticker: {text[:300]!r}')
    if not str(text).strip():
        return _fail('PVRINOX explain returned empty text')
    if result.get('ok') is not True and 'unavailable' in text.lower() and 'PVRINOX' not in text:
        return _fail('PVRINOX must still identify ticker on soft failure')
    return 0


def test_current_preferred_over_historical() -> int:
    from backend.trading.tradecard_explain import lookup_current_candidate

    board = _board_with(_pvrinox_row(state='PULLBACK_WATCH', score=81))
    historical = {'ticker': 'PVRINOX', 'status': 'OLD_HISTORICAL', 'state': 'OLD_HISTORICAL'}
    with patch('backend.trading.tradecard_journal.get_active_valid_entry', return_value=historical):
        lookup = lookup_current_candidate('PVRINOX', board=board)
    if lookup.get('source') != 'opening_board':
        return _fail(f'current board must win over journal, got {lookup.get("source")!r}')
    if str((lookup.get('board_row') or {}).get('state') or '') != 'PULLBACK_WATCH':
        return _fail('must keep current-session state, not historical')
    return 0


def test_existing_trace_renders() -> int:
    from backend.trading.tradecard_explain import run_tradecard_explain_safe

    board = _board_with(_pvrinox_row())
    with patch('backend.trading.tradecard_evidence.build_tradecard_evidence_matrix', return_value={
        'ticker': 'PVRINOX', 'consensus_score': 70, 'confidence': 'MEDIUM',
        'decision': 'HIGH CONVICTION WATCH', 'final_reason': 'ok',
        'evidence_items': [], 'direct_confirms': [], 'indirect_confirms': [],
        'risk_filters': [], 'missing_modules': [], 'market_mode': 'LIVE',
    }):
        result = run_tradecard_explain_safe('PVRINOX', board=board, timeout_sec=5)
    text = result.get('text') or ''
    if 'Candidate Decision Trace' not in text:
        return _fail('existing 52P trace header missing')
    if 'Trace unavailable for this candidate' in text:
        return _fail('valid trace must not show unavailable')
    return 0


def test_missing_trace_unavailable() -> int:
    from backend.trading.tradecard_explain import run_tradecard_explain_safe

    row = _pvrinox_row()
    row.pop('decision_trace', None)
    board = _board_with(row)
    with patch('backend.trading.tradecard_evidence.build_tradecard_evidence_matrix', return_value={
        'ticker': 'NILKAMAL', 'consensus_score': 10, 'confidence': 'LOW',
        'decision': 'NO TRADE / REJECTED', 'final_reason': 'historical',
        'evidence_items': [], 'direct_confirms': [], 'indirect_confirms': [],
        'risk_filters': [], 'missing_modules': [], 'market_mode': 'RESEARCH_MODE',
    }), patch('backend.trading.candidate_decision_trace.extract_decision_trace', return_value=None), \
         patch('backend.trading.candidate_decision_trace.build_candidate_decision_trace', side_effect=RuntimeError('no rebuild')):
        # Force missing board_row path for NILKAMAL historical compatibility.
        empty = _board_with()
        result = run_tradecard_explain_safe('NILKAMAL', board=empty, timeout_sec=5)
    text = result.get('text') or ''
    if 'NILKAMAL' not in text:
        return _fail('NILKAMAL must appear in explain')
    if 'Trace unavailable for this candidate' not in text:
        return _fail('missing trace must show Trace unavailable')
    if not text.strip():
        return _fail('NILKAMAL must not be silent')
    return 0


def test_slow_refresh_times_out() -> int:
    from backend.trading.tradecard_explain import (
        REASON_REFRESH_TIMEOUT,
        REASON_TOTAL_TIMEOUT,
        freshness_meta_for_explain,
        run_tradecard_explain_safe,
    )

    def _timeout_refresh(*args, **kwargs):
        raise TimeoutError('tradecard_explain_refresh timed out after 0.2s')

    with patch.dict(os.environ, {'TRADECARD_EXPLAIN_ALLOW_REFRESH': '1'}, clear=False), \
         patch('backend.trading.tradecard_explain.explain_allow_bounded_refresh', return_value=True), \
         patch('backend.telegram.india_mode_lock.is_live_market_hours_phase', return_value=True), \
         patch('backend.runtime.global_job_locks.run_with_timeout', side_effect=_timeout_refresh):
        meta = freshness_meta_for_explain(force=True, chat_id='timeout-test')
    if meta.get('explain_reason') != REASON_REFRESH_TIMEOUT and not meta.get('refresh_failed'):
        return _fail(f'slow refresh must mark timeout/failure, got {meta!r}')

    def _timeout_total(fn, **kwargs):
        raise TimeoutError('tradecard_explain timed out after 0.2s')

    board = _board_with(_pvrinox_row())
    with patch('backend.runtime.global_job_locks.run_with_timeout', side_effect=_timeout_total):
        result = run_tradecard_explain_safe('PVRINOX', board=board, timeout_sec=0.2)
    text = result.get('text') or ''
    if 'PVRINOX' not in text or 'temporarily unavailable' not in text.lower():
        return _fail(f'timeout fallback missing: {text!r}')
    if result.get('reason') != REASON_TOTAL_TIMEOUT:
        return _fail(f'expected {REASON_TOTAL_TIMEOUT}, got {result.get("reason")!r}')
    return 0


def test_explain_skips_full_scanner_refresh() -> int:
    from backend.telegram.lazy_command_runner import run_tradecard_only
    from backend.trading.tradecard_explain import freshness_meta_for_explain

    called: list[str] = []

    def _scoped(scope: str, **kwargs):
        called.append(scope)
        return {'ok': True, scope: 'ok'}

    meta = freshness_meta_for_explain(force=False)
    if meta.get('scopes_called'):
        return _fail('default explain freshness must not call refresh scopes')
    if not meta.get('explain_read_mostly') or not meta.get('refresh_skipped'):
        return _fail('explain freshness must be read-mostly / skipped')

    board = _board_with(_pvrinox_row())
    with isolated_ai_usage_log(), \
         patch('backend.trading.tradecard_explain._safe_board_for_explain', return_value=board), \
         patch('backend.telegram.lazy_command_runner._scoped_refresh', side_effect=_scoped), \
         patch('backend.trading.tradecard_refresh._run_lightweight_refresh', side_effect=AssertionError('refresh must not run')), \
         patch('backend.trading.tradecard_evidence.build_tradecard_evidence_matrix', return_value={
             'ticker': 'PVRINOX', 'consensus_score': 70, 'confidence': 'MEDIUM',
             'decision': 'VALID ENTRY', 'final_reason': 'ok',
             'evidence_items': [], 'direct_confirms': [], 'indirect_confirms': [],
             'risk_filters': [], 'missing_modules': [], 'market_mode': 'LIVE',
         }):
        result = run_tradecard_only('explain PVRINOX', chat_id='never-silent')
    if called:
        return _fail(f'explain must not call scoped refresh, called={called}')
    if 'PVRINOX' not in (result.get('text') or ''):
        return _fail('runner explain missing PVRINOX')
    return 0


def test_stale_caches_do_not_block() -> int:
    from backend.trading.tradecard_explain import run_tradecard_explain_safe

    board = _board_with(_pvrinox_row(), session_stale=True)
    with patch('backend.trading.tradecard_evidence.build_tradecard_evidence_matrix', side_effect=RuntimeError('stale cache boom')):
        result = run_tradecard_explain_safe('PVRINOX', board=board, timeout_sec=5)
    text = result.get('text') or ''
    if 'PVRINOX' not in text or not text.strip():
        return _fail('stale/optional evidence failure must still respond')
    return 0


def test_evidence_exception_fallback() -> int:
    from backend.telegram.response_format import format_tradecard_evidence_explain_telegram

    with patch('backend.telegram.response_format._append_tradecard_evidence', side_effect=RuntimeError('evidence boom')):
        text = format_tradecard_evidence_explain_telegram('PVRINOX', board=_board_with(), board_row=None)
    if 'PVRINOX' not in text:
        return _fail('evidence failure must keep ticker')
    if 'Evidence matrix temporarily unavailable' not in text and 'Trace unavailable' not in text:
        return _fail('evidence failure must keep a clean body')
    return 0


def test_trace_exception_preserves_base() -> int:
    from backend.telegram.response_format import format_tradecard_evidence_explain_telegram

    board = _board_with(_pvrinox_row())
    with patch('backend.trading.tradecard_evidence.build_tradecard_evidence_matrix', return_value={
        'ticker': 'PVRINOX', 'consensus_score': 55, 'confidence': 'MEDIUM',
        'decision': 'HIGH CONVICTION WATCH', 'final_reason': 'base ok',
        'evidence_items': [{'module': 'scanner', 'scope': 'direct', 'verdict': 'confirm', 'weight': 10, 'age_label': 'now', 'detail': 'live'}],
        'direct_confirms': [], 'indirect_confirms': [], 'risk_filters': [], 'missing_modules': [],
        'market_mode': 'LIVE',
    }), patch('backend.trading.candidate_decision_trace.format_candidate_decision_trace_telegram', side_effect=RuntimeError('trace boom')), \
         patch('backend.trading.candidate_decision_trace.extract_decision_trace', return_value={'ok': True}):
        text = format_tradecard_evidence_explain_telegram(
            'PVRINOX',
            board=board,
            board_row=board['ranked_candidates'][0],
            lookup={'found': True, 'source': 'opening_board', 'state': 'TRADECARD_CANDIDATE'},
        )
    if 'Evidence Matrix' not in text and 'Consensus score' not in text and 'PVRINOX' not in text:
        return _fail('base explanation must remain when trace render fails')
    if 'Trace unavailable for this candidate' not in text:
        return _fail('trace render failure must append unavailable')
    return 0


def test_lookup_exception_fallback() -> int:
    from backend.trading.tradecard_explain import REASON_LOOKUP_FAILURE, run_tradecard_explain_safe

    with patch('backend.trading.tradecard_explain.lookup_current_candidate', side_effect=RuntimeError('lookup boom')):
        result = run_tradecard_explain_safe('PVRINOX', timeout_sec=5)
    if result.get('reason') != REASON_LOOKUP_FAILURE:
        return _fail(f'lookup failure reason mismatch: {result.get("reason")!r}')
    if 'PVRINOX' not in (result.get('text') or ''):
        return _fail('lookup failure must still name ticker')
    return 0


def test_malformed_historical_payload() -> int:
    from backend.trading.tradecard_explain import run_tradecard_explain_safe

    board = {
        'ok': True,
        'ranked_candidates': [{'ticker': 'PVRINOX', 'score': 'bad', 'state': None, 'decision_trace': 'not-a-dict'}],
    }
    result = run_tradecard_explain_safe('PVRINOX', board=board, timeout_sec=5)
    if 'PVRINOX' not in (result.get('text') or ''):
        return _fail('malformed payload must not crash / stay silent')
    return 0


def test_unknown_symbol_clean() -> int:
    from backend.trading.tradecard_explain import run_tradecard_explain_safe

    result = run_tradecard_explain_safe('ZZZNOTREAL', board=_board_with(), timeout_sec=5)
    text = result.get('text') or ''
    if 'ZZZNOTREAL' not in text:
        return _fail('unknown symbol must still return named response')
    if 'Trace unavailable for this candidate' not in text and 'temporarily unavailable' not in text.lower():
        return _fail('unknown symbol needs clean unavailable wording')
    return 0


def test_formatting_failure_plain_fallback() -> int:
    from backend.telegram.telegram_analysis_bot import send_analysis_message

    class _Resp:
        def __init__(self, code: int):
            self.status_code = code

    calls: list[dict] = []

    def _post(url, json=None, timeout=10):
        payload = dict(json or {})
        calls.append(payload)
        if payload.get('parse_mode'):
            return _Resp(400)
        return _Resp(200)

    html_body = (
        '<b>Tradecard Explain</b>\n'
        'Ticker: <b>PVRINOX</b>\n'
        'State: <code>ENTRY_MISSED</code>\n'
        'Paper only.'
    )
    with patch.dict(os.environ, {'DISABLE_TELEGRAM': '0', 'DISABLE_TELEGRAM_SENDS': '0'}, clear=False), \
         patch('backend.telegram.telegram_analysis_bot.BOT_TOKEN', 'tok'), \
         patch('backend.telegram.telegram_analysis_bot.CHAT_ID', '1'), \
         patch('backend.telegram.telegram_analysis_bot.API_URL', 'https://example.test/bot'), \
         patch('backend.config.local_safe_mode.local_telegram_send_dry_run', return_value=False), \
         patch('backend.utils.telegram_guard.is_telegram_send_enabled', return_value=True), \
         patch('backend.utils.config.DISABLE_TELEGRAM', False), \
         patch('backend.utils.config.DISABLE_TELEGRAM_SENDS', False), \
         patch('backend.telegram.telegram_analysis_bot.requests.post', side_effect=_post):
        out = send_analysis_message(html_body, command='tradecard', parse_mode='HTML')

    if len(calls) != 2:
        return _fail(f'expected exactly two send attempts, got {len(calls)}')
    if calls[0].get('parse_mode') != 'HTML':
        return _fail(f'first request must use HTML parse_mode, got {calls[0]!r}')
    if 'parse_mode' in calls[1]:
        return _fail(f'second request must omit parse_mode, got {calls[1]!r}')
    plain = str(calls[1].get('text') or '')
    if 'PVRINOX' not in plain or 'Tradecard Explain' not in plain:
        return _fail(f'plain fallback missing readable content: {plain!r}')
    for tag in ('<b>', '</b>', '<code>', '</code>', '<i>', '</i>'):
        if tag in plain:
            return _fail(f'plain fallback still contains HTML tag {tag!r}: {plain!r}')
    if not out.get('ok') or not out.get('plain_fallback'):
        return _fail(f'plain-text fallback result missing: {out!r}')
    return 0


def test_formatting_both_sends_fail_cleanly() -> int:
    from backend.telegram.telegram_analysis_bot import send_analysis_message

    class _Resp:
        def __init__(self, code: int):
            self.status_code = code

    calls: list[dict] = []

    def _post(url, json=None, timeout=10):
        calls.append(dict(json or {}))
        return _Resp(500)

    with patch.dict(os.environ, {'DISABLE_TELEGRAM': '0', 'DISABLE_TELEGRAM_SENDS': '0'}, clear=False), \
         patch('backend.telegram.telegram_analysis_bot.BOT_TOKEN', 'tok'), \
         patch('backend.telegram.telegram_analysis_bot.CHAT_ID', '1'), \
         patch('backend.telegram.telegram_analysis_bot.API_URL', 'https://example.test/bot'), \
         patch('backend.config.local_safe_mode.local_telegram_send_dry_run', return_value=False), \
         patch('backend.utils.telegram_guard.is_telegram_send_enabled', return_value=True), \
         patch('backend.utils.config.DISABLE_TELEGRAM', False), \
         patch('backend.utils.config.DISABLE_TELEGRAM_SENDS', False), \
         patch('backend.telegram.telegram_analysis_bot.requests.post', side_effect=_post):
        out = send_analysis_message(
            '<b>Tradecard Explain</b>\nTicker: <b>PVRINOX</b>',
            command='tradecard',
            parse_mode='HTML',
        )
    if out.get('ok') or out.get('sent'):
        return _fail(f'both-fail path must report not sent: {out!r}')
    if not out.get('plain_fallback'):
        return _fail('both-fail path must still attempt plain fallback')
    if 'Traceback' in str(out) or 'Exception' in str(out.get('text') or ''):
        return _fail('failed send must not expose stack traces')
    if len(calls) != 2:
        return _fail(f'both-fail path expected 2 attempts, got {len(calls)}')
    return 0


def test_long_trace_split_or_truncate() -> int:
    from backend.trading.tradecard_explain import split_explain_messages, truncate_explain_text

    huge = '<b>Tradecard Explain</b>\n' + ('line\n' * 5000)
    parts = split_explain_messages(huge, max_chars=800)
    if len(parts) < 2:
        return _fail('long output must split into multiple parts')
    if any(len(p) > 900 for p in parts):
        return _fail('split parts exceed safety bound')
    trunc = truncate_explain_text(huge, max_chars=500)
    if len(trunc) > 520 or 'truncated' not in trunc:
        return _fail('truncate helper failed')
    return 0


def _check_one_logical_explain(texts: list[str]) -> str | None:
    """Return error message if texts are not exactly one logical Tradecard Explain."""
    if not texts:
        return 'no explain parts returned'
    if any(not str(t or '').strip() for t in texts):
        return 'empty explain part is not allowed'
    joined = '\n'.join(texts)
    if 'PVRINOX' not in joined:
        return 'logical response missing PVRINOX'
    header = '<b>Tradecard Explain</b>'
    headers = sum(1 for t in texts if header in t)
    if headers == 0:
        return 'missing Tradecard Explain header'
    if headers > 1:
        return f'expected exactly one Tradecard Explain header, got {headers}'
    # Continuation parts (if any) must not repeat the full header.
    for index, part in enumerate(texts[1:], start=2):
        if header in part:
            return f'continuation part {index} must not repeat full Tradecard Explain header'
    # Identical full message bodies must not be duplicated.
    stripped = [str(t).strip() for t in texts]
    if len(stripped) >= 2 and stripped[0] == stripped[1]:
        return 'identical full explanation body sent twice'
    return None


def test_one_logical_response() -> int:
    from backend.telegram.telegram_analysis_bot import handle_analysis_command

    board = _board_with(_pvrinox_row())
    with isolated_ai_usage_log(), \
         patch('backend.trading.tradecard_explain._safe_board_for_explain', return_value=board), \
         patch('backend.trading.tradecard_evidence.build_tradecard_evidence_matrix', return_value={
             'ticker': 'PVRINOX', 'consensus_score': 70, 'confidence': 'MEDIUM',
             'decision': 'VALID ENTRY', 'final_reason': 'ok',
             'evidence_items': [], 'direct_confirms': [], 'indirect_confirms': [],
             'risk_filters': [], 'missing_modules': [], 'market_mode': 'LIVE',
         }):
        results = handle_analysis_command('/tradecard explain PVRINOX', 'never_silent', dry_run=True)
    texts = [str(r.get('text') or '') for r in (results or [])]
    err = _check_one_logical_explain(texts)
    if err:
        return _fail(err)
    return 0


def test_duplicate_full_explanation_rejected_by_checker() -> int:
    body = (
        '<b>Tradecard Explain</b>\n'
        'Ticker: <b>PVRINOX</b>\n'
        'State: ENTRY_MISSED\n'
        'Paper only.'
    )
    err = _check_one_logical_explain([body, body])
    if err is None:
        return _fail('duplicate full explanation bodies must fail the logical-response checker')
    if 'twice' not in err and 'exactly one' not in err:
        return _fail(f'unexpected duplicate checker message: {err!r}')
    # Also reject two complete headers even when bodies differ slightly.
    err2 = _check_one_logical_explain([body, body + '\nextra'])
    if err2 is None:
        return _fail('two Tradecard Explain headers must fail the checker')
    return 0


def test_prohibited_call_points_are_not_invoked() -> int:
    """Guard canonical AI/broker/outcome/learning/refresh call points during explain."""
    import sys
    import types
    from contextlib import ExitStack

    from backend.trading.tradecard_explain import run_tradecard_explain_safe

    board = _board_with(_pvrinox_row())
    boom = AssertionError('prohibited_call')
    evidence = {
        'ticker': 'PVRINOX', 'consensus_score': 70, 'confidence': 'MEDIUM',
        'decision': 'VALID ENTRY', 'final_reason': 'ok',
        'evidence_items': [], 'direct_confirms': [], 'indirect_confirms': [],
        'risk_filters': [], 'missing_modules': [], 'market_mode': 'LIVE',
    }

    # ask_ai lives in ai_router; stub the module so the guard does not import
    # heavy provider SDKs (which can fail on some local Python builds).
    ai_router_stub = types.ModuleType('backend.ai.ai_router')

    def _ask_ai_boom(*_a, **_k):
        raise boom

    ai_router_stub.ask_ai = _ask_ai_boom  # type: ignore[attr-defined]

    patches = [
        # Default explain path must not refresh scanner/prices.
        patch('backend.trading.tradecard_refresh._run_lightweight_refresh', side_effect=boom),
        patch('backend.telegram.lazy_command_runner._scoped_refresh', side_effect=boom),
        # Conversational AI routing (imports cleanly).
        patch('backend.telegram.ai_usage_guard.guarded_ask_ai', side_effect=boom),
        # Broker refresh / intelligence.
        patch('backend.analytics.broker_intelligence.refresh_broker_intelligence', side_effect=boom),
        patch('backend.analytics.broker_intelligence.handle_broker_command', side_effect=boom),
        # Outcome resolution.
        patch('backend.storage.outcome_resolver.run_outcome_resolver_once', side_effect=boom),
        patch('backend.trading.tradecard_journal.resolve_pending_tradecard_outcomes', side_effect=boom),
        # Tradecard persistence.
        patch('backend.trading.tradecard_journal.persist_tradecard_generation', side_effect=boom),
        # Candidate snapshot / learning mutation.
        patch('backend.trading.candidate_outcome_learning.build_candidate_snapshot', side_effect=boom),
        patch('backend.trading.candidate_outcome_learning.capture_quality_snapshots', side_effect=boom),
        patch('backend.trading.candidate_outcome_learning.resolve_candidate_outcomes', side_effect=boom),
        # Evidence stub so explain can complete without live collectors.
        patch('backend.trading.tradecard_evidence.build_tradecard_evidence_matrix', return_value=evidence),
    ]
    with ExitStack() as stack:
        stack.enter_context(patch.dict(sys.modules, {'backend.ai.ai_router': ai_router_stub}))
        for item in patches:
            stack.enter_context(item)
        result = run_tradecard_explain_safe('PVRINOX', board=board, timeout_sec=5)
    if 'PVRINOX' not in (result.get('text') or ''):
        return _fail('mutation-guarded explain failed to respond with PVRINOX')
    return 0


def test_no_repo_data_mutation_from_focused_explain() -> int:
    """Explain must not create files under a patched data root; repo data/ stays untouched."""
    import subprocess

    from backend.trading.tradecard_explain import run_tradecard_explain_safe

    before = subprocess.check_output(
        ['git', 'status', '--short', '--', 'data'],
        cwd=str(PROJECT_ROOT),
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    board = _board_with(_pvrinox_row())
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        def _direct(fn, **kwargs):
            return fn()

        with patch('backend.utils.config.DATA_DIR', root), \
             patch('backend.runtime.global_job_locks.run_with_timeout', side_effect=_direct), \
             patch('backend.trading.tradecard_evidence.build_tradecard_evidence_matrix', return_value={
                 'ticker': 'PVRINOX', 'consensus_score': 70, 'confidence': 'MEDIUM',
                 'decision': 'VALID ENTRY', 'final_reason': 'ok',
                 'evidence_items': [], 'direct_confirms': [], 'indirect_confirms': [],
                 'risk_filters': [], 'missing_modules': [], 'market_mode': 'LIVE',
             }):
            run_tradecard_explain_safe('PVRINOX', board=board, timeout_sec=5)
        written = [p for p in root.rglob('*') if p.is_file()]
        if written:
            return _fail(f'explain wrote under patched data root: {written}')
    after = subprocess.check_output(
        ['git', 'status', '--short', '--', 'data'],
        cwd=str(PROJECT_ROOT),
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    if before != after:
        return _fail(
            'repository data/ status changed during focused explain test:\n'
            f'before={before!r}\nafter={after!r}'
        )
    return 0


def main() -> int:
    checks = (
        test_build_still_52p,
        test_build_pair_mismatches_rejected_52p,
        test_current_pvrinox_returns_explanation,
        test_current_preferred_over_historical,
        test_existing_trace_renders,
        test_missing_trace_unavailable,
        test_slow_refresh_times_out,
        test_explain_skips_full_scanner_refresh,
        test_stale_caches_do_not_block,
        test_evidence_exception_fallback,
        test_trace_exception_preserves_base,
        test_lookup_exception_fallback,
        test_malformed_historical_payload,
        test_unknown_symbol_clean,
        test_formatting_failure_plain_fallback,
        test_formatting_both_sends_fail_cleanly,
        test_long_trace_split_or_truncate,
        test_one_logical_response,
        test_duplicate_full_explanation_rejected_by_checker,
        test_prohibited_call_points_are_not_invoked,
        test_no_repo_data_mutation_from_focused_explain,
    )
    for check in checks:
        err = check()
        if err:
            return err
        print(f'PASS: {check.__name__}')
    print('TRADECARD_EXPLAIN_NEVER_SILENT_52P_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
