from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from arctic_base.config import Settings
from arctic_base.models import WorkbenchMeta
from arctic_base.storage.errors import AlreadyExists, NotFound
from arctic_base.storage.filesystem import FilesystemStorage


SUBJECT_DIRECTORIES = (
    "Notes",
    "Screenshots",
    "Exports-Downloads",
    "Exports-Downloads/firmware/extracted",
    "Import-Templates",
    "Import-Templates/external-docs",
    "Payloads",
    "PRJ",
    "Errors",
    "Output",
    "Report",
    "refallsubloop/services",
    "refallsubloop/mcp-servers",
    "refallsubloop/tools",
    "refallsubloop/config",
    "refallsubloop/logs/agents",
    "refallsubloop/logs/trajectories",
    "refallsubloop/logs/events",
    "refallsubloop/logs/loop",
    "refallsubloop/logs/infra",
    ".refall/conversations",
)


@dataclass(frozen=True)
class SubjectBootstrap:
    subject: str
    workbench_slug: str
    subject_path: Path
    created: bool


def slugify_subject(value: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in value.strip())
    while "--" in out:
        out = out.replace("--", "-")
    out = out.strip("-")
    return out[:64] or "subject"


def bootstrap_subject(
    *,
    settings: Settings,
    storage: FilesystemStorage,
    subject: str,
    title: str | None = None,
    description: str = "",
    source_path: str | None = None,
    tags: list[str] | None = None,
) -> SubjectBootstrap:
    slug = slugify_subject(subject)
    subject_root = settings.refall_subject_root
    if subject_root is None:
        subject_root = settings.refall_data_root / "subjects"
    subject_path = (subject_root / slug).resolve()

    created_path = not subject_path.exists()
    _create_subject_layout(
        subject_path=subject_path,
        subject=slug,
        title=title or subject,
        description=description,
        source_path=source_path,
        tags=tags or [],
        workbench_slug=slug,
    )
    created_workbench = _create_or_update_workbench(
        storage=storage,
        slug=slug,
        title=title or subject,
        description=description,
        subject_path=subject_path,
        source_path=source_path,
        tags=tags or [],
    )
    return SubjectBootstrap(
        subject=slug,
        workbench_slug=slug,
        subject_path=subject_path,
        created=created_path or created_workbench,
    )


def _create_subject_layout(
    *,
    subject_path: Path,
    subject: str,
    title: str,
    description: str,
    source_path: str | None,
    tags: list[str],
    workbench_slug: str,
) -> None:
    for rel in SUBJECT_DIRECTORIES:
        (subject_path / rel).mkdir(parents=True, exist_ok=True)

    refall_dir = subject_path / ".refall"
    refall_dir.mkdir(parents=True, exist_ok=True)
    state_path = refall_dir / "subject_state.json"
    ledger_path = refall_dir / "evidence_ledger.json"
    now = datetime.now(UTC).isoformat()

    if not state_path.exists():
        state = {
            "version": 1,
            "subject": subject,
            "title": title,
            "description": description,
            "source_path": source_path,
            "tags": tags,
            "workbench_slug": workbench_slug,
            "status": "created",
            "created_at": now,
            "updated_at": now,
        }
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    if not ledger_path.exists():
        ledger = {"version": 1, "subject": subject, "entries": []}
        ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")


def _create_or_update_workbench(
    *,
    storage: FilesystemStorage,
    slug: str,
    title: str,
    description: str,
    subject_path: Path,
    source_path: str | None,
    tags: list[str],
) -> bool:
    now = datetime.now(UTC)
    merged_tags = _merge_tags(["refall", "subject"], tags)
    custom_fields = {
        "refall_subject": slug,
        "refall_subject_path": str(subject_path),
        "refall_layout": "qedcs-refall-v1",
    }
    if source_path:
        custom_fields["refall_source_path"] = source_path

    meta = WorkbenchMeta(
        slug=slug,
        title=title,
        description=description,
        local_path=str(subject_path),
        tags=merged_tags,
        custom_fields=custom_fields,
        created_at=now,
        updated_at=now,
    )

    try:
        storage.create_workbench(meta)
    except AlreadyExists:
        try:
            current = storage.get_workbench(slug)
        except NotFound:
            raise
        patch = {
            "local_path": str(subject_path),
            "tags": _merge_tags(current.tags, merged_tags),
            "custom_fields": {**current.custom_fields, **custom_fields},
        }
        if description and not current.description:
            patch["description"] = description
        storage.update_workbench(slug, patch)
        return False
    return True


def _merge_tags(*groups: list[str]) -> list[str]:
    out: list[str] = []
    for group in groups:
        for tag in group:
            if tag not in out:
                out.append(tag)
    return out
