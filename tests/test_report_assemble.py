import json

from ref_all_executor.report_assemble import assemble_report


class FakeTransport:
    def __init__(self, script):
        self.script = script
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        for (m, suffix), response in self.script.items():
            if method == m and url.endswith(suffix):
                status, data = response
                return status, json.dumps(data).encode() if not isinstance(data, bytes) else data
        raise AssertionError(f"unexpected {method} {url}")


def test_assemble_report_updates_current_object() -> None:
    enriched = {
        "findings": [{"title": "Command injection", "severity": "CRITICAL", "impact": "RCE"}],
        "sections": {"high-impact": [], "other": []},
        "attack_chains": [],
    }
    t = FakeTransport({
        ("GET", "/api/refall/reports/template"): (200, b"<!doctype html><h1>REFALL-V10 Report</h1>"),
        ("GET", "/api/workbenches/alpha"): (
            200,
            {"custom_fields": {"refall_current_report_object_id": "obj_report"}},
        ),
        ("PUT", "/api/workbenches/alpha/objects/obj_report/content"): (200, {"ok": True}),
    })

    result = assemble_report("alpha", "alpha", enriched, base="http://ab", transport=t)

    assert result == {"workbench": "alpha", "object_id": "obj_report", "mode": "updated"}
    assert "Command injection" in next(call[3].decode() for call in t.calls if call[0] == "PUT")


def test_assemble_report_refuses_to_replace_richer_native_report() -> None:
    enriched = {"findings": [], "leads": [], "sections": {}, "attack_chains": []}
    current = """
    <section id="methodology"><h2>Methodology</h2><p>Static validation.</p></section>
    <section id="architecture"><h2>Architecture</h2><p>Updater boundary.</p></section>
    <section id="flows"><h2>Flows</h2><p>manifest to firmware</p></section>
    """
    t = FakeTransport({
        ("GET", "/api/refall/reports/template"): (200, b"<!doctype html><h1>REFALL AB Report</h1>"),
        ("GET", "/api/workbenches/alpha"): (
            200, {"custom_fields": {"refall_current_report_object_id": "obj_report"}},
        ),
        ("GET", "/api/workbenches/alpha/refall-report"): (
            200, {"object_id": "obj_report", "content": current},
        ),
    })

    result = assemble_report("alpha", "alpha", enriched, base="http://ab", transport=t)

    assert result["mode"] == "downgrade_refused"
    assert {"methodology", "architecture", "flows"}.issubset(result["lost_sections"])
    assert not any(call[0] == "PUT" for call in t.calls)


def test_assemble_report_renders_leads_and_fact_sections() -> None:
    enriched = {
        "findings": [],
        "leads": [{"title": "Review admin export", "status": "OPEN", "severity": "medium"}],
        "sections": {
            "high-impact": [],
            "other": [],
            "recon": [{"title": "POST /login route", "description": "HTTP endpoint"}],
            "architecture": [{"title": "SPI flash bus exposed", "description": "SOIC-8 pads"}],
            "software": [{"title": "compiler version gcc 12.2", "description": "ELF note"}],
        },
        "attack_chains": [],
    }
    t = FakeTransport({
        ("GET", "/api/refall/reports/template"): (200, b"<!doctype html><h1>REFALL-V10 Report</h1>"),
        ("GET", "/api/workbenches/alpha"): (
            200,
            {"custom_fields": {"refall_current_report_object_id": "obj_report"}},
        ),
        ("PUT", "/api/workbenches/alpha/objects/obj_report/content"): (200, {"ok": True}),
    })

    assemble_report("alpha", "alpha", enriched, base="http://ab", transport=t)

    html = next(call[3].decode() for call in t.calls if call[0] == "PUT")
    assert "Review admin export" in html
    assert "POST /login route" in html
    assert "SPI flash bus exposed" in html
    assert "compiler version gcc 12.2" in html


def test_assemble_report_renders_runtime_gate_and_visual_artifacts() -> None:
    enriched = {
        "findings": [],
        "leads": [],
        "sections": {},
        "attack_chains": [],
        "runtime": {
            "observations": [{"kind": "claim", "claim": "PoC reached command sink", "confidence": "high"}],
            "artifacts": [{"id": "art_1", "kind": "codebadger-graph", "path": "/tmp/graph.html", "mime": "text/html"}],
            "visual_artifacts": [{"id": "art_1", "kind": "codebadger-graph", "path": "/tmp/graph.html", "mime": "text/html"}],
            "evidence_graph": {"nodes": [{"id": "finding:1"}], "edges": [{"id": "edge:1"}]},
            "pending_actions": [{"id": "pa_1", "title": "Need approval", "status": "open", "kind": "operator_decision_needed"}],
            "capabilities": {"grants": [{"id": "cap_1", "class": "lan_network_probe", "reason": "scope"}], "requests": []},
            "capability_decisions": [{"status": "accepted", "capability_class": "lan_network_probe", "summary": "authorized"}],
            "disposition_transitions": [
                {
                    "finding_id": "find_1",
                    "status": "refused",
                    "receipt_type": None,
                    "refusal_reasons": ["missing duplicate equivalence"],
                    "summary": "Duplicate not proven.",
                }
            ],
            "closeout_overrides": [
                {
                    "status": "accepted",
                    "check_ids": ["pending-actions-open"],
                    "summary": "Operator accepted residual item.",
                }
            ],
            "closeout_gate": {
                "passed": False,
                "checks": [{"id": "valid-findings-missing-proof", "status": "fail", "blocking": True, "count": 1}],
                "summary": {"unvalidated_findings": 1},
            },
        },
    }
    t = FakeTransport({
        ("GET", "/api/refall/reports/template"): (200, b"<!doctype html><h1>REFALL-V10 Report</h1>"),
        ("GET", "/api/workbenches/alpha"): (
            200,
            {"custom_fields": {"refall_current_report_object_id": "obj_report"}},
        ),
        ("PUT", "/api/workbenches/alpha/objects/obj_report/content"): (200, {"ok": True}),
    })

    assemble_report("alpha", "alpha", enriched, base="http://ab", transport=t)

    html = next(call[3].decode() for call in t.calls if call[0] == "PUT")
    assert "Runtime Evidence" in html
    assert "PoC reached command sink" in html
    assert "Visual Evidence" in html
    assert "codebadger-graph" in html
    assert "Closeout Gate" in html
    assert "valid-findings-missing-proof" in html
    assert "Pending Actions" in html
    assert "Need approval" in html
    assert "Capability Decisions" in html
    assert "lan_network_probe" in html
    assert "Disposition Transitions" in html
    assert "missing duplicate equivalence" in html
    assert "Closeout Overrides" in html
    assert "pending-actions-open" in html
