"""
Catalyst-aware gainer classification — Phase 4B.18.

Classifies radar/gainer/tradecard candidates by catalyst source.
No LLM calls — broker app alerts ingested via /feed text only.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')

STAGE = '4B.18'

CATALYST_CONFIRMED = 'CATALYST_CONFIRMED'
BROKER_APP_ALERT = 'BROKER_APP_ALERT'
PRICE_VOLUME_ONLY = 'PRICE_VOLUME_ONLY'
UNKNOWN_CATALYST = 'UNKNOWN_CATALYST'
THEME_ONLY = 'THEME_ONLY'

CATALYST_STATES = frozenset({
    CATALYST_CONFIRMED,
    BROKER_APP_ALERT,
    PRICE_VOLUME_ONLY,
    UNKNOWN_CATALYST,
    THEME_ONLY,
})

BROKER_APP_ALERT_RE = re.compile(
    r'\b(rating|order|result|regulatory|upgrade)\b.*\balert\b|\balert\b.*\b(rating|order|result|regulatory|upgrade)\b',
    re.I,
)
SYMBOL_HEADLINE_RE = re.compile(
    r'^([A-Z][A-Z0-9]{1,14})\s+(?:rating|quarterly|result|order|regulatory|upgrade)',
    re.I | re.M,
)
TARGET_PRICE_RE = re.compile(
    r'(?:target(?:\s+price)?|tp|price target)\s*(?:to|at|:)?\s*(?:rs\.?|₹)\s*([\d,]+(?:\.\d+)?)',
    re.I,
)
TARGET_PRICE_FALLBACK_RE = re.compile(
    r'(?:rs\.?|₹)\s*([\d,]+(?:\.\d+)?)\s+target',
    re.I,
)
BROKER_NAMES = (
    'motilal oswal', 'investec', 'macquarie', 'goldman sachs', 'morgan stanley',
    'jp morgan', 'jpmorgan', 'clsa', 'icici securities', 'kotak institutional',
    'axis capital', 'nomura', 'jefferies', 'bernstein', 'hsbc', 'citi', 'credit suisse',
    'bank of america', 'bofa', 'ambit', 'elara', 'prabhudas lilladher', 'sharekhan',
)

COMPANY_ALIAS_TO_TICKER: dict[str, str] = {
    'bharat electronics': 'BEL',
    'bharat electronics ltd': 'BEL',
    'metropolis healthcare': 'METROPOLIS',
    'dixon technologies': 'DIXON',
    'hitachi energy india': 'POWERINDIA',
    'siemens energy india': 'ENRIN',
    'h t media': 'HTMEDIA',
    'ht media': 'HTMEDIA',
}

ALERT_TYPE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r'\border\b', re.I), 'order'),
    (re.compile(r'\bresult', re.I), 'result'),
    (re.compile(r'\bregulatory\b', re.I), 'regulatory'),
    (re.compile(r'\bupgrade\b', re.I), 'upgrade'),
    (re.compile(r'\brating\b', re.I), 'rating'),
)

CATALYST_TYPE_FOR_ALERT: dict[str, str] = {
    'order': 'ORDER_WIN',
    'result': 'RESULT_ALERT',
    'regulatory': 'REGULATORY_APPROVAL',
    'upgrade': 'BROKER_UPGRADE',
    'rating': 'BROKER_UPGRADE',
}


def _normalize_ticker(sym: object) -> str:
    return str(sym or '').strip().upper().replace('.NS', '').replace('.BO', '')


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value in (None, ''):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def is_broker_app_alert_text(text: str) -> bool:
    blob = str(text or '').strip()
    if len(blob) < 20:
        return False
    if BROKER_APP_ALERT_RE.search(blob):
        return True
    first = blob.splitlines()[0].strip() if blob else ''
    return bool(SYMBOL_HEADLINE_RE.match(first) and 'alert' in first.lower())


def _resolve_company_ticker(text: str) -> str:
    lower = str(text or '').lower()
    for phrase, ticker in sorted(COMPANY_ALIAS_TO_TICKER.items(), key=lambda x: -len(x[0])):
        if phrase in lower:
            return ticker
    return ''


def _extract_alert_types(text: str) -> list[str]:
    blob = str(text or '')
    found: list[str] = []
    for pattern, label in ALERT_TYPE_RULES:
        if pattern.search(blob) and label not in found:
            found.append(label)
    return found or ['rating']


def _extract_broker(text: str) -> str:
    lower = str(text or '').lower()
    for name in BROKER_NAMES:
        if name in lower:
            return name.title()
    match = re.search(
        r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s+(?:rates?|maintains?|initiated|upgraded|downgraded)\b',
        str(text or ''),
    )
    if match:
        return match.group(1).strip()
    return ''


def _extract_target_price(text: str) -> Optional[float]:
    blob = str(text or '')
    for pattern in (TARGET_PRICE_RE, TARGET_PRICE_FALLBACK_RE):
        match = pattern.search(blob)
        if match:
            try:
                return float(match.group(1).replace(',', ''))
            except ValueError:
                pass
    match = re.search(r'(?:rs\.?|₹)\s*([\d,]+(?:\.\d+)?)', blob, re.I)
    if match and 'target' in blob.lower():
        try:
            return float(match.group(1).replace(',', ''))
        except ValueError:
            pass
    return None


def _extract_symbol_from_headline(text: str) -> str:
    first = str(text or '').strip().splitlines()[0] if text else ''
    match = SYMBOL_HEADLINE_RE.match(first.strip())
    if match:
        return _normalize_ticker(match.group(1))
    match = re.match(r'^([A-Z][A-Z0-9]{1,14})\b', first.strip())
    if match:
        return _normalize_ticker(match.group(1))
    return ''


def parse_broker_app_alert(text: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Parse pasted broker/app alert text into structured catalyst fields."""
    raw = str(text or '').strip()
    ist_now = (now or datetime.now(tz=IST)).replace(microsecond=0)
    symbol = _extract_symbol_from_headline(raw)
    company = ''
    for phrase, ticker in COMPANY_ALIAS_TO_TICKER.items():
        if phrase in raw.lower():
            company = phrase.title()
            if not symbol:
                symbol = ticker
            break
    if not symbol:
        from backend.my_feed.text_extractor import extract_tickers

        tickers = extract_tickers(raw)
        if tickers:
            symbol = _normalize_ticker(tickers[0])
    alert_types = _extract_alert_types(raw)
    broker = _extract_broker(raw)
    target = _extract_target_price(raw)
    confidence = 'high' if symbol and broker else ('medium' if symbol else 'low')
    catalyst_type = CATALYST_TYPE_FOR_ALERT.get(alert_types[0], 'BROKER_UPGRADE')
    summary = ' '.join(raw.split())
    if len(summary) > 240:
        summary = summary[:237] + '...'
    return {
        'symbol': symbol,
        'ticker': symbol,
        'company_name': company,
        'alert_types': alert_types,
        'alert_type': '/'.join(alert_types),
        'broker': broker,
        'source': broker or 'broker app',
        'target_price': target,
        'catalyst_text': raw,
        'headline': raw.splitlines()[0].strip() if raw else '',
        'summary': summary,
        'timestamp': ist_now.isoformat(),
        'confidence': confidence,
        'catalyst_type': catalyst_type,
        'side': 'BULLISH',
        'source_key': 'broker_app',
        'broker_app_alert': True,
    }


