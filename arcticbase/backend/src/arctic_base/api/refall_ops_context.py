from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from arctic_base.api.deps import get_storage
from arctic_base.api.refall_ops import require_ops
from arctic_base.config import Settings
from arctic_base.refall import ledger
from arctic_base.refall.coverage_store import store_for_workbench
from arctic_base.storage.errors import NotFound
from arctic_base.storage.filesystem import FilesystemStorage

router = APIRouter(prefix="/refall/ops", tags=["refall-ops-context"])


@router.get("/debug/{subject}", operation_id="getRefallOpsDebug")
def get_debug(
    subject: str,
    settings: Annotated[Settings, Depends(require_ops)],
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    try:
        workbench = storage.get_workbench(subject)
    except NotFound as exc:
        raise HTTPException(404, f"REFALL workbench not found: {subject}") from exc
    store = store_for_workbench(storage, subject)
    return {
        "subject": subject,
        "deployment_mode": settings.refall_deployment_mode,
        "status": "available",
        "workbench": workbench.model_dump(mode="json"),
        "coverage_context": store.get_context(subject) or {"subject": subject, "info_md": None},
        "coverage": store.coverage(subject),
        "coverage_funnel": store.funnel(subject),
        "ledger_stats": ledger.stats(storage, subject),
        "events": ledger.list_entries(storage, subject, kind="ops-event"),
        "audit_tail": _read_jsonl_tail(storage.root / "refall_ops_audit.jsonl"),
        "logs": _discover_logs(storage, subject),
    }


@router.get(
    "/debug/{subject}/conversation/{cid}",
    operation_id="getRefallOpsDebugConversation",
)
def get_debug_conversation(
    subject: str,
    cid: str,
    settings: Annotated[Settings, Depends(require_ops)],
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    del settings
    events_dir = _find_conversation_events(storage, subject, cid)
    if events_dir is None:
        return {
            "subject": subject,
            "conversation_id": cid,
            "events": [],
            "total_events": 0,
            "error": "Conversation events not found",
        }
    events = _parse_conversation_events(events_dir)
    return {
        "subject": subject,
        "conversation_id": cid,
        "phase": events_dir.parent.name.split("-")[0] if "-" in events_dir.parent.name else "unknown",
        "events_path": str(events_dir),
        "events": events,
        "total_events": len(events),
    }


@router.get("/debug/{subject}/live", operation_id="getRefallOpsDebugLive")
def get_debug_live(
    subject: str,
    settings: Annotated[Settings, Depends(require_ops)],
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    del settings
    active = []
    for cid, phase in _active_conversations(storage, subject).items():
        active.append({
            "cid": cid,
            "phase": phase,
            "status": "active",
            "recent_events": _recent_conversation_events(storage, subject, cid, limit=5),
        })
    return {"subject": subject, "live": bool(active), "active": active, "events": active}


def _read_jsonl_tail(path, limit: int = 50) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"raw": line})
    return rows


def _discover_logs(storage: FilesystemStorage, subject: str) -> list[dict]:
    base = storage.root / "workbenches" / subject
    out = []
    for path in sorted(base.glob("**/*.log"))[:100]:
        out.append({"path": str(path.relative_to(base)), "size": path.stat().st_size})
    for root in _subject_roots(storage, subject):
        if root == base or not root.is_dir():
            continue
        for path in sorted((root / "refallsubloop" / "logs").glob("**/*.log"))[:100]:
            out.append({"path": str(path.relative_to(root)), "size": path.stat().st_size})
    return out


def _subject_roots(storage: FilesystemStorage, subject: str) -> list[Path]:
    roots = [storage.root / "workbenches" / subject]
    try:
        workbench = storage.get_workbench(subject)
    except NotFound:
        workbench = None
    if workbench is not None:
        for value in (
            workbench.local_path,
            workbench.custom_fields.get("refall_subject_path"),
        ):
            if value:
                roots.append(Path(value))
    seen: set[str] = set()
    out: list[Path] = []
    for root in roots:
        key = str(root.resolve() if root.exists() else root)
        if key not in seen:
            seen.add(key)
            out.append(root)
    return out


def _agent_log_roots(storage: FilesystemStorage, subject: str) -> list[Path]:
    roots: list[Path] = []
    for root in _subject_roots(storage, subject):
        roots.extend([
            root / "refallsubloop" / "logs" / "agents",
            root / "refall" / "logs" / "agents",
            root / ".refall" / "conversations",
        ])
    # `conversations` is the live Agent Canvas store (dev_conversations only
    # exists in dev mode); both are searched so a conversation stays inspectable
    # while it is running, and from the subject-side archive after it is reaped.
    roots.append(Path.home() / ".openhands" / "agent-canvas" / "conversations")
    roots.append(Path.home() / ".openhands" / "agent-canvas" / "dev_conversations")
    return roots


def _event_log_paths(storage: FilesystemStorage, subject: str) -> list[Path]:
    paths: list[Path] = []
    for root in _subject_roots(storage, subject):
        paths.extend([
            root / "refallsubloop" / "logs" / "events" / "events.jsonl",
            root / "refall" / "logs" / "events" / "events.jsonl",
        ])
    return paths


def _find_conversation_events(storage: FilesystemStorage, subject: str, cid: str) -> Path | None:
    cid_key = cid.replace("-", "")
    for root in _agent_log_roots(storage, subject):
        if not root.is_dir():
            continue
        candidates = [root / cid, root / cid_key]
        candidates.extend(path for path in root.iterdir() if path.is_dir())
        for candidate in candidates:
            name_key = candidate.name.replace("-", "")
            if cid_key[:12] not in name_key and name_key not in cid_key:
                continue
            events = candidate / "events"
            if events.is_dir():
                return events
    return None


def _active_conversations(storage: FilesystemStorage, subject: str) -> dict[str, str]:
    state_rows = _active_from_loop_state(storage, subject)
    if state_rows is not None:
        return state_rows
    started: dict[str, str] = {}
    completed: set[str] = set()
    for path in _event_log_paths(storage, subject):
        if not path.is_file():
            continue
        for entry in _read_jsonl_tail(path, limit=1000):
            event_type = str(entry.get("type") or entry.get("kind") or "")
            cid = str(entry.get("cid") or entry.get("conversation_id") or "")
            if not cid:
                continue
            if event_type in {"agent_start", "conversation_start", "conversation_started"}:
                started[cid] = str(entry.get("phase") or entry.get("lane") or "unknown")
            elif event_type in {"agent_complete", "conversation_complete", "conversation_finished"}:
                completed.add(cid)
    return {cid: phase for cid, phase in started.items() if cid not in completed}


def _active_from_loop_state(storage: FilesystemStorage, subject: str) -> dict[str, str] | None:
    for root in _subject_roots(storage, subject):
        state_path = root / ".refall" / "loop_state.json"
        if not state_path.is_file():
            continue
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        active: dict[str, str] = {}
        for item in state.get("active") or []:
            if not isinstance(item, dict) or not item.get("cid"):
                continue
            active[str(item["cid"])] = str(item.get("task_class") or item.get("lane") or "unknown")
        return active
    return None


def _recent_conversation_events(
    storage: FilesystemStorage,
    subject: str,
    cid: str,
    *,
    limit: int,
) -> list[dict]:
    events_dir = _find_conversation_events(storage, subject, cid)
    if events_dir is None:
        return []
    return _parse_conversation_events(events_dir)[-limit:]


def _parse_conversation_events(events_dir: Path) -> list[dict]:
    timeline: list[dict] = []
    for event_file in sorted(events_dir.glob("*.json")):
        try:
            event = json.loads(event_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        kind = str(event.get("kind") or "")
        if kind == "ACPToolCallEvent":
            raw_output = _event_output(event)
            timeline.append({
                "kind": "tool_call",
                "timestamp": event.get("timestamp", ""),
                "title": event.get("title", ""),
                "tool_kind": event.get("tool_kind", ""),
                "status": event.get("status", ""),
                "output": raw_output[:2000],
                "output_lines": raw_output.count("\n") + 1 if raw_output else 0,
                "output_full_length": len(raw_output),
            })
        elif kind == "MessageEvent":
            content = _event_text(event.get("content"))
            if content.strip():
                timeline.append({
                    "kind": "message",
                    "timestamp": event.get("timestamp", ""),
                    "source": event.get("source", ""),
                    "content": content[:3000],
                })
        else:
            timeline.append({
                "kind": kind or "event",
                "timestamp": event.get("timestamp", ""),
                "title": event.get("title", ""),
                "status": event.get("status", ""),
            })
    return timeline


def _event_output(event: dict) -> str:
    raw = event.get("raw_output")
    if raw:
        return str(raw)
    return _event_text(event.get("content"))


def _event_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("text"), str):
                parts.append(item["text"])
            inner = item.get("content")
            if isinstance(inner, dict) and isinstance(inner.get("text"), str):
                parts.append(inner["text"])
            elif isinstance(inner, str):
                parts.append(inner)
        return " ".join(parts)
    return "" if content is None else str(content)
