import pytest
from fastapi.testclient import TestClient
from coverage_service import app as appmod, db as dbmod
from coverage_service.store import Store


@pytest.fixture
def client(tmp_path, monkeypatch):
    conn = dbmod.connect(str(tmp_path / "c.db"))
    dbmod.init_schema(conn)
    store = Store(conn)
    monkeypatch.setattr(appmod, "STORE", store)
    return TestClient(appmod.app)


def test_enumerate_then_claim_submit_flow(client):
    r = client.post("/enumerate", json={"subject": "bra", "files": [
        {"path": "a.py", "total_lines": 3, "symbols": [{"name": "f", "line_start": 1, "line_end": 3}]}]})
    assert r.status_code == 200 and r.json()["units"] >= 3
    u = client.post("/claim_next", json={"subject": "bra", "agent": "A"}).json()
    assert u["type"] in ("symbol", "line_range")
    bad = client.post("/submit", json={"unit_id": u["id"], "agent": "A", "summary": "x", "evidence": []})
    assert bad.status_code == 422
    ok = client.post("/submit", json={"unit_id": u["id"], "agent": "A", "summary": "x",
                                       "evidence": [{"file": "a.py", "line_start": 1, "line_end": 3}]})
    assert ok.status_code == 200
    assert client.get("/coverage", params={"subject": "bra"}).json()["characterized_pct"] == 100.0


def test_gate_endpoint(client):
    client.post("/enumerate", json={"subject": "bra", "files": [{"path": "a.py", "total_lines": 5, "symbols": []}]})
    assert client.get("/gate", params={"subject": "bra"}).json()["locked"] is True


def test_dashboard_is_operator_console(client):
    html = client.get("/").text
    # self-contained SPA that fetches the endpoints client-side
    assert "Operator Console" in html
    assert "/subjects" in html and "/wishlist" in html and "/funnel" in html
    assert "Findings" in html and "INFO.md" in html


def test_api_allows_browser_preflight_for_agent_posts(client):
    rv = client.options("/review_finding", headers={
        "Origin": "http://host.docker.internal",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })

    assert rv.status_code in (200, 204)
    assert rv.headers["access-control-allow-origin"] == "*"


def test_dashboard_moves_false_positives_to_collapsed_section(client):
    html = client.get("/").text
    assert "nonRejectedFindings" in html
    assert "rejectedFindings" in html
    assert "chainableFindings" in html
    assert "DUPLICATE" in html
    assert "<details class=\"fp-section\">" in html
    assert "<summary>False positives / duplicates" in html
    assert "<summary>Chainable / deferred findings" in html


def test_dashboard_non_rejected_findings_include_trace_and_runtime_viability(client):
    html = client.get("/").text
    assert "findingTrace" in html
    assert "End-to-end trace" in html
    assert "Runtime validation viability" in html
    assert "Runtime proof target" in html


def test_subjects_endpoint_shape(client, tmp_path, monkeypatch):
    (tmp_path / "subjA").mkdir()
    (tmp_path / ".hidden").mkdir()
    monkeypatch.setattr(appmod, "SUBJECTS_ROOT", str(tmp_path))
    subs = client.get("/subjects").json()
    names = {s["subject"] for s in subs}
    assert "subjA" in names and ".hidden" not in names
    a = next(s for s in subs if s["subject"] == "subjA")
    assert a["root_container"] == "/projects/subjA" and a["has_context"] is False


def test_search_endpoint(client):
    client.post("/enumerate", json={"subject": "bra", "files": [
        {"path": "a.py", "total_lines": 4, "symbols": [{"name": "login", "line_start": 1, "line_end": 4}]}]})
    hits = client.get("/search", params={"subject": "bra", "type": "symbol"}).json()
    assert any(h["name"] == "login" for h in hits)


def test_finding_lifecycle_endpoints(client):
    bad = client.post("/finding", json={"finding": {"subject": "bra", "title": "x", "code_paths": []}})
    assert bad.status_code == 422                       # no evidence anchor
    f = client.post("/finding", json={"finding": {"subject": "bra", "title": "Auth bypass",
        "severity": "HIGH", "code_paths": ["auth.py:12"]}}).json()
    assert f["status"] == "PROVISIONALLY_VALID"
    rv = client.post("/review_finding", json={"finding_id": f["id"], "agent": "rev",
        "status": "VALID", "reasoning": "triggerable"}).json()
    assert rv["status"] == "VALID"
    assert len(client.get("/findings", params={"subject": "bra", "status": "VALID"}).json()) == 1
    assert client.get("/findings_summary", params={"subject": "bra"}).json()["by_severity"] == {"HIGH": 1}


