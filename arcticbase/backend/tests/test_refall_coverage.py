from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arctic_base.api.deps import get_storage
from arctic_base.main import app
from arctic_base.storage.filesystem import FilesystemStorage


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    storage = FilesystemStorage(tmp_path / "data")
    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _create_workbench(client: TestClient, slug: str) -> None:
    r = client.post("/api/workbenches", json={"title": slug, "slug": slug, "tags": ["refall"]})
    assert r.status_code == 201, r.text


def test_workbench_coverage_db_is_created_inside_workbench(client: TestClient, tmp_path: Path) -> None:
    _create_workbench(client, "alpha")

    r = client.post(
        "/api/workbenches/alpha/coverage/enumerate",
        json={"files": [{"path": "a.py", "total_lines": 3, "symbols": []}]},
    )

    assert r.status_code == 200, r.text
    assert (tmp_path / "data/workbenches/alpha/refall_coverage.db").is_file()


def test_workbench_coverage_rows_are_isolated(client: TestClient) -> None:
    _create_workbench(client, "alpha")
    _create_workbench(client, "beta")

    client.post(
        "/api/workbenches/alpha/coverage/enumerate",
        json={"files": [{"path": "a.py", "total_lines": 3, "symbols": []}]},
    )
    client.post(
        "/api/workbenches/beta/coverage/enumerate",
        json={"files": [{"path": "b.py", "total_lines": 7, "symbols": []}]},
    )

    alpha = client.get("/api/workbenches/alpha/coverage/stats").json()
    beta = client.get("/api/workbenches/beta/coverage/stats").json()

    assert alpha["lines_total"] == 3
    assert beta["lines_total"] == 7


def test_workbench_coverage_claim_submit_and_search(client: TestClient) -> None:
    _create_workbench(client, "alpha")
    client.post(
        "/api/workbenches/alpha/coverage/enumerate",
        json={
            "files": [
                {
                    "path": "a.py",
                    "total_lines": 5,
                    "symbols": [{"name": "main", "line_start": 2, "line_end": 4}],
                }
            ]
        },
    )

    claim = client.post("/api/workbenches/alpha/coverage/claim", json={"agent": "codex-a"})
    assert claim.status_code == 200, claim.text
    unit = claim.json()
    assert unit["type"] == "symbol"
    assert unit["subject"] == "alpha"

    submit = client.post(
        "/api/workbenches/alpha/coverage/submit",
        json={
            "unit_id": unit["id"],
            "agent": "codex-a",
            "summary": "Reviewed main",
            "evidence": [{"file": "a.py", "line_start": 2, "line_end": 4}],
        },
    )
    assert submit.status_code == 200, submit.text

    stats = client.get("/api/workbenches/alpha/coverage/stats").json()
    assert stats["symbols_total"] == 1
    assert stats["lines_covered"] == 3

    search = client.get("/api/workbenches/alpha/coverage/search?state=characterized").json()
    assert [row["id"] for row in search] == [unit["id"]]


def test_workbench_coverage_plan_and_context(client: TestClient) -> None:
    _create_workbench(client, "alpha")

    plan = client.post(
        "/api/workbenches/alpha/coverage/plan",
        json={"investigations": [{"title": "Auth review", "priority": 10}]},
    )
    assert plan.status_code == 200, plan.text
    assert client.get("/api/workbenches/alpha/coverage/plan").json()["total"] == 1

    context = client.post(
        "/api/workbenches/alpha/coverage/context",
        json={"info_md": "# Alpha\n", "generated_by": "context-agent"},
    )
    assert context.status_code == 200, context.text
    assert context.json()["context_id"].startswith("ctx_")
    fetched_context = client.get("/api/workbenches/alpha/coverage/context").json()
    assert fetched_context["info_md"] == "# Alpha\n"
    assert fetched_context["context_id"] == context.json()["context_id"]


