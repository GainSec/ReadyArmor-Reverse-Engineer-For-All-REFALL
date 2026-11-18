import json
import base64
from pathlib import Path
from types import SimpleNamespace

from ref_all_executor.standing_loop import (
    AgentCanvasDispatcher,
    AgentTask,
    DispatchedConversation,
    ParsedOutput,
    PollResult,
    RefallStandingLoop,
    StandingLoopConfig,
    _finding_code_paths,
    _pending_action_worker_claimable,
    parse_agent_output,
)
from ref_all_executor.work_modules import WorkModule


class FakeCoverage:
    def __init__(self, units=None, lines_total=10):
        self.units = list(units or [])
        self.lines_total = lines_total
        self.calls = []
        self.submits = []
        self.findings = []
        self.enumerated = []
        self.source_inventories = []
        self.context = {"subject": "alpha", "info_md": "# Alpha context\nPrioritize auth."}
        self.scope_overlay = None
        self.source_inventory = None
        self.threat_model = None
        self.threat_models = []
        self.reject_findings = False

    def get_context(self, subject):
        self.calls.append(("get_context", subject))
        return self.context

    def coverage(self, subject):
        self.calls.append(("coverage", subject))
        return {
            "subject": subject,
            "lines_total": self.lines_total,
            "resolved_pct": 0.0,
            "symbols_total": len(self.units),
        }

    def gate(self, subject):
        self.calls.append(("gate", subject))
        return {"subject": subject, "locked": True, "resolved_pct": 0.0, "phase": "discovery"}

    def claim_next(self, subject, agent):
        self.calls.append(("claim_next", subject, agent))
        if not self.units:
            return None
        return self.units.pop(0)

    def submit(self, unit_id, agent, summary, evidence, **kw):
        self.submits.append((unit_id, agent, summary, evidence, kw))
        return {"id": unit_id, "state": "characterized"}

    def add_finding(self, subject, finding):
        if self.reject_findings:
            raise RuntimeError("finding promotion refused: missing evidence")
        created = {"id": finding.get("id") or f"find-{len(self.findings) + 1}", "subject": subject, **finding}
        self.findings.append((subject, created))
        return created

    def enumerate(self, subject, files):
        self.enumerated.append((subject, files))
        self.lines_total = sum(file["total_lines"] for file in files)
        return {"subject": subject, "units": len(files)}

    def put_source_inventory(self, subject, inventory):
        self.source_inventories.append((subject, inventory))
        self.source_inventory = inventory
        return inventory

    def get_source_inventory(self, subject):
        return self.source_inventory

    def get_scope_overlay(self, subject):
        return self.scope_overlay

    def put_threat_model(self, subject, threat_model):
        created = {
            "subject": subject,
            "threat_model_id": threat_model.get("threat_model_id") or f"tm-{len(self.threat_models) + 1}",
            **threat_model,
        }
        self.threat_model = created
        self.threat_models.append((subject, created))
        return created

    def get_threat_model(self, subject):
        return self.threat_model


class FakeArcticBase:
    def __init__(self, subject_path: Path):
        self.subject_path = subject_path
        self.extra_custom_fields = {}
        self.ledger = []
        self.events = []
        self.pending_actions = []
        self.resolved_pending = []
        self.transitions = []
        self.runtime_artifacts = []
        self.capability_requests = []
        self.runtime_manifests = []
        self.runtime_events = []
        self.runtime_checkpoints = []
        self.resume_preflights = []

    def get_workbench(self, slug):
        return {
            "slug": slug,
            "local_path": str(self.subject_path),
            "custom_fields": {
                "refall_subject": slug,
                "refall_subject_path": str(self.subject_path),
                "refall_source_path": str(self.subject_path / "PRJ"),
                **self.extra_custom_fields,
            },
        }

    def append_ledger(self, slug, entry):
        self.ledger.append((slug, entry))
        return {"id": f"led-{len(self.ledger)}", **entry}

    def ledger_stats(self, slug):
        by_kind = {}
        for _, entry in self.ledger:
            by_kind[entry["kind"]] = by_kind.get(entry["kind"], 0) + 1
        return {"total": len(self.ledger), "by_kind": by_kind}

    def push_ops_event(self, event):
        self.events.append(event)
        return {"ok": True}

    def create_pending_action(self, slug, action):
        created = {"id": f"pa-{len(self.pending_actions) + 1}", "status": "open", **action}
        self.pending_actions.append(created)
        self.ledger.append((slug, {**action, "kind": "pending-action", "pending_kind": action.get("kind")}))
        return created

    def list_pending_actions(self, slug, **filters):
        return [action for action in self.pending_actions if action.get("status") in {"open", "claimed"}]

    def claim_pending_action(self, slug, action_id, claimed_by="refall-manager"):
        for action in self.pending_actions:
            if action["id"] == action_id:
                action["status"] = "claimed"
                action["claimed_by"] = claimed_by
                return action
        raise RuntimeError("missing pending action")

    def resolve_pending_action(self, slug, action_id, receipt, receipt_type="agent_resolution", resolved_by="refall-standing-loop"):
        for action in self.pending_actions:
            if action["id"] == action_id:
                action["status"] = "done"
                action["resolution_receipt"] = receipt
                self.resolved_pending.append((slug, action_id, receipt, receipt_type, resolved_by))
                return action
        raise RuntimeError("missing pending action")

    def transition_finding(self, slug, finding_id, transition):
        self.transitions.append((slug, finding_id, transition))
        return {
            "id": f"tr-{len(self.transitions)}",
            "status": "accepted",
            "accepted": True,
            "finding_id": finding_id,
        }

    def create_runtime_artifact(self, slug, artifact):
        created = {"id": f"art-{len(self.runtime_artifacts) + 1}", **artifact}
        self.runtime_artifacts.append((slug, created))
        return created

    def request_capability(self, slug, request):
        created = {"id": f"capreq-{len(self.capability_requests) + 1}", "status": "open", **request}
        self.capability_requests.append((slug, created))
        return created

    def put_runtime_manifest(self, slug, manifest):
        created = {
            "manifest_id": manifest.get("manifest_id") or f"manifest-{len(self.runtime_manifests) + 1}",
            "workbench_object_id": manifest.get("workbench_object_id") or "obj_manifest",
            **manifest,
        }
        self.runtime_manifests.append((slug, created))
        return created

    def append_runtime_event(self, slug, event):
        created = {"id": f"rte-{len(self.runtime_events) + 1}", **event}
        self.runtime_events.append((slug, created))
        return created

    def put_runtime_checkpoint(self, slug, checkpoint):
        created = {"id": f"ckpt-{len(self.runtime_checkpoints) + 1}", **checkpoint}
        self.runtime_checkpoints.append((slug, created))
        return created

    def list_runtime_checkpoints(self, slug):
        return [checkpoint for item_slug, checkpoint in self.runtime_checkpoints if item_slug == slug]

    def resume_preflight(self, slug, input_hashes):
        self.resume_preflights.append((slug, input_hashes))
        return {"accepted": True, "status": "accepted"}

    def get_runtime_manifest(self, slug):
        for item_slug, manifest in reversed(self.runtime_manifests):
            if item_slug == slug:
                return manifest
        return {}


class FakeDispatcher:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.started = []
        self.deleted = []

    def start(self, task):
        self.started.append(task)
        return DispatchedConversation(
            cid=f"cid-{len(self.started)}",
            subject=task.subject,
            lane=task.lane,
            task_class=task.task_class,
            unit=task.unit,
            objective=task.objective,
            attempt=task.attempt,
            # Propagate work-module provenance, exactly as the real dispatcher does.
            module_id=task.module_id,
            module_target=task.module_target,
            submits_coverage=task.submits_coverage,
        )

    def poll(self, active):
        if not self.statuses:
            return PollResult(cid=active.cid, status="running")
        status, response = self.statuses.pop(0)
        return PollResult(cid=active.cid, status=status, response=response)

    def delete(self, cid):
        self.deleted.append(cid)


class FakeOHClient:
    def __init__(self):
        self.started = []

    def start_conversation(self, workspace, agent_settings, text, max_iterations=30):
        self.started.append({
            "workspace": workspace,
            "agent_settings": agent_settings,
            "text": text,
            "max_iterations": max_iterations,
        })
        return "cid-ssh"


def test_parse_agent_output_extracts_rich_ledger_items() -> None:
    parsed = parse_agent_output(
        """
```finding
{"title":"SQL injection","severity":"HIGH","impact":"database read","evidence":["app.py:10"],"reproduction_steps":"curl /login","remediation":"parameterize"}
```
[FACT] Login route | POST /login exists
[LEAD:medium] Admin export | review authorization | curl /admin/export
[ASK] semgrep | need source query
[COVERAGE] app.py, auth.py
[DONE] found auth issue
"""
    )

    assert parsed.done == "found auth issue"
    assert parsed.findings[0]["title"] == "SQL injection"
    assert parsed.facts[0]["title"] == "Login route"
    assert parsed.leads[0]["title"] == "Admin export"
    assert parsed.asks[0]["title"] == "semgrep"
    assert parsed.coverage == ["app.py", "auth.py"]


def test_standing_loop_dispatches_polls_ledgers_submits_and_writes_state(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[{
        "id": "unit-1",
        "subject": "alpha",
        "type": "symbol",
        "path": "app.py",
        "line_start": 10,
        "line_end": 20,
        "name": "login",
    }])
    ab = FakeArcticBase(subject_path)
    dispatcher = FakeDispatcher([(
        "finished",
        "[FACT] Login route | POST /login\n[LEAD:high] Login injection | validate parameters\n[DONE] characterized login",
    )])
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=2, max_parallel=1, poll_interval_s=0),
    )

    result = loop.run()

    assert result["status"] == "idle"
    assert dispatcher.started
    assert "# Alpha context" in dispatcher.started[0].objective
    assert coverage.submits[0][0] == "unit-1"
    assert any(entry["kind"] == "fact" for _, entry in ab.ledger)
    assert any(entry["kind"] == "lead" for _, entry in ab.ledger)
    state = json.loads((subject_path / ".refall" / "loop_state.json").read_text())
    assert state["status"] == "idle"
    events = (subject_path / "refallsubloop/logs/events/events.jsonl").read_text()
    assert "agent_start" in events
    assert "agent_complete" in events
    blackboard = json.loads((subject_path / ".refall" / "blackboard.json").read_text())
    assert "characterized login" in blackboard[-1]


def test_standing_loop_resumes_active_conversation_on_update(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / ".refall").mkdir(parents=True)
    (subject_path / ".refall" / "loop_state.json").write_text(
        json.dumps({
            "status": "running",
            "iteration": 4,
            "active": [{
                "cid": "cid-active",
                "subject": "alpha",
                "lane": "A",
                "task_class": "characterize",
                "unit": {"id": "unit-active", "path": "svc.py", "line_start": 1, "line_end": 3},
                "objective": "existing objective",
            }],
        }),
        encoding="utf-8",
    )
    coverage = FakeCoverage(units=[])
    ab = FakeArcticBase(subject_path)
    dispatcher = FakeDispatcher([("finished", "[DONE] resumed unit")])
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    result = loop.run()

    assert result["completed"] == 1
    assert dispatcher.started == []
    assert coverage.submits[0][0] == "unit-active"


