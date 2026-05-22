"""
NSE CORPORATE ANNOUNCEMENTS TRACKER
Zero-latency scraper for live exchange filings using session/cookie spoofing.
Bypasses NSE firewall to get earnings, dividends, and resignations instantly.
"""

import os
import json
import requests
import time
from datetime import datetime, timezone
from pathlib import Path

# ============================================================
# TARGET ENDPOINTS & HEADERS
# ============================================================
BASE_URL = 'https://www.nseindia.com'
API_URL = 'https://www.nseindia.com/api/corporate-announcements?index=equities'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Referer': 'https://www.nseindia.com/companies-listing/corporate-filings-announcements'
}

OUTPUT_FILE = Path(__file__).parent.parent / 'data' / 'nse_announcements.json'

def fetch_nse_announcements():
    print("=" * 60)
    print("NSE CORPORATE ANNOUNCEMENTS - Zero Latency API")
    print("=" * 60)
    
    session = requests.Session()
    session.headers.update(HEADERS)
    
    try:
        # STEP 1: The "Knock" (Get the security cookies)
        print("[1/3] Spoofing browser session on NSE Homepage...")
        session.get(BASE_URL, timeout=10)
        time.sleep(2) # Brief pause to mimic human loading time
        
        # STEP 2: The "Heist" (Hit the hidden JSON API)
        print("[2/3] Fetching live corporate filings...")
        response = session.get(API_URL, timeout=15)
        
        if response.status_code != 200:
            print(f"[ERROR] NSE Firewall blocked request: HTTP {response.status_code}")
            return None
            
        data = response.json()
        
        # STEP 3: The "Extraction" (Filter for high-impact news)
        print("[3/3] Parsing and filtering data...")
        raw_announcements = data.get('data', [])
        
        parsed_data = []
        for item in raw_announcements[:50]: # Look at the 50 most recent
            subject = item.get('subject', '')
            desc = item.get('desc', '')
            full_text = f"{subject} {desc}".upper()
            
            # Simple keyword scoring for high-impact filings
            impact = "LOW"
            if any(word in full_text for word in ['EARNINGS', 'FINANCIAL RESULTS', 'PROFIT', 'LOSS']):
                impact = "HIGH (Earnings)"
            elif any(word in full_text for word in ['DIVIDEND', 'BONUS', 'SPLIT']):
                impact = "HIGH (Corporate Action)"
            elif any(word in full_text for word in ['RESIGNATION', 'APPOINTMENT', 'DIRECTOR', 'CEO']):
                impact = "MEDIUM (Management)"
            elif any(word in full_text for word in ['ACQUISITION', 'MERGER', 'STAKE']):
                impact = "HIGH (M&A)"
                
            parsed_data.append({
                'symbol': item.get('symbol', ''),
                'company_name': item.get('sm_name', ''),
                'broadcast_time': item.get('an_dt', ''), # Time it hit the exchange
                'subject': subject,
                'details': desc,
                'impact_category': impact,
                # NSE attachments have a specific URL structure
                'attachment_url': f"https://www.nseindia.com/corporate/{item.get('attchmntFile')}" if item.get('attchmntFile') else None
            })
            
        # Sort so highest impact stuff is at the top
        high_impact = [x for x in parsed_data if 'HIGH' in x['impact_category']]
        medium_impact = [x for x in parsed_data if 'MEDIUM' in x['impact_category']]
        
        output = {
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'total_fetched': len(parsed_data),
            'high_impact_count': len(high_impact),
            'latest_high_impact': high_impact[:10],
            'latest_medium_impact': medium_impact[:10],
            'all_recent': parsed_data[:20]
        }
        
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
            
        print("-" * 60)
        print(f"[SUCCESS] Intercepted {len(parsed_data)} live filings. {len(high_impact)} High-Impact events detected.")
        if high_impact:
            print(f"  -> LATEST: {high_impact[0]['symbol']} | {high_impact[0]['impact_category']}")
        print("=" * 60)
        
        return output
        
    except requests.exceptions.Timeout:
        print("[ERROR] NSE connection timed out. They might be throttling.")
    except Exception as e:
        print(f"[ERROR] NSE Tracker failed: {str(e)[:100]}")
        
    return None

if __name__ == '__main__':
    fetch_nse_announcements()