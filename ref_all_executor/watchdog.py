from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .arcticbase_client import ArcticBaseClient
from .oh_client import OHClient


DEFAULT_REPO_ROOT = str(Path(__file__).resolve().parents[1])
DEFAULT_BASE_URL = "http://127.0.0.1:7673"
DEFAULT_OH_BASE = "http://127.0.0.1:8000"
DEFAULT_SUBJECT = "hyundai"
WATCHDOG_NAME = "refall-watchdog-cron"
CRON_MARKER = "REFALL_V10_WATCHDOG"
FAILURE_RE = re.compile(
    r"\b(error|failed|failure|refus(?:al|ed|e)|cannot comply|denied|blocked|timeout|exception)\b",
    re.IGNORECASE,
)
CRASH_POLICY_REASONS = {
    "dead_or_stuck_loop_state",
    "openhands_agent_server_unreachable",
    "refall_api_unreachable",
}
WISHLIST_INSTALLERS = {
    "binwalk": [["brew", "install", "binwalk"]],
    "exiftool": [["brew", "install", "exiftool"]],
    "radare2": [["brew", "install", "radare2"]],
    "r2": [["brew", "install", "radare2"]],
    "rizin": [["brew", "install", "rizin"]],
    "rz-bin": [["brew", "install", "rizin"]],
    "yara": [["brew", "install", "yara"]],
}


@dataclass
class Thresholds:
    stale_agent_s: int
    no_progress_s: int
    stop_no_progress_s: int
    loop_dead_s: int
    terminal_grace_s: int
    max_runtime_s: int
    max_tokens: int
    max_cost_usd: float
    failure_refusal_count: int


@dataclass
class WatchdogConfig:
    subject: str = DEFAULT_SUBJECT
    repo_root: Path = Path(DEFAULT_REPO_ROOT)
    base_url: str = DEFAULT_BASE_URL
    oh_base: str = DEFAULT_OH_BASE
    log_path: Path | None = None
    audit_path: Path | None = None
    state_path: Path | None = None
    stale_seconds: int = 3600
    no_progress_seconds: int = 1800
    stop_no_progress_seconds: int = 7200
    loop_dead_seconds: int = 900
    max_runtime_seconds: int = 21600
    max_total_tokens: int = 1_500_000
    max_cost_usd: float = 100.0
    failure_refusal_count: int = 3
    no_progress_samples: int | None = None
    install_wishlist_items: bool = True
    wishlist_install_timeout_seconds: int = 900
    enforce: bool = True
    dry_run: bool = False

    def paths(self) -> tuple[Path, Path, Path]:
        repo_root = Path(self.repo_root).expanduser()
        log_path = self.log_path or repo_root / "logs/refall-watchdog-cron.log"
        audit_path = self.audit_path or repo_root / "logs/refall-watchdog-cron.jsonl"
        state_path = self.state_path or repo_root / "logs/refall-watchdog-state.json"
        return log_path, audit_path, state_path

    def thresholds(self) -> Thresholds:
        return Thresholds(
            stale_agent_s=self.stale_seconds,
            no_progress_s=self.no_progress_seconds,
            stop_no_progress_s=self.stop_no_progress_seconds,
            loop_dead_s=self.loop_dead_seconds,
            terminal_grace_s=120,
            max_runtime_s=self.max_runtime_seconds,
            max_tokens=self.max_total_tokens,
            max_cost_usd=self.max_cost_usd,
            failure_refusal_count=self.failure_refusal_count,
        )


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def thresholds_from_env() -> Thresholds:
    return Thresholds(
        stale_agent_s=_env_int("REFALL_WATCHDOG_STALE_AGENT_S", 3600),
        no_progress_s=_env_int("REFALL_WATCHDOG_NO_PROGRESS_S", 1800),
        stop_no_progress_s=_env_int("REFALL_WATCHDOG_STOP_NO_PROGRESS_S", 7200),
        loop_dead_s=_env_int("REFALL_WATCHDOG_LOOP_DEAD_S", 900),
        terminal_grace_s=_env_int("REFALL_WATCHDOG_TERMINAL_GRACE_S", 120),
        max_runtime_s=_env_int("REFALL_WATCHDOG_MAX_RUNTIME_S", 21600),
        max_tokens=_env_int("REFALL_WATCHDOG_MAX_TOKENS", 1500000),
        max_cost_usd=_env_float("REFALL_WATCHDOG_MAX_COST_USD", 100.0),
        failure_refusal_count=_env_int("REFALL_WATCHDOG_FAILURE_REFUSAL_COUNT", 3),
    )


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def append_text(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line.rstrip() + "\n")


def request_json(method: str, url: str, *, headers: dict[str, str] | None = None, body: Any = None, timeout: int = 20) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            parsed = json.loads(raw) if raw else None
            return {"ok": True, "status": response.status, "data": parsed}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        return {"ok": False, "status": exc.code, "error": text[:1000]}
    except Exception as exc:
        return {"ok": False, "status": None, "error": repr(exc)}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def event_ts(event: dict[str, Any]) -> float | None:
    return parse_timestamp(event.get("created_at"))


def parse_timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def openhands_updated_ts(info: dict[str, Any]) -> float | None:
    for key in ("updated_at", "last_updated_at", "modified_at", "created_at"):
        ts = parse_timestamp(info.get(key))
        if ts is not None:
            return ts
    return None


def endpoint_name(path: str) -> str:
    return path.strip("/").replace("/", "_").replace("-", "_")


