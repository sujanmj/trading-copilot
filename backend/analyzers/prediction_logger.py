"""
Prediction Logger v2.0 - Clean & Robust
========================================
Fixes from v1.5:
- Live price fallback when entry_price not in AI text
- Deduplication check before insert
- Stricter price parsing (rejects garbage like Rs.1.0)
- Better ticker extraction (longest match wins)
- Risk items also get entry_price for evaluation
"""

import os
os.environ['PYTHONIOENCODING'] = 'utf-8'

import sys
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from backend.storage.db_manager import insert_prediction, insert_signal, init_db, DB_PATH

try:
    from backend.utils.nse_top500 import get_all_tickers, get_ticker_to_sector_map
    NSE_TICKERS = set(get_all_tickers())
    SECTOR_MAP = get_ticker_to_sector_map()
except ImportError:
    NSE_TICKERS = set()
    SECTOR_MAP = {}

# Live price via Angel One (shared client — credentials in config/keys.env)
from backend.utils.angel_one_client import fetch_ltp, is_configured

def safe_print(text):
    try:
        print(text)
    except (UnicodeEncodeError, ValueError):
        try:
            print(text.encode('ascii', errors='replace').decode('ascii'))
        except Exception:
            pass


# ============================================================
# CONFIGURATION
# ============================================================

DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'
INTELLIGENCE_FILE = DATA_DIR / 'unified_intelligence.json'
SCANNER_FILE = DATA_DIR / 'scanner_data.json'

COMMODITY_TICKERS = {
    'GOLDBEES', 'SILVERBEES', 'HDFCGOLD', 'SBIGOLD', 'AXISGOLD',
    'NIFTYBEES', 'BANKBEES', 'JUNIORBEES',
}

INDEX_TICKERS = {
    'NIFTY', 'SENSEX', 'BANKNIFTY', 'FINNIFTY', 'NIFTY50', 'NIFTYIT',
}

# Strict blacklist - these are NEVER valid tickers
BLACKLIST_WORDS = {
    'IT', 'BANKING', 'BANKS', 'PHARMA', 'AUTO', 'METALS', 'FMCG',
    'POWER', 'ENERGY', 'GAS', 'TELECOM', 'CHEMICALS',
    'CEMENT', 'TEXTILES', 'AGRI', 'RETAIL', 'INFRA', 'CAPGOODS',
    'REALTY', 'CONSUMER', 'CONSTRUCTION', 'RAILWAYS', 'DEFENCE',
    'HEALTHCARE', 'MEDIA', 'LOGISTICS', 'HOTELS', 'NEW-AGE',
    'TECH', 'NBFC', 'FINANCE', 'INSURANCE',
    'TATA', 'ADANI', 'BAJAJ', 'GODREJ', 'MAHINDRA',
    'STOCKS', 'SECTOR', 'INDEX', 'INDICES', 'MARKET', 'MARKETS',
    'GOLD', 'SILVER', 'CRUDE', 'COPPER',
    'BUY', 'SELL', 'HOLD', 'AVOID', 'WATCH', 'ACCUMULATE',
    'STRONG', 'WEAK', 'BULLISH', 'BEARISH',
    'I', 'A', 'THE', 'OK', 'NEW', 'FOR', 'WHO', 'CEO', 'IPO',
    'GST', 'RBI', 'SEBI', 'FII', 'DII', 'NSE', 'BSE',
    'ETF', 'ETFS', 'PSU', 'PSUS',
    'OIL-LINKED', 'RUPEE-SENSITIVE', 'RATE-SENSITIVE', 'TARIFF-SENSITIVE',
    'EXPORT', 'IMPORT', 'EXPORTERS', 'IMPORTERS',
    # Group names without specific company
    'HDFC',  # Should be HDFCBANK or HDFCLIFE specifically
}

VALID_TICKERS = NSE_TICKERS | COMMODITY_TICKERS | INDEX_TICKERS


