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

from backend.utils.config import DATA_DIR

print("[BOOT] master_analyzer.py starting...")

if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass


from backend.storage.json_io import atomic_write_json

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
    from backend.ai.ai_router import ask_ai
    from backend.ai.response_validator import validate_ai_response
    AI_ROUTER_AVAILABLE = True
    print("[OK] imported ai_router")
    print("[OK] imported response_validator")
except ImportError as e:
    AI_ROUTER_AVAILABLE = False
    ask_ai = None
    validate_ai_response = None
    print(f"[FAIL] ai_router not available: {e}")

try:
    from backend.analyzers.learning_engine import build_memory_summary
    LEARNING_AVAILABLE = True
    print("[OK] imported learning_engine")
except ImportError as e:
    LEARNING_AVAILABLE = False
    build_memory_summary = None
    print(f"[FAIL] learning_engine not available: {e}")

def _load_env_keys():
    """Load env via config (Railway /app/config/keys.env or config/keys.env)."""
    from backend.utils.config import load_env, get_env, IS_RAILWAY, CONFIG_DIR
    load_env()
    has_keys = bool(get_env('ANTHROPIC_API_KEY') or get_env('GOOGLE_API_KEY') or get_env('GEMINI_API_KEY'))
    if IS_RAILWAY:
        print("[OK] Railway deployment — using platform environment")
    elif (CONFIG_DIR / 'keys.env').exists():
        print(f"[OK] loaded env from {CONFIG_DIR / 'keys.env'}")
    elif has_keys:
        print("[OK] API keys present in environment")
    else:
        print("[INFO] No API keys in environment yet")


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
    data_dir = DATA_DIR
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

    from backend.utils.market_data_validator import sanitize_for_analyzer
    if validated.get('india_markets'):
        validated['india_markets'] = sanitize_for_analyzer(validated['india_markets'])
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
    """Always return a plain string for prompt injection — never a dict."""
    if not LEARNING_AVAILABLE or not build_memory_summary:
        return "No performance history yet. Using conservative default calibration."
    try:
        summary = build_memory_summary()
        if summary is None:
            return "No performance history yet."
        if isinstance(summary, dict):
            print("[WARN] build_memory_summary returned dict — converting to string")
            return json.dumps(summary, indent=2, default=str)
        if isinstance(summary, str):
            return summary
        return str(summary)
    except AttributeError as e:
        print(f"[WARN] build_memory_summary AttributeError (likely .get on non-dict): {e}")
        traceback.print_exc()
        return f"Memory unavailable: {e}"
    except Exception as e:
        print(f"[WARN] build_memory_summary failed: {e}")
        traceback.print_exc()
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


def _extract_known_tickers(all_data):
    tickers = set()
    scanner = _safe_dict(all_data.get('scanner'))
    for sig in scanner.get('top_signals') or []:
        if isinstance(sig, dict):
            t = str(sig.get('ticker') or '').strip().upper()
            if t:
                tickers.add(t)
    india = _safe_dict(all_data.get('india_markets'))
    for sym in (india.get('prices') or {}):
        tickers.add(str(sym).upper())
    return list(tickers)


def validate_analysis_json(parsed):
    """Return (ok, missing_or_invalid_fields) — delegates to reliability schemas."""
    if not isinstance(parsed, dict):
        return False, ['root (not an object)']
    try:
        from backend.ai.reliability.hallucination import detect_hallucinations, validate_schema
        model, schema_errors = validate_schema(parsed)
        if model is None:
            return False, schema_errors or ['schema_validation_failed']
        issues = detect_hallucinations(parsed)
        if len(issues) >= 4:
            return False, issues
        return True, []
    except Exception as e:
        problems = []
        for field in REQUIRED_JSON_FIELDS:
            if field not in parsed or parsed[field] in (None, ''):
                problems.append(field)
        if problems:
            return False, problems
        return False, [str(e)]


