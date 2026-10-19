"""Daily, evidence-grounded reviews of resolved candidate outcomes.

Price outcomes remain authoritative. News retrieval and AI summaries are stored
as supporting research and are never treated as proof of causation.
"""

from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
AI_POSTMORTEMS_PER_RUN = 4
MAX_POSTMORTEM_ATTEMPTS = 3
_EVENT_OUTCOME_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _event_type(text: str) -> str:
    try:
        from backend.my_feed.entity_mapping import infer_event_type_from_text

        return str(infer_event_type_from_text(text) or 'GENERAL_NEWS').upper()
    except Exception:
        return 'GENERAL_NEWS'


def _base_record(snapshot: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any]:
    text = ' '.join(str(snapshot.get(k) or '') for k in (
        'news_headline', 'reason_text', 'risk_text', 'sector_theme', 'pattern_label',
    )).strip()
    session_date = str(snapshot.get('session_date') or outcome.get('session_date') or '')[:10]
    return {
        'snapshot_id': snapshot.get('snapshot_id'),
        'symbol': snapshot.get('symbol'),
        'session_date': session_date,
        'snapshot_at': snapshot.get('snapshot_at'),
        'stage': snapshot.get('stage'),
        'outcome': str(outcome.get('outcome') or '').upper(),
        'close_return_pct': outcome.get('close_return_pct'),
        'mfe_pct': outcome.get('max_favorable_excursion_pct'),
        'mae_pct': outcome.get('max_adverse_excursion_pct'),
        'event_type': _event_type(text),
        'event_text': text,
        'verification_status': snapshot.get('verification_status'),
        'macro_regime': snapshot.get('macro_regime'),
        'reason_tags': outcome.get('reason_tags') or [],
        'evidence_status': 'PENDING' if str(outcome.get('outcome') or '').upper() == 'LOSS' else 'COMPLETE',
        'context': {
            'score': snapshot.get('score'),
            'reference_price': snapshot.get('reference_price'),
            'reference_price_time': snapshot.get('reference_price_time'),
            'price_move_at_snapshot': snapshot.get('price_move_at_snapshot'),
            'volume_participation': snapshot.get('volume_participation'),
            'catalyst_status': snapshot.get('catalyst_status'),
            'matched_source': snapshot.get('matched_source'),
            'news_headline': snapshot.get('news_headline'),
            'news_source': snapshot.get('news_source'),
            'macro_regime': snapshot.get('macro_regime'),
            'sector_theme': snapshot.get('sector_theme'),
            'reason_text': snapshot.get('reason_text'),
            'risk_text': snapshot.get('risk_text'),
            'close_return_pct': outcome.get('close_return_pct'),
            'max_favorable_excursion_pct': outcome.get('max_favorable_excursion_pct'),
            'max_adverse_excursion_pct': outcome.get('max_adverse_excursion_pct'),
            'resolved_at': outcome.get('resolved_at'),
        },
    }


def _published_at(entry: Any) -> str | None:
    parsed = getattr(entry, 'published_parsed', None)
    if parsed:
        try:
            return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
        except (TypeError, ValueError):
            pass
    value = str(entry.get('published') or '').strip()
    if not value:
        return None
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _company_name(symbol: str) -> str:
    try:
        from backend.my_feed.entity_mapping import COMPANY_ALIAS_RULES

        for _pattern, ticker, name in COMPANY_ALIAS_RULES:
            if str(ticker).upper() == symbol:
                return str(name)
    except Exception:
        pass
    return symbol


