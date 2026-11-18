from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import socket
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from . import config
from .arcticbase_client import ArcticBaseClient
from .coverage_client import CoverageClient
from .oh_client import OHClient, TERMINAL
from .report_draft import draft_report
from .report_enrich import enrich_workbench_report
from .runtime_invocation import InvocationOutcome, classify_invocation, record_retry_failure
from .runtime_state import connect_runtime
from .router import route
from .source_inventory import build_source_inventory
from .work_modules import (
    SUBJECT_TARGET as SUBJECT_MODULE_TARGET,
    ModuleRegistry,
    ModuleScheduler,
    WorkModule,
    load_subject_config,
)
from .structured_submit import coverage_paths_from_submission, parse_refall_submissions, primary_submission


EVENT_TERMINAL = TERMINAL | {
    "failed",
    "complete",
    "completed",
    "output_truncated",
    "capability_missing",
    "scope_blocked",
    "operator_stop",
    "tool_execution_error",
    "agent_canvas_transport_error",
    "provider_unavailable",
    "provider_timeout",
    "provider_rate_limited",
    "agent_canvas_session_lost",
}


@dataclass
class StandingLoopConfig:
    max_cycles: int = 0
    max_parallel: int = 4
    poll_interval_s: float = 5
    report_interval_cycles: int = 10
    visualization_min_findings: int = 3
    visualization_min_resolved_pct: float = 25.0
    stall_cycles: int = 36
    # Dispatch a report-writing agent once this many NEW intel items
    # (facts + leads + findings) have accumulated since the last one. It takes a
    # single parallel slot for that cycle (3 analysis + 1 report), then the loop
    # returns to full analysis. 0 disables it.
    report_agent_intel_threshold: int = 30


@dataclass
class AgentTask:
    subject: str
    task_class: str
    lane: str
    unit: dict | None
    objective: str
    max_iterations: int = 30
    attempt: int = 1
    # Work-module provenance. `module_id`/`module_target` let the loop mark
    # per-target module progress on completion; `submits_coverage` is True only
    # for the breadth (characterize) module, so follow-on modules do not
    # re-transition a unit's coverage state.
    module_id: str | None = None
    module_target: str | None = None
    submits_coverage: bool = False


@dataclass
class DispatchedConversation:
    cid: str
    subject: str
    lane: str
    task_class: str
    unit: dict | None
    objective: str
    attempt: int = 1
    started_at: float = field(default_factory=time.time)
    module_id: str | None = None
    module_target: str | None = None
    submits_coverage: bool = False
    workspace_host: str | None = None


@dataclass
class PollResult:
    cid: str
    status: str
    response: str = ""
    trajectory: bytes = b""


@dataclass
class ParsedOutput:
    findings: list[dict] = field(default_factory=list)
    facts: list[dict] = field(default_factory=list)
    leads: list[dict] = field(default_factory=list)
    flows: list[dict] = field(default_factory=list)
    asks: list[dict] = field(default_factory=list)
    pending_actions: list[dict] = field(default_factory=list)
    coverage: list[str] = field(default_factory=list)
    done: str = ""
    structured: list[dict] = field(default_factory=list)
    structured_errors: list[str] = field(default_factory=list)
    structured_missing: bool = False
    transitions: list[dict] = field(default_factory=list)
    capability_requests: list[dict] = field(default_factory=list)
    threat_models: list[dict] = field(default_factory=list)


def read_conversation_agent_text(cid: str, conversations_dir: str | None = None) -> str:
    """All text the agent produced across the whole conversation.

    Reads the Agent Canvas event stream from disk (bind-mounted at
    <conversations>/<cid-without-dashes>/events/event-*.json) and concatenates
    every agent-authored message and action text, in order. This is the
    authoritative source of an agent's [FACT]/[FLOW]/[LEAD]/```finding /
    ```refall-submit output -- the `agent_final_response` endpoint returns empty
    for ACP agents, which end on a tool call rather than a final message.

    Parsing EVERY agent response (not just a "final" one) means an agent that
    emits intel across several turns is fully captured, and one that emits a
    single comprehensive message is captured too.
    """
    root = Path(conversations_dir or config.OPENHANDS_CONVERSATIONS_DIR)
    events = next(
        (candidate / "events" for candidate in (root / cid.replace("-", ""), root / cid)
         if (candidate / "events").is_dir()),
        None,
    )
    if events is None:
        return ""
    texts: list[str] = []
    for path in sorted(events.glob("event-*.json")):
        try:
            event = json.loads(path.read_text(errors="replace"))
        except Exception:
            continue
        if event.get("source") != "agent":
            continue
        if event.get("kind") == "MessageEvent":
            # Agent Canvas currently stores message chunks directly in
            # `content`; older releases nested them under `llm_message`.
            # Accept both because persisted conversations span upgrades.
            chunks = event.get("content")
            if chunks is None:
                chunks = (event.get("llm_message", {}) or {}).get("content", [])
            if isinstance(chunks, str):
                texts.append(chunks)
                chunks = []
            for chunk in chunks or []:
                if isinstance(chunk, dict) and chunk.get("type") == "text" and chunk.get("text"):
                    texts.append(chunk["text"])
        action = event.get("action")
        if isinstance(action, dict) and action.get("message"):
            texts.append(action["message"])
    return "\n\n".join(texts)


def _with_resource_context(objective: str) -> str:
    resources = config.ssh_resource_instructions()
    if not resources or "## Remote SSH Resources" in objective:
        return objective
    return f"{resources}\n\n{objective}"


def _with_workspace_context(subject: str, workspace: str, objective: str) -> str:
    if "## REFALL Workspace Layout" in objective:
        return objective
    source = config.subject_workspace(subject)
    layout = (
        "## REFALL Workspace Layout\n"
        f"- Writable agent workspace: `{workspace}`\n"
        f"- Read-only subject source root: `{source}`\n"
        f"Run local analysis commands from the writable workspace, but inspect target files under `{source}`. "
        f"Do not write to `{source}`; place scratch files, extracted metadata, notes, and temporary outputs under `{workspace}`."
    )
    return f"{layout}\n\n{objective}"


class AgentCanvasDispatcher:
    def __init__(self, oh: OHClient | None = None) -> None:
        self.oh = oh or OHClient()

    def start(self, task: AgentTask) -> DispatchedConversation:
        workspace = config.prepare_subject_agent_workspace(
            task.subject,
            lane=task.lane,
            task_class=task.task_class,
            unit=task.unit,
            objective=task.objective,
        )
        workspace_host = str(config.agent_workspace_host_path(
            task.subject, lane=task.lane, task_class=task.task_class,
            unit=task.unit, objective=task.objective,
        ))
        objective = _with_workspace_context(task.subject, workspace, _with_resource_context(task.objective))
        cid = self.oh.start_conversation(
            workspace=config.local_workspace(workspace),
            agent_settings=config.LANES[task.lane],
            text=objective,
            max_iterations=task.max_iterations,
        )
        return DispatchedConversation(
            cid=cid,
            subject=task.subject,
            lane=task.lane,
            task_class=task.task_class,
            unit=task.unit,
            objective=objective,
            attempt=task.attempt,
            module_id=task.module_id,
            module_target=task.module_target,
            submits_coverage=task.submits_coverage,
            workspace_host=workspace_host,
        )

    def poll(self, active: DispatchedConversation) -> PollResult:
        try:
            status = self.oh.execution_status(active.cid) or "unknown"
        except Exception:
            # A transient Agent Canvas / proxy failure (e.g. the OpenHands
            # agent-server briefly returning 502 under load) must NOT crash the
            # standing loop. Treat this poll as "still running" and retry on the
            # next cycle; the conversation stays active and completes once the
            # canvas recovers.
            return PollResult(cid=active.cid, status="unknown")
        if status not in EVENT_TERMINAL:
            return PollResult(cid=active.cid, status=status)
        # The real output is the agent's own messages in the CONVERSATION EVENT
        # STREAM -- every [FACT]/[FLOW]/[LEAD]/```finding/```refall-submit the
        # agent emitted, across all its responses. The agent_final_response
        # endpoint returns EMPTY for ACP agents (they end on a tool call), so it
        # cannot be the source. Read the events (all agent responses) and combine
        # with whatever final_response yields; dedup downstream makes overlap safe.
        response = read_conversation_agent_text(active.cid)
        if not response.strip():
            response = self._safe_final_response(active.cid)
        try:
            trajectory = self.oh.download_trajectory(active.cid)
        except Exception:
            trajectory = b""
        return PollResult(cid=active.cid, status=status, response=response, trajectory=trajectory)

    def _safe_final_response(self, cid: str) -> str:
        try:
            return self.oh.final_response(cid)
        except Exception:
            return ""

    def delete(self, cid: str) -> None:
        self.oh.delete(cid)