def test_source_inventory_round_trip(client: TestClient) -> None:
    _create_workbench(client, "alpha")
    payload = {
        "subject": "alpha",
        "root": "/subjects/alpha",
        "files": [
            {
                "path": "app.py",
                "sha256": "a" * 64,
                "size_bytes": 10,
                "total_lines": 1,
                "kind": "python",
            }
        ],
        "skipped": [{"path": "locked.log", "reason": "unreadable"}],
        "observations": [{"kind": "symlink", "path": "link"}],
    }

    saved = client.put("/api/workbenches/alpha/coverage/source-inventory", json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["inventory_id"].startswith("inv_")

    fetched = client.get("/api/workbenches/alpha/coverage/source-inventory")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["inventory_id"] == saved.json()["inventory_id"]
    assert fetched.json()["files"][0]["path"] == "app.py"


def test_workbench_coverage_findings_wishlist_and_validation(client: TestClient) -> None:
    _create_workbench(client, "alpha")

    finding = client.post(
        "/api/workbenches/alpha/coverage/findings",
        json={
            "title": "Command injection",
            "description": "Shell metacharacters reach subprocess shell=True.",
            "impact": "Remote command execution as service user.",
            "severity": "HIGH",
            "code_paths": ["source:app.py::run"],
            "source_anchors": ["source:app.py::run"],
            "artifact_refs": ["obj_static_trace"],
            "evidence": [{"kind": "source_anchor", "ref": "source:app.py::run"}],
            "confidence": "medium",
            "limitations": ["Static analysis only."],
            "affected_component": "request handler",
            "likelihood": "medium",
            "reproduction_steps": ["Trace request data into subprocess at app.py::run."],
            "poc": "Candidate metacharacter payload; not executed in static-only scope.",
            "poc_status": "candidate PoC, unverified",
            "poc_refs": ["obj_candidate_payload"],
            "verification_status": "static_only",
            "remediation": "Avoid shell execution and pass an argument vector.",
            "cwe": "CWE-78: OS Command Injection",
            "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            "cvss_score": 9.8,
            "affected_product": "Example Product",
            "affected_versions": ["1.0 (affected)"],
            "references": [],
            "discovery": "Test researcher",
            "created_by": "codex",
            "vuln_class": "command-injection",
        },
    )
    assert finding.status_code == 201, finding.text
    finding_id = finding.json()["id"]
    assert finding.json()["code_paths"] == ["source:app.py::run"]
    assert finding.json()["source_anchors"] == ["source:app.py::run"]
    assert finding.json()["artifact_refs"] == ["obj_static_trace"]
    assert finding.json()["evidence"] == [{"kind": "source_anchor", "ref": "source:app.py::run"}]
    assert finding.json()["confidence"] == "medium"
    assert finding.json()["limitations"] == ["Static analysis only."]
    assert finding.json()["affected_component"] == "request handler"
    assert finding.json()["likelihood"] == "medium"
    assert finding.json()["poc_status"] == "candidate PoC, unverified"
    assert finding.json()["poc_refs"] == ["obj_candidate_payload"]
    assert finding.json()["cwe"] == "CWE-78: OS Command Injection"
    assert finding.json()["cvss_score"] == 9.8
    assert finding.json()["affected_versions"] == ["1.0 (affected)"]

    validation = client.post(
        "/api/workbenches/alpha/coverage/finding-validation",
        json={
            "finding_id": finding_id,
            "agent": "validator",
            "repro_status": "reproduced",
            "patch_status": "not_started",
            "production_viability": "direct",
            "critic_reasoning": "Payload executed in harness.",
        },
    )
    assert validation.status_code == 200, validation.text
    assert validation.json()["status"] == "PROVISIONALLY_VALID"
    assert validation.json()["repro_status"] == "reproduced"

    findings = client.get("/api/workbenches/alpha/coverage/findings?status=PROVISIONALLY_VALID")
    assert findings.status_code == 200, findings.text
    assert [item["title"] for item in findings.json()] == ["Command injection"]
    assert findings.json()[0]["confidence"] == "medium"
    assert findings.json()[0]["evidence"][0]["ref"] == "source:app.py::run"

    summary = client.get("/api/workbenches/alpha/coverage/findings/summary")
    assert summary.status_code == 200, summary.text
    assert summary.json()["by_severity"]["HIGH"] == 1

    wish = client.post(
        "/api/workbenches/alpha/coverage/wishlist",
        json={
            "kind": "tool",
            "item": "rizin",
            "reason": "binary triage",
            "requested_by": "head",
            "status": "provided",
        },
    )
    assert wish.status_code == 201, wish.text
    wishlist = client.get("/api/workbenches/alpha/coverage/wishlist?status=provided")
    assert wishlist.status_code == 200, wishlist.text
    assert wishlist.json()[0]["item"] == "rizin"


def test_workbench_coverage_finding_creation_is_idempotent_by_id(client: TestClient) -> None:
    _create_workbench(client, "alpha")
    body = {
        "id": "find_same",
        "title": "Command injection",
        "severity": "HIGH",
        "code_paths": ["app.py:10"],
        "evidence": [{"kind": "source_anchor", "ref": "app.py:10"}],
        "confidence": "medium",
    }

    first = client.post("/api/workbenches/alpha/coverage/findings", json=body)
    second = client.post(
        "/api/workbenches/alpha/coverage/findings",
        json={
            **body,
            "artifact_refs": ["obj_second_review"],
            "evidence": [
                *body["evidence"],
                {"kind": "runtime_artifact", "artifact_ref": "obj_second_review"},
            ],
            "limitations": ["Dynamic validation remains pending."],
        },
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"] == "find_same"
    assert second.json()["artifact_refs"] == ["obj_second_review"]
    assert second.json()["limitations"] == ["Dynamic validation remains pending."]
    assert len(second.json()["evidence"]) == 2
    assert len(client.get("/api/workbenches/alpha/coverage/findings").json()) == 1


def test_workbench_coverage_finding_accepts_source_anchors_without_code_paths(client: TestClient) -> None:
    _create_workbench(client, "alpha")

    finding = client.post(
        "/api/workbenches/alpha/coverage/findings",
        json={
            "title": "Command injection",
            "severity": "HIGH",
            "source_anchors": ["app.py:10"],
            "evidence": [{"kind": "source_anchor", "ref": "app.py:10"}],
            "confidence": "medium",
        },
    )

    assert finding.status_code == 201, finding.text
    assert finding.json()["code_paths"] == ["app.py:10"]


def test_workbench_coverage_finding_accepts_artifact_refs_without_code_paths(client: TestClient) -> None:
    _create_workbench(client, "alpha")

    finding = client.post(
        "/api/workbenches/alpha/coverage/findings",
        json={
            "title": "Runtime-only finding",
            "severity": "MEDIUM",
            "artifact_refs": ["obj_runtime_trace"],
            "evidence": [{"kind": "runtime_artifact", "ref": "obj_runtime_trace"}],
            "confidence": "medium",
        },
    )

    assert finding.status_code == 201, finding.text
    assert finding.json()["code_paths"] == ["obj_runtime_trace"]


def test_workbench_coverage_attack_patterns_and_class_coverage(client: TestClient) -> None:
    _create_workbench(client, "alpha")

    pattern = client.post(
        "/api/workbenches/alpha/coverage/attack-patterns",
        json={
            "vuln_class": "command-injection",
            "title": "Shell metacharacter flow",
            "description": "Untrusted text reaches a shell command.",
            "sources": ["endpoint:POST /run"],
            "sinks": ["source:app.py::run"],
            "refs": ["artifact:obj_pattern"],
        },
    )
    assert pattern.status_code == 201, pattern.text

    patterns = client.get(
        "/api/workbenches/alpha/coverage/attack-patterns?vuln_class=command-injection"
    )
    assert patterns.status_code == 200, patterns.text
    assert patterns.json()[0]["title"] == "Shell metacharacter flow"

    updated = client.post(
        "/api/workbenches/alpha/coverage/class-coverage",
        json={
            "vuln_class": "command-injection",
            "state": "checked",
            "checked_by": "codex",
            "notes": "Reviewed command execution paths.",
        },
    )
    assert updated.status_code == 200, updated.text
    classes = client.get("/api/workbenches/alpha/coverage/class-coverage")
    assert classes.status_code == 200, classes.text
    assert classes.json()[0]["vuln_class"] == "command-injection"
