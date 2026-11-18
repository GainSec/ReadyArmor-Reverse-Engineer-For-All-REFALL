import json
from pathlib import Path

from ref_all_executor.report_enrich import enrich_findings, enrich_workbench_report, write_enriched


def test_enrich_findings_filters_garbage_and_deduplicates() -> None:
    entries = [
        {"kind": "finding", "title": "", "severity": "HIGH"},
        {"kind": "finding", "title": "SQL injection", "severity": "HIGH", "refs": ["endpoint:POST /login"]},
        {"kind": "finding", "title": "SQL injection", "severity": "HIGH", "refs": ["endpoint:POST /login"]},
        {"kind": "finding", "title": "Stored XSS", "severity": "LOW", "refs": ["source:web.py::render"]},
    ]

    enriched = enrich_findings(entries)

    assert [finding["title"] for finding in enriched["findings"]] == ["SQL injection", "Stored XSS"]
    assert enriched["sections"]["high-impact"][0]["title"] == "SQL injection"
    assert enriched["sections"]["other"][0]["title"] == "Stored XSS"
    assert enriched["attack_chains"][0]["findings"] == ["SQL injection", "Stored XSS"]


def test_write_enriched_is_idempotent(tmp_path: Path) -> None:
    enriched = enrich_findings([
        {"kind": "finding", "title": "Command injection", "severity": "CRITICAL", "refs": ["source:a.py::run"]},
    ])

    first = write_enriched(tmp_path, "alpha", enriched)
    second = write_enriched(tmp_path, "alpha", enriched)

    assert first == second
    findings = json.loads((tmp_path / "alpha/refall/enriched/findings/findings.json").read_text())
    assert findings[0]["title"] == "Command injection"


def test_enrich_findings_resolves_leads_and_groups_facts() -> None:
    entries = [
        {"kind": "finding", "title": "SQL injection in login", "severity": "HIGH"},
        {"kind": "lead", "title": "SQL injection login", "severity": "high"},
        {"kind": "lead", "title": "Review admin export", "severity": "medium"},
        {"kind": "fact", "title": "SPI flash bus exposed", "description": "SOIC-8 pads present"},
        {"kind": "fact", "title": "compiler version gcc 12.2", "description": "ELF note"},
        {"kind": "fact", "title": "POST /login route", "description": "HTTP login endpoint"},
    ]

    enriched = enrich_findings(entries)

    assert [(lead["title"], lead["status"]) for lead in enriched["leads"]] == [
        ("SQL injection login", "DONE"),
        ("Review admin export", "OPEN"),
    ]
    assert enriched["sections"]["architecture"][0]["title"] == "SPI flash bus exposed"
    assert enriched["sections"]["software"][0]["title"] == "compiler version gcc 12.2"
    assert enriched["sections"]["recon"][0]["title"] == "POST /login route"


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


def test_enrich_workbench_report_reads_ledger_writes_artifacts_and_assembles(tmp_path: Path) -> None:
    t = FakeTransport({
        ("GET", "/api/workbenches/alpha/ledger/entries"): (
            200,
            [{"kind": "finding", "title": "Command injection", "severity": "CRITICAL"}],
        ),
        ("GET", "/api/refall/reports/template"): (200, b"<!doctype html><h1>REFALL-V10 Report</h1>"),
        ("GET", "/api/workbenches/alpha"): (
            200,
            {"custom_fields": {"refall_current_report_object_id": "obj_report"}},
        ),
        ("PUT", "/api/workbenches/alpha/objects/obj_report/content"): (200, {"ok": True}),
    })

    out = enrich_workbench_report("alpha", "alpha", root=tmp_path, base="http://ab", transport=t)

    assert out["enriched"]["findings"][0]["title"] == "Command injection"
    assert Path(out["outputs"]["findings"]).is_file()
    assert out["assembled"]["mode"] == "updated"


