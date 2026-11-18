from coverage_service.tools import vendor_disclosure


def test_vendor_disclosure_renders_submission_ready_valid_findings(monkeypatch):
    def fake_get(path):
        if path.startswith("/findings?"):
            return [
                {
                    "id": "valid-1",
                    "status": "VALID",
                    "severity": "HIGH",
                    "title": "Stored printer attribute HTML injection",
                    "vuln_class": "CWE-79",
                    "code_paths": ["PrinterSimulatorServer:sym.func.10001@0x10001abc"],
                    "attacker_position": "NETWORK_ADJACENT",
                    "privileges_required": "NONE",
                    "user_interaction": "Admin views printer web UI",
                    "description": "An IPP printer attribute is reflected into the web index without escaping.",
                    "impact": "A submitted attribute can execute script in the operator browser.",
                    "reasoning": "Static review confirmed the raw attribute reaches the generated HTML.",
                    "repro_hints": "Run: python3 poc/printer_sim_poc.py --case add-printer-attr --start-server --port 6340. Expected: web index contains the raw marker.",
                    "production_viability": "Runtime confirmed against PrinterSimulatorServer; the marker appeared in the generated web index.",
                    "repro_status": "runtime_confirmed",
                    "critic_reasoning": "Visual trace: IPP request -> printer attribute parser -> web index render -> raw HTML sink. Raw output: [add-printer-attr] web index contains raw marker: True. Artifacts: /subjects/example-binary/refall-impact/add-printer/proof.log and /projects/REFALL-V10/poc/out/add-printer-attr.http",
                    "mitigation": "HTML-escape all printer-controlled strings before rendering.",
                    "patch_status": "unpatched",
                },
                {
                    "id": "fp-1",
                    "status": "FALSE_POSITIVE",
                    "severity": "HIGH",
                    "title": "Rejected raster overflow",
                    "reasoning": "The exposed queue rejects the format before the parser.",
                    "code_paths": ["PrinterSimulatorServer:sym.func.10002@0x10002abc"],
                },
                {
                    "id": "dup-1",
                    "status": "DUPLICATE",
                    "severity": "MEDIUM",
                    "title": "Duplicate attribute injection",
                    "reasoning": "Same root cause as valid-1.",
                    "code_paths": ["PrinterSimulatorServer:sym.func.10003@0x10003abc"],
                },
                {
                    "id": "chain-1",
                    "status": "CHAINABLE_DEFERRED",
                    "severity": "LOW",
                    "title": "Stored local-only attribute injection",
                    "reasoning": "Real sink but only same-user planting is proven.",
                    "repro_hints": "Needs localhost CSRF or another non-self planting primitive before promotion.",
                    "code_paths": ["PrinterSimulatorServer:sym.func.10004@0x10004abc"],
                },
            ]
        if path.startswith("/funnel?"):
            return {
                "candidates": 3,
                "valid": 1,
                "false_positive": 1,
                "duplicate": 1,
                "chainable_deferred": 1,
                "needs_research": 0,
                "rejection_rate": 0.5,
            }
        if path.startswith("/plan_progress?"):
            return {"total": 3, "done": 3, "open": 0, "claimed": 0}
        if path.startswith("/context?"):
            return {
                "subject": "example-binary",
                "root_container": "/projects/example-binary",
                "info_md": "Example Binary macOS target used for IPP/security validation.",
            }
        raise AssertionError(path)

    monkeypatch.setattr(vendor_disclosure, "_get", fake_get)

    doc = vendor_disclosure.build("example-binary", "Example Binary Vendor Disclosure")

    assert "Vendor Disclosure Report" in doc
    assert "Stored printer attribute HTML injection" in doc
    assert "CWE-79" in doc
    assert "python3 poc/printer_sim_poc.py --case add-printer-attr" in doc
    assert "[add-printer-attr] web index contains raw marker: True" in doc
    assert "HTML-escape all printer-controlled strings" in doc
    assert "Disclosure Timeline" in doc
    assert "Submission Checklist" in doc
    assert "False positives / duplicates appendix (2)" in doc
    assert doc.index("Stored printer attribute HTML injection") < doc.index("False positives / duplicates appendix")
    assert "Rejected raster overflow" in doc
    assert "Duplicate attribute injection" in doc
    assert "Stored local-only attribute injection" not in doc
    assert "Chainable / deferred appendix" not in doc
    assert "excluded from this vendor submission package" in doc
    assert "/Users/" not in doc
    assert "/projects/" not in doc
    assert "poc/out/add-printer-attr.http" in doc
    assert "Local Artifacts" not in doc
    assert "<script src" not in doc
    assert "<link " not in doc