def search_prediction_day_news(
    *, symbol: str,
    session_date: str,
    snapshot_at: str | None,
    cutoff_at: str | None = None,
    max_results: int = 8,
) -> list[dict[str, str]]:
    """Search Google News RSS and retain only timestamped, ticker-linked items."""
    import feedparser
    import requests

    name = _company_name(str(symbol or '').strip().upper())
    day = datetime.strptime(session_date[:10], '%Y-%m-%d').date()
    query = f'("{name}" OR "{symbol}") after:{day.isoformat()} before:{(day + timedelta(days=1)).isoformat()}'
    response = requests.get(
        'https://news.google.com/rss/search',
        params={'q': query, 'hl': 'en-IN', 'gl': 'IN', 'ceid': 'IN:en'},
        timeout=12,
        headers={'User-Agent': 'AstraEdge-EOD-Research/1.0'},
    )
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    start = None
    if snapshot_at:
        try:
            start = datetime.fromisoformat(str(snapshot_at).replace('Z', '+00:00'))
            if start.tzinfo is None:
                start = start.replace(tzinfo=IST)
            start = start.astimezone(timezone.utc)
        except ValueError:
            start = None
    end = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=IST).astimezone(timezone.utc)
    if cutoff_at:
        try:
            cutoff = datetime.fromisoformat(str(cutoff_at).replace('Z', '+00:00'))
            if cutoff.tzinfo is None:
                cutoff = cutoff.replace(tzinfo=IST)
            end = min(end, cutoff.astimezone(timezone.utc))
        except ValueError:
            pass

    records: list[dict[str, str]] = []
    seen: set[str] = set()
    ticker_norm = str(symbol or '').strip().upper()
    name_norm = name.casefold()
    for entry in getattr(feed, 'entries', []) or []:
        title = html.unescape(re.sub(r'<[^>]+>', ' ', str(entry.get('title') or ''))).strip()
        snippet = html.unescape(re.sub(r'<[^>]+>', ' ', str(entry.get('summary') or ''))).strip()
        url = str(entry.get('link') or '').strip()
        published = _published_at(entry)
        if not title or not url or not published or url in seen:
            continue
        try:
            published_dt = datetime.fromisoformat(published.replace('Z', '+00:00'))
        except ValueError:
            continue
        if start and published_dt < start.astimezone(timezone.utc):
            continue
        if published_dt > end:
            continue
        blob = f'{title} {snippet}'.casefold()
        if ticker_norm.casefold() not in blob and name_norm not in blob:
            continue
        seen.add(url)
        source = entry.get('source')
        if isinstance(source, dict):
            source_name = str(source.get('title') or 'Google News publisher')
        else:
            source_name = str(source or 'Google News publisher')
        records.append({
            'source_name': source_name[:160],
            'title': title[:500],
            'url': url[:2000],
            'published_at': published,
            'snippet': snippet[:1600],
        })
        if len(records) >= max_results:
            break
    return records


def _parse_ai_result(text: str) -> dict[str, Any]:
    body = str(text or '').strip()
    match = re.search(r'\{.*\}', body, flags=re.S)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {'cause_category': 'UNCLASSIFIED', 'summary': body[:1000], 'confidence': 0.45}


