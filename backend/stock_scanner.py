"""
NSE Stock Scanner v1 - Path C
Detects unusual price/volume action across NSE Top 500

Signals:
- VOLUME_SPIKE: Today's volume > 2x avg(20-day)
- BREAKOUT: Price breaks above 20-day high
- BREAKDOWN: Price breaks below 20-day low
- GAP_UP / GAP_DOWN: Open gaps >2% from prev close
- SECTOR_ROTATION: Entire sectors moving together
- CORRELATION_BREAK: Stock moves opposite to its sector

Cross-references with other tiers (govt, news, reddit) downstream.
"""

import yfinance as yf
import json
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

# Add current dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from nse_top500 import (
    get_all_tickers,
    get_yahoo_symbols,
    get_ticker_to_sector_map,
    NSE_BY_SECTOR,
)

# ============================================================
# CONFIGURATION
# ============================================================

# Volume thresholds
VOLUME_SPIKE_MULTIPLIER = 2.0       # Today vol > 2x avg
VOLUME_STRONG_MULTIPLIER = 3.0      # Strong signal threshold

# Price thresholds
GAP_THRESHOLD_PERCENT = 2.0         # Gap up/down threshold
BIG_MOVE_PERCENT = 3.0              # Significant intraday move
MAJOR_MOVE_PERCENT = 5.0            # Major move (alert level)

# Lookback periods
LOOKBACK_DAYS = 30                  # Historical window
BREAKOUT_LOOKBACK = 20              # Days for breakout/breakdown calc
AVG_VOLUME_DAYS = 20                # Days for avg volume calc

# Sector rotation
SECTOR_MOVE_THRESHOLD = 1.0         # Avg sector move >1% = signal
SECTOR_MIN_STOCKS = 3               # Need at least 3 stocks per sector

# Batch settings (yfinance can choke on too many at once)
BATCH_SIZE = 50
BATCH_DELAY = 1                     # seconds between batches

# Output
OUTPUT_FILE = Path(__file__).parent.parent / 'data' / 'scanner_data.json'

# ============================================================
# DATA FETCHING
# ============================================================

def fetch_batch(symbols, period='1mo'):
    """Fetch OHLCV for a batch of symbols using yfinance"""
    try:
        # yfinance can take a list - much faster than one-by-one
        data = yf.download(
            tickers=symbols,
            period=period,
            interval='1d',
            group_by='ticker',
            auto_adjust=True,
            progress=False,
            threads=True,
            timeout=20,
        )
        return data
    except Exception as e:
        print(f"  [ERROR] Batch fetch failed: {e}")
        return None


def parse_ticker_data(ticker, ticker_data):
    """Extract metrics from a single ticker's historical data"""
    try:
        if ticker_data is None or ticker_data.empty:
            return None
        
        # Drop rows with NaN
        df = ticker_data.dropna()
        if len(df) < 5:
            return None
        
        # Latest day
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else latest
        
        current_price = float(latest['Close'])
        prev_close = float(prev['Close'])
        today_open = float(latest['Open'])
        today_high = float(latest['High'])
        today_low = float(latest['Low'])
        today_volume = float(latest['Volume'])
        
        # Skip illiquid (no volume) stocks
        if today_volume == 0:
            return None
        
        # Change %
        change_percent = ((current_price - prev_close) / prev_close) * 100 if prev_close > 0 else 0
        
        # Gap %
        gap_percent = ((today_open - prev_close) / prev_close) * 100 if prev_close > 0 else 0
        
        # 20-day metrics (use available data if less than 20 days)
        lookback = df.tail(BREAKOUT_LOOKBACK + 1).iloc[:-1]  # Exclude today
        if len(lookback) < 5:
            return None
        
        avg_volume = float(lookback['Volume'].mean())
        max_high_20d = float(lookback['High'].max())
        min_low_20d = float(lookback['Low'].min())
        
        # Volume ratio
        volume_ratio = today_volume / avg_volume if avg_volume > 0 else 0
        
        return {
            'ticker': ticker,
            'price': round(current_price, 2),
            'prev_close': round(prev_close, 2),
            'change_percent': round(change_percent, 2),
            'gap_percent': round(gap_percent, 2),
            'open': round(today_open, 2),
            'high': round(today_high, 2),
            'low': round(today_low, 2),
            'volume': int(today_volume),
            'avg_volume_20d': int(avg_volume),
            'volume_ratio': round(volume_ratio, 2),
            'high_20d': round(max_high_20d, 2),
            'low_20d': round(min_low_20d, 2),
        }
    
    except Exception as e:
        return None