def normalize_recommendation(text):
    if not text:
        return 'WATCH'
    text_lower = text.lower()
    if 'strong buy' in text_lower or 'buy' in text_lower:
        return 'BUY'
    if 'accumulate' in text_lower:
        return 'ACCUMULATE'
    if 'sell' in text_lower or 'short' in text_lower:
        return 'SELL'
    if 'avoid' in text_lower:
        return 'AVOID'
    if 'hold' in text_lower:
        return 'HOLD'
    if 'watch' in text_lower or 'monitor' in text_lower:
        return 'WATCH'
    return 'WATCH'


def get_sector_for_ticker(ticker):
    if not ticker:
        return 'UNKNOWN'
    if ticker in SECTOR_MAP:
        return SECTOR_MAP[ticker]
    if ticker in COMMODITY_TICKERS:
        if 'GOLD' in ticker:
            return 'COMMODITY_GOLD'
        if 'SILVER' in ticker:
            return 'COMMODITY_SILVER'
        if 'NIFTY' in ticker or 'BEES' in ticker:
            return 'INDEX_ETF'
    if ticker in INDEX_TICKERS:
        return 'INDEX'
    return 'UNKNOWN'


def is_valid_ticker(ticker):
    if not ticker or len(ticker) < 3:  # Min 3 chars (was 2)
        return False
    ticker_upper = ticker.upper()
    if ticker_upper in BLACKLIST_WORDS:
        return False
    if ticker_upper in VALID_TICKERS:
        return True
    return False


def fetch_live_price(ticker):
    """Fetch exact LTP from Angel One SmartAPI (shared client)."""
    if not ticker:
        return None
    if not is_configured():
        return None
    ltp, source = fetch_ltp(str(ticker).upper().replace('.NS', ''))
    if ltp and 5 <= ltp <= 1000000:
        return round(ltp, 2)
    return None
# ============================================================
# DEDUPLICATION
# ============================================================

