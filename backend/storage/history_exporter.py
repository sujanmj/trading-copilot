"""
history_exporter.py v2.2 - Removed 30d (replaced with Custom in GUI)
"""

print("[HISTORY] history_exporter.py starting...")

import os
import sys
import json
import sqlite3
from datetime import datetime, timedelta, date
from pathlib import Path
from collections import defaultdict

from backend.storage.json_io import atomic_write_json

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from backend.utils.config import DATA_DIR

OUTPUT_FILE = DATA_DIR / 'history_data.json'


def get_db_path():
    from backend.storage.db_finder import resolve_db_path
    return Path(resolve_db_path())


def empty_history_output():
    empty_period = {
        'name': 'today',
        'label': 'Today',
        'start_date': date.today().isoformat(),
        'end_date': date.today().isoformat(),
        'days_count': 1,
        'stats': {'total': 0, 'wins': 0, 'losses': 0, 'neutral': 0, 'pending': 0, 'evaluated': 0, 'win_rate': 0},
        'top_winners': [],
        'top_losers': [],
        'timeline': [],
        'signals_count': 0,
        'opportunities_count': 0,
        'risks_count': 0,
    }
    return {
        'last_updated': datetime.now().isoformat(),
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'today_date': date.today().isoformat(),
        'today_weekday': date.today().strftime('%A'),
        'periods': {
            'today': empty_period,
            'yesterday': {**empty_period, 'name': 'yesterday', 'label': 'Yesterday'},
            'this_week': {**empty_period, 'name': 'this_week', 'label': 'This Week'},
            'last_week': {**empty_period, 'name': 'last_week', 'label': 'Last Week'},
            '15d': {**empty_period, 'name': '15d', 'label': 'Last 15 Days'},
        },
        'by_sector': [],
        'by_confidence': [],
        'context_snapshots': [],
        'total_in_db': {'predictions': 0, 'signals': 0, 'snapshots': 0},
        'intelligence_journal': {'status': 'empty', 'entries': [], 'dates': []},
    }


def get_today_range():
    today = date.today()
    return today, today


def get_yesterday_range():
    yesterday = date.today() - timedelta(days=1)
    return yesterday, yesterday


def get_this_week_range():
    today = date.today()
    weekday = today.weekday()
    if weekday == 6:
        return today, today
    else:
        prev_sunday = today - timedelta(days=weekday + 1)
        return prev_sunday, today


def get_last_week_range():
    today = date.today()
    weekday = today.weekday()
    if weekday == 6:
        this_sunday = today
    else:
        this_sunday = today - timedelta(days=weekday + 1)
    last_sunday = this_sunday - timedelta(days=7)
    last_friday = last_sunday + timedelta(days=5)
    return last_sunday, last_friday


def get_days_back_range(days):
    today = date.today()
    start = today - timedelta(days=days)
    return start, today


def get_predictions_in_range(start_date, end_date):
    db_path = get_db_path()
    if not db_path.exists():
        print(f"[WARN] Database not found: {db_path}")
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
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
        WHERE p.prediction_date >= ? AND p.prediction_date <= ?
        ORDER BY p.prediction_date DESC, p.rank_in_list ASC
    '''
    cursor.execute(query, (start_date.isoformat(), end_date.isoformat()))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_signals_in_range(start_date, end_date):
    db_path = get_db_path()
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT s.*, o.verdict, o.change_1d_pct, o.change_3d_pct, o.change_7d_pct,
               o.max_gain_pct, o.max_loss_pct
        FROM signals s
        LEFT JOIN outcomes o ON o.source_id = s.id AND o.source_type = 'signal'
        WHERE s.signal_date >= ? AND s.signal_date <= ?
        ORDER BY s.signal_date DESC, s.created_at DESC
    ''', (start_date.isoformat(), end_date.isoformat()))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_context_snapshots(days=30):
    db_path = get_db_path()
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
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


def calculate_period_stats(predictions):
    total = len(predictions)
    if total == 0:
        return {'total': 0, 'wins': 0, 'losses': 0, 'neutral': 0, 'pending': 0, 'evaluated': 0, 'win_rate': 0}
    wins = sum(1 for p in predictions if p.get('verdict') == 'WIN')
    losses = sum(1 for p in predictions if p.get('verdict') == 'LOSS')
    neutral = sum(1 for p in predictions if p.get('verdict') == 'NEUTRAL')
    pending = sum(1 for p in predictions if p.get('verdict') in [None, 'PENDING', ''])
    evaluated = wins + losses
    win_rate = (wins / evaluated * 100) if evaluated > 0 else 0
    return {
        'total': total, 'wins': wins, 'losses': losses,
        'neutral': neutral, 'pending': pending,
        'evaluated': evaluated, 'win_rate': round(win_rate, 1)
    }


def get_top_winners(predictions, limit=10):
    wins = [p for p in predictions if p.get('verdict') == 'WIN']
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
    losses = [p for p in predictions if p.get('verdict') == 'LOSS']
    def loss_score(p):
        return min(
            p.get('max_loss_pct') or 0,
            p.get('change_7d_pct') or 0,
            p.get('change_3d_pct') or 0,
            p.get('change_1d_pct') or 0
        )
    losses.sort(key=loss_score)
    return losses[:limit]


def group_by_date(predictions):
    grouped = defaultdict(list)
    for p in predictions:
        d = p.get('prediction_date', 'unknown')
        grouped[d].append(p)
    timeline = []
    for d in sorted(grouped.keys(), reverse=True):
        day_preds = grouped[d]
        day_stats = calculate_period_stats(day_preds)
        timeline.append({
            'date': d, 'stats': day_stats, 'predictions': day_preds
        })
    return timeline


