from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arctic_base.api.deps import get_storage
from arctic_base.main import app
from arctic_base.refall.coverage_db import connect, init_schema
from arctic_base.storage.filesystem import FilesystemStorage


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    storage = FilesystemStorage(tmp_path / "data")
    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_duplicate_finding_updates_canonical_related_locations(client: TestClient) -> None:
    created = client.post("/api/workbenches", json={"title": "Alpha", "slug": "alpha", "tags": ["refall"]})
    assert created.status_code == 201, created.text
    body = {
        "title": "Command injection",
        "severity": "HIGH",
        "vuln_class": "command-injection",
        "code_paths": ["app.py:10"],
        "evidence": [{"kind": "source_anchor", "ref": "app.py:10"}],
        "confidence": "medium",
    }
    first = client.post("/api/workbenches/alpha/coverage/findings", json=body)
    assert first.status_code == 201, first.text

    second_body = dict(body, code_paths=["views.py:22"], evidence=[{"kind": "source_anchor", "ref": "views.py:22"}])
    second = client.post("/api/workbenches/alpha/coverage/findings", json=second_body)
    assert second.status_code == 201, second.text

    assert second.json()["id"] == first.json()["id"]
    assert second.json()["canonical_finding_id"] == first.json()["id"]
    assert {"path": "views.py", "anchor": "views.py:22"} in second.json()["related_locations"]
    findings = client.get("/api/workbenches/alpha/coverage/findings").json()
    assert len(findings) == 1


def test_duplicate_finding_merges_variant_reproduction_and_history(client: TestClient) -> None:
    created = client.post("/api/workbenches", json={"title": "Alpha", "slug": "alpha", "tags": ["refall"]})
    assert created.status_code == 201, created.text
    base = {
        "title": "Command injection",
        "severity": "HIGH",
        "vuln_class": "command-injection",
        "confidence": "medium",
    }
    first = client.post(
        "/api/workbenches/alpha/coverage/findings",
        json={
            **base,
            "code_paths": ["app.py:10"],
            "evidence": [{"kind": "source_anchor", "ref": "app.py:10"}],
            "reproduction_steps": ["curl /first"],
            "history": [{"event": "first-proof"}],
        },
    )
    assert first.status_code == 201, first.text

    second = client.post(
        "/api/workbenches/alpha/coverage/findings",
        json={
            **base,
            "code_paths": ["views.py:22"],
            "evidence": [{"kind": "source_anchor", "ref": "views.py:22"}],
            "reproduction_steps": ["curl /second"],
            "history": [{"event": "second-proof"}],
        },
    )

    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]
    assert "curl /first" in second.json()["repro_hints"]
    assert "curl /second" in second.json()["repro_hints"]
    assert {"event": "first-proof"} in second.json()["history"]
    assert {"event": "second-proof"} in second.json()["history"]


def test_dedup_schema_migrates_existing_findings_table(tmp_path: Path) -> None:
    conn = connect(tmp_path / "coverage.db")
    conn.execute(
        """
        CREATE TABLE findings (
          id TEXT PRIMARY KEY, subject TEXT NOT NULL,
          title TEXT NOT NULL, description TEXT, impact TEXT,
          severity TEXT, privileges_required TEXT, attacker_position TEXT, user_interaction TEXT,
          status TEXT DEFAULT 'PROVISIONALLY_VALID',
          quality_tier TEXT DEFAULT 'HYPOTHESIS',
          production_viability TEXT, repro_status TEXT DEFAULT 'not_attempted', patch_status TEXT,
          code_paths TEXT NOT NULL, mitigation TEXT, reasoning TEXT, repro_hints TEXT,
          critic_reasoning TEXT, vuln_class TEXT, source_unit_id TEXT, investigation_id TEXT,
          pass_number INTEGER DEFAULT 1, impact_score INTEGER, likelihood_score INTEGER,
          mantis_risk_score REAL, priority TEXT, inferred_exposure TEXT, availability_tier TEXT,
          duplicate_of TEXT, constituent_findings TEXT, history TEXT,
          created_by TEXT, created_at REAL, updated_at REAL
        )
        """
    )
    conn.commit()

    init_schema(conn)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(findings)")}
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(findings)")}
    assert {"dedup_key", "canonical_finding_id", "related_locations"} <= columns
    assert "ix_find_subject_dedup" in indexes