# ============================================================
# SIGNAL DETECTION
# ============================================================

def detect_signals(metrics):
    """Run all signal detectors on a single stock's metrics"""
    if not metrics:
        return []
    
    signals = []
    
    # 1. VOLUME SPIKE
    if metrics['volume_ratio'] >= VOLUME_STRONG_MULTIPLIER:
        signals.append({
            'type': 'VOLUME_SPIKE',
            'strength': 'STRONG',
            'detail': f"{metrics['volume_ratio']:.1f}x avg volume"
        })
    elif metrics['volume_ratio'] >= VOLUME_SPIKE_MULTIPLIER:
        signals.append({
            'type': 'VOLUME_SPIKE',
            'strength': 'MODERATE',
            'detail': f"{metrics['volume_ratio']:.1f}x avg volume"
        })
    
    # 2. BREAKOUT (today's high > 20-day high before today)
    if metrics['high'] > metrics['high_20d']:
        breakout_pct = ((metrics['high'] - metrics['high_20d']) / metrics['high_20d']) * 100
        signals.append({
            'type': 'BREAKOUT',
            'strength': 'STRONG' if breakout_pct > 2 else 'MODERATE',
            'detail': f"Broke 20-day high (Rs.{metrics['high_20d']}) by {breakout_pct:.1f}%"
        })
    
    # 3. BREAKDOWN (today's low < 20-day low before today)
    if metrics['low'] < metrics['low_20d']:
        breakdown_pct = ((metrics['low_20d'] - metrics['low']) / metrics['low_20d']) * 100
        signals.append({
            'type': 'BREAKDOWN',
            'strength': 'STRONG' if breakdown_pct > 2 else 'MODERATE',
            'detail': f"Broke 20-day low (Rs.{metrics['low_20d']}) by {breakdown_pct:.1f}%"
        })
    
    # 4. GAP UP
    if metrics['gap_percent'] >= GAP_THRESHOLD_PERCENT:
        signals.append({
            'type': 'GAP_UP',
            'strength': 'STRONG' if metrics['gap_percent'] > 4 else 'MODERATE',
            'detail': f"Gapped up {metrics['gap_percent']:.1f}%"
        })
    
    # 5. GAP DOWN
    elif metrics['gap_percent'] <= -GAP_THRESHOLD_PERCENT:
        signals.append({
            'type': 'GAP_DOWN',
            'strength': 'STRONG' if metrics['gap_percent'] < -4 else 'MODERATE',
            'detail': f"Gapped down {metrics['gap_percent']:.1f}%"
        })
    
    # 6. MAJOR MOVE (intraday)
    if abs(metrics['change_percent']) >= MAJOR_MOVE_PERCENT:
        signals.append({
            'type': 'MAJOR_MOVE',
            'strength': 'STRONG',
            'detail': f"Moved {metrics['change_percent']:+.1f}% today"
        })
    elif abs(metrics['change_percent']) >= BIG_MOVE_PERCENT:
        signals.append({
            'type': 'BIG_MOVE',
            'strength': 'MODERATE',
            'detail': f"Moved {metrics['change_percent']:+.1f}% today"
        })
    
    return signals


