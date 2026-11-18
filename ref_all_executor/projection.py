from __future__ import annotations

import json
import sqlite3
import time
import uuid

from .runtime_state import list_events


PROJECTOR = "refall.runtime.v1"


def project_runtime_events(conn: sqlite3.Connection, subject: str) -> dict:
    watermark = conn.execute(
        "SELECT last_event_created_at FROM projection_watermarks WHERE projector=?",
        (PROJECTOR,),
    ).fetchone()
    since = float(watermark[0]) if watermark else -1.0
    events = [
        event for event in reversed(list_events(conn, subject, limit=10000))
        if float(event.get("created_at") or 0) > since
    ]
    projected = 0
    latest = since
    for event in events:
        latest = max(latest, float(event.get("created_at") or 0))
        if event.get("type") != "worker_submit":
            continue
        observation = _observation_from_event(conn, event)
        _delta_from_observation(conn, observation)
        projected += 1
    conn.execute(
        "INSERT INTO projection_watermarks(projector,last_event_created_at,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(projector) DO UPDATE SET last_event_created_at=excluded.last_event_created_at,"
        "updated_at=excluded.updated_at",
        (PROJECTOR, latest, time.time()),
    )
    conn.commit()
    return {"subject": subject, "events_seen": len(events), "events_projected": projected}


def _observation_from_event(conn: sqlite3.Connection, event: dict) -> dict:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), list) else []
    refs = [
        item.get("ref") for item in evidence
        if isinstance(item, dict) and item.get("ref")
    ]
    anchors = [
        item.get("ref") for item in evidence
        if isinstance(item, dict) and item.get("kind") == "source_anchor" and item.get("ref")
    ]
    claim = str(payload.get("summary") or payload.get("claim") or event.get("type"))
    observation = {
        "id": f"obs_{uuid.uuid4().hex}",
        "source_event_id": event["id"],
        "subject": event["subject"],
        "kind": "source_fact" if anchors else "runtime_fact",
        "claim": claim,
        "evidence_refs": refs,
        "source_anchors": anchors,
        "confidence": str(payload.get("confidence") or "medium"),
        "limitations": payload.get("limitations") or [],
        "created_at": time.time(),
    }
    conn.execute(
        "INSERT OR IGNORE INTO observations(id,source_event_id,subject,kind,claim,evidence_refs,"
        "source_anchors,confidence,limitations,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            observation["id"],
            observation["source_event_id"],
            observation["subject"],
            observation["kind"],
            observation["claim"],
            json.dumps(observation["evidence_refs"]),
            json.dumps(observation["source_anchors"]),
            observation["confidence"],
            json.dumps(observation["limitations"]),
            observation["created_at"],
        ),
    )
    row = conn.execute(
        "SELECT * FROM observations WHERE source_event_id=? AND kind=? AND claim=?",
        (observation["source_event_id"], observation["kind"], observation["claim"]),
    ).fetchone()
    return dict(row)


def _delta_from_observation(conn: sqlite3.Connection, observation: dict) -> None:
    props = {
        "claim": observation.get("claim"),
        "kind": observation.get("kind"),
        "evidence_refs": json.loads(observation.get("evidence_refs") or "[]"),
    }
    conn.execute(
        "INSERT OR IGNORE INTO evidence_deltas(id,source_observation_id,operation,node_type,node_id,properties,created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (
            f"ed_{uuid.uuid4().hex}",
            observation["id"],
            "upsert_node",
            "observation",
            observation["id"],
            json.dumps(props),
            time.time(),
        ),
    )
