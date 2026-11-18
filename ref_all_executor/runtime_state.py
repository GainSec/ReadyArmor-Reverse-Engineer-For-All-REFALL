from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL, workbench TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS task_epochs (
  id TEXT PRIMARY KEY, run_id TEXT, task_id TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS worker_sessions (
  id TEXT PRIMARY KEY, run_id TEXT, task_id TEXT, status TEXT, created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS runtime_events (
  id TEXT PRIMARY KEY, run_id TEXT, task_id TEXT, session_id TEXT,
  type TEXT NOT NULL, subject TEXT NOT NULL, workbench TEXT,
  payload TEXT, artifact_refs TEXT, created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_runtime_events_subject ON runtime_events(subject, created_at);
CREATE TABLE IF NOT EXISTS artifacts (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL, run_id TEXT, task_id TEXT,
  kind TEXT NOT NULL, path TEXT NOT NULL, mime TEXT, sha256 TEXT, size_bytes INTEGER,
  source_event_id TEXT, workbench_object_id TEXT, created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_artifacts_subject ON artifacts(subject, created_at);
CREATE TABLE IF NOT EXISTS observations (
  id TEXT PRIMARY KEY, source_event_id TEXT NOT NULL, subject TEXT NOT NULL,
  kind TEXT NOT NULL, claim TEXT, evidence_refs TEXT, source_anchors TEXT,
  confidence TEXT, limitations TEXT, created_at REAL,
  UNIQUE(source_event_id, kind, claim)
);
CREATE TABLE IF NOT EXISTS evidence_deltas (
  id TEXT PRIMARY KEY, source_observation_id TEXT NOT NULL, operation TEXT NOT NULL,
  node_type TEXT, node_id TEXT, properties TEXT, created_at REAL,
  UNIQUE(source_observation_id, operation, node_type, node_id)
);
CREATE TABLE IF NOT EXISTS projection_watermarks (
  projector TEXT PRIMARY KEY, last_event_created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS control_signals (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL, kind TEXT, payload TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS retry_state (
  id TEXT PRIMARY KEY, task_id TEXT, session_id TEXT, attempt INTEGER, max_attempts INTEGER,
  failure_class TEXT, last_error TEXT, next_action TEXT, status TEXT, artifact_refs TEXT,
  created_at REAL, updated_at REAL
);
"""


def runtime_root(subject_path: Path) -> Path:
    return subject_path / ".refall" / "runtime"


def runtime_db_path(subject_path: Path) -> Path:
    return runtime_root(subject_path) / "state.sqlite"


def connect_runtime(subject_path: Path) -> sqlite3.Connection:
    path = runtime_db_path(subject_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    _ensure_column(conn, "retry_state", "artifact_refs", "TEXT")
    conn.commit()
    return conn


def append_event(
    conn: sqlite3.Connection,
    *,
    subject: str,
    event_type: str,
    workbench: str | None = None,
    run_id: str | None = None,
    task_id: str | None = None,
    session_id: str | None = None,
    payload: dict | None = None,
    artifact_refs: list[str] | None = None,
) -> dict:
    now = time.time()
    event = {
        "id": f"rte_{uuid.uuid4().hex}",
        "run_id": run_id,
        "task_id": task_id,
        "session_id": session_id,
        "type": event_type,
        "subject": subject,
        "workbench": workbench,
        "payload": payload or {},
        "artifact_refs": artifact_refs or [],
        "created_at": now,
    }
    conn.execute(
        "INSERT INTO runtime_events(id,run_id,task_id,session_id,type,subject,workbench,payload,artifact_refs,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            event["id"],
            run_id,
            task_id,
            session_id,
            event_type,
            subject,
            workbench,
            json.dumps(payload or {}),
            json.dumps(artifact_refs or []),
            now,
        ),
    )
    conn.commit()
    return event


def list_events(conn: sqlite3.Connection, subject: str, limit: int = 500) -> list[dict]:
    return [_event_row(row) for row in conn.execute(
        "SELECT * FROM runtime_events WHERE subject=? ORDER BY created_at DESC LIMIT ?",
        (subject, limit),
    )]


def list_artifacts(conn: sqlite3.Connection, subject: str, limit: int = 500) -> list[dict]:
    return [dict(row) for row in conn.execute(
        "SELECT * FROM artifacts WHERE subject=? ORDER BY created_at DESC LIMIT ?",
        (subject, limit),
    )]


def list_observations(conn: sqlite3.Connection, subject: str, limit: int = 500) -> list[dict]:
    return [_observation_row(row) for row in conn.execute(
        "SELECT * FROM observations WHERE subject=? ORDER BY created_at DESC LIMIT ?",
        (subject, limit),
    )]


def list_deltas(conn: sqlite3.Connection, limit: int = 1000) -> list[dict]:
    return [_delta_row(row) for row in conn.execute(
        "SELECT * FROM evidence_deltas ORDER BY created_at ASC LIMIT ?",
        (limit,),
    )]


def _event_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["payload"] = _load(data.get("payload"), {})
    data["artifact_refs"] = _load(data.get("artifact_refs"), [])
    return data


def _observation_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["evidence_refs"] = _load(data.get("evidence_refs"), [])
    data["source_anchors"] = _load(data.get("source_anchors"), [])
    data["limitations"] = _load(data.get("limitations"), [])
    return data


def _delta_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["properties"] = _load(data.get("properties"), {})
    return data


def _load(raw: object, default: object) -> object:
    if raw in (None, ""):
        return default
    try:
        return json.loads(str(raw))
    except json.JSONDecodeError:
        return default


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
