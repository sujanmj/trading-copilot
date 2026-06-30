"""
Daily Report Pack — shadow-only aggregated local intelligence summary.

Combines market router, freshness, final confidence, watchlist, broker,
historical learning/simulation, and calibration into one JSON pack.
Does not place trades or send Telegram.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.utils.config import DATA_DIR

try:
    from backend.analytics.actual_learning_resolver import LEARNING_PACK_VERSION
except Exception:
    LEARNING_PACK_VERSION = '4A3_price_bridge'

SHADOW_MODE = True
DISCLAIMER = 'Shadow analysis only — not trade execution.'

LATEST_PATH = DATA_DIR / 'daily_report_pack_latest.json'
HISTORY_PATH = DATA_DIR / 'daily_report_pack_history.jsonl'

FILE_PATHS = {
    'final_confidence': DATA_DIR / 'final_confidence_report.json',
    'tomorrow_watchlist': DATA_DIR / 'tomorrow_watchlist_report.json',
    'calibration': DATA_DIR / 'confidence_calibration_report.json',
}

SECRET_PATTERN = re.compile(
    r'(api[_-]?key|secret|password|token|bearer\s+[a-z0-9._-]+)',
    re.IGNORECASE,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _relative_data_path(path: Path) -> str:
    try:
        return str(path.relative_to(DATA_DIR.parent)).replace('\\', '/')
    except ValueError:
        return str(path).replace('\\', '/')


def _compact_final_confidence(report: dict[str, Any] | None) -> dict[str, Any]:
    if not report or report.get('ok') is not True:
        return {'ok': False, 'error': 'final confidence report unavailable'}
    summary = report.get('summary') or {}
    return {
        'ok': True,
        'active_mode': report.get('active_mode'),
        'market_closed': report.get('market_closed'),
        'buy_cap_active': report.get('buy_cap_active'),
        'checked': summary.get('checked', 0),
        'buy_candidate': summary.get('buy_candidate', 0),
        'watch': summary.get('watch', 0),
        'avoid': summary.get('avoid', 0),
        'no_decision': summary.get('no_decision', 0),
        'calibration': report.get('calibration') or {},
        'simulation': report.get('simulation') or {},
        'top_tickers': [
            row.get('ticker')
            for row in (report.get('top_candidates') or [])[:5]
            if row.get('ticker')
        ],
    }


def _compact_watchlist(report: dict[str, Any] | None) -> dict[str, Any]:
    if not report or report.get('ok') is not True:
        return {'ok': False, 'error': 'tomorrow watchlist unavailable'}
    summary = report.get('summary') or {}
    return {
        'ok': True,
        'market_mode': report.get('market_mode'),
        'watch': summary.get('watch', 0),
        'avoid': summary.get('avoid', 0),
        'no_decision': summary.get('no_decision', 0),
        'raw_candidates': summary.get('raw_candidates', 0),
        'unique_tickers': summary.get('unique_tickers', 0),
        'duplicates_removed': summary.get('duplicates_removed', 0),
        'top_watchlist': (report.get('top_watchlist') or [])[:10],
        'risk_notes': report.get('risk_notes') or [],
    }


def _compact_calibration(report: dict[str, Any] | None) -> dict[str, Any]:
    if not report or report.get('ok') is not True:
        return {'ok': False, 'error': 'calibration report unavailable'}
    summary = report.get('summary') or {}
    return {
        'ok': True,
        'live_resolved': summary.get('live_resolved', 0),
        'historical_resolved': summary.get('historical_resolved', 0),
        'recommendations': len(report.get('recommendations') or []),
        'overconfident_buckets': summary.get('overconfident_buckets', 0),
        'underconfident_buckets': summary.get('underconfident_buckets', 0),
        'warnings': report.get('warnings') or [],
    }


def _compact_broker(dashboard: dict[str, Any] | None) -> dict[str, Any]:
    if not dashboard or dashboard.get('ok') is not True:
        return {'ok': False, 'error': 'broker intelligence unavailable'}
    stats = dashboard.get('stats') or {}
    return {
        'ok': True,
        'broker_predictions': stats.get('broker_predictions', 0),
        'sources': stats.get('sources', 0),
        'tickers': stats.get('tickers', 0),
        'conflicts': stats.get('conflicts', 0),
        'agreements': stats.get('agreements', 0),
        'warnings': dashboard.get('warnings') or [],
    }


def _compact_external_source_coverage(coverage: dict[str, Any] | None) -> dict[str, Any]:
    if not coverage or coverage.get('ok') is not True:
        return {'ok': False, 'error': 'external source coverage unavailable'}
    ext = coverage.get('external_evidence') if isinstance(coverage.get('external_evidence'), dict) else {}
    return {
        'ok': True,
        'collected_items': coverage.get('collected_items', 0),
        'source_count': coverage.get('source_count', 0),
        'unique_tickers': coverage.get('unique_tickers', 0),
        'broker_db_pick_count': coverage.get('broker_db_pick_count', 0),
        'latest_sources': (coverage.get('latest_sources') or [])[:8],
        'broker_prediction_candidate': ext.get('broker_prediction_candidate', 0),
        'stock_news_evidence': ext.get('stock_news_evidence', 0),
        'market_context': ext.get('market_context', 0),
        'macro_context': ext.get('macro_context', 0),
        'external_evidence_accepted': ext.get('accepted', 0),
        'warnings': coverage.get('warnings') or [],
        'disclaimer': coverage.get('disclaimer') or 'External evidence is separated from our final prediction.',
    }


def _compact_broker_write_review(review: dict[str, Any] | None) -> dict[str, Any]:
    if not review or review.get('ok') is not True:
        return {'ok': False, 'error': 'broker write review unavailable'}
    summary = review.get('summary') if isinstance(review.get('summary'), dict) else {}
    return {
        'ok': True,
        'generated_at': review.get('generated_at'),
        'write_safe': summary.get('write_safe', 0),
        'review_only': summary.get('review_only', 0),
        'rejected': summary.get('rejected', 0),
        'duplicates': summary.get('duplicates', 0),
        'total_candidates': summary.get('total_candidates', 0),
        'disclaimer': 'Only write-safe items can enter broker prediction memory.',
    }


def _compact_external_evidence_adapter() -> dict[str, Any]:
    """Read-only external evidence summary via adapter (no broker DB writes)."""
    try:
        from backend.analytics.external_evidence_adapter import (
            get_external_evidence_summary,
            get_market_context_summary,
        )

        summary = get_external_evidence_summary()
        context = get_market_context_summary(limit=8)
        if summary.get('ok') is not True:
            return {'ok': False, 'error': summary.get('error') or 'external evidence unavailable'}

        top_stock: list[dict[str, Any]] = []
        try:
            from backend.collectors.broker_app_collector import get_external_evidence_dashboard

            dashboard = get_external_evidence_dashboard()
            for row in dashboard.get('stock_news') or []:
                if not isinstance(row, dict):
                    continue
                top_stock.append({
                    'ticker': row.get('ticker'),
                    'direction': row.get('direction'),
                    'title': (row.get('title') or '')[:120],
                    'source': row.get('source'),
                })
                if len(top_stock) >= 8:
                    break
        except Exception:
            pass

        return {
            'ok': True,
            'summary': summary,
            'market_context_count': int(context.get('market_context_count') or 0),
            'macro_context_count': int(context.get('macro_context_count') or 0),
            'context_warnings': context.get('warnings') or [],
            'context_items': (context.get('items') or [])[:8],
            'top_stock_evidence': top_stock[:8],
            'direction_counts': summary.get('direction_counts') or {},
            'disclaimer': summary.get('disclaimer') or 'External evidence is read-only and not trade execution.',
            'sample_ticker_fn': 'get_ticker_external_evidence',
        }
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}


def _compact_external_evidence(dashboard: dict[str, Any] | None) -> dict[str, Any]:
    if not dashboard or dashboard.get('ok') is not True:
        return {'ok': False, 'error': 'external evidence unavailable'}
    summary = dashboard.get('summary') if isinstance(dashboard.get('summary'), dict) else {}
    top_items: list[dict[str, Any]] = []
    for bucket in ('broker_candidates', 'stock_news', 'market_context_items', 'macro_context_items'):
        for row in dashboard.get(bucket) or []:
            if not isinstance(row, dict):
                continue
            top_items.append({
                'classification': row.get('classification') or bucket,
                'ticker': row.get('ticker'),
                'direction': row.get('direction'),
                'title': (row.get('title') or '')[:120],
                'source': row.get('source'),
            })
            if len(top_items) >= 12:
                break
        if len(top_items) >= 12:
            break
    return {
        'ok': True,
        'accepted': summary.get('accepted', 0),
        'broker_prediction_candidate': summary.get('broker_prediction_candidate', 0),
        'stock_news_evidence': summary.get('stock_news_evidence', 0),
        'market_context': summary.get('market_context', 0),
        'macro_context': summary.get('macro_context', 0),
        'rejected': summary.get('rejected', 0),
        'top_evidence_items': top_items[:12],
        'disclaimer': dashboard.get('disclaimer') or 'External evidence is separated from our final prediction.',
    }


def _compact_historical_learning(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not summary:
        return {'ok': False, 'error': 'historical learning unavailable'}
    stats = summary.get('stats') or {}
    overall = summary.get('overall') or {}
    return {
        'ok': True,
        'price_rows': stats.get('historical_prices', summary.get('price_row_count', 0)),
        'replay_rows': stats.get('historical_outcome_replay', 0),
        'win_rate': overall.get('win_rate'),
        'warnings': overall.get('warnings') or [],
        'simulation': summary.get('simulation') or {},
    }


def _compact_simulation(dashboard: dict[str, Any] | None) -> dict[str, Any]:
    if not dashboard:
        dashboard = {}
    sim = dashboard.get('simulation') if isinstance(dashboard.get('simulation'), dict) else dashboard
    if not sim:
        try:
            from backend.analytics.historical_prediction_simulator import get_simulation_dashboard

            sim_payload = get_simulation_dashboard()
            sim = sim_payload.get('simulation') or {}
        except Exception:
            sim = {}
    stats = sim.get('stats') or sim
    return {
        'ok': True,
        'simulation_runs': stats.get('simulation_runs', 0),
        'simulated_predictions': stats.get('simulated_predictions', 0),
        'simulated_outcomes': stats.get('simulated_outcomes', 0),
        'sim_win_rate': stats.get('sim_win_rate'),
        'strategy_count': len(sim.get('strategies') or stats.get('strategies') or []),
    }


def _collect_risk_notes(sections: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    seen: set[str] = set()

    def add(note: str) -> None:
        text = str(note or '').strip()
        if not text or text in seen:
            return
        seen.add(text)
        notes.append(text)

    add(DISCLAIMER)

    router = sections.get('market_router') or {}
    if router.get('market_closed'):
        add('Market closed — shadow review only.')

    freshness = sections.get('source_freshness') or {}
    if freshness.get('safe_to_use') is False:
        add('Source freshness not fully safe — treat scores cautiously.')
    for warning in freshness.get('warnings') or []:
        add(f'Freshness: {str(warning).replace("_", " ")}.')

    for warning in (sections.get('confidence_calibration') or {}).get('warnings') or []:
        add(f'Calibration: {str(warning).replace("_", " ")}.')

    for note in (sections.get('tomorrow_watchlist') or {}).get('risk_notes') or []:
        add(note)

    for warning in (sections.get('broker_intelligence') or {}).get('warnings') or []:
        add(f'Broker: {str(warning).replace("_", " ")}.')

    for warning in (sections.get('external_source_coverage') or {}).get('warnings') or []:
        add(f'External coverage: {str(warning).replace("_", " ")}.')

    ext_ev = sections.get('external_evidence') or {}
    if ext_ev.get('ok') and int(ext_ev.get('rejected') or 0) > int(ext_ev.get('accepted') or 0):
        add('Most external headlines are context/news — not broker picks.')
    if ext_ev.get('market_context_count') or ext_ev.get('macro_context_count'):
        add(
            'External market/macro context attached as risk notes only — not ticker BUY signals.',
        )

    if not notes:
        add('Review all sections before manual action — not trade execution.')
    return notes


def _refresh_component_reports(*, limit: int) -> dict[str, str]:
    """Regenerate underlying JSON reports (no trades/outcomes)."""
    statuses: dict[str, str] = {}

    from backend.analytics.final_confidence_fusion import build_final_confidence_report

    fc = build_final_confidence_report(limit=max(limit, 50))
    if fc.get('ok') is not True:
        statuses['final_confidence'] = 'fail'
    else:
        FILE_PATHS['final_confidence'].parent.mkdir(parents=True, exist_ok=True)
        FILE_PATHS['final_confidence'].write_text(
            json.dumps(fc, indent=2, default=str),
            encoding='utf-8',
        )
        statuses['final_confidence'] = 'ok'

    from backend.analytics.tomorrow_watchlist_report import write_tomorrow_watchlist_report

    tw = write_tomorrow_watchlist_report(limit=limit)
    statuses['tomorrow_watchlist'] = 'ok' if tw.get('ok') is True else 'fail'

    from backend.analytics.confidence_calibration_engine import build_confidence_calibration_report

    cal = build_confidence_calibration_report()
    if cal.get('ok') is not True:
        statuses['calibration'] = 'fail'
    else:
        FILE_PATHS['calibration'].parent.mkdir(parents=True, exist_ok=True)
        FILE_PATHS['calibration'].write_text(
            json.dumps(cal, indent=2, default=str),
            encoding='utf-8',
        )
        statuses['calibration'] = 'ok'

    return statuses


def generate_daily_report_pack(
    *,
    refresh: bool = False,
    limit: int = 25,
    pack_mode: str | None = None,
) -> dict[str, Any]:
    """Build daily report pack from live modules and/or cached JSON files."""
    refresh_status: dict[str, str] = {}
    if refresh:
        refresh_status = _refresh_component_reports(limit=limit)

    try:
        from backend.analytics.market_calendar_router import get_market_router_payload

        market_router = get_market_router_payload() or {}
    except Exception as exc:
        market_router = {'ok': False, 'error': str(exc)}

    try:
        from backend.analytics.source_freshness import get_source_freshness_report

        source_freshness = get_source_freshness_report() or {}
    except Exception as exc:
        source_freshness = {'ok': False, 'error': str(exc)}

    fc_raw = _load_json(FILE_PATHS['final_confidence'])
    tw_raw = _load_json(FILE_PATHS['tomorrow_watchlist'])
    cal_raw = _load_json(FILE_PATHS['calibration'])

    if tw_raw is None or tw_raw.get('ok') is not True:
        from backend.analytics.tomorrow_watchlist_report import write_tomorrow_watchlist_report

        tw_raw = write_tomorrow_watchlist_report(limit=limit)

    final_confidence = _compact_final_confidence(fc_raw)
    tomorrow_watchlist = _compact_watchlist(tw_raw)
    confidence_calibration = _compact_calibration(cal_raw)

    try:
        from backend.analytics.broker_prediction_intelligence import get_broker_intelligence_dashboard

        broker_intelligence = _compact_broker(get_broker_intelligence_dashboard())
    except Exception as exc:
        broker_intelligence = {'ok': False, 'error': str(exc)}

    try:
        from backend.collectors.broker_app_collector import (
            get_external_evidence_dashboard,
            get_external_source_coverage,
        )
        from backend.collectors.broker_db_write_gate import get_latest_broker_write_review

        external_source_coverage = _compact_external_source_coverage(get_external_source_coverage())
        external_evidence = _compact_external_evidence(get_external_evidence_dashboard())
        external_evidence_adapter = _compact_external_evidence_adapter()
        if external_evidence_adapter.get('ok') is True:
            external_evidence = {
                **external_evidence,
                'adapter_summary': external_evidence_adapter.get('summary') or {},
                'market_context_count': external_evidence_adapter.get('market_context_count', 0),
                'macro_context_count': external_evidence_adapter.get('macro_context_count', 0),
                'top_stock_evidence': external_evidence_adapter.get('top_stock_evidence') or [],
                'context_items': external_evidence_adapter.get('context_items') or [],
                'direction_counts': external_evidence_adapter.get('direction_counts') or {},
                'disclaimer': external_evidence_adapter.get('disclaimer')
                or external_evidence.get('disclaimer'),
            }
        broker_write_review = _compact_broker_write_review(get_latest_broker_write_review())
    except Exception as exc:
        external_source_coverage = {'ok': False, 'error': str(exc)}
        external_evidence = {'ok': False, 'error': str(exc)}
        external_evidence_adapter = {'ok': False, 'error': str(exc)}
        broker_write_review = {'ok': False, 'error': str(exc)}

    try:
        from backend.analytics.historical_learning_engine import get_historical_learning_summary

        historical_learning = _compact_historical_learning(get_historical_learning_summary())
    except Exception as exc:
        historical_learning = {'ok': False, 'error': str(exc)}

    try:
        from backend.analytics.historical_prediction_simulator import get_simulation_dashboard

        historical_simulation = _compact_simulation(get_simulation_dashboard())
    except Exception as exc:
        historical_simulation = {'ok': False, 'error': str(exc)}

    market_mode = str(
        market_router.get('active_mode')
        or tomorrow_watchlist.get('market_mode')
        or final_confidence.get('active_mode')
        or 'RESEARCH_MODE',
    )

    sections = {
        'market_router': market_router,
        'source_freshness': source_freshness,
        'final_confidence': final_confidence,
        'tomorrow_watchlist': tomorrow_watchlist,
        'broker_intelligence': broker_intelligence,
        'external_source_coverage': external_source_coverage,
        'external_evidence': external_evidence,
        'broker_write_review': broker_write_review,
        'historical_learning': historical_learning,
        'historical_simulation': historical_simulation,
        'confidence_calibration': confidence_calibration,
    }
    risk_notes = _collect_risk_notes(sections)

    pack = {
        'ok': True,
        'generated_at': _now_iso(),
        'pack_mode': str(pack_mode or '').strip().lower(),
        'learning_pack_version': LEARNING_PACK_VERSION,
        'shadow_mode': SHADOW_MODE,
        'market_mode': market_mode,
        'market_router': market_router,
        'source_freshness': source_freshness,
        'final_confidence': final_confidence,
        'tomorrow_watchlist': tomorrow_watchlist,
        'broker_intelligence': broker_intelligence,
        'external_source_coverage': external_source_coverage,
        'external_evidence': external_evidence,
        'broker_write_review': broker_write_review,
        'historical_learning': historical_learning,
        'historical_simulation': historical_simulation,
        'confidence_calibration': confidence_calibration,
        'risk_notes': risk_notes,
        'files': {
            key: _relative_data_path(path)
            for key, path in FILE_PATHS.items()
        },
        'refresh_status': refresh_status,
        'disclaimer': DISCLAIMER,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(
        json.dumps(pack, indent=2, default=str, ensure_ascii=False),
        encoding='utf-8',
    )
    append_daily_report_history(pack)
    pack['output_path'] = _relative_data_path(LATEST_PATH)
    return pack


def get_latest_daily_report_pack() -> dict[str, Any]:
    """Load latest pack JSON or generate if missing."""
    cached = _load_json(LATEST_PATH)
    if cached and cached.get('ok') is True:
        return {**cached, 'cached': True}
    report = generate_daily_report_pack(refresh=False)
    report['cached'] = False
    return report


def append_daily_report_history(report: dict[str, Any]) -> dict[str, Any]:
    """Append compact history line for each pack generation."""
    summary = {
        'generated_at': report.get('generated_at'),
        'market_mode': report.get('market_mode'),
        'shadow_mode': report.get('shadow_mode'),
        'watch': (report.get('tomorrow_watchlist') or {}).get('watch', 0),
        'avoid': (report.get('tomorrow_watchlist') or {}).get('avoid', 0),
        'no_decision': (report.get('tomorrow_watchlist') or {}).get('no_decision', 0),
        'risk_notes_count': len(report.get('risk_notes') or []),
        'files': report.get('files') or {},
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(summary, default=str, ensure_ascii=False) + '\n')
    return {'ok': True, 'history_path': _relative_data_path(HISTORY_PATH), 'entry': summary}


def pack_contains_secrets(report: dict[str, Any]) -> bool:
    blob = json.dumps(report, default=str)
    return bool(SECRET_PATTERN.search(blob))
