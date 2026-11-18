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


def test_runtime_events_artifacts_and_projection_are_api_visible(tmp_path: Path, client: TestClient) -> None:
    subject_root = tmp_path / "subject"
    subject_root.mkdir()
    created = client.post(
        "/api/workbenches",
        json={
            "title": "alpha",
            "slug": "alpha",
            "tags": ["refall"],
            "custom_fields": {"refall_subject_path": str(subject_root)},
        },
    )
    assert created.status_code == 201, created.text

    event = client.post(
        "/api/workbenches/alpha/runtime/events",
        json={
            "type": "worker_submit",
            "task_id": "task_1",
            "session_id": "cid_1",
            "payload": {
                "summary": "Found source fact",
                "evidence": [{"kind": "source_anchor", "ref": "app.py:10", "claim": "source reaches sink"}],
            },
        },
    )
    assert event.status_code == 201, event.text
    artifact = client.post(
        "/api/workbenches/alpha/runtime/artifacts",
        json={
            "kind": "log",
            "task_id": "task_1",
            "content": "raw worker output",
            "mime": "text/plain",
        },
    )
    assert artifact.status_code == 201, artifact.text
    assert artifact.json()["sha256"]

    projected = client.post("/api/workbenches/alpha/runtime/project")
    assert projected.status_code == 200, projected.text
    assert projected.json()["events_projected"] == 1

    observations = client.get("/api/workbenches/alpha/runtime/observations").json()
    assert observations[0]["kind"] == "source_fact"
    graph = client.get("/api/workbenches/alpha/runtime/evidence-graph").json()
    assert graph["nodes"][0]["type"] == "observation"


def test_nonfatal_errors_projection_uses_runtime_events(client: TestClient) -> None:
    created = client.post("/api/workbenches", json={"title": "Alpha", "slug": "alpha", "tags": ["refall"]})
    assert created.status_code == 201, created.text
    event = client.post(
        "/api/workbenches/alpha/runtime/events",
        json={
            "type": "worker_submit_invalid",
            "task_id": "task_1",
            "session_id": "cid_1",
            "payload": {
                "summary": "malformed refall-submit",
                "failure_class": "contract_error",
            },
            "artifact_refs": ["art_1"],
        },
    )
    assert event.status_code == 201, event.text

    errors = client.get("/api/workbenches/alpha/runtime/nonfatal-errors")
    assert errors.status_code == 200, errors.text
    assert errors.json()["errors"][0]["type"] == "worker_submit_invalid"
    assert errors.json()["errors"][0]["failure_class"] == "contract_error"
    assert errors.json()["errors"][0]["artifact_refs"] == ["art_1"]

    ndjson = client.get("/api/workbenches/alpha/runtime/nonfatal-errors.ndjson")
    assert ndjson.status_code == 200, ndjson.text
    assert ndjson.headers["content-type"].startswith("application/x-ndjson")
    assert "worker_submit_invalid" in ndjson.text


def test_nonfatal_errors_projection_includes_ledger_refusals(client: TestClient) -> None:
    created = client.post("/api/workbenches", json={"title": "Alpha", "slug": "alpha", "tags": ["refall"]})
    assert created.status_code == 201, created.text
    ledgered = client.post(
        "/api/workbenches/alpha/ledger/entries",
        json={
            "kind": "ops-event",
            "action": "finding.promotion.refused",
            "status": "refused",
            "summary": "source anchor outside inventory",
            "refusal_reasons": ["unknown source anchor"],
        },
    )
    assert ledgered.status_code == 201, ledgered.text

    errors = client.get("/api/workbenches/alpha/runtime/nonfatal-errors")

    assert errors.status_code == 200, errors.text
    row = errors.json()["errors"][0]
    assert row["source"] == "ledger"
    assert row["type"] == "finding.promotion.refused"
    assert row["summary"] == "source anchor outside inventory"
    assert row["refusal_reasons"] == ["unknown source anchor"]


def test_nonfatal_errors_projection_normalizes_refusal_reasons_alias(client: TestClient) -> None:
    created = client.post("/api/workbenches", json={"title": "Alpha", "slug": "alpha", "tags": ["refall"]})
    assert created.status_code == 201, created.text
    runtime = client.post(
        "/api/workbenches/alpha/runtime/events",
        json={
            "type": "finding_promotion_refused",
            "payload": {
                "summary": "runtime refused",
                "reasons": ["missing evidence"],
            },
        },
    )
    assert runtime.status_code == 201, runtime.text
    ledgered = client.post(
        "/api/workbenches/alpha/ledger/entries",
        json={
            "kind": "ops-event",
            "action": "finding.promotion.refused",
            "status": "blocked",
            "summary": "ledger refused",
            "reasons": ["source anchor outside inventory"],
        },
    )
    assert ledgered.status_code == 201, ledgered.text

    errors = client.get("/api/workbenches/alpha/runtime/nonfatal-errors")

    assert errors.status_code == 200, errors.text
    by_summary = {item["summary"]: item for item in errors.json()["errors"]}
    assert by_summary["runtime refused"]["refusal_reasons"] == ["missing evidence"]
    assert by_summary["ledger refused"]["refusal_reasons"] == ["source anchor outside inventory"]


