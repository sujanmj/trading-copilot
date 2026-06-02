"""
GOVERNMENT TRACKER v8 - Full Article Translation
- v7 features intact (forced English titles)
- NEW: Article body also auto-translated to English
- Saves both English and original versions in JSON
"""

import os
import json
import sys
import re
import requests
import feedparser
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from collections import Counter
from bs4 import BeautifulSoup


from backend.storage.json_io import atomic_write_json

# Force UTF-8 (Windows fix)
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

env_path = Path(__file__).resolve().parent.parent.parent / 'config' / 'keys.env'
load_dotenv(env_path)


GOVT_SOURCES = {
    'SEBI Press Releases': 'https://www.sebi.gov.in/sebirss.xml',
    'BSE Announcements': 'https://www.bseindia.com/data/xml/notices.xml',
    'Economic Times Markets': 'https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms',
    'Business Standard Markets': 'https://www.business-standard.com/rss/markets-106.rss',
    'LiveMint Economy': 'https://www.livemint.com/rss/economy',
    'LiveMint Markets': 'https://www.livemint.com/rss/markets',
}


HIGH_IMPACT_KEYWORDS = {
    'pm_modi_en': ['narendra modi', 'pm modi', 'prime minister', 'pmo'],
    'pm_modi_hi': ['प्रधानमंत्री', 'मोदी', 'प्रधान मंत्री'],
    'finance_min_en': ['nirmala sitharaman', 'finance minister'],
    'finance_min_hi': ['वित्त मंत्री', 'वित्तमंत्री'],
    'rbi_gov': ['shaktikanta', 'rbi governor', 'governor das'],
    'petroleum_en': ['petrol', 'diesel', 'lpg', 'crude', 'oil price', 'fuel price', 'refinery'],
    'petroleum_hi': ['पेट्रोल', 'डीजल', 'ईंधन', 'तेल'],
    'gold_silver_en': ['gold', 'silver', 'precious metal', 'jewellery'],
    'gold_silver_hi': ['सोना', 'चांदी', 'आभूषण'],
    'rate_action': ['repo rate', 'rate cut', 'rate hike', 'monetary policy', 'mpc'],
    'tax_action': ['gst', 'tax cut', 'tax hike', 'income tax', 'corporate tax'],
    'budget': ['budget', 'fiscal deficit', 'capex'],
    'trade': ['tariff', 'trade deal', 'export ban', 'import ban', 'sanctions'],
    'war_en': ['war', 'iran', 'israel', 'ukraine', 'russia', 'border'],
    'war_hi': ['युद्ध', 'सीमा', 'सेना'],
    'major_action_en': ['ban', 'crackdown', 'reform', 'amendment', 'new policy'],
    'major_action_hi': ['प्रतिबंध', 'सुधार', 'नई नीति'],
    'wfh_en': ['work from home', 'wfh', 'remote work'],
    'wfh_hi': ['घर से काम'],
    'auto_ev': ['ev policy', 'electric vehicle', 'fame', 'scrappage'],
}


