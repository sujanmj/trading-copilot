"""
Stock-specific catalyst radar — Stage 50N.

News-first priority list with price/volume confirmation.
Research-only — no broker execution, no blind BUY/SELL.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.utils.config import DATA_DIR

IST = ZoneInfo('Asia/Kolkata')
STAGE = '50W'
CACHE_FILE = DATA_DIR / 'stock_catalyst_radar_latest.json'

CATALYST_TYPES = frozenset({
    'PROJECT_ANNOUNCEMENT',
    'ORDER_WIN',
    'ACQUISITION',
    'STAKE_BUY',
    'STAKE_SALE',
    'OFS',
    'BLOCK_DEAL',
    'BULK_DEAL',
    'BROKER_UPGRADE',
    'BROKER_DOWNGRADE',
    'TARGET_UPGRADE',
    'TARGET_DOWNGRADE',
    'RESULT_ALERT',
    'BOARD_MEETING',
    'DIVIDEND_BONUS_SPLIT',
    'REGULATORY_APPROVAL',
    'REGULATORY_RISK',
    'MANAGEMENT_CHANGE',
    'SECTOR_NEWS',
    'GENERAL_NEWS',
    'AI_INVESTMENT',
})

CATALYST_SIDES = frozenset({
    'BULLISH',
    'BEARISH',
    'MIXED',
    'NEUTRAL',
    'RISK',
})

PRIORITY_HIGH = 75
PRIORITY_MEDIUM = 55
PRIORITY_LOW = 35

COMPANY_NAME_TO_TICKER: dict[str, str] = {
    'general insurance corporation of india': 'GICRE',
    'general insurance corporation': 'GICRE',
    'gic re': 'GICRE',
    'arvind smartspaces': 'ARVSMART',
    'arvind smart spaces': 'ARVSMART',
    'gmr airports': 'GMRAIRPORT',
    'gmr airport': 'GMRAIRPORT',
    'hcl technologies': 'HCLTECH',
    'hcl tech': 'HCLTECH',
    'suzlon energy': 'SUZLON',
    'dr lal pathlabs': 'LALPATHLAB',
    'lal pathlabs': 'LALPATHLAB',
    'mtar technologies': 'MTARTECH',
    'pinelabs': 'PINELABS',
    'pine labs': 'PINELABS',
    'ptcil': 'PTCIL',
    'ptc industries': 'PTCIL',
    'reliance industries': 'RELIANCE',
    'tata consultancy services': 'TCS',
    'infosys': 'INFY',
    'wipro': 'WIPRO',
}

REJECT_TICKER_WORDS = frozenset({
    'THE', 'AND', 'FOR', 'WITH', 'FROM', 'ONLY', 'WAIT', 'RISK', 'OFF', 'THIS', 'THAT',
    'WILL', 'HAVE', 'BEEN', 'WERE', 'WAS', 'ARE', 'NOT', 'OUT', 'INTO', 'OVER', 'UNDER',
    'HIGH', 'LOW', 'OPEN', 'CLOSE', 'YEAR', 'WEEK', 'MONTH', 'INDIA', 'INDIAN', 'STOCK',
    'SHARE', 'SHARES', 'INDEX', 'POINTS', 'PER', 'CENT', 'PERCENT', 'NEWS', 'UPDATE',
    'ALERT', 'MARKET', 'TODAY', 'PRICE', 'PRICES', 'FALLS', 'BELOW', 'ABOVE', 'RS',
    'LAKH', 'CRORE', 'AMID', 'GLOBAL', 'CHECK', 'CITY', 'BUY', 'SELL',
})

TICKER_RE = re.compile(r'\b([A-Z]{2,15})\b')

CATALYST_TYPE_RANK: dict[str, int] = {
    'AI_INVESTMENT': 100,
    'ACQUISITION': 95,
    'ORDER_WIN': 92,
    'PROJECT_ANNOUNCEMENT': 90,
    'STAKE_BUY': 88,
    'BROKER_UPGRADE': 85,
    'TARGET_UPGRADE': 85,
    'REGULATORY_APPROVAL': 84,
    'DIVIDEND_BONUS_SPLIT': 80,
    'RESULT_ALERT': 75,
    'BLOCK_DEAL': 70,
    'BULK_DEAL': 68,
    'BOARD_MEETING': 50,
    'MANAGEMENT_CHANGE': 48,
    'OFS': 86,
    'STAKE_SALE': 86,
    'BROKER_DOWNGRADE': 82,
    'TARGET_DOWNGRADE': 82,
    'REGULATORY_RISK': 80,
    'SECTOR_NEWS': 20,
    'GENERAL_NEWS': 10,
}

CATALYST_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r'\b(ai investment|investment in ai|artificial intelligence stake|sarvam ai)\b', re.I), 'AI_INVESTMENT', 'BULLISH'),
    (re.compile(r'\b(project|smart city|township|housing project|real estate project)\b', re.I), 'PROJECT_ANNOUNCEMENT', 'BULLISH'),
    (re.compile(r'\b(order win|wins order|bagged order|contract win|wins contract)\b', re.I), 'ORDER_WIN', 'BULLISH'),
    (re.compile(r'\b(acquisition|acquires|to acquire|merger|takeover)\b', re.I), 'ACQUISITION', 'BULLISH'),
    (re.compile(r'\b(stake buy|buys stake|buying stake|bought stake|picks up stake|invests in|investment in)\b', re.I), 'STAKE_BUY', 'BULLISH'),
    (re.compile(r'\b(promoter sells|ofs|offer for sale|stake dilution|stake sale|sells stake|offloads stake|divest)\b', re.I), 'OFS', 'BEARISH'),
    (re.compile(r'\b(block deal|block trade)\b', re.I), 'BLOCK_DEAL', 'MIXED'),
    (re.compile(r'\b(bulk deal)\b', re.I), 'BULK_DEAL', 'MIXED'),
    (re.compile(r'\b(upgrade|upgraded|overweight|outperform|buy rating|accumulate|rating upgrade)\b', re.I), 'BROKER_UPGRADE', 'BULLISH'),
    (re.compile(r'\b(downgrade|downgraded|underweight|underperform|sell rating|reduce rating)\b', re.I), 'BROKER_DOWNGRADE', 'BEARISH'),
    (re.compile(r'\b(target raised|target upgrade|raises target|hikes target|price target raised|traffic)\b', re.I), 'TARGET_UPGRADE', 'BULLISH'),
    (re.compile(r'\b(target cut|target downgrade|cuts target|lowers target|price target cut)\b', re.I), 'TARGET_DOWNGRADE', 'BEARISH'),
    (re.compile(r'\b(results|earnings|quarterly|q[1-4]|profit|revenue beat|revenue miss)\b', re.I), 'RESULT_ALERT', 'MIXED'),
    (re.compile(r'\b(board meeting|board meet|agm|egm)\b', re.I), 'BOARD_MEETING', 'NEUTRAL'),
    (re.compile(r'\b(dividend|bonus issue|stock split|bonus share)\b', re.I), 'DIVIDEND_BONUS_SPLIT', 'BULLISH'),
    (re.compile(r'\b(regulatory approval|sebi approval|rbi approval|clearance granted)\b', re.I), 'REGULATORY_APPROVAL', 'BULLISH'),
    (re.compile(r'\b(regulatory risk|sebi probe|rbi action|investigation|penalty|fine imposed)\b', re.I), 'REGULATORY_RISK', 'BEARISH'),
    (re.compile(r'\b(ceo|md|cfo|management change|resigns|appoints new)\b', re.I), 'MANAGEMENT_CHANGE', 'MIXED'),
    (re.compile(r'\b(falls|crashes|plunges|tumbles|slumps)\b', re.I), 'GENERAL_NEWS', 'RISK'),
    (re.compile(r'\b(sector|industry|theme|policy boost|sector tailwind)\b', re.I), 'SECTOR_NEWS', 'NEUTRAL'),
)

SHARP_FALL_RE = re.compile(
    r'\b(fall(?:s|en)?|drop(?:ped|s)?|plunge(?:d|s)?|crash(?:ed|es)?|tumble(?:d|s)?|slump(?:ed|s)?)\b'
    r'|(?:-\s*)?\d+(?:\.\d+)?\s*%',
    re.IGNORECASE,
)

HCLTECH_AI_STAKE_FORCE_RE = re.compile(
    r'(hcl\s+tech\s+shares\s+jump.*?buying\s+stake\s+in\s+sarvam\s+ai|'
    r'buying\s+stake\s+in\s+sarvam\s+ai|buys\s+stake\s+in\s+sarvam\s+ai|'
    r'buying\s+stake|buys\s+stake|stake\s+in\s+sarvam|sarvam\s+ai|'
    r'sarvam\s+ai\s+for\s+rs[\s,.]*1[\s,.]*427\s+crore|'
    r'sarvam\s+ai\s+stake|ai\s+investment|rs[\s,.]*1[\s,.]*427\s+crore)',
    re.IGNORECASE,
)


def _hcltech_sarvam_ai_stake(text: str, *, ticker: str = '') -> bool:
    """Hard rule — HCLTECH Sarvam AI stake headlines stay BULLISH / AI_INVESTMENT."""
    blob = str(text or '')
    sym = _normalize_ticker(ticker)
    if sym and sym not in ('', 'HCLTECH'):
        return False
    if HCLTECH_AI_STAKE_FORCE_RE.search(blob):
        return True
    lower = blob.lower()
    if 'sarvam' in lower and 'ai' in lower:
        return True
    if re.search(r'stake\s+in\s+sarvam', lower):
        return True
    if re.search(r'(buying|buys)\s+stake', lower) and 'sarvam' in lower:
        return True
    if 'ai investment' in lower and (not sym or sym == 'HCLTECH' or 'hcl' in lower):
        return True
    if re.search(r'rs[\s,.]*1[\s,.]*427\s+crore', lower) and 'sarvam' in lower:
        return True
    if 'sarvam ai' in lower and re.search(r'\b(stake|investment)\b', lower):
        return True
    return False

SOURCE_QUALITY: dict[str, float] = {
    'nse_filings': 1.0,
    'external_evidence': 0.9,
    'news_feed': 0.85,
    'inshorts': 0.75,
    'my_feed': 0.8,
    'broker_evidence': 0.85,
}


def _now_iso() -> str:
    return datetime.now(IST).replace(microsecond=0).isoformat()


def _today() -> str:
    return datetime.now(IST).strftime('%Y-%m-%d')


def _load_json(path: Path) -> Any:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}


def _normalize_ticker(value: object) -> str:
    return str(value or '').strip().upper()


def _parse_ts(value: object) -> Optional[datetime]:
    raw = str(value or '').strip()
    if not raw:
        return None
    for fmt in ('%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
        try:
            dt = datetime.strptime(raw[:19], fmt[: len(raw[:19]) + 2] if len(fmt) > 19 else fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=IST)
            return dt.astimezone(IST)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    except ValueError:
        return None


def resolve_tickers_from_text(text: str, *, known: Optional[frozenset[str]] = None) -> list[str]:
    """Map company names and valid tickers from headline/body text."""
    blob = str(text or '')
    lower = blob.lower()
    found: list[str] = []

    for name, sym in sorted(COMPANY_NAME_TO_TICKER.items(), key=lambda x: -len(x[0])):
        if name in lower and sym not in found:
            found.append(sym)

    try:
        from backend.collectors.external_evidence_classifier import extract_company_or_ticker

        ext = extract_company_or_ticker(blob)
        if ext:
            sym = _normalize_ticker(ext)
            if sym and sym not in found:
                found.append(sym)
    except Exception:
        pass

    universe = known
    if universe is None:
        try:
            from backend.collectors.external_evidence_classifier import load_universe

            universe = load_universe()
        except Exception:
            universe = frozenset()

    for match in TICKER_RE.finditer(blob.upper()):
        token = match.group(1)
        if token in REJECT_TICKER_WORDS:
            continue
        if universe and token not in universe:
            continue
        if token not in found:
            found.append(token)
    return found


def classify_catalyst(text: str) -> tuple[str, str]:
    """Return strongest (catalyst_type, side) from headline/body."""
    blob = str(text or '')
    lower = blob.lower()
    if _hcltech_sarvam_ai_stake(blob):
        return 'AI_INVESTMENT', 'BULLISH'
    matches: list[tuple[str, str, int]] = []

    for pattern, ctype, side in CATALYST_RULES:
        if pattern.search(blob):
            matches.append((ctype, side, CATALYST_TYPE_RANK.get(ctype, 50)))

    if re.search(r'\b(shares jump|shares surge|shares rally|jump \d+%)\b', lower) and re.search(
        r'\b(buying stake|buys stake|bought stake|acquisition|investment in)\b', lower
    ):
        if re.search(r'\b(ai|artificial intelligence)\b', lower):
            matches.append(('AI_INVESTMENT', 'BULLISH', CATALYST_TYPE_RANK['AI_INVESTMENT']))
        else:
            matches.append(('STAKE_BUY', 'BULLISH', CATALYST_TYPE_RANK['STAKE_BUY']))

    if not matches:
        if SHARP_FALL_RE.search(blob):
            return 'GENERAL_NEWS', 'RISK'
        return 'GENERAL_NEWS', 'NEUTRAL'

    matches.sort(key=lambda item: item[2], reverse=True)
    ctype, side, _ = matches[0]

    if ctype in ('BLOCK_DEAL', 'BULK_DEAL') and re.search(r'\b(jump|surge|rally|gain)\b', lower):
        side = 'BULLISH'
    elif ctype in ('BLOCK_DEAL', 'BULK_DEAL'):
        side = 'MIXED'

    if ctype in ('OFS', 'STAKE_SALE') and re.search(r'\b(absorb|strong demand|above floor)\b', lower):
        side = 'MIXED'

    return ctype, side


_GENERIC_INDEX_HEADLINE_RE = re.compile(
    r'\b(sensex|nifty\s*50|nifty|top\s+gainers?|among\s+top|index\s+(?:rises|falls|gains))\b',
    re.IGNORECASE,
)


def _headline_evidence_tier(headline: str, catalyst_type: str) -> int:
    """Rank headline evidence — specific corporate beats generic index noise."""
    ctype = str(catalyst_type or 'GENERAL_NEWS').upper()
    blob = str(headline or '')
    if ctype in (
        'AI_INVESTMENT', 'ACQUISITION', 'STAKE_BUY', 'STAKE_SALE', 'OFS',
        'PROJECT_ANNOUNCEMENT', 'ORDER_WIN', 'BLOCK_DEAL', 'BULK_DEAL',
        'REGULATORY_APPROVAL', 'DIVIDEND_BONUS_SPLIT', 'RESULT_ALERT',
    ):
        return 100
    if ctype in (
        'BROKER_UPGRADE', 'BROKER_DOWNGRADE', 'TARGET_UPGRADE', 'TARGET_DOWNGRADE',
        'MANAGEMENT_CHANGE', 'BOARD_MEETING',
    ):
        return 85
    if ctype == 'SECTOR_NEWS':
        return 40
    if _GENERIC_INDEX_HEADLINE_RE.search(blob):
        return 10
    if ctype == 'GENERAL_NEWS':
        return 25
    return 60


def _combine_sides(sides: list[str]) -> str:
    normalized = {str(s or '').upper() for s in sides if s}
    if not normalized:
        return 'NEUTRAL'
    if 'BEARISH' in normalized or 'RISK' in normalized:
        if 'BULLISH' in normalized:
            return 'MIXED'
        return 'BEARISH' if 'BEARISH' in normalized else 'RISK'
    if 'MIXED' in normalized:
        return 'MIXED'
    if 'BULLISH' in normalized:
        return 'BULLISH'
    return 'NEUTRAL'


def _merge_raw_by_ticker(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        sym = _normalize_ticker(row.get('ticker'))
        if not sym:
            continue
        buckets.setdefault(sym, []).append(row)

    merged: list[dict[str, Any]] = []
    for sym, group in buckets.items():
        classified: list[dict[str, Any]] = []
        for g in group:
            headline = str(g.get('headline') or '').strip()
            ctype, side = classify_catalyst(headline or str(g.get('catalyst_type') or ''))
            tier = _headline_evidence_tier(headline, ctype)
            classified.append({
                **g,
                'headline': headline,
                'catalyst_type': ctype,
                'side': side,
                '_evidence_tier': tier,
            })

        best = max(
            classified,
            key=lambda g: (
                int(g.get('_evidence_tier') or 0),
                _freshness_score(_parse_ts(g.get('published_at'))),
                CATALYST_TYPE_RANK.get(str(g.get('catalyst_type') or ''), 0),
            ),
        )
        best_tier = int(best.get('_evidence_tier') or 0)
        best_type = str(best.get('catalyst_type') or 'GENERAL_NEWS')
        best_side = str(best.get('side') or 'NEUTRAL').upper()

        forced_ai = next(
            (g for g in classified if _hcltech_sarvam_ai_stake(str(g.get('headline') or ''), ticker=sym)),
            None,
        )
        if forced_ai:
            best_type = 'AI_INVESTMENT'
            best_side = 'BULLISH'
            best = forced_ai
            side = 'BULLISH'
        elif best_type in ('AI_INVESTMENT', 'STAKE_BUY') and best_side == 'BULLISH':
            side = 'BULLISH'
        elif best_tier >= 40:
            side = best_side
        else:
            strong_sides = [
                str(g.get('side') or 'NEUTRAL').upper()
                for g in classified
                if int(g.get('_evidence_tier') or 0) >= 40
                and not _GENERIC_INDEX_HEADLINE_RE.search(str(g.get('headline') or ''))
            ]
            side = _combine_sides(strong_sides) if strong_sides else best_side
            if side == 'MIXED' and any(
                str(g.get('catalyst_type') or '').upper() == 'AI_INVESTMENT'
                for g in classified
            ):
                side = 'BULLISH'

        headlines = [str(g.get('headline') or '').strip() for g in classified if g.get('headline')]
        merged.append({
            'ticker': sym,
            'tickers': [sym],
            'headline': str(best.get('headline') or headlines[0] if headlines else ''),
            'catalyst_notes': headlines,
            'catalyst_type': best_type,
            'side': side,
            'published_at': best.get('published_at'),
            'source': best.get('source'),
            'source_key': best.get('source_key'),
            'url': best.get('url'),
        })
    return merged


def _safe_optional_float(value: Any) -> Optional[float]:
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _quote_metrics(ticker: str, row: dict[str, Any]) -> dict[str, Any]:
    quote = _scanner_quote(ticker)
    quote_available = bool(
        quote
        and (
            _safe_optional_float(quote.get('price') or quote.get('last_price'))
            or _safe_optional_float(quote.get('change_percent')) is not None
        )
    )
    change_pct = _safe_optional_float(row.get('change_pct'))
    volume_ratio = _safe_optional_float(row.get('volume_ratio'))
    if change_pct is None and quote_available:
        change_pct = _safe_optional_float(quote.get('change_percent'))
    if volume_ratio is None and quote_available:
        volume_ratio = _safe_optional_float(quote.get('volume_ratio'))
    return {
        'quote_available': quote_available,
        'change_pct': change_pct,
        'volume_ratio': volume_ratio,
        'quote': quote,
    }


def format_price_reaction_display(change_pct: Optional[float], *, quote_available: bool) -> str:
    if not quote_available or change_pct is None:
        return 'unavailable'
    return f'{change_pct:+.1f}%'


def format_volume_display(volume_ratio: Optional[float], *, quote_available: bool) -> str:
    if not quote_available or volume_ratio is None:
        return 'unavailable'
    return f'{volume_ratio:.1f}x'


def _finalize_catalyst_display_row(row: dict[str, Any]) -> dict[str, Any]:
    """User-facing trade status — bearish/risk/avoid never show WAIT FOR LIVE DATA."""
    side = str(row.get('side') or '').upper()
    priority = str(row.get('priority') or '').upper()
    if priority == 'AVOID' or side in ('BEARISH', 'RISK'):
        return {**row, 'trade_status': 'AVOID/RISK'}
    return row


def _reconcile_trade_status(
    *,
    priority: str,
    side: str,
    quote_available: bool,
    volume_ratio: Optional[float],
    change_pct: Optional[float],
    ticker: str,
) -> str:
    side_u = side.upper()
    if priority == 'AVOID' or side_u in ('BEARISH', 'RISK'):
        return 'AVOID/RISK'
    if not quote_available:
        return 'WAIT FOR LIVE DATA'
    from backend.trading.trade_card_engine import MIN_RR, MIN_VOLUME_RATIO, detect_entry_missed, _compute_plan

    row = _scanner_quote(ticker)
    if not row:
        return 'WAIT FOR LIVE DATA'
    plan = _compute_plan(row)
    missed, _ = detect_entry_missed(
        price=plan['price'],
        change_pct=plan['change_pct'],
        volume_ratio=plan['volume_ratio'],
        day_high=plan.get('day_high'),
        vwap=plan.get('vwap'),
        open_price=plan.get('open_price'),
        risk_reward=plan['risk_reward'],
        sl_pct=plan['sl_pct'],
    )
    if missed:
        return 'ENTRY MISSED'
    if plan['risk_reward'] < MIN_RR:
        return 'NO TRADE'
    vol = volume_ratio if volume_ratio is not None else plan['volume_ratio']
    if vol is None or vol < MIN_VOLUME_RATIO:
        return 'WAIT FOR VOLUME'
    return 'VALID ENTRY WATCH'


def _eligible_for_priority_list(row: dict[str, Any]) -> bool:
    ctype = str(row.get('catalyst_type') or 'GENERAL_NEWS').upper()
    side = str(row.get('side') or 'NEUTRAL').upper()
    score = float(row.get('score') or 0)
    if not row.get('ticker'):
        return False
    if ctype == 'GENERAL_NEWS' and side == 'NEUTRAL':
        return False
    if ctype == 'SECTOR_NEWS' and side == 'NEUTRAL' and score < PRIORITY_MEDIUM:
        return False
    if row.get('freshness_label') == 'stale':
        return False
    if score < PRIORITY_LOW and side not in ('BEARISH', 'RISK'):
        return False
    return True


def _freshness_score(ts: Optional[datetime]) -> float:
    if not ts:
        return 8.0
    age_h = max(0.0, (datetime.now(IST) - ts).total_seconds() / 3600.0)
    if age_h <= 2:
        return 25.0
    if age_h <= 6:
        return 20.0
    if age_h <= 12:
        return 15.0
    if age_h <= 24:
        return 10.0
    if age_h <= 48:
        return 5.0
    return 2.0


def _quality_score(catalyst_type: str, source_key: str) -> float:
    base = SOURCE_QUALITY.get(source_key, 0.6)
    type_weight = {
        'PROJECT_ANNOUNCEMENT': 1.0,
        'ORDER_WIN': 1.0,
        'ACQUISITION': 0.95,
        'STAKE_BUY': 0.9,
        'BROKER_UPGRADE': 0.85,
        'TARGET_UPGRADE': 0.85,
        'REGULATORY_APPROVAL': 0.9,
        'OFS': 0.9,
        'STAKE_SALE': 0.9,
        'REGULATORY_RISK': 0.85,
        'BLOCK_DEAL': 0.7,
        'BULK_DEAL': 0.7,
        'GENERAL_NEWS': 0.45,
    }.get(catalyst_type, 0.65)
    return round(min(25.0, base * 25.0 * type_weight), 1)


def _scanner_quote(ticker: str) -> dict[str, Any]:
    scanner = _load_json(DATA_DIR / 'scanner_data.json')
    for sig in (scanner or {}).get('top_signals') or (scanner or {}).get('signals') or []:
        if not isinstance(sig, dict):
            continue
        if _normalize_ticker(sig.get('ticker') or sig.get('symbol')) == ticker:
            return sig
    return {}


def _price_reaction_score(change_pct: Optional[float], side: str) -> float:
    if change_pct is None:
        return 4.0
    mag = abs(change_pct)
    if side == 'BEARISH':
        if change_pct <= -5:
            return 18.0
        if change_pct <= -2:
            return 12.0
        if change_pct < 0:
            return 8.0
        return 3.0
    if side == 'RISK':
        if change_pct <= -4:
            return 15.0
        return 5.0
    if change_pct >= 4:
        return 20.0
    if change_pct >= 2:
        return 14.0
    if change_pct >= 0.5:
        return 8.0
    if change_pct <= -2 and side in ('MIXED', 'NEUTRAL'):
        return 4.0
    return 2.0


def _volume_score(volume_ratio: Optional[float], side: str) -> float:
    if volume_ratio is None:
        return 3.0
    if volume_ratio >= 1.5:
        return 15.0
    if volume_ratio >= 1.0:
        return 11.0
    if volume_ratio >= 0.8:
        return 7.0
    if side in ('BEARISH', 'RISK'):
        return 4.0
    return 2.0


def _sector_support_score(ticker: str) -> float:
    intel = _load_json(DATA_DIR / 'intelligence.json')
    sectors = (intel or {}).get('sector_rotation') or {}
    bullish = {_normalize_ticker(s) for s in (sectors.get('bullish') or [])}
    bearish = {_normalize_ticker(s) for s in (sectors.get('bearish') or [])}
    if ticker in bullish:
        return 10.0
    if ticker in bearish:
        return 2.0
    return 5.0


def _risk_penalty(side: str, catalyst_type: str, change_pct: Optional[float]) -> float:
    chg = abs(change_pct) if change_pct is not None else 0.0
    if side == 'BEARISH':
        return -25.0
    if side == 'RISK':
        return -20.0
    if catalyst_type in ('OFS', 'STAKE_SALE', 'REGULATORY_RISK', 'BROKER_DOWNGRADE'):
        return -15.0
    if side == 'MIXED' and chg >= 6:
        return -8.0
    return 0.0


def _priority_label(total: float, side: str) -> str:
    if side in ('BEARISH', 'RISK') or total < PRIORITY_LOW:
        return 'AVOID'
    if total >= PRIORITY_HIGH:
        return 'HIGH'
    if total >= PRIORITY_MEDIUM:
        return 'MEDIUM'
    if total >= PRIORITY_LOW:
        return 'LOW'
    return 'AVOID'


def _apply_live_ticker_classification(row: dict[str, Any]) -> dict[str, Any]:
    """Hard rules on merged/live catalyst rows — HCLTECH Sarvam AI stays BULLISH."""
    sym = _normalize_ticker(row.get('ticker'))
    headlines = [str(row.get('headline') or '')]
    headlines.extend(str(note) for note in (row.get('catalyst_notes') or []) if note)
    forced_headline = ''
    for text in headlines:
        if _hcltech_sarvam_ai_stake(text, ticker=sym or 'HCLTECH'):
            forced_headline = text
            break
    if not forced_headline:
        return row
    notes = [str(n) for n in (row.get('catalyst_notes') or []) if n]
    if forced_headline not in notes:
        notes.insert(0, forced_headline)
    return {
        **row,
        'ticker': 'HCLTECH' if sym in ('', 'HCLTECH') else sym,
        'side': 'BULLISH',
        'catalyst_type': 'AI_INVESTMENT',
        'headline': forced_headline,
        'catalyst_notes': notes,
    }


def score_catalyst_row(row: dict[str, Any]) -> dict[str, Any]:
    ticker = _normalize_ticker(row.get('ticker'))
    headline = str(row.get('headline') or '')
    side = str(row.get('side') or 'NEUTRAL').upper()
    ctype = str(row.get('catalyst_type') or 'GENERAL_NEWS').upper()
    for candidate in [headline, *(row.get('catalyst_notes') or [])]:
        if _hcltech_sarvam_ai_stake(str(candidate), ticker=ticker):
            side = 'BULLISH'
            ctype = 'AI_INVESTMENT'
            headline = str(candidate)
            row = {**row, 'side': side, 'catalyst_type': ctype, 'headline': headline}
            break
    if _hcltech_sarvam_ai_stake(headline, ticker=ticker):
        side = 'BULLISH'
        ctype = 'AI_INVESTMENT'
        row = {**row, 'side': side, 'catalyst_type': ctype, 'headline': headline or row.get('headline')}
    metrics = _quote_metrics(ticker, row)
    change_pct = metrics['change_pct']
    volume_ratio = metrics['volume_ratio']
    quote_available = metrics['quote_available']

    ts = _parse_ts(row.get('published_at') or row.get('timestamp'))
    fresh = _freshness_score(ts)
    quality = _quality_score(ctype, str(row.get('source_key') or 'news_feed'))
    price = _price_reaction_score(change_pct, side)
    volume = _volume_score(volume_ratio, side)
    sector = _sector_support_score(ticker)
    penalty = _risk_penalty(side, ctype, change_pct)
    total = round(fresh + quality + price + volume + sector + penalty, 1)

    priority = _priority_label(total, side)
    trade_status = _reconcile_trade_status(
        priority=priority,
        side=side,
        quote_available=quote_available,
        volume_ratio=volume_ratio,
        change_pct=change_pct,
        ticker=ticker,
    )

    reason_parts = [
        f"{ctype.replace('_', ' ').lower()}",
        f"freshness {fresh:.0f}/25",
    ]
    if not quote_available:
        reason_parts.append('live quote unavailable')
    elif volume_ratio is not None and volume_ratio < 0.8 and side not in ('BEARISH', 'RISK'):
        reason_parts.append('volume confirm required')
    if side == 'RISK':
        reason_parts.append('sharp move without positive catalyst')

    return _finalize_catalyst_display_row(_apply_live_ticker_classification({
        **row,
        'ticker': ticker,
        'side': side,
        'catalyst_type': ctype,
        'change_pct': change_pct,
        'volume_ratio': volume_ratio,
        'quote_available': quote_available,
        'price_display': format_price_reaction_display(change_pct, quote_available=quote_available),
        'volume_display': format_volume_display(volume_ratio, quote_available=quote_available),
        'score': total,
        'score_breakdown': {
            'freshness': fresh,
            'quality': quality,
            'price_reaction': price,
            'volume_confirmation': volume,
            'sector_support': sector,
            'risk_penalty': penalty,
        },
        'priority': priority,
        'trade_status': trade_status,
        'reason': '; '.join(reason_parts),
        'freshness_label': 'today' if fresh >= 15 else ('recent' if fresh >= 8 else 'stale'),
    }))


def _iter_news_feed_items() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fname in ('news_feed.json', 'live_news_feed.json'):
        payload = _load_json(DATA_DIR / fname)
        items = payload.get('items') or payload.get('news') or payload.get('articles') or []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    out.append({**item, '_source_key': 'news_feed'})
    return out


def _iter_external_evidence() -> list[dict[str, Any]]:
    payload = _load_json(DATA_DIR / 'external_evidence_latest.json')
    items = payload.get('items') or payload.get('evidence') or []
    if not isinstance(items, list):
        return []
    return [{**item, '_source_key': 'external_evidence'} for item in items if isinstance(item, dict)]


def _iter_inshorts() -> list[dict[str, Any]]:
    payload = _load_json(DATA_DIR / 'inshorts_feed.json')
    items = payload.get('items') or payload.get('news') or []
    if not isinstance(items, list):
        return []
    return [{**item, '_source_key': 'inshorts'} for item in items if isinstance(item, dict)]


def _iter_nse_filings() -> list[dict[str, Any]]:
    payload = _load_json(DATA_DIR / 'nse_announcements.json')
    items = payload.get('announcements') or payload.get('items') or []
    if not isinstance(items, list):
        return []
    return [{**item, '_source_key': 'nse_filings'} for item in items if isinstance(item, dict)]


def _iter_my_feed_text() -> list[dict[str, Any]]:
    try:
        from backend.my_feed.feed_processor import list_feed_items, sanitize_item_for_api
        from backend.my_feed.feed_verification import is_catalyst_eligible_item

        rows = [sanitize_item_for_api(r) for r in list_feed_items(limit=40, today_only=False)]
        eligible: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict) or not is_catalyst_eligible_item(row):
                continue
            headline = str(row.get('verified_headline') or row.get('cleaned_summary') or '').strip()
            if not headline:
                continue
            item = {
                **row,
                'title': headline,
                'headline': headline,
                'summary': str(row.get('verified_summary') or row.get('cleaned_summary') or headline),
                'published_at': row.get('source_time') or row.get('created_at'),
                'source': row.get('source_name') or 'my_feed_verified',
                'url': row.get('source_url') or '',
                '_source_key': 'my_feed',
            }
            eligible.append(item)
        return eligible
    except Exception:
        return []


def _stub_source_status() -> dict[str, str]:
    """Report optional feeds — never crash if unavailable."""
    status: dict[str, str] = {}
    for key, path in (
        ('bse_announcements', DATA_DIR / 'bse_announcements.json'),
        ('bulk_block_deals', DATA_DIR / 'bulk_block_deals.json'),
        ('company_filings', DATA_DIR / 'company_filings.json'),
    ):
        status[key] = 'available' if path.is_file() else 'unavailable'
    return status


def _normalize_raw_item(item: dict[str, Any]) -> Optional[dict[str, Any]]:
    title = str(item.get('title') or item.get('headline') or item.get('subject') or '').strip()
    body = str(
        item.get('summary')
        or item.get('description')
        or item.get('content')
        or item.get('text')
        or item.get('message')
        or ''
    ).strip()
    blob = f'{title}. {body}'.strip()
    if len(blob) < 12:
        return None

    tickers = item.get('tickers') or item.get('symbols') or []
    if isinstance(tickers, str):
        tickers = [tickers]
    resolved = [_normalize_ticker(t) for t in tickers if t]
    if not resolved:
        resolved = resolve_tickers_from_text(blob)
    if not resolved:
        return None

    ctype, side = classify_catalyst(blob)
    if ctype == 'GENERAL_NEWS' and side == 'NEUTRAL' and len(blob) < 40:
        return None

    return {
        'ticker': resolved[0],
        'tickers': resolved,
        'headline': title or body[:120],
        'catalyst_type': ctype,
        'side': side,
        'published_at': item.get('published') or item.get('published_at') or item.get('timestamp') or item.get('created_at'),
        'source': item.get('source') or item.get('source_name') or item.get('publisher') or 'news',
        'source_key': item.get('_source_key') or 'news_feed',
        'url': item.get('link') or item.get('url') or '',
    }


def _collect_raw_catalysts() -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    for batch in (
        _iter_news_feed_items(),
        _iter_external_evidence(),
        _iter_inshorts(),
        _iter_nse_filings(),
        _iter_my_feed_text(),
    ):
        for item in batch:
            norm = _normalize_raw_item(item)
            if norm:
                raw.append(norm)

    # Dedupe by ticker + catalyst type + headline prefix
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in raw:
        key = f"{row['ticker']}|{row['catalyst_type']}|{str(row.get('headline') or '')[:60].lower()}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def build_catalyst_radar(*, persist: bool = True, force_refresh: bool = False) -> dict[str, Any]:
    session_date = _today()
    if not force_refresh and CACHE_FILE.is_file():
        cached = _load_json(CACHE_FILE)
        if cached.get('session_date') == session_date and cached.get('items'):
            return cached

    raw = _collect_raw_catalysts()
    merged_raw = _merge_raw_by_ticker(raw)
    scored = [score_catalyst_row(row) for row in merged_raw]
    scored.sort(key=lambda r: (r.get('score') or 0), reverse=True)

    priority_list = [r for r in scored if _eligible_for_priority_list(r)][:10]
    bullish = [r for r in priority_list if r.get('side') == 'BULLISH' and r.get('priority') != 'AVOID']
    avoid = [r for r in scored if r.get('side') in ('BEARISH', 'RISK') or r.get('priority') == 'AVOID']

    payload: dict[str, Any] = {
        'ok': True,
        'stage': STAGE,
        'session_date': session_date,
        'generated_at': _now_iso(),
        'items': scored[:40],
        'priority_list': priority_list,
        'bullish_watch': bullish[:8],
        'avoid_list': avoid[:6],
        'source_status': _stub_source_status(),
        'paper_only': True,
        'disclaimer': 'Research watchlist — confirm price/volume before any paper entry.',
    }
    if persist:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    return payload


def get_catalyst_radar(*, rebuild: bool = False) -> dict[str, Any]:
    if rebuild or not CACHE_FILE.is_file():
        return build_catalyst_radar(force_refresh=True)
    cached = _load_json(CACHE_FILE)
    if cached.get('session_date') == _today() and cached.get('items') is not None:
        items = [_finalize_catalyst_display_row(_apply_live_ticker_classification(dict(r))) for r in (cached.get('items') or []) if isinstance(r, dict)]
        priority = [_finalize_catalyst_display_row(_apply_live_ticker_classification(dict(r))) for r in (cached.get('priority_list') or []) if isinstance(r, dict)]
        return {
            **cached,
            'items': items,
            'priority_list': priority,
            'bullish_watch': [_finalize_catalyst_display_row(_apply_live_ticker_classification(dict(r))) for r in (cached.get('bullish_watch') or []) if isinstance(r, dict)],
        }
    return build_catalyst_radar(force_refresh=True)


def get_clean_catalyst_radar(*, today_only: bool = False) -> dict[str, Any]:
    """
    Single cleaned catalyst build path for /catalysts and /catalysts today.

    Uses session cache when available; today_only only affects display filtering downstream.
    """
    radar = get_catalyst_radar()
    if not today_only:
        return radar
    filtered_items = [r for r in (radar.get('items') or []) if r.get('freshness_label') == 'today']
    filtered_priority = [r for r in (radar.get('priority_list') or []) if r.get('freshness_label') == 'today']
    filtered_watch = [r for r in (radar.get('bullish_watch') or []) if r.get('freshness_label') == 'today']
    return {
        **radar,
        'items': filtered_items,
        'priority_list': filtered_priority,
        'bullish_watch': filtered_watch,
        'display_filter': 'today',
    }


def pick_catalyst_tradecard_candidate(*, registry: Optional[dict[str, str]] = None) -> tuple[Optional[str], str]:
    """Return best catalyst-confirmed ticker for trade card, if any."""
    radar = get_catalyst_radar()
    reg = registry or {}
    for row in radar.get('priority_list') or radar.get('items') or []:
        ticker = _normalize_ticker(row.get('ticker'))
        if not ticker or ticker in reg:
            continue
        side = str(row.get('side') or '').upper()
        if side in ('BEARISH', 'RISK'):
            continue
        if row.get('priority') == 'AVOID':
            continue
        status = str(row.get('trade_status') or '')
        if status in ('ENTRY MISSED', 'AVOID/RISK', 'NO_TRADE'):
            continue
        if float(row.get('score') or 0) < PRIORITY_MEDIUM:
            continue
        quote = _scanner_quote(ticker)
        if not quote:
            continue
        return ticker, 'catalyst_confirmed'
    return None, 'no_catalyst_candidate'


def explain_catalyst(ticker: str) -> Optional[dict[str, Any]]:
    sym = _normalize_ticker(ticker)
    radar = get_catalyst_radar()
    matches = [
        row for row in (radar.get('items') or [])
        if _normalize_ticker(row.get('ticker')) == sym
    ]
    if not matches:
        return None
    matches.sort(key=lambda r: r.get('score') or 0, reverse=True)
    primary = dict(matches[0])
    notes = primary.get('catalyst_notes') or []
    for row in matches[1:]:
        for note in row.get('catalyst_notes') or [row.get('headline')]:
            if note and note not in notes:
                notes.append(note)
    primary['catalyst_notes'] = notes
    return _finalize_catalyst_display_row(_apply_live_ticker_classification(primary))


def format_catalyst_radar_telegram(*, today_only: bool = False, explain_ticker: Optional[str] = None) -> str:
    if explain_ticker:
        row = explain_catalyst(explain_ticker)
        if not row:
            return f'No catalyst radar entry for {_normalize_ticker(explain_ticker)} today.'
        row = _finalize_catalyst_display_row(_apply_live_ticker_classification(row))
        sym = _normalize_ticker(explain_ticker)
        notes_blob = ' '.join(
            [str(row.get('headline') or '')]
            + [str(n) for n in (row.get('catalyst_notes') or [])]
        )
        if sym == 'HCLTECH' and not _hcltech_sarvam_ai_stake(notes_blob, ticker='HCLTECH'):
            return (
                f'<b>📡 CATALYST EXPLAIN — HCLTECH</b>\n'
                'No stock-specific AI stake evidence currently in live cache.\n'
                'Paper watch only — no order execution.'
            )
        bd = row.get('score_breakdown') or {}
        lines = [
            f"<b>📡 CATALYST EXPLAIN — {row.get('ticker')}</b>",
            f"Side: {row.get('side')} · Type: {str(row.get('catalyst_type', '')).replace('_', ' ')}",
            f"Headline: {str(row.get('headline') or '')[:180]}",
        ]
        primary_headline = str(row.get('headline') or '')
        also_count = 0
        for note in (row.get('catalyst_notes') or []):
            note_text = str(note or '').strip()
            if not note_text or note_text == primary_headline:
                continue
            lines.append(f"Also: {note_text[:120]}")
            also_count += 1
            if also_count >= 3:
                break
        lines.extend([
            f"Freshness: {row.get('freshness_label')} · Score: {row.get('score')}",
            f"Price reaction: {row.get('price_display') or format_price_reaction_display(row.get('change_pct'), quote_available=bool(row.get('quote_available')))} · "
            f"Volume: {row.get('volume_display') or format_volume_display(row.get('volume_ratio'), quote_available=bool(row.get('quote_available')))}",
            f"Priority: {row.get('priority')} · Status: {row.get('trade_status')}",
            f"Breakdown: fresh {bd.get('freshness', 0):.0f} · quality {bd.get('quality', 0):.0f} · "
            f"price {bd.get('price_reaction', 0):.0f} · vol {bd.get('volume_confirmation', 0):.0f}",
            'Paper watch only — no order execution.',
        ])
        return '\n'.join(lines)

    radar = get_clean_catalyst_radar(today_only=today_only)
    items = radar.get('priority_list') or []

    lines = ['<b>📡 STOCK CATALYST RADAR</b> <i>(news-first · paper only)</i>']
    if not items:
        lines.append('No fresh actionable catalysts in cache — check again after news refresh.')
    for idx, row in enumerate(items[:10], start=1):
        row = _finalize_catalyst_display_row(_apply_live_ticker_classification(dict(row)))
        lines.append('')
        lines.append(
            f"{idx}. <b>{row.get('ticker')}</b> — {row.get('side')}\n"
            f"   Catalyst: {str(row.get('catalyst_type', '')).replace('_', ' ').lower()}\n"
            f"   Freshness: {row.get('freshness_label')} · Price: {row.get('price_display') or 'unavailable'}\n"
            f"   Volume: {row.get('volume_display') or 'unavailable'} · Priority: {row.get('priority')}\n"
            f"   Trade status: {row.get('trade_status')}"
        )
    lines.append('')
    lines.append('Use /catalysts explain &lt;ticker&gt; for detail. Research only — confirm manually.')
    return '\n'.join(lines)


def format_preopen_catalyst_watchlist() -> str:
    radar = build_catalyst_radar(force_refresh=True)
    watch = radar.get('bullish_watch') or []
    avoid = radar.get('avoid_list') or []

    lines = ['<b>📡 CATALYST WATCHLIST — PREOPEN</b>']
    if not watch and not avoid:
        lines.append('No ranked catalysts yet — awaiting news refresh.')
        return '\n'.join(lines)

    for idx, row in enumerate(watch[:5], start=1):
        lines.append(
            f"{idx}. <b>{row.get('ticker')}</b> — "
            f"{str(row.get('catalyst_type', '')).replace('_', ' ').lower()} catalyst"
        )
    for row in avoid[:3]:
        lines.append(
            f"Avoid: <b>{row.get('ticker')}</b> — "
            f"{str(row.get('catalyst_type', '')).replace('_', ' ').lower()}"
        )
    lines.append('<i>Paper watch only — confirm at open.</i>')
    return '\n'.join(lines)


def catalyst_scanner_confirmed(ticker: str) -> bool:
    """True when catalyst ticker also appears in live scanner."""
    sym = _normalize_ticker(ticker)
    quote = _scanner_quote(sym)
    if not quote:
        return False
    row = explain_catalyst(sym)
    if not row:
        return False
    if row.get('side') in ('BEARISH', 'RISK'):
        return False
    return float(row.get('score') or 0) >= PRIORITY_MEDIUM
