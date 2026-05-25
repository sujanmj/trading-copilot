"""
learning_engine.py - Memory-Augmented AI
=========================================
Reads past predictions + outcomes from SQLite.
Generates performance summary that gets injected into AI prompts.

This is what makes the AI "learn" from its past decisions.
"""

import os
import sys
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR.parent / 'data' / 'trading_history.db'


def get_db_connection():
    """Get DB connection with row factory"""
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_past_predictions_with_outcomes(days=30):
    """Fetch all evaluated predictions from last N days"""
    conn = get_db_connection()
    if not conn:
        return []
    
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 
            p.id, p.prediction_date, p.ticker, p.sector, 
            p.recommendation, p.category, p.confidence, p.run_type,
            p.entry_price, p.target_price, p.stop_loss,
            p.reasoning, p.overall_conviction,
            o.verdict, o.change_1d_pct, o.change_3d_pct, o.change_7d_pct,
            o.max_gain_pct, o.max_loss_pct
        FROM predictions p
        LEFT JOIN outcomes o ON o.source_id = p.id AND o.source_type = 'prediction'
        WHERE p.prediction_date >= date('now', ?)
          AND o.verdict IN ('WIN', 'LOSS', 'NEUTRAL')
        ORDER BY p.prediction_date DESC
    ''', (f'-{days} days',))
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_pending_predictions(days=3):
    """Get recent pending predictions (still being evaluated)"""
    conn = get_db_connection()
    if not conn:
        return []
    
    cursor = conn.cursor()
    cursor.execute('''
        SELECT p.ticker, p.sector, p.recommendation, p.category, 
               p.confidence, p.prediction_date, p.entry_price
        FROM predictions p
        LEFT JOIN outcomes o ON o.source_id = p.id AND o.source_type = 'prediction'
        WHERE p.prediction_date >= date('now', ?)
          AND (o.verdict IS NULL OR o.verdict = 'PENDING')
        ORDER BY p.prediction_date DESC
        LIMIT 50
    ''', (f'-{days} days',))
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def calculate_overall_stats(predictions):
    """Calculate overall win/loss stats"""
    if not predictions:
        return {
            'total': 0, 'wins': 0, 'losses': 0, 'neutral': 0,
            'win_rate': 0, 'evaluated': 0
        }
    
    wins = sum(1 for p in predictions if p['verdict'] == 'WIN')
    losses = sum(1 for p in predictions if p['verdict'] == 'LOSS')
    neutral = sum(1 for p in predictions if p['verdict'] == 'NEUTRAL')
    evaluated = wins + losses
    win_rate = (wins / evaluated * 100) if evaluated > 0 else 0
    
    return {
        'total': len(predictions),
        'wins': wins,
        'losses': losses,
        'neutral': neutral,
        'evaluated': evaluated,
        'win_rate': round(win_rate, 1)
    }


def calculate_sector_performance(predictions, min_samples=3):
    """Calculate win rate per sector (only if enough samples)"""
    sector_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total': 0})
    
    for p in predictions:
        sector = p.get('sector') or 'UNKNOWN'
        if sector == 'UNKNOWN':
            continue
        
        sector_stats[sector]['total'] += 1
        if p['verdict'] == 'WIN':
            sector_stats[sector]['wins'] += 1
        elif p['verdict'] == 'LOSS':
            sector_stats[sector]['losses'] += 1
    
    # Filter sectors with enough data
    results = []
    for sector, stats in sector_stats.items():
        evaluated = stats['wins'] + stats['losses']
        if evaluated < min_samples:
            continue
        
        win_rate = (stats['wins'] / evaluated * 100)
        results.append({
            'sector': sector,
            'samples': evaluated,
            'win_rate': round(win_rate, 1),
            'wins': stats['wins'],
            'losses': stats['losses']
        })
    
    results.sort(key=lambda x: x['win_rate'], reverse=True)
    return results


def calculate_confidence_calibration(predictions, min_samples=5):
    """Calculate accuracy by confidence level"""
    conf_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total': 0})
    
    for p in predictions:
        conf = (p.get('confidence') or 'UNKNOWN').upper()
        if conf == 'UNKNOWN':
            continue
        
        conf_stats[conf]['total'] += 1
        if p['verdict'] == 'WIN':
            conf_stats[conf]['wins'] += 1
        elif p['verdict'] == 'LOSS':
            conf_stats[conf]['losses'] += 1
    
    results = []
    for conf, stats in conf_stats.items():
        evaluated = stats['wins'] + stats['losses']
        if evaluated < min_samples:
            continue
        win_rate = (stats['wins'] / evaluated * 100)
        results.append({
            'confidence': conf,
            'samples': evaluated,
            'win_rate': round(win_rate, 1)
        })
    
    # Order: HIGH, MEDIUM, LOW
    order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
    results.sort(key=lambda x: order.get(x['confidence'], 99))
    return results


def calculate_recommendation_performance(predictions, min_samples=3):
    """Calculate win rate by recommendation type (BUY, AVOID, etc.)"""
    rec_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total': 0})
    
    for p in predictions:
        rec = (p.get('recommendation') or 'UNKNOWN').upper()
        if rec == 'UNKNOWN':
            continue
        
        rec_stats[rec]['total'] += 1
        if p['verdict'] == 'WIN':
            rec_stats[rec]['wins'] += 1
        elif p['verdict'] == 'LOSS':
            rec_stats[rec]['losses'] += 1
    
    results = []
    for rec, stats in rec_stats.items():
        evaluated = stats['wins'] + stats['losses']
        if evaluated < min_samples:
            continue
        win_rate = (stats['wins'] / evaluated * 100)
        results.append({
            'recommendation': rec,
            'samples': evaluated,
            'win_rate': round(win_rate, 1)
        })
    
    results.sort(key=lambda x: x['win_rate'], reverse=True)
    return results


def get_recent_failures(predictions, limit=5):
    """Get recent worst losses (lessons to learn from)"""
    losses = [p for p in predictions if p['verdict'] == 'LOSS']
    
    def loss_severity(p):
        return min(
            p.get('max_loss_pct') or 0,
            p.get('change_7d_pct') or 0,
            p.get('change_3d_pct') or 0,
            p.get('change_1d_pct') or 0,
            0
        )
    
    losses.sort(key=loss_severity)  # Worst losses first
    return losses[:limit]


def get_recent_wins(predictions, limit=5):
    """Get recent best wins (patterns that worked)"""
    wins = [p for p in predictions if p['verdict'] == 'WIN']
    
    def gain_score(p):
        return max(
            p.get('max_gain_pct') or 0,
            p.get('change_7d_pct') or 0,
            p.get('change_3d_pct') or 0,
            p.get('change_1d_pct') or 0,
            0
        )
    
    wins.sort(key=gain_score, reverse=True)
    return wins[:limit]


def detect_failure_patterns(predictions):
    """Identify patterns in failures"""
    losses = [p for p in predictions if p['verdict'] == 'LOSS']
    if len(losses) < 5:
        return []
    
    patterns = []
    
    # Pattern 1: HIGH confidence failures
    high_conf_losses = [p for p in losses if (p.get('confidence') or '').upper() == 'HIGH']
    high_conf_total = sum(1 for p in predictions if (p.get('confidence') or '').upper() == 'HIGH' 
                          and p['verdict'] in ['WIN', 'LOSS'])
    if high_conf_total >= 5:
        high_conf_loss_rate = len(high_conf_losses) / high_conf_total * 100
        if high_conf_loss_rate > 40:
            patterns.append(
                f"HIGH confidence picks failing {high_conf_loss_rate:.0f}% of time - calibrate down"
            )
    
    # Pattern 2: Sector concentration
    sector_losses = defaultdict(int)
    for p in losses:
        sector_losses[p.get('sector', 'UNKNOWN')] += 1
    
    for sector, count in sector_losses.items():
        if count >= 3 and sector != 'UNKNOWN':
            patterns.append(f"{sector}: {count} recent losses - be skeptical of this sector")
    
    # Pattern 3: Risk vs Opportunity bias
    opp_predictions = [p for p in predictions if p.get('category') == 'opportunity' 
                       and p['verdict'] in ['WIN', 'LOSS']]
    risk_predictions = [p for p in predictions if p.get('category') == 'risk' 
                        and p['verdict'] in ['WIN', 'LOSS']]
    
    if len(opp_predictions) >= 5 and len(risk_predictions) >= 5:
        opp_wins = sum(1 for p in opp_predictions if p['verdict'] == 'WIN')
        risk_wins = sum(1 for p in risk_predictions if p['verdict'] == 'WIN')
        opp_rate = opp_wins / len(opp_predictions) * 100
        risk_rate = risk_wins / len(risk_predictions) * 100
        
        if abs(opp_rate - risk_rate) > 20:
            if opp_rate > risk_rate:
                patterns.append(f"Opportunities ({opp_rate:.0f}%) outperforming Risks ({risk_rate:.0f}%) - trust BUY signals more")
            else:
                patterns.append(f"Risks ({risk_rate:.0f}%) outperforming Opportunities ({opp_rate:.0f}%) - trust AVOID calls more")
    
    return patterns


def _safe_row(row):
    """DB rows should be dicts; guard against unexpected types."""
    return row if isinstance(row, dict) else {}


def build_memory_summary(days=30):
    """
    THE MAIN FUNCTION
    Returns formatted string to inject into AI prompts.
    """
    
    # Get historical data
    predictions = get_past_predictions_with_outcomes(days=days)
    pending = get_recent_pending_predictions(days=3)
    
    # If no evaluated history yet, return minimal context
    if not predictions:
        return _build_cold_start_summary(pending)
    
    # Calculate stats
    overall = calculate_overall_stats(predictions)
    sector_perf = calculate_sector_performance(predictions)
    conf_cal = calculate_confidence_calibration(predictions)
    rec_perf = calculate_recommendation_performance(predictions)
    recent_wins = get_recent_wins(predictions, limit=3)
    recent_losses = get_recent_failures(predictions, limit=3)
    patterns = detect_failure_patterns(predictions)
    
    # Build summary string
    lines = []
    lines.append("=" * 60)
    lines.append("📊 YOUR PAST PERFORMANCE (Last 30 Days)")
    lines.append("=" * 60)
    lines.append(f"Total evaluated: {overall['evaluated']} predictions")
    lines.append(f"Wins: {overall['wins']} | Losses: {overall['losses']} | Neutral: {overall['neutral']}")
    lines.append(f"Overall Win Rate: {overall['win_rate']}%")
    
    # Confidence calibration
    if conf_cal:
        lines.append("\n🎯 CONFIDENCE CALIBRATION (USE THIS):")
        for c in conf_cal:
            indicator = "✅ trustworthy" if c['win_rate'] >= 60 else "⚠️ unreliable" if c['win_rate'] < 40 else "🟡 moderate"
            lines.append(f"  {c['confidence']}: {c['win_rate']}% accurate ({c['samples']} samples) {indicator}")
    
    # Sector performance
    if sector_perf:
        lines.append("\n🏷️ SECTOR PERFORMANCE:")
        # Top 5 best sectors
        best = sector_perf[:5]
        for s in best:
            if s['win_rate'] >= 55:
                lines.append(f"  ✅ {s['sector']}: {s['win_rate']}% ({s['samples']} samples) - TRUST SIGNALS HERE")
        
        # Worst 3 sectors
        worst = [s for s in sector_perf if s['win_rate'] < 45]
        if worst:
            lines.append("\n  Sectors to BE SKEPTICAL:")
            for s in worst[:3]:
                lines.append(f"  ❌ {s['sector']}: {s['win_rate']}% ({s['samples']} samples) - DOWNGRADE CONFIDENCE")
    
    # Recommendation type performance
    if rec_perf:
        lines.append("\n📋 RECOMMENDATION TYPES:")
        for r in rec_perf[:5]:
            lines.append(f"  {r['recommendation']}: {r['win_rate']}% accurate ({r['samples']} samples)")
    
    # Failure patterns
    if patterns:
        lines.append("\n⚠️ FAILURE PATTERNS DETECTED:")
        for p in patterns:
            lines.append(f"  • {p}")
    
    # Recent wins (positive examples)
    if recent_wins:
        lines.append("\n✅ RECENT WINS (patterns that worked):")
        for w in recent_wins:
            w = _safe_row(w)
            gain = w.get('max_gain_pct') or w.get('change_7d_pct') or 0
            lines.append(f"  {w['ticker']} ({w.get('sector', '?')}) - {w.get('recommendation', '?')} - {w.get('confidence', '?')} conf - +{gain:.1f}%")
    
    # Recent losses (lessons)
    if recent_losses:
        lines.append("\n❌ RECENT LOSSES (avoid similar setups):")
        for l in recent_losses:
            l = _safe_row(l)
            loss = l.get('max_loss_pct') or l.get('change_7d_pct') or 0
            lines.append(f"  {l['ticker']} ({l.get('sector', '?')}) - {l.get('recommendation', '?')} - {l.get('confidence', '?')} conf - {loss:.1f}%")
    
    # Pending predictions context
    if pending:
        lines.append("\n⏳ STILL PENDING (don't repeat these tickers):")
        seen = set()
        for p in pending[:10]:
            p = _safe_row(p)
            ticker = p.get('ticker')
            if ticker and ticker not in seen:
                lines.append(f"  {ticker} - {p.get('recommendation', '?')} (predicted {p.get('prediction_date', '?')})")
                seen.add(ticker)
    
    # Calibration instructions
    lines.append("\n" + "=" * 60)
    lines.append("🎓 CALIBRATION INSTRUCTIONS FOR THIS PREDICTION:")
    lines.append("=" * 60)
    
    if overall['evaluated'] < 20:
        lines.append("- ⚠️ Limited data. Be conservative on confidence.")
    
    # Auto-calibration based on data
    high_conf_data = next((c for c in conf_cal if c['confidence'] == 'HIGH'), None)
    if high_conf_data:
        if high_conf_data['win_rate'] < 50:
            lines.append("- ⚠️ HIGH confidence has been wrong more often than right. Be very strict with HIGH confidence.")
        elif high_conf_data['win_rate'] > 70:
            lines.append("- ✅ HIGH confidence has been reliable. Continue current criteria.")
    
    medium_conf_data = next((c for c in conf_cal if c['confidence'] == 'MEDIUM'), None)
    if medium_conf_data and medium_conf_data['win_rate'] < 40:
        lines.append("- ⚠️ MEDIUM confidence underperforming. Either upgrade to HIGH (with strong signals) or LOW.")
    
    if patterns:
        lines.append("- Apply the failure patterns above when generating today's predictions.")
    
    lines.append("- Use sector performance to weight your conviction.")
    lines.append("- Don't repeat tickers from pending list above.")
    
    return "\n".join(lines)


def _build_cold_start_summary(pending):
    """When no historical data exists yet"""
    lines = []
    lines.append("=" * 60)
    lines.append("📊 PERFORMANCE HISTORY")
    lines.append("=" * 60)
    lines.append("⚠️ No evaluated predictions yet (system just started).")
    lines.append("⚠️ Be conservative on confidence levels.")
    lines.append("⚠️ Default most picks to MEDIUM confidence.")
    lines.append("⚠️ Reserve HIGH confidence only for strongly cross-validated signals.")
    
    if pending:
        lines.append("\n⏳ STILL PENDING (don't repeat these tickers):")
        seen = set()
        for p in pending[:10]:
            p = _safe_row(p)
            ticker = p.get('ticker')
            if ticker and ticker not in seen:
                lines.append(f"  {ticker} - {p.get('recommendation', '?')}")
                seen.add(ticker)
    
    return "\n".join(lines)


def get_quick_stats():
    """Quick stats for status checks"""
    predictions = get_past_predictions_with_outcomes(days=30)
    overall = calculate_overall_stats(predictions)
    return overall


if __name__ == "__main__":
    print("=" * 60)
    print("LEARNING ENGINE - Memory Generation Test")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    summary = build_memory_summary(days=30)
    print("\n" + summary + "\n")
    
    print("=" * 60)
    print(f"Length: {len(summary)} chars")
    print("=" * 60)