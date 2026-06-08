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
STAGE = '48A'
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


def _freshness_status(*ages: Optional[float]) -> str:
    valid = [a for a in ages if a is not None]
    if not valid:
        return 'stale'
    if all(a <= 6 for a in valid):
        return 'fresh'
    if any(a <= 24 for a in valid):
        return 'partial'
    return 'stale'


def compute_freshness_panel() -> dict[str, Any]:
    from backend.analytics.theme_baskets import BASKETS_FILE, load_theme_baskets

    data = load_theme_baskets()
    news_age_h = _file_age_hours(get_data_path('news_feed.json'))
    govt_age_h = _file_age_hours(get_data_path('govt_intelligence.json'))
    news_age_h = min(filter(lambda x: x is not None, [news_age_h, govt_age_h]), default=news_age_h)

    cache_refreshed = data.get('cache_refreshed_at') or data.get('generated_at')
    theme_cache_age_h = None
    if cache_refreshed:
        try:
            ts = datetime.fromisoformat(str(cache_refreshed))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=IST)
            theme_cache_age_h = (datetime.now(IST) - ts.astimezone(IST)).total_seconds() / 3600.0
        except (TypeError, ValueError):
            theme_cache_age_h = _file_age_hours(BASKETS_FILE)

    scanner_age_h = _file_age_hours(get_data_path('scanner_data.json'))
    status = _freshness_status(news_age_h, theme_cache_age_h, scanner_age_h)

    def _fmt(age_h: Optional[float]) -> str:
        if age_h is None:
            return 'unknown'
        if age_h < 1:
            return f'{int(age_h * 60)}m ago'
        return f'{age_h:.1f}h ago'

    return {
        'status': status,
        'latest_news_age': _fmt(news_age_h),
        'latest_theme_cache_age': _fmt(theme_cache_age_h),
        'latest_scanner_age': _fmt(scanner_age_h),
        'news_age_hours': news_age_h,
        'theme_cache_age_hours': theme_cache_age_h,
        'scanner_age_hours': scanner_age_h,
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
        'Policy continuity / state capex risk — neutral framing only. '
        'Watch state-contract names for volatility; avoid blind entry until policy clarity.'
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
    stale = freshness.get('status') == 'stale'

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

    positive: list[dict[str, Any]] = []
    indirect: list[dict[str, Any]] = []
    risk: list[dict[str, Any]] = []
    seen_tickers: set[str] = set()

    for theme_row in themes_out[:5]:
        tid = theme_row['theme_id']
        ranked = rank_theme_stocks(tid, limit=6)
        negative_theme = _detect_negative_impact(headline, tid)
        for row in ranked:
            ticker = str(row.get('ticker') or '').upper()
            if not ticker or ticker in seen_tickers:
                continue
            seen_tickers.add(ticker)
            bucket = str(row.get('bucket') or '')
            side = 'Risk' if negative_theme and bucket != 'direct' else (
                'Beneficiary' if bucket == 'direct' else 'Indirect'
            )
            if negative_theme and bucket == 'direct' and any(t in lower for t in NEGATIVE_POLICY_TERMS):
                side = 'Risk'
            score = int(row.get('score') or 0)
            entry = {
                'ticker': ticker,
                'theme_id': tid,
                'theme': theme_row.get('display_name'),
                'impact_side': side,
                'score': score,
                'reason': theme_row.get('why') or row.get('label') or '',
                'freshness': freshness.get('status', 'unknown'),
                'confirmation_needed': row.get('confirm') or 'Confirm with price + volume + sector breadth',
                'stance': _stance_for_score(score, stale=stale, negative=(side == 'Risk')),
            }
            if side == 'Beneficiary':
                positive.append(entry)
            elif side == 'Risk':
                risk.append(entry)
            else:
                indirect.append(entry)

    top_score = themes_out[0].get('budget_impact_score', 0) if themes_out else 0
    has_conf = any(t in lower for t in ('order', 'tender', 'project', 'contract', 'allocation'))
    stance = _stance_for_score(top_score, stale=stale, negative=bool(risk and not positive), has_confirmation=has_conf)

    result = {
        'ok': True,
        'mode': 'news_analysis',
        'headline': headline[:240],
        'detected_themes': themes_out,
        'impact_map': build_impact_map(themes_out[0]['theme_id'] if themes_out else hint_ids[0] if hint_ids else ''),
        'positive': positive[:8],
        'indirect': indirect[:8],
        'risk': risk[:8],
        'stance': stance,
        'confirmation': 'Confirm with price + volume + sector breadth.',
        'freshness': freshness,
        'political_neutral': False,
    }
    if persist:
        _append_event_log({
            'stage': STAGE,
            'mode': 'analyze_news',
            'text': headline[:240],
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


def get_budget_overview() -> dict[str, Any]:
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

    stock_rankings = []
    for row in top_themes[:5]:
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
        'source_counts': {
            'themes': len(list_all_baskets()),
            'budget_themes': len(top_themes),
            'catalysts': len(top_catalysts),
        },
        'disclaimer': 'Research only — watch/confirm. No blind entry.',
    }
    return payload


def get_budget_themes() -> dict[str, Any]:
    from backend.analytics.theme_baskets import THEME_CATEGORIES, get_basket_by_id

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
        scored = _budget_impact_score(str(cat.get('headline') or ''), str(resolved or theme_id))
        enriched.append({**cat, 'budget_impact_score': scored.get('budget_impact_score', cat.get('catalyst_score', 0))})
    return {
        'ok': True,
        'theme_id': resolved,
        'catalysts': enriched,
        'count': len(enriched),
    }


def get_budget_theme_scan(theme_id: str, *, limit: int = 12) -> dict[str, Any]:
    from backend.analytics.theme_baskets import get_basket_by_id, rank_theme_stocks, resolve_theme_id

    resolved = resolve_theme_id(theme_id)
    if not get_basket_by_id(theme_id):
        return {'ok': False, 'error': f'theme not found: {theme_id}'}
    freshness = compute_freshness_panel()
    stale = freshness.get('status') == 'stale'
    ranked = rank_theme_stocks(theme_id, limit=limit)
    stocks = []
    for row in ranked:
        bucket = str(row.get('bucket') or '')
        side = 'Beneficiary' if bucket == 'direct' else ('Indirect' if bucket != 'avoid_or_risk' else 'Avoid')
        score = int(row.get('score') or 0)
        stocks.append({
            'ticker': row.get('ticker'),
            'theme_id': resolved,
            'impact_side': side,
            'score': score,
            'reason': row.get('label') or '',
            'freshness': freshness.get('status'),
            'confirmation_needed': row.get('confirm') or '',
            'stance': _stance_for_score(score, stale=stale),
            'bucket': bucket,
        })
    return {
        'ok': True,
        'theme_id': resolved,
        'stocks': stocks,
        'count': len(stocks),
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
        f"News: {fresh.get('latest_news_age', '—')} · Theme cache: {fresh.get('latest_theme_cache_age', '—')}",
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