def broker_alert_to_catalyst_row(parsed: dict[str, Any]) -> dict[str, Any]:
    """Convert parsed broker alert into opening-board catalyst row shape."""
    sym = _normalize_ticker(parsed.get('symbol') or parsed.get('ticker'))
    headline = str(parsed.get('headline') or parsed.get('summary') or '').strip()
    return {
        'ticker': sym,
        'headline': headline,
        'title': headline,
        'catalyst_type': str(parsed.get('catalyst_type') or 'BROKER_UPGRADE'),
        'side': 'BULLISH',
        'score': 78.0,
        'source_key': 'broker_app',
        'broker_app_alert': True,
        'broker': parsed.get('broker') or '',
        'alert_type': parsed.get('alert_type') or '',
        'target_price': parsed.get('target_price'),
        'summary': parsed.get('summary') or headline,
        'published_at': parsed.get('timestamp'),
        'confidence': parsed.get('confidence') or 'medium',
    }


def _is_broker_app_catalyst(catalyst: dict[str, Any] | None) -> bool:
    if not catalyst:
        return False
    if catalyst.get('broker_app_alert'):
        return True
    source = str(catalyst.get('source_key') or '').lower()
    return source in ('broker_app', 'my_feed_broker_app')


def _has_confirmed_catalyst(catalyst: dict[str, Any] | None) -> bool:
    if not catalyst:
        return False
    if _is_broker_app_catalyst(catalyst):
        return True
    try:
        from backend.trading.opening_rally_radar import _has_direct_catalyst

        return _has_direct_catalyst(catalyst)
    except Exception:
        ctype = str(catalyst.get('catalyst_type') or '').upper()
        side = str(catalyst.get('side') or '').upper()
        if side in ('BEARISH', 'RISK'):
            return False
        return ctype not in ('', 'GENERAL_NEWS', 'SECTOR_NEWS')


