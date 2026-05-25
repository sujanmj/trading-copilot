"""
MASTER ANALYZER v10 - Robust logging + safe imports
"""

import os
import json
import sys
import io
import traceback
from datetime import datetime
from pathlib import Path

print("[BOOT] master_analyzer.py starting...")

if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).parent))

try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
    print("[OK] imported dotenv")
except ImportError as e:
    DOTENV_AVAILABLE = False
    def load_dotenv(*args, **kwargs):
        return False
    print(f"[FAIL] dotenv not available: {e}")

try:
    from ai_router import ask_ai
    from response_validator import validate_ai_response
    AI_ROUTER_AVAILABLE = True
    print("[OK] imported ai_router")
    print("[OK] imported response_validator")
except ImportError as e:
    AI_ROUTER_AVAILABLE = False
    ask_ai = None
    validate_ai_response = None
    print(f"[FAIL] ai_router not available: {e}")

try:
    from learning_engine import build_memory_summary
    LEARNING_AVAILABLE = True
    print("[OK] imported learning_engine")
except ImportError as e:
    LEARNING_AVAILABLE = False
    build_memory_summary = None
    print(f"[FAIL] learning_engine not available: {e}")

def _load_env_keys():
    """Railway: /app/config/keys.env or os.environ. Local: config/keys.env."""
    loaded = False
    if DOTENV_AVAILABLE:
        for env_path in (
            Path('/app/config/keys.env'),
            Path(__file__).parent.parent / 'config' / 'keys.env',
        ):
            if env_path.exists():
                load_dotenv(env_path, override=False)
                print(f"[OK] loaded env from {env_path}")
                loaded = True
                break
    has_keys = bool(
        os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('GOOGLE_API_KEY')
    )
    if not loaded and has_keys:
        print("[OK] API keys present in environment (no keys.env file needed)")
    elif not loaded and not has_keys:
        print("[INFO] No keys.env file and no API keys in environment yet")


_load_env_keys()


def load_json_safe(filepath):
    try:
        if not Path(filepath).exists():
            return None
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"  WARN failed to load {filepath}: {e}")
        return None


def _coerce_source_data(data, source_name):
    """Ensure each data source is a dict (not a raw JSON string)."""
    if data is None:
        return None
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        print(f"[WARN] {source_name} returned str not dict, trying json.loads()")
        try:
            parsed = json.loads(data)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        print(f"[WARN] {source_name} still not dict after json.loads()")
        return None
    print(f"[WARN] {source_name} returned {type(data).__name__} not dict")
    return None


def gather_all_data():
    data_dir = Path(__file__).parent.parent / 'data'
    raw = {
        'global_markets': load_json_safe(data_dir / 'global_markets.json'),
        'india_markets':  load_json_safe(data_dir / 'latest_market_data.json'),
        'news':           load_json_safe(data_dir / 'news_feed.json'),
        'youtube':        load_json_safe(data_dir / 'youtube_feed.json'),
        'govt':           load_json_safe(data_dir / 'govt_intelligence.json'),
        'inshorts':       load_json_safe(data_dir / 'inshorts_feed.json'),
        'reddit':         load_json_safe(data_dir / 'reddit_data.json'),
        'telegram':       load_json_safe(data_dir / 'telegram_sentiment.json'),
        'scanner':        load_json_safe(data_dir / 'scanner_data.json'),
        'twitter':        load_json_safe(data_dir / 'twitter_data.json'),
        'nse_filings':    load_json_safe(data_dir / 'nse_announcements.json'),
    }
    validated = {}
    for key, value in raw.items():
        if value is None:
            validated[key] = None
        elif isinstance(value, dict):
            validated[key] = value
        elif isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    validated[key] = parsed
                    print(f"[WARN] {key} was string, parsed as JSON")
                elif isinstance(parsed, list):
                    validated[key] = {'items': parsed}
                    print(f"[WARN] {key} was string JSON list, wrapped in dict")
                else:
                    print(f"[ERROR] {key} parsed to unexpected type: {type(parsed)}")
                    validated[key] = None
            except json.JSONDecodeError:
                print(f"[ERROR] {key} is string and not valid JSON: {value[:100]}")
                validated[key] = None
        elif isinstance(value, list):
            validated[key] = {'items': value}
            print(f"[WARN] {key} was list, wrapped in dict")
        else:
            print(f"[ERROR] {key} unexpected type: {type(value)}")
            validated[key] = None
    return validated


