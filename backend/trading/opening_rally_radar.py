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
STAGE = '4B.2'
SCANNER_FILE = DATA_DIR / 'scanner_data.json'
CATALYST_FILE = DATA_DIR / 'stock_catalyst_radar_latest.json'
PREMARKET_FILE = DATA_DIR / 'premarket_conviction_latest.json'

RADAR_STATES = frozenset({
    'RADAR_ARMED',
    'PRICE_IGNITION',
    'SECTOR_BREADTH_CONFIRM',
    'VOLUME_IGNITION',
    'TRADECARD_CANDIDATE',
    'PULLBACK_ONLY_PLAN',
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
STRONG_OPENING_MOVE_PCT = 2.0

SECTOR_PEERS: dict[str, set[str]] = {
    'IT': {'INFY', 'HCLTECH', 'TCS', 'WIPRO', 'TECHM', 'LTIM', 'MPHASIS', 'COFORGE', 'PERSISTENT'},
    'RAILWAYS': {'RAILTEL', 'RVNL', 'IRCON', 'RITES', 'TITAGARH', 'JWL'},
    'DEFENCE': {'BEML', 'HAL', 'BEL', 'BDL', 'MAZDOCK', 'COCHINSHIP'},
}

OPENING_STAGE_CATEGORY = {
    '0900': 'OPENING_RADAR_ARMED',
    '0920': 'OPENING_RALLY_RADAR',
    '0925': 'EARLY_TRADECARD_PROVISIONAL',
    '0931': 'FINAL_OPENING_CONFIRMATION',
}


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


def _minutes_from_time_text(value: object) -> int | None:
    text = str(value or '').strip()
    if ':' not in text:
        return None
    try:
        hour, minute = text.split(':', 1)
        return int(hour) * 60 + int(minute[:2])
    except (TypeError, ValueError):
        return None


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


def _sector_for_symbol(sym: str) -> str:
    ticker = _normalize_ticker(sym)
    for sector, peers in SECTOR_PEERS.items():
        if ticker in peers:
            return sector
    return ''


def _strong_opening_move(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    change_pct = abs(_safe_float(row.get('change_percent')))
    volume_ratio = _safe_float(row.get('volume_ratio'))
    above_open, above_vwap = _price_strength(row)
    return change_pct >= 1.5 or volume_ratio >= VOLUME_IGNITION_MIN or (above_open and above_vwap)


def _sector_breadth_map(scanner_index: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_sector: dict[str, list[str]] = {}
    for sym, row in scanner_index.items():
        sector = _sector_for_symbol(sym)
        if not sector or not _strong_opening_move(row):
            continue
        by_sector.setdefault(sector, []).append(sym)

    out: dict[str, dict[str, Any]] = {}
    for sector, symbols in by_sector.items():
        unique = sorted({_normalize_ticker(sym) for sym in symbols if sym})
        if len(unique) < 2:
            continue
        boost = 12 if len(unique) >= 3 else 8
        print(
            f'[OPENING_SECTOR_BREADTH] sector={sector} symbols={",".join(unique)} boost={boost}',
            flush=True,
        )
        for sym in unique:
            out[sym] = {'sector': sector, 'symbols': unique, 'boost': boost}
    return out


def _build_why_lines(
    *,
    catalyst: dict[str, Any] | None,
    themes: list[str],
    previous_mover: bool,
    volume_ratio: float,
    above_open: bool,
    above_vwap: bool,
    sector_breadth: dict[str, Any] | None = None,
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
    if sector_breadth:
        sector = str(sector_breadth.get('sector') or 'sector')
        symbols = '/'.join(sector_breadth.get('symbols') or [])
        parts.append(f'{sector} sector breadth confirmation: {symbols}')
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
    sector_breadth: dict[str, Any] | None = None,
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
    breadth_boost = int((sector_breadth or {}).get('boost') or 0)
    strong_price_reaction = change_pct >= STRONG_OPENING_MOVE_PCT or (change_pct >= 1.5 and above_open)

    if has_catalyst:
        cat_score = _safe_float((catalyst or {}).get('score'), 50.0)
        score += min(32.0, cat_score * 0.35 + 18.0)
    if themes:
        score += 12.0
    if previous_mover:
        score += 8.0
    if breadth_boost:
        score += breadth_boost
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
        sector_breadth=sector_breadth,
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
        sector_breadth_boost=breadth_boost,
        strong_price_reaction=strong_price_reaction,
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
        'extended': extended,
        'pullback_only': bool(extended and state in ('TRADECARD_CANDIDATE', 'CHASE_RISK')),
        'sector_breadth': sector_breadth or {},
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
    sector_breadth_boost: int = 0,
    strong_price_reaction: bool = False,
) -> str:
    if catalyst_side in ('BEARISH', 'RISK'):
        return 'REJECTED'

    armed_signal = has_catalyst or has_theme or previous_mover
    volume_signal = volume_ratio >= VOLUME_IGNITION_MIN
    breadth_signal = sector_breadth_boost > 0
    price_ignition_signal = strong_price_reaction and (armed_signal or breadth_signal)
    sector_confirm_signal = breadth_signal and strong_price_reaction
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
        if sector_confirm_signal:
            return 'SECTOR_BREADTH_CONFIRM'
        if volume_signal and (armed_signal or above_open):
            return 'VOLUME_IGNITION'
        if price_ignition_signal and (has_catalyst or has_theme):
            return 'PRICE_IGNITION'
        if armed_signal and not volume_signal:
            return 'RADAR_ARMED'
        if momentum_only:
            return 'MOMENTUM_ONLY_WATCH'
        return 'RADAR_ARMED' if armed_signal else 'REJECTED'

    if phase in ('CONFIRMATION', 'POST_CONFIRM'):
        if extended and sector_confirm_signal and score >= 60:
            return 'TRADECARD_CANDIDATE'
        if extended:
            return 'CHASE_RISK'
        if sector_confirm_signal and score >= 60:
            return 'TRADECARD_CANDIDATE'
        if price_ignition_signal and score >= 60:
            return 'TRADECARD_CANDIDATE'
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
    sector_breadth = _sector_breadth_map(scanner_index)
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
            sector_breadth=sector_breadth.get(sym),
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
        elif state in ('VOLUME_IGNITION', 'PRICE_IGNITION', 'SECTOR_BREADTH_CONFIRM'):
            catalyst = 'yes' if row.get('has_catalyst') else 'no'
            print(
                f'[OPENING_VOLUME_IGNITION] symbol={sym} state={state} move={row.get("change_percent")} '
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
        if r.get('state') in (
            'TRADECARD_CANDIDATE',
            'VOLUME_IGNITION',
            'PRICE_IGNITION',
            'SECTOR_BREADTH_CONFIRM',
            'PULLBACK_ONLY_PLAN',
            'MOMENTUM_ONLY_WATCH',
            'CHASE_RISK',
        )
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
    if now is None:
        mins = _minutes_from_time_text(data.get('time_ist')) or mins

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


def _opening_state_display(state: str) -> str:
    token = str(state or '').upper()
    if token == 'MOMENTUM_ONLY_WATCH':
        return 'PURE_VOLUME_SPIKE'
    if token == 'PULLBACK_ONLY_PLAN':
        return 'PULLBACK ONLY PLAN'
    return token.replace('_', ' ')


def resolve_final_confirmation_state(
    row: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> str:
    """Map opening-board row to final confirmation state at ~09:31."""
    if not row:
        return 'NO_CLEAN_ENTRY'
    state = str(row.get('state') or '').upper()
    score = int(row.get('score') or 0)
    change_pct = _safe_float(row.get('change_percent'))
    has_catalyst = bool(row.get('has_catalyst'))
    if state == 'REJECTED':
        return 'NO_CLEAN_ENTRY'
    if state == 'CHASE_RISK' or change_pct >= EXTENDED_MOVE_PCT or row.get('pullback_only'):
        if score >= 55:
            print(
                f'[OPENING_PULLBACK_ONLY_PLAN] symbol={row.get("ticker")} reason=extended_but_strongest',
                flush=True,
            )
            return 'PULLBACK_ONLY_PLAN'
        return 'CHASE_RISK'
    if state == 'MOMENTUM_ONLY_WATCH':
        return 'WAIT_FOR_PULLBACK'
    if state in ('TRADECARD_CANDIDATE', 'VOLUME_IGNITION') and score >= 60:
        if has_catalyst or (state == 'VOLUME_IGNITION' and score >= 70):
            return 'CONFIRMED'
        return 'WAIT_FOR_PULLBACK'
    if state == 'RADAR_ARMED':
        return 'WAIT_FOR_PULLBACK'
    mins = _minutes_since_midnight(_now_ist(now))
    if mins >= 9 * 60 + 31 and score < 55:
        return 'NO_CLEAN_ENTRY'
    return 'WAIT_FOR_PULLBACK'


def _opening_row_price(row: dict[str, Any] | None) -> float | None:
    scanner = (row or {}).get('scanner_row') if isinstance((row or {}).get('scanner_row'), dict) else {}
    for source in (scanner, row or {}):
        for key in ('price', 'last_price', 'current_price', 'ltp'):
            val = _safe_float(source.get(key), 0.0)
            if val > 0:
                return val
    return None


def _opening_row_volume(row: dict[str, Any] | None) -> float | None:
    val = _safe_float((row or {}).get('volume_ratio'), 0.0)
    return val if val > 0 else None


def _opening_pullback_card(row: dict[str, Any], *, now: datetime, state: str) -> dict[str, Any] | None:
    sym = _normalize_ticker(row.get('ticker'))
    price = _opening_row_price(row)
    if not sym or price is None:
        return None
    scanner = row.get('scanner_row') if isinstance(row.get('scanner_row'), dict) else {}
    vwap = _safe_float(scanner.get('vwap'), 0.0) or price * 0.985
    open_price = _safe_float(scanner.get('open_price') or scanner.get('open'), 0.0) or price * 0.98
    zone_low = round(min(vwap, open_price) * 0.998, 2)
    zone_high = round(max(vwap, open_price) * 1.002, 2)
    if zone_high >= price:
        zone_high = round(price * 0.992, 2)
        zone_low = round(zone_high * 0.985, 2)
    stop = round(zone_low * 0.985, 2)
    return {
        'ok': True,
        'ticker': sym,
        'status': 'VALID_ENTRY',
        'session_date': now.astimezone(IST).date().isoformat(),
        'generated_at': now.replace(microsecond=0).isoformat(),
        'current_price': round(price, 2),
        'entry_zone': f'{zone_low}-{zone_high}',
        'stop_loss': stop,
        'target_1': round(price * 1.015, 2),
        'target_2': round(price * 1.03, 2),
        'risk_reward': 1.5,
        'confidence': 'MEDIUM' if int(row.get('score') or 0) >= 70 else 'LOW',
        'capital_plan': 'Pullback/retest paper plan only; no market chase.',
        'reason': 'Strongest candidate but extended. Paper entry only on VWAP/retest/opening-range hold. No market chase.',
        'invalid_if': f'Opening range/VWAP hold fails or price trades below {stop}.',
        'paper_only': True,
        'source_label': 'opening_pullback_only',
        'opening_state': state,
    }


def _persist_opening_best_tradecard(
    *,
    row: dict[str, Any] | None,
    now: datetime,
    state: str,
) -> dict[str, Any] | None:
    if not row:
        return None
    card = _opening_pullback_card(row, now=now, state=state)
    if not card:
        return None
    try:
        from backend.trading.tradecard_journal import persist_tradecard_generation

        record = persist_tradecard_generation(card, source_label='opening_pullback_only')
        print(
            f'[TRADECARD_GENERATED_FROM_OPENING_BEST] symbol={card.get("ticker")} '
            f'state={state} generated={"yes" if record else "blocked_or_duplicate"}',
            flush=True,
        )
        return record
    except Exception as exc:
        print(
            f'[TRADECARD_GENERATED_FROM_OPENING_BEST] symbol={card.get("ticker")} '
            f'state={state} generated=no error={exc}',
            flush=True,
        )
        return None


def _capture_opening_workflow(
    *,
    stage: str,
    board: dict[str, Any],
    candidates: list[dict[str, Any]],
    best_sym: str = '',
    timestamp: str = '',
) -> None:
    category = OPENING_STAGE_CATEGORY.get(stage, 'OPENING_RALLY_RADAR')
    best = _normalize_ticker(best_sym)
    ts = timestamp or str(board.get('generated_at') or _now_ist().replace(microsecond=0).isoformat())
    print(
        f'[OPENING_WORKFLOW_CAPTURE] stage={stage} candidates={len(candidates)} best={best or "-"}',
        flush=True,
    )
    try:
        from backend.orchestration.alert_event_log import log_alert_event
    except Exception:
        return
    for row in candidates:
        sym = _normalize_ticker(row.get('ticker'))
        if not sym:
            continue
        why = ' + '.join(row.get('why') or []) or 'opening workflow'
        state = str(row.get('state') or '')
        is_best = bool(best and sym == best)
        try:
            log_alert_event(
                category=category,
                tickers=sym,
                direction='BULLISH',
                score=float(row.get('score') or 0),
                price_at_alert=_opening_row_price(row),
                volume_at_alert=_opening_row_volume(row),
                reason=f'{stage} {state}: {why}',
                timestamp=ts,
                metadata={
                    'opening_workflow': True,
                    'opening_stage': stage,
                    'opening_state': state,
                    'opening_best': is_best,
                    'pullback_only': bool(row.get('pullback_only') or state == 'CHASE_RISK'),
                    'sector_breadth': row.get('sector_breadth') or {},
                },
            )
            print(
                f'[OPENING_LEARNING_CAPTURE] symbol={sym} stage={stage} '
                f'status={"pending" if is_best and stage in ("0925", "0931") else "captured"}',
                flush=True,
            )
        except Exception:
            print(
                f'[OPENING_LEARNING_CAPTURE] symbol={sym} stage={stage} status=failed',
                flush=True,
            )


def _send_scheduled_opening_text(
    *,
    alert_key: str,
    text: str,
    log_tag: str,
    log_fields: str,
    send_fn: Callable[[str], bool] | None,
    command: str,
) -> bool:
    sent = False
    if send_fn is not None:
        sent = bool(send_fn(text))
    else:
        try:
            from backend.telegram.telegram_analysis_bot import send_analysis_message

            sent = bool(send_analysis_message(text, command=command).get('sent'))
        except Exception:
            sent = False
    print(f'[{log_tag}] {log_fields} sent={"yes" if sent else "no"}', flush=True)
    return sent


def _gate_scheduled_alert(alert_key: str, text: str) -> bool:
    try:
        from backend.orchestration.alert_quality_engine import evaluate_text_alert, record_text_alert_sent

        gate = evaluate_text_alert(alert_key, text)
        if not gate.get('send'):
            return False
        record_text_alert_sent(alert_key, gate)
    except Exception:
        pass
    return True


def run_scheduled_radar_armed_0900(
    *,
    now: datetime | None = None,
    send_fn: Callable[[str], bool] | None = None,
) -> bool:
    """09:00 IST — news/theme watchlist only (no entry)."""
    ist_now = _now_ist(now)
    board = build_opening_rally_board(now=ist_now)
    candidates = [
        r for r in (board.get('ranked_candidates') or [])
        if r.get('state') == 'RADAR_ARMED'
    ]
    ts = ist_now.replace(microsecond=0).isoformat()
    if not candidates:
        print('[OPENING_RADAR_NO_CANDIDATES] reason=no_radar_armed_at_0900', flush=True)
        print(
            f'[OPENING_RADAR_ARMED_SCHEDULED] time={ts} candidates=0 sent=no',
            flush=True,
        )
        return False

    from backend.telegram.response_format import format_radar_armed_scheduled_telegram

    text = format_radar_armed_scheduled_telegram(board=board, candidates=candidates)
    if not _gate_scheduled_alert('radar_armed_0900', text):
        print(
            f'[OPENING_RADAR_ARMED_SCHEDULED] time={ts} candidates={len(candidates)} sent=no',
            flush=True,
        )
        return False
    sent = _send_scheduled_opening_text(
        alert_key='radar_armed_0900',
        text=text,
        log_tag='OPENING_RADAR_ARMED_SCHEDULED',
        log_fields=f'time={ts} candidates={len(candidates)}',
        send_fn=send_fn,
        command='radar_armed_0900',
    )
    if sent:
        _capture_opening_workflow(
            stage='0900',
            board=board,
            candidates=candidates,
            timestamp=ts,
        )
    return sent


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
    if not _gate_scheduled_alert('opening_radar_scheduled', text):
        print(f'[OPENING_RADAR_SCHEDULED] time={ts} candidates={len(candidates)} sent=no', flush=True)
        return False

    sent = _send_scheduled_opening_text(
        alert_key='opening_radar_scheduled',
        text=text,
        log_tag='OPENING_RADAR_SCHEDULED',
        log_fields=f'time={ts} candidates={len(candidates)}',
        send_fn=send_fn,
        command='opening_radar_scheduled',
    )
    if sent:
        _capture_opening_workflow(
            stage='0920',
            board=board,
            candidates=candidates,
            timestamp=ts,
        )
    return sent


def run_scheduled_early_tradecards_0925(
    *,
    now: datetime | None = None,
    send_fn: Callable[[str], bool] | None = None,
) -> bool:
    """09:25 IST — provisional top tradecard candidates before 09:30."""
    ist_now = _now_ist(now)
    board = build_opening_rally_board(now=ist_now)
    candidates = [
        r for r in (board.get('ranked_candidates') or [])
        if r.get('state') != 'REJECTED'
    ]
    ts = ist_now.replace(microsecond=0).isoformat()
    best_sym, _, _ = pick_best_opening_tradecard(board)
    if not candidates:
        print('[OPENING_RADAR_NO_CANDIDATES] reason=no_early_tradecard_candidates', flush=True)
        print(
            f'[EARLY_TRADECARDS_SCHEDULED] time={ts} candidates=0 '
            f'provisional_best=- sent=no',
            flush=True,
        )
        return False

    from backend.telegram.response_format import format_early_tradecards_scheduled_telegram

    text = format_early_tradecards_scheduled_telegram(board=board)
    if not _gate_scheduled_alert('early_tradecards_0925', text):
        print(
            f'[EARLY_TRADECARDS_SCHEDULED] time={ts} candidates={len(candidates)} '
            f'provisional_best={best_sym or "-"} sent=no',
            flush=True,
        )
        return False
    sent = _send_scheduled_opening_text(
        alert_key='early_tradecards_0925',
        text=text,
        log_tag='EARLY_TRADECARDS_SCHEDULED',
        log_fields=(
            f'time={ts} candidates={len(candidates)} '
            f'provisional_best={best_sym or "-"}'
        ),
        send_fn=send_fn,
        command='early_tradecards_0925',
    )
    if sent:
        best_row = next(
            (
                r for r in candidates
                if _normalize_ticker(r.get('ticker')) == _normalize_ticker(best_sym)
            ),
            None,
        )
        _capture_opening_workflow(
            stage='0925',
            board=board,
            candidates=candidates,
            best_sym=best_sym or '',
            timestamp=ts,
        )
        _persist_opening_best_tradecard(
            row=best_row,
            now=ist_now,
            state=str((best_row or {}).get('state') or 'TRADECARD_CANDIDATE'),
        )
    return sent


def run_scheduled_final_confirmation_0931(
    *,
    now: datetime | None = None,
    send_fn: Callable[[str], bool] | None = None,
) -> bool:
    """09:31 IST — final opening confirmation or chase/no-entry state."""
    ist_now = _now_ist(now)
    board = build_opening_rally_board(now=ist_now)
    best_sym, best_score, _ = pick_best_opening_tradecard(board)
    best_row = next(
        (
            r for r in (board.get('ranked_candidates') or [])
            if _normalize_ticker(r.get('ticker')) == _normalize_ticker(best_sym)
        ),
        None,
    )
    confirm_state = resolve_final_confirmation_state(best_row, now=ist_now)
    ts = ist_now.replace(microsecond=0).isoformat()
    if not best_sym:
        print('[OPENING_RADAR_NO_CANDIDATES] reason=no_final_confirmation_pick', flush=True)
        print(
            f'[FINAL_OPENING_CONFIRMATION] time={ts} best=- '
            f'state=no_clean_entry sent=no',
            flush=True,
        )
        return False

    from backend.telegram.response_format import format_final_opening_confirmation_telegram

    text = format_final_opening_confirmation_telegram(
        board=board,
        best_sym=best_sym,
        best_score=best_score,
        confirm_state=confirm_state,
        best_row=best_row,
    )
    if not _gate_scheduled_alert('final_opening_confirmation_0931', text):
        print(
            f'[FINAL_OPENING_CONFIRMATION] time={ts} best={best_sym} '
            f'state={confirm_state.lower()} sent=no',
            flush=True,
        )
        return False
    sent = _send_scheduled_opening_text(
        alert_key='final_opening_confirmation_0931',
        text=text,
        log_tag='FINAL_OPENING_CONFIRMATION',
        log_fields=(
            f'time={ts} best={best_sym} state={confirm_state.lower()}'
        ),
        send_fn=send_fn,
        command='final_opening_confirmation_0931',
    )
    if sent:
        _capture_opening_workflow(
            stage='0931',
            board=board,
            candidates=[best_row] if best_row else [],
            best_sym=best_sym or '',
            timestamp=ts,
        )
        _persist_opening_best_tradecard(
            row=best_row,
            now=ist_now,
            state=confirm_state,
        )
    return sent


OPENING_MORNING_SLOT_RUNNERS: dict[str, Callable[..., bool]] = {
    'radar_armed_0900': run_scheduled_radar_armed_0900,
    'opening_radar_0920': run_scheduled_opening_radar_alert,
    'early_tradecards_0925': run_scheduled_early_tradecards_0925,
    'final_confirmation_0931': run_scheduled_final_confirmation_0931,
}


def run_opening_morning_scheduled_slot(
    slot: str,
    *,
    now: datetime | None = None,
    send_fn: Callable[[str], bool] | None = None,
) -> bool:
    runner = OPENING_MORNING_SLOT_RUNNERS.get(slot)
    if runner is None:
        return False
    return runner(now=now, send_fn=send_fn)


def format_opening_radar_action(state: str) -> str:
    token = str(state or '').upper()
    if token == 'VOLUME_IGNITION':
        return 'prepare tradecard; no blind chase'
    if token == 'PRICE_IGNITION':
        return 'price ignition; confirm breadth/VWAP before paper plan'
    if token == 'SECTOR_BREADTH_CONFIRM':
        return 'sector breadth confirm; prepare pullback/retest plan'
    if token == 'RADAR_ARMED':
        return 'watch only - no entry yet'
    if token == 'TRADECARD_CANDIDATE':
        return 'review /tradecards then /tradecard'
    if token == 'PULLBACK_ONLY_PLAN':
        return 'paper plan only on VWAP/retest; no market chase'
    if token == 'CHASE_RISK':
        return 'strong but extended; pullback/retest only'
    if token == 'MOMENTUM_ONLY_WATCH':
        return 'momentum watch - confirm catalyst'
    return 'research only'
