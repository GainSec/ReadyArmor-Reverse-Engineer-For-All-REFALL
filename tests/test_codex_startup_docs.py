from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_startup_sequence_preserves_context_and_capability_prerequisites():
    required = {
        "00-INGEST-FIRST.md": ["stored context", "REFALL_PUBLIC_BASE_URL", "SOURCE_PATH"],
        "01-BOOT-INFRA.md": ["/api/health", "/api/refall/ops/status", "Agent Canvas/OpenHands"],
        "02-NEXT-SUBJECT-LIFECYCLE.md": ["subject create", "run_local_command", "Generate Context before Start Loop"],
        "03-MONITOR-RECOVER-CLOSEOUT.md": ["report draft", "report enrich", "closeout/gate"],
        "04-REMOTE-SSH-RESOURCES.md": ["REFALL_SSH_RESOURCE_ALIASES", "ssh <alias> <command>"],
    }
    for name, fragments in required.items():
        text = (ROOT / "docs/codex-startup" / name).read_text()
        for fragment in fragments:
            assert fragment in text
        root_name = "11-REMOTE-SSH-RESOURCES.md" if name.startswith("04-") else name
        assert (ROOT / "starthere" / root_name).read_text() == text


def test_root_startup_pack_has_all_runtime_roles():
    for name in ["README.md", "04-AGENTS.md", "05-REFALL-MANAGER-OPERATING-GUIDE.md", "06-MANAGER-AGENTS.md", "07-CODEX.md", "08-OPERATING-GUIDE.md", "09-BASE-INSTALLATION.md", "10-CLAUDE-SPECIALIST.md"]:
        assert (ROOT / "starthere" / name).is_file()


def test_startup_index_links_to_current_product_guides():
    text = (ROOT / "docs/README.md").read_text()
    for target in ["../BASE-INSTALLATION.md", "../OPERATING_GUIDE.md", "architecture.md", "configuration.md", "api.md", "evidence.md", "../starthere/README.md"]:
        assert target in text


def test_release_excludes_historical_workbench_export():
    assert not (ROOT / "docs/workbench-backups/refall-v10-workbench-2026-07-25.tar.gz").exists()
