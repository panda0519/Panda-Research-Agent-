import json
import sqlite3

conn = sqlite3.connect("research_runs.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT run_id, status, sources_count, gaps_count, features_count, created_at FROM runs ORDER BY created_at DESC")
rows = cur.fetchall()
for r in rows:
    print(dict(r))
conn.close()