def test_standing_loop_resume_preflight_uses_latest_source_inventory(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    (subject_path / "PRJ" / "app.py").write_text("one\n", encoding="utf-8")
    state_path = subject_path / ".refall" / "loop_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "run_id": "run-resume",
        "status": "running",
        "iteration": 4,
        "active": [{
            "cid": "cid-active",
            "subject": "alpha",
            "lane": "A",
            "task_class": "characterize",
            "unit": {"id": "unit-active", "path": "app.py", "line_start": 1, "line_end": 1},
            "objective": "existing objective",
        }],
    }), encoding="utf-8")
    coverage = FakeCoverage(units=[])
    coverage.source_inventory = {
        "inventory_id": "inv-current",
        "files": [{"path": "app.py", "sha256": "a" * 64, "total_lines": 1, "kind": "python"}],
    }
    ab = FakeArcticBase(subject_path)
    ab.runtime_checkpoints.append((
        "alpha",
        {
            "id": "ckpt-old",
            "checkpoint_key": "inventory:latest",
            "input_hashes": {"source:app.py": "a" * 64},
        },
    ))
    dispatcher = FakeDispatcher([("finished", "[DONE] resumed unit")])
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    loop.run()

    assert ab.resume_preflights
    assert ab.resume_preflights[0][1]["source:app.py"] == "a" * 64


