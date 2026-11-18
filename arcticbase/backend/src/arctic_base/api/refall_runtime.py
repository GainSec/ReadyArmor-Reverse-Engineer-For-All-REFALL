from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from arctic_base.api.deps import get_storage
from arctic_base.models import ObjectKind, ObjectMeta
from arctic_base.refall import ledger
from arctic_base.refall.artifact_store import save_artifact
from arctic_base.refall.coverage_store import store_for_workbench
from arctic_base.refall.evidence_graph import graph_from_deltas
from arctic_base.refall.projection import project_runtime_events
from arctic_base.refall.runtime_state import (
    append_event,
    connect_runtime,
    get_latest_manifest,
    list_artifacts,
    list_checkpoints,
    list_deltas,
    list_events,
    list_nonfatal_errors,
    list_observations,
    put_checkpoint,
    put_manifest,
    resume_preflight,
)
from arctic_base.storage.errors import NotFound
from arctic_base.storage.filesystem import FilesystemStorage, new_object_id

router = APIRouter(prefix="/workbenches/{slug}/runtime", tags=["refall-runtime"])


class RuntimeEventReq(BaseModel):
    type: str
    run_id: str | None = None
    task_id: str | None = None
    session_id: str | None = None
    payload: dict = Field(default_factory=dict)
    artifact_refs: list[str] = Field(default_factory=list)


class RuntimeArtifactReq(BaseModel):
    kind: str
    content: str
    mime: str = "text/plain"
    task_id: str | None = None
    run_id: str | None = None
    source_event_id: str | None = None
    workbench_object_id: str | None = None


