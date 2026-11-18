import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arctic_base.api.deps import get_storage
from arctic_base.main import app
from arctic_base.refall.artifact_store import save_artifact
from arctic_base.refall.runtime_state import append_event, connect_runtime
from arctic_base.storage.filesystem import FilesystemStorage


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    storage = FilesystemStorage(tmp_path / "data")
    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _create_workbench(client: TestClient, slug: str = "alpha") -> None:
    r = client.post("/api/workbenches", json={"title": slug, "slug": slug, "tags": ["refall"]})
    assert r.status_code == 201, r.text


def _set_context_and_current_report(client: TestClient, slug: str = "alpha") -> dict:
    context = client.post(f"/api/workbenches/{slug}/coverage/context", json={"info_md": f"# {slug}\n"})
    assert context.status_code == 200, context.text
    report = client.post(
        f"/api/workbenches/{slug}/objects",
        json={
            "kind": "html",
            "title": "Current report",
            "filename": "refall-report.html",
            "mime": "text/html",
            "drawer": "Report",
            "content": "<html>current</html>",
        },
    )
    assert report.status_code == 201, report.text
    patched = client.patch(
        f"/api/workbenches/{slug}",
        json={"custom_fields": {"refall_current_report_object_id": report.json()["id"]}},
    )
    assert patched.status_code == 200, patched.text
    return report.json()


def test_closeout_blocks_unreceipted_false_positive(client: TestClient, tmp_path: Path) -> None:
    _create_workbench(client)
    finding = client.post(
        "/api/workbenches/alpha/coverage/findings",
            json={
                "title": "Suppressed bug",
                "severity": "HIGH",
                "code_paths": ["app.py:10"],
                "evidence": [{"kind": "source_anchor", "ref": "app.py:10"}],
                "confidence": "medium",
            },
        ).json()
    db_path = tmp_path / "data/workbenches/alpha/refall_coverage.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE findings SET status='FALSE_POSITIVE' WHERE id=?", (finding["id"],))

    gate = client.get("/api/workbenches/alpha/closeout/gate").json()

    assert gate["passed"] is False
    assert any(check["id"] == "false-positive-without-receipt" for check in gate["checks"])


