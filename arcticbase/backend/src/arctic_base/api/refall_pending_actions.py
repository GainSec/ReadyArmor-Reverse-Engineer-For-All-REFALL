from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from arctic_base.api.deps import get_storage
from arctic_base.refall import ledger
from arctic_base.refall.coverage_store import store_for_workbench
from arctic_base.storage.filesystem import FilesystemStorage

router = APIRouter(prefix="/workbenches/{slug}/pending-actions", tags=["refall-pending-actions"])


class PendingActionReq(BaseModel):
    id: str | None = None
    kind: str
    title: str
    description: str | None = None
    priority: str = "medium"
    status: str = "open"
    source_event_id: str | None = None
    source_finding_id: str | None = None
    source_unit_id: str | None = None
    required_receipt_type: str | None = None
    assigned_lane: str | None = None
    created_by: str | None = None


class ClaimReq(BaseModel):
    claimed_by: str = "refall-manager"
    lease_s: int = 900


class ResolveReq(BaseModel):
    resolved_by: str | None = None
    receipt_type: str | None = None
    receipt: dict = Field(default_factory=dict)


@router.get("", operation_id="listRefallPendingActions")
def list_pending_actions(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
    status: str | None = None,
    kind: str | None = None,
    include_terminal: bool = True,
) -> list[dict]:
    return store_for_workbench(storage, slug).list_pending_actions(
        slug,
        status=status,
        kind=kind,
        include_terminal=include_terminal,
    )


@router.post("", status_code=201, operation_id="createRefallPendingAction")
def create_pending_action(
    slug: str,
    body: PendingActionReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    store = store_for_workbench(storage, slug)
    try:
        action = store.create_pending_action(slug, body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
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
    return action


@router.post("/{action_id}/claim", operation_id="claimRefallPendingAction")
def claim_pending_action(
    slug: str,
    action_id: str,
    body: ClaimReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    try:
        action = store_for_workbench(storage, slug).claim_pending_action(
            slug,
            action_id,
            body.claimed_by,
            body.lease_s,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    ledger.append_entry(
        storage,
        slug,
        {
            "kind": "pending-action",
            "subject": slug,
            "action": "pending.claim",
            "status": action["status"],
            "pending_action_id": action["id"],
            "summary": action["title"],
        },
    )
    return action


@router.post("/{action_id}/resolve", operation_id="resolveRefallPendingAction")
def resolve_pending_action(
    slug: str,
    action_id: str,
    body: ResolveReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    return _finish(slug, action_id, "done", body, storage)


@router.post("/{action_id}/defer", operation_id="deferRefallPendingAction")
def defer_pending_action(
    slug: str,
    action_id: str,
    body: ResolveReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    return _finish(slug, action_id, "deferred", body, storage)


@router.post("/{action_id}/cancel", operation_id="cancelRefallPendingAction")
def cancel_pending_action(
    slug: str,
    action_id: str,
    body: ResolveReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    return _finish(slug, action_id, "cancelled", body, storage)


def _finish(
    slug: str,
    action_id: str,
    status: str,
    body: ResolveReq,
    storage: FilesystemStorage,
) -> dict:
    store = store_for_workbench(storage, slug)
    try:
        action = store.finish_pending_action(
            slug,
            action_id,
            status=status,
            receipt_type=body.receipt_type,
            receipt=body.receipt,
            resolved_by=body.resolved_by,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    ledger.append_entry(
        storage,
        slug,
        {
            "kind": "pending-action",
            "subject": slug,
            "action": f"pending.{status}",
            "status": action["status"],
            "pending_action_id": action["id"],
            "receipt_type": body.receipt_type,
            "summary": action["title"],
        },
    )
    return action
