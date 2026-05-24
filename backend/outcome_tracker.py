"""
outcome_tracker.py - v2 COMPLETE REWRITE
==========================================
Evaluates pending predictions by fetching actual market prices.

Logic:
- Predictions stored with entry/target/stop loss
- Fetch prices at 1d, 3d, 7d after prediction date
- Determine WIN/LOSS/NEUTRAL based on:
  * For 'opportunity' (BUY): target hit = WIN, stop hit = LOSS
  * For 'risk' (AVOID): if stock dropped = WIN (correctly avoided), if rose = LOSS
- Updates outcomes table in trading_copilot.db
"""

import os
import sys
import json
import sqlite3
import yfinance as yf
from datetime import datetime, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR.parent / 'data'
DB_PATH = Path(__file__).parent.parent / 'data' / 'trading_copilot.db'

# Thresholds for verdict (when no specific target/SL)
WIN_THRESHOLD_PCT = 2.0      # +2% = WIN
LOSS_THRESHOLD_PCT = -2.0    # -2% = LOSS
RISK_WIN_THRESHOLD = -1.0    # AVOID stock dropped 1%+ = correctly avoided


def add_nse_suffix(ticker):
    """Add .NS suffix for NSE stocks"""
    if not ticker:
        return None
    ticker = ticker.upper().strip()
    
    # Skip if not a real ticker
    if ticker in ['UNKNOWN', 'N/A', 'NONE', '']:
        return None
    
    # Already has suffix
    if '.' in ticker:
        return ticker
    
    return f"{ticker}.NS"


def fetch_price_for_date(ticker, target_date):
    """
    Fetch closing price for a ticker on or near a specific date.
    Returns (price, actual_date_used) or (None, None)
    """
    symbol = add_nse_suffix(ticker)
    if not symbol:
        return None, None
    
    try:
        # Fetch a window around the target date
        start = (target_date - timedelta(days=2)).strftime('%Y-%m-%d')
        end = (target_date + timedelta(days=4)).strftime('%Y-%m-%d')
        
        stock = yf.Ticker(symbol)
        hist = stock.history(start=start, end=end)
        
        if hist.empty:
            return None, None
        
        # Find the closest available date >= target_date
        target_str = target_date.strftime('%Y-%m-%d')
        for date_idx in hist.index:
            if date_idx.strftime('%Y-%m-%d') >= target_str:
                price = float(hist.loc[date_idx, 'Close'])
                actual_date = date_idx.strftime('%Y-%m-%d')
                return price, actual_date
        
        # If target is in future, use last available
        last_idx = hist.index[-1]
        price = float(hist.loc[last_idx, 'Close'])
        actual_date = last_idx.strftime('%Y-%m-%d')
        return price, actual_date
    
    except Exception as e:
        return None, None


def calculate_change_pct(entry, current):
    """Calculate percentage change"""
    if not entry or not current or entry == 0:
        return None
    return round(((current - entry) / entry) * 100, 2)