def _normalize_format_input(data, label):
    """Coerce formatter input to dict or return an error message string."""
    if data is None:
        return None, f"{label}: No data"
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return None, f"{label}: Invalid data format"
    if isinstance(data, list):
        data = {'items': data}
    if not isinstance(data, dict):
        return None, f"{label}: Unexpected type {type(data).__name__}"
    return data, None


def _safe_dict(value):
    return value if isinstance(value, dict) else {}


def _safe_list(value):
    return value if isinstance(value, list) else []


def format_global_markets(data):
    data, err = _normalize_format_input(data, "GLOBAL MARKETS")
    if err:
        return err

    lines = ["=== GLOBAL MARKETS ==="]

    sentiment = _safe_dict(data.get('sentiment'))
    for region, info in sentiment.items():
        info = _safe_dict(info)
        avg = info.get('average_change', info.get('expected_open', 0))
        try:
            lines.append(f"  {region.upper()}: {info.get('mood', '?')} ({float(avg):+.2f}%)")
        except (TypeError, ValueError):
            lines.append(f"  {region.upper()}: {info.get('mood', '?')}")

    markets = data.get('markets', {})
    if isinstance(markets, dict):
        for name, info in list(markets.items())[:10]:
            if not isinstance(info, dict):
                continue
            # Flat structure from global_collector: {ticker, change_pct, latest_price}
            if 'change_pct' in info or 'latest_price' in info:
                change = info.get('change_pct', info.get('change_percent', 0))
                price = info.get('latest_price', info.get('price', 0))
                ticker = info.get('ticker', name)
                try:
                    lines.append(f"  {name} ({ticker}): {float(price):,.2f} ({float(change):+.2f}%)")
                except (TypeError, ValueError):
                    lines.append(f"  {name} ({ticker})")
                continue
            # Legacy nested: markets[group][symbol] = info
            lines.append(f"\n[{name}]")
            for sym, sym_info in list(info.items())[:5]:
                sym_info = _safe_dict(sym_info)
                change = sym_info.get('change_percent', sym_info.get('change_pct', 0))
                price = sym_info.get('price', sym_info.get('latest_price', 0))
                try:
                    lines.append(f"  {sym}: {float(price):,.0f} ({float(change):+.2f}%)")
                except (TypeError, ValueError):
                    lines.append(f"  {sym}")

    for a in _safe_list(data.get('alerts'))[:5]:
        a = _safe_dict(a)
        lines.append(f"  ALERT: {a.get('message', '')}")
    return "\n".join(lines)


def format_india_markets(data):
    data, err = _normalize_format_input(data, "INDIA MARKETS")
    if err:
        return err

    lines = ["=== INDIA STOCKS ==="]
    prices = data.get('prices', {})
    if not isinstance(prices, dict):
        return "INDIA MARKETS: Invalid prices format"

    for name, info in prices.items():
        info = _safe_dict(info)
        change = info.get('change_percent', 0)
        price = info.get('price', 0)
        try:
            lines.append(f"  {name}: Rs.{float(price):,.2f} ({float(change):+.2f}%)")
        except (TypeError, ValueError):
            lines.append(f"  {name}: Rs.{price} ({change}%)")
    return "\n".join(lines)


def format_news(data):
    data, err = _normalize_format_input(data, "NEWS")
    if err:
        return err

    lines = ["=== NEWS ==="]
    lines.append(f"Articles: {data.get('total_articles', 0)}")
    top_stocks = data.get('top_stocks', {})
    if isinstance(top_stocks, dict):
        for stock, count in list(top_stocks.items())[:10]:
            lines.append(f"  {stock}: {count} articles")
    for h in _safe_list(data.get('hot_stocks'))[:5]:
        h = _safe_dict(h)
        lines.append(f"  HOT [{h.get('velocity', '?')}] {h.get('stock', '?')}: {h.get('mention_count', 0)} mentions")
    for a in _safe_list(data.get('articles'))[:15]:
        a = _safe_dict(a)
        label = str(a.get('sentiment_label', '?'))[:3].upper()
        lines.append(f"  [{label}] {str(a.get('title', ''))[:100]}")
    return "\n".join(lines)


def format_inshorts(data):
    data, err = _normalize_format_input(data, "INSHORTS")
    if err:
        return "" if "No data" in err else err

    lines = ["=== INSHORTS ==="]
    for s in _safe_list(data.get('stories'))[:10]:
        s = _safe_dict(s)
        lines.append(f"  [{s.get('category', '?')}] {str(s.get('title', ''))[:100]}")
    return "\n".join(lines)