class RuntimeManifestReq(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    refall_version: str | None = None
    provider_roles: dict = Field(default_factory=dict)
    runtime_host: dict = Field(default_factory=dict)
    config_hashes: dict[str, str] = Field(default_factory=dict)
    source_hashes: dict[str, str] = Field(default_factory=dict)
    source_inventory_id: str | None = None
    scope_overlay_id: str | None = None
    threat_model_id: str | None = None
    capability_grant_ids: list[str] = Field(default_factory=list)
    capability_request_ids: list[str] = Field(default_factory=list)
    checkpoint_ids: list[str] = Field(default_factory=list)
    output_object_ids: list[str] = Field(default_factory=list)
    git: dict = Field(default_factory=dict)
    dynamic_testing: dict = Field(default_factory=dict)
    stage_status: dict = Field(default_factory=dict)


class RuntimeCheckpointReq(BaseModel):
    run_id: str | None = None
    stage: str
    checkpoint_key: str
    status: str
    input_hashes: dict[str, str] = Field(default_factory=dict)
    output_refs: list[str] = Field(default_factory=list)
    payload: dict = Field(default_factory=dict)


class ResumePreflightReq(BaseModel):
    input_hashes: dict[str, str] = Field(default_factory=dict)


@router.get("/runs", operation_id="listRefallRuntimeRuns")
def list_runtime_runs(slug: str, storage: Annotated[FilesystemStorage, Depends(get_storage)]) -> dict:
    conn = connect_runtime(_subject_path(storage, slug))
    rows = [dict(row) for row in conn.execute("SELECT * FROM runs ORDER BY created_at DESC")]
    return {"subject": slug, "runs": rows}


@router.put("/manifest", operation_id="putRefallRuntimeManifest")
def put_runtime_manifest(
    slug: str,
    body: RuntimeManifestReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    conn = connect_runtime(_subject_path(storage, slug))
    existing = get_latest_manifest(conn, slug) or {}
    try:
        manifest = put_manifest(conn, slug, slug, body.model_dump(), workbench_object_id=existing.get("workbench_object_id"))
    except ValidationError as exc:
        raise HTTPException(422, exc.errors()) from exc
    object_id = _publish_manifest_runbook(storage, slug, manifest)
    if object_id != manifest.get("workbench_object_id"):
        manifest = put_manifest(conn, slug, slug, manifest, workbench_object_id=object_id)
        _publish_manifest_runbook(storage, slug, manifest)
    ledger.append_entry(
        storage,
        slug,
        {
            "kind": "runtime-event",
            "subject": slug,
            "event_type": "run_manifest_updated",
            "summary": f"Run manifest updated for {slug}",
            "run_id": manifest["run_id"],
            "manifest_id": manifest["manifest_id"],
            "workbench_object_id": manifest.get("workbench_object_id"),
        },
    )
    return manifest


@router.get("/manifest", operation_id="getRefallRuntimeManifest")
def get_runtime_manifest(slug: str, storage: Annotated[FilesystemStorage, Depends(get_storage)]) -> dict:
    manifest = get_latest_manifest(connect_runtime(_subject_path(storage, slug)), slug)
    if not manifest:
        raise HTTPException(404, "no run manifest")
    return manifest


@router.post("/checkpoints", status_code=201, operation_id="putRefallRuntimeCheckpoint")
def put_runtime_checkpoint(
    slug: str,
    body: RuntimeCheckpointReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    checkpoint = put_checkpoint(
        connect_runtime(_subject_path(storage, slug)),
        subject=slug,
        workbench=slug,
        run_id=body.run_id,
        stage=body.stage,
        checkpoint_key=body.checkpoint_key,
        status=body.status,
        input_hashes=body.input_hashes,
        output_refs=body.output_refs,
        payload=body.payload,
    )
    ledger.append_entry(
        storage,
        slug,
        {
            "kind": "runtime-event",
            "subject": slug,
            "event_type": "checkpoint_updated",
            "summary": f"Checkpoint {checkpoint['checkpoint_key']} updated",
            "run_id": checkpoint.get("run_id"),
            "checkpoint_id": checkpoint["id"],
            "stage": checkpoint["stage"],
            "status": checkpoint["status"],
        },
    )
    return checkpoint


@router.get("/checkpoints", operation_id="listRefallRuntimeCheckpoints")
def get_runtime_checkpoints(slug: str, storage: Annotated[FilesystemStorage, Depends(get_storage)]) -> list[dict]:
    return list_checkpoints(connect_runtime(_subject_path(storage, slug)), slug)


@router.post("/resume-preflight", operation_id="preflightRefallRuntimeResume")
def runtime_resume_preflight(
    slug: str,
    body: ResumePreflightReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    result = resume_preflight(connect_runtime(_subject_path(storage, slug)), slug, body.input_hashes)
    if result["accepted"]:
        return result
    store = store_for_workbench(storage, slug)
    action = store.create_pending_action(
        slug,
        {
            "kind": "resume_drift_decision",
            "title": "Review changed REFALL resume inputs",
            "description": result["message"],
            "priority": "high",
            "required_receipt_type": "manager_review",
            "assigned_lane": "review",
            "created_by": "refall-runtime",
            "identity_key": "resume_drift:" + ",".join(sorted(str(item["path"]) for item in result["changes"])),
        },
    )
    ledger.append_entry(
        storage,
        slug,
        {
            "kind": "pending-action",
            "subject": slug,
            "action": "resume.preflight.drift",
            "status": action["status"],
            "pending_action_id": action["id"],
            "summary": result["message"],
            "changes": result["changes"],
        },
    )
    raise HTTPException(409, result)


@router.post("/events", status_code=201, operation_id="appendRefallRuntimeEvent")
def append_runtime_event(
    slug: str,
    body: RuntimeEventReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    conn = connect_runtime(_subject_path(storage, slug))
    event = append_event(
        conn,
        subject=slug,
        workbench=slug,
        event_type=body.type,
        run_id=body.run_id,
        task_id=body.task_id,
        session_id=body.session_id,
        payload=body.payload,
        artifact_refs=body.artifact_refs,
    )
    ledger.append_entry(
        storage,
        slug,
        {
            "kind": "runtime-event",
            "subject": slug,
            "runtime_event_id": event["id"],
            "event_type": body.type,
            "summary": body.payload.get("summary") or body.type,
        },
    )
    store = store_for_workbench(storage, slug)
    for action in store.trigger_pending_actions_for_runtime_event(slug, event):
        ledger.append_entry(
            storage,
            slug,
            {
                "kind": "pending-action",
                "subject": slug,
                "action": "pending.create",
                "status": action["status"],
                "pending_action_id": action["id"],
                "title": action["title"],
                "summary": action.get("description") or action["title"],
            },
        )
    return event


@router.get("/events", operation_id="listRefallRuntimeEvents")
def get_runtime_events(slug: str, storage: Annotated[FilesystemStorage, Depends(get_storage)]) -> list[dict]:
    return list_events(connect_runtime(_subject_path(storage, slug)), slug)


@router.get("/nonfatal-errors", operation_id="listRefallRuntimeNonfatalErrors")
def get_nonfatal_errors(slug: str, storage: Annotated[FilesystemStorage, Depends(get_storage)], limit: int = 500) -> dict:
    errors = _nonfatal_errors(storage, slug, limit=limit)
    return {"subject": slug, "count": len(errors), "errors": errors}


@router.get("/nonfatal-errors.ndjson", operation_id="exportRefallRuntimeNonfatalErrorsNdjson")
def get_nonfatal_errors_ndjson(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
    limit: int = 500,
) -> Response:
    lines = [
        json.dumps(item, sort_keys=True)
        for item in _nonfatal_errors(storage, slug, limit=limit)
    ]
    body = "\n".join(lines) + ("\n" if lines else "")
    return Response(content=body, media_type="application/x-ndjson")


@router.post("/artifacts", status_code=201, operation_id="createRefallRuntimeArtifact")
def create_runtime_artifact(
    slug: str,
    body: RuntimeArtifactReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    conn = connect_runtime(_subject_path(storage, slug))
    return save_artifact(
        conn,
        _subject_path(storage, slug),
        subject=slug,
        kind=body.kind,
        content=body.content,
        mime=body.mime,
        task_id=body.task_id,
        run_id=body.run_id,
        source_event_id=body.source_event_id,
        workbench_object_id=body.workbench_object_id,
    )


@router.get("/artifacts", operation_id="listRefallRuntimeArtifacts")
def get_runtime_artifacts(slug: str, storage: Annotated[FilesystemStorage, Depends(get_storage)]) -> list[dict]:
    return list_artifacts(connect_runtime(_subject_path(storage, slug)), slug)


@router.get("/observations", operation_id="listRefallRuntimeObservations")
def get_runtime_observations(slug: str, storage: Annotated[FilesystemStorage, Depends(get_storage)]) -> list[dict]:
    return list_observations(connect_runtime(_subject_path(storage, slug)), slug)


@router.get("/evidence-graph", operation_id="getRefallRuntimeEvidenceGraph")
def get_runtime_evidence_graph(slug: str, storage: Annotated[FilesystemStorage, Depends(get_storage)]) -> dict:
    return graph_from_deltas(list_deltas(connect_runtime(_subject_path(storage, slug))))


@router.post("/project", operation_id="projectRefallRuntimeEvents")
def project_runtime(slug: str, storage: Annotated[FilesystemStorage, Depends(get_storage)]) -> dict:
    result = project_runtime_events(connect_runtime(_subject_path(storage, slug)), slug)
    ledger.append_entry(
        storage,
        slug,
        {
            "kind": "runtime-event",
            "subject": slug,
            "event_type": "projection_committed",
            "summary": f"Projected {result['events_projected']} runtime events",
            "projection": result,
        },
    )
    return result


def _publish_manifest_runbook(storage: FilesystemStorage, slug: str, manifest: dict) -> str:
    object_id = manifest.get("workbench_object_id")
    if object_id:
        try:
            storage.put_object_content(slug, str(object_id), _manifest_runbook_bytes(manifest))
            return str(object_id)
        except NotFound:
            pass
    return _create_manifest_runbook(storage, slug, manifest)


def _create_manifest_runbook(storage: FilesystemStorage, slug: str, manifest: dict) -> str:
    now = datetime.now(UTC)
    meta = ObjectMeta(
        id=new_object_id(),
        kind=ObjectKind.runbook,
        title="REFALL Run Manifest",
        drawer="Run Manifest",
        filename="refall-run-manifest.json",
        mime="application/json",
        description="Latest REFALL run manifest for this workbench.",
        created_at=now,
        updated_at=now,
    )
    created = storage.create_object(slug, meta, content=_manifest_runbook_bytes(manifest))
    return created.id


def _manifest_runbook_bytes(manifest: dict) -> bytes:
    return json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")


def _nonfatal_errors(storage: FilesystemStorage, slug: str, *, limit: int) -> list[dict]:
    limit = max(1, min(int(limit), 5000))
    runtime_errors = list_nonfatal_errors(connect_runtime(_subject_path(storage, slug)), slug, limit=limit)
    ledger_errors = _ledger_nonfatal_errors(storage, slug)
    errors = [*runtime_errors, *ledger_errors]
    errors.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return errors[:limit]


def _ledger_nonfatal_errors(storage: FilesystemStorage, slug: str) -> list[dict]:
    rows: list[dict] = []
    for entry in ledger.list_entries(storage, slug):
        if not _ledger_entry_is_nonfatal_error(entry):
            continue
        rows.append({
            "id": entry.get("id"),
            "source": "ledger",
            "type": entry.get("action") or entry.get("event_type") or entry.get("kind"),
            "created_at": entry.get("created_at"),
            "run_id": entry.get("run_id"),
            "task_id": entry.get("task_id"),
            "session_id": entry.get("session_id"),
            "summary": entry.get("summary") or entry.get("title") or entry.get("action") or entry.get("event_type"),
            "failure_class": entry.get("failure_class") or entry.get("status"),
            "refusal_reasons": _reason_list(entry),
            "artifact_refs": entry.get("artifact_refs") or [],
        })
    return rows


def _ledger_entry_is_nonfatal_error(entry: dict) -> bool:
    if entry.get("kind") == "runtime-event" and entry.get("runtime_event_id"):
        return False
    haystack = " ".join(
        str(entry.get(key) or "").lower()
        for key in ("kind", "action", "event_type", "status", "summary")
    )
    markers = (
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
    if any(marker in haystack for marker in markers):
        return True
    return bool(entry.get("failure_class") or entry.get("refusal_reasons") or entry.get("reasons"))


def _reason_list(entry: dict) -> list[str]:
    for key in ("refusal_reasons", "reasons"):
        value = entry.get(key)
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
    return []


def _subject_path(storage: FilesystemStorage, slug: str) -> Path:
    try:
        workbench = storage.get_workbench(slug)
    except Exception as exc:
        raise HTTPException(404, f"workbench not found: {slug}") from exc
    raw = workbench.custom_fields.get("refall_subject_path") or workbench.local_path
    if raw:
        return Path(raw)
    return storage.root / "workbenches" / slug
