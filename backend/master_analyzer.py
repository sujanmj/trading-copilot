"""
MASTER ANALYZER v7 - Memory-Augmented (Self-Aware AI)
Reads past performance from learning_engine and feeds it to AI prompt.
"""

import os
import json
import sys
import io
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
except ImportError:
    print("[WARN] python-dotenv not installed.")
    DOTENV_AVAILABLE = False
    def load_dotenv(*args, **kwargs):
        return False


if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass


sys.path.insert(0, str(Path(__file__).parent))
from ai_router import ask_ai

# Import learning engine for memory-augmented predictions
try:
    from learning_engine import build_memory_summary
    LEARNING_AVAILABLE = True
except ImportError:
    LEARNING_AVAILABLE = False
    print("[WARN] learning_engine not available - running without memory")


env_path = Path(__file__).parent.parent / 'config' / 'keys.env'
if DOTENV_AVAILABLE:
    if env_path.exists():
        load_dotenv(env_path, override=False)


def load_json_safe(filepath):
    try:
        if not Path(filepath).exists():
            return None
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"  WARN failed to load {filepath}: {e}")
        return None


def gather_all_data():
    data_dir = Path(__file__).parent.parent / 'data'
    return {
        'global_markets': load_json_safe(data_dir / 'global_markets.json'),
        'india_markets': load_json_safe(data_dir / 'latest_market_data.json'),
        'news': load_json_safe(data_dir / 'news_feed.json'),
        'youtube': load_json_safe(data_dir / 'youtube_feed.json'),
        'govt': load_json_safe(data_dir / 'govt_intelligence.json'),
        'inshorts': load_json_safe(data_dir / 'inshorts_feed.json'),
        'reddit': load_json_safe(data_dir / 'reddit_data.json'),
        'scanner': load_json_safe(data_dir / 'scanner_data.json'),
    }


def format_global_markets(data):
    if not data:
        return "GLOBAL MARKETS: No data available"
    lines = ["=== GLOBAL MARKETS ==="]
    lines.append(f"Updated: {data.get('collection_time', 'unknown')}")
    sentiment = data.get('sentiment', {})
    lines.append("\nREGIONAL SENTIMENT:")
    for region, info in sentiment.items():
        avg = info.get('average_change', info.get('expected_open', 0))
        lines.append(f"  {region.upper()}: {info.get('mood', '?')} (avg {avg:+.2f}%)")
    lines.append("\nKEY MARKET DATA:")
    markets = data.get('markets', {})
    for group_name, symbols in markets.items():
        lines.append(f"\n[{group_name}]")
        for name, info in list(symbols.items())[:6]:
            change = info.get('change_percent', 0)
            arrow = '+' if change >= 0 else ''
            lines.append(f"  {name}: {info.get('price', 0):,.2f} ({arrow}{change:.2f}%)")
    alerts = data.get('alerts', [])
    if alerts:
        lines.append("\nUNUSUAL MOVEMENTS:")
        for a in alerts[:10]:
            lines.append(f"  {a['message']}")
    return "\n".join(lines)


def format_india_markets(data):
    if not data:
        return "INDIA MARKETS: No data available"
    lines = ["=== INDIA STOCK SNAPSHOT ==="]
    prices = data.get('prices', {})
    for name, info in prices.items():
        change = info.get('change_percent', 0)
        arrow = '+' if change >= 0 else ''
        lines.append(f"  {name}: Rs.{info.get('price', 0):,.2f} ({arrow}{change:.2f}%)")
    return "\n".join(lines)


def format_news(data):
    if not data:
        return "NEWS: No data available"
    lines = ["=== NEWS INTELLIGENCE ==="]
    lines.append(f"Total articles: {data.get('total_articles', 0)}")
    sent = data.get('sentiment_distribution', {})
    if sent:
        lines.append(f"Sentiment: pos={sent.get('positive', 0)}, neu={sent.get('neutral', 0)}, neg={sent.get('negative', 0)}")
    top_stocks = data.get('top_stocks', {})
    if top_stocks:
        lines.append("\nMOST MENTIONED STOCKS:")
        for stock, count in list(top_stocks.items())[:15]:
            lines.append(f"  {stock}: {count} articles")
    sectors = data.get('sector_buzz', {})
    if sectors:
        lines.append("\nSECTOR BUZZ:")
        for sector, count in list(sectors.items())[:8]:
            lines.append(f"  {sector}: {count} mentions")
    hot = data.get('hot_stocks', [])
    if hot:
        lines.append("\nHOT STOCKS (high mention velocity):")
        for h in hot[:8]:
            lines.append(f"  [{h['velocity']}] {h['stock']}: {h['mention_count']} mentions")
    articles = data.get('articles', [])
    if articles:
        lines.append("\nTOP HEADLINES (latest 25):")
        for a in articles[:25]:
            sentiment_tag = a.get('sentiment_label', 'neutral')
            title = a.get('title', '')[:120]
            source = a.get('source', '')[:20]
            lines.append(f"  [{sentiment_tag.upper()[:3]}|{source}] {title}")
    return "\n".join(lines)