def is_duplicate_prediction(ticker, recommendation, prediction_date):
    """Skip if same ticker + recommendation + date already exists."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) FROM predictions
            WHERE ticker = ? AND recommendation = ? AND prediction_date = ?
        ''', (ticker, recommendation, prediction_date))
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        return False


# ============================================================
# PARSER
# ============================================================

def parse_conviction(analysis_text):
    if not analysis_text:
        return 0
    
    patterns = [
        r'Overall conviction[:\s]+\*?\*?(\d+)/10',
        r'Overall conviction[:\s]+\*?\*?(\d+)',
        r'overall conviction[:\s]+\*?\*?(\d+)\s*/\s*10',
        r'\*\*Overall[^:]*:\s*\*?\*?(\d+)/10',
        r'conviction score[:\s]+(\d+)',
        r'overall[:\s]+(\d+)/10',
        r'CONVICTION[:\s]+(\d+)/10',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, analysis_text, re.IGNORECASE | re.DOTALL)
        if match:
            try:
                score = int(match.group(1))
                if 0 <= score <= 10:
                    return score
            except (ValueError, IndexError):
                continue
    return 0


def find_section(text, keyword):
    if not text:
        return ""
    parts = re.split(r'\n##\s+', text)
    keyword_upper = keyword.upper()
    for part in parts:
        first_line = part.split('\n')[0].upper()
        if keyword_upper in first_line:
            lines = part.split('\n')
            return '\n'.join(lines[1:])
    return ""


def parse_price(text):
    """Parse price - STRICTER to avoid garbage values"""
    if not text:
        return None
    
    # Look for prices like "Rs.1,180" or "₹2,888" or "1180-1200" or "Rs.198-202"
    # Strip ranges - take first number
    text = text.replace('—', '-').replace('–', '-')
    
    # Match: optional currency, digits with optional comma/dot, optional decimals
    # MIN 2 digits to avoid catching "1" or "2.5"
    matches = re.findall(r'(?:Rs\.?\s*|\u20b9\s*)?(\d{2,7}(?:[,.]\d{3})*(?:\.\d{1,2})?)', text)
    
    for val_str in matches:
        try:
            val = float(val_str.replace(',', ''))
            # Reject obvious garbage: too small (likely volume ratio or decimal) or too large
            if 5 <= val <= 1000000:
                return round(val, 2)
        except:
            continue
    return None


def parse_confidence(text):
    if not text:
        return 'MEDIUM'
    text_lower = text.lower()
    if 'high' in text_lower:
        return 'HIGH'
    if 'low' in text_lower:
        return 'LOW'
    return 'MEDIUM'


def split_into_numbered_items(section_text):
    """Handles BOTH '1. ' and '### **1.' formats"""
    if not section_text:
        return []
    
    items_v1 = []
    current_item = []
    current_rank = None
    
    for line in section_text.split('\n'):
        match = re.match(r'^\s*(\d{1,2})\.\s+(.*)', line)
        if match:
            if current_rank and current_item:
                items_v1.append((current_rank, '\n'.join(current_item)))
            current_rank = int(match.group(1))
            current_item = [match.group(2)]
        else:
            if current_rank:
                current_item.append(line)
    
    if current_rank and current_item:
        items_v1.append((current_rank, '\n'.join(current_item)))
    
    if items_v1:
        return items_v1
    
    items_v2 = []
    current_item = []
    current_rank = None
    
    for line in section_text.split('\n'):
        match = re.match(r'^\s*#{0,4}\s*\*\*(\d{1,2})\.\s+(.*)', line)
        if match:
            if current_rank and current_item:
                items_v2.append((current_rank, '\n'.join(current_item)))
            current_rank = int(match.group(1))
            current_item = [match.group(2)]
        else:
            if current_rank:
                current_item.append(line)
    
    if current_rank and current_item:
        items_v2.append((current_rank, '\n'.join(current_item)))
    
    return items_v2


def extract_ticker(first_line):
    """
    v2.0: Try LONGEST match first to avoid grabbing 'BANK' before 'ICICIBANK'
    """
    if not first_line:
        return None
    
    cleaned = first_line.replace('**', '').replace('*', '')
    cleaned = cleaned.replace('—', '-').replace('–', '-')
    cleaned = ''.join(c for c in cleaned if ord(c) < 128).strip()
    
    candidates = re.findall(r'\b([A-Z][A-Z0-9&\-]{2,14})\b', cleaned)
    
    # Sort by length DESCENDING - longer tickers first
    # This prevents "BANK" matching before "ICICIBANK"
    candidates.sort(key=len, reverse=True)
    
    for candidate in candidates:
        if is_valid_ticker(candidate):
            return candidate
    
    return None


def parse_opportunity_item(rank, content):
    if not content or len(content.strip()) < 5:
        return None
    
    first_line = content.split('\n')[0]
    ticker = extract_ticker(first_line)
    
    if not ticker:
        return None
    
    recommendation = normalize_recommendation(first_line + ' ' + content)
    
    why_match = re.search(r'(?:Why|Reason)[:\s]+\*?\*?(.+?)(?=\n\s*[-\*]\s*(?:Entry|Target|Stop|Confidence|Cross)|\Z)', 
                          content, re.IGNORECASE | re.DOTALL)
    entry_match = re.search(r'Entry[:\s]+\*?\*?([^\n]+)', content, re.IGNORECASE)
    target_match = re.search(r'Target[:\s]+\*?\*?([^\n]+)', content, re.IGNORECASE)
    stop_match = re.search(r'Stop[\s\-]?[Ll]oss[:\s]+\*?\*?([^\n]+)', content, re.IGNORECASE)
    conf_match = re.search(r'Confidence[:\s]+\*?\*?([^\n]+)', content, re.IGNORECASE)
    cross_match = re.search(r'Cross[\s\-]?validation[:\s]+\*?\*?([^\n]+)', content, re.IGNORECASE)
    
    entry_price = parse_price(entry_match.group(1)) if entry_match else None
    
    # Fallback: if no entry price parsed, fetch live
    if entry_price is None:
        entry_price = fetch_live_price(ticker)
    
    return {
        'rank': rank,
        'ticker': ticker,
        'recommendation': recommendation,
        'reasoning': why_match.group(1).strip().strip('*')[:500] if why_match else '',
        'entry_price': entry_price,
        'target_price': parse_price(target_match.group(1)) if target_match else None,
        'stop_loss': parse_price(stop_match.group(1)) if stop_match else None,
        'confidence': parse_confidence(conf_match.group(1)) if conf_match else 'MEDIUM',
        'cross_validation': cross_match.group(1).strip().strip('*')[:200] if cross_match else '',
    }


def parse_risk_item(rank, content):
    if not content or len(content.strip()) < 3:
        return None
    
    first_line = content.split('\n')[0]
    ticker = extract_ticker(first_line)
    
    if not ticker:
        return None
    
    reasoning = first_line.replace(ticker, '', 1).strip(' -*:')
    if len(reasoning) < 30 and len(content) > len(first_line):
        reasoning = content.replace(ticker, '', 1).strip(' -*:').replace('\n', ' ')[:300]
    
    # CRITICAL FIX: Risks now also get entry_price for evaluation
    entry_price = fetch_live_price(ticker)
    
    return {
        'rank': rank,
        'ticker': ticker,
        'recommendation': 'AVOID',
        'reasoning': reasoning[:500],
        'confidence': 'MEDIUM',
        'entry_price': entry_price,
    }


# ============================================================
# MAIN LOGGER
# ============================================================

def log_predictions_from_intelligence():
    # Initialize variables to avoid UnboundLocalError
    saved_opps = 0
    skipped_opps = 0
    saved_risks = 0
    skipped_risks = 0
    
    init_db()
    if not INTELLIGENCE_FILE.exists(): return False
    
    with open(INTELLIGENCE_FILE, 'r', encoding='utf-8') as f:
        intel = json.load(f)
    
    prediction_date = intel.get('timestamp', datetime.now().isoformat())[:10]
    run_type = os.environ.get('AI_USE_CASE', 'manual_refresh')
    conviction = 6 # Default as it's not explicitly in the JSON root
    
    # NEW: Directly read from structured JSON instead of parsing text
    opportunities = intel.get('top_opportunities', [])
    risks = intel.get('risks_and_avoids', [])

    safe_print(f"[INFO] Processing {len(opportunities)} opportunities and {len(risks)} risks")

    for i, opp in enumerate(opportunities, 1):
        ticker = opp.get('symbol')
        if not is_valid_ticker(ticker):
            continue

        recommendation = normalize_recommendation(opp.get('action', 'BUY'))

        if is_duplicate_prediction(ticker, recommendation, prediction_date):
            skipped_opps += 1
            continue

        prediction_data = {
            'prediction_date': prediction_date,
            'run_type': run_type,
            'ticker': ticker,
            'sector': get_sector_for_ticker(ticker),
            'recommendation': recommendation,
            'category': 'opportunity',
            'rank_in_list': i,
            'entry_price': parse_price(str(opp.get('entry_zone', ''))),
            'target_price': parse_price(str(opp.get('target', ''))),
            'stop_loss': parse_price(str(opp.get('stop_loss', ''))),
            'confidence': opp.get('confidence', 'MEDIUM'),
            'reasoning': opp.get('logic', ''),
            'overall_conviction': conviction,
            'raw_data': opp
        }
        
        if insert_prediction(prediction_data):
            # Patch: Create outcome row for grading
            try:
                conn_db = sqlite3.connect(DB_PATH)
                cur = conn_db.cursor()
                cur.execute("SELECT id FROM predictions WHERE ticker=? AND prediction_date=? ORDER BY id DESC LIMIT 1", (ticker, prediction_date))
                p_id = cur.fetchone()[0]
                cur.execute("INSERT INTO outcomes (ticker, prediction_date, entry_price, source_id, source_type, verdict) VALUES (?, ?, ?, ?, ?, 'PENDING')", 
                            (ticker, prediction_date, prediction_data['entry_price'], p_id, 'prediction'))
                conn_db.commit(); conn_db.close()
                saved_opps += 1
            except: pass

    for i, risk in enumerate(risks, 1):
        ticker = risk.get('symbol')
        if not is_valid_ticker(ticker):
            continue

        recommendation = 'AVOID'

        if is_duplicate_prediction(ticker, recommendation, prediction_date):
            skipped_risks += 1
            continue

        risk_data = {
            'prediction_date': prediction_date,
            'run_type': run_type,
            'ticker': ticker,
            'sector': get_sector_for_ticker(ticker),
            'recommendation': recommendation,
            'category': 'risk',
            'rank_in_list': i,
            'entry_price': fetch_live_price(ticker),
            'confidence': 'MEDIUM',
            'reasoning': risk.get('logic', ''),
            'overall_conviction': conviction,
            'raw_data': risk
        }
        
        if insert_prediction(risk_data):
            try:
                conn_db = sqlite3.connect(DB_PATH)
                cur = conn_db.cursor()
                cur.execute("SELECT id FROM predictions WHERE ticker=? AND prediction_date=? ORDER BY id DESC LIMIT 1", (ticker, prediction_date))
                p_id = cur.fetchone()[0]
                cur.execute("INSERT INTO outcomes (ticker, prediction_date, entry_price, source_id, source_type, verdict) VALUES (?, ?, ?, ?, ?, 'PENDING')", 
                            (ticker, prediction_date, risk_data['entry_price'], p_id, 'prediction'))
                conn_db.commit(); conn_db.close()
                saved_risks += 1
            except: pass

    saved_signals = log_scanner_signals(prediction_date)
    return True

def log_scanner_signals(signal_date):
    if not SCANNER_FILE.exists():
        return 0
    
    try:
        with open(SCANNER_FILE, 'r', encoding='utf-8') as f:
            scanner = json.load(f)
    except Exception as e:
        safe_print(f"[WARN] Failed to load scanner: {e}")
        return 0
    
    top_signals = scanner.get('top_signals', [])
    saved = 0
    
    for sig in top_signals:
        strength = sig.get('strength', '')
        if strength not in ('ULTRA', 'STRONG'):
            continue
        
        signal_data = {
            'signal_date': signal_date,
            'ticker': sig.get('ticker'),
            'sector': sig.get('sector'),
            'strength': strength,
            'direction': sig.get('direction', 'NEUTRAL'),
            'signal_types': sig.get('signals', []),
            'price': sig.get('price'),
            'change_percent': sig.get('change_percent'),
            'volume_ratio': sig.get('volume_ratio'),
            'high_20d': sig.get('high_20d'),
            'low_20d': sig.get('low_20d'),
            'gap_percent': sig.get('gap_percent'),
            'raw_data': sig,
        }
        
        if insert_signal(signal_data):
            saved += 1
            try:
                from backend.analytics.signal_outcomes import (
                    create_pending_outcome_for_signal,
                    track_scanner_signal,
                )
                conn_db = sqlite3.connect(DB_PATH)
                cur = conn_db.cursor()
                cur.execute(
                    "SELECT id FROM signals WHERE signal_date=? AND ticker=? AND strength=?",
                    (signal_date, signal_data['ticker'], strength),
                )
                row = cur.fetchone()
                conn_db.close()
                if row:
                    sig_id = row[0]
                    create_pending_outcome_for_signal(
                        sig_id,
                        signal_data['ticker'],
                        signal_date,
                        signal_data.get('price'),
                    )
                track_scanner_signal(sig, signal_date)
            except Exception as e:
                safe_print(f"[WARN] Signal outcome tracking: {e}")
    
    return saved


if __name__ == "__main__":
    try:
        log_predictions_from_intelligence()
    except Exception as e:
        import traceback
        safe_print(f"[FATAL] {e}")
        try:
            traceback.print_exc()
        except Exception:
            pass