"""
Read-only tradecard evidence matrix and consensus scoring.

This module explains why a ticker is a watch, entry candidate, or rejection.
It does not refresh caches, place orders, or weaken tradecard safety gates.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.storage.data_paths import get_data_path
from backend.utils.config import DATA_DIR

IST = ZoneInfo('Asia/Kolkata')

MODULE_ORDER: tuple[str, ...] = (
    'scanner',
    'news',
    'my_feed',
    'broker',
    'budget',
    'theme',
    'global',
    'tv',
    'memory',
    'risk',
)

DIRECT_CATALYST_MODULES = frozenset({'news', 'my_feed', 'broker'})
POSITIVE_TERMS = (
    'order win', 'wins order', 'bagged order', 'work order', 'received order',
    'awarded contract', 'contract award', 'crore order', 'contract', 'approval', 'approved',
    'stake', 'investment', 'upgrade', 'target raised', 'target upgrade',
    'outperform', 'overweight', 'accumulate', 'result beat', 'profit rises',
    'capex', 'project', 'launch', 'bullish',
)

BULLISH_CATALYST_TYPES = frozenset({
    'ORDER_WIN', 'PROJECT_ANNOUNCEMENT', 'ACQUISITION', 'STAKE_BUY', 'AI_INVESTMENT',
    'REGULATORY_APPROVAL', 'BROKER_UPGRADE', 'TARGET_UPGRADE', 'DIVIDEND_BONUS_SPLIT',
})
NEGATIVE_TERMS = (
    'downgrade', 'target cut', 'target downgrade', 'underperform', 'underweight',
    'sell rating', 'probe', 'penalty', 'fine', 'falls', 'plunges', 'slumps',
    'fraud', 'ban', 'delay', 'regulatory risk', 'bearish', 'risk',
)
GLOBAL_RISK_TERMS = (
    'risk-off', 'risk off', 'war', 'selloff', 'crude spike', 'oil shock',
    'dollar spike', 'usd spike', 'weak global', 'global weakness', 'sanctions',
    'volatility spike',
)
GLOBAL_SUPPORT_TERMS = (
    'risk-on', 'risk on', 'global support', 'global markets firm', 'nifty support',
    'cooling crude', 'lower crude', 'dovish', 'liquidity support',
)


def _normalize_ticker(value: object) -> str:
    return re.sub(r'[^A-Z0-9&.-]', '', str(value or '').strip().upper())


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value in (None, ''):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: object) -> datetime | None:
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        if raw.endswith('Z'):
            raw = raw[:-1] + '+00:00'
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _age_label_from_dt(ts: datetime | None) -> str:
    if ts is None:
        return 'unknown'
    age_seconds = max(0, int((_now_utc() - ts.astimezone(timezone.utc)).total_seconds()))
    if age_seconds < 60:
        return f'{age_seconds}s'
    minutes = age_seconds // 60
    if minutes < 60:
        return f'{minutes}m'
    hours = minutes // 60
    if hours < 48:
        return f'{hours}h'
    return f'{hours // 24}d'


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}


def _source_payload(
    context: dict[str, Any],
    key: str,
    filename: str,
) -> tuple[Any, str, str]:
    if key in context:
        payload = context.get(key)
        return payload, f'context:{key}', _freshness_from_payload(payload, None)
    path = get_data_path(filename)
    payload = _read_json(path)
    return payload, str(path), _freshness_from_payload(payload, path)


def _freshness_from_payload(payload: Any, path: Path | None) -> str:
    if isinstance(payload, dict):
        explicit = payload.get('freshness_label') or payload.get('freshness')
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        for key in ('generated_at', 'refreshed_at', 'cache_refreshed_at', 'updated_at', 'timestamp'):
            ts = _parse_ts(payload.get(key))
            if ts is not None:
                return _age_label_from_dt(ts)
    if path is not None and path.is_file():
        try:
            return _age_label_from_dt(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc))
        except OSError:
            return 'unknown'
    return 'unknown'


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key in (
        'top_signals',
        'signals',
        'live_scanner',
        'items',
        'articles',
        'news',
        'priority_list',
        'bullish_watch',
        'avoid_list',
        'rows',
        'top_catalysts',
        'stock_rankings',
        'ranked_candidates',
        'top_setups',
        'predictions',
    ):
        value = payload.get(key)
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, dict))
    return rows


def _row_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        'ticker',
        'symbol',
        'name',
        'company',
        'headline',
        'title',
        'summary',
        'reason',
        'why',
        'note',
        'catalyst',
        'action',
        'stance',
        'priority',
        'side',
        'trade_status',
    ):
        value = row.get(key)
        if isinstance(value, (str, int, float)):
            parts.append(str(value))
    for key in ('catalyst_notes', 'notes', 'tickers', 'stocks', 'sectors', 'themes'):
        value = row.get(key)
        if isinstance(value, list):
            parts.extend(str(v) for v in value[:8])
    return ' '.join(parts)


def _matches_ticker(row: dict[str, Any], ticker: str, aliases: tuple[str, ...] = ()) -> bool:
    fields = (
        row.get('ticker'),
        row.get('symbol'),
        row.get('nse_symbol'),
        row.get('stock'),
        row.get('company_ticker'),
    )
    if any(_normalize_ticker(value) == ticker for value in fields):
        return True
    text = _row_text(row).upper()
    if re.search(rf'(?<![A-Z0-9]){re.escape(ticker)}(?![A-Z0-9])', text):
        return True
    return any(alias and alias.upper() in text for alias in aliases)


def _item(
    module: str,
    scope: str,
    verdict: str,
    weight: float,
    freshness: str,
    reason: str,
    *,
    ticker: str = '',
    tickers_matched: list[str] | None = None,
    sectors_matched: list[str] | None = None,
    source_path: str = '',
) -> dict[str, Any]:
    out = {
        'module': module,
        'scope': scope,
        'verdict': verdict,
        'weight': round(float(weight), 2),
        'freshness': freshness or 'unknown',
        'reason': str(reason or '').strip()[:240] or 'No detail available',
        'tickers_matched': tickers_matched if tickers_matched is not None else ([ticker] if ticker else []),
        'sectors_matched': sectors_matched if sectors_matched is not None else [],
    }
    if source_path:
        out['source_path'] = source_path
    return out


def _missing(module: str, reason: str, *, source_path: str = '') -> dict[str, Any]:
    return _item(module, 'no_data', 'neutral', 0, 'missing', reason, source_path=source_path)


def _scanner_evidence(ticker: str, context: dict[str, Any]) -> dict[str, Any]:
    payload, source, freshness = _source_payload(context, 'scanner', 'scanner_data.json')
    for row in _extract_rows(payload):
        if not _matches_ticker(row, ticker):
            continue
        direction = str(row.get('direction') or row.get('side') or '').upper()
        action = str(row.get('action') or row.get('entry_status') or row.get('status') or '').upper()
        reason = str(row.get('reason') or row.get('strength') or 'Live scanner price/volume row matched')
        if direction == 'BEARISH' or 'AVOID' in action or 'RISK' in action:
            return _item('scanner', 'risk', 'warn', -12, freshness, reason, ticker=ticker, source_path=source)
        change = _safe_float(row.get('change_percent') or row.get('change_pct'))
        volume = _safe_float(row.get('volume_ratio'), 1.0)
        detail = f'Price/volume confirmation; change {change:+.1f}%, volume {volume:.1f}x'
        return _item('scanner', 'direct', 'confirm', 20, freshness, detail, ticker=ticker, source_path=source)
    return _missing('scanner', 'No fresh scanner row for ticker; active entry not allowed without scanner confirmation', source_path=source)


def _direct_text_evidence(
    *,
    module: str,
    ticker: str,
    payload: Any,
    source: str,
    freshness: str,
    positive_weight: float,
    negative_weight: float,
    aliases: tuple[str, ...] = (),
) -> dict[str, Any]:
    matches = [row for row in _extract_rows(payload) if _matches_ticker(row, ticker, aliases)]
    if not matches:
        return _missing(module, f'No direct {module} item matched ticker', source_path=source)

    best = matches[0]
    text = _row_text(best)
    lower = text.lower()
    side = str(best.get('side') or best.get('catalyst_side') or '').upper()
    ctype = str(best.get('catalyst_type') or '').upper()
    verdict = 'neutral'
    weight = 0.0
    scope = 'direct'
    if side in ('BEARISH', 'RISK') or any(term in lower for term in NEGATIVE_TERMS):
        verdict = 'reject' if module in ('news', 'broker') else 'warn'
        weight = negative_weight
        scope = 'risk'
    elif (
        side == 'BULLISH'
        or ctype in BULLISH_CATALYST_TYPES
        or any(term in lower for term in POSITIVE_TERMS)
    ):
        verdict = 'confirm'
        weight = positive_weight
    reason = (
        str(best.get('headline') or best.get('title') or best.get('reason') or best.get('summary') or text)
        .replace('\n', ' ')
        .strip()
    )
    if verdict == 'neutral':
        reason = reason or f'{module} mentioned ticker without a clear confirm/reject signal'
    return _item(module, scope, verdict, weight, freshness, reason, ticker=ticker, source_path=source)


def _news_evidence(ticker: str, context: dict[str, Any], aliases: tuple[str, ...]) -> dict[str, Any]:
    if 'news' in context:
        payload, source, freshness = _source_payload(context, 'news', 'stock_catalyst_radar_latest.json')
        return _direct_text_evidence(
            module='news',
            ticker=ticker,
            payload=payload,
            source=source,
            freshness=freshness,
            positive_weight=15,
            negative_weight=-18,
            aliases=aliases,
        )

    paths = [
        get_data_path('stock_catalyst_radar_latest.json'),
        get_data_path('live_news_feed.json'),
        get_data_path('news_feed.json'),
        get_data_path('inshorts_feed.json'),
    ]
    combined: list[dict[str, Any]] = []
    source_parts: list[str] = []
    newest: datetime | None = None
    for path in paths:
        payload = _read_json(path)
        rows = _extract_rows(payload)
        if rows:
            combined.extend(rows)
            source_parts.append(str(path))
        if path.is_file():
            try:
                ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                newest = ts if newest is None or ts > newest else newest
            except OSError:
                pass
    return _direct_text_evidence(
        module='news',
        ticker=ticker,
        payload=combined,
        source=';'.join(source_parts) if source_parts else str(paths[0]),
        freshness=_age_label_from_dt(newest),
        positive_weight=15,
        negative_weight=-18,
        aliases=aliases,
    )


def _my_feed_evidence(ticker: str, context: dict[str, Any], aliases: tuple[str, ...]) -> dict[str, Any]:
    payload, source, freshness = _source_payload(context, 'my_feed', 'telegram_myfeed_cache.json')
    if not payload and 'feed' in context:
        payload, source, freshness = _source_payload(context, 'feed', 'telegram_myfeed_cache.json')
    return _direct_text_evidence(
        module='my_feed',
        ticker=ticker,
        payload=payload,
        source=source,
        freshness=freshness,
        positive_weight=15,
        negative_weight=-12,
        aliases=aliases,
    )


def _broker_evidence(ticker: str, context: dict[str, Any], aliases: tuple[str, ...]) -> dict[str, Any]:
    if 'broker' in context:
        payload, source, freshness = _source_payload(context, 'broker', 'broker_intelligence_cache.json')
    else:
        primary = get_data_path('broker_intelligence_cache.json')
        secondary = get_data_path('broker_app_collector_latest.json')
        p1 = _read_json(primary)
        p2 = _read_json(secondary)
        payload = _extract_rows(p1) + _extract_rows(p2)
        source = f'{primary};{secondary}'
        newest: datetime | None = None
        for path in (primary, secondary):
            if path.is_file():
                try:
                    ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                    newest = ts if newest is None or ts > newest else newest
                except OSError:
                    pass
        freshness = _age_label_from_dt(newest)
    return _direct_text_evidence(
        module='broker',
        ticker=ticker,
        payload=payload,
        source=source,
        freshness=freshness,
        positive_weight=10,
        negative_weight=-12,
        aliases=aliases,
    )


def _budget_evidence(ticker: str, context: dict[str, Any]) -> dict[str, Any]:
    payload, source, freshness = _source_payload(context, 'budget', 'budget_impact_cache.json')
    if not isinstance(payload, dict) or not payload:
        return _missing('budget', 'Budget cache unavailable', source_path=source)

    for row in _extract_rows(payload):
        if _matches_ticker(row, ticker):
            text = _row_text(row)
            if any(term in text.lower() for term in NEGATIVE_TERMS) or 'avoid' in text.lower():
                return _item('budget', 'risk', 'warn', -10, freshness, text[:180], ticker=ticker, source_path=source)
            return _item('budget', 'indirect', 'confirm', 8, freshness, text[:180] or 'Budget/theme ranking supports ticker', ticker=ticker, source_path=source)

    for key, label in (('beneficiary_map', 'budget beneficiary theme'), ('risk_map', 'budget risk theme')):
        value = payload.get(key)
        if not isinstance(value, dict):
            continue
        for theme_id, names in value.items():
            if isinstance(names, list) and ticker in {_normalize_ticker(v) for v in names}:
                if key == 'risk_map':
                    return _item('budget', 'risk', 'warn', -10, freshness, f'Budget risk map includes {ticker} in {theme_id}', ticker=ticker, sectors_matched=[str(theme_id)], source_path=source)
                return _item('budget', 'indirect', 'confirm', 7, freshness, f'{label}: {theme_id}', ticker=ticker, sectors_matched=[str(theme_id)], source_path=source)
    return _missing('budget', 'No budget/theme link found for ticker', source_path=source)


def _theme_evidence(ticker: str, context: dict[str, Any]) -> dict[str, Any]:
    payload, source, freshness = _source_payload(context, 'theme', 'theme_baskets.json')
    if not isinstance(payload, dict) or not payload:
        return _missing('theme', 'Theme basket cache unavailable', source_path=source)
    baskets = payload.get('baskets') if isinstance(payload.get('baskets'), list) else []
    for basket in baskets:
        if not isinstance(basket, dict):
            continue
        stocks = basket.get('stocks') or {}
        if not isinstance(stocks, dict):
            continue
        theme_id = str(basket.get('theme_id') or basket.get('display_name') or '')
        for bucket in ('avoid_or_risk', 'risk'):
            if ticker in {_normalize_ticker(v) for v in (stocks.get(bucket) or [])}:
                return _item('theme', 'risk', 'warn', -8, freshness, f'Theme risk basket: {theme_id}', ticker=ticker, sectors_matched=[theme_id], source_path=source)
        for bucket, weight in (('direct', 7), ('indirect', 5), ('raw_material', 4)):
            if ticker in {_normalize_ticker(v) for v in (stocks.get(bucket) or [])}:
                return _item('theme', 'indirect', 'confirm', weight, freshness, f'{bucket.replace("_", " ")} theme basket: {theme_id}', ticker=ticker, sectors_matched=[theme_id], source_path=source)
    return _missing('theme', 'Ticker not present in refreshed theme baskets', source_path=source)


def _global_evidence(context: dict[str, Any]) -> dict[str, Any]:
    payload, source, freshness = _source_payload(context, 'global', 'global_markets.json')
    text = _payload_text(payload).lower()
    if not text.strip():
        return _missing('global', 'Global/macro cache unavailable', source_path=source)
    risk_hits = [term for term in GLOBAL_RISK_TERMS if term in text]
    if risk_hits:
        penalty = -15 if len(risk_hits) >= 2 else -8
        return _item('global', 'risk', 'warn', penalty, freshness, f'Macro risk tone: {risk_hits[0]}', source_path=source)
    support_hits = [term for term in GLOBAL_SUPPORT_TERMS if term in text]
    if support_hits:
        return _item('global', 'indirect', 'confirm', 5, freshness, f'Macro support: {support_hits[0]}', source_path=source)
    return _item('global', 'risk', 'neutral', 0, freshness, 'Macro cache present; no clear risk/support signal', source_path=source)


def _tv_evidence(ticker: str, context: dict[str, Any], aliases: tuple[str, ...]) -> dict[str, Any]:
    payload, source, freshness = _source_payload(context, 'tv', 'tv_intelligence.json')
    match = _direct_text_evidence(
        module='tv',
        ticker=ticker,
        payload=payload,
        source=source,
        freshness=freshness,
        positive_weight=4,
        negative_weight=-4,
        aliases=aliases,
    )
    if match['scope'] == 'direct' and match['verdict'] == 'confirm':
        match['reason'] = 'Low-weight TV/narrative mention: ' + match['reason'][:180]
    return match


def _memory_evidence(ticker: str, context: dict[str, Any], aliases: tuple[str, ...]) -> dict[str, Any]:
    if 'memory' in context:
        payload, source, freshness = _source_payload(context, 'memory', 'confidence_calibration_report.json')
    else:
        paths = [get_data_path('confidence_calibration_report.json'), get_data_path('prediction_history.json')]
        payload = []
        newest: datetime | None = None
        for path in paths:
            data = _read_json(path)
            payload.extend(_extract_rows(data))
            if path.is_file():
                try:
                    ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                    newest = ts if newest is None or ts > newest else newest
                except OSError:
                    pass
        source = ';'.join(str(p) for p in paths)
        freshness = _age_label_from_dt(newest)
    row = _direct_text_evidence(
        module='memory',
        ticker=ticker,
        payload=payload,
        source=source,
        freshness=freshness,
        positive_weight=5,
        negative_weight=-6,
        aliases=aliases,
    )
    if row['scope'] == 'direct':
        row['scope'] = 'indirect'
        row['reason'] = 'Calibration/history support: ' + row['reason'][:180]
    return row


def _risk_evidence(ticker: str, context: dict[str, Any], current_items: list[dict[str, Any]]) -> dict[str, Any]:
    risk = context.get('risk') or context.get('avoid') or {}
    if isinstance(risk, dict):
        blocked = risk.get('blocked') or risk.get('avoid') or risk.get('tickers') or []
        if isinstance(blocked, str):
            blocked = [blocked]
        if ticker in {_normalize_ticker(v) for v in blocked} or bool(risk.get('hard_block')):
            reason = str(risk.get('reason') or risk.get('detail') or 'Avoid/risk filter triggered')
            return _item('risk', 'risk', 'block', -30, 'fresh', reason, ticker=ticker)
    elif isinstance(risk, list) and ticker in {_normalize_ticker(v) for v in risk}:
        return _item('risk', 'risk', 'block', -30, 'fresh', 'Avoid/risk filter includes ticker', ticker=ticker)

    return _item('risk', 'risk', 'neutral', 0, 'fresh', 'No hard avoid/risk filter found', ticker=ticker)


def _payload_text(payload: Any, *, limit: int = 8000) -> str:
    if isinstance(payload, dict):
        chunks = [_row_text(payload)]
        for value in payload.values():
            if isinstance(value, (dict, list)):
                chunks.append(_payload_text(value, limit=limit))
        return ' '.join(chunks)[:limit]
    if isinstance(payload, list):
        return ' '.join(_payload_text(v, limit=limit) for v in payload[:40])[:limit]
    if isinstance(payload, (str, int, float)):
        return str(payload)
    return ''


def _freshness_multiplier(freshness: object) -> float:
    text = str(freshness or '').lower()
    if not text or 'missing' in text or 'unavailable' in text:
        return 0.0
    if 'stale' in text:
        return 0.25
    match = re.search(r'(\d+(?:\.\d+)?)\s*([smhd])', text)
    if not match:
        return 1.0
    value = float(match.group(1))
    unit = match.group(2)
    hours = value / 3600 if unit == 's' else value / 60 if unit == 'm' else value if unit == 'h' else value * 24
    if hours > 48:
        return 0.25
    if hours > 24:
        return 0.5
    return 1.0


def _market_mode(context: dict[str, Any]) -> str:
    mode = str(context.get('market_mode') or context.get('mode') or '').strip().upper()
    if mode:
        return mode
    try:
        from backend.telegram.india_mode_lock import resolve_telegram_market_phase

        return str(resolve_telegram_market_phase() or '').strip().upper() or 'RESEARCH'
    except Exception:
        return 'RESEARCH'


def _is_live_mode(mode: str) -> bool:
    return mode in {'LIVE', 'INDIA_MARKET_HOURS', 'MARKET_HOURS'}


def _is_closed_mode(mode: str) -> bool:
    return any(token in mode for token in ('AFTER', 'WEEKEND', 'CLOSED', 'RESEARCH', 'POSTMARKET'))


def _score_items(items: list[dict[str, Any]]) -> float:
    score = 50.0
    for item in items:
        weight = _safe_float(item.get('weight'))
        if weight > 0:
            weight *= _freshness_multiplier(item.get('freshness'))
        score += weight
    return max(0.0, min(100.0, score))


def _decision(
    *,
    score: float,
    scanner_confirmed: bool,
    direct_catalyst: bool,
    hard_block: bool,
    mode: str,
    live_trigger: bool,
) -> tuple[str, str, float]:
    adjusted = score
    if hard_block:
        return 'AVOID / BLOCKED', 'Hard risk/avoid filter blocks active entry.', min(score, 35.0)
    if not scanner_confirmed:
        adjusted = min(adjusted, 55.0)
        if direct_catalyst:
            return 'RESEARCH WATCH ONLY', 'Direct catalyst exists, but scanner has not confirmed price/volume.', adjusted
        return 'NO TRADE / REJECTED', 'Selection requires scanner confirmation or a direct catalyst; neither is present.', min(adjusted, 49.0)
    if _is_closed_mode(mode):
        if direct_catalyst and adjusted >= 65:
            return 'NEXT-SESSION WATCH ONLY', 'Market is closed; wait for fresh price and volume confirmation next session.', min(adjusted, 79.0)
        return 'MOMENTUM-ONLY WATCH', 'Scanner confirms momentum, but market is closed or catalyst support is limited.', min(adjusted, 72.0)
    if score >= 75 and direct_catalyst:
        if _is_live_mode(mode) and live_trigger:
            return 'VALID_ENTRY', 'Scanner, catalyst, and risk checks align; still paper-only/manual.', score
        return 'HIGH CONVICTION WATCH', 'Scanner plus direct catalyst align; wait for live trigger confirmation.', score
    if scanner_confirmed and not direct_catalyst and score >= 60:
        return 'MOMENTUM-ONLY WATCH', 'Scanner confirms price/volume, but no fresh direct catalyst was found.', min(score, 72.0)
    if score >= 65:
        return 'WATCH FOR ENTRY', 'Evidence is supportive, but trigger confirmation is still required.', score
    if score >= 50:
        return 'RESEARCH WATCH', 'Evidence is mixed or incomplete; research-only watch.', score
    return 'NO TRADE / REJECTED', 'Evidence is too weak or contradictory for an active watch.', score


def _confidence(score: float, direct_count: int, risk_count: int) -> str:
    if score >= 80 and direct_count >= 2 and risk_count == 0:
        return 'HIGH'
    if score >= 65:
        return 'MEDIUM'
    return 'LOW'


def build_tradecard_evidence_matrix(ticker: object, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Build a structured evidence matrix for a ticker.

    The function is read-only. The optional context is for tests and callers that
    already have payloads in memory.
    """
    sym = _normalize_ticker(ticker)
    ctx = context if isinstance(context, dict) else {}
    aliases = tuple(str(v).strip() for v in (ctx.get('aliases') or ctx.get('company_aliases') or []) if str(v).strip())

    if not sym:
        return {
            'ticker': '',
            'evidence_items': [],
            'direct_confirms': [],
            'indirect_confirms': [],
            'risk_filters': [],
            'missing_modules': [],
            'consensus_score': 0,
            'confidence': 'LOW',
            'decision': 'NO TRADE / REJECTED',
            'final_reason': 'No ticker supplied for evidence matrix.',
            'market_mode': _market_mode(ctx),
        }

    explicit_items = ctx.get('evidence_items')
    if isinstance(explicit_items, list):
        items = [dict(row) for row in explicit_items if isinstance(row, dict)]
    else:
        items = [
            _scanner_evidence(sym, ctx),
            _news_evidence(sym, ctx, aliases),
            _my_feed_evidence(sym, ctx, aliases),
            _broker_evidence(sym, ctx, aliases),
            _budget_evidence(sym, ctx),
            _theme_evidence(sym, ctx),
            _global_evidence(ctx),
            _tv_evidence(sym, ctx, aliases),
            _memory_evidence(sym, ctx, aliases),
        ]
        items.append(_risk_evidence(sym, ctx, items))

    present = {str(item.get('module') or '').strip() for item in items}
    for module in MODULE_ORDER:
        if module not in present:
            items.append(_missing(module, f'{module} evidence not available'))

    scanner_confirmed = any(item.get('module') == 'scanner' and item.get('scope') == 'direct' and item.get('verdict') == 'confirm' for item in items)
    direct_catalyst = any(item.get('module') in DIRECT_CATALYST_MODULES and item.get('scope') == 'direct' and item.get('verdict') == 'confirm' for item in items)
    hard_block = any(item.get('verdict') == 'block' for item in items)
    score = _score_items(items)
    mode = _market_mode(ctx)
    live_trigger = bool(ctx.get('live_trigger') or str((ctx.get('card') or {}).get('status') or '').upper() == 'VALID_ENTRY')
    decision, reason, score = _decision(
        score=score,
        scanner_confirmed=scanner_confirmed,
        direct_catalyst=direct_catalyst,
        hard_block=hard_block,
        mode=mode,
        live_trigger=live_trigger,
    )

    direct_confirms = [i for i in items if i.get('scope') == 'direct' and i.get('verdict') == 'confirm']
    indirect_confirms = [i for i in items if i.get('scope') == 'indirect' and i.get('verdict') == 'confirm']
    risk_filters = [i for i in items if i.get('scope') == 'risk' or i.get('verdict') in ('warn', 'reject', 'block')]
    missing_modules = [i for i in items if i.get('scope') == 'no_data' or i.get('verdict') == 'neutral' and i.get('weight') == 0]

    return {
        'ticker': sym,
        'evidence_items': items,
        'direct_confirms': direct_confirms,
        'indirect_confirms': indirect_confirms,
        'risk_filters': risk_filters,
        'missing_modules': missing_modules,
        'consensus_score': int(round(score)),
        'confidence': _confidence(score, len(direct_confirms), len([i for i in risk_filters if i.get('verdict') != 'neutral'])),
        'decision': decision,
        'final_reason': reason,
        'market_mode': mode,
        'selection_basis_ok': scanner_confirmed or direct_catalyst,
        'scanner_confirmed': scanner_confirmed,
        'direct_catalyst_confirmed': direct_catalyst,
    }