KEYWORD_STOCK_MAP = {
    'petrol': ['RELIANCE', 'IOC', 'BPCL', 'HPCL', 'ONGC'],
    'diesel': ['RELIANCE', 'IOC', 'BPCL', 'HPCL'],
    'crude oil': ['RELIANCE', 'ONGC', 'IOC'],
    'fuel price': ['RELIANCE', 'IOC', 'BPCL', 'HPCL'],
    'lpg': ['IOC', 'BPCL', 'HPCL', 'GAIL'],
    'पेट्रोल': ['RELIANCE', 'IOC', 'BPCL', 'HPCL', 'ONGC'],
    'डीजल': ['RELIANCE', 'IOC', 'BPCL', 'HPCL'],
    'gold': ['GOLDBEES', 'TITAN', 'KALYAN'],
    'silver': ['SILVERBEES', 'VEDL'],
    'jewellery': ['TITAN', 'KALYAN', 'PCJEWELLER'],
    'सोना': ['GOLDBEES', 'TITAN', 'KALYAN'],
    'चांदी': ['SILVERBEES', 'VEDL'],
    'steel sector': ['TATASTEEL', 'JSWSTEEL', 'SAIL'],
    'cement': ['ULTRACEMCO', 'AMBUJA', 'ACC'],
    'pharma sector': ['SUNPHARMA', 'CIPLA', 'DRREDDY'],
    'banking sector': ['HDFCBANK', 'ICICIBANK', 'SBIN'],
    'auto sector': ['MARUTI', 'TATAMOTORS', 'M&M'],
    'electric vehicle': ['TATAMOTORS', 'M&M', 'EICHER'],
    'real estate sector': ['DLF', 'GODREJPROP', 'OBEROI'],
    'telecom sector': ['BHARTIARTL'],
    'work from home': ['TCS', 'INFY', 'WIPRO', 'HCLTECH'],
    'wfh': ['TCS', 'INFY', 'WIPRO', 'HCLTECH'],
    'घर से काम': ['TCS', 'INFY', 'WIPRO', 'HCLTECH'],
    'iran': ['ONGC', 'OIL INDIA', 'RELIANCE'],
    'sanctions': ['ONGC', 'RELIANCE'],
    'gst rate': ['ITC', 'NESTLE', 'HUL'],
    'repo rate': ['HDFCBANK', 'ICICIBANK', 'BAJFINANCE'],
}


NOISE_PATTERNS = [
    'recovery certificate', 'demat account', 'isin number',
    'daily bulletin', 'appeal no', 'penalty report',
    'surveillance measure', 'enhanced surveillance',
    'graded surveillance', 'price band', 'forfeiture of equity',
    'listing of new securities', 'listing of equity shares',
    'change in name', 'suspension of trading', 'suspension in trading',
    'revocation of suspension', 'short term additional',
    'long term additional', 'asm)', 'ibc',
    'completion certificate', 'attachment of bank',
    'attachment of demat', 'notice of demand',
    'release order', 'settlement order', 'cancellation of rc',
    'discontinuation of investor',
]


# ============================================================
# TRANSLATION ENGINE
# ============================================================

_TRANSLATION_CACHE = {}


def is_hindi(text):
    """Detect Hindi (Devanagari script). 5+ Hindi chars = Hindi text."""
    if not text:
        return False
    hindi_chars = sum(1 for c in text if '\u0900' <= c <= '\u097F')
    return hindi_chars >= 5


def translate_with_ai(text):
    """Translate using AI router (Haiku/Gemini/Sonnet)"""
    try:
        from backend.ai.ai_router import ask_ai
        prompt = f"Translate this Hindi text to English. Return ONLY the English translation, no explanations, no quotes:\n\n{text}"
        result = ask_ai(prompt, use_case='translate', max_tokens=2000)
        
        if isinstance(result, dict):
            if result.get('success'):
                translated = result.get('text', '').strip()
            else:
                return None
        else:
            translated = str(result).strip() if result else None
        
        if not translated:
            return None
        
        translated = translated.strip().strip('"').strip("'")
        translated = re.sub(r'^(Translation|English):\s*', '', translated, flags=re.IGNORECASE)
        return translated.strip()
    except Exception as e:
        return None


def translate_with_google(text):
    """Free Google Translate (no API key needed). Best for long text."""
    try:
        # Google Translate has ~5000 char limit per request
        # For longer text, split into chunks
        if len(text) <= 4500:
            return _google_translate_chunk(text)
        
        # Split long text into chunks at sentence boundaries
        chunks = []
        current_chunk = ""
        sentences = text.split('।')  # Hindi period
        if len(sentences) == 1:
            sentences = text.split('. ')  # English period fallback
        
        for sentence in sentences:
            if len(current_chunk) + len(sentence) < 4500:
                current_chunk += sentence + '। '
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = sentence + '। '
        
        if current_chunk:
            chunks.append(current_chunk)
        
        # Translate each chunk
        translated_chunks = []
        for i, chunk in enumerate(chunks):
            translated = _google_translate_chunk(chunk)
            if translated:
                translated_chunks.append(translated)
        
        return ' '.join(translated_chunks) if translated_chunks else None
    
    except Exception as e:
        return None


