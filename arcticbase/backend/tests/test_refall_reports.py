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


def test_refall_report_spec_and_template_are_served(client: TestClient) -> None:
    index = client.get("/api/refall/reports/spec-index")
    assert index.status_code == 200, index.text
    files = index.json()["files"]
    assert "deliverable.md" in files
    assert "findings-standard.md" in files
    assert all("encrypt" not in name for name in files)

    spec = client.get("/api/refall/reports/spec/findings-standard.md")
    assert spec.status_code == 200, spec.text
    assert "REFALL finding" in spec.text

    template = client.get("/api/refall/reports/template")
    assert template.status_code == 200, template.text
    assert "REFALL-V10 Report" in template.text


def test_refall_report_spec_bundle_has_no_encryption_endpoint(client: TestClient) -> None:
    bundle = client.get("/api/refall/reports/spec")
    assert bundle.status_code == 200, bundle.text
    assert "report encryption" not in bundle.text.lower()

    encrypted = client.get("/api/refall/reports/encrypt")
    assert encrypted.status_code == 404


def test_current_report_uses_explicit_workbench_object_id(client: TestClient) -> None:
    created = client.post(
        "/api/workbenches",
        json={"title": "Alpha", "slug": "alpha", "tags": ["refall"]},
    )
    assert created.status_code == 201, created.text
    obj = client.post(
        "/api/workbenches/alpha/objects",
        json={
            "kind": "html",
            "title": "Current Report",
            "drawer": "Report",
            "filename": "report.html",
            "mime": "text/html",
            "content": "<!doctype html><title>Alpha Report</title><h1>Alpha</h1>",
        },
    ).json()
    patch = client.patch(
        "/api/workbenches/alpha",
        json={"custom_fields": {"refall_current_report_object_id": obj["id"]}},
    )
    assert patch.status_code == 200, patch.text

    report = client.get("/api/workbenches/alpha/refall-report")

    assert report.status_code == 200, report.text
    body = report.json()
    assert body["object_id"] == obj["id"]
    assert "Alpha Report" in body["content"]
