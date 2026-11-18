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


def _create_workbench(client: TestClient, slug: str = "alpha") -> None:
    r = client.post("/api/workbenches", json={"title": slug, "slug": slug, "tags": ["refall"]})
    assert r.status_code == 201, r.text


def test_pending_action_create_is_idempotent_by_source_tuple(client: TestClient) -> None:
    _create_workbench(client)
    body = {
        "kind": "live_validation_pending",
        "title": "Validate runtime reachability",
        "source_finding_id": "find_1",
        "source_unit_id": "unit_1",
        "source_event_id": "led_1",
        "priority": "high",
        "required_receipt_type": "live_repro",
        "assigned_lane": "dynamic-validation",
    }

    first = client.post("/api/workbenches/alpha/pending-actions", json=body)
    second = client.post("/api/workbenches/alpha/pending-actions", json=body)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]
    listed = client.get("/api/workbenches/alpha/pending-actions").json()
    assert len(listed) == 1


def test_pending_action_identity_ignores_title_changes(client: TestClient) -> None:
    _create_workbench(client)
    first = client.post(
        "/api/workbenches/alpha/pending-actions",
        json={
            "kind": "ingress_enumeration",
            "title": "Enumerate ingress path",
            "source_finding_id": "find_1",
            "source_unit_id": "unit_1",
            "source_event_id": "led_1",
        },
    )
    second = client.post(
        "/api/workbenches/alpha/pending-actions",
        json={
            "kind": "ingress_enumeration",
            "title": "Updated wording for ingress work",
            "source_finding_id": "find_1",
            "source_unit_id": "unit_1",
            "source_event_id": "led_1",
        },
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]
    assert len(client.get("/api/workbenches/alpha/pending-actions").json()) == 1


