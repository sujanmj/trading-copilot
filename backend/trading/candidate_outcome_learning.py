"""
Candidate outcome learning — Phase 4B.18K / AstraEdge 52I.

Primary learning set: 09:20 quality tradecards + 09:31 final confirmation.
09:00 is premarket context only (excluded from main W/L stats).
Paper/research only — no trade execution.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, time
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path

IST = ZoneInfo('Asia/Kolkata')
STAGE = '4B.18K-A'

MIN_QUALITY_SCORE = 60
MAX_QUALITY_CANDIDATES = 10

WIN_MFE_PCT = 1.0
WIN_CLOSE_PCT = 0.7
LOSS_MAE_PCT = -1.0
LOSS_CLOSE_PCT = -0.7

AI_EXPLAIN_CAP = 4
PRIMARY_STAGES = frozenset({'opening_0920', 'final_0931', 'manual_tradecards'})
EXCLUDED_FROM_MAIN_STATS = frozenset({'premarket_context', 'opening_0900'})

OUTCOME_WIN = 'WIN'
OUTCOME_LOSS = 'LOSS'
OUTCOME_NEUTRAL = 'NEUTRAL'
OUTCOME_PENDING = 'PENDING_DATA'

WINNER_TAGS = frozenset({
    'verified_stock_specific_news',
    'official_source_confirmed',
    'fresh_scanner_confirmed',
    'volume_above_2x',
    'volume_above_5x',
    'sector_breadth_confirmed',
    'strong_result_news',
    'order_win_confirmed',
    'breakout_retest_confirmed',
    'relative_strength_in_red_market',
})

LOSER_TAGS = frozenset({
    'theme_only_no_stock_news',
    'stale_previous_session_mover',
    'weak_scanner_freshness',
    'high_chase_risk',
    'no_volume_followthrough',
    'macro_red_market_pressure',
    'unverified_feed',
    'price_volume_only_no_catalyst',
    'gap_up_failed',
    'failed_vwap',
    'news_not_enough_without_live_strength',
})


def _now_ist(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(tz=IST)
    if now.tzinfo is None:
        return now.replace(tzinfo=IST)
    return now.astimezone(IST)


def _session_date(now: datetime | None = None) -> str:
    return _now_ist(now).date().isoformat()


def _snapshots_path() -> Path:
    return get_data_path('candidate_snapshots.jsonl')


def _outcomes_path() -> Path:
    return get_data_path('candidate_outcomes.jsonl')


def _learning_path() -> Path:
    return get_data_path('candidate_learning_records.jsonl')


def _state_path() -> Path:
    return get_data_path('candidate_outcome_learning_state.json')


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + '\n')


def _load_jsonl(path: Path, *, limit: int = 50000) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    except OSError:
        return []
    return rows[-limit:]


def _safe_float(value: object, default: float | None = None) -> float | None:
    try:
        if value in (None, ''):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_symbol(value: object) -> str:
    return str(value or '').strip().upper()


def filter_quality_candidates(
    candidates: list[dict[str, Any]],
    *,
    min_score: int = MIN_QUALITY_SCORE,
    max_count: int = MAX_QUALITY_CANDIDATES,
) -> list[dict[str, Any]]:
    """Quality gate for /tradecards and scheduled tradecard lists."""
    kept: list[dict[str, Any]] = []
    for row in candidates or []:
        if not isinstance(row, dict):
            continue
        if str(row.get('state') or '').upper() == 'REJECTED':
            continue
        score = int(row.get('score') or 0)
        if score < min_score:
            continue
        kept.append(row)
    kept.sort(key=lambda r: int(r.get('score') or 0), reverse=True)
    return kept[:max_count]


def format_no_quality_tradecard_block() -> list[str]:
    return [
        'NO QUALITY TRADECARD',
        'Reason: no candidate above confidence 60',
    ]


def _row_price(row: dict[str, Any]) -> tuple[float | None, str]:
    scanner = row.get('scanner_row') if isinstance(row.get('scanner_row'), dict) else {}
    for key in ('price', 'ltp', 'last_price', 'close'):
        val = _safe_float((scanner or {}).get(key) or row.get(key))
        if val and val > 0:
            ts = str((scanner or {}).get('timestamp') or (scanner or {}).get('scan_time_local') or '')
            return val, ts or 'scanner_row'
    return None, ''


def _row_volume_ratio(row: dict[str, Any]) -> float | None:
    scanner = row.get('scanner_row') if isinstance(row.get('scanner_row'), dict) else {}
    return _safe_float((scanner or {}).get('volume_ratio') or row.get('volume_ratio'))


def _row_change_pct(row: dict[str, Any]) -> float | None:
    scanner = row.get('scanner_row') if isinstance(row.get('scanner_row'), dict) else {}
    return _safe_float((scanner or {}).get('change_percent') or row.get('change_percent'))


def build_candidate_snapshot(
    row: dict[str, Any],
    *,
    board: dict[str, Any],
    stage: str,
    rank: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    ist = _now_ist(now)
    sym = _normalize_symbol(row.get('ticker'))
    ref_price, ref_time = _row_price(row)
    catalyst = row.get('catalyst') if isinstance(row.get('catalyst'), dict) else {}
    freshness = board.get('market_freshness') if isinstance(board.get('market_freshness'), dict) else {}
    macro = board.get('macro_shock') if isinstance(board.get('macro_shock'), dict) else {}
    return {
        'snapshot_id': uuid.uuid4().hex[:16],
        'session_date': str(board.get('source_session_date') or board.get('session_date') or _session_date(ist)),
        'snapshot_time_ist': ist.strftime('%H:%M'),
        'snapshot_at': ist.replace(microsecond=0).isoformat(),
        'stage': stage,
        'symbol': sym,
        'rank': rank,
        'score': int(row.get('score') or 0),
        'confidence': int(row.get('score') or 0),
        'state': str(row.get('state') or ''),
        'action': str(row.get('state') or ''),
        'catalyst_status': str(row.get('catalyst_state') or row.get('catalyst_status') or ''),
        'verification_status': str(row.get('verification_status') or catalyst.get('verification_status') or ''),
        'matched_source': str(row.get('matched_source') or catalyst.get('source') or ''),
        'news_headline': str(catalyst.get('headline') or row.get('catalyst_line') or '')[:200],
        'news_source': str(catalyst.get('source') or row.get('matched_source') or ''),
        'feed_ids': list(row.get('feed_ids') or []),
        'news_ids': list(row.get('news_ids') or []),
        'macro_regime': str(board.get('macro_regime') or macro.get('regime') or ''),
        'scanner_freshness': str(board.get('scanner_freshness_status') or (freshness.get('scanner') or {}).get('freshness_status') or ''),
        'gainers_freshness': str(board.get('gainers_freshness_status') or (freshness.get('gainers') or {}).get('freshness_status') or ''),
        'volume_participation': _row_volume_ratio(row),
        'price_move_at_snapshot': _row_change_pct(row),
        'pattern_label': str(row.get('chart_pattern') or row.get('pattern_label') or ''),
        'sector_theme': ' + '.join(row.get('themes') or [])[:120],
        'reason_text': ' + '.join(row.get('why') or [])[:200],
        'risk_text': ' + '.join(row.get('risk_filters') or row.get('why') or [])[:120],
        'reference_price': ref_price,
        'reference_price_time': ref_time,
        'previous_mover': bool(row.get('previous_mover') or row.get('previous_session_mover')),
        'has_catalyst': bool(row.get('has_catalyst') or row.get('catalyst_line')),
        'stage_version': STAGE,
    }


def capture_quality_snapshots(
    *,
    board: dict[str, Any],
    candidates: list[dict[str, Any]],
    stage: str,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Persist quality-gated candidate snapshots for learning."""
    if stage in EXCLUDED_FROM_MAIN_STATS:
        return []
    if board.get('reference_only') or board.get('session_stale'):
        return []
    if board.get('quality_tradecard_blocked') or board.get('live_confirmation_blocked') or board.get('stale_after_auto_refresh'):
        print(f'[CANDIDATE_OUTCOME_LEARNING] stage={stage} skipped=stale_scanner', flush=True)
        return []
    quality = filter_quality_candidates(candidates)
    if not quality and stage in PRIMARY_STAGES:
        print(f'[CANDIDATE_OUTCOME_LEARNING] stage={stage} quality=0', flush=True)
    day = str(board.get('source_session_date') or board.get('session_date') or _session_date(now))[:10]
    existing_keys = {
        f"{s.get('session_date')}|{s.get('stage')}|{s.get('symbol')}"
        for s in _load_jsonl(_snapshots_path())
        if str(s.get('session_date') or '')[:10] == day
    }
    stored: list[dict[str, Any]] = []
    for idx, row in enumerate(quality, start=1):
        sym = _normalize_symbol(row.get('ticker'))
        dedupe_key = f'{day}|{stage}|{sym}'
        if dedupe_key in existing_keys:
            continue
        snap = build_candidate_snapshot(row, board=board, stage=stage, rank=idx, now=now)
        _append_jsonl(_snapshots_path(), snap)
        stored.append(snap)
        existing_keys.add(dedupe_key)
        print(
            f'[CANDIDATE_SNAPSHOT] stage={stage} symbol={snap.get("symbol")} '
            f'rank={idx} score={snap.get("score")}',
            flush=True,
        )
    return stored


