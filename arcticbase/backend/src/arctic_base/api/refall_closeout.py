from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from arctic_base.api.deps import get_storage
from arctic_base.refall import ledger
from arctic_base.refall.closeout_gate import evaluate_closeout_gate
from arctic_base.storage.filesystem import FilesystemStorage

router = APIRouter(prefix="/workbenches/{slug}/closeout", tags=["refall-closeout"])


class CloseoutOverrideReq(BaseModel):
    operator: str
    reason: str
    check_ids: list[str] = Field(default_factory=list)
    receipt: dict = Field(default_factory=dict)


@router.get("/gate", operation_id="getRefallCloseoutGate")
def get_closeout_gate(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
    threshold: float = 0.95,
) -> dict:
    return evaluate_closeout_gate(storage, slug, threshold=threshold)


@router.post("/override", operation_id="overrideRefallCloseoutGate")
def override_closeout_gate(
    slug: str,
    body: Annotated[CloseoutOverrideReq, Body()],
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    if not body.receipt or not body.check_ids:
        raise HTTPException(422, "closeout override requires check_ids and receipt")
    entry = ledger.append_entry(
        storage,
        slug,
        {
            "kind": "ops-event",
            "subject": slug,
            "action": "closeout.override",
            "status": "accepted",
            "created_by": body.operator,
            "summary": body.reason,
            "check_ids": body.check_ids,
            "receipt": body.receipt,
        },
    )
    return {"status": "accepted", "ledger_id": entry["id"], "check_ids": body.check_ids}
