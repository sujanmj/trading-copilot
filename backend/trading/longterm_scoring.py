"""
Long-term fundamental scoring — Phase 4B.14B.

Scores Screener export rows for watchlist research only.
Does not generate intraday tradecards.
"""

from __future__ import annotations

from typing import Any

STAGE = '4B.14B'

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


def _roce_component(roce: float | None) -> tuple[float, list[str], list[str]]:
    reasons: list[str] = []
    risks: list[str] = []
    if roce is None:
        return 0.0, reasons, risks
    if roce >= 40:
        score = min(98.0, 88.0 + (roce - 40) * 0.25)
        reasons.append('ROCE exceptional')
    elif roce >= 25:
        score = 78.0 + (roce - 25) * 0.67
        reasons.append('ROCE strong')
    elif roce >= 18:
        score = 68.0 + (roce - 18) * 1.43
        reasons.append('ROCE strong')
    elif roce >= 12:
        score = 58.0 + (roce - 12) * 1.67
        reasons.append('ROCE acceptable')
    elif roce >= 8:
        score = 42.0 + (roce - 8) * 4.0
    else:
        score = max(15.0, 25.0 + roce * 2.0)
        risks.append('weak ROCE')
    return score, reasons, risks


def _roe_component(roe: float | None) -> tuple[float, list[str], list[str]]:
    reasons: list[str] = []
    risks: list[str] = []
    if roe is None:
        return 0.0, reasons, risks
    if roe >= 25:
        score = min(97.0, 86.0 + (roe - 25) * 0.35)
        reasons.append('ROE strong')
    elif roe >= 15:
        score = 72.0 + (roe - 15) * 1.4
        reasons.append('ROE strong')
    elif roe >= 10:
        score = 58.0 + (roe - 10) * 2.8
    else:
        score = max(18.0, 28.0 + roe * 3.0)
        risks.append('weak ROE')
    return score, reasons, risks


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
    fcf = _safe_float(row.get('free_cashflow'))
    market_cap = _safe_float(row.get('market_cap'))
    pledged = _safe_float(row.get('pledged_percent'))
    promoter = _safe_float(row.get('promoter_holding'))
    avg_volume = _safe_float(row.get('avg_volume') or row.get('volume'))

    reasons: list[str] = []
    risk_flags: list[str] = []

    roce_score, roce_reasons, roce_risks = _roce_component(roce)
    roe_score, roe_reasons, roe_risks = _roe_component(roe)
    reasons.extend(roce_reasons)
    reasons.extend(roe_reasons)
    risk_flags.extend(roce_risks)
    risk_flags.extend(roe_risks)

    quality_parts = [s for s in (roce_score, roe_score) if s > 0]
    quality_score = _clamp(sum(quality_parts) / len(quality_parts)) if quality_parts else 0

    if debt is None:
        debt_score = 50
    elif debt <= 0.1:
        debt_score = _clamp(92.0 - debt * 10.0)
        reasons.append('debt low')
    elif debt <= 0.5:
        debt_score = _clamp(86.0 - (debt - 0.1) * 20.0)
        reasons.append('debt low')
    elif debt <= 0.8:
        debt_score = _clamp(72.0 - (debt - 0.5) * 15.0)
    elif debt <= 1.5:
        debt_score = _clamp(58.0 - (debt - 0.8) * 10.0)
    else:
        debt_score = 25
        risk_flags.append('high debt')

    growth_parts: list[float] = []
    if sales_g is not None:
        if sales_g >= 15:
            growth_parts.append(85.0 + min(10.0, sales_g - 15))
            reasons.append('sales growth strong')
        elif sales_g >= 5:
            growth_parts.append(62.0 + (sales_g - 5) * 2.3)
        elif sales_g >= 0:
            growth_parts.append(45.0 + sales_g * 3.4)
        else:
            growth_parts.append(max(12.0, 30.0 + sales_g))
            risk_flags.append('sales decline')
    if profit_g is not None:
        if profit_g >= 15:
            growth_parts.append(85.0 + min(10.0, profit_g - 15))
            reasons.append('profit growth steady')
        elif profit_g >= 5:
            growth_parts.append(62.0 + (profit_g - 5) * 2.3)
        elif profit_g >= 0:
            growth_parts.append(45.0 + profit_g * 3.4)
        else:
            growth_parts.append(max(12.0, 30.0 + profit_g))
            risk_flags.append('profit decline')
    growth_score = _clamp(sum(growth_parts) / len(growth_parts)) if growth_parts else 0

    if pe is None:
        valuation_score = 50
        reasons.append('valuation data missing')
    elif pe <= 0:
        valuation_score = 20
        risk_flags.append('negative earnings')
    elif pe <= 18:
        valuation_score = _clamp(78.0 + (18 - pe) * 0.5)
        reasons.append('valuation reasonable')
    elif pe <= 30:
        valuation_score = _clamp(68.0 - (pe - 18) * 0.67)
    elif pe <= 50:
        valuation_score = _clamp(48.0 - (pe - 30) * 0.6)
        risk_flags.append('valuation expensive')
    else:
        valuation_score = 25
        risk_flags.append('valuation expensive')

    if payout is None:
        dividend_score = 50
    elif payout == 0:
        dividend_score = 52
    elif 20 <= payout <= 80:
        dividend_score = _clamp(68.0 + min(8.0, 50 - abs(payout - 50) * 0.15))
        reasons.append('dividend payout balanced')
    elif payout > 100:
        dividend_score = 32
        risk_flags.append('payout above earnings')
    elif payout > 80:
        dividend_score = 42
        risk_flags.append('high payout ratio')
    elif payout > 0:
        dividend_score = 55

    if fcf is None:
        fcf_score = 50
    elif fcf > 0:
        fcf_score = _clamp(58.0 + min(20.0, fcf * 0.04))
        reasons.append('FCF positive')
    else:
        fcf_score = 28
        risk_flags.append('negative free cash flow')

    cap_bucket = str(row.get('cap_bucket') or _infer_cap_bucket(market_cap))
    cap_adj = 0.0
    if market_cap is not None:
        if market_cap >= 20000:
            cap_adj = 3.0
        elif market_cap >= 5000:
            cap_adj = 1.5
        elif market_cap < 500:
            cap_adj = -5.0
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
        weights: list[float] = []
        scores: list[float] = []
        for weight, comp in (
            (0.24, quality_score),
            (0.14, debt_score),
            (0.18, growth_score),
            (0.16, valuation_score),
            (0.10, dividend_score),
            (0.08, fcf_score),
        ):
            if comp > 0 or weight in (0.24, 0.16):
                weights.append(weight)
                scores.append(float(comp))
        total_w = sum(weights) or 1.0
        base_score = sum(s * w for s, w in zip(scores, weights)) / total_w
        longterm_score = _clamp(base_score + cap_adj)

        if debt is not None and debt >= 0.45 and 'debt low' in reasons:
            longterm_score = _clamp(longterm_score - 2)

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

    return {
        'longterm_score': longterm_score,
        'quality_score': quality_score,
        'valuation_score': valuation_score,
        'debt_score': debt_score,
        'growth_score': growth_score,
        'dividend_score': dividend_score,
        'fcf_score': fcf_score,
        'cap_bucket': cap_bucket,
        'reasons': reasons[:8],
        'risk_flags': list(dict.fromkeys(risk_flags))[:8],
        'verdict': verdict,
    }
