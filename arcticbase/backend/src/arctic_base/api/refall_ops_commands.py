from __future__ import annotations

import html
import json
import re as _re
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from arctic_base.api.deps import get_storage
from arctic_base.api.refall_ops import active_refall_agents, infra_checks, require_ops, status_payload
from arctic_base.api.refall_ops_sse import record_event
from arctic_base.config import Settings
from arctic_base.models import ObjectKind, ObjectMeta
from arctic_base.refall.closeout_gate import evaluate_closeout_gate
from arctic_base.refall import ledger
from arctic_base.refall.coverage_store import store_for_workbench
from arctic_base.refall.subjects import bootstrap_subject
from arctic_base.storage.errors import NotFound
from arctic_base.storage.filesystem import FilesystemStorage
from arctic_base.storage.filesystem import new_object_id
from ref_all_executor.agent_workspace import AgentWorkspaceError, sync_agent_canvas_workspace

router = APIRouter(prefix="/refall/ops", tags=["refall-ops-commands"])

KNOWN_COMMANDS = {
    "status",
    "subjects",
    "agents",
    "infra",
    "start",
    "update",
    "closeout",
    "context",
    "coverage",
    "threat-model",
    "doctor",
    "estimate",
    "logs",
}

MAX_CONTEXT_FILE_READ = 8000
MAX_CONTEXT_MATERIALS = 50000
MAX_CONTEXT_OBJECT_READ = 3000
MAX_CONTEXT_OBJECTS = 10
READABLE_CONTEXT_EXTENSIONS = {
    ".bash",
    ".c",
    ".cfg",
    ".conf",
    ".cpp",
    ".css",
    ".csv",
    ".dockerfile",
    ".env",
    ".go",
    ".h",
    ".hcl",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".md",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".toml",
    ".ts",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
    ".zsh",
}
READABLE_CONTEXT_NAMES = {"dockerfile", "makefile"}
SKIP_CONTEXT_NAMES = {
    ".DS_Store",
    ".git",
    "__pycache__",
    "node_modules",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "uv.lock",
    "Thumbs.db",
}


class CommandReq(BaseModel):
    command: str


class GenerateContextReq(BaseModel):
    slug: str
    operator_input: str = ""


class SaveContextReq(BaseModel):
    slug: str
    context: str


def require_ops_commands() -> Settings:
    settings = require_ops()
    if not settings.refall_enable_ops_commands:
        raise HTTPException(403, "REFALL ops commands disabled")
    return settings


