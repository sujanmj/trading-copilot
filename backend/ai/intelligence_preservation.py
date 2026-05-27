"""
Intelligence Preservation Layer — nuance, contradictions, and regime-aware compression.

Sits between dedupe/rank and Gemini/Claude synthesis. Ensures high-fidelity signals
reach Claude even when bulk context is compressed.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.ai.signal_ranker import (
    extract_key_metrics,
    rank_govt_items,
    rank_news_articles,
    rank_news_articles_with_stats,
    rank_reddit_tickers,
    rank_scanner_signals,
)
from backend.ai.novelty_scoring import select_diverse_raw_evidence
from backend.ai.token_optimizer import section_char_limit
from backend.ai.token_optimizer import estimate_tokens, extract_symbols

# ── Logging tags (required by spec) ──────────────────────────────────────────

def _log(tag: str, msg: str):
    print(f"[{tag}] {msg}")


# ── Constants ───────────────────────────────────────────────────────────────

BULLISH_LABELS = frozenset({'BULL', 'BULLISH', 'POS', 'POSITIVE', 'UP', 'LONG', 'BUY'})
BEARISH_LABELS = frozenset({'BEAR', 'BEARISH', 'NEG', 'NEGATIVE', 'DOWN', 'SHORT', 'SELL', 'AVOID'})

HIGH_IMPACT_KEYWORDS = (
    'sebi', 'rbi', 'budget', 'tariff', 'sanction', 'policy', 'rate cut', 'rate hike',
    'repo rate', 'crash', 'circuit', 'halt', 'emergency', 'war', 'inflation', 'cpi',
    'fii', 'dii', 'institutional', 'outflow', 'inflow', 'default', 'downgrade',
    'upgrade', 'fraud', 'probe', 'ban', 'subsidy', 'stimulus', 'geopolitical',
)

REGIME_NAMES = (
    'bullish_trend',
    'sideways',
    'volatile',
    'high_risk',
    'risk_off',
    'regime_transition',
    'macro_uncertainty',
    'panic_volatile',
)

MIN_REGIME_DURATION_SEC = float(__import__('os').environ.get('REGIME_MIN_DURATION_SEC', '900'))


def _safe_dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _safe_list(v) -> list:
    return v if isinstance(v, list) else []


def _sentiment_bucket(label: Any) -> str:
    text = str(label or '').strip().upper()
    if text in BULLISH_LABELS or text.startswith('BULL') or text.startswith('POS'):
        return 'bullish'
    if text in BEARISH_LABELS or text.startswith('BEAR') or text.startswith('NEG'):
        return 'bearish'
    return 'neutral'


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _contains_high_impact(text: str) -> bool:
    lower = (text or '').lower()
    return any(kw in lower for kw in HIGH_IMPACT_KEYWORDS)


# ── 1. Contradiction preservation ───────────────────────────────────────────

def detect_contradictions(all_data: Dict[str, Any]) -> Dict[str, Any]:
    """Detect opposing signals — never flatten these in compression."""
    contradictions: List[dict] = []

    news = _safe_dict(all_data.get('news'))
    articles = _safe_list(news.get('articles'))
    bull_n = bear_n = neutral_n = 0
    for art in articles:
        bucket = _sentiment_bucket(art.get('sentiment_label'))
        if bucket == 'bullish':
            bull_n += 1
        elif bucket == 'bearish':
            bear_n += 1
        else:
            neutral_n += 1

    if bull_n >= 2 and bear_n >= 2:
        score = _clamp(min(bull_n, bear_n) / max(bull_n, bear_n, 1))
        contradictions.append({
            'type': 'news_sentiment_split',
            'summary': f'News conflict: {bull_n} bullish vs {bear_n} bearish headlines (neutral={neutral_n})',
            'disagreement_score': round(score, 3),
            'bullish_count': bull_n,
            'bearish_count': bear_n,
        })
        _log('CONTRADICTION DETECTED', contradictions[-1]['summary'])

    scanner = _safe_dict(all_data.get('scanner'))
    signals = _safe_list(scanner.get('top_signals'))
    longs = [s for s in signals if _sentiment_bucket(s.get('direction')) == 'bullish']
    shorts = [s for s in signals if _sentiment_bucket(s.get('direction')) == 'bearish']
    if len(longs) >= 2 and len(shorts) >= 2:
        score = _clamp(min(len(longs), len(shorts)) / max(len(longs), len(shorts), 1))
        long_tickers = ', '.join(str(_safe_dict(s).get('ticker', '?')) for s in longs[:4])
        short_tickers = ', '.join(str(_safe_dict(s).get('ticker', '?')) for s in shorts[:4])
        contradictions.append({
            'type': 'scanner_direction_split',
            'summary': f'Scanner split: LONG [{long_tickers}] vs SHORT [{short_tickers}]',
            'disagreement_score': round(score, 3),
            'long_count': len(longs),
            'short_count': len(shorts),
        })
        _log('CONTRADICTION DETECTED', contradictions[-1]['summary'])

    india = _safe_dict(all_data.get('india_markets'))
    global_m = _safe_dict(all_data.get('global_markets'))
    india_prices = _safe_dict(india.get('prices'))
    india_changes = [
        float(_safe_dict(p).get('change_percent') or 0) for p in india_prices.values()
    ]
    india_avg = sum(india_changes) / len(india_changes) if india_changes else 0.0

    global_changes: List[float] = []
    for key in ('markets', 'indices', 'prices'):
        block = _safe_dict(global_m.get(key))
        for info in block.values():
            info = _safe_dict(info)
            try:
                global_changes.append(float(info.get('change_percent', info.get('change_pct', 0)) or 0))
            except (TypeError, ValueError):
                continue
    global_avg = sum(global_changes) / len(global_changes) if global_changes else 0.0

    if global_changes and abs(global_avg) > 0.25 and abs(india_avg) > 0.25:
        if (global_avg > 0 and india_avg < 0) or (global_avg < 0 and india_avg > 0):
            score = _clamp(abs(global_avg - india_avg) / 3.0)
            contradictions.append({
                'type': 'global_india_divergence',
                'summary': (
                    f'Global/India divergence: global avg {global_avg:+.2f}% vs '
                    f'India avg {india_avg:+.2f}%'
                ),
                'disagreement_score': round(score, 3),
                'global_avg': round(global_avg, 3),
                'india_avg': round(india_avg, 3),
            })
            _log('CONTRADICTION DETECTED', contradictions[-1]['summary'])

    reddit = _safe_dict(all_data.get('reddit'))
    mood = _safe_dict(reddit.get('market_mood'))
    reddit_sent = _sentiment_bucket(mood.get('sentiment'))
    news_dominant = 'bullish' if bull_n > bear_n else ('bearish' if bear_n > bull_n else 'neutral')
    if reddit_sent in ('bullish', 'bearish') and news_dominant in ('bullish', 'bearish'):
        if reddit_sent != news_dominant:
            score = _clamp(abs(bull_n - bear_n) / max(bull_n + bear_n, 1) + 0.3)
            contradictions.append({
                'type': 'retail_institutional_divergence',
                'summary': f'Reddit {reddit_sent.upper()} vs news dominant {news_dominant.upper()}',
                'disagreement_score': round(score, 3),
                'reddit_sentiment': reddit_sent,
                'news_dominant': news_dominant,
            })
            _log('CONTRADICTION DETECTED', contradictions[-1]['summary'])

    govt = _safe_dict(all_data.get('govt'))
    govt_dirs = [_sentiment_bucket(i.get('direction')) for i in _safe_list(govt.get('high_impact_items'))]
    govt_bull = sum(1 for d in govt_dirs if d == 'bullish')
    govt_bear = sum(1 for d in govt_dirs if d == 'bearish')
    if govt_bull >= 1 and govt_bear >= 1:
        contradictions.append({
            'type': 'institutional_policy_divergence',
            'summary': f'Govt policy mix: {govt_bull} bullish vs {govt_bear} bearish high-impact items',
            'disagreement_score': round(_clamp(min(govt_bull, govt_bear) / max(govt_bull, govt_bear, 1)), 3),
        })
        _log('CONTRADICTION DETECTED', contradictions[-1]['summary'])

    outliers = _detect_outlier_signals(scanner, signals)
    for outlier in outliers:
        contradictions.append(outlier)
        _log('CONTRADICTION DETECTED', outlier['summary'])

    if contradictions:
        overall = sum(c.get('disagreement_score', 0) for c in contradictions) / len(contradictions)
    else:
        overall = 0.0

    summary_lines = ['=== CONTRADICTIONS (PRESERVE — DO NOT FLATTEN) ===']
    for c in contradictions:
        summary_lines.append(
            f"  [{c.get('type', '?')}] disagreement={c.get('disagreement_score', 0):.2f} | {c.get('summary', '')}"
        )
    if len(summary_lines) == 1:
        summary_lines.append('  No major contradictions detected.')

    return {
        'contradictions': contradictions,
        'overall_disagreement_score': round(overall, 3),
        'summary_block': '\n'.join(summary_lines),
        'count': len(contradictions),
    }


def _detect_outlier_signals(scanner: dict, signals: List[dict]) -> List[dict]:
    """Unusual spikes opposing sector consensus."""
    outliers = []
    sectors = _safe_list(scanner.get('sector_rotation'))
    sector_dir = {
        str(_safe_dict(r).get('sector', '')).upper(): _sentiment_bucket(_safe_dict(r).get('direction'))
        for r in sectors
    }

    for sig in signals[:12]:
        sig = _safe_dict(sig)
        sector = str(sig.get('sector', '')).upper()
        ticker_dir = _sentiment_bucket(sig.get('direction'))
        sector_consensus = sector_dir.get(sector, 'neutral')
        chg = abs(float(sig.get('change_percent') or 0))
        strength = str(sig.get('strength', '')).upper()

        if sector_consensus in ('bullish', 'bearish') and ticker_dir in ('bullish', 'bearish'):
            if ticker_dir != sector_consensus and chg >= 2.0:
                outliers.append({
                    'type': 'outlier_vs_sector',
                    'summary': (
                        f"Outlier {sig.get('ticker', '?')} {ticker_dir} ({chg:+.1f}%) "
                        f"vs sector {sector} consensus {sector_consensus}"
                    ),
                    'disagreement_score': round(_clamp(chg / 8.0), 3),
                    'ticker': sig.get('ticker'),
                })
        elif strength == 'ULTRA' and chg >= 5.0:
            outliers.append({
                'type': 'scanner_anomaly',
                'summary': f"Anomaly {sig.get('ticker', '?')} ULTRA move {float(sig.get('change_percent', 0)):+.2f}%",
                'disagreement_score': round(_clamp(chg / 10.0), 3),
                'ticker': sig.get('ticker'),
            })
    return outliers[:5]


# ── 2. Confidence scoring ─────────────────────────────────────────────────────

def _count_sources_for_ticker(all_data: Dict[str, Any], ticker: str) -> int:
    ticker = str(ticker or '').upper().replace('.NS', '')
    if not ticker:
        return 0
    sources = 0

    for sig in _safe_list(_safe_dict(all_data.get('scanner')).get('top_signals')):
        if str(_safe_dict(sig).get('ticker', '')).upper().replace('.NS', '') == ticker:
            sources += 1
            break

    for art in _safe_list(_safe_dict(all_data.get('news')).get('articles')):
        title = str(_safe_dict(art).get('title', '')).upper()
        if ticker in title or ticker in str(_safe_dict(art).get('stocks', '')).upper():
            sources += 1
            break

    for t in _safe_list(_safe_dict(all_data.get('reddit')).get('trending_tickers')):
        if str(_safe_dict(t).get('ticker', '')).upper().replace('.NS', '') == ticker:
            sources += 1
            break

    for item in _safe_list(_safe_dict(all_data.get('govt')).get('high_impact_items')):
        stocks = [str(s).upper() for s in _safe_list(_safe_dict(item).get('affected_stocks'))]
        if ticker in stocks or ticker.replace('.NS', '') in [s.replace('.NS', '') for s in stocks]:
            sources += 1
            break

    return sources


def _agreement_score_for_signal(all_data: Dict[str, Any], ticker: str, direction: str) -> float:
    """How many independent sources agree on direction for this ticker."""
    ticker = str(ticker or '').upper().replace('.NS', '')
    if not ticker:
        return 0.5
    target = _sentiment_bucket(direction)
    votes: List[str] = []

    for sig in _safe_list(_safe_dict(all_data.get('scanner')).get('top_signals')):
        sig = _safe_dict(sig)
        if str(sig.get('ticker', '')).upper().replace('.NS', '') == ticker:
            votes.append(_sentiment_bucket(sig.get('direction')))

    for t in _safe_list(_safe_dict(all_data.get('reddit')).get('trending_tickers')):
        t = _safe_dict(t)
        if str(t.get('ticker', '')).upper().replace('.NS', '') == ticker:
            votes.append(_sentiment_bucket(t.get('sentiment')))

    for art in _safe_list(_safe_dict(all_data.get('news')).get('articles'))[:30]:
        art = _safe_dict(art)
        title = str(art.get('title', '')).upper()
        if ticker in title:
            votes.append(_sentiment_bucket(art.get('sentiment_label')))

    if not votes:
        return 0.5
    matching = sum(1 for v in votes if v == target and target != 'neutral')
    neutral = sum(1 for v in votes if v == 'neutral')
    return _clamp(0.35 + (matching / len(votes)) * 0.65 - (neutral / len(votes)) * 0.1)


def _impact_score(kind: str, item: dict) -> float:
    item = _safe_dict(item)
    if kind == 'scanner':
        strength = {'ULTRA': 10, 'STRONG': 8, 'MODERATE': 5, 'WEAK': 3}.get(
            str(item.get('strength', '')).upper(), 4
        )
        vol = float(item.get('volume_ratio') or 1)
        chg = abs(float(item.get('change_percent') or 0))
        return round(min(10.0, strength * 0.4 + min(vol, 5) * 0.3 + min(chg, 8) * 0.3), 2)
    if kind == 'govt':
        base = float(item.get('impact_score') or 5)
        headline = str(item.get('english_headline', item.get('title', '')))
        if _contains_high_impact(headline):
            base = min(10.0, base + 1.5)
        return round(base, 2)
    if kind == 'news':
        score = abs(float(item.get('sentiment_score') or 0.5)) * 5
        if _contains_high_impact(str(item.get('title', ''))):
            score = min(10.0, score + 3)
        return round(score, 2)
    return 5.0


def _confidence_score(source_count: int, agreement: float, impact: float) -> float:
    return round(_clamp(0.25 + source_count * 0.12 + agreement * 0.35 + (impact / 10) * 0.28), 3)


def build_scored_signals(all_data: Dict[str, Any], contradictions: dict) -> Dict[str, Any]:
    """Every summarized signal carries confidence metadata."""
    scored: List[dict] = []

    for sig in rank_scanner_signals(_safe_dict(all_data.get('scanner')), limit=10):
        sig = _safe_dict(sig)
        ticker = str(sig.get('ticker', '?'))
        direction = str(sig.get('direction', '?'))
        impact = _impact_score('scanner', sig)
        src_count = _count_sources_for_ticker(all_data, ticker)
        agreement = _agreement_score_for_signal(all_data, ticker, direction)
        confidence = _confidence_score(src_count, agreement, impact)
        bypass = (
            str(sig.get('strength', '')).upper() == 'ULTRA'
            or impact >= 8.0
            or abs(float(sig.get('change_percent') or 0)) >= 5.0
        )
        scored.append({
            'kind': 'scanner',
            'ticker': ticker,
            'label': f"[{sig.get('strength', '?')}|{direction}] {ticker} {float(sig.get('change_percent', 0)):+.2f}%",
            'confidence': confidence,
            'source_count': src_count,
            'agreement_score': round(agreement, 3),
            'impact_score': impact,
            'bypass_compression': bypass,
        })
        if bypass:
            _log('RAW SIGNAL PRESERVED', f'scanner {ticker} impact={impact}')

    for gov in rank_govt_items(_safe_dict(all_data.get('govt')), limit=6):
        gov = _safe_dict(gov)
        headline = str(gov.get('english_headline', gov.get('title', '')))
        impact = _impact_score('govt', gov)
        stocks = _safe_list(gov.get('affected_stocks'))
        src_count = max(1, len(stocks))
        agreement = 0.7 if gov.get('direction') else 0.5
        confidence = _confidence_score(src_count, agreement, impact)
        bypass = impact >= 7 or _contains_high_impact(headline)
        scored.append({
            'kind': 'govt',
            'ticker': stocks[0] if stocks else 'MACRO',
            'label': f"[GOVT {impact}] {headline[:90]}",
            'confidence': confidence,
            'source_count': src_count,
            'agreement_score': round(agreement, 3),
            'impact_score': impact,
            'bypass_compression': bypass,
        })
        if bypass:
            _log('RAW SIGNAL PRESERVED', f'govt impact={impact} {headline[:60]}')

    for art in rank_news_articles(_safe_dict(all_data.get('news')), limit=6):
        art = _safe_dict(art)
        impact = _impact_score('news', art)
        title = str(art.get('title', ''))
        bypass = _contains_high_impact(title) or impact >= 7
        scored.append({
            'kind': 'news',
            'ticker': 'NEWS',
            'label': f"[{art.get('sentiment_label', '?')}] {title[:90]}",
            'confidence': _confidence_score(1, 0.5, impact),
            'source_count': 1,
            'agreement_score': 0.5,
            'impact_score': impact,
            'bypass_compression': bypass,
        })
        if bypass:
            _log('RAW SIGNAL PRESERVED', f'headline {title[:60]}')

    lines = ['=== SCORED SIGNALS (confidence metadata) ===']
    for s in sorted(scored, key=lambda x: x['impact_score'], reverse=True)[:18]:
        lines.append(
            f"  {s['label']} | conf={s['confidence']:.2f} sources={s['source_count']} "
            f"agree={s['agreement_score']:.2f} impact={s['impact_score']:.1f}"
            f"{' [BYPASS]' if s['bypass_compression'] else ''}"
        )

    return {
        'signals': scored,
        'summary_block': '\n'.join(lines),
        'bypass_items': [s for s in scored if s['bypass_compression']],
    }


# ── 3. Market regime detection ────────────────────────────────────────────────

def detect_market_regime(
    all_data: Dict[str, Any],
    contradictions: Optional[dict] = None,
    previous_regime: Optional[str] = None,
    regime_since: Optional[str] = None,
) -> Dict[str, Any]:
    metrics = extract_key_metrics(all_data)
    india_avg = float(metrics.get('india_avg_change') or 0)
    scanner = _safe_dict(all_data.get('scanner'))
    signals = _safe_list(scanner.get('top_signals'))

    abs_changes = [abs(float(_safe_dict(s).get('change_percent') or 0)) for s in signals]
    avg_abs = sum(abs_changes) / len(abs_changes) if abs_changes else 0.0
    ultra_count = sum(1 for s in signals if str(_safe_dict(s).get('strength', '')).upper() == 'ULTRA')

    news = _safe_dict(all_data.get('news'))
    articles = _safe_list(news.get('articles'))
    shock_count = sum(1 for a in articles[:25] if _contains_high_impact(str(_safe_dict(a).get('title', ''))))

    disagree = float((contradictions or {}).get('overall_disagreement_score') or 0)
    scores = {name: 0.0 for name in REGIME_NAMES}

    volatility_index = _clamp(
        avg_abs / 6.0 + ultra_count * 0.08 + abs(india_avg) / 4.0 + shock_count * 0.05 + disagree * 0.25
    )

    if india_avg > 0.35 and avg_abs < 2.5:
        scores['bullish_trend'] += 0.45
    if abs(india_avg) < 0.3 and avg_abs < 1.8:
        scores['sideways'] += 0.5
    if avg_abs >= 2.0 or ultra_count >= 2:
        scores['volatile'] += 0.35
    if disagree >= 0.32 and volatility_index >= 0.38:
        scores['high_risk'] += 0.42
    if disagree >= 0.4 and volatility_index >= 0.42:
        scores['risk_off'] += 0.35
    liquidity_stress = ultra_count >= 3 and avg_abs >= 3.5 and shock_count >= 2
    macro_contradiction = disagree >= 0.45 and shock_count >= 3
    vix_like_extreme = avg_abs >= 5.0 and ultra_count >= 5 and volatility_index >= 0.62
    if vix_like_extreme and macro_contradiction and liquidity_stress:
        scores['panic_volatile'] += 0.72
    elif (
        (avg_abs >= 4.5 or ultra_count >= 5)
        and disagree >= 0.4
        and volatility_index >= 0.58
        and liquidity_stress
    ):
        scores['panic_volatile'] += 0.55
    elif avg_abs >= 3.0 and ultra_count >= 3 and volatility_index >= 0.5:
        scores['volatile'] += 0.25
        scores['high_risk'] += 0.18
    if int(metrics.get('govt_high_impact') or 0) >= 3 or shock_count >= 3:
        scores['macro_uncertainty'] += 0.5
    if disagree >= 0.35 or (previous_regime and previous_regime != max(scores, key=scores.get)):
        scores['regime_transition'] += 0.35 + disagree * 0.4

    if previous_regime == 'panic_volatile' and scores['panic_volatile'] < scores.get('volatile', 0) + 0.12:
        scores['panic_volatile'] = max(scores['panic_volatile'], scores.get('volatile', 0) + 0.12)

    candidate = max(scores, key=lambda k: scores[k])
    if scores[candidate] < 0.25:
        candidate = 'sideways'
        scores['sideways'] = 0.5

    primary = candidate
    now = datetime.now()
    elapsed_sec = MIN_REGIME_DURATION_SEC + 1
    if regime_since and previous_regime:
        try:
            since_dt = datetime.fromisoformat(str(regime_since).replace('Z', '+00:00'))
            if since_dt.tzinfo:
                since_dt = since_dt.replace(tzinfo=None)
            elapsed_sec = (now - since_dt).total_seconds()
        except Exception:
            elapsed_sec = MIN_REGIME_DURATION_SEC + 1

    if previous_regime and candidate != previous_regime and elapsed_sec < MIN_REGIME_DURATION_SEC:
        allow_shift = (
            candidate == 'panic_volatile' and vix_like_extreme
        ) or (
            previous_regime == 'panic_volatile'
            and scores.get('panic_volatile', 0) < scores.get('volatile', 0)
        )
        if not allow_shift:
            primary = previous_regime
            candidate = previous_regime

    regime_shift = bool(previous_regime and previous_regime != primary)
    new_regime_since = regime_since
    if regime_shift or not regime_since:
        new_regime_since = now.isoformat()
    elif not previous_regime:
        new_regime_since = now.isoformat()

    sentiment_instability = _clamp(disagree + (shock_count * 0.06))
    news_shock_intensity = _clamp(shock_count / 8.0)
    scanner_anomaly_strength = _clamp(ultra_count / 5.0 + avg_abs / 8.0)

    # Regime-aware compression aggressiveness (lower = preserve more detail)
    if primary == 'bullish_trend' and volatility_index < 0.4:
        compression_aggressiveness = 0.88
    elif primary == 'sideways' and volatility_index < 0.45:
        compression_aggressiveness = 0.62
    elif primary == 'panic_volatile' or volatility_index > 0.65:
        compression_aggressiveness = 0.22
    elif primary in ('volatile', 'high_risk', 'risk_off'):
        compression_aggressiveness = 0.35
    elif primary == 'macro_uncertainty':
        compression_aggressiveness = 0.18
    elif primary == 'regime_transition':
        compression_aggressiveness = 0.25
    elif primary in ('sideways', 'bullish_trend'):
        compression_aggressiveness = 0.72
    else:
        compression_aggressiveness = 0.55

    if regime_shift:
        _log('REGIME SHIFT', f'{previous_regime} -> {primary} (vol={volatility_index:.2f})')

    summary_lines = [
        '=== MARKET REGIME ===',
        f"  Primary: {primary.replace('_', ' ').upper()} | volatility={volatility_index:.2f}",
        f"  Persistence: {int(elapsed_sec // 60)}m in current regime",
        f"  Compression mode: {'AGGRESSIVE' if compression_aggressiveness >= 0.7 else 'PRESERVE DETAIL'} "
        f"(aggressiveness={compression_aggressiveness:.2f})",
        f"  Signals: news_shock={news_shock_intensity:.2f} sentiment_instability={sentiment_instability:.2f} "
        f"scanner_anomaly={scanner_anomaly_strength:.2f}",
    ]

    return {
        'primary_regime': primary,
        'regime_scores': {k: round(v, 3) for k, v in scores.items()},
        'volatility_index': round(volatility_index, 3),
        'sentiment_instability': round(sentiment_instability, 3),
        'news_shock_intensity': round(news_shock_intensity, 3),
        'scanner_anomaly_strength': round(scanner_anomaly_strength, 3),
        'compression_aggressiveness': round(compression_aggressiveness, 3),
        'regime_shift': regime_shift,
        'previous_regime': previous_regime,
        'regime_since': new_regime_since,
        'summary_block': '\n'.join(summary_lines),
    }


# ── 4. Raw high-impact evidence (untouched) ───────────────────────────────────

def extract_raw_high_impact(all_data: Dict[str, Any], scored: dict) -> str:
    """Diverse raw evidence block — novelty-filtered, passed to Claude verbatim."""
    candidates: List[tuple] = []
    _, novelty_stats = rank_news_articles_with_stats(_safe_dict(all_data.get('news')), limit=10)

    for art in rank_news_articles(_safe_dict(all_data.get('news')), limit=10):
        art = _safe_dict(art)
        title = str(art.get('title', '')).strip()
        if not title:
            continue
        novelty = float(art.get('_novelty_score') or 5)
        if novelty < 2.0 and not _contains_high_impact(title):
            continue
        line = (
            f"HEADLINE | [{art.get('sentiment_label', '?')}] {title} "
            f"| source={art.get('source', art.get('publisher', '?'))}"
        )
        candidates.append((novelty + 1.0, line, 'news'))

    for gov in rank_govt_items(_safe_dict(all_data.get('govt')), limit=6):
        gov = _safe_dict(gov)
        headline = str(gov.get('english_headline', gov.get('title', ''))).strip()
        impact = float(gov.get('impact_score') or 0)
        if impact < 4 and not _contains_high_impact(headline):
            continue
        stocks = ', '.join(str(s) for s in _safe_list(gov.get('affected_stocks'))[:5])
        line = (
            f"GOVT ALERT | [{impact}/10 {gov.get('direction', '?')}] "
            f"{headline} | affects: {stocks or 'MACRO'}"
        )
        candidates.append((impact + 2.0, line, 'govt'))

    for sig in rank_scanner_signals(_safe_dict(all_data.get('scanner')), limit=8):
        sig = _safe_dict(sig)
        strength = str(sig.get('strength', '')).upper()
        chg = float(sig.get('change_percent') or 0)
        if strength != 'ULTRA' and abs(chg) < 4.0:
            continue
        signals_txt = ' + '.join(_safe_list(sig.get('signals'))[:3])
        line = (
            f"SCANNER ANOMALY | [{strength}|{sig.get('direction', '?')}] "
            f"{sig.get('ticker', '?')} Rs.{sig.get('price', '?')} {chg:+.2f}% "
            f"vol={float(sig.get('volume_ratio') or 0):.1f}x | {signals_txt}"
        )
        score = 8.0 + abs(chg) * 0.3 + (2.0 if strength == 'ULTRA' else 0)
        candidates.append((score, line, 'scanner'))

    for rev in _detect_sentiment_reversals(all_data)[:5]:
        candidates.append((7.5, f"SENTIMENT REVERSAL | {rev}", 'sentiment'))

    nse = _safe_dict(all_data.get('nse_filings'))
    for item in _safe_list(nse.get('latest_high_impact'))[:3]:
        item = _safe_dict(item)
        line = (
            f"NSE FILING | [{item.get('symbol', '?')}] {item.get('impact_category', '?')} | "
            f"{str(item.get('subject', ''))[:100]}"
        )
        candidates.append((6.5, line, 'nse'))

    selected, diversity_meta = select_diverse_raw_evidence(candidates, limit=8)
    lines = ['=== RAW HIGH-IMPACT EVIDENCE (UNTOUCHED — DO NOT IGNORE) ===']
    if selected:
        lines.extend(selected)
        for ln in selected[:4]:
            _log('RAW SIGNAL PRESERVED', ln[:80])
    else:
        lines.append('  (No extreme raw signals — market relatively calm)')

    lines.append(
        f"  [evidence_meta] novelty_avg={novelty_stats.get('avg_novelty_score', '?')} "
        f"repetition_suppressed={novelty_stats.get('repetition_suppressed', 0)} "
        f"diversity_suppressed={diversity_meta.get('diversity_suppressed', 0)}"
    )
    return '\n'.join(lines)


def _detect_sentiment_reversals(all_data: Dict[str, Any]) -> List[str]:
    """Tickers where retail/news disagree sharply."""
    reversals = []
    reddit_map = {
        str(_safe_dict(t).get('ticker', '')).upper().replace('.NS', ''): _sentiment_bucket(t.get('sentiment'))
        for t in _safe_list(_safe_dict(all_data.get('reddit')).get('trending_tickers'))
    }
    for ticker, reddit_dir in reddit_map.items():
        if not ticker or reddit_dir == 'neutral':
            continue
        news_dirs = []
        for art in _safe_list(_safe_dict(all_data.get('news')).get('articles'))[:40]:
            title = str(_safe_dict(art).get('title', '')).upper()
            if ticker in title:
                news_dirs.append(_sentiment_bucket(art.get('sentiment_label')))
        if not news_dirs:
            continue
        bull = sum(1 for d in news_dirs if d == 'bullish')
        bear = sum(1 for d in news_dirs if d == 'bearish')
        news_dir = 'bullish' if bull > bear else ('bearish' if bear > bull else 'neutral')
        if news_dir in ('bullish', 'bearish') and news_dir != reddit_dir:
            reversals.append(f"{ticker}: Reddit {reddit_dir} vs News {news_dir} ({bull}B/{bear}S articles)")
    return reversals


# ── 5–7. Adaptive compression profile ───────────────────────────────────────

def build_compression_profile(regime: dict, contradictions: dict, scored: dict) -> dict:
    aggressiveness = float(regime.get('compression_aggressiveness') or 0.6)
    volatility = float(regime.get('volatility_index') or 0.5)
    disagree = float(contradictions.get('overall_disagreement_score') or 0)
    bypass_count = len(scored.get('bypass_items') or [])

    # Adaptive section limits — lower aggressiveness = larger preserved sections
    base_section = int(1800 + (1.0 - aggressiveness) * 2200)
    max_per_section = min(4500, base_section + int(bypass_count * 80))
    max_prompt = int(22000 + (1.0 - aggressiveness) * 12000)
    gemini_word_cap = int(900 + aggressiveness * 900)

    skip_gemini = False
    primary = regime.get('primary_regime', 'sideways')
    if volatility > 0.58 or disagree > 0.45:
        skip_gemini = True
    if primary in ('panic_volatile', 'macro_uncertainty', 'regime_transition'):
        skip_gemini = True
        gemini_word_cap = int(gemini_word_cap * 0.75)
    if volatility > 0.72 or disagree > 0.55:
        skip_gemini = True
        _log('REGIME SHIFT', 'Skipping Gemini compression — preserving detail for volatile/contradictory market')

    return {
        'compression_aggressiveness': aggressiveness,
        'max_per_section': max_per_section,
        'max_prompt_chars': max_prompt,
        'gemini_word_cap': gemini_word_cap,
        'skip_gemini': skip_gemini,
        'preserve_contradictions': True,
        'volatility_index': volatility,
        'disagreement_score': disagree,
    }


def adaptive_compress_sections(
    sections: Dict[str, str],
    profile: dict,
    scored: dict,
) -> Dict[str, str]:
    """Apply lighter compression to high-impact sections."""
    from backend.ai.token_optimizer import compress_section

    max_chars = int(profile.get('max_per_section') or 2800)
    bypass_kinds = {s.get('kind') for s in (scored.get('bypass_items') or [])}

    protected_sections = set()
    if 'govt' in bypass_kinds or profile.get('volatility_index', 0) > 0.5:
        protected_sections.add('govt')
    if 'scanner' in bypass_kinds or profile.get('disagreement_score', 0) > 0.35:
        protected_sections.add('scanner')
    if float(profile.get('news_shock_intensity') or 0) > 0.3:
        protected_sections.add('news')

    out = {}
    for name, body in sections.items():
        if not body:
            continue
        protected = name in protected_sections
        limit = section_char_limit(max_chars, name, protected=protected)
        out[name] = compress_section(str(body), limit)
    return out


# ── 6. Compression quality evaluation ─────────────────────────────────────────

def _compute_sentiment_diversity(all_data: Dict[str, Any]) -> Tuple[float, float]:
    """Return (sentiment_diversity_score, minority_signal_retention_score)."""
    buckets = {'bullish': 0, 'bearish': 0, 'neutral': 0}
    sources = 0

    for art in _safe_list(_safe_dict(all_data.get('news')).get('articles'))[:40]:
        b = _sentiment_bucket(_safe_dict(art).get('sentiment_label'))
        buckets[b] += 1
        sources += 1

    reddit = _safe_dict(all_data.get('reddit'))
    mood = _sentiment_bucket(_safe_dict(reddit.get('market_mood')).get('sentiment'))
    if mood != 'neutral':
        buckets[mood] += 2
        sources += 2

    for sig in _safe_list(_safe_dict(all_data.get('scanner')).get('top_signals'))[:12]:
        b = _sentiment_bucket(_safe_dict(sig).get('direction'))
        if b != 'neutral':
            buckets[b] += 1
            sources += 1

    active = sum(1 for v in buckets.values() if v > 0)
    diversity = _clamp(active / 3.0)
    if sources > 0:
        minority = min(buckets.values())
        majority = max(buckets.values())
        minority_retention = _clamp(minority / max(majority, 1) + (0.15 if active >= 2 else 0))
    else:
        minority_retention = 0.5
    return round(diversity, 3), round(minority_retention, 3)


def evaluate_compression_quality(
    raw_blob: str,
    compressed_blob: str,
    preservation: dict,
    all_data: Optional[Dict[str, Any]] = None,
) -> dict:
    raw_syms = extract_symbols(raw_blob or '')
    comp_syms = extract_symbols(compressed_blob or '')
    symbol_retention = len(raw_syms & comp_syms) / max(len(raw_syms), 1)

    contra_block = preservation.get('contradictions', {}).get('summary_block', '')
    contra_types = len(preservation.get('contradictions', {}).get('contradictions') or [])
    contra_in_output = sum(1 for line in (compressed_blob or '').splitlines() if 'CONTRADICTION' in line.upper())
    contradiction_retention = 1.0 if contra_types == 0 else _clamp(
        (contra_in_output + (1 if contra_block else 0)) / max(contra_types, 1)
    )

    def _sentiment_density(text: str) -> Tuple[int, int]:
        upper = (text or '').upper()
        bull = sum(upper.count(w) for w in ('BULLISH', 'BULL', 'BUY', 'UP', 'LONG'))
        bear = sum(upper.count(w) for w in ('BEARISH', 'BEAR', 'SELL', 'DOWN', 'SHORT', 'AVOID'))
        return bull, bear

    rb, rs = _sentiment_density(raw_blob)
    cb, cs = _sentiment_density(compressed_blob)
    if rb + rs == 0:
        sentiment_preservation = 1.0
    else:
        sentiment_preservation = _clamp(
            1.0 - (abs(rb - cb) + abs(rs - cs)) / max(rb + rs, 1)
        )

    raw_len = max(len(raw_blob or ''), 1)
    comp_len = len(compressed_blob or '')
    compression_ratio = round(comp_len / raw_len, 3)

    sentiment_diversity_score, minority_signal_retention_score = (0.5, 0.5)
    novelty_avg = 0.0
    repetition_suppressed = 0
    if all_data:
        sentiment_diversity_score, minority_signal_retention_score = _compute_sentiment_diversity(all_data)
        km = extract_key_metrics(all_data)
        novelty_avg = float(km.get('novelty_avg_score') or 0)
        repetition_suppressed = int(km.get('repetition_suppressed') or 0)

    regime = preservation.get('regime') or {}
    primary = regime.get('primary_regime', 'sideways')
    truncation_severity = round(_clamp(compression_ratio), 3)
    if primary in ('panic_volatile', 'macro_uncertainty', 'regime_transition') and compression_ratio < 0.35:
        truncation_severity = round(compression_ratio * 0.7, 3)

    raw_evidence_len = len(preservation.get('raw_evidence_block') or '')
    intelligence_quality = round(
        symbol_retention * 0.18
        + contradiction_retention * 0.26
        + sentiment_preservation * 0.20
        + sentiment_diversity_score * 0.12
        + minority_signal_retention_score * 0.10
        + (1.0 - _clamp(compression_ratio, 0, 1)) * 0.06
        + _clamp(raw_evidence_len / 2000, 0, 1) * 0.18,
        3,
    )

    metrics = {
        'information_retention_score': round(symbol_retention, 3),
        'contradiction_retention_score': round(contradiction_retention, 3),
        'sentiment_preservation_score': round(sentiment_preservation, 3),
        'sentiment_diversity_score': sentiment_diversity_score,
        'minority_signal_retention_score': minority_signal_retention_score,
        'truncation_severity': truncation_severity,
        'compression_ratio': compression_ratio,
        'intelligence_quality_score': intelligence_quality,
        'raw_evidence_chars': raw_evidence_len,
        'novelty_avg_score': round(novelty_avg, 3),
        'repetition_suppressed_count': repetition_suppressed,
        'primary_regime': primary,
    }

    _log(
        'QUALITY SCORE',
        f"IQ={intelligence_quality:.2f} info={symbol_retention:.2f} "
        f"contra={contradiction_retention:.2f} sentiment={sentiment_preservation:.2f} "
        f"ratio={compression_ratio:.2f}",
    )
    return metrics


# ── Assembly + safety ─────────────────────────────────────────────────────────

def should_block_stale_reuse(all_data: Dict[str, Any], state: dict) -> bool:
    """Prevent stale compressed context during volatile or contradictory regimes."""
    prev_regime = state.get('last_regime')
    regime_since = state.get('regime_since')
    contradictions = detect_contradictions(all_data)
    regime = detect_market_regime(
        all_data,
        contradictions,
        previous_regime=prev_regime,
        regime_since=regime_since,
    )

    if regime.get('regime_shift'):
        return True
    if float(regime.get('volatility_index') or 0) >= 0.58:
        _log('REGIME SHIFT', 'Blocking stale reuse — elevated volatility')
        return True
    if float(contradictions.get('overall_disagreement_score') or 0) >= 0.48:
        _log('CONTRADICTION DETECTED', 'Blocking stale reuse — high disagreement')
        return True
    if float(regime.get('news_shock_intensity') or 0) >= 0.45:
        _log('RAW SIGNAL PRESERVED', 'Blocking stale reuse — news shock detected')
        return True
    return False


def format_preservation_for_claude(
    raw_evidence: str,
    contradictions_block: str,
    regime_block: str,
    scored_block: str,
    compressed_summary: str,
) -> str:
    """Final Claude input — raw + structured preservation layers + compressed bulk."""
    parts = [
        raw_evidence,
        contradictions_block,
        regime_block,
        scored_block,
        '=== COMPRESSED MARKET CONTEXT (bulk sections) ===',
        compressed_summary,
        '',
        'INSTRUCTION: Preserve contradictions above — do NOT flatten opposing views. '
        'Weight RAW HIGH-IMPACT EVIDENCE heavily in opportunities, risks, and mood.',
    ]
    return '\n\n'.join(p for p in parts if p)


def build_preservation_layer(
    all_data: Dict[str, Any],
    previous_state: Optional[dict] = None,
) -> dict:
    """Full preservation package consumed by intelligence_compressor."""
    prev_regime = (previous_state or {}).get('last_regime')
    regime_since = (previous_state or {}).get('regime_since')
    contradictions = detect_contradictions(all_data)
    regime = detect_market_regime(
        all_data,
        contradictions,
        previous_regime=prev_regime,
        regime_since=regime_since,
    )
    scored = build_scored_signals(all_data, contradictions)
    raw_evidence = extract_raw_high_impact(all_data, scored)
    profile = build_compression_profile(regime, contradictions, scored)
    profile['news_shock_intensity'] = regime.get('news_shock_intensity', 0)

    return {
        'contradictions': contradictions,
        'regime': regime,
        'scored_signals': scored,
        'raw_evidence_block': raw_evidence,
        'compression_profile': profile,
        'contradictions_block': contradictions['summary_block'],
        'regime_block': regime['summary_block'],
        'scored_signals_block': scored['summary_block'],
    }