def _safe_html(value: object) -> str:
    text = str(value or '')
    text = re.sub(r'\bbuy\b', 'entry', text, flags=re.IGNORECASE)
    text = re.sub(r'\bsell\b', 'avoid', text, flags=re.IGNORECASE)
    return html.escape(text, quote=False)


def _signed_weight(value: object) -> str:
    weight = _safe_float(value)
    if weight > 0:
        return f'+{weight:g}'
    if weight < 0:
        return f'{weight:g}'
    return '0'


def _format_item(item: dict[str, Any]) -> str:
    module = _safe_html(str(item.get('module') or '').replace('_', ' ').title())
    verdict = _safe_html(str(item.get('verdict') or 'neutral'))
    freshness = _safe_html(item.get('freshness') or 'unknown')
    reason = _safe_html(item.get('reason') or '')
    return f'- {module}: {verdict} ({_signed_weight(item.get("weight"))}) [{freshness}] - {reason}'


def _format_group(title: str, rows: list[dict[str, Any]], *, limit: int, empty: str) -> list[str]:
    lines = [title]
    if not rows:
        lines.append(f'- {empty}')
        return lines
    for item in rows[:limit]:
        lines.append(_format_item(item))
    if len(rows) > limit:
        lines.append(f'- plus {len(rows) - limit} more')
    return lines


