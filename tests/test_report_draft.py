import json

from ref_all_executor.report_draft import (
    _populated_report_sections,
    _structural_downgrade_sections,
    build_html_report,
    draft_report,
)


class FakeTransport:
    def __init__(self, script):
        self.script = script
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        for (m, suffix), response in self.script.items():
            if method == m and url.endswith(suffix):
                status, data = response
                if isinstance(data, bytes):
                    return status, data
                return status, json.dumps(data).encode()
        raise AssertionError(f"unexpected {method} {url}")


def test_structural_downgrade_detects_loss_of_populated_required_sections() -> None:
    existing = """
    <section id="methodology"><h2>Methodology</h2><p>Static and runtime validation.</p></section>
    <section id="architecture"><h2>Architecture</h2><p>Updater to bootloader trust boundary.</p></section>
    <section id="flows"><h2>Flows</h2><p>client -&gt; manifest -&gt; firmware</p></section>
    """
    sparse = """
    <section id="methodology"><h2>Methodology</h2><p class="empty">None recorded.</p></section>
    <section id="architecture"><h2>Architecture</h2><p class="empty">None recorded.</p></section>
    <section id="flows"><h2>Flows</h2><p>client -&gt; manifest -&gt; firmware</p></section>
    """

    assert _structural_downgrade_sections(existing, sparse) == [
        "methodology",
        "architecture",
    ]


def test_structural_downgrade_allows_equal_or_richer_formatting_changes() -> None:
    existing = '<section id="architecture"><h2>Architecture</h2><p>Updater boundary</p></section>'
    richer = (
        '<section class="panel" id="architecture"><h2>Architecture &amp; Attack Surface</h2>'
        '<table><tr><td>Updater boundary</td></tr></table></section>'
    )

    assert _structural_downgrade_sections(existing, richer) == []


def test_structural_downgrade_understands_template_details_sections() -> None:
    existing = (
        '<details class="panel" id="architecture"><summary>Architecture</summary>'
        '<div data-refall-slot="architecture"><table><tr><td>Updater boundary</td>'
        '</tr></table></div></details>'
    )
    sparse_template = (
        '<details class="panel" id="architecture"><summary>Architecture</summary>'
        '<div data-refall-slot="architecture"><p class="empty">None recorded.</p></div>'
        '</details>'
    )

    assert _structural_downgrade_sections(existing, sparse_template) == [
        "architecture"
    ]


def test_draft_report_creates_current_report_object() -> None:
    t = FakeTransport({
        ("GET", "/api/workbenches/alpha"): (
            200,
            {"slug": "alpha", "title": "Alpha", "custom_fields": {}},
        ),
        ("GET", "/api/workbenches/alpha/coverage/stats"): (
            200,
            {"resolved_pct": 50.0, "lines_total": 10, "lines_covered": 5, "symbols_total": 2},
        ),
        ("GET", "/api/workbenches/alpha/ledger/entries"): (
            200,
            [{"kind": "finding", "title": "SQL injection", "severity": "HIGH"}],
        ),
        ("GET", "/api/workbenches/alpha/ledger/stats"): (
            200,
            {"total": 1, "by_kind": {"finding": 1}, "by_severity": {"HIGH": 1}},
        ),
        ("POST", "/api/workbenches/alpha/objects"): (201, {"id": "obj_report"}),
        ("PATCH", "/api/workbenches/alpha"): (200, {"ok": True}),
    })

    result = draft_report("alpha", "alpha", base="http://ab", transport=t)

    assert result == {"workbench": "alpha", "object_id": "obj_report", "mode": "created"}
    created = json.loads(next(call[3] for call in t.calls if call[0] == "POST"))
    assert created["kind"] == "html"
    assert created["drawer"] == "Report"
    assert "SQL injection" in created["content"]
    patched = json.loads(t.calls[-1][3])
    assert patched["custom_fields"]["refall_current_report_object_id"] == "obj_report"


def test_mapping_mode_report_uses_ara_codex_theme_and_visual() -> None:
    html = build_html_report(
        workbench="agent-ready-armor",
        subject="agent-ready-armor",
        coverage={
            "files_done": 300,
            "files_total": 300,
            "lines_covered": 148844,
            "lines_total": 148844,
            "resolved_pct": 100.0,
        },
        ledger_entries=[{"kind": "fact", "title": "arch:component | forge", "description": "src/ara/forge/cli.py:1-10"}],
        ledger_stats={"by_kind": {"fact": 1}},
        mapping_mode=True,
    )

    assert "ARA Source Mapping Codex" in html
    assert "REFALL Security Report" not in html
    assert "#0a0e18" in html and "#ffd166" in html and "#4aa6cc" in html
    assert "<svg" in html
    assert "Coverage-to-codex visual" in html