def test_standing_loop_auto_enumerates_source_when_coverage_empty(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    prj = subject_path / "PRJ"
    prj.mkdir(parents=True)
    (prj / "app.py").write_text("one\ntwo\n", encoding="utf-8")
    coverage = FakeCoverage(units=[], lines_total=0)
    ab = FakeArcticBase(subject_path)
    dispatcher = FakeDispatcher([])
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    result = loop.run()

    assert result["enumerated"] == 1
    assert coverage.source_inventories
    assert coverage.source_inventories[0][1]["files"][0]["path"] == "app.py"
    assert coverage.enumerated == [("alpha", [{"path": "app.py", "total_lines": 2, "src": "source-inventory"}])]
    manifest = ab.runtime_manifests[-1][1]
    assert manifest["source_inventory_id"] == coverage.source_inventories[0][1]["inventory_id"]
    assert manifest["source_hashes"]["app.py"] == coverage.source_inventories[0][1]["files"][0]["sha256"]


def test_standing_loop_does_not_mark_binary_only_subject_as_line_covered(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "binary"
    prj = subject_path / "PRJ"
    prj.mkdir(parents=True)
    (prj / "firmware.bin").write_bytes(b"\x00firmware" * 32)
    coverage = FakeCoverage(units=[], lines_total=0)
    ab = FakeArcticBase(subject_path)
    loop = RefallStandingLoop(
        "binary", coverage=coverage, arcticbase=ab, dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    result = loop.run()

    assert result["enumerated"] == 0
    assert coverage.enumerated == []
    assert any(action["kind"] == "binary_analysis_plan_required" for action in ab.pending_actions)


def test_standing_loop_manifest_uses_existing_source_inventory(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[], lines_total=2)
    coverage.source_inventory = {
        "subject": "alpha",
        "inventory_id": "inv-existing",
        "root": str(subject_path / "PRJ"),
        "files": [{"path": "app.py", "sha256": "b" * 64, "total_lines": 2, "kind": "python"}],
        "skipped": [],
    }
    ab = FakeArcticBase(subject_path)
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    loop.run()

    assert ab.runtime_manifests[0][1]["source_inventory_id"] == "inv-existing"
    assert ab.runtime_manifests[-1][1]["source_hashes"]["app.py"] == "b" * 64


def test_dispatch_lane_pattern_can_mix_codex_and_claude_across_task_types(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    ab = FakeArcticBase(subject_path)
    ab.extra_custom_fields["refall_characterize_lane_pattern"] = "B,B,B,A"
    loop = RefallStandingLoop(
        "alpha",
        coverage=FakeCoverage(units=[]),
        arcticbase=ab,
        dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=1, max_parallel=4, poll_interval_s=0),
    )

    lanes = [
        loop._task_for_characterize({"id": "unit-1", "path": "f1.py"}).lane,
        loop._task_for_unit_module(WorkModule(id="recon", task_class="recon"), {"id": "unit-2", "path": "f2.py"}).lane,
        loop._task_for_pending_action({"id": "pa-1", "title": "review"}).lane,
        loop._task_for_subject_module(WorkModule(id="identify", task_class="identify")).lane,
        loop._task_for_characterize({"id": "unit-3", "path": "f3.py"}).lane,
    ]

    assert lanes == ["B", "B", "B", "A", "B"]


def test_dispatch_lane_pattern_fills_active_lane_deficit(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    ab = FakeArcticBase(subject_path)
    ab.extra_custom_fields["refall_lane_pattern"] = "B,B,B,A"
    loop = RefallStandingLoop(
        "alpha",
        coverage=FakeCoverage(units=[]),
        arcticbase=ab,
        dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=1, max_parallel=4, poll_interval_s=0),
    )
    active = [
        DispatchedConversation(
            cid=f"cid-{index}",
            subject="alpha",
            lane="B",
            task_class="review",
            unit=None,
            objective="active",
        )
        for index in range(3)
    ]

    task = loop._task_for_pending_action({"id": "pa-1", "title": "review"}, active=active)

    assert task.lane == "A"


def test_standing_loop_includes_scope_overlay_in_objective(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[{
        "id": "unit-1",
        "subject": "alpha",
        "type": "symbol",
        "path": "app.py",
        "line_start": 1,
        "line_end": 2,
        "name": "login",
    }])
    coverage.scope_overlay = {
        "local_roots": [str(subject_path / "PRJ")],
        "lan_targets": [{"host": "192.0.2.10", "ports": [80, 81]}],
        "external_targets": [],
        "operator_notes": "No external testing.",
    }
    dispatcher = FakeDispatcher([])
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=FakeArcticBase(subject_path),
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    loop.run()

    objective = dispatcher.started[0].objective
    assert "## Scope Overlay" in objective
    assert "192.0.2.10" in objective
    assert "No external testing." in objective


def test_agent_canvas_dispatcher_includes_remote_ssh_resources_in_prompt() -> None:
    oh = FakeOHClient()
    dispatcher = AgentCanvasDispatcher(oh=oh)

    dispatcher.start(
        AgentTask(
            subject="alpha",
            task_class="characterize",
            lane="A",
            unit={"id": "unit-ssh"},
            objective="## Task\nReview the assigned unit.",
            max_iterations=1,
        )
    )

    objective = oh.started[0]["text"]
    assert "## Remote SSH Resources" in objective
    assert "ssh sectortw <command>" in objective
    assert "ssh sectortl <command>" in objective
    assert "## Task\nReview the assigned unit." in objective


def test_agent_canvas_dispatcher_uses_writable_subject_scratch_workspace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("REFALL_AGENT_WORKSPACE_HOST_ROOT", str(tmp_path / "refallsub"))
    monkeypatch.setenv("REFALL_AGENT_WORKSPACE_CONTAINER_ROOT", "/projects/refallsub")
    oh = FakeOHClient()
    dispatcher = AgentCanvasDispatcher(oh=oh)

    dispatcher.start(
        AgentTask(
            subject="alpha",
            task_class="characterize",
            lane="A",
            unit={"id": "unit-ssh", "path": "firmware.bin"},
            objective="## Task\nReview the assigned unit.",
            max_iterations=1,
        )
    )

    assert oh.started[0]["workspace"] == {
        "kind": "LocalWorkspace",
        "working_dir": "/projects/refallsub/alpha/A-characterize-unit-ssh",
    }
    assert (tmp_path / "refallsub" / "alpha" / "A-characterize-unit-ssh").is_dir()
    objective = oh.started[0]["text"]
    assert "Writable agent workspace: `/projects/refallsub/alpha/A-characterize-unit-ssh`" in objective
    assert "Read-only subject source root: `/projects/alpha`" in objective
    assert "Do not write to `/projects/alpha`" in objective


def test_standing_loop_dispatches_requested_threat_model_cycle(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[{
        "id": "unit-1",
        "subject": "alpha",
        "type": "symbol",
        "path": "app.py",
        "line_start": 1,
        "line_end": 2,
        "name": "login",
    }])
    coverage.source_inventory = {
        "subject": "alpha",
        "inventory_id": "inv-alpha",
        "root": str(subject_path / "PRJ"),
        "files": [{"path": "app.py", "sha256": "a" * 64, "total_lines": 2, "kind": "python"}],
        "skipped": [],
    }
    coverage.scope_overlay = {
        "overlay_id": "scope-alpha",
        "local_roots": [str(subject_path / "PRJ")],
        "lan_targets": [{"host": "192.0.2.10", "ports": [80]}],
        "external_targets": [],
        "threat_model_requested": True,
    }
    dispatcher = FakeDispatcher([(
        "finished",
        """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "threat_model_submit",
  "subject": "alpha",
  "task_id": "threat_model",
  "status": "done",
  "summary": "Threat model drafted.",
  "produced_by": "cid_1",
  "created_at": "2026-07-24T00:00:00Z",
  "threat_model": {
    "assets": [{"id":"asset:web","name":"web app"}],
    "ingress_points": [{"id":"ingress:http","description":"HTTP service"}],
    "trust_boundaries": [{"id":"tb:user-service","description":"user input to service"}],
    "threats": [{"id":"thr:cmd","title":"Command injection","vuln_class":"command-injection"}],
    "hunt_prompts": ["Trace user input to subprocess calls."],
    "status": "active"
  }
}
```
""",
    )])
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=FakeArcticBase(subject_path),
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    result = loop.run()

    assert result["completed"] == 1
    assert dispatcher.started[0].task_class == "threat_model"
    assert "## Threat Model Inputs" in dispatcher.started[0].objective
    assert "inv-alpha" in dispatcher.started[0].objective
    assert coverage.threat_models[0][1]["threats"][0]["id"] == "thr:cmd"
    assert coverage.submits == []
    assert any(event["type"] == "threat_model_updated" for _, event in loop.arcticbase.runtime_events)
    assert loop.arcticbase.runtime_manifests[-1][1]["threat_model_id"] == coverage.threat_models[0][1]["threat_model_id"]


def test_standing_loop_escalates_promotion_gate_refusals(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[{
        "id": "unit-1",
        "subject": "alpha",
        "type": "symbol",
        "path": "app.py",
        "line_start": 1,
        "line_end": 2,
        "name": "login",
    }])
    coverage.reject_findings = True
    dispatcher = FakeDispatcher([(
        "finished",
        """
```finding
{"title":"Command injection","severity":"HIGH","code_paths":["app.py:1"],"evidence":[{"kind":"source_anchor","ref":"app.py:1"}],"confidence":"medium"}
```
[DONE] found candidate
""",
    )])
    ab = FakeArcticBase(subject_path)
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    loop.run()

    assert any(entry.get("action") == "finding.promotion.refused" for _, entry in ab.ledger)
    assert any(action["kind"] == "finding_candidate_review" for action in ab.pending_actions)


def test_standing_loop_writes_run_manifest_at_start_and_idle(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[], lines_total=10)
    ab = FakeArcticBase(subject_path)
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    result = loop.run()

    assert result["status"] == "idle"
    assert len(ab.runtime_manifests) >= 2
    start_manifest = ab.runtime_manifests[0][1]
    idle_manifest = ab.runtime_manifests[-1][1]
    assert start_manifest["run_id"] == idle_manifest["run_id"]
    assert start_manifest["provider_roles"]["manager"] == "codex"
    assert idle_manifest["stage_status"]["loop"] == "idle"
    state = json.loads((subject_path / ".refall" / "loop_state.json").read_text())
    assert state["run_id"] == idle_manifest["run_id"]
    assert ab.runtime_events
    assert all(event["run_id"] == idle_manifest["run_id"] for _, event in ab.runtime_events)


def test_standing_loop_writes_runtime_checkpoints(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[], lines_total=10)
    ab = FakeArcticBase(subject_path)
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    loop.run()

    keys = [checkpoint["checkpoint_key"] for _, checkpoint in ab.runtime_checkpoints]
    assert "loop:start" in keys
    assert "loop:idle" in keys
    assert all(checkpoint["run_id"] == loop.run_id for _, checkpoint in ab.runtime_checkpoints)
    idle_checkpoint = next(checkpoint for _, checkpoint in ab.runtime_checkpoints if checkpoint["checkpoint_key"] == "loop:idle")
    idle_manifest = ab.runtime_manifests[-1][1]
    assert idle_checkpoint["id"] in idle_manifest["checkpoint_ids"]


def test_standing_loop_requires_structured_submit_when_configured(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("REFALL_REQUIRE_STRUCTURED_SUBMIT", "true")
    monkeypatch.setenv("REFALL_RETRY_MAX_ATTEMPTS", "1")
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[{
        "id": "unit-1",
        "subject": "alpha",
        "type": "symbol",
        "path": "app.py",
        "line_start": 1,
        "line_end": 2,
        "name": "login",
    }])
    ab = FakeArcticBase(subject_path)
    dispatcher = FakeDispatcher([("finished", "[DONE] legacy completion")])
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    loop.run()

    assert coverage.submits == []
    assert any(entry.get("kind") == "pending-action" for _, entry in ab.ledger)
    assert ab.runtime_artifacts[0][1]["kind"] == "worker-submit-invalid"
    assert "legacy completion" in ab.runtime_artifacts[0][1]["content"]


def test_failed_submit_artifact_preserves_binary_trajectory_as_base64(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    subject_path.mkdir(parents=True)
    ab = FakeArcticBase(subject_path)
    loop = RefallStandingLoop(
        "alpha",
        coverage=FakeCoverage(),
        arcticbase=ab,
        dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )
    conversation = DispatchedConversation(
        cid="cid-binary",
        subject="alpha",
        lane="B",
        task_class="source_review",
        unit={"id": "unit-1"},
        objective="review",
    )
    trajectory = b"PK\x03\x04\xff\x00provider diagnostic"

    refs = loop._save_failed_submit_artifact(
        conversation,
        PollResult(cid="cid-binary", status="error", trajectory=trajectory),
        SimpleNamespace(last_error="worker status error"),
    )

    assert refs
    artifact = ab.runtime_artifacts[0][1]
    assert artifact["mime"] == "application/json"
    payload = json.loads(artifact["content"])
    assert payload["status"] == "error"
    assert payload["last_error"] == "worker status error"
    assert base64.b64decode(payload["trajectory_base64"]) == trajectory


def test_completed_agent_artifact_preserves_binary_trajectory_as_base64(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    subject_path.mkdir(parents=True)
    ab = FakeArcticBase(subject_path)
    loop = RefallStandingLoop(
        "alpha",
        coverage=FakeCoverage(),
        arcticbase=ab,
        dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )
    conversation = DispatchedConversation(
        cid="cid-complete-binary",
        subject="alpha",
        lane="B",
        task_class="report",
        unit=None,
        objective="compile report",
    )
    trajectory = b"PK\x03\x04\xff\x00completed provider trajectory"

    refs = loop._save_trajectory_artifact(
        conversation,
        PollResult(cid=conversation.cid, status="finished", trajectory=trajectory),
    )

    assert refs
    artifact = ab.runtime_artifacts[0][1]
    assert artifact["mime"] == "application/json"
    payload = json.loads(artifact["content"])
    assert payload["schema"] == "refall.agent-trajectory.v1"
    assert payload["status"] == "finished"
    assert payload["trajectory_encoding"] == "base64"
    assert base64.b64decode(payload["trajectory_base64"]) == trajectory


def test_report_submission_identity_cannot_collide_with_analysis_task() -> None:
    from ref_all_executor.standing_loop import _structured_submission_keys

    parsed = ParsedOutput(structured=[{
        "subject": "alpha",
        "type": "task_result_submit",
        "task_id": "analysis-module",
    }])
    analysis = DispatchedConversation(
        cid="analysis-cid",
        subject="alpha",
        lane="B",
        task_class="identify",
        unit=None,
        objective="analyze",
    )
    report = DispatchedConversation(
        cid="report-cid",
        subject="alpha",
        lane="B",
        task_class="report",
        unit=None,
        objective="report",
    )

    assert _structured_submission_keys(parsed, report) != _structured_submission_keys(parsed, analysis)


def test_named_finding_is_normalized_to_canonical_title() -> None:
    from ref_all_executor.standing_loop import _finding_payload_for_store

    finding = {
        "id": "F-1",
        "name": "ActionBar response fields execute as JavaScript",
        "status": "PROVISIONALLY_VALID",
        "source_anchors": ["app.js:10"],
        "code_paths": ["app.js:10"],
        "impact": "Script execution",
    }
    parsed = ParsedOutput(findings=[finding])
    conversation = DispatchedConversation(
        cid="report-cid",
        subject="alpha",
        lane="B",
        task_class="report",
        unit=None,
        objective="report",
    )

    payload = _finding_payload_for_store(finding, parsed, conversation)

    assert payload is not None
    assert payload["title"] == finding["name"]


def test_standing_loop_retires_prior_cid_when_retrying_invalid_submit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("REFALL_REQUIRE_STRUCTURED_SUBMIT", "true")
    monkeypatch.setenv("REFALL_RETRY_MAX_ATTEMPTS", "2")
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[{
        "id": "unit-1",
        "subject": "alpha",
        "type": "symbol",
        "path": "app.py",
        "line_start": 1,
        "line_end": 2,
        "name": "login",
    }])
    ab = FakeArcticBase(subject_path)
    dispatcher = FakeDispatcher([
        ("finished", "[DONE] legacy completion"),
        (
            "finished",
            """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "task_result_submit",
  "subject": "alpha",
  "task_id": "task_1",
  "unit_id": "unit-1",
  "status": "done",
  "summary": "Reviewed login",
  "produced_by": "cid_2",
  "created_at": "2026-07-24T00:00:00Z",
  "evidence": [{"kind":"source_anchor","ref":"app.py:1","claim":"reviewed"}],
  "source_anchors": ["app.py:1"],
  "confidence": "medium",
  "limitations": []
}
```
""",
        ),
    ])
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=2, max_parallel=1, poll_interval_s=0),
    )

    loop.run()

    # cid-1 is retired by the retry path; cid-2 is reaped after it completes
    # successfully, so the agent server does not hold it for the life of the run.
    assert dispatcher.deleted == ["cid-1", "cid-2"]
    events = [
        json.loads(line)
        for line in (subject_path / "refallsubloop/logs/events/events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    retry_events = [event for event in events if event["type"] == "retry_scheduled"]
    retired_events = [
        event for event in events
        if event["type"] == "agent_complete" and event.get("status") == "retry_replaced"
    ]
    assert retry_events[0]["prior_cid"] == "cid-1"
    assert retired_events[0]["cid"] == "cid-1"
    assert retired_events[0]["replacement_cid"] == "cid-2"
    assert retired_events[0]["delete_status"] == "deleted"
    assert coverage.submits[0][0] == "unit-1"


def test_standing_loop_rejects_contract_invalid_structured_submit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("REFALL_REQUIRE_STRUCTURED_SUBMIT", "true")
    monkeypatch.setenv("REFALL_RETRY_MAX_ATTEMPTS", "1")
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[{
        "id": "unit-1",
        "subject": "alpha",
        "type": "symbol",
        "path": "app.py",
        "line_start": 1,
        "line_end": 2,
        "name": "login",
    }])
    ab = FakeArcticBase(subject_path)
    dispatcher = FakeDispatcher([(
        "finished",
        """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "task_result_submit",
  "subject": "alpha",
  "task_id": "task_1",
  "unit_id": "unit-1",
  "status": "done",
  "summary": "Reviewed login",
  "produced_by": "cid_1",
  "created_at": "2026-07-24T00:00:00Z",
  "evidence": [{"kind":"source_anchor","ref":"app.py:1","claim":"reviewed"}],
  "confidence": "medium",
  "limitations": []
}
```
""",
    )])
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    loop.run()

    assert coverage.submits == []
    assert ab.runtime_artifacts[0][1]["kind"] == "worker-submit-invalid"
    assert any(
        "source_anchors or artifact_refs" in entry.get("summary", "")
        for _, entry in ab.ledger
        if entry.get("action") == "worker.submit.failed"
    )
    assert any(
        "source_anchors or artifact_refs" in action["description"]
        for action in ab.pending_actions
    )


def test_standing_loop_retries_missing_structured_submit_before_operator_attention(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_REQUIRE_STRUCTURED_SUBMIT", "true")
    monkeypatch.setenv("REFALL_RETRY_MAX_ATTEMPTS", "2")
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[{
        "id": "unit-1",
        "subject": "alpha",
        "type": "symbol",
        "path": "app.py",
        "line_start": 1,
        "line_end": 2,
        "name": "login",
    }])
    ab = FakeArcticBase(subject_path)
    dispatcher = FakeDispatcher([
        ("finished", "[DONE] legacy completion"),
        ("finished", """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "task_result_submit",
  "subject": "alpha",
  "task_id": "task_1",
  "unit_id": "unit_1",
  "status": "done",
  "summary": "Structured repair completion",
  "produced_by": "cid_2",
  "created_at": "2026-07-24T00:00:00Z",
  "evidence": [{"kind":"source_anchor","ref":"app.py:1","claim":"reviewed"}],
  "source_anchors": ["app.py:1"],
  "confidence": "medium",
  "limitations": []
}
```
"""),
    ])
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=2, max_parallel=1, poll_interval_s=0),
    )

    loop.run()

    assert len(dispatcher.started) == 2
    assert dispatcher.started[1].attempt == 2
    assert "Retry Repair" in dispatcher.started[1].objective
    assert coverage.submits[0][2] == "Structured repair completion"
    assert not any(action["title"].startswith("Worker output needs manager review") for action in ab.pending_actions)
    assert ab.runtime_artifacts[0][1]["kind"] == "worker-submit-invalid"


def test_standing_loop_requests_capability_for_capability_missing_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_REQUIRE_STRUCTURED_SUBMIT", "true")
    monkeypatch.setenv("REFALL_RETRY_MAX_ATTEMPTS", "3")
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[{
        "id": "unit-1",
        "subject": "alpha",
        "type": "symbol",
        "path": "app.py",
        "line_start": 1,
        "line_end": 2,
        "name": "login",
    }])
    ab = FakeArcticBase(subject_path)
    dispatcher = FakeDispatcher([(
        "capability_missing",
        "capability_class=lan_network_probe; need target HTTP access before validation",
    )])
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    loop.run()

    assert len(dispatcher.started) == 1
    assert coverage.submits == []
    assert ab.capability_requests[0][1]["class"] == "lan_network_probe"
    assert ab.capability_requests[0][1]["requested_by"] == "cid-1"
    assert any(
        action["required_receipt_type"] == "capability_decision"
        and action["title"] == "Capability required: lan_network_probe"
        for action in ab.pending_actions
    )