def determine_verdict(prediction, outcome_data):
    """
    Determine WIN/LOSS/NEUTRAL based on prediction type and price action.
    
    For 'opportunity' (BUY/Accumulate): want price UP
    For 'risk' (AVOID): want price DOWN (you correctly avoided a faller)
    """
    category = (prediction.get('category') or 'opportunity').lower()
    target = prediction.get('target_price')
    stop_loss = prediction.get('stop_loss')
    entry = prediction.get('entry_price') or outcome_data.get('entry_price')
    
    # Get the most relevant change (prefer 7d > 3d > 1d)
    change_7d = outcome_data.get('change_7d_pct')
    change_3d = outcome_data.get('change_3d_pct')
    change_1d = outcome_data.get('change_1d_pct')
    
    # Use the most recent available
    change_pct = change_7d if change_7d is not None else (change_3d if change_3d is not None else change_1d)
    
    if change_pct is None:
        return 'PENDING'
    
    # Check max gain/loss for target/stop hits
    max_gain = outcome_data.get('max_gain_pct') or change_pct
    max_loss = outcome_data.get('max_loss_pct') or change_pct
    
    target_hit = 0
    stop_hit = 0
    
    if category == 'opportunity':
        # BUY logic: want price UP
        
        # Check target hit (if target was specified)
        if target and entry and target > entry:
            target_pct_needed = ((target - entry) / entry) * 100
            if max_gain and max_gain >= target_pct_needed:
                target_hit = 1
        
        # Check stop loss hit
        if stop_loss and entry and stop_loss < entry:
            stop_pct_needed = ((stop_loss - entry) / entry) * 100
            if max_loss and max_loss <= stop_pct_needed:
                stop_hit = 1
        
        # Determine verdict
        if target_hit:
            return 'WIN', target_hit, stop_hit
        elif stop_hit:
            return 'LOSS', target_hit, stop_hit
        elif change_pct >= WIN_THRESHOLD_PCT:
            return 'WIN', target_hit, stop_hit
        elif change_pct <= LOSS_THRESHOLD_PCT:
            return 'LOSS', target_hit, stop_hit
        else:
            return 'NEUTRAL', target_hit, stop_hit
    
    else:  # category == 'risk'
        # AVOID logic: stock should DROP for us to be "right"
        
        if change_pct <= RISK_WIN_THRESHOLD:
            # Stock dropped, we correctly avoided it = WIN
            return 'WIN', target_hit, stop_hit
        elif change_pct >= 2.0:
            # Stock rose 2%+ — we missed an opportunity = LOSS
            return 'LOSS', target_hit, stop_hit
        else:
            return 'NEUTRAL', target_hit, stop_hit