def test_security_report_preserves_all_required_spec_sections_when_empty() -> None:
    rendered = build_html_report(
        workbench="alpha",
        subject="alpha",
        coverage={"resolved_pct": 0, "lines_total": 0, "lines_covered": 0},
        ledger_entries=[],
        ledger_stats={"total": 0},
    )

    required = {
        "scope",
        "methodology",
        "coverage",
        "evidence-ledger",
        "findings-validated",
        "findings-provisional",
        "false-positives",
        "attack-chains",
        "architecture",
        "flows",
        "repro",
        "remediation",
        "pending-actions",
        "runtime-evidence",
        "runtime-warnings",
        "capability-decisions",
        "freshness",
        "visual-evidence",
        "provenance",
        "closeout-gate",
    }
    for anchor in required:
        assert f'id="{anchor}"' in rendered
        assert f'href="#{anchor}"' in rendered

    assert "None recorded." in rendered


def test_security_report_uses_finding_name_when_title_is_absent() -> None:
    rendered = build_html_report(
        workbench="alpha",
        subject="alpha",
        coverage={"resolved_pct": 0, "lines_total": 1, "lines_covered": 0},
        ledger_entries=[{
            "kind": "finding",
            "name": "ActionBar response fields execute as JavaScript",
            "severity": "MEDIUM",
            "impact": "Conditional script execution",
            "code_paths": ["app.js:10"],
        }],
        ledger_stats={"total": 1, "by_kind": {"finding": 1}},
    )

    assert "ActionBar response fields execute as JavaScript" in rendered
    assert "untitled" not in rendered


def test_security_report_populates_required_evidence_summaries() -> None:
    rendered = build_html_report(
        workbench="alpha",
        subject="alpha",
        coverage={
            "files_total": 5,
            "files_done": 0,
            "lines_total": 100,
            "lines_covered": 0,
            "resolved_pct": 0,
        },
        ledger_entries=[
            {
                "kind": "finding",
                "name": "Conditional eval sink",
                "status": "PROVISIONALLY_VALID",
                "severity": "HIGH",
                "impact": "Conditional script execution",
                "code_paths": ["app.js:10"],
                "reproduction_steps": ["Inspect app.js:10."],
                "remediation": "Remove eval.",
            },
            {
                "kind": "fact",
                "title": "arch:scope",
                "description": "Local read-only source review.",
                "phase": "identify",
                "source_anchors": ["app.js:10"],
            },
            {
                "kind": "fact",
                "fact_kind": "flow",
                "flow": {
                    "from": "response",
                    "to": "eval",
                    "relation": "taints",
                    "evidence": "app.js:10",
                },
            },
        ],
        ledger_stats={"total": 3, "by_kind": {"finding": 1, "fact": 2}},
        nonfatal_errors=[{"summary": "bounded preflight warning"}],
        run_manifest={
            "run_id": "run-1",
            "source_hashes": {"app.js": "sha256:x"},
            "config_hashes": {"lanes": "sha256:y"},
        },
    )

    populated = _populated_report_sections(rendered)
    assert {
        "scope",
        "methodology",
        "coverage",
        "evidence-ledger",
        "findings-validated",
        "false-positives",
        "attack-chains",
        "repro",
        "remediation",
        "runtime-warnings",
        "freshness",
        "visual-evidence",
        "provenance",
    } <= populated


def test_mapping_mode_report_includes_equipment_digest_from_resolved_receipt() -> None:
    html = build_html_report(
        workbench="agent-ready-armor",
        subject="agent-ready-armor",
        coverage={
            "files_done": 300,
            "files_total": 300,
            "lines_covered": 148844,
            "lines_total": 148844,
            "resolved_pct": 100.0,
        },
        ledger_entries=[],
        ledger_stats={"by_kind": {"lead": 1}},
        pending_actions=[{
            "kind": "mapping_report_gap",
            "title": "Integrate ARA equipment and capability concepts",
            "status": "done",
            "resolution_receipt": {
                "receipt": {
                    "summary": "Integrated source-backed equipment/capability mapping guidance for Armor, Weapon, Packs, Tempers/Temper, Trim, Forge/Reforge, chunks/bytes/crumbs/alphabets, Rhema, Absolute, Shadow, Canary, Policy, Bulwark, Courtyard, Sew, Tailor, Keep, TOD, Danger, Task, Spoils, Hermes.",
                    "evidence_refs": [
                        "src/ara/weapons.py",
                        "src/ara/tempers.py",
                        "src/ara/armors.py",
                        "src/ara/forge/alphabets/pack.py",
                    ],
                }
            },
        }],
        mapping_mode=True,
    )

    assert "Capability/Equipment Mapping" in html
    assert "Weapon" in html
    assert "Tempers" in html
    assert "crumbs" in html
    assert "Courtyard" in html
    assert "TOD" in html
    assert "Spoils" in html
    assert "src/ara/weapons.py" in html