def test_standing_loop_scope_blocked_status_requires_scope_decision_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_REQUIRE_STRUCTURED_SUBMIT", "true")
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[{
        "id": "unit-1",
        "subject": "alpha",
        "type": "symbol",
        "path": "app.py",
        "line_start": 1,
        "line_end": 2,
        "name": "login",
    }])
    ab = FakeArcticBase(subject_path)
    dispatcher = FakeDispatcher([(
        "scope_blocked",
        "External target validation is outside the signed permit.",
    )])
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    loop.run()

    assert coverage.submits == []
    assert ab.capability_requests == []
    assert any(
        action["required_receipt_type"] == "scope_decision"
        and action["title"] == "Scope blocked for cid-1"
        for action in ab.pending_actions
    )


def test_parse_agent_output_prefers_structured_submit() -> None:
    parsed = parse_agent_output(
        """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "task_result_submit",
  "subject": "alpha",
  "task_id": "task_1",
  "unit_id": "unit_1",
  "status": "done",
  "summary": "Structured completion",
  "produced_by": "cid_1",
  "created_at": "2026-07-24T00:00:00Z",
  "evidence": [{"kind":"source_anchor","ref":"app.py:1","claim":"reviewed"}],
  "source_anchors": ["app.py:1"],
  "confidence": "medium",
  "limitations": []
}
```
[DONE] legacy completion
"""
    )

    assert parsed.done == "Structured completion"
    assert parsed.coverage == ["app.py"]


def test_parse_agent_output_ingests_intelligence_nested_in_evidence_object() -> None:
    parsed = parse_agent_output(
        """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "task_result_submit",
  "subject": "alpha",
  "task_id": "task_1",
  "status": "complete",
  "summary": "Bounded assessment",
  "produced_by": "cid_1",
  "created_at": "2026-08-23T00:00:00Z",
  "confidence": "medium",
  "limitations": ["local only"],
  "source_anchors": ["app.js:10-20"],
  "evidence": {
    "facts": [{"id":"FACT-1","text":"[FACT] arch:component | acquired client"}],
    "flows": [{"id":"FLOW-1","text":"[FLOW] response -> eval : taints | app.js:10-20"}],
    "findings": [{"id":"F-1","title":"Response eval","source_anchors":["app.js:10-20"]}]
  }
}
```
"""
    )

    assert parsed.done == "Bounded assessment"
    assert [(fact["title"], fact["description"]) for fact in parsed.facts] == [
        ("arch:component", "acquired client")
    ]
    assert [(flow["from"], flow["to"], flow["relation"]) for flow in parsed.flows] == [
        ("response", "eval", "taints")
    ]
    assert [finding["title"] for finding in parsed.findings] == ["Response eval"]


def test_parse_agent_output_ingests_typed_evidence_list() -> None:
    parsed = parse_agent_output(
        """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "task_result_submit",
  "subject": "alpha",
  "task_id": "task_1",
  "status": "complete",
  "summary": "Bounded assessment",
  "produced_by": "cid_1",
  "created_at": "2026-08-23T00:00:00Z",
  "confidence": "medium",
  "limitations": ["local only"],
  "source_anchors": ["app.js:10-20"],
  "evidence": [
    {"kind":"fact","text":"[FACT] arch:component | acquired client","source_anchors":["app.js:10"]},
    {"kind":"flow","text":"[FLOW] response -> eval : taints | app.js:10-20","source_anchors":["app.js:10-20"]}
  ]
}
```
"""
    )

    assert [fact["title"] for fact in parsed.facts] == ["arch:component"]
    assert [(flow["from"], flow["to"]) for flow in parsed.flows] == [("response", "eval")]


def test_intel_dedup_preserves_distinct_facts_with_shared_aspect(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    ab = FakeArcticBase(subject_path)
    loop = RefallStandingLoop(
        "alpha",
        coverage=FakeCoverage(),
        arcticbase=ab,
        dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )
    conversation = DispatchedConversation(
        cid="cid-1", subject="alpha", lane="B", task_class="identify",
        unit=None, objective="test",
    )
    parsed = ParsedOutput(facts=[
        {"kind": "fact", "title": "arch:component", "description": "jQuery 3.6.0"},
        {"kind": "fact", "title": "arch:component", "description": "Kendo UI 2014.1.528"},
    ])

    counts = loop._persist_new_intel(conversation, parsed)

    assert counts["facts"] == 2
    fact_entries = [entry for _, entry in ab.ledger if entry.get("kind") == "fact"]
    assert [entry["description"] for entry in fact_entries] == ["jQuery 3.6.0", "Kendo UI 2014.1.528"]


def test_parse_agent_output_treats_characterized_status_as_completion() -> None:
    parsed = parse_agent_output(
        """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "task_result_submit",
  "subject": "alpha",
  "task_id": "task_1",
  "unit_id": "unit_1",
  "status": "characterized",
  "summary": "Source unit characterized",
  "produced_by": "cid_1",
  "created_at": "2026-07-24T00:00:00Z",
  "evidence": [{"kind":"source_anchor","ref":"app.py:1-20","claim":"reviewed"}],
  "source_anchors": ["app.py:1-20"],
  "confidence": "medium",
  "limitations": []
}
```
"""
    )

    assert parsed.done == "Source unit characterized"
    assert parsed.pending_actions == []
    assert parsed.coverage == ["app.py"]


def test_parse_agent_output_salvages_markers_from_invalid_submit() -> None:
    # A submission that fails strict validation (missing produced_by) must not
    # cause its embedded [FACT]/[FLOW]/[LEAD] markers to be discarded. They
    # arrive as JSON array-string elements and must still be parsed.
    parsed = parse_agent_output(
        """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "task_result_submit",
  "subject": "alpha",
  "status": "done",
  "summary": "no produced_by so this is schema-invalid",
  "facts": [
    "[FACT] arch:language | MIPS Windows CE PE",
    "[FACT] arch:component | bluetooth-update"
  ],
  "flows": [
    "[FLOW] BtFwUpgrade::init -> bt_upgrade_config.ini : reads | evidence"
  ],
  "leads": [
    "[LEAD:medium] Review update-media trust boundary | matters | next step"
  ]
}
```
"""
    )

    titles = {f["title"] for f in parsed.facts}
    assert "arch:language" in titles
    assert "arch:component" in titles
    assert any(fl["from"].startswith("BtFwUpgrade") for fl in parsed.flows)
    assert any(l["severity"] == "medium" for l in parsed.leads)


def test_parse_agent_output_preserves_structured_pending_actions() -> None:
    parsed = parse_agent_output(
        """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "control_submit",
  "subject": "alpha",
  "task_id": "task_1",
  "status": "needs_capability",
  "summary": "Need target HTTP access",
  "produced_by": "cid_1",
  "created_at": "2026-07-24T00:00:00Z",
  "capability_class": "lan_network_probe",
  "pending_actions": [
    {"kind":"operator_decision_needed","title":"Grant target HTTP","description":"Need HTTP probe"}
  ]
}
```
"""
    )

    assert parsed.pending_actions[0]["title"] == "Grant target HTTP"
    assert any(action["title"] == "Capability required: lan_network_probe" for action in parsed.pending_actions)


def test_standing_loop_claims_pending_action_before_normal_coverage_unit(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[{
        "id": "unit-1",
        "subject": "alpha",
        "type": "symbol",
        "path": "app.py",
        "line_start": 1,
        "line_end": 2,
        "name": "login",
    }])
    ab = FakeArcticBase(subject_path)
    ab.pending_actions.append({
        "id": "pa-existing",
        "status": "open",
        "kind": "operator_decision_needed",
        "title": "Review blocked validation",
        "description": "Runtime proof was blocked.",
        "priority": "high",
    })
    dispatcher = FakeDispatcher([("finished", "[DONE] pending action resolved")])
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    loop.run()

    assert dispatcher.started[0].task_class == "pending_action"
    assert dispatcher.started[0].unit["id"] == "pa-existing"
    assert coverage.submits == []
    assert ab.resolved_pending[0][1] == "pa-existing"


def test_pending_action_worker_filter_leaves_manager_reviews_for_manager() -> None:
    assert not _pending_action_worker_claimable({
        "kind": "watchdog_conversation_stopped",
        "required_receipt_type": "watchdog_stop_review",
    })
    assert not _pending_action_worker_claimable({
        "kind": "finding_candidate_review",
        "description": "finding promotion refused: source anchor not in source inventory: image@0x40",
        "required_receipt_type": "manager_review",
    })
    assert _pending_action_worker_claimable({
        "kind": "operator_decision_needed",
        "description": "Runtime proof was blocked.",
    })


def test_finding_code_paths_accept_mapping_source_anchor() -> None:
    conversation = DispatchedConversation(
        cid="c1", subject="alpha", lane="B", task_class="review", unit=None, objective=""
    )
    paths = _finding_code_paths(
        {"evidence": [{"path": "firmware.bin", "anchor": "0x40"}]},
        ParsedOutput(),
        conversation,
    )
    assert paths == ["firmware.bin:0x40"]


def test_standing_loop_prioritizes_fresh_coverage_before_followup_unit_work(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[{
        "id": "unit-2",
        "subject": "alpha",
        "type": "symbol",
        "path": "new.py",
        "line_start": 1,
        "line_end": 2,
        "name": "fresh",
    }])
    ab = FakeArcticBase(subject_path)
    dispatcher = FakeDispatcher([])
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )
    loop.scheduler.record_characterized({
        "id": "unit-1",
        "subject": "alpha",
        "type": "symbol",
        "path": "old.py",
        "line_start": 1,
        "line_end": 2,
        "name": "old",
    })

    task = loop._claim_next_task(active=[])

    assert task is not None
    assert task.task_class == "characterize"
    assert task.module_id == "characterize"
    assert task.unit["id"] == "unit-2"


