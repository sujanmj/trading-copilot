"""
Novelty + repetition scoring — suppress low-value repetitive headlines (e.g. celebrity commentary).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Tuple

HIGH_IMPACT_KEYWORDS = (
    'sebi', 'rbi', 'budget', 'tariff', 'sanction', 'policy', 'rate cut', 'rate hike',
    'repo rate', 'crash', 'circuit', 'halt', 'emergency', 'war', 'inflation', 'cpi',
    'fii', 'dii', 'institutional', 'outflow', 'inflow', 'default', 'downgrade',
    'upgrade', 'fraud', 'probe', 'ban', 'subsidy', 'stimulus', 'geopolitical',
)


def _contains_high_impact(text: str) -> bool:
    lower = (text or '').lower()
    return any(kw in lower for kw in HIGH_IMPACT_KEYWORDS)

LOW_VALUE_PATTERNS = (
    r'jim cramer', r'celebrity', r'what to watch', r'market wrap', r'stock pick',
    r'wall street', r'dow jones today', r's&p 500 today', r'nasdaq today',
    r'yahoo finance', r'motley fool', r'cnbc\s', r'fox business',
    r'crypto bro', r'bitcoin price', r'elon musk tweet',
)

INDIA_RELEVANCE_KEYWORDS = (
    'nifty', 'sensex', 'bank nifty', 'nse', 'bse', 'india', 'rupee', 'inr',
    'sebi', 'rbi', 'mumbai', 'fii', 'dii', 'nifty50', 'midcap', 'smallcap',
)

ENTITY_RE = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b')


def _safe_dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _safe_list(v) -> list:
    return v if isinstance(v, list) else []


def _normalize_title(title: str) -> str:
    t = re.sub(r'[^\w\s]', ' ', (title or '').lower())
    return re.sub(r'\s+', ' ', t).strip()


def _is_low_value_chatter(title: str) -> bool:
    lower = (title or '').lower()
    return any(re.search(p, lower) for p in LOW_VALUE_PATTERNS)


def _india_relevance_boost(title: str) -> float:
    lower = (title or '').lower()
    hits = sum(1 for kw in INDIA_RELEVANCE_KEYWORDS if kw in lower)
    return min(0.35, hits * 0.08)


def extract_entities(title: str) -> List[str]:
    """Named entities / celebrity tokens for repetition dampening."""
    entities = []
    for m in ENTITY_RE.finditer(title or ''):
        name = m.group(1).strip().lower()
        if len(name) > 3 and name not in ('the', 'and', 'for', 'with', 'from', 'stock', 'market'):
            entities.append(name)
    return entities[:4]


def score_article_novelty(
    article: dict,
    *,
    title_counts: Counter,
    entity_counts: Counter,
    seen_normalized: set,
) -> Tuple[float, dict]:
    """Return (score 0-10, meta) with novelty + repetition penalties."""
    art = _safe_dict(article)
    title = str(art.get('title', '')).strip()
    norm = _normalize_title(title)
    meta = {'title': title[:80], 'suppressed': False, 'reason': ''}

    if not title:
        return 0.0, meta

    base = 4.0
    base += abs(float(art.get('sentiment_score') or 0)) * 2.5
    if _contains_high_impact(title):
        base += 2.5
    base += _india_relevance_boost(title)

    # Novelty — penalize near-duplicate titles
    if norm in seen_normalized:
        base -= 3.5
        meta['reason'] = 'duplicate_title'
    elif title_counts.get(norm, 0) >= 1:
        base -= 2.0 * title_counts[norm]
        meta['reason'] = 'repeated_title'

    # Entity repetition dampening (e.g. same celebrity name across headlines)
    for ent in extract_entities(title):
        freq = entity_counts.get(ent, 0)
        if freq >= 2:
            penalty = min(2.5, 0.6 * (freq - 1))
            base -= penalty
            meta['reason'] = meta['reason'] or f'entity_repeat:{ent}'

    if _is_low_value_chatter(title):
        base -= 2.5
        meta['reason'] = meta['reason'] or 'low_value_chatter'

    if base < 1.5:
        meta['suppressed'] = True

    return max(0.0, min(10.0, base)), meta


def rank_news_with_novelty(news: dict, limit: int = 12) -> Tuple[List[dict], dict]:
    """Rank news by novelty-adjusted score; return stats for observability."""
    articles = _safe_list(_safe_dict(news).get('articles'))
    title_counts: Counter = Counter()
    entity_counts: Counter = Counter()
    for art in articles:
        norm = _normalize_title(str(_safe_dict(art).get('title', '')))
        if norm:
            title_counts[norm] += 1
        for ent in extract_entities(str(_safe_dict(art).get('title', ''))):
            entity_counts[ent] += 1

    seen_normalized: set = set()
    scored: List[Tuple[float, dict, dict]] = []
    suppressed = 0

    for art in articles:
        score, meta = score_article_novelty(
            art,
            title_counts=title_counts,
            entity_counts=entity_counts,
            seen_normalized=seen_normalized,
        )
        if meta.get('suppressed') and not _contains_high_impact(str(_safe_dict(art).get('title', ''))):
            suppressed += 1
            continue
        norm = _normalize_title(str(_safe_dict(art).get('title', '')))
        if norm:
            seen_normalized.add(norm)
        enriched = dict(_safe_dict(art))
        enriched['_novelty_score'] = round(score, 2)
        enriched['_novelty_meta'] = meta
        scored.append((score, enriched, meta))

    scored.sort(key=lambda x: x[0], reverse=True)
    ranked = [item[1] for item in scored[:limit]]

    avg_novelty = round(sum(s[0] for s in scored[:limit]) / max(len(scored[:limit]), 1), 3) if scored else 0.0
    stats = {
        'articles_in': len(articles),
        'articles_ranked': len(ranked),
        'repetition_suppressed': suppressed,
        'avg_novelty_score': avg_novelty,
        'top_entity_repeats': entity_counts.most_common(5),
    }
    return ranked, stats


def select_diverse_raw_evidence(
    candidates: List[Tuple[float, str, str]],
    limit: int = 8,
) -> Tuple[List[str], dict]:
    """
    Pick diverse raw evidence lines.
    candidates: [(score, line, bucket)] where bucket is source category key.
    """
    selected: List[str] = []
    used_buckets: Counter = Counter()
    used_entities: Counter = Counter()
    suppressed = 0

    for score, line, bucket in sorted(candidates, key=lambda x: x[0], reverse=True):
        if len(selected) >= limit:
            break
        if used_buckets[bucket] >= 2:
            suppressed += 1
            continue
        ents = extract_entities(line)
        if any(used_entities[e] >= 2 for e in ents):
            suppressed += 1
            continue
        selected.append(line)
        used_buckets[bucket] += 1
        for e in ents:
            used_entities[e] += 1

    return selected, {'diversity_suppressed': suppressed, 'buckets_used': dict(used_buckets)}