def _google_translate_chunk(text):
    """Translate a single chunk via Google Translate"""
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            'client': 'gtx', 'sl': 'hi', 'tl': 'en', 'dt': 't',
            'q': text[:5000]
        }
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, params=params, headers=headers, timeout=20)
        data = r.json()
        result = ''.join([s[0] for s in data[0] if s[0]])
        return result.strip() if result else None
    except Exception:
        return None


def force_english(text, prefer_google=False):
    """
    Always returns English text.
    
    For SHORT text (titles): Try AI first, Google fallback
    For LONG text (article body): Use Google directly (faster, no quota)
    """
    if not text or not is_hindi(text):
        return text
    
    # Cache check
    cache_key = text[:200]  # Use first 200 chars as cache key
    if cache_key in _TRANSLATION_CACHE:
        return _TRANSLATION_CACHE[cache_key]
    
    # For long text or when explicitly asked, use Google
    if prefer_google or len(text) > 500:
        translated = translate_with_google(text)
        if translated and not is_hindi(translated):
            _TRANSLATION_CACHE[cache_key] = translated
            return translated
    
    # For short text, try AI first
    translated = translate_with_ai(text)
    if translated and not is_hindi(translated):
        _TRANSLATION_CACHE[cache_key] = translated
        return translated
    
    # Fallback to Google
    translated = translate_with_google(text)
    if translated and not is_hindi(translated):
        _TRANSLATION_CACHE[cache_key] = translated
        return translated
    
    # Last resort
    fallback = f"[Hindi] {text}"
    _TRANSLATION_CACHE[cache_key] = fallback
    return fallback


# ============================================================
# EXISTING FUNCTIONS
# ============================================================

def is_noise(item):
    title = item.get('title', '').lower()
    for pattern in NOISE_PATTERNS:
        if pattern in title:
            return True
    return False


def convert_to_english_link(hindi_url):
    """Convert PIB Hindi URL to English version"""
    if not hindi_url or 'pib.gov.in' not in hindi_url:
        return hindi_url

    english_url = hindi_url.replace('PressReleaseIframePage.aspx', 'PressReleasePage.aspx')
    english_url = english_url.replace('Lang=2', 'Lang=1')

    if 'Lang=' not in english_url and 'PRID=' in english_url:
        if '?' in english_url:
            english_url += '&Lang=1'
        else:
            english_url += '?Lang=1'

    return english_url


def fetch_rss_feed(url, source_name, hours_back=72):
    try:
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        if response.status_code != 200:
            return []

        feed = feedparser.parse(response.content)
        cutoff = datetime.now() - timedelta(hours=hours_back)

        items = []
        for entry in feed.entries[:30]:
            pub_date = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                pub_date = datetime(*entry.published_parsed[:6])
            elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                pub_date = datetime(*entry.updated_parsed[:6])

            if pub_date and pub_date < cutoff:
                continue

            original_link = entry.get('link', '')
            english_link = convert_to_english_link(original_link)

            raw_title = entry.get('title', '').strip()
            raw_description = entry.get('summary', '')[:600].strip()

            # Force translate title and description
            english_title = force_english(raw_title)
            english_description = force_english(raw_description)

            items.append({
                'source': source_name,
                'title': english_title,
                'title_original': raw_title,
                'was_translated': raw_title != english_title,
                'description': english_description,
                'description_original': raw_description,
                'link': english_link,
                'original_hindi_link': original_link,
                'published': pub_date.isoformat() if pub_date else '',
                'published_str': pub_date.strftime('%Y-%m-%d %H:%M') if pub_date else 'unknown',
            })

        return items
    except Exception as e:
        print(f"  WARN {source_name}: {str(e)[:80]}")
        return []


