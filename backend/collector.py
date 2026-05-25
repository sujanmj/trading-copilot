import os
import json
import pyotp
import requests
from pathlib import Path
from dotenv import load_dotenv
from SmartApi import SmartConnect

# Resolve the absolute path to config/keys.env from the current backend directory context
BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent
ENV_PATH = ROOT_DIR / "config" / "keys.env"

# Load the environment keys (override=False protects existing platform vars on Railway)
load_dotenv(dotenv_path=ENV_PATH, override=False)

# Global caches to prevent rate-limiting and redundant logins
_angel_session = None
_instrument_map = {}

def _initialize_angel_one():
    """Handles the automated TOTP login and fetches the NSE instrument tokens."""
    global _angel_session, _instrument_map
    
    api_key = os.getenv("ANGEL_API_KEY")
    client_id = os.getenv("ANGEL_CLIENT_ID")
    pin = os.getenv("ANGEL_PIN")
    totp_secret = os.getenv("ANGEL_TOTP_SECRET")

    if not all([api_key, client_id, pin, totp_secret]):
        print("[!] Angel One credentials missing in config/keys.env")
        return None

    try:
        print("[*] Authenticating with Angel One (Auto-TOTP)...")
        obj = SmartConnect(api_key=api_key)
        
        # Programmatically generate the live 6-digit 2FA token
        live_totp = pyotp.TOTP(totp_secret).now()
        
        data = obj.generateSession(client_id, pin, live_totp)
        if data.get('status') == False:
            print(f"[!] Angel One Login Failed: {data.get('message')}")
            return None
        
        _angel_session = obj
        print("[+] Angel One Authenticated Successfully.")

        if not _instrument_map:
            print("[*] Downloading NSE Instrument Master List...")
            url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
            response = requests.get(url, timeout=15).json()
            
            for item in response:
                if item['exch_seg'] == 'NSE' and '-EQ' in item['symbol']:
                    clean_sym = item['symbol'].replace('-EQ', '')
                    _instrument_map[clean_sym] = item['token']
            print(f"[+] Loaded {len(_instrument_map)} NSE instruments.")
            
    except Exception as e:
        print(f"[!] Angel One initialization error: {str(e)}")
        
    return _angel_session

def fetch_accurate_nse_price(symbol: str) -> float:
    """
    Fetches real-time Last Traded Price (LTP) directly from Angel One API.
    """
    global _angel_session, _instrument_map
    
    if _angel_session is None:
        _initialize_angel_one()
        if _angel_session is None:
            return 0.0

    clean_symbol = symbol.strip().upper().replace('.NS', '').replace('.BO', '')
    
    token = _instrument_map.get(clean_symbol)
    if not token:
        print(f"[!] Token not found in Angel mapping for {clean_symbol}")
        return 0.0

    try:
        res = _angel_session.ltpData("NSE", f"{clean_symbol}-EQ", token)
        
        if res and res.get('status'):
            return float(res['data']['ltp'])
        elif res and res.get('message') == 'Invalid Token':
            print("[*] Angel session expired. Re-authenticating...")
            _angel_session = None
            _initialize_angel_one()
            res = _angel_session.ltpData("NSE", f"{clean_symbol}-EQ", token)
            if res and res.get('status'):
                return float(res['data']['ltp'])
                
        return 0.0
        
    except Exception as e:
        print(f"[!] Error fetching price for {clean_symbol}: {str(e)}")
        return 0.0

def get_stock_price(symbol):
    """Keep function namespace uniform across other caller scripts."""
    return fetch_accurate_nse_price(symbol)


# ============================================================
# INDIA MARKET DATA (yfinance)
# ============================================================

INDIA_SYMBOLS = {
    'NIFTY 50': '^NSEI',
    'SENSEX': '^BSESN',
    'RELIANCE': 'RELIANCE.NS',
    'TCS': 'TCS.NS',
    'HDFCBANK': 'HDFCBANK.NS',
    'INFY': 'INFY.NS',
    'ICICIBANK': 'ICICIBANK.NS',
    'SBIN': 'SBIN.NS',
    'BHARTIARTL': 'BHARTIARTL.NS',
    'ITC': 'ITC.NS',
    'LT': 'LT.NS',
    'AXISBANK': 'AXISBANK.NS',
    'KOTAKBANK': 'KOTAKBANK.NS',
    'BAJAJFINSV': 'BAJAJFINSV.NS',
    'MARUTI': 'MARUTI.NS',
}

OUTPUT_FILE = ROOT_DIR / 'data' / 'latest_market_data.json'


def _fetch_yfinance_once(name, ticker):
    """Single yfinance attempt for one ticker symbol."""
    import yfinance as yf
    print(f"  [FETCH] {name} ({ticker}) via yfinance...")
    stock = yf.Ticker(ticker)
    hist = stock.history(period='5d')
    if hist is None or hist.empty or len(hist) < 1:
        print(f"  [FAIL] {name} ({ticker}): no yfinance history")
        return None
    close = float(hist['Close'].iloc[-1])
    prev = float(hist['Close'].iloc[-2]) if len(hist) >= 2 else close
    change_pct = ((close - prev) / prev * 100) if prev else 0.0
    print(f"  [OK] {name} ({ticker}): Rs.{close:,.2f} ({change_pct:+.2f}%)")
    return {
        'price': round(close, 2),
        'change_percent': round(change_pct, 2),
        'source': f'yfinance:{ticker}',
    }


def fetch_symbol_yfinance(name, ticker):
    """Fetch via yfinance; retry with .BO if .NS fails (404 / empty data)."""
    try:
        row = _fetch_yfinance_once(name, ticker)
        if row:
            return row
        if ticker.endswith('.NS'):
            bo_ticker = ticker[:-3] + '.BO'
            print(f"  [RETRY] {name}: .NS failed, trying BSE {bo_ticker}...")
            return _fetch_yfinance_once(name, bo_ticker)
        return None
    except Exception as e:
        err = str(e).lower()
        print(f"  [FAIL] {name} ({ticker}) yfinance error: {e}")
        if ticker.endswith('.NS') or '404' in err or 'not found' in err:
            bo_ticker = ticker.replace('.NS', '.BO') if '.NS' in ticker else f"{ticker}.BO"
            try:
                print(f"  [RETRY] {name}: trying BSE {bo_ticker}...")
                return _fetch_yfinance_once(name, bo_ticker)
            except Exception as e2:
                print(f"  [FAIL] {name} ({bo_ticker}) also failed: {e2}")
        return None


def collect_india_market_data():
    """Collect India prices — save partial results even if some symbols fail."""
    print("=" * 60)
    print("INDIA MARKET COLLECTOR")
    print(f"Time: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    prices = {}
    ok_count = 0
    fail_count = 0

    for name, ticker in INDIA_SYMBOLS.items():
        row = fetch_symbol_yfinance(name, ticker)
        if row:
            prices[name] = row
            ok_count += 1
        else:
            fail_count += 1

    output = {
        'last_updated': __import__('datetime').datetime.now().isoformat(),
        'prices': prices,
        'symbols_ok': ok_count,
        'symbols_failed': fail_count,
        'total_symbols': len(INDIA_SYMBOLS),
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("-" * 60)
    print(f"[SAVED] {OUTPUT_FILE}")
    print(f"  OK: {ok_count} | Failed: {fail_count} | Total in file: {len(prices)}")
    print("=" * 60)
    return output


if __name__ == '__main__':
    collect_india_market_data()