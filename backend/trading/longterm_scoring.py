"""
Long-term fundamental scoring — Phase 4B.14.

Scores Screener export rows for watchlist research only.
Does not generate intraday tradecards.
"""

from __future__ import annotations

from typing import Any

STAGE = '4B.14'

VERDICT_QUALITY = 'quality_watchlist'
VERDICT_VALUE_TRAP = 'value_trap_risk'
VERDICT_LIQUIDITY = 'low_liquidity_risk'
VERDICT_REJECT = 'reject'
VERDICT_UNKNOWN = 'unknown'


def _safe_float(value: object) -> float | None:
    if value in (None, '', '—', '-', 'NA', 'N/A', 'nan'):
        return None
    try:
        text = str(value).strip().replace(',', '').replace('%', '')
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _clamp(score: float) -> int:
    return max(0, min(100, int(round(score))))


def _infer_cap_bucket(market_cap: float | None) -> str:
    """Infer cap bucket from market cap (Screener.in typically reports Cr)."""
    if market_cap is None:
        return 'unknown'
    if market_cap >= 20000:
        return 'large cap'
    if market_cap >= 5000:
        return 'mid cap'
    if market_cap >= 500:
        return 'small cap'
    return 'micro cap'


def score_longterm_stock(row: dict[str, Any]) -> dict[str, Any]:
    """
    Score one normalized Screener row.

    Returns component scores, longterm_score, reasons, risk_flags, verdict.
    """
    roce = _safe_float(row.get('roce'))
    roe = _safe_float(row.get('roe'))
    pe = _safe_float(row.get('pe'))
    debt = _safe_float(row.get('debt_to_equity'))
    sales_g = _safe_float(row.get('sales_growth'))
    profit_g = _safe_float(row.get('profit_growth'))
    payout = _safe_float(row.get('dividend_payout'))
    market_cap = _safe_float(row.get('market_cap'))
    pledged = _safe_float(row.get('pledged_percent'))
    promoter = _safe_float(row.get('promoter_holding'))
    current_price = _safe_float(row.get('current_price'))
    avg_volume = _safe_float(row.get('avg_volume') or row.get('volume'))

    reasons: list[str] = []
    risk_flags: list[str] = []

    # Quality
    quality_parts: list[float] = []
    if roce is not None:
        if roce >= 18:
            quality_parts.append(90)
            reasons.append('ROCE strong')
        elif roce >= 12:
            quality_parts.append(70)
            reasons.append('ROCE acceptable')
        elif roce >= 8:
            quality_parts.append(45)
        else:
            quality_parts.append(25)
            risk_flags.append('weak ROCE')
    if roe is not None:
        if roe >= 15:
            quality_parts.append(88)
            reasons.append('ROE strong')
        elif roe >= 10:
            quality_parts.append(65)
        else:
            quality_parts.append(35)
            risk_flags.append('weak ROE')
    quality_score = _clamp(sum(quality_parts) / len(quality_parts)) if quality_parts else 0

    # Debt
    if debt is None:
        debt_score = 50
    elif debt <= 0.3:
        debt_score = 90
        reasons.append('debt low')
    elif debt <= 0.8:
        debt_score = 75
    elif debt <= 1.5:
        debt_score = 55
    else:
        debt_score = 25
        risk_flags.append('high debt')

    # Growth
    growth_parts: list[float] = []
    if sales_g is not None:
        if sales_g >= 15:
            growth_parts.append(85)
            reasons.append('sales growth strong')
        elif sales_g >= 5:
            growth_parts.append(65)
        elif sales_g >= 0:
            growth_parts.append(45)
        else:
            growth_parts.append(20)
            risk_flags.append('sales decline')
    if profit_g is not None:
        if profit_g >= 15:
            growth_parts.append(85)
            reasons.append('profit growth steady')
        elif profit_g >= 5:
            growth_parts.append(65)
        elif profit_g >= 0:
            growth_parts.append(45)
        else:
            growth_parts.append(20)
            risk_flags.append('profit decline')
    growth_score = _clamp(sum(growth_parts) / len(growth_parts)) if growth_parts else 0

    # Valuation
    if pe is None:
        valuation_score = 50
    elif pe <= 0:
        valuation_score = 20
        risk_flags.append('negative earnings')
    elif pe <= 18:
        valuation_score = 80
        reasons.append('valuation reasonable')
    elif pe <= 30:
        valuation_score = 60
    elif pe <= 50:
        valuation_score = 40
        risk_flags.append('valuation expensive')
    else:
        valuation_score = 25
        risk_flags.append('valuation expensive')

    # Dividend
    if payout is None:
        dividend_score = 50
    elif 15 <= payout <= 50:
        dividend_score = 75
        reasons.append('dividend payout balanced')
    elif payout > 70:
        dividend_score = 40
        risk_flags.append('high payout ratio')
    elif payout > 0:
        dividend_score = 55
    else:
        dividend_score = 45

    # Liquidity / promoter risk
    if market_cap is not None and market_cap < 500:
        risk_flags.append('microcap liquidity risk')
    if avg_volume is not None and avg_volume < 10000:
        risk_flags.append('low liquidity')
    if pledged is not None and pledged >= 25:
        risk_flags.append('high pledged holding')
    if promoter is not None and promoter < 40:
        risk_flags.append('low promoter holding')

    known = sum(1 for v in (roce, roe, pe, debt, sales_g, profit_g) if v is not None)
    if known == 0:
        verdict = VERDICT_UNKNOWN
        longterm_score = 0
    else:
        weights = []
        scores = []
        for weight, comp in (
            (0.25, quality_score),
            (0.15, debt_score),
            (0.20, growth_score),
            (0.20, valuation_score),
            (0.10, dividend_score),
        ):
            if comp > 0 or (comp == 0 and weight == 0.25 and quality_score == 0):
                weights.append(weight)
                scores.append(comp)
        total_w = sum(weights) or 1
        longterm_score = _clamp(sum(s * w for s, w in zip(scores, weights)) / total_w)

        # Risk penalties
        if 'high debt' in risk_flags and 'profit decline' in risk_flags:
            longterm_score = _clamp(longterm_score - 15)
        if 'valuation expensive' in risk_flags and growth_score < 50:
            longterm_score = _clamp(longterm_score - 10)
            verdict = VERDICT_VALUE_TRAP
        elif 'microcap liquidity risk' in risk_flags or 'low liquidity' in risk_flags:
            verdict = VERDICT_LIQUIDITY
        elif longterm_score >= 65 and len(risk_flags) <= 1:
            verdict = VERDICT_QUALITY
        elif longterm_score < 40 or len(risk_flags) >= 3:
            verdict = VERDICT_REJECT
        else:
            verdict = VERDICT_UNKNOWN

    cap_bucket = str(row.get('cap_bucket') or _infer_cap_bucket(market_cap))

    return {
        'longterm_score': longterm_score,
        'quality_score': quality_score,
        'valuation_score': valuation_score,
        'debt_score': debt_score,
        'growth_score': growth_score,
        'dividend_score': dividend_score,
        'cap_bucket': cap_bucket,
        'reasons': reasons[:8],
        'risk_flags': list(dict.fromkeys(risk_flags))[:8],
        'verdict': verdict,
    }
