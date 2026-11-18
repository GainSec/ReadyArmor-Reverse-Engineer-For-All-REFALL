from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from arctic_base.api.deps import get_storage
from arctic_base.config import Settings, get_settings
from arctic_base.storage.filesystem import FilesystemStorage

router = APIRouter(prefix="/refall/ops", tags=["refall-ops"])


def require_ops() -> Settings:
    settings = get_settings()
    if not settings.refall_enable_ops:
        raise HTTPException(404, "REFALL ops disabled")
    return settings


def infra_checks() -> list[dict]:
    checks = []
    for tool in ("python", "uv", "node", "pnpm", "docker", "colima", "tmux"):
        checks.append({
            "id": tool,
            "status": "available" if shutil.which(tool) else "unsupported",
        })
    return checks


def status_payload(settings: Settings) -> dict:
    return {
        "enabled": True,
        "commands_enabled": settings.refall_enable_ops_commands,
        "deployment_mode": settings.refall_deployment_mode,
        "public_base_url": settings.refall_public_base_url,
        "openhands_base": settings.refall_openhands_base,
        "head_provider": settings.refall_head_provider,
        "allowed_head_providers": [
            item.strip()
            for item in settings.refall_allowed_head_providers.split(",")
            if item.strip()
        ],
        "loop_launch_enabled": settings.refall_enable_loop_launch,
        "loop": {
            "repo_root": str(settings.refall_repo_root),
            "max_parallel": settings.refall_loop_max_parallel,
            "poll_interval_s": settings.refall_loop_poll_interval_s,
            "report_interval_cycles": settings.refall_loop_report_interval_cycles,
            "stall_cycles": settings.refall_loop_stall_cycles,
        },
    }


@router.get("/status", operation_id="getRefallOpsStatus")
def get_status(settings: Annotated[Settings, Depends(require_ops)]) -> dict:
    return status_payload(settings)


@router.get("/agents", operation_id="getRefallOpsAgents")
def get_agents(
    settings: Annotated[Settings, Depends(require_ops)],
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    providers = [
        item.strip()
        for item in settings.refall_allowed_head_providers.split(",")
        if item.strip()
    ]
    return {
        "head_agent": settings.refall_head_agent_name,
        "head_provider": settings.refall_head_provider,
        "providers": providers,
        "loop_launch_enabled": settings.refall_enable_loop_launch,
        "active": active_refall_agents(storage),
    }


@router.get("/infra", operation_id="getRefallOpsInfra")
def get_infra(settings: Annotated[Settings, Depends(require_ops)]) -> dict:
    return {
        "deployment_mode": settings.refall_deployment_mode,
        "checks": infra_checks(),
    }


@router.get("/subjects", operation_id="getRefallOpsSubjects")
def get_subjects(
    settings: Annotated[Settings, Depends(require_ops)],
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    del settings
    subjects = []
    for workbench in storage.list_workbenches():
        if "refall" in workbench.tags or workbench.custom_fields.get("refall_subject"):
            subjects.append({
                "slug": workbench.slug,
                "title": workbench.title,
                "local_path": workbench.local_path,
                "subject": workbench.custom_fields.get("refall_subject", workbench.slug),
            })
    return {"subjects": subjects}


def active_refall_agents(storage: FilesystemStorage) -> list[dict]:
    active: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for workbench in storage.list_workbenches():
        if "refall" not in workbench.tags and not workbench.custom_fields.get("refall_subject"):
            continue
        subject = str(workbench.custom_fields.get("refall_subject") or workbench.slug)
        for root in _subject_roots(workbench):
            loop_state_present = (root / ".refall" / "loop_state.json").is_file()
            loop_state_rows = _active_from_loop_state(root, workbench.slug, subject)
            for row in loop_state_rows:
                key = (row["workbench"], row["cid"])
                if key not in seen:
                    active.append(row)
                    seen.add(key)
            if loop_state_present:
                continue
            for row in _active_from_event_log(root, workbench.slug, subject):
                key = (row["workbench"], row["cid"])
                if key not in seen:
                    active.append(row)
                    seen.add(key)
    return sorted(active, key=lambda item: (item["workbench"], item["cid"]))


def _subject_roots(workbench) -> list[Path]:
    roots: list[Path] = []
    for raw in (
        workbench.local_path,
        workbench.custom_fields.get("refall_subject_path"),
    ):
        if raw:
            roots.append(Path(str(raw)).expanduser())
    seen: set[str] = set()
    out: list[Path] = []
    for root in roots:
        key = str(root.resolve() if root.exists() else root)
        if key not in seen:
            out.append(root)
            seen.add(key)
    return out


def _active_from_loop_state(root: Path, workbench: str, subject: str) -> list[dict]:
    state_path = root / ".refall" / "loop_state.json"
    if not state_path.is_file():
        return []
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = []
    for item in state.get("active") or []:
        if not isinstance(item, dict) or not item.get("cid"):
            continue
        unit = item.get("unit") if isinstance(item.get("unit"), dict) else {}
        rows.append({
            "workbench": workbench,
            "subject": item.get("subject") or subject,
            "cid": str(item["cid"]),
            "phase": item.get("task_class") or "unknown",
            "lane": item.get("lane") or "unknown",
            "status": state.get("status") or "active",
            "iteration": state.get("iteration"),
            "unit_id": unit.get("id"),
            "path": unit.get("path") or unit.get("name"),
            "source": "loop_state",
        })
    return rows


def _active_from_event_log(root: Path, workbench: str, subject: str) -> list[dict]:
    path = root / "refallsubloop" / "logs" / "events" / "events.jsonl"
    if not path.is_file():
        return []
    started: dict[str, dict] = {}
    completed: set[str] = set()
    for entry in _read_jsonl_tail(path, 1000):
        event_type = str(entry.get("type") or entry.get("kind") or "")
        cid = str(entry.get("cid") or entry.get("conversation_id") or "")
        if not cid:
            continue
        if event_type in {"agent_start", "conversation_start", "conversation_started"}:
            started[cid] = {
                "workbench": workbench,
                "subject": subject,
                "cid": cid,
                "phase": entry.get("phase") or "unknown",
                "lane": entry.get("lane") or "unknown",
                "status": "active",
                "unit_id": entry.get("unit_id"),
                "source": "events",
            }
        elif event_type in {"agent_complete", "conversation_complete", "conversation_finished"}:
            completed.add(cid)
    return [row for cid, row in started.items() if cid not in completed]


def _read_jsonl_tail(path: Path, limit: int) -> list[dict]:
    rows = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:
        return rows
    for line in lines:
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows
