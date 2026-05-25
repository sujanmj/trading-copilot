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
    sources = {
        'global_markets': data_dir / 'global_markets.json',
        'india_markets':  data_dir / 'latest_market_data.json',
        'news':           data_dir / 'news_feed.json',
        'youtube':        data_dir / 'youtube_feed.json',
        'govt':           data_dir / 'govt_intelligence.json',
        'inshorts':       data_dir / 'inshorts_feed.json',
        'reddit':         data_dir / 'reddit_data.json',
        'telegram':       data_dir / 'telegram_sentiment.json',
        'scanner':        data_dir / 'scanner_data.json',
        'twitter':        data_dir / 'twitter_data.json',
        'nse_filings':    data_dir / 'nse_announcements.json',
    }
    result = {}
    for name, path in sources.items():
        raw = load_json_safe(path)
        result[name] = _coerce_source_data(raw, name)
    return result


def format_global_markets(data):
    if not data:
        return "GLOBAL MARKETS: No data"
    lines = ["=== GLOBAL MARKETS ==="]
    for region, info in data.get('sentiment', {}).items():
        avg = info.get('average_change', info.get('expected_open', 0))
        lines.append(f"  {region.upper()}: {info.get('mood','?')} ({avg:+.2f}%)")
    for group, symbols in data.get('markets', {}).items():
        lines.append(f"\n[{group}]")
        for name, info in list(symbols.items())[:5]:
            change = info.get('change_percent', 0)
            lines.append(f"  {name}: {info.get('price',0):,.0f} ({change:+.2f}%)")
    for a in data.get('alerts', [])[:5]:
        lines.append(f"  ALERT: {a.get('message','')}")
    return "\n".join(lines)


def format_india_markets(data):
    if not data:
        return "INDIA MARKETS: No data"
    lines = ["=== INDIA STOCKS ==="]
    for name, info in data.get('prices', {}).items():
        change = info.get('change_percent', 0)
        lines.append(f"  {name}: Rs.{info.get('price',0):,.2f} ({change:+.2f}%)")
    return "\n".join(lines)


def format_news(data):
    if not data:
        return "NEWS: No data"
    lines = ["=== NEWS ==="]
    lines.append(f"Articles: {data.get('total_articles', 0)}")
    for stock, count in list(data.get('top_stocks', {}).items())[:10]:
        lines.append(f"  {stock}: {count} articles")
    for h in data.get('hot_stocks', [])[:5]:
        lines.append(f"  HOT [{h.get('velocity','?')}] {h.get('stock','?')}: {h.get('mention_count',0)} mentions")
    for a in data.get('articles', [])[:15]:
        lines.append(f"  [{a.get('sentiment_label','?')[:3].upper()}] {a.get('title','')[:100]}")
    return "\n".join(lines)


def format_inshorts(data):
    if not data:
        return ""
    lines = ["=== INSHORTS ==="]
    for s in data.get('stories', [])[:10]:
        lines.append(f"  [{s.get('category','?')}] {s.get('title','')[:100]}")
    return "\n".join(lines)


def format_youtube(data):
    if not data:
        return "TV: No data"
    lines = ["=== TV/YOUTUBE ==="]
    lines.append(f"Videos: {data.get('total_videos',0)} | Live: {data.get('live_streams',0)}")
    for v in data.get('live_now', [])[:4]:
        lines.append(f"  LIVE [{v.get('channel','?')}] {v.get('title','')[:80]}")
    for v in data.get('recent_videos', [])[:6]:
        lines.append(f"  [{v.get('channel','?')}] {v.get('title','')[:80]}")
    for stock, count in list(data.get('stock_mentions', {}).items())[:8]:
        lines.append(f"  TV mention: {stock} ({count}x)")
    return "\n".join(lines)


def format_govt(data):
    if not data:
        return "GOVT: No data"
    lines = ["=== GOVT INTELLIGENCE ==="]
    lines.append(f"HIGH: {data.get('high_impact_count',0)} | MED: {data.get('medium_impact_count',0)}")
    for i, item in enumerate(data.get('high_impact_items', [])[:6], 1):
        headline = item.get('english_headline', item.get('title',''))[:120]
        stocks = item.get('affected_stocks', [])
        lines.append(f"  {i}. [{item.get('impact_score',0)}/10 {item.get('direction','?')}] {headline}")
        if stocks:
            lines.append(f"     Affects: {', '.join(stocks[:5])}")
    return "\n".join(lines)


def format_reddit(data):
    if not data:
        return "REDDIT: No data"
    lines = ["=== REDDIT SENTIMENT ==="]
    mood = data.get('market_mood', {})
    lines.append(f"Mood: {mood.get('sentiment','?').upper()} ({mood.get('confidence',0)}%)")
    for t in data.get('trending_tickers', [])[:8]:
        lines.append(f"  {t.get('ticker','?')}: {t.get('mentions',0)} mentions | {t.get('sentiment','?').upper()}")
    for h in data.get('hot_discussions', [])[:5]:
        lines.append(f"  [{h.get('score',0)}up] {h.get('title','')[:100]}")
    return "\n".join(lines)


def format_scanner(data):
    if not data:
        return "SCANNER: No data"
    lines = ["=== NSE SCANNER ==="]
    lines.append(f"Scanned: {data.get('total_scanned',0)} | Signals: {data.get('total_signals',0)}")
    for s in data.get('top_signals', [])[:15]:
        lines.append(
            f"  [{s.get('strength','?')}|{s.get('direction','?')}] "
            f"{s.get('ticker','?')} ({s.get('sector','?')}) "
            f"Rs.{s.get('price',0)} {s.get('change_percent',0):+.2f}% "
            f"vol:{s.get('volume_ratio',0):.1f}x | "
            f"{' + '.join(s.get('signals',[])[:3])}"
        )
    for r in data.get('sector_rotation', [])[:8]:
        lines.append(
            f"  SECTOR [{r.get('direction','?')}] {r.get('sector','?')}: "
            f"{r.get('avg_change_percent',0):+.2f}% "
            f"({r.get('stocks_analyzed',0)} stocks)"
        )
    return "\n".join(lines)


def format_twitter(data):
    if not data:
        return ""
    lines = ["=== TWITTER ==="]
    for t in data.get('tweets', [])[:8]:
        lines.append(f"  [{t.get('account','?')}] {t.get('text','')[:100]}")
    return "\n".join(lines)


def format_nse(data):
    if not data:
        return ""
    lines = ["=== NSE FILINGS ==="]
    for item in data.get('latest_high_impact', [])[:5]:
        lines.append(f"  [{item.get('symbol','?')}] {item.get('impact_category','?')} | {item.get('subject','')[:80]}")
    return "\n".join(lines)


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

    global_str   = format_global_markets(all_data.get('global_markets'))
    india_str    = format_india_markets(all_data.get('india_markets'))
    news_str     = format_news(all_data.get('news'))
    inshorts_str = format_inshorts(all_data.get('inshorts'))
    youtube_str  = format_youtube(all_data.get('youtube'))
    govt_str     = format_govt(all_data.get('govt'))
    reddit_str   = format_reddit(all_data.get('reddit'))
    scanner_str  = format_scanner(all_data.get('scanner'))
    twitter_str  = format_twitter(all_data.get('twitter'))
    nse_str      = format_nse(all_data.get('nse_filings'))
    memory_str   = build_memory_context()

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
                'reddit_mood':        all_data['reddit'].get('market_mood', {}).get('sentiment', 'unknown') if all_data.get('reddit') else 'unknown',
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