def _is_fresh_catalyst(catalyst: dict[str, Any] | None, *, now: datetime | None = None) -> bool:
    if not catalyst:
        return False
    if _is_broker_app_catalyst(catalyst):
        return True
    ts = str(catalyst.get('published_at') or catalyst.get('timestamp') or '')
    if not ts:
        return str(catalyst.get('freshness_label') or '').lower() in ('today', 'recent')
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        age = (now or datetime.now(tz=IST)) - dt.astimezone(IST)
        return age <= timedelta(hours=36)
    except ValueError:
        return True


def _is_price_volume_candidate(
    scanner_row: dict[str, Any] | None,
    gainer_meta: dict[str, Any] | None,
) -> bool:
    change = _safe_float((scanner_row or {}).get('change_percent'))
    vol_ratio = _safe_float((scanner_row or {}).get('volume_ratio'))
    rank = int((gainer_meta or {}).get('rank_in_bucket') or 99)
    if rank <= 10 and change >= 2.0:
        return True
    if vol_ratio >= 1.5 and change >= 1.5:
        return True
    return False


def _is_big_unexplained_move(
    scanner_row: dict[str, Any] | None,
    gainer_meta: dict[str, Any] | None,
) -> bool:
    change = _safe_float((scanner_row or {}).get('change_percent'))
    vol_ratio = _safe_float((scanner_row or {}).get('volume_ratio'))
    rank = int((gainer_meta or {}).get('rank_in_bucket') or 99)
    return change >= 5.0 or (change >= 3.0 and vol_ratio >= 2.0) or rank <= 5


