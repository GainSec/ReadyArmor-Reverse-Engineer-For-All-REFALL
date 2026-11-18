from __future__ import annotations

import hashlib
import sqlite3
import time
import uuid
from pathlib import Path

from .runtime_state import runtime_root


def save_artifact(
    conn: sqlite3.Connection,
    subject_path: Path,
    *,
    subject: str,
    kind: str,
    content: bytes | str,
    mime: str = "application/octet-stream",
    task_id: str | None = None,
    run_id: str | None = None,
    source_event_id: str | None = None,
    workbench_object_id: str | None = None,
) -> dict:
    data = content.encode("utf-8") if isinstance(content, str) else content
    artifact_id = f"art_{uuid.uuid4().hex}"
    root = runtime_root(subject_path) / "artifacts" / kind
    root.mkdir(parents=True, exist_ok=True)
    suffix = ".txt" if mime.startswith("text/") else ".bin"
    path = root / f"{artifact_id}{suffix}"
    path.write_bytes(data)
    sha256 = hashlib.sha256(data).hexdigest()
    created_at = time.time()
    record = {
        "id": artifact_id,
        "subject": subject,
        "run_id": run_id,
        "task_id": task_id,
        "kind": kind,
        "path": str(path),
        "mime": mime,
        "sha256": sha256,
        "size_bytes": len(data),
        "source_event_id": source_event_id,
        "workbench_object_id": workbench_object_id,
        "created_at": created_at,
    }
    conn.execute(
        "INSERT INTO artifacts(id,subject,run_id,task_id,kind,path,mime,sha256,size_bytes,"
        "source_event_id,workbench_object_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            artifact_id,
            subject,
            run_id,
            task_id,
            kind,
            str(path),
            mime,
            sha256,
            len(data),
            source_event_id,
            workbench_object_id,
            created_at,
        ),
    )
    conn.commit()
    return record