def test_draft_report_fetches_terminal_pending_actions_in_mapping_mode() -> None:
    t = FakeTransport({
        ("GET", "/api/workbenches/alpha"): (
            200,
            {
                "slug": "alpha",
                "title": "Alpha",
                "custom_fields": {
                    "refall_no_findings": "true",
                    "refall_current_report_object_id": "obj_old",
                },
            },
        ),
        ("GET", "/api/workbenches/alpha/coverage/stats"): (
            200,
            {"resolved_pct": 100.0, "lines_total": 10, "lines_covered": 10, "files_total": 1, "files_done": 1},
        ),
        ("GET", "/api/workbenches/alpha/ledger/entries"): (200, []),
        ("GET", "/api/workbenches/alpha/ledger/stats"): (200, {"total": 1, "by_kind": {"lead": 1}}),
        ("GET", "/api/workbenches/alpha/pending-actions?include_terminal=true"): (
            200,
            [{
                "kind": "mapping_report_gap",
                "status": "done",
                "resolution_receipt": {
                    "receipt": {
                        "summary": "Weapon Tempers Hermes",
                        "evidence_refs": ["src/ara/weapons.py", "src/ara/tempers.py"],
                    }
                },
            }],
        ),
        ("PUT", "/api/workbenches/alpha/objects/obj_old/content"): (200, {"ok": True}),
    })

    draft_report("alpha", "alpha", base="http://ab", transport=t)

    requested = [call[1] for call in t.calls if call[0] == "GET"]
    assert any(url.endswith("/api/workbenches/alpha/pending-actions?include_terminal=true") for url in requested)
    body = next(call[3].decode() for call in t.calls if call[0] == "PUT")
    assert "Capability/Equipment Mapping" in body
    assert "Weapon" in body
    assert "Tempers" in body


def test_draft_report_updates_existing_current_report_object() -> None:
    t = FakeTransport({
        ("GET", "/api/workbenches/alpha"): (
            200,
            {"slug": "alpha", "title": "Alpha", "custom_fields": {"refall_current_report_object_id": "obj_old"}},
        ),
        ("GET", "/api/workbenches/alpha/coverage/stats"): (
            200,
            {"resolved_pct": 100.0, "lines_total": 10, "lines_covered": 10, "symbols_total": 2},
        ),
        ("GET", "/api/workbenches/alpha/ledger/entries"): (
            200,
            [{"kind": "finding", "title": "Command injection", "severity": "CRITICAL"}],
        ),
        ("GET", "/api/workbenches/alpha/ledger/stats"): (
            200,
            {"total": 1, "by_kind": {"finding": 1}, "by_severity": {"CRITICAL": 1}},
        ),
        ("PUT", "/api/workbenches/alpha/objects/obj_old/content"): (200, {"ok": True}),
    })

    result = draft_report("alpha", "alpha", base="http://ab", transport=t)

    assert result == {"workbench": "alpha", "object_id": "obj_old", "mode": "updated"}
    assert any(call[0] == "PUT" and "Command injection" in call[3].decode() for call in t.calls)


def test_draft_report_refuses_structural_downgrade_of_current_report() -> None:
    existing = """
    <section id="methodology"><h2>Methodology</h2><p>Validated static review.</p></section>
    <section id="architecture"><h2>Architecture</h2><p>Updater trust boundary.</p></section>
    <section id="flows"><h2>Flows</h2><p>client to firmware</p></section>
    """
    t = FakeTransport({
        ("GET", "/api/workbenches/alpha"): (
            200,
            {"slug": "alpha", "custom_fields": {"refall_current_report_object_id": "obj_old"}},
        ),
        ("GET", "/api/workbenches/alpha/coverage/stats"): (200, {}),
        ("GET", "/api/workbenches/alpha/ledger/entries"): (200, []),
        ("GET", "/api/workbenches/alpha/ledger/stats"): (200, {"total": 0}),
        ("GET", "/api/workbenches/alpha/refall-report"): (
            200, {"object_id": "obj_old", "content": existing},
        ),
    })

    result = draft_report("alpha", "alpha", base="http://ab", transport=t)

    assert result["mode"] == "downgrade_refused"
    assert {"architecture", "flows"}.issubset(result["lost_sections"])
    assert not any(call[0] == "PUT" for call in t.calls)