def evaluate_pending_outcomes(verbose=True):
    """Main function: evaluate all pending outcomes"""
    
    if not DB_PATH.exists():
        print(f"[ERROR] Database not found: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get all pending outcomes that link to predictions
    cursor.execute('''
        SELECT 
            o.id as outcome_id,
            o.ticker, o.prediction_date, o.entry_price,
            o.price_1d, o.price_3d, o.price_7d,
            o.source_id, o.source_type,
            p.target_price, p.stop_loss, p.category, p.recommendation,
            p.confidence, p.sector
        FROM outcomes o
        LEFT JOIN predictions p ON o.source_id = p.id AND o.source_type = 'prediction'
        WHERE o.verdict = 'PENDING'
        ORDER BY o.prediction_date ASC
    ''')
    
    pending = [dict(r) for r in cursor.fetchall()]
    
    print("=" * 60)
    print(f"OUTCOME TRACKER v2")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print(f"\nFound {len(pending)} PENDING outcomes to evaluate")
    
    if not pending:
        print("Nothing to evaluate!")
        conn.close()
        return
    
    today = datetime.now().date()
    stats = {'evaluated': 0, 'wins': 0, 'losses': 0, 'neutrals': 0, 'still_pending': 0, 'errors': 0}
    
    for i, outcome in enumerate(pending, 1):
        ticker = outcome['ticker']
        pred_date_str = outcome['prediction_date']
        entry = outcome['entry_price']
        
        if not ticker or not pred_date_str:
            stats['errors'] += 1
            continue
        
        try:
            pred_date = datetime.strptime(pred_date_str, '%Y-%m-%d').date()
        except:
            stats['errors'] += 1
            continue
        
        days_elapsed = (today - pred_date).days

        if verbose:
            print(f"\n[{i}/{len(pending)}] {ticker} (predicted {pred_date_str}, {days_elapsed}d ago)")

        # Need at least 1 full trading day before evaluating
        if days_elapsed < 1:
            if verbose:
                print("  [SKIP] Too recent — waiting for 1d price data")
            stats['still_pending'] += 1
            continue

        # Backfill missing entry price from market data on prediction date
        if not entry:
            entry, _ = fetch_price_for_date(ticker, pred_date)
            if entry:
                cursor.execute(
                    'UPDATE outcomes SET entry_price = ? WHERE id = ?',
                    (entry, outcome['outcome_id'])
                )
            else:
                if verbose:
                    print("  [SKIP] No entry price available")
                stats['errors'] += 1
                continue
        
        # Fetch prices for 1d, 3d, 7d windows
        price_1d, date_1d = fetch_price_for_date(ticker, pred_date + timedelta(days=1))
        price_3d, date_3d = None, None
        price_7d, date_7d = None, None
        
        if days_elapsed >= 3:
            price_3d, date_3d = fetch_price_for_date(ticker, pred_date + timedelta(days=3))
        
        if days_elapsed >= 7:
            price_7d, date_7d = fetch_price_for_date(ticker, pred_date + timedelta(days=7))
        
        # Calculate changes
        change_1d = calculate_change_pct(entry, price_1d) if price_1d else None
        change_3d = calculate_change_pct(entry, price_3d) if price_3d else None
        change_7d = calculate_change_pct(entry, price_7d) if price_7d else None
        
        # Calculate max gain/loss (using available data)
        all_prices = [p for p in [price_1d, price_3d, price_7d] if p]
        if all_prices and entry:
            max_price = max(all_prices)
            min_price = min(all_prices)
            max_gain = round(((max_price - entry) / entry) * 100, 2)
            max_loss = round(((min_price - entry) / entry) * 100, 2)
        else:
            max_gain = None
            max_loss = None
        
        # Determine verdict
        outcome_data = {
            'entry_price': entry,
            'change_1d_pct': change_1d,
            'change_3d_pct': change_3d,
            'change_7d_pct': change_7d,
            'max_gain_pct': max_gain,
            'max_loss_pct': max_loss
        }
        
        verdict_result = determine_verdict(outcome, outcome_data)

        if isinstance(verdict_result, tuple):
            verdict, target_hit, stop_hit = verdict_result
        else:
            verdict = verdict_result
            target_hit, stop_hit = 0, 0

        # Keep PENDING if we still lack usable price movement data
        if verdict == 'PENDING' and change_1d is None and change_3d is None and change_7d is None:
            if verbose:
                print("  [SKIP] Price data not available yet")
            stats['still_pending'] += 1
            continue
        
        # Update DB
        cursor.execute('''
            UPDATE outcomes
            SET price_1d = ?, change_1d_pct = ?,
                price_3d = ?, change_3d_pct = ?,
                price_7d = ?, change_7d_pct = ?,
                max_gain_pct = ?, max_loss_pct = ?,
                target_hit = ?, stop_loss_hit = ?,
                verdict = ?, last_checked = ?
            WHERE id = ?
        ''', (
            price_1d, change_1d,
            price_3d, change_3d,
            price_7d, change_7d,
            max_gain, max_loss,
            target_hit, stop_hit,
            verdict, datetime.now().isoformat(),
            outcome['outcome_id']
        ))
        
        # Update stats
        if verdict == 'WIN':
            stats['wins'] += 1
        elif verdict == 'LOSS':
            stats['losses'] += 1
        elif verdict == 'NEUTRAL':
            stats['neutrals'] += 1
        else:
            stats['still_pending'] += 1
        
        stats['evaluated'] += 1
        
        if verbose:
            change_str = ""
            if change_7d is not None:
                change_str = f"7d: {change_7d:+.2f}%"
            elif change_3d is not None:
                change_str = f"3d: {change_3d:+.2f}%"
            elif change_1d is not None:
                change_str = f"1d: {change_1d:+.2f}%"
            
            verdict_emoji = {'WIN': '✅', 'LOSS': '❌', 'NEUTRAL': '⚪', 'PENDING': '⏸️'}.get(verdict, '?')
            print(f"  {verdict_emoji} {verdict} | Entry: Rs.{entry} | {change_str}")
    
    conn.commit()
    conn.close()
    
    # Summary
    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)
    print(f"  Total processed: {len(pending)}")
    print(f"  ✅ Wins: {stats['wins']}")
    print(f"  ❌ Losses: {stats['losses']}")
    print(f"  ⚪ Neutrals: {stats['neutrals']}")
    print(f"  ⏸️ Still pending (too recent): {stats['still_pending']}")
    print(f"  ⚠️ Errors: {stats['errors']}")
    
    evaluated = stats['wins'] + stats['losses']
    if evaluated > 0:
        win_rate = (stats['wins'] / evaluated) * 100
        print(f"\n  📊 Win Rate: {win_rate:.1f}% ({stats['wins']}/{evaluated})")
    
    print("=" * 60)
    
    return stats


