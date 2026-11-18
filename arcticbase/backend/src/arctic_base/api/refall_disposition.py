from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from arctic_base.api.deps import get_storage
from arctic_base.refall import ledger
from arctic_base.refall.coverage_store import store_for_workbench
from arctic_base.storage.filesystem import FilesystemStorage

router = APIRouter(prefix="/workbenches/{slug}", tags=["refall-disposition"])


class TransitionReq(BaseModel):
    from_status: str | None = None
    to_status: str | None = None
    from_quality: str | None = None
    to_quality: str | None = None
    proposed_by: str | None = None
    reason: str = ""
    receipt_type: str | None = None
    receipt: dict = Field(default_factory=dict)
    duplicate_of: str | None = None
    severity_reduction: bool = False


@router.post("/findings/{finding_id}/transitions", operation_id="transitionRefallFinding")
def transition_finding(
    slug: str,
    finding_id: str,
    body: TransitionReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    store = store_for_workbench(storage, slug)
    payload = body.model_dump()
    source_root = _source_root_for_transition(storage, slug)
    if source_root:
        payload["_source_root"] = str(source_root)
    try:
        result = store.transition_finding(slug, finding_id, payload)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    ledger.append_entry(
        storage,
        slug,
        {
            "kind": "disposition-transition",
            "subject": slug,
            "finding_id": finding_id,
            "transition_id": result["id"],
            "status": result["status"],
            "summary": body.reason,
            "receipt_type": body.receipt_type,
            "refusal_reasons": result.get("refusal_reasons", []),
        },
    )
    for action in store.trigger_pending_actions_for_transition(slug, result):
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
    return result


@router.get("/findings/{finding_id}/transitions", operation_id="listRefallFindingTransitions")
def list_finding_transitions(
    slug: str,
    finding_id: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> list[dict]:
    return store_for_workbench(storage, slug).list_transitions(slug, finding_id=finding_id)


@router.get("/disposition/refusals", operation_id="listRefallDispositionRefusals")
def list_disposition_refusals(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> list[dict]:
    return store_for_workbench(storage, slug).list_transitions(slug, status="refused")


def _source_root_for_transition(storage: FilesystemStorage, slug: str) -> Path | None:
    try:
        workbench = storage.get_workbench(slug)
    except Exception:
        return None
    custom = workbench.custom_fields or {}
    raw_source = custom.get("refall_source_path")
    if raw_source:
        return Path(str(raw_source)).expanduser()
    raw_subject = custom.get("refall_subject_path")
    if raw_subject:
        prj = Path(str(raw_subject)).expanduser() / "PRJ"
        if prj.exists():
            return prj
        return Path(str(raw_subject)).expanduser()
    if workbench.local_path:
        return Path(str(workbench.local_path)).expanduser()
    return None
