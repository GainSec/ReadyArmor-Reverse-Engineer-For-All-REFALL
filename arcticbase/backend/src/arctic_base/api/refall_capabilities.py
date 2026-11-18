from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from arctic_base.config import Settings, get_settings
from arctic_base.api.deps import get_storage
from arctic_base.refall import ledger
from arctic_base.refall.coverage_store import store_for_workbench
from arctic_base.storage.filesystem import FilesystemStorage

router = APIRouter(prefix="/workbenches/{slug}", tags=["refall-capabilities"])


def require_capability_operator(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> str | None:
    """Authenticate capability mutations when a host-only token is configured."""
    token_path = settings.refall_capability_operator_token_path
    if token_path is None:
        return None
    try:
        expected = token_path.read_text().strip()
    except OSError as exc:
        raise HTTPException(503, "capability operator credential unavailable") from exc
    supplied = request.headers.get("X-REFALL-Operator-Token", "")
    if not expected or not secrets.compare_digest(supplied, expected):
        raise HTTPException(403, "valid capability operator credential required")
    return "operator"


class CapabilityGrantReq(BaseModel):
    id: str | None = None
    class_: str = Field(alias="class")
    scope: dict = Field(default_factory=dict)
    granted_by: str | None = None
    reason: str | None = None
    expires_at: float | None = None
    dry_run_required: bool = False
    destructive_token_required: bool = False


class CapabilityRequestReq(BaseModel):
    id: str | None = None
    class_: str = Field(alias="class")
    scope: dict = Field(default_factory=dict)
    requested_by: str | None = None
    reason: str | None = None


@router.get("/capabilities", operation_id="listRefallCapabilities")
def list_capabilities(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
    include_revoked: bool = False,
) -> dict:
    store = store_for_workbench(storage, slug)
    return {
        "subject": slug,
        "grants": store.list_capability_grants(slug, include_revoked=include_revoked),
        "requests": [
            _request_row(item) for item in store.conn.execute(
                "SELECT * FROM capability_requests WHERE subject=? ORDER BY updated_at DESC",
                (slug,),
            )
        ],
    }


@router.post("/capabilities/request", status_code=201, operation_id="requestRefallCapability")
def request_capability(
    slug: str,
    body: CapabilityRequestReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    store = store_for_workbench(storage, slug)
    try:
        request = store.request_capability(slug, {**body.model_dump(by_alias=True), "class": body.class_})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    ledger.append_entry(
        storage,
        slug,
        {
            "kind": "capability-request",
            "subject": slug,
            "status": request["status"],
            "capability_request_id": request["id"],
            "capability_class": request["class"],
            "summary": request.get("reason") or "",
        },
    )
    return request


@router.post("/capabilities/grant", status_code=201, operation_id="grantRefallCapability")
def grant_capability(
    slug: str,
    body: CapabilityGrantReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
    operator_identity: Annotated[str | None, Depends(require_capability_operator)],
) -> dict:
    store = store_for_workbench(storage, slug)
    payload = body.model_dump(by_alias=True)
    payload["class"] = body.class_
    if operator_identity is not None:
        payload["granted_by"] = operator_identity
    try:
        grant = store.grant_capability(slug, payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    ledger.append_entry(
        storage,
        slug,
        {
            "kind": "capability-grant",
            "subject": slug,
            "status": "granted",
            "capability_grant_id": grant["id"],
            "capability_class": grant["class"],
            "summary": grant.get("reason") or "",
        },
    )
    return grant


@router.post("/capabilities/revoke/{grant_id}", operation_id="revokeRefallCapability")
def revoke_capability(
    slug: str,
    grant_id: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
    _operator_identity: Annotated[str | None, Depends(require_capability_operator)],
) -> dict:
    store = store_for_workbench(storage, slug)
    try:
        grant = store.revoke_capability(slug, grant_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    ledger.append_entry(
        storage,
        slug,
        {
            "kind": "capability-grant",
            "subject": slug,
            "status": "revoked",
            "capability_grant_id": grant["id"],
            "capability_class": grant["class"],
        },
    )
    return grant


@router.post("/capabilities/revoke", operation_id="revokeRefallCapabilityCompat")
def revoke_capability_compat(
    slug: str,
    body: Annotated[dict, Body()],
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
    operator_identity: Annotated[str | None, Depends(require_capability_operator)],
) -> dict:
    grant_id = str(body.get("grant_id") or "")
    if not grant_id:
        raise HTTPException(422, "grant_id required")
    return revoke_capability(slug, grant_id, storage, operator_identity)


@router.post("/execution/authorize", operation_id="authorizeRefallExecution")
def authorize_execution(
    slug: str,
    request: Annotated[dict, Body()],
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    result = store_for_workbench(storage, slug).authorize_execution(slug, request)
    ledger.append_entry(
        storage,
        slug,
        {
            "kind": "capability-decision",
            "subject": slug,
            "status": result["status"],
            "capability_class": request.get("capability_class"),
            "grant_id": result.get("grant_id"),
            "summary": "; ".join(result.get("refusal_reasons") or []) or "authorized",
            "request": request,
        },
    )
    return result


def _request_row(row) -> dict:
    import json

    data = dict(row)
    try:
        data["scope"] = json.loads(data.get("scope") or "{}")
    except json.JSONDecodeError:
        data["scope"] = {}
    return data
