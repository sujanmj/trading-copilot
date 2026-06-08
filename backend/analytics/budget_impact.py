"""
AstraEdge Budget Impact Intelligence — Stage 48A.

Uses Theme Wishlist engine to map budget/govt/policy/news to themes and stock impact.
Research-only — watch/confirm stances, never buy now or guaranteed.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path
from backend.storage.json_io import atomic_write_json

IST = ZoneInfo('Asia/Kolkata')
STAGE = '48F'
ENGINE_NAME = 'Budget Impact Intelligence'

CACHE_FILE = get_data_path('budget_impact_cache.json')
EVENT_LOG_FILE = get_data_path('budget_event_log.jsonl')

FORBIDDEN_WORDS = ('buy now', 'guaranteed', 'sure shot', 'sell now', 'invest now')
ALLOWED_STANCES = (
    'Investment Watch',
    'Short-term Watch',
    'Avoid / Risk',
    'Wait for Confirmation',
    'Research Only',
)

POLITICAL_PARTY_TERMS = (
    'congress', 'bjp', 'aap', 'dmk', 'tmc', 'sp', 'bsp', 'nda', 'upi alliance',
    'may lose', 'may come', 'may win', 'election result', 'regime change',
)

NEGATIVE_POLICY_TERMS = (
    'rate hike', 'repo hike', 'tightening', 'margin squeeze', 'import duty',
    'tax hike', 'regulatory action', 'crude spike', 'oil shock', 'war', 'sanctions',
    'fuel price hike', 'margin risk', 'demand destruction',
)

POSITIVE_CRUDE_TERMS = ('crude spike', 'oil shock', 'brent surge', 'oil price rise')
NEGATIVE_CRUDE_THEMES = ('aviation', 'paints', 'chemicals', 'omc', 'tyres', 'logistics')

THEME_EVENT_HINTS: dict[str, tuple[str, ...]] = {
    'highway': ('roads_highways', 'infrastructure', 'cement_steel_paint', 'logistics_warehousing', 'housing_real_estate'),
    'road project': ('roads_highways', 'infrastructure', 'cement_steel_paint'),
    'expressway': ('roads_highways', 'infrastructure', 'cement_steel_paint'),
    'bengaluru': ('roads_highways', 'infrastructure', 'it_digital_india'),
    'rate hike': ('rbi_rates', 'psu_banks', 'private_banks', 'nbfc', 'housing_real_estate', 'auto_ev_batteries'),
    'repo rate': ('rbi_rates', 'psu_banks', 'private_banks', 'nbfc', 'housing_real_estate'),
    'crude spike': ('crude_sensitive', 'oil_gas_energy', 'aviation', 'cement_steel_paint', 'chemicals'),
    'oil shock': ('crude_sensitive', 'oil_gas_energy', 'aviation', 'chemicals'),
    'defence budget': ('defence_aerospace', 'semiconductors_electronics'),
    'defense budget': ('defence_aerospace', 'semiconductors_electronics'),
    'defence allocation': ('defence_aerospace',),
    'railway allocation': ('railways_metro', 'cement_steel_paint', 'logistics_warehousing'),
    'rail budget': ('railways_metro', 'cement_steel_paint'),
    'union budget': ('infrastructure', 'defence_aerospace', 'railways_metro', 'housing_real_estate'),
    'project delay': ('cement_steel_paint', 'infrastructure', 'roads_highways'),
    'project delayed': ('cement_steel_paint', 'infrastructure', 'roads_highways'),
}

POSITIVE_CATALYST_TERMS = (
    'allocation', 'order win', 'order wins', 'tender awarded', 'tender award',
    'bags order', 'wins order', 'won order', 'contract awarded', 'capex',
    'approval', 'approved', 'project launch', 'subsidy', 'pli ', 'demand boost',
    'highway project', 'road project', 'expressway', 'infra project', 'announces',
)

NEGATIVE_CATALYST_TERMS = (
    'delay', 'delayed', 'postpone', 'postponed', 'probe', 'warning', 'penalty',
    'rate hike', 'repo hike', 'tax hike', 'ban', 'margin pressure', 'cost spike',
    'fraud', 'downgrade', 'project delay', 'project delayed', 'shelved',
    'cancelled', 'canceled', 'under investigation', 'margin squeeze',
)

HIGHWAY_DIRECT_TICKERS = ('HGINFRA', 'IRB', 'PNCINFRA', 'KNR', 'GRINFRA', 'LT')
CEMENT_STEEL_PAINT_INDIRECT = (
    'ULTRACEMCO', 'ACC', 'DALBHARAT', 'SHREECEM', 'AMBUJACEM', 'TATASTEEL',
    'JSWSTEEL', 'ASIANPAINT', 'BERGER', 'SAIL',
)
STEEL_SECTOR_TICKERS = ('TATASTEEL', 'JSWSTEEL', 'SAIL', 'HINDALCO', 'NMDC')

STOCK_SECTION_LABELS = {
    'positive_investment_watch': 'Positive / Investment Watch',
    'indirect_watch': 'Indirect Watch',
    'avoid_risk': 'Avoid / Risk',
    'wait_confirmation': 'Wait for Confirmation',
    'research_only': 'Research Only',
}


def _log(msg: str) -> None:
    print(f'[BUDGET_IMPACT] {msg}', flush=True)


def _now_iso() -> str:
    return datetime.now(IST).replace(microsecond=0).isoformat()


def _sanitize_text(text: str) -> str:
    out = str(text or '')
    for word in FORBIDDEN_WORDS:
        out = re.sub(re.escape(word), 'watch', out, flags=re.IGNORECASE)
    return out


def _append_event_log(entry: dict[str, Any]) -> None:
    EVENT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(EVENT_LOG_FILE, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, default=str) + '\n')


def _load_cache() -> dict[str, Any]:
    if CACHE_FILE.is_file():
        try:
            data = json.loads(CACHE_FILE.read_text(encoding='utf-8'))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _save_cache(payload: dict[str, Any]) -> None:
    payload['stage'] = STAGE
    payload['engine'] = ENGINE_NAME
    atomic_write_json(CACHE_FILE, payload)


def _file_age_hours(path) -> Optional[float]:
    try:
        if not path.is_file():
            return None
        mtime = datetime.fromtimestamp(path.stat().st_mtime, IST)
        return (datetime.now(IST) - mtime).total_seconds() / 3600.0
    except OSError:
        return None


def _file_timestamp_iso(path) -> Optional[str]:
    try:
        if not path.is_file():
            return None
        mtime = datetime.fromtimestamp(path.stat().st_mtime, IST)
        return mtime.replace(microsecond=0).isoformat()
    except OSError:
        return None


def _age_label(age_h: Optional[float]) -> str:
    if age_h is None:
        return 'Unavailable'
    if age_h < 1:
        return f'{int(age_h * 60)}m ago'
    return f'{age_h:.1f}h ago'


def _source_freshness_status(age_h: Optional[float]) -> str:
    if age_h is None:
        return 'unavailable'
    if age_h <= 6:
        return 'fresh'
    if age_h <= 24:
        return 'partial'
    return 'stale'


def _freshness_status(*ages: Optional[float]) -> str:
    valid = [a for a in ages if a is not None]
    if not valid:
        return 'cache_missing'
    if all(a <= 6 for a in valid):
        return 'fresh'
    if any(a <= 24 for a in valid):
        return 'partial'
    return 'stale'


def _build_source_freshness_row(*, label: str, path, timestamp: Optional[str] = None) -> dict[str, Any]:
    age_h = _file_age_hours(path) if path else None
    ts = timestamp or _file_timestamp_iso(path) if path else None
    return {
        'label': label,
        'timestamp': ts,
        'age_hours': age_h,
        'age_label': _age_label(age_h),
        'status': _source_freshness_status(age_h),
    }


def dedupe_catalyst_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from backend.analytics.theme_baskets import _normalize_title

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        norm = _normalize_title(str(row.get('headline') or ''))
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(row)
    return out


def detect_catalyst_direction(text: str) -> str:
    lower = _sanitize_text(str(text or '')).lower()
    pos = [t for t in POSITIVE_CATALYST_TERMS if t in lower]
    neg = [t for t in NEGATIVE_CATALYST_TERMS if t in lower]
    if pos and neg:
        return 'Mixed'
    if neg:
        return 'Negative'
    if pos:
        return 'Positive'
    return 'Mixed'


def extract_named_companies_strict(text: str) -> list[str]:
    from backend.analytics.theme_baskets import COMPANY_ALIASES, _normalize_text, _ticker_in_text

    lower = _normalize_text(text)
    found: list[str] = []
    for alias, ticker in sorted(COMPANY_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in lower and ticker not in found:
            found.append(ticker)
    for ticker in set(COMPANY_ALIASES.values()):
        if _ticker_in_text(ticker, text) and ticker not in found:
            found.append(ticker)
    return found


def _is_highway_catalyst(text: str) -> bool:
    lower = str(text or '').lower()
    return any(w in lower for w in ('highway', 'road project', 'expressway', 'nhai', 'bengaluru'))


def _is_steel_catalyst(text: str) -> bool:
    lower = str(text or '').lower()
    return any(w in lower for w in ('steel', 'tata steel', 'jsw steel', 'sail', 'iron ore'))


def _assign_stock_section(*, stance: str, side: str, direction: str, stale: bool, generic: bool = False) -> str:
    if stale or generic:
        return 'research_only'
    if 'Avoid' in stance or side in ('Risk', 'Avoid'):
        return 'avoid_risk'
    if stance == 'Investment Watch' or (side == 'Beneficiary' and direction == 'Positive'):
        return 'positive_investment_watch'
    if side == 'Indirect' and direction == 'Positive':
        return 'indirect_watch'
    if stance == 'Wait for Confirmation' or direction in ('Mixed', 'Negative'):
        return 'wait_confirmation'
    if stance == 'Research Only':
        return 'research_only'
    if side == 'Indirect':
        return 'indirect_watch'
    return 'wait_confirmation'


def rank_stocks_for_catalyst(
    headline: str,
    theme_id: str,
    *,
    freshness: Optional[dict[str, Any]] = None,
    limit: int = 12,
) -> dict[str, Any]:
    from backend.analytics.theme_baskets import get_basket_by_id, rank_theme_stocks, resolve_theme_id

    resolved = resolve_theme_id(theme_id) or theme_id
    freshness = freshness or compute_freshness_panel()
    stale = freshness.get('status') in ('stale', 'cache_missing')
    direction = detect_catalyst_direction(headline)
    named = extract_named_companies_strict(headline)
    lower = str(headline or '').lower()

    sections: dict[str, list[dict[str, Any]]] = {
        'positive_investment_watch': [],
        'indirect_watch': [],
        'avoid_risk': [],
        'wait_confirmation': [],
        'research_only': [],
    }
    stocks: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_stock(
        ticker: str,
        *,
        side: str,
        stance: str,
        reason: str,
        score: int,
        named_hit: bool = False,
        generic: bool = False,
    ) -> None:
        t = str(ticker or '').upper()
        if not t or t in seen:
            return
        seen.add(t)
        section_key = _assign_stock_section(
            stance=stance,
            side=side,
            direction=direction,
            stale=stale,
            generic=generic,
        )
        entry = {
            'ticker': t,
            'theme_id': resolved,
            'impact_side': side,
            'score': score,
            'reason': _sanitize_text(reason),
            'freshness': freshness.get('status', 'unknown'),
            'confirmation_needed': 'Confirm with price + volume + sector breadth',
            'stance': stance,
            'section': section_key,
            'section_label': STOCK_SECTION_LABELS.get(section_key, section_key),
            'catalyst_direction': direction,
            'named_in_headline': named_hit or t in named,
        }
        stocks.append(entry)
        sections[section_key].append(entry)

    if direction == 'Negative':
        for t in named:
            add_stock(
                t,
                side='Risk',
                stance='Avoid / Risk',
                reason=f'Named company in negative catalyst: {headline[:100]}',
                score=25,
                named_hit=True,
            )
        if _is_steel_catalyst(headline):
            for t in STEEL_SECTOR_TICKERS:
                if t in named:
                    continue
                add_stock(
                    t,
                    side='Risk',
                    stance='Wait for Confirmation',
                    reason='Steel sector — watch carefully after negative catalyst',
                    score=35,
                )
        for t in named:
            if t in STEEL_SECTOR_TICKERS and t not in [s['ticker'] for s in sections['avoid_risk']]:
                add_stock(
                    t,
                    side='Risk',
                    stance='Avoid / Risk',
                    reason='Named steel name in negative headline',
                    score=20,
                    named_hit=True,
                )
    elif direction == 'Positive' and _is_highway_catalyst(headline):
        for t in HIGHWAY_DIRECT_TICKERS:
            add_stock(
                t,
                side='Beneficiary',
                stance='Investment Watch',
                reason='Direct roads/highways beneficiary from project catalyst',
                score=78,
            )
        for t in CEMENT_STEEL_PAINT_INDIRECT:
            add_stock(
                t,
                side='Indirect',
                stance='Short-term Watch',
                reason='Cement/steel/paint indirect beneficiary',
                score=62,
            )
    elif direction == 'Positive':
        basket = get_basket_by_id(resolved) or {}
        for row in rank_theme_stocks(resolved, limit=limit):
            bucket = str(row.get('bucket') or '')
            t = str(row.get('ticker') or '').upper()
            if t in named:
                add_stock(
                    t,
                    side='Beneficiary',
                    stance='Investment Watch',
                    reason=f'Named in catalyst + {row.get("label") or "theme match"}',
                    score=min(95, int(row.get('score') or 0) + 10),
                    named_hit=True,
                )
                continue
            side = 'Beneficiary' if bucket == 'direct' else 'Indirect'
            stance = _stance_for_score(
                int(row.get('score') or 0),
                stale=stale,
                has_confirmation=any(w in lower for w in ('order', 'tender', 'project', 'contract')),
            )
            add_stock(
                t,
                side=side,
                stance=stance,
                reason=row.get('label') or row.get('confirm') or 'Theme beneficiary',
                score=int(row.get('score') or 0),
            )
        if not stocks and basket:
            add_stock(
                str((basket.get('stocks') or {}).get('direct', [''])[0]),
                side='Beneficiary',
                stance='Wait for Confirmation',
                reason='Broad theme match — confirm before acting',
                score=45,
                generic=True,
            )
    else:
        for t in named:
            add_stock(
                t,
                side='Risk' if direction == 'Negative' else 'Beneficiary',
                stance='Wait for Confirmation',
                reason='Named company — mixed/unclear catalyst direction',
                score=40,
                named_hit=True,
            )
        if not stocks:
            sections['research_only'].append({
                'ticker': '',
                'theme_id': resolved,
                'impact_side': 'Research',
                'score': 20,
                'reason': 'Broad theme without price/volume confirmation',
                'freshness': freshness.get('status', 'unknown'),
                'confirmation_needed': 'Confirm with price + volume + sector breadth',
                'stance': 'Research Only',
                'section': 'research_only',
                'section_label': STOCK_SECTION_LABELS['research_only'],
                'catalyst_direction': direction,
                'named_in_headline': False,
            })

    for row in stocks:
        if row.get('reason'):
            row['reason'] = _sanitize_text(str(row['reason']))

    return {
        'stocks': stocks[:limit],
        'sections': sections,
        'section_labels': STOCK_SECTION_LABELS,
        'catalyst_direction': direction,
        'named_companies': named,
        'headline': _sanitize_text(headline[:240]),
    }


def build_stock_ranking_sections(stocks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    sections: dict[str, list[dict[str, Any]]] = {
        'positive_investment_watch': [],
        'indirect_watch': [],
        'avoid_risk': [],
        'wait_confirmation': [],
        'research_only': [],
    }
    for row in stocks:
        key = str(row.get('section') or _assign_stock_section(
            stance=str(row.get('stance') or ''),
            side=str(row.get('impact_side') or ''),
            direction=str(row.get('catalyst_direction') or 'Mixed'),
            stale=str(row.get('freshness') or '') in ('stale', 'cache_missing'),
        ))
        if key not in sections:
            key = 'research_only'
        sections[key].append(row)
    return sections


def compute_freshness_panel() -> dict[str, Any]:
    from backend.analytics.theme_baskets import BASKETS_FILE, load_theme_baskets

    data = load_theme_baskets()
    news_path = get_data_path('news_feed.json')
    govt_path = get_data_path('govt_intelligence.json')
    scanner_path = get_data_path('scanner_data.json')

    news_age_h = _file_age_hours(news_path)
    govt_age_h = _file_age_hours(govt_path)
    combined_news_age = min(filter(lambda x: x is not None, [news_age_h, govt_age_h]), default=news_age_h)

    cache_refreshed = data.get('cache_refreshed_at') or data.get('generated_at')
    theme_cache_age_h = None
    theme_ts = cache_refreshed
    if cache_refreshed:
        try:
            ts = datetime.fromisoformat(str(cache_refreshed))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=IST)
            theme_cache_age_h = (datetime.now(IST) - ts.astimezone(IST)).total_seconds() / 3600.0
        except (TypeError, ValueError):
            theme_cache_age_h = _file_age_hours(BASKETS_FILE)
            theme_ts = _file_timestamp_iso(BASKETS_FILE)

    scanner_age_h = _file_age_hours(scanner_path)
    budget_cache_age_h = _file_age_hours(CACHE_FILE)
    budget_ts = _file_timestamp_iso(CACHE_FILE)
    cached = _load_cache()
    if cached.get('generated_at') or cached.get('refreshed_at'):
        budget_ts = cached.get('refreshed_at') or cached.get('generated_at')

    news_row = _build_source_freshness_row(label='News', path=news_path)
    if govt_age_h is not None and (news_age_h is None or govt_age_h < news_age_h):
        news_row = _build_source_freshness_row(label='News', path=govt_path)
    if combined_news_age is not None:
        news_row['age_hours'] = combined_news_age
        news_row['age_label'] = _age_label(combined_news_age)
        news_row['status'] = _source_freshness_status(combined_news_age)

    theme_row = {
        'label': 'Theme cache',
        'timestamp': theme_ts,
        'age_hours': theme_cache_age_h,
        'age_label': _age_label(theme_cache_age_h),
        'status': _source_freshness_status(theme_cache_age_h),
    }
    scanner_row = _build_source_freshness_row(label='Scanner', path=scanner_path)
    budget_row = {
        'label': 'Budget cache',
        'timestamp': budget_ts,
        'age_hours': budget_cache_age_h,
        'age_label': _age_label(budget_cache_age_h),
        'status': _source_freshness_status(budget_cache_age_h),
    }

    status = _freshness_status(combined_news_age, theme_cache_age_h, scanner_age_h, budget_cache_age_h)

    return {
        'status': status,
        'news': news_row,
        'theme_cache': theme_row,
        'scanner': scanner_row,
        'budget_cache': budget_row,
        'latest_news_age': news_row['age_label'],
        'latest_theme_cache_age': theme_row['age_label'],
        'latest_scanner_age': scanner_row['age_label'],
        'latest_budget_cache_age': budget_row['age_label'],
        'news_age_hours': combined_news_age,
        'theme_cache_age_hours': theme_cache_age_h,
        'scanner_age_hours': scanner_age_h,
        'budget_cache_age_hours': budget_cache_age_h,
        'cache_refreshed_at': cache_refreshed,
    }


def _is_political_text(text: str) -> bool:
    lower = str(text or '').lower()
    hits = sum(1 for t in POLITICAL_PARTY_TERMS if t in lower)
    return hits >= 2 or ('election' in lower and any(p in lower for p in ('lose', 'win', 'come', 'govt')))


def _political_neutral_analysis(text: str) -> dict[str, Any]:
    theme_ids = [
        'infrastructure', 'roads_highways', 'power_grid_transmission',
        'housing_real_estate', 'psu_banks', 'water_jal_jeevan',
    ]
    from backend.analytics.theme_baskets import get_basket_by_id

    themes = []
    for tid in theme_ids:
        basket = get_basket_by_id(tid)
        if basket:
            themes.append({
                'theme_id': tid,
                'display_name': basket.get('display_name') or tid,
                'category': basket.get('category') or '',
            })
    return {
        'ok': True,
        'mode': 'policy_continuity',
        'headline': text[:240],
        'summary': (
            'Policy continuity / state capex uncertainty — neutral framing only. '
            'Watch tender delay risk and state-contract names for volatility; avoid blind entry until policy clarity.'
        ),
        'detected_themes': themes,
        'positive': [],
        'indirect': [],
        'risk': [],
        'stance': 'Wait for Confirmation',
        'confirmation': 'Confirm tender/order continuity before acting.',
        'political_neutral': True,
    }


def _budget_impact_score(headline: str, theme_id: str, *, item: Optional[dict] = None) -> dict[str, Any]:
    from backend.analytics.theme_baskets import score_theme_catalyst

    scored = score_theme_catalyst(headline, theme_id, item=item)
    if not scored:
        return {
            'budget_impact_score': 0,
            'impact_10': 1,
            'components': {},
            'relevant': False,
        }

    comp = scored.get('components') or {}
    theme_match = min(10.0, float(comp.get('sector_specificity_score') or 0))
    govt_authority = float(comp.get('govt_authority_score') or 0)
    budget_amount = float(comp.get('budget_amount_score') or 0)
    project_specificity = float(comp.get('order_tender_clarity_score') or 0)
    named_company = float(comp.get('named_company_score') or 0)
    direct_sector = min(10.0, theme_match + (2.0 if named_company >= 8 else 0))
    location = float(comp.get('location_relevance_score') or 0)
    market_conf = float(comp.get('market_confirmation_score') or 0)
    stale_penalty = 0.0
    generic_penalty = 4.0 if scored.get('broad_policy') else 0.0
    duplicate_penalty = float(comp.get('duplicate_penalty') or 0)
    priced_in = float(comp.get('already_priced_in_penalty') or 0)

    raw = (
        theme_match + govt_authority + budget_amount + project_specificity
        + named_company + direct_sector + location + market_conf
        - stale_penalty - generic_penalty - duplicate_penalty - priced_in
    )
    budget_score = max(0, min(100, int(round(raw * 2.0))))
    return {
        'budget_impact_score': budget_score,
        'impact_10': scored.get('impact_10', 1),
        'catalyst_score': scored.get('catalyst_score', 0),
        'why': scored.get('why', ''),
        'action': scored.get('action', 'watch only'),
        'named_companies': scored.get('named_companies') or [],
        'components': {
            'theme_match_score': theme_match,
            'govt_authority_score': govt_authority,
            'budget_amount_score': budget_amount,
            'project_specificity_score': project_specificity,
            'named_company_score': named_company,
            'direct_sector_score': direct_sector,
            'location_relevance_score': location,
            'market_confirmation_score': market_conf,
            'stale_penalty': stale_penalty,
            'generic_policy_penalty': generic_penalty,
            'duplicate_penalty': duplicate_penalty,
            'already_priced_in_penalty': priced_in,
        },
        'relevant': True,
        'headline': scored.get('headline') or headline[:240],
    }


def _stance_for_score(score: int, *, stale: bool = False, negative: bool = False, has_confirmation: bool = False) -> str:
    if stale:
        return 'Research Only'
    if negative:
        return 'Avoid / Risk'
    if score >= 75 and has_confirmation:
        return 'Investment Watch'
    if score >= 60:
        return 'Short-term Watch' if has_confirmation else 'Wait for Confirmation'
    if score >= 45:
        return 'Wait for Confirmation'
    return 'Research Only'


def _detect_negative_impact(text: str, theme_id: str) -> bool:
    lower = str(text or '').lower()
    if theme_id in ('rbi_rates',) and any(t in lower for t in ('rate hike', 'repo hike', 'tightening')):
        return theme_id in ('nbfc', 'housing_real_estate', 'auto_ev_batteries')
    if any(t in lower for t in POSITIVE_CRUDE_TERMS):
        if theme_id in ('aviation', 'cement_steel_paint', 'chemicals', 'crude_sensitive'):
            return theme_id in ('aviation', 'chemicals')
    if any(t in lower for t in NEGATIVE_POLICY_TERMS):
        basket = None
        try:
            from backend.analytics.theme_baskets import get_basket_by_id
            basket = get_basket_by_id(theme_id) or {}
        except Exception:
            basket = {}
        risk_sectors = [str(s).lower() for s in (basket.get('risk_sectors') or [])]
        if risk_sectors and any(t in lower for t in ('tax', 'regulatory', 'rate', 'margin', 'import')):
            return True
    return False


def analyze_news_text(text: str, *, persist: bool = False) -> dict[str, Any]:
    """Analyze pasted budget/govt news — simulator + API."""
    headline = str(text or '').strip()
    if not headline:
        return {'ok': False, 'error': 'text required'}

    if _is_political_text(headline):
        result = _political_neutral_analysis(headline)
        result['catalyst_direction'] = 'Mixed'
        result['suggested_stance'] = 'Wait for Confirmation'
        if persist:
            _append_event_log({'stage': STAGE, 'mode': 'political_neutral', 'text': headline[:240], 'at': _now_iso()})
        return result

    from backend.analytics.theme_baskets import (
        get_basket_by_id,
        match_headline_to_themes,
        rank_theme_stocks,
    )

    lower = headline.lower()
    hint_ids: list[str] = []
    for hint, ids in THEME_EVENT_HINTS.items():
        if hint in lower:
            for tid in ids:
                if tid not in hint_ids:
                    hint_ids.append(tid)

    matches = match_headline_to_themes(headline)
    for row in matches:
        tid = str(row.get('theme_id') or '')
        if tid and tid not in hint_ids:
            hint_ids.append(tid)

    freshness = compute_freshness_panel()
    stale = freshness.get('status') in ('stale', 'cache_missing')
    direction = detect_catalyst_direction(headline)
    named = extract_named_companies_strict(headline)

    themes_out = []
    for tid in hint_ids[:8]:
        basket = get_basket_by_id(tid)
        if not basket:
            continue
        scored = _budget_impact_score(headline, tid)
        if not scored.get('relevant') and tid not in hint_ids[:3]:
            continue
        themes_out.append({
            'theme_id': tid,
            'display_name': basket.get('display_name') or tid,
            'budget_impact_score': scored.get('budget_impact_score', 0),
            'impact_10': scored.get('impact_10', 1),
            'why': scored.get('why', ''),
        })

    themes_out.sort(key=lambda r: r.get('budget_impact_score', 0), reverse=True)
    primary_theme = themes_out[0]['theme_id'] if themes_out else (hint_ids[0] if hint_ids else 'infrastructure')

    ranked = rank_stocks_for_catalyst(headline, primary_theme, freshness=freshness, limit=12)
    sections = ranked.get('sections') or {}
    positive = list(sections.get('positive_investment_watch') or [])
    indirect = list(sections.get('indirect_watch') or [])
    risk = list(sections.get('avoid_risk') or [])
    wait_rows = list(sections.get('wait_confirmation') or [])
    research_rows = list(sections.get('research_only') or [])

    top_score = themes_out[0].get('budget_impact_score', 0) if themes_out else 0
    has_conf = any(t in lower for t in ('order', 'tender', 'project', 'contract', 'allocation'))
    stance = _stance_for_score(
        top_score,
        stale=stale,
        negative=(direction == 'Negative'),
        has_confirmation=has_conf,
    )
    if direction == 'Negative' and named:
        stance = 'Avoid / Risk'
    elif direction == 'Mixed' and not positive:
        stance = 'Wait for Confirmation'

    result = {
        'ok': True,
        'mode': 'news_analysis',
        'headline': _sanitize_text(headline[:240]),
        'catalyst_direction': direction,
        'detected_direction': direction,
        'detected_themes': themes_out,
        'named_companies': named,
        'impact_map': build_impact_map(primary_theme),
        'positive': positive[:8],
        'indirect': indirect[:8],
        'risk': risk[:8],
        'wait': wait_rows[:8],
        'research_only': research_rows[:8],
        'stock_sections': sections,
        'section_labels': STOCK_SECTION_LABELS,
        'direct_beneficiaries': positive[:8],
        'indirect_beneficiaries': indirect[:8],
        'risks_possible_losers': risk[:8],
        'suggested_stance': stance,
        'stance': stance,
        'confirmation': 'Confirm with price + volume + sector breadth.',
        'freshness': freshness,
        'political_neutral': False,
    }
    if persist:
        _append_event_log({
            'stage': STAGE,
            'mode': 'analyze_news',
            'text': _sanitize_text(headline[:240]),
            'themes': [t.get('theme_id') for t in themes_out],
            'at': _now_iso(),
        })
    return result


def build_impact_map(theme_id: str) -> dict[str, Any]:
    from backend.analytics.theme_baskets import get_basket_by_id

    basket = get_basket_by_id(theme_id) or {}
    stocks = basket.get('stocks') or {}
    return {
        'theme_id': theme_id,
        'display_name': basket.get('display_name') or theme_id,
        'direct_beneficiaries': list(basket.get('direct_beneficiary_sectors') or [])[:8],
        'indirect_beneficiaries': list(basket.get('indirect_beneficiary_sectors') or [])[:8],
        'raw_material': list(basket.get('raw_material_beneficiaries') or [])[:6],
        'risks': list(basket.get('risk_sectors') or [])[:6],
        'risk_stocks': list(stocks.get('avoid_or_risk') or [])[:6],
    }


def get_budget_overview(*, cache_only: bool = False, lite: bool = False) -> dict[str, Any]:
    if cache_only and lite:
        cached = _load_cache()
        if cached and cached.get('ok'):
            return {
                'ok': True,
                'lite': True,
                'from_cache': True,
                'stage': STAGE,
                'engine': ENGINE_NAME,
                'generated_at': cached.get('generated_at') or cached.get('refreshed_at'),
                'freshness': cached.get('freshness') or {
                    'status': 'cached',
                    'latest_news_age': 'Unavailable',
                    'latest_theme_cache_age': 'Unavailable',
                    'latest_scanner_age': 'Unavailable',
                    'latest_budget_cache_age': _age_label(_file_age_hours(CACHE_FILE)),
                },
                'top_themes': (cached.get('top_themes') or [])[:8],
                'top_catalysts': (cached.get('top_catalysts') or [])[:5],
                'beneficiary_map': cached.get('beneficiary_map') or {},
                'risk_map': cached.get('risk_map') or {},
                'stock_rankings': (cached.get('stock_rankings') or [])[:10],
                'source_counts': cached.get('source_counts') or {},
                'disclaimer': cached.get('disclaimer') or 'Research only — watch/confirm. No blind entry.',
            }
        return {
            'ok': True,
            'lite': True,
            'cache_missing': True,
            'stale': True,
            'stage': STAGE,
            'engine': ENGINE_NAME,
            'generated_at': _now_iso(),
            'message': 'Budget cache unavailable. Tap Refresh Budget Intel.',
            'freshness': {'status': 'cache_missing', 'lite': True, 'stale': True},
            'top_themes': [],
            'top_catalysts': [],
            'beneficiary_map': {},
            'risk_map': {},
            'stock_rankings': [],
            'source_counts': {'themes': 0, 'budget_themes': 0, 'catalysts': 0},
            'disclaimer': 'Research only — watch/confirm. No blind entry.',
        }

    if cache_only:
        cached = _load_cache()
        if cached and cached.get('ok'):
            cached = dict(cached)
            cached['from_cache'] = True
            cached.setdefault('stage', STAGE)
            cached.setdefault('engine', ENGINE_NAME)
            if 'freshness' not in cached:
                cached['freshness'] = compute_freshness_panel()
            return cached
        return {
            'ok': True,
            'cache_missing': True,
            'stage': STAGE,
            'engine': ENGINE_NAME,
            'generated_at': _now_iso(),
            'message': 'Budget cache unavailable. Tap Refresh Budget Intel.',
            'freshness': compute_freshness_panel(),
            'top_themes': [],
            'top_catalysts': [],
            'beneficiary_map': {},
            'risk_map': {},
            'stock_rankings': [],
            'source_counts': {'themes': 0, 'budget_themes': 0, 'catalysts': 0},
            'disclaimer': 'Research only — watch/confirm. No blind entry.',
        }

    from backend.analytics.theme_baskets import (
        BUDGET_THEME_IDS,
        get_basket_by_id,
        get_theme_catalysts,
        list_all_baskets,
    )

    freshness = compute_freshness_panel()
    top_themes = []
    top_catalysts = []
    beneficiary_map: dict[str, list[str]] = {}
    risk_map: dict[str, list[str]] = {}

    for tid in BUDGET_THEME_IDS:
        basket = get_basket_by_id(tid)
        if not basket:
            continue
        catalysts = get_theme_catalysts(tid, limit=1, for_top_display=True)
        top_score = 40
        if catalysts:
            top_score = int(catalysts[0].get('catalyst_score') or 40)
        top_themes.append({
            'theme_id': tid,
            'display_name': basket.get('display_name') or tid,
            'category': basket.get('category') or '',
            'budget_impact_score': top_score,
            'latest_catalyst': catalysts[0].get('headline') if catalysts else None,
        })
        stocks = basket.get('stocks') or {}
        beneficiary_map[tid] = list(stocks.get('direct') or [])[:5]
        risk_map[tid] = list(stocks.get('avoid_or_risk') or [])[:3]

    top_themes.sort(key=lambda r: r.get('budget_impact_score', 0), reverse=True)

    for tid in BUDGET_THEME_IDS[:6]:
        for cat in get_theme_catalysts(tid, limit=2, for_top_display=True):
            top_catalysts.append({
                'theme_id': tid,
                'display_name': (get_basket_by_id(tid) or {}).get('display_name') or tid,
                **{k: cat.get(k) for k in ('headline', 'impact_10', 'catalyst_score', 'why', 'action')},
            })
    top_catalysts.sort(key=lambda r: r.get('catalyst_score', 0), reverse=True)
    top_catalysts = dedupe_catalyst_rows(top_catalysts)

    stock_rankings: list[dict[str, Any]] = []
    stock_ranking_sections: dict[str, list[dict[str, Any]]] = {
        'positive_investment_watch': [],
        'indirect_watch': [],
        'avoid_risk': [],
        'wait_confirmation': [],
        'research_only': [],
    }
    if top_catalysts:
        lead = top_catalysts[0]
        ranked = rank_stocks_for_catalyst(
            str(lead.get('headline') or ''),
            str(lead.get('theme_id') or top_themes[0]['theme_id'] if top_themes else 'infrastructure'),
            freshness=freshness,
            limit=15,
        )
        stock_rankings = ranked.get('stocks') or []
        stock_ranking_sections = ranked.get('sections') or stock_ranking_sections
    else:
        for row in top_themes[:3]:
            scan = get_budget_theme_scan(row['theme_id'], limit=5)
            stock_rankings.extend(scan.get('stocks') or [])

    payload = {
        'ok': True,
        'stage': STAGE,
        'engine': ENGINE_NAME,
        'generated_at': _now_iso(),
        'freshness': freshness,
        'top_themes': top_themes[:12],
        'top_catalysts': top_catalysts[:8],
        'beneficiary_map': beneficiary_map,
        'risk_map': risk_map,
        'stock_rankings': stock_rankings[:15],
        'stock_ranking_sections': stock_ranking_sections,
        'section_labels': STOCK_SECTION_LABELS,
        'source_counts': {
            'themes': len(list_all_baskets()),
            'budget_themes': len(top_themes),
            'catalysts': len(top_catalysts),
        },
        'disclaimer': 'Research only — watch/confirm. No blind entry.',
    }
    return payload


def get_budget_themes(*, lite: bool = False) -> dict[str, Any]:
    from backend.analytics.theme_baskets import THEME_CATEGORIES, get_basket_by_id, load_theme_baskets

    if lite:
        load_theme_baskets()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for category, ids in THEME_CATEGORIES.items():
        rows = []
        for tid in ids:
            basket = get_basket_by_id(tid)
            if basket:
                rows.append({
                    'theme_id': tid,
                    'display_name': basket.get('display_name') or tid,
                })
        if rows:
            grouped[category] = rows
    return {
        'ok': True,
        'stage': STAGE,
        'lite': bool(lite),
        'categories': grouped,
        'count': sum(len(v) for v in grouped.values()),
    }


def get_budget_theme_detail(theme_id: str) -> dict[str, Any]:
    from backend.analytics.theme_baskets import get_basket_by_id, resolve_theme_id

    resolved = resolve_theme_id(theme_id)
    basket = get_basket_by_id(theme_id)
    if not basket or not resolved:
        return {'ok': False, 'error': f'theme not found: {theme_id}'}
    impact = build_impact_map(resolved)
    freshness = compute_freshness_panel()
    return {
        'ok': True,
        'theme_id': resolved,
        'basket': basket,
        'impact_map': impact,
        'freshness': freshness,
        'disclaimer': 'Research only — watch/confirm.',
    }


def get_budget_theme_news(theme_id: str, *, limit: int = 12) -> dict[str, Any]:
    from backend.analytics.theme_baskets import get_basket_by_id, get_theme_catalysts, resolve_theme_id

    resolved = resolve_theme_id(theme_id)
    if not get_basket_by_id(theme_id):
        return {'ok': False, 'error': f'theme not found: {theme_id}'}
    catalysts = get_theme_catalysts(theme_id, limit=limit, for_top_display=False)
    enriched = []
    for cat in catalysts:
        headline_text = str(cat.get('headline') or '')
        scored = _budget_impact_score(headline_text, str(resolved or theme_id))
        enriched.append({
            **cat,
            'budget_impact_score': scored.get('budget_impact_score', cat.get('catalyst_score', 0)),
            'catalyst_direction': detect_catalyst_direction(headline_text),
            'named_companies': extract_named_companies_strict(headline_text),
        })
    enriched = dedupe_catalyst_rows(enriched)
    return {
        'ok': True,
        'theme_id': resolved,
        'catalysts': enriched,
        'count': len(enriched),
    }


def get_budget_theme_scan(
    theme_id: str,
    *,
    limit: int = 12,
    catalyst_headline: str | None = None,
) -> dict[str, Any]:
    from backend.analytics.theme_baskets import get_basket_by_id, get_theme_catalysts, resolve_theme_id

    resolved = resolve_theme_id(theme_id)
    if not get_basket_by_id(theme_id):
        return {'ok': False, 'error': f'theme not found: {theme_id}'}
    freshness = compute_freshness_panel()

    headline = str(catalyst_headline or '').strip()
    if not headline:
        catalysts = get_theme_catalysts(theme_id, limit=3, for_top_display=False)
        catalysts = dedupe_catalyst_rows(catalysts)
        if catalysts:
            headline = str(catalysts[0].get('headline') or '')

    if headline:
        ranked = rank_stocks_for_catalyst(headline, theme_id, freshness=freshness, limit=limit)
        return {
            'ok': True,
            'theme_id': resolved,
            'catalyst_headline': headline[:240],
            'catalyst_direction': ranked.get('catalyst_direction'),
            'named_companies': ranked.get('named_companies') or [],
            'stocks': ranked.get('stocks') or [],
            'sections': ranked.get('sections') or {},
            'section_labels': STOCK_SECTION_LABELS,
            'count': len(ranked.get('stocks') or []),
            'freshness': freshness,
        }

    return {
        'ok': True,
        'theme_id': resolved,
        'stocks': [],
        'sections': build_stock_ranking_sections([]),
        'section_labels': STOCK_SECTION_LABELS,
        'count': 0,
        'freshness': freshness,
    }


def refresh_budget_intel(*, persist: bool = True) -> dict[str, Any]:
    from backend.analytics.theme_baskets import refresh_theme_catalyst_cache

    theme_refresh = refresh_theme_catalyst_cache(persist=persist)
    overview = get_budget_overview()
    overview['theme_refresh'] = {
        'themes_matched': theme_refresh.get('themes_matched'),
        'total_matches': theme_refresh.get('total_matches'),
        'refreshed_at': theme_refresh.get('refreshed_at'),
    }
    overview['refreshed_at'] = _now_iso()
    if persist:
        _save_cache(overview)
        _append_event_log({
            'stage': STAGE,
            'mode': 'refresh',
            'themes_matched': theme_refresh.get('themes_matched'),
            'at': _now_iso(),
        })
    _log(f"refreshed budget intel themes={theme_refresh.get('themes_matched', 0)}")
    return overview


def format_budget_overview_telegram() -> str:
    overview = get_budget_overview()
    fresh = overview.get('freshness') or {}
    lines = [
        '<b>🏛️ Budget Impact Intelligence</b>',
        '',
        f"Freshness: <code>{fresh.get('status', 'unknown')}</code>",
        f"News: {fresh.get('latest_news_age', 'Unavailable')} · Theme cache: {fresh.get('latest_theme_cache_age', 'Unavailable')}",
        '',
        '<b>Top budget themes:</b>',
    ]
    for row in (overview.get('top_themes') or [])[:6]:
        lines.append(f"• {row.get('display_name')} · score {row.get('budget_impact_score', '—')}")
    lines.extend([
        '',
        '<i>Research only — watch/confirm. Use /budget theme infra or /budget analyze &lt;text&gt;</i>',
    ])
    return _sanitize_text('\n'.join(lines))


def format_budget_theme_telegram(theme_key: str) -> str:
    from backend.analytics.theme_baskets import format_theme_detail_telegram, resolve_theme_id

    resolved = resolve_theme_id(theme_key)
    if not resolved:
        return f'Unknown theme: <code>{theme_key}</code>. Try /budget or /budget theme infra.'
    header = f'<b>🏛️ Budget — {(get_budget_theme_detail(resolved).get("impact_map") or {}).get("display_name", resolved)}</b>\n\n'
    return _sanitize_text(header + format_theme_detail_telegram(resolved).split('\n', 1)[-1])


def format_budget_analyze_telegram(text: str) -> str:
    result = analyze_news_text(text)
    if not result.get('ok'):
        return f"Analyze failed: {result.get('error', 'unknown')}"
    if result.get('political_neutral'):
        themes = ', '.join(t.get('display_name', '') for t in (result.get('detected_themes') or [])[:5])
        return _sanitize_text(
            f"<b>🏛️ Policy continuity mode</b>\n\n{result.get('summary')}\n\nThemes: {themes}\n\n"
            f"Stance: {result.get('stance')}"
        )
    themes = ', '.join(t.get('display_name', '') for t in (result.get('detected_themes') or [])[:6])
    pos = ', '.join(p.get('ticker', '') for p in (result.get('positive') or [])[:5])
    ind = ', '.join(p.get('ticker', '') for p in (result.get('indirect') or [])[:5])
    lines = [
        '<b>🏛️ Budget analyze</b>',
        '',
        f"Themes: {themes or '—'}",
        f"Positive: {pos or '—'}",
        f"Indirect: {ind or '—'}",
        f"Stance: {result.get('stance', 'Research Only')}",
        '',
        '<i>Watch only — confirm with price + volume.</i>',
    ]
    return _sanitize_text('\n'.join(lines))


def handle_budget_command(args: str) -> str:
    raw = str(args or '').strip()
    if not raw:
        return format_budget_overview_telegram()
    parts = raw.split(maxsplit=1)
    sub = parts[0].lower()
    if sub == 'theme' and len(parts) >= 2:
        return format_budget_theme_telegram(parts[1].strip())
    if sub == 'analyze' and len(parts) >= 2:
        return format_budget_analyze_telegram(parts[1].strip())
    if sub == 'refresh':
        result = refresh_budget_intel(persist=True)
        return _sanitize_text(
            f"<b>🔄 Budget refresh</b>\nThemes matched: {result.get('source_counts', {}).get('budget_themes', 0)}\n"
            f"Refreshed: {result.get('refreshed_at', '—')}\n<i>Manual refresh — no auto alerts.</i>"
        )
    return format_budget_theme_telegram(raw)
