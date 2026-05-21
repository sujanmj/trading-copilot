import json
import sqlite3
import os
from pathlib import Path
from datetime import datetime
import pytz
import pandas as pd
import numpy as np

# Machine Learning Core
from xgboost import XGBClassifier
from sklearn.preprocessing import LabelEncoder

IST = pytz.timezone('Asia/Kolkata')
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "trading_history.db"

def load_json_safely(filename: str) -> dict:
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return {}
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def fallback_heuristic_scoring(df: pd.DataFrame) -> np.ndarray:
    """Cold-start mathematical engine used if historical training rows are insufficient."""
    scores = []
    for _, row in df.iterrows():
        p = 0.50
        if 2.0 <= row['one_day_change'] <= 6.0: p += 0.15
        if row['confidence'] == 'HIGH': p += 0.10
        if row['global_mood'] == 'bullish': p += 0.10
        if row['global_mood'] == 'bearish': p -= 0.15
        scores.append(min(max(p, 0.0), 1.0))
    return np.array(scores)

def main():
    print("[*] Initializing Adaptive XGBoost Meta-Labeling Engine...")
    
    # 1. Gather real-time feature frames
    scanner_data = load_json_safely("scanner_data.json")
    news_feed = load_json_safely("news_feed.json")
    global_markets = load_json_safely("global_markets.json")
    
    global_mood = global_markets.get("market_mood", "neutral").lower()
    sensex_mentions = news_feed.get("stats", {}).get("SENSEX_mentions", 0)
    raw_signals = scanner_data.get("signals", []) or scanner_data.get("stocks", [])
    
    if not raw_signals:
        print("[!] No active scanner signals detected. Exiting ML cycle.")
        return

    # 2. Build the Live Prediction DataFrame
    live_df = pd.DataFrame(raw_signals)
    live_df['global_mood'] = global_mood
    live_df['sensex_mentions'] = sensex_mentions
    
    # Standardize feature naming columns
    if 'one_day_change' not in live_df.columns: live_df['one_day_change'] = 0.0
    if 'confidence' not in live_df.columns: live_df['confidence'] = 'MEDIUM'
    
    # Process Categorical Strings to Integers
    le_mood = LabelEncoder().fit(['neutral', 'bullish', 'bearish'])
    le_conf = LabelEncoder().fit(['LOW', 'MEDIUM', 'HIGH'])
    
    live_df['mood_encoded'] = le_mood.transform(live_df['global_mood'])
    live_df['conf_encoded'] = le_conf.transform(live_df['confidence'].fillna('MEDIUM'))
    
    features = ['one_day_change', 'mood_encoded', 'conf_encoded', 'sensex_mentions']
    X_live = live_df[features]

    # 3. Pull Historical Data to Check Model Feasibility
    trained_ml_active = False
    probabilities = []

    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(DB_PATH)
            # Pull rows that have gone through a daily outcome check (WIN=1, LOSS=0)
            query = "SELECT one_day_change, global_mood, confidence, sensex_mentions, outcome FROM historical_trades WHERE outcome IS NOT NULL"
            train_df = pd.read_sql_query(query, conn)
            conn.close()
            
            # Require at least 25 settled trade parameters to safely build an XGBoost structure
            if len(train_df) >= 25:
                print(f"[+] Found {len(train_df)} historical training profiles. Fitting XGBoost Core...")
                
                train_df['mood_encoded'] = le_mood.transform(train_df['global_mood'].str.lower().fillna('neutral'))
                train_df['conf_encoded'] = le_conf.transform(train_df['confidence'].fillna('MEDIUM'))
                
                X_train = train_df[features]
                y_train = train_df['outcome'].astype(int)
                
                # Setup regularized, low-depth trees to prevent noisy overfits
                model = XGBClassifier(
                    n_estimators=50,
                    max_depth=3,
                    learning_rate=0.05,
                    reg_alpha=0.1,    # L1 Regularization
                    reg_lambda=1.0,   # L2 Regularization
                    eval_metric='logloss'
                )
                model.fit(X_train, y_train)
                
                # Predict probability for class 1 (WIN)
                probabilities = model.predict_proba(X_live)[:, 1]
                trained_ml_active = True
                print("[+] XGBoost probability vectors generated successfully.")
        except Exception as e:
            print(f"[!] Error pulling historical data, falling back to heuristics: {str(e)}")

    if not trained_ml_active:
        print("[*] Cold-Start Phase: Executing Ensemble Heuristic Scoring...")
        probabilities = fallback_heuristic_scoring(live_df)

    # 4. Filter and Isolate Elite Tier Setups
    elite_signals = []
    for idx, stock in enumerate(raw_signals):
        prob = float(probabilities[idx])
        stock["ml_confidence"] = f"{round(prob * 100, 1)}%"
        
        # Hard constraint filter gatekeepers: must clear >72% probability
        if prob >= 0.72 and stock.get("action") != "AVOID":
            stock["elite_tier"] = True
            elite_signals.append(stock)
        else:
            stock["elite_tier"] = False

    # 5. Flush High-Conviction payloads to disk
    output_payload = {
        "updated_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        "engine_mode": "XGBoost_Classifier" if trained_ml_active else "Mathematical_Heuristic_Ensemble",
        "total_raw_signals": len(raw_signals),
        "elite_signals_count": len(elite_signals),
        "elite_signals": elite_signals
    }
    
    with open(DATA_DIR / "high_conviction_alerts.json", "w") as f:
        json.dump(output_payload, f, indent=2)
        
    print(f"[+] Matrix execution complete. Isolated {len(elite_signals)} premium high-probability trades.")

if __name__ == "__main__":
    main()