def _parse_ts(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    except ValueError:
        return None


def _session_from_ts(ts: datetime | None) -> str:
    if ts is None:
        return ''
    return ts.astimezone(IST).date().isoformat()


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _broker_eod_price(symbol: str, session_date: str) -> tuple[float | None, float | None, float | None, str, bool]:
    """Broker/EOD tier — local broker cache + historical close."""
    sym = _normalize_symbol(symbol)
    close = high = low = None
    source = ''
    stale = False
    for rel in ('broker_app_collector_latest.json', 'broker_intelligence_cache.json', 'daily_report_pack_latest.json'):
        data = _load_json_file(get_data_path(rel))
        if not data:
            continue
        ts = _parse_ts(data.get('generated_at') or data.get('last_updated') or data.get('timestamp'))
        if ts and _session_from_ts(ts) != session_date:
            stale = True
        for row in data.get('rows') or data.get('picks') or data.get('items') or []:
            if not isinstance(row, dict):
                continue
            if _normalize_symbol(row.get('ticker') or row.get('symbol')) != sym:
                continue
            close = _safe_float(row.get('close') or row.get('ltp') or row.get('price'))
            high = _safe_float(row.get('high')) or close
            low = _safe_float(row.get('low')) or close
            if close:
                source = rel
                break
        if close:
            break
    if close is None:
        try:
            from backend.analytics.actual_learning_resolver import capture_eod_price_evidence

            evidence = capture_eod_price_evidence([sym], session_date=session_date)
            rows = evidence.get(sym) or []
            if rows:
                last = rows[-1]
                close = _safe_float(last.get('price'))
                high = _safe_float(last.get('high')) or close
                low = _safe_float(last.get('low')) or close
                if close:
                    source = str(last.get('source') or 'eod_price_evidence')
        except Exception:
            pass
    if close is None:
        try:
            from backend.storage.historical_market_store import get_historical_db_path, get_prices

            if get_historical_db_path().exists():
                rows = get_prices(ticker=sym, market='NSE', to_date=session_date, limit=3)
                for row in reversed(rows):
                    if int(row.get('fake_prices') or 0):
                        continue
                    c = _safe_float(row.get('close'))
                    if c and c > 0:
                        close = c
                        high = _safe_float(row.get('high')) or c
                        low = _safe_float(row.get('low')) or c
                        source = 'historical_market_store'
                        break
        except Exception:
            pass
    return close, high, low, source, stale and not source


def _intraday_price_path(
    symbol: str,
    *,
    session_date: str,
    reference_price: float,
) -> tuple[float | None, float | None, float | None, str, bool]:
    sym = _normalize_symbol(symbol)
    high = low = close = None
    stale = False
    try:
        from backend.trading.intraday_candle_memory import load_recent_candles

        candles = load_recent_candles(sym, session_date=session_date, limit=500)
        highs: list[float] = []
        lows: list[float] = []
        closes: list[float] = []
        for c in candles:
            h = _safe_float(c.get('high'))
            l = _safe_float(c.get('low'))
            cl = _safe_float(c.get('close') or c.get('price') or c.get('ltp'))
            if h and h > 0:
                highs.append(h)
            if l and l > 0:
                lows.append(l)
            if cl and cl > 0:
                closes.append(cl)
        if closes:
            high = max(highs) if highs else max(closes)
            low = min(lows) if lows else min(closes)
            close = closes[-1]
            return close, high, low, 'intraday_candle_memory', stale
    except Exception:
        pass
    return None, None, None, '', stale


def _scanner_gainer_price(symbol: str, session_date: str) -> tuple[float | None, float | None, float | None, str, bool]:
    sym = _normalize_symbol(symbol)
    stale = False
    scanner = _load_json_file(get_data_path('scanner_data.json'))
    if scanner:
        ts = _parse_ts(scanner.get('last_updated') or scanner.get('scan_time_local'))
        if ts and _session_from_ts(ts) != session_date:
            stale = True
        for key in ('top_signals', 'all_signals', 'signals'):
            for row in scanner.get(key) or []:
                if not isinstance(row, dict):
                    continue
                if _normalize_symbol(row.get('ticker') or row.get('symbol')) != sym:
                    continue
                close = _safe_float(row.get('price') or row.get('ltp') or row.get('close'))
                high = _safe_float(row.get('high')) or close
                low = _safe_float(row.get('low')) or close
                if close:
                    return close, high, low, 'scanner_data', stale
    try:
        from backend.analytics.actual_learning_resolver import capture_eod_price_evidence

        evidence = capture_eod_price_evidence([sym], session_date=session_date)
        rows = evidence.get(sym) or []
        if rows:
            last = rows[-1]
            close = _safe_float(last.get('price'))
            high = _safe_float(last.get('high')) or close
            low = _safe_float(last.get('low')) or close
            if close:
                return close, high, low, str(last.get('source') or 'scanner_gainer_cache'), stale
    except Exception:
        pass
    return None, None, None, '', stale


def _quote_cache_price(symbol: str, session_date: str) -> tuple[float | None, float | None, float | None, str, bool]:
    sym = _normalize_symbol(symbol)
    stale = False
    try:
        from backend.storage.market_memory_outcomes import load_latest_market_data, lookup_latest_price

        for rel in ('latest_market_data_memory_enriched.json', 'latest_market_data.json'):
            market = load_latest_market_data(get_data_path(rel)) or {}
            ts = _parse_ts(market.get('last_updated') or market.get('generated_at'))
            if ts and _session_from_ts(ts) != session_date:
                stale = True
            close = lookup_latest_price(market, sym)
            if close:
                entry = (market.get('prices') or {}).get(sym) or {}
                high = _safe_float(entry.get('high') if isinstance(entry, dict) else None) or close
                low = _safe_float(entry.get('low') if isinstance(entry, dict) else None) or close
                return close, high, low, rel, stale
    except Exception:
        pass
    return None, None, None, '', stale


def _price_path_after_reference(
    symbol: str,
    *,
    session_date: str,
    reference_price: float,
) -> dict[str, Any]:
    """
    Resolve close/MFE/MAE using ordered local sources only — never AI.
    Order: broker/EOD → intraday → scanner/gainer → quote cache → public fallback.
    """
    if reference_price <= 0:
        return {
            'close_price': None,
            'high_after_reference': None,
            'low_after_reference': None,
            'close_return_pct': None,
            'max_favorable_excursion_pct': None,
            'max_adverse_excursion_pct': None,
            'price_source': '',
            'pending_reason': 'no_reference_price',
        }

    tiers: list[tuple[str, Callable[..., tuple]]] = [
        ('broker_eod', _broker_eod_price),
        ('intraday', lambda s, d: _intraday_price_path(s, session_date=d, reference_price=reference_price)),
        ('scanner_gainer', _scanner_gainer_price),
        ('quote_cache', _quote_cache_price),
    ]
    close = high = low = None
    source = ''
    stale_flag = False
    for _name, fn in tiers:
        try:
            if _name == 'intraday':
                c, h, l, src, stale = fn(symbol, session_date)
            else:
                c, h, l, src, stale = fn(symbol, session_date)
        except Exception:
            continue
        if c and c > 0:
            close, high, low, source, stale_flag = c, h or c, l or c, src, stale
            break

    if close is None:
        return {
            'close_price': None,
            'high_after_reference': None,
            'low_after_reference': None,
            'close_return_pct': None,
            'max_favorable_excursion_pct': None,
            'max_adverse_excursion_pct': None,
            'price_source': '',
            'pending_reason': 'missing_price_data',
        }

    if stale_flag:
        return {
            'close_price': close,
            'high_after_reference': high,
            'low_after_reference': low,
            'close_return_pct': None,
            'max_favorable_excursion_pct': None,
            'max_adverse_excursion_pct': None,
            'price_source': source,
            'pending_reason': 'stale_price_data',
        }

    high = max(reference_price, high or close, close)
    low = min(reference_price, low or close, close)
    close_return = ((close - reference_price) / reference_price) * 100.0
    mfe = ((high - reference_price) / reference_price) * 100.0
    mae = ((low - reference_price) / reference_price) * 100.0
    return {
        'close_price': close,
        'high_after_reference': high,
        'low_after_reference': low,
        'close_return_pct': round(close_return, 3),
        'max_favorable_excursion_pct': round(mfe, 3),
        'max_adverse_excursion_pct': round(mae, 3),
        'price_source': source,
        'pending_reason': '',
    }


def classify_outcome(metrics: dict[str, Any]) -> tuple[str, str]:
    pending = str(metrics.get('pending_reason') or '').strip()
    if pending in ('missing_price_data', 'stale_price_data', 'no_reference_price', 'no_price_data'):
        return OUTCOME_PENDING, pending
    mfe = _safe_float(metrics.get('max_favorable_excursion_pct'))
    mae = _safe_float(metrics.get('max_adverse_excursion_pct'))
    close_ret = _safe_float(metrics.get('close_return_pct'))
    if mfe is None and mae is None and close_ret is None:
        return OUTCOME_PENDING, 'no_price_data'
    if (mfe is not None and mfe >= WIN_MFE_PCT) or (close_ret is not None and close_ret >= WIN_CLOSE_PCT):
        return OUTCOME_WIN, ''
    if (mae is not None and mae <= LOSS_MAE_PCT) or (close_ret is not None and close_ret <= LOSS_CLOSE_PCT):
        return OUTCOME_LOSS, ''
    return OUTCOME_NEUTRAL, ''


def generate_reason_tags(snapshot: dict[str, Any], outcome: str) -> list[str]:
    tags: list[str] = []
    vol = _safe_float(snapshot.get('volume_participation')) or 0.0
    scanner_fresh = str(snapshot.get('scanner_freshness') or '').upper()
    verify = str(snapshot.get('verification_status') or '').upper()
    state = str(snapshot.get('state') or '').upper()
    macro = str(snapshot.get('macro_regime') or '').upper()
    if outcome == OUTCOME_WIN:
        if verify in ('VERIFIED', 'PARTIALLY_VERIFIED'):
            tags.append('verified_stock_specific_news')
        if 'OFFICIAL' in str(snapshot.get('matched_source') or '').upper() or snapshot.get('stage') == 'final_0931':
            if verify.startswith('VER'):
                tags.append('official_source_confirmed')
        if scanner_fresh == 'CURRENT':
            tags.append('fresh_scanner_confirmed')
        if vol >= 5:
            tags.append('volume_above_5x')
        elif vol >= 2:
            tags.append('volume_above_2x')
        if 'RED' in macro and (_safe_float(snapshot.get('price_move_at_snapshot')) or 0) > 0:
            tags.append('relative_strength_in_red_market')
        if not tags:
            tags.append('fresh_scanner_confirmed')
    elif outcome == OUTCOME_LOSS:
        if snapshot.get('previous_mover'):
            tags.append('stale_previous_session_mover')
        if scanner_fresh in ('STALE', 'MISSING', 'PREVIOUS_SESSION'):
            tags.append('weak_scanner_freshness')
        if state in ('CHASE_RISK', 'PULLBACK_ONLY_PLAN'):
            tags.append('high_chase_risk')
        if vol < 1.2:
            tags.append('no_volume_followthrough')
        if 'RED' in macro:
            tags.append('macro_red_market_pressure')
        if verify == 'UNVERIFIED':
            tags.append('unverified_feed')
        if not snapshot.get('has_catalyst'):
            tags.append('price_volume_only_no_catalyst')
        if not tags:
            tags.append('news_not_enough_without_live_strength')
    return tags[:6]


def deterministic_reason_summary(tags: list[str], outcome: str) -> str:
    if not tags:
        if outcome == OUTCOME_PENDING:
            return 'Pending price data for outcome resolution.'
        return 'Outcome resolved from price path; no strong contextual tag.'
    return '; '.join(t.replace('_', ' ') for t in tags[:4])


def needs_ai_explanation(
    snapshot: dict[str, Any],
    outcome: str,
    tags: list[str],
    *,
    score: int,
) -> bool:
    if outcome not in (OUTCOME_WIN, OUTCOME_LOSS):
        return False
    if len(tags) >= 2:
        return False
    if outcome == OUTCOME_LOSS and int(snapshot.get('confidence') or snapshot.get('score') or 0) >= 70:
        return True
    if outcome == OUTCOME_WIN and len(tags) <= 1:
        return True
    if outcome == OUTCOME_WIN and 'RED' in str(snapshot.get('macro_regime') or '').upper():
        return True
    return score >= 65 and len(tags) < 2


def run_ai_explainer(
    snapshot: dict[str, Any],
    outcome_record: dict[str, Any],
) -> dict[str, Any]:
    """AI fallback — compact explainer only; never overrides price outcome."""
    if str(outcome_record.get('outcome') or '') not in (OUTCOME_WIN, OUTCOME_LOSS):
        return {'ai_explain_status': 'SKIPPED', 'ai_reason_summary': '', 'ai_reason_tags': []}

    payload = {
        'symbol': snapshot.get('symbol'),
        'stage': snapshot.get('stage'),
        'score': snapshot.get('score'),
        'outcome': outcome_record.get('outcome'),
        'reference_price': snapshot.get('reference_price'),
        'close_return_pct': outcome_record.get('close_return_pct'),
        'mfe_pct': outcome_record.get('max_favorable_excursion_pct'),
        'mae_pct': outcome_record.get('max_adverse_excursion_pct'),
        'news_headline': snapshot.get('news_headline'),
        'verification_status': snapshot.get('verification_status'),
        'volume_participation': snapshot.get('volume_participation'),
        'macro_regime': snapshot.get('macro_regime'),
        'reason_tags': outcome_record.get('reason_tags'),
        'sector_theme': snapshot.get('sector_theme'),
    }
    prompt = (
        'Explain in 2 short sentences why this paper-research tradecard candidate '
        f'likely {outcome_record.get("outcome")}. Use only this JSON context. '
        'Do not invent prices, hidden facts, or trade advice. JSON:\n'
        f'{json.dumps(payload, ensure_ascii=False)}'
    )
    try:
        from backend.ai.ai_pool_router import (
            OUTCOME_EXPLAINER_USE_CASE,
            execute_pooled_ai,
            should_escalate_outcome_explainer_to_claude,
        )

        allow_claude = should_escalate_outcome_explainer_to_claude(
            snapshot,
            outcome_record,
            prior_failed_or_weak=False,
        )
        result = execute_pooled_ai(
            prompt,
            use_case=OUTCOME_EXPLAINER_USE_CASE,
            max_tokens=180,
            allow_claude=allow_claude,
        )
        if not result.get('success') or not result.get('text'):
            if not allow_claude and should_escalate_outcome_explainer_to_claude(
                snapshot, outcome_record, prior_failed_or_weak=True,
            ):
                result = execute_pooled_ai(
                    prompt,
                    use_case=OUTCOME_EXPLAINER_USE_CASE,
                    max_tokens=180,
                    allow_claude=True,
                )
        if result.get('success') and result.get('text'):
            return {
                'ai_explain_status': 'OK',
                'ai_reason_summary': str(result['text']).strip()[:400],
                'ai_reason_tags': list(outcome_record.get('reason_tags') or [])[:4],
                'explanation_confidence': float(result.get('explanation_confidence') or 0.6),
                'model_used': str(result.get('model') or ''),
                'provider_used': str(result.get('provider_used') or ''),
                'key_slot_used': str(result.get('key_slot_used') or ''),
            }
        return {
            'ai_explain_status': str(result.get('ai_explain_status') or 'FAILED'),
            'ai_reason_summary': '',
            'ai_reason_tags': list(outcome_record.get('reason_tags') or [])[:4],
            'missing_data_note': str(result.get('error') or '')[:120],
        }
    except Exception as exc:
        return {
            'ai_explain_status': 'SKIPPED',
            'ai_reason_summary': '',
            'ai_reason_tags': [],
            'missing_data_note': str(exc)[:120],
        }


def resolve_candidate_outcomes(
    *,
    session_date: str | None = None,
    run_ai: bool = True,
) -> dict[str, Any]:
    """15:45 / close review — resolve primary-stage snapshots against EOD data."""
    day = session_date or _session_date()
    snapshots = [
        s for s in _load_jsonl(_snapshots_path())
        if str(s.get('session_date') or '')[:10] == day
        and str(s.get('stage') or '') in PRIMARY_STAGES
    ]
    existing = {
        str(o.get('snapshot_id') or ''): o
        for o in _load_jsonl(_outcomes_path())
        if str(o.get('session_date') or '')[:10] == day
    }
    resolved: list[dict[str, Any]] = []
    ai_used = 0
    ai_skipped = 0
    for snap in snapshots:
        sid = str(snap.get('snapshot_id') or '')
        if sid in existing:
            resolved.append(existing[sid])
            continue
        ref = _safe_float(snap.get('reference_price'))
        if not ref or ref <= 0:
            outcome_rec = {
                **snap,
                'outcome': OUTCOME_PENDING,
                'pending_reason': 'no_reference_price',
                'reason_tags': [],
                'reason_summary': 'No reference price at snapshot — outcome pending.',
                'resolved_at': _now_ist().isoformat(),
            }
            _append_jsonl(_outcomes_path(), outcome_rec)
            resolved.append(outcome_rec)
            continue
        metrics = _price_path_after_reference(
            str(snap.get('symbol') or ''),
            session_date=day,
            reference_price=ref,
        )
        pending_from_metrics = str(metrics.get('pending_reason') or '').strip()
        outcome, pending_reason = classify_outcome(metrics)
        if outcome == OUTCOME_PENDING:
            outcome_rec = {
                **snap,
                **metrics,
                'outcome': OUTCOME_PENDING,
                'pending_reason': pending_reason or pending_from_metrics or 'missing_price_data',
                'reason_tags': [],
                'reason_summary': 'Price data unavailable for EOD resolution.',
                'resolved_at': _now_ist().isoformat(),
            }
            _append_jsonl(_outcomes_path(), outcome_rec)
            resolved.append(outcome_rec)
            continue
        tags = generate_reason_tags(snap, outcome)
        summary = deterministic_reason_summary(tags, outcome)
        outcome_rec = {
            **snap,
            **metrics,
            'outcome': outcome,
            'pending_reason': '',
            'reason_tags': tags,
            'reason_summary': summary,
            'ai_explain_needed': needs_ai_explanation(snap, outcome, tags, score=int(snap.get('score') or 0)),
            'resolved_at': _now_ist().isoformat(),
        }
        if run_ai and outcome_rec.get('ai_explain_needed') and ai_used < AI_EXPLAIN_CAP:
            ai_payload = run_ai_explainer(snap, outcome_rec)
            outcome_rec.update(ai_payload)
            if ai_payload.get('ai_explain_status') == 'OK':
                ai_used += 1
            else:
                ai_skipped += 1
        else:
            outcome_rec['ai_explain_status'] = 'SKIPPED'
            if outcome_rec.get('ai_explain_needed'):
                ai_skipped += 1
        _append_jsonl(_outcomes_path(), outcome_rec)
        _update_learning_aggregate(outcome_rec)
        resolved.append(outcome_rec)

    state = {
        'session_date': day,
        'resolved_count': len(resolved),
        'ai_explanations_used': ai_used,
        'ai_explanations_skipped': ai_skipped,
        'updated_at': _now_ist().isoformat(),
    }
    try:
        _state_path().write_text(json.dumps(state, indent=2), encoding='utf-8')
    except OSError:
        pass
    print(
        f'[CANDIDATE_OUTCOME_RESOLVE] date={day} resolved={len(resolved)} '
        f'ai_used={ai_used} ai_skipped={ai_skipped}',
        flush=True,
    )
    return {
        'session_date': day,
        'resolved': resolved,
        'ai_used': ai_used,
        'ai_skipped': ai_skipped,
    }


def _update_learning_aggregate(outcome_rec: dict[str, Any]) -> None:
    key = '|'.join([
        str(outcome_rec.get('symbol') or ''),
        str(outcome_rec.get('catalyst_status') or ''),
        str(outcome_rec.get('verification_status') or ''),
        str(outcome_rec.get('macro_regime') or ''),
        str(outcome_rec.get('pattern_label') or ''),
    ])
    vol = _safe_float(outcome_rec.get('volume_participation')) or 0.0
    vol_bucket = '5x+' if vol >= 5 else '2x+' if vol >= 2 else 'low'
    record = {
        'aggregate_key': key,
        'symbol': outcome_rec.get('symbol'),
        'catalyst_type': outcome_rec.get('catalyst_status'),
        'verification_status': outcome_rec.get('verification_status'),
        'macro_regime': outcome_rec.get('macro_regime'),
        'scanner_freshness': outcome_rec.get('scanner_freshness'),
        'volume_bucket': vol_bucket,
        'pattern_label': outcome_rec.get('pattern_label'),
        'outcome': outcome_rec.get('outcome'),
        'close_return_pct': outcome_rec.get('close_return_pct'),
        'mfe_pct': outcome_rec.get('max_favorable_excursion_pct'),
        'mae_pct': outcome_rec.get('max_adverse_excursion_pct'),
        'reason_tags': outcome_rec.get('reason_tags') or [],
        'session_date': outcome_rec.get('session_date'),
        'recorded_at': _now_ist().isoformat(),
        'stage_version': STAGE,
    }
    _append_jsonl(_learning_path(), record)
    try:
        from backend.trading.weekly_signal_capture import capture_outcome_learning_signal

        capture_outcome_learning_signal(outcome_rec)
    except Exception:
        pass


def learning_stats() -> dict[str, Any]:
    snapshots = _load_jsonl(_snapshots_path())
    outcomes = _load_jsonl(_outcomes_path())
    learning = _load_jsonl(_learning_path())
    state = {}
    try:
        if _state_path().is_file():
            state = json.loads(_state_path().read_text(encoding='utf-8'))
    except Exception:
        state = {}
    return {
        'candidate_snapshots': len(snapshots),
        'candidate_outcomes': len(outcomes),
        'candidate_learning_records': len(learning),
        'ai_explanations_used_today': int(state.get('ai_explanations_used') or 0),
    }


def _group_outcomes_by_stage(outcomes: list[dict[str, Any]], stage: str) -> dict[str, list[str]]:
    groups = {OUTCOME_WIN: [], OUTCOME_LOSS: [], OUTCOME_NEUTRAL: [], OUTCOME_PENDING: []}
    for row in outcomes:
        if str(row.get('stage') or '') != stage:
            continue
        sym = _normalize_symbol(row.get('symbol'))
        if not sym:
            continue
        bucket = str(row.get('outcome') or OUTCOME_PENDING)
        if bucket not in groups:
            bucket = OUTCOME_PENDING
        groups[bucket].append(sym)
    return groups


def format_candidate_outcome_learning_block(
    *,
    session_date: str | None = None,
) -> list[str]:
    day = session_date or _session_date()
    outcomes = [
        o for o in _load_jsonl(_outcomes_path())
        if str(o.get('session_date') or '')[:10] == day
    ]
    if not outcomes:
        snapshots = [
            s for s in _load_jsonl(_snapshots_path())
            if str(s.get('session_date') or '')[:10] == day
        ]
        if not snapshots:
            return [
                'No quality snapshots today.',
                'Reason: 52I was not active during 09:20/09:31 capture window OR no candidate scored above 60.',
                'Next capture: next market session 09:20/09:31.',
            ]
        return ['Candidate outcome learning: snapshots captured; EOD resolution pending.']

    lines = ['', '<b>Candidate Outcome Learning</b>', '']
    state = {}
    try:
        if _state_path().is_file():
            state = json.loads(_state_path().read_text(encoding='utf-8'))
    except Exception:
        pass

    for stage_label, stage_key in (
        ('09:20 Quality Tradecards', 'opening_0920'),
        ('09:31 Final Confirmation', 'final_0931'),
    ):
        groups = _group_outcomes_by_stage(outcomes, stage_key)
        tracked = sum(len(v) for v in groups.values())
        lines.append(f'<b>{stage_label}:</b>')
        lines.append(f'Tracked: {tracked}')
        lines.append(f'Won: {len(groups[OUTCOME_WIN])} — {", ".join(groups[OUTCOME_WIN][:6]) or "—"}')
        lines.append(f'Lost: {len(groups[OUTCOME_LOSS])} — {", ".join(groups[OUTCOME_LOSS][:6]) or "—"}')
        lines.append(f'Neutral: {len(groups[OUTCOME_NEUTRAL])} — {", ".join(groups[OUTCOME_NEUTRAL][:6]) or "—"}')
        lines.append(f'Pending data: {len(groups[OUTCOME_PENDING])} — {", ".join(groups[OUTCOME_PENDING][:6]) or "—"}')
        lines.append('')

    winners = [o for o in outcomes if o.get('outcome') == OUTCOME_WIN][:4]
    losers = [o for o in outcomes if o.get('outcome') == OUTCOME_LOSS][:4]
    if winners:
        lines.append('<b>Winner reasons:</b>')
        for row in winners:
            sym = row.get('symbol')
            summary = row.get('ai_reason_summary') or row.get('reason_summary') or '—'
            tags = ', '.join(row.get('reason_tags') or []) or '—'
            lines.append(f'- {sym}: {summary} [{tags}]')
        lines.append('')
    if losers:
        lines.append('<b>Loser reasons:</b>')
        for row in losers:
            sym = row.get('symbol')
            summary = row.get('ai_reason_summary') or row.get('reason_summary') or '—'
            tags = ', '.join(row.get('reason_tags') or []) or '—'
            lines.append(f'- {sym}: {summary} [{tags}]')
        lines.append('')

    ai_used = int(state.get('ai_explanations_used') or 0)
    ai_skipped = int(state.get('ai_explanations_skipped') or 0)
    lines.extend([
        '<b>AI explanations:</b>',
        f'Used: {ai_used}',
        f'Skipped: {ai_skipped}',
        f'Budget/cap: {"ok" if ai_used < AI_EXPLAIN_CAP else "cap_reached"}',
    ])
    return lines


def format_learn_today_telegram(*, session_date: str | None = None) -> str:
    """Read-only view — snapshots/resolution auto-run on schedule; no save side effects."""
    day = session_date or _session_date()
    lines = [f'<b>/learn today — {day}</b>', '<i>Read-only — auto-captured at 09:20/09:31</i>', '']
    lines.extend(format_candidate_outcome_learning_block(session_date=day))
    lines.append('')
    lines.append('<i>Paper/research only — simulated outcome, not real P&amp;L</i>')
    return '\n'.join(lines)


def format_learn_symbol_telegram(symbol: str) -> str:
    sym = _normalize_symbol(symbol)
    rows = [r for r in _load_jsonl(_learning_path()) if _normalize_symbol(r.get('symbol')) == sym]
    if not rows:
        return f'<b>/learn symbol {sym}</b>\n\nNo outcome memory for {sym} yet.'
    wins = sum(1 for r in rows if r.get('outcome') == OUTCOME_WIN)
    losses = sum(1 for r in rows if r.get('outcome') == OUTCOME_LOSS)
    neutrals = sum(1 for r in rows if r.get('outcome') == OUTCOME_NEUTRAL)
    pending = sum(1 for r in rows if r.get('outcome') == OUTCOME_PENDING)
    lines = [
        f'<b>/learn symbol {sym}</b>',
        '',
        f'Samples: {len(rows)}',
        f'W/L/N/P: {wins}/{losses}/{neutrals}/{pending}',
    ]
    tag_counts: dict[str, int] = {}
    for row in rows:
        for tag in row.get('reason_tags') or []:
            tag_counts[str(tag)] = tag_counts.get(str(tag), 0) + 1
    if tag_counts:
        best = sorted(tag_counts.items(), key=lambda kv: kv[1], reverse=True)[:4]
        lines.append('Top tags: ' + ', '.join(f'{k}({v})' for k, v in best))
    return '\n'.join(lines)


def format_learn_patterns_telegram() -> str:
    rows = _load_jsonl(_learning_path(), limit=5000)
    if not rows:
        return '<b>/learn patterns</b>\n\nNo candidate learning records yet.'
    win_tags: dict[str, int] = {}
    loss_tags: dict[str, int] = {}
    for row in rows:
        bucket = win_tags if row.get('outcome') == OUTCOME_WIN else loss_tags
        for tag in row.get('reason_tags') or []:
            bucket[str(tag)] = bucket.get(str(tag), 0) + 1
    best = sorted(win_tags.items(), key=lambda kv: kv[1], reverse=True)[:5]
    worst = sorted(loss_tags.items(), key=lambda kv: kv[1], reverse=True)[:5]
    lines = [
        '<b>/learn patterns</b>',
        '',
        '<b>Best reason tags:</b>',
    ]
    lines.extend([f'- {k}: {v}' for k, v in best] or ['- —'])
    lines.append('')
    lines.append('<b>Worst reason tags:</b>')
    lines.extend([f'- {k}: {v}' for k, v in worst] or ['- —'])
    return '\n'.join(lines)
