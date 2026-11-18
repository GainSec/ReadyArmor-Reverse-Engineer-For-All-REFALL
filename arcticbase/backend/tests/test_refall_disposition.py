import hashlib
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


def _create_finding(client: TestClient, slug: str = "alpha", **overrides) -> dict:
    body = {
        "title": "Command injection",
        "description": "Untrusted text reaches a shell.",
        "impact": "Remote command execution.",
        "severity": "HIGH",
        "code_paths": ["app.py:10"],
        "source_anchors": ["app.py:10"],
        "evidence": [{"kind": "source_anchor", "ref": "app.py:10"}],
        "confidence": "medium",
        "created_by": "researcher",
    }
    body.update(overrides)
    r = client.post(f"/api/workbenches/{slug}/coverage/findings", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_false_positive_transition_without_receipt_is_refused_and_ledgers(client: TestClient) -> None:
    _create_workbench(client)
    finding = _create_finding(client)

    r = client.post(
        f"/api/workbenches/alpha/findings/{finding['id']}/transitions",
        json={
            "to_status": "FALSE_POSITIVE",
            "proposed_by": "critic",
            "reason": "Looks unreachable.",
        },
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "refused"
    assert body["accepted"] is False
    assert "receipt_type" in " ".join(body["refusal_reasons"])
    assert client.get("/api/workbenches/alpha/coverage/findings?status=FALSE_POSITIVE").json() == []

    refusals = client.get("/api/workbenches/alpha/disposition/refusals").json()
    assert refusals[0]["finding_id"] == finding["id"]
    entries = client.get("/api/workbenches/alpha/ledger/entries?kind=disposition-transition").json()
    assert entries[0]["status"] == "refused"


def test_finding_creation_rejects_unknown_status(client: TestClient) -> None:
    _create_workbench(client)

    r = client.post(
        "/api/workbenches/alpha/coverage/findings",
        json={
            "title": "Bad status",
            "severity": "LOW",
            "status": "NOPE",
            "code_paths": ["app.py:10"],
        },
    )

    assert r.status_code == 422
    assert "bad status" in r.text


@pytest.mark.parametrize("status", ["VALID", "FALSE_POSITIVE", "DUPLICATE", "CHAINABLE_DEFERRED"])
def test_finding_creation_rejects_transition_controlled_statuses(
    client: TestClient,
    status: str,
) -> None:
    _create_workbench(client)

    r = client.post(
        "/api/workbenches/alpha/coverage/findings",
        json={
            "title": "Pre-mutated finding",
            "severity": "LOW",
            "status": status,
            "code_paths": ["app.py:10"],
        },
    )

    assert r.status_code == 422
    assert "transition" in r.text.lower()
    assert client.get(f"/api/workbenches/alpha/coverage/findings?status={status}").json() == []


def test_transition_to_unknown_status_is_refused(client: TestClient) -> None:
    _create_workbench(client)
    finding = _create_finding(client, severity="LOW")

    r = client.post(
        f"/api/workbenches/alpha/findings/{finding['id']}/transitions",
        json={
            "to_status": "NOPE",
            "proposed_by": "critic",
            "reason": "Invalid lifecycle status.",
        },
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "refused"
    assert any("bad status" in reason for reason in body["refusal_reasons"])
    current = client.get("/api/workbenches/alpha/coverage/findings?status=PROVISIONALLY_VALID").json()
    assert current[0]["id"] == finding["id"]


def test_duplicate_transition_requires_duplicate_equivalence_receipt(client: TestClient) -> None:
    _create_workbench(client)
    canonical = _create_finding(client, id="find_canon", title="Canonical bug")
    candidate = _create_finding(client, id="find_dupe", title="Duplicate bug")

    refused = client.post(
        f"/api/workbenches/alpha/findings/{candidate['id']}/transitions",
        json={
            "to_status": "DUPLICATE",
            "proposed_by": "critic",
            "reason": "Same family.",
            "receipt_type": "duplicate_equivalence",
            "receipt": {"evidence_refs": ["led_1"], "source_anchors": ["app.py:10"]},
        },
    )
    assert refused.status_code == 200, refused.text
    assert refused.json()["status"] == "refused"

    accepted = client.post(
        f"/api/workbenches/alpha/findings/{candidate['id']}/transitions",
        json={
            "to_status": "DUPLICATE",
            "duplicate_of": canonical["id"],
            "proposed_by": "critic",
            "reason": "Same root cause, sink, and fix.",
            "receipt_type": "duplicate_equivalence",
            "receipt": {
                "summary": "Equivalent trigger and sink.",
                "evidence_refs": ["led_1"],
                "source_anchors": ["app.py:10"],
            },
        },
    )

    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    findings = client.get("/api/workbenches/alpha/coverage/findings?status=DUPLICATE").json()
    assert findings[0]["duplicate_of"] == canonical["id"]


def test_quality_downgrade_requires_trigger_inventory_receipt(client: TestClient) -> None:
    _create_workbench(client)
    finding = _create_finding(client, quality_tier="LIVE_CONFIRMED")

    r = client.post(
        f"/api/workbenches/alpha/findings/{finding['id']}/transitions",
        json={
            "from_quality": "LIVE_CONFIRMED",
            "to_quality": "CODE_CONFIRMED",
            "proposed_by": "critic",
            "reason": "Runtime proof no longer considered enough.",
            "receipt_type": "code_anchor",
            "receipt": {"evidence_refs": ["led_1"], "source_anchors": ["app.py:10"]},
        },
    )

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "refused"
    assert "trigger" in " ".join(r.json()["refusal_reasons"]).lower()


def test_live_repro_transition_to_valid_is_accepted(client: TestClient) -> None:
    _create_workbench(client)
    finding = _create_finding(client)

    r = client.post(
        f"/api/workbenches/alpha/findings/{finding['id']}/transitions",
        json={
            "from_status": "PROVISIONALLY_VALID",
            "to_status": "VALID",
            "from_quality": "HYPOTHESIS",
            "to_quality": "LIVE_CONFIRMED",
            "proposed_by": "validator",
            "reason": "Payload executed in harness.",
            "receipt_type": "live_repro",
            "receipt": {
                "summary": "Observed command output in target harness.",
                "evidence_refs": ["led_runtime"],
                "artifact_refs": ["obj_poc"],
            },
        },
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "accepted"
    assert body["finding"]["status"] == "VALID"
    assert body["finding"]["quality_tier"] == "LIVE_CONFIRMED"


def test_valid_transition_without_positive_receipt_is_refused(client: TestClient) -> None:
    _create_workbench(client)
    finding = _create_finding(client)

    r = client.post(
        f"/api/workbenches/alpha/findings/{finding['id']}/transitions",
        json={
            "to_status": "VALID",
            "proposed_by": "validator",
            "reason": "Looks exploitable.",
        },
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "refused"
    assert any("positive validation" in reason for reason in body["refusal_reasons"])
    current = client.get("/api/workbenches/alpha/coverage/findings?status=PROVISIONALLY_VALID").json()
    assert current[0]["id"] == finding["id"]


def test_live_confirmed_quality_requires_live_repro_receipt(client: TestClient) -> None:
    _create_workbench(client)
    finding = _create_finding(client)

    r = client.post(
        f"/api/workbenches/alpha/findings/{finding['id']}/transitions",
        json={
            "from_quality": "HYPOTHESIS",
            "to_quality": "LIVE_CONFIRMED",
            "proposed_by": "validator",
            "reason": "Runtime confidence raised without proof.",
            "receipt_type": "code_anchor",
            "receipt": {"source_anchors": ["app.py:10"]},
        },
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "refused"
    assert any("LIVE_CONFIRMED" in reason for reason in body["refusal_reasons"])


def test_validation_endpoint_cannot_mutate_status_directly(client: TestClient) -> None:
    _create_workbench(client)
    finding = _create_finding(client)

    r = client.post(
        f"/api/workbenches/alpha/coverage/finding-validation",
        json={
            "finding_id": finding["id"],
            "agent": "critic",
            "status": "FALSE_POSITIVE",
            "critic_reasoning": "Unreachable, but no transition receipt was supplied.",
        },
    )

    assert r.status_code == 422, r.text
    assert "transition" in r.text.lower()
    assert client.get("/api/workbenches/alpha/coverage/findings?status=FALSE_POSITIVE").json() == []
    current = client.get("/api/workbenches/alpha/coverage/findings?status=PROVISIONALLY_VALID").json()
    assert current[0]["id"] == finding["id"]


def test_suppressive_transition_with_unresolved_pending_action_is_refused(client: TestClient) -> None:
    _create_workbench(client)
    finding = _create_finding(client, severity="MEDIUM")
    pending_update = client.post(
        "/api/workbenches/alpha/coverage/finding-validation",
        json={
            "finding_id": finding["id"],
            "agent": "critic",
            "repro_status": "runtime_viable",
        },
    )
    assert pending_update.status_code == 200, pending_update.text

    r = client.post(
        f"/api/workbenches/alpha/findings/{finding['id']}/transitions",
        json={
            "to_status": "FALSE_POSITIVE",
            "proposed_by": "critic",
            "reason": "Non-reachable after review.",
            "receipt_type": "non_reachability_proof",
            "receipt": {"evidence_refs": ["led_1"], "source_anchors": ["app.py:10"]},
        },
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "refused"
    assert any("pending action" in reason for reason in body["refusal_reasons"])


def test_transition_receipt_with_stale_source_hash_is_refused(
    client: TestClient,
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    old_content = b"def route():\n    return False\n"
    (source / "app.py").write_bytes(b"def route():\n    return True\n")
    _create_workbench(client)
    patched = client.patch(
        "/api/workbenches/alpha",
        json={"custom_fields": {"refall_source_path": str(source)}},
    )
    assert patched.status_code == 200, patched.text
    finding = _create_finding(client)

    r = client.post(
        f"/api/workbenches/alpha/findings/{finding['id']}/transitions",
        json={
            "to_status": "FALSE_POSITIVE",
            "proposed_by": "critic",
            "reason": "Route is unreachable in config.",
            "receipt_type": "non_reachability_proof",
            "receipt": {
                "summary": "Old route map excluded this path.",
                "source_anchors": ["app.py:1"],
                "source_hashes": {"app.py:1": hashlib.sha256(old_content).hexdigest()},
            },
        },
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "refused"
    assert any("stale evidence" in reason for reason in body["refusal_reasons"])


def test_chainable_deferred_is_kept_internal_and_blocks_vendor_export(client: TestClient) -> None:
    _create_workbench(client)
    finding = _create_finding(client)

    r = client.post(
        f"/api/workbenches/alpha/findings/{finding['id']}/transitions",
        json={
            "to_status": "CHAINABLE_DEFERRED",
            "proposed_by": "manager",
            "reason": "Primitive is real but standalone exploitability is not proven.",
            "receipt_type": "chain_preservation",
            "receipt": {
                "summary": "Keep primitive for attack-chain synthesis.",
                "evidence_refs": ["led_primitive"],
                "source_anchors": ["app.py:10"],
            },
        },
    )

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "accepted"
    gate = client.get("/api/workbenches/alpha/closeout/gate").json()
    assert any(check["id"] == "chainable-deferred-internal-only" for check in gate["checks"])
