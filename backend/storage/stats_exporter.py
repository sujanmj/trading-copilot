"""
Stats Exporter v1 - Path D
Exports SQLite database stats to JSON for the GUI Stats tab

Generates: data/stats_data.json
Auto-runs after outcome_tracker (or manually)
"""

print("[STATS] stats_exporter.py starting...")

import os
os.environ['PYTHONIOENCODING'] = 'utf-8'

import sys
import json
from datetime import datetime, timezone
from pathlib import Path

from backend.storage.json_io import atomic_write_json
from backend.storage.db_manager import (
    get_connection,
    get_db_stats,
    get_recent_predictions,
    get_top_winners,
    get_top_losers,
    calculate_accuracy_metrics,
    init_db,
)


def safe_print(text):
    try:
        print(text)
    except (UnicodeEncodeError, ValueError):
        try:
            print(text.encode('ascii', errors='replace').decode('ascii'))
        except Exception:
            pass


from backend.utils.config import DATA_DIR

OUTPUT_FILE = DATA_DIR / 'stats_data.json'


def empty_stats_output():
    return {
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'generation_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'db_stats': {'total_predictions': 0, 'total_signals': 0, 'total_outcomes': 0, 'evaluated_outcomes': 0, 'db_size_kb': 0},
        'metrics_all_time': {'win_rate': 0, 'wins': 0, 'losses': 0, 'neutral': 0, 'pending': 0, 'total_evaluated': 0},
        'metrics_weekly': {'win_rate': 0},
        'metrics_daily': {'win_rate': 0},
        'recent_predictions': [],
        'top_winners': [],
        'top_losers': [],
        'by_sector': [],
        'by_run_type': [],
        'by_date': [],
        'signals_summary': {'total': 0, 'ultra': 0, 'strong': 0, 'bullish': 0, 'bearish': 0, 'top_tickers': []},
        'calibration_dashboard': {
            'status': 'empty',
            'market_day_performance': {'day_types': []},
            'confidence_calibration': {'numeric_buckets': [], 'bands': []},
            'signal_type_performance': {'categories': []},
            'telegram_precision': {},
            'calibration_health': {},
        },
    }


def write_stats_output(output):
    atomic_write_json(OUTPUT_FILE, output)


def get_predictions_by_sector():
    """Group predictions by sector with win rates"""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT 
                p.sector,
                COUNT(p.id) as total,
                SUM(CASE WHEN o.verdict='WIN' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN o.verdict='LOSS' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN o.verdict IS NOT NULL AND o.verdict != 'PENDING' THEN 1 ELSE 0 END) as evaluated
            FROM predictions p
            LEFT JOIN outcomes o ON o.source_type='prediction' AND o.source_id=p.id
            WHERE p.sector IS NOT NULL AND p.sector != 'UNKNOWN'
            GROUP BY p.sector
            ORDER BY total DESC
        """).fetchall()
        
        result = []
        for r in rows:
            d = dict(r)
            evaluated = d['evaluated'] or 0
            wins = d['wins'] or 0
            win_rate = (wins / evaluated * 100) if evaluated > 0 else 0
            result.append({
                'sector': d['sector'],
                'total': d['total'],
                'wins': wins,
                'losses': d['losses'] or 0,
                'evaluated': evaluated,
                'win_rate': round(win_rate, 1),
            })
        return result
    finally:
        conn.close()


def get_predictions_by_run_type():
    """Group by which run created the prediction (overnight, premarket, etc.)"""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT 
                p.run_type,
                COUNT(p.id) as total,
                SUM(CASE WHEN o.verdict='WIN' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN o.verdict IS NOT NULL AND o.verdict != 'PENDING' THEN 1 ELSE 0 END) as evaluated
            FROM predictions p
            LEFT JOIN outcomes o ON o.source_type='prediction' AND o.source_id=p.id
            GROUP BY p.run_type
            ORDER BY total DESC
        """).fetchall()
        
        result = []
        for r in rows:
            d = dict(r)
            evaluated = d['evaluated'] or 0
            wins = d['wins'] or 0
            win_rate = (wins / evaluated * 100) if evaluated > 0 else 0
            result.append({
                'run_type': d['run_type'] or 'unknown',
                'total': d['total'],
                'wins': wins,
                'evaluated': evaluated,
                'win_rate': round(win_rate, 1),
            })
        return result
    finally:
        conn.close()


