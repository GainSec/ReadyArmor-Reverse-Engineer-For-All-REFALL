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


def test_ledger_append_persists_rich_finding_fields(client: TestClient, tmp_path: Path) -> None:
    _create_workbench(client)

    body = {
        "kind": "finding",
        "title": "Command injection",
        "lane": "dynamic-validation",
        "severity": "HIGH",
        "summary": "Validated shell injection path.",
        "impact": "Remote command execution as service user.",
        "confidence_justification": "Observed command output in controlled harness.",
        "reproduction_steps": ["send payload", "observe output"],
        "remediation": "Use argv arrays and reject shell metacharacters.",
        "flag": "needs-vendor-review",
        "flag_justification": "Public exploitability depends on auth mode.",
        "related_leads": ["lead-1"],
        "validation": {"status": "reproduced", "artifact": "artifact:obj_abc"},
        "refs": ["source:app.py::run", "endpoint:POST /api/run", "artifact:obj_abc"],
    }

    r = client.post("/api/workbenches/alpha/ledger/entries", json=body)

    assert r.status_code == 201, r.text
    entry = r.json()
    assert entry["id"].startswith("led_")
    for key, value in body.items():
        assert entry[key] == value

    ledger_path = tmp_path / "data/workbenches/alpha/refall_ledger.jsonl"
    assert ledger_path.is_file()

    fetched = client.get(f"/api/workbenches/alpha/ledger/entries/{entry['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["reproduction_steps"] == ["send payload", "observe output"]


def test_ledger_list_filters_and_stats(client: TestClient) -> None:
    _create_workbench(client)
    client.post(
        "/api/workbenches/alpha/ledger/entries",
        json={"kind": "fact", "title": "Router exists", "lane": "source-review"},
    )
    client.post(
        "/api/workbenches/alpha/ledger/entries",
        json={"kind": "finding", "title": "SQLi", "lane": "source-review", "severity": "HIGH"},
    )
    client.post(
        "/api/workbenches/alpha/ledger/entries",
        json={"kind": "finding", "title": "XSS", "lane": "source-review", "severity": "LOW"},
    )

    filtered = client.get(
        "/api/workbenches/alpha/ledger/entries?kind=finding&lane=source-review&severity=HIGH"
    )
    assert filtered.status_code == 200, filtered.text
    assert [entry["title"] for entry in filtered.json()] == ["SQLi"]

    stats = client.get("/api/workbenches/alpha/ledger/stats")
    assert stats.status_code == 200, stats.text
    body = stats.json()
    assert body["total"] == 3
    assert body["by_kind"]["finding"] == 2
    assert body["by_severity"]["HIGH"] == 1
