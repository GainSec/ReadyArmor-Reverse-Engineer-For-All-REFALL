from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_architecture_covers_components_state_and_gates():
    architecture = (ROOT / "docs/architecture.md").read_text()
    for contract in ["ref_all_executor/", "coverage_service/", "Agent Canvas/OpenHands", "refall_coverage.db", "refall_ledger.jsonl", "state.sqlite", "disposition gate", "capability broker", "closeout gate"]:
        assert contract in architecture


def test_api_reference_covers_evidence_and_operational_surfaces():
    text = (ROOT / "docs/api.md").read_text()
    for route in ["/api/refall/ops/command", "/pending-actions", "/runtime/events", "/runtime/artifacts", "/runtime/evidence-graph", "/capabilities", "/closeout/gate", "/findings/{finding_id}/transitions"]:
        assert route in text


def test_runtime_report_specs_keep_gate_and_evidence_requirements():
    base = ROOT / "arcticbase/backend/src/arctic_base/refall_report"
    for rel, terms in {
        "spec/deliverable.md": ["Closeout gate", "Pending actions", "Runtime evidence", "Capability decisions", "visual-evidence-pack"],
        "spec/input-format.md": ["/closeout/gate", "/pending-actions", "/runtime/observations", "/runtime/artifacts", "/runtime/evidence-graph", "/capabilities"],
        "spec/design-system.md": ["closeout gate", "runtime artifacts", "visual evidence", "CodeCharta", "Codebadger"],
        "modules/README.md": ["closeout gate", "pending actions", "runtime observations", "capability decisions", "visual-evidence-pack"],
    }.items():
        text = (base / rel).read_text()
        for term in terms:
            assert term in text