def get_predictions_by_date():
    """Daily prediction count and accuracy"""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT 
                p.prediction_date,
                COUNT(p.id) as total,
                SUM(CASE WHEN o.verdict='WIN' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN o.verdict='LOSS' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN o.verdict IS NOT NULL AND o.verdict != 'PENDING' THEN 1 ELSE 0 END) as evaluated,
                AVG(o.max_gain_pct) as avg_max_gain,
                AVG(o.max_loss_pct) as avg_max_loss
            FROM predictions p
            LEFT JOIN outcomes o ON o.source_type='prediction' AND o.source_id=p.id
            GROUP BY p.prediction_date
            ORDER BY p.prediction_date DESC
            LIMIT 30
        """).fetchall()
        
        result = []
        for r in rows:
            d = dict(r)
            evaluated = d['evaluated'] or 0
            wins = d['wins'] or 0
            win_rate = (wins / evaluated * 100) if evaluated > 0 else 0
            result.append({
                'date': d['prediction_date'],
                'total': d['total'],
                'wins': wins,
                'losses': d['losses'] or 0,
                'evaluated': evaluated,
                'win_rate': round(win_rate, 1),
                'avg_max_gain': round(d['avg_max_gain'] or 0, 2),
                'avg_max_loss': round(d['avg_max_loss'] or 0, 2),
            })
        return result
    finally:
        conn.close()


def get_recent_predictions_simple(limit=15):
    """Recent predictions formatted for GUI"""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT 
                p.id, p.prediction_date, p.ticker, p.sector,
                p.recommendation, p.category, p.confidence,
                p.entry_price, p.target_price, p.reasoning,
                p.cross_validation, p.overall_conviction,
                o.verdict, o.change_1d_pct, o.change_3d_pct, o.change_7d_pct,
                o.max_gain_pct, o.max_loss_pct, o.target_hit
            FROM predictions p
            LEFT JOIN outcomes o ON o.source_type='prediction' AND o.source_id=p.id
            ORDER BY p.created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_signals_summary():
    """Stats on scanner signals"""
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        ultra = conn.execute("SELECT COUNT(*) FROM signals WHERE strength='ULTRA'").fetchone()[0]
        strong = conn.execute("SELECT COUNT(*) FROM signals WHERE strength='STRONG'").fetchone()[0]
        bullish = conn.execute("SELECT COUNT(*) FROM signals WHERE direction='BULLISH'").fetchone()[0]
        bearish = conn.execute("SELECT COUNT(*) FROM signals WHERE direction='BEARISH'").fetchone()[0]
        
        # Top tickers with most signals
        top_tickers = conn.execute("""
            SELECT ticker, COUNT(*) as count
            FROM signals
            GROUP BY ticker
            ORDER BY count DESC
            LIMIT 10
        """).fetchall()
        
        return {
            'total': total,
            'ultra': ultra,
            'strong': strong,
            'bullish': bullish,
            'bearish': bearish,
            'top_tickers': [dict(r) for r in top_tickers],
        }
    finally:
        conn.close()


def export_stats():
    safe_print("=" * 60)
    safe_print("STATS EXPORTER v1")
    safe_print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    safe_print("=" * 60)

    output = empty_stats_output()

    try:
        from backend.storage.db_finder import resolve_db_path
        safe_print(f"[DB] Using: {resolve_db_path()}")

        try:
            init_db()
        except Exception as e:
            safe_print(f"[WARN] init_db failed: {e}")

        try:
            output['db_stats'] = get_db_stats()
        except Exception as e:
            safe_print(f"[WARN] get_db_stats failed: {e}")

        db_stats = output['db_stats']
        if db_stats.get('total_predictions', 0) == 0:
            safe_print("[INFO] No predictions yet — writing valid empty stats JSON")
        else:
            for label, fn, key in [
                ('all_time', lambda: calculate_accuracy_metrics('all_time'), 'metrics_all_time'),
                ('weekly', lambda: calculate_accuracy_metrics('weekly'), 'metrics_weekly'),
                ('daily', lambda: calculate_accuracy_metrics('daily'), 'metrics_daily'),
            ]:
                try:
                    output[key] = fn() or output[key]
                except Exception as e:
                    safe_print(f"[WARN] {label} metrics failed: {e}")
            try:
                output['recent_predictions'] = get_recent_predictions_simple(15)
                output['top_winners'] = get_top_winners(10)
                output['top_losers'] = get_top_losers(10)
                output['by_sector'] = get_predictions_by_sector()
                output['by_run_type'] = get_predictions_by_run_type()
                output['by_date'] = get_predictions_by_date()
                output['signals_summary'] = get_signals_summary()
            except Exception as e:
                safe_print(f"[WARN] detail queries failed: {e}")

        try:
            from backend.analytics.regime_analytics import build_calibration_dashboard
            output['calibration_dashboard'] = build_calibration_dashboard()
        except Exception as e:
            safe_print(f"[WARN] calibration dashboard failed: {e}")
            output['calibration_dashboard'] = {'status': 'degraded', 'reason': str(e)}

        output['last_updated'] = datetime.now(timezone.utc).isoformat()
        output['generation_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        write_stats_output(output)
        safe_print(f"\n[OK] Saved {OUTPUT_FILE}")
        safe_print(f"  Predictions: {db_stats.get('total_predictions', 0)}")
        safe_print("=" * 60)
        return output

    except Exception as e:
        import traceback
        safe_print(f"[WARN] Stats export failed: {e}")
        traceback.print_exc()
        write_stats_output(output)
        safe_print(f"[OK] Wrote fallback stats to {OUTPUT_FILE}")
        return output


if __name__ == "__main__":
    print("[STATS] stats_exporter.py __main__ running export_stats()")
    try:
        export_stats()
    except Exception as e:
        import traceback
        safe_print(f"[FATAL] {e}")
        try:
            traceback.print_exc()
        except Exception:
            pass
        try:
            write_stats_output(empty_stats_output())
            safe_print(f"[STATS] Wrote emergency empty stats to {OUTPUT_FILE}")
        except Exception:
            pass