def numeric_usage(data: Any) -> dict[str, float]:
    out = {"tokens": 0.0, "cost_usd": 0.0}
    token_keys = {
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "input_tokens",
        "output_tokens",
        "per_turn_token",
    }
    cost_keys = {
        "cost",
        "cost_usd",
        "accumulated_cost",
        "total_cost",
        "total_cost_usd",
    }

    def walk(value: Any, key_path: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{key_path}.{key}" if key_path else str(key))
        elif isinstance(value, list):
            for item in value:
                walk(item, key_path)
        elif isinstance(value, (int, float)):
            key = key_path.lower().split(".")[-1]
            if key in token_keys or key.endswith("_tokens"):
                out["tokens"] += float(value)
            if key in cost_keys or key.endswith("_cost_usd"):
                out["cost_usd"] += float(value)

    walk(data)
    return out


def compact_json(value: Any, limit: int = 4000) -> str:
    text = json.dumps(value, sort_keys=True, default=str)
    return text[:limit]


def normalize_wishlist_tool(item: Any) -> str:
    text = str(item or "").strip()
    if not text:
        return ""
    token = re.split(r"\s+", text, maxsplit=1)[0]
    token = Path(token).name
    token = re.sub(r"[^A-Za-z0-9_.+-]", "", token)
    return token.lower()


def wishlist_item_key(item: dict[str, Any]) -> str:
    return normalize_wishlist_tool(item.get("item")) or str(item.get("item") or "").strip().lower()


def runtime_by_cid(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        cid = str(event.get("session_id") or payload.get("cid") or "")
        if not cid:
            continue
        row = rows.setdefault(cid, {"events": [], "start_ts": None, "last_ts": None, "complete": False})
        row["events"].append(event)
        ts = event_ts(event)
        if event.get("type") == "agent_start" and ts is not None:
            row["start_ts"] = ts if row["start_ts"] is None else min(row["start_ts"], ts)
        if ts is not None:
            row["last_ts"] = ts if row["last_ts"] is None else max(row["last_ts"], ts)
        if event.get("type") == "agent_complete":
            row["complete"] = True
    return rows


def latest_loop_cycle(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    cycles = [event for event in events if event.get("type") == "loop_cycle"]
    if not cycles:
        return None
    return max(cycles, key=lambda item: event_ts(item) or 0)


def progress_signature(coverage: Any, events: list[dict[str, Any]], active: list[dict[str, Any]]) -> str:
    latest_event = max(events, key=lambda item: event_ts(item) or 0, default={})
    loop = latest_loop_cycle(events) or {}
    coverage_payload = coverage if isinstance(coverage, dict) else {}
    parts = {
        "latest_event": latest_event.get("id"),
        "latest_event_type": latest_event.get("type"),
        "loop_cycle": (loop.get("payload") or {}).get("cycle") if isinstance(loop.get("payload"), dict) else None,
        "resolved_pct": coverage_payload.get("resolved_pct"),
        "files_characterized": coverage_payload.get("files_characterized"),
        "lines_covered": coverage_payload.get("lines_covered"),
        "active": sorted((item.get("cid"), item.get("phase"), item.get("unit_id")) for item in active),
    }
    return json.dumps(parts, sort_keys=True, default=str)


def cid_signature(agent: dict[str, Any], oh_info: dict[str, Any] | None, live_info: dict[str, Any] | None, cid_events: dict[str, Any]) -> str:
    recent_events = []
    if isinstance(live_info, dict):
        recent_events = live_info.get("recent_events") or []
    parts = {
        "status": agent.get("status"),
        "phase": agent.get("phase"),
        "unit_id": agent.get("unit_id"),
        "oh_execution_status": (oh_info or {}).get("execution_status"),
        "oh_status": (oh_info or {}).get("status"),
        "oh_updated": (oh_info or {}).get("updated_at") or (oh_info or {}).get("last_updated_at"),
        "runtime_last_ts": cid_events.get("last_ts"),
        "runtime_event_count": len(cid_events.get("events") or []),
        "live_event_count": len(recent_events),
        "live_last": recent_events[-1] if recent_events else None,
    }
    return json.dumps(parts, sort_keys=True, default=str)


def failure_refusal_count(*values: Any) -> int:
    def walk(value: Any) -> int:
        if isinstance(value, list):
            return sum(walk(item) for item in value)
        if not isinstance(value, dict):
            return 0
        if value.get("type") == "structured_submission_duplicate":
            return 0

        count = 0
        status = str(value.get("status") or value.get("execution_status") or "").lower()
        if status in {"error", "failed", "failure", "refused", "denied", "blocked", "timeout", "timed_out"}:
            count += 1

        for key in ("error", "failure", "failure_class", "refusal_reason", "refusal_reasons", "reason", "reasons"):
            item = value.get(key)
            if item in (None, "", [], {}):
                continue
            count += max(1, len(FAILURE_RE.findall(compact_json(item, limit=4000))))

        # Live tool events often include source text or command output. Only
        # inspect those free-form fields when the event itself did not succeed.
        if value.get("kind") == "tool_call" and status and status not in {"completed", "success", "succeeded", "pending", "running"}:
            count += len(FAILURE_RE.findall(compact_json({
                "title": value.get("title"),
                "output": value.get("output"),
            }, limit=4000)))

        return count + sum(
            walk(item)
            for key, item in value.items()
            if key not in {
                "status",
                "execution_status",
                "error",
                "failure",
                "failure_class",
                "refusal_reason",
                "refusal_reasons",
                "reason",
                "reasons",
                "title",
                "output",
            }
        )

    return sum(walk(value) for value in values)


def summarize_endpoint_payloads(endpoints: dict[str, Any]) -> dict[str, Any]:
    coverage = ((endpoints.get("coverage_stats") or {}).get("data") or {})
    context = ((endpoints.get("coverage_context") or {}).get("data") or {})
    agents = ((endpoints.get("ops_agents") or {}).get("data") or {})
    live = ((endpoints.get("ops_debug_live") or {}).get("data") or {})
    events = ((endpoints.get("runtime_events") or {}).get("data") or [])
    manifest = ((endpoints.get("runtime_manifest") or {}).get("data") or {})
    pending = ((endpoints.get("pending_actions") or {}).get("data") or [])
    if not isinstance(events, list):
        events = []
    if not isinstance(pending, list):
        pending = []
    latest_event = max(events, key=lambda item: event_ts(item) or 0, default={})
    pending_by_status: dict[str, int] = {}
    pending_by_kind: dict[str, int] = {}
    for action in pending:
        if not isinstance(action, dict):
            continue
        pending_by_status[str(action.get("status") or "unknown")] = pending_by_status.get(str(action.get("status") or "unknown"), 0) + 1
        pending_by_kind[str(action.get("kind") or "unknown")] = pending_by_kind.get(str(action.get("kind") or "unknown"), 0) + 1
    return {
        "endpoint_ok": {name: result.get("ok") for name, result in endpoints.items()},
        "endpoint_status": {name: result.get("status") for name, result in endpoints.items()},
        "coverage": coverage if isinstance(coverage, dict) else {},
        "context": {
            "present": bool(isinstance(context, dict) and (context.get("info_md") or "").strip()),
            "context_id": context.get("context_id") if isinstance(context, dict) else None,
            "generated_by": context.get("generated_by") if isinstance(context, dict) else None,
        },
        "ops_agents": {
            "active_count": len(agents.get("active") or []) if isinstance(agents, dict) else 0,
            "loop_launch_enabled": agents.get("loop_launch_enabled") if isinstance(agents, dict) else None,
        },
        "ops_debug_live": {
            "live": live.get("live") if isinstance(live, dict) else None,
            "active_count": len(live.get("active") or []) if isinstance(live, dict) else 0,
        },
        "runtime_events": {
            "count": len(events),
            "latest_id": latest_event.get("id"),
            "latest_type": latest_event.get("type"),
            "latest_created_at": latest_event.get("created_at"),
        },
        "runtime_manifest": {
            "run_id": manifest.get("run_id") if isinstance(manifest, dict) else None,
            "manifest_id": manifest.get("manifest_id") if isinstance(manifest, dict) else None,
            "stage_status": manifest.get("stage_status") if isinstance(manifest, dict) else {},
            "updated_at": manifest.get("updated_at") if isinstance(manifest, dict) else None,
        },
        "pending_actions": {
            "count": len(pending),
            "by_status": pending_by_status,
            "by_kind": pending_by_kind,
        },
    }


def create_pending_action(
    ab: ArcticBaseClient,
    subject: str,
    issue: dict[str, Any],
    receipt: dict[str, Any],
    *,
    kind: str,
) -> dict[str, Any]:
    cid = issue.get("cid") or "unknown"
    short = re.sub(r"[^a-zA-Z0-9_]+", "_", str(cid))[:24]
    agent = issue.get("agent") if isinstance(issue.get("agent"), dict) else {}
    stopped = kind == "watchdog_conversation_stopped"
    action = {
        "id": f"pa_{kind}_{short}",
        "kind": kind,
        "title": (
            f"Review watchdog-stopped Agent Canvas conversation {cid}"
            if stopped
            else f"Review REFALL watchdog alert for {subject}"
        ),
        "description": (
            ("REFALL watchdog stopped or attempted to stop an active Agent Canvas conversation. " if stopped else "REFALL watchdog detected a loop-control issue. ")
            + f"Reason: {issue.get('reason')}. Phase: {agent.get('phase')}. Lane: {agent.get('lane')}. "
            f"Unit: {agent.get('unit_id') or agent.get('path')}."
        ),
        "priority": "high",
        "status": "open",
        "source_unit_id": agent.get("unit_id"),
        "required_receipt_type": "watchdog_stop_review" if stopped else "watchdog_alert_review",
        "assigned_lane": "review",
        "created_by": WATCHDOG_NAME,
        "identity_key": f"{kind}:{subject}:{issue.get('reason')}:{cid}:{agent.get('unit_id') or agent.get('path')}",
    }
    try:
        return ab.create_pending_action(subject, action)
    except Exception as exc:
        return {"ok": False, "error": repr(exc), "requested_action": action, "receipt": receipt}


def append_stop_records(ab: ArcticBaseClient, subject: str, manifest: dict[str, Any], issue: dict[str, Any], metrics: dict[str, Any], delete_result: dict[str, Any]) -> dict[str, Any]:
    agent = issue.get("agent") if isinstance(issue.get("agent"), dict) else {}
    cid = issue.get("cid")
    receipt = {
        "watchdog": WATCHDOG_NAME,
        "timestamp": iso_now(),
        "cid": cid,
        "lane": agent.get("lane"),
        "phase": agent.get("phase"),
        "unit_id": agent.get("unit_id"),
        "path": agent.get("path"),
        "reason": issue.get("reason"),
        "metrics": metrics,
        "delete_result": delete_result,
        "allowed_resources": manifest.get("allowed_resources") if isinstance(manifest.get("allowed_resources"), list) else [],
    }
    runtime_event = ab.append_runtime_event(
        subject,
        {
            "type": "watchdog_conversation_stopped",
            "run_id": manifest.get("run_id"),
            "task_id": agent.get("unit_id"),
            "session_id": cid,
            "payload": {
                "summary": f"Watchdog stopped Agent Canvas conversation {cid}: {issue.get('reason')}",
                **receipt,
            },
        },
    )
    ledger = _safe_ledger(
        ab,
        subject,
        {
            "kind": "ops-event",
            "subject": subject,
            "action": "watchdog.stop_conversation",
            "status": "stopped" if delete_result.get("ok") else "stop_failed",
            "summary": f"Watchdog handled Agent Canvas conversation {cid}: {issue.get('reason')}",
            "cid": cid,
            "lane": agent.get("lane"),
            "phase": agent.get("phase"),
            "unit_id": agent.get("unit_id"),
            "path": agent.get("path"),
            "reason": issue.get("reason"),
            "metrics": metrics,
            "runtime_event_id": runtime_event.get("id"),
        },
    )
    pending = create_pending_action(ab, subject, issue, receipt, kind="watchdog_conversation_stopped")
    return {
        "cid": cid,
        "reason": issue.get("reason"),
        "runtime_event": runtime_event,
        "ledger": ledger,
        "pending_action": pending,
    }


def append_alert_records(ab: ArcticBaseClient, subject: str, manifest: dict[str, Any], issue: dict[str, Any]) -> dict[str, Any]:
    agent = issue.get("agent") if isinstance(issue.get("agent"), dict) else {}
    cid = issue.get("cid")
    receipt = {
        "watchdog": WATCHDOG_NAME,
        "timestamp": iso_now(),
        "cid": cid,
        "lane": agent.get("lane"),
        "phase": agent.get("phase"),
        "unit_id": agent.get("unit_id"),
        "path": agent.get("path"),
        "reason": issue.get("reason"),
        "metrics": issue.get("metrics") if isinstance(issue.get("metrics"), dict) else {},
    }
    runtime_event = ab.append_runtime_event(
        subject,
        {
            "type": "watchdog_alert",
            "run_id": manifest.get("run_id"),
            "task_id": agent.get("unit_id"),
            "session_id": cid,
            "payload": {
                "summary": f"Watchdog alert for {subject}: {issue.get('reason')}",
                **receipt,
            },
        },
    )
    ledger = _safe_ledger(
        ab,
        subject,
        {
            "kind": "ops-event",
            "subject": subject,
            "action": "watchdog.alert",
            "status": "alert",
            "summary": f"Watchdog alert for {subject}: {issue.get('reason')}",
            "cid": cid,
            "lane": agent.get("lane"),
            "phase": agent.get("phase"),
            "unit_id": agent.get("unit_id"),
            "path": agent.get("path"),
            "reason": issue.get("reason"),
            "metrics": receipt["metrics"],
            "runtime_event_id": runtime_event.get("id"),
        },
    )
    pending = create_pending_action(ab, subject, issue, receipt, kind="watchdog_alert")
    return {"runtime_event": runtime_event, "ledger": ledger, "pending_action": pending}


def _safe_ledger(ab: ArcticBaseClient, subject: str, entry: dict[str, Any]) -> dict[str, Any]:
    append = getattr(ab, "append_ledger", None)
    if append is None:
        return {"ok": False, "disabled": True, "entry": entry}
    try:
        return append(subject, entry)
    except Exception as exc:
        return {"ok": False, "error": repr(exc), "entry": entry}


class RefallWatchdog:
    def __init__(
        self,
        *,
        subject: str | None = None,
        repo_root: Path | None = None,
        base_url: str | None = None,
        oh_base: str | None = None,
        log_path: Path | None = None,
        jsonl_path: Path | None = None,
        state_path: Path | None = None,
        dry_run: bool = False,
        arcticbase: ArcticBaseClient | None = None,
        openhands: OHClient | None = None,
        config: WatchdogConfig | None = None,
        now: Any | None = None,
    ) -> None:
        cfg = config or WatchdogConfig(
            subject=subject or DEFAULT_SUBJECT,
            repo_root=repo_root or Path(DEFAULT_REPO_ROOT),
            base_url=base_url or DEFAULT_BASE_URL,
            oh_base=oh_base or DEFAULT_OH_BASE,
            log_path=log_path,
            audit_path=jsonl_path,
            state_path=state_path,
            dry_run=dry_run,
        )
        resolved_log_path, resolved_jsonl_path, resolved_state_path = cfg.paths()
        self.subject = subject or cfg.subject
        self.repo_root = Path(repo_root or cfg.repo_root).expanduser()
        self.base_url = (base_url or cfg.base_url).rstrip("/")
        self.oh_base = (oh_base or cfg.oh_base).rstrip("/")
        self.log_path = Path(log_path or resolved_log_path)
        self.jsonl_path = Path(jsonl_path or resolved_jsonl_path)
        self.state_path = Path(state_path or resolved_state_path)
        self.dry_run = dry_run or cfg.dry_run
        self.enforce = cfg.enforce
        self.no_progress_samples = cfg.no_progress_samples
        self.install_wishlist_items = (
            cfg.install_wishlist_items
            if config is not None
            else _env_bool("REFALL_WATCHDOG_INSTALL_WISHLIST", True)
        )
        self.wishlist_install_timeout_s = (
            cfg.wishlist_install_timeout_seconds
            if config is not None
            else _env_int("REFALL_WATCHDOG_WISHLIST_INSTALL_TIMEOUT_S", 900)
        )
        self.thresholds = cfg.thresholds() if config is not None else thresholds_from_env()
        self.ab = arcticbase or ArcticBaseClient(base=self.base_url)
        self.oh = openhands or OHClient(base=self.oh_base)
        self.now = now or time.time

    def run_once(self) -> dict[str, Any]:
        lock_path = self.state_path.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("w", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            sample = self._run_unlocked()
            return sample

    def _run_unlocked(self) -> dict[str, Any]:
        now = float(self.now())
        state = load_json(self.state_path, {"subjects": {}, "cids": {}})
        endpoints = self._collect_endpoints()
        core_endpoint_names = (
            "ops_agents",
            "ops_debug_live",
            "coverage_stats",
            "runtime_events",
            "runtime_manifest",
            "pending_actions",
            "coverage_context",
        )
        core_endpoint_failures = {
            name: (endpoints.get(name) or {})
            for name in core_endpoint_names
            if not (endpoints.get(name) or {}).get("ok")
        }
        active = [
            item for item in (((endpoints.get("ops_agents") or {}).get("data") or {}).get("active") or [])
            if item.get("subject") == self.subject or item.get("workbench") == self.subject
        ]
        cids = sorted({str(item["cid"]) for item in active if item.get("cid")})
        oh_info = {cid: self._conversation_probe(cid) for cid in cids}
        reconciled = self._reconcile_absent_conversations(active, oh_info, now)
        reconciled_pairs = {
            (str(item.get("workbench") or self.subject), str(cid))
            for item in reconciled
            for cid in item.get("cids", [])
        }
        if reconciled_pairs:
            active = [
                item for item in active
                if (str(item.get("workbench") or self.subject), str(item.get("cid"))) not in reconciled_pairs
            ]
            cids = sorted({str(item["cid"]) for item in active if item.get("cid")})
        events = ((endpoints.get("runtime_events") or {}).get("data") or [])
        if not isinstance(events, list):
            events = []
        manifest = ((endpoints.get("runtime_manifest") or {}).get("data") or {})
        if not isinstance(manifest, dict):
            manifest = {}
        coverage = (endpoints.get("coverage_stats") or {}).get("data")
        live_active = {
            item.get("cid"): item
            for item in ((((endpoints.get("ops_debug_live") or {}).get("data") or {}).get("active") or []))
            if isinstance(item, dict) and item.get("cid")
        }
        context = (endpoints.get("coverage_context") or {}).get("data")
        runtime_index = runtime_by_cid(events)
        issues: list[dict[str, Any]] = []
        stops: list[dict[str, Any]] = []
        wishlist_summary = self._handle_wishlist(endpoints)

        if len(core_endpoint_failures) == len(core_endpoint_names):
            issues.append({
                "scope": "subject",
                "reason": "refall_api_unreachable",
                "metrics": {
                    "base_url": self.base_url,
                    "failed_endpoints": {
                        name: {
                            "status": result.get("status"),
                            "error": result.get("error"),
                        }
                        for name, result in core_endpoint_failures.items()
                    },
                },
            })

        subject_state = state.setdefault("subjects", {}).setdefault(self.subject, {})
        sig = progress_signature(coverage, events, active)
        if subject_state.get("signature") != sig:
            subject_state["signature"] = sig
            subject_state["signature_since"] = now
            subject_state["same_signature_samples"] = 1
        else:
            subject_state["same_signature_samples"] = int(subject_state.get("same_signature_samples") or 0) + 1
        no_progress_for = now - float(subject_state.get("signature_since") or now)

        if active and (not isinstance(context, dict) or not (context.get("info_md") or "").strip()):
            issues.append({"scope": "subject", "reason": "missing_context_while_active", "age_s": 0})
        if active and cids and all(not (oh_info.get(cid) or {}).get("ok") for cid in cids):
            errors = {
                cid: (oh_info.get(cid) or {}).get("error")
                for cid in cids
            }
            issues.append({
                "scope": "subject",
                "reason": "openhands_agent_server_unreachable",
                "metrics": {
                    "failed_cids": cids,
                    "errors": errors,
                },
            })
        latest_cycle = latest_loop_cycle(events)
        latest_cycle_ts = event_ts(latest_cycle or {}) if latest_cycle else None
        if active and (latest_cycle_ts is None or now - latest_cycle_ts > self.thresholds.loop_dead_s):
            issues.append({
                "scope": "subject",
                "reason": "dead_or_stuck_loop_state",
                "age_s": None if latest_cycle_ts is None else round(now - latest_cycle_ts, 3),
            })
        no_progress_by_samples = (
            self.no_progress_samples is not None
            and int(subject_state.get("same_signature_samples") or 0) >= self.no_progress_samples
        )
        if active and (no_progress_for > self.thresholds.no_progress_s or no_progress_by_samples):
            issues.append({"scope": "subject", "reason": "no_progress", "age_s": round(no_progress_for, 3)})

        for agent in active:
            cid = str(agent.get("cid"))
            info_result = oh_info.get(cid) or {}
            info = info_result.get("data") if info_result.get("ok") and isinstance(info_result.get("data"), dict) else {}
            cid_events = runtime_index.get(cid, {"events": [], "start_ts": None, "last_ts": None, "complete": False})
            cid_state = state.setdefault("cids", {}).setdefault(cid, {})
            cid_sig = cid_signature(agent, info, live_active.get(cid), cid_events)
            if cid_state.get("signature") != cid_sig:
                cid_state["signature"] = cid_sig
                cid_state["signature_since"] = now
            stale_for = now - float(cid_state.get("signature_since") or now)
            oh_updated = openhands_updated_ts(info)
            if oh_updated is not None:
                stale_for = max(stale_for, now - oh_updated)
            start_ts = cid_events.get("start_ts") or cid_state.setdefault("first_seen", now)
            runtime_s = max(0.0, now - float(start_ts))
            usage = numeric_usage(info)
            fail_count = failure_refusal_count(info, live_active.get(cid), cid_events.get("events")[-10:])
            metrics = {
                "runtime_s": round(runtime_s, 3),
                "stale_for_s": round(stale_for, 3),
                "tokens": usage["tokens"],
                "cost_usd": usage["cost_usd"],
                "failure_refusal_count": fail_count,
                "openhands_status": info.get("execution_status") or info.get("status"),
                "openhands_info_ok": bool(info_result.get("ok")),
                "openhands_error": info_result.get("error"),
            }
            terminal_status = str(metrics["openhands_status"] or "").lower()
            if (
                terminal_status in {"finished", "error", "stopped", "paused"}
                and str(agent.get("status")).lower() == "running"
                and stale_for > self.thresholds.terminal_grace_s
            ):
                issues.append({"scope": "cid", "cid": cid, "agent": agent, "reason": "active_agent_terminal_in_openhands", "metrics": metrics})
            if stale_for > self.thresholds.stale_agent_s:
                issue = {"scope": "cid", "cid": cid, "agent": agent, "reason": "stale_active_agent", "metrics": metrics}
                issues.append(issue)
                if stale_for > self.thresholds.stop_no_progress_s:
                    stops.append(issue)
            if runtime_s > self.thresholds.max_runtime_s:
                issue = {"scope": "cid", "cid": cid, "agent": agent, "reason": "excessive_runtime", "metrics": metrics}
                issues.append(issue)
                stops.append(issue)
            if usage["tokens"] > self.thresholds.max_tokens:
                issue = {"scope": "cid", "cid": cid, "agent": agent, "reason": "token_ceiling", "metrics": metrics}
                issues.append(issue)
                stops.append(issue)
            if usage["cost_usd"] > self.thresholds.max_cost_usd:
                issue = {"scope": "cid", "cid": cid, "agent": agent, "reason": "excessive_cost_usage", "metrics": metrics}
                issues.append(issue)
                stops.append(issue)
            if fail_count >= self.thresholds.failure_refusal_count:
                issue = {"scope": "cid", "cid": cid, "agent": agent, "reason": "repeated_failures_refusals", "metrics": metrics}
                issues.append(issue)
                stops.append(issue)

        stop_keys = {(issue.get("cid"), issue.get("reason")) for issue in self._dedupe_stops(stops)}
        alert_records = []
        for issue in self._dedupe_issues(issues):
            key = (issue.get("cid"), issue.get("reason"))
            if key in stop_keys:
                continue
            if issue.get("reason") == "refall_api_unreachable":
                alert_records.append({"local_only": True, "issue": issue})
                continue
            if self.dry_run:
                alert_records.append({"dry_run": True, "issue": issue})
                continue
            try:
                alert_records.append(append_alert_records(self.ab, self.subject, manifest, issue))
            except Exception as exc:
                alert_records.append({"ok": False, "error": repr(exc), "traceback": traceback.format_exc(limit=4), "issue": issue})

        stop_records = []
        for issue in self._dedupe_stops(stops):
            metrics = issue.get("metrics") if isinstance(issue.get("metrics"), dict) else {}
            delete_result = {"ok": False, "dry_run": True} if self.dry_run or not self.enforce else self._delete_conversation(str(issue["cid"]))
            if delete_result.get("ok") and not self.dry_run and self.enforce:
                try:
                    stop_records.append(append_stop_records(self.ab, self.subject, manifest, issue, metrics, delete_result))
                except Exception as exc:
                    stop_records.append({"ok": False, "error": repr(exc), "traceback": traceback.format_exc(limit=4), "issue": issue})
            else:
                stop_records.append({"delete_result": delete_result, "issue": issue})

        sample = {
            "timestamp": iso_now(),
            "subject": self.subject,
            "base_url": self.base_url,
            "oh_base": self.oh_base,
            "active_count": len(active),
            "active_cids": cids,
            "reconciled_absent_cids": sorted({
                str(cid) for item in reconciled for cid in item.get("cids", [])
            }),
            "reconciliation": reconciled,
            "endpoints": summarize_endpoint_payloads(endpoints),
            "openhands": oh_info,
            "issues": issues,
            "findings": issues,
            "alerts": alert_records,
            "stops": stop_records,
            "stopped": stop_records,
            "wishlist": wishlist_summary,
            "crash_policy_reasons": sorted({
                str(issue.get("reason"))
                for issue in issues
                if issue.get("reason") in CRASH_POLICY_REASONS
            }),
            "thresholds": self.thresholds.__dict__,
            "dry_run": self.dry_run,
        }
        state["last_sample_at"] = now
        state["last_active_cids"] = cids
        save_json(self.state_path, state)
        append_jsonl(self.jsonl_path, sample)
        status = "ok" if not issues else "issues"
        append_text(self.log_path, f"{iso_now()} subject={self.subject} status={status} active={len(active)} issues={len(issues)} stops={len(stop_records)}")
        return sample

    def _collect_endpoints(self) -> dict[str, Any]:
        calls = {
            "ops_agents": lambda: self.ab.ops_agents(),
            "ops_debug_live": lambda: self.ab.ops_debug_live(self.subject),
            "coverage_stats": lambda: self.ab.coverage_stats(self.subject),
            "runtime_events": lambda: self.ab.list_runtime_events(self.subject),
            "runtime_manifest": lambda: self.ab.get_runtime_manifest(self.subject),
            "pending_actions": lambda: self.ab.list_pending_actions(self.subject),
            "coverage_context": lambda: self.ab.get_coverage_context(self.subject),
            "wishlist_open": lambda: self.ab.list_wishlist(self.subject, status="open"),
            "wishlist_provided": lambda: self.ab.list_wishlist(self.subject, status="provided"),
        }
        return {name: self._safe_call(fn) for name, fn in calls.items()}

    def _handle_wishlist(self, endpoints: dict[str, Any]) -> dict[str, Any]:
        open_result = endpoints.get("wishlist_open") or {}
        provided_result = endpoints.get("wishlist_provided") or {}
        open_items = open_result.get("data") if open_result.get("ok") else []
        provided_items = provided_result.get("data") if provided_result.get("ok") else []
        if not isinstance(open_items, list):
            open_items = []
        if not isinstance(provided_items, list):
            provided_items = []

        provided_keys = {
            wishlist_item_key(item)
            for item in provided_items
            if isinstance(item, dict) and wishlist_item_key(item)
        }
        provided_records = []
        install_attempts = []
        unhandled = []

        for item in open_items:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "").lower()
            tool = normalize_wishlist_tool(item.get("item"))
            if not tool or (kind and kind not in {"tool", "cli", "binary", "package", "dependency"}):
                unhandled.append({"item": item, "reason": "unsupported_wishlist_kind"})
                continue
            if tool in provided_keys:
                continue
            if shutil.which(tool):
                provided_records.append(self._record_wishlist_provided(item, tool, {"mode": "already_available"}))
                provided_keys.add(tool)
                continue
            if self.dry_run:
                unhandled.append({"item": item, "reason": "dry_run_install_skipped", "tool": tool})
                continue
            if not self.install_wishlist_items:
                unhandled.append({"item": item, "reason": "install_disabled"})
                continue
            installer = WISHLIST_INSTALLERS.get(tool)
            if not installer:
                unhandled.append({"item": item, "reason": "no_allowlisted_installer", "tool": tool})
                continue
            install_result = self._install_wishlist_tool(tool, installer)
            install_attempts.append({"item": item, "tool": tool, "result": install_result})
            if install_result.get("ok") and shutil.which(tool):
                provided_records.append(self._record_wishlist_provided(item, tool, {"mode": "installed", "install_result": install_result}))
                provided_keys.add(tool)
            else:
                unhandled.append({"item": item, "reason": "install_failed", "tool": tool, "install_result": install_result})

        return {
            "open_count": len(open_items),
            "provided_count": len(provided_records),
            "provided": provided_records,
            "install_attempts": install_attempts,
            "unhandled": unhandled,
            "endpoint_ok": {
                "open": bool(open_result.get("ok")),
                "provided": bool(provided_result.get("ok")),
            },
        }

    def _record_wishlist_provided(self, source_item: dict[str, Any], tool: str, receipt: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "subject": self.subject,
            "kind": source_item.get("kind") or "tool",
            "item": tool,
            "reason": f"Watchdog provided requested wishlist item from {source_item.get('id') or 'unknown'}",
            "requested_by": WATCHDOG_NAME,
            "status": "provided",
        }
        if self.dry_run:
            return {"dry_run": True, "request": payload, "receipt": receipt}
        created = self.ab.create_wishlist_item(self.subject, payload)
        ledger = _safe_ledger(
            self.ab,
            self.subject,
            {
                "kind": "ops-event",
                "subject": self.subject,
                "action": "watchdog.wishlist.provided",
                "status": "provided",
                "summary": f"Watchdog provided wishlist tool {tool}",
                "wishlist_item_id": source_item.get("id"),
                "provided_wishlist_item_id": created.get("id") if isinstance(created, dict) else None,
                "tool": tool,
                "receipt": receipt,
            },
        )
        return {"source": source_item, "created": created, "ledger": ledger, "receipt": receipt}

    def _install_wishlist_tool(self, tool: str, commands: list[list[str]]) -> dict[str, Any]:
        attempts = []
        for command in commands:
            try:
                proc = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self.wishlist_install_timeout_s,
                    check=False,
                )
            except Exception as exc:
                attempts.append({"command": command, "ok": False, "error": repr(exc)})
                continue
            attempts.append({
                "command": command,
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout_tail": proc.stdout[-2000:],
                "stderr_tail": proc.stderr[-2000:],
            })
            if proc.returncode == 0:
                return {"ok": True, "tool": tool, "attempts": attempts}
        return {"ok": False, "tool": tool, "attempts": attempts}

    def _conversation_probe(self, cid: str) -> dict[str, Any]:
        probe = getattr(self.oh, "conversation_probe", None)
        if probe is None:
            return self._safe_call(lambda: self.oh.conversation_info(cid))
        try:
            status, data = probe(cid)
            return {
                "ok": status < 500,
                "status": status,
                "data": data if isinstance(data, dict) else {},
            }
        except Exception as exc:
            return {"ok": False, "status": None, "error": repr(exc)}

    def _reconcile_absent_conversations(
        self,
        active: list[dict[str, Any]],
        probes: dict[str, dict[str, Any]],
        now: float,
    ) -> list[dict[str, Any]]:
        """Remove only conversations that Canvas definitively reports as 404.

        Network errors and 5xx responses are deliberately ignored.  The state
        file is updated atomically, while runtime and ledger records preserve
        why the bookkeeping changed.
        """
        if self.dry_run or not self.enforce:
            return []
        missing_by_workbench: dict[str, set[str]] = {}
        for agent in active:
            cid = str(agent.get("cid") or "")
            probe = probes.get(cid) or {}
            if cid and probe.get("status") == 404:
                workbench = str(agent.get("workbench") or self.subject)
                missing_by_workbench.setdefault(workbench, set()).add(cid)

        records: list[dict[str, Any]] = []
        for workbench, missing in sorted(missing_by_workbench.items()):
            try:
                wb = self.ab.get_workbench(workbench)
            except Exception:
                continue
            fields = wb.get("custom_fields") if isinstance(wb.get("custom_fields"), dict) else {}
            roots = [wb.get("local_path"), fields.get("refall_subject_path")]
            seen_paths: set[str] = set()
            for raw_root in roots:
                if not raw_root:
                    continue
                state_path = Path(str(raw_root)).expanduser() / ".refall" / "loop_state.json"
                path_key = str(state_path)
                if path_key in seen_paths or not state_path.is_file():
                    continue
                seen_paths.add(path_key)
                state = load_json(state_path, None)
                if not isinstance(state, dict) or not isinstance(state.get("active"), list):
                    continue
                removed = [
                    str(item.get("cid")) for item in state["active"]
                    if isinstance(item, dict) and str(item.get("cid") or "") in missing
                ]
                if not removed:
                    continue
                state["active"] = [
                    item for item in state["active"]
                    if not (isinstance(item, dict) and str(item.get("cid") or "") in missing)
                ]
                state["active_count"] = len(state["active"])
                if not state["active"]:
                    state["status"] = "idle"
                state["current_target"] = f"{len(state['active'])} active agents (Canvas state reconciled)"
                state["last_updated"] = datetime.fromtimestamp(now, timezone.utc).isoformat()
                save_json(state_path, state)

                payload = {
                    "summary": f"Reconciled {len(removed)} absent Agent Canvas conversation(s)",
                    "watchdog": WATCHDOG_NAME,
                    "cids": sorted(removed),
                    "reason": "canvas_conversation_not_found",
                    "state_path": str(state_path),
                }
                try:
                    runtime_event = self.ab.append_runtime_event(
                        workbench,
                        {
                            "type": "canvas_state_reconciled",
                            "payload": payload,
                        },
                    )
                except Exception as exc:
                    runtime_event = {"ok": False, "error": repr(exc)}
                ledger = _safe_ledger(
                    self.ab,
                    workbench,
                    {
                        "kind": "ops-event",
                        "subject": workbench,
                        "action": "watchdog.canvas_state.reconciled",
                        "status": "reconciled",
                        "summary": payload["summary"],
                        "cids": sorted(removed),
                        "reason": payload["reason"],
                        "runtime_event_id": runtime_event.get("id"),
                    },
                )
                cancellations = self._cancel_reconciled_pending_actions(
                    workbench,
                    set(removed),
                    runtime_event,
                )
                records.append({
                    "workbench": workbench,
                    "cids": sorted(removed),
                    "state_path": str(state_path),
                    "runtime_event": runtime_event,
                    "ledger": ledger,
                    "pending_action_cancellations": cancellations,
                })
        return records

    def _cancel_reconciled_pending_actions(
        self,
        workbench: str,
        removed_cids: set[str],
        runtime_event: dict[str, Any],
    ) -> list[dict[str, Any]]:
        event_id = str(runtime_event.get("id") or "").strip()
        if not event_id:
            return [{
                "action_id": None,
                "ok": False,
                "error": "reconciliation runtime event was not persisted",
            }]
        try:
            pending = self.ab.list_pending_actions(workbench)
        except Exception as exc:
            return [{"action_id": None, "ok": False, "error": repr(exc)}]
        if not isinstance(pending, list):
            return []

        results: list[dict[str, Any]] = []
        allowed_kinds = {"watchdog_conversation_stopped", "watchdog_alert"}
        for action in pending:
            if not isinstance(action, dict):
                continue
            if action.get("status") not in {"open", "claimed"}:
                continue
            kind = str(action.get("kind") or "")
            if kind not in allowed_kinds:
                continue
            text = f"{action.get('title') or ''}\n{action.get('description') or ''}"
            matching_cids = sorted(cid for cid in removed_cids if cid in text)
            if not matching_cids:
                continue
            action_id = str(action.get("id") or "")
            receipt_type = action.get("required_receipt_type") or (
                "watchdog_stop_review"
                if kind == "watchdog_conversation_stopped"
                else "watchdog_alert_review"
            )
            receipt = {
                "summary": "Cancelled stale watchdog action after Canvas-state reconciliation",
                "evidence_refs": [event_id],
                "reconciled_cids": matching_cids,
                "reason": "canvas_conversation_not_found",
            }
            try:
                cancelled = self.ab.cancel_pending_action(
                    workbench,
                    action_id,
                    receipt,
                    receipt_type=receipt_type,
                    resolved_by=WATCHDOG_NAME,
                )
                results.append({
                    "action_id": action_id,
                    "ok": True,
                    "status": cancelled.get("status") if isinstance(cancelled, dict) else None,
                    "receipt_type": receipt_type,
                })
            except Exception as exc:
                results.append({"action_id": action_id, "ok": False, "error": repr(exc)})
        return results

    def _delete_conversation(self, cid: str) -> dict[str, Any]:
        return self._safe_call(lambda: self.oh.delete(cid))

    def _dedupe_stops(self, issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._dedupe_issues(issues)

    def _dedupe_issues(self, issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen = set()
        out = []
        for issue in issues:
            key = (issue.get("cid"), issue.get("reason"))
            if key in seen:
                continue
            seen.add(key)
            out.append(issue)
        return out

    @staticmethod
    def _safe_call(fn: Any) -> dict[str, Any]:
        try:
            return {"ok": True, "status": 200, "data": fn()}
        except Exception as exc:
            return {"ok": False, "status": None, "error": repr(exc)}


def discover_subjects(base_url: str) -> list[str]:
    client = ArcticBaseClient(base=base_url)
    try:
        subjects = client.list_subjects()
    except Exception:
        return []
    out: list[str] = []
    for item in subjects:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug") or item.get("subject") or "").strip()
        if slug:
            out.append(slug)
    return sorted(set(out))


def render_cron_entry(
    repo_root: Path,
    *,
    interval_minutes: int = 5,
    subject: str = "all",
    base_url: str = DEFAULT_BASE_URL,
    oh_base: str = DEFAULT_OH_BASE,
    marker: str = CRON_MARKER,
) -> str:
    interval = max(1, int(interval_minutes))
    root = str(Path(repo_root).expanduser())
    return (
        f"*/{interval} * * * * "
        f"REFALL_REPO_ROOT={root} "
        f"REFALL_PUBLIC_BASE_URL={base_url} "
        f"REFALL_WORKBENCH_BASE={base_url} "
        f"REFALL_OPENHANDS_BASE={oh_base} "
        f"REFALL_WATCHDOG_SUBJECT={subject} "
        f"{root}/deploy/cron/refall-watchdog-cron.sh # {marker}"
    )


def merge_crontab(existing: str, entry: str, *, marker_prefix: str = CRON_MARKER) -> str:
    lines = []
    for line in existing.splitlines():
        if marker_prefix in line or "refall-watchdog-cron.sh" in line:
            continue
        if line.strip():
            lines.append(line.rstrip())
    lines.append(entry.rstrip())
    return "\n".join(lines) + "\n"


def install_cron(
    *,
    repo_root: Path,
    interval_minutes: int = 5,
    subject: str = "all",
    base_url: str = DEFAULT_BASE_URL,
    oh_base: str = DEFAULT_OH_BASE,
) -> dict[str, Any]:
    entry = render_cron_entry(
        repo_root,
        interval_minutes=interval_minutes,
        subject=subject,
        base_url=base_url,
        oh_base=oh_base,
    )
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    existing = current.stdout if current.returncode == 0 else ""
    merged = merge_crontab(existing, entry)
    subprocess.run(["crontab", "-"], input=merged, text=True, check=True)
    return {"installed": True, "entry": entry, "marker": CRON_MARKER}


def run_watchdog_subjects(
    *,
    subject: str,
    repo_root: Path,
    base_url: str,
    oh_base: str,
    log_path: Path | None,
    jsonl_path: Path | None,
    state_path: Path | None,
    dry_run: bool,
) -> list[dict[str, Any]]:
    subjects = discover_subjects(base_url) if subject in {"all", "*"} else [subject]
    if not subjects:
        subjects = [subject]
    samples: list[dict[str, Any]] = []
    for slug in subjects:
        samples.append(
            RefallWatchdog(
                subject=slug,
                repo_root=repo_root,
                base_url=base_url,
                oh_base=oh_base,
                log_path=log_path,
                jsonl_path=jsonl_path,
                state_path=state_path,
                dry_run=dry_run,
            ).run_once()
        )
    return samples


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="refall-watchdog")
    parser.add_argument("--subject", default=os.environ.get("REFALL_WATCHDOG_SUBJECT", DEFAULT_SUBJECT))
    parser.add_argument("--repo-root", default=os.environ.get("REFALL_REPO_ROOT", DEFAULT_REPO_ROOT))
    parser.add_argument("--base-url", default=os.environ.get("REFALL_PUBLIC_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--oh-base", default=os.environ.get("REFALL_OPENHANDS_BASE", DEFAULT_OH_BASE))
    parser.add_argument("--log-path", default=None)
    parser.add_argument("--jsonl-path", default=None)
    parser.add_argument("--state-path", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--install-cron", action="store_true")
    parser.add_argument("--interval-minutes", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    repo_root = Path(args.repo_root).expanduser()
    log_path = Path(args.log_path) if args.log_path else repo_root / "logs/refall-watchdog-cron.log"
    jsonl_path = Path(args.jsonl_path) if args.jsonl_path else repo_root / "logs/refall-watchdog-cron.jsonl"
    state_path = Path(args.state_path) if args.state_path else repo_root / "logs/refall-watchdog-state.json"
    if args.install_cron:
        out = install_cron(
            repo_root=repo_root,
            interval_minutes=args.interval_minutes,
            subject=args.subject,
            base_url=args.base_url,
            oh_base=args.oh_base,
        )
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0
    try:
        samples = run_watchdog_subjects(
            subject=args.subject,
            repo_root=repo_root,
            base_url=args.base_url,
            oh_base=args.oh_base,
            log_path=log_path,
            jsonl_path=jsonl_path,
            state_path=state_path,
            dry_run=args.dry_run,
        )
    except BlockingIOError:
        append_text(log_path, f"{iso_now()} subject={args.subject} status=skipped reason=lock_held")
        return 0
    except Exception as exc:
        row = {"timestamp": iso_now(), "subject": args.subject, "status": "watchdog_error", "error": repr(exc), "traceback": traceback.format_exc(limit=8)}
        append_jsonl(jsonl_path, row)
        append_text(log_path, f"{iso_now()} subject={args.subject} status=watchdog_error error={exc!r}")
        print(json.dumps(row, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps({
        "timestamp": iso_now(),
        "subject": args.subject,
        "subjects_checked": [sample["subject"] for sample in samples],
        "active_count": sum(int(sample["active_count"]) for sample in samples),
        "issues": [issue for sample in samples for issue in sample["issues"]],
        "stops": [stop for sample in samples for stop in sample["stops"]],
    }, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