def composite_strength(signals):
    """Score the overall strength when multiple signals overlap"""
    if not signals:
        return 'NONE'
    
    strong_count = sum(1 for s in signals if s['strength'] == 'STRONG')
    moderate_count = sum(1 for s in signals if s['strength'] == 'MODERATE')
    
    # 2+ strong signals = ULTRA
    if strong_count >= 2:
        return 'ULTRA'
    if strong_count >= 1 and moderate_count >= 1:
        return 'STRONG'
    if strong_count >= 1:
        return 'STRONG'
    if moderate_count >= 2:
        return 'MODERATE'
    return 'WEAK'


def signal_direction(metrics, signals):
    """Determine if overall signal is bullish or bearish"""
    bull_signals = ['BREAKOUT', 'GAP_UP']
    bear_signals = ['BREAKDOWN', 'GAP_DOWN']
    
    has_bull = any(s['type'] in bull_signals for s in signals)
    has_bear = any(s['type'] in bear_signals for s in signals)
    
    if has_bull and not has_bear:
        return 'BULLISH'
    if has_bear and not has_bull:
        return 'BEARISH'
    
    # Fallback to price change direction
    if metrics['change_percent'] > 1:
        return 'BULLISH'
    if metrics['change_percent'] < -1:
        return 'BEARISH'
    return 'NEUTRAL'


# ============================================================
# SECTOR ROTATION ANALYSIS (Bonus Feature)
# ============================================================

def analyze_sector_rotation(all_metrics):
    """
    Calculate avg movement per sector to detect rotation patterns
    """
    sector_map = get_ticker_to_sector_map()
    sector_moves = defaultdict(list)
    sector_volumes = defaultdict(list)
    
    for m in all_metrics:
        if not m:
            continue
        sector = sector_map.get(m['ticker'])
        if not sector:
            continue
        sector_moves[sector].append(m['change_percent'])
        sector_volumes[sector].append(m['volume_ratio'])
    
    sector_summary = []
    for sector, moves in sector_moves.items():
        if len(moves) < SECTOR_MIN_STOCKS:
            continue
        
        avg_move = sum(moves) / len(moves)
        avg_volume_ratio = sum(sector_volumes[sector]) / len(sector_volumes[sector])
        
        # Direction
        if avg_move > SECTOR_MOVE_THRESHOLD:
            direction = 'BULLISH'
        elif avg_move < -SECTOR_MOVE_THRESHOLD:
            direction = 'BEARISH'
        else:
            direction = 'NEUTRAL'
        
        # Strength based on volume too
        strength = 'STRONG' if (abs(avg_move) > 2 and avg_volume_ratio > 1.3) else \
                   'MODERATE' if abs(avg_move) > 1 else 'WEAK'
        
        sector_summary.append({
            'sector': sector,
            'avg_change_percent': round(avg_move, 2),
            'avg_volume_ratio': round(avg_volume_ratio, 2),
            'stocks_analyzed': len(moves),
            'direction': direction,
            'strength': strength,
        })
    
    # Sort by absolute move (biggest movers first)
    sector_summary.sort(key=lambda x: abs(x['avg_change_percent']), reverse=True)
    
    return sector_summary


# ============================================================
# CORRELATION BREAKDOWN (Bonus Feature)
# ============================================================