def test_output_contract_suppresses_findings_when_subject_config_requests_it(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    ab = FakeArcticBase(subject_path)
    ab.extra_custom_fields["refall_no_findings"] = "true"
    loop = RefallStandingLoop(
        "alpha",
        coverage=FakeCoverage(),
        arcticbase=ab,
        dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    contract = loop._output_contract()
    pending_objective = loop._pending_action_objective("review", {"id": "pa-1", "kind": "finding_candidate_review"})

    assert "Do NOT emit ```finding blocks" in contract
    assert "For each FINDING" not in contract
    assert "Do NOT emit finding blocks" in pending_objective


def test_standing_loop_creates_pending_actions_from_structured_submit(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[{
        "id": "unit-1",
        "subject": "alpha",
        "type": "symbol",
        "path": "app.py",
        "line_start": 1,
        "line_end": 2,
        "name": "login",
    }])
    ab = FakeArcticBase(subject_path)
    dispatcher = FakeDispatcher([(
        "finished",
        """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "control_submit",
  "subject": "alpha",
  "task_id": "task_1",
  "status": "needs_capability",
  "summary": "Need target HTTP access",
  "produced_by": "cid_1",
  "created_at": "2026-07-24T00:00:00Z",
  "capability_class": "lan_network_probe",
  "pending_actions": [
    {"kind":"operator_decision_needed","title":"Grant target HTTP","description":"Need HTTP probe"}
  ]
}
```
""",
    )])
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    loop.run()

    assert any(action["title"] == "Grant target HTTP" for action in ab.pending_actions)
    assert any(action["title"] == "Capability required: lan_network_probe" for action in ab.pending_actions)
    assert ab.capability_requests[0][1]["class"] == "lan_network_probe"
    assert coverage.submits == []


def test_standing_loop_persists_structured_findings_to_workbench_coverage(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[{
        "id": "unit-1",
        "subject": "alpha",
        "type": "symbol",
        "path": "app.py",
        "line_start": 1,
        "line_end": 2,
        "name": "login",
    }])
    ab = FakeArcticBase(subject_path)
    dispatcher = FakeDispatcher([(
        "finished",
        """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "task_result_submit",
  "subject": "alpha",
  "task_id": "task_1",
  "unit_id": "unit_1",
  "status": "done",
  "summary": "Found a SQL injection.",
  "produced_by": "cid_1",
  "created_at": "2026-07-24T00:00:00Z",
  "evidence": [{"kind":"source_anchor","ref":"app.py:1","claim":"query built with user input"}],
  "source_anchors": ["app.py:1"],
  "confidence": "high",
  "limitations": [],
  "findings": [
    {
      "id": "find-sqli",
      "title": "SQL injection",
      "severity": "HIGH",
      "description": "User input reaches SQL text.",
      "impact": "Database read/write.",
      "code_paths": ["app.py:1"],
      "vuln_class": "sql-injection"
    }
  ]
}
```
""",
    )])
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    loop.run()

    assert coverage.findings[0][0] == "alpha"
    assert coverage.findings[0][1]["id"] == "find-sqli"
    assert coverage.findings[0][1]["status"] == "PROVISIONALLY_VALID"
    assert any(entry["kind"] == "finding" for _, entry in ab.ledger)


def test_standing_loop_routes_structured_transition_through_disposition_gate(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[{
        "id": "unit-1",
        "subject": "alpha",
        "type": "symbol",
        "path": "app.py",
        "line_start": 1,
        "line_end": 2,
        "name": "login",
    }])
    ab = FakeArcticBase(subject_path)
    dispatcher = FakeDispatcher([(
        "finished",
        """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "finding_submit",
  "subject": "alpha",
  "task_id": "task_1",
  "unit_id": "unit_1",
  "status": "done",
  "summary": "Route is not reachable in shipped config.",
  "produced_by": "cid_1",
  "created_at": "2026-07-24T00:00:00Z",
  "finding_id": "find-1",
  "evidence": [{"kind":"source_anchor","ref":"app.py:1","claim":"route excluded"}],
  "source_anchors": ["app.py:1"],
  "confidence": "high",
  "limitations": [],
  "proposed_transition": {"from_status":"PROVISIONALLY_VALID","to_status":"FALSE_POSITIVE"},
  "receipt_type": "non_reachability_proof",
  "receipt": {"summary":"Route excluded from shipped config.","source_anchors":["app.py:1"]}
}
```
""",
    )])
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    loop.run()

    assert ab.transitions == [(
        "alpha",
        "find-1",
        {
            "from_status": "PROVISIONALLY_VALID",
            "to_status": "FALSE_POSITIVE",
            "proposed_by": "cid_1",
            "reason": "Route is not reachable in shipped config.",
            "receipt_type": "non_reachability_proof",
            "receipt": {
                "summary": "Route excluded from shipped config.",
                "source_anchors": ["app.py:1"],
            },
        },
    )]


def test_standing_loop_routes_nested_finding_transition_through_disposition_gate(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[{
        "id": "unit-1",
        "subject": "alpha",
        "type": "symbol",
        "path": "app.py",
        "line_start": 1,
        "line_end": 2,
        "name": "login",
    }])
    ab = FakeArcticBase(subject_path)
    dispatcher = FakeDispatcher([(
        "finished",
        """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "task_result_submit",
  "subject": "alpha",
  "task_id": "task_1",
  "unit_id": "unit_1",
  "status": "done",
  "summary": "Reviewed route reachability.",
  "produced_by": "cid_1",
  "created_at": "2026-07-24T00:00:00Z",
  "evidence": [{"kind":"source_anchor","ref":"app.py:1","claim":"route excluded"}],
  "source_anchors": ["app.py:1"],
  "confidence": "high",
  "limitations": [],
  "findings": [
    {
      "id": "find-nested",
      "title": "Nested candidate issue",
      "severity": "LOW",
      "code_paths": ["app.py:1"],
      "proposed_transition": {
        "to_status": "FALSE_POSITIVE",
        "receipt_type": "non_reachability_proof",
        "receipt": {"source_anchors": ["app.py:1"], "summary": "Route excluded from shipped config."}
      }
    }
  ]
}
```
""",
    )])
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    loop.run()

    assert ab.transitions == [(
        "alpha",
        "find-nested",
        {
            "to_status": "FALSE_POSITIVE",
            "proposed_by": "cid_1",
            "reason": "Reviewed route reachability.",
            "receipt_type": "non_reachability_proof",
            "receipt": {"source_anchors": ["app.py:1"], "summary": "Route excluded from shipped config."},
        },
    )]


def test_standing_loop_duplicate_structured_submission_is_idempotent_by_submission_id(tmp_path: Path) -> None:
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    (subject_path / ".refall").mkdir(parents=True)
    unit = {
        "id": "unit-1",
        "subject": "alpha",
        "type": "symbol",
        "path": "app.py",
        "line_start": 1,
        "line_end": 2,
        "name": "login",
    }
    coverage = FakeCoverage(units=[])
    ab = FakeArcticBase(subject_path)
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )
    conversation = DispatchedConversation(
        cid="cid-1",
        subject="alpha",
        lane="A",
        task_class="characterize",
        unit=unit,
        objective="review login",
    )
    response = """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "task_result_submit",
  "subject": "alpha",
  "submission_id": "submit-1",
  "task_id": "task_1",
  "unit_id": "unit-1",
  "status": "done",
  "summary": "Structured completion",
  "produced_by": "cid_1",
  "created_at": "2026-07-24T00:00:00Z",
  "evidence": [{"kind":"source_anchor","ref":"app.py:1","claim":"reviewed"}],
  "source_anchors": ["app.py:1"],
  "confidence": "medium",
  "limitations": [],
  "findings": [
    {"id": "find-sqli", "title": "SQL injection", "severity": "HIGH", "code_paths": ["app.py:1"]}
  ]
}
```
"""

    loop._finish_conversation(conversation, PollResult(cid="cid-1", status="finished", response=response))
    loop._finish_conversation(conversation, PollResult(cid="cid-1", status="finished", response=response))

    assert len(coverage.submits) == 1
    assert len(coverage.findings) == 1
    finding_entries = [entry for _, entry in ab.ledger if entry.get("kind") == "finding"]
    assert len(finding_entries) == 1


def test_standing_loop_archives_events_and_reaps_completed_conversation(
    tmp_path: Path, monkeypatch
) -> None:
    """A finished conversation is archived, then deleted so the agent server frees it."""
    conversations = tmp_path / "agent-canvas" / "conversations"
    # Agent Canvas stores events under the cid with dashes stripped.
    canvas_events = conversations / "cid1" / "events"
    canvas_events.mkdir(parents=True)
    (canvas_events / "0001.json").write_text('{"action": "read", "path": "app.py"}')
    monkeypatch.setattr(
        "ref_all_executor.config.OPENHANDS_CONVERSATIONS_DIR", str(conversations)
    )

    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[{
        "id": "unit-1",
        "subject": "alpha",
        "type": "symbol",
        "path": "app.py",
        "line_start": 1,
        "line_end": 2,
        "name": "login",
    }])
    ab = FakeArcticBase(subject_path)
    dispatcher = FakeDispatcher([("finished", "[DONE] reviewed login")])
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    loop.run()

    # The conversation is released so the agent server does not hold it for the run.
    assert dispatcher.deleted == ["cid-1"]
    # ...but its event stream survives, under the root the debug endpoint searches.
    archived = subject_path / "refallsubloop/logs/agents/cid-1/events/0001.json"
    assert archived.is_file()
    assert "app.py" in archived.read_text()

    events = [
        json.loads(line)
        for line in (subject_path / "refallsubloop/logs/events/events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    complete = [e for e in events if e["type"] == "agent_complete"]
    assert complete[0]["archive_status"] == "archived"
    assert complete[0]["delete_status"] == "deleted"


def test_standing_loop_still_reaps_when_no_canvas_events_exist(
    tmp_path: Path, monkeypatch
) -> None:
    """A missing event dir must not block the reap — that would reintroduce the leak."""
    monkeypatch.setattr(
        "ref_all_executor.config.OPENHANDS_CONVERSATIONS_DIR", str(tmp_path / "absent")
    )
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[{
        "id": "unit-1",
        "subject": "alpha",
        "type": "symbol",
        "path": "app.py",
        "line_start": 1,
        "line_end": 2,
        "name": "login",
    }])
    ab = FakeArcticBase(subject_path)
    dispatcher = FakeDispatcher([("finished", "[DONE] reviewed login")])
    loop = RefallStandingLoop(
        "alpha",
        coverage=coverage,
        arcticbase=ab,
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )

    loop.run()

    assert dispatcher.deleted == ["cid-1"]
    events = [
        json.loads(line)
        for line in (subject_path / "refallsubloop/logs/events/events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    complete = [e for e in events if e["type"] == "agent_complete"]
    assert complete[0]["archive_status"] == "not_found"
    assert complete[0]["delete_status"] == "deleted"


def test_modules_dispatch_followon_assessment_after_characterize(tmp_path: Path, monkeypatch):
    """The core wiring: once a unit is characterized, the loop dispatches a
    follow-on assessment module (recon/review) on it, not just more characterize."""
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[{
        "id": "unit-1", "subject": "alpha", "type": "symbol",
        "path": "app.c", "line_start": 1, "line_end": 9, "name": "parse",
    }])
    ab = FakeArcticBase(subject_path)
    # security assessment default: characterize -> sec_recon -> sec_review
    dispatcher = FakeDispatcher([
        ("finished", "[DONE] characterized parse()"),   # unit-1 characterize
        ("finished", "[DONE] recon of parse()"),         # follow-on sec_recon
    ])
    # Continuous mode (as production runs it). The loop stops on its own once
    # coverage has no units AND the scheduler has no follow-on work left.
    loop = RefallStandingLoop(
        "alpha", coverage=coverage, arcticbase=ab, dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=0, max_parallel=1, poll_interval_s=0),
    )
    loop.run()

    dispatched_classes = [t.task_class for t in dispatcher.started]
    # characterize ran first, then a NON-characterize assessment module.
    assert dispatched_classes[0] == "characterize"
    assert any(c != "characterize" for c in dispatched_classes), \
        f"no follow-on assessment dispatched, only: {dispatched_classes}"
    # progress persisted
    prog = json.loads((subject_path / ".refall/module_progress.json").read_text())
    assert "unit-1" in prog["characterized"]


def test_module_registry_defaults_to_security_assessment(tmp_path: Path):
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    loop = RefallStandingLoop(
        "alpha", coverage=FakeCoverage(), arcticbase=FakeArcticBase(subject_path),
        dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )
    ids = {m.id for m in loop.module_registry.active}
    assert "characterize" in ids and "sec_recon" in ids


def test_flow_marker_parses_into_structured_edge():
    """[FLOW] a -> b : relation | evidence becomes a typed edge that can rebuild
    a call/data-flow graph -- structured enough to reconstruct a diagram."""
    parsed = parse_agent_output(
        "[FLOW] update_check -> verlist.ini : reads | nk.exe:0x1240\n"
        "[FLOW] parse_nk -> decompress : calls | NK.bin\n"
        "[FACT] arch:language | MIPS Windows CE PE\n"
    )
    assert len(parsed.flows) == 2
    e0 = parsed.flows[0]
    assert e0["from"] == "update_check" and e0["to"] == "verlist.ini"
    assert e0["relation"] == "reads" and e0["evidence"] == "nk.exe:0x1240"
    # architecture rides along as a parseable fact
    assert any(f["title"].startswith("arch:language") for f in parsed.facts)


def test_flows_persist_to_ledger_as_typed_facts():
    from ref_all_executor.standing_loop import _entries_from_parsed, DispatchedConversation
    parsed = parse_agent_output("[FLOW] a -> b : calls | x.c:1\n")
    conv = DispatchedConversation(cid="c1", subject="s", lane="A",
                                  task_class="characterize", unit={"id": "u1"}, objective="")
    entries = _entries_from_parsed(parsed, conv)
    flow_entries = [e for e in entries if e.get("fact_kind") == "flow"]
    assert len(flow_entries) == 1
    assert flow_entries[0]["flow"]["relation"] == "calls"
    assert flow_entries[0]["kind"] == "fact"   # allowed ledger kind


def test_determination_fields_extracted_from_structured_submit():
    from ref_all_executor.standing_loop import _determination_fields, ParsedOutput
    parsed = ParsedOutput(structured=[{
        "sensitivity": "high",
        "data_touched": ["NK.bin", "verlist.ini"],
        "flows_in": ["WinMain"],
        "flows_out": ["decompress", "verify_sig"],
    }])
    fields = _determination_fields(parsed)
    assert fields["sensitivity"] == "high"
    assert fields["data_touched"] == ["NK.bin", "verlist.ini"]
    assert fields["flows_out"] == ["decompress", "verify_sig"]


def test_determination_fields_empty_when_absent():
    from ref_all_executor.standing_loop import _determination_fields, ParsedOutput
    assert _determination_fields(ParsedOutput()) == {}


def test_report_agent_fires_after_intel_threshold(tmp_path: Path):
    """A report-writing agent takes one slot once N new intel accumulate,
    without interrupting analysis agents."""
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    ab = FakeArcticBase(subject_path)
    # Pre-load ledger with 30 facts so the threshold is already crossed.
    for i in range(30):
        ab.ledger.append(("alpha", {"kind": "fact", "title": f"f{i}"}))
    coverage = FakeCoverage(units=[])
    dispatcher = FakeDispatcher([])
    loop = RefallStandingLoop(
        "alpha", coverage=coverage, arcticbase=ab, dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=0, max_parallel=4, poll_interval_s=0,
                                  report_agent_intel_threshold=30),
    )
    active = []
    loop._maybe_dispatch_report_agent(1, active)
    assert len(active) == 1
    assert active[0].task_class == "report"
    # counter advanced so it will not immediately re-fire
    assert loop.last_report_intel == 30
    active2 = []
    loop._maybe_dispatch_report_agent(2, active2)
    assert active2 == []   # no new intel since -> no report