def test_closeout_override_requires_receipt(client: TestClient) -> None:
    _create_workbench(client)
    client.post("/api/workbenches/alpha/pending-actions", json={"kind": "operator_decision_needed", "title": "Scope"})

    missing = client.post(
        "/api/workbenches/alpha/closeout/override",
        json={"operator": "nigel", "reason": "Ship anyway", "check_ids": ["pending-actions-open"]},
    )
    assert missing.status_code == 422

    accepted = client.post(
        "/api/workbenches/alpha/closeout/override",
        json={
            "operator": "nigel",
            "reason": "Explicit test-scope decision.",
            "check_ids": ["pending-actions-open"],
            "receipt": {"evidence_refs": ["led_scope"], "reason": "Allowed deferral"},
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    entries = client.get("/api/workbenches/alpha/ledger/entries?kind=ops-event").json()
    assert any(entry.get("action") == "closeout.override" for entry in entries)


def test_closeout_override_marks_matching_blocker_nonblocking(client: TestClient) -> None:
    _create_workbench(client)
    client.post("/api/workbenches/alpha/pending-actions", json={"kind": "operator_decision_needed", "title": "Scope"})
    override = client.post(
        "/api/workbenches/alpha/closeout/override",
        json={
            "operator": "nigel",
            "reason": "Explicitly accepted residual scope item.",
            "check_ids": ["pending-actions-open"],
            "receipt": {"evidence_refs": ["led_scope"], "reason": "Operator accepted deferral"},
        },
    )
    assert override.status_code == 200, override.text
    _set_context_and_current_report(client)

    gate = client.get("/api/workbenches/alpha/closeout/gate").json()

    pending_check = next(check for check in gate["checks"] if check["id"] == "pending-actions-open")
    assert pending_check["status"] == "warn"
    assert pending_check["blocking"] is False
    assert pending_check["overridden"] is True
    assert gate["passed"] is True


def test_closeout_gate_marks_current_report_stale(client: TestClient) -> None:
    _create_workbench(client)
    report = client.post(
        "/api/workbenches/alpha/objects",
        json={
            "kind": "html",
            "title": "Old report",
            "filename": "refall-report.html",
            "mime": "text/html",
            "drawer": "Report",
            "content": "<html>old</html>",
        },
    ).json()
    client.patch(
        "/api/workbenches/alpha",
        json={"custom_fields": {"refall_current_report_object_id": report["id"]}},
    )
    client.post("/api/workbenches/alpha/ledger/entries", json={"kind": "fact", "title": "newer fact"})

    gate = client.get("/api/workbenches/alpha/closeout/gate").json()

    assert any(check["id"] == "report-stale" and check["status"] == "fail" for check in gate["checks"])


def test_coverage_below_threshold_is_warning_not_blocker(client: TestClient) -> None:
    _create_workbench(client)
    client.post(
        "/api/workbenches/alpha/coverage/enumerate",
        json={"files": [{"path": "a.py", "total_lines": 10, "symbols": []}]},
    )

    gate = client.get("/api/workbenches/alpha/closeout/gate").json()

    assert any(check["id"] == "coverage-threshold" and check["status"] == "warn" for check in gate["checks"])


def test_closeout_warns_when_recommended_toolchain_has_not_run(client: TestClient) -> None:
    _create_workbench(client)
    client.post(
        "/api/workbenches/alpha/coverage/findings",
            json={
                "title": "High impact path needs visual/tool support",
                "severity": "HIGH",
                "code_paths": ["app.py:10"],
                "evidence": [{"kind": "source_anchor", "ref": "app.py:10"}],
                "confidence": "medium",
            },
        )

    gate = client.get("/api/workbenches/alpha/closeout/gate").json()

    assert any(check["id"] == "codebadger-toolchain-not-run" and check["status"] == "warn" for check in gate["checks"])


def test_closeout_tracks_vendor_report_generation(client: TestClient) -> None:
    _create_workbench(client)

    missing = client.get("/api/workbenches/alpha/closeout/gate").json()
    assert any(check["id"] == "vendor-cna-report-generated" and check["status"] == "warn" for check in missing["checks"])

    report = client.post(
        "/api/workbenches/alpha/objects",
        json={
            "kind": "html",
            "title": "Vendor CNA report",
            "filename": "vendor-cna-report.html",
            "mime": "text/html",
            "drawer": "Report",
            "content": "<html>vendor</html>",
        },
    )
    assert report.status_code == 201, report.text
    client.post(
        "/api/workbenches/alpha/ledger/entries",
        json={
            "kind": "ops-event",
            "action": "report.vendor_cna.generated",
            "title": "Vendor/CNA report generated",
            "artifact_refs": [report.json()["id"]],
        },
    )

    present = client.get("/api/workbenches/alpha/closeout/gate").json()
    assert any(check["id"] == "vendor-cna-report-generated" and check["status"] == "pass" for check in present["checks"])


def test_closeout_warns_when_external_validation_is_scope_blocked(client: TestClient) -> None:
    _create_workbench(client)
    client.post(
        "/api/workbenches/alpha/ledger/entries",
        json={
            "kind": "runtime-event",
            "action": "validation.scope_blocked",
            "title": "External validation blocked",
            "status": "scope_blocked",
            "summary": "No signed permit for internet validation.",
        },
    )

    gate = client.get("/api/workbenches/alpha/closeout/gate").json()

    assert any(check["id"] == "external-validation-scope-blocked" and check["status"] == "warn" for check in gate["checks"])


def test_closeout_includes_runtime_and_artifact_informational_checks(client: TestClient, tmp_path: Path) -> None:
    _create_workbench(client)
    subject_path = tmp_path / "subject-alpha"
    conn = connect_runtime(subject_path)
    append_event(conn, subject="alpha", event_type="worker_session_finished", payload={"status": "finished"})
    save_artifact(conn, subject_path, subject="alpha", kind="codebadger_graph", content="graph")
    client.patch(
        "/api/workbenches/alpha",
        json={"custom_fields": {"refall_subject_path": str(subject_path)}},
    )

    gate = client.get("/api/workbenches/alpha/closeout/gate").json()

    artifacts = next(check for check in gate["checks"] if check["id"] == "artifacts-by-type")
    sessions = next(check for check in gate["checks"] if check["id"] == "runtime-sessions")
    assert artifacts["status"] == "info"
    assert artifacts["details"] == [{"codebadger_graph": 1}]
    assert sessions["status"] == "info"
    assert sessions["details"] == [{"worker_session_finished": 1}]


def test_closeout_warns_on_resume_drift_decision(client: TestClient) -> None:
    _create_workbench(client)
    pending = client.post(
        "/api/workbenches/alpha/pending-actions",
        json={
            "kind": "resume_drift_decision",
            "title": "Review changed resume inputs",
            "required_receipt_type": "manager_review",
        },
    )
    assert pending.status_code == 201, pending.text

    gate = client.get("/api/workbenches/alpha/closeout/gate").json()

    check = next(item for item in gate["checks"] if item["id"] == "resume-drift-decision")
    assert check["status"] == "warn"
    assert check["blocking"] is False
