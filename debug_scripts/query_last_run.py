import sqlite3
import json
import sys

conn = sqlite3.connect("research_runs.db")
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT 1")
r = c.fetchone()

print("=" * 60)
print("RUN_ID:", r["run_id"])
print("TOPIC:", r["topic"])
print("STATUS:", r["status"])
print("sources_count:", r["sources_count"])
print("gaps_count:", r["gaps_count"])
print("features_count:", r["features_count"])
print("=" * 60)

bb = json.loads(r["blackboard_json"])
meta = bb.get("metadata", {})

print("\n=== PHASES ===")
print(json.dumps(meta.get("phases", {}), indent=2))

print("\n=== PHASE_ERRORS ===")
print(json.dumps(meta.get("phase_errors", {}), indent=2))

print("\n=== DEGRADED_PHASES ===")
print(json.dumps(meta.get("degraded_phases", []), indent=2))

print("\n=== FULL METADATA (non-phases) ===")
for k, v in meta.items():
    if k not in ("phases",):
        print(f"  {k}: {json.dumps(v) if isinstance(v, (dict, list)) else v}")
