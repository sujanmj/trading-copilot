"""
Opening Rally Radar — Phase 4B.0.

Early-layer rally candidate board before /tradecard single pick.
Paper/research only — no execution, no LLM calls.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from backend.utils.config import DATA_DIR

IST = ZoneInfo('Asia/Kolkata')
STAGE = '4B.1'
SCANNER_FILE = DATA_DIR / 'scanner_data.json'
CATALYST_FILE = DATA_DIR / 'stock_catalyst_radar_latest.json'
PREMARKET_FILE = DATA_DIR / 'premarket_conviction_latest.json'

RADAR_STATES = frozenset({
    'RADAR_ARMED',
    'VOLUME_IGNITION',
    'TRADECARD_CANDIDATE',
    'MOMENTUM_ONLY_WATCH',
    'CHASE_RISK',
    'REJECTED',
})

DIRECT_CATALYST_TYPES = frozenset({
    'ORDER_WIN',
    'PROJECT_ANNOUNCEMENT',
    'ACQUISITION',
    'STAKE_BUY',
    'AI_INVESTMENT',
    'REGULATORY_APPROVAL',
    'BROKER_UPGRADE',
    'TARGET_UPGRADE',
    'RESULT_ALERT',
})

VOLUME_IGNITION_MIN = 2.0
EXTENDED_MOVE_PCT = 4.5


def _now_ist(now: datetime | None = None) -> datetime:
    if now is not None:
        if now.tzinfo is None:
            return now.replace(tzinfo=IST)
        return now.astimezone(IST)
    return datetime.now(IST)


def _normalize_ticker(value: object) -> str:
    return str(value or '').strip().upper()


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value in (None, ''):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _minutes_since_midnight(now: datetime) -> int:
    local = _now_ist(now)
    return local.hour * 60 + local.minute


def opening_radar_time_phase(now: datetime | None = None) -> str:
    """IST timing bucket for opening rally state machine."""
    mins = _minutes_since_midnight(_now_ist(now))
    if mins < 8 * 60 + 30:
        return 'PRE_ARMED'
    if mins < 9 * 60 + 15:
        return 'ARMED'
    if mins < 9 * 60 + 18:
        return 'OBSERVE'
    if mins < 9 * 60 + 23:
        return 'IGNITION'
    if mins < 9 * 60 + 31:
        return 'CONFIRMATION'
    if mins < 9 * 60 + 35:
        return 'POST_CONFIRM'
    if mins < 9 * 60 + 46:
        return 'CHASE'
    return 'AFTER'


def _catalyst_map(payload: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    data = payload if payload is not None else _load_json(CATALYST_FILE)
    out: dict[str, dict[str, Any]] = {}
    for row in (data.get('priority_list') or data.get('items') or []):
        if not isinstance(row, dict):
            continue
        sym = _normalize_ticker(row.get('ticker'))
        if sym and sym not in out:
            out[sym] = row
    return out


def _scanner_index(payload: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    data = payload if payload is not None else _load_json(SCANNER_FILE)
    out: dict[str, dict[str, Any]] = {}
    for row in (data.get('top_signals') or data.get('signals') or []):
        if not isinstance(row, dict):
            continue
        sym = _normalize_ticker(row.get('ticker') or row.get('symbol'))
        if sym:
            out[sym] = row
    return out


def _live_registry() -> dict[str, str]:
    try:
        from backend.analytics.unified_decision_engine import build_live_rejection_set

        return build_live_rejection_set() or {}
    except Exception:
        return {}


def _theme_matches_for_ticker(sym: str) -> list[str]:
    """Return active theme basket ids that list this ticker."""
    matches: list[str] = []
    try:
        from backend.analytics.theme_baskets import load_theme_baskets

        for basket in load_theme_baskets().get('baskets') or []:
            if not isinstance(basket, dict):
                continue
            stocks = basket.get('stocks') or {}
            direct = {_normalize_ticker(t) for t in (stocks.get('direct') or [])}
            indirect = {_normalize_ticker(t) for t in (stocks.get('indirect') or [])}
            if sym in direct or sym in indirect:
                tid = str(basket.get('theme_id') or '')
                if tid:
                    matches.append(tid)
    except Exception:
        pass
    return matches


def _previous_session_movers(payload: dict[str, Any] | None = None) -> set[str]:
    data = payload if payload is not None else _load_json(PREMARKET_FILE)
    movers: set[str] = set()
    for row in data.get('previous_session_movers') or data.get('top_setups') or []:
        if not isinstance(row, dict):
            continue
        sym = _normalize_ticker(row.get('ticker'))
        if sym:
            movers.add(sym)
    scanner = _scanner_index()
    for sym, row in scanner.items():
        if abs(_safe_float(row.get('change_percent'))) >= 3.0:
            movers.add(sym)
    return movers


def _macro_risk_penalty() -> float:
    try:
        global_m = _load_json(DATA_DIR / 'global_markets_latest.json')
        sentiment = str(global_m.get('sentiment') or global_m.get('overall_sentiment') or '').lower()
        if any(term in sentiment for term in ('risk-off', 'risk off', 'bearish', 'weak')):
            return 12.0
    except Exception:
        pass
    return 0.0


def _has_direct_catalyst(catalyst: dict[str, Any] | None) -> bool:
    if not catalyst:
        return False
    ctype = str(catalyst.get('catalyst_type') or '').upper()
    side = str(catalyst.get('side') or '').upper()
    if side in ('BEARISH', 'RISK'):
        return False
    if ctype in DIRECT_CATALYST_TYPES:
        return True
    if side == 'BULLISH' and ctype not in ('GENERAL_NEWS', 'SECTOR_NEWS'):
        return True
    return False


def _price_strength(scanner_row: dict[str, Any] | None) -> tuple[bool, bool]:
    if not scanner_row:
        return False, False
    price = _safe_float(scanner_row.get('price') or scanner_row.get('last_price'))
    open_price = _safe_float(scanner_row.get('open_price') or scanner_row.get('open'))
    vwap = _safe_float(scanner_row.get('vwap'))
    above_open = bool(price and open_price and price >= open_price * 0.998)
    above_vwap = bool(price and vwap and price >= vwap * 0.998)
    return above_open, above_vwap


def _build_why_lines(
    *,
    catalyst: dict[str, Any] | None,
    themes: list[str],
    previous_mover: bool,
    volume_ratio: float,
    above_open: bool,
    above_vwap: bool,
) -> list[str]:
    parts: list[str] = []
    if catalyst and _has_direct_catalyst(catalyst):
        headline = str(catalyst.get('headline') or catalyst.get('title') or '').strip()
        if headline:
            parts.append(f'fresh {str(catalyst.get("catalyst_type") or "news").replace("_", " ").lower()}')
        else:
            parts.append('fresh company news')
    if themes:
        label = themes[0].replace('_', ' ')
        parts.append(f'{label} theme')
    if previous_mover:
        parts.append('previous-session mover')
    if volume_ratio >= 1.5:
        parts.append(f'volume {volume_ratio:.1f}x')
    if above_open:
        parts.append('above open')
    if above_vwap:
        parts.append('above VWAP')
    return parts or ['opening watch']


def score_opening_candidate(
    sym: str,
    *,
    catalyst: dict[str, Any] | None,
    scanner_row: dict[str, Any] | None,
    themes: list[str],
    previous_mover: bool,
    registry: dict[str, str],
    macro_penalty: float = 0.0,
    phase: str = '',
) -> dict[str, Any]:
    """Score one symbol for opening rally board."""
    if sym in registry:
        return {
            'ticker': sym,
            'score': 0,
            'state': 'REJECTED',
            'why': [f'hard avoid: {registry[sym][:80]}'],
            'has_catalyst': False,
            'volume_ratio': 0.0,
            'change_percent': 0.0,
        }

    score = 18.0
    has_catalyst = _has_direct_catalyst(catalyst)
    volume_ratio = _safe_float((scanner_row or {}).get('volume_ratio'), 0.0)
    change_pct = _safe_float((scanner_row or {}).get('change_percent'))
    above_open, above_vwap = _price_strength(scanner_row)

    if has_catalyst:
        cat_score = _safe_float((catalyst or {}).get('score'), 50.0)
        score += min(32.0, cat_score * 0.35 + 18.0)
    if themes:
        score += 12.0
    if previous_mover:
        score += 8.0
    if volume_ratio >= 1.2:
        score += min(28.0, volume_ratio * 5.5)
    if above_open:
        score += 10.0
    if above_vwap:
        score += 5.0
    if macro_penalty:
        score -= macro_penalty

    # momentum-only: volume without catalyst gets lower ceiling
    momentum_only = volume_ratio >= VOLUME_IGNITION_MIN and not has_catalyst and not themes
    if momentum_only:
        score = min(score, 62.0)

    extended = change_pct >= EXTENDED_MOVE_PCT or (
        phase in ('CHASE', 'POST_CONFIRM', 'AFTER') and change_pct >= 3.0
    )
    if extended and phase in ('CHASE', 'POST_CONFIRM', 'AFTER'):
        score -= 18.0

    why = _build_why_lines(
        catalyst=catalyst,
        themes=themes,
        previous_mover=previous_mover,
        volume_ratio=volume_ratio,
        above_open=above_open,
        above_vwap=above_vwap,
    )

    state = _resolve_state(
        score=int(round(max(0, score))),
        has_catalyst=has_catalyst,
        has_theme=bool(themes),
        previous_mover=previous_mover,
        volume_ratio=volume_ratio,
        change_pct=change_pct,
        above_open=above_open,
        momentum_only=momentum_only,
        extended=extended,
        phase=phase,
        catalyst_side=str((catalyst or {}).get('side') or '').upper(),
    )

    return {
        'ticker': sym,
        'score': int(round(max(0, score))),
        'state': state,
        'why': why,
        'has_catalyst': has_catalyst,
        'volume_ratio': round(volume_ratio, 2),
        'change_percent': round(change_pct, 2),
        'themes': themes,
        'previous_mover': previous_mover,
        'momentum_only': momentum_only,
        'catalyst': catalyst,
        'scanner_row': scanner_row,
    }


def _resolve_state(
    *,
    score: int,
    has_catalyst: bool,
    has_theme: bool,
    previous_mover: bool,
    volume_ratio: float,
    change_pct: float,
    above_open: bool,
    momentum_only: bool,
    extended: bool,
    phase: str,
    catalyst_side: str,
) -> str:
    if catalyst_side in ('BEARISH', 'RISK'):
        return 'REJECTED'

    armed_signal = has_catalyst or has_theme or previous_mover
    volume_signal = volume_ratio >= VOLUME_IGNITION_MIN
    strong_signal = score >= 82 and volume_ratio >= 3.0 and (has_catalyst or has_theme)

    if phase == 'PRE_ARMED':
        return 'RADAR_ARMED' if armed_signal else 'REJECTED'

    if phase == 'ARMED':
        return 'RADAR_ARMED' if armed_signal else 'REJECTED'

    if phase == 'OBSERVE':
        if strong_signal and armed_signal:
            return 'VOLUME_IGNITION'
        return 'RADAR_ARMED' if armed_signal else 'REJECTED'

    if phase == 'CHASE':
        if extended:
            return 'CHASE_RISK'
        if momentum_only:
            return 'MOMENTUM_ONLY_WATCH'
        return 'TRADECARD_CANDIDATE' if score >= 55 else 'RADAR_ARMED'

    if phase in ('POST_CONFIRM', 'AFTER') and extended:
        return 'CHASE_RISK'

    if momentum_only and not armed_signal:
        return 'MOMENTUM_ONLY_WATCH'

    if phase == 'IGNITION':
        if volume_signal and (armed_signal or above_open):
            return 'VOLUME_IGNITION'
        if armed_signal and not volume_signal:
            return 'RADAR_ARMED'
        if momentum_only:
            return 'MOMENTUM_ONLY_WATCH'
        return 'RADAR_ARMED' if armed_signal else 'REJECTED'

    if phase in ('CONFIRMATION', 'POST_CONFIRM'):
        if extended:
            return 'CHASE_RISK'
        if score >= 60 and (has_catalyst or (volume_signal and above_open)):
            return 'TRADECARD_CANDIDATE'
        if momentum_only:
            return 'MOMENTUM_ONLY_WATCH'
        if volume_signal:
            return 'VOLUME_IGNITION'
        return 'RADAR_ARMED' if armed_signal else 'REJECTED'

    if volume_signal and armed_signal:
        return 'VOLUME_IGNITION'
    if armed_signal:
        return 'RADAR_ARMED'
    if momentum_only:
        return 'MOMENTUM_ONLY_WATCH'
    return 'REJECTED'


def build_opening_rally_board(
    *,
    now: datetime | None = None,
    catalyst_payload: dict[str, Any] | None = None,
    scanner_payload: dict[str, Any] | None = None,
    premarket_payload: dict[str, Any] | None = None,
    registry: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build ranked opening rally candidate board."""
    ist_now = _now_ist(now)
    phase = opening_radar_time_phase(ist_now)
    catalyst_map = _catalyst_map(catalyst_payload)
    scanner_index = _scanner_index(scanner_payload)
    reg = registry if registry is not None else _live_registry()
    prev_movers = _previous_session_movers(premarket_payload)
    macro_penalty = _macro_risk_penalty()

    universe: set[str] = set(catalyst_map.keys()) | set(scanner_index.keys()) | prev_movers

    ranked: list[dict[str, Any]] = []
    for sym in universe:
        if not sym:
            continue
        themes = _theme_matches_for_ticker(sym)
        row = score_opening_candidate(
            sym,
            catalyst=catalyst_map.get(sym),
            scanner_row=scanner_index.get(sym),
            themes=themes,
            previous_mover=sym in prev_movers,
            registry=reg,
            macro_penalty=macro_penalty,
            phase=phase,
        )
        if row.get('state') == 'REJECTED' and row.get('score', 0) <= 0:
            continue
        ranked.append(row)

    ranked.sort(
        key=lambda r: (
            0 if r.get('state') == 'REJECTED' else 1,
            int(r.get('score') or 0),
            _safe_float(r.get('volume_ratio')),
        ),
        reverse=True,
    )

    payload = {
        'ok': True,
        'stage': STAGE,
        'generated_at': ist_now.replace(microsecond=0).isoformat(),
        'phase': phase,
        'time_ist': ist_now.strftime('%H:%M'),
        'ranked_candidates': ranked[:10],
        'macro_penalty': macro_penalty,
    }
    _log_opening_radar_events(payload)
    return payload


