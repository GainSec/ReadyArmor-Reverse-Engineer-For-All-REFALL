from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = ROOT / "docs/specs/refall-runtime-discipline"


def test_runtime_contract_references_cover_implemented_obligations():
    required = {
        "01-disposition-refusal-gates.md": ["typed receipt", "source hashes", "ledger"],
        "02-pending-action-preservation.md": ["unresolved work", "required receipt", "closeout"],
        "03-closeout-conformance-gate.md": ["pending", "validation", "closeout"],
        "04-structured-terminal-submissions.md": ["refall-submit", "refall.submit.v1", "task_result_submit"],
        "05-runtime-event-projection.md": ["runtime database", "observations", "manifest"],
        "06-failure-aware-retries.md": ["retry", "two attempts", "pending work"],
        "07-capability-gated-execution-broker.md": ["operator grants", "scope", "authorize its own"],
    }
    index = (SPEC_DIR / "README.md").read_text()
    for name, terms in required.items():
        assert name in index
        text = (SPEC_DIR / name).read_text()
        for term in terms:
            assert term in text
        assert "../../evidence.md" in text
        assert "../../api.md" in text