def format_youtube(data):
    data, err = _normalize_format_input(data, "TV")
    if err:
        return err

    lines = ["=== TV/YOUTUBE ==="]
    lines.append(f"Videos: {data.get('total_videos', 0)} | Live: {data.get('live_streams', 0)}")
    for v in _safe_list(data.get('live_now'))[:4]:
        v = _safe_dict(v)
        lines.append(f"  LIVE [{v.get('channel', '?')}] {str(v.get('title', ''))[:80]}")
    for v in _safe_list(data.get('recent_videos'))[:6]:
        v = _safe_dict(v)
        lines.append(f"  [{v.get('channel', '?')}] {str(v.get('title', ''))[:80]}")
    stock_mentions = data.get('stock_mentions', {})
    if isinstance(stock_mentions, dict):
        for stock, count in list(stock_mentions.items())[:8]:
            lines.append(f"  TV mention: {stock} ({count}x)")
    return "\n".join(lines)


def format_govt(data):
    data, err = _normalize_format_input(data, "GOVT")
    if err:
        return err

    lines = ["=== GOVT INTELLIGENCE ==="]
    lines.append(f"HIGH: {data.get('high_impact_count', 0)} | MED: {data.get('medium_impact_count', 0)}")
    for i, item in enumerate(_safe_list(data.get('high_impact_items'))[:6], 1):
        item = _safe_dict(item)
        headline = str(item.get('english_headline', item.get('title', '')))[:120]
        stocks = _safe_list(item.get('affected_stocks'))
        lines.append(f"  {i}. [{item.get('impact_score', 0)}/10 {item.get('direction', '?')}] {headline}")
        if stocks:
            lines.append(f"     Affects: {', '.join(str(s) for s in stocks[:5])}")
    return "\n".join(lines)


def format_reddit(data):
    data, err = _normalize_format_input(data, "REDDIT")
    if err:
        return err

    lines = ["=== REDDIT SENTIMENT ==="]
    mood = _safe_dict(data.get('market_mood'))
    lines.append(f"Mood: {str(mood.get('sentiment', '?')).upper()} ({mood.get('confidence', 0)}%)")
    for t in _safe_list(data.get('trending_tickers'))[:8]:
        t = _safe_dict(t)
        lines.append(f"  {t.get('ticker', '?')}: {t.get('mentions', 0)} mentions | {str(t.get('sentiment', '?')).upper()}")
    for h in _safe_list(data.get('hot_discussions'))[:5]:
        h = _safe_dict(h)
        lines.append(f"  [{h.get('score', 0)}up] {str(h.get('title', ''))[:100]}")
    return "\n".join(lines)


def format_scanner(data):
    data, err = _normalize_format_input(data, "SCANNER")
    if err:
        return err

    lines = ["=== NSE SCANNER ==="]
    lines.append(f"Scanned: {data.get('total_scanned', 0)} | Signals: {data.get('total_signals', 0)}")
    for s in _safe_list(data.get('top_signals'))[:15]:
        s = _safe_dict(s)
        signals = s.get('signals', [])
        sig_text = ' + '.join(signals[:3]) if isinstance(signals, list) else str(signals)
        lines.append(
            f"  [{s.get('strength', '?')}|{s.get('direction', '?')}] "
            f"{s.get('ticker', '?')} ({s.get('sector', '?')}) "
            f"Rs.{s.get('price', 0)} {s.get('change_percent', 0):+.2f}% "
            f"vol:{s.get('volume_ratio', 0):.1f}x | {sig_text}"
        )
    for r in _safe_list(data.get('sector_rotation'))[:8]:
        r = _safe_dict(r)
        lines.append(
            f"  SECTOR [{r.get('direction', '?')}] {r.get('sector', '?')}: "
            f"{r.get('avg_change_percent', 0):+.2f}% "
            f"({r.get('stocks_analyzed', 0)} stocks)"
        )
    return "\n".join(lines)


def format_twitter(data):
    data, err = _normalize_format_input(data, "TWITTER")
    if err:
        return "" if "No data" in err else err

    lines = ["=== TWITTER ==="]
    for t in _safe_list(data.get('tweets'))[:8]:
        t = _safe_dict(t)
        lines.append(f"  [{t.get('account', '?')}] {str(t.get('text', ''))[:100]}")
    return "\n".join(lines)


