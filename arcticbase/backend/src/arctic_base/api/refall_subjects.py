from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from arctic_base.api.deps import get_storage
from arctic_base.config import get_settings
from arctic_base.models import ObjectKind, ObjectMeta
from arctic_base.refall.subjects import bootstrap_subject
from arctic_base.storage.filesystem import FilesystemStorage, new_object_id

router = APIRouter(prefix="/refall/subjects", tags=["refall-subjects"])


class SubjectCreate(BaseModel):
    subject: str
    title: str | None = None
    description: str = ""
    source_path: str | None = None
    tags: list[str] = Field(default_factory=list)


class SubjectCreateResponse(BaseModel):
    subject: str
    workbench_slug: str
    subject_path: str
    created: bool


class MirrorResponse(BaseModel):
    workbench_slug: str
    object_id: str


@router.post("", response_model=SubjectCreateResponse, status_code=201, operation_id="createRefallSubject")
def create_subject(
    body: SubjectCreate,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> SubjectCreateResponse:
    result = bootstrap_subject(
        settings=get_settings(),
        storage=storage,
        subject=body.subject,
        title=body.title,
        description=body.description,
        source_path=body.source_path,
        tags=body.tags,
    )
    return SubjectCreateResponse(
        subject=result.subject,
        workbench_slug=result.workbench_slug,
        subject_path=str(result.subject_path),
        created=result.created,
    )


@router.post(
    "/{slug}/mirror-workbench",
    response_model=MirrorResponse,
    status_code=201,
    operation_id="mirrorRefallSubjectWorkbench",
)
def mirror_workbench(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> MirrorResponse:
    workbench = storage.get_workbench(slug)
    content = {
        "version": 1,
        "subject": workbench.custom_fields.get("refall_subject", slug),
        "workbench_slug": workbench.slug,
        "subject_path": workbench.custom_fields.get("refall_subject_path", workbench.local_path),
        "source_path": workbench.custom_fields.get("refall_source_path"),
        "tags": workbench.tags,
        "mirrored_at": datetime.now(UTC).isoformat(),
    }
    meta = ObjectMeta(
        id=new_object_id(),
        kind=ObjectKind.md,
        title="REFALL Subject Manifest",
        description="Explicit REFALL subject metadata mirror.",
        drawer="Subject",
        filename="REFALL-SUBJECT-MANIFEST.md",
        mime="text/markdown",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    markdown = "# REFALL Subject Manifest\n\n```json\n"
    markdown += json.dumps(content, indent=2)
    markdown += "\n```\n"
    created = storage.create_object(workbench.slug, meta, content=markdown.encode("utf-8"))
    return MirrorResponse(workbench_slug=workbench.slug, object_id=created.id)
