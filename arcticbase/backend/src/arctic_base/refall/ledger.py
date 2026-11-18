from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arctic_base.storage.filesystem import FilesystemStorage


LEDGER_KINDS = {
    "fact",
    "lead",
    "finding",
    "observation",
    "hypothesis",
    "remediation",
    "attack-chain",
    "ask",
    "coverage",
    "validation",
    "artifact",
    "ops-event",
    "disposition-transition",
    "pending-action",
    "capability-grant",
    "capability-request",
    "capability-decision",
    "runtime-event",
    "closeout-gate",
}


def ledger_path(storage: FilesystemStorage, slug: str) -> Path:
    storage.get_workbench(slug)
    return storage.root / "workbenches" / slug / "refall_ledger.jsonl"


def append_entry(storage: FilesystemStorage, slug: str, entry: dict[str, Any]) -> dict[str, Any]:
    path = ledger_path(storage, slug)
    now = datetime.now(UTC).isoformat()
    data = dict(entry)
    data.setdefault("kind", "fact")
    if data["kind"] not in LEDGER_KINDS:
        raise ValueError(f"unsupported ledger kind: {data['kind']}")
    data.setdefault("id", f"led_{uuid.uuid4().hex}")
    data.setdefault("workbench_slug", slug)
    data.setdefault("created_at", now)
    data["updated_at"] = now

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(data, sort_keys=True) + "\n")
    storage.audit(slug, "refall.ledger.append", id=data["id"], kind=data["kind"])
    return data


def list_entries(
    storage: FilesystemStorage,
    slug: str,
    *,
    kind: str | None = None,
    lane: str | None = None,
    severity: str | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    entries = _read_entries(ledger_path(storage, slug))
    out: list[dict[str, Any]] = []
    for entry in entries:
        if kind and entry.get("kind") != kind:
            continue
        if lane and entry.get("lane") != lane:
            continue
        if severity and entry.get("severity") != severity:
            continue
        if since and str(entry.get("created_at", "")) < since:
            continue
        out.append(entry)
    return out


def get_entry(storage: FilesystemStorage, slug: str, entry_id: str) -> dict[str, Any] | None:
    for entry in _read_entries(ledger_path(storage, slug)):
        if entry.get("id") == entry_id:
            return entry
    return None


def stats(storage: FilesystemStorage, slug: str) -> dict[str, Any]:
    entries = _read_entries(ledger_path(storage, slug))
    by_kind = Counter(str(entry.get("kind")) for entry in entries if entry.get("kind"))
    by_lane = Counter(str(entry.get("lane")) for entry in entries if entry.get("lane"))
    by_severity = Counter(str(entry.get("severity")) for entry in entries if entry.get("severity"))
    return {
        "workbench_slug": slug,
        "total": len(entries),
        "by_kind": dict(by_kind),
        "by_lane": dict(by_lane),
        "by_severity": dict(by_severity),
    }


def _read_entries(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        out.append(json.loads(line))
    return out