def format_nse(data):
    data, err = _normalize_format_input(data, "NSE FILINGS")
    if err:
        return "" if "No data" in err else err

    lines = ["=== NSE FILINGS ==="]
    for item in _safe_list(data.get('latest_high_impact'))[:5]:
        item = _safe_dict(item)
        lines.append(f"  [{item.get('symbol', '?')}] {item.get('impact_category', '?')} | {str(item.get('subject', ''))[:80]}")
    return "\n".join(lines)


def format_telegram(data):
    data, err = _normalize_format_input(data, "TELEGRAM")
    if err:
        return "" if "No data" in err else err

    lines = ["=== TELEGRAM SENTIMENT ==="]
    mood = _safe_dict(data.get('market_mood', data.get('overall_sentiment')))
    if mood:
        lines.append(f"Mood: {mood.get('sentiment', mood.get('label', '?'))}")
    channels = _safe_list(data.get('channels', data.get('messages')))
    for ch in channels[:6]:
        ch = _safe_dict(ch)
        lines.append(f"  [{ch.get('channel', ch.get('name', '?'))}] {str(ch.get('text', ch.get('summary', '')))[:100]}")
    return "\n".join(lines) if len(lines) > 1 else ""


def build_memory_context():
    if not LEARNING_AVAILABLE or not build_memory_summary:
        return "No performance history yet. Using conservative default calibration."
    try:
        return build_memory_summary()
    except Exception as e:
        print(f"[WARN] build_memory_summary failed: {e}")
        return f"Memory unavailable: {e}"


def is_indian_market_open():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0)
    market_close = now.replace(hour=15, minute=30, second=0)
    return market_open <= now <= market_close


REQUIRED_JSON_FIELDS = [
    'executive_summary',
    'government_impact',
    'sector_rotation',
    'market_mood',
    'self_calibration',
    'top_opportunities',
    'risks_and_avoids',
    'action_plan',
]


def validate_analysis_json(parsed):
    """Return (ok, missing_or_invalid_fields)."""
    if not isinstance(parsed, dict):
        return False, ['root (not an object)']

    problems = []
    for field in REQUIRED_JSON_FIELDS:
        if field not in parsed or parsed[field] in (None, ''):
            problems.append(field)

    if 'government_impact' in parsed and not isinstance(parsed['government_impact'], dict):
        problems.append('government_impact (not an object)')
    if 'sector_rotation' in parsed and not isinstance(parsed['sector_rotation'], dict):
        problems.append('sector_rotation (not an object)')
    if 'market_mood' in parsed and not isinstance(parsed['market_mood'], dict):
        problems.append('market_mood (not an object)')
    if 'top_opportunities' in parsed and not isinstance(parsed['top_opportunities'], list):
        problems.append('top_opportunities (not a list)')
    if 'risks_and_avoids' in parsed and not isinstance(parsed['risks_and_avoids'], list):
        problems.append('risks_and_avoids (not a list)')

    return len(problems) == 0, problems


