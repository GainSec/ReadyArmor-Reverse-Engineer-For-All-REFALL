from coverage_service.tools import report_findings


def test_findings_report_links_poc_pack_when_present(monkeypatch, tmp_path):
    def fake_get(path):
        if path.startswith("/findings?"):
            return []
        if path.startswith("/funnel?"):
            return {"candidates": 0, "valid": 0, "false_positive": 0, "needs_research": 0, "rejection_rate": 0}
        if path.startswith("/plan_progress?"):
            return {"done": 0}
        raise AssertionError(path)

    (tmp_path / "example-binary_poc_oid.txt").write_text("obj_poc")
    monkeypatch.setattr(report_findings, "_get", fake_get)
    monkeypatch.setattr(report_findings, "STATE_DIR", str(tmp_path))

    html = report_findings.build("example-binary", "Example Binary")

    assert "PoC pack" in html
    assert "http://127.0.0.1:7673/wb/ref-all/o/obj_poc" in html


def test_findings_report_renders_repro_hints(monkeypatch):
    def fake_get(path):
        if path.startswith("/findings?"):
            return [
                {
                    "status": "VALID",
                    "severity": "MEDIUM",
                    "title": "Stored HTML injection",
                    "vuln_class": "CWE-79",
                    "code_paths": ["bin:sym.func@0x1"],
                    "attacker_position": "EXTERNAL",
                    "privileges_required": "NONE",
                    "description": "raw string reaches HTML",
                    "impact": "stored script execution",
                    "reasoning": "reviewed",
                    "repro_hints": "Submit job-name with <script> and view the job table.",
                    "mitigation": "escape HTML",
                }
            ]
        if path.startswith("/funnel?"):
            return {"candidates": 1, "valid": 1, "false_positive": 0, "needs_research": 0, "rejection_rate": 0}
        if path.startswith("/plan_progress?"):
            return {"done": 1}
        raise AssertionError(path)

    monkeypatch.setattr(report_findings, "_get", fake_get)

    html = report_findings.build("example-binary", "Example Binary")

    assert "Repro / proof" in html
    assert "Submit job-name with &lt;script&gt;" in html


def test_valid_findings_render_trace_and_runtime_viability(monkeypatch):
    def fake_get(path):
        if path.startswith("/findings?"):
            return [
                {
                    "status": "VALID",
                    "severity": "CRITICAL",
                    "title": "Unchecked raster line copy",
                    "vuln_class": "CWE-120",
                    "code_paths": [
                        "PrinterSimulatorServer:sym.func.100023d4c@0x100023e38",
                        "PrinterSimulatorServer:sym.func.100023d4c@0x100023ebc",
                    ],
                    "attacker_position": "EXTERNAL",
                    "privileges_required": "NONE",
                    "description": "IPP raster header line_length reaches memcpy without a capacity check.",
                    "impact": "heap overflow during raster copy",
                    "reasoning": "review confirmed the unchecked memcpy sink and external reachability",
                    "repro_hints": "Dynamic repro plan: submit an IPP raster job with oversized line_length. Static proof: memcpy uses x23 from the raster header. Expected dynamic proof: crash during line copy.",
                    "mitigation": "bound line_length",
                    "production_viability": "Runtime validation is ready once the simulator is launched under ASAN or lldb.",
                }
            ]
        if path.startswith("/funnel?"):
            return {"candidates": 1, "valid": 1, "false_positive": 0, "needs_research": 0, "rejection_rate": 0}
        if path.startswith("/plan_progress?"):
            return {"done": 1}
        raise AssertionError(path)

    monkeypatch.setattr(report_findings, "_get", fake_get)

    html = report_findings.build("example-binary", "Example Binary")

    assert "End-to-end trace" in html
    assert "Runtime validation viability" in html
    assert "Attacker input" in html
    assert "IPP raster header line_length reaches memcpy" in html
    assert "Runtime validation is ready once the simulator is launched" in html


def test_findings_report_renders_validation_artifact(monkeypatch):
    def fake_get(path):
        if path.startswith("/findings?"):
            return [
                {
                    "status": "VALID",
                    "severity": "MEDIUM",
                    "title": "Runtime enriched issue",
                    "code_paths": ["bin:sym.func@0x1"],
                    "critic_reasoning": "Visual trace: request -> parser -> sink. Raw output: crash log attached.",
                }
            ]
        if path.startswith("/funnel?"):
            return {"candidates": 1, "valid": 1, "false_positive": 0, "needs_research": 0, "rejection_rate": 0}
        if path.startswith("/plan_progress?"):
            return {"done": 1}
        raise AssertionError(path)

    monkeypatch.setattr(report_findings, "_get", fake_get)

    html = report_findings.build("example-binary", "Example Binary")

    assert "Validation artifact" in html
    assert "Visual trace: request -&gt; parser -&gt; sink" in html


def test_findings_report_groups_duplicates_with_false_positives(monkeypatch):
    def fake_get(path):
        if path.startswith("/findings?"):
            return [
                {
                    "status": "VALID",
                    "severity": "MEDIUM",
                    "title": "Real issue",
                    "code_paths": ["bin:sym.func@0x1"],
                },
                {
                    "status": "FALSE_POSITIVE",
                    "severity": "HIGH",
                    "title": "Rejected issue",
                    "reasoning": "bounded copy",
                },
                {
                    "status": "DUPLICATE",
                    "severity": "CRITICAL",
                    "title": "Duplicate issue",
                    "reasoning": "same root cause as retained finding",
                },
            ]
        if path.startswith("/funnel?"):
            return {
                "candidates": 3,
                "valid": 1,
                "false_positive": 1,
                "needs_research": 0,
                "duplicate": 1,
                "rejection_rate": 0.5,
            }
        if path.startswith("/plan_progress?"):
            return {"done": 3}
        raise AssertionError(path)

    monkeypatch.setattr(report_findings, "_get", fake_get)

    html = report_findings.build("example-binary", "Example Binary")

    assert "Rejected as false positives / duplicates (2)" in html
    assert "Duplicate issue" in html
    assert "same root cause as retained finding" in html
    assert "Duplicates (" not in html


def test_findings_report_keeps_chainable_deferred_out_of_main_flow(monkeypatch):
    def fake_get(path):
        if path.startswith("/findings?"):
            return [
                {
                    "status": "VALID",
                    "severity": "MEDIUM",
                    "title": "Standalone issue",
                    "code_paths": ["bin:sym.func@0x1"],
                },
                {
                    "status": "CHAINABLE_DEFERRED",
                    "severity": "LOW",
                    "title": "Stored sink without non-self planting",
                    "reasoning": "Real sink, but standalone exploitability is not proven.",
                    "repro_hints": "Needs localhost CSRF or another planting primitive before promotion.",
                    "code_paths": ["bin:sym.func@0x2"],
                },
            ]
        if path.startswith("/funnel?"):
            return {
                "candidates": 2,
                "valid": 1,
                "false_positive": 0,
                "needs_research": 0,
                "duplicate": 0,
                "chainable_deferred": 1,
                "rejection_rate": 0,
            }
        if path.startswith("/plan_progress?"):
            return {"done": 2}
        raise AssertionError(path)

    monkeypatch.setattr(report_findings, "_get", fake_get)

    html = report_findings.build("example-binary", "Example Binary")

    assert "Validated findings (1)" in html
    assert "Chainable / deferred findings (1)" in html
    assert html.index("Standalone issue") < html.index("Chainable / deferred findings")
    assert "Stored sink without non-self planting" in html
    assert "Needs localhost CSRF" in html
