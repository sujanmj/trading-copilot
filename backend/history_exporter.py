"""
history_exporter.py
====================
Exports prediction history data from SQLite to JSON for GUI consumption.
Generates: data/history_data.json

Includes:
- Predictions grouped by date
- Win/loss summary per day
- Top winners and losers
- Daily timelines
- Period filters (1d, 7d, 15d, 30d)
"""

import os
import sys
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR.parent / 'data'
DB_PATH = DATA_DIR / 'trading_history.db'
OUTPUT_FILE = DATA_DIR / 'history_data.json'


def get_predictions_with_outcomes(days=30):
    """Get all predictions joined with outcomes for last N days"""
    if not DB_PATH.exists():
        print(f"[ERROR] Database not found: {DB_PATH}")
        return []
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Join predictions with outcomes
    query = '''
        SELECT 
            p.id, p.created_at, p.prediction_date, p.run_type, p.use_case,
            p.ticker, p.sector, p.recommendation, p.category, p.rank_in_list,
            p.entry_price, p.target_price, p.stop_loss, p.confidence,
            p.reasoning, p.cross_validation, p.overall_conviction,
            o.entry_price as outcome_entry,
            o.price_1d, o.change_1d_pct,
            o.price_3d, o.change_3d_pct,
            o.price_7d, o.change_7d_pct,
            o.target_hit, o.stop_loss_hit,
            o.max_gain_pct, o.max_loss_pct,
            o.verdict, o.last_checked
        FROM predictions p
        LEFT JOIN outcomes o ON o.source_id = p.id AND o.source_type = 'prediction'
        WHERE p.prediction_date >= date('now', ?)
        ORDER BY p.prediction_date DESC, p.rank_in_list ASC
    '''
    
    cursor.execute(query, (f'-{days} days',))
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(r) for r in rows]


def calculate_period_stats(predictions):
    """Calculate stats for a list of predictions"""
    total = len(predictions)
    if total == 0:
        return {'total': 0, 'wins': 0, 'losses': 0, 'neutral': 0, 'pending': 0, 'win_rate': 0}
    
    wins = sum(1 for p in predictions if p.get('verdict') == 'WIN')
    losses = sum(1 for p in predictions if p.get('verdict') == 'LOSS')
    neutral = sum(1 for p in predictions if p.get('verdict') == 'NEUTRAL')
    pending = sum(1 for p in predictions if p.get('verdict') in [None, 'PENDING', ''])
    
    evaluated = wins + losses
    win_rate = (wins / evaluated * 100) if evaluated > 0 else 0
    
    return {
        'total': total,
        'wins': wins,
        'losses': losses,
        'neutral': neutral,
        'pending': pending,
        'evaluated': evaluated,
        'win_rate': round(win_rate, 1)
    }


def get_top_winners(predictions, limit=10):
    """Get top winning predictions"""
    wins = [p for p in predictions if p.get('verdict') == 'WIN']
    
    # Sort by max gain or 7d change
    def gain_score(p):
        return max(
            p.get('max_gain_pct') or 0,
            p.get('change_7d_pct') or 0,
            p.get('change_3d_pct') or 0,
            p.get('change_1d_pct') or 0
        )
    
    wins.sort(key=gain_score, reverse=True)
    return wins[:limit]


def get_top_losers(predictions, limit=10):
    """Get top losing predictions"""
    losses = [p for p in predictions if p.get('verdict') == 'LOSS']
    
    def loss_score(p):
        return min(
            p.get('max_loss_pct') or 0,
            p.get('change_7d_pct') or 0,
            p.get('change_3d_pct') or 0,
            p.get('change_1d_pct') or 0
        )
    
    losses.sort(key=loss_score)  # Most negative first
    return losses[:limit]


def group_by_date(predictions):
    """Group predictions by prediction_date"""
    grouped = defaultdict(list)
    for p in predictions:
        date = p.get('prediction_date', 'unknown')
        grouped[date].append(p)
    
    # Convert to sorted list of dicts
    timeline = []
    for date in sorted(grouped.keys(), reverse=True):
        day_preds = grouped[date]
        day_stats = calculate_period_stats(day_preds)
        timeline.append({
            'date': date,
            'stats': day_stats,
            'predictions': day_preds
        })
    
    return timeline


