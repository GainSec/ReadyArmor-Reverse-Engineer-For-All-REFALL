from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from arctic_base.api.deps import get_storage
from arctic_base.storage.filesystem import FilesystemStorage

router = APIRouter(tags=["refall-reports"])

REPORT_ROOT = Path(__file__).resolve().parents[1] / "refall_report"
SPEC_DIR = REPORT_ROOT / "spec"
TEMPLATE_PATH = REPORT_ROOT / "template.html"


@router.get("/refall/reports/spec-index", operation_id="getRefallReportSpecIndex")
def spec_index() -> dict:
    files = sorted(path.name for path in SPEC_DIR.glob("*.md") if path.is_file())
    return {"files": files}


@router.get("/refall/reports/spec", response_class=PlainTextResponse, operation_id="getRefallReportSpec")
def spec_bundle() -> str:
    parts = []
    for filename in spec_index()["files"]:
        parts.append(f"<!-- {filename} -->\n")
        parts.append((SPEC_DIR / filename).read_text(encoding="utf-8"))
        parts.append("\n")
    return "\n".join(parts)


@router.get(
    "/refall/reports/spec/{filename}",
    response_class=PlainTextResponse,
    operation_id="getRefallReportSpecFile",
)
def spec_file(filename: str) -> str:
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(404, "not found")
    path = SPEC_DIR / filename
    if not path.is_file() or path.suffix != ".md":
        raise HTTPException(404, "not found")
    return path.read_text(encoding="utf-8")


@router.get(
    "/refall/reports/template",
    response_class=PlainTextResponse,
    operation_id="getRefallReportTemplate",
)
def report_template() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


@router.get("/workbenches/{slug}/refall-report", operation_id="getCurrentRefallReport")
def current_report(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    workbench = storage.get_workbench(slug)
    object_id = workbench.custom_fields.get("refall_current_report_object_id")
    if not object_id:
        raise HTTPException(404, "current report object not set")
    meta = storage.get_object(slug, object_id)
    content, etag = storage.get_object_content(slug, object_id)
    return {
        "workbench_slug": slug,
        "object_id": object_id,
        "title": meta.title,
        "mime": meta.mime,
        "etag": etag,
        "content": content.decode("utf-8", errors="replace"),
    }