def format_inshorts(data):
    if not data:
        return ""
    lines = ["=== INSHORTS (Filtered Trading News) ==="]
    lines.append(f"Stories: {data.get('total_stories', 0)}")
    mentions = data.get('top_mentions', {})
    if mentions:
        lines.append("\nMENTIONED:")
        for stock, count in list(mentions.items())[:10]:
            lines.append(f"  {stock}: {count}x")
    stories = data.get('stories', [])
    if stories:
        lines.append("\nLATEST HEADLINES:")
        for s in stories[:15]:
            title = s.get('title', '')[:120]
            cat = s.get('category', '')[:10]
            lines.append(f"  [{cat}] {title}")
    return "\n".join(lines)


def format_youtube(data):
    if not data:
        return "YOUTUBE: No data available"
    lines = ["=== TV/YOUTUBE INTELLIGENCE ==="]
    lines.append(f"Videos: {data.get('total_videos', 0)} | Live: {data.get('live_streams', 0)} | Recent (3h): {data.get('recent_videos_3h', 0)}")
    live = data.get('live_now', [])
    if live:
        lines.append("\nLIVE NOW:")
        for v in live[:6]:
            lines.append(f"  [{v.get('channel', '?')}] {v.get('title', '')[:90]}")
    recent = data.get('recent_videos', [])
    if recent:
        lines.append("\nRECENT VIDEOS:")
        for v in recent[:10]:
            lines.append(f"  [{v.get('channel', '?')}] {v.get('title', '')[:90]}")
    stocks = data.get('stock_mentions', {})
    if stocks:
        lines.append("\nSTOCKS DISCUSSED ON TV:")
        for stock, count in list(stocks.items())[:10]:
            lines.append(f"  {stock}: {count} videos")
    buzz = data.get('cross_channel_buzz', [])
    if buzz:
        lines.append("\nCROSS-CHANNEL BUZZ:")
        for b in buzz[:5]:
            lines.append(f"  [{b.get('signal_strength', '?')}] {b.get('stock', '?')} on {b.get('channel_count', 0)} channels")
    return "\n".join(lines)


def format_govt(data):
    if not data:
        return "GOVERNMENT INTEL: No data available"
    lines = ["=== TIER 1: OFFICIAL GOVERNMENT INTELLIGENCE ==="]
    lines.append(f"HIGH IMPACT: {data.get('high_impact_count', 0)} | Medium: {data.get('medium_impact_count', 0)}")
    high_impact = data.get('high_impact_items', [])
    if high_impact:
        lines.append("\n*** HIGH-IMPACT ANNOUNCEMENTS ***")
        for i, item in enumerate(high_impact[:8], 1):
            score = item.get('impact_score', 0)
            direction = item.get('direction', 'NEUTRAL')
            headline = item.get('english_headline', item.get('title', ''))[:130]
            source = item.get('source', '?')
            stocks = item.get('affected_stocks', [])
            relevance = item.get('market_relevance', '')
            lines.append(f"\n  {i}. [{score}/10 {direction}] {source} | {relevance}")
            lines.append(f"     {headline}")
            if stocks:
                lines.append(f"     Affects: {', '.join(stocks[:8])}")
            summary = item.get('english_summary', '')
            if summary:
                lines.append(f"     Summary: {summary[:300]}")
    return "\n".join(lines)