def _build_format_sections(all_data):
    """Build formatted section strings (used by compression pipeline)."""
    sections = {}

    def _safe_fmt(name, fn, key, fallback=''):
        try:
            sections[name] = fn(all_data.get(key))
        except Exception as e:
            print(f"[ERROR] format_{name} crashed: {e}")
            traceback.print_exc()
            sections[name] = fallback or f"{name.upper()}: Error formatting"

    _safe_fmt('global', format_global_markets, 'global_markets')
    _safe_fmt('india', format_india_markets, 'india_markets')
    _safe_fmt('news', format_news, 'news')
    _safe_fmt('inshorts', format_inshorts, 'inshorts', '')
    _safe_fmt('youtube', format_youtube, 'youtube')
    _safe_fmt('govt', format_govt, 'govt')
    _safe_fmt('reddit', format_reddit, 'reddit')
    _safe_fmt('scanner', format_scanner, 'scanner')
    _safe_fmt('twitter', format_twitter, 'twitter', '')
    _safe_fmt('nse', format_nse, 'nse_filings', '')
    _safe_fmt('telegram', format_telegram, 'telegram', '')
    return sections


def generate_unified_analysis(all_data, compressed_context=None, force_claude=False):
    print("[DEBUG] all_data types:")
    if not isinstance(all_data, dict):
        print(f"  [CRASH] all_data is {type(all_data).__name__}, expected dict")
        return None
    for k, v in all_data.items():
        print(f"  {k}: {type(v).__name__} = {str(v)[:80] if v is not None else 'None'}")

    try:
        from backend.ai.intelligence_compressor import prepare_intelligence_pipeline, persist_analysis_state
        from backend.ai.ai_pipeline_router import call_expensive, pipeline_status
        from backend.ai.ai_budget_manager import budget_status

        from backend.ai.token_optimizer import cap_prompt, estimate_tokens, compress_section

        print("\n[ANALYSIS] Cost-efficient pipeline...")

        use_case = os.environ.get('AI_USE_CASE', 'manual_refresh')
        force = force_claude or use_case == 'manual_refresh'
        pipeline_quality = {}
        preservation_ctx = {}

        if compressed_context is None:
            pipeline = prepare_intelligence_pipeline(all_data, _build_format_sections, force=force)
            if pipeline.get('reuse_intel'):
                print("[CLAUDE SKIPPED] Returning reused intelligence")
                return pipeline['reuse_intel']
            compressed_context = pipeline.get('compressed_context') or ''
            pipeline_quality = pipeline.get('quality_metrics') or {}
            preservation_ctx = pipeline.get('preservation') or {}
            persist_analysis_state(
                pipeline.get('decision') or {},
                preservation=preservation_ctx,
                quality=pipeline_quality,
            )
            if pipeline_quality:
                print(
                    f"[QUALITY SCORE] IQ={pipeline_quality.get('intelligence_quality_score', '?')} "
                    f"ratio={pipeline_quality.get('compression_ratio', '?')} "
                    f"regime={((pipeline.get('preservation') or {}).get('regime') or {}).get('primary_regime', '?')}"
                )

        memory_str = build_memory_context()
        if not isinstance(memory_str, str):
            memory_str = str(memory_str)

        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')
        budget = budget_status()
        print(f"[AI COST] Budget: ${budget['spent']:.4f}/${budget['limit']:.2f} "
              f"low_cost={budget['low_cost_mode']}")

        prompt = f"""You are an institutional-grade Indian market intelligence AI.
Time: {current_time}
Market Open: {is_indian_market_open()}

SELF-CALIBRATION MEMORY (keep brief in output):
{compress_section(memory_str, 2500)}

COMPRESSED MARKET INTELLIGENCE (deduplicated, ranked, preservation-layer enriched):
{compressed_context}

PRESERVATION RULES:
- RAW HIGH-IMPACT EVIDENCE section is verbatim — treat as highest priority
- CONTRADICTIONS section lists opposing signals — reflect BOTH sides in mood and risks
- SCORED SIGNALS include confidence/source_count/agreement_score/impact_score — use these for ranking
- Do NOT flatten disagreement or remove minority/outlier signals
- If regime is PANIC/VOLATILE or REGIME TRANSITION, widen confidence intervals and add caution

CRITICAL: Output ONLY valid JSON. No markdown. No explanations.

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
- Exactly 10 top_opportunities AND 10 risks_and_avoids
- Use ONLY actual NSE tickers
- ULTRA scanner signals MUST appear in top 5 opportunities
- No repeated tickers
- Output ONLY valid JSON
"""

        prompt = cap_prompt(prompt)
        print(f"[COMPRESSOR] Final synthesis prompt ~{estimate_tokens(prompt)} tokens")

        if not AI_ROUTER_AVAILABLE:
            print("  [ERROR] ai_router unavailable — cannot call AI")
            return None

        try:
            from backend.ai.pipeline_observability import record_claude_decision, finalize_cycle
        except Exception as obs_import_err:
            record_claude_decision = None
            finalize_cycle = None
            print(f"  [WARN] pipeline_observability unavailable (non-fatal): {obs_import_err}")

        raw_result = call_expensive(
            prompt,
            use_case='final_synthesis',
            max_tokens=4500,
            force=force,
        )

        model = raw_result.get('model', '') if isinstance(raw_result, dict) else ''
        provider = raw_result.get('provider', '') if isinstance(raw_result, dict) else ''
        cache_hit = bool(isinstance(raw_result, dict) and raw_result.get('_from_cache'))
        claude_ran = bool(
            raw_result.get('success')
            and ('sonnet' in str(model).lower() or provider == 'anthropic')
        )
        skipped_reason = None
        if not claude_ran:
            if cache_hit and raw_result.get('success'):
                skipped_reason = 'synthesis served from cache (may be Gemini or Claude cached result)'
            elif not raw_result.get('success'):
                skipped_reason = f"synthesis failed: {raw_result.get('error')}"
            else:
                skipped_reason = f"Claude bypassed — used {model} ({provider})"

        if record_claude_decision:
            try:
                record_claude_decision(
                    ran=claude_ran,
                    skipped_reason=skipped_reason,
                    model=model,
                    provider=provider,
                    cache_hit=cache_hit,
                    prompt_tokens=estimate_tokens(prompt),
                    force=force,
                    budget=budget,
                )
            except Exception as obs_err:
                print(f"  [WARN] record_claude_decision skipped: {obs_err}")
        if finalize_cycle:
            try:
                finalize_cycle(quality=pipeline_quality)
            except Exception as obs_err:
                print(f"  [WARN] finalize_cycle skipped: {obs_err}")

        result = validate_ai_response(raw_result, source='master_analyzer') if validate_ai_response else raw_result

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

        from backend.ai.reliability.response_gateway import (
            build_retry_prompt,
            process_intelligence_synthesis,
        )
        from backend.metrics.execution_metrics import record_reliability_event

        regime_info = preservation_ctx.get('regime') or {}
        contra = preservation_ctx.get('contradictions') or {}
        gateway_context = {
            'known_tickers': _extract_known_tickers(all_data),
            'preservation': preservation_ctx,
            'scanner': _safe_dict(all_data.get('scanner')),
            'regime': regime_info.get('primary_regime') or 'sideways',
            'sentiment_diversity_score': pipeline_quality.get('sentiment_diversity_score'),
            'novelty_avg_score': pipeline_quality.get('novelty_avg_score'),
            'contradiction_severity': contra.get('overall_disagreement_score'),
        }

        def _retry_synthesis():
            if cache_hit:
                return None
            retry_prompt = build_retry_prompt(prompt)
            retry_raw = call_expensive(
                retry_prompt,
                use_case='final_synthesis',
                max_tokens=3500,
                force=force,
            )
            retry_result = validate_ai_response(retry_raw, source='master_analyzer_retry')
            if isinstance(retry_result, dict) and retry_result.get('success'):
                return retry_result.get('text')
            return None

        gateway = process_intelligence_synthesis(
            ai_text,
            context=gateway_context,
            retry_callback=_retry_synthesis if not cache_hit else None,
        )

        if not gateway.success or not gateway.data:
            print(f"  [ERROR] Reliability gateway rejected output: "
                  f"{(gateway.hallucinations + gateway.schema_errors)[:5]}")
            record_reliability_event('signal_survival', ok=False)
            return None

        if gateway.used_fallback:
            print("  [SAFE FALLBACK] Serving last-valid intelligence (degraded)")

        rel_score = (gateway.data.get('reliability_meta') or {}).get('reliability_score')
        if rel_score is not None:
            record_reliability_event('signal_survival', ok=True, reliability_score=rel_score)

        return gateway.data

    except AttributeError as e:
        print(f"[CRASH] AttributeError: {e}")
        print("[CRASH] Full traceback:")
        traceback.print_exc()
        return None
    except Exception as e:
        print(f"[CRASH] Exception: {e}")
        traceback.print_exc()
        return None