def detect_correlation_breaks(all_metrics, sector_summary):
    """
    Find stocks moving OPPOSITE to their sector
    These are often the most interesting (idiosyncratic news/events)
    """
    sector_map = get_ticker_to_sector_map()
    sector_moves = {s['sector']: s['avg_change_percent'] for s in sector_summary}
    
    breaks = []
    for m in all_metrics:
        if not m:
            continue
        sector = sector_map.get(m['ticker'])
        if not sector or sector not in sector_moves:
            continue
        
        sector_move = sector_moves[sector]
        stock_move = m['change_percent']
        
        # Both moves must be material (>1%)
        if abs(sector_move) < 1 or abs(stock_move) < 1:
            continue
        
        # Opposite signs and material divergence
        if (sector_move > 0 and stock_move < -1) or (sector_move < 0 and stock_move > 1):
            divergence = stock_move - sector_move
            breaks.append({
                'ticker': m['ticker'],
                'sector': sector,
                'stock_change': stock_move,
                'sector_change': sector_move,
                'divergence': round(divergence, 2),
                'volume_ratio': m['volume_ratio'],
                'note': f"Stock {stock_move:+.1f}% vs sector {sector_move:+.1f}%",
            })
    
    # Sort by absolute divergence
    breaks.sort(key=lambda x: abs(x['divergence']), reverse=True)
    return breaks[:15]  # Top 15 divergences


# ============================================================
# MAIN SCANNER
# ============================================================