def _log_opening_radar_events(board: dict[str, Any]) -> None:
    for idx, row in enumerate(board.get('ranked_candidates') or [], start=1):
        sym = row.get('ticker')
        state = str(row.get('state') or '')
        score = int(row.get('score') or 0)
        why = ' + '.join(row.get('why') or [])
        if state == 'RADAR_ARMED':
            print(f'[OPENING_RADAR_ARMED] symbol={sym} reason={why}', flush=True)
        elif state == 'VOLUME_IGNITION':
            catalyst = 'yes' if row.get('has_catalyst') else 'no'
            print(
                f'[OPENING_VOLUME_IGNITION] symbol={sym} move={row.get("change_percent")} '
                f'volume={row.get("volume_ratio")} catalyst={catalyst}',
                flush=True,
            )
        elif state == 'TRADECARD_CANDIDATE':
            print(f'[OPENING_TRADECARD_CANDIDATE] symbol={sym} score={score} state={state}', flush=True)
        elif state == 'CHASE_RISK':
            print(f'[OPENING_CHASE_RISK] symbol={sym} reason=extended/late/no_pullback', flush=True)
        if sym:
            print(
                f'[MULTI_TRADECARD_RANK] symbol={sym} rank={idx} score={score} reason={why}',
                flush=True,
            )