def test_runtime_manifest_round_trip_and_runbook_publish(client: TestClient) -> None:
    created = client.post(
        "/api/workbenches",
        json={"title": "Alpha", "slug": "alpha", "tags": ["refall"]},
    )
    assert created.status_code == 201, created.text

    manifest = client.put(
        "/api/workbenches/alpha/runtime/manifest",
        json={
            "run_id": "run_1",
            "provider_roles": {"manager": "codex"},
            "source_hashes": {"app.py": "sha256:" + "a" * 64},
            "dynamic_testing": {"status": "not_applicable"},
            "git": {"sha": None},
        },
    )

    assert manifest.status_code == 200, manifest.text
    body = manifest.json()
    assert body["run_id"] == "run_1"
    assert body["manifest_id"].startswith("manifest_")
    assert body["workbench_object_id"].startswith("obj_")
    fetched = client.get("/api/workbenches/alpha/runtime/manifest")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["manifest_id"] == body["manifest_id"]
    assert fetched.json()["provider_roles"]["manager"] == "codex"
    content = client.get(f"/api/workbenches/alpha/objects/{body['workbench_object_id']}/content")
    assert content.status_code == 200, content.text
    assert content.json()["run_id"] == "run_1"
    assert content.json()["workbench_object_id"] == body["workbench_object_id"]
    assert content.json()["provider_roles"]["manager"] == "codex"


def test_runtime_manifest_recreates_deleted_runbook(client: TestClient) -> None:
    created = client.post(
        "/api/workbenches",
        json={"title": "Alpha", "slug": "alpha", "tags": ["refall"]},
    )
    assert created.status_code == 201, created.text

    first = client.put(
        "/api/workbenches/alpha/runtime/manifest",
        json={
            "run_id": "run_1",
            "provider_roles": {"manager": "codex"},
            "source_hashes": {"app.py": "sha256:" + "a" * 64},
            "dynamic_testing": {"status": "not_applicable"},
            "git": {"sha": None},
        },
    )
    assert first.status_code == 200, first.text
    old_id = first.json()["workbench_object_id"]

    deleted = client.delete(f"/api/workbenches/alpha/objects/{old_id}")
    assert deleted.status_code == 204, deleted.text

    second = client.put(
        "/api/workbenches/alpha/runtime/manifest",
        json={
            "run_id": "run_1",
            "provider_roles": {"manager": "codex"},
            "source_hashes": {"app.py": "sha256:" + "b" * 64},
            "dynamic_testing": {"status": "not_applicable"},
            "git": {"sha": None},
        },
    )
    assert second.status_code == 200, second.text
    new_id = second.json()["workbench_object_id"]
    assert new_id.startswith("obj_")
    assert new_id != old_id

    content = client.get(f"/api/workbenches/alpha/objects/{new_id}/content")
    assert content.status_code == 200, content.text
    assert content.json()["workbench_object_id"] == new_id
    assert content.json()["source_hashes"]["app.py"] == "sha256:" + "b" * 64


def test_runtime_checkpoint_round_trip_and_drift(client: TestClient) -> None:
    created = client.post(
        "/api/workbenches",
        json={"title": "Alpha", "slug": "alpha", "tags": ["refall"]},
    )
    assert created.status_code == 201, created.text
    body = {
        "run_id": "run_1",
        "stage": "source_inventory",
        "checkpoint_key": "inventory:latest",
        "status": "complete",
        "input_hashes": {"app.py": "sha256:" + "a" * 64},
        "output_refs": ["inventory:inv_1"],
        "payload": {"files": 1},
    }

    checkpoint = client.post("/api/workbenches/alpha/runtime/checkpoints", json=body)
    assert checkpoint.status_code == 201, checkpoint.text
    assert checkpoint.json()["checkpoint_key"] == "inventory:latest"

    listed = client.get("/api/workbenches/alpha/runtime/checkpoints")
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["stage"] == "source_inventory"

    drift = client.post(
        "/api/workbenches/alpha/runtime/resume-preflight",
        json={"input_hashes": {"app.py": "sha256:" + "b" * 64}},
    )
    assert drift.status_code == 409
    assert "changed" in drift.text.lower()

    pending = client.get("/api/workbenches/alpha/pending-actions?kind=resume_drift_decision")
    assert pending.status_code == 200, pending.text
    assert pending.json()[0]["required_receipt_type"] == "manager_review"


def test_runtime_resume_preflight_detects_added_source_input(client: TestClient) -> None:
    created = client.post(
        "/api/workbenches",
        json={"title": "Alpha", "slug": "alpha", "tags": ["refall"]},
    )
    assert created.status_code == 201, created.text
    checkpoint = client.post(
        "/api/workbenches/alpha/runtime/checkpoints",
        json={
            "run_id": "run_1",
            "stage": "source_inventory",
            "checkpoint_key": "inventory:latest",
            "status": "complete",
            "input_hashes": {"source:app.py": "sha256:" + "a" * 64},
            "output_refs": ["inventory:inv_1"],
            "payload": {"files": 1},
        },
    )
    assert checkpoint.status_code == 201, checkpoint.text

    drift = client.post(
        "/api/workbenches/alpha/runtime/resume-preflight",
        json={
            "input_hashes": {
                "source:app.py": "sha256:" + "a" * 64,
                "source:new.py": "sha256:" + "b" * 64,
            }
        },
    )

    assert drift.status_code == 409, drift.text
    assert {"path": "source:new.py", "expected": None, "actual": "sha256:" + "b" * 64, "reason": "added"} in drift.json()["detail"]["changes"]