class RefallStandingLoop:
    def __init__(
        self,
        subject: str,
        *,
        workbench: str | None = None,
        coverage: CoverageClient | None = None,
        arcticbase: ArcticBaseClient | None = None,
        dispatcher: AgentCanvasDispatcher | None = None,
        config: StandingLoopConfig | None = None,
        sleep: Callable[[float], None] = time.sleep,
        draft_reporter: Callable[[str, str], dict] | None = None,
        enrich_reporter: Callable[[str, str], dict] | None = None,
    ) -> None:
        self.subject = subject
        self.workbench = workbench or subject
        self.coverage = coverage or CoverageClient(workbench_slug=self.workbench)
        self.arcticbase = arcticbase or ArcticBaseClient()
        self.dispatcher = dispatcher or AgentCanvasDispatcher()
        self.config = config or _config_from_env()
        self.sleep = sleep
        self.draft_reporter = draft_reporter or draft_report
        self.enrich_reporter = enrich_reporter or enrich_workbench_report
        self.subject_path = self._resolve_subject_path()
        self.run_id: str | None = None
        self.checkpoint_ids: list[str] = []
        self.source_inventory: dict | None = None
        self.scope_overlay: dict | None = None
        self.threat_model: dict | None = None
        self.threat_model_dispatched = False
        self.dispatch_lane_pattern = self._load_dispatch_lane_pattern()
        self.dispatch_lane_index = 0
        self.report_agent_continuous, self.report_agent_lane = self._load_report_agent_policy()
        self.module_registry = self._build_module_registry()
        self.scheduler = ModuleScheduler(
            self.module_registry, self._load_module_progress()
        )
        # Intel count (facts+leads+findings) at the last report-agent dispatch,
        # so a report agent fires once each `report_agent_intel_threshold` of new
        # intel accumulates. Persisted so a restart does not immediately re-fire.
        self.last_report_intel = int(self._load_module_progress().get("last_report_intel") or 0)
        # Stable identities of intel already persisted this run, so the real-time
        # incremental path and the terminal salvage path never double-write.
        self._ingested_keys: set[tuple] = set()

    def _build_module_registry(self) -> ModuleRegistry:
        """Load this subject's work-module config off the workbench.

        Any failure falls back to the default (a security assessment) rather
        than stopping the loop -- a bad module config must never prevent work.
        """
        try:
            workbench = self.arcticbase.get_workbench(self.workbench)
            return ModuleRegistry.from_config(load_subject_config(workbench))
        except Exception as exc:
            self._append_event(
                "module_config_fallback",
                {"subject": self.subject, "error": str(exc)[:300]},
            )
            return ModuleRegistry.from_config(None)

    def _load_dispatch_lane_pattern(self) -> tuple[str, ...]:
        raw: object = os.environ.get("REFALL_LANE_PATTERN") or os.environ.get("REFALL_CHARACTERIZE_LANE_PATTERN", "")
        try:
            workbench = self.arcticbase.get_workbench(self.workbench)
            custom = workbench.get("custom_fields") or {}
            raw = custom.get("refall_lane_pattern") or custom.get("refall_characterize_lane_pattern") or raw
        except Exception as exc:
            self._append_event(
                "dispatch_lane_pattern_unavailable",
                {"subject": self.subject, "error": str(exc)[:300]},
            )
        if isinstance(raw, str):
            parts = [part.strip() for part in raw.split(",")]
        elif isinstance(raw, list):
            parts = [str(part).strip() for part in raw]
        else:
            parts = []
        lanes = tuple(part for part in parts if part in config.LANES)
        return lanes

    def _load_report_agent_policy(self) -> tuple[bool, str | None]:
        continuous: object = os.environ.get("REFALL_LOOP_REPORT_AGENT_CONTINUOUS", "false")
        lane: object = os.environ.get("REFALL_LOOP_REPORT_AGENT_LANE", "")
        try:
            workbench = self.arcticbase.get_workbench(self.workbench)
            custom = workbench.get("custom_fields") or {}
            continuous = custom.get("refall_report_agent_continuous", continuous)
            lane = custom.get("refall_report_lane", lane)
        except Exception as exc:
            self._append_event(
                "report_agent_policy_unavailable",
                {"subject": self.subject, "error": str(exc)[:300]},
            )
        enabled = str(continuous).strip().lower() in {"1", "true", "yes", "on"}
        selected_lane = str(lane).strip()
        return enabled, selected_lane if selected_lane in config.LANES else None

    def _lane_pattern_targets(self) -> dict[str, int]:
        targets: dict[str, int] = {}
        for lane in self.dispatch_lane_pattern:
            targets[lane] = targets.get(lane, 0) + 1
        return targets

    def _next_dispatch_lane(
        self,
        default_lane: str,
        active: list[DispatchedConversation] | None = None,
    ) -> str:
        if not self.dispatch_lane_pattern:
            return default_lane
        if active:
            targets = self._lane_pattern_targets()
            current: dict[str, int] = {}
            for conversation in active:
                if conversation.task_class == "report":
                    continue
                current[conversation.lane] = current.get(conversation.lane, 0) + 1
            deficits = [
                (targets[lane] - current.get(lane, 0), index, lane)
                for index, lane in enumerate(self.dispatch_lane_pattern)
                if current.get(lane, 0) < targets[lane]
            ]
            if deficits:
                deficit, _index, lane = max(deficits)
                if deficit > 0:
                    return lane
        lane = self.dispatch_lane_pattern[
            self.dispatch_lane_index % len(self.dispatch_lane_pattern)
        ]
        self.dispatch_lane_index += 1
        return lane

    def _route_with_dispatch_pattern(
        self,
        task_class: str,
        active: list[DispatchedConversation] | None = None,
    ) -> tuple[str, str]:
        decision = route(task_class)
        lane = self._next_dispatch_lane(decision.lane, active)
        reason = decision.reason
        if lane != decision.lane:
            reason = f"{reason} Lane pattern override selected lane {lane} for this dispatch."
        return lane, reason

    def _module_progress_path(self) -> Path:
        return self.subject_path / ".refall" / "module_progress.json"

    def _load_module_progress(self) -> dict:
        try:
            return json.loads(self._module_progress_path().read_text())
        except Exception:
            return {}

    def _save_module_progress(self) -> None:
        try:
            path = self._module_progress_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            state = self.scheduler.to_state()
            state["last_report_intel"] = self.last_report_intel
            path.write_text(json.dumps(state, indent=2, sort_keys=True))
        except Exception as exc:
            self._append_event(
                "module_progress_save_failed",
                {"subject": self.subject, "error": str(exc)[:300]},
            )

    def run(self) -> dict:
        self._ensure_dirs()
        state = self._load_state()
        self.run_id = str(state.get("run_id") or f"run_{uuid.uuid4().hex}")
        self.checkpoint_ids = []
        self.source_inventory = None
        self.scope_overlay = None
        self.threat_model = None
        self.threat_model_dispatched = False
        active = [self._active_from_dict(item) for item in state.get("active", [])]
        cycle = int(state.get("iteration") or 0)
        completed = 0
        dispatched = 0
        last_completion_cycle = int(state.get("last_completion_cycle") or cycle)
        self._latest_source_inventory()
        if active:
            self._load_resume_source_inventory()
        if active and self._resume_preflight_refused():
            final_state = self._write_state(cycle, active, "resume_blocked", last_completion_cycle)
            self._write_checkpoint(
                "resume",
                "resume:blocked",
                "blocked",
                {"active": len(active), "cycle": cycle},
            )
            self._write_run_manifest("resume_blocked", cycle, active, final_state)
            return {
                "subject": self.subject,
                "workbench": self.workbench,
                "status": "resume_blocked",
                "cycles": cycle,
                "active": len(active),
                "completed": completed,
                "dispatched": dispatched,
                "enumerated": 0,
                "state": final_state,
            }
        enumerated = self._auto_enumerate_if_empty()

        self._append_event("loop_start", {"subject": self.subject, "active": len(active)})
        self._write_run_manifest("running", cycle, active)
        while True:
            if self.config.max_cycles and cycle >= self.config.max_cycles + int(state.get("iteration") or 0):
                break
            cycle += 1
            gate = self._safe_gate()
            coverage_stats = self._safe_coverage()
            self._append_event(
                "loop_cycle",
                {
                    "subject": self.subject,
                    "cycle": cycle,
                    "active": len(active),
                    "coverage_pct": coverage_stats.get("resolved_pct", 0),
                    "gate_locked": gate.get("locked"),
                },
            )

            claimed_this_cycle = 0
            if self.report_agent_continuous:
                self._maybe_dispatch_report_agent(cycle, active)
            analysis_limit = self.config.max_parallel - (1 if self.report_agent_continuous else 0)
            while len(active) < self.config.max_parallel:
                if self.report_agent_continuous:
                    analysis_active = sum(
                        conversation.task_class != "report" for conversation in active
                    )
                    if analysis_active >= analysis_limit:
                        break
                task = self._claim_next_task(active)
                if not task:
                    break
                conversation = self.dispatcher.start(task)
                active.append(conversation)
                dispatched += 1
                claimed_this_cycle += 1
                self._append_event(
                    "agent_start",
                    {
                        "subject": self.subject,
                        "cid": conversation.cid,
                        "phase": conversation.task_class,
                        "lane": conversation.lane,
                        "unit_id": (conversation.unit or {}).get("id"),
                        "module_id": conversation.module_id,
                    },
                )

            next_active: list[DispatchedConversation] = []
            for conversation in active:
                result = self.dispatcher.poll(conversation)
                if result.status in EVENT_TERMINAL:
                    completed += 1
                    last_completion_cycle = cycle
                    retry = self._finish_conversation(conversation, result)
                    if retry is not None:
                        next_active.append(retry)
                else:
                    # Real-time: pull any intel the still-running agent has already
                    # written to its workspace, so facts/leads/findings/flows and
                    # the determination table update live instead of only at the end.
                    self._incremental_ingest(conversation)
                    next_active.append(conversation)
            active = next_active

            self._maybe_write_determinations(cycle)
            self._maybe_refresh_report(cycle)
            self._maybe_dispatch_report_agent(cycle, active)
            self._maybe_dispatch_visualization(cycle, active)
            self._write_state(cycle, active, "running" if active else "idle", last_completion_cycle)

            if active and cycle - last_completion_cycle > self.config.stall_cycles:
                self._append_event("loop_stall", {"subject": self.subject, "active": len(active)})
                break
            if not active and not dispatched:
                break
            if not active and self.config.max_cycles:
                break
            # Idle: nothing running and nothing claimable this cycle. With work
            # modules, coverage-gate state alone no longer decides this -- there
            # may be follow-on module work even when coverage is "locked", and
            # equally no module work even when it is not. Stop only when a fill
            # attempt produced nothing and none of that pending work exists.
            if not active and claimed_this_cycle == 0 and not self._has_pending_module_work(active):
                if not self._claim_peek_possible(gate):
                    break
            if self.config.poll_interval_s:
                self.sleep(self.config.poll_interval_s)

        status = "running" if active else "idle"
        final_state = self._write_state(cycle, active, status, last_completion_cycle)
        self._append_event(
            "loop_idle" if status == "idle" else "loop_running",
            {"subject": self.subject, "active": len(active), "cycle": cycle},
        )
        self._write_run_manifest(status, cycle, active, final_state)
        return {
            "subject": self.subject,
            "workbench": self.workbench,
            "status": status,
            "cycles": cycle,
            "active": len(active),
            "completed": completed,
            "dispatched": dispatched,
            "enumerated": enumerated,
            "state": final_state,
        }

    def _claim_next_task(self, active: list[DispatchedConversation] | None = None) -> AgentTask | None:
        # 1. Operator/manager pending actions always preempt.
        pending = self._claim_pending_action()
        if pending:
            if pending.get("kind") == "threat_model_request":
                return self._task_for_threat_model(action=pending, active=active)
            return self._task_for_pending_action(pending, active=active)
        threat_model = self._claim_threat_model_task(active=active)
        if threat_model:
            return threat_model

        active = active or []
        in_flight = self._module_in_flight(active)
        in_flight_targets = self._module_in_flight_targets(active)

        # 2. Subject-scoped modules (identify, research, toolchain, synthesis):
        #    once each, foundational, so they run early. A single-target module
        #    already running is not re-dispatched (no 4 agents doing one identify).
        subject_module = self.scheduler.next_subject_module(in_flight, in_flight_targets)
        if subject_module is not None:
            return self._task_for_subject_module(subject_module, active=active)

        # 3. Breadth: claim a new coverage unit for the characterize module.
        #
        # Exhaustive mapping jobs need the denominator covered before the loop
        # repeatedly deepens a small initial slice. Keep pending actions and
        # one-shot subject setup ahead of breadth, but prefer fresh source units
        # over per-target follow-on modules while unclaimed coverage remains.
        if self.scheduler.has_breadth():
            unit = self._claim_next()
            if unit:
                return self._task_for_characterize(unit, active=active)

        # 4. Findings need verification/patching once they exist and no fresh
        # coverage unit is waiting.
        finding_work = self.scheduler.next_finding_module(in_flight, in_flight_targets)
        if finding_work is not None:
            module, finding = finding_work
            return self._task_for_finding_module(module, finding, active=active)

        # 5. Depth: follow-on assessment on units already characterized.
        unit_work = self.scheduler.next_unit_module(in_flight, in_flight_targets)
        if unit_work is not None:
            module, unit = unit_work
            return self._task_for_unit_module(module, unit, active=active)

        return None

    def _module_in_flight(self, active: list[DispatchedConversation]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for conversation in active:
            if conversation.module_id:
                counts[conversation.module_id] = counts.get(conversation.module_id, 0) + 1
        return counts

    def _module_in_flight_targets(self, active: list[DispatchedConversation]) -> set[tuple[str, str]]:
        """(module_id, target) pairs currently running, for once-per-target dedup."""
        pairs: set[tuple[str, str]] = set()
        for conversation in active:
            if conversation.module_id and conversation.module_target:
                pairs.add((conversation.module_id, conversation.module_target))
        return pairs

    def _task_for_characterize(
        self,
        unit: dict,
        active: list[DispatchedConversation] | None = None,
    ) -> AgentTask:
        """The breadth module: claim a new unit and characterize it."""
        module = next(iter(self.scheduler.breadth_modules()), None)
        task_class = "characterize"
        lane, reason = self._route_with_dispatch_pattern(task_class, active)
        extra = f"## Module\n{module.objective}" if module and module.objective else ""
        objective = self._objective(task_class, reason, unit, extra=extra)
        return AgentTask(
            subject=self.subject,
            task_class=task_class,
            lane=lane,
            unit=unit,
            objective=objective,
            max_iterations=30,
            module_id=module.id if module else "characterize",
            module_target=str(unit.get("id")),
            submits_coverage=True,
        )

    def _task_for_unit_module(
        self,
        module: WorkModule,
        unit: dict,
        active: list[DispatchedConversation] | None = None,
    ) -> AgentTask:
        """A follow-on module (recon/review/decompose) on a characterized unit."""
        lane, reason = self._route_with_dispatch_pattern(module.task_class, active)
        # Do NOT waste the resources already spent characterizing this unit: point
        # the agent at the prior determination and artifacts and require it to
        # build on them rather than re-read the target from scratch.
        reuse = (
            "## Build On Prior Work (do not redo)\n"
            f"This unit ({unit.get('path') or unit.get('name')}) has already been "
            "characterized and may have prior findings, flows, and saved analysis "
            "artifacts. Before analyzing:\n"
            "- Read this unit's stored summary, sensitivity, data_touched, flows_in/"
            "flows_out via the coverage/search API.\n"
            "- Read prior findings/facts/leads for this unit in the ledger and the "
            "shared blackboard.\n"
            "- Reuse any saved decompilation/disassembly/extracted artifacts instead "
            "of regenerating them.\n"
            "Extend and deepen that work; do not re-characterize."
        )
        module_block = f"## Module: {module.id}\n{module.objective}" if module.objective else ""
        extra = "\n\n".join(p for p in [reuse, module_block] if p)
        objective = self._objective(module.task_class, reason, unit, extra=extra)
        return AgentTask(
            subject=self.subject,
            task_class=module.task_class,
            lane=lane,
            unit=unit,
            objective=objective,
            max_iterations=30,
            module_id=module.id,
            module_target=str(unit.get("id")),
            submits_coverage=False,
        )

    def _task_for_subject_module(
        self,
        module: WorkModule,
        active: list[DispatchedConversation] | None = None,
    ) -> AgentTask:
        lane, reason = self._route_with_dispatch_pattern(module.task_class, active)
        context_md = str(self._coverage_context().get("info_md") or "").strip()
        scope = self._scope_overlay_text()
        objective = "\n\n".join(part for part in [
            f"## REFALL context.md\n{context_md}" if context_md else "",
            f"## Scope Overlay\n```json\n{scope}\n```" if scope else "",
            self._blackboard_text(),
            f"## Task\nRun {module.task_class} for REFALL subject {self.subject}.",
            f"## Routing\n{reason}",
            f"## Module: {module.id}\n{module.objective}" if module.objective else "",
            self._output_contract(),
        ] if part)
        return AgentTask(
            subject=self.subject,
            task_class=module.task_class,
            lane=lane,
            unit=None,
            objective=objective,
            max_iterations=30,
            module_id=module.id,
            module_target=SUBJECT_MODULE_TARGET,
            submits_coverage=False,
        )

    def _task_for_finding_module(
        self,
        module: WorkModule,
        finding: dict,
        active: list[DispatchedConversation] | None = None,
    ) -> AgentTask:
        lane, reason = self._route_with_dispatch_pattern(module.task_class, active)
        context_md = str(self._coverage_context().get("info_md") or "").strip()
        objective = "\n\n".join(part for part in [
            f"## REFALL context.md\n{context_md}" if context_md else "",
            self._blackboard_text(),
            f"## Task\nRun {module.task_class} for a REFALL finding on subject {self.subject}.",
            f"## Routing\n{reason}",
            "## Finding\n"
            f"- ID: {finding.get('id')}\n"
            f"- Title: {finding.get('title')}\n"
            f"- Path: {finding.get('path')}",
            f"## Module: {module.id}\n{module.objective}" if module.objective else "",
            self._output_contract(),
        ] if part)
        return AgentTask(
            subject=self.subject,
            task_class=module.task_class,
            lane=lane,
            unit=None,
            objective=objective,
            max_iterations=30,
            module_id=module.id,
            module_target=str(finding.get("id")),
            submits_coverage=False,
        )

    def _task_for_pending_action(
        self,
        action: dict,
        active: list[DispatchedConversation] | None = None,
    ) -> AgentTask:
        lane, reason = self._route_with_dispatch_pattern("verify", active)
        objective = self._pending_action_objective(reason, action)
        return AgentTask(
            subject=self.subject,
            task_class="pending_action",
            lane=lane,
            unit=action,
            objective=objective,
            max_iterations=30,
        )

    def _claim_threat_model_task(
        self,
        active: list[DispatchedConversation] | None = None,
    ) -> AgentTask | None:
        if self.threat_model_dispatched:
            return None
        if not self._threat_model_requested():
            return None
        if self._active_threat_model():
            return None
        inputs = self._threat_model_inputs()
        if not inputs:
            return None
        return self._task_for_threat_model(inputs=inputs, active=active)

    def _task_for_threat_model(
        self,
        *,
        action: dict | None = None,
        inputs: dict | None = None,
        active: list[DispatchedConversation] | None = None,
    ) -> AgentTask | None:
        if self.threat_model_dispatched:
            return None
        inputs = inputs or self._threat_model_inputs()
        if not inputs:
            return None
        self.threat_model_dispatched = True
        lane, reason = self._route_with_dispatch_pattern("threat_model", active)
        unit = action or {
            "id": "threat_model",
            "type": "planning",
            "path": "REFALL/threat-model",
            "source_inventory_id": inputs["source_inventory"].get("inventory_id"),
            "scope_overlay_id": inputs["scope"].get("overlay_id"),
        }
        return AgentTask(
            subject=self.subject,
            task_class="threat_model",
            lane=lane,
            unit=unit,
            objective=self._threat_model_objective(reason, unit, inputs),
            max_iterations=20,
        )

    def _threat_model_inputs(self) -> dict | None:
        context = self._coverage_context()
        context_md = str(context.get("info_md") or "").strip()
        if not context_md:
            return None
        scope = self._scope_overlay()
        if not scope:
            return None
        inventory = self._latest_source_inventory()
        if not inventory or not inventory.get("files"):
            return None
        return {"context": context, "scope": scope, "source_inventory": inventory}

    def _threat_model_objective(self, reason: str, unit: dict, inputs: dict) -> str:
        context_md = str((inputs.get("context") or {}).get("info_md") or "").strip()
        scope_json = json.dumps(inputs.get("scope") or {}, indent=2, sort_keys=True)
        inventory = inputs.get("source_inventory") or {}
        files = [
            {
                "path": item.get("path"),
                "kind": item.get("kind"),
                "total_lines": item.get("total_lines"),
                "sha256": item.get("sha256"),
            }
            for item in (inventory.get("files") or [])[:80]
        ]
        inventory_summary = {
            "inventory_id": inventory.get("inventory_id"),
            "root": inventory.get("root"),
            "file_count": len(inventory.get("files") or []),
            "skipped_count": len(inventory.get("skipped") or []),
            "files": files,
        }
        return "\n\n".join([
            f"## REFALL context.md\n{context_md}",
            f"## Scope Overlay\n```json\n{scope_json}\n```",
            f"## Threat Model Inputs\n```json\n{json.dumps(inventory_summary, indent=2, sort_keys=True)}\n```",
            self._blackboard_text(),
            f"## Task\nGenerate or refresh the optional REFALL threat model for subject {self.subject}.",
            f"## Routing\n{reason}",
            "## Request\n"
            f"- ID: {unit.get('id')}\n"
            f"- Kind: {unit.get('kind') or unit.get('type')}\n"
            f"- Title: {unit.get('title') or 'Threat model'}",
            "## Output Contract\n"
            "Return one terminal ```refall-submit JSON block using schema refall.submit.v1 and type "
            "threat_model_submit. Include task_id \"threat_model\", status \"done\", summary, produced_by, "
            "created_at, and a threat_model object with assets, ingress_points, trust_boundaries, threats, "
            "hunt_prompts, and status. Keep this REFALL-owned; do not use VVAH report or encryption specs.",
        ])

    def _objective(self, task_class: str, reason: str, unit: dict, extra: str = "") -> str:
        context_md = str(self._coverage_context().get("info_md") or "").strip()
        scope = self._scope_overlay_text()
        blackboard = self._blackboard_text()
        path = unit.get("path") or unit.get("name") or "unknown"
        line_start = unit.get("line_start") or "?"
        line_end = unit.get("line_end") or "?"
        return "\n\n".join(part for part in [
            f"## REFALL context.md\n{context_md}" if context_md else "",
            f"## Scope Overlay\n```json\n{scope}\n```" if scope else "",
            blackboard,
            f"## Task\nRun {task_class} for REFALL subject {self.subject}.",
            f"## Routing\n{reason}",
            "## Coverage Unit\n"
            f"- ID: {unit.get('id')}\n"
            f"- Type: {unit.get('type')}\n"
            f"- Path: {path}\n"
            f"- Lines: {line_start}-{line_end}",
            self._output_contract(),
            extra,
        ] if part)

    def _submission_defaults(self, conversation: "DispatchedConversation") -> dict:
        """Bookkeeping the loop owns, used to backfill an agent's submit envelope
        so its work isn't rejected over fields it was never clearly told to
        write (produced_by/created_at/task_id/unit_id). See
        structured_submit.backfill_submission_envelope."""
        unit = conversation.unit or {}
        unit_id = unit.get("id")
        return {
            "produced_by": conversation.cid or conversation.lane or "refall-worker",
            "created_at": datetime.now(UTC).isoformat(),
            "subject": self.subject,
            "task_id": conversation.module_target or unit_id or conversation.task_class,
            "unit_id": unit_id,
        }

    @staticmethod
    def _parse_result(result: PollResult, defaults: dict | None = None) -> "ParsedOutput":
        text = result.response or ""
        if not text and result.trajectory:
            text = result.trajectory.decode("utf-8", errors="replace")
        return parse_agent_output(text, defaults)

    def _ingest_workspace_output(self, conversation: DispatchedConversation, parsed: "ParsedOutput") -> None:
        """Read the agent's writable workspace and merge its saved deliverables
        into `parsed`. Agents commonly save their real output as files -- a
        REFALL_SUBMISSION.json with findings, plus analysis/disassembly files --
        and end on a file-save action, leaving final_response empty. Without this
        that work is invisible to the loop. Files are also registered as durable
        runtime artifacts so the RE (disassembly, strings, notes) is preserved.
        """
        ws = conversation.workspace_host
        if not ws:
            return
        root = Path(ws)
        if not root.is_dir():
            return
        try:
            for path in sorted(root.rglob("*")):
                if ".refall-ingested" in path.parts:
                    continue
                if not path.is_file():
                    continue
                name = path.name.lower()
                # Structured submission files -> parse findings/facts/etc.
                if path.suffix == ".json" and ("submission" in name or "refall" in name or "finding" in name):
                    self._merge_submission_file(path, parsed)
                # Analysis/disassembly/notes -> keep as durable artifacts.
                elif path.suffix in {".md", ".txt", ".json"} and path.stat().st_size < 2_000_000:
                    self._register_workspace_artifact(conversation, path)
        except Exception as exc:
            self._append_event(
                "workspace_ingest_error",
                {"subject": self.subject, "cid": conversation.cid, "error": str(exc)[:300]},
            )

    def _merge_submission_file(self, path: Path, parsed: "ParsedOutput") -> None:
        try:
            data = json.loads(path.read_text(errors="replace"))
        except Exception:
            return
        blocks = data if isinstance(data, list) else [data]

        def merge_marker(text: str) -> None:
            marker = parse_agent_output(text)
            for source, target in (
                (marker.findings, parsed.findings),
                (marker.facts, parsed.facts),
                (marker.leads, parsed.leads),
                (marker.flows, parsed.flows),
            ):
                for item in source:
                    if item not in target:
                        target.append(item)

        for block in blocks:
            if not isinstance(block, dict):
                continue
            if "refall.submit" not in str(block.get("schema", "")) and "findings" not in block and "evidence" not in block:
                continue
            for finding in block.get("findings") or []:
                if isinstance(finding, dict) and finding.get("title") and finding not in parsed.findings:
                    parsed.findings.append(finding)
                elif isinstance(finding, str):
                    merge_marker(finding)
            for fact in block.get("facts") or []:
                if isinstance(fact, dict) and fact not in parsed.facts:
                    parsed.facts.append({**fact, "kind": "fact"})
                elif isinstance(fact, str):
                    merge_marker(fact)
            for lead in block.get("leads") or []:
                if isinstance(lead, dict) and lead not in parsed.leads:
                    parsed.leads.append({**lead, "kind": "lead"})
                elif isinstance(lead, str):
                    merge_marker(lead)
            for flow in block.get("flows") or []:
                if isinstance(flow, dict) and flow not in parsed.flows:
                    parsed.flows.append({**flow, "kind": "flow"})
                elif isinstance(flow, str):
                    merge_marker(flow)

    def _register_workspace_artifact(self, conversation: DispatchedConversation, path: Path) -> None:
        if not hasattr(self.arcticbase, "create_runtime_artifact"):
            return
        marker_dir = path.parent / ".refall-ingested"
        marker = marker_dir / path.name
        if marker.exists():
            return  # already ingested on a prior cycle
        try:
            content = path.read_text(errors="replace")
        except Exception:
            return
        try:
            self.arcticbase.create_runtime_artifact(
                self.workbench,
                {
                    "kind": "agent-analysis",
                    "content": content[:1_000_000],
                    "mime": "text/markdown" if path.suffix == ".md" else "text/plain",
                    "task_id": conversation.module_target or (conversation.unit or {}).get("id"),
                    "source_event_id": conversation.cid,
                    "filename": path.name,
                },
            )
            marker_dir.mkdir(exist_ok=True)
            marker.write_text("1")
        except Exception:
            pass

    def _salvage_intel(
        self, conversation: DispatchedConversation, parsed: "ParsedOutput", status: str
    ) -> dict | None:
        """Persist ALL intel an agent produced, on every outcome. This is the
        single place facts/leads/findings/flows are written, so a stopped or
        malformed agent still contributes its evidence instead of having it
        discarded. Also pulls in deliverables the agent saved to its workspace,
        since agents commonly save findings to files rather than emitting them.
        """
        self._ingest_workspace_output(conversation, parsed)
        counts = self._persist_new_intel(conversation, parsed)
        if counts and sum(counts.values()):
            self._append_event("intel_salvaged", {"subject": self.subject, "cid": conversation.cid, "status": status, **counts})
        return counts

    def _intel_key(self, conversation: DispatchedConversation, kind: str, item: dict) -> tuple:
        if kind == "finding":
            ident = str(item.get("id") or item.get("title") or "")
        elif kind == "flow":
            ident = f"{item.get('from')}->{item.get('to')}:{item.get('relation')}"
        else:
            explicit = item.get("id") or item.get("ref")
            if explicit:
                ident = str(explicit)
            else:
                material = {
                    key: item.get(key)
                    for key in ("title", "description", "text", "severity", "investigation_plan")
                    if item.get(key) not in (None, "", [], {})
                }
                ident = hashlib.sha256(
                    json.dumps(material or item, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()
        return (kind, ident)

    def _persist_new_intel(self, conversation: DispatchedConversation, parsed: "ParsedOutput") -> dict:
        """Persist only intel not seen before this run -- shared by the real-time
        incremental path and the terminal salvage path, so an item that lands live
        is never re-persisted at completion. Dedup is by stable identity, not by
        object identity, so re-reading the same workspace file is safe.
        """
        new = ParsedOutput()
        staged_keys: list[tuple] = []
        for kind, src, dst in (
            ("finding", parsed.findings, new.findings),
            ("fact", parsed.facts, new.facts),
            ("lead", parsed.leads, new.leads),
            ("flow", parsed.flows, new.flows),
        ):
            for item in src or []:
                if not isinstance(item, dict):
                    continue
                key = self._intel_key(conversation, kind, item)
                if key in self._ingested_keys:
                    continue
                self._ingested_keys.add(key)
                staged_keys.append(key)
                dst.append(item)
        try:
            for entry in _entries_from_parsed(new, conversation):
                self.arcticbase.append_ledger(self.workbench, entry)
            self._persist_findings(new, conversation)
            for finding in new.findings:
                self.scheduler.record_finding(finding)
        except Exception as exc:
            # A backend failure did not ingest these items. Allow a later poll or
            # retry to persist them instead of poisoning the in-memory dedup set.
            for key in staged_keys:
                self._ingested_keys.discard(key)
            self._append_event(
                "intel_persist_error",
                {"subject": self.subject, "cid": conversation.cid, "error": str(exc)[:300]},
            )
            return None
        return {"facts": len(new.facts), "leads": len(new.leads),
                "findings": len(new.findings), "flows": len(new.flows)}

    def _incremental_ingest(self, conversation: DispatchedConversation) -> None:
        """Pull intel a still-running agent has already emitted, in near real time.

        Two live sources: the agent's conversation event stream (every tagged
        response so far) and any files it has saved to its workspace. Both are
        parsed and de-duplicated, so intel appears as it is produced rather than
        only at completion.
        """
        fresh = ParsedOutput()
        stream_text = read_conversation_agent_text(conversation.cid)
        if stream_text.strip():
            stream = parse_agent_output(stream_text, self._submission_defaults(conversation))
            fresh.facts.extend(stream.facts)
            fresh.leads.extend(stream.leads)
            fresh.findings.extend(stream.findings)
            fresh.flows.extend(stream.flows)
        if conversation.workspace_host:
            self._ingest_workspace_output(conversation, fresh)
        counts = self._persist_new_intel(conversation, fresh)
        if counts and sum(counts.values()):
            self._append_event("incremental_intel", {"subject": self.subject, "cid": conversation.cid, **counts})

    def _record_module_completion(self, conversation: DispatchedConversation, parsed) -> None:
        """Advance the scheduler after a module finishes on a target.

        Characterizing a unit unlocks its follow-on modules; any findings the
        run produced enter the queue for finding-sourced modules (verify/patch).
        Progress persists so a restart resumes exactly here.
        """
        try:
            if conversation.task_class == "characterize" and conversation.unit:
                self.scheduler.record_characterized(conversation.unit)
            elif conversation.module_id and conversation.module_target:
                self.scheduler.mark_done(conversation.module_id, conversation.module_target)

            for finding in getattr(parsed, "findings", None) or []:
                if isinstance(finding, dict):
                    self.scheduler.record_finding(finding)

            self._save_module_progress()
        except Exception as exc:
            self._append_event(
                "module_completion_error",
                {"subject": self.subject, "cid": conversation.cid, "error": str(exc)[:300]},
            )

    def _block_empty_subject_module_completion(
        self,
        conversation: DispatchedConversation,
        parsed: "ParsedOutput",
        persistence_failed: bool = False,
    ) -> bool:
        """Keep subject-level custom work pending when no canonical intel landed.

        Unit modules can legitimately advance coverage through their determination
        payload. Subject modules have no such independent output, so completing one
        with zero facts, leads, findings, or flows would silently discard its work.
        """
        if not (
            conversation.module_id
            and conversation.module_target
            and conversation.unit is None
        ):
            return False
        intel_count = sum(
            len(items or [])
            for items in (parsed.facts, parsed.leads, parsed.findings, parsed.flows)
        )
        if intel_count and not persistence_failed:
            return False
        reason = (
            "canonical_persistence_failed"
            if persistence_failed
            else "zero_canonical_intelligence"
        )
        description = (
            f"Subject module {conversation.module_id!r} for target "
            f"{conversation.module_target!r} did not produce durable canonical "
            "intelligence. Review the agent workspace/output and rerun the module "
            "after ingestion is available."
        )
        if hasattr(self.arcticbase, "create_pending_action"):
            self.arcticbase.create_pending_action(
                self.workbench,
                {
                    "kind": "worker_output_not_ingested",
                    "title": f"Subject module produced no canonical intelligence: {conversation.module_id}",
                    "description": description,
                    "source_event_id": conversation.cid,
                    "priority": "high",
                    "required_receipt_type": "workspace_ingestion_review",
                    "created_by": "refall-standing-loop",
                },
            )
        self._append_event(
            "module_completion_blocked",
            {
                "subject": self.subject,
                "cid": conversation.cid,
                "module_id": conversation.module_id,
                "module_target": conversation.module_target,
                "reason": reason,
                "workspace_host": conversation.workspace_host,
            },
        )
        return True

    def _output_contract(self) -> str:
        if self._suppress_findings_for_subject():
            return (
                "## Output Contract\n"
                "Always compile evidence as you work: emit facts, leads, and flows, including "
                "negative results. Do NOT emit ```finding blocks, finding_submit payloads, "
                "or finding-promotion requests for this subject. Bug-like or security-relevant "
                "observations must be preserved as [LEAD] and [FACT] mapping evidence with "
                "source anchors.\n"
                "Prefer one terminal ```refall-submit JSON block using schema refall.submit.v1.\n"
                "REQUIRED envelope fields (omitting them will NOT lose your intel, but your task "
                "cannot be marked complete without them): `schema`, `type` (task_result_submit), "
                "`subject`, `task_id` (or `unit_id`), `status`, `summary`, `produced_by`, "
                "`created_at`, `evidence`, `confidence`, `limitations`, and `source_anchors` or "
                "`artifact_refs`.\n\n"
                "Source anchors MUST use source-inventory-relative paths rooted at the subject "
                "source tree. Use `src/ara/cli.py:10-20`, not `/projects/agent-ready-armor/"
                "src/ara/cli.py:10-20` and not `projects/agent-ready-armor/src/ara/cli.py`. "
                "Before submitting a task result, verify unusual anchors against "
                "`/api/workbenches/<subject>/coverage/search?q=<path>` or use `artifact_refs` "
                "when the evidence is a generated artifact rather than source.\n\n"
                "When you characterize a unit, ALSO include these structured determination fields "
                "in the refall-submit block so the central per-file table and later diagrams can be "
                "rebuilt:\n"
                "- `sensitivity`: one of low|medium|high|critical\n"
                "- `data_touched`: array of data/assets this code reads or writes "
                "(e.g. [\"NK.bin\", \"verlist.ini\", \"user PII\"])\n"
                "- `flows_in`: array of callers/entrypoints that reach this unit "
                "(function names, map symbols, or file:offset)\n"
                "- `flows_out`: array of callees/sinks this unit reaches\n\n"
                "Capture architecture and function/data flow as PARSEABLE facts/leads, not prose, "
                "so a final agent can reconstruct diagrams:\n"
                "- Architecture: `[FACT] arch:<aspect> | <value>` "
                "(e.g. `[FACT] arch:language | MIPS Windows CE PE`, "
                "`[FACT] arch:entrypoint | WinMain @ nk.exe:0x...`, "
                "`[FACT] arch:component | bluetooth-update`).\n"
                "- Flows/traces/call edges: `[FLOW] <from> -> <to> : <relation> | <evidence>` "
                "(relation is calls|reads|writes|updates|taints; "
                "e.g. `[FLOW] update_check -> verlist.ini : reads | nk.exe:0x1240`).\n\n"
                "Do NOT waste the resources spent on deep analysis. When you decompile, "
                "disassemble, extract strings/config, build a trace, or produce any costly "
                "intermediate, SAVE it as a durable file in your writable workspace and "
                "reference it in `artifact_refs` (or a [COVERAGE] path). Persist the reusable "
                "output, not just a summary of it, so later modules build on it instead of "
                "regenerating it.\n\n"
                "Legacy compatibility remains available: observations as [FACT], "
                "leads as [LEAD:severity], tool/resource requests as [ASK], files touched "
                "as [COVERAGE], and [DONE] summary. Finding output is intentionally disabled "
                "for this subject."
            )
        return (
            "## Output Contract\n"
            "Always compile evidence as you work: emit findings, facts, and leads even for "
            "negative results. Prefer one terminal ```refall-submit JSON block using schema "
            "refall.submit.v1.\n"
            "REQUIRED envelope fields (omitting them will NOT lose your intel, but your task "
            "cannot be marked complete without them): `schema`, `type` (task_result_submit), "
            "`subject`, `task_id` (or `unit_id`), `status`, `summary`, `produced_by`, "
            "`created_at`, `evidence`, `confidence`, `limitations`, and `source_anchors` or "
            "`artifact_refs`. Each finding you report needs its OWN `code_paths`, "
            "`source_anchors`, or `artifact_refs`.\n\n"
            "Source anchors MUST use source-inventory-relative paths rooted at the subject "
            "source tree. Use `src/ara/cli.py:10-20`, not `/projects/agent-ready-armor/"
            "src/ara/cli.py:10-20` and not `projects/agent-ready-armor/src/ara/cli.py`. "
            "Before submitting a finding or task result, verify unusual anchors against "
            "`/api/workbenches/<subject>/coverage/search?q=<path>` or use `artifact_refs` "
            "when the evidence is a generated artifact rather than source.\n\n"
            "When you characterize a unit, ALSO include these structured determination fields "
            "in the refall-submit block so the central per-file table and later diagrams can be "
            "rebuilt:\n"
            "- `sensitivity`: one of low|medium|high|critical\n"
            "- `data_touched`: array of data/assets this code reads or writes "
            "(e.g. [\"NK.bin\", \"verlist.ini\", \"user PII\"])\n"
            "- `flows_in`: array of callers/entrypoints that reach this unit "
            "(function names, map symbols, or file:offset)\n"
            "- `flows_out`: array of callees/sinks this unit reaches\n\n"
            "Capture architecture and function/data flow as PARSEABLE facts/leads, not prose, "
            "so a final agent can reconstruct diagrams:\n"
            "- Architecture: `[FACT] arch:<aspect> | <value>` "
            "(e.g. `[FACT] arch:language | MIPS Windows CE PE`, "
            "`[FACT] arch:entrypoint | WinMain @ nk.exe:0x...`, "
            "`[FACT] arch:component | bluetooth-update`).\n"
            "- Flows/traces/call edges: `[FLOW] <from> -> <to> : <relation> | <evidence>` "
            "(relation is calls|reads|writes|updates|taints; "
            "e.g. `[FLOW] update_check -> verlist.ini : reads | nk.exe:0x1240`).\n\n"
            "Do NOT waste the resources spent on deep analysis. When you decompile, "
            "disassemble, extract strings/config, build a trace, or produce any costly "
            "intermediate, SAVE it as a durable file in your writable workspace and "
            "reference it in `artifact_refs` (or a [COVERAGE] path). Persist the reusable "
            "output, not just a summary of it, so later modules build on it instead of "
            "regenerating it.\n\n"
            "For each FINDING, include the affected component, source-grounded impact, "
            "exact confirmation steps, observed evidence, confidence, limitations, and "
            "recommended follow-up. Keep confirmation steps distinct from any proposed "
            "dynamic proof; under source-only scope, do not claim live exploitability.\n\n"
            "Legacy compatibility remains available: findings as ```finding JSON blocks, "
            "observations as [FACT], leads as [LEAD:severity], tool/resource requests as [ASK], "
            "files touched as [COVERAGE], and [DONE] summary."
        )

    def _suppress_findings_for_subject(self) -> bool:
        try:
            workbench = self.arcticbase.get_workbench(self.workbench)
            custom = workbench.get("custom_fields") or {}
        except Exception:
            return False
        raw = custom.get("refall_no_findings")
        return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}

    def _pending_action_objective(self, reason: str, action: dict) -> str:
        context_md = str((self.coverage.get_context(self.workbench) or {}).get("info_md") or "").strip()
        scope = self._scope_overlay_text()
        blackboard = self._blackboard_text()
        receipt_type = action.get("required_receipt_type") or "agent_resolution"
        return "\n\n".join(part for part in [
            f"## REFALL context.md\n{context_md}" if context_md else "",
            f"## Scope Overlay\n```json\n{scope}\n```" if scope else "",
            blackboard,
            f"## Task\nResolve pending REFALL action for subject {self.subject}.",
            f"## Routing\n{reason}",
            "## Pending Action\n"
            f"- ID: {action.get('id')}\n"
            f"- Kind: {action.get('kind')}\n"
            f"- Status: {action.get('status')}\n"
            f"- Priority: {action.get('priority')}\n"
            f"- Title: {action.get('title')}\n"
            f"- Description: {action.get('description') or ''}\n"
            f"- Required receipt: {receipt_type}\n"
            f"- Source unit: {action.get('source_unit_id') or ''}\n"
            f"- Source finding: {action.get('source_finding_id') or ''}",
            # An assessment-style pending action (e.g. "assess NK.bin update trust")
            # is real analysis work: the agent MUST emit its discovered evidence as
            # structured findings/facts/leads/flows, not just a resolution note.
            # Otherwise the RE happens and produces no captured intel.
            "## Emit Your Analysis As Structured Intel\n"
            + (
                "As you work this action, emit EVERYTHING you discover as [FACT] observations, "
                "[LEAD:severity] leads, and [FLOW] from -> to : relation | evidence edges for "
                "call/data flows. Do NOT emit finding blocks or finding_submit payloads for this "
                "subject; preserve bug-like observations as mapping leads. Record negative results "
                "too. Do not leave your analysis only in prose -- unemitted work is lost."
                if self._suppress_findings_for_subject()
                else
                "As you work this action, emit EVERYTHING you discover: ```finding blocks for "
                "vulnerabilities (with severity, impact, evidence, reproduction, remediation), "
                "[FACT] observations, [LEAD:severity] leads, and [FLOW] from -> to : relation | evidence "
                "edges for call/data flows. Record negative results too. Do not leave your analysis "
                "only in prose -- unemitted work is lost."
            ),
            self._output_contract(),
            "## Resolution\n"
            "ALSO return one terminal ```refall-submit JSON block using schema refall.submit.v1: "
            "type task_result_submit with status done and concrete source_anchors or artifact_refs when "
            "resolved, or type control_submit if operator input or a capability is still required.",
        ] if part)

    def _finish_conversation(
        self,
        conversation: DispatchedConversation,
        result: PollResult,
    ) -> DispatchedConversation | None:
        outcome = classify_invocation(
            result.status,
            result.response or "",
            require_structured_submit=_require_structured_submit(),
            attempt=conversation.attempt,
            max_attempts=_retry_max_attempts(),
        )
        # Parse the agent output once. A duplicate structured submission (same
        # submission_id re-applied on a retry) must not re-persist, so that guard
        # runs BEFORE salvage. Otherwise, salvage intel from EVERY invocation --
        # an agent stopped at max_iterations, or one that ended without a clean
        # terminal submit, still produced facts/leads/findings/flows, and none of
        # that agent's work should be thrown away.
        parsed = self._parse_result(result, self._submission_defaults(conversation))
        if conversation.task_class == "report":
            limited_ids = {
                str(submission.get("submission_id") or submission.get("task_id") or "")
                for submission in parsed.structured
                if str(submission.get("status") or "").strip().lower()
                in {
                    "complete_with_limitations",
                    "completed_with_limitations",
                    "complete_with_scope_limitations",
                    "completed_with_scope_limitations",
                }
            }
            if limited_ids:
                limited = next(
                    submission for submission in parsed.structured
                    if str(submission.get("submission_id") or submission.get("task_id") or "")
                    in limited_ids
                )
                parsed.done = parsed.done or str(limited.get("summary") or "")
                parsed.pending_actions = [
                    action for action in parsed.pending_actions
                    if not (
                        action.get("kind") == "worker_blocked"
                        and str(action.get("source_event_id") or "") in limited_ids
                    )
                ]
        submission_keys = _structured_submission_keys(parsed, conversation)
        if submission_keys and self._structured_submissions_already_applied(submission_keys):
            self._append_event(
                "structured_submission_duplicate",
                {
                    "subject": self.subject,
                    "cid": conversation.cid,
                    "unit_id": (conversation.unit or {}).get("id"),
                    "submission_keys": submission_keys,
                },
            )
            return None
        salvage_counts = self._salvage_intel(conversation, parsed, result.status)
        if outcome.state != "completed":
            artifact_refs = self._save_failed_submit_artifact(conversation, result, outcome)
            self._record_retry_failure(conversation, outcome, artifact_refs)
            self.arcticbase.append_ledger(
                self.workbench,
                {
                    "kind": "ops-event",
                    "action": "worker.submit.failed",
                    "status": outcome.state,
                    "subject": self.subject,
                    "agent": conversation.cid,
                    "unit_id": (conversation.unit or {}).get("id"),
                    "failure_class": outcome.failure_class,
                    "summary": outcome.last_error,
                    "artifact_refs": artifact_refs,
                },
            )
            self._append_event(
                "worker_submit_invalid",
                {
                    "subject": self.subject,
                    "cid": conversation.cid,
                    "failure_class": outcome.failure_class,
                    "unit_id": (conversation.unit or {}).get("id"),
                    "artifact_refs": artifact_refs,
                    "attempt": outcome.attempt,
                    "max_attempts": outcome.max_attempts,
                    "next_action": outcome.next_action,
                },
            )
            if outcome.retryable:
                retry = self._start_retry(conversation, outcome, artifact_refs)
                if retry is not None:
                    return retry
            if self._create_failure_pending_action(conversation, outcome, artifact_refs):
                self._push_blackboard(outcome.last_error)
                return None
            if hasattr(self.arcticbase, "create_pending_action"):
                self.arcticbase.create_pending_action(
                    self.workbench,
                    {
                        "kind": "operator_decision_needed",
                        "title": f"Worker output needs manager review for {conversation.cid}",
                        "description": outcome.last_error,
                        "source_unit_id": (conversation.unit or {}).get("id"),
                        "source_event_id": artifact_refs[0] if artifact_refs else None,
                        "priority": "high",
                        "created_by": "refall-standing-loop",
                    },
                )
            self._push_blackboard(outcome.last_error)
            return None
        # `parsed`, its intel, and the duplicate-submission guard were all handled
        # above. The success path only adds what requires a clean completion:
        # transitions, coverage completion, and pending/threat-model resolution.
        self._apply_structured_transitions(parsed, conversation)
        self._persist_capability_requests(parsed, conversation)
        self._persist_pending_actions(parsed, conversation)
        if result.status == "finished" and conversation.task_class == "threat_model":
            threat_model = self._persist_threat_model(parsed, conversation, result.response or "")
            if threat_model and (conversation.unit or {}).get("kind") == "threat_model_request":
                self._resolve_threat_model_action(conversation, threat_model)
        elif result.status == "finished" and conversation.task_class == "pending_action" and conversation.unit:
            self._resolve_pending_action(conversation, result, parsed)
        elif (
            result.status == "finished"
            and conversation.unit
            and conversation.task_class == "characterize"
            and _should_submit_coverage(parsed)
        ):
            # Only the breadth (characterize) module transitions a unit's coverage
            # state and fills the central determination row (summary/sensitivity/
            # flows). Follow-on modules use other task classes and never re-submit
            # coverage; their evidence lands as findings/facts/leads via the ledger.
            evidence = _coverage_evidence(parsed, conversation.unit)
            summary = parsed.done or (result.response or "")[:500] or "Agent finished without a summary."
            determination = _determination_fields(parsed)
            self.coverage.submit(
                conversation.unit["id"],
                f"refall-loop-{conversation.lane}",
                summary,
                evidence,
                subject=self.workbench,
                **determination,
            )
        module_completion_blocked = self._block_empty_subject_module_completion(
            conversation, parsed, persistence_failed=salvage_counts is None
        )
        if not module_completion_blocked:
            self._record_module_completion(conversation, parsed)
        if submission_keys:
            self._record_structured_submissions(submission_keys)
        self._push_blackboard(parsed.done or result.response[:500] or result.status)
        trajectory_refs = self._save_trajectory_artifact(conversation, result)
        archive_status = self._archive_conversation_events(conversation)
        reap_status = self._reap_conversation(conversation)
        self._append_event(
            "agent_complete",
            {
                "subject": self.subject,
                "cid": conversation.cid,
                "phase": conversation.task_class,
                "lane": conversation.lane,
                "status": "completion_blocked" if module_completion_blocked else result.status,
                "unit_id": (conversation.unit or {}).get("id"),
                "findings": len(parsed.findings),
                "facts": len(parsed.facts),
                "leads": len(parsed.leads),
                "flows": len(parsed.flows),
                "pending_actions": len(parsed.pending_actions),
                "module_id": conversation.module_id,
                "artifact_refs": trajectory_refs,
                "archive_status": archive_status,
                "delete_status": reap_status,
            },
        )
        return None

    def _save_trajectory_artifact(
        self,
        conversation: DispatchedConversation,
        result: PollResult,
    ) -> list[str]:
        """Persist the agent trajectory before the conversation is reaped.

        poll() already downloaded the bytes, so this is the last point at which
        they can be written durably; once the conversation is deleted from the
        agent server they are unrecoverable.
        """
        if not result.trajectory:
            return []
        if not hasattr(self.arcticbase, "create_runtime_artifact"):
            return []
        content = json.dumps(
            {
                "schema": "refall.agent-trajectory.v1",
                "status": result.status,
                "conversation_id": conversation.cid,
                "trajectory_encoding": "base64",
                "trajectory_sha256": hashlib.sha256(result.trajectory).hexdigest(),
                "trajectory_base64": base64.b64encode(result.trajectory).decode("ascii"),
            },
            sort_keys=True,
        )
        try:
            artifact = self.arcticbase.create_runtime_artifact(
                self.workbench,
                {
                    "kind": "agent-trajectory",
                    "content": content,
                    "mime": "application/json",
                    "task_id": (conversation.unit or {}).get("id"),
                    "source_event_id": conversation.cid,
                },
            )
        except Exception:
            return []
        artifact_id = artifact.get("id")
        return [str(artifact_id)] if artifact_id else []

    def _archive_conversation_events(self, conversation: DispatchedConversation) -> str:
        """Copy an agent's event stream out of Agent Canvas storage before reaping.

        The canvas keeps events under `<conversations>/<cid without dashes>/events`,
        which is bind-mounted read-write into the container, so deleting the
        conversation also removes them. Copying into `logs/agents/<cid>/events`
        puts them under the first root the REFALL AB debug endpoint searches, so
        the conversation stays inspectable permanently.
        """
        cid_key = conversation.cid.replace("-", "")
        source = Path(config.OPENHANDS_CONVERSATIONS_DIR) / cid_key / "events"
        if not source.is_dir():
            return "not_found"
        target = self.subject_path / "refallsubloop" / "logs" / "agents" / conversation.cid / "events"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        except Exception as exc:
            self._append_event(
                "conversation_events_archive_failed",
                {
                    "subject": self.subject,
                    "cid": conversation.cid,
                    "unit_id": (conversation.unit or {}).get("id"),
                    "error": str(exc)[:500],
                },
            )
            return "archive_failed"
        return "archived"

    def _reap_conversation(self, conversation: DispatchedConversation) -> str:
        """Delete a finished conversation so the agent server can release it.

        The agent server holds conversation state, event streams, and
        trajectories in memory for the life of the process; without this the
        backend grows unbounded until it is OOM-killed. Events are archived to
        the subject log tree first so deletion costs no evidence.
        """
        delete = getattr(self.dispatcher, "delete", None)
        if not callable(delete):
            return "unsupported"
        try:
            delete(conversation.cid)
        except Exception as exc:
            self._append_event(
                "conversation_delete_failed",
                {
                    "subject": self.subject,
                    "cid": conversation.cid,
                    "unit_id": (conversation.unit or {}).get("id"),
                    "error": str(exc)[:500],
                },
            )
            return "delete_failed"
        return "deleted"

    def _auto_enumerate_if_empty(self) -> int:
        stats = self._safe_coverage()
        if stats.get("lines_total", 0):
            return 0
        root = self._source_root()
        if not root or not root.is_dir():
            return 0
        inventory = build_source_inventory(self.workbench, root)
        self.source_inventory = inventory
        if hasattr(self.coverage, "put_source_inventory"):
            try:
                self.coverage.put_source_inventory(self.workbench, inventory)
            except Exception:
                pass
        files = [
            {
                "path": item["path"],
                "total_lines": item["total_lines"],
                "src": "source-inventory",
            }
            for item in inventory.get("files", [])
        ]
        if not files:
            return 0
        if all(str(item.get("kind") or "").lower() == "binary" for item in inventory.get("files") or []):
            if hasattr(self.arcticbase, "create_pending_action"):
                self.arcticbase.create_pending_action(
                    self.workbench,
                    {
                        "kind": "binary_analysis_plan_required",
                        "title": "Binary-only subject requires an explicit analysis plan",
                        "description": (
                            "REFALL did not convert a binary-only source root into synthetic line coverage. "
                            "Configure binary/static-analysis modules or provide a manager-approved binary plan."
                        ),
                        "priority": "high",
                        "required_receipt_type": "manager_review",
                        "created_by": "refall-standing-loop",
                    },
                )
            self._append_event(
                "binary_analysis_plan_required",
                {"subject": self.subject, "files": [item["path"] for item in inventory.get("files") or []]},
            )
            return 0
        self.coverage.enumerate(self.workbench, files)
        self._append_event(
            "coverage_enumerated",
            {
                "subject": self.subject,
                "files": len(files),
                "source_inventory_id": inventory.get("inventory_id"),
                "skipped": len(inventory.get("skipped") or []),
            },
        )
        return len(files)

    def _maybe_write_determinations(self, cycle: int) -> None:
        """Compile the central 'what is every file, and what did we learn' table.

        This runs every report cycle regardless of findings, so even a pure
        characterization run produces a durable, queryable roll-up instead of
        results scattered across unit rows and ledger entries. The units table
        already holds per-file determinations (summary/sensitivity); this
        surfaces them as one artifact plus module/evidence progress.
        """
        if self.config.report_interval_cycles <= 0 or cycle % self.config.report_interval_cycles:
            return
        if not hasattr(self.arcticbase, "create_runtime_artifact"):
            return
        try:
            coverage = self._safe_coverage()
            ledger_stats = self.arcticbase.ledger_stats(self.workbench)
            by_kind = ledger_stats.get("by_kind") or {}
            module_done: dict[str, int] = {}
            for done in self.scheduler.completed.values():
                for module_id in done:
                    module_done[module_id] = module_done.get(module_id, 0) + 1
            digest = {
                "subject": self.subject,
                "cycle": cycle,
                "coverage": {
                    "files_total": coverage.get("files_total"),
                    "files_done": coverage.get("files_done"),
                    "resolved_pct": coverage.get("resolved_pct"),
                    "characterized_pct": coverage.get("characterized_pct"),
                },
                "evidence_compiled": {
                    "findings": by_kind.get("finding", 0),
                    "facts": by_kind.get("fact", 0),
                    "leads": by_kind.get("lead", 0),
                },
                "modules": {
                    "active": [m.id for m in self.module_registry.active],
                    "completions_by_module": module_done,
                    "units_characterized": len(self.scheduler.characterized),
                    "findings_tracked": len(self.scheduler.findings),
                },
            }
            self.arcticbase.create_runtime_artifact(
                self.workbench,
                {
                    "kind": "determinations-digest",
                    "content": json.dumps(digest, indent=2, sort_keys=True),
                    "mime": "application/json",
                    "task_id": f"determinations-cycle-{cycle}",
                },
            )
            self._append_event("determinations_digest", digest)
        except Exception as exc:
            self._append_event(
                "determinations_digest_error",
                {"subject": self.subject, "error": str(exc)[:300]},
            )

    def _maybe_refresh_report(self, cycle: int) -> None:
        if self.config.report_interval_cycles <= 0 or cycle % self.config.report_interval_cycles:
            return
        stats = self.arcticbase.ledger_stats(self.workbench)
        by_kind = stats.get("by_kind") or {}
        if self._suppress_findings_for_subject():
            mapping_intel = sum(int(by_kind.get(kind, 0) or 0) for kind in ("fact", "lead", "flow", "artifact"))
            if mapping_intel <= 0:
                return
        elif by_kind.get("finding", 0) <= 0:
            return
        try:
            draft = self.draft_reporter(self.workbench, self.subject)
            self.arcticbase.append_ledger(
                self.workbench,
                {
                    "kind": "artifact",
                    "lane": "report-draft",
                    "subject": self.subject,
                    "summary": "Standing loop refreshed draft report",
                    "report": draft,
                },
            )
            self._append_event("report_refresh", {"subject": self.subject, "cycle": cycle, "report": draft})
        except Exception as exc:
            self._append_event("report_refresh_error", {"subject": self.subject, "error": str(exc)[:500]})

    def _intel_count(self) -> int:
        """Total facts + leads + findings compiled so far (server-authoritative)."""
        try:
            by_kind = (self.arcticbase.ledger_stats(self.workbench) or {}).get("by_kind") or {}
        except Exception:
            return self.last_report_intel
        return int(by_kind.get("fact", 0)) + int(by_kind.get("lead", 0)) + int(by_kind.get("finding", 0))

    def _maybe_dispatch_report_agent(self, cycle: int, active: list[DispatchedConversation]) -> None:
        """Reserve one slot for a report-writing agent when enough new intel exists.

        The default policy is triggered by accumulated intel volume, not cycle
        count, so the report keeps pace with discovery without interrupting a
        running analysis agent. Subjects with `refall_report_agent_continuous`
        reserve one slot and immediately replace a completed report agent. The
        agent enriches the living report AND maintains a running analyst-notes
        digest from canonical evidence.
        """
        if any(getattr(conversation, "task_class", None) == "report" for conversation in active):
            return
        threshold = self.config.report_agent_intel_threshold
        if len(active) >= self.config.max_parallel:
            return
        intel = self._intel_count()
        if not self.report_agent_continuous:
            if threshold <= 0:
                return
            if not self._source_coverage_complete():
                return
            if intel - self.last_report_intel < threshold:
                return
        lane, reason = self._route_with_dispatch_pattern("doc_synthesis", active)
        if self.report_agent_lane:
            lane = self.report_agent_lane
        objective = self._report_agent_objective(intel)
        task = AgentTask(
            subject=self.subject,
            task_class="report",
            lane=lane,
            unit=None,
            objective=objective,
            max_iterations=25,
        )
        try:
            conversation = self.dispatcher.start(task)
        except Exception as exc:
            self._append_event("report_agent_dispatch_failed", {"subject": self.subject, "error": str(exc)[:300]})
            return
        active.append(conversation)
        self.last_report_intel = intel
        self._save_module_progress()
        self._append_event(
            "report_agent_dispatched",
            {"subject": self.subject, "cid": conversation.cid, "cycle": cycle, "intel": intel},
        )

    def _report_agent_objective(self, intel: int) -> str:
        context_md = str(self._coverage_context().get("info_md") or "").strip()
        if self._suppress_findings_for_subject():
            return "\n\n".join(part for part in [
                f"## REFALL context.md\n{context_md}" if context_md else "",
                self._blackboard_text(),
                f"## Task\nYou are the ARA source-mapping codex report agent for subject {self.subject}.",
                "## Inputs to read first\n"
                f"- Existing report: GET /api/workbenches/{self.workbench}/refall-report\n"
                f"- Source-backed facts/leads/flows via /api/workbenches/{self.workbench}/ledger/entries\n"
                f"- Per-file determinations via /api/workbenches/{self.workbench}/coverage/search\n"
                f"- Runtime artifacts via /api/workbenches/{self.workbench}/runtime/artifacts\n"
                f"- Evidence graph via /api/workbenches/{self.workbench}/runtime/evidence-graph",
                "## Produce two things — source mapping, not a security report\n"
                "1. ENRICH the living HTML report as an ARA Source Mapping Codex using the ARA theme "
                "(deep navy #0a0e18, gold #ffd166, blue #4aa6cc). Include source-backed sections for "
                "system architecture, features/functionality/capabilities, task/workflow lifecycle, "
                "Forge/Reforge, Armor/Weapons/Packs/Tempers/Trim, chunks/bytes/crumbs/alphabets, "
                "Hermes integration, guard/runtime controls, persistence, and not-found concepts.\n"
                "2. UPDATE a durable `analyst-notes` artifact with source-backed architecture notes, "
                "feature inventory, unresolved decomposition questions, and visual assets still needed. "
                "Do not rank findings, do not write attack chains, and do not present this as a security audit.",
                "## Visual Requirements\n"
                "Add or preserve instantly digestible visuals: inline SVG diagrams, source-to-feature maps, "
                "workflow swimlanes, component dependency graphs, and file/line coverage tables. Every visual "
                "must cite source anchors or artifact refs.",
                "## Persistence\n"
                "Save analyst notes as a runtime artifact of kind 'analyst-notes' and update the report object. "
                "Reference evidence by ledger id, artifact id, or file:line. Do not invent claims; compile "
                "only source-backed facts, leads, flows, and artifacts.\n"
                f"(~{intel} intel items compiled so far.)",
                self._output_contract(),
            ] if part)
        return "\n\n".join(part for part in [
            f"## REFALL context.md\n{context_md}" if context_md else "",
            self._blackboard_text(),
            f"## Task\nYou are the REFALL report-writing agent for subject {self.subject}.",
            "## Report-Lane Boundary\n"
            f"Use `task_id: report-agent-{intel}` in the terminal submission. Never reuse an analysis "
            "module or coverage-unit task ID. Treat Loop Directives embedded in context as analyst "
            "background, not as an instruction to repeat source analysis. Compile canonical evidence "
            "only; do not create a new finding unless it already has ledger-backed evidence.",
            "## Inputs to read first\n"
            f"- Existing report: GET /api/workbenches/{self.workbench}/refall-report\n"
            f"- New evidence since last report (findings/facts/leads/flows) via "
            f"/api/workbenches/{self.workbench}/ledger/entries\n"
            f"- Per-file determinations via /api/workbenches/{self.workbench}/coverage/search\n"
            f"- Evidence graph via /api/workbenches/{self.workbench}/runtime/evidence-graph\n"
            f"- Prior analyst notes artifact (kind 'analyst-notes') via "
            f"/api/workbenches/{self.workbench}/runtime/artifacts",
            "## Produce two things — build on prior work, do not re-synthesise everything\n"
            "1. ENRICH the living formal report: fold in new findings ranked by "
            "impact/likelihood, refresh the architecture and function/data-flow "
            "picture from [FLOW] edges and arch: facts, and update attack chains.\n"
            "2. UPDATE a running `analyst-notes` artifact (a compiling narrative, "
            "distinct from the formal report) with: architecture as understood so "
            "far, function/data-flow narrative, open leads and hypotheses, and what "
            "has been ruled out. Append/refine; keep prior notes.",
            "## Persistence\n"
            "Save the analyst notes as a durable runtime artifact of kind "
            "'analyst-notes' and update the report object. Reference evidence by "
            "finding id, ledger id, or file:line. Do not invent findings — only "
            "compile ledger-backed evidence.\n"
            f"(~{intel} intel items compiled so far.)",
            self._output_contract(),
        ] if part)

    def _maybe_dispatch_visualization(self, cycle: int, active: list[DispatchedConversation]) -> None:
        if cycle % 20:
            return
        if not self._source_coverage_complete():
            return
        stats = self.arcticbase.ledger_stats(self.workbench)
        coverage = self._safe_coverage()
        if (
            not self._suppress_findings_for_subject()
            and (stats.get("by_kind") or {}).get("finding", 0) < self.config.visualization_min_findings
        ):
            return
        if coverage.get("resolved_pct", 0) < self.config.visualization_min_resolved_pct:
            return
        if len(active) >= self.config.max_parallel:
            return
        lane, reason = self._route_with_dispatch_pattern("doc_synthesis", active)
        visual_reason = (
            "Generate ARA source-mapping visuals from completed coverage, source-backed facts, "
            "leads, flows, and runtime artifacts. Include architecture, feature, workflow, "
            "equipment, Hermes, chunks/alphabets, and guard/control diagrams with source anchors."
            if self._suppress_findings_for_subject()
            else reason or "Generate REFALL attack surface visualization from current ledger findings."
        )
        task = AgentTask(
            subject=self.subject,
            task_class="visualization",
            lane=lane,
            unit=None,
            objective=self._objective(
                "visualization",
                visual_reason,
                {"id": "visualization", "type": "artifact", "path": "Report", "line_start": None, "line_end": None},
            ),
            max_iterations=20,
        )
        conversation = self.dispatcher.start(task)
        active.append(conversation)
        self._append_event(
            "agent_start",
            {
                "subject": self.subject,
                "cid": conversation.cid,
                "phase": "visualization",
                "lane": conversation.lane,
                "unit_id": None,
            },
        )

    def _source_coverage_complete(self) -> bool:
        coverage = self._safe_coverage()
        total = coverage.get("files_total")
        done = coverage.get("files_done")
        if total is not None and done is not None:
            try:
                return int(done) >= int(total)
            except (TypeError, ValueError):
                return False
        return True

    def _claim_next(self) -> dict | None:
        try:
            return self.coverage.claim_next(self.workbench, "refall-standing-loop")
        except RuntimeError as exc:
            if "404" in str(exc) or "no open units" in str(exc).lower():
                return None
            raise

    def _claim_pending_action(self) -> dict | None:
        if not (
            hasattr(self.arcticbase, "list_pending_actions")
            and hasattr(self.arcticbase, "claim_pending_action")
        ):
            return None
        try:
            actions = self.arcticbase.list_pending_actions(self.workbench, include_terminal=False)
        except RuntimeError as exc:
            if "404" in str(exc):
                return None
            raise
        if not isinstance(actions, list):
            return None
        now = time.time()
        candidates = [
            action for action in actions
            if _pending_action_claimable(action, now)
            and _pending_action_worker_claimable(action)
        ]
        if not candidates:
            return None
        candidates.sort(key=_pending_action_sort_key)
        for action in candidates:
            if action.get("kind") == "threat_model_request" and not self._threat_model_inputs():
                continue
            action_id = str(action.get("id") or "")
            if not action_id:
                continue
            try:
                return self.arcticbase.claim_pending_action(
                    self.workbench,
                    action_id,
                    "refall-standing-loop",
                )
            except RuntimeError as exc:
                if "404" in str(exc) or "409" in str(exc):
                    continue
                raise
        return None

    def _claim_peek_possible(self, gate: dict) -> bool:
        if not gate.get("locked"):
            return False
        if not hasattr(self.arcticbase, "list_pending_actions"):
            return False
        try:
            actions = self.arcticbase.list_pending_actions(self.workbench, include_terminal=False)
        except Exception:
            return False
        now = time.time()
        return any(
            _pending_action_claimable(action, now)
            and _pending_action_worker_claimable(action)
            for action in actions or []
        )

    def _has_pending_module_work(self, active: list[DispatchedConversation]) -> bool:
        """Follow-on/subject/finding module work waiting to be dispatched.

        Breadth (characterize) is not counted here -- it is governed by the
        coverage gate. This keeps the loop alive to finish assessment on units
        it has already characterized, instead of idling out the moment coverage
        has no new units to claim.
        """
        in_flight = self._module_in_flight(active)
        return (
            self.scheduler.next_subject_module(in_flight) is not None
            or self.scheduler.next_finding_module(in_flight) is not None
            or self.scheduler.next_unit_module(in_flight) is not None
        )

    def _safe_coverage(self) -> dict:
        try:
            return self.coverage.coverage(self.workbench)
        except Exception:
            return {"subject": self.subject, "lines_total": 0, "resolved_pct": 0.0}

    def _safe_gate(self) -> dict:
        try:
            return self.coverage.gate(self.workbench)
        except Exception:
            return {"subject": self.subject, "locked": True, "resolved_pct": 0.0}

    def _coverage_context(self) -> dict:
        try:
            context = self.coverage.get_context(self.workbench) or {}
        except Exception:
            context = {}
        return context if isinstance(context, dict) else {}

    def _latest_source_inventory(self) -> dict:
        if isinstance(self.source_inventory, dict) and self.source_inventory.get("files"):
            return self.source_inventory
        if not hasattr(self.coverage, "get_source_inventory"):
            return {}
        try:
            inventory = self.coverage.get_source_inventory(self.workbench) or {}
        except Exception:
            inventory = {}
        self.source_inventory = inventory if isinstance(inventory, dict) else {}
        return self.source_inventory

    def _active_threat_model(self) -> dict:
        if isinstance(self.threat_model, dict) and self.threat_model.get("status") == "active":
            return self.threat_model
        if not hasattr(self.coverage, "get_threat_model"):
            return {}
        try:
            threat_model = self.coverage.get_threat_model(self.workbench) or {}
        except Exception:
            threat_model = {}
        if isinstance(threat_model, dict) and threat_model.get("status") == "active":
            self.threat_model = threat_model
            return threat_model
        return {}

    def _threat_model_requested(self) -> bool:
        scope = self._scope_overlay()
        if _truthy(scope.get("threat_model_requested")):
            return True
        try:
            workbench = self.arcticbase.get_workbench(self.workbench)
        except Exception:
            workbench = {}
        fields = workbench.get("custom_fields") or {}
        return any(
            _truthy(fields.get(key))
            for key in ("threat_model_requested", "refall_threat_model_requested")
        )

    def _resolve_subject_path(self) -> Path:
        try:
            workbench = self.arcticbase.get_workbench(self.workbench)
        except Exception:
            workbench = {}
        fields = workbench.get("custom_fields") or {}
        for value in (fields.get("refall_subject_path"), workbench.get("local_path")):
            if value:
                return Path(value)
        root = Path(os.environ.get("REFALL_LOOP_STATE_ROOT", ".refall-loop-state"))
        return root / self.subject

    def _source_root(self) -> Path | None:
        try:
            workbench = self.arcticbase.get_workbench(self.workbench)
        except Exception:
            workbench = {}
        fields = workbench.get("custom_fields") or {}
        for value in (fields.get("refall_source_path"), str(self.subject_path / "PRJ")):
            if value and Path(value).is_dir():
                return Path(value)
        return None

    def _state_path(self) -> Path:
        return self.subject_path / ".refall" / "loop_state.json"

    def _events_path(self) -> Path:
        return self.subject_path / "refallsubloop" / "logs" / "events" / "events.jsonl"

    def _blackboard_path(self) -> Path:
        return self.subject_path / ".refall" / "blackboard.json"

    def _ensure_dirs(self) -> None:
        for path in (self._state_path().parent, self._events_path().parent, self._blackboard_path().parent):
            path.mkdir(parents=True, exist_ok=True)

    def _load_state(self) -> dict:
        path = self._state_path()
        if not path.is_file():
            return {"iteration": 0, "active": [], "last_completion_cycle": 0}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"iteration": 0, "active": [], "last_completion_cycle": 0}

    def _write_state(
        self,
        cycle: int,
        active: list[DispatchedConversation],
        status: str,
        last_completion_cycle: int,
    ) -> dict:
        coverage = self._safe_coverage()
        state = {
            "status": status,
            "subject": self.subject,
            "workbench": self.workbench,
            "run_id": self.run_id,
            "iteration": cycle,
            "active": [asdict(item) for item in active],
            "active_count": len(active),
            "coverage_pct": coverage.get("resolved_pct", 0),
            "current_target": f"{len(active)} active agents, resolved={coverage.get('resolved_pct', 0)}%",
            "last_completion_cycle": last_completion_cycle,
            "last_updated": datetime.now(UTC).isoformat(),
        }
        self._state_path().write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return state

    def _write_run_manifest(
        self,
        loop_status: str,
        cycle: int,
        active: list[DispatchedConversation],
        state: dict | None = None,
    ) -> None:
        if not hasattr(self.arcticbase, "put_runtime_manifest") or not self.run_id:
            return
        coverage = self._safe_coverage()
        manifest = {
            "run_id": self.run_id,
            "refall_version": "REFALL-V10",
            "provider_roles": _provider_roles(),
            "runtime_host": {
                "hostname": socket.gethostname(),
                "subject_path": str(self.subject_path),
            },
            "config_hashes": {"lanes": _stable_json_sha256(config.LANES)},
            "source_hashes": self._source_hashes(),
            "source_inventory_id": (self.source_inventory or {}).get("inventory_id"),
            "scope_overlay_id": (self.scope_overlay or {}).get("overlay_id"),
            "threat_model_id": (self.threat_model or {}).get("threat_model_id"),
            "checkpoint_ids": list(self.checkpoint_ids),
            "git": {"sha": None},
            "dynamic_testing": {"status": "not_applicable"},
            "stage_status": {
                "loop": loop_status,
                "cycle": cycle,
                "active": len(active),
                "coverage_pct": coverage.get("resolved_pct", 0),
            },
        }
        if state:
            manifest["stage_status"]["state_status"] = state.get("status")
        try:
            self.arcticbase.put_runtime_manifest(self.workbench, manifest)
        except Exception:
            pass
    def _append_event(self, event_type: str, fields: dict) -> None:
        event = {"ts": datetime.now(UTC).isoformat(), "type": event_type, **fields}
        event["run_id"] = self.run_id
        self._events_path().parent.mkdir(parents=True, exist_ok=True)
        with self._events_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
        self.arcticbase.push_ops_event(event)
        if hasattr(self.arcticbase, "append_runtime_event"):
            try:
                self.arcticbase.append_runtime_event(
                    self.workbench,
                    {
                        "type": event_type,
                        "run_id": self.run_id,
                        "task_id": str(fields.get("unit_id") or "") or None,
                        "session_id": str(fields.get("cid") or "") or None,
                        "payload": fields,
                        "artifact_refs": fields.get("artifact_refs") if isinstance(fields.get("artifact_refs"), list) else [],
                    },
                )
            except Exception:
                pass
        self._write_event_checkpoint(event_type, fields)

    def _resume_preflight_refused(self) -> bool:
        if not (
            hasattr(self.arcticbase, "list_runtime_checkpoints")
            and hasattr(self.arcticbase, "resume_preflight")
        ):
            return False
        try:
            prior = self.arcticbase.list_runtime_checkpoints(self.workbench)
        except Exception:
            return False
        if not prior:
            return False
        try:
            result = self.arcticbase.resume_preflight(self.workbench, self._checkpoint_input_hashes())
        except RuntimeError as exc:
            if "409" in str(exc):
                self._append_event("resume_preflight_refused", {"subject": self.subject, "error": str(exc)[:500]})
                return True
            raise
        except Exception:
            return False
        if isinstance(result, dict) and result.get("accepted") is False:
            self._append_event("resume_preflight_refused", {"subject": self.subject, "result": result})
            return True
        return False

    def _load_resume_source_inventory(self) -> None:
        inventory = self._latest_source_inventory()
        if inventory.get("files"):
            return
        root = self._source_root()
        if not root or not root.is_dir():
            return
        try:
            inventory = build_source_inventory(self.workbench, root)
        except Exception:
            return
        self.source_inventory = inventory
        if hasattr(self.coverage, "put_source_inventory"):
            try:
                self.coverage.put_source_inventory(self.workbench, inventory)
            except Exception:
                pass

    def _write_event_checkpoint(self, event_type: str, fields: dict) -> None:
        if event_type == "loop_start":
            self._write_checkpoint("loop", "loop:start", "complete", fields)
        elif event_type == "coverage_enumerated":
            self._write_checkpoint(
                "coverage_enumeration",
                "coverage:enumerated",
                "complete",
                fields,
                output_refs=[f"coverage:{self.workbench}"],
            )
        elif event_type == "agent_start":
            self._write_checkpoint(
                "agent",
                f"agent:start:{fields.get('cid') or fields.get('unit_id') or 'unknown'}",
                "running",
                fields,
            )
        elif event_type == "agent_complete":
            self._write_checkpoint(
                "agent",
                f"agent:complete:{fields.get('cid') or fields.get('unit_id') or 'unknown'}",
                "complete",
                fields,
            )
        elif event_type == "report_refresh":
            self._write_checkpoint("report", "report:refresh", "complete", fields)
        elif event_type == "report_refresh_error":
            self._write_checkpoint("report", "report:refresh", "failed", fields)
        elif event_type in {"loop_idle", "loop_running"}:
            status = "complete" if event_type == "loop_idle" else "running"
            self._write_checkpoint("loop", f"loop:{event_type.removeprefix('loop_')}", status, fields)

    def _write_checkpoint(
        self,
        stage: str,
        checkpoint_key: str,
        status: str,
        payload: dict | None = None,
        *,
        output_refs: list[str] | None = None,
        input_hashes: dict[str, str] | None = None,
    ) -> None:
        if not hasattr(self.arcticbase, "put_runtime_checkpoint") or not self.run_id:
            return
        checkpoint = {
            "run_id": self.run_id,
            "stage": stage,
            "checkpoint_key": checkpoint_key,
            "status": status,
            "input_hashes": input_hashes or self._checkpoint_input_hashes(),
            "output_refs": output_refs or [],
            "payload": {"subject": self.subject, **(payload or {})},
        }
        try:
            created = self.arcticbase.put_runtime_checkpoint(self.workbench, checkpoint)
        except Exception:
            return
        checkpoint_id = created.get("id") if isinstance(created, dict) else None
        if checkpoint_id and checkpoint_id not in self.checkpoint_ids:
            self.checkpoint_ids.append(str(checkpoint_id))

    def _checkpoint_input_hashes(self) -> dict[str, str]:
        hashes = {"config:lanes": _stable_json_sha256(config.LANES)}
        hashes.update({f"source:{path}": sha for path, sha in self._source_hashes().items()})
        return hashes

    def _source_hashes(self) -> dict[str, str]:
        inventory = self.source_inventory if isinstance(self.source_inventory, dict) else {}
        hashes: dict[str, str] = {}
        for item in inventory.get("files") or []:
            path = str(item.get("path") or "")
            sha = str(item.get("sha256") or "")
            if path and sha:
                hashes[path] = sha
        return hashes

    def _scope_overlay_text(self) -> str:
        scope = self._scope_overlay()
        if not scope:
            return ""
        return json.dumps(scope, indent=2, sort_keys=True)

    def _scope_overlay(self) -> dict:
        if isinstance(self.scope_overlay, dict):
            return self.scope_overlay
        if not hasattr(self.coverage, "get_scope_overlay"):
            self.scope_overlay = {}
            return {}
        try:
            scope = self.coverage.get_scope_overlay(self.workbench) or {}
        except Exception:
            scope = {}
        self.scope_overlay = scope if isinstance(scope, dict) else {}
        return self.scope_overlay

    def _blackboard_text(self) -> str:
        path = self._blackboard_path()
        if not path.is_file():
            return ""
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return ""
        if not entries:
            return ""
        return "## Prior Results\n" + "\n---\n".join(str(item) for item in entries[-5:])

    def _push_blackboard(self, summary: str) -> None:
        if not summary:
            return
        path = self._blackboard_path()
        try:
            entries = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
        except json.JSONDecodeError:
            entries = []
        entries.append(summary[:600])
        path.write_text(json.dumps(entries[-10:], indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def _active_from_dict(item: dict) -> DispatchedConversation:
        # A resumed characterize conversation must still submit coverage on
        # completion, so default submits_coverage to True for that task class
        # when older state predates the field.
        task_class = item.get("task_class", "characterize")
        submits = item.get("submits_coverage")
        if submits is None:
            submits = task_class == "characterize"
        return DispatchedConversation(
            cid=item["cid"],
            subject=item.get("subject", ""),
            lane=item.get("lane", "A"),
            task_class=task_class,
            unit=item.get("unit"),
            objective=item.get("objective", ""),
            attempt=int(item.get("attempt") or 1),
            started_at=float(item.get("started_at") or time.time()),
            module_id=item.get("module_id"),
            module_target=item.get("module_target"),
            submits_coverage=bool(submits),
            workspace_host=item.get("workspace_host"),
        )

    def _persist_pending_actions(self, parsed: ParsedOutput, conversation: DispatchedConversation) -> None:
        if not hasattr(self.arcticbase, "create_pending_action"):
            return
        for action in parsed.pending_actions:
            if not isinstance(action, dict):
                continue
            payload = {
                "kind": action.get("kind") or "operator_decision_needed",
                "title": action.get("title") or "Pending REFALL action",
                "description": action.get("description") or action.get("summary") or "",
                "priority": action.get("priority") or "medium",
                "source_unit_id": action.get("source_unit_id") or (conversation.unit or {}).get("id"),
                "source_event_id": action.get("source_event_id"),
                "source_finding_id": action.get("source_finding_id"),
                "required_receipt_type": action.get("required_receipt_type"),
                "assigned_lane": action.get("assigned_lane"),
                "created_by": action.get("created_by") or "refall-standing-loop",
            }
            self.arcticbase.create_pending_action(self.workbench, payload)

    def _persist_findings(self, parsed: ParsedOutput, conversation: DispatchedConversation) -> None:
        if not parsed.findings or not hasattr(self.coverage, "add_finding"):
            return
        for finding in parsed.findings:
            payload = _finding_payload_for_store(finding, parsed, conversation)
            if not payload:
                continue
            try:
                self.coverage.add_finding(self.workbench, payload)
            except RuntimeError as exc:
                if "finding promotion refused" in str(exc):
                    self._record_finding_promotion_refusal(payload, parsed, conversation, str(exc))
                    continue
                self.arcticbase.append_ledger(
                    self.workbench,
                    {
                        "kind": "ops-event",
                        "action": "finding.persist.failed",
                        "status": "blocked",
                        "subject": self.subject,
                        "agent": conversation.cid,
                        "unit_id": (conversation.unit or {}).get("id"),
                        "summary": str(exc)[:500],
                        "finding_title": payload.get("title"),
                    },
                )

    def _record_finding_promotion_refusal(
        self,
        candidate: dict,
        parsed: ParsedOutput,
        conversation: DispatchedConversation,
        message: str,
    ) -> None:
        reasons = _promotion_refusal_reasons(message)
        pending_action_id = None
        if hasattr(self.arcticbase, "create_pending_action"):
            action = self.arcticbase.create_pending_action(
                self.workbench,
                {
                    "kind": "finding_candidate_review",
                    "title": f"Review refused finding candidate: {candidate.get('title') or 'untitled'}",
                    "description": message,
                    "priority": "high" if str(candidate.get("severity") or "").upper() in {"HIGH", "CRITICAL"} else "medium",
                    "source_unit_id": (conversation.unit or {}).get("id"),
                    "required_receipt_type": "manager_review",
                    "assigned_lane": "source-analysis",
                    "created_by": "refall-standing-loop",
                },
            )
            pending_action_id = action.get("id") if isinstance(action, dict) else None
        self.arcticbase.append_ledger(
            self.workbench,
            {
                "kind": "ops-event",
                "action": "finding.promotion.refused",
                "status": "blocked",
                "subject": self.subject,
                "agent": conversation.cid,
                "unit_id": (conversation.unit or {}).get("id"),
                "summary": message,
                "candidate": candidate,
                "reasons": reasons,
                "pending_action_id": pending_action_id,
                "coverage": list(parsed.coverage),
            },
        )
        self._append_event(
            "finding_promotion_refused",
            {
                "subject": self.subject,
                "cid": conversation.cid,
                "unit_id": (conversation.unit or {}).get("id"),
                "candidate_title": candidate.get("title"),
                "reasons": reasons,
                "pending_action_id": pending_action_id,
            },
        )

    def _persist_capability_requests(self, parsed: ParsedOutput, conversation: DispatchedConversation) -> None:
        if not parsed.capability_requests or not hasattr(self.arcticbase, "request_capability"):
            return
        for request in parsed.capability_requests:
            payload = {
                "class": request.get("class"),
                "scope": request.get("scope") or {},
                "requested_by": request.get("requested_by") or conversation.cid,
                "reason": request.get("reason") or "",
            }
            try:
                self.arcticbase.request_capability(self.workbench, payload)
            except RuntimeError as exc:
                self.arcticbase.append_ledger(
                    self.workbench,
                    {
                        "kind": "ops-event",
                        "action": "capability.request.failed",
                        "status": "blocked",
                        "subject": self.subject,
                        "agent": conversation.cid,
                        "unit_id": (conversation.unit or {}).get("id"),
                        "summary": str(exc)[:500],
                    },
                )

    def _persist_threat_model(
        self,
        parsed: ParsedOutput,
        conversation: DispatchedConversation,
        response: str,
    ) -> dict | None:
        payload = _threat_model_payload_for_store(parsed, conversation, response)
        if not payload:
            summary = "Threat model worker finished without a valid threat_model_submit payload."
            self.arcticbase.append_ledger(
                self.workbench,
                {
                    "kind": "ops-event",
                    "action": "threat-model.persist.failed",
                    "status": "blocked",
                    "subject": self.subject,
                    "agent": conversation.cid,
                    "unit_id": (conversation.unit or {}).get("id"),
                    "summary": summary,
                },
            )
            if hasattr(self.arcticbase, "create_pending_action"):
                self.arcticbase.create_pending_action(
                    self.workbench,
                    {
                        "kind": "operator_decision_needed",
                        "title": "Threat model output needs manager review",
                        "description": summary,
                        "source_unit_id": (conversation.unit or {}).get("id"),
                        "priority": "medium",
                        "required_receipt_type": "manager_review",
                        "created_by": "refall-standing-loop",
                    },
                )
            return None
        if not hasattr(self.coverage, "put_threat_model"):
            return None
        try:
            stored = self.coverage.put_threat_model(self.workbench, payload)
        except Exception as exc:
            self.arcticbase.append_ledger(
                self.workbench,
                {
                    "kind": "ops-event",
                    "action": "threat-model.persist.failed",
                    "status": "blocked",
                    "subject": self.subject,
                    "agent": conversation.cid,
                    "unit_id": (conversation.unit or {}).get("id"),
                    "summary": str(exc)[:500],
                },
            )
            return None
        self.threat_model = stored if isinstance(stored, dict) else payload
        self._append_event(
            "threat_model_updated",
            {
                "subject": self.subject,
                "cid": conversation.cid,
                "unit_id": (conversation.unit or {}).get("id"),
                "threat_model_id": self.threat_model.get("threat_model_id"),
                "threats": len(self.threat_model.get("threats") or []),
                "assets": len(self.threat_model.get("assets") or []),
            },
        )
        return self.threat_model

    def _save_failed_submit_artifact(
        self,
        conversation: DispatchedConversation,
        result: PollResult,
        outcome,
    ) -> list[str]:
        if not hasattr(self.arcticbase, "create_runtime_artifact"):
            return []
        content = result.response or ""
        mime = "text/plain"
        if not content and result.trajectory:
            # Agent Canvas trajectories are binary session archives. Decoding
            # them with replacement corrupts the ZIP and destroys the provider
            # diagnostic we need to explain terminal worker failures.
            content = json.dumps(
                {
                    "schema": "refall.worker-trajectory.v1",
                    "status": result.status,
                    "last_error": outcome.last_error,
                    "trajectory_encoding": "base64",
                    "trajectory_sha256": hashlib.sha256(result.trajectory).hexdigest(),
                    "trajectory_base64": base64.b64encode(result.trajectory).decode("ascii"),
                },
                sort_keys=True,
            )
            mime = "application/json"
        if not content:
            content = outcome.last_error
        try:
            artifact = self.arcticbase.create_runtime_artifact(
                self.workbench,
                {
                    "kind": "worker-submit-invalid",
                    "content": content,
                    "mime": mime,
                    "task_id": (conversation.unit or {}).get("id"),
                    "source_event_id": conversation.cid,
                },
            )
        except Exception:
            return []
        artifact_id = artifact.get("id")
        return [str(artifact_id)] if artifact_id else []

    def _record_retry_failure(
        self,
        conversation: DispatchedConversation,
        outcome,
        artifact_refs: list[str],
    ) -> None:
        try:
            conn = connect_runtime(self.subject_path)
            record_retry_failure(
                conn,
                str((conversation.unit or {}).get("id") or conversation.cid),
                conversation.cid,
                outcome,
                artifact_refs=artifact_refs,
            )
        except Exception:
            pass

    def _structured_submissions_already_applied(self, keys: list[str]) -> bool:
        try:
            conn = connect_runtime(self.subject_path)
            return all(
                conn.execute("SELECT 1 FROM control_signals WHERE id=?", (_submission_marker_id(key),)).fetchone()
                for key in keys
            )
        except Exception:
            return False

    def _record_structured_submissions(self, keys: list[str]) -> None:
        try:
            conn = connect_runtime(self.subject_path)
            now = time.time()
            for key in keys:
                conn.execute(
                    "INSERT OR IGNORE INTO control_signals(id,subject,kind,payload,created_at) VALUES(?,?,?,?,?)",
                    (
                        _submission_marker_id(key),
                        self.subject,
                        "structured_submission_applied",
                        json.dumps({"key": key}),
                        now,
                    ),
                )
            conn.commit()
        except Exception:
            pass

    def _start_retry(
        self,
        conversation: DispatchedConversation,
        outcome,
        artifact_refs: list[str],
    ) -> DispatchedConversation | None:
        # Provider failover: if a Claude (lane A) agent balks at a task -- refuses,
        # truncates, or ends without a valid submit -- retry it on Codex (lane B)
        # instead of re-dispatching to the same provider. Retries are capped, so
        # this switches once and cannot ping-pong.
        retry_lane = _failover_lane(conversation.lane)
        if retry_lane != conversation.lane:
            self._append_event(
                "retry_provider_switch",
                {
                    "subject": self.subject,
                    "cid": conversation.cid,
                    "from_lane": conversation.lane,
                    "to_lane": retry_lane,
                    "failure_class": outcome.failure_class,
                    "unit_id": (conversation.unit or {}).get("id"),
                },
            )
        task = AgentTask(
            subject=conversation.subject,
            task_class=conversation.task_class,
            lane=retry_lane,
            unit=conversation.unit,
            objective=_retry_objective(conversation, outcome, artifact_refs, switched_to=retry_lane if retry_lane != conversation.lane else None),
            max_iterations=30,
            attempt=conversation.attempt + 1,
            module_id=conversation.module_id,
            module_target=conversation.module_target,
            submits_coverage=conversation.submits_coverage,
        )
        try:
            retry = self.dispatcher.start(task)
        except Exception as exc:
            self.arcticbase.append_ledger(
                self.workbench,
                {
                    "kind": "ops-event",
                    "action": "retry.dispatch.failed",
                    "status": "blocked",
                    "subject": self.subject,
                    "agent": conversation.cid,
                    "unit_id": (conversation.unit or {}).get("id"),
                    "summary": str(exc)[:500],
                    "artifact_refs": artifact_refs,
                },
            )
            return None
        self._append_event(
            "retry_scheduled",
            {
                "subject": self.subject,
                "cid": retry.cid,
                "prior_cid": conversation.cid,
                "failure_class": outcome.failure_class,
                "unit_id": (conversation.unit or {}).get("id"),
                "attempt": retry.attempt,
                "max_attempts": outcome.max_attempts,
                "artifact_refs": artifact_refs,
            },
        )
        self._retire_replaced_conversation(conversation, retry, outcome)
        return retry

    def _retire_replaced_conversation(
        self,
        conversation: DispatchedConversation,
        retry: DispatchedConversation,
        outcome: InvocationOutcome,
    ) -> None:
        # Archive before deleting, exactly as the success path does. A retried
        # conversation is the one whose events matter most -- it is the failed
        # attempt a reviewer needs in order to judge whether the retry was right.
        archive_status = self._archive_conversation_events(conversation)
        delete_status = "unsupported"
        delete = getattr(self.dispatcher, "delete", None)
        if callable(delete):
            try:
                delete(conversation.cid)
                delete_status = "deleted"
            except Exception as exc:
                delete_status = "delete_failed"
                self._append_event(
                    "retry_prior_delete_failed",
                    {
                        "subject": self.subject,
                        "cid": conversation.cid,
                        "replacement_cid": retry.cid,
                        "failure_class": outcome.failure_class,
                        "unit_id": (conversation.unit or {}).get("id"),
                        "error": str(exc)[:500],
                    },
                )
        self._append_event(
            "agent_complete",
            {
                "subject": self.subject,
                "cid": conversation.cid,
                "replacement_cid": retry.cid,
                "lane": conversation.lane,
                "phase": conversation.task_class,
                "unit_id": (conversation.unit or {}).get("id"),
                "status": "retry_replaced",
                "archive_status": archive_status,
                "delete_status": delete_status,
                "failure_class": outcome.failure_class,
                "facts": 0,
                "findings": 0,
                "leads": 0,
                "pending_actions": 0,
            },
        )

    def _create_failure_pending_action(
        self,
        conversation: DispatchedConversation,
        outcome: InvocationOutcome,
        artifact_refs: list[str],
    ) -> bool:
        unit_id = (conversation.unit or {}).get("id")
        if outcome.failure_class == "capability_missing":
            capability_class = _capability_class_from_failure(outcome.last_error)
            if hasattr(self.arcticbase, "request_capability"):
                self.arcticbase.request_capability(
                    self.workbench,
                    {
                        "class": capability_class,
                        "scope": _capability_scope_from_failure(outcome.last_error),
                        "requested_by": conversation.cid,
                        "reason": outcome.last_error,
                    },
                )
            if hasattr(self.arcticbase, "create_pending_action"):
                self.arcticbase.create_pending_action(
                    self.workbench,
                    {
                        "kind": "operator_decision_needed",
                        "title": f"Capability required: {capability_class}",
                        "description": outcome.last_error,
                        "source_unit_id": unit_id,
                        "source_event_id": artifact_refs[0] if artifact_refs else None,
                        "priority": "high",
                        "required_receipt_type": "capability_decision",
                        "created_by": "refall-standing-loop",
                    },
                )
            return True
        if outcome.failure_class == "scope_blocked":
            if hasattr(self.arcticbase, "create_pending_action"):
                self.arcticbase.create_pending_action(
                    self.workbench,
                    {
                        "kind": "operator_decision_needed",
                        "title": f"Scope blocked for {conversation.cid}",
                        "description": outcome.last_error,
                        "source_unit_id": unit_id,
                        "source_event_id": artifact_refs[0] if artifact_refs else None,
                        "priority": "high",
                        "required_receipt_type": "scope_decision",
                        "created_by": "refall-standing-loop",
                    },
                )
            return True
        return False

    def _apply_structured_transitions(self, parsed: ParsedOutput, conversation: DispatchedConversation) -> None:
        if not parsed.transitions or not hasattr(self.arcticbase, "transition_finding"):
            return
        for item in parsed.transitions:
            finding_id = str(item.get("finding_id") or "").strip()
            transition = dict(item.get("transition") or {})
            if not finding_id or not transition:
                if hasattr(self.arcticbase, "create_pending_action"):
                    self.arcticbase.create_pending_action(
                        self.workbench,
                        {
                            "kind": "operator_decision_needed",
                            "title": "Structured transition needs manager review",
                            "description": "Worker proposed a finding transition without a usable finding_id.",
                            "source_unit_id": (conversation.unit or {}).get("id"),
                            "priority": "high",
                            "required_receipt_type": "manager_review",
                            "created_by": "refall-standing-loop",
                        },
                    )
                continue
            transition.setdefault("proposed_by", conversation.cid)
            transition.setdefault("reason", parsed.done or "Structured REFALL transition proposal.")
            try:
                result = self.arcticbase.transition_finding(self.workbench, finding_id, transition)
            except RuntimeError as exc:
                self.arcticbase.append_ledger(
                    self.workbench,
                    {
                        "kind": "ops-event",
                        "action": "disposition.transition.failed",
                        "status": "blocked",
                        "subject": self.subject,
                        "agent": conversation.cid,
                        "unit_id": (conversation.unit or {}).get("id"),
                        "finding_id": finding_id,
                        "summary": str(exc)[:500],
                    },
                )
                if hasattr(self.arcticbase, "create_pending_action"):
                    self.arcticbase.create_pending_action(
                        self.workbench,
                        {
                            "kind": "operator_decision_needed",
                            "title": f"Disposition transition failed for {finding_id}",
                            "description": str(exc)[:500],
                            "source_unit_id": (conversation.unit or {}).get("id"),
                            "source_finding_id": finding_id,
                            "priority": "high",
                            "required_receipt_type": "manager_review",
                            "created_by": "refall-standing-loop",
                        },
                    )
                continue
            if str(result.get("status") or "").lower() == "refused" and hasattr(self.arcticbase, "create_pending_action"):
                self.arcticbase.create_pending_action(
                    self.workbench,
                    {
                        "kind": "operator_decision_needed",
                        "title": f"Disposition transition refused for {finding_id}",
                        "description": "; ".join(str(reason) for reason in result.get("refusal_reasons") or []),
                        "source_unit_id": (conversation.unit or {}).get("id"),
                        "source_finding_id": finding_id,
                        "priority": "high",
                        "required_receipt_type": "manager_review",
                        "created_by": "refall-standing-loop",
                    },
                )

    def _resolve_pending_action(
        self,
        conversation: DispatchedConversation,
        result: PollResult,
        parsed: ParsedOutput,
    ) -> None:
        if not hasattr(self.arcticbase, "resolve_pending_action"):
            return
        action = conversation.unit or {}
        action_id = str(action.get("id") or "")
        if not action_id:
            return
        summary = parsed.done or (result.response or "")[:500] or "Pending action worker finished without a summary."
        receipt = {
            "summary": summary,
            "evidence_refs": _pending_action_evidence_refs(parsed),
            "finding_titles": [
                str(finding.get("title"))
                for finding in parsed.findings
                if finding.get("title")
            ],
            "lead_titles": [
                str(lead.get("title"))
                for lead in parsed.leads
                if lead.get("title")
            ],
            "resolved_by_agent": conversation.cid,
        }
        receipt_type = str(action.get("required_receipt_type") or "agent_resolution")
        try:
            self.arcticbase.resolve_pending_action(
                self.workbench,
                action_id,
                receipt,
                receipt_type=receipt_type,
                resolved_by="refall-standing-loop",
            )
            self._append_event(
                "pending_action_resolved",
                {
                    "subject": self.subject,
                    "cid": conversation.cid,
                    "unit_id": action_id,
                    "receipt_type": receipt_type,
                },
            )
        except RuntimeError as exc:
            self.arcticbase.append_ledger(
                self.workbench,
                {
                    "kind": "ops-event",
                    "action": "pending.resolve.failed",
                    "status": "blocked",
                    "subject": self.subject,
                    "agent": conversation.cid,
                    "pending_action_id": action_id,
                    "summary": str(exc)[:500],
                },
            )
            self._append_event(
                "pending_action_resolution_failed",
                {
                    "subject": self.subject,
                    "cid": conversation.cid,
                    "unit_id": action_id,
                    "error": str(exc)[:500],
                },
            )

    def _resolve_threat_model_action(
        self,
        conversation: DispatchedConversation,
        threat_model: dict,
    ) -> None:
        if not hasattr(self.arcticbase, "resolve_pending_action"):
            return
        action = conversation.unit or {}
        action_id = str(action.get("id") or "")
        if not action_id:
            return
        threat_model_id = str(threat_model.get("threat_model_id") or "threat-model")
        receipt = {
            "summary": f"Threat model stored: {threat_model_id}",
            "evidence_refs": [threat_model_id],
            "threat_model_id": threat_model_id,
            "threat_count": len(threat_model.get("threats") or []),
            "asset_count": len(threat_model.get("assets") or []),
            "resolved_by_agent": conversation.cid,
        }
        receipt_type = str(action.get("required_receipt_type") or "threat_model")
        try:
            self.arcticbase.resolve_pending_action(
                self.workbench,
                action_id,
                receipt,
                receipt_type=receipt_type,
                resolved_by="refall-standing-loop",
            )
            self._append_event(
                "threat_model_request_resolved",
                {
                    "subject": self.subject,
                    "cid": conversation.cid,
                    "unit_id": action_id,
                    "threat_model_id": threat_model_id,
                },
            )
        except RuntimeError as exc:
            self.arcticbase.append_ledger(
                self.workbench,
                {
                    "kind": "ops-event",
                    "action": "threat-model.resolve.failed",
                    "status": "blocked",
                    "subject": self.subject,
                    "agent": conversation.cid,
                    "pending_action_id": action_id,
                    "summary": str(exc)[:500],
                },
            )


def parse_agent_output(response: str, defaults: dict | None = None) -> ParsedOutput:
    parsed = ParsedOutput()
    structured = parse_refall_submissions(response, defaults)
    parsed.structured = structured.submissions
    parsed.structured_errors = structured.errors
    parsed.structured_missing = structured.missing
    if structured.valid:
        for submission in structured.submissions:
            parsed.pending_actions.extend(_pending_actions_from_submission(submission))
            for transition in _transitions_from_submission(submission):
                parsed.transitions.append(transition)
            if submission.get("type") == "task_result_submit":
                if _structured_status_is_done(submission):
                    parsed.done = str(submission.get("summary") or "")
                else:
                    parsed.pending_actions.append(_pending_action_from_blocked_submission(submission))
                parsed.coverage.extend(coverage_paths_from_submission(submission))
                for fact in _submission_intelligence(submission, "facts"):
                    normalized = _normalize_structured_intel("fact", fact)
                    if normalized:
                        parsed.facts.append(normalized)
                for flow in _submission_intelligence(submission, "flows"):
                    normalized = _normalize_structured_intel("flow", flow)
                    if normalized:
                        parsed.flows.append(normalized)
                for lead in _submission_intelligence(submission, "leads"):
                    normalized = _normalize_structured_intel("lead", lead)
                    if normalized:
                        parsed.leads.append(normalized)
                for ask in submission.get("asks") or []:
                    if isinstance(ask, dict):
                        parsed.asks.append({"kind": "ask", **ask})
                for finding in _submission_intelligence(submission, "findings"):
                    if isinstance(finding, dict):
                        parsed.findings.append({"kind": "finding", **finding})
            elif submission.get("type") == "finding_submit":
                for finding in submission.get("findings") or [submission]:
                    if isinstance(finding, dict):
                        parsed.findings.append({"kind": "finding", **finding})
            elif submission.get("type") == "control_submit":
                parsed.asks.append({
                    "kind": "ask",
                    "title": str(submission.get("status") or "control"),
                    "description": str(submission.get("summary") or ""),
                })
                if submission.get("status") == "needs_capability":
                    capability_class = str(submission.get("capability_class") or "capability")
                    parsed.capability_requests.append({
                        "class": capability_class,
                        "scope": submission.get("capability_scope") or submission.get("scope") or {},
                        "requested_by": str(submission.get("produced_by") or "refall-worker"),
                        "reason": str(submission.get("summary") or ""),
                    })
                    parsed.pending_actions.append({
                        "kind": "operator_decision_needed",
                        "title": f"Capability required: {capability_class}",
                        "description": str(submission.get("summary") or ""),
                        "priority": "high",
                        "source_event_id": submission.get("submission_id") or submission.get("task_id"),
                        "required_receipt_type": "capability_decision",
                    })
            elif submission.get("type") == "threat_model_submit":
                threat_model = submission.get("threat_model")
                if isinstance(threat_model, dict):
                    parsed.threat_models.append(threat_model)
        primary = primary_submission(structured)
        if not parsed.done and _structured_status_is_done(primary):
            parsed.done = str(primary.get("summary") or "")
        return parsed

    json_blocks = re.findall(r"```finding\s*\n(.*?)\n```", response, re.DOTALL | re.IGNORECASE)
    for block in json_blocks:
        try:
            finding = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(finding, dict):
            finding.setdefault("kind", "finding")
            parsed.findings.append(finding)

    in_finding_block = False
    for raw_line in response.splitlines():
        line = raw_line.strip()
        # Markers frequently arrive as JSON array-string elements inside a
        # ```refall-submit block whose submission failed strict validation
        # (e.g. missing produced_by) — e.g.  "[FACT] arch:x | y",  — so the
        # bare regexes below never match. Unwrap the JSON string quoting first
        # so the same parsers apply and no intel is silently discarded.
        if line.startswith('"[') and (line.endswith('"') or line.endswith('",')):
            try:
                line = json.loads(line.rstrip().rstrip(","))
            except (json.JSONDecodeError, ValueError):
                pass
        if line.lower().startswith("```finding"):
            in_finding_block = True
            continue
        if in_finding_block and line.startswith("```"):
            in_finding_block = False
            continue
        if in_finding_block or not line:
            continue

        lead = re.match(r"\[LEAD:(\w+)\]\s*(.+?)(?:\s*\|\s*(.+?))?(?:\s*\|\s*(.+?))?$", line, re.I)
        if lead:
            parsed.leads.append({
                "kind": "lead",
                "severity": lead.group(1).lower(),
                "title": lead.group(2).strip(),
                "description": (lead.group(3) or "").strip(),
                "investigation_plan": (lead.group(4) or "").strip(),
            })
            continue

        # [FLOW] <from> -> <to> : <relation> | <evidence>  -- a code/data-flow
        # edge, structured enough to reconstruct call graphs and diagrams later.
        flow = re.match(
            r"\[FLOW\]\s*(.+?)\s*->\s*(.+?)\s*:\s*(\w+)(?:\s*\|\s*(.+?))?$", line, re.I
        )
        if flow:
            parsed.flows.append({
                "kind": "flow",
                "from": flow.group(1).strip(),
                "to": flow.group(2).strip(),
                "relation": flow.group(3).strip().lower(),
                "evidence": (flow.group(4) or "").strip(),
            })
            continue

        fact = re.match(r"\[FACT\]\s*(.+?)(?:\s*\|\s*(.+?))?$", line, re.I)
        if fact:
            parsed.facts.append({
                "kind": "fact",
                "title": fact.group(1).strip(),
                "description": (fact.group(2) or "").strip(),
            })
            continue

        ask = re.match(r"\[ASK\]\s*(.+?)(?:\s*\|\s*(.+?))?$", line, re.I)
        if ask:
            parsed.asks.append({
                "kind": "ask",
                "title": ask.group(1).strip(),
                "description": (ask.group(2) or "").strip(),
            })
            continue

        coverage = re.match(r"\[COVERAGE\]\s*(.+)$", line, re.I)
        if coverage:
            parsed.coverage.extend([
                item.strip()
                for item in coverage.group(1).split(",")
                if item.strip()
            ])
            continue

        done = re.match(r"\[DONE\]\s*(.+)$", line, re.I)
        if done:
            parsed.done = done.group(1).strip()
            continue
    return parsed


def _submission_intelligence(submission: dict, key: str) -> list:
    """Return intelligence from both contract-native and common nested shape.

    Agents frequently interpret the required `evidence` field as an evidence
    package and place facts/flows/findings beneath it. Preserve that valid,
    source-anchored work instead of silently recording only the envelope.
    """
    items: list = []
    direct = submission.get(key)
    if isinstance(direct, list):
        items.extend(direct)
    evidence = submission.get("evidence")
    if isinstance(evidence, dict):
        nested = evidence.get(key)
        if isinstance(nested, list):
            items.extend(nested)
    elif isinstance(evidence, list):
        expected_kind = {
            "facts": "fact",
            "flows": "flow",
            "leads": "lead",
            "findings": "finding",
        }.get(key)
        if expected_kind:
            items.extend(
                item
                for item in evidence
                if isinstance(item, dict)
                and str(item.get("kind") or "").strip().lower() == expected_kind
            )
    return items


def _normalize_structured_intel(kind: str, item) -> dict | None:
    payload = dict(item) if isinstance(item, dict) else {}
    text = str(payload.get("text") if isinstance(item, dict) else item or "").strip()
    if kind == "fact":
        match = re.match(r"\[FACT\]\s*(.+?)(?:\s*\|\s*(.+?))?$", text, re.I)
        if match:
            payload.setdefault("title", match.group(1).strip())
            payload.setdefault("description", (match.group(2) or "").strip())
        elif text:
            payload.setdefault("title", str(payload.get("id") or "Structured fact"))
            payload.setdefault("description", text)
        return {"kind": "fact", **payload} if payload.get("title") else None
    if kind == "flow":
        match = re.match(
            r"\[FLOW\]\s*(.+?)\s*->\s*(.+?)\s*:\s*(\w+)(?:\s*\|\s*(.+?))?$", text, re.I
        )
        if match:
            payload.setdefault("from", match.group(1).strip())
            payload.setdefault("to", match.group(2).strip())
            payload.setdefault("relation", match.group(3).strip().lower())
            payload.setdefault("evidence", (match.group(4) or "").strip())
        return {"kind": "flow", **payload} if payload.get("from") and payload.get("to") else None
    if kind == "lead":
        match = re.match(r"\[LEAD:(\w+)\]\s*(.+?)(?:\s*\|\s*(.+?))?(?:\s*\|\s*(.+?))?$", text, re.I)
        if match:
            payload.setdefault("severity", match.group(1).lower())
            payload.setdefault("title", match.group(2).strip())
            payload.setdefault("description", (match.group(3) or "").strip())
            payload.setdefault("investigation_plan", (match.group(4) or "").strip())
        elif text:
            payload.setdefault("title", str(payload.get("id") or "Structured lead"))
            payload.setdefault("description", text)
        return {"kind": "lead", **payload} if payload.get("title") else None
    return None


def _structured_status_is_done(submission: dict) -> bool:
    return str(submission.get("status") or "").strip().lower() in {
        "characterized",
        "done",
        "complete",
        "completed",
    }


def _transitions_from_submission(submission: dict) -> list[dict]:
    transitions: list[dict] = []
    direct = _transition_from_holder(submission, submission)
    if direct:
        transitions.append(direct)
    for finding in submission.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        nested = _transition_from_holder(finding, submission)
        if nested:
            transitions.append(nested)
    return transitions


def _transition_from_holder(holder: dict, submission: dict) -> dict | None:
    proposed = holder.get("proposed_transition")
    if not isinstance(proposed, dict):
        return None
    finding_id = proposed.get("finding_id") or holder.get("finding_id") or holder.get("id")
    if holder is submission:
        findings = [item for item in submission.get("findings") or [] if isinstance(item, dict)]
        if not finding_id and len(findings) == 1:
            finding_id = findings[0].get("id") or findings[0].get("finding_id")
    transition = dict(proposed)
    transition.pop("finding_id", None)
    transition.setdefault("proposed_by", str(submission.get("produced_by") or "refall-worker"))
    transition.setdefault("reason", str(holder.get("summary") or submission.get("summary") or ""))
    if holder.get("receipt_type") and not transition.get("receipt_type"):
        transition["receipt_type"] = holder.get("receipt_type")
    if submission.get("receipt_type") and not transition.get("receipt_type"):
        transition["receipt_type"] = submission.get("receipt_type")
    if holder.get("receipt") and not transition.get("receipt"):
        transition["receipt"] = holder.get("receipt")
    if submission.get("receipt") and not transition.get("receipt"):
        transition["receipt"] = submission.get("receipt")
    if holder.get("duplicate_of") and not transition.get("duplicate_of"):
        transition["duplicate_of"] = holder.get("duplicate_of")
    if submission.get("duplicate_of") and not transition.get("duplicate_of"):
        transition["duplicate_of"] = submission.get("duplicate_of")
    return {"finding_id": finding_id, "transition": transition}


def _pending_actions_from_submission(submission: dict) -> list[dict]:
    actions: list[dict] = []
    for action in submission.get("pending_actions") or []:
        if not isinstance(action, dict):
            continue
        title = str(action.get("title") or action.get("summary") or "").strip()
        if not title:
            title = "Pending REFALL action"
        actions.append({
            "kind": action.get("kind") or "operator_decision_needed",
            "title": title,
            "description": action.get("description") or action.get("summary") or "",
            "priority": action.get("priority") or "medium",
            "source_event_id": action.get("source_event_id") or submission.get("submission_id") or submission.get("task_id"),
            "source_unit_id": action.get("source_unit_id") or submission.get("unit_id"),
            "source_finding_id": action.get("source_finding_id"),
            "required_receipt_type": action.get("required_receipt_type"),
            "assigned_lane": action.get("assigned_lane"),
            "created_by": action.get("created_by") or str(submission.get("produced_by") or "refall-worker"),
        })
    return actions


def _pending_action_from_blocked_submission(submission: dict) -> dict:
    status = str(submission.get("status") or "blocked")
    summary = str(submission.get("summary") or "")
    return {
        "kind": "operator_decision_needed" if status.startswith("needs_") else "worker_blocked",
        "title": f"Worker reported {status}",
        "description": summary,
        "priority": "high" if status in {"needs_capability", "blocked"} else "medium",
        "source_event_id": submission.get("submission_id") or submission.get("task_id"),
        "source_unit_id": submission.get("unit_id"),
        "required_receipt_type": "manager_review",
        "created_by": str(submission.get("produced_by") or "refall-worker"),
    }


def _should_submit_coverage(parsed: ParsedOutput) -> bool:
    if parsed.structured:
        return bool(parsed.done)
    return True


def _structured_submission_keys(parsed: ParsedOutput, conversation: DispatchedConversation) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for submission in parsed.structured:
        if not isinstance(submission, dict):
            continue
        subject = str(submission.get("subject") or conversation.subject or "").strip()
        submission_id = str(submission.get("submission_id") or "").strip()
        task_id = str(
            submission.get("task_id")
            or submission.get("unit_id")
            or (conversation.unit or {}).get("id")
            or ""
        ).strip()
        identity_scope = "report:" if conversation.task_class == "report" else ""
        if submission_id:
            key = f"{subject}:{identity_scope}submission:{submission_id}"
        elif task_id:
            submit_type = str(submission.get("type") or "unknown").strip()
            key = f"{subject}:{identity_scope}task:{task_id}:{submit_type}"
        else:
            continue
        if key not in seen:
            keys.append(key)
            seen.add(key)
    return keys


def _submission_marker_id(key: str) -> str:
    return "ssub_" + hashlib.sha256(key.encode("utf-8")).hexdigest()


def _pending_action_claimable(action: dict, now: float) -> bool:
    status = str(action.get("status") or "")
    if status == "open":
        return True
    if status != "claimed":
        return False
    lease = action.get("lease_expires")
    try:
        return lease is not None and float(lease) < now
    except (TypeError, ValueError):
        return False


def _pending_action_worker_claimable(action: dict) -> bool:
    """Return whether the standing loop may dispatch this action.

    Watchdog stop receipts and source-inventory promotion refusals are manager
    work. Re-dispatching them to worker agents creates an endless lease/stop/
    requeue cycle without changing the underlying decision or evidence.
    """
    kind = str(action.get("kind") or "").strip().lower()
    receipt_type = str(action.get("required_receipt_type") or "").strip().lower()
    description = str(action.get("description") or "").lower()
    if kind == "watchdog_conversation_stopped" or receipt_type == "watchdog_stop_review":
        return False
    if kind == "finding_candidate_review" and (
        receipt_type == "manager_review"
        or "source anchor not in source inventory" in description
    ):
        return False
    return True


def _pending_action_sort_key(action: dict) -> tuple[int, int, str]:
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    kind_order = {"live_validation_pending": 0, "operator_decision_needed": 1}
    return (
        priority_order.get(str(action.get("priority") or "medium").lower(), 4),
        kind_order.get(str(action.get("kind") or ""), 2),
        str(action.get("updated_at") or action.get("created_at") or ""),
    )


def _require_structured_submit() -> bool:
    return os.environ.get("REFALL_REQUIRE_STRUCTURED_SUBMIT", "false").lower() in {"1", "true", "yes"}


def _retry_max_attempts() -> int:
    try:
        return max(1, int(os.environ.get("REFALL_RETRY_MAX_ATTEMPTS", str(config.RETRY_MAX_ATTEMPTS))))
    except ValueError:
        return max(1, config.RETRY_MAX_ATTEMPTS)


def _provider_roles() -> dict:
    roles = {"manager": os.environ.get("REFALL_MANAGER_PROVIDER", "codex")}
    for lane, settings in config.LANES.items():
        roles[lane] = (
            settings.get("acp_server")
            or settings.get("runner")
            or settings.get("model")
            or "unknown"
        )
    return roles


def _stable_json_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "requested"}
    return False


def _promotion_refusal_reasons(message: str) -> list[str]:
    _, _, detail = str(message).partition(":")
    return [part.strip() for part in detail.split(";") if part.strip()]


# Provider failover order: Claude (A) balks -> retry on Codex (B). Other lanes
# retry on themselves (no second provider defined for them).
_LANE_FAILOVER = {"A": "B"}


def _failover_lane(lane: str) -> str:
    return _LANE_FAILOVER.get(lane, lane)


def _retry_objective(
    conversation: DispatchedConversation,
    outcome,
    artifact_refs: list[str],
    switched_to: str | None = None,
) -> str:
    artifact_text = ", ".join(artifact_refs) if artifact_refs else "none"
    switch_note = (
        f"This task was reassigned to a different provider (lane {switched_to}) because the "
        "previous provider balked. Approach it fresh with your own tooling."
        if switched_to else ""
    )
    return "\n\n".join(part for part in [
        conversation.objective,
        "## Retry Repair",
        (
            f"Previous attempt {outcome.attempt}/{outcome.max_attempts} failed with "
            f"{outcome.failure_class}: {outcome.last_error}"
        ),
        switch_note,
        f"Failed-output artifact refs: {artifact_text}",
        (
            "Return only a valid terminal ```refall-submit JSON block using schema "
            "refall.submit.v1. Keep it compact and include source_anchors or artifact_refs."
        ),
    ] if part)


def _entries_from_parsed(parsed: ParsedOutput, conversation: DispatchedConversation) -> list[dict]:
    base = {
        "subject": conversation.subject,
        "lane": conversation.lane,
        "agent": conversation.cid,
        "unit_id": (conversation.unit or {}).get("id"),
        "phase": conversation.task_class,
    }
    entries: list[dict] = []
    for finding in parsed.findings:
        entries.append({**base, **finding, "kind": "finding"})
    for fact in parsed.facts:
        entries.append({**base, **fact, "kind": "fact"})
    for lead in parsed.leads:
        entries.append({**base, **lead, "kind": "lead"})
    for flow in parsed.flows:
        # A flow edge is durable evidence of a code/data trace. Stored as a fact
        # so it lives in the ledger (an allowed kind) while keeping its typed
        # from/to/relation fields, which a viz agent reads to build the graph.
        entries.append({
            **base, "kind": "fact", "fact_kind": "flow",
            "title": f"{flow.get('from')} -> {flow.get('to')} ({flow.get('relation')})",
            "flow": flow,
        })
    for ask in parsed.asks:
        entries.append({**base, **ask, "kind": "ask"})
    if parsed.done:
        entries.append({**base, "kind": "coverage", "title": "Agent completed coverage unit", "summary": parsed.done})
    return entries


def _finding_payload_for_store(
    finding: dict,
    parsed: ParsedOutput,
    conversation: DispatchedConversation,
) -> dict | None:
    if not isinstance(finding, dict):
        return None
    title = str(finding.get("title") or finding.get("name") or "").strip()
    if not title:
        return None
    payload = {
        key: value
        for key, value in finding.items()
        if key not in {"kind", "proposed_transition", "receipt", "receipt_type"}
    }
    payload["title"] = title
    envelope = _finding_envelope_defaults(parsed, finding)
    for key in ("evidence", "source_anchors", "artifact_refs", "confidence", "limitations"):
        if payload.get(key) in (None, "", [], {}) and envelope.get(key) not in (None, "", [], {}):
            payload[key] = envelope[key]
    payload = _normalize_finding_payload_shape(payload)
    code_paths = _finding_code_paths(finding, parsed, conversation)
    if not code_paths:
        return None
    payload["code_paths"] = code_paths
    payload.setdefault("source_unit_id", (conversation.unit or {}).get("id"))
    if str(payload.get("status") or "PROVISIONALLY_VALID") not in {"PROVISIONALLY_VALID", "NEEDS_RESEARCH"}:
        payload["status"] = "PROVISIONALLY_VALID"
    else:
        payload.setdefault("status", "PROVISIONALLY_VALID")
    payload.setdefault("quality_tier", "HYPOTHESIS")
    payload.setdefault("created_by", conversation.cid)
    return payload


def _threat_model_payload_for_store(
    parsed: ParsedOutput,
    conversation: DispatchedConversation,
    response: str,
) -> dict | None:
    source = parsed.threat_models[0] if parsed.threat_models else None
    if not isinstance(source, dict):
        for submission in parsed.structured:
            threat_model = submission.get("threat_model") if isinstance(submission, dict) else None
            if isinstance(threat_model, dict):
                source = threat_model
                break
    if not isinstance(source, dict):
        return None
    payload = dict(source)
    payload["subject"] = conversation.subject
    payload.setdefault("status", "active")
    payload.setdefault("created_by", conversation.cid)
    payload.setdefault("assets", [])
    payload.setdefault("ingress_points", [])
    payload.setdefault("trust_boundaries", [])
    payload.setdefault("threats", [])
    payload.setdefault("hunt_prompts", [])
    if response and not payload.get("summary"):
        payload["summary"] = response[:1000]
    return payload


def _finding_code_paths(
    finding: dict,
    parsed: ParsedOutput,
    conversation: DispatchedConversation,
) -> list[str]:
    paths: list[str] = []
    for key in ("code_paths", "source_anchors", "refs"):
        paths.extend(_reference_list(finding.get(key)))
    for item in finding.get("evidence") or []:
        if isinstance(item, str) and _looks_like_source_reference(item):
            paths.append(item.strip())
        elif isinstance(item, dict):
            ref = _reference_list(item)
            paths.extend(ref)
    if not paths:
        paths.extend(parsed.coverage)
    if not paths and conversation.unit:
        unit = conversation.unit
        path = str(unit.get("path") or unit.get("name") or "")
        if path:
            line_start = unit.get("line_start")
            paths.append(f"{path}:{line_start}" if line_start else path)
    return sorted(set(paths))


_FINDING_TEXT_FIELDS = {
    "title", "description", "impact", "likelihood", "severity",
    "privileges_required", "attacker_position", "user_interaction", "status",
    "quality_tier", "production_viability", "repro_status", "patch_status",
    "affected_component", "component", "affected_product", "confidence",
    "verification_status", "mitigation", "remediation", "poc", "poc_status",
    "cwe", "cvss_vector", "discovery", "credit", "reasoning",
    "critic_reasoning", "vuln_class", "source_unit_id", "investigation_id",
    "priority", "inferred_exposure", "availability_tier", "duplicate_of",
    "dedup_key", "canonical_finding_id", "created_by",
}


_FINDING_STRING_LIST_FIELDS = {
    "code_paths",
    "source_anchors",
    "artifact_refs",
    "limitations",
    "repro_hints",
    "reproduction_steps",
    "poc_refs",
    "affected_versions",
    "references",
    "data_touched",
    "constituent_findings",
}


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _reference_list(value: object) -> list[str]:
    """Normalize string or mapping source references without stringifying maps."""
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        path = str(value.get("path") or value.get("file") or value.get("ref") or "").strip()
        anchor = str(value.get("anchor") or value.get("location") or "").strip()
        if path and anchor and anchor != path:
            if anchor.startswith((":", "#", "0x")):
                return [f"{path}{anchor if anchor.startswith(':') else ':' + anchor.lstrip('#')}" ]
            return [f"{path}:{anchor}"]
        return [path] if path else []
    if not isinstance(value, (list, tuple, set)):
        return []
    refs: list[str] = []
    for item in value:
        refs.extend(_reference_list(item))
    return refs


def _looks_like_source_reference(value: object) -> bool:
    text = str(value or "").strip()
    if not text or text.startswith(("art_", "obj_", "artifact:", "http://", "https://")):
        return False
    if re.search(r":(?:\d+(?:-\d+)?|0x[0-9a-f]+)$", text, re.IGNORECASE):
        return True
    if "/" in text or "\\" in text:
        return True
    return bool(re.match(r"^[^\s]+\.[A-Za-z0-9_+-]{1,12}$", text))


def _finding_envelope_defaults(parsed: ParsedOutput, finding: dict) -> dict:
    finding_id = str(finding.get("id") or finding.get("finding_id") or "").strip()
    title = str(finding.get("title") or "").strip()
    fallback: dict = {}
    for submission in parsed.structured:
        if not isinstance(submission, dict):
            continue
        if not fallback:
            fallback = submission
        for candidate in submission.get("findings") or []:
            if not isinstance(candidate, dict):
                continue
            candidate_id = str(candidate.get("id") or candidate.get("finding_id") or "").strip()
            candidate_title = str(candidate.get("title") or "").strip()
            if (finding_id and candidate_id == finding_id) or (title and candidate_title == title):
                return submission
    return fallback


def _normalize_finding_payload_shape(payload: dict) -> dict:
    normalized = dict(payload)
    if not normalized.get("affected_component") and isinstance(normalized.get("component"), str):
        normalized["affected_component"] = normalized["component"].strip()
    if not normalized.get("affected_versions") and normalized.get("affected"):
        normalized["affected_versions"] = _string_list(normalized.get("affected"))
    if not normalized.get("remediation"):
        followup = normalized.get("recommended_followup") or normalized.get("recommended_follow_up")
        if isinstance(followup, str):
            normalized["remediation"] = followup
        elif isinstance(followup, list):
            normalized["remediation"] = " ".join(str(item) for item in followup if str(item).strip())
    for key in _FINDING_TEXT_FIELDS:
        value = normalized.get(key)
        if value is None or isinstance(value, str):
            continue
        if isinstance(value, list):
            normalized[key] = " ".join(str(item).strip() for item in value if str(item).strip())
        elif isinstance(value, dict):
            normalized[key] = json.dumps(value, sort_keys=True)
        else:
            normalized[key] = str(value)
    for key in _FINDING_STRING_LIST_FIELDS:
        if key in normalized:
            normalized[key] = (
                _reference_list(normalized.get(key))
                if key in {"code_paths", "source_anchors", "refs"}
                else _string_list(normalized.get(key))
            )

    refs = set(normalized.get("code_paths") or [])
    refs.update(normalized.get("source_anchors") or [])
    title = str(normalized.get("title") or "agent finding")
    evidence: list[dict] = []
    raw_evidence = normalized.get("evidence")
    if isinstance(raw_evidence, (str, dict)):
        raw_evidence = [raw_evidence]
    for item in raw_evidence or []:
        if isinstance(item, dict):
            evidence.append(dict(item))
        elif isinstance(item, str) and item.strip():
            value = item.strip()
            if value in refs or _looks_like_source_reference(value):
                evidence.append({"kind": "source_anchor", "ref": value, "claim": title})
            else:
                evidence.append({"kind": "agent_observation", "claim": value})
    if not evidence:
        for ref in normalized.get("source_anchors") or normalized.get("code_paths") or []:
            evidence.append({"kind": "source_anchor", "ref": ref, "claim": title})
        for artifact_ref in normalized.get("artifact_refs") or []:
            evidence.append({"kind": "artifact_ref", "artifact_ref": artifact_ref, "claim": title})
    normalized["evidence"] = evidence

    for key, summary_key in (("history", "summary"), ("related_locations", "ref")):
        raw_items = normalized.get(key)
        if isinstance(raw_items, (str, dict)):
            raw_items = [raw_items]
        if raw_items is not None:
            normalized[key] = [
                dict(item) if isinstance(item, dict) else {summary_key: str(item)}
                for item in raw_items
                if isinstance(item, dict) or str(item).strip()
            ]
    return normalized


def _pending_action_evidence_refs(parsed: ParsedOutput) -> list[str]:
    refs: list[str] = list(parsed.coverage)
    holders = [*parsed.structured, *parsed.findings]
    for holder in holders:
        if not isinstance(holder, dict):
            continue
        for key in ("source_anchors", "artifact_refs", "code_paths"):
            refs.extend(_string_list(holder.get(key)))
        raw_evidence = holder.get("evidence")
        if isinstance(raw_evidence, (str, dict)):
            raw_evidence = [raw_evidence]
        for item in raw_evidence or []:
            if isinstance(item, str) and item.strip():
                refs.append(item.strip())
            elif isinstance(item, dict):
                for key in ("ref", "file", "artifact_ref"):
                    value = item.get(key)
                    if value:
                        refs.append(str(value).strip())
                        break
    return list(dict.fromkeys(ref for ref in refs if ref))


def _determination_fields(parsed: ParsedOutput) -> dict:
    """Pull the structured per-unit determination the units table already stores.

    The `units` table has dedicated columns (sensitivity, data_touched, flows_in,
    flows_out) that the store and /submit endpoint accept but the loop never
    filled. An agent supplies them in its structured `refall-submit` block; this
    forwards whatever it provided so the central determination row is complete
    enough to reconstruct architecture and function flows later.
    """
    fields: dict = {}
    for block in getattr(parsed, "structured", None) or []:
        if not isinstance(block, dict):
            continue
        for key in ("sensitivity", "data_touched", "flows_in", "flows_out"):
            value = block.get(key)
            if value not in (None, "", [], {}) and key not in fields:
                fields[key] = value
    return fields


def _coverage_evidence(parsed: ParsedOutput, unit: dict) -> list[dict]:
    evidence: list[dict] = []
    for finding in parsed.findings:
        for item in finding.get("evidence") or []:
            if isinstance(item, dict) and item.get("file"):
                evidence.append(item)
            elif isinstance(item, str) and item.strip():
                file_part, _, line_part = item.partition(":")
                row = {"file": file_part or unit.get("path") or "unknown"}
                if line_part.isdigit():
                    row["line_start"] = int(line_part)
                evidence.append(row)
    for path in parsed.coverage:
        evidence.append({"file": path})
    if not evidence:
        evidence.append({
            "file": unit.get("path") or unit.get("name") or "unknown",
            "line_start": unit.get("line_start"),
            "line_end": unit.get("line_end"),
        })
    return evidence


_KNOWN_CAPABILITY_CLASSES = (
    "lan_network_probe",
    "external_network",
    "dynamic_target_probe",
    "write_subject",
    "run_local_command",
    "docker_control",
    "codebadger_docker",
    "destructive_action",
    "secret_use",
)


def _capability_class_from_failure(message: str) -> str:
    text = str(message or "")
    explicit = re.search(r"\bcapability[_ -]?class\s*[:=]\s*([A-Za-z0-9_-]+)", text)
    if explicit:
        return explicit.group(1)
    lowered = text.lower()
    for capability_class in _KNOWN_CAPABILITY_CLASSES:
        if capability_class in lowered:
            return capability_class
    if "codebadger" in lowered:
        return "codebadger_docker"
    if "docker" in lowered or "compose" in lowered:
        return "docker_control"
    if any(token in lowered for token in ("http", "curl", "socket", "tcp", "udp", "port")):
        return "lan_network_probe"
    if any(token in lowered for token in ("write", "file", "path")):
        return "write_subject"
    return "capability"


def _capability_scope_from_failure(message: str) -> dict:
    text = str(message or "")
    scope: dict[str, list[object]] = {}
    hosts = sorted(set(re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text)))
    if hosts:
        scope["hosts"] = hosts
    ports = sorted({
        int(match)
        for match in re.findall(r"(?::|\bport\s+)(\d{1,5})\b", text, flags=re.IGNORECASE)
        if 0 < int(match) <= 65535
    })
    if ports:
        scope["ports"] = ports
    paths = sorted({
        match
        for match in re.findall(r"(?<![A-Za-z0-9_])/(?:[^\s;,'\"]+)", text)
        if match != "/"
    })
    if paths:
        scope["paths"] = paths
    return scope


def _config_from_env() -> StandingLoopConfig:
    return StandingLoopConfig(
        max_cycles=int(os.environ.get("REFALL_LOOP_MAX_CYCLES", "0")),
        max_parallel=int(os.environ.get("REFALL_LOOP_MAX_PARALLEL", "4")),
        poll_interval_s=float(os.environ.get("REFALL_LOOP_POLL_INTERVAL_S", "5")),
        report_interval_cycles=int(os.environ.get("REFALL_LOOP_REPORT_INTERVAL_CYCLES", "10")),
        stall_cycles=int(os.environ.get("REFALL_LOOP_STALL_CYCLES", "36")),
        report_agent_intel_threshold=int(
            os.environ.get("REFALL_LOOP_REPORT_AGENT_INTEL_THRESHOLD", "30")
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="refall-standing-loop")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--workbench", default=None)
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--max-parallel", type=int, default=None)
    parser.add_argument("--poll-interval-s", type=float, default=None)
    args = parser.parse_args(argv)

    cfg = _config_from_env()
    if args.max_cycles is not None:
        cfg.max_cycles = args.max_cycles
    if args.max_parallel is not None:
        cfg.max_parallel = args.max_parallel
    if args.poll_interval_s is not None:
        cfg.poll_interval_s = args.poll_interval_s

    try:
        result = RefallStandingLoop(args.subject, workbench=args.workbench, config=cfg).run()
    finally:
        # A continuous loop owns its supervisor cron; retire it on exit so a
        # stopped subject does not leave a supervisor probing forever. Bounded
        # `update` passes never installed one.
        if cfg.max_cycles == 0:
            _retire_supervisor(args.subject)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _retire_supervisor(subject: str) -> None:
    try:
        from . import supervisor as supervisor_mod

        supervisor_mod.uninstall_cron(subject=subject)
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