def pick_best_opening_tradecard(
    board: dict[str, Any] | None = None,
) -> tuple[Optional[str], int, list[str]]:
    """Pick top tradecard candidate from opening board; log beat list."""
    data = board or build_opening_rally_board()
    candidates = [
        r for r in (data.get('ranked_candidates') or [])
        if r.get('state') in ('TRADECARD_CANDIDATE', 'VOLUME_IGNITION', 'MOMENTUM_ONLY_WATCH')
        and int(r.get('score') or 0) > 0
    ]
    if not candidates:
        candidates = [r for r in (data.get('ranked_candidates') or []) if r.get('state') != 'REJECTED']
    if not candidates:
        return None, 0, []

    best = candidates[0]
    sym = _normalize_ticker(best.get('ticker'))
    score = int(best.get('score') or 0)
    others = [
        _normalize_ticker(r.get('ticker'))
        for r in candidates[1:6]
        if _normalize_ticker(r.get('ticker')) and _normalize_ticker(r.get('ticker')) != sym
    ]
    if sym:
        print(f'[BEST_TRADECARD_SELECTED] symbol={sym} score={score} beat={",".join(others)}', flush=True)
    return sym or None, score, others


def select_synced_tradecard(
    *,
    now: datetime | None = None,
    board: dict[str, Any] | None = None,
    legacy_ticker: str = '',
) -> dict[str, Any]:
    """Align /tradecard selection with /tradecards opening-board best pick."""
    data = board or build_opening_rally_board(now=now)
    best_sym, best_score, _ = pick_best_opening_tradecard(data)
    tradecards_best = _normalize_ticker(best_sym)
    legacy = _normalize_ticker(legacy_ticker)

    best_row = next(
        (
            r for r in (data.get('ranked_candidates') or [])
            if _normalize_ticker(r.get('ticker')) == tradecards_best
        ),
        None,
    )
    state = str((best_row or {}).get('state') or '').upper()
    ist_now = _now_ist(now)
    mins = _minutes_since_midnight(ist_now)

    selected = tradecards_best
    source = 'radar'
    reason = 'aligned with /tradecards best pick'
    status_override = ''

    if not tradecards_best:
        selected = legacy
        source = 'legacy'
        reason = 'no opening-board candidates'
    elif state == 'REJECTED':
        selected = legacy or tradecards_best
        source = 'legacy' if legacy and legacy != tradecards_best else 'radar'
        reason = 'radar best rejected on opening board'
    elif state == 'CHASE_RISK' and mins >= 9 * 60 + 40:
        status_override = 'NO_ACTIVE_ENTRY'
        reason = 'CHASE_RISK after 09:40 — pullback only, no fresh entry'
    elif legacy and legacy != tradecards_best:
        reason = f'radar board best {tradecards_best} overrides legacy {legacy}'

    if not selected:
        selected = legacy
        if legacy:
            source = 'legacy'
            reason = reason or 'fallback to legacy trade card engine'

    print(
        f'[TRADECARD_SELECTOR_SYNC] tradecards_best={tradecards_best or "-"} '
        f'tradecard_selected={selected or "-"} source={source} reason={reason}',
        flush=True,
    )
    return {
        'tradecards_best': tradecards_best,
        'selected': selected,
        'source': source,
        'reason': reason,
        'state': state,
        'status_override': status_override,
        'score': int(best_score or 0),
        'board': data,
    }


