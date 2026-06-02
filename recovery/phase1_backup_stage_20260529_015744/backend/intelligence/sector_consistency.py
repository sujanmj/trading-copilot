"""
Stable sector rotation — weighted aggregation frozen per active snapshot.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from backend.utils.config import DATA_DIR

SCANNER_FILE = DATA_DIR / 'scanner_data.json'
MIN_ROTATION_CONFIDENCE = 0.35


def _load_scanner_sectors() -> List[dict]:
    if not SCANNER_FILE.exists():
        return []
    try:
        data = json.loads(SCANNER_FILE.read_text(encoding='utf-8'))
    except Exception:
        return []
    raw = data.get('sector_rotation')
    return raw if isinstance(raw, list) else []


def _sector_score(row: dict) -> float:
    try:
        move = abs(float(row.get('avg_change_percent') or row.get('change_percent') or 0))
    except (TypeError, ValueError):
        move = 0.0
    try:
        vol = float(row.get('avg_volume_ratio') or row.get('volume_ratio') or 1.0)
    except (TypeError, ValueError):
        vol = 1.0
    breadth = min(1.0, int(row.get('stocks_analyzed') or row.get('count') or 1) / 5.0)
    strength_map = {'STRONG': 1.0, 'MODERATE': 0.65, 'WEAK': 0.35}
    strength = strength_map.get(str(row.get('strength') or '').upper(), 0.5)
    return round(move * 0.45 + (vol - 1.0) * 0.25 + breadth * 0.15 + strength * 0.15, 3)


def stabilize_sector_rotation(
    intel: Optional[dict] = None,
    scanner_sectors: Optional[List[dict]] = None,
) -> dict:
    """
    Merge scanner quantitative sectors with AI lists into a stable ranked structure.
    Returns {bullish, bearish, rotation_strength, sectors[]} sorted by score.
    """
    intel = intel if isinstance(intel, dict) else {}
    existing = intel.get('sector_rotation') if isinstance(intel.get('sector_rotation'), dict) else {}
    scanner_rows = scanner_sectors if scanner_sectors is not None else _load_scanner_sectors()

    merged: Dict[str, dict] = {}
    for row in scanner_rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get('sector') or row.get('name') or '').strip().upper()
        if not name:
            continue
        score = _sector_score(row)
        if score < MIN_ROTATION_CONFIDENCE:
            continue
        direction = str(row.get('direction') or '').upper()
        merged[name] = {
            'sector': name,
            'score': score,
            'direction': direction or 'NEUTRAL',
            'rotation_strength': round(min(1.0, score / 2.5), 2),
            'source': 'scanner',
        }

    for side, direction in (('bullish', 'BULLISH'), ('bearish', 'BEARISH')):
        items = existing.get(side) if isinstance(existing.get(side), list) else []
        for item in items:
            name = str(item).strip().upper()
            if not name:
                continue
            entry = merged.get(name) or {
                'sector': name,
                'score': MIN_ROTATION_CONFIDENCE + 0.1,
                'direction': direction,
                'rotation_strength': 0.4,
                'source': 'intel',
            }
            entry['direction'] = direction
            entry['score'] = max(float(entry.get('score') or 0), MIN_ROTATION_CONFIDENCE + 0.05)
            entry['rotation_strength'] = round(min(1.0, float(entry['score']) / 2.5), 2)
            merged[name] = entry

    ranked = sorted(merged.values(), key=lambda x: (-float(x.get('score') or 0), x.get('sector', '')))
    bullish = [s['sector'] for s in ranked if s.get('direction') == 'BULLISH'][:6]
    bearish = [s['sector'] for s in ranked if s.get('direction') == 'BEARISH'][:6]
    top_strength = float(ranked[0]['rotation_strength']) if ranked else 0.0

    return {
        'bullish': bullish,
        'bearish': bearish,
        'rotation_strength': round(top_strength, 2),
        'sectors': ranked[:12],
        'source': 'sector_consistency',
    }