def evaluate_signals_outcomes(verbose=True):
    """Also evaluate scanner signal outcomes"""
    
    if not DB_PATH.exists():
        return
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            o.id as outcome_id,
            o.ticker, o.prediction_date, o.entry_price,
            o.source_id,
            s.direction, s.strength, s.sector
        FROM outcomes o
        INNER JOIN signals s ON o.source_id = s.id AND o.source_type = 'signal'
        WHERE o.verdict = 'PENDING'
        ORDER BY o.prediction_date ASC
    ''')
    
    pending = [dict(r) for r in cursor.fetchall()]
    
    print(f"\n[SIGNALS] Evaluating {len(pending)} pending signal outcomes...")
    
    today = datetime.now().date()
    sig_stats = {'wins': 0, 'losses': 0, 'neutrals': 0, 'pending': 0}
    
    for outcome in pending:
        ticker = outcome['ticker']
        pred_date_str = outcome['prediction_date']
        entry = outcome['entry_price']
        direction = outcome.get('direction', 'BULLISH')
        
        if not ticker or not pred_date_str or not entry:
            continue
        
        try:
            pred_date = datetime.strptime(pred_date_str, '%Y-%m-%d').date()
        except:
            continue
        
        days_elapsed = (today - pred_date).days
        if days_elapsed < 0:
            sig_stats['pending'] += 1
            continue
        
        # Fetch prices
        price_1d, _ = fetch_price_for_date(ticker, pred_date + timedelta(days=1))
        price_3d, _ = (fetch_price_for_date(ticker, pred_date + timedelta(days=3)) if days_elapsed >= 3 else (None, None))
        price_7d, _ = (fetch_price_for_date(ticker, pred_date + timedelta(days=7)) if days_elapsed >= 7 else (None, None))
        
        change_1d = calculate_change_pct(entry, price_1d) if price_1d else None
        change_3d = calculate_change_pct(entry, price_3d) if price_3d else None
        change_7d = calculate_change_pct(entry, price_7d) if price_7d else None
        
        change_pct = change_7d if change_7d is not None else (change_3d if change_3d is not None else change_1d)
        
        if change_pct is None:
            continue
        
        # For signals: BULLISH should go UP, BEARISH should go DOWN
        if direction == 'BULLISH':
            verdict = 'WIN' if change_pct >= 2 else ('LOSS' if change_pct <= -2 else 'NEUTRAL')
        else:  # BEARISH
            verdict = 'WIN' if change_pct <= -2 else ('LOSS' if change_pct >= 2 else 'NEUTRAL')
        
        all_prices = [p for p in [price_1d, price_3d, price_7d] if p]
        if all_prices and entry:
            max_gain = round(((max(all_prices) - entry) / entry) * 100, 2)
            max_loss = round(((min(all_prices) - entry) / entry) * 100, 2)
        else:
            max_gain = None
            max_loss = None
        
        cursor.execute('''
            UPDATE outcomes
            SET price_1d = ?, change_1d_pct = ?,
                price_3d = ?, change_3d_pct = ?,
                price_7d = ?, change_7d_pct = ?,
                max_gain_pct = ?, max_loss_pct = ?,
                verdict = ?, last_checked = ?
            WHERE id = ?
        ''', (
            price_1d, change_1d,
            price_3d, change_3d,
            price_7d, change_7d,
            max_gain, max_loss,
            verdict, datetime.now().isoformat(),
            outcome['outcome_id']
        ))
        
        sig_stats[verdict.lower() + ('s' if verdict != 'PENDING' else '')] += 1 if verdict in ['WIN', 'LOSS', 'NEUTRAL'] else 0
        if verdict == 'WIN':
            sig_stats['wins'] += 1
        elif verdict == 'LOSS':
            sig_stats['losses'] += 1
        elif verdict == 'NEUTRAL':
            sig_stats['neutrals'] += 1
    
    conn.commit()
    conn.close()
    
    print(f"  ✅ Wins: {sig_stats['wins']} | ❌ Losses: {sig_stats['losses']} | ⚪ Neutral: {sig_stats['neutrals']} | ⏸️ Pending: {sig_stats['pending']}")
    
    return sig_stats


if __name__ == "__main__":
    print("\n[STAGE 1] Evaluating prediction outcomes...")
    evaluate_pending_outcomes(verbose=True)
    
    print("\n[STAGE 2] Evaluating signal outcomes...")
    evaluate_signals_outcomes(verbose=False)
    
    print("\n[DONE] All pending outcomes processed.")