"""
Premarket conviction pipeline (Stage 46H).

Builds premarket_conviction_report.json and Telegram message formatters.
Research-only wording — watch for entry, confirm after 9:15, no blind entry.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path
from backend.storage.json_io import atomic_write_json

IST = ZoneInfo('Asia/Kolkata')
REPORT_FILE = get_data_path('premarket_conviction_report.json')

FORBIDDEN_WORDS = ('buy now', 'invest now', 'guaranteed')
REQUIRED_PHRASES = ('confirm after 9:15', 'no blind entry', 'watch for entry')

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
        candidates.append({
            'ticker': ticker,
            'setup': str(row.get('decision') or row.get('label') or 'WATCH').replace('_', ' '),
            'score': round(score),
            'reasons': [
                str(row.get('primary_reason') or row.get('logic') or 'Final confidence candidate')[:80],
                'Sector + memory alignment pending open confirmation',
            ],
            'sector': row.get('sector') or '?',
            'source': 'final_confidence',
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
        candidates.append({
            'ticker': ticker,
            'setup': str(row.get('setup') or row.get('action') or 'WATCH').replace('_', ' '),
            'score': round(score),
            'reasons': [
                str(row.get('why') or row.get('reason') or 'Watchlist candidate')[:80],
                'Confirm only if price strength + volume + sector support',
            ],
            'sector': row.get('sector') or '?',
            'source': 'watchlist',
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
        score = min(95, 55 + abs(chg) * 2 + vol_r * 4)
        candidates.append({
            'ticker': ticker,
            'setup': f"{sig.get('direction', 'NEUTRAL')} scanner signal",
            'score': round(score),
            'reasons': [
                f"Overnight/scanner move {chg:+.1f}% · vol {vol_r:.1f}x",
                'Watch for entry — confirm after 9:15 with volume',
            ],
            'sector': sig.get('sector') or '?',
            'source': 'scanner',
        })

    opps = (intel or {}).get('top_opportunities') or []
    for row in opps[:4]:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get('symbol') or row.get('ticker') or '').upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        candidates.append({
            'ticker': ticker,
            'setup': str(row.get('action') or 'WATCH'),
            'score': 52,
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


def _apply_volume_caps(setups: list[dict], scanner: dict, intel: dict) -> list[dict]:
    """Weak volume premarket caps — vol<0.5 not Top3 unless catalyst; vol<0.3 Watch Later."""
    adjusted: list[dict] = []
    for setup in setups:
        ticker = str(setup.get('ticker', '')).upper()
        vol_r = _ticker_vol_ratio(ticker, scanner)
        row = dict(setup)
        if vol_r < 0.3:
            row['setup'] = 'Watch Later — weak volume'
            row['score'] = min(int(row.get('score', 50)), 48)
            row['tier_cap'] = 'not_top3'
            row['watch_only'] = True
        elif vol_r < 0.5:
            if not _has_catalyst(row, intel):
                row['setup'] = 'WATCH ONLY — weak participation'
                row['score'] = min(int(row.get('score', 50)), 60)
                row['tier_cap'] = 'not_top3'
                row['watch_only'] = True
        adjusted.append(row)
    return adjusted


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


def _market_mode_and_freshness(daily_pack: dict, final_conf: dict) -> dict:
    mode = (
        (daily_pack or {}).get('market_mode')
        or ((daily_pack or {}).get('summary') or {}).get('market_mode')
        or (final_conf or {}).get('active_mode')
        or 'unknown'
    )
    generated = (
        (daily_pack or {}).get('generated_at')
        or (final_conf or {}).get('generated_at')
        or ''
    )
    return {'market_mode': str(mode), 'latest_report_at': generated}


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
    daily_pack = _load_json(DATA_FILES['daily_pack'])

    bullish_sectors, bearish_sectors = _sector_cues(intel)
    setups = _build_setup_candidates(scanner, watchlist, final_conf, intel)
    setups = _apply_volume_caps(setups, scanner, intel)
    avoids = _build_avoid_list(intel, scanner)
    setups = _apply_conflict_guard(setups, avoids)
    setups = _rank_top_setups(setups)

    report = {
        'generated_at': now.isoformat(),
        'date': now.date().isoformat(),
        'stage': '46H',
        'market_bias': _market_bias(intel, final_conf, global_m),
        'market_mode': _market_mode_and_freshness(daily_pack, final_conf),
        'overnight_global': {
            'sentiment': global_m.get('sentiment') or global_m.get('overall_sentiment'),
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
        'avoid': avoids,
        'memory_snapshot': {
            'win_rate': ((memory or {}).get('learning') or {}).get('overall', {}).get('win_rate'),
            'total_predictions': ((memory or {}).get('stats') or {}).get('predictions'),
        },
        'market_data_fresh': bool(market.get('timestamp') or market.get('updated_at')),
        'wording_rules': {
            'required': list(REQUIRED_PHRASES),
            'forbidden': list(FORBIDDEN_WORDS),
        },
    }

    if persist:
        atomic_write_json(REPORT_FILE, report)
        _log(f'report written {REPORT_FILE.name} setups={len(setups)}')
    return report


def _slot_label(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(IST)
    return now.strftime('%H:%M IST')


def format_premarket_telegram(*, full: bool = False, report: Optional[dict] = None) -> str:
    """Format premarket message for Telegram (/premarket or /premarket full)."""
    data = report or build_premarket_conviction_report(persist=not bool(report))
    bias = data.get('market_bias') or 'Neutral'
    setups = data.get('top_setups') or []
    avoids = data.get('avoid') or []
    mode_info = data.get('market_mode') or {}
    slot = _slot_label()

    title = '🌅 PREMARKET TOP SETUPS' if not full else '🌅 PREMARKET FULL BRIEF'
    lines = [
        f'<b>{title} — {slot}</b>',
        f'<b>Market bias:</b> {bias}',
        f"<b>Mode:</b> <code>{mode_info.get('market_mode', '—')}</code>",
        '',
        '<b>Top watch:</b>',
    ]

    if setups:
        for idx, setup in enumerate(setups[:3 if not full else 5], 1):
            reasons = setup.get('reasons') or []
            why = reasons[0] if reasons else 'Setup candidate'
            why2 = reasons[1] if len(reasons) > 1 else 'Confirm only if price strength + volume + sector support'
            lines.extend([
                f"{idx}. <b>{setup.get('ticker')}</b> — {setup.get('setup')} · Score {setup.get('score', '—')}",
                f"   Why: {why}",
                f"   {why2}",
            ])
    else:
        lines.append('— Awaiting scanner + watchlist data')

    if full:
        sectors = data.get('sector_cues') or {}
        og = data.get('overnight_global') or {}
        lines.extend([
            '',
            '<b>Overnight / global (US context only)</b>',
            f"• Sentiment: {og.get('sentiment') or '—'}",
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

    lines.extend([
        '',
        '<b>Rule:</b> Watch for entry — no blind entry before open.',
        'Confirm after 9:15 with price strength + volume + sector support.',
        '<i>No blind entry · confirm after 9:15 · watch for entry only.</i>',
    ])
    text = '\n'.join(lines)
    return _enforce_wording(text)


def _enforce_wording(text: str) -> str:
    lower = text.lower()
    for bad in FORBIDDEN_WORDS:
        if bad in lower:
            text = re.sub(re.escape(bad), 'watch for entry', text, flags=re.IGNORECASE)
    return text


def send_scheduled_premarket(slot: str, *, send_fn: Optional[Callable[[str], bool]] = None) -> bool:
    """Send premarket alert for scheduler slot."""
    from backend.orchestration.alert_freshness_gate import gate_alert_dispatch

    allow, gate_msg = gate_alert_dispatch('PRE_MARKET')
    report = build_premarket_conviction_report(persist=True)
    full = slot in ('premarket_full', 'premarket_action', 'premarket_confirm')
    text = format_premarket_telegram(full=full, report=report)
    if not allow and gate_msg:
        text = f'{text}\n\n<i>{gate_msg}</i>'
    if send_fn:
        return bool(send_fn(text))
    try:
        from backend.telegram.telegram_analysis_bot import send_analysis_message
        return bool(send_analysis_message(text, command=f'premarket_{slot}').get('sent'))
    except Exception as exc:
        _log(f'send failed slot={slot}: {exc}')
        return False