def format_reddit(data):
    if not data:
        return "REDDIT INTEL: No data available"
    lines = ["=== TIER 7: REDDIT RETAIL SENTIMENT ==="]
    lines.append(f"Posts analyzed: {data.get('total_posts_analyzed', 0)}")
    mood = data.get('market_mood', {})
    if mood:
        sentiment = mood.get('sentiment', 'unknown')
        confidence = mood.get('confidence', 0)
        summary = mood.get('summary', '')
        themes = mood.get('themes', [])
        lines.append(f"\nOVERALL RETAIL MOOD: {sentiment.upper()} (confidence: {confidence}%)")
        if summary:
            lines.append(f"Summary: {summary}")
        if themes:
            lines.append(f"Dominant themes: {', '.join(themes)}")
    trending = data.get('trending_tickers', [])
    if trending:
        lines.append("\nTRENDING TICKERS ON REDDIT (retail buzz):")
        for t in trending[:12]:
            ticker = t.get('ticker', '?')
            mentions = t.get('mentions', 0)
            sent = t.get('sentiment', 'neutral')
            score = t.get('sentiment_score', 0.5)
            top_post_title = t.get('top_post', {}).get('title', '')[:80]
            lines.append(f"  {ticker}: {mentions} mentions | {sent.upper()} ({score:.2f}) | Top: {top_post_title}")
    hot = data.get('hot_discussions', [])
    if hot:
        lines.append("\nHOT REDDIT DISCUSSIONS:")
        for h in hot[:8]:
            title = h.get('title', '')[:120]
            score = h.get('score', 0)
            comments = h.get('comments', 0)
            sent = h.get('sentiment', 'neutral')
            tickers = h.get('tickers', [])
            ticker_str = f" [{', '.join(tickers[:3])}]" if tickers else ""
            lines.append(f"  [{score}up/{comments}c|{sent.upper()[:3]}] {title}{ticker_str}")
    return "\n".join(lines)


def format_scanner(data):
    if not data:
        return "SCANNER: No data available"
    lines = ["=== TIER 8: NSE STOCK SCANNER ==="]
    lines.append(f"Universe: {data.get('universe', 'NSE')} | Scanned: {data.get('total_scanned', 0)} stocks | Signals: {data.get('total_signals', 0)}")
    summary = data.get('summary', {})
    if summary:
        lines.append("\nSIGNAL BREAKDOWN:")
        for sig_type, count in sorted(summary.items(), key=lambda x: -x[1]):
            lines.append(f"  {sig_type}: {count}")
    top = data.get('top_signals', [])
    if top:
        lines.append("\n*** ULTRA/STRONG SIGNALS ***")
        for s in top[:15]:
            ticker = s.get('ticker', '?')
            sector = s.get('sector', '?')
            strength = s.get('strength', '?')
            direction = s.get('direction', '?')
            change = s.get('change_percent', 0)
            volume_ratio = s.get('volume_ratio', 0)
            signals = s.get('signals', [])
            price = s.get('price', 0)
            sigs_str = ' + '.join(signals[:4])
            lines.append(f"  [{strength}|{direction}] {ticker} ({sector}) Rs.{price} {change:+.2f}% vol:{volume_ratio:.1f}x | {sigs_str}")
    rotation = data.get('sector_rotation', [])
    if rotation:
        lines.append("\nSECTOR ROTATION:")
        for r in rotation[:10]:
            sector = r.get('sector', '?')
            avg_move = r.get('avg_change_percent', 0)
            direction = r.get('direction', '?')
            strength = r.get('strength', '?')
            stocks_count = r.get('stocks_analyzed', 0)
            vol_ratio = r.get('avg_volume_ratio', 0)
            lines.append(f"  [{direction}|{strength}] {sector}: {avg_move:+.2f}% avg ({stocks_count} stocks, vol {vol_ratio:.1f}x)")
    breaks = data.get('correlation_breaks', [])
    if breaks:
        lines.append("\nCORRELATION BREAKS:")
        for b in breaks[:10]:
            ticker = b.get('ticker', '?')
            sector = b.get('sector', '?')
            note = b.get('note', '')
            lines.append(f"  {ticker} ({sector}): {note}")
    by_signal = data.get('by_signal', {})
    if by_signal:
        vs = by_signal.get('volume_spikes', [])
        if vs:
            lines.append("\nTOP VOLUME SPIKES:")
            for v in vs[:8]:
                lines.append(f"  {v.get('ticker', '?')} ({v.get('sector', '?')}): {v.get('volume_ratio', 0):.1f}x vol, {v.get('change_percent', 0):+.2f}%")
    return "\n".join(lines)


def is_indian_market_open():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0)
    market_close = now.replace(hour=15, minute=30, second=0)
    return market_open <= now <= market_close


