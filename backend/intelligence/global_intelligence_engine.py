"""
Overnight global intelligence pipeline — US close scan → macro synthesis → India open report.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

import pytz

from backend.storage.json_io import atomic_write_json
from backend.utils.config import DATA_DIR

IST = pytz.timezone('Asia/Kolkata')
TIMELINE_FILE = DATA_DIR / 'overnight_timeline.json'
IMPACT_FILE = DATA_DIR / 'overnight_global_impact.json'


def _append_timeline(stage: str, detail: str, *, payload: Optional[dict] = None) -> dict:
    entry = {
        'stage': stage,
        'at': datetime.now(IST).isoformat(),
        'detail': detail,
        'payload': payload or {},
    }
    data = {'events': []}
    if TIMELINE_FILE.exists():
        try:
            data = json.loads(TIMELINE_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    events = list(data.get('events') or [])
    events.append(entry)
    data['events'] = events[-48:]
    data['last_stage'] = stage
    data['updated_at'] = entry['at']
    atomic_write_json(TIMELINE_FILE, data)
    return entry


def run_us_close_scan() -> dict:
    """4:00 AM IST — refresh global markets after US session."""
    from backend.collectors.global_collector import fetch_global_sentiment
    global_data = fetch_global_sentiment()
    _append_timeline('us_close_scan', 'US market close global scan complete', payload={
        'symbols': len(global_data.get('flat_markets') or {}),
    })
    return global_data


def run_macro_synthesis() -> dict:
    """4:15 AM IST — aggregate macro + geopolitics."""
    from backend.intelligence.india_next_open_engine import build_india_next_open_report
    report = build_india_next_open_report()
    impact = {
        'generated_at': datetime.now(IST).isoformat(),
        'stage': 'macro_synthesis',
        'india_next_open': report,
        'global_file': str(DATA_DIR / 'global_markets.json'),
    }
    if (DATA_DIR / 'global_markets.json').exists():
        try:
            impact['global_snapshot'] = json.loads((DATA_DIR / 'global_markets.json').read_text(encoding='utf-8'))
        except Exception:
            pass
    atomic_write_json(IMPACT_FILE, impact)
    _append_timeline('macro_synthesis', report.get('narrative', 'Macro synthesis complete')[:200], payload={
        'open_bias': report.get('india_open_bias'),
    })
    return impact


def run_india_next_open_report(*, run_analyzer: bool = True) -> dict:
    """5:00 AM IST — India next-open AI report."""
    impact = run_macro_synthesis()
    report = impact.get('india_next_open') or {}
    if run_analyzer:
        import os
        os.environ['AI_USE_CASE'] = 'overnight_brief'
        try:
            from backend.orchestration.master_scheduler import run_standalone_script
            run_standalone_script('master_analyzer.py')
        except Exception as exc:
            _append_timeline('india_next_open', f'Analyzer skipped: {exc}')
        else:
            _append_timeline('india_next_open', 'Overnight AI synthesis complete')
    try:
        from backend.intelligence.active_snapshot import publish_active_snapshot, begin_publish_job
        from backend.utils.config import DATA_DIR as DD
        intel_path = DD / 'unified_intelligence.json'
        intel = {}
        if intel_path.exists():
            intel = json.loads(intel_path.read_text(encoding='utf-8'))
        mood = intel.setdefault('market_mood', {})
        mood['india_outlook'] = report.get('india_outlook') or mood.get('india_outlook')
        mood['global_mood'] = report.get('india_open_bias') or mood.get('global_mood')
        mood['overnight_narrative'] = report.get('narrative')
        intel['overnight_impact'] = report
        job = begin_publish_job(source='overnight_pipeline')
        publish_active_snapshot(intel, source='overnight_pipeline', publish_token=job.get('publish_token'))
    except Exception:
        pass
    return {'impact': impact, 'report': report}


def run_premarket_scanner() -> dict:
    """8:30 AM IST — NSE scanner preload."""
    from backend.orchestration.master_scheduler import run_standalone_script
    run_standalone_script('stock_scanner.py')
    _append_timeline('premarket_scanner', 'Premarket NSE scanner complete')
    return {'status': 'ok'}


def run_market_open_tactical() -> dict:
    """9:00 AM IST — tactical refresh for open."""
    from backend.orchestration.master_scheduler import run_standalone_script
    run_standalone_script('stock_scanner.py')
    try:
        from backend.lifecycle.prediction_lifecycle_engine import refresh_brain_opportunities
        refresh_brain_opportunities()
    except Exception:
        pass
    _append_timeline('market_open_tactical', 'Market open tactical refresh complete')
    return {'status': 'ok'}


def get_overnight_global_impact() -> Dict[str, Any]:
    if IMPACT_FILE.exists():
        try:
            return json.loads(IMPACT_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}


def get_overnight_timeline() -> Dict[str, Any]:
    if TIMELINE_FILE.exists():
        try:
            return json.loads(TIMELINE_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {'events': []}
