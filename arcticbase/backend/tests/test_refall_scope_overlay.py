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


def test_scope_overlay_round_trip(client: TestClient) -> None:
    created = client.post("/api/workbenches", json={"title": "Alpha", "slug": "alpha", "tags": ["refall"]})
    assert created.status_code == 201, created.text
    overlay = {
        "local_roots": ["/subjects/alpha"],
        "lan_targets": [{"host": "192.0.2.10", "ports": [80, 81]}],
        "external_targets": [],
        "excluded_paths": [{"path": "vendor/", "reason": "third-party"}],
        "evidence_rules": ["source anchors required"],
        "operator_notes": "No external testing.",
    }

    saved = client.put("/api/workbenches/alpha/coverage/scope-overlay", json=overlay)
    assert saved.status_code == 200, saved.text
    assert saved.json()["overlay_id"].startswith("scope_")
    fetched = client.get("/api/workbenches/alpha/coverage/scope-overlay")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["lan_targets"][0]["host"] == "192.0.2.10"
    assert fetched.json()["external_targets"] == []
