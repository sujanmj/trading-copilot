import yfinance as yf
import logging
import warnings
import json
from pathlib import Path
from datetime import datetime, timezone

# ============================================================
# 1. GAG THE SPAM (Data still flows perfectly)
# ============================================================
logging.getLogger('yfinance').setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore", category=FutureWarning)

# ============================================================
# 2. EXACT TIER-1 US INDICES
# ============================================================
GLOBAL_INDICES = {
    'S&P_500': '^GSPC', 
    'NASDAQ': '^IXIC', 
    'DOW_JONES': '^DJI', 
    'CRUDE_OIL': 'CL=F', 
    'GOLD': 'GC=F'
}

OUTPUT_FILE = Path(__file__).resolve().parent.parent.parent / 'data' / 'global_markets.json'

def fetch_global_sentiment():
    print("=" * 60)
    print("GLOBAL MARKETS COLLECTOR v4 - US Overnight Data")
    print("=" * 60)
    
    results = {}
    for name, ticker in GLOBAL_INDICES.items():
        try:
            # progress=False stops the ugly loading bars in your terminal
            data = yf.download(ticker, period="5d", progress=False) 
            
            if len(data) >= 2:
                # Calculate the exact percentage change from yesterday to today
                close_yesterday = float(data['Close'].iloc[-2].item())
                close_today = float(data['Close'].iloc[-1].item())
                pct_change = ((close_today - close_yesterday) / close_yesterday) * 100
                
                results[name] = {
                    "ticker": ticker,
                    "change_pct": round(pct_change, 2),
                    "latest_price": round(close_today, 2)
                }
                print(f"  [OK] {name.ljust(12)} -> {pct_change:+.2f}%")
            else:
                print(f"  [FAIL] {name.ljust(12)} -> Insufficient data")
        except Exception as e:
            print(f"  [ERROR] {name.ljust(12)} -> Fetch failed")

    # Save to JSON so the Master Analyzer / AI can read it
    output = {
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'markets': results
    }
    
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2)
        
    print("-" * 60)
    print(f"[SAVED] Global macro data ready for AI prediction engine.")
    print("=" * 60)

if __name__ == '__main__':
    fetch_global_sentiment()