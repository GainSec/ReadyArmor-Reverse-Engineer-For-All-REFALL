from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arctic_base.api.deps import get_storage
from arctic_base.main import app
from arctic_base.refall.promotion_gates import evaluate_finding_candidate
from arctic_base.storage.filesystem import FilesystemStorage


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    storage = FilesystemStorage(tmp_path / "data")
    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_promotion_gate_rejects_missing_evidence() -> None:
    result = evaluate_finding_candidate(
        {
            "title": "Command injection",
            "severity": "HIGH",
            "vuln_class": "command-injection",
            "code_paths": ["app.py:10"],
        },
        source_inventory={"files": [{"path": "app.py"}]},
        scope_overlay={"external_targets": []},
    )

    assert result["accepted"] is False
    assert "evidence" in " ".join(result["reasons"])


def test_promotion_gate_accepts_source_anchored_candidate() -> None:
    result = evaluate_finding_candidate(
        {
            "title": "Command injection",
            "severity": "HIGH",
            "vuln_class": "command-injection",
            "code_paths": ["app.py:10"],
            "evidence": [{"kind": "source_anchor", "ref": "app.py:10"}],
            "confidence": "medium",
        },
        source_inventory={"files": [{"path": "app.py"}]},
        scope_overlay={"external_targets": []},
    )

    assert result["accepted"] is True


def test_promotion_gate_accepts_documented_source_line_range() -> None:
    result = evaluate_finding_candidate(
        {
            "title": "Command injection",
            "severity": "HIGH",
            "vuln_class": "command-injection",
            "code_paths": ["app.py:10-20"],
            "evidence": [{"kind": "source_anchor", "ref": "app.py:10-20"}],
            "confidence": "medium",
        },
        source_inventory={"files": [{"path": "app.py"}]},
        scope_overlay={"external_targets": []},
    )

    assert result["accepted"] is True


def test_promotion_gate_rejects_unknown_source_anchor() -> None:
    result = evaluate_finding_candidate(
        {
            "title": "Command injection",
            "severity": "HIGH",
            "vuln_class": "command-injection",
            "code_paths": ["missing.py:10"],
            "evidence": [{"kind": "source_anchor", "ref": "missing.py:10"}],
            "confidence": "medium",
        },
        source_inventory={"files": [{"path": "app.py"}]},
        scope_overlay={"external_targets": []},
    )

    assert result["accepted"] is False
    assert "not in source inventory" in " ".join(result["reasons"])


def test_promotion_gate_rejects_external_target_outside_scope() -> None:
    result = evaluate_finding_candidate(
        {
            "title": "SSRF reaches external service",
            "severity": "HIGH",
            "vuln_class": "ssrf",
            "code_paths": ["app.py:10"],
            "evidence": [{"kind": "source_anchor", "ref": "app.py:10"}],
            "artifact_refs": ["https://outside.example.test/proof"],
            "confidence": "medium",
        },
        source_inventory={"files": [{"path": "app.py"}]},
        scope_overlay={"external_targets": [{"host": "allowed.example.test"}]},
    )

    assert result["accepted"] is False
    assert "outside explicit scope" in " ".join(result["reasons"])


def test_promotion_gate_checks_external_urls_in_code_paths() -> None:
    result = evaluate_finding_candidate(
        {
            "title": "External redirect",
            "severity": "MEDIUM",
            "vuln_class": "open-redirect",
            "code_paths": ["https://outside.example.test/callback"],
            "artifact_refs": ["obj_runtime_trace"],
            "confidence": "medium",
        },
        source_inventory={"files": [{"path": "app.py"}]},
        scope_overlay={"external_targets": []},
    )

    assert result["accepted"] is False
    assert "outside explicit scope" in " ".join(result["reasons"])


def test_api_refused_finding_creates_review_pending_action(client: TestClient) -> None:
    created = client.post("/api/workbenches", json={"title": "Alpha", "slug": "alpha", "tags": ["refall"]})
    assert created.status_code == 201, created.text
    inventory = client.put(
        "/api/workbenches/alpha/coverage/source-inventory",
        json={
            "subject": "alpha",
            "root": "/subjects/alpha",
            "files": [{"path": "app.py", "sha256": "a" * 64, "total_lines": 1, "kind": "python"}],
        },
    )
    assert inventory.status_code == 200, inventory.text

    refused = client.post(
        "/api/workbenches/alpha/coverage/findings",
        json={
            "title": "Command injection",
            "severity": "HIGH",
            "vuln_class": "command-injection",
            "code_paths": ["app.py:10"],
        },
    )

    assert refused.status_code == 422, refused.text
    assert "finding promotion refused" in refused.text
    pending = client.get("/api/workbenches/alpha/pending-actions").json()
    assert pending[0]["kind"] == "finding_candidate_review"
    assert pending[0]["required_receipt_type"] == "manager_review"


def test_api_refuses_weak_finding_without_inventory_context(client: TestClient) -> None:
    created = client.post("/api/workbenches", json={"title": "Alpha", "slug": "alpha", "tags": ["refall"]})
    assert created.status_code == 201, created.text

    refused = client.post(
        "/api/workbenches/alpha/coverage/findings",
        json={
            "title": "Command injection",
            "severity": "HIGH",
            "vuln_class": "command-injection",
            "code_paths": ["missing.py:10"],
        },
    )

    assert refused.status_code == 422, refused.text
    assert "finding promotion refused" in refused.text
    assert "missing evidence" in refused.text
    pending = client.get("/api/workbenches/alpha/pending-actions").json()
    assert pending[0]["kind"] == "finding_candidate_review"
