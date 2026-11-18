from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

from arctic_base.refall.contracts import RunManifest


NONFATAL_EVENT_MARKERS = (
    "error",
    "failed",
    "failure",
    "invalid",
    "refused",
    "blocked",
    "timeout",
    "rate_limited",
    "scope_blocked",
    "capability_missing",
)
NONFATAL_PAYLOAD_KEYS = {
    "failure_class",
    "error",
    "refusal_reasons",
    "reasons",
}
NONFATAL_STATUSES = {
    "error",
    "failed",
    "failure",
    "invalid",
    "refused",
    "blocked",
    "timeout",
    "rate_limited",
    "scope_blocked",
    "capability_missing",
}


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
CREATE TABLE IF NOT EXISTS run_manifests (
  id TEXT PRIMARY KEY,
  subject TEXT NOT NULL,
  workbench TEXT,
  run_id TEXT NOT NULL,
  payload TEXT NOT NULL,
  workbench_object_id TEXT,
  created_at REAL,
  updated_at REAL
);
CREATE INDEX IF NOT EXISTS ix_run_manifests_subject ON run_manifests(subject, updated_at);
CREATE TABLE IF NOT EXISTS stage_checkpoints (
  id TEXT PRIMARY KEY,
  subject TEXT NOT NULL,
  workbench TEXT,
  run_id TEXT,
  stage TEXT NOT NULL,
  checkpoint_key TEXT NOT NULL,
  status TEXT NOT NULL,
  input_hashes TEXT,
  output_refs TEXT,
  payload TEXT,
  created_at REAL,
  updated_at REAL,
  UNIQUE(subject, checkpoint_key)
);
CREATE INDEX IF NOT EXISTS ix_stage_checkpoints_subject ON stage_checkpoints(subject, updated_at);
"""


def runtime_root(subject_path: Path) -> Path:
    return subject_path / ".refall" / "runtime"


def connect_runtime(subject_path: Path) -> sqlite3.Connection:
    path = runtime_root(subject_path) / "state.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    _ensure_column(conn, "retry_state", "artifact_refs", "TEXT")
    _ensure_column(conn, "run_manifests", "workbench_object_id", "TEXT")
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


def list_nonfatal_errors(conn: sqlite3.Connection, subject: str, limit: int = 500) -> list[dict]:
    errors: list[dict] = []
    for event in list_events(conn, subject, limit=limit * 4):
        if _runtime_event_is_nonfatal_error(event):
            errors.append(_nonfatal_error_row(event))
        if len(errors) >= limit:
            break
    return errors


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


def put_manifest(
    conn: sqlite3.Connection,
    subject: str,
    workbench: str,
    payload: dict,
    *,
    workbench_object_id: str | None = None,
) -> dict:
    now = time.time()
    payload = dict(payload or {})
    payload.pop("subject", None)
    payload.pop("workbench", None)
    existing = None
    if payload.get("run_id"):
        existing = conn.execute(
            "SELECT * FROM run_manifests WHERE subject=? AND run_id=? ORDER BY updated_at DESC LIMIT 1",
            (subject, payload["run_id"]),
        ).fetchone()
    object_id = workbench_object_id or (existing["workbench_object_id"] if existing else None)
    manifest = RunManifest(subject=subject, workbench=workbench, **payload).model_dump(mode="json")
    record = {**manifest, "workbench_object_id": object_id}
    created_at = existing["created_at"] if existing else now
    conn.execute(
        "INSERT INTO run_manifests(id,subject,workbench,run_id,payload,workbench_object_id,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, "
        "workbench_object_id=excluded.workbench_object_id, updated_at=excluded.updated_at",
        (
            manifest["manifest_id"],
            subject,
            workbench,
            manifest["run_id"],
            json.dumps(record, sort_keys=True),
            object_id,
            created_at,
            now,
        ),
    )
    conn.commit()
    return record


def get_latest_manifest(conn: sqlite3.Connection, subject: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM run_manifests WHERE subject=? ORDER BY updated_at DESC LIMIT 1",
        (subject,),
    ).fetchone()
    if not row:
        return None
    payload = _load(row["payload"], {})
    if isinstance(payload, dict):
        payload.setdefault("workbench_object_id", row["workbench_object_id"])
        return payload
    return None


def put_checkpoint(
    conn: sqlite3.Connection,
    *,
    subject: str,
    workbench: str | None,
    run_id: str | None,
    stage: str,
    checkpoint_key: str,
    status: str,
    input_hashes: dict | None = None,
    output_refs: list[str] | None = None,
    payload: dict | None = None,
) -> dict:
    now = time.time()
    existing = conn.execute(
        "SELECT id,created_at FROM stage_checkpoints WHERE subject=? AND checkpoint_key=?",
        (subject, checkpoint_key),
    ).fetchone()
    checkpoint_id = existing["id"] if existing else f"ckpt_{uuid.uuid4().hex}"
    created_at = existing["created_at"] if existing else now
    record = {
        "id": checkpoint_id,
        "subject": subject,
        "workbench": workbench,
        "run_id": run_id,
        "stage": stage,
        "checkpoint_key": checkpoint_key,
        "status": status,
        "input_hashes": input_hashes or {},
        "output_refs": output_refs or [],
        "payload": payload or {},
        "created_at": created_at,
        "updated_at": now,
    }
    conn.execute(
        "INSERT INTO stage_checkpoints(id,subject,workbench,run_id,stage,checkpoint_key,status,"
        "input_hashes,output_refs,payload,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(subject,checkpoint_key) DO UPDATE SET "
        "workbench=excluded.workbench, run_id=excluded.run_id, stage=excluded.stage, "
        "status=excluded.status, input_hashes=excluded.input_hashes, "
        "output_refs=excluded.output_refs, payload=excluded.payload, updated_at=excluded.updated_at",
        (
            checkpoint_id,
            subject,
            workbench,
            run_id,
            stage,
            checkpoint_key,
            status,
            json.dumps(record["input_hashes"], sort_keys=True),
            json.dumps(record["output_refs"], sort_keys=True),
            json.dumps(record["payload"], sort_keys=True),
            created_at,
            now,
        ),
    )
    conn.commit()
    return record


def list_checkpoints(conn: sqlite3.Connection, subject: str, limit: int = 500) -> list[dict]:
    return [
        _checkpoint_row(row)
        for row in conn.execute(
            "SELECT * FROM stage_checkpoints WHERE subject=? ORDER BY updated_at DESC LIMIT ?",
            (subject, limit),
        )
    ]


def resume_preflight(conn: sqlite3.Connection, subject: str, current_hashes: dict | None) -> dict:
    current = {str(key): str(value) for key, value in (current_hashes or {}).items()}
    checkpoints = list_checkpoints(conn, subject, limit=1000)
    expected: dict[str, str] = {}
    checkpoint_ids: list[str] = []
    for checkpoint in reversed(checkpoints):
        hashes = checkpoint.get("input_hashes") if isinstance(checkpoint.get("input_hashes"), dict) else {}
        if hashes:
            checkpoint_ids.append(str(checkpoint["id"]))
        for key, value in hashes.items():
            expected[str(key)] = str(value)
    changes = []
    if current:
        for key, expected_hash in sorted(expected.items()):
            actual_hash = current.get(key)
            if actual_hash is None:
                changes.append({"path": key, "expected": expected_hash, "actual": None, "reason": "missing"})
            elif str(actual_hash) != str(expected_hash):
                changes.append({"path": key, "expected": expected_hash, "actual": actual_hash, "reason": "changed"})
        for key, actual_hash in sorted(current.items()):
            if key not in expected:
                changes.append({"path": key, "expected": None, "actual": actual_hash, "reason": "added"})
    return {
        "subject": subject,
        "accepted": not changes,
        "status": "accepted" if not changes else "drift",
        "message": "resume input hashes accepted" if not changes else "resume input hashes changed",
        "changes": changes,
        "checkpoint_ids": checkpoint_ids,
    }


def _event_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["payload"] = _load(data.get("payload"), {})
    data["artifact_refs"] = _load(data.get("artifact_refs"), [])
    return data


def _runtime_event_is_nonfatal_error(event: dict) -> bool:
    event_type = str(event.get("type") or "").lower()
    if any(marker in event_type for marker in NONFATAL_EVENT_MARKERS):
        return True
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    if any(key in payload and payload.get(key) not in (None, "", []) for key in NONFATAL_PAYLOAD_KEYS):
        return True
    status = str(payload.get("status") or "").lower()
    return status in NONFATAL_STATUSES


def _nonfatal_error_row(event: dict) -> dict:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return {
        "id": event.get("id"),
        "source": "runtime",
        "type": event.get("type"),
        "created_at": event.get("created_at"),
        "run_id": event.get("run_id"),
        "task_id": event.get("task_id"),
        "session_id": event.get("session_id"),
        "summary": _payload_summary(payload, str(event.get("type") or "")),
        "failure_class": payload.get("failure_class") or payload.get("error_class") or payload.get("kind"),
        "refusal_reasons": _reason_list(payload),
        "artifact_refs": event.get("artifact_refs") or [],
    }


def _reason_list(payload: dict) -> list[str]:
    for key in ("refusal_reasons", "reasons"):
        value = payload.get(key)
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
    return []


def _payload_summary(payload: dict, fallback: str) -> str:
    for key in ("summary", "message", "error", "detail"):
        value = payload.get(key)
        if value:
            return str(value)
    return fallback


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


def _checkpoint_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["input_hashes"] = _load(data.get("input_hashes"), {})
    data["output_refs"] = _load(data.get("output_refs"), [])
    data["payload"] = _load(data.get("payload"), {})
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
