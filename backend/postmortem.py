"""
postmortem.py - AI Post-Mortem Analyzer
========================================
Analyzes failed predictions to explain WHY they failed.

Compares:
- Original prediction context (what AI saw)
- Outcome reality (what actually happened)
- Returns AI explanation of what went wrong + lessons learned
"""

import os
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR.parent / 'data'
DB_PATH = DATA_DIR / 'trading_history.db'

sys.path.insert(0, str(BASE_DIR))

# Optional: AI router
try:
    from ai_router import ask_ai
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

# Optional: dotenv
try:
    from dotenv import load_dotenv
    env_path = BASE_DIR.parent / 'config' / 'keys.env'
    load_dotenv(env_path)
except ImportError:
    pass


def get_prediction_with_outcome(prediction_id):
    """Fetch prediction + its outcome from DB"""
    if not DB_PATH.exists():
        return None
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            p.id, p.created_at, p.prediction_date, p.run_type, p.use_case,
            p.ticker, p.sector, p.recommendation, p.category, p.rank_in_list,
            p.entry_price, p.target_price, p.stop_loss, p.confidence,
            p.reasoning, p.cross_validation, p.overall_conviction,
            o.price_1d, o.change_1d_pct,
            o.price_3d, o.change_3d_pct,
            o.price_7d, o.change_7d_pct,
            o.target_hit, o.stop_loss_hit,
            o.max_gain_pct, o.max_loss_pct,
            o.verdict, o.last_checked
        FROM predictions p
        LEFT JOIN outcomes o ON o.source_id = p.id AND o.source_type = 'prediction'
        WHERE p.id = ?
    ''', (prediction_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    return dict(row) if row else None


def get_context_snapshot_near_date(target_date_str):
    """Get context snapshot closest to a date"""
    if not DB_PATH.exists():
        return None
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='context_snapshots'")
    if not cursor.fetchone():
        conn.close()
        return None
    
    # Try to find snapshot on or near the target date
    cursor.execute('''
        SELECT * FROM context_snapshots
        WHERE date(timestamp) <= ?
        ORDER BY timestamp DESC
        LIMIT 1
    ''', (target_date_str,))
    
    row = cursor.fetchone()
    conn.close()
    
    return dict(row) if row else None


def get_latest_context_snapshot():
    """Get the most recent context snapshot (current market state)"""
    if not DB_PATH.exists():
        return None
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='context_snapshots'")
    if not cursor.fetchone():
        conn.close()
        return None
    
    cursor.execute('''
        SELECT * FROM context_snapshots
        ORDER BY timestamp DESC
        LIMIT 1
    ''')
    
    row = cursor.fetchone()
    conn.close()
    
    return dict(row) if row else None


def format_context_summary(snapshot):
    """Format snapshot for AI prompt"""
    if not snapshot:
        return "No context data available"
    
    parts = []
    parts.append(f"Timestamp: {snapshot.get('timestamp', 'unknown')}")
    parts.append(f"Global mood: {snapshot.get('global_mood', '?')}")
    parts.append(f"US: {snapshot.get('us_change_pct', 0):+.2f}% | Europe: {snapshot.get('europe_change_pct', 0):+.2f}% | Asia: {snapshot.get('asia_change_pct', 0):+.2f}%")
    parts.append(f"Nifty: {snapshot.get('nifty_change_pct', 0):+.2f}% | Bank Nifty: {snapshot.get('banknifty_change_pct', 0):+.2f}% | Sensex: {snapshot.get('sensex_change_pct', 0):+.2f}%")
    parts.append(f"News: +{snapshot.get('news_positive_count', 0)} -{snapshot.get('news_negative_count', 0)}")
    parts.append(f"Reddit: {snapshot.get('reddit_mood', '?')} ({snapshot.get('reddit_confidence', 0)}%)")
    parts.append(f"Govt high impact: {snapshot.get('govt_high_impact_count', 0)}")
    parts.append(f"Scanner: {snapshot.get('scanner_total_signals', 0)} signals ({snapshot.get('scanner_ultra_signals', 0)} ULTRA, {snapshot.get('scanner_bullish_count', 0)} bullish, {snapshot.get('scanner_bearish_count', 0)} bearish)")
    
    # Top sectors
    try:
        top_sectors = json.loads(snapshot.get('top_sectors_json', '[]'))
        if top_sectors:
            sectors_str = ', '.join(f"{s['sector']} ({s['change']:+.1f}%)" for s in top_sectors[:5])
            parts.append(f"Top sectors: {sectors_str}")
    except:
        pass
    
    # Bottom sectors
    try:
        bottom_sectors = json.loads(snapshot.get('bottom_sectors_json', '[]'))
        if bottom_sectors:
            sectors_str = ', '.join(f"{s['sector']} ({s['change']:+.1f}%)" for s in bottom_sectors[:5])
            parts.append(f"Bottom sectors: {sectors_str}")
    except:
        pass
    
    return '\n'.join(parts)


def analyze_postmortem(prediction_id):
    """
    Generate post-mortem analysis for a prediction.
    Returns dict with analysis or error.
    """
    
    # 1. Fetch prediction
    pred = get_prediction_with_outcome(prediction_id)
    if not pred:
        return {'success': False, 'error': f'Prediction {prediction_id} not found'}
    
    # 2. Check if it's actually a failure worth analyzing
    verdict = pred.get('verdict', 'PENDING')
    if verdict == 'PENDING':
        return {
            'success': False, 
            'error': 'Prediction outcome not yet evaluated. Wait for outcome tracker to run.'
        }
    
    if verdict == 'WIN':
        # We can still analyze wins (what went RIGHT)
        analysis_type = 'WIN_ANALYSIS'
    elif verdict == 'LOSS':
        analysis_type = 'FAILURE_ANALYSIS'
    else:
        analysis_type = 'NEUTRAL_ANALYSIS'
    
    # 3. Get context at prediction time
    pred_date = pred.get('prediction_date', '')
    context_at_prediction = get_context_snapshot_near_date(pred_date)
    
    # 4. Get current/recent context (post-outcome)
    context_now = get_latest_context_snapshot()
    
    # 5. Build AI prompt
    if not AI_AVAILABLE:
        return {'success': False, 'error': 'AI router not available'}
    
    ticker = pred.get('ticker', '?')
    category = pred.get('category', 'opportunity')
    recommendation = pred.get('recommendation', '?')
    confidence = pred.get('confidence', 'MEDIUM')
    entry = pred.get('entry_price', 'N/A')
    target = pred.get('target_price', 'N/A')
    stop = pred.get('stop_loss', 'N/A')
    reasoning = pred.get('reasoning', '')
    cross_val = pred.get('cross_validation', '')
    
    change_1d = pred.get('change_1d_pct')
    change_3d = pred.get('change_3d_pct')
    change_7d = pred.get('change_7d_pct')
    max_gain = pred.get('max_gain_pct')
    max_loss = pred.get('max_loss_pct')
    target_hit = pred.get('target_hit', 0)
    stop_hit = pred.get('stop_loss_hit', 0)
    
    actual_change = change_7d or change_3d or change_1d or 0
    
    prompt = f"""You are an expert trading analyst conducting a post-mortem analysis.

═══════════════════════════════════════════════
PREDICTION DETAILS
═══════════════════════════════════════════════
Ticker: {ticker}
Sector: {pred.get('sector', '?')}
Category: {category.upper()}
Recommendation: {recommendation}
Confidence: {confidence}
Predicted on: {pred_date}
Entry: Rs.{entry}
Target: Rs.{target}
Stop Loss: Rs.{stop}

AI's Original Reasoning:
{reasoning}

Cross-Validation Notes:
{cross_val}

═══════════════════════════════════════════════
ACTUAL OUTCOME ({verdict})
═══════════════════════════════════════════════
1-day change: {f'{change_1d:+.2f}%' if change_1d is not None else 'N/A'}
3-day change: {f'{change_3d:+.2f}%' if change_3d is not None else 'N/A'}
7-day change: {f'{change_7d:+.2f}%' if change_7d is not None else 'N/A'}
Max gain: {f'{max_gain:+.2f}%' if max_gain is not None else 'N/A'}
Max loss: {f'{max_loss:+.2f}%' if max_loss is not None else 'N/A'}
Target hit: {'YES' if target_hit else 'NO'}
Stop loss hit: {'YES' if stop_hit else 'NO'}

═══════════════════════════════════════════════
CONTEXT AT PREDICTION TIME
═══════════════════════════════════════════════
{format_context_summary(context_at_prediction)}

═══════════════════════════════════════════════
CURRENT CONTEXT (now)
═══════════════════════════════════════════════
{format_context_summary(context_now)}

═══════════════════════════════════════════════
YOUR TASK
═══════════════════════════════════════════════

This was a {verdict} ({"correct" if verdict == 'WIN' else "incorrect" if verdict == 'LOSS' else "inconclusive"} call).

For LOSS predictions: Explain WHY it failed.
For WIN predictions: Explain WHY it worked.
For NEUTRAL: Explain why neither target nor stop hit.

Provide analysis in this EXACT format (be concise but specific):

## 🔬 What Happened
[2-3 sentences explaining the actual price action vs prediction]

## 🎯 Key Factors {('That Helped' if verdict == 'WIN' else 'That Hurt' if verdict == 'LOSS' else 'In Play')}
1. [Most important factor with specific data]
2. [Second factor]
3. [Third factor]

## 🤖 AI's Mistakes/Right Calls
- ✓ What the AI got right: [list]
- ✗ What the AI missed/got wrong: [list]

## 💡 Lesson Learned
[1-2 sentences with actionable insight for future predictions]

## 🎯 What to Watch Next Time
[Specific signals/patterns the trader should monitor]

Be honest, data-driven, and specific. Use numbers from the context. Don't be vague."""

    try:
        result = ask_ai(prompt, use_case='postmortem', max_tokens=1500)
        
        if not result.get('success'):
            return {
                'success': False,
                'error': result.get('error', 'AI call failed')
            }
        
        return {
            'success': True,
            'prediction_id': prediction_id,
            'ticker': ticker,
            'verdict': verdict,
            'category': category,
            'analysis_type': analysis_type,
            'analysis': result.get('text', ''),
            'model_used': result.get('model', ''),
            'cost': result.get('estimated_cost', 0),
            'context_at_prediction': bool(context_at_prediction),
            'context_now': bool(context_now),
            'generated_at': datetime.now().isoformat()
        }
    
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python postmortem.py <prediction_id>")
        print("\nList recent failed predictions:")
        if DB_PATH.exists():
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT p.id, p.ticker, p.prediction_date, p.recommendation, o.verdict, o.change_7d_pct
                FROM predictions p
                JOIN outcomes o ON o.source_id = p.id AND o.source_type = 'prediction'
                WHERE o.verdict IN ('WIN', 'LOSS')
                ORDER BY p.created_at DESC
                LIMIT 10
            ''')
            for row in cursor.fetchall():
                print(f"  ID {row[0]}: {row[1]} ({row[3]}) - {row[4]} - 7d: {row[5]}%")
            conn.close()
        sys.exit(1)
    
    pred_id = int(sys.argv[1])
    print(f"\n[POST-MORTEM] Analyzing prediction {pred_id}...")
    print("=" * 60)
    
    result = analyze_postmortem(pred_id)
    
    if result['success']:
        print(f"\nTicker: {result['ticker']}")
        print(f"Verdict: {result['verdict']}")
        print(f"Model: {result['model_used']} (cost: ${result['cost']})")
        print("\n" + "=" * 60)
        print(result['analysis'])
        print("=" * 60)
    else:
        print(f"\n[ERROR] {result['error']}")