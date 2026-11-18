from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arctic_base.api.deps import get_storage
from arctic_base.main import app
from arctic_base.storage.filesystem import FilesystemStorage


EXPECTED_SUBJECT_DIRS = {
    "Notes",
    "Screenshots",
    "Exports-Downloads",
    "Exports-Downloads/firmware/extracted",
    "Import-Templates",
    "Import-Templates/external-docs",
    "Payloads",
    "PRJ",
    "Errors",
    "Output",
    "Report",
    "refallsubloop/services",
    "refallsubloop/mcp-servers",
    "refallsubloop/tools",
    "refallsubloop/config",
    "refallsubloop/logs/agents",
    "refallsubloop/logs/trajectories",
    "refallsubloop/logs/events",
    "refallsubloop/logs/loop",
    "refallsubloop/logs/infra",
    ".refall/conversations",
}


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    storage = FilesystemStorage(tmp_path / "data")
    monkeypatch.setenv("REFALL_SUBJECT_ROOT", str(tmp_path / "subjects"))
    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_create_refall_subject_creates_workbench_and_qedcs_layout(
    client: TestClient,
    tmp_path: Path,
) -> None:
    r = client.post(
        "/api/refall/subjects",
        json={
            "subject": "Example Subject",
            "title": "Example Subject",
            "description": "REFALL engagement subject",
            "source_path": "/input/example",
            "tags": ["firmware"],
        },
    )

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["subject"] == "example-subject"
    assert body["workbench_slug"] == "example-subject"
    assert body["subject_path"] == str(tmp_path / "subjects" / "example-subject")
    assert body["created"] is True

    subject_path = tmp_path / "subjects" / "example-subject"
    for rel in EXPECTED_SUBJECT_DIRS:
        assert (subject_path / rel).is_dir(), rel

    assert (subject_path / ".refall/subject_state.json").is_file()
    assert (subject_path / ".refall/evidence_ledger.json").is_file()

    wb = client.get("/api/workbenches/example-subject")
    assert wb.status_code == 200, wb.text
    meta = wb.json()
    assert meta["local_path"] == str(subject_path)
    assert meta["custom_fields"]["refall_subject"] == "example-subject"
    assert meta["custom_fields"]["refall_subject_path"] == str(subject_path)
    assert meta["custom_fields"]["refall_source_path"] == "/input/example"
    assert "refall" in meta["tags"]
    assert "subject" in meta["tags"]
    assert "firmware" in meta["tags"]


def test_subject_bootstrap_does_not_mirror_objects_by_default(client: TestClient) -> None:
    client.post("/api/refall/subjects", json={"subject": "No Mirror"})

    objects = client.get("/api/workbenches/no-mirror/objects").json()

    assert objects == []


def test_create_refall_subject_converts_existing_workbench(
    client: TestClient,
    tmp_path: Path,
) -> None:
    source = tmp_path / "target-src"
    source.mkdir()
    (source / "app.py").write_text("print('ara')\n", encoding="utf-8")
    client.post(
        "/api/workbenches",
        json={
            "title": "ARA-V10-VISUAL",
            "slug": "ara-v10-visual",
            "tags": ["visual"],
        },
    )

    r = client.post(
        "/api/refall/subjects",
        json={
            "subject": "ara-v10-visual",
            "title": "ARA-V10-VISUAL",
            "source_path": str(source),
            "tags": ["visual"],
        },
    )

    assert r.status_code == 201, r.text
    wb = client.get("/api/workbenches/ara-v10-visual").json()
    assert "refall" in wb["tags"]
    assert "subject" in wb["tags"]
    assert "visual" in wb["tags"]
    assert wb["custom_fields"]["refall_subject"] == "ara-v10-visual"
    assert wb["custom_fields"]["refall_source_path"] == str(source)
    assert Path(wb["custom_fields"]["refall_subject_path"]).is_dir()


def test_subject_mirror_endpoint_is_explicit(client: TestClient) -> None:
    client.post("/api/refall/subjects", json={"subject": "Mirror Me"})

    r = client.post("/api/refall/subjects/mirror-me/mirror-workbench")

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["workbench_slug"] == "mirror-me"
    assert body["object_id"].startswith("obj_")

    objects = client.get("/api/workbenches/mirror-me/objects?drawer=Subject").json()
    assert len(objects) == 1
    assert objects[0]["title"] == "REFALL Subject Manifest"
