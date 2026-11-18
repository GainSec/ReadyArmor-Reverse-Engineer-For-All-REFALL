from pathlib import Path
import time

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


def test_capability_grant_rejects_missing_operator_token_when_configured(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    _create_workbench(client)
    token_path = tmp_path / "operator-token"
    token_path.write_text("host-only-token\n")
    monkeypatch.setenv("REFALL_CAPABILITY_OPERATOR_TOKEN_PATH", str(token_path))

    r = client.post(
        "/api/workbenches/alpha/capabilities/grant",
        json={
            "class": "external_network",
            "scope": {"hosts": ["example.test"], "methods": ["HEAD"]},
            "granted_by": "codex",
            "reason": "An agent must not be able to impersonate the manager.",
        },
    )

    assert r.status_code == 403, r.text
    assert client.get("/api/workbenches/alpha/capabilities").json()["grants"] == []


def test_capability_grant_uses_authenticated_operator_identity(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:
    _create_workbench(client)
    token_path = tmp_path / "operator-token"
    token_path.write_text("host-only-token\n")
    monkeypatch.setenv("REFALL_CAPABILITY_OPERATOR_TOKEN_PATH", str(token_path))

    r = client.post(
        "/api/workbenches/alpha/capabilities/grant",
        headers={"X-REFALL-Operator-Token": "host-only-token"},
        json={
            "class": "external_network",
            "scope": {"hosts": ["example.test"], "methods": ["HEAD"]},
            "granted_by": "agent-controlled-value",
            "reason": "Authenticated host operator grant.",
        },
    )

    assert r.status_code == 201, r.text
    assert r.json()["granted_by"] == "operator"


def test_network_command_outside_scope_is_refused_and_ledgers(client: TestClient) -> None:
    _create_workbench(client)
    client.post(
        "/api/workbenches/alpha/capabilities/grant",
        json={
            "class": "lan_network_probe",
            "scope": {"hosts": ["192.0.2.10"], "ports": [80]},
            "granted_by": "operator",
            "reason": "Authorized target.",
        },
    )

    r = client.post(
        "/api/workbenches/alpha/execution/authorize",
        json={
            "requested_by": "agent",
            "capability_class": "lan_network_probe",
            "command": ["curl", "http://192.0.2.11:80/"],
            "declared_effects": ["network"],
            "target": {"host": "192.0.2.11", "port": 80, "scheme": "http"},
        },
    )

    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is False
    entries = client.get("/api/workbenches/alpha/ledger/entries?kind=capability-decision").json()
    assert entries[0]["status"] == "refused"


def test_lan_target_inside_scope_is_accepted(client: TestClient) -> None:
    _create_workbench(client)
    grant = client.post(
        "/api/workbenches/alpha/capabilities/grant",
        json={
            "class": "lan_network_probe",
            "scope": {"hosts": ["192.0.2.10"], "ports": [80, 81]},
            "granted_by": "operator",
            "reason": "Authorized target.",
        },
    )
    assert grant.status_code == 201, grant.text

    r = client.post(
        "/api/workbenches/alpha/execution/authorize",
        json={
            "requested_by": "agent",
            "capability_class": "lan_network_probe",
            "command": ["curl", "http://192.0.2.10:80/"],
            "declared_effects": ["network"],
            "target": {"host": "192.0.2.10", "port": 80, "scheme": "http"},
        },
    )

    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is True
    assert r.json()["grant_id"] == grant.json()["id"]


def test_network_http_method_outside_grant_scope_is_refused(client: TestClient) -> None:
    _create_workbench(client)
    client.post(
        "/api/workbenches/alpha/capabilities/grant",
        json={
            "class": "external_network",
            "scope": {
                "hosts": ["api.example.test"],
                "ports": [443],
                "methods": ["GET", "HEAD"],
            },
            "granted_by": "operator",
            "reason": "Passive validation only.",
        },
    )

    r = client.post(
        "/api/workbenches/alpha/execution/authorize",
        json={
            "requested_by": "agent",
            "capability_class": "external_network",
            "command": ["curl", "-X", "POST", "https://api.example.test/check"],
            "declared_effects": ["network"],
            "target": {
                "host": "api.example.test",
                "port": 443,
                "scheme": "https",
                "method": "POST",
            },
        },
    )

    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is False
    assert "HTTP method outside grant scope" in r.json()["refusal_reasons"]


def test_network_request_omitting_method_is_refused_when_grant_scopes_methods(
    client: TestClient,
) -> None:
    _create_workbench(client)
    client.post(
        "/api/workbenches/alpha/capabilities/grant",
        json={
            "class": "external_network",
            "scope": {
                "hosts": ["api.example.test"],
                "ports": [443],
                "methods": ["GET", "HEAD"],
            },
            "granted_by": "operator",
            "reason": "Passive validation only.",
        },
    )

    r = client.post(
        "/api/workbenches/alpha/execution/authorize",
        json={
            "requested_by": "agent",
            "capability_class": "external_network",
            "command": ["custom-http-client", "https://api.example.test/check"],
            "declared_effects": ["network"],
            "target": {
                "host": "api.example.test",
                "port": 443,
                "scheme": "https",
            },
        },
    )

    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is False
    assert "HTTP method required by grant scope" in r.json()["refusal_reasons"]


def test_write_outside_subject_root_is_refused(client: TestClient) -> None:
    _create_workbench(client)
    client.post(
        "/api/workbenches/alpha/capabilities/grant",
        json={
            "class": "write_subject",
            "scope": {"paths": ["/tmp/refall-subject"]},
            "granted_by": "operator",
            "reason": "Subject output.",
        },
    )

    r = client.post(
        "/api/workbenches/alpha/execution/authorize",
        json={
            "requested_by": "agent",
            "capability_class": "write_subject",
            "command": ["touch", "/etc/passwd"],
            "declared_effects": ["write"],
            "target": {"path": "/etc/passwd"},
        },
    )

    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is False


def test_destructive_request_requires_dry_run_and_token(client: TestClient) -> None:
    _create_workbench(client)
    client.post(
        "/api/workbenches/alpha/capabilities/grant",
        json={
            "class": "destructive_action",
            "scope": {"paths": ["/tmp/refall-subject"]},
            "granted_by": "operator",
            "reason": "Cleanup approved.",
            "dry_run_required": True,
            "destructive_token_required": True,
        },
    )

    missing = client.post(
        "/api/workbenches/alpha/execution/authorize",
        json={
            "requested_by": "agent",
            "capability_class": "destructive_action",
            "command": ["rm", "-rf", "/tmp/refall-subject/out"],
            "declared_effects": ["destructive"],
            "target": {"path": "/tmp/refall-subject/out"},
            "dry_run": False,
        },
    )
    assert missing.status_code == 200, missing.text
    assert missing.json()["accepted"] is False

    accepted = client.post(
        "/api/workbenches/alpha/execution/authorize",
        json={
            "requested_by": "agent",
            "capability_class": "destructive_action",
            "command": ["rm", "-rf", "/tmp/refall-subject/out"],
            "declared_effects": ["destructive"],
            "target": {"path": "/tmp/refall-subject/out"},
            "dry_run": True,
            "destructive_approval_token": "destructive-approval",
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["accepted"] is True


def test_agent_cannot_authorize_its_own_live_action(client: TestClient) -> None:
    _create_workbench(client)
    client.post(
        "/api/workbenches/alpha/capabilities/grant",
        json={
            "class": "lan_network_probe",
            "scope": {"hosts": ["192.0.2.10"], "ports": [80]},
            "granted_by": "agent-cid",
            "reason": "Self-issued grant must not authorize.",
        },
    )

    r = client.post(
        "/api/workbenches/alpha/execution/authorize",
        json={
            "requested_by": "agent-cid",
            "capability_class": "lan_network_probe",
            "command": ["curl", "http://192.0.2.10:80/"],
            "declared_effects": ["network"],
            "target": {"host": "192.0.2.10", "port": 80, "scheme": "http"},
        },
    )

    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is False
    assert "agents cannot authorize their own live actions" in r.json()["refusal_reasons"]


def test_run_local_command_requires_path_scope(client: TestClient) -> None:
    _create_workbench(client)
    client.post(
        "/api/workbenches/alpha/capabilities/grant",
        json={
            "class": "run_local_command",
            "scope": {},
            "granted_by": "operator",
            "reason": "Unscoped process grant must not authorize.",
        },
    )

    r = client.post(
        "/api/workbenches/alpha/execution/authorize",
        json={
            "requested_by": "refall-ops-command",
            "capability_class": "run_local_command",
            "command": ["python", "-m", "ref_all_executor.standing_loop"],
            "declared_effects": ["process"],
            "target": {"path": "/tmp/refall-subject"},
        },
    )

    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is False
    assert "target path scope required" in r.json()["refusal_reasons"]


def test_docker_command_cannot_hide_behind_process_effect(client: TestClient) -> None:
    _create_workbench(client)
    client.post(
        "/api/workbenches/alpha/capabilities/grant",
        json={
            "class": "run_local_command",
            "scope": {"paths": ["/tmp/refall-subject"]},
            "granted_by": "operator",
            "reason": "Generic process grant.",
        },
    )

    r = client.post(
        "/api/workbenches/alpha/execution/authorize",
        json={
            "requested_by": "agent",
            "capability_class": "run_local_command",
            "command": ["zsh", "-lc", "docker compose up -d"],
            "declared_effects": ["process"],
            "target": {"path": "/tmp/refall-subject"},
        },
    )

    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is False
    assert "Docker command requires Docker capability" in r.json()["refusal_reasons"]


def test_codebadger_command_requires_codebadger_capability(client: TestClient, tmp_path: Path) -> None:
    _create_workbench(client)
    client.post(
        "/api/workbenches/alpha/capabilities/grant",
        json={
            "class": "docker_control",
            "scope": {"paths": ["/tmp/refall-subject"]},
            "granted_by": "operator",
            "reason": "Plain Docker only.",
        },
    )

    r = client.post(
        "/api/workbenches/alpha/execution/authorize",
        json={
            "requested_by": "agent",
            "capability_class": "docker_control",
            "command": [str(tmp_path / "refall/toolchain/bin/codebadger-service"), "supervise"],
            "declared_effects": ["docker"],
            "target": {"path": "/tmp/refall-subject"},
        },
    )

    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is False
    assert "Codebadger command requires codebadger capability" in r.json()["refusal_reasons"]


def test_destructive_command_cannot_hide_behind_process_effect(client: TestClient) -> None:
    _create_workbench(client)
    client.post(
        "/api/workbenches/alpha/capabilities/grant",
        json={
            "class": "run_local_command",
            "scope": {"paths": ["/tmp/refall-subject"]},
            "granted_by": "operator",
            "reason": "Generic process grant.",
        },
    )

    r = client.post(
        "/api/workbenches/alpha/execution/authorize",
        json={
            "requested_by": "agent",
            "capability_class": "run_local_command",
            "command": ["rm", "-rf", "/tmp/refall-subject/out"],
            "declared_effects": ["process"],
            "target": {"path": "/tmp/refall-subject/out"},
        },
    )

    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is False
    assert "destructive command requires destructive capability" in r.json()["refusal_reasons"]


def test_expired_capability_grant_is_not_accepted(client: TestClient) -> None:
    _create_workbench(client)
    grant = client.post(
        "/api/workbenches/alpha/capabilities/grant",
        json={
            "class": "lan_network_probe",
            "scope": {"hosts": ["192.0.2.10"], "ports": [80]},
            "granted_by": "operator",
            "reason": "Short-lived target probe.",
            "expires_at": time.time() - 1,
        },
    )
    assert grant.status_code == 201, grant.text

    r = client.post(
        "/api/workbenches/alpha/execution/authorize",
        json={
            "requested_by": "agent",
            "capability_class": "lan_network_probe",
            "command": ["curl", "http://192.0.2.10:80/"],
            "declared_effects": ["network"],
            "target": {"host": "192.0.2.10", "port": 80, "scheme": "http"},
        },
    )

    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is False
    assert "no matching unexpired grant for requested scope" in r.json()["refusal_reasons"]