def test_draft_report_includes_closeout_and_runtime_evidence() -> None:
    t = FakeTransport({
        ("GET", "/api/workbenches/alpha"): (
            200,
            {"slug": "alpha", "title": "Alpha", "custom_fields": {}},
        ),
        ("GET", "/api/workbenches/alpha/coverage/stats"): (
            200,
            {"resolved_pct": 90.0, "lines_total": 10, "lines_covered": 9, "symbols_total": 2},
        ),
        ("GET", "/api/workbenches/alpha/ledger/entries"): (
            200,
            [{"kind": "finding", "title": "Command injection", "severity": "CRITICAL"}],
        ),
        ("GET", "/api/workbenches/alpha/ledger/stats"): (
            200,
            {"total": 1, "by_kind": {"finding": 1}, "by_severity": {"CRITICAL": 1}},
        ),
        ("GET", "/api/workbenches/alpha/closeout/gate"): (
            200,
            {
                "passed": False,
                "checks": [{"id": "pending-actions-open", "status": "fail", "blocking": True, "count": 1, "details": ["pa_1"]}],
                "summary": {"pending_actions_open": 1},
            },
        ),
        ("GET", "/api/workbenches/alpha/runtime/observations"): (
            200,
            [{"kind": "claim", "claim": "runtime exploit reproduced", "confidence": "high", "evidence_refs": ["art_visual"]}],
        ),
        ("GET", "/api/workbenches/alpha/runtime/artifacts"): (
            200,
            [{"id": "art_visual", "kind": "codebadger-graph", "path": "/tmp/graph.html", "mime": "text/html", "size_bytes": 200}],
        ),
        ("GET", "/api/workbenches/alpha/runtime/evidence-graph"): (
            200,
            {"nodes": [{"id": "finding:1"}], "edges": [{"id": "edge:1"}]},
        ),
        ("GET", "/api/workbenches/alpha/runtime/manifest"): (
            200,
            {
                "run_id": "run_1",
                "manifest_id": "manifest_1",
                "provider_roles": {"manager": "codex", "A": "claude"},
                "dynamic_testing": {"status": "not_applicable"},
            },
        ),
        ("GET", "/api/workbenches/alpha/runtime/nonfatal-errors"): (
            200,
            {
                "subject": "alpha",
                "errors": [{
                    "type": "worker_submit_invalid",
                    "summary": "malformed refall-submit",
                    "failure_class": "contract_error",
                    "task_id": "task_1",
                }],
            },
        ),
        ("GET", "/api/workbenches/alpha/pending-actions"): (
            200,
            [{"id": "pa_1", "kind": "operator_decision_needed", "title": "Need approval", "status": "open"}],
        ),
        ("GET", "/api/workbenches/alpha/capabilities"): (
            200,
            {"grants": [{"id": "cap_1", "class": "lan_network_probe", "reason": "scope"}], "requests": []},
        ),
        ("POST", "/api/workbenches/alpha/objects"): (201, {"id": "obj_report"}),
        ("PATCH", "/api/workbenches/alpha"): (200, {"ok": True}),
    })

    draft_report("alpha", "alpha", base="http://ab", transport=t)

    created = json.loads(next(call[3] for call in t.calls if call[0] == "POST"))
    assert "Closeout Gate" in created["content"]
    assert "pending-actions-open" in created["content"]
    assert "Runtime Evidence" in created["content"]
    assert "Run Manifest" in created["content"]
    assert "run_1" in created["content"]
    assert "codex" in created["content"]
    assert "runtime exploit reproduced" in created["content"]
    assert "Runtime Warnings" in created["content"]
    assert "malformed refall-submit" in created["content"]
    assert "contract_error" in created["content"]
    assert "codebadger-graph" in created["content"]
    assert "1 nodes / 1 edges" in created["content"]
    assert "Pending Actions" in created["content"]
    assert "Need approval" in created["content"]
    assert "Capability Decisions" in created["content"]
    assert "lan_network_probe" in created["content"]