def generate_unified_analysis(all_data):
    print("\n[ANALYSIS] Sending to AI for unified intelligence...")

    # NEW v7: Build memory summary from past performance
    memory_summary = ""
    if LEARNING_AVAILABLE:
        try:
            print("[LEARNING] Building memory from past predictions...")
            memory_summary = build_memory_summary(days=30)
            print(f"[LEARNING] Memory summary: {len(memory_summary)} chars")
        except Exception as e:
            print(f"[WARN] Failed to build memory: {e}")
            memory_summary = ""

    govt_str = format_govt(all_data['govt'])
    global_str = format_global_markets(all_data['global_markets'])
    india_str = format_india_markets(all_data['india_markets'])
    news_str = format_news(all_data['news'])
    youtube_str = format_youtube(all_data['youtube'])
    inshorts_str = format_inshorts(all_data['inshorts'])
    reddit_str = format_reddit(all_data['reddit'])
    scanner_str = format_scanner(all_data['scanner'])

    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    market_status = "OPEN" if is_indian_market_open() else "CLOSED"

    # Memory section
    memory_section = ""
    if memory_summary:
        memory_section = f"\n{memory_summary}\n\n"

    prompt = f"""You are an expert Indian stock market analyst with self-awareness of your past performance.

CURRENT TIME: {current_time} (Indian Market: {market_status})

{memory_section}

You have EIGHT real-time data sources. Cross-reference for actionable intelligence.

PRIORITY ORDER:
TIER 1 = Government (highest reliability)
TIER 8 = Stock Scanner (most CURRENT signal)
TIER 2 = News  |  TIER 3 = Inshorts  |  TIER 5 = India Markets
TIER 6 = Global Markets  |  TIER 4 = TV/YouTube  |  TIER 7 = Reddit

KEY ANALYSIS PRINCIPLES:
1. Tier 1 + Tier 8 alignment = HIGHEST conviction
2. Volume spikes (Tier 8) often PRECEDE news by hours
3. Correlation breaks = idiosyncratic opportunities
4. ULTRA strength signals = highest action priority
5. **USE YOUR PAST PERFORMANCE TO CALIBRATE CONFIDENCE LEVELS**

{govt_str}

{scanner_str}

{global_str}

{india_str}

{news_str}

{inshorts_str}

{youtube_str}

{reddit_str}

---

Provide UNIFIED INTELLIGENCE in this EXACT format. BE COMPREHENSIVE. CRITICAL: Output BOTH all 10 opportunities AND all 10 risks completely. Do not truncate.

# UNIFIED MARKET INTELLIGENCE

## EXECUTIVE SUMMARY (3-4 lines)

## GOVERNMENT POLICY IMPACT
- Affected sectors:
- Likely market reaction:
- Confidence:

## SCANNER ALERTS
- Top ULTRA/STRONG signals:
- Sector rotation pattern:
- Notable correlation breaks:

## RETAIL SENTIMENT (REDDIT)
- Overall retail mood:
- Top tickers retail is buzzing about:

## MARKET MOOD
- Global Mood:
- India Outlook:
- Retail Mood:
- Confidence Level:

## SELF-CALIBRATION (NEW)
Based on your past performance, comment on:
- Which sectors you're trusting more today (and why)
- Which you're being skeptical about
- How you're calibrating today's confidence levels

## TOP 10 OPPORTUNITIES TODAY/TOMORROW
[List EXACTLY 10. Order by conviction. APPLY YOUR PAST PERFORMANCE LEARNINGS.]

1. [TICKER] - [Buy/Hold/Watch/Accumulate]
   - Why: [reason]
   - Entry: [price]
   - Target: [price]
   - Stop Loss: [price]
   - Confidence: [High/Medium/Low - JUSTIFIED BY YOUR HISTORICAL CALIBRATION]
   - Cross-validation:
   - Past performance check: [If you've predicted this ticker/sector before, mention it]

2. [Same format]
3. [Same format]
4. [Same format]
5. [Same format]
6. [Same format]
7. [Same format]
8. [Same format]
9. [Same format]
10. [Same format]

## TOP 10 RISKS / AVOID LIST
[MANDATORY: List EXACTLY 10.]

1. [TICKER] - [Risk reason]
2. [Same format]
3. [Same format]
4. [Same format]
5. [Same format]
6. [Same format]
7. [Same format]
8. [Same format]
9. [Same format]
10. [Same format]

## SECTOR ROTATION SIGNAL
- Sectors showing strength:
- Sectors showing weakness:

## OVERNIGHT GLOBAL IMPACT
- US impact:
- Europe impact:
- Asia impact:
- Commodity impact:
- Currency impact:

## SCANNER + NEWS ALERTS
[5-7 cross-validated alerts]

## CROSS-VALIDATION SCORE
- Govt + Scanner alignment: X/10
- Reddit + Scanner alignment: X/10
- Overall conviction: X/10

## ACTION PLAN
[Specific, time-bound actions for IMMEDIATE / INTRADAY / TOMORROW]

---
RULES:
- MUST give exactly 10 opportunities AND 10 risks
- Use ONLY actual NSE stock tickers (e.g., RELIANCE, TCS, ICICIBANK), NOT sector names
- Be specific with entry/target/stop-loss
- ULTRA scanner signals MUST appear in top 5 opportunities or risks
- For commodities, use ETF tickers (GOLDBEES, SILVERBEES) not "GOLD" or "SILVER"
- IMPORTANT: Calibrate your confidence levels based on past performance shown above
- IMPORTANT: Don't repeat tickers from "STILL PENDING" list above
- IMPORTANT: Mention specifically how past data is influencing today's calls"""

    use_case = os.environ.get('AI_USE_CASE', 'manual_refresh')
    result = ask_ai(prompt, use_case=use_case, max_tokens=8000)

    if result['success']:
        print(f"  [AI] Used: {result['model']} ({result['provider']})")
        if 'estimated_cost' in result:
            print(f"  [AI] Cost: ${result['estimated_cost']}")
        return result['text']
    else:
        print(f"  ERROR: {result.get('error', 'Unknown')}")
        return None


