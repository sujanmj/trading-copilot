"""
Global Markets Collector v3 - With Commodities & Currencies
Tracks: USA, Europe, Asia indices + Big Tech + Commodities + FX

v3 Changes:
- Added COMMODITIES group (Gold, Silver, Crude, Copper, NatGas)
- Added CURRENCIES group (USD/INR, EUR/INR, etc.)
- Added INDIA_ETFS group (GOLDBEES, SILVERBEES, etc.)
"""

import os
os.environ['PYTHONIOENCODING'] = 'utf-8'

import yfinance as yf
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')


def safe_print(text):
    try:
        print(text)
    except (UnicodeEncodeError, ValueError):
        try:
            print(text.encode('ascii', errors='replace').decode('ascii'))
        except Exception:
            pass


# ============================================================
# CONFIGURATION - All Markets Tracked
# ============================================================

MARKETS = {
    'USA_INDICES': {
        'S&P 500': '^GSPC',
        'NASDAQ': '^IXIC',
        'DOW JONES': '^DJI',
        'Russell 2000': '^RUT',
        'VIX (Fear)': '^VIX',
    },
    'USA_BIGTECH': {
        'Apple': 'AAPL',
        'Microsoft': 'MSFT',
        'NVIDIA': 'NVDA',
        'Meta': 'META',
        'Google': 'GOOGL',
        'Amazon': 'AMZN',
        'Tesla': 'TSLA',
    },
    'EUROPE_INDICES': {
        'FTSE 100': '^FTSE',
        'DAX (Germany)': '^GDAXI',
        'CAC 40 (France)': '^FCHI',
        'STOXX 50': '^STOXX50E',
    },
    'ASIA_INDICES': {
        'Nikkei (Japan)': '^N225',
        'Hang Seng (HK)': '^HSI',
        'Shanghai': '000001.SS',
        'KOSPI (Korea)': '^KS11',
        'TSX (Canada)': '^GSPTSE',
    },
    # NEW v3: COMMODITIES
    'COMMODITIES': {
        'Gold (Spot)': 'GC=F',
        'Silver (Spot)': 'SI=F',
        'Crude Oil (WTI)': 'CL=F',
        'Brent Crude': 'BZ=F',
        'Natural Gas': 'NG=F',
        'Copper': 'HG=F',
        'Platinum': 'PL=F',
        'Palladium': 'PA=F',
    },
    # NEW v3: CURRENCIES
    'CURRENCIES': {
        'USD/INR': 'INR=X',
        'EUR/INR': 'EURINR=X',
        'GBP/INR': 'GBPINR=X',
        'JPY/INR': 'JPYINR=X',
        'DXY (Dollar Index)': 'DX-Y.NYB',
    },
    # NEW v3: INDIA-LISTED COMMODITY ETFs
    'INDIA_COMMODITY_ETFS': {
        'Gold ETF (GOLDBEES)': 'GOLDBEES.NS',
        'Silver ETF (SILVERBEES)': 'SILVERBEES.NS',
        'Gold ETF (HDFC)': 'HDFCGOLD.NS',
        'Gold ETF (SBI)': 'SBIGOLD.NS',
    },
    # NEW v3: CRYPTO (optional but useful)
    'CRYPTO': {
        'Bitcoin': 'BTC-USD',
        'Ethereum': 'ETH-USD',
    },
}


# Alert thresholds for commodities (different from stocks)
ALERT_THRESHOLDS = {
    'NORMAL_STOCK': 1.5,        # 1.5%+ for stocks/indices
    'COMMODITY': 1.0,           # 1%+ for commodities (more volatile narrative)
    'CURRENCY': 0.3,            # 0.3%+ for FX (very stable usually)
    'CRYPTO': 3.0,              # 3%+ for crypto (very volatile)
}


# ============================================================
# DATA FETCHING
# ============================================================

def fetch_market_data(symbol, name):
    """Fetch latest data for a single symbol"""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period='5d', interval='1d')
        
        if hist is None or hist.empty:
            return None
        
        # Get latest close and previous close
        latest = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) >= 2 else latest
        
        current_price = float(latest['Close'])
        prev_close = float(prev['Close'])
        
        if prev_close == 0:
            return None
        
        change_percent = ((current_price - prev_close) / prev_close) * 100
        
        return {
            'name': name,
            'symbol': symbol,
            'price': round(current_price, 2),
            'prev_close': round(prev_close, 2),
            'change_percent': round(change_percent, 2),
            'high': round(float(latest['High']), 2),
            'low': round(float(latest['Low']), 2),
            'volume': int(latest['Volume']) if 'Volume' in latest else 0,
        }
    except Exception as e:
        return None


# ============================================================
# SENTIMENT ANALYSIS
# ============================================================