def test_report_agent_waits_for_complete_source_coverage(tmp_path: Path):
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    ab = FakeArcticBase(subject_path)
    for i in range(30):
        ab.ledger.append(("alpha", {"kind": "fact", "title": f"f{i}"}))
    coverage = FakeCoverage(units=[])
    loop = RefallStandingLoop(
        "alpha", coverage=coverage, arcticbase=ab, dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=0, max_parallel=4, poll_interval_s=0,
                                  report_agent_intel_threshold=30),
    )
    loop._safe_coverage = lambda: {"files_done": 2, "files_total": 3, "resolved_pct": 90.0}
    active = []

    loop._maybe_dispatch_report_agent(1, active)

    assert active == []
    assert loop.last_report_intel == 0


def test_report_agent_disabled_at_zero_threshold(tmp_path: Path):
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    ab = FakeArcticBase(subject_path)
    for i in range(50):
        ab.ledger.append(("alpha", {"kind": "finding", "title": f"x{i}"}))
    loop = RefallStandingLoop(
        "alpha", coverage=FakeCoverage(), arcticbase=ab, dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=0, max_parallel=4, poll_interval_s=0,
                                  report_agent_intel_threshold=0),
    )
    active = []
    loop._maybe_dispatch_report_agent(1, active)
    assert active == []


def test_report_agent_needs_a_free_slot(tmp_path: Path):
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    ab = FakeArcticBase(subject_path)
    for i in range(40):
        ab.ledger.append(("alpha", {"kind": "lead", "title": f"l{i}"}))
    loop = RefallStandingLoop(
        "alpha", coverage=FakeCoverage(), arcticbase=ab, dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=0, max_parallel=2, poll_interval_s=0,
                                  report_agent_intel_threshold=30),
    )
    full = ["busy", "busy"]  # both slots occupied
    loop._maybe_dispatch_report_agent(1, full)
    assert len(full) == 2   # nothing added; no free slot


def test_continuous_codex_report_agent_uses_fifth_slot_beside_four_analysis_agents(tmp_path: Path):
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    units = [
        {
            "id": f"unit-{index}",
            "subject": "alpha",
            "type": "symbol",
            "path": f"file-{index}.py",
            "line_start": 1,
            "line_end": 2,
            "name": f"unit-{index}",
        }
        for index in range(8)
    ]
    ab = FakeArcticBase(subject_path)
    ab.extra_custom_fields.update({
        "refall_lane_pattern": "A,A,B,B",
        "refall_report_agent_continuous": True,
        "refall_report_lane": "B",
    })
    dispatcher = FakeDispatcher([])
    loop = RefallStandingLoop(
        "alpha",
        coverage=FakeCoverage(units=units),
        arcticbase=ab,
        dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=1, max_parallel=5, poll_interval_s=0),
    )

    loop.run()

    report_tasks = [task for task in dispatcher.started if task.task_class == "report"]
    analysis_tasks = [task for task in dispatcher.started if task.task_class != "report"]
    assert len(report_tasks) == 1
    assert report_tasks[0].lane == "B"
    assert len(analysis_tasks) == 4
    assert sorted(task.lane for task in analysis_tasks) == ["A", "A", "B", "B"]


def test_continuous_report_complete_with_limitations_does_not_open_worker_blocked(tmp_path: Path):
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    ab = FakeArcticBase(subject_path)
    loop = RefallStandingLoop(
        "alpha", coverage=FakeCoverage(), arcticbase=ab,
        dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=0, max_parallel=1, poll_interval_s=0),
    )
    conv = DispatchedConversation(
        cid="report-cid", subject="alpha", lane="B", task_class="report",
        unit=None, objective="compile partial report", submits_coverage=False,
    )
    response = """```refall-submit
{"schema":"refall.submit.v1","type":"task_result_submit","subject":"alpha","submission_id":"report-partial-1","task_id":"report","status":"complete_with_limitations","summary":"Partial report compiled; analysis is still in progress.","produced_by":"report-cid","created_at":"2026-08-24T00:00:00Z","evidence":[{"kind":"artifact","ref":"report.md","claim":"partial report"}],"artifact_refs":["report.md"],"confidence":"medium","limitations":["coverage still running"],"findings":[]}
```"""

    loop._finish_conversation(
        conv, PollResult(cid=conv.cid, status="finished", response=response)
    )

    assert not any(action.get("kind") == "worker_blocked" for action in ab.pending_actions)


def test_continuous_report_completed_with_scope_limitations_does_not_open_worker_blocked(tmp_path: Path):
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    ab = FakeArcticBase(subject_path)
    loop = RefallStandingLoop(
        "alpha", coverage=FakeCoverage(), arcticbase=ab,
        dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=0, max_parallel=1, poll_interval_s=0),
    )
    conv = DispatchedConversation(
        cid="report-cid", subject="alpha", lane="B", task_class="report",
        unit=None, objective="compile partial report", submits_coverage=False,
    )
    response = """```refall-submit
{"schema":"refall.submit.v1","type":"task_result_submit","subject":"alpha","submission_id":"report-partial-scope-1","task_id":"report","status":"completed_with_scope_limitations","summary":"Partial report compiled within static-only scope.","produced_by":"report-cid","created_at":"2026-08-24T00:00:00Z","evidence":[{"kind":"artifact","ref":"report.md","claim":"partial report"}],"artifact_refs":["report.md"],"confidence":"medium","limitations":["dynamic validation is out of scope"],"findings":[]}
```"""

    loop._finish_conversation(
        conv, PollResult(cid=conv.cid, status="finished", response=response)
    )

    assert not any(action.get("kind") == "worker_blocked" for action in ab.pending_actions)


def test_no_findings_mapping_subject_refreshes_report_from_mapping_intel(tmp_path: Path):
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    ab = FakeArcticBase(subject_path)
    ab.extra_custom_fields["refall_no_findings"] = "true"
    ab.ledger.append(("alpha", {"kind": "lead", "title": "equipment map"}))
    calls = []

    loop = RefallStandingLoop(
        "alpha",
        coverage=FakeCoverage(),
        arcticbase=ab,
        dispatcher=FakeDispatcher([]),
        draft_reporter=lambda workbench, subject: calls.append((workbench, subject)) or {"object_id": "obj_report"},
        config=StandingLoopConfig(max_cycles=0, poll_interval_s=0, report_interval_cycles=2),
    )

    loop._maybe_refresh_report(2)

    assert calls == [("alpha", "alpha")]
    assert any(entry["kind"] == "artifact" and entry["summary"] == "Standing loop refreshed draft report" for _, entry in ab.ledger)


def test_visualization_waits_for_complete_source_coverage(tmp_path: Path):
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    ab = FakeArcticBase(subject_path)
    for i in range(3):
        ab.ledger.append(("alpha", {"kind": "finding", "title": f"f{i}"}))
    loop = RefallStandingLoop(
        "alpha", coverage=FakeCoverage(), arcticbase=ab, dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=0, max_parallel=4, poll_interval_s=0),
    )
    loop._safe_coverage = lambda: {"files_done": 2, "files_total": 3, "resolved_pct": 90.0}
    active = []

    loop._maybe_dispatch_visualization(20, active)

    assert active == []