def test_resolve_pending_action_requires_configured_receipt(client: TestClient) -> None:
    _create_workbench(client)
    created = client.post(
        "/api/workbenches/alpha/pending-actions",
        json={
            "kind": "live_validation_pending",
            "title": "Validate runtime reachability",
            "source_finding_id": "find_1",
            "required_receipt_type": "live_repro",
        },
    ).json()

    missing = client.post(
        f"/api/workbenches/alpha/pending-actions/{created['id']}/resolve",
        json={"resolved_by": "validator"},
    )
    assert missing.status_code == 422

    resolved = client.post(
        f"/api/workbenches/alpha/pending-actions/{created['id']}/resolve",
        json={
            "resolved_by": "validator",
            "receipt_type": "live_repro",
            "receipt": {"evidence_refs": ["led_runtime"], "artifact_refs": ["obj_poc"]},
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "done"


def test_deferred_pending_action_needs_receipt_and_is_closeout_visible(client: TestClient) -> None:
    _create_workbench(client)
    created = client.post(
        "/api/workbenches/alpha/pending-actions",
        json={"kind": "operator_decision_needed", "title": "Need scope decision"},
    ).json()

    no_receipt = client.post(f"/api/workbenches/alpha/pending-actions/{created['id']}/defer", json={})
    assert no_receipt.status_code == 422

    deferred = client.post(
        f"/api/workbenches/alpha/pending-actions/{created['id']}/defer",
        json={
            "resolved_by": "operator",
            "receipt_type": "operator_override",
            "receipt": {"reason": "Out of test window", "evidence_refs": ["led_scope"]},
        },
    )
    assert deferred.status_code == 200, deferred.text
    gate = client.get("/api/workbenches/alpha/closeout/gate").json()
    assert gate["summary"]["pending_actions_deferred"] == 1


def test_open_pending_action_blocks_closeout(client: TestClient) -> None:
    _create_workbench(client)
    client.post(
        "/api/workbenches/alpha/pending-actions",
        json={"kind": "operator_decision_needed", "title": "Need scope decision"},
    )

    gate = client.get("/api/workbenches/alpha/closeout/gate").json()

    assert gate["passed"] is False
    assert any(check["id"] == "pending-actions-open" and check["status"] == "fail" for check in gate["checks"])


def test_validation_status_creates_live_validation_pending_action(client: TestClient) -> None:
    _create_workbench(client)
    finding = client.post(
        "/api/workbenches/alpha/coverage/findings",
        json={
            "title": "Source-only command injection",
            "severity": "HIGH",
            "code_paths": ["app.py:10"],
            "source_anchors": ["app.py:10"],
            "evidence": [{"kind": "source_anchor", "ref": "app.py:10"}],
            "confidence": "medium",
        },
    ).json()

    updated = client.post(
        "/api/workbenches/alpha/coverage/finding-validation",
        json={
            "finding_id": finding["id"],
            "agent": "critic",
            "repro_status": "runtime_viable",
        },
    )

    assert updated.status_code == 200, updated.text
    pending = client.get("/api/workbenches/alpha/pending-actions").json()
    assert pending[0]["kind"] == "live_validation_pending"
    assert pending[0]["source_finding_id"] == finding["id"]
    entries = client.get("/api/workbenches/alpha/ledger/entries?kind=pending-action").json()
    assert any(entry["pending_action_id"] == pending[0]["id"] for entry in entries)


def test_high_impact_finding_without_visual_creates_visual_pending_action(client: TestClient) -> None:
    _create_workbench(client)

    finding = client.post(
        "/api/workbenches/alpha/coverage/findings",
        json={
            "title": "Critical auth bypass",
            "severity": "CRITICAL",
            "code_paths": ["auth.py:44"],
            "source_anchors": ["auth.py:44"],
            "evidence": [{"kind": "source_anchor", "ref": "auth.py:44"}],
            "confidence": "medium",
        },
    )

    assert finding.status_code == 201, finding.text
    pending = client.get("/api/workbenches/alpha/pending-actions?kind=visual_evidence_needed").json()
    assert pending[0]["source_finding_id"] == finding.json()["id"]
    assert pending[0]["required_receipt_type"] == "visual_evidence"
    entries = client.get("/api/workbenches/alpha/ledger/entries?kind=pending-action").json()
    assert any(entry["pending_action_id"] == pending[0]["id"] for entry in entries)


def test_refused_duplicate_transition_creates_duplicate_review_action(client: TestClient) -> None:
    _create_workbench(client)
    finding = client.post(
        "/api/workbenches/alpha/coverage/findings",
        json={
            "title": "Candidate duplicate",
            "severity": "HIGH",
            "code_paths": ["app.py:10"],
            "source_anchors": ["app.py:10"],
            "evidence": [{"kind": "source_anchor", "ref": "app.py:10"}],
            "confidence": "medium",
        },
    ).json()

    transition = client.post(
        f"/api/workbenches/alpha/findings/{finding['id']}/transitions",
        json={
            "to_status": "DUPLICATE",
            "proposed_by": "critic",
            "reason": "Looks like a duplicate but canonical finding was not supplied.",
            "receipt_type": "duplicate_equivalence",
            "receipt": {"source_anchors": ["app.py:10"], "evidence_refs": ["led_1"]},
        },
    )

    assert transition.status_code == 200, transition.text
    assert transition.json()["status"] == "refused"
    pending = client.get("/api/workbenches/alpha/pending-actions?kind=duplicate_equivalence_review").json()
    assert pending[0]["source_finding_id"] == finding["id"]
    assert pending[0]["required_receipt_type"] == "duplicate_equivalence"


def test_runtime_event_triggers_follow_up_pending_action(client: TestClient) -> None:
    _create_workbench(client)

    event = client.post(
        "/api/workbenches/alpha/runtime/events",
        json={
            "type": "confirmed_parser_bug",
            "task_id": "task_1",
            "payload": {
                "summary": "Parser accepts malformed nested documents.",
                "finding_id": "find_parser",
            },
        },
    )

    assert event.status_code == 201, event.text
    pending = client.get("/api/workbenches/alpha/pending-actions?kind=parser_family_sweep").json()
    assert pending[0]["source_event_id"] == event.json()["id"]
    assert pending[0]["source_finding_id"] == "find_parser"
