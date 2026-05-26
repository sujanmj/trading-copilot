import json
import sqlite3
import os
from pathlib import Path
from datetime import datetime
import pytz

IST = pytz.timezone('Asia/Kolkata')
from backend.utils.config import DATA_DIR, DB_PATH

# Optional ML stack — lifecycle must complete without these
try:
    import pandas as pd
    import numpy as np
    PANDAS_OK = True
except ImportError:
    pd = None  # type: ignore
    np = None  # type: ignore
    PANDAS_OK = False

try:
    from xgboost import XGBClassifier
    from sklearn.preprocessing import LabelEncoder
    XGBOOST_OK = True
except ImportError:
    XGBClassifier = None  # type: ignore
    LabelEncoder = None  # type: ignore
    XGBOOST_OK = False


def load_json_safely(filename: str) -> dict:
    filepath = DATA_DIR / filename
    if not filepath.exists():
        return {}
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def _write_heuristic_only_payload(raw_signals: list, probabilities: list, engine_mode: str):
    elite_signals = []
    for idx, stock in enumerate(raw_signals):
        prob = float(probabilities[idx]) if idx < len(probabilities) else 0.5
        stock = dict(stock)
        stock["ml_confidence"] = f"{round(prob * 100, 1)}%"
        if prob >= 0.72 and stock.get("action") != "AVOID":
            stock["elite_tier"] = True
            elite_signals.append(stock)
        else:
            stock["elite_tier"] = False

    output_payload = {
        "updated_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        "engine_mode": engine_mode,
        "xgboost_available": XGBOOST_OK,
        "total_raw_signals": len(raw_signals),
        "elite_signals_count": len(elite_signals),
        "elite_signals": elite_signals,
    }
    out_path = DATA_DIR / "high_conviction_alerts.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, indent=2)
    print(f"[+] Meta-labeler complete ({engine_mode}). Elite signals: {len(elite_signals)}")
    return output_payload


def fallback_heuristic_scoring(rows: list) -> list:
    """Cold-start scoring without pandas/numpy."""
    scores = []
    for row in rows:
        p = 0.50
        change = float(row.get('one_day_change') or row.get('change_percent') or 0)
        if 2.0 <= change <= 6.0:
            p += 0.15
        if str(row.get('confidence', '')).upper() == 'HIGH':
            p += 0.10
        mood = str(row.get('global_mood', 'neutral')).lower()
        if mood == 'bullish':
            p += 0.10
        elif mood == 'bearish':
            p -= 0.15
        scores.append(min(max(p, 0.0), 1.0))
    return scores


def fallback_heuristic_scoring_df(df) -> "np.ndarray":
    scores = []
    for _, row in df.iterrows():
        p = 0.50
        if 2.0 <= row['one_day_change'] <= 6.0:
            p += 0.15
        if row['confidence'] == 'HIGH':
            p += 0.10
        if row['global_mood'] == 'bullish':
            p += 0.10
        if row['global_mood'] == 'bearish':
            p -= 0.15
        scores.append(min(max(p, 0.0), 1.0))
    return np.array(scores)


def main():
    print("[*] Initializing Meta-Labeling Engine (optional ML)...")

    scanner_data = load_json_safely("scanner_data.json")
    news_feed = load_json_safely("news_feed.json")
    global_markets = load_json_safely("global_markets.json")

    global_mood = global_markets.get("market_mood", "neutral").lower()
    sensex_mentions = news_feed.get("stats", {}).get("SENSEX_mentions", 0)
    raw_signals = scanner_data.get("signals", []) or scanner_data.get("top_signals", []) or scanner_data.get("stocks", [])

    if not raw_signals:
        print("[!] No active scanner signals — writing empty high_conviction_alerts.json")
        return _write_heuristic_only_payload([], [], "No_Signals")

    if not PANDAS_OK:
        print("[*] pandas/numpy unavailable — heuristic scoring only")
        enriched = []
        for s in raw_signals:
            row = dict(s)
            row['global_mood'] = global_mood
            row['sensex_mentions'] = sensex_mentions
            row['one_day_change'] = row.get('one_day_change') or row.get('change_percent') or 0.0
            enriched.append(row)
        probs = fallback_heuristic_scoring(enriched)
        return _write_heuristic_only_payload(raw_signals, probs, "Mathematical_Heuristic_Ensemble")

    live_df = pd.DataFrame(raw_signals)
    live_df['global_mood'] = global_mood
    live_df['sensex_mentions'] = sensex_mentions
    if 'one_day_change' not in live_df.columns:
        live_df['one_day_change'] = live_df.get('change_percent', 0.0)
    if 'confidence' not in live_df.columns:
        live_df['confidence'] = 'MEDIUM'

    trained_ml_active = False
    probabilities = []

    if XGBOOST_OK and DB_PATH.exists():
        try:
            le_mood = LabelEncoder().fit(['neutral', 'bullish', 'bearish'])
            le_conf = LabelEncoder().fit(['LOW', 'MEDIUM', 'HIGH'])
            live_df['mood_encoded'] = le_mood.transform(live_df['global_mood'].fillna('neutral').str.lower())
            live_df['conf_encoded'] = le_conf.transform(live_df['confidence'].fillna('MEDIUM'))
            features = ['one_day_change', 'mood_encoded', 'conf_encoded', 'sensex_mentions']
            X_live = live_df[features]

            conn = sqlite3.connect(DB_PATH)
            query = (
                "SELECT one_day_change, global_mood, confidence, sensex_mentions, outcome "
                "FROM historical_trades WHERE outcome IS NOT NULL"
            )
            train_df = pd.read_sql_query(query, conn)
            conn.close()

            if len(train_df) >= 25:
                print(f"[+] Found {len(train_df)} historical profiles — fitting XGBoost...")
                train_df['mood_encoded'] = le_mood.transform(train_df['global_mood'].str.lower().fillna('neutral'))
                train_df['conf_encoded'] = le_conf.transform(train_df['confidence'].fillna('MEDIUM'))
                X_train = train_df[features]
                y_train = train_df['outcome'].astype(int)
                model = XGBClassifier(
                    n_estimators=50,
                    max_depth=3,
                    learning_rate=0.05,
                    reg_alpha=0.1,
                    reg_lambda=1.0,
                    eval_metric='logloss',
                )
                model.fit(X_train, y_train)
                probabilities = model.predict_proba(X_live)[:, 1].tolist()
                trained_ml_active = True
        except Exception as e:
            print(f"[!] XGBoost path unavailable, using heuristics: {e}")

    if not trained_ml_active:
        print("[*] Heuristic scoring (xgboost unavailable or insufficient training data)")
        probabilities = fallback_heuristic_scoring_df(live_df).tolist()

    mode = "XGBoost_Classifier" if trained_ml_active else "Mathematical_Heuristic_Ensemble"
    return _write_heuristic_only_payload(raw_signals, probabilities, mode)


if __name__ == "__main__":
    main()
