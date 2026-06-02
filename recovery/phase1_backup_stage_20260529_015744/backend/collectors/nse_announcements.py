"""
NSE CORPORATE ANNOUNCEMENTS - Zero Latency API
Includes Session/Cookie bypass for NSE's aggressive WAF.
"""
import json
import time
import requests
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_FILE = Path(__file__).resolve().parent.parent.parent / 'data' / 'nse_announcements.json'

def run_nse_tracker():
    print("=" * 60)
    print("NSE CORPORATE ANNOUNCEMENTS - Zero Latency API")
    print("=" * 60)

    # 1. Use a Session to persist cookies across requests
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.nseindia.com/'
    })

    # 2. Hit the homepage FIRST to grab the security cookies
    print("[1/3] Spoofing browser session on NSE Homepage to grab cookies...")
    try:
        session.get("https://www.nseindia.com", timeout=10)
    except Exception as e:
        print(f"[ERROR] Homepage ping failed: {e}")
        return
        
    time.sleep(2)  # CRITICAL: Pause to mimic human behavior

    # 3. Hit the hidden API using the cookies we just stole
    print("[2/3] Fetching live corporate filings...")
    api_url = "https://www.nseindia.com/api/corporate-announcements?index=equities"
    
    try:
        response = session.get(api_url, timeout=10)
        
        try:
            data = response.json()
        except json.JSONDecodeError:
            print("[ERROR] NSE returned HTML instead of JSON. The firewall blocked the request.")
            return

        print("[3/3] Parsing filings...")
        
        # Categorize the data for the AI Brain
        high_impact = []
        medium_impact = []
        
        # The NSE API returns a list under the 'data' key
        # The NSE API sometimes returns a raw list, or a dict with a 'data' key
        filings = data if isinstance(data, list) else data.get('data', [])
        
        for item in filings[:20]: # Check the latest 20
            symbol = item.get('symbol', 'UNKNOWN')
            subject = item.get('subject', '')
            desc = item.get('desc', '')
            
            subject_upper = subject.upper()
            
            # Filter for institutional-grade catalysts
            if any(word in subject_upper for word in ['ACQUISITION', 'MERGER', 'DIVIDEND', 'FINANCIAL RESULTS', 'RESIGNATION', 'SPLIT', 'ALLOTMENT']):
                high_impact.append({
                    'symbol': symbol,
                    'impact_category': 'HIGH',
                    'subject': subject,
                    'description': desc[:200]
                })
            else:
                medium_impact.append({
                    'symbol': symbol,
                    'impact_category': 'MEDIUM',
                    'subject': subject,
                    'description': desc[:200]
                })

        output = {
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'latest_high_impact': high_impact,
            'latest_medium_impact': medium_impact
        }

        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
            
        print(f"[SUCCESS] Scraped {len(high_impact)} High Impact and {len(medium_impact)} Medium Impact filings.")
        print("=" * 60)

    except Exception as e:
        print(f"[ERROR] Request failed: {e}")

if __name__ == "__main__":
    run_nse_tracker()