def test_enrich_workbench_report_collects_runtime_and_gate_state(tmp_path: Path) -> None:
    t = FakeTransport({
        ("GET", "/api/workbenches/alpha/ledger/entries"): (
            200,
            [{"kind": "finding", "title": "Command injection", "severity": "CRITICAL"}],
        ),
        ("GET", "/api/workbenches/alpha/runtime/observations"): (
            200,
            [{"kind": "claim", "claim": "command reached runtime sink", "confidence": "high"}],
        ),
        ("GET", "/api/workbenches/alpha/runtime/artifacts"): (
            200,
            [{"id": "art_1", "kind": "codecharta-map", "path": "/tmp/map.cc.json", "mime": "application/json"}],
        ),
        ("GET", "/api/workbenches/alpha/runtime/evidence-graph"): (
            200,
            {"nodes": [{"id": "finding:command"}], "edges": []},
        ),
        ("GET", "/api/workbenches/alpha/closeout/gate"): (
            200,
            {"passed": True, "checks": [], "summary": {"pending_actions_open": 0}},
        ),
        ("GET", "/api/workbenches/alpha/pending-actions"): (
            200,
            [{"id": "pa_1", "kind": "operator_decision_needed", "title": "Need approval", "status": "open"}],
        ),
        ("GET", "/api/workbenches/alpha/capabilities"): (
            200,
            {"grants": [{"id": "cap_1", "class": "run_local_command", "reason": "loop launch"}], "requests": []},
        ),
        ("GET", "/api/refall/reports/template"): (200, b"<!doctype html><h1>REFALL-V10 Report</h1>"),
        ("GET", "/api/workbenches/alpha"): (
            200,
            {"custom_fields": {"refall_current_report_object_id": "obj_report"}},
        ),
        ("PUT", "/api/workbenches/alpha/objects/obj_report/content"): (200, {"ok": True}),
    })

    out = enrich_workbench_report("alpha", "alpha", root=tmp_path, base="http://ab", transport=t)

    runtime_path = Path(out["outputs"]["runtime"])
    runtime = json.loads(runtime_path.read_text())
    assert runtime["observations"][0]["claim"] == "command reached runtime sink"
    assert runtime["visual_artifacts"][0]["kind"] == "codecharta-map"
    assert runtime["pending_actions"][0]["title"] == "Need approval"
    assert runtime["capabilities"]["grants"][0]["class"] == "run_local_command"
    html = next(call[3].decode() for call in t.calls if call[0] == "PUT")
    assert "Runtime Evidence" in html
    assert "command reached runtime sink" in html
    assert "Pending Actions" in html
    assert "Capability Decisions" in html


def test_enrich_findings_preserves_dispositions_and_closeout_overrides() -> None:
    enriched = enrich_findings([
        {
            "kind": "disposition-transition",
            "finding_id": "find_1",
            "status": "accepted",
            "receipt_type": "chain_preservation",
            "summary": "Primitive retained for chaining.",
        },
        {
            "kind": "disposition-transition",
            "finding_id": "find_2",
            "status": "refused",
            "refusal_reasons": ["duplicate requires canonical finding"],
            "summary": "Duplicate was not proven.",
        },
        {
            "kind": "ops-event",
            "action": "closeout.override",
            "status": "accepted",
            "check_ids": ["pending-actions-open"],
            "summary": "Operator accepted residual item.",
        },
    ])

    runtime = enriched["runtime"]
    assert runtime["disposition_transitions"][0]["finding_id"] == "find_1"
    assert runtime["disposition_transitions"][1]["status"] == "refused"
    assert runtime["closeout_overrides"][0]["check_ids"] == ["pending-actions-open"]


def test_enrich_findings_projects_promotion_gate_refusals_outside_final_findings() -> None:
    enriched = enrich_findings([
        {
            "kind": "finding",
            "title": "Accepted command injection",
            "severity": "HIGH",
            "refs": ["app.py:10"],
        },
        {
            "kind": "ops-event",
            "action": "finding.promotion.refused",
            "status": "blocked",
            "summary": "finding promotion refused: missing evidence",
            "candidate": {"title": "Rejected command injection", "severity": "HIGH"},
            "reasons": ["missing evidence"],
        },
    ])

    assert [finding["title"] for finding in enriched["findings"]] == ["Accepted command injection"]
    assert enriched["runtime"]["promotion_gate_refusals"][0]["candidate"]["title"] == "Rejected command injection"


def test_enrich_findings_merges_related_duplicate_locations() -> None:
    enriched = enrich_findings([
        {
            "kind": "finding",
            "title": "Command injection",
            "severity": "HIGH",
            "vuln_class": "command-injection",
            "code_paths": ["app.py:10"],
            "related_locations": [{"path": "app.py", "anchor": "app.py:10"}],
        },
        {
            "kind": "finding",
            "title": "Command injection",
            "severity": "HIGH",
            "vuln_class": "command-injection",
            "code_paths": ["views.py:22"],
            "related_locations": [{"path": "views.py", "anchor": "views.py:22"}],
        },
    ])

    assert len(enriched["findings"]) == 1
    assert {"path": "views.py", "anchor": "views.py:22"} in enriched["findings"][0]["related_locations"]