def fetch_press_release_body(url, max_chars=8000):
    """
    Fetch full press release body.
    NEW IN v8: Auto-translates Hindi body to English.
    Returns dict with both English and original versions.
    """
    try:
        english_url = convert_to_english_link(url)

        response = requests.get(english_url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

        if response.status_code != 200:
            response = requests.get(url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            if response.status_code != 200:
                return {'body': '', 'body_original': '', 'was_translated': False}

        soup = BeautifulSoup(response.content, 'lxml')

        content_selectors = [
            'div.innner-page-main-about-us-content-right-part',
            'div#PdfDiv',
            'div.contentMain',
            'div.PressDtlContent',
            'div.detail-content',
            'div[class*="content"]',
        ]

        body_text = ''
        for selector in content_selectors:
            element = soup.select_one(selector)
            if element:
                body_text = element.get_text(separator=' ', strip=True)
                if len(body_text) > 100:
                    break

        if len(body_text) < 100:
            paragraphs = soup.find_all('p')
            body_text = ' '.join(p.get_text(strip=True) for p in paragraphs)

        body_text = ' '.join(body_text.split())
        body_text = body_text[:max_chars]

        # NEW IN v8: Translate body if Hindi
        body_original = body_text
        body_was_translated = False
        
        if is_hindi(body_text):
            print(f"    [TRANSLATING BODY] {len(body_text)} chars...")
            body_english = force_english(body_text, prefer_google=True)
            if body_english and not is_hindi(body_english):
                body_text = body_english
                body_was_translated = True
                print(f"    [BODY TRANSLATED] {len(body_text)} chars English")

        return {
            'body': body_text,
            'body_original': body_original,
            'was_translated': body_was_translated
        }

    except Exception as e:
        print(f"    WARN scraping {url[:50]}: {str(e)[:60]}")
        return {'body': '', 'body_original': '', 'was_translated': False}


def smart_summarize_speech(text, title=''):
    """AI summarization with structured output"""
    if not text:
        return {'headline': title, 'summary': ''}

    try:
        from backend.ai.ai_router import ask_ai

        prompt = f"""You are a financial news editor. Analyze this Indian government press release and extract market-relevant content.

TITLE: {title}

FULL TEXT:
{text[:6000]}

Your task:
1. If text contains Hindi, translate it to English first
2. Extract the ACTUAL substantive content (skip introductions, formal greetings, location/date info)
3. Focus on what was ANNOUNCED, DECIDED, or COMMITTED — not the venue or audience
4. Identify any market-relevant content: policies, rates, taxes, sectors mentioned, trade deals, etc.

Provide output in this EXACT format:

HEADLINE: [One clear English sentence describing the substance, max 120 chars. NOT "PM addressed event" but WHAT was announced/said. If no substantive announcement, say "Ceremonial address - no policy content"]

SUMMARY: [2-4 sentences summarizing the KEY POINTS. What did they actually SAY? What policies, decisions, or statements were made? Skip pleasantries and venue details. Focus on market-relevant content.]

KEY_POINTS:
- [Bullet 1: specific announcement/quote]
- [Bullet 2: specific announcement/quote]
- [Bullet 3: specific announcement/quote]

MARKET_RELEVANCE: [HIGH/MEDIUM/LOW/NONE - explain in one line]

Be substantive. If purely ceremonial, say so honestly."""

        result = ask_ai(prompt, model_override='gemini', max_tokens=1500)

        if not result.get('success'):
            return {'headline': title, 'summary': text[:300]}

        response_text = result.get('text', '')

        headline = ''
        summary = ''
        key_points = []
        market_relevance = ''

        for line in response_text.split('\n'):
            line = line.strip()
            if line.startswith('HEADLINE:'):
                headline = line.replace('HEADLINE:', '').strip()
            elif line.startswith('SUMMARY:'):
                summary = line.replace('SUMMARY:', '').strip()
            elif line.startswith('- '):
                key_points.append(line[2:].strip())
            elif line.startswith('MARKET_RELEVANCE:'):
                market_relevance = line.replace('MARKET_RELEVANCE:', '').strip()

        if 'SUMMARY:' in response_text and not summary.endswith('.'):
            try:
                summary_section = response_text.split('SUMMARY:')[1].split('KEY_POINTS:')[0].strip()
                summary = summary_section
            except:
                pass

        return {
            'headline': headline or title,
            'summary': summary or '',
            'key_points': key_points[:5],
            'market_relevance': market_relevance,
        }

    except Exception as e:
        print(f"    Summarization error: {str(e)[:80]}")
        return {'headline': title, 'summary': text[:300]}


def detect_keywords(text):
    text_lower = text.lower()
    detected = {}
    for category, keywords in HIGH_IMPACT_KEYWORDS.items():
        matches = []
        for kw in keywords:
            if kw.lower() in text_lower:
                matches.append(kw)
        if matches:
            detected[category] = matches
    return detected


def predict_affected_stocks(text):
    text_lower = text.lower()
    affected = set()
    for keyword, stocks in KEYWORD_STOCK_MAP.items():
        if keyword.lower() in text_lower:
            for stock in stocks:
                affected.add(stock)
    return list(affected)


def calculate_impact_score(item):
    translated_text = (item.get('title', '') + ' ' + item.get('description', '')).lower()
    original_text = (item.get('title_original', '') + ' ' + item.get('description_original', '')).lower()
    text = translated_text + ' ' + original_text
    
    score = 0
    reasons = []

    if any(w in text for w in ['narendra modi', 'pm modi', 'prime minister']):
        score += 5
        reasons.append('PM speech/action')
    elif 'प्रधानमंत्री' in text or 'मोदी' in text:
        score += 5
        reasons.append('PM speech/action')

    if any(w in text for w in ['nirmala sitharaman', 'finance minister']):
        score += 4
        reasons.append('FM speech/action')
    elif 'वित्त मंत्री' in text:
        score += 4
        reasons.append('FM speech/action')

    if any(w in text for w in ['rbi governor', 'shaktikanta']):
        score += 4
        reasons.append('RBI Governor')

    if any(w in text for w in ['repo rate', 'rate cut', 'rate hike', 'monetary policy']):
        score += 3
        reasons.append('Rate policy')

    if any(w in text for w in ['petrol', 'diesel', 'crude', 'fuel', 'पेट्रोल', 'डीजल']):
        score += 2
        reasons.append('Energy impact')

    if any(w in text for w in ['gold', 'silver', 'सोना', 'चांदी']):
        score += 2
        reasons.append('Precious metals')

    if any(w in text for w in ['war', 'iran', 'israel', 'sanctions', 'युद्ध']):
        score += 2
        reasons.append('Geopolitical')

    high_impact = ['ban', 'tariff', 'subsidy', 'budget', 'crisis', 'emergency', 'reform']
    for word in high_impact:
        if word in text:
            score += 2
            reasons.append(f'Action: {word}')
            break

    if any(w in text for w in ['address', 'addresses', 'speech', 'announces', 'भाषण', 'संबोधन']):
        score += 2
        reasons.append('Speech detected')

    if 'gst' in text or 'income tax' in text:
        score += 2
        reasons.append('Tax policy')

    return min(score, 10), reasons


def detect_directional_bias(text):
    text_lower = text.lower()
    positive = ['boost', 'reform', 'incentive', 'subsidy', 'approve', 'launch',
                'reduce duty', 'support', 'invest', 'growth']
    negative = ['ban', 'restrict', 'crackdown', 'penalty', 'fine',
                'cut subsidy', 'sanction', 'emergency', 'war', 'rate hike']
    pos = sum(1 for w in positive if w in text_lower)
    neg = sum(1 for w in negative if w in text_lower)
    if pos > neg and pos > 0:
        return 'BULLISH', pos - neg
    elif neg > pos:
        return 'BEARISH', neg - pos
    return 'NEUTRAL', 0


def collect_govt_intelligence():
    print("\n" + "=" * 60)
    print("GOVERNMENT TRACKER v8 - FULL ARTICLE TRANSLATION")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    print("\n[FETCHING + TRANSLATING] Government feeds...")
    print("-" * 60)

    all_items = []
    for source_name, url in GOVT_SOURCES.items():
        items = fetch_rss_feed(url, source_name)
        translated_count = sum(1 for i in items if i.get('was_translated'))
        print(f"  {source_name:35s} {len(items):3d} items ({translated_count} translated)")
        all_items.extend(items)

    print(f"\n[TOTAL] {len(all_items)} items raw")
    total_translated = sum(1 for i in all_items if i.get('was_translated'))
    print(f"[TRANSLATED] {total_translated} items had Hindi → English title conversion")

    filtered = [i for i in all_items if not is_noise(i)]
    noise_count = len(all_items) - len(filtered)
    print(f"[FILTERED] Removed {noise_count} routine items")
    print(f"[REMAINING] {len(filtered)} signal items")

    if not filtered:
        return None

    print("\n[ANALYZING] Initial scoring...")

    high_impact = []
    medium_impact = []
    affected_stocks = Counter()
    keyword_stats = Counter()

    for item in filtered:
        text = (item.get('title', '') + ' ' + item.get('description', '') + ' ' +
                item.get('title_original', '') + ' ' + item.get('description_original', ''))

        keywords = detect_keywords(text)
        for cat, matches in keywords.items():
            for m in matches:
                keyword_stats[m] += 1

        stocks = predict_affected_stocks(text)
        for s in stocks:
            affected_stocks[s] += 1

        score, reasons = calculate_impact_score(item)
        direction, strength = detect_directional_bias(text)

        item['keywords'] = keywords
        item['affected_stocks'] = stocks
        item['impact_score'] = score
        item['impact_reasons'] = reasons
        item['direction'] = direction

        if score >= 4:
            high_impact.append(item)
        elif score >= 2:
            medium_impact.append(item)

    high_impact.sort(key=lambda x: x['impact_score'], reverse=True)
    medium_impact.sort(key=lambda x: x['impact_score'], reverse=True)

    # NEW IN v8: Fetch and translate article bodies for top items
    print(f"\n[FETCHING ARTICLE BODIES] Top {min(len(high_impact), 10)} high-impact items...")
    print("-" * 60)

    for i, item in enumerate(high_impact[:10], 1):
        link = item.get('link', '')
        if not link or 'pib.gov.in' not in link:
            item['body'] = ''
            item['body_was_translated'] = False
            continue

        print(f"  {i}. {item.get('title', '')[:55]}")
        body_data = fetch_press_release_body(link)
        
        item['body'] = body_data['body']
        item['body_original'] = body_data['body_original']
        item['body_was_translated'] = body_data['was_translated']

        # Continue with summarization for top 5
        if i <= 5 and item['body']:
            print(f"     Calling Gemini for summary...")
            summary_data = smart_summarize_speech(item['body'], item.get('title', ''))

            item['english_headline'] = summary_data.get('headline', '')
            item['english_summary'] = summary_data.get('summary', '')
            item['key_points'] = summary_data.get('key_points', [])
            item['market_relevance'] = summary_data.get('market_relevance', '')

            full_text = (item['english_headline'] + ' ' + item['english_summary'] +
                        ' '.join(item['key_points'])).lower()

            bonus_score = 0
            bonus_reasons = []

            if 'petrol' in full_text or 'diesel' in full_text or 'fuel' in full_text:
                bonus_score += 3
                bonus_reasons.append('PETROL/FUEL')
                item['affected_stocks'] = list(set(item.get('affected_stocks', []) +
                    ['RELIANCE', 'IOC', 'BPCL', 'HPCL', 'ONGC']))

            if 'gold' in full_text or 'silver' in full_text:
                bonus_score += 3
                bonus_reasons.append('GOLD/SILVER')
                item['affected_stocks'] = list(set(item.get('affected_stocks', []) +
                    ['GOLDBEES', 'TITAN', 'KALYAN', 'SILVERBEES']))

            if 'iran' in full_text or 'war' in full_text:
                bonus_score += 2
                bonus_reasons.append('GEOPOLITICAL')

            if 'work from home' in full_text or 'wfh' in full_text:
                bonus_score += 2
                bonus_reasons.append('WFH')
                item['affected_stocks'] = list(set(item.get('affected_stocks', []) +
                    ['TCS', 'INFY', 'WIPRO', 'HCLTECH']))

            if 'gst' in full_text or 'income tax' in full_text:
                bonus_score += 2
                bonus_reasons.append('TAX')

            if 'subsidy' in full_text or 'incentive' in full_text:
                bonus_score += 2
                bonus_reasons.append('SUBSIDY')

            if 'NONE' in (item.get('market_relevance') or '').upper():
                item['impact_score'] = max(item['impact_score'] - 3, 1)
                bonus_reasons.append('Ceremonial - reduced')

            if bonus_score > 0:
                item['impact_score'] = min(item['impact_score'] + bonus_score, 10)
                item['impact_reasons'] = item.get('impact_reasons', []) + bonus_reasons
                print(f"     >> {item['impact_score']}/10 | {', '.join(bonus_reasons)}")
            else:
                print(f"     >> {item['impact_score']}/10 | {item.get('market_relevance', 'unknown')}")

    high_impact.sort(key=lambda x: x['impact_score'], reverse=True)

    print("\n" + "=" * 60)
    print(f"FINAL HIGH-IMPACT (4+): {len(high_impact)} items")
    print("=" * 60)

    if high_impact:
        for i, item in enumerate(high_impact[:10], 1):
            print(f"\n{i}. Score: {item['impact_score']}/10 | {item['direction']} | {item.get('market_relevance', 'unknown')}")
            print(f"   Source: {item['source']}")
            print(f"   Headline: {item.get('english_headline', item.get('title', ''))[:130]}")
            if item.get('body_was_translated'):
                print(f"   [Body translated to English]")
            if item.get('affected_stocks'):
                print(f"   Stocks: {', '.join(item['affected_stocks'][:8])}")

    output = {
        'timestamp': datetime.now().isoformat(),
        'collection_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_raw': len(all_items),
        'total_translated': total_translated,
        'noise_filtered': noise_count,
        'analyzed_items': len(filtered),
        'high_impact_count': len(high_impact),
        'medium_impact_count': len(medium_impact),
        'high_impact_items': high_impact[:20],
        'medium_impact_items': medium_impact[:15],
        'affected_stocks': dict(affected_stocks.most_common(20)),
        'top_keywords': dict(keyword_stats.most_common(20)),
        'all_filtered_items': [
            {
                'source': i['source'],
                'title': i['title'],
                'title_original': i.get('title_original', ''),
                'was_translated': i.get('was_translated', False),
                'published': i['published_str'],
                'impact_score': i['impact_score'],
                'direction': i['direction'],
                'affected_stocks': i['affected_stocks']
            }
            for i in filtered
        ]
    }

    data_dir = Path(__file__).resolve().parent.parent.parent / 'data'
    data_dir.mkdir(exist_ok=True)
    output_file = data_dir / 'govt_intelligence.json'

    atomic_write_json(output_file, output)

    print(f"\nSaved to: {output_file}")
    print("=" * 60 + "\n")
    return output


if __name__ == "__main__":
    print("Starting Government Tracker v8...")
    try:
        collect_govt_intelligence()
        print("Done!")
    except Exception as e:
        import traceback
        print(f"ERROR: {e}")
        traceback.print_exc()