def test_draft_report_includes_disposition_transitions_and_closeout_overrides() -> None:
    t = FakeTransport({
        ("GET", "/api/workbenches/alpha"): (
            200,
            {"slug": "alpha", "title": "Alpha", "custom_fields": {}},
        ),
        ("GET", "/api/workbenches/alpha/coverage/stats"): (
            200,
            {"resolved_pct": 100.0, "lines_total": 10, "lines_covered": 10, "symbols_total": 2},
        ),
        ("GET", "/api/workbenches/alpha/ledger/entries"): (
            200,
            [
                {
                    "kind": "disposition-transition",
                    "finding_id": "find_1",
                    "status": "accepted",
                    "receipt_type": "non_reachability_proof",
                    "summary": "Route is absent in production config.",
                },
                {
                    "kind": "disposition-transition",
                    "finding_id": "find_2",
                    "status": "refused",
                    "receipt_type": None,
                    "refusal_reasons": ["suppressive transition requires receipt_type"],
                    "summary": "Weak duplicate claim.",
                },
                {
                    "kind": "ops-event",
                    "action": "closeout.override",
                    "status": "accepted",
                    "check_ids": ["pending-actions-open"],
                    "summary": "Operator accepted residual item.",
                },
            ],
        ),
        ("GET", "/api/workbenches/alpha/ledger/stats"): (
            200,
            {"total": 3, "by_kind": {"disposition-transition": 2, "ops-event": 1}},
        ),
        ("POST", "/api/workbenches/alpha/objects"): (201, {"id": "obj_report"}),
        ("PATCH", "/api/workbenches/alpha"): (200, {"ok": True}),
    })

    draft_report("alpha", "alpha", base="http://ab", transport=t)

    created = json.loads(next(call[3] for call in t.calls if call[0] == "POST"))
    assert "Disposition Transitions" in created["content"]
    assert "find_1" in created["content"]
    assert "non_reachability_proof" in created["content"]
    assert "suppressive transition requires receipt_type" in created["content"]
    assert "Closeout Overrides" in created["content"]
    assert "pending-actions-open" in created["content"]


def test_draft_report_renders_related_finding_locations() -> None:
    html = build_html_report(
        workbench="alpha",
        subject="alpha",
        coverage={"resolved_pct": 10, "lines_total": 10, "lines_covered": 1, "symbols_total": 1},
        ledger_entries=[
            {
                "kind": "finding",
                "title": "Command injection",
                "severity": "HIGH",
                "vuln_class": "command-injection",
                "code_paths": ["app.py:10"],
                "related_locations": [
                    {"path": "app.py", "anchor": "app.py:10"},
                    {"path": "views.py", "anchor": "views.py:22"},
                ],
            }
        ],
        ledger_stats={"total": 1},
    )

    assert "Related Locations" in html
    assert "views.py:22" in html


def test_draft_report_deduplicates_validation_variant_by_finding_id() -> None:
    html = build_html_report(
        workbench="alpha",
        subject="alpha",
        coverage={"resolved_pct": 0, "lines_total": 0, "lines_covered": 0},
        ledger_entries=[
            {
                "kind": "finding",
                "id": "FW-001",
                "subject": "alpha",
                "title": "Hardcoded credential",
                "affected_component": "initial component wording",
                "severity": "medium",
                "artifact_refs": ["initial.txt"],
            },
            {
                "kind": "finding",
                "id": "FW-001",
                "subject": "alpha",
                "title": "Hardcoded credential",
                "affected_component": "validation component wording",
                "severity": "medium",
                "artifact_refs": ["validation.txt"],
            },
        ],
        ledger_stats={"total": 2},
    )

    assert '<b>1</b><span>Total findings</span>' in html
    assert "initial.txt" in html
    assert "validation.txt" in html


def test_draft_report_renders_nonfatal_errors() -> None:
    html = build_html_report(
        workbench="alpha",
        subject="alpha",
        coverage={"resolved_pct": 10, "lines_total": 10, "lines_covered": 1, "symbols_total": 1},
        ledger_entries=[],
        ledger_stats={"total": 0},
        nonfatal_errors=[
            {
                "source": "runtime",
                "type": "worker_submit_invalid",
                "summary": "malformed refall-submit",
                "failure_class": "contract_error",
                "task_id": "task_1",
            }
        ],
    )

    assert "Runtime Warnings" in html
    assert "worker_submit_invalid" in html
    assert "malformed refall-submit" in html


def test_report_renders_numeric_cvss_score() -> None:
    html = build_html_report(
        workbench="alpha",
        subject="alpha",
        coverage={"resolved_pct": 10, "lines_total": 10, "lines_covered": 1, "symbols_total": 1},
        ledger_entries=[{
            "kind": "finding",
            "title": "Command injection",
            "severity": "CRITICAL",
            "affected_component": "request handler",
            "cvss_score": 9.8,
            "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
        }],
        ledger_stats={"total": 1},
    )

    assert "CVSS 9.8" in html
    assert "Affected component" in html
    assert "request handler" in html
