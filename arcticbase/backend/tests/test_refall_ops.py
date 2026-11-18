from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient

from arctic_base.api import refall_ops_commands
from arctic_base.api.deps import get_storage
from arctic_base.main import app
from arctic_base.storage.filesystem import FilesystemStorage


@pytest.fixture
def ops_client(tmp_path: Path, monkeypatch) -> TestClient:
    storage = FilesystemStorage(tmp_path / "data")
    monkeypatch.setenv("REFALL_DATA_ROOT", str(tmp_path / "refall"))
    monkeypatch.setenv("REFALL_REPO_ROOT", str(Path(__file__).resolve().parents[3]))
    monkeypatch.setenv("REFALL_ENABLE_LOOP_LAUNCH", "false")
    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_ops_disabled_by_default(ops_client: TestClient, monkeypatch) -> None:
    monkeypatch.delenv("REFALL_ENABLE_OPS", raising=False)

    r = ops_client.get("/api/refall/ops/status")

    assert r.status_code == 404


def test_ops_status_enabled(ops_client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    monkeypatch.setenv("REFALL_ENABLE_OPS_COMMANDS", "false")

    r = ops_client.get("/api/refall/ops/status")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["commands_enabled"] is False
    assert body["deployment_mode"] == "local-dev"
    assert body["loop_launch_enabled"] is False
    assert body["loop"]["max_parallel"] == 4


def test_ops_command_requires_separate_enable(ops_client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    monkeypatch.setenv("REFALL_ENABLE_OPS_COMMANDS", "false")

    r = ops_client.post("/api/refall/ops/command", json={"command": "status"})

    assert r.status_code == 403


def test_ops_command_rejects_unknown_or_disallowed_commands(
    ops_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    monkeypatch.setenv("REFALL_ENABLE_OPS_COMMANDS", "true")
    monkeypatch.setenv("REFALL_OPS_ALLOWED_COMMANDS", "status")

    unknown = ops_client.post("/api/refall/ops/command", json={"command": "shell whoami"})
    disallowed = ops_client.post("/api/refall/ops/command", json={"command": "subjects"})

    assert unknown.status_code == 422
    assert disallowed.status_code == 403


def test_ops_command_status_is_audited(ops_client: TestClient, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    monkeypatch.setenv("REFALL_ENABLE_OPS_COMMANDS", "true")
    monkeypatch.setenv("REFALL_OPS_ALLOWED_COMMANDS", "status")

    r = ops_client.post("/api/refall/ops/command", json={"command": "status"})

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"
    audit = tmp_path / "data/refall_ops_audit.jsonl"
    assert audit.is_file()
    assert "status" in audit.read_text(encoding="utf-8")


def test_ops_infra_is_provider_neutral(ops_client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")

    r = ops_client.get("/api/refall/ops/infra")

    assert r.status_code == 200, r.text
    checks = {check["id"]: check for check in r.json()["checks"]}
    assert checks["colima"]["status"] in {"available", "unsupported"}
    assert checks["tmux"]["status"] in {"available", "unsupported"}


def test_ops_debug_surfaces_workbench_ledger_coverage_and_audit(
    ops_client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    ops_client.post("/api/workbenches", json={"title": "Alpha", "slug": "alpha", "tags": ["refall"]})
    ops_client.post(
        "/api/workbenches/alpha/coverage/context",
        json={"info_md": "# Alpha context\n", "generated_by": "test"},
    )
    ops_client.post(
        "/api/workbenches/alpha/ledger/entries",
        json={"kind": "ops-event", "action": "loop.start", "summary": "started"},
    )
    audit = tmp_path / "data/refall_ops_audit.jsonl"
    audit.write_text('{"command":"status","status":"accepted"}\n', encoding="utf-8")

    r = ops_client.get("/api/refall/ops/debug/alpha")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["subject"] == "alpha"
    assert body["workbench"]["slug"] == "alpha"
    assert body["coverage_context"]["info_md"] == "# Alpha context\n"
    assert body["ledger_stats"]["total"] == 1
    assert body["events"][0]["action"] == "loop.start"
    assert body["audit_tail"][0]["command"] == "status"


def test_ops_debug_conversation_reads_refall_agent_event_timeline(
    ops_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    created = ops_client.post("/api/refall/subjects", json={"subject": "conv"}).json()
    events = Path(created["subject_path"]) / "refallsubloop/logs/agents/source-review-cid123/events"
    events.mkdir(parents=True)
    (events / "0001.json").write_text(
        '{"kind":"MessageEvent","timestamp":"2026-07-24T00:00:00Z","source":"agent","content":"started"}\n',
        encoding="utf-8",
    )
    (events / "0002.json").write_text(
        '{"kind":"ACPToolCallEvent","timestamp":"2026-07-24T00:00:01Z","title":"Read file","tool_kind":"read","status":"complete","raw_output":"line 1\\nline 2"}\n',
        encoding="utf-8",
    )

    r = ops_client.get("/api/refall/ops/debug/conv/conversation/cid123")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["conversation_id"] == "cid123"
    assert body["total_events"] == 2
    assert body["events"][0]["kind"] == "message"
    assert body["events"][1]["kind"] == "tool_call"
    assert body["events"][1]["output_lines"] == 2


def test_ops_debug_live_reports_active_refall_conversations_from_event_log(
    ops_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    created = ops_client.post("/api/refall/subjects", json={"subject": "live"}).json()
    events_dir = Path(created["subject_path"]) / "refallsubloop/logs/events"
    events_dir.mkdir(parents=True, exist_ok=True)
    (events_dir / "events.jsonl").write_text(
        "\n".join([
            '{"type":"agent_start","cid":"cid-old","phase":"source-review"}',
            '{"type":"agent_complete","cid":"cid-old","phase":"source-review"}',
            '{"type":"agent_start","cid":"cid-live","phase":"dynamic-validation"}',
        ])
        + "\n",
        encoding="utf-8",
    )
    agent_events = Path(created["subject_path"]) / "refallsubloop/logs/agents/dynamic-validation-cid-live/events"
    agent_events.mkdir(parents=True)
    (agent_events / "0001.json").write_text(
        '{"kind":"ACPToolCallEvent","title":"curl target","status":"running","raw_output":"HTTP/1.1 200 OK"}\n',
        encoding="utf-8",
    )

    r = ops_client.get("/api/refall/ops/debug/live/live")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["live"] is True
    assert body["active"][0]["cid"] == "cid-live"
    assert body["active"][0]["phase"] == "dynamic-validation"
    assert body["active"][0]["recent_events"][0]["title"] == "curl target"


def test_ops_debug_live_prefers_loop_state_over_stale_event_log(
    ops_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    created = ops_client.post("/api/refall/subjects", json={"subject": "live-state"}).json()
    subject_path = Path(created["subject_path"])
    state_dir = subject_path / ".refall"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "loop_state.json").write_text(
        """
        {
          "status": "running",
          "active": [{
            "cid": "cid-state",
            "lane": "A",
            "task_class": "characterize",
            "unit": {"id": "unit-1", "path": "app.py"}
          }]
        }
        """,
        encoding="utf-8",
    )
    events_dir = subject_path / "refallsubloop/logs/events"
    events_dir.mkdir(parents=True, exist_ok=True)
    (events_dir / "events.jsonl").write_text(
        '{"type":"agent_start","cid":"cid-stale","phase":"characterize"}\n',
        encoding="utf-8",
    )

    r = ops_client.get("/api/refall/ops/debug/live-state/live")

    assert r.status_code == 200, r.text
    body = r.json()
    assert [item["cid"] for item in body["active"]] == ["cid-state"]
    assert body["active"][0]["phase"] == "characterize"


def test_ops_agents_reports_active_standing_loop_state(
    ops_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    created = ops_client.post("/api/refall/subjects", json={"subject": "agents"})
    assert created.status_code == 201, created.text
    state_dir = Path(created.json()["subject_path"]) / ".refall"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "loop_state.json").write_text(
        """
        {
          "status": "running",
          "iteration": 7,
          "active": [{
            "cid": "cid-state",
            "subject": "agents",
            "lane": "source-review",
            "task_class": "characterize",
            "unit": {"id": "unit-1", "path": "app.py"}
          }]
        }
        """,
        encoding="utf-8",
    )

    r = ops_client.get("/api/refall/ops/agents")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["active"][0]["cid"] == "cid-state"
    assert body["active"][0]["workbench"] == "agents"
    assert body["active"][0]["unit_id"] == "unit-1"


def test_ops_agents_prefers_loop_state_over_stale_event_log(
    ops_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    created = ops_client.post("/api/refall/subjects", json={"subject": "agents-state"})
    assert created.status_code == 201, created.text
    subject_path = Path(created.json()["subject_path"])
    state_dir = subject_path / ".refall"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "loop_state.json").write_text(
        """
        {
          "status": "running",
          "iteration": 8,
          "active": [{
            "cid": "cid-state",
            "subject": "agents-state",
            "lane": "A",
            "task_class": "characterize",
            "unit": {"id": "unit-1", "path": "app.py"}
          }]
        }
        """,
        encoding="utf-8",
    )
    events_dir = subject_path / "refallsubloop/logs/events"
    events_dir.mkdir(parents=True, exist_ok=True)
    (events_dir / "events.jsonl").write_text(
        "\n".join([
            '{"type":"agent_start","cid":"cid-stale-1","phase":"characterize"}',
            '{"type":"agent_start","cid":"cid-stale-2","phase":"characterize"}',
        ])
        + "\n",
        encoding="utf-8",
    )

    r = ops_client.get("/api/refall/ops/agents")

    assert r.status_code == 200, r.text
    assert [item["cid"] for item in r.json()["active"]] == ["cid-state"]


def test_ops_command_lifecycle_commands_mutate_workbench_state(
    ops_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    monkeypatch.setenv("REFALL_ENABLE_OPS_COMMANDS", "true")
    monkeypatch.setenv("REFALL_OPS_ALLOWED_COMMANDS", "start,update,closeout,coverage")
    created = ops_client.post("/api/refall/subjects", json={"subject": "gamma"})
    assert created.status_code == 201, created.text
    saved = ops_client.post(
        "/api/refall/ops/context/save",
        json={"slug": "gamma", "context": "# Gamma briefing\n\nRead before dispatch.\n"},
    )
    assert saved.status_code == 200, saved.text

    started = ops_client.post("/api/refall/ops/command", json={"command": "start gamma"})
    updated = ops_client.post("/api/refall/ops/command", json={"command": "update gamma"})
    closed = ops_client.post("/api/refall/ops/command", json={"command": "closeout gamma"})
    coverage = ops_client.post("/api/refall/ops/command", json={"command": "coverage gamma"})

    assert started.status_code == 200, started.text
    assert updated.status_code == 200, updated.text
    assert closed.status_code == 200, closed.text
    assert coverage.status_code == 200, coverage.text
    assert started.json()["status"] == "started"
    assert started.json()["loop"]["status"] == "disabled"
    assert updated.json()["status"] == "updated"
    assert updated.json()["loop"]["status"] == "disabled"
    assert closed.json()["status"] == "closed"
    assert closed.json()["report"]["object_id"]
    assert coverage.json()["coverage"]["subject"] == "gamma"
    context = ops_client.get("/api/workbenches/gamma/coverage/context").json()
    assert context["info_md"] == "# Gamma briefing\n\nRead before dispatch.\n"
    entries = ops_client.get("/api/workbenches/gamma/ledger/entries?kind=ops-event").json()
    assert [entry["action"] for entry in entries if entry["action"].startswith("loop.")] == [
        "loop.start",
        "loop.update",
        "loop.closeout",
    ]


def test_ops_command_threat_model_requests_optional_cycle(
    ops_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    monkeypatch.setenv("REFALL_ENABLE_OPS_COMMANDS", "true")
    monkeypatch.setenv("REFALL_OPS_ALLOWED_COMMANDS", "threat-model")
    created = ops_client.post("/api/refall/subjects", json={"subject": "theta"})
    assert created.status_code == 201, created.text

    requested = ops_client.post("/api/refall/ops/command", json={"command": "threat-model theta"})

    assert requested.status_code == 200, requested.text
    body = requested.json()
    assert body["status"] == "requested"
    assert body["command"] == "threat-model"
    assert body["scope_overlay"]["threat_model_requested"] is True
    assert body["pending_action"]["kind"] == "threat_model_request"
    assert body["pending_action"]["required_receipt_type"] == "threat_model"
    scope = ops_client.get("/api/workbenches/theta/coverage/scope-overlay").json()
    assert scope["threat_model_requested"] is True
    entries = ops_client.get("/api/workbenches/theta/ledger/entries?kind=ops-event").json()
    assert any(entry.get("action") == "threat-model.request" for entry in entries)


def test_ops_command_doctor_and_estimate_report_readiness(
    ops_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    monkeypatch.setenv("REFALL_ENABLE_OPS_COMMANDS", "true")
    monkeypatch.setenv("REFALL_OPS_ALLOWED_COMMANDS", "doctor,estimate")
    monkeypatch.setenv("REFALL_CODEX_COMMAND", "python3")
    created = ops_client.post("/api/refall/subjects", json={"subject": "estimate-ready"})
    assert created.status_code == 201, created.text
    enumerated = ops_client.post(
        "/api/workbenches/estimate-ready/coverage/enumerate",
        json={
            "files": [{
                "path": "app.py",
                "total_lines": 25,
                "symbols": [{"name": "handler", "line_start": 1, "line_end": 25}],
            }],
        },
    )
    assert enumerated.status_code == 200, enumerated.text

    doctor = ops_client.post("/api/refall/ops/command", json={"command": "doctor estimate-ready"})
    estimate = ops_client.post("/api/refall/ops/command", json={"command": "estimate estimate-ready"})

    assert doctor.status_code == 200, doctor.text
    assert doctor.json()["command"] == "doctor"
    assert any(check["id"] == "provider.codex" for check in doctor.json()["doctor"]["checks"])
    assert estimate.status_code == 200, estimate.text
    assert estimate.json()["command"] == "estimate"
    assert estimate.json()["estimate"]["subject"] == "estimate-ready"
    assert estimate.json()["estimate"]["estimated_open_units"] >= 1


def test_ops_command_estimate_does_not_emit_extra_doctor_event(
    ops_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    monkeypatch.setenv("REFALL_ENABLE_OPS_COMMANDS", "true")
    monkeypatch.setenv("REFALL_OPS_ALLOWED_COMMANDS", "estimate")
    created = ops_client.post("/api/refall/subjects", json={"subject": "estimate-only"})
    assert created.status_code == 201, created.text

    estimate = ops_client.post("/api/refall/ops/command", json={"command": "estimate estimate-only"})

    assert estimate.status_code == 200, estimate.text
    assert estimate.json()["estimate"]["doctor"]["checks"]
    entries = ops_client.get("/api/workbenches/estimate-only/ledger/entries?kind=ops-event").json()
    actions = [entry.get("action") for entry in entries]
    assert "estimate.run" in actions
    assert "doctor.run" not in actions


def test_ops_closeout_blocks_when_closeout_gate_fails(
    ops_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    monkeypatch.setenv("REFALL_ENABLE_OPS_COMMANDS", "true")
    monkeypatch.setenv("REFALL_OPS_ALLOWED_COMMANDS", "closeout")
    created = ops_client.post("/api/refall/subjects", json={"subject": "blocked"})
    assert created.status_code == 201, created.text
    saved = ops_client.post(
        "/api/refall/ops/context/save",
        json={"slug": "blocked", "context": "# Blocked briefing\n"},
    )
    assert saved.status_code == 200, saved.text
    pending = ops_client.post(
        "/api/workbenches/blocked/pending-actions",
        json={"kind": "operator_decision_needed", "title": "Need scope decision"},
    )
    assert pending.status_code == 201, pending.text

    closed = ops_client.post("/api/refall/ops/command", json={"command": "closeout blocked"})

    assert closed.status_code == 200, closed.text
    body = closed.json()
    assert body["status"] == "blocked"
    assert body["report"]["object_id"]
    assert body["closeout_gate"]["passed"] is False
    entries = ops_client.get("/api/workbenches/blocked/ledger/entries?kind=ops-event").json()
    assert any(entry.get("action") == "loop.closeout.blocked" for entry in entries)
    current = ops_client.get("/api/workbenches/blocked/refall-report")
    assert current.status_code == 200, current.text


def test_ops_start_and_update_launch_standing_loop_when_enabled(
    ops_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    monkeypatch.setenv("REFALL_ENABLE_OPS_COMMANDS", "true")
    monkeypatch.setenv("REFALL_ENABLE_LOOP_LAUNCH", "true")
    monkeypatch.setenv("REFALL_ENABLE_LOOP_SUPERVISOR_CRON", "false")
    monkeypatch.setenv("REFALL_OPS_ALLOWED_COMMANDS", "start,update")
    calls = []
    supervisor_calls = []

    class FakePopen:
        def __init__(self, argv, **kwargs):
            calls.append((argv, kwargs))
            self.pid = 4242 + len(calls)

    monkeypatch.setattr(refall_ops_commands.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(
        refall_ops_commands,
        "_sync_agent_canvas_workspace",
        lambda **kwargs: {"status": "already-synced"},
    )
    monkeypatch.setattr(refall_ops_commands, "_assert_openhands_api_ready", lambda settings: None)
    monkeypatch.setattr(
        refall_ops_commands,
        "_install_loop_supervisor",
        lambda **kwargs: supervisor_calls.append(kwargs) or {"installed": True},
    )
    created = ops_client.post("/api/refall/subjects", json={"subject": "lambda"})
    assert created.status_code == 201, created.text
    saved = ops_client.post(
        "/api/refall/ops/context/save",
        json={"slug": "lambda", "context": "# Lambda briefing\n"},
    )
    assert saved.status_code == 200, saved.text
    granted = ops_client.post(
        "/api/workbenches/lambda/capabilities/grant",
        json={
            "class": "run_local_command",
            "scope": {"paths": [created.json()["subject_path"]]},
            "granted_by": "operator",
            "reason": "Allow REFALL standing loop process launch for this subject.",
        },
    )
    assert granted.status_code == 201, granted.text

    started = ops_client.post("/api/refall/ops/command", json={"command": "start lambda"})
    updated = ops_client.post("/api/refall/ops/command", json={"command": "update lambda"})

    assert started.status_code == 200, started.text
    assert updated.status_code == 200, updated.text
    assert started.json()["loop"]["status"] == "launched"
    assert started.json()["loop"]["pid"] == 4243
    assert updated.json()["loop"]["max_cycles"] == 1
    assert len(calls) == 2
    assert calls[0][0][1:3] == ["-m", "ref_all_executor.standing_loop"]
    assert calls[0][0][-2:] == ["--max-cycles", "0"]
    assert calls[1][0][-2:] == ["--max-cycles", "1"]
    assert calls[0][1]["start_new_session"] is True
    assert started.json()["loop"]["supervisor"] == {
        "installed": False,
        "disabled": True,
        "reason": "REFALL_ENABLE_LOOP_SUPERVISOR_CRON=false",
    }
    assert supervisor_calls == []


def test_ops_start_requires_process_capability_when_launch_enabled(
    ops_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    monkeypatch.setenv("REFALL_ENABLE_OPS_COMMANDS", "true")
    monkeypatch.setenv("REFALL_ENABLE_LOOP_LAUNCH", "true")
    monkeypatch.setenv("REFALL_OPS_ALLOWED_COMMANDS", "start")
    calls = []

    class FakePopen:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))
            self.pid = 1

    monkeypatch.setattr(refall_ops_commands.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(
        refall_ops_commands,
        "_sync_agent_canvas_workspace",
        lambda **kwargs: {"status": "already-synced"},
    )
    monkeypatch.setattr(refall_ops_commands, "_assert_openhands_api_ready", lambda settings: None)
    created = ops_client.post("/api/refall/subjects", json={"subject": "requires-cap"})
    assert created.status_code == 201, created.text
    saved = ops_client.post(
        "/api/refall/ops/context/save",
        json={"slug": "requires-cap", "context": "# Requires capability\n"},
    )
    assert saved.status_code == 200, saved.text

    started = ops_client.post("/api/refall/ops/command", json={"command": "start requires-cap"})

    assert started.status_code == 403
    assert "run_local_command capability refused" in started.text
    assert calls == []
    decisions = ops_client.get("/api/workbenches/requires-cap/ledger/entries?kind=capability-decision").json()
    assert decisions[0]["status"] == "refused"


def test_ops_command_start_requires_context(
    ops_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    monkeypatch.setenv("REFALL_ENABLE_OPS_COMMANDS", "true")
    monkeypatch.setenv("REFALL_OPS_ALLOWED_COMMANDS", "start")
    created = ops_client.post("/api/refall/subjects", json={"subject": "gamma"})
    assert created.status_code == 201, created.text

    started = ops_client.post("/api/refall/ops/command", json={"command": "start gamma"})

    assert started.status_code == 409
    assert "Generate Context" in started.text


def test_ops_command_logs_returns_audit_tail_and_workbench_logs(
    ops_client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    monkeypatch.setenv("REFALL_ENABLE_OPS_COMMANDS", "true")
    monkeypatch.setenv("REFALL_OPS_ALLOWED_COMMANDS", "logs")
    ops_client.post("/api/workbenches", json={"title": "Delta", "slug": "delta", "tags": ["refall"]})
    log_dir = tmp_path / "data/workbenches/delta/refall/logs"
    log_dir.mkdir(parents=True)
    (log_dir / "loop.log").write_text("line 1\nline 2\n", encoding="utf-8")
    audit = tmp_path / "data/refall_ops_audit.jsonl"
    audit.write_text('{"command":"status","status":"accepted"}\n', encoding="utf-8")

    r = ops_client.post("/api/refall/ops/command", json={"command": "logs delta"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["logs"][0]["path"] == "refall/logs/loop.log"
    assert body["logs"][0]["tail"] == ["line 1", "line 2"]
    assert body["audit_tail"][0]["command"] == "status"


def test_ops_context_generate_endpoint_creates_visible_context_artifacts(
    ops_client: TestClient,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    monkeypatch.setenv("REFALL_ENABLE_OPS_COMMANDS", "true")
    monkeypatch.setenv("REFALL_OPS_ALLOWED_COMMANDS", "context")
    monkeypatch.setenv("REFALL_HEAD_PROVIDER", "codex")
    source = tmp_path / "projects" / "epsilon"
    source.mkdir(parents=True)
    (source / "README.md").write_text("# Epsilon\n", encoding="utf-8")
    calls = []

    monkeypatch.setattr(refall_ops_commands.shutil, "which", lambda name: f"/bin/{name}")

    def fake_run(cmd, *, input, text, capture_output, timeout, cwd):
        calls.append({
            "cmd": cmd,
            "input": input,
            "text": text,
            "capture_output": capture_output,
            "timeout": timeout,
            "cwd": cwd,
        })
        return subprocess.CompletedProcess(
            cmd,
            0,
            "## Manager Brief\n- Actual source was read.\n- Risky area: app.py handler.\n",
            "",
        )

    monkeypatch.setattr(refall_ops_commands.subprocess, "run", fake_run)
    ops_client.post(
        "/api/refall/subjects",
        json={"subject": "epsilon", "source_path": str(source)},
    )
    ops_client.post(
        "/api/workbenches/epsilon/objects",
        json={
            "kind": "md",
            "title": "Operator Notes",
            "filename": "notes.md",
            "mime": "text/markdown",
            "content": "# Notes\nNeed auth review.\n",
        },
    )
    ops_client.post(
        "/api/workbenches/epsilon/coverage/enumerate",
        json={
            "files": [{
                "path": "app.py",
                "total_lines": 8,
                "symbols": [{"name": "handler", "line_start": 1, "line_end": 8}],
            }],
        },
    )
    inventory = ops_client.put(
        "/api/workbenches/epsilon/coverage/source-inventory",
        json={
            "root": str(source),
            "files": [{
                "path": "app.py",
                "sha256": "a" * 64,
                "size_bytes": 80,
                "total_lines": 8,
                "kind": "python",
            }],
        },
    )
    assert inventory.status_code == 200, inventory.text
    scope = ops_client.put(
        "/api/workbenches/epsilon/coverage/scope-overlay",
        json={
            "local_roots": [str(source)],
            "lan_targets": [{"host": "192.0.2.10", "ports": [80, 81]}],
            "external_targets": [],
            "operator_notes": "No external testing.",
        },
    )
    assert scope.status_code == 200, scope.text

    r = ops_client.post(
        "/api/refall/ops/context/generate",
        json={"slug": "epsilon", "operator_input": "Prioritize authentication and authorization."},
    )

    assert r.status_code == 200, r.text
    assert calls
    assert calls[0]["cmd"][:2] == ["codex", "exec"]
    assert "--ask-for-approval" not in calls[0]["cmd"]
    assert "-c" in calls[0]["cmd"]
    assert "approval_policy=\"never\"" in calls[0]["cmd"]
    assert calls[0]["cwd"] == str(source)
    assert "REFALL context.md briefing generation" in calls[0]["input"]
    assert "Prioritize authentication and authorization." in calls[0]["input"]
    assert "README.md" in calls[0]["input"]
    assert "# Epsilon" in calls[0]["input"]
    assert "Need auth review." in calls[0]["input"]
    assert "Source Inventory Metadata" in calls[0]["input"]
    assert inventory.json()["inventory_id"] in calls[0]["input"]
    assert "Scope Overlay" in calls[0]["input"]
    assert "No external testing." in calls[0]["input"]
    assert "manager context" not in calls[0]["input"].lower()
    body = r.json()
    assert body["status"] == "ok"
    assert body["provider"] == "codex"
    assert body["context"]["subject"] == "epsilon"
    assert "Actual source was read" in body["context"]["info_md"]
    fetched = ops_client.get("/api/workbenches/epsilon/coverage/context").json()
    assert fetched["generated_by"] == "refall-context-writer-codex"
    objects = ops_client.get("/api/workbenches/epsilon/objects").json()
    context_objects = [
        obj for obj in objects
        if obj["title"] == "Context" and obj["filename"] == "context.md"
    ]
    assert len(context_objects) == 1
    content = ops_client.get(
        f"/api/workbenches/epsilon/objects/{context_objects[0]['id']}/content",
    )
    assert "Actual source was read" in content.text
    subject_path = Path(ops_client.get("/api/workbenches/epsilon").json()["custom_fields"]["refall_subject_path"])
    assert "Actual source was read" in (subject_path / "context.md").read_text(encoding="utf-8")


def test_ops_context_save_endpoint_updates_visible_context_artifacts(
    ops_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    monkeypatch.setenv("REFALL_ENABLE_OPS_COMMANDS", "true")
    created = ops_client.post("/api/refall/subjects", json={"subject": "iota"})
    assert created.status_code == 201, created.text

    first = ops_client.post(
        "/api/refall/ops/context/save",
        json={"slug": "iota", "context": "# Iota briefing\n"},
    )
    second = ops_client.post(
        "/api/refall/ops/context/save",
        json={"slug": "iota", "context": "# Iota briefing v2\n"},
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["context"]["generated_by"] == "operator"
    assert second.json()["context"]["info_md"] == "# Iota briefing v2\n"
    objects = ops_client.get("/api/workbenches/iota/objects").json()
    context_objects = [
        obj for obj in objects
        if obj["title"] == "Context" and obj["filename"] == "context.md"
    ]
    assert len(context_objects) == 1
    content = ops_client.get(
        f"/api/workbenches/iota/objects/{context_objects[0]['id']}/content",
    )
    assert content.text == "# Iota briefing v2\n"


def test_ops_command_context_fails_when_subject_source_is_not_mounted(
    ops_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    monkeypatch.setenv("REFALL_ENABLE_OPS_COMMANDS", "true")
    monkeypatch.setenv("REFALL_OPS_ALLOWED_COMMANDS", "context")
    ops_client.post(
        "/api/refall/subjects",
        json={"subject": "zeta", "source_path": "/definitely/not/mounted/zeta"},
    )

    r = ops_client.post("/api/refall/ops/command", json={"command": "context zeta"})

    assert r.status_code == 409
    assert "not available to the context generator" in r.text


def test_ops_command_context_requires_recorded_source_or_populated_prj(
    ops_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    monkeypatch.setenv("REFALL_ENABLE_OPS_COMMANDS", "true")
    monkeypatch.setenv("REFALL_OPS_ALLOWED_COMMANDS", "context")
    ops_client.post("/api/refall/subjects", json={"subject": "eta"})

    r = ops_client.post("/api/refall/ops/command", json={"command": "context eta"})

    assert r.status_code == 409
    assert "source path is not recorded" in r.text


def test_ops_command_context_can_use_populated_subject_prj(
    ops_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REFALL_ENABLE_OPS", "true")
    monkeypatch.setenv("REFALL_ENABLE_OPS_COMMANDS", "true")
    monkeypatch.setenv("REFALL_OPS_ALLOWED_COMMANDS", "context")
    monkeypatch.setattr(refall_ops_commands.shutil, "which", lambda name: f"/bin/{name}")
    calls = []

    def fake_run(cmd, *, input, text, capture_output, timeout, cwd):
        calls.append(cwd)
        return subprocess.CompletedProcess(cmd, 0, "# PRJ context\n", "")

    monkeypatch.setattr(refall_ops_commands.subprocess, "run", fake_run)
    created = ops_client.post("/api/refall/subjects", json={"subject": "theta"}).json()
    prj = Path(created["subject_path"]) / "PRJ"
    (prj / "main.py").write_text("print('theta')\n", encoding="utf-8")

    r = ops_client.post("/api/refall/ops/command", json={"command": "context theta"})

    assert r.status_code == 200, r.text
    assert calls == [str(prj.resolve())]
    assert r.json()["context"]["root_container"] == str(prj.resolve())