def classify_candidate_catalyst(
    sym: str,
    *,
    catalyst: dict[str, Any] | None = None,
    themes: list[str] | None = None,
    scanner_row: dict[str, Any] | None = None,
    gainer_meta: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return catalyst state + display metadata for one candidate."""
    ticker = _normalize_ticker(sym)
    themes = list(themes or [])
    has_theme = bool(themes)
    fresh = _is_fresh_catalyst(catalyst, now=now)

    if catalyst and _is_broker_app_catalyst(catalyst) and fresh:
        alert_type = str(catalyst.get('alert_type') or 'broker alert')
        broker = str(catalyst.get('broker') or catalyst.get('source') or 'broker app')
        return {
            'state': BROKER_APP_ALERT,
            'ticker': ticker,
            'alert_type': alert_type,
            'broker': broker,
            'source': 'broker app / my_feed',
            'summary': str(catalyst.get('summary') or catalyst.get('headline') or ''),
            'target_price': catalyst.get('target_price'),
            'freshness': 'today',
            'catalyst': catalyst,
            'risk_flags': [],
        }

    if catalyst and _has_confirmed_catalyst(catalyst) and fresh:
        ctype = str(catalyst.get('catalyst_type') or 'news').replace('_', ' ').lower()
        return {
            'state': CATALYST_CONFIRMED,
            'ticker': ticker,
            'alert_type': ctype,
            'broker': str(catalyst.get('broker') or catalyst.get('source_name') or ''),
            'source': str(catalyst.get('source_key') or 'news'),
            'summary': str(catalyst.get('headline') or catalyst.get('title') or catalyst.get('summary') or ''),
            'target_price': catalyst.get('target_price'),
            'freshness': str(catalyst.get('freshness_label') or 'today'),
            'catalyst': catalyst,
            'risk_flags': [],
        }

    if has_theme and not catalyst:
        return {
            'state': THEME_ONLY,
            'ticker': ticker,
            'alert_type': 'theme',
            'broker': '',
            'source': 'theme basket',
            'summary': f'{themes[0].replace("_", " ")} theme match',
            'target_price': None,
            'freshness': 'n/a',
            'catalyst': None,
            'risk_flags': [],
        }

    if _is_price_volume_candidate(scanner_row, gainer_meta):
        flags: list[str] = []
        if _is_big_unexplained_move(scanner_row, gainer_meta):
            flags.append('catalyst not found — confirm manually; no blind chase')
        return {
            'state': PRICE_VOLUME_ONLY,
            'ticker': ticker,
            'alert_type': 'price-volume',
            'broker': '',
            'source': '',
            'summary': '',
            'target_price': None,
            'freshness': 'n/a',
            'catalyst': None,
            'risk_flags': flags,
        }

    if _is_big_unexplained_move(scanner_row, gainer_meta):
        return {
            'state': UNKNOWN_CATALYST,
            'ticker': ticker,
            'alert_type': '',
            'broker': '',
            'source': '',
            'summary': '',
            'target_price': None,
            'freshness': 'n/a',
            'catalyst': None,
            'risk_flags': ['no stock-specific catalyst found', 'price-volume only; confirm manually'],
        }

    return {
        'state': UNKNOWN_CATALYST,
        'ticker': ticker,
        'alert_type': '',
        'broker': '',
        'source': '',
        'summary': '',
        'target_price': None,
        'freshness': 'n/a',
        'catalyst': None,
        'risk_flags': [],
    }


def catalyst_score_boost(classification: dict[str, Any]) -> int:
    """Controlled score delta from catalyst state — no blind news boost."""
    state = str(classification.get('state') or '')
    catalyst = classification.get('catalyst') if isinstance(classification.get('catalyst'), dict) else {}
    if state == CATALYST_CONFIRMED:
        base = 8
        score = _safe_float((catalyst or {}).get('score'), 50.0)
        fresh = str((catalyst or {}).get('freshness_label') or classification.get('freshness') or '')
        if score >= 80 or fresh == 'today':
            return 12
        if score >= 65:
            return 10
        return base
    if state == BROKER_APP_ALERT:
        conf = str(classification.get('confidence') or (catalyst or {}).get('confidence') or '')
        return 8 if conf in ('high', 'medium', '') else 6
    if state == THEME_ONLY:
        return 3
    return 0


def format_catalyst_state_label(state: str) -> str:
    mapping = {
        CATALYST_CONFIRMED: 'CATALYST CONFIRMED',
        BROKER_APP_ALERT: 'CATALYST CONFIRMED',
        PRICE_VOLUME_ONLY: 'PRICE-VOLUME ONLY',
        UNKNOWN_CATALYST: 'UNKNOWN CATALYST',
        THEME_ONLY: 'THEME ONLY',
    }
    return mapping.get(str(state or ''), str(state or '').replace('_', ' '))


def format_catalyst_line(classification: dict[str, Any] | None) -> str:
    """Radar/tradecards catalyst line per 4B.18 spec."""
    if not classification:
        return 'Catalyst: missing — price-volume only'
    state = str(classification.get('state') or '')
    if state in (CATALYST_CONFIRMED, BROKER_APP_ALERT):
        alert = str(classification.get('alert_type') or 'news').lower()
        if state == BROKER_APP_ALERT:
            parts = [p.strip() for p in alert.split('/') if p.strip()]
            label = '/'.join(parts[:2]) if parts else 'broker alert'
            return f'Catalyst: confirmed — {label}'
        if 'result' in alert:
            return 'Catalyst: confirmed — result'
        if 'regulatory' in alert:
            return 'Catalyst: confirmed — regulatory'
        if 'order' in alert:
            return 'Catalyst: confirmed — order'
        if 'broker' in alert or 'upgrade' in alert or 'rating' in alert:
            return 'Catalyst: confirmed — broker/order alert'
        return f'Catalyst: confirmed — {alert}'
    if state == THEME_ONLY:
        return 'Catalyst: theme only — no stock-specific news'
    if state == UNKNOWN_CATALYST:
        return 'Catalyst: missing — unexplained move'
    return 'Catalyst: missing — price-volume only'


def format_catalyst_risk_line(classification: dict[str, Any] | None) -> str:
    flags = list((classification or {}).get('risk_flags') or [])
    state = str((classification or {}).get('state') or '')
    if state == UNKNOWN_CATALYST:
        return 'Risk: no stock-specific catalyst found'
    if state == PRICE_VOLUME_ONLY and flags:
        return f'Risk: {flags[0]}'
    if state == PRICE_VOLUME_ONLY:
        return 'Risk: no stock-specific catalyst found'
    return ''


def apply_catalyst_classification(
    row: dict[str, Any],
    *,
    catalyst: dict[str, Any] | None = None,
    gainer_meta: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Attach classification, adjust score, preserve eligibility for no-news movers."""
    out = dict(row)
    classification = classify_candidate_catalyst(
        out.get('ticker') or '',
        catalyst=catalyst or out.get('catalyst'),
        themes=out.get('themes'),
        scanner_row=out.get('scanner_row') if isinstance(out.get('scanner_row'), dict) else out,
        gainer_meta=gainer_meta,
        now=now,
    )
    out['catalyst_state'] = classification.get('state')
    out['catalyst_classification'] = classification
    out['has_catalyst'] = classification.get('state') in (CATALYST_CONFIRMED, BROKER_APP_ALERT)
    out['catalyst_line'] = format_catalyst_line(classification)
    out['catalyst_risk_line'] = format_catalyst_risk_line(classification)
    if classification.get('state') in (UNKNOWN_CATALYST, PRICE_VOLUME_ONLY) and str(out.get('state') or '') == 'REJECTED':
        change = _safe_float(out.get('change_percent'))
        vol_ratio = _safe_float(out.get('volume_ratio'))
        if change >= 3.0 or vol_ratio >= 1.5:
            out['state'] = 'MOMENTUM_ONLY_WATCH'
    return out


def merge_broker_feed_catalysts(
    catalyst_map: dict[str, dict[str, Any]],
    *,
    limit: int = 40,
) -> dict[str, dict[str, Any]]:
    """Merge /feed broker-app alerts into catalyst map (no full-market scan)."""
    out = dict(catalyst_map)
    try:
        from backend.my_feed.feed_processor import list_feed_items, sanitize_item_for_api

        rows = [sanitize_item_for_api(r) for r in list_feed_items(limit=limit, today_only=False)]
    except Exception:
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        payload = row.get('payload') if isinstance(row.get('payload'), dict) else {}
        if not payload.get('broker_app_alert') and str(row.get('event_type') or '') != 'broker_app_alert':
            raw = str(row.get('raw_user_text') or row.get('cleaned_summary') or '')
            if not is_broker_app_alert_text(raw):
                continue
            parsed = parse_broker_app_alert(raw)
            if not parsed.get('symbol'):
                continue
            cat_row = broker_alert_to_catalyst_row(parsed)
        else:
            parsed = payload.get('broker_alert') if isinstance(payload.get('broker_alert'), dict) else {}
            cat_row = broker_alert_to_catalyst_row(parsed) if parsed else {}
            if not cat_row:
                sym = _normalize_ticker((row.get('tickers') or [''])[0])
                if not sym:
                    continue
                cat_row = broker_alert_to_catalyst_row({
                    'symbol': sym,
                    'headline': row.get('cleaned_summary'),
                    'summary': row.get('cleaned_summary'),
                    'broker': row.get('source_name') or payload.get('broker'),
                    'alert_type': payload.get('alert_type') or 'rating',
                    'target_price': payload.get('target_price'),
                })
        sym = _normalize_ticker(cat_row.get('ticker'))
        if sym and sym not in out:
            out[sym] = cat_row
    return out


def build_extended_catalyst_map(payload: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Catalyst map from radar cache + broker /feed items."""
    from backend.trading.opening_rally_radar import _catalyst_map

    base = _catalyst_map(payload)
    return merge_broker_feed_catalysts(base)


def format_catalyst_symbol_telegram(
    sym: str,
    *,
    board: dict[str, Any] | None = None,
) -> str:
    """Format /catalyst SYMBOL output."""
    from backend.trading.opening_rally_radar import build_opening_rally_board

    ticker = _normalize_ticker(sym)
    if not ticker:
        return 'Usage: /catalyst SYMBOL — e.g. /catalyst BEL'
    data = board or build_opening_rally_board()
    catalyst_map = build_extended_catalyst_map()
    catalyst = catalyst_map.get(ticker)
    row = next(
        (r for r in (data.get('ranked_candidates') or []) if _normalize_ticker(r.get('ticker')) == ticker),
        {},
    )
    scanner_row = row.get('scanner_row') if isinstance(row.get('scanner_row'), dict) else row
    gainer_scan = data.get('gainer_scan') or {}
    gmeta = (gainer_scan.get('by_symbol') or {}).get(ticker) if isinstance(gainer_scan.get('by_symbol'), dict) else None
    if not gmeta:
        try:
            from backend.trading.all_cap_gainers import scan_all_cap_gainers

            gscan = scan_all_cap_gainers(catalyst_map=catalyst_map)
            gmeta = (gscan.get('by_symbol') or {}).get(ticker)
        except Exception:
            gmeta = None
    classification = classify_candidate_catalyst(
        ticker,
        catalyst=catalyst,
        themes=row.get('themes'),
        scanner_row=scanner_row,
        gainer_meta=gmeta,
    )
    used = 'yes' if row else 'no'
    lines = [f'<b>CATALYST — {ticker}</b>']
    state = str(classification.get('state') or UNKNOWN_CATALYST)
    if state in (CATALYST_CONFIRMED, BROKER_APP_ALERT):
        lines.append(f'State: {state}')
        lines.append(f'Type: {classification.get("alert_type") or "alert"}')
        src = str(classification.get('source') or 'news')
        lines.append(f'Source: {src}')
        summary = str(classification.get('summary') or '').strip()
        if summary:
            lines.append(f'Summary: {summary[:200]}')
        target = classification.get('target_price')
        if target not in (None, ''):
            lines.append(f'Target: {target}')
        lines.append(f'Freshness: {classification.get("freshness") or "today"}')
        lines.append(f'Used in radar: {used}')
        return '\n'.join(lines)

    lines.append(f'State: {state}')
    lines.append('No fresh stock-specific catalyst found.')
    action_parts: list[str] = []
    change = _safe_float((scanner_row or {}).get('change_percent'))
    vol = _safe_float((scanner_row or {}).get('volume_ratio'))
    if int((gmeta or {}).get('rank_in_bucket') or 99) <= 10:
        action_parts.append('top gainer')
    if vol >= 1.5:
        action_parts.append('volume ignition')
    elif change >= 2:
        action_parts.append(f'+{change:.1f}% move')
    if action_parts:
        lines.append(f'Market action: {" + ".join(action_parts)}.')
    lines.append('Risk: price-volume only; confirm manually.')
    lines.append(f'Used in radar: {used}')
    return '\n'.join(lines)


def classify_gainer_row_catalyst(
    sym: str,
    meta: dict[str, Any],
    *,
    catalyst_map: dict[str, dict[str, Any]] | None = None,
    scanner_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach catalyst classification to gainer scan meta."""
    cmap = catalyst_map or {}
    classification = classify_candidate_catalyst(
        sym,
        catalyst=cmap.get(_normalize_ticker(sym)),
        themes=None,
        scanner_row=scanner_row,
        gainer_meta=meta,
    )
    return {
        **meta,
        'catalyst_state': classification.get('state'),
        'catalyst_classification': classification,
        'has_catalyst': classification.get('state') in (CATALYST_CONFIRMED, BROKER_APP_ALERT),
        'catalyst_line': format_catalyst_line(classification),
    }
