"""
data_audit.py
==============
Audits prediction database to identify bad data.
SHOWS you the issues, doesn't change anything.
"""

import sqlite3
import sys
from pathlib import Path
from collections import Counter

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR.parent / 'data' / 'trading_history.db'

# Known sector names that AI sometimes incorrectly puts as tickers
NON_TICKER_WORDS = [
    'IT', 'BANK', 'AUTO', 'PHARMA', 'METAL', 'METALS', 'ENERGY', 'CONSUMER',
    'TECH', 'TECHNOLOGY', 'FMCG', 'BANKING', 'FINANCE', 'INFRA', 'CEMENT',
    'POWER', 'OIL', 'GAS', 'STEEL', 'NIFTY', 'SENSEX', 'GOLD', 'SILVER',
    'CRUDE', 'COMMODITIES', 'RETAIL', 'TELECOM', 'MEDIA', 'HEALTHCARE',
    'REALTY', 'CHEMICAL', 'CHEMICALS', 'INFRASTRUCTURE', 'CAPITAL', 'GOODS'
]

def audit():
    if not DB_PATH.exists():
        print("ERROR: DB not found")
        return
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("=" * 70)
    print("DATABASE AUDIT - Identifying bad data")
    print("=" * 70)
    
    # 1. Total counts
    cursor.execute("SELECT COUNT(*) FROM predictions")
    total_pred = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM outcomes")
    total_out = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM signals")
    total_sig = cursor.fetchone()[0]
    
    print(f"\n[BASELINE]")
    print(f"  Total predictions: {total_pred}")
    print(f"  Total outcomes: {total_out}")
    print(f"  Total signals: {total_sig}")
    
    # 2. Find non-ticker words used as tickers
    print(f"\n[ISSUE 1] Sector/category words used as tickers")
    print("-" * 70)
    placeholders = ','.join('?' * len(NON_TICKER_WORDS))
    cursor.execute(f"""
        SELECT ticker, COUNT(*) as count, 
               GROUP_CONCAT(DISTINCT category) as categories
        FROM predictions 
        WHERE UPPER(ticker) IN ({placeholders})
        GROUP BY ticker
        ORDER BY count DESC
    """, NON_TICKER_WORDS)
    
    bad_tickers = cursor.fetchall()
    bad_ticker_count = sum(r['count'] for r in bad_tickers)
    if bad_tickers:
        for row in bad_tickers:
            print(f"  '{row['ticker']}' used {row['count']} times (categories: {row['categories']})")
        print(f"\n  TOTAL BAD TICKER ROWS: {bad_ticker_count}")
    else:
        print("  None found ✅")
    
    # 3. Find predictions with NULL/garbage entry prices
    print(f"\n[ISSUE 2] Outcomes with NULL or garbage entry prices")
    print("-" * 70)
    
    cursor.execute("SELECT COUNT(*) FROM outcomes WHERE entry_price IS NULL")
    null_entry = cursor.fetchone()[0]
    print(f"  NULL entry prices: {null_entry}")
    
    cursor.execute("SELECT ticker, entry_price FROM outcomes WHERE entry_price IS NOT NULL AND entry_price < 5")
    tiny_prices = cursor.fetchall()
    print(f"  Suspicious tiny prices (<Rs.5): {len(tiny_prices)}")
    for row in tiny_prices[:10]:
        print(f"    {row['ticker']}: Rs.{row['entry_price']}")
    
    # 4. Find duplicate predictions
    print(f"\n[ISSUE 3] Duplicate predictions (same ticker, same date, same category)")
    print("-" * 70)
    cursor.execute("""
        SELECT ticker, prediction_date, category, COUNT(*) as cnt
        FROM predictions
        GROUP BY ticker, prediction_date, category
        HAVING cnt > 1
        ORDER BY cnt DESC
    """)
    
    dups = cursor.fetchall()
    if dups:
        for row in dups[:15]:
            print(f"  {row['ticker']} on {row['prediction_date']} ({row['category']}): {row['cnt']} duplicates")
        total_dup_excess = sum(r['cnt'] - 1 for r in dups)
        print(f"\n  TOTAL EXCESS DUPLICATE ROWS: {total_dup_excess}")
    else:
        print("  None found ✅")
    
    # 5. Predictions with no entry price logged
    print(f"\n[ISSUE 4] Predictions with NULL entry_price in predictions table")
    print("-" * 70)
    cursor.execute("SELECT COUNT(*) FROM predictions WHERE entry_price IS NULL")
    null_pred_entry = cursor.fetchone()[0]
    print(f"  Predictions without entry_price: {null_pred_entry}")
    
    # 6. Tickers per category
    print(f"\n[BREAKDOWN] Predictions by category")
    print("-" * 70)
    cursor.execute("""
        SELECT category, COUNT(*) as cnt 
        FROM predictions 
        GROUP BY category
    """)
    for row in cursor.fetchall():
        print(f"  {row['category']}: {row['cnt']}")
    
    # 7. Run types
    print(f"\n[BREAKDOWN] Predictions by run_type")
    print("-" * 70)
    cursor.execute("""
        SELECT run_type, COUNT(*) as cnt 
        FROM predictions 
        GROUP BY run_type
        ORDER BY cnt DESC
    """)
    for row in cursor.fetchall():
        print(f"  {row['run_type'] or 'NULL'}: {row['cnt']}")
    
    # 8. Outcomes evaluation status
    print(f"\n[BREAKDOWN] Outcomes by verdict")
    print("-" * 70)
    cursor.execute("SELECT verdict, COUNT(*) FROM outcomes GROUP BY verdict")
    for row in cursor.fetchall():
        print(f"  {row[0] or 'NULL'}: {row[1]}")
    
    # 9. Top tickers (frequency)
    print(f"\n[BREAKDOWN] Top 15 most-predicted tickers")
    print("-" * 70)
    cursor.execute("""
        SELECT ticker, COUNT(*) as cnt 
        FROM predictions 
        GROUP BY ticker 
        ORDER BY cnt DESC 
        LIMIT 15
    """)
    for row in cursor.fetchall():
        marker = " ⚠️" if row['ticker'].upper() in NON_TICKER_WORDS else ""
        print(f"  {row['ticker']}: {row['cnt']}{marker}")
    
    # 10. Summary
    print(f"\n" + "=" * 70)
    print("AUDIT SUMMARY")
    print("=" * 70)
    
    bad_rows = bad_ticker_count + len(tiny_prices)
    excess_dups = sum(r['cnt'] - 1 for r in dups) if dups else 0
    
    print(f"  Bad ticker rows (sector names): {bad_ticker_count}")
    print(f"  Suspicious entry prices (<Rs.5): {len(tiny_prices)}")
    print(f"  Excess duplicates: {excess_dups}")
    print(f"  NULL entry prices: {null_entry}")
    print(f"  ----------")
    print(f"  Total predictions: {total_pred}")
    estimated_bad = max(bad_ticker_count + len(tiny_prices) + excess_dups, 0)
    print(f"  Estimated bad rows: ~{estimated_bad}")
    print(f"  Estimated clean rows: ~{total_pred - estimated_bad}")
    
    conn.close()
    print("=" * 70)


if __name__ == "__main__":
    audit()