def test_no_findings_mapping_subject_visualizes_after_complete_coverage(tmp_path: Path):
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    ab = FakeArcticBase(subject_path)
    ab.extra_custom_fields["refall_no_findings"] = "true"
    loop = RefallStandingLoop(
        "alpha", coverage=FakeCoverage(), arcticbase=ab, dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=0, max_parallel=4, poll_interval_s=0),
    )
    loop._safe_coverage = lambda: {"files_done": 3, "files_total": 3, "resolved_pct": 100.0}
    active = []

    loop._maybe_dispatch_visualization(20, active)

    assert len(active) == 1
    assert active[0].task_class == "visualization"
    assert "source-mapping visuals" in active[0].objective


def test_retry_fails_over_from_claude_to_codex(tmp_path: Path, monkeypatch):
    """A lane-A (Claude) task that balks retries on lane B (Codex), not Claude again."""
    monkeypatch.setenv("REFALL_REQUIRE_STRUCTURED_SUBMIT", "true")
    monkeypatch.setenv("REFALL_RETRY_MAX_ATTEMPTS", "2")
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage(units=[{
        "id": "unit-1", "subject": "alpha", "type": "symbol",
        "path": "app.c", "line_start": 1, "line_end": 2, "name": "f",
    }])
    ab = FakeArcticBase(subject_path)
    # First attempt (lane A) ends with no structured submit -> retryable balk.
    dispatcher = FakeDispatcher([
        ("finished", "I cannot complete this."),   # cid-1, lane A, no refall-submit
    ])
    loop = RefallStandingLoop(
        "alpha", coverage=coverage, arcticbase=ab, dispatcher=dispatcher,
        config=StandingLoopConfig(max_cycles=1, max_parallel=1, poll_interval_s=0),
    )
    loop.run()
    # the characterize task started on A, retry must be dispatched on B
    lanes = [t.lane for t in dispatcher.started]
    assert lanes[0] == "A"
    assert "B" in lanes, f"no failover to Codex; lanes were {lanes}"
    switch = [e for e in _read_events(subject_path) if e.get("type") == "retry_provider_switch"]
    assert switch and switch[0]["from_lane"] == "A" and switch[0]["to_lane"] == "B"


def _read_events(subject_path):
    import json as _json
    p = subject_path / "refallsubloop/logs/events/events.jsonl"
    return [_json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def test_failover_lane_helper():
    from ref_all_executor.standing_loop import _failover_lane
    assert _failover_lane("A") == "B"   # Claude -> Codex
    assert _failover_lane("B") == "B"   # Codex stays (no third provider)
    assert _failover_lane("C") == "C"


def test_stopped_agent_intel_is_salvaged_not_discarded(tmp_path: Path):
    """The core fix: an agent stopped mid-work (not 'finished') still gets its
    facts/leads/findings/flows persisted, instead of everything being thrown away."""
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage()
    ab = FakeArcticBase(subject_path)
    loop = RefallStandingLoop(
        "alpha", coverage=coverage, arcticbase=ab, dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=0, max_parallel=1, poll_interval_s=0),
    )
    conv = DispatchedConversation(cid="c1", subject="alpha", lane="A",
                                  task_class="pending_action", unit={"id": "u1"}, objective="")
    # Agent did real RE work then got STOPPED at max_iterations (no clean submit).
    response = (
        "Analyzing NK.bin update path...\n"
        "[FACT] arch:language | MIPS Windows CE PE\n"
        "[FLOW] update_check -> verlist.ini : reads | nk.bin:0x1240\n"
        "[LEAD:high] unsigned firmware accepted | no signature check on BT update | check bt_upgrade_config.ini\n"
        "```finding\n"
        '{"title":"Unsigned BT firmware accepted","severity":"HIGH","code_paths":["bt.dll:0x40"],'
        '"evidence":["bt.dll:0x40"]}\n'
        "```\n"
    )
    loop._finish_conversation(conv, PollResult(cid="c1", status="stopped", response=response))

    kinds = [e.get("kind") for _, e in ab.ledger]
    assert "fact" in kinds, "stopped agent's fact was discarded"
    assert "lead" in kinds, "stopped agent's lead was discarded"
    assert any(e.get("fact_kind") == "flow" for _, e in ab.ledger), "flow edge discarded"
    assert len(coverage.findings) == 1, "stopped agent's finding was discarded"
    salvaged = [e for e in ab.events if e.get("type") == "intel_salvaged"]
    assert salvaged and salvaged[0]["status"] == "stopped"


def test_ingests_findings_saved_to_agent_workspace(tmp_path: Path):
    """The unlock: agents save REFALL_SUBMISSION.json with findings to their
    workspace and end with empty final_response. The loop must read that file
    and ingest the findings instead of seeing nothing."""
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    ab = FakeArcticBase(subject_path)
    coverage = FakeCoverage()
    loop = RefallStandingLoop(
        "alpha", coverage=coverage, arcticbase=ab, dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=0, max_parallel=1, poll_interval_s=0),
    )
    # agent workspace with a saved submission (agent ended with empty response)
    ws = tmp_path / "ws" / "B-pending_action-pa_x"
    ws.mkdir(parents=True)
    (ws / "REFALL_SUBMISSION.json").write_text(json.dumps({
        "schema": "refall.submit.v1",
        "findings": [
            {"title": "Unsigned BT firmware accepted", "severity": "CRITICAL",
             "code_paths": ["bt.dll:0x40"], "evidence": ["bt.dll:0x40"]},
            {"title": "IPC.dll missing auth", "severity": "HIGH",
             "code_paths": ["ipc.dll:0x10"], "evidence": ["ipc.dll:0x10"]},
        ],
        "facts": [{"title": "arch: MIPS Windows CE PE"}],
    }))
    (ws / "bt_disasm.txt").write_text("0x40: jal verify\n" * 5)
    conv = DispatchedConversation(cid="c1", subject="alpha", lane="B",
                                  task_class="pending_action", unit={"id": "pa_x"},
                                  objective="", workspace_host=str(ws))
    # empty final_response, exactly like the real failure mode
    loop._finish_conversation(conv, PollResult(cid="c1", status="finished", response=""))

    assert len(coverage.findings) == 2, "workspace findings not ingested"
    titles = {f.get("title") for _, f in coverage.findings}
    assert "Unsigned BT firmware accepted" in titles
    kinds = [e.get("kind") for _, e in ab.ledger]
    assert "fact" in kinds
    # analysis file registered as a durable artifact
    art_kinds = [a.get("kind") for _, a in ab.runtime_artifacts]
    assert "agent-analysis" in art_kinds


def test_active_conversation_restore_preserves_workspace_host(tmp_path: Path):
    """A bounded update must retain the host workspace created by the
    dispatching process so the resuming process can ingest saved submissions."""
    workspace = tmp_path / "refallsub" / "alpha" / "A-doc_synthesis-test"
    original = DispatchedConversation(
        cid="resume-cid",
        subject="alpha",
        lane="A",
        task_class="doc_synthesis",
        unit=None,
        objective="canonicalize saved output",
        workspace_host=str(workspace),
        module_id="canonicalize",
        module_target="__subject__",
        submits_coverage=False,
    )

    restored = RefallStandingLoop._active_from_dict(original.__dict__)

    assert restored.workspace_host == str(workspace)


def test_workspace_submission_normalizes_marker_string_facts_and_flows(tmp_path: Path):
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    ab = FakeArcticBase(subject_path)
    loop = RefallStandingLoop(
        "alpha", coverage=FakeCoverage(), arcticbase=ab,
        dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=0, max_parallel=1, poll_interval_s=0),
    )
    ws = tmp_path / "ws" / "A-doc_synthesis-test"
    ws.mkdir(parents=True)
    (ws / "REFALL_SUBMISSION.json").write_text(json.dumps({
        "schema": "refall.submit.v1",
        "facts": [
            "[FACT] arch:component | update client",
            {"title": "methodology:passive", "description": "source review only"},
        ],
        "flows": [
            "[FLOW] update_client -> version.json : reads | src/update.c:40",
            {"from": "version.json", "to": "update.img", "relation": "references",
             "evidence": "src/update.c:45"},
        ],
    }), encoding="utf-8")
    conv = DispatchedConversation(
        cid="resume-cid", subject="alpha", lane="A", task_class="doc_synthesis",
        unit=None, objective="", workspace_host=str(ws),
        module_id="canonicalize", module_target="__subject__",
    )

    loop._finish_conversation(
        conv, PollResult(cid=conv.cid, status="finished", response="")
    )

    entries = [entry for _, entry in ab.ledger]
    assert any(entry.get("title") == "arch:component" for entry in entries)
    assert any(entry.get("title") == "methodology:passive" for entry in entries)
    assert any(
        entry.get("fact_kind") == "flow"
        and entry.get("flow", {}).get("from") == "update_client"
        for entry in entries
    )
    assert any(
        entry.get("fact_kind") == "flow"
        and entry.get("flow", {}).get("from") == "version.json"
        for entry in entries
    )


def test_custom_module_with_missing_workspace_and_zero_intel_is_not_completed(tmp_path: Path):
    """A resumed custom module must not silently advance when its workspace was
    lost and its terminal response contains no canonical intelligence."""
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    (subject_path / ".refall").mkdir()
    ab = FakeArcticBase(subject_path)
    loop = RefallStandingLoop(
        "alpha", coverage=FakeCoverage(), arcticbase=ab,
        dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=0, max_parallel=1, poll_interval_s=0),
    )
    completed = []
    loop._record_module_completion = lambda conversation, parsed: completed.append(
        (conversation.module_id, conversation.module_target)
    )
    conv = DispatchedConversation(
        cid="resume-cid", subject="alpha", lane="A", task_class="doc_synthesis",
        unit=None, objective="canonicalize existing evidence", workspace_host=None,
        module_id="canonicalize", module_target="__subject__",
        submits_coverage=False,
    )

    loop._finish_conversation(
        conv, PollResult(cid=conv.cid, status="finished", response="")
    )

    assert completed == []
    assert any(
        action.get("kind") == "worker_output_not_ingested"
        for action in ab.pending_actions
    )
    assert any(
        event.get("type") == "module_completion_blocked"
        for event in ab.events
    )


def test_subject_module_persistence_failure_is_not_marked_complete(tmp_path: Path):
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    (subject_path / ".refall").mkdir()
    ab = FakeArcticBase(subject_path)

    def reject_ledger(slug, entry):
        raise RuntimeError("backend unavailable")

    ab.append_ledger = reject_ledger
    loop = RefallStandingLoop(
        "alpha", coverage=FakeCoverage(), arcticbase=ab,
        dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=0, max_parallel=1, poll_interval_s=0),
    )
    completed = []
    loop._record_module_completion = lambda conversation, parsed: completed.append(
        (conversation.module_id, conversation.module_target)
    )
    conv = DispatchedConversation(
        cid="subject-cid", subject="alpha", lane="B", task_class="doc_synthesis",
        unit=None, objective="synthesize", module_id="synthesize",
        module_target="__subject__", submits_coverage=False,
    )

    loop._finish_conversation(
        conv,
        PollResult(
            cid=conv.cid, status="finished",
            response="[FACT] architecture:entrypoint | main.py:1",
        ),
    )

    assert completed == []
    assert any(
        action.get("kind") == "worker_output_not_ingested"
        for action in ab.pending_actions
    )
    blocked = [event for event in ab.events if event.get("type") == "module_completion_blocked"]
    assert blocked and blocked[0].get("reason") == "canonical_persistence_failed"


