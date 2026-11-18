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


def test_threat_model_round_trip(client: TestClient) -> None:
    created = client.post("/api/workbenches", json={"title": "Alpha", "slug": "alpha", "tags": ["refall"]})
    assert created.status_code == 201, created.text
    payload = {
        "assets": [{"id": "asset:web", "name": "web app"}],
        "ingress_points": [{"id": "ingress:http", "description": "HTTP service"}],
        "trust_boundaries": [{"id": "tb:user-service", "description": "user input to service"}],
        "threats": [{"id": "thr:cmd", "title": "Command injection", "vuln_class": "command-injection"}],
        "hunt_prompts": ["Trace user input to subprocess calls."],
        "status": "active",
    }

    saved = client.put("/api/workbenches/alpha/coverage/threat-model", json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["threat_model_id"].startswith("tm_")

    fetched = client.get("/api/workbenches/alpha/coverage/threat-model")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["threat_model_id"] == saved.json()["threat_model_id"]
    assert fetched.json()["threats"][0]["id"] == "thr:cmd"


def test_missing_threat_model_returns_skipped_default(client: TestClient) -> None:
    created = client.post("/api/workbenches", json={"title": "Beta", "slug": "beta", "tags": ["refall"]})
    assert created.status_code == 201, created.text

    fetched = client.get("/api/workbenches/beta/coverage/threat-model")

    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["subject"] == "beta"
    assert fetched.json()["status"] == "skipped"
