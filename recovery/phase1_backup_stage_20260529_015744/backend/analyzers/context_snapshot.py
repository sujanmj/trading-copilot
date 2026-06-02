"""
context_snapshot.py - v2
========================
Snapshots market context whenever AI makes predictions.
Stores in: data/trading_history.db (same DB as predictions)
"""

import os
import sys
import json
import sqlite3
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from backend.utils.config import DATA_DIR, DB_PATH

def init_context_table():
    """Create context_snapshots table if not exists"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS context_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id TEXT UNIQUE NOT NULL,
            timestamp TEXT NOT NULL,
            run_type TEXT,
            global_mood TEXT,
            us_change_pct REAL,
            europe_change_pct REAL,
            asia_change_pct REAL,
            nifty_price REAL,
            nifty_change_pct REAL,
            banknifty_change_pct REAL,
            sensex_change_pct REAL,
            top_sectors_json TEXT,
            bottom_sectors_json TEXT,
            news_positive_count INTEGER,
            news_negative_count INTEGER,
            news_neutral_count INTEGER,
            reddit_mood TEXT,
            reddit_confidence INTEGER,
            govt_high_impact_count INTEGER,
            scanner_total_signals INTEGER,
            scanner_ultra_signals INTEGER,
            scanner_bullish_count INTEGER,
            scanner_bearish_count INTEGER,
            raw_context_json TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_snapshot_timestamp 
        ON context_snapshots(timestamp)
    ''')
    
    conn.commit()
    conn.close()
    print("[INIT] context_snapshots table ready in trading_history.db")


def load_json_safe(filename):
    filepath = DATA_DIR / filename
    try:
        if filepath.exists():
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"[WARN] Could not load {filename}: {e}")
        return {}


def capture_snapshot(run_type='manual'):
    """Capture current market context to DB"""
    
    snapshot_id = f"snap_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    timestamp = datetime.now().isoformat()
    
    print(f"\n[SNAPSHOT] Capturing context: {snapshot_id}")
    
    global_data = load_json_safe('global_markets.json')
    india_data = load_json_safe('latest_market_data.json')
    news_data = load_json_safe('news_feed.json')
    reddit_data = load_json_safe('reddit_data.json')
    govt_data = load_json_safe('govt_intelligence.json')
    scanner_data = load_json_safe('scanner_data.json')
    
    global_sentiment = global_data.get('sentiment', {})
    us_data = global_sentiment.get('usa', {})
    europe_data = global_sentiment.get('europe', {})
    asia_data = global_sentiment.get('asia', {})
    
    global_mood = 'NEUTRAL'
    moods = [us_data.get('mood'), europe_data.get('mood'), asia_data.get('mood')]
    bullish_count = sum(1 for m in moods if m in ['BULLISH', 'POSITIVE'])
    bearish_count = sum(1 for m in moods if m in ['BEARISH', 'NEGATIVE'])
    if bullish_count > bearish_count:
        global_mood = 'BULLISH'
    elif bearish_count > bullish_count:
        global_mood = 'BEARISH'
    
    india_prices = india_data.get('prices', {})
    nifty = india_prices.get('NIFTY 50', india_prices.get('NIFTY', {}))
    banknifty = india_prices.get('BANK NIFTY', india_prices.get('BANKNIFTY', {}))
    sensex = india_prices.get('SENSEX', {})
    
    sector_rotation = scanner_data.get('sector_rotation', [])
    top_sectors = [{'sector': s.get('sector'), 'change': s.get('avg_change_percent', 0)} 
                   for s in sector_rotation[:5]]
    bottom_sectors = [{'sector': s.get('sector'), 'change': s.get('avg_change_percent', 0)} 
                      for s in sector_rotation[-5:]] if len(sector_rotation) > 5 else []
    
    sentiment_dist = news_data.get('sentiment_distribution', {})
    reddit_mood_data = reddit_data.get('market_mood', {})
    
    summary = scanner_data.get('summary', {})
    top_signals = scanner_data.get('top_signals', [])
    ultra_count = sum(1 for s in top_signals if s.get('strength') == 'ULTRA')
    bullish_signals = sum(1 for s in top_signals if s.get('direction') == 'BULLISH')
    bearish_signals = sum(1 for s in top_signals if s.get('direction') == 'BEARISH')
    
    raw_context = {
        'global_summary': global_sentiment,
        'india_summary': {
            'nifty': nifty,
            'banknifty': banknifty,
            'sensex': sensex
        },
        'top_sectors': top_sectors,
        'bottom_sectors': bottom_sectors,
        'news_sentiment': sentiment_dist,
        'news_top_stocks': news_data.get('top_stocks', {}),
        'reddit_summary': {
            'mood': reddit_mood_data.get('sentiment'),
            'confidence': reddit_mood_data.get('confidence'),
            'themes': reddit_mood_data.get('themes', []),
            'summary': reddit_mood_data.get('summary', '')[:300]
        },
        'govt_high_impact': govt_data.get('high_impact_count', 0),
        'govt_top_items': [
            {'title': i.get('english_headline', i.get('title', ''))[:150],
             'score': i.get('impact_score'),
             'direction': i.get('direction')}
            for i in govt_data.get('high_impact_items', [])[:3]
        ],
        'scanner_summary': summary,
        'scanner_top_5': [
            {'ticker': s.get('ticker'), 
             'strength': s.get('strength'),
             'direction': s.get('direction'),
             'change_pct': s.get('change_percent')}
            for s in top_signals[:5]
        ]
    }
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO context_snapshots (
                snapshot_id, timestamp, run_type,
                global_mood, us_change_pct, europe_change_pct, asia_change_pct,
                nifty_price, nifty_change_pct, banknifty_change_pct, sensex_change_pct,
                top_sectors_json, bottom_sectors_json,
                news_positive_count, news_negative_count, news_neutral_count,
                reddit_mood, reddit_confidence,
                govt_high_impact_count,
                scanner_total_signals, scanner_ultra_signals,
                scanner_bullish_count, scanner_bearish_count,
                raw_context_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            snapshot_id, timestamp, run_type,
            global_mood,
            us_data.get('average_change', 0),
            europe_data.get('average_change', 0),
            asia_data.get('average_change', 0),
            nifty.get('price', 0),
            nifty.get('change_percent', 0),
            banknifty.get('change_percent', 0),
            sensex.get('change_percent', 0),
            json.dumps(top_sectors),
            json.dumps(bottom_sectors),
            sentiment_dist.get('positive', 0),
            sentiment_dist.get('negative', 0),
            sentiment_dist.get('neutral', 0),
            reddit_mood_data.get('sentiment', 'NEUTRAL'),
            reddit_mood_data.get('confidence', 0),
            govt_data.get('high_impact_count', 0),
            scanner_data.get('total_signals', 0),
            ultra_count,
            bullish_signals,
            bearish_signals,
            json.dumps(raw_context, default=str)
        ))
        
        conn.commit()
        print(f"[SAVED] Snapshot {snapshot_id} stored in trading_history.db")
        print(f"  Global: {global_mood} | Nifty: {nifty.get('change_percent', 0):.2f}%")
        print(f"  News: +{sentiment_dist.get('positive', 0)} -{sentiment_dist.get('negative', 0)}")
        print(f"  Reddit: {reddit_mood_data.get('sentiment', '?')} ({reddit_mood_data.get('confidence', 0)}%)")
        print(f"  Scanner: {scanner_data.get('total_signals', 0)} signals ({ultra_count} ULTRA)")
        
    except Exception as e:
        print(f"[ERROR] Failed to save snapshot: {e}")
    finally:
        conn.close()
    
    return snapshot_id


def get_recent_snapshots(days=7):
    """Get snapshots from last N days for analysis"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM context_snapshots
        WHERE timestamp >= datetime('now', ?)
        ORDER BY timestamp DESC
    ''', (f'-{days} days',))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(r) for r in rows]


def get_snapshot_by_date(date_str):
    """Get snapshot closest to a specific date (YYYY-MM-DD)"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM context_snapshots
        WHERE date(timestamp) = ?
        ORDER BY timestamp DESC
        LIMIT 1
    ''', (date_str,))
    
    row = cursor.fetchone()
    conn.close()
    
    return dict(row) if row else None


if __name__ == "__main__":
    init_context_table()
    
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        print("\n=== TESTING SNAPSHOT CAPTURE ===")
        snapshot_id = capture_snapshot('test')
        print(f"\n[OK] Snapshot saved: {snapshot_id}")
    else:
        print("\nUsage:")
        print("  python context_snapshot.py        # Just init table")
        print("  python context_snapshot.py test   # Capture test snapshot")