def run_master_analysis():
    print("\n" + "=" * 60)
    print("MASTER ANALYZER v7 - 8 TIERS + Memory-Augmented AI")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    print("\n[STEP 1] Gathering data from all 8 sources...")
    print("-" * 60)
    all_data = gather_all_data()

    sources_loaded = 0
    for source, data in all_data.items():
        if data:
            print(f"  OK   {source}")
            sources_loaded += 1
        else:
            print(f"  MISS {source}")

    if sources_loaded == 0:
        print("\nERROR: No data sources available")
        return None

    print(f"\n[INFO] {sources_loaded}/8 sources loaded")

    analysis = generate_unified_analysis(all_data)

    if not analysis:
        print("\nERROR: Failed to generate analysis")
        return None

    print("\n" + "=" * 60)
    print("UNIFIED INTELLIGENCE OUTPUT")
    print("=" * 60)
    print(analysis)
    print("=" * 60)

    output = {
        'timestamp': datetime.now().isoformat(),
        'generation_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'market_open': is_indian_market_open(),
        'sources_used': sources_loaded,
        'memory_augmented': LEARNING_AVAILABLE,
        'analysis': analysis,
        'data_snapshot': {
            'govt_high_impact': all_data['govt'].get('high_impact_count', 0) if all_data['govt'] else 0,
            'global_alerts': len(all_data['global_markets'].get('alerts', [])) if all_data['global_markets'] else 0,
            'news_articles': all_data['news'].get('total_articles', 0) if all_data['news'] else 0,
            'inshorts_stories': all_data['inshorts'].get('total_stories', 0) if all_data['inshorts'] else 0,
            'tv_videos': all_data['youtube'].get('total_videos', 0) if all_data['youtube'] else 0,
            'india_stocks': len(all_data['india_markets'].get('prices', {})) if all_data['india_markets'] else 0,
            'reddit_posts': all_data['reddit'].get('total_posts_analyzed', 0) if all_data['reddit'] else 0,
            'reddit_mood': all_data['reddit'].get('market_mood', {}).get('sentiment', 'unknown') if all_data['reddit'] else 'unknown',
            'scanner_stocks': all_data['scanner'].get('total_scanned', 0) if all_data['scanner'] else 0,
            'scanner_signals': all_data['scanner'].get('total_signals', 0) if all_data['scanner'] else 0,
            'scanner_top_signal': (all_data['scanner'].get('top_signals') or [{}])[0].get('ticker', 'none') if all_data['scanner'] else 'none',
        }
    }

    data_dir = Path(__file__).parent.parent / 'data'
    output_file = data_dir / 'unified_intelligence.json'

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, default=str, ensure_ascii=False)

    print(f"\nSaved to: {output_file}")
    print("=" * 60 + "\n")
    return output


if __name__ == "__main__":
    print("Starting master analyzer v7 (Memory-Augmented)...")
    
    analysis_success = False
    try:
        result = run_master_analysis()
        if result:
            analysis_success = True
            print("Done!")
    except Exception as e:
        import traceback
        print(f"ERROR: {e}")
        traceback.print_exc()
    
    if analysis_success:
        try:
            from context_snapshot import capture_snapshot, init_context_table
            init_context_table()
            snapshot_id = capture_snapshot(run_type='master_analyzer')
            print(f"\n[CONTEXT] Snapshot captured: {snapshot_id}")
        except Exception as e:
            print(f"[WARN] Context snapshot failed: {e}")
    else:
        print("[CONTEXT] Skipped snapshot")