def build_period(name, start_date, end_date, label):
    preds = get_predictions_in_range(start_date, end_date)
    signals = get_signals_in_range(start_date, end_date)
    return {
        'name': name,
        'label': label,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'days_count': (end_date - start_date).days + 1,
        'stats': calculate_period_stats(preds),
        'top_winners': get_top_winners(preds, 10),
        'top_losers': get_top_losers(preds, 10),
        'timeline': group_by_date(preds),
        'signals_count': len(signals),
        'opportunities_count': sum(1 for p in preds if p.get('category') == 'opportunity'),
        'risks_count': sum(1 for p in preds if p.get('category') == 'risk'),
    }


def build_export():
    print("=" * 60)
    print("HISTORY EXPORTER v2.2 - Smart Periods + Custom")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    try:
        from backend.storage.db_finder import resolve_db_path
        db_path = resolve_db_path()
        print(f"[DB] Using: {db_path}")

        today = date.today()
        weekday_name = today.strftime('%A')
        print(f"\nToday is: {today.isoformat()} ({weekday_name})")

        periods = {}

        start, end = get_today_range()
        periods['today'] = build_period('today', start, end, 'Today')
        print(f"\n[TODAY]      ({start})            {periods['today']['stats']['total']} predictions")

        start, end = get_yesterday_range()
        periods['yesterday'] = build_period('yesterday', start, end, 'Yesterday')
        print(f"[YESTERDAY]  ({start})            {periods['yesterday']['stats']['total']} predictions")

        start, end = get_this_week_range()
        label = f'This Week ({start.strftime("%a %d %b")} - {end.strftime("%a %d %b")})'
        periods['this_week'] = build_period('this_week', start, end, label)
        print(f"[THIS WEEK]  ({start} to {end}) {periods['this_week']['stats']['total']} predictions")

        start, end = get_last_week_range()
        label = f'Last Week ({start.strftime("%a %d %b")} - {end.strftime("%a %d %b")})'
        periods['last_week'] = build_period('last_week', start, end, label)
        print(f"[LAST WEEK]  ({start} to {end}) {periods['last_week']['stats']['total']} predictions")

        start, end = get_days_back_range(15)
        periods['15d'] = build_period('15d', start, end, 'Last 15 Days')
        print(f"[15D]                              {periods['15d']['stats']['total']} predictions")

        start_all = today - timedelta(days=90)
        all_predictions = get_predictions_in_range(start_all, today)

        if not all_predictions:
            print("[INFO] No predictions yet — writing empty history JSON")
            output = empty_history_output()
            try:
                from backend.analytics.daily_journal_engine import build_intelligence_journal
                output['intelligence_journal'] = build_intelligence_journal(limit=21)
            except Exception as e:
                print(f"[WARN] intelligence journal failed: {e}")
            atomic_write_json(OUTPUT_FILE, output)
            print(f"\n[SAVED] {OUTPUT_FILE}")
            print("=" * 60)
            return output

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
                'sector': sector, 'total': stats['total'],
                'wins': stats['wins'], 'losses': stats['losses'],
                'pending': stats['pending'], 'win_rate': round(win_rate, 1)
            })
        sectors_list.sort(key=lambda x: x['total'], reverse=True)

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
                'confidence': conf, 'total': stats['total'],
                'wins': stats['wins'], 'losses': stats['losses'],
                'win_rate': round(win_rate, 1)
            })

        snapshots = get_context_snapshots(90)

        try:
            from backend.analytics.daily_journal_engine import build_intelligence_journal
            intelligence_journal = build_intelligence_journal(limit=21)
        except Exception as e:
            print(f"[WARN] intelligence journal failed: {e}")
            intelligence_journal = {'status': 'degraded', 'entries': [], 'reason': str(e)}

        output = {
            'last_updated': datetime.now().isoformat(),
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'today_date': today.isoformat(),
            'today_weekday': weekday_name,
            'periods': periods,
            'by_sector': sectors_list,
            'by_confidence': conf_list,
            'context_snapshots': snapshots[:30],
            'total_in_db': {
                'predictions': len(all_predictions),
                'signals': sum(p['signals_count'] for p in periods.values()),
                'snapshots': len(snapshots)
            },
            'intelligence_journal': intelligence_journal,
        }

        atomic_write_json(OUTPUT_FILE, output)

        print(f"\n[SAVED] {OUTPUT_FILE}")
        print(f"  File size: {OUTPUT_FILE.stat().st_size / 1024:.1f} KB")
        print("=" * 60)

        return output
    except Exception as e:
        import traceback
        print(f"[WARN] History export failed: {e}")
        traceback.print_exc()
        output = empty_history_output()
        atomic_write_json(OUTPUT_FILE, output)
        print(f"[SAVED] fallback empty history to {OUTPUT_FILE}")
        return output


def build_custom_period(start_date_str, end_date_str):
    """Build period for custom date range (called by API)"""
    try:
        start = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except:
        return {'error': 'Invalid date format. Use YYYY-MM-DD'}
    
    if start > end:
        return {'error': 'Start date must be before end date'}
    
    label = f'Custom ({start.strftime("%d %b %Y")} - {end.strftime("%d %b %Y")})'
    period = build_period('custom', start, end, label)
    return period


if __name__ == "__main__":
    print("[HISTORY] history_exporter.py __main__ running build_export()")
    try:
        build_export()
    except Exception as e:
        import traceback
        print(f"[HISTORY] FATAL: {e}")
        traceback.print_exc()
        try:
            atomic_write_json(OUTPUT_FILE, empty_history_output())
            print(f"[HISTORY] Wrote emergency empty history to {OUTPUT_FILE}")
        except Exception:
            pass