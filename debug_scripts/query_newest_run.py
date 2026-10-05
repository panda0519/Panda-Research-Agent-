"""Query the newest row from research_runs.db and dump key fields."""
import json
import sqlite3
import sys

db_path = "research_runs.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT 1")
row = cur.fetchone()
if not row:
    print("NO ROWS FOUND")
    sys.exit(1)

print(f"run_id: {row['run_id']}")
print(f"status: {row['status']}")
print(f"sources_count: {row['sources_count']}")
print(f"gaps_count: {row['gaps_count']}")
print(f"features_count: {row['features_count']}")

bb = json.loads(row["blackboard_json"])
print(f"len(existing_solutions): {len(bb.get('existing_solutions', []))}")
print(f"len(claim_verifications): {len(bb.get('claim_verifications', []))}")
print(f"len(tech_stack): {len(bb.get('tech_stack', []))}")
print(f"len(evaluations): {len(bb.get('evaluations', []))}")
print(f"len(consistency_issues): {len(bb.get('consistency_issues', []))}")

phase_errors = bb.get("metadata", {}).get("phase_errors", {})
print(f"\nmetadata.phase_errors:")
print(json.dumps(phase_errors, indent=2))

conn.close()