@router.post("/command", operation_id="runRefallOpsCommand")
def run_command(
    body: Annotated[CommandReq, Body()],
    settings: Annotated[Settings, Depends(require_ops_commands)],
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    parts = body.command.strip().split()
    if not parts:
        raise HTTPException(422, "command required")
    name = parts[0]
    args = parts[1:]
    if name not in KNOWN_COMMANDS:
        _audit(storage, name, args, "rejected-unknown")
        raise HTTPException(422, f"unknown REFALL ops command: {name}")

    allowed = {item.strip() for item in settings.refall_ops_allowed_commands.split(",") if item.strip()}
    if name not in allowed:
        _audit(storage, name, args, "rejected-disallowed")
        raise HTTPException(403, f"REFALL ops command not allowed: {name}")

    payload = _execute_named_command(name, args, settings, storage)
    _audit(storage, name, args, "accepted")
    return payload


@router.post("/context/generate", operation_id="generateRefallContext")
def generate_context(
    body: Annotated[GenerateContextReq, Body()],
    settings: Annotated[Settings, Depends(require_ops_commands)],
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    return _context_subject(body.slug.strip(), settings, storage, body.operator_input)


@router.post("/context/save", operation_id="saveRefallContext")
def save_context(
    body: Annotated[SaveContextReq, Body()],
    settings: Annotated[Settings, Depends(require_ops_commands)],
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    del settings
    slug = body.slug.strip()
    if not slug:
        raise HTTPException(422, "slug required")
    workbench = storage.get_workbench(slug)
    context, object_result = _save_context_artifacts(
        storage=storage,
        slug=slug,
        info_md=_normalized_markdown(body.context),
        generated_by="operator",
        root_container=_coverage_root_container(workbench.model_dump(mode="json")),
    )
    entry = _append_ops_event(
        storage,
        slug,
        action="context.save",
        summary="REFALL context.md saved by operator",
        status="ok",
        object=object_result,
    )
    return {
        "status": "ok",
        "command": "context.save",
        "subject": slug,
        "context": context,
        "object": object_result,
        "ledger_id": entry["id"],
    }


def _execute_named_command(
    name: str,
    args: list[str],
    settings: Settings,
    storage: FilesystemStorage,
) -> dict:
    if name == "status":
        return {"status": "ok", "command": name, "result": status_payload(settings)}
    if name == "subjects":
        subjects = []
        for workbench in storage.list_workbenches():
            if "refall" in workbench.tags or workbench.custom_fields.get("refall_subject"):
                subjects.append({"slug": workbench.slug, "title": workbench.title})
        return {"status": "ok", "command": name, "subjects": subjects}
    if name == "agents":
        return {
            "status": "ok",
            "command": name,
            "head_agent": settings.refall_head_agent_name,
            "head_provider": settings.refall_head_provider,
            "loop_launch_enabled": settings.refall_enable_loop_launch,
            "active": active_refall_agents(storage),
        }
    if name == "infra":
        return {"status": "ok", "command": name, "checks": infra_checks()}
    if name == "start":
        subject = _require_subject_arg(name, args)
        return _start_subject(subject, settings, storage)
    if name == "update":
        subject = _require_subject_arg(name, args)
        return _update_subject(subject, settings, storage)
    if name == "closeout":
        subject = _require_subject_arg(name, args)
        return _closeout_subject(subject, storage)
    if name == "context":
        subject = _require_subject_arg(name, args)
        return _context_subject(subject, settings, storage)
    if name == "coverage":
        subject = _require_subject_arg(name, args)
        return _coverage_subject(subject, storage)
    if name == "threat-model":
        subject = _require_subject_arg(name, args)
        return _threat_model_subject(subject, storage)
    if name == "doctor":
        subject = args[0].strip() if args and args[0].strip() else None
        return _doctor(settings, storage, subject)
    if name == "estimate":
        subject = _require_subject_arg(name, args)
        return _estimate_subject(subject, settings, storage)
    if name == "logs":
        subject = _require_subject_arg(name, args)
        return _logs_subject(subject, storage)
    raise HTTPException(422, f"unhandled REFALL ops command: {name}")


def _audit(storage: FilesystemStorage, command: str, args: list[str], status: str) -> None:
    path = storage.root / "refall_ops_audit.jsonl"
    event = {
        "ts": datetime.now(UTC).isoformat(),
        "command": command,
        "args": args,
        "status": status,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")


def _require_subject_arg(command: str, args: list[str]) -> str:
    if not args or not args[0].strip():
        raise HTTPException(422, f"{command} requires a subject")
    return args[0].strip()


def _start_subject(subject: str, settings: Settings, storage: FilesystemStorage) -> dict:
    boot = bootstrap_subject(settings=settings, storage=storage, subject=subject)
    slug = boot.workbench_slug
    workbench = storage.get_workbench(slug)
    source_path = _loop_source_path(workbench.model_dump(mode="json"), boot.subject_path)
    store = store_for_workbench(storage, slug)
    context = store.get_context(slug)
    if not context or not str(context.get("info_md") or "").strip():
        raise HTTPException(
            409,
            "Generate Context before starting REFALL; context.md is required for the head and specialist agents.",
        )
    if settings.refall_enable_loop_launch:
        _authorize_process_launch(
            storage=storage,
            slug=slug,
            settings=settings,
            subject=boot.subject,
            workbench=slug,
            max_cycles=0,
            subject_path=boot.subject_path,
            action="loop.start",
        )
    loop = _launch_standing_loop(
        settings=settings,
        subject=boot.subject,
        workbench=slug,
        max_cycles=0,
        subject_path=boot.subject_path,
        source_path=source_path,
    )
    entry = _append_ops_event(
        storage,
        slug,
        action="loop.start",
        summary="REFALL loop started",
        status="started",
        subject_path=str(boot.subject_path),
        loop=loop,
    )
    return {
        "status": "started",
        "command": "start",
        "subject": boot.subject,
        "workbench": slug,
        "subject_path": str(boot.subject_path),
        "created": boot.created,
        "ledger_id": entry["id"],
        "loop": loop,
    }


def _update_subject(subject: str, settings: Settings, storage: FilesystemStorage) -> dict:
    workbench = storage.get_workbench(subject)
    store = store_for_workbench(storage, subject)
    coverage = store.coverage(subject)
    ledger_stats = ledger.stats(storage, subject)
    subject_path = _subject_context_dir(workbench.model_dump(mode="json"))
    source_path = _loop_source_path(workbench.model_dump(mode="json"), subject_path)
    if settings.refall_enable_loop_launch:
        _authorize_process_launch(
            storage=storage,
            slug=subject,
            settings=settings,
            subject=(workbench.custom_fields.get("refall_subject") or subject),
            workbench=subject,
            max_cycles=1,
            subject_path=subject_path,
            action="loop.update",
        )
    loop = _launch_standing_loop(
        settings=settings,
        subject=(workbench.custom_fields.get("refall_subject") or subject),
        workbench=subject,
        max_cycles=1,
        subject_path=subject_path,
        source_path=source_path,
    )
    entry = _append_ops_event(
        storage,
        subject,
        action="loop.update",
        summary="REFALL loop state updated",
        status="updated",
        coverage=coverage,
        ledger_stats=ledger_stats,
        loop=loop,
    )
    return {
        "status": "updated",
        "command": "update",
        "subject": subject,
        "workbench": subject,
        "coverage": coverage,
        "ledger_stats": ledger_stats,
        "ledger_id": entry["id"],
        "loop": loop,
    }


def _authorize_process_launch(
    *,
    storage: FilesystemStorage,
    slug: str,
    settings: Settings,
    subject: str,
    workbench: str,
    max_cycles: int,
    subject_path: Path | None,
    action: str,
) -> dict:
    store = store_for_workbench(storage, slug)
    request = {
        "requested_by": "refall-ops-command",
        "capability_class": "run_local_command",
        "command": _standing_loop_argv(settings, subject, workbench, max_cycles),
        "declared_effects": ["process"],
        "target": {"path": str(subject_path) if subject_path is not None else ""},
        "action": action,
    }
    result = store.authorize_execution(slug, request)
    ledger.append_entry(
        storage,
        slug,
        {
            "kind": "capability-decision",
            "subject": slug,
            "status": result["status"],
            "capability_class": request["capability_class"],
            "grant_id": result.get("grant_id"),
            "summary": "; ".join(result.get("refusal_reasons") or []) or "authorized",
            "request": request,
        },
    )
    if not result.get("accepted"):
        refusal = ", ".join(result.get("refusal_reasons") or ["refused"])
        raise HTTPException(403, f"run_local_command capability refused: {refusal}")
    return result


def _standing_loop_argv(settings: Settings, subject: str, workbench: str, max_cycles: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "ref_all_executor.standing_loop",
        "--subject",
        subject,
        "--workbench",
        workbench,
        "--max-parallel",
        str(settings.refall_loop_max_parallel),
        "--poll-interval-s",
        str(settings.refall_loop_poll_interval_s),
        "--max-cycles",
        str(max_cycles),
    ]


def _launch_standing_loop(
    *,
    settings: Settings,
    subject: str,
    workbench: str,
    max_cycles: int,
    subject_path: Path | None,
    source_path: Path | None = None,
) -> dict:
    if not settings.refall_enable_loop_launch:
        return {
            "status": "disabled",
            "enabled": False,
            "reason": "REFALL_ENABLE_LOOP_LAUNCH=false",
        }

    repo_root = Path(settings.refall_repo_root).expanduser().resolve()
    if not repo_root.is_dir():
        raise HTTPException(503, f"REFALL_REPO_ROOT is not available: {repo_root}")

    if subject_path is None:
        root = settings.refall_subject_root or (settings.refall_data_root / "subjects")
        subject_path = Path(root).expanduser() / subject
    agent_workspace = None
    if source_path is not None:
        try:
            agent_workspace = _sync_agent_canvas_workspace(subject=subject, source_path=source_path)
        except AgentWorkspaceError as exc:
            raise HTTPException(503, str(exc)) from exc
    _assert_openhands_api_ready(settings)
    loop_log_dir = subject_path / "refallsubloop" / "logs" / "loop"
    loop_log_dir.mkdir(parents=True, exist_ok=True)
    log_path = loop_log_dir / f"standing-loop-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.log"

    env = os.environ.copy()
    env["REFALL_REPO_ROOT"] = str(repo_root)
    env["REFALL_WORKBENCH_BASE"] = settings.refall_public_base_url
    env["REFALL_COVERAGE_WORKBENCH_SLUG"] = workbench
    env["REFALL_LOOP_MAX_PARALLEL"] = str(settings.refall_loop_max_parallel)
    env["REFALL_LOOP_POLL_INTERVAL_S"] = str(settings.refall_loop_poll_interval_s)
    env["REFALL_LOOP_REPORT_INTERVAL_CYCLES"] = str(settings.refall_loop_report_interval_cycles)
    env["REFALL_LOOP_STALL_CYCLES"] = str(settings.refall_loop_stall_cycles)
    env["PYTHONPATH"] = str(repo_root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    argv = _standing_loop_argv(settings, subject, workbench, max_cycles)
    try:
        with log_path.open("ab") as log:
            proc = subprocess.Popen(
                argv,
                cwd=str(repo_root),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError as exc:
        raise HTTPException(503, f"REFALL standing loop failed to start: {exc}") from exc

    supervisor = None
    if max_cycles == 0:
        # Continuous loops get a supervisor cron for as long as they run. Bounded
        # `update` passes finish on their own and do not need supervision.
        if settings.refall_enable_loop_supervisor_cron:
            supervisor = _install_loop_supervisor(settings=settings, subject=subject, repo_root=repo_root)
        else:
            supervisor = {
                "installed": False,
                "disabled": True,
                "reason": "REFALL_ENABLE_LOOP_SUPERVISOR_CRON=false",
            }

    return {
        "status": "launched",
        "enabled": True,
        "pid": proc.pid,
        "mode": "continuous" if max_cycles == 0 else "bounded",
        "max_cycles": max_cycles,
        "log": str(log_path),
        "workbench": workbench,
        "agent_workspace": agent_workspace,
        "supervisor": supervisor,
    }


def _install_loop_supervisor(*, settings: Settings, subject: str, repo_root: Path) -> dict:
    """Install the supervisor cron alongside a newly started standing loop.

    Best effort by design: a supervisor that cannot be installed must never stop
    a loop from starting. The failure is reported in the launch payload instead.
    """
    try:
        from ref_all_executor import supervisor as supervisor_mod
    except Exception as exc:  # pragma: no cover - import guard
        return {"installed": False, "error": f"import failed: {exc}"[:200]}

    hold = Path(repo_root) / "logs" / "refall-supervisor-HOLD"
    if hold.exists():
        return {
            "installed": False,
            "held": True,
            "error": f"supervisor is holding after repeated recoveries; clear {hold} first",
        }
    try:
        return supervisor_mod.install_cron(
            repo_root=repo_root,
            subject=subject,
            base_url=settings.refall_public_base_url,
            oh_base=settings.refall_openhands_base,
        )
    except Exception as exc:
        return {"installed": False, "error": str(exc)[:200]}


def _loop_source_path(workbench: dict, subject_path: Path | None) -> Path | None:
    custom = workbench.get("custom_fields") or {}
    recorded = custom.get("refall_source_path")
    if recorded:
        path = Path(str(recorded)).expanduser()
        if not path.is_dir():
            raise HTTPException(409, f"REFALL source path is not available: {path}")
        return path
    if subject_path is None:
        return None
    prj = subject_path / "PRJ"
    return prj if prj.is_dir() else None


def _sync_agent_canvas_workspace(*, subject: str, source_path: Path, runner=subprocess) -> dict:
    return sync_agent_canvas_workspace(subject, source_path, runner=runner)


def _assert_openhands_api_ready(settings: Settings) -> None:
    url = settings.refall_openhands_base.rstrip("/") + "/api/conversations"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=8):
            return
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            return
        body = exc.read(300).decode("utf-8", errors="replace")
        raise HTTPException(503, f"OpenHands Agent Canvas API is not ready: HTTP {exc.code} {body}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(503, f"OpenHands Agent Canvas API is not reachable: {exc.reason}") from exc


def _closeout_subject(subject: str, storage: FilesystemStorage) -> dict:
    storage.get_workbench(subject)
    store = store_for_workbench(storage, subject)
    coverage = store.coverage(subject)
    ledger_stats = ledger.stats(storage, subject)
    report = _ensure_current_report(storage, subject, coverage, ledger_stats)
    closeout_gate = evaluate_closeout_gate(storage, subject)
    if not closeout_gate.get("passed"):
        entry = _append_ops_event(
            storage,
            subject,
            action="loop.closeout.blocked",
            summary="REFALL closeout blocked by required gates",
            status="blocked",
            coverage=coverage,
            ledger_stats=ledger_stats,
            report=report,
            closeout_gate=closeout_gate,
        )
        return {
            "status": "blocked",
            "command": "closeout",
            "subject": subject,
            "workbench": subject,
            "coverage": coverage,
            "ledger_stats": ledger_stats,
            "report": report,
            "closeout_gate": closeout_gate,
            "ledger_id": entry["id"],
        }
    entry = _append_ops_event(
        storage,
        subject,
        action="loop.closeout",
        summary="REFALL loop closed out",
        status="closed",
        coverage=coverage,
        ledger_stats=ledger_stats,
        report=report,
        closeout_gate=closeout_gate,
    )
    return {
        "status": "closed",
        "command": "closeout",
        "subject": subject,
        "workbench": subject,
        "coverage": coverage,
        "ledger_stats": ledger_stats,
        "report": report,
        "closeout_gate": closeout_gate,
        "ledger_id": entry["id"],
    }


def _coverage_subject(subject: str, storage: FilesystemStorage) -> dict:
    storage.get_workbench(subject)
    store = store_for_workbench(storage, subject)
    return {
        "status": "ok",
        "command": "coverage",
        "subject": subject,
        "coverage": store.coverage(subject),
        "funnel": store.funnel(subject),
        "context": store.get_context(subject) or {"subject": subject, "info_md": None},
        "ledger_stats": ledger.stats(storage, subject),
    }


def _threat_model_subject(subject: str, storage: FilesystemStorage) -> dict:
    storage.get_workbench(subject)
    store = store_for_workbench(storage, subject)
    existing_scope = store.get_scope_overlay(subject) or {"subject": subject}
    requested_scope = {
        **existing_scope,
        "subject": subject,
        "threat_model_requested": True,
        "threat_model_requested_by": "refall-ops-command",
        "threat_model_requested_at": datetime.now(UTC).isoformat(),
    }
    scope = store.set_scope_overlay(subject, requested_scope, updated_by="refall-ops-command")
    pending = store.create_pending_action(
        subject,
        {
            "identity_key": f"{subject}:threat-model-request",
            "kind": "threat_model_request",
            "title": "Generate REFALL threat model",
            "description": (
                "Run an optional threat model cycle after context and source inventory are available. "
                "Use this to shape the next discovery pass; skip or refresh it when it is not useful."
            ),
            "priority": "medium",
            "required_receipt_type": "threat_model",
            "assigned_lane": "doc-synthesis",
            "created_by": "refall-ops-command",
        },
    )
    entry = _append_ops_event(
        storage,
        subject,
        action="threat-model.request",
        summary="Optional REFALL threat model cycle requested",
        status="requested",
        scope_overlay_id=scope.get("overlay_id"),
        pending_action_id=pending.get("id"),
    )
    return {
        "status": "requested",
        "command": "threat-model",
        "subject": subject,
        "scope_overlay": scope,
        "pending_action": pending,
        "ledger_id": entry["id"],
    }


def _doctor(settings: Settings, storage: FilesystemStorage, subject: str | None = None) -> dict:
    doctor_payload = _doctor_payload(settings, storage, subject)
    if subject:
        entry = _append_ops_event(
            storage,
            subject,
            action="doctor.run",
            summary=f"REFALL doctor completed with status {doctor_payload['status']}",
            status=doctor_payload["status"],
            doctor=doctor_payload,
        )
        return {"status": doctor_payload["status"], "command": "doctor", "subject": subject, "doctor": doctor_payload, "ledger_id": entry["id"]}
    return {"status": doctor_payload["status"], "command": "doctor", "doctor": doctor_payload}


def _doctor_payload(settings: Settings, storage: FilesystemStorage, subject: str | None = None) -> dict:
    checks: list[dict] = []
    _doctor_check(checks, "arcticbase_ops", "ok", "ArcticBase REFALL Ops is enabled")
    _doctor_check(
        checks,
        "agent_canvas",
        "ok" if settings.refall_openhands_base else "warn",
        "Agent Canvas URL configured" if settings.refall_openhands_base else "Agent Canvas URL missing",
        url=settings.refall_openhands_base,
    )
    _doctor_check(
        checks,
        "public_base_url",
        "ok" if settings.refall_public_base_url else "warn",
        "public ArcticBase URL configured" if settings.refall_public_base_url else "public ArcticBase URL missing",
        url=settings.refall_public_base_url,
    )
    for provider in [
        item.strip().lower()
        for item in settings.refall_allowed_head_providers.split(",")
        if item.strip()
    ]:
        command = _provider_command(settings, provider)
        _doctor_check(
            checks,
            f"provider.{provider}",
            "ok" if shutil.which(command) else "warn",
            f"{provider} command {'available' if shutil.which(command) else 'not found'}",
            command=command,
        )
    _secret_presence_checks(checks, settings)
    _toolchain_checks(checks, settings.refall_repo_root)
    _report_spec_checks(checks)
    if subject:
        _subject_readiness_checks(checks, settings, storage, subject)
    return {"status": _aggregate_doctor_status(checks), "subject": subject, "checks": checks}


def _estimate_subject(subject: str, settings: Settings, storage: FilesystemStorage) -> dict:
    storage.get_workbench(subject)
    store = store_for_workbench(storage, subject)
    coverage = store.coverage(subject)
    inventory = store.get_latest_source_inventory(subject) or {}
    pending = store.list_pending_actions(subject, include_terminal=False)
    funnel = store.funnel(subject)
    capabilities = {
        "grants": store.list_capability_grants(subject),
        "requests": _capability_requests(store, subject),
    }
    closeout_gate = evaluate_closeout_gate(storage, subject)
    doctor_payload = _doctor_payload(settings, storage, subject)
    files = inventory.get("files") if isinstance(inventory.get("files"), list) else []
    lines_total = int(coverage.get("lines_total") or sum(int(item.get("total_lines") or 0) for item in files))
    resolved_pct = float(coverage.get("resolved_pct") or 0)
    symbols_total = int(coverage.get("symbols_total") or 0)
    open_units = _estimated_open_units(symbols_total, lines_total, resolved_pct)
    open_pending = [action for action in pending if action.get("status") in {"open", "claimed"}]
    estimate = {
        "subject": subject,
        "coverage": coverage,
        "source_inventory": {
            "inventory_id": inventory.get("inventory_id"),
            "files_total": len(files),
            "lines_total": lines_total,
            "size_bytes": sum(int(item.get("size_bytes") or 0) for item in files),
        },
        "pending_actions_open": len(open_pending),
        "findings": funnel.get("findings", {}),
        "closeout": closeout_gate,
        "doctor": doctor_payload,
        "estimated_open_units": open_units,
        "estimated_agent_tasks": max(open_units, 1) + len(open_pending),
        "missing_prerequisites": _missing_prerequisites(doctor_payload, coverage, inventory),
        "dynamic_testing": _dynamic_testing_state(store.get_scope_overlay(subject) or {}, capabilities, inventory),
    }
    entry = _append_ops_event(
        storage,
        subject,
        action="estimate.run",
        summary=f"REFALL estimate generated: {estimate['estimated_agent_tasks']} agent tasks",
        status="ok",
        estimate=estimate,
    )
    return {"status": "ok", "command": "estimate", "subject": subject, "estimate": estimate, "ledger_id": entry["id"]}


def _doctor_check(checks: list[dict], check_id: str, status: str, summary: str, **fields) -> None:
    checks.append({"id": check_id, "status": status, "summary": summary, **fields})


def _provider_command(settings: Settings, provider: str) -> str:
    return {
        "codex": settings.refall_codex_command,
        "claude": settings.refall_claude_command,
        "grok": settings.refall_grok_command,
    }.get(provider, provider)


def _secret_presence_checks(checks: list[dict], settings: Settings) -> None:
    key_path = settings.refall_openhands_api_key_path
    present = False
    if key_path is not None:
        try:
            present = key_path.expanduser().is_file() and bool(key_path.expanduser().read_text(encoding="utf-8").strip())
        except OSError:
            present = False
    _doctor_check(
        checks,
        "openhands_api_key",
        "ok" if present else "warn",
        "OpenHands API key file present" if present else "OpenHands API key file missing or empty",
    )
    for env_name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY", "GROK_API_KEY"):
        _doctor_check(
            checks,
            f"secret.{env_name.lower()}",
            "ok" if os.environ.get(env_name) else "warn",
            f"{env_name} {'present' if os.environ.get(env_name) else 'not set'}",
        )


def _toolchain_checks(checks: list[dict], repo_root: Path) -> None:
    root = repo_root.expanduser()
    for check_id, path in (
        ("toolchain.install", root / "toolchain" / "install.sh"),
        ("toolchain.codebadger", root / "toolchain" / "bin" / "codebadger-service"),
        ("toolchain.codecharta", root / "toolchain" / "bin" / "lizard-to-codecharta"),
        ("toolchain.package", root / "toolchain" / "package.json"),
    ):
        _doctor_check(
            checks,
            check_id,
            "ok" if path.exists() else "warn",
            f"{path} {'exists' if path.exists() else 'missing'}",
        )


def _report_spec_checks(checks: list[dict]) -> None:
    root = Path(__file__).resolve().parents[1] / "refall_report"
    for check_id, path in (
        ("report.spec.findings", root / "spec" / "findings-standard.md"),
        ("report.spec.input", root / "spec" / "input-format.md"),
        ("report.template", root / "template.html"),
    ):
        _doctor_check(
            checks,
            check_id,
            "ok" if path.exists() else "warn",
            f"{path} {'exists' if path.exists() else 'missing'}",
        )


def _subject_readiness_checks(
    checks: list[dict],
    settings: Settings,
    storage: FilesystemStorage,
    subject: str,
) -> None:
    try:
        workbench = storage.get_workbench(subject)
    except NotFound:
        _doctor_check(checks, "subject.workbench", "fail", f"workbench {subject} not found")
        return
    data = workbench.model_dump(mode="json")
    subject_dir = _subject_context_dir(data)
    writable = _path_writable(subject_dir) if subject_dir is not None else False
    _doctor_check(
        checks,
        "subject.runtime_root",
        "ok" if writable else "warn",
        f"{subject_dir or ((settings.refall_subject_root or settings.refall_data_root / 'subjects') / subject)} {'writable' if writable else 'not writable or missing'}",
    )
    store = store_for_workbench(storage, subject)
    coverage = store.coverage(subject)
    inventory = store.get_latest_source_inventory(subject)
    context = store.get_context(subject)
    _doctor_check(
        checks,
        "subject.coverage",
        "ok" if int(coverage.get("lines_total") or 0) > 0 else "warn",
        f"{coverage.get('lines_total', 0)} total lines in coverage",
    )
    _doctor_check(
        checks,
        "subject.source_inventory",
        "ok" if inventory and inventory.get("files") else "warn",
        f"{len((inventory or {}).get('files') or [])} files in latest source inventory",
    )
    _doctor_check(
        checks,
        "subject.context",
        "ok" if context and str(context.get("info_md") or "").strip() else "warn",
        "context.md present" if context and str(context.get("info_md") or "").strip() else "context.md missing",
    )
    if subject_dir is not None:
        runtime_db = subject_dir / ".refall" / "runtime" / "state.sqlite"
        _doctor_check(
            checks,
            "subject.runtime_db",
            "ok" if runtime_db.exists() else "warn",
            f"{runtime_db} {'exists' if runtime_db.exists() else 'not created yet'}",
        )
    grants = store.list_capability_grants(subject)
    _doctor_check(checks, "subject.capabilities", "ok", f"{len(grants)} active capability grants", count=len(grants))
    closeout = evaluate_closeout_gate(storage, subject)
    _doctor_check(
        checks,
        "subject.closeout_gate",
        "ok" if closeout.get("passed") else "warn",
        "closeout gate passes" if closeout.get("passed") else "closeout gate has warnings or blockers",
        passed=closeout.get("passed"),
    )


def _path_writable(path: Path | None) -> bool:
    if path is None:
        return False
    probe = path if path.exists() else path.parent
    return probe.exists() and os.access(probe, os.W_OK)


def _capability_requests(store, subject: str) -> list[dict]:
    return [
        dict(row)
        for row in store.conn.execute(
            "SELECT * FROM capability_requests WHERE subject=? ORDER BY updated_at DESC",
            (subject,),
        )
    ]


def _estimated_open_units(symbols_total: int, lines_total: int, resolved_pct: float) -> int:
    unresolved_ratio = max(0.0, min(1.0, 1.0 - (resolved_pct / 100.0)))
    if symbols_total > 0:
        return max(0, int((symbols_total * unresolved_ratio) + 0.999))
    if lines_total > 0:
        return max(1, int(((lines_total / 200.0) * unresolved_ratio) + 0.999))
    return 0


def _missing_prerequisites(doctor_payload: dict, coverage: dict, inventory: dict) -> list[str]:
    missing: list[str] = []
    if int(coverage.get("lines_total") or 0) <= 0:
        missing.append("coverage.enumerate")
    if not inventory or not inventory.get("files"):
        missing.append("source_inventory")
    provider_ok = any(
        str(check.get("id") or "").startswith("provider.")
        and check.get("status") == "ok"
        for check in doctor_payload.get("checks", [])
    )
    if not provider_ok:
        missing.append("provider_command")
    return missing


def _dynamic_testing_state(scope: dict, capabilities: dict, inventory: dict) -> str:
    if not inventory or not inventory.get("files"):
        return "not_applicable"
    grants = capabilities.get("grants") if isinstance(capabilities, dict) else []
    for grant in grants or []:
        capability = str(grant.get("class") or grant.get("capability_class") or "").lower()
        if capability in {"lan_network_probe", "web_dynamic_testing", "external_network_probe"}:
            return "available"
    if (scope.get("lan_targets") or scope.get("external_targets")):
        return "scope_required"
    return "scope_required"


def _aggregate_doctor_status(checks: list[dict]) -> str:
    statuses = {str(check.get("status") or "") for check in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "ok"


def _context_subject(
    subject: str,
    settings: Settings,
    storage: FilesystemStorage,
    operator_input: str = "",
) -> dict:
    slug = subject.strip()
    if not slug:
        raise HTTPException(422, "context requires a subject")
    workbench = storage.get_workbench(slug)
    store = store_for_workbench(storage, slug)
    coverage = store.coverage(slug)
    ledger_stats = ledger.stats(storage, slug)
    workbench_data = workbench.model_dump(mode="json")
    root = _subject_context_root(workbench_data)
    materials = _context_materials(
        storage=storage,
        workbench=workbench_data,
        root=root,
    )
    writer = _run_context_writer(
        settings=settings,
        subject=slug,
        slug=workbench.slug,
        root=root,
        materials=materials,
        operator_input=operator_input,
        coverage=coverage,
        ledger_stats=ledger_stats,
    )
    context, object_result = _save_context_artifacts(
        storage=storage,
        slug=slug,
        info_md=_normalized_markdown(writer["output"]),
        generated_by=f"refall-context-writer-{writer['provider']}",
        root_container=str(root),
    )
    entry = _append_ops_event(
        storage,
        slug,
        action="context.generate",
        summary=f"REFALL context.md generated by {writer['provider']} context writer",
        status="ok",
        provider=writer["provider"],
        invocation=writer["invocation"],
        object=object_result,
        coverage=coverage,
        ledger_stats=ledger_stats,
    )
    return {
        "status": "ok",
        "command": "context",
        "subject": slug,
        "provider": writer["provider"],
        "context": context,
        "object": object_result,
        "coverage": coverage,
        "ledger_stats": ledger_stats,
        "invocation": writer["invocation"],
        "ledger_id": entry["id"],
    }


def _subject_context_root(workbench: dict) -> Path:
    custom = workbench.get("custom_fields") or {}
    raw = custom.get("refall_source_path")
    subject_path = custom.get("refall_subject_path")
    if not raw and subject_path:
        prj = Path(str(subject_path)).expanduser() / "PRJ"
        if prj.is_dir() and any(prj.iterdir()):
            raw = str(prj)
    if not raw:
        hint = f" or place source under {Path(str(subject_path)).expanduser() / 'PRJ'}" if subject_path else ""
        raise HTTPException(
            409,
            f"REFALL subject source path is not recorded; set refall_source_path{hint}",
        )
    root = Path(str(raw)).expanduser()
    if not root.is_dir():
        raise HTTPException(
            409,
            f"REFALL subject path is not available to the context generator: {root}",
        )
    return root.resolve()


def _run_context_writer(
    *,
    settings: Settings,
    subject: str,
    slug: str,
    root: Path,
    materials: str,
    operator_input: str,
    coverage: dict,
    ledger_stats: dict,
) -> dict:
    provider = settings.refall_head_provider.strip().lower()
    allowed = {
        item.strip().lower()
        for item in settings.refall_allowed_head_providers.split(",")
        if item.strip()
    }
    if provider not in allowed:
        raise HTTPException(422, f"REFALL context writer provider is not allowed: {provider}")

    prompt = _context_writer_prompt(
        subject=subject,
        slug=slug,
        root=root,
        materials=materials,
        operator_input=operator_input,
        coverage=coverage,
        ledger_stats=ledger_stats,
        public_base_url=settings.refall_public_base_url,
    )

    with tempfile.TemporaryDirectory(prefix="refall-context-") as tmp:
        output_path = Path(tmp) / "context.md"
        argv, stdin = _context_writer_argv(
            settings=settings,
            provider=provider,
            root=root,
            output_path=output_path,
            prompt=prompt,
        )
        executable = argv[0]
        if shutil.which(executable) is None:
            raise HTTPException(503, f"REFALL context writer CLI not found for provider {provider}: {executable}")

        try:
            result = subprocess.run(
                argv,
                input=stdin,
                text=True,
                capture_output=True,
                timeout=settings.refall_context_manager_timeout_s,
                cwd=str(root),
            )
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(
                504,
                f"REFALL context generation timed out after {exc.timeout}s",
            ) from exc
        except OSError as exc:
            raise HTTPException(
                503,
                f"REFALL context generation failed to start: {exc}",
            ) from exc

        output = ""
        if output_path.is_file():
            output = output_path.read_text(encoding="utf-8", errors="replace")
        if not output.strip():
            output = result.stdout or ""

        invocation = {
            "provider": provider,
            "argv": _redacted_argv(argv),
            "cwd": str(root),
            "returncode": result.returncode,
            "stderr_tail": (result.stderr or "")[-2000:],
        }
        if result.returncode != 0:
            raise HTTPException(
                502,
                {
                    "detail": "REFALL context generation failed",
                    "invocation": invocation,
                },
            )
        if not output.strip():
            raise HTTPException(
                502,
                {
                    "detail": "REFALL context generation returned empty output",
                    "invocation": invocation,
                },
            )

    return {"provider": provider, "output": output, "invocation": invocation}


def _context_writer_argv(
    *,
    settings: Settings,
    provider: str,
    root: Path,
    output_path: Path,
    prompt: str,
) -> tuple[list[str], str | None]:
    if provider == "codex":
        return (
            [
                settings.refall_codex_command,
                "exec",
                "-C",
                str(root),
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "-c",
                "approval_policy=\"never\"",
                "--output-last-message",
                str(output_path),
                "-",
            ],
            prompt,
        )
    if provider == "claude":
        return (
            [
                settings.refall_claude_command,
                "-p",
                "--output-format",
                "text",
                "--permission-mode",
                "dontAsk",
                "--add-dir",
                str(root),
            ],
            prompt,
        )
    if provider == "grok":
        return ([settings.refall_grok_command, "-p", prompt], None)
    raise HTTPException(422, f"unsupported REFALL context writer provider: {provider}")


def _context_writer_prompt(
    *,
    subject: str,
    slug: str,
    root: Path,
    materials: str,
    operator_input: str,
    coverage: dict,
    ledger_stats: dict,
    public_base_url: str,
) -> str:
    context_endpoint = f"/api/workbenches/{slug}/coverage/context"
    full_context_endpoint = f"{public_base_url.rstrip('/')}{context_endpoint}"
    workbench_url = f"{public_base_url.rstrip('/')}/wb/{slug}"
    ledger_url = f"{public_base_url.rstrip('/')}/api/workbenches/{slug}/ledger/entries"
    directives = operator_input.strip() or "None provided."
    return f"""# REFALL context.md briefing generation

OUTPUT ONLY THE BRIEFING DOCUMENT. Do not wrap the answer in JSON, backticks, or commentary.

You are writing `context.md` for a REFALL security engagement on subject `{subject}`.
This document is prepared before the loop starts. The REFALL head agent and specialist agents read
it before dispatching work, taking coverage claims, drafting reports, or enriching reports.

Hard requirements:
- Return only Markdown for `context.md`.
- Target 60-160 lines. Be concrete. Cite real paths found under `{root}`.
- Do not modify files.
- Do not call external network services.
- Do not spawn subagents.
- Do not post the result yourself. ArcticBase will store your final answer at `{full_context_endpoint}`.
- Preserve operator directives even when source materials suggest a different priority.

Required sections:
- Subject
- Operator Directives
- Available Materials
- Initial Assessment
- Approach
- Coverage Tracker
- Loop Directives

Workbench: {workbench_url}
Ledger: {ledger_url}

Operator directives:
{directives}

Raw materials:
{materials.rstrip()}

Coverage state:
```json
{json.dumps(coverage, indent=2, sort_keys=True)}
```

Ledger state:
```json
{json.dumps(ledger_stats, indent=2, sort_keys=True)}
```
"""


def _context_materials(
    *,
    storage: FilesystemStorage,
    workbench: dict,
    root: Path,
) -> str:
    sections = [
        "## Workbench Metadata\n"
        + json.dumps(_context_workbench_metadata(workbench), indent=2, sort_keys=True),
    ]
    try:
        scope = store_for_workbench(storage, str(workbench["slug"])).get_scope_overlay(str(workbench["slug"]))
    except Exception:
        scope = None
    if scope:
        sections.append("## Scope Overlay\n" + json.dumps(scope, indent=2, sort_keys=True))
    source = _source_materials(root)
    if source:
        sections.append("## Source Files\n" + source)
    try:
        inventory = store_for_workbench(storage, str(workbench["slug"])).get_latest_source_inventory(str(workbench["slug"]))
    except Exception:
        inventory = None
    if inventory:
        sections.append(
            "## Source Inventory Metadata\n"
            + json.dumps(
                {
                    "inventory_id": inventory.get("inventory_id"),
                    "root": inventory.get("root"),
                    "files": [
                        {
                            "path": item.get("path"),
                            "sha256": item.get("sha256"),
                            "total_lines": item.get("total_lines"),
                            "kind": item.get("kind"),
                        }
                        for item in (inventory.get("files") or [])[:200]
                    ],
                    "skipped": inventory.get("skipped") or [],
                    "observations": inventory.get("observations") or [],
                },
                indent=2,
                sort_keys=True,
            )
        )
    try:
        threat_model = store_for_workbench(storage, str(workbench["slug"])).get_latest_threat_model(str(workbench["slug"]))
    except Exception:
        threat_model = None
    if threat_model:
        sections.append("## Threat Model\n" + json.dumps(threat_model, indent=2, sort_keys=True))
    objects = _workbench_text_materials(storage, str(workbench["slug"]))
    if objects:
        sections.append("## Workbench Text Objects\n" + objects)
    return "\n\n".join(sections)[:MAX_CONTEXT_MATERIALS]


def _context_workbench_metadata(workbench: dict) -> dict:
    custom = {
        str(key): str(value)
        for key, value in (workbench.get("custom_fields") or {}).items()
        if str(key).lower() != "context"
    }
    return {
        "slug": workbench.get("slug"),
        "title": workbench.get("title"),
        "description": workbench.get("description"),
        "url": workbench.get("url"),
        "ip": workbench.get("ip"),
        "local_path": workbench.get("local_path"),
        "tags": workbench.get("tags") or [],
        "custom_fields": custom,
    }


def _source_materials(root: Path) -> str:
    if not root.is_dir():
        return ""
    parts: list[str] = []
    total = 0
    stop = False
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            dirname
            for dirname in dirnames
            if not _skip_context_name(dirname)
        )
        for filename in sorted(filenames):
            if _skip_context_name(filename) or filename == "context.md":
                continue
            path = Path(dirpath) / filename
            try:
                stat = path.stat()
                rel = str(path.relative_to(root))
            except OSError:
                continue
            if _readable_context_path(path):
                try:
                    body = path.read_text(encoding="utf-8", errors="replace")[:MAX_CONTEXT_FILE_READ]
                except OSError:
                    body = "<unreadable>"
                block = f"### {rel}\n```text\n{body.rstrip()}\n```\n"
            else:
                block = f"### {rel}\n[binary or non-text file, {stat.st_size} bytes]\n"
            if total + len(block) > MAX_CONTEXT_MATERIALS:
                parts.append("### <truncated>\nContext material size cap reached.\n")
                stop = True
                break
            parts.append(block)
            total += len(block)
        if stop:
            break
    return "\n".join(parts)


def _workbench_text_materials(storage: FilesystemStorage, slug: str) -> str:
    parts: list[str] = []
    count = 0
    for obj in storage.list_objects(slug, include_archived=False):
        if count >= MAX_CONTEXT_OBJECTS:
            break
        if obj.kind not in {ObjectKind.md, ObjectKind.html, ObjectKind.runbook}:
            continue
        if _is_context_object(obj):
            continue
        try:
            data, _etag = storage.get_object_content(slug, obj.id)
        except NotFound:
            continue
        text = data.decode("utf-8", errors="replace")[:MAX_CONTEXT_OBJECT_READ]
        parts.append(
            f"### {obj.title or obj.filename or obj.id} ({obj.kind.value})\n"
            f"Filename: {obj.filename or 'none'}\n"
            f"```text\n{text.rstrip()}\n```\n"
        )
        count += 1
    return "\n".join(parts)


def _readable_context_path(path: Path) -> bool:
    name = path.name.lower()
    return name in READABLE_CONTEXT_NAMES or path.suffix.lower() in READABLE_CONTEXT_EXTENSIONS


def _skip_context_name(name: str) -> bool:
    lower = name.lower()
    return lower.startswith(".") or lower in {item.lower() for item in SKIP_CONTEXT_NAMES}


def _save_context_artifacts(
    *,
    storage: FilesystemStorage,
    slug: str,
    info_md: str,
    generated_by: str,
    root_container: str | None,
) -> tuple[dict, dict]:
    context = store_for_workbench(storage, slug).set_context(
        slug,
        info_md,
        generated_by,
        root_container,
    )
    workbench = storage.get_workbench(slug)
    subject_dir = _subject_context_dir(workbench.model_dump(mode="json"))
    if subject_dir is not None:
        subject_dir.mkdir(parents=True, exist_ok=True)
        (subject_dir / "context.md").write_text(info_md, encoding="utf-8")
    object_result = _upsert_context_object(storage, slug, info_md)
    return context, object_result


def _subject_context_dir(workbench: dict) -> Path | None:
    custom = workbench.get("custom_fields") or {}
    raw = custom.get("refall_subject_path") or workbench.get("local_path")
    if not raw:
        return None
    return Path(str(raw)).expanduser().resolve()


def _coverage_root_container(workbench: dict) -> str | None:
    custom = workbench.get("custom_fields") or {}
    raw = custom.get("refall_source_path") or custom.get("refall_subject_path") or workbench.get("local_path")
    if not raw:
        return None
    return str(Path(str(raw)).expanduser())


def _upsert_context_object(storage: FilesystemStorage, slug: str, info_md: str) -> dict:
    content = info_md.encode("utf-8")
    existing = None
    for obj in storage.list_objects(slug, include_archived=True):
        if _is_context_object(obj):
            existing = obj
            break
    if existing is not None:
        if existing.archived:
            storage.update_object_meta(slug, existing.id, {"archived": False})
        storage.put_object_content(slug, existing.id, content)
        return {"object_id": existing.id, "mode": "updated"}

    now = datetime.now(UTC)
    meta = ObjectMeta(
        id=new_object_id(),
        kind=ObjectKind.md,
        title="Context",
        description="REFALL subject briefing generated before loop dispatch and editable by the operator.",
        drawer="Subject",
        filename="context.md",
        mime="text/markdown",
        created_at=now,
        updated_at=now,
    )
    created = storage.create_object(slug, meta, content=content)
    return {"object_id": created.id, "mode": "created"}


def _is_context_object(obj: ObjectMeta) -> bool:
    return (
        obj.kind == ObjectKind.md
        and (
            (obj.filename or "").lower() == "context.md"
            or (obj.title or "").strip().lower() == "context"
        )
    )


def _normalized_markdown(value: str) -> str:
    return value.strip() + "\n"


def _redacted_argv(argv: list[str]) -> list[str]:
    redacted = []
    skip_next = False
    for index, part in enumerate(argv):
        if skip_next:
            redacted.append("<redacted>")
            skip_next = False
            continue
        redacted.append(part)
        if part == "--output-last-message":
            skip_next = True
        elif part == "-p" and index + 1 < len(argv) and not argv[index + 1].startswith("-"):
            skip_next = True
    return redacted


def _logs_subject(subject: str, storage: FilesystemStorage) -> dict:
    storage.get_workbench(subject)
    return {
        "status": "ok",
        "command": "logs",
        "subject": subject,
        "audit_tail": _read_jsonl_tail(storage.root / "refall_ops_audit.jsonl"),
        "logs": _discover_log_tails(storage.root / "workbenches" / subject),
    }


def _append_ops_event(
    storage: FilesystemStorage,
    slug: str,
    *,
    action: str,
    summary: str,
    status: str,
    **fields,
) -> dict:
    entry = ledger.append_entry(
        storage,
        slug,
        {
            "kind": "ops-event",
            "action": action,
            "summary": summary,
            "status": status,
            "created_by": "refall-ops-command",
            **fields,
        },
    )
    record_event({"subject": slug, "action": action, "summary": summary, "status": status})
    return entry


def _ensure_current_report(
    storage: FilesystemStorage,
    slug: str,
    coverage: dict,
    ledger_stats: dict,
) -> dict:
    workbench = storage.get_workbench(slug)
    entries = ledger.list_entries(storage, slug)
    content = _render_closeout_report(slug, coverage, ledger_stats, entries)
    current_id = workbench.custom_fields.get("refall_current_report_object_id")
    if current_id:
        try:
            storage.put_object_content(slug, current_id, content.encode("utf-8"))
            return {"object_id": current_id, "mode": "updated"}
        except NotFound:
            pass
    now = datetime.now(UTC)
    meta = ObjectMeta(
        id=new_object_id(),
        kind=ObjectKind.html,
        title=f"{slug} REFALL Closeout Report",
        description="Current REFALL closeout report generated by the ops command surface.",
        drawer="Report",
        filename="refall-closeout-report.html",
        mime="text/html",
        created_at=now,
        updated_at=now,
    )
    created = storage.create_object(slug, meta, content=content.encode("utf-8"))
    storage.update_workbench(
        slug,
        {"custom_fields": {**workbench.custom_fields, "refall_current_report_object_id": created.id}},
    )
    return {"object_id": created.id, "mode": "created"}


_SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]


def _e(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


def _entry_text(entry: dict, *keys: str) -> str:
    for key in keys:
        value = entry.get(key)
        if value:
            return str(value)
    return ""


def _dedup_by(items: list[dict], *keys: str) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        ident = "||".join(str(item.get(key) or "") for key in keys).strip("|")
        if ident and ident in seen:
            continue
        seen.add(ident)
        out.append(item)
    return out


def _finding_sort_key(finding: dict) -> tuple:
    sev = str(finding.get("severity") or "").strip().lower()
    rank = _SEVERITY_ORDER.index(sev) if sev in _SEVERITY_ORDER else len(_SEVERITY_ORDER)
    return (rank, str(finding.get("title") or ""))


def _collect_findings(entries: list[dict]) -> list[dict]:
    findings = _dedup_by([e for e in entries if e.get("kind") == "finding"], "id", "title")
    return sorted(findings, key=_finding_sort_key)


def _finding_anchors(finding: dict) -> list[str]:
    anchors = finding.get("code_paths") or finding.get("source_anchors") or []
    return [str(a) for a in anchors if str(a).strip()]


def _sev_of(item: dict, default: str = "") -> str:
    sev = str(item.get("severity") or default).strip().lower()
    return sev if sev in _SEVERITY_ORDER else (default or "unrated")


def _report_exec_summary(findings: list[dict]) -> str:
    if not findings:
        return (
            '<section class="panel" id="summary"><h2>Executive Summary</h2>'
            '<p class="muted">No findings have been compiled into the ledger yet. '
            "Findings, facts, leads and flows appear here as loop agents emit and "
            "the loop ingests them.</p></section>"
        )
    rows = ""
    for i, finding in enumerate(findings, 1):
        sev = _sev_of(finding)
        anchors = _finding_anchors(finding)
        affected = ", ".join(f"<code>{_e(a)}</code>" for a in anchors[:3]) or '<span class="muted">—</span>'
        rows += (
            f'<tr><td>{i}</td>'
            f'<td><a href="#finding-{i}">{_e(_entry_text(finding, "title") or "(untitled)")}</a></td>'
            f'<td><span class="badge {_e(sev)}">{_e(sev.title())}</span></td>'
            f'<td>{_e(_entry_text(finding, "impact", "impact_class") or "—")}</td>'
            f"<td>{affected}</td>"
            f'<td>{_e(_entry_text(finding, "status") or "PROVISIONALLY_VALID")}</td></tr>'
        )
    return (
        '<section class="panel" id="summary"><h2>Executive Summary</h2>'
        "<table><thead><tr><th>#</th><th>Finding</th><th>Severity</th>"
        "<th>Primary Impact</th><th>Affected Artifact(s)</th><th>Status</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></section>"
    )


def _report_finding_articles(findings: list[dict]) -> str:
    articles = []
    for i, finding in enumerate(findings, 1):
        sev = _sev_of(finding)
        title = _entry_text(finding, "title") or "(untitled finding)"
        desc = _entry_text(finding, "description", "summary")
        anchors = _finding_anchors(finding)
        kvs = []
        impact = _entry_text(finding, "impact", "impact_class")
        if impact:
            kvs.append(f'<div class="kv"><strong>Impact class</strong>{_e(impact)}</div>')
        if finding.get("vector") or finding.get("cvss"):
            vec = _entry_text(finding, "vector")
            cvss = _entry_text(finding, "cvss")
            val = f'<code>{_e(vec)}</code>' if vec else _e(cvss)
            kvs.append(f'<div class="kv"><strong>CVSS</strong>{val}</div>')
        if anchors:
            kvs.append(
                '<div class="kv"><strong>Affected artifact(s)</strong>'
                + " ".join(f"<code>{_e(a)}</code>" for a in anchors[:8]) + "</div>"
            )
        quality = _entry_text(finding, "quality_tier")
        status = _entry_text(finding, "status") or "PROVISIONALLY_VALID"
        kvs.append(
            f'<div class="kv"><strong>State</strong>{_e(status)}'
            + (f' · {_e(quality)}' if quality else "") + "</div>"
        )
        remediation = _entry_text(finding, "remediation", "remediation_summary", "fix")
        remediation_html = (
            f"<h4>Remediation</h4><p>{_e(remediation)}</p>" if remediation else ""
        )
        evidence = finding.get("evidence") or []
        evidence_html = ""
        if evidence:
            items = "".join(
                f'<li><code>{_e(ev.get("ref") or ev.get("file") or "")}</code> — {_e(ev.get("claim") or "")}</li>'
                for ev in evidence if isinstance(ev, dict)
            )
            if items:
                evidence_html = f"<h4>Evidence</h4><ul class=\"evlist\">{items}</ul>"
        cvss_badge = _entry_text(finding, "cvss")
        badge_label = f"CVSS {cvss_badge} · {sev.title()}" if cvss_badge else sev.title()
        articles.append(
            f'<article class="finding {_e(sev)}" id="finding-{i}">'
            f'<div class="finding-header"><span class="badge {_e(sev)}">{_e(badge_label)}</span>'
            f"<h3>Finding {i}: {_e(title)}</h3></div>"
            f'<div class="finding-body">'
            f'<div class="grid">{"".join(kvs)}</div>'
            f'<h4>Summary</h4><p>{_e(desc) or "<span class=\'muted\'>No description provided.</span>"}</p>'
            f"{remediation_html}{evidence_html}</div></article>"
        )
    return "".join(articles)


def _report_attack_surface_section(entries: list[dict]) -> str:
    arch = _dedup_by(
        [e for e in entries if e.get("kind") == "fact" and str(e.get("title") or "").startswith("arch:")],
        "title",
    )
    if not arch:
        return ""
    rows = "".join(
        f'<tr><td><code>{_e(str(a.get("title"))[5:])}</code></td>'
        f'<td>{_e(_entry_text(a, "description", "summary"))}</td></tr>'
        for a in arch
    )
    return (
        '<section class="panel" id="architecture"><h2>Architecture &amp; Attack Surface '
        f'<small>({len(arch)})</small></h2>'
        '<table><thead><tr><th>Aspect</th><th>Value</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></section>"
    )


def _report_flows_section(entries: list[dict]) -> str:
    flows = _dedup_by(
        [e for e in entries if e.get("kind") == "fact" and e.get("fact_kind") == "flow"], "title"
    )
    if not flows:
        return ""
    rows = ""
    for entry in flows:
        flow = entry.get("flow") or {}
        rows += (
            f'<tr><td><code>{_e(flow.get("from"))}</code></td>'
            f'<td class="rel">{_e(flow.get("relation"))}</td>'
            f'<td><code>{_e(flow.get("to"))}</code></td>'
            f'<td>{_e(flow.get("evidence"))}</td></tr>'
        )
    return (
        '<section class="panel" id="flows"><h2>Data &amp; Control Flows '
        f'<small>({len(flows)})</small></h2>'
        '<table><thead><tr><th>From</th><th>Rel</th><th>To</th><th>Evidence</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></section>"
    )


def _report_leads_section(entries: list[dict]) -> str:
    leads = _dedup_by([e for e in entries if e.get("kind") == "lead"], "title")
    if not leads:
        return ""
    items = ""
    for lead in leads:
        sev = _sev_of(lead, "medium")
        items += (
            f'<div class="lead"><div class="fhead"><span class="badge {_e(sev)}">{_e(sev.title())}</span>'
            f'<b>{_e(_entry_text(lead, "title"))}</b></div>'
            f'<p>{_e(_entry_text(lead, "description"))}</p>'
            + (
                f'<p class="plan">→ {_e(lead.get("investigation_plan"))}</p>'
                if lead.get("investigation_plan") else ""
            )
            + "</div>"
        )
    return (
        '<section class="panel" id="leads"><h2>Open Leads '
        f'<small>({len(leads)})</small></h2>{items}</section>'
    )


def _report_facts_section(entries: list[dict]) -> str:
    facts = _dedup_by(
        [
            e for e in entries
            if e.get("kind") == "fact"
            and e.get("fact_kind") != "flow"
            and not str(e.get("title") or "").startswith("arch:")
        ],
        "title",
    )
    if not facts:
        return ""
    rows = "".join(
        f'<tr><td><b>{_e(_entry_text(f, "title"))}</b></td>'
        f'<td>{_e(_entry_text(f, "description", "summary"))}</td></tr>'
        for f in facts[:150]
    )
    return (
        '<section class="panel" id="facts"><h2>Key Facts '
        f'<small>({len(facts)})</small></h2>'
        f"<table><tbody>{rows}</tbody></table></section>"
    )


def _report_toc(findings: list[dict], has: dict[str, bool]) -> str:
    links = ['<a href="#summary">Executive summary</a>']
    for anchor, label in [
        ("leads", "Open leads"),
        ("facts", "Key facts"),
        ("architecture", "Architecture & attack surface"),
        ("flows", "Data & control flows"),
    ]:
        if has.get(anchor):
            links.append(f'<a href="#{anchor}">{_e(label)}</a>')
    for i, finding in enumerate(findings, 1):
        title = _entry_text(finding, "title") or f"Finding {i}"
        links.append(f'<a href="#finding-{i}">Finding {i}: {_e(title)}</a>')
    if has.get("activity"):
        links.append('<a href="#activity">Ledger activity</a>')
    return "".join(links)


_REPORT_SECTION_RE = _re.compile(
    r'<section(?:\s+class="panel")?\s+id="([^"]+)"\s*>\s*<h2>(.*?)</h2>(.*?)</section>',
    _re.DOTALL,
)


def _collapse_report_sections(body: str) -> str:
    """Convert each panel <section> into a <details> collapsed by default."""
    def repl(m: "_re.Match") -> str:
        return (
            f'<details class="panel" id="{m.group(1)}">'
            f"<summary>{m.group(2)}</summary>"
            f'<div class="sec-body">{m.group(3)}</div></details>'
        )
    return _REPORT_SECTION_RE.sub(repl, body)


def _render_closeout_report(slug: str, coverage: dict, ledger_stats: dict, entries: list[dict]) -> str:
    by_kind = ledger_stats.get("by_kind") or {}
    findings = _collect_findings(entries)
    high = sum(1 for f in findings if _sev_of(f) in {"critical", "high"})
    stat_cards = "".join(
        f'<div class="stat"><b>{_e(value)}</b><span>{_e(label)}</span></div>'
        for label, value in [
            ("Total findings", len(findings)),
            ("Critical / High", high),
            ("Facts", by_kind.get("fact", 0)),
            ("Leads", by_kind.get("lead", 0)),
            ("Resolved", f'{coverage.get("resolved_pct", 0)}%'),
            ("Lines covered", f'{coverage.get("lines_covered", 0)}/{coverage.get("lines_total", 0)}'),
        ]
    )
    attack = _report_attack_surface_section(entries)
    flows = _report_flows_section(entries)
    leads = _report_leads_section(entries)
    facts = _report_facts_section(entries)
    activity_rows = "".join(_ledger_row(entry) for entry in entries[-80:][::-1])
    has = {
        "architecture": bool(attack), "flows": bool(flows),
        "leads": bool(leads), "facts": bool(facts), "activity": bool(activity_rows),
    }
    toc = _report_toc(findings, has)
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    activity_section = (
        '<section class="panel" id="activity"><h2>Ledger Activity '
        '<small>(last 80)</small></h2>'
        '<table><thead><tr><th>Time</th><th>Kind</th><th>Ref</th><th>Summary</th></tr></thead>'
        f"<tbody>{activity_rows}</tbody></table></section>"
        if activity_rows else ""
    )
    articles = _report_finding_articles(findings)
    findings_detail = (
        f'<section class="panel" id="findings-detail"><h2>Findings '
        f'<small>({len(findings)})</small></h2>{articles}</section>'
        if articles else ""
    )
    body = _collapse_report_sections("".join([
        _report_exec_summary(findings),
        leads, facts, attack, flows,
        findings_detail,
        activity_section,
    ]))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(slug)} — REFALL Security Report</title>
<style>
 :root{{--bg:#0d1117;--panel:#161b24;--panel2:#1c2230;--ink:#e8edf6;--muted:#93a0b6;--line:#28313f;--accent:#5cc8ff;--code-bg:#0a0d13;--code-ink:#cfe6ff;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;--crit:#ff5470;--high:#ff8f6b;--med:#ffcf6b;--low:#5ef2a6}}
 *{{box-sizing:border-box}}body{{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--ink);line-height:1.5}}
 a{{color:var(--accent);text-decoration:none}}
 .shell{{max-width:1400px;margin:0 auto;display:grid;grid-template-columns:290px 1fr;min-height:100vh}}
 aside{{position:sticky;top:0;height:100vh;overflow:auto;padding:20px 16px;background:#10151f;border-right:1px solid var(--line)}}
 .brand{{background:linear-gradient(#1a2130,#141a26);border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:16px}}
 .brand .kicker{{display:inline-block;background:var(--panel2);border:1px solid var(--line);color:var(--accent);padding:2px 8px;border-radius:5px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}}
 .brand h1{{font-size:17px;margin:0 0 4px}}.brand p{{margin:0;color:var(--muted);font-size:12.5px}}
 .nav-title{{font-size:11px;text-transform:uppercase;color:var(--muted);font-weight:700;margin:16px 0 8px;letter-spacing:.06em}}
 .toc a{{display:block;padding:6px 9px;color:#c4d2ea;border-radius:5px;font-size:12.5px;margin-bottom:2px}}
 .toc a:hover{{background:var(--panel2);color:#fff}}
 main{{padding:28px 32px;min-width:0}}
 h2{{font-size:19px;margin:0 0 14px;padding-bottom:8px;border-bottom:1px solid var(--line)}}h2 small{{color:var(--muted);font-weight:400}}
 h3{{margin:0}}h4{{margin:16px 0 6px;font-size:14px;color:var(--accent)}}
 .muted{{color:var(--muted)}}code{{font-family:var(--mono);font-size:.85em;color:var(--accent);word-break:break-word}}
 .hero{{background:linear-gradient(#171d29,#121620);border:1px solid var(--line);border-radius:12px;padding:26px}}
 .hero h2{{border:none;font-size:28px;margin:0 0 8px;padding:0}}.hero p{{color:var(--muted);margin:6px 0 0}}
 .stats{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px;margin:18px 0}}
 .stat{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:13px 14px}}
 .stat b{{display:block;font-size:23px}}.stat span{{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em}}
 .panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;margin-top:20px}}
 details.panel{{padding:0;overflow:hidden}}
 details.panel>summary{{list-style:none;cursor:pointer;padding:16px 20px;font-size:18px;font-weight:600;color:var(--ink);display:flex;align-items:center;gap:10px}}
 details.panel>summary::-webkit-details-marker{{display:none}}
 details.panel>summary::before{{content:"\\25B8";color:var(--accent);font-size:13px;transition:transform .15s}}
 details.panel[open]>summary{{border-bottom:1px solid var(--line)}}
 details.panel[open]>summary::before{{transform:rotate(90deg)}}
 details.panel>summary small{{color:var(--muted);font-weight:400}}
 details.panel>summary:hover{{color:var(--accent)}}
 .sec-body{{padding:18px 20px}}
 table{{width:100%;border-collapse:collapse;font-size:13.5px}}
 th,td{{text-align:left;vertical-align:top;padding:9px 10px;border-bottom:1px solid var(--line)}}
 th{{background:var(--panel2);color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.04em}}
 .badge{{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11.5px;font-weight:700;border:1px solid var(--line);background:var(--panel2);color:var(--muted);text-transform:uppercase;letter-spacing:.03em}}
 .badge.critical{{color:var(--crit);border-color:#5a2f3a;background:#2a1720}}
 .badge.high{{color:var(--high);border-color:#5a3f2f;background:#2a1d16}}
 .badge.medium{{color:var(--med);border-color:#5a4f2f;background:#2a2516}}
 .badge.low{{color:var(--low);border-color:#2f5a44;background:#132a20}}
 .finding{{background:var(--panel);border:1px solid var(--line);border-radius:12px;margin-top:20px;overflow:hidden}}
 .finding.critical{{border-left:4px solid var(--crit)}}.finding.high{{border-left:4px solid var(--high)}}.finding.medium{{border-left:4px solid var(--med)}}.finding.low{{border-left:4px solid var(--low)}}
 .finding-header{{padding:16px 20px;background:linear-gradient(#1a212e,#141a25);border-bottom:1px solid var(--line)}}
 .finding-header .badge{{margin-bottom:8px}}.finding-header h3{{font-size:20px}}
 .finding-body{{padding:20px}}
 .grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}
 .kv{{border:1px solid var(--line);border-radius:8px;padding:10px 12px;background:var(--panel2)}}
 .kv strong{{display:block;font-size:11px;text-transform:uppercase;color:var(--muted);margin-bottom:5px;letter-spacing:.04em}}
 .evlist{{margin:6px 0 0;padding-left:18px}}.evlist li{{margin:3px 0}}
 .lead{{border:1px solid var(--line);border-left:4px solid var(--med);border-radius:10px;padding:12px 14px;margin-top:12px;background:var(--panel2)}}
 .fhead{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:6px}}
 .rel{{color:var(--accent);font-family:var(--mono);font-size:12px}}.plan{{color:var(--accent);font-size:13px;margin:6px 0 0}}
 details.activity summary{{cursor:pointer;color:var(--muted)}}
 .foot{{color:var(--muted);font-size:12px;margin-top:26px;border-top:1px solid var(--line);padding-top:14px}}
 @media(max-width:980px){{.shell{{grid-template-columns:1fr}}aside{{position:relative;height:auto}}.stats{{grid-template-columns:repeat(2,1fr)}}.grid{{grid-template-columns:1fr}}main{{padding:18px}}}}
</style>
</head>
<body>
<div class="shell">
<aside>
  <div class="brand"><span class="kicker">REFALL-V10</span><h1>{_e(slug)}</h1><p>Security assessment · live evidence</p></div>
  <div class="nav-title">Contents</div>
  <nav class="toc">{toc}</nav>
</aside>
<main>
  <div class="hero"><h2>{_e(slug)} — REFALL Security Report</h2>
    <p>Deterministic report compiled from the workbench ledger, findings, and coverage. Regenerates as evidence lands.</p>
    <p class="muted">Generated {generated}</p>
  </div>
  <div class="stats">{stat_cards}</div>
  {body}
  <div class="foot">REFALL-V10 · rendered from the workbench ledger &amp; findings table. Sections populate automatically as loop agents emit findings, facts, leads, and flows.</div>
</main>
</div>
</body>
</html>
"""


def _ledger_row(entry: dict) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(str(entry.get('created_at') or ''))}</td>"
        f"<td>{html.escape(str(entry.get('kind') or ''))}</td>"
        f"<td>{html.escape(str(entry.get('action') or entry.get('title') or ''))}</td>"
        f"<td>{html.escape(str(entry.get('summary') or ''))}</td>"
        "</tr>"
    )


def _read_jsonl_tail(path: Path, limit: int = 50) -> list[dict]:
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


def _discover_log_tails(base: Path, limit: int = 20, line_limit: int = 80) -> list[dict]:
    if not base.is_dir():
        return []
    logs = []
    for path in sorted(base.glob("**/*.log"))[:limit]:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-line_limit:]
        except OSError:
            lines = []
        logs.append({
            "path": str(path.relative_to(base)),
            "size": path.stat().st_size,
            "tail": lines,
        })
    return logs