def _explain_loss(record: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    from backend.ai.ai_pool_router import OUTCOME_EXPLAINER_USE_CASE, execute_pooled_ai

    payload = {
        'prediction_context': record.get('context') or {},
        'outcome': record.get('outcome'),
        'event_type': record.get('event_type'),
        'reason_tags': record.get('reason_tags') or [],
        'dated_sources': evidence,
    }
    prompt = (
        'You are reviewing an already-resolved paper prediction. Price outcome is authoritative. '
        'Using only the supplied prediction context and dated source records, return JSON with '
        'cause_category, summary (at most 3 sentences), confidence (0 to 1), and evidence_urls '
        '(URLs selected from supplied records). Describe possible contributors, not proven causality. '
        'If evidence is weak or unrelated, say so. Never invent facts, headlines, prices, or URLs.\n'
        f'{json.dumps(payload, ensure_ascii=False, default=str)}'
    )
    result = execute_pooled_ai(
        prompt,
        use_case=OUTCOME_EXPLAINER_USE_CASE,
        max_tokens=360,
        allow_claude=False,
    )
    if not result.get('success') or not result.get('text'):
        return {'success': False, 'error': str(result.get('error') or 'provider unavailable')}
    parsed = _parse_ai_result(str(result.get('text')))
    return {
        'success': True,
        'cause_category': str(parsed.get('cause_category') or 'UNCLASSIFIED')[:80],
        'cause_summary': str(parsed.get('summary') or result.get('text') or '')[:1200],
        'confidence': max(0.0, min(1.0, float(parsed.get('confidence') or 0.5))),
        'model': str(result.get('model') or ''),
        'provider': str(result.get('provider_used') or result.get('provider') or ''),
    }


def process_candidate_postmortems(
    outcomes: list[dict[str, Any]],
    *,
    session_date: str,
    ai_limit: int = AI_POSTMORTEMS_PER_RUN,
) -> dict[str, int]:
    """Persist every resolved candidate and drain a bounded daily loss queue."""
    from backend.storage.prediction_postmortem_store import (
        get_pending_postmortems,
        update_postmortem_status,
        upsert_postmortem,
    )

    indexed_snapshots: dict[str, dict[str, Any]] = {}
    saved = 0
    for outcome in outcomes or []:
        if not isinstance(outcome, dict):
            continue
        snapshot_id = str(outcome.get('snapshot_id') or '').strip()
        symbol = str(outcome.get('symbol') or '').strip().upper()
        if not snapshot_id or not symbol:
            continue
        if str(outcome.get('outcome') or '').upper() not in {'WIN', 'LOSS', 'NEUTRAL'}:
            continue
        record = _base_record(outcome, outcome)
        # Resolver outcome rows include the original snapshot fields.
        indexed_snapshots[snapshot_id] = dict(outcome)
        evidence = outcome.get('evidence_records') if isinstance(outcome.get('evidence_records'), list) else []
        if str(outcome.get('outcome') or '').upper() == 'LOSS' and evidence and outcome.get('ai_explain_status') == 'OK':
            record.update({
                'evidence_status': 'COMPLETE',
                'cause_category': 'AI_REVIEW',
                'cause_summary': outcome.get('ai_reason_summary'),
                'explanation_confidence': outcome.get('explanation_confidence'),
                'model': outcome.get('model_used'),
                'provider': outcome.get('provider_used'),
                'attempts': 1,
            })
        upsert_postmortem(record, evidence)
        saved += 1

    result = {'saved': saved, 'processed': 0, 'completed': 0, 'pending': 0, 'errors': 0}
    pending = get_pending_postmortems(limit=max(0, int(ai_limit)))
    for row in pending:
        snapshot_id = str(row.get('snapshot_id') or '')
        attempts = int(row.get('attempts') or 0) + 1
        evidence = list(row.get('evidence') or [])
        try:
            if not evidence:
                evidence = search_prediction_day_news(
                    symbol=str(row.get('symbol') or ''),
                    session_date=str(row.get('session_date') or session_date),
                    snapshot_at=row.get('snapshot_at'),
                    cutoff_at=(row.get('context') or {}).get('resolved_at'),
                )
                base = {**row, 'evidence_status': 'PENDING', 'attempts': attempts}
                upsert_postmortem(base, evidence)
            if not evidence:
                final = attempts >= MAX_POSTMORTEM_ATTEMPTS
                update_postmortem_status(
                    snapshot_id,
                    status='NO_EVIDENCE' if final else 'PENDING',
                    attempts=attempts,
                    error=None if final else 'no dated ticker-specific articles found yet',
                )
                result['processed'] += 1
                result['pending' if not final else 'completed'] += 1
                continue

            context_record = {
                **row,
                'reason_tags': row.get('reason_tags') or [],
                'context': row.get('context') or {},
            }
            ai = _explain_loss(context_record, evidence)
            if ai.get('success'):
                update_postmortem_status(
                    snapshot_id,
                    status='COMPLETE',
                    attempts=attempts,
                    cause_category=ai.get('cause_category'),
                    cause_summary=ai.get('cause_summary'),
                    explanation_confidence=ai.get('confidence'),
                    model=ai.get('model'),
                    provider=ai.get('provider'),
                )
                result['completed'] += 1
            else:
                update_postmortem_status(
                    snapshot_id,
                    status='PENDING',
                    attempts=attempts,
                    error=ai.get('error'),
                )
                result['pending'] += 1
            result['processed'] += 1
        except Exception as exc:
            update_postmortem_status(
                snapshot_id,
                status='PENDING',
                attempts=attempts,
                error=f'{type(exc).__name__}: {exc}',
            )
            result['errors'] += 1
            result['pending'] += 1
    return result


def get_candidate_event_analogs(candidate: dict[str, Any], *, min_samples: int = 5) -> dict[str, Any]:
    """Return descriptive historical outcomes for a candidate's event type."""
    raw = candidate.get('raw_payload')
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    raw = raw if isinstance(raw, dict) else {}
    signal = candidate.get('signal_stack')
    if isinstance(signal, dict):
        raw_text = json.dumps(signal, ensure_ascii=False, default=str)
    else:
        raw_text = str(signal or '')
    text = ' '.join(str(v or '') for v in (
        candidate.get('catalyst_line'), candidate.get('news_headline'),
        candidate.get('reasoning'), candidate.get('reason_text'),
        raw.get('headline'), raw.get('news_headline'), raw.get('catalyst'),
        raw_text,
    )).strip()
    event_type = _event_type(text)
    if not text or event_type == 'GENERAL_NEWS':
        return {'available': False, 'reason': 'no_specific_event_type', 'event_type': event_type}
    cached = _EVENT_OUTCOME_CACHE.get(event_type)
    if cached and time.monotonic() - cached[0] < 300:
        rows = cached[1]
    else:
        from backend.storage.prediction_postmortem_store import get_event_outcomes

        rows = get_event_outcomes(event_type=event_type, limit=2000)
        _EVENT_OUTCOME_CACHE[event_type] = (time.monotonic(), rows)
    if len(rows) < min_samples:
        return {
            'available': False,
            'reason': 'low_sample',
            'event_type': event_type,
            'sample_count': len(rows),
            'minimum_sample_count': min_samples,
        }
    wins = sum(str(row.get('outcome') or '').upper() == 'WIN' for row in rows)
    losses = sum(str(row.get('outcome') or '').upper() == 'LOSS' for row in rows)
    moves = [float(row['close_return_pct']) for row in rows if row.get('close_return_pct') is not None]
    return {
        'available': True,
        'event_type': event_type,
        'sample_count': len(rows),
        'wins': wins,
        'losses': losses,
        'win_rate_pct': wins / len(rows) * 100.0,
        'mean_close_return_pct': sum(moves) / len(moves) if moves else None,
        'research_only': True,
    }


def get_postmortem_context_for_question(question: str, *, limit: int = 4) -> list[dict[str, Any]]:
    """Find ticker-specific saved postmortems referenced in an Ask AI question."""
    normalized = str(question or '').strip()
    if not normalized:
        return []
    symbols: list[str] = []
    try:
        from backend.my_feed.entity_mapping import map_entities_from_text

        mapped = map_entities_from_text(normalized)
        symbols = [str(value).upper() for value in mapped.get('tickers') or []]
    except Exception:
        pass
    if not symbols:
        symbols = [token for token in re.findall(r'(?<![A-Za-z0-9])[A-Z][A-Z0-9]{1,14}(?![A-Za-z0-9])', normalized)]
    if not symbols:
        return []
    from backend.storage.prediction_postmortem_store import get_postmortems

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for symbol in symbols[:3]:
        for row in get_postmortems(symbol=symbol, limit=limit):
            if row.get('snapshot_id') not in seen:
                rows.append(row)
                seen.add(str(row.get('snapshot_id') or ''))
    return rows[:limit]