def format_tradecard_evidence_matrix_telegram(matrix: dict[str, Any], *, compact: bool = False) -> str:
    """Format a matrix for Telegram. Compact mode is safe for regular /tradecard."""
    ticker = _safe_html(matrix.get('ticker') or '')
    score = int(matrix.get('consensus_score') or 0)
    decision = _safe_html(matrix.get('decision') or 'NO TRADE / REJECTED')
    confidence = _safe_html(matrix.get('confidence') or 'LOW')
    mode = _safe_html(matrix.get('market_mode') or 'RESEARCH')
    reason = _safe_html(matrix.get('final_reason') or '')

    if compact:
        direct = matrix.get('direct_confirms') or []
        indirect = matrix.get('indirect_confirms') or []
        risks = [r for r in (matrix.get('risk_filters') or []) if r.get('verdict') != 'neutral']
        missing = matrix.get('missing_modules') or []
        direct_labels = ', '.join(str(r.get('module') or '') for r in direct[:3]) or 'none'
        indirect_labels = ', '.join(str(r.get('module') or '') for r in indirect[:3]) or 'none'
        risk_label = '; '.join(str(r.get('reason') or '')[:70] for r in risks[:2]) or 'clear'
        missing_labels = ', '.join(str(r.get('module') or '') for r in missing[:4]) or 'none'
        lines = [
            '',
            '<b>Evidence Matrix</b>',
            f'Consensus: <b>{score}</b> | Confidence: <b>{confidence}</b> | Decision: <code>{decision}</code>',
            f'Direct confirms: {_safe_html(direct_labels)}',
            f'Indirect confirms: {_safe_html(indirect_labels)}',
            f'Risk filters: {_safe_html(risk_label)}',
            f'Missing/no-data: {_safe_html(missing_labels)}',
            f'Final reason: {reason}',
            f'Use /tradecard explain {ticker} for full evidence.',
        ]
        return '\n'.join(lines)

    lines = [
        f'<b>Evidence Matrix - {ticker}</b>',
        f'Consensus score: <b>{score}</b>',
        f'Confidence: <b>{confidence}</b>',
        f'Decision: <code>{decision}</code>',
        f'Mode: <code>{mode}</code>',
        '',
    ]
    lines.extend(_format_group('Direct confirms:', matrix.get('direct_confirms') or [], limit=6, empty='No direct stock confirmation.'))
    lines.append('')
    lines.extend(_format_group('Indirect confirms:', matrix.get('indirect_confirms') or [], limit=6, empty='No sector/theme support found.'))
    lines.append('')
    lines.extend(_format_group('Risk filters / contradictions:', matrix.get('risk_filters') or [], limit=6, empty='No hard risk filter found.'))
    lines.append('')
    lines.extend(_format_group('Missing/no-data modules:', matrix.get('missing_modules') or [], limit=8, empty='None.'))
    lines.extend([
        '',
        '<b>Final explanation</b>',
        reason,
        'No blind entry. Confirm fresh price plus volume before any paper action.',
        'Paper only.',
    ])
    return '\n'.join(lines)


def format_tradecard_evidence_explain(ticker: object, context: dict[str, Any] | None = None) -> str:
    matrix = build_tradecard_evidence_matrix(ticker, context=context)
    return format_tradecard_evidence_matrix_telegram(matrix, compact=False)
