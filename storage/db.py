"""SQLite persistence layer for research agent runs.

Stores each run as a row containing metadata, serialized Blackboard state JSON,
and the final markdown report.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from blackboard import Blackboard

DEFAULT_DB_PATH = "research_runs.db"


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Initialize the runs table schema if not already present."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    project_context TEXT,
                    status TEXT NOT NULL,
                    sources_count INTEGER DEFAULT 0,
                    gaps_count INTEGER DEFAULT 0,
                    features_count INTEGER DEFAULT 0,
                    blackboard_json TEXT NOT NULL,
                    report_markdown TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
    finally:
        conn.close()


def save_run(
    blackboard: Blackboard,
    status: str = "completed",
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Insert or update a research run record in SQLite."""
    init_db(db_path)
    now = datetime.now(timezone.utc).isoformat()
    bb_json = blackboard.to_json()
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO runs (
                    run_id, topic, project_context, status,
                    sources_count, gaps_count, features_count,
                    blackboard_json, report_markdown, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    topic = excluded.topic,
                    project_context = excluded.project_context,
                    status = excluded.status,
                    sources_count = excluded.sources_count,
                    gaps_count = excluded.gaps_count,
                    features_count = excluded.features_count,
                    blackboard_json = excluded.blackboard_json,
                    report_markdown = excluded.report_markdown,
                    updated_at = excluded.updated_at
                """,
                (
                    blackboard.run_id,
                    blackboard.topic,
                    blackboard.project_context,
                    status,
                    len(blackboard.sources),
                    len(blackboard.gaps),
                    len(blackboard.proposed_features),
                    bb_json,
                    blackboard.report_markdown,
                    now,
                    now,
                ),
            )
    finally:
        conn.close()


def get_run(run_id: str, db_path: str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """Fetch a run by its ID."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        conn.close()


def list_runs(db_path: str = DEFAULT_DB_PATH, limit: int = 50) -> List[Dict[str, Any]]:
    """List recent runs with summary statistics."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT run_id, topic, project_context, status,
                   sources_count, gaps_count, features_count,
                   created_at, updated_at
            FROM runs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