def get_signals_history(days=30):
    """Get scanner signals history"""
    if not DB_PATH.exists():
        return []
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT s.*, o.verdict, o.change_1d_pct, o.change_3d_pct, o.change_7d_pct,
               o.max_gain_pct, o.max_loss_pct
        FROM signals s
        LEFT JOIN outcomes o ON o.source_id = s.id AND o.source_type = 'signal'
        WHERE s.signal_date >= date('now', ?)
        ORDER BY s.signal_date DESC, s.created_at DESC
    ''', (f'-{days} days',))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(r) for r in rows]


def get_context_snapshots(days=30):
    """Get context snapshots history"""
    if not DB_PATH.exists():
        return []
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check if context_snapshots table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='context_snapshots'")
    if not cursor.fetchone():
        conn.close()
        return []
    
    cursor.execute('''
        SELECT id, snapshot_id, timestamp, run_type, global_mood,
               nifty_change_pct, news_positive_count, news_negative_count,
               reddit_mood, reddit_confidence, scanner_total_signals,
               scanner_ultra_signals
        FROM context_snapshots
        WHERE timestamp >= datetime('now', ?)
        ORDER BY timestamp DESC
    ''', (f'-{days} days',))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(r) for r in rows]


def build_export(days_options=[1, 7, 15, 30]):
    """Build complete history export"""
    
    print("=" * 60)
    print("HISTORY EXPORTER")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Get all data for max period
    max_days = max(days_options)
    print(f"\n[FETCHING] Last {max_days} days of predictions...")
    all_predictions = get_predictions_with_outcomes(max_days)
    print(f"  Total predictions: {len(all_predictions)}")
    
    print(f"\n[FETCHING] Last {max_days} days of signals...")
    all_signals = get_signals_history(max_days)
    print(f"  Total signals: {len(all_signals)}")
    
    print(f"\n[FETCHING] Context snapshots...")
    snapshots = get_context_snapshots(max_days)
    print(f"  Total snapshots: {len(snapshots)}")
    
    # Build period summaries
    periods = {}
    for days in days_options:
        cutoff = datetime.now() - timedelta(days=days)
        period_preds = [
            p for p in all_predictions 
            if p.get('prediction_date') and p['prediction_date'] >= cutoff.strftime('%Y-%m-%d')
        ]
        period_signals = [
            s for s in all_signals 
            if s.get('signal_date') and s['signal_date'] >= cutoff.strftime('%Y-%m-%d')
        ]
        
        periods[f'{days}d'] = {
            'days': days,
            'stats': calculate_period_stats(period_preds),
            'top_winners': get_top_winners(period_preds, 10),
            'top_losers': get_top_losers(period_preds, 10),
            'timeline': group_by_date(period_preds)[:30],  # Cap at 30 days
            'signals_count': len(period_signals),
            'opportunities_count': sum(1 for p in period_preds if p.get('category') == 'opportunity'),
            'risks_count': sum(1 for p in period_preds if p.get('category') == 'risk'),
        }
        
        s = periods[f'{days}d']['stats']
        print(f"\n[{days}d] {s['total']} predictions | {s['wins']}W/{s['losses']}L | Win rate: {s['win_rate']}%")
    
    # By sector breakdown (30d)
    sector_stats = defaultdict(lambda: {'total': 0, 'wins': 0, 'losses': 0, 'pending': 0})
    for p in all_predictions:
        sector = p.get('sector') or 'UNKNOWN'
        sector_stats[sector]['total'] += 1
        verdict = p.get('verdict')
        if verdict == 'WIN':
            sector_stats[sector]['wins'] += 1
        elif verdict == 'LOSS':
            sector_stats[sector]['losses'] += 1
        else:
            sector_stats[sector]['pending'] += 1
    
    sectors_list = []
    for sector, stats in sector_stats.items():
        evaluated = stats['wins'] + stats['losses']
        win_rate = (stats['wins'] / evaluated * 100) if evaluated > 0 else 0
        sectors_list.append({
            'sector': sector,
            'total': stats['total'],
            'wins': stats['wins'],
            'losses': stats['losses'],
            'pending': stats['pending'],
            'win_rate': round(win_rate, 1)
        })
    sectors_list.sort(key=lambda x: x['total'], reverse=True)
    
    # By confidence breakdown
    conf_stats = defaultdict(lambda: {'total': 0, 'wins': 0, 'losses': 0})
    for p in all_predictions:
        conf = (p.get('confidence') or 'UNKNOWN').upper()
        conf_stats[conf]['total'] += 1
        verdict = p.get('verdict')
        if verdict == 'WIN':
            conf_stats[conf]['wins'] += 1
        elif verdict == 'LOSS':
            conf_stats[conf]['losses'] += 1
    
    conf_list = []
    for conf, stats in conf_stats.items():
        evaluated = stats['wins'] + stats['losses']
        win_rate = (stats['wins'] / evaluated * 100) if evaluated > 0 else 0
        conf_list.append({
            'confidence': conf,
            'total': stats['total'],
            'wins': stats['wins'],
            'losses': stats['losses'],
            'win_rate': round(win_rate, 1)
        })
    
    # Output
    output = {
        'last_updated': datetime.now().isoformat(),
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'periods': periods,
        'by_sector': sectors_list,
        'by_confidence': conf_list,
        'context_snapshots': snapshots[:30],  # Last 30
        'total_in_db': {
            'predictions': len(all_predictions),
            'signals': len(all_signals),
            'snapshots': len(snapshots)
        }
    }
    
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, default=str, ensure_ascii=False)
    
    print(f"\n[SAVED] {OUTPUT_FILE}")
    print(f"  File size: {OUTPUT_FILE.stat().st_size / 1024:.1f} KB")
    print("=" * 60)
    
    return output


if __name__ == "__main__":
    build_export()