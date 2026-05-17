"""
force_clean.py - Wipe ALL bad data without prompts
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).parent.parent / 'data' / 'trading_history.db'
conn = sqlite3.connect(DB)
c = conn.cursor()

# Show before
c.execute("SELECT COUNT(*) FROM predictions")
p_before = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM outcomes")
o_before = c.fetchone()[0]

print(f"Before: {p_before} predictions, {o_before} outcomes")

# Delete everything
c.execute("DELETE FROM outcomes")
c.execute("DELETE FROM predictions")
c.execute("DELETE FROM sqlite_sequence WHERE name IN ('predictions', 'outcomes')")
conn.commit()

# Show after
c.execute("SELECT COUNT(*) FROM predictions")
p_after = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM outcomes")
o_after = c.fetchone()[0]

conn.close()
print(f"After: {p_after} predictions, {o_after} outcomes")
print("✅ Clean!")