def test_finding_validation_endpoint_updates_runtime_fields(client):
    f = client.post("/finding", json={"finding": {"subject": "bra", "title": "Overflow",
        "severity": "HIGH", "status": "VALID", "code_paths": ["bin:sym.func@0x1"]}}).json()

    rv = client.post("/finding_validation", json={
        "finding_id": f["id"],
        "agent": "validator-A",
        "production_viability": "Runtime validation is directly actionable with a crafted request.",
        "repro_status": "runtime_viable",
        "repro_hints": "Dynamic repro: send crafted request. Expected dynamic proof: crash.",
        "critic_reasoning": "Visual trace: request -> parser -> unchecked sink.",
        "patch_status": "unpatched",
    }).json()

    assert rv["status"] == "VALID"
    assert rv["production_viability"].startswith("Runtime validation")
    assert rv["repro_status"] == "runtime_viable"
    assert rv["critic_reasoning"].startswith("Visual trace")


def test_finding_validation_endpoint_replaces_runtime_fields(client):
    f = client.post("/finding", json={"finding": {"subject": "bra", "title": "Overflow",
        "severity": "HIGH", "status": "VALID", "code_paths": ["bin:sym.func@0x1"]}}).json()
    client.post("/finding_validation", json={
        "finding_id": f["id"],
        "agent": "validator-A",
        "production_viability": "First PoC attempt was blocked before reaching the parser.",
        "repro_status": "NOT_PROVEN",
        "critic_reasoning": "Raw output: document-format-error.",
    })

    rv = client.post("/finding_validation", json={
        "finding_id": f["id"],
        "agent": "validator-B",
        "production_viability": "Improved PoC reached runtime proof.",
        "repro_status": "runtime_confirmed",
        "critic_reasoning": "Raw output: injected marker appeared in web UI.",
    }).json()

    assert rv["repro_status"] == "runtime_confirmed"
    assert rv["production_viability"].startswith("Improved PoC")
    assert rv["critic_reasoning"].startswith("Raw output: injected marker")


def test_loop_capabilities_endpoint_advertises_base_global_capabilities(client):
    rv = client.get("/loop/capabilities", params={"subject": "example-subject"}).json()

    assert rv["subject"] == "example-subject"
    assert rv["host_actions"] == []
    assert any(capability["id"] == "saleae_logic_mcp" for capability in rv["global_capabilities"])
    saleae = next(capability for capability in rv["global_capabilities"] if capability["id"] == "saleae_logic_mcp")
    assert saleae["class"] == "physical_capture"
    assert "Manager-mediated" in saleae["access"]
    assert "put the probes on the pads" in saleae["operator_prompt"]
    assert any("UART" in protocol for protocol in saleae["protocols"])
    assert any("SPI" in protocol for protocol in saleae["protocols"])
    assert "read-only" in " ".join(saleae["guardrails"]).lower()
    assert any(capability["id"] == "autoprober_smart_powerstrip" for capability in rv["global_capabilities"])
    powerstrip = next(
        capability
        for capability in rv["global_capabilities"]
        if capability["id"] == "autoprober_smart_powerstrip"
    )
    assert powerstrip["class"] == "power_control"
    assert "Manager-mediated" in powerstrip["access"]
    assert "Configure endpoint mapping" in powerstrip["access"]
    assert powerstrip["matter_node_id"] == 1
    assert powerstrip["endpoints"]["1"] == "Outlet 1"
    assert powerstrip["endpoints"]["4"] == "Outlet 4"
    assert powerstrip["endpoints"]["5"] == "USB ports"
    assert any("power-cycle" in action for action in powerstrip["safe_actions"])
    assert any("concurrently" in note for note in powerstrip["recovery_notes"])
    assert "explicit" in " ".join(powerstrip["guardrails"]).lower()
    assert "shared" in " ".join(powerstrip["guardrails"]).lower()
    assert "create_or_improve_script" in rv["workflow"]
    assert "record_validation_or_demote" in rv["workflow"]

def test_plan_and_investigation_endpoints(client):
    n = client.post("/plan", json={"subject": "bra", "investigations": [
        {"title": "Auth", "target_files": ["auth.py"], "question": "trace tokens", "priority": 1},
        {"title": "Upload", "target_files": ["up.py"], "question": "trace paths", "priority": 2}]}).json()
    assert n["investigations"] == 2
    i1 = client.post("/claim_investigation", json={"subject": "bra", "agent": "A"}).json()
    assert i1["title"] == "Auth"                        # priority order
    client.post("/complete_investigation", json={"investigation_id": i1["id"], "agent": "A"})
    assert client.get("/plan_progress", params={"subject": "bra"}).json()["done"] == 1
