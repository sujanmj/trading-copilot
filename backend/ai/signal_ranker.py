"""Rank and filter high-value signals before synthesis."""

from typing import Any, Dict, List


def _safe_dict(v):
    return v if isinstance(v, dict) else {}


def _safe_list(v):
    return v if isinstance(v, list) else []


def rank_scanner_signals(scanner: dict, limit: int = 12) -> List[dict]:
    signals = _safe_list(_safe_dict(scanner).get('top_signals'))
    strength_order = {'ULTRA': 4, 'STRONG': 3, 'MODERATE': 2, 'WEAK': 1}

    def score(s):
        s = _safe_dict(s)
        base = strength_order.get(str(s.get('strength', '')).upper(), 0)
        vol = float(s.get('volume_ratio') or 0)
        chg = abs(float(s.get('change_percent') or 0))
        return (base * 100) + (vol * 10) + chg

    ranked = sorted(signals, key=score, reverse=True)
    return ranked[:limit]


def rank_govt_items(govt: dict, limit: int = 6) -> List[dict]:
    items = _safe_list(_safe_dict(govt).get('high_impact_items'))
    return sorted(
        items,
        key=lambda i: float(_safe_dict(i).get('impact_score') or 0),
        reverse=True,
    )[:limit]


def rank_news_articles(news: dict, limit: int = 12) -> List[dict]:
    articles = _safe_list(_safe_dict(news).get('articles'))
    return articles[:limit]


def rank_reddit_tickers(reddit: dict, limit: int = 8) -> List[dict]:
    tickers = _safe_list(_safe_dict(reddit).get('trending_tickers'))
    return sorted(
        tickers,
        key=lambda t: int(_safe_dict(t).get('mentions') or 0),
        reverse=True,
    )[:limit]


def extract_key_metrics(all_data: Dict[str, Any]) -> Dict[str, Any]:
    """Compact metrics for change detection."""
    india = _safe_dict(all_data.get('india_markets'))
    prices = _safe_dict(india.get('prices'))
    avg_change = 0.0
    if prices:
        changes = [float(_safe_dict(p).get('change_percent') or 0) for p in prices.values()]
        avg_change = sum(changes) / len(changes) if changes else 0.0

    scanner = _safe_dict(all_data.get('scanner'))
    top_signals = rank_scanner_signals(scanner, limit=5)
    signal_tickers = [str(_safe_dict(s).get('ticker', '')) for s in top_signals]

    news = _safe_dict(all_data.get('news'))
    govt = _safe_dict(all_data.get('govt'))
    reddit = _safe_dict(all_data.get('reddit'))
    mood = _safe_dict(reddit.get('market_mood'))

    return {
        'india_avg_change': round(avg_change, 3),
        'news_count': int(news.get('total_articles') or len(_safe_list(news.get('articles')))),
        'govt_high_impact': int(govt.get('high_impact_count') or 0),
        'scanner_signals': int(scanner.get('total_signals') or 0),
        'top_scanner_tickers': signal_tickers,
        'reddit_sentiment': str(mood.get('sentiment', 'unknown')),
        'reddit_confidence': int(mood.get('confidence') or 0),
    }


def format_ranked_summary(all_data: Dict[str, Any]) -> str:
    """Human-readable ranked highlights for compression."""
    lines = ['=== RANKED SIGNALS ===']

    for s in rank_scanner_signals(_safe_dict(all_data.get('scanner'))):
        s = _safe_dict(s)
        lines.append(
            f"SCANNER [{s.get('strength','?')}] {s.get('ticker','?')} "
            f"{s.get('change_percent',0):+.1f}% vol:{s.get('volume_ratio',0):.1f}x"
        )

    for g in rank_govt_items(_safe_dict(all_data.get('govt'))):
        g = _safe_dict(g)
        headline = str(g.get('english_headline', g.get('title', '')))[:100]
        lines.append(f"GOVT [{g.get('impact_score',0)}] {headline}")

    for a in rank_news_articles(_safe_dict(all_data.get('news')), limit=8):
        a = _safe_dict(a)
        lines.append(f"NEWS [{str(a.get('sentiment_label','?'))[:3]}] {str(a.get('title',''))[:90]}")

    for t in rank_reddit_tickers(_safe_dict(all_data.get('reddit'))):
        t = _safe_dict(t)
        lines.append(f"REDDIT {t.get('ticker','?')} mentions:{t.get('mentions',0)}")

    return '\n'.join(lines)
