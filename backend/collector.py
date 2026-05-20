import os
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