def calculate_regional_sentiment(group_data):
    """Calculate average sentiment for a market group"""
    if not group_data:
        return {'mood': 'UNKNOWN', 'average_change': 0}
    
    changes = [v.get('change_percent', 0) for v in group_data.values() if v]
    if not changes:
        return {'mood': 'UNKNOWN', 'average_change': 0}
    
    avg = sum(changes) / len(changes)
    
    if avg > 1.0:
        mood = 'BULLISH'
    elif avg > 0.3:
        mood = 'POSITIVE'
    elif avg > -0.3:
        mood = 'NEUTRAL'
    elif avg > -1.0:
        mood = 'NEGATIVE'
    else:
        mood = 'BEARISH'
    
    return {
        'mood': mood,
        'average_change': round(avg, 2),
        'symbols_count': len(changes),
    }


def detect_alerts(all_markets):
    """Find unusual movements across all markets"""
    alerts = []
    
    for group_name, symbols in all_markets.items():
        # Choose threshold based on group
        if 'COMMODIT' in group_name or 'INDIA_COMMODITY' in group_name:
            threshold = ALERT_THRESHOLDS['COMMODITY']
        elif 'CURRENC' in group_name:
            threshold = ALERT_THRESHOLDS['CURRENCY']
        elif 'CRYPTO' in group_name:
            threshold = ALERT_THRESHOLDS['CRYPTO']
        else:
            threshold = ALERT_THRESHOLDS['NORMAL_STOCK']
        
        for name, data in symbols.items():
            if not data:
                continue
            change = data.get('change_percent', 0)
            
            if abs(change) >= threshold:
                # Severity classification
                if abs(change) >= threshold * 3:
                    severity = 'MAJOR'
                elif abs(change) >= threshold * 2:
                    severity = 'SIGNIFICANT'
                else:
                    severity = 'NOTABLE'
                
                direction = 'UP' if change >= 0 else 'DOWN'
                
                alerts.append({
                    'name': name,
                    'group': group_name,
                    'change_percent': change,
                    'direction': direction,
                    'severity': severity,
                    'price': data.get('price'),
                    'message': f"[{severity}] {name} ({group_name}) moved {direction} {abs(change):.2f}%",
                })
    
    # Sort by severity then magnitude
    severity_order = {'MAJOR': 3, 'SIGNIFICANT': 2, 'NOTABLE': 1}
    alerts.sort(key=lambda x: (-severity_order.get(x['severity'], 0), 
                               -abs(x['change_percent'])))
    
    return alerts


# ============================================================
# MAIN COLLECTOR
# ============================================================

def collect_all_markets():
    safe_print("=" * 60)
    safe_print("GLOBAL MARKETS COLLECTOR v3 (with Commodities)")
    safe_print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    safe_print("=" * 60)
    
    all_markets = {}
    sentiment = {}
    total_symbols = 0
    
    for group_name, symbols_dict in MARKETS.items():
        safe_print(f"\n[FETCH] {group_name} ({len(symbols_dict)} symbols)...")
        
        group_data = {}
        for name, symbol in symbols_dict.items():
            data = fetch_market_data(symbol, name)
            if data:
                group_data[name] = data
                total_symbols += 1
        
        all_markets[group_name] = group_data
        
        # Calculate sentiment for this group
        sentiment_key = group_name.lower().replace('_indices', '').replace('_', ' ').strip()
        sentiment[sentiment_key] = calculate_regional_sentiment(group_data)
        
        # Print group summary
        if group_data:
            avg = sentiment[sentiment_key].get('average_change', 0)
            mood = sentiment[sentiment_key].get('mood', '?')
            safe_print(f"  [{mood}] avg: {avg:+.2f}% ({len(group_data)} symbols)")
    
    # Detect unusual movements
    alerts = detect_alerts(all_markets)
    
    if alerts:
        safe_print(f"\n[ALERTS] Found {len(alerts)} unusual movements:")
        for a in alerts[:10]:
            try:
                safe_print(f"  {a['message']}")
            except:
                pass
    
    # Build output
    output = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'collection_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'markets': all_markets,
        'sentiment': sentiment,
        'alerts': alerts,
        'total_symbols': total_symbols,
        'groups': list(MARKETS.keys()),
    }
    
    # Save
    output_file = Path(__file__).parent.parent / 'data' / 'global_markets.json'
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    
    safe_print(f"\nSaved to: {output_file}")
    safe_print(f"Total symbols tracked: {total_symbols}")
    safe_print("=" * 60)
    safe_print("Done!")
    
    return output


if __name__ == "__main__":
    try:
        collect_all_markets()
    except Exception as e:
        import traceback
        safe_print(f"[FATAL] {e}")
        traceback.print_exc()