def generate_unified_analysis(all_data):
    print("\n[ANALYSIS] Building prompt from all data sources...")
    print("[DEBUG] Data types: " + ", ".join(
        f"{k}:{type(v).__name__}" for k, v in all_data.items()
    ))

    try:
        global_str = format_global_markets(all_data.get('global_markets'))
    except Exception as e:
        print(f"[ERROR] format_global_markets crashed: {e}")
        traceback.print_exc()
        global_str = "GLOBAL MARKETS: Error formatting"

    try:
        india_str = format_india_markets(all_data.get('india_markets'))
    except Exception as e:
        print(f"[ERROR] format_india_markets crashed: {e}")
        traceback.print_exc()
        india_str = "INDIA: Error formatting"

    try:
        news_str = format_news(all_data.get('news'))
    except Exception as e:
        print(f"[ERROR] format_news crashed: {e}")
        traceback.print_exc()
        news_str = "NEWS: Error formatting"

    try:
        inshorts_str = format_inshorts(all_data.get('inshorts'))
    except Exception as e:
        print(f"[ERROR] format_inshorts crashed: {e}")
        traceback.print_exc()
        inshorts_str = ""

    try:
        youtube_str = format_youtube(all_data.get('youtube'))
    except Exception as e:
        print(f"[ERROR] format_youtube crashed: {e}")
        traceback.print_exc()
        youtube_str = "TV: Error formatting"

    try:
        govt_str = format_govt(all_data.get('govt'))
    except Exception as e:
        print(f"[ERROR] format_govt crashed: {e}")
        traceback.print_exc()
        govt_str = "GOVT: Error formatting"

    try:
        reddit_str = format_reddit(all_data.get('reddit'))
    except Exception as e:
        print(f"[ERROR] format_reddit crashed: {e}")
        traceback.print_exc()
        reddit_str = "REDDIT: Error formatting"

    try:
        scanner_str = format_scanner(all_data.get('scanner'))
    except Exception as e:
        print(f"[ERROR] format_scanner crashed: {e}")
        traceback.print_exc()
        scanner_str = "SCANNER: Error formatting"

    try:
        twitter_str = format_twitter(all_data.get('twitter'))
    except Exception as e:
        print(f"[ERROR] format_twitter crashed: {e}")
        traceback.print_exc()
        twitter_str = ""

    try:
        nse_str = format_nse(all_data.get('nse_filings'))
    except Exception as e:
        print(f"[ERROR] format_nse crashed: {e}")
        traceback.print_exc()
        nse_str = ""

    try:
        telegram_str = format_telegram(all_data.get('telegram'))
    except Exception as e:
        print(f"[ERROR] format_telegram crashed: {e}")
        traceback.print_exc()
        telegram_str = ""

    memory_str = build_memory_context()

    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')

    prompt = f"""You are an institutional-grade Indian market intelligence AI.
Time: {current_time}
Market Open: {is_indian_market_open()}

SELF-CALIBRATION MEMORY:
{memory_str}

{nse_str}
{govt_str}
{scanner_str}
{global_str}
{india_str}
{news_str}
{inshorts_str}
{youtube_str}
{reddit_str}
{twitter_str}
{telegram_str}

CRITICAL INSTRUCTION: You are a backend API. Output ONLY valid JSON. No markdown. No explanations.

Required JSON schema:
{{
  "executive_summary": "2-3 sentences summarizing market bias and macro conditions.",
  "government_impact": {{
    "summary": "Brief summary of policy impact",
    "confidence_score": "5/10"
  }},
  "sector_rotation": {{
    "bullish": ["TELECOM", "PHARMA"],
    "bearish": ["CHEMICALS", "MEDIA"]
  }},
  "market_mood": {{
    "global_mood": "BEARISH",
    "india_outlook": "CAUTIOUSLY BULLISH",
    "retail_mood": "NEUTRAL",
    "confidence_level": "6.5/10"
  }},
  "self_calibration": "Based on past performance...",
  "top_opportunities": [
    {{
      "symbol": "ERIS",
      "action": "BUY",
      "entry_zone": "1450-1460",
      "target": "1580",
      "stop_loss": "1390",
      "confidence": "HIGH",
      "logic": "Reason here."
    }}
  ],
  "risks_and_avoids": [
    {{
      "symbol": "PIIND",
      "logic": "Reason here."
    }}
  ],
  "action_plan": "Actionable steps for today."
}}

RULES:
- Give exactly 10 items in top_opportunities AND 10 in risks_and_avoids
- Use ONLY actual NSE tickers
- ULTRA scanner signals MUST appear in top 5 opportunities
- No repeated tickers
- Output ONLY valid JSON, no markdown
"""

    if not AI_ROUTER_AVAILABLE or not ask_ai:
        print("  [ERROR] ai_router unavailable — cannot call AI")
        return None

    use_case = os.environ.get('AI_USE_CASE', 'manual_refresh')
    try:
        raw_result = ask_ai(prompt, use_case=use_case, max_tokens=8000)
        result = validate_ai_response(raw_result, source='master_analyzer') if validate_ai_response else raw_result
    except Exception as e:
        print(f"  [ERROR] ask_ai raised exception: {e}")
        traceback.print_exc()
        return None

    if isinstance(result, str):
        print(f"[WARN] ai_router returned string instead of dict: {result[:100]}")
        result = {
            'success': bool(result),
            'text': result,
            'model': 'unknown',
            'provider': 'unknown',
            'estimated_cost': 0,
            'error': None,
        }

    if not isinstance(result, dict):
        print(f"[ERROR] ai_router returned {type(result)}: {result}")
        return None

    if not result.get('success'):
        print(f"  ERROR: {result.get('error', 'Unknown')}")
        return None

    print(f"  [AI] Used: {result.get('model', '?')} ({result.get('provider', '?')})")
    ai_text = result.get('text') or ''
    if not ai_text:
        print("  [ERROR] AI returned empty text")
        return None

    clean_text = ai_text.strip()
    if "```json" in clean_text:
        clean_text = clean_text.split("```json")[1].split("```")[0].strip()
    elif "```" in clean_text:
        clean_text = clean_text.split("```")[1].split("```")[0].strip()

    try:
        parsed = json.loads(clean_text)
    except json.JSONDecodeError as e:
        print(f"  [ERROR] JSON parse failed: {e}")
        print(f"  [ERROR] Line {e.lineno}, col {e.colno}: {e.msg}")
        print(f"  [ERROR] Clean text preview:\n{clean_text[:800]}")
        print(f"  [ERROR] Raw AI response preview:\n{ai_text[:800]}")
        return None

    ok, problems = validate_analysis_json(parsed)
    if not ok:
        print(f"  [WARN] Invalid or missing fields: {problems}")
        return None

    return parsed