def run_scanner():
    print("=" * 60)
    print("STOCK SCANNER v1 - NSE Top 500 Universe")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    all_tickers = get_all_tickers()
    yahoo_symbols = [f"{t}.NS" for t in all_tickers]
    
    print(f"[INFO] Scanning {len(all_tickers)} tickers in batches of {BATCH_SIZE}...")
    
    all_metrics = []
    
    # Process in batches
    for i in range(0, len(yahoo_symbols), BATCH_SIZE):
        batch = yahoo_symbols[i:i + BATCH_SIZE]
        batch_tickers = all_tickers[i:i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (len(yahoo_symbols) + BATCH_SIZE - 1) // BATCH_SIZE
        
        print(f"[BATCH {batch_num}/{total_batches}] Fetching {len(batch)} tickers...")
        
        try:
            data = fetch_batch(batch, period='2mo')
            if data is None or data.empty:
                print(f"  [WARN] Empty batch")
                continue
            
            for ticker, ysym in zip(batch_tickers, batch):
                try:
                    if len(batch) == 1:
                        ticker_df = data
                    else:
                        # Multi-ticker: data has MultiIndex columns (ticker, field)
                        if ysym in data.columns.get_level_values(0):
                            ticker_df = data[ysym]
                        else:
                            continue
                    
                    metrics = parse_ticker_data(ticker, ticker_df)
                    if metrics:
                        all_metrics.append(metrics)
                except Exception as e:
                    pass  # Silent skip for individual ticker errors
            
        except Exception as e:
            print(f"  [ERROR] Batch failed: {e}")
        
        time.sleep(BATCH_DELAY)
    
    print(f"\n[INFO] Successfully parsed {len(all_metrics)} stocks")
    
    if not all_metrics:
        print("[ERROR] No data collected. Aborting.")
        return None
    
    # ============================================================
    # SIGNAL DETECTION
    # ============================================================
    print(f"\n[INFO] Running signal detection...")
    
    signals_found = []
    summary_counts = defaultdict(int)
    sector_map = get_ticker_to_sector_map()
    
    for m in all_metrics:
        signals = detect_signals(m)
        if not signals:
            continue
        
        strength = composite_strength(signals)
        direction = signal_direction(m, signals)
        sector = sector_map.get(m['ticker'], 'UNKNOWN')
        
        # Count by signal type
        for sig in signals:
            summary_counts[sig['type']] += 1
        
        signals_found.append({
            'ticker': m['ticker'],
            'sector': sector,
            'price': m['price'],
            'change_percent': m['change_percent'],
            'volume': m['volume'],
            'volume_ratio': m['volume_ratio'],
            'strength': strength,
            'direction': direction,
            'signals': [s['type'] for s in signals],
            'signal_details': signals,
            'high_20d': m['high_20d'],
            'low_20d': m['low_20d'],
            'gap_percent': m['gap_percent'],
        })
    
    # Sort by composite: ULTRA > STRONG > MODERATE > WEAK
    strength_rank = {'ULTRA': 4, 'STRONG': 3, 'MODERATE': 2, 'WEAK': 1, 'NONE': 0}
    signals_found.sort(key=lambda x: (
        -strength_rank.get(x['strength'], 0),
        -abs(x['change_percent']),
        -x['volume_ratio']
    ))
    
    # ============================================================
    # SECTOR ROTATION
    # ============================================================
    print(f"[INFO] Analyzing sector rotation...")
    sector_summary = analyze_sector_rotation(all_metrics)
    
    # ============================================================
    # CORRELATION BREAKDOWNS
    # ============================================================
    print(f"[INFO] Detecting correlation breakdowns...")
    correlation_breaks = detect_correlation_breaks(all_metrics, sector_summary)
    
    # ============================================================
    # CATEGORIZE SIGNALS BY TYPE
    # ============================================================
    by_signal = {
        'volume_spikes': [s for s in signals_found if 'VOLUME_SPIKE' in s['signals']][:15],
        'breakouts': [s for s in signals_found if 'BREAKOUT' in s['signals']][:15],
        'breakdowns': [s for s in signals_found if 'BREAKDOWN' in s['signals']][:15],
        'gap_ups': [s for s in signals_found if 'GAP_UP' in s['signals']][:10],
        'gap_downs': [s for s in signals_found if 'GAP_DOWN' in s['signals']][:10],
        'major_moves': [s for s in signals_found if 'MAJOR_MOVE' in s['signals']][:10],
    }
    
    # ============================================================
    # BUILD OUTPUT
    # ============================================================
    output = {
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'scan_time_local': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'universe': 'NSE Top 500',
        'total_scanned': len(all_metrics),
        'total_signals': len(signals_found),
        'summary': dict(summary_counts),
        'top_signals': signals_found[:30],  # Top 30 by strength
        'by_signal': by_signal,
        'sector_rotation': sector_summary,
        'correlation_breaks': correlation_breaks,
        'meta': {
            'volume_spike_threshold': VOLUME_SPIKE_MULTIPLIER,
            'volume_strong_threshold': VOLUME_STRONG_MULTIPLIER,
            'gap_threshold_pct': GAP_THRESHOLD_PERCENT,
            'major_move_pct': MAJOR_MOVE_PERCENT,
        }
    }
    
    # Save
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    
    # ============================================================
    # PRINT SUMMARY
    # ============================================================
    print("\n" + "=" * 60)
    print("SCAN COMPLETE")
    print("=" * 60)
    print(f"Stocks scanned: {len(all_metrics)}")
    print(f"Signals found: {len(signals_found)}")
    print(f"\nSignal breakdown:")
    for sig_type, count in sorted(summary_counts.items(), key=lambda x: -x[1]):
        print(f"  {sig_type}: {count}")
    
    if signals_found:
        print(f"\nTop 5 strongest signals:")
        for s in signals_found[:5]:
            sigs = ' + '.join(s['signals'][:3])
            print(f"  [{s['strength']}|{s['direction']}] {s['ticker']:12s} {s['change_percent']:+6.2f}% vol:{s['volume_ratio']:.1f}x | {sigs}")
    
    if sector_summary:
        print(f"\nTop sector moves:")
        for s in sector_summary[:5]:
            print(f"  [{s['direction']:7s}|{s['strength']:8s}] {s['sector']:25s} {s['avg_change_percent']:+6.2f}% ({s['stocks_analyzed']} stocks)")
    
    if correlation_breaks:
        print(f"\nTop correlation breaks (stock vs sector divergence):")
        for c in correlation_breaks[:5]:
            print(f"  {c['ticker']:12s} ({c['sector']:20s}) {c['note']}")
    
    print(f"\n[OK] Saved {OUTPUT_FILE}")
    print("=" * 60)
    
    return output


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        run_scanner()
    except KeyboardInterrupt:
        print("\n[INTERRUPTED]")
    except Exception as e:
        import traceback
        print(f"\n[FATAL ERROR] {e}")
        traceback.print_exc()