def run_scheduled_opening_radar_alert(
    *,
    now: datetime | None = None,
    send_fn: Callable[[str], bool] | None = None,
) -> bool:
    """Send scheduled 09:20 opening rally radar when candidates exist (paper only)."""
    ist_now = _now_ist(now)
    board = build_opening_rally_board(now=ist_now)
    candidates = [
        r for r in (board.get('ranked_candidates') or [])
        if r.get('state') != 'REJECTED'
    ]
    ts = ist_now.replace(microsecond=0).isoformat()
    if not candidates:
        print('[OPENING_RADAR_NO_CANDIDATES] reason=no_non_rejected_candidates', flush=True)
        print(f'[OPENING_RADAR_SCHEDULED] time={ts} candidates=0 sent=no', flush=True)
        return False

    from backend.telegram.response_format import format_opening_radar_telegram

    text = format_opening_radar_telegram(board=board)
    try:
        from backend.orchestration.alert_quality_engine import evaluate_text_alert, record_text_alert_sent

        gate = evaluate_text_alert('opening_radar_scheduled', text)
        if not gate.get('send'):
            print(f'[OPENING_RADAR_SCHEDULED] time={ts} candidates={len(candidates)} sent=no', flush=True)
            return False
        record_text_alert_sent('opening_radar_scheduled', gate)
    except Exception:
        pass

    sent = False
    if send_fn is not None:
        sent = bool(send_fn(text))
    else:
        try:
            from backend.telegram.telegram_analysis_bot import send_analysis_message

            sent = bool(send_analysis_message(text, command='opening_radar_scheduled').get('sent'))
        except Exception:
            sent = False
    print(
        f'[OPENING_RADAR_SCHEDULED] time={ts} candidates={len(candidates)} '
        f'sent={"yes" if sent else "no"}',
        flush=True,
    )
    return sent


def format_opening_radar_action(state: str) -> str:
    token = str(state or '').upper()
    if token == 'VOLUME_IGNITION':
        return 'prepare tradecard; no blind chase'
    if token == 'RADAR_ARMED':
        return 'watch only — no entry yet'
    if token == 'TRADECARD_CANDIDATE':
        return 'review /tradecards then /tradecard'
    if token == 'CHASE_RISK':
        return 'no fresh entry — chase risk'
    if token == 'MOMENTUM_ONLY_WATCH':
        return 'momentum watch — confirm catalyst'
    return 'research only'
