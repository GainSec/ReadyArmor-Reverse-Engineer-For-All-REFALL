from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException

from arctic_base.api.deps import get_storage
from arctic_base.refall import ledger
from arctic_base.storage.filesystem import FilesystemStorage

router = APIRouter(prefix="/workbenches/{slug}/ledger", tags=["refall-ledger"])


@router.post("/entries", status_code=201, operation_id="appendRefallLedgerEntry")
def append_ledger_entry(
    slug: str,
    entry: Annotated[dict[str, Any], Body()],
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict[str, Any]:
    try:
        return ledger.append_entry(storage, slug, entry)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/entries", operation_id="listRefallLedgerEntries")
def list_ledger_entries(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
    kind: str | None = None,
    lane: str | None = None,
    severity: str | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    return ledger.list_entries(storage, slug, kind=kind, lane=lane, severity=severity, since=since)


@router.get("/entries/{entry_id}", operation_id="getRefallLedgerEntry")
def get_ledger_entry(
    slug: str,
    entry_id: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict[str, Any]:
    entry = ledger.get_entry(storage, slug, entry_id)
    if entry is None:
        raise HTTPException(404, "not found")
    return entry


@router.get("/stats", operation_id="getRefallLedgerStats")
def ledger_stats(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict[str, Any]:
    return ledger.stats(storage, slug)
