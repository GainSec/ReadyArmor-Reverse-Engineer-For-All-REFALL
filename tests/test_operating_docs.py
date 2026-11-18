from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_operating_guides_cover_subject_lifecycle_and_evidence():
    operating = (ROOT / "OPERATING_GUIDE.md").read_text()
    for command in ["subject create", "ops command context", "ops command doctor", "loop start", "loop update", "report draft", "report enrich", "loop closeout"]:
        assert command in operating
    for route in ["/closeout/gate", "/ledger/entries", "/capabilities/grant"]:
        assert route in operating
    evidence = (ROOT / "docs/evidence.md").read_text()
    for contract in ["refall-submit", "refall.submit.v1", "task_result_submit", "submission_id", "source_hashes", "scope_blocked", "capability_missing", "LIVE_CONFIRMED"]:
        assert contract in evidence


def test_public_operating_guides_use_portable_examples():
    for rel in ["README.md", "BASE-INSTALLATION.md", "OPERATING_GUIDE.md", "REFALL-MANAGER-OPERATING-GUIDE.md"]:
        text = (ROOT / rel).read_text()
        assert re.search(r"/(?:Users|home)/[^/\s\"'`<>]+", text) is None
        assert "192.168.30.13" not in text
        assert "--ask-for-approval" not in text


def test_product_documentation_local_links_resolve():
    paths = list((ROOT / "docs").rglob("*.md")) + list(ROOT.glob("*.md"))
    for path in paths:
        if path.name in {"AGENTS.md", "CODEX.md", "CLAUDE.md"}:
            continue
        text = re.sub(r"```.*?```", "", path.read_text(), flags=re.S)
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            if target.startswith(("http:", "https:", "mailto:", "#")):
                continue
            target = target.split("#")[0]
            assert (path.parent / target).exists(), (path, target)


def test_manager_guide_preserves_operator_authorization_boundary():
    guide = (ROOT / "REFALL-MANAGER-OPERATING-GUIDE.md").read_text()
    assert "subject-scoped `run_local_command`" in guide
    assert "cannot authorize its own live action" in guide
    assert "Grok is not an SSH resource" in guide
    assert "host-orchestrated" in guide
    assert "must not receive host credentials" in guide