def run_master_analysis():
    try:
        print("\n" + "=" * 60)
        print("MASTER ANALYZER v10 - Clean JSON Engine")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"AI Router: {'OK' if AI_ROUTER_AVAILABLE else 'MISSING'}")
        print(f"Learning Engine: {'OK' if LEARNING_AVAILABLE else 'MISSING'}")
        print("=" * 60)

        print("\n[STEP 1] Gathering data...")
        all_data = gather_all_data()

        sources_loaded = sum(1 for v in all_data.values() if v)
        for source, data in all_data.items():
            status = "OK  " if data else "MISS"
            detail = ""
            if data and isinstance(data, dict):
                if 'total_articles' in data:
                    detail = f" ({data.get('total_articles', 0)} articles)"
                elif 'prices' in data:
                    detail = f" ({len(data.get('prices', {}))} prices)"
                elif 'top_signals' in data:
                    detail = f" ({data.get('total_signals', 0)} signals)"
            print(f"  {status} {source}{detail}")

        if sources_loaded == 0:
            print("\n[ERROR] No data sources available — cannot analyze")
            return None

        print(f"\n[INFO] {sources_loaded}/{len(all_data)} sources loaded")

        analysis_dict = None
        for attempt in range(3):
            if attempt > 0:
                print(f"\n[RETRY {attempt}/2] Retrying analysis...")
            try:
                analysis_dict = generate_unified_analysis(all_data)
            except Exception as e:
                print(f"[ERROR] generate_unified_analysis attempt {attempt + 1} crashed: {e}")
                traceback.print_exc()
                analysis_dict = None
            if analysis_dict:
                break

        if not analysis_dict:
            print("\n[ERROR] Failed after 3 attempts — unified_intelligence.json NOT updated")
            return None

        print("\n" + "=" * 60)
        print("ANALYSIS COMPLETE")
        print("=" * 60)

        output = {
            'timestamp': datetime.now().isoformat(),
            'generation_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'market_open': is_indian_market_open(),
            'sources_used': sources_loaded,
            'memory_augmented': LEARNING_AVAILABLE,
            'data_snapshot': {
                'govt_high_impact':   all_data['govt'].get('high_impact_count', 0) if all_data.get('govt') else 0,
                'news_articles':      all_data['news'].get('total_articles', 0) if all_data.get('news') else 0,
                'scanner_stocks':     all_data['scanner'].get('total_scanned', 0) if all_data.get('scanner') else 0,
                'scanner_signals':    all_data['scanner'].get('total_signals', 0) if all_data.get('scanner') else 0,
                'reddit_mood':        _safe_dict(all_data['reddit'].get('market_mood')).get('sentiment', 'unknown') if all_data.get('reddit') else 'unknown',
                'tv_videos':          all_data['youtube'].get('total_videos', 0) if all_data.get('youtube') else 0,
            }
        }

        output.update(analysis_dict)

        data_dir = Path(__file__).parent.parent / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        output_file = data_dir / 'unified_intelligence.json'

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, default=str, ensure_ascii=False)

        print(f"\n[SAVED] {output_file}")
        return output

    except Exception as e:
        print(f"\n[FATAL] run_master_analysis crashed: {e}")
        traceback.print_exc()
        return None


if __name__ == "__main__":
    print("Starting master analyzer v10...")
    result = None
    try:
        result = run_master_analysis()
        if result:
            print("[DONE] Analysis succeeded")
            try:
                from context_snapshot import capture_snapshot, init_context_table
                init_context_table()
                snapshot_id = capture_snapshot(run_type='master_analyzer')
                print(f"[CONTEXT] Snapshot: {snapshot_id}")
            except Exception as e:
                print(f"[WARN] Snapshot failed: {e}")
                traceback.print_exc()
        else:
            print("[FAILED] Analysis returned None — check logs above")
    except Exception as e:
        print(f"[FATAL] Unhandled error in __main__: {e}")
        traceback.print_exc()
    sys.exit(0 if result else 1)