def run_master_analysis():
    try:
        print("\n" + "=" * 60)
        print("MASTER ANALYZER v11 - Cost-Efficient Pipeline")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"AI Router: {'OK' if AI_ROUTER_AVAILABLE else 'MISSING'}")
        print(f"Learning Engine: {'OK' if LEARNING_AVAILABLE else 'MISSING'}")
        print("=" * 60)

        try:
            from backend.ai.ai_budget_manager import budget_status
            from backend.ai.ai_pipeline_router import pipeline_status
            b = budget_status()
            print(f"[AI COST] Daily spend ${b['spent']:.4f}/${b['limit']:.2f} "
                  f"low_cost={b['low_cost_mode']}")
        except Exception:
            pipeline_status = budget_status = None

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

        force = os.environ.get('AI_USE_CASE') == 'manual_refresh'
        analysis_dict = None
        for attempt in range(3):
            if attempt > 0:
                print(f"\n[RETRY {attempt}/2] Retrying analysis...")
            try:
                analysis_dict = generate_unified_analysis(all_data, force_claude=force)
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
                'govt_high_impact':   _safe_dict(all_data.get('govt')).get('high_impact_count', 0),
                'news_articles':      _safe_dict(all_data.get('news')).get('total_articles', 0),
                'scanner_stocks':     _safe_dict(all_data.get('scanner')).get('total_scanned', 0),
                'scanner_signals':    _safe_dict(all_data.get('scanner')).get('total_signals', 0),
                'reddit_mood':        _safe_dict(_safe_dict(all_data.get('reddit')).get('market_mood')).get('sentiment', 'unknown'),
                'tv_videos':          _safe_dict(all_data.get('youtube')).get('total_videos', 0),
            },
        }

        output.update(analysis_dict)
        output['pipeline_meta'] = pipeline_status() if pipeline_status else {}
        output['reused'] = bool(analysis_dict.get('reused'))
        if analysis_dict.get('reliability_meta'):
            output['reliability_meta'] = analysis_dict['reliability_meta']
        if analysis_dict.get('confidence_metrics'):
            output['confidence_metrics'] = analysis_dict['confidence_metrics']

        from backend.ai.reliability.response_gateway import validate_for_persistence
        persist_ok, safe_output = validate_for_persistence(output)
        if not persist_ok:
            print("\n[ERROR] Persistence safety check failed — unified_intelligence.json NOT updated")
            return None

        data_dir = DATA_DIR
        output_file = data_dir / 'unified_intelligence.json'

        atomic_write_json(output_file, safe_output)

        print(f"\n[SAVED] {output_file}")
        try:
            from backend.analytics.signal_outcomes import track_intelligence_snapshot
            track_intelligence_snapshot(safe_output)
        except Exception as e:
            print(f"[WARN] Outcome tracking skipped: {e}")
        return safe_output

    except Exception as e:
        print(f"\n[FATAL] run_master_analysis crashed: {e}")
        traceback.print_exc()
        return None


if __name__ == "__main__":
    from backend.utils.bootstrap import setup_project_path

    setup_project_path()
    from backend.utils.process_lock import try_acquire_lock, release_lock
    from backend.utils.local_logging import setup_logger

    analyzer_log = setup_logger('analyzer', 'analyzer.log')

    if not try_acquire_lock('master_analyzer'):
        print("[SKIP] master_analyzer already running")
        analyzer_log.warning("Duplicate run blocked by process lock")
        sys.exit(0)

    print("Starting master analyzer v10...")
    analyzer_log.info("master_analyzer starting")
    result = None
    try:
        result = run_master_analysis()
        if result:
            print("[DONE] Analysis succeeded")
            analyzer_log.info("Analysis succeeded")
            try:
                from backend.analyzers.context_snapshot import capture_snapshot, init_context_table
                init_context_table()
                snapshot_id = capture_snapshot(run_type='master_analyzer')
                print(f"[CONTEXT] Snapshot: {snapshot_id}")
            except Exception as e:
                print(f"[WARN] Snapshot failed: {e}")
                traceback.print_exc()
        else:
            print("[FAILED] Analysis returned None — check logs above")
            analyzer_log.error("Analysis returned None")
    except Exception as e:
        print(f"[FATAL] Unhandled error in __main__: {e}")
        analyzer_log.exception("Fatal error: %s", e)
        traceback.print_exc()
    finally:
        release_lock('master_analyzer')
    sys.exit(0 if result else 1)