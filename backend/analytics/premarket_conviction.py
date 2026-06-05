"""
Premarket conviction pipeline (Stage 46I).

Builds premarket_conviction_report.json and Telegram message formatters.
Research-only wording — watch for entry, confirm after 9:15 (before open), no blind entry.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, time
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path
from backend.storage.json_io import atomic_write_json

IST = ZoneInfo('Asia/Kolkata')
REPORT_FILE = get_data_path('premarket_conviction_report.json')

FORBIDDEN_WORDS = ('buy now', 'invest now', 'guaranteed')
REQUIRED_PHRASES_PREOPEN = ('confirm after 9:15', 'no blind entry', 'watch for entry')
REQUIRED_PHRASES_OPEN = ('no blind entry', 'watch for entry')

DATA_FILES = {
    'global': 'global_markets.json',
    'news': 'news_feed.json',
    'govt': 'govt_intelligence.json',
    'broker': 'broker_intelligence.json',
    'scanner': 'scanner_data.json',
    'intel': 'unified_intelligence.json',
    'final_confidence': 'final_confidence_report.json',
    'memory': 'market_memory_dashboard_cache.json',
    'watchlist': 'tomorrow_watchlist_report.json',
    'market': 'latest_market_data.json',
    'daily_pack': 'daily_report_pack_latest.json',
}

SLOT_TITLES = {
    'premarket_top3': '🌅 PREMARKET TOP SETUPS',
    'premarket_action': '🌅 PREMARKET FULL BRIEF',
    'premarket_full': '🌅 PREMARKET FULL BRIEF',
    'preopen_watch': '🌅 PRE-OPEN WATCH',
    'live_validation': '🌅 FIRST LIVE VALIDATION',
    'open_confirmation': '🌅 OPEN CONFIRMATION / REJECTION',
    'premarket_confirm': '🌅 OPEN CONFIRMATION / REJECTION',
}


def _log(msg: str) -> None:
    print(f'[PREMARKET] {msg}', flush=True)


def _load_json(name: str) -> dict:
    path = get_data_path(name)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_after_open(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(IST)
    return now.time() >= time(9, 15)


def _india_mode_info() -> dict:
    from backend.analytics.market_calendar_router import get_india_telegram_mode
    return get_india_telegram_mode()


def _market_bias(intel: dict, final_conf: dict, global_m: dict) -> str:
    mood = (intel or {}).get('market_mood') or {}
    outlook = str(mood.get('india_outlook') or mood.get('global_mood') or '').lower()
    score = _safe_float((final_conf or {}).get('aggregate_score') or (final_conf or {}).get('score'), 50)
    global_sent = str((global_m or {}).get('sentiment') or '').lower()
    if 'bear' in outlook or 'risk' in outlook or score < 42 or 'bear' in global_sent:
        return 'Risk-off'
    if 'bull' in outlook or score >= 58 or 'bull' in global_sent:
        return 'Bullish'
    return 'Neutral'


def _sector_cues(intel: dict) -> tuple[list[str], list[str]]:
    sectors = (intel or {}).get('sector_rotation') or {}
    bullish = [str(s) for s in (sectors.get('bullish') or [])[:4]]
    bearish = [str(s) for s in (sectors.get('bearish') or [])[:4]]
    return bullish, bearish


def _negative_move_label(chg: float, direction: str) -> str:
    if chg < -0.5 or direction == 'BEARISH':
        return 'Bearish / short watch'
    if chg < 0:
        return 'Avoid — negative move'
    return ''


def _build_setup_candidates(
    scanner: dict,
    watchlist: dict,
    final_conf: dict,
    intel: dict,
    *,
    limit: int = 5,
) -> list[dict]:
    candidates: list[dict] = []
    seen: set[str] = set()

    fc_rows = (final_conf or {}).get('ranked') or (final_conf or {}).get('candidates') or []
    for row in fc_rows[:8]:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get('ticker') or row.get('symbol') or '').upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        score = _safe_float(row.get('final_score') or row.get('score'), 50)
        chg = _safe_float(row.get('change_percent'))
        direction = str(row.get('direction') or 'NEUTRAL').upper()
        neg_label = _negative_move_label(chg, direction)
        setup = neg_label or str(row.get('decision') or row.get('label') or 'WATCH').replace('_', ' ')
        if neg_label:
            score = min(score, 52)
        candidates.append({
            'ticker': ticker,
            'setup': setup,
            'score': round(score),
            'reasons': [
                str(row.get('primary_reason') or row.get('logic') or 'Final confidence candidate')[:80],
                'Sector + memory alignment pending open confirmation',
            ],
            'sector': row.get('sector') or '?',
            'source': 'final_confidence',
            'change_percent': chg,
            'direction': direction,
        })

    wl_rows = (watchlist or {}).get('top_watchlist') or (watchlist or {}).get('watchlist') or []
    for row in wl_rows[:6]:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get('ticker') or row.get('symbol') or '').upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        score = _safe_float(row.get('score') or row.get('confidence_score'), 55)
        chg = _safe_float(row.get('change_percent'))
        direction = str(row.get('direction') or 'NEUTRAL').upper()
        neg_label = _negative_move_label(chg, direction)
        setup = neg_label or str(row.get('setup') or row.get('action') or 'WATCH').replace('_', ' ')
        if neg_label:
            score = min(score, 50)
        candidates.append({
            'ticker': ticker,
            'setup': setup,
            'score': round(score),
            'reasons': [
                str(row.get('why') or row.get('reason') or 'Watchlist candidate')[:80],
                'Confirm only if price strength + volume + sector support',
            ],
            'sector': row.get('sector') or '?',
            'source': 'watchlist',
            'change_percent': chg,
            'direction': direction,
        })

    for sig in (scanner or {}).get('top_signals', [])[:8]:
        if not isinstance(sig, dict):
            continue
        ticker = str(sig.get('ticker') or '').upper()
        if not ticker or ticker in seen:
            continue
        if str(sig.get('strength', '')).upper() not in ('ULTRA', 'STRONG'):
            continue
        seen.add(ticker)
        vol_r = _safe_float(sig.get('volume_ratio'))
        chg = _safe_float(sig.get('change_percent'))
        direction = str(sig.get('direction', 'NEUTRAL')).upper()
        neg_label = _negative_move_label(chg, direction)
        if neg_label:
            setup = neg_label
            score = min(55, 45 + abs(chg))
        else:
            setup = f"{direction} scanner signal"
            score = min(95, 55 + abs(chg) * 2 + vol_r * 4)
        reason2 = (
            'Wait for volume confirmation'
            if _is_after_open()
            else 'Watch for entry — confirm after 9:15 with volume'
        )
        candidates.append({
            'ticker': ticker,
            'setup': setup,
            'score': round(score),
            'reasons': [
                f"Overnight/scanner move {chg:+.1f}% · vol {vol_r:.1f}x",
                reason2,
            ],
            'sector': sig.get('sector') or '?',
            'source': 'scanner',
            'change_percent': chg,
            'direction': direction,
        })

    opps = (intel or {}).get('top_opportunities') or []
    for row in opps[:4]:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get('symbol') or row.get('ticker') or '').upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        action = str(row.get('action') or 'WATCH').upper()
        if 'SELL' in action or 'AVOID' in action or 'SHORT' in action:
            setup = 'Bearish / short watch'
            score = 48
        else:
            setup = str(row.get('action') or 'WATCH')
            score = 52
        candidates.append({
            'ticker': ticker,
            'setup': setup,
            'score': score,
            'reasons': [
                str(row.get('logic') or 'Intel opportunity')[:80],
                'No blind entry before open',
            ],
            'sector': row.get('sector') or '?',
            'source': 'intel',
        })

    candidates.sort(key=lambda c: c.get('score', 0), reverse=True)
    return candidates[:limit]


def _format_sentiment_value(value: Any) -> str:
    """Render sentiment dict/list as clean lines — never raw Python dict."""
    if value is None:
        return '—'
    if isinstance(value, str):
        return value[:200]
    if isinstance(value, dict):
        if any(k in value for k in ('usa', 'asia', 'global')):
            return _format_global_sentiment_dict(value)
        lines = []
        for key in ('summary', 'consensus', 'bias', 'mood', 'stance'):
            if value.get(key):
                lines.append(f"{key.replace('_', ' ').title()}: {value[key]}")
        for key, val in value.items():
            if key in ('summary', 'consensus', 'bias', 'mood', 'stance'):
                continue
            if isinstance(val, (str, int, float)):
                lines.append(f"{str(key).replace('_', ' ').title()}: {val}")
        return '\n'.join(lines[:6]) if lines else '—'
    if isinstance(value, list):
        return ', '.join(str(v) for v in value[:6]) or '—'
    return str(value)[:200]


def _mood_label(mood: str, change: float) -> str:
    token = str(mood or 'NEUTRAL').upper()
    if 'BULL' in token:
        label = 'Bullish'
    elif 'BEAR' in token:
        label = 'Bearish'
    else:
        label = 'Neutral'
    return f'{label} ({change:+.2f}%)'


def _format_global_sentiment_dict(sentiment: dict) -> str:
    """Format US/Asia/Global sentiment without raw dict."""
    lines: list[str] = []
    for region_key, display in (('usa', 'US'), ('asia', 'Asia'), ('global', 'Global')):
        block = sentiment.get(region_key)
        if not isinstance(block, dict):
            continue
        mood = block.get('mood') or block.get('sentiment') or 'NEUTRAL'
        chg = _safe_float(block.get('average_change') or block.get('change_percent'))
        lines.append(f'{display}: {_mood_label(str(mood), chg)}')
    return '\n'.join(lines) if lines else '—'


def _ticker_vol_ratio(ticker: str, scanner: dict) -> float:
    for sig in (scanner or {}).get('top_signals', []) or []:
        if not isinstance(sig, dict):
            continue
        if str(sig.get('ticker', '')).upper() == ticker.upper():
            return _safe_float(sig.get('volume_ratio'))
    return 0.0


def _has_catalyst(setup: dict, intel: dict) -> bool:
    reasons = ' '.join(str(r) for r in (setup.get('reasons') or [])).lower()
    catalyst_words = ('earnings', 'result', 'guidance', 'order', 'deal', 'upgrade', 'downgrade', 'catalyst')
    if any(w in reasons for w in catalyst_words):
        return True
    ticker = str(setup.get('ticker', '')).upper()
    for row in (intel or {}).get('top_opportunities') or []:
        if isinstance(row, dict) and str(row.get('symbol', row.get('ticker', ''))).upper() == ticker:
            logic = str(row.get('logic', '')).lower()
            if any(w in logic for w in catalyst_words):
                return True
    return False


def _apply_volume_caps(setups: list[dict], scanner: dict, intel: dict) -> tuple[list[dict], list[dict]]:
    """Weak volume separation — vol<0.5 not Top3; vol<0.3 low confidence bucket."""
    adjusted: list[dict] = []
    watch_later: list[dict] = []
    low_confidence: list[dict] = []

    for setup in setups:
        ticker = str(setup.get('ticker', '')).upper()
        vol_r = _ticker_vol_ratio(ticker, scanner)
        row = dict(setup)
        if vol_r < 0.3:
            row['setup'] = 'Low confidence / ignore unless volume appears'
            row['score'] = min(int(row.get('score', 50)), 42)
            row['tier_cap'] = 'not_top3'
            row['watch_only'] = True
            low_confidence.append(row)
        elif vol_r < 0.5:
            if not _has_catalyst(row, intel):
                row['setup'] = 'Watch later — weak participation'
                row['score'] = min(int(row.get('score', 50)), 55)
                row['tier_cap'] = 'not_top3'
                row['watch_only'] = True
                watch_later.append(row)
            else:
                adjusted.append(row)
        else:
            adjusted.append(row)
    return adjusted, watch_later + low_confidence


def _apply_conflict_guard(setups: list[dict], avoids: list[dict]) -> list[dict]:
    avoid_tickers = {str(a.get('ticker', '')).upper() for a in avoids if a.get('ticker')}
    top_tickers = {str(s.get('ticker', '')).upper() for s in setups[:3]}
    conflicted = top_tickers & avoid_tickers
    if not conflicted:
        return setups
    out: list[dict] = []
    for setup in setups:
        ticker = str(setup.get('ticker', '')).upper()
        if ticker in conflicted:
            row = dict(setup)
            row['setup'] = 'Conflict/Wait'
            row['score'] = min(int(row.get('score', 50)), 55)
            row['conflict'] = True
            avoid_reason = next(
                (a.get('reason', 'mixed signal') for a in avoids if str(a.get('ticker', '')).upper() == ticker),
                'mixed signal',
            )
            row['reasons'] = [
                str((setup.get('reasons') or ['Setup candidate'])[0]),
                f'Conflict with avoid list — {avoid_reason}',
            ]
            out.append(row)
        else:
            out.append(setup)
    return out


def _rank_top_setups(setups: list[dict], limit: int = 5) -> list[dict]:
    """Top 3 excludes not_top3 unless catalyst cleared cap."""
    eligible = [s for s in setups if s.get('tier_cap') != 'not_top3']
    deferred = [s for s in setups if s.get('tier_cap') == 'not_top3']
    ranked = sorted(eligible, key=lambda c: c.get('score', 0), reverse=True)
    tail = sorted(deferred, key=lambda c: c.get('score', 0), reverse=True)
    return (ranked + tail)[:limit]


def _build_avoid_list(intel: dict, scanner: dict) -> list[dict]:
    avoids: list[dict] = []
    for row in (intel or {}).get('risks_and_avoids') or []:
        if isinstance(row, dict):
            ticker = str(row.get('symbol') or row.get('ticker') or '?')
            reason = str(row.get('logic') or row.get('reason') or 'Risk flagged')[:80]
            avoids.append({'ticker': ticker, 'reason': reason})
    for sig in (scanner or {}).get('top_signals', [])[:12]:
        if not isinstance(sig, dict):
            continue
        vol_r = _safe_float(sig.get('volume_ratio'))
        chg = abs(_safe_float(sig.get('change_percent')))
        if vol_r < 0.5 and chg >= 3:
            avoids.append({
                'ticker': sig.get('ticker', '?'),
                'reason': f'Gap {chg:.1f}% but weak participation {vol_r:.1f}x',
            })
    return avoids[:4]


def build_premarket_conviction_report(*, persist: bool = True) -> dict:
    """Aggregate premarket inputs into conviction report."""
    now = datetime.now(IST)
    global_m = _load_json(DATA_FILES['global'])
    news = _load_json(DATA_FILES['news'])
    govt = _load_json(DATA_FILES['govt'])
    broker = _load_json(DATA_FILES['broker'])
    scanner = _load_json(DATA_FILES['scanner'])
    intel = _load_json(DATA_FILES['intel'])
    final_conf = _load_json(DATA_FILES['final_confidence'])
    memory = _load_json(DATA_FILES['memory'])
    watchlist = _load_json(DATA_FILES['watchlist'])
    market = _load_json(DATA_FILES['market'])
    india_mode = _india_mode_info()

    from backend.orchestration.alert_freshness_gate import premarket_freshness_state

    fresh_ok, fresh_header, stale_keys = premarket_freshness_state(now=now, try_refresh=False)

    bullish_sectors, bearish_sectors = _sector_cues(intel)
    setups = _build_setup_candidates(scanner, watchlist, final_conf, intel)
    setups, deferred_weak = _apply_volume_caps(setups, scanner, intel)
    avoids = _build_avoid_list(intel, scanner)
    setups = _apply_conflict_guard(setups, avoids)
    setups = _rank_top_setups(setups)

    if not fresh_ok:
        from backend.orchestration.alert_freshness_gate import cap_premarket_scores
        setups = cap_premarket_scores(setups)

    report = {
        'generated_at': now.isoformat(),
        'date': now.date().isoformat(),
        'stage': '46I',
        'market_bias': _market_bias(intel, final_conf, global_m),
        'market_mode': india_mode,
        'freshness_ok': fresh_ok,
        'freshness_header': fresh_header if not fresh_ok else '',
        'stale_keys': stale_keys,
        'overnight_global': {
            'sentiment': global_m.get('sentiment') or global_m.get('overall_sentiment'),
            'sentiment_formatted': _format_global_sentiment_dict(
                global_m.get('sentiment') or {}
            ) if isinstance(global_m.get('sentiment'), dict) else _format_sentiment_value(
                global_m.get('sentiment') or global_m.get('overall_sentiment')
            ),
            'us_close': global_m.get('us_close_summary') or global_m.get('summary'),
            'commodities': global_m.get('commodities') or global_m.get('commodity_cues'),
            'inr_crude': global_m.get('inr_crude') or global_m.get('fx_commodity'),
        },
        'india_news_count': len((news or {}).get('articles') or []),
        'govt_high_impact': len((govt or {}).get('high_impact_items') or []),
        'broker_sentiment': _format_sentiment_value(
            (broker or {}).get('summary') or (broker or {}).get('consensus') or broker
        ),
        'sector_cues': {'bullish': bullish_sectors, 'bearish': bearish_sectors},
        'top_setups': setups,
        'deferred_weak_volume': deferred_weak,
        'avoid': avoids,
        'memory_snapshot': {
            'win_rate': ((memory or {}).get('learning') or {}).get('overall', {}).get('win_rate'),
            'total_predictions': ((memory or {}).get('stats') or {}).get('predictions'),
        },
        'market_data_fresh': bool(market.get('timestamp') or market.get('updated_at')),
        'wording_rules': {
            'required_preopen': list(REQUIRED_PHRASES_PREOPEN),
            'required_open': list(REQUIRED_PHRASES_OPEN),
            'forbidden': list(FORBIDDEN_WORDS),
        },
    }

    if persist:
        atomic_write_json(REPORT_FILE, report)
        _log(f'report written {REPORT_FILE.name} setups={len(setups)} fresh={fresh_ok}')
    return report


def _slot_label(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(IST)
    return now.strftime('%H:%M IST')


def _title_for_slot(slot: str, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(IST)
    if slot in SLOT_TITLES:
        return SLOT_TITLES[slot]
    if _is_after_open(now):
        if now.hour == 9 and now.minute >= 20:
            return SLOT_TITLES['live_validation']
        return SLOT_TITLES.get('premarket_top3', '🌅 PREMARKET TOP SETUPS')
    return '🌅 PREMARKET TOP SETUPS'


def _action_wording(now: Optional[datetime] = None) -> list[str]:
    """Time-aware rule/footer lines — no confirm-after-9:15 after open."""
    now = now or datetime.now(IST)
    if _is_after_open(now):
        return [
            '<b>Rule:</b> Market open — use Confirmed / Rejected / Wait for volume.',
            '<i>No blind entry · Confirmed / Rejected / Wait for volume.</i>',
        ]
    return [
        '<b>Rule:</b> Watch for entry — no blind entry before open.',
        'Confirm after 9:15 with price strength + volume + sector support.',
        '<i>No blind entry · confirm after 9:15 · watch for entry only.</i>',
    ]


def format_premarket_telegram(
    *,
    full: bool = False,
    report: Optional[dict] = None,
    slot: str = '',
) -> str:
    """Format premarket message for Telegram (/premarket or scheduled slots)."""
    data = report or build_premarket_conviction_report(persist=not bool(report))
    now = datetime.now(IST)
    bias = data.get('market_bias') or 'Neutral'
    setups = data.get('top_setups') or []
    deferred = data.get('deferred_weak_volume') or []
    avoids = data.get('avoid') or []
    mode_info = data.get('market_mode') or {}
    fresh_ok = data.get('freshness_ok', True)
    fresh_header = data.get('freshness_header') or ''

    slot_key = slot or ('premarket_action' if full else 'premarket_top3')
    title = _title_for_slot(slot_key, now)
    slot = _slot_label(now)

    lines: list[str] = []
    if not fresh_ok and fresh_header:
        lines.append(f'<b>{fresh_header}</b>')
        lines.append('<i>Watchlist preparation only — not conviction.</i>')
        lines.append('')
    lines.extend([
        f'<b>{title} — {slot}</b>',
        f'<b>Market bias:</b> {bias}',
        f"<b>Mode:</b> <code>{mode_info.get('market_mode', '—')}</code>",
        '',
        '<b>Top watch:</b>',
    ])

    top3 = [s for s in setups if s.get('tier_cap') != 'not_top3'][:3 if not full else 5]
    display_setups = top3 if top3 else setups[:3 if not full else 5]

    if display_setups:
        for idx, setup in enumerate(display_setups, 1):
            reasons = setup.get('reasons') or []
            why = reasons[0] if reasons else 'Setup candidate'
            why2 = reasons[1] if len(reasons) > 1 else (
                'Wait for volume confirmation' if _is_after_open(now)
                else 'Confirm only if price strength + volume + sector support'
            )
            lines.extend([
                f"{idx}. <b>{setup.get('ticker')}</b> — {setup.get('setup')} · Score {setup.get('score', '—')}",
                f"   Why: {why}",
                f"   {why2}",
            ])
    else:
        lines.append('— Awaiting scanner + watchlist data')

    if deferred:
        lines.extend(['', '<b>Watch later — weak participation:</b>'])
        for row in deferred[:4]:
            lines.append(
                f"• {row.get('ticker')} — {row.get('setup')} · Score {row.get('score', '—')}"
            )

    if full:
        sectors = data.get('sector_cues') or {}
        og = data.get('overnight_global') or {}
        sentiment_text = og.get('sentiment_formatted') or _format_sentiment_value(og.get('sentiment'))
        lines.extend([
            '',
            '<b>Overnight / global (US/global context only)</b>',
        ])
        for line in str(sentiment_text).split('\n'):
            if line.strip():
                lines.append(f'• {line.strip()}')
        lines.extend([
            f"• US close: {str(og.get('us_close') or '—')[:120]}",
            '<i>US/global cues for India open — not a US trading signal.</i>',
            '',
            '<b>Sectors</b>',
            f"↑ {', '.join(sectors.get('bullish') or []) or '—'}",
            f"↓ {', '.join(sectors.get('bearish') or []) or '—'}",
            '',
            f"<b>News articles:</b> {data.get('india_news_count', 0)} · "
            f"<b>Govt high impact:</b> {data.get('govt_high_impact', 0)}",
            '<b>Broker sentiment</b>',
        ])
        broker_lines = str(data.get('broker_sentiment') or '—').split('\n')
        lines.extend(f'• {line}' for line in broker_lines[:5])

    lines.extend(['', '<b>Avoid:</b>'])
    if avoids:
        for row in avoids[:3]:
            lines.append(f"• {row.get('ticker')} — {row.get('reason')}")
    else:
        lines.append('• No explicit avoid flags')

    lines.append('')
    lines.extend(_action_wording(now))

    text = '\n'.join(lines)
    return _enforce_wording(text, now=now)


def _enforce_wording(text: str, *, now: Optional[datetime] = None) -> str:
    lower = text.lower()
    for bad in FORBIDDEN_WORDS:
        if bad in lower:
            text = re.sub(re.escape(bad), 'watch for entry', text, flags=re.IGNORECASE)
    if _is_after_open(now):
        text = re.sub(r'confirm after 9:15', 'Wait for volume confirmation', text, flags=re.IGNORECASE)
    return text


def send_scheduled_premarket(slot: str, *, send_fn: Optional[Callable[[str], bool]] = None) -> bool:
    """Send premarket alert for scheduler slot."""
    from backend.orchestration.alert_freshness_gate import premarket_freshness_state

    now = datetime.now(IST)
    try_refresh = now.hour == 8 and now.minute == 30
    fresh_ok, _header, _keys = premarket_freshness_state(now=now, try_refresh=try_refresh)

    report = build_premarket_conviction_report(persist=True)
    if not fresh_ok and try_refresh:
        report = build_premarket_conviction_report(persist=True)

    full = slot in ('premarket_full', 'premarket_action', 'premarket_confirm', 'open_confirmation')
    mapped_slot = slot
    if slot == 'premarket_top3':
        mapped_slot = 'premarket_top3'
    elif slot in ('premarket_full', 'premarket_action'):
        mapped_slot = 'premarket_action'
    elif slot == 'preopen_watch':
        mapped_slot = 'preopen_watch'
    elif slot == 'live_validation':
        mapped_slot = 'live_validation'
    elif slot in ('open_confirmation', 'premarket_confirm'):
        mapped_slot = 'open_confirmation'

    text = format_premarket_telegram(full=full, report=report, slot=mapped_slot)
    if send_fn:
        sent = bool(send_fn(text))
    else:
        try:
            from backend.telegram.telegram_analysis_bot import send_analysis_message
            sent = bool(send_analysis_message(text, command=f'premarket_{slot}').get('sent'))
        except Exception as exc:
            _log(f'send failed slot={slot}: {exc}')
            sent = False

    if sent:
        try:
            from backend.orchestration.alert_event_log import log_alert_event
            tickers = [str(s.get('ticker', '')) for s in (report.get('top_setups') or [])[:5] if s.get('ticker')]
            log_alert_event(
                category='PRE_MARKET',
                tickers=tickers,
                direction=str(report.get('market_bias') or 'NEUTRAL'),
                score=65.0 if not fresh_ok else None,
                reason=f'premarket slot={slot}',
            )
        except Exception:
            pass
    return sent