def test_incremental_ingest_updates_intel_in_real_time(tmp_path: Path):
    """Intel from a still-RUNNING agent's workspace is persisted live, and not
    re-persisted at completion (unified dedup)."""
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage()
    ab = FakeArcticBase(subject_path)
    loop = RefallStandingLoop(
        "alpha", coverage=coverage, arcticbase=ab, dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=0, max_parallel=1, poll_interval_s=0),
    )
    ws = tmp_path / "ws" / "B-recon-x"; ws.mkdir(parents=True)
    (ws / "refall_submission.json").write_text(json.dumps({
        "schema": "refall.submit.v1",
        "findings": [{"title": "Live finding", "severity": "HIGH", "code_paths": ["x.dll:0x1"], "evidence": ["x.dll:0x1"]}],
        "facts": [{"title": "arch: MIPS"}],
    }))
    conv = DispatchedConversation(cid="c1", subject="alpha", lane="B", task_class="recon",
                                  unit={"id": "u1"}, objective="", workspace_host=str(ws))
    # 1) while running -> ingested live
    loop._incremental_ingest(conv)
    assert len(coverage.findings) == 1
    # 2) polling again (agent still running, same file) -> NOT re-ingested
    loop._incremental_ingest(conv)
    assert len(coverage.findings) == 1, "re-persisted duplicate on re-poll"
    # 3) at completion salvage -> still no duplicate
    loop._finish_conversation(conv, PollResult(cid="c1", status="finished", response=""))
    assert len(coverage.findings) == 1, "salvage re-persisted what incremental already did"


def test_workspace_ingest_skips_refall_ingested_marker_dirs(tmp_path: Path):
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    ab = FakeArcticBase(subject_path)
    loop = RefallStandingLoop(
        "alpha", coverage=FakeCoverage(), arcticbase=ab, dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=0, max_parallel=1, poll_interval_s=0),
    )
    ws = tmp_path / "ws" / "B-recon-x"
    marker = ws / "artifacts" / ".refall-ingested" / ".refall-ingested"
    marker.mkdir(parents=True)
    (marker / "old.txt").write_text("already ingested", encoding="utf-8")
    (ws / "notes.txt").parent.mkdir(parents=True, exist_ok=True)
    (ws / "notes.txt").write_text("fresh note", encoding="utf-8")
    conv = DispatchedConversation(
        cid="c1", subject="alpha", lane="B", task_class="recon",
        unit={"id": "u1"}, objective="", workspace_host=str(ws),
    )

    loop._incremental_ingest(conv)

    filenames = [artifact.get("filename") for _, artifact in ab.runtime_artifacts]
    assert "notes.txt" in filenames
    assert "old.txt" not in filenames


def test_read_conversation_agent_text_from_event_stream(tmp_path: Path):
    """The real fix: capture the agent's tagged output from the conversation
    EVENT STREAM (every agent message), not the empty agent_final_response."""
    from ref_all_executor.standing_loop import read_conversation_agent_text
    cid = "8259249e-b6ce-4ae6-86e9-6949cfd02bfc"
    ev = tmp_path / cid.replace("-", "") / "events"
    ev.mkdir(parents=True)
    # a MessageEvent (agent) with the tagged final synthesis
    (ev / "event-00000-a.json").write_text(json.dumps({
        "source": "agent", "kind": "MessageEvent",
        "llm_message": {"role": "assistant", "content": [
            {"type": "text", "text": "[FACT] arch:language | MIPS Windows CE PE\n"
             "[FLOW] update_check -> verlist.ini : reads | nk.bin:0x1240\n"
             "```finding\n{\"title\":\"Unsigned BT firmware\",\"severity\":\"CRITICAL\"}\n```"}]},
    }))
    # a user event (must be ignored)
    (ev / "event-00001-u.json").write_text(json.dumps({"source": "user", "kind": "MessageEvent"}))
    # an agent ActionEvent with a message
    (ev / "event-00002-b.json").write_text(json.dumps({
        "source": "agent", "kind": "ActionEvent",
        "action": {"message": "[LEAD:high] downgrade accepted | no version floor | check verlist.ini"}}))

    text = read_conversation_agent_text(cid, conversations_dir=str(tmp_path))
    assert "[FACT] arch:language" in text
    assert "[FLOW] update_check" in text
    assert "[LEAD:high] downgrade" in text
    assert "```finding" in text
    parsed = parse_agent_output(text)
    assert len(parsed.facts) >= 1 and len(parsed.flows) >= 1
    assert len(parsed.leads) >= 1 and len(parsed.findings) >= 1


def test_read_conversation_agent_text_missing_dir_is_empty(tmp_path: Path):
    from ref_all_executor.standing_loop import read_conversation_agent_text
    assert read_conversation_agent_text("no-such-cid", conversations_dir=str(tmp_path)) == ""


def test_read_conversation_agent_text_supports_current_canvas_content_schema(tmp_path: Path):
    from ref_all_executor.standing_loop import read_conversation_agent_text

    cid = "cdffac94-f24a-4803-b953-e678722ee58d"
    events = tmp_path / cid.replace("-", "") / "events"
    events.mkdir(parents=True)
    (events / "event-00000.json").write_text(json.dumps({
        "source": "agent",
        "kind": "MessageEvent",
        "content": [{"type": "text", "text": "```refall-submit\n{\"schema\":\"refall.submit.v1\"}\n```"}],
    }))

    text = read_conversation_agent_text(cid, conversations_dir=str(tmp_path))

    assert "```refall-submit" in text
    assert "refall.submit.v1" in text


def test_read_conversation_agent_text_supports_hyphenated_archive_directory(tmp_path: Path):
    from ref_all_executor.standing_loop import read_conversation_agent_text

    cid = "a9450bc8-2098-4bbc-8aaf-f24c0972ff26"
    events = tmp_path / cid / "events"
    events.mkdir(parents=True)
    (events / "event-00000.json").write_text(json.dumps({
        "source": "agent",
        "kind": "ActionEvent",
        "action": {"message": "[FACT] arch:archive | durable"},
    }))

    assert "[FACT] arch:archive" in read_conversation_agent_text(cid, conversations_dir=str(tmp_path))


def test_finding_persistence_normalizes_agent_field_shapes_and_inherits_envelope_evidence(tmp_path: Path):
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage()
    loop = RefallStandingLoop(
        "alpha", coverage=coverage, arcticbase=FakeArcticBase(subject_path),
        dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=0, max_parallel=1, poll_interval_s=0),
    )
    parsed = ParsedOutput(
        findings=[{
            "title": "Agent-shaped finding",
            "severity": "HIGH",
            "component": "request handler",
            "affected": "1.0 (affected)",
            "source_anchors": "app.py:7",
            "evidence": ["app.py:7", "Observed unsafe call result."],
            "limitations": "Static analysis only.",
            "reproduction_steps": "Inspect the call at app.py:7.",
            "poc_refs": "obj_candidate_poc",
            "remediation": ["Reject oversized input.", "Add a regression test."],
        }],
        structured=[{
            "confidence": "high",
            "source_anchors": ["app.py:7"],
            "artifact_refs": ["art_parent"],
            "evidence": [{"kind": "source_anchor", "ref": "app.py:7", "claim": "unsafe call"}],
            "limitations": ["No live reproduction."],
        }],
    )
    conversation = DispatchedConversation(
        cid="cid-1", subject="alpha", lane="A", task_class="review",
        unit={"id": "unit-1", "path": "app.py", "line_start": 7}, objective="",
    )

    loop._persist_findings(parsed, conversation)

    payload = coverage.findings[0][1]
    assert payload["code_paths"] == ["app.py:7"]
    assert payload["source_anchors"] == ["app.py:7"]
    assert payload["artifact_refs"] == ["art_parent"]
    assert payload["evidence"] == [
        {"kind": "source_anchor", "ref": "app.py:7", "claim": "Agent-shaped finding"},
        {"kind": "agent_observation", "claim": "Observed unsafe call result."},
    ]
    assert payload["limitations"] == ["Static analysis only."]
    assert payload["reproduction_steps"] == ["Inspect the call at app.py:7."]
    assert payload["affected_versions"] == ["1.0 (affected)"]
    assert payload["affected_component"] == "request handler"
    assert payload["poc_refs"] == ["obj_candidate_poc"]
    assert payload["remediation"] == "Reject oversized input. Add a regression test."
    assert payload["confidence"] == "high"


def test_pending_action_receipt_uses_nested_finding_evidence(tmp_path: Path):
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    arcticbase = FakeArcticBase(subject_path)
    arcticbase.pending_actions.append({
        "id": "pa-1",
        "status": "claimed",
        "required_receipt_type": "manager_review",
    })
    loop = RefallStandingLoop(
        "alpha", coverage=FakeCoverage(), arcticbase=arcticbase,
        dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=0, max_parallel=1, poll_interval_s=0),
    )
    parsed = ParsedOutput(
        findings=[{
            "title": "Reviewed candidate",
            "source_anchors": ["app.py:7"],
            "artifact_refs": ["art_review"],
            "evidence": [{"kind": "source_anchor", "ref": "app.py:7"}],
        }],
        structured=[{
            "source_anchors": ["app.py:7"],
            "artifact_refs": ["art_review"],
        }],
        done="Reviewed the candidate against source and saved analysis.",
    )
    conversation = DispatchedConversation(
        cid="cid-review", subject="alpha", lane="B", task_class="pending_action",
        unit={"id": "pa-1", "required_receipt_type": "manager_review"}, objective="",
    )

    loop._resolve_pending_action(
        conversation,
        PollResult(cid="cid-review", status="finished", response="done"),
        parsed,
    )

    _, _, receipt, receipt_type, _ = arcticbase.resolved_pending[0]
    assert receipt_type == "manager_review"
    assert receipt["evidence_refs"] == ["app.py:7", "art_review"]


def test_finding_persistence_restructures_existing_anchor_when_evidence_is_omitted(tmp_path: Path):
    subject_path = tmp_path / "subjects" / "alpha"
    (subject_path / "PRJ").mkdir(parents=True)
    coverage = FakeCoverage()
    loop = RefallStandingLoop(
        "alpha", coverage=coverage, arcticbase=FakeArcticBase(subject_path),
        dispatcher=FakeDispatcher([]),
        config=StandingLoopConfig(max_cycles=0, max_parallel=1, poll_interval_s=0),
    )
    parsed = ParsedOutput(findings=[{
        "title": "Anchored finding",
        "source_anchors": ["app.py:9"],
        "confidence": "medium",
        "limitations": [],
    }])
    conversation = DispatchedConversation(
        cid="cid-2", subject="alpha", lane="A", task_class="review",
        unit={"id": "unit-2"}, objective="",
    )

    loop._persist_findings(parsed, conversation)

    assert coverage.findings[0][1]["evidence"] == [
        {"kind": "source_anchor", "ref": "app.py:9", "claim": "Anchored finding"}
    ]
