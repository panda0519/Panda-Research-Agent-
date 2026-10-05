import sqlite3
import json

db_path = "research_runs.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

query = """
SELECT 
    run_id,
    topic,
    status,
    sources_count,
    gaps_count,
    features_count,
    blackboard_json,
    created_at
FROM runs
ORDER BY created_at DESC
LIMIT 1;
"""

print("=== SQL QUERY ===")
print(query.strip())
print("\n=== QUERY EXECUTION & RESULTS ===")

cursor.execute(query)
row = cursor.fetchone()

if row:
    run_id, topic, status, sources_count, gaps_count, features_count, bb_raw, created_at = row
    bb = json.loads(bb_raw) if bb_raw else {}
    meta = bb.get("metadata", {})
    
    print(f"run_id: {run_id}")
    print(f"created_at: {created_at}")
    print(f"topic: {topic}")
    print(f"status: {status}")
    print(f"sources_count: {sources_count}")
    print(f"gaps_count: {gaps_count}")
    print(f"features_count: {features_count}")
    print(f"len(paper_notes): {len(bb.get('paper_notes', []))}")
    print(f"len(existing_solutions): {len(bb.get('existing_solutions', []))}")
    print(f"len(tech_stack): {len(bb.get('tech_stack', []))}")
    print(f"len(evaluations): {len(bb.get('evaluations', []))}")
    print(f"len(claim_verifications): {len(bb.get('claim_verifications', []))}")
    print(f"len(consistency_issues): {len(bb.get('consistency_issues', []))}")
    print(f"phase_errors: {json.dumps(meta.get('phase_errors', {}), indent=2)}")
else:
    print("No runs found in database.")

conn.close()

