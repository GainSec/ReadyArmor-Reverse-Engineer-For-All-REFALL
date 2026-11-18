import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_codebadger_is_registered_as_default_opt_in_service() -> None:
    registry = json.loads((ROOT / "toolchain/config/services.json").read_text(encoding="utf-8"))
    services = {item["name"]: item for item in registry["services"]}
    slots = {item["name"] for item in registry.get("extension_slots", [])}

    service = services["codebadger-mcp"]
    assert "Codebadger MCP" in service["description"]
    assert "codebadger-service\" supervise" in service["start_cmd"]
    assert service["health_check"]["type"] == "command"
    assert "codebadger-service\" health" in service["health_check"]["cmd"]
    assert service["port"] == 4242
    assert service["autostart"] is False
    assert "codebadger-mcp" not in slots


def test_codebase_memory_is_opt_in_and_not_a_mac_startup_blocker() -> None:
    registry = json.loads((ROOT / "toolchain/config/services.json").read_text(encoding="utf-8"))
    services = {item["name"]: item for item in registry["services"]}
    service = services["codebase-memory"]

    assert service["autostart"] is False
    assert "codebase-memory-mcp" in service["start_cmd"]


def test_codebase_memory_installer_does_not_pull_linux_asset_on_macos() -> None:
    installer = (ROOT / "toolchain/install.sh").read_text(encoding="utf-8")

    assert "os=\"$(uname -s)\"" in installer
    assert "Linux" in installer
    assert "unsupported OS" in installer


def test_codebadger_install_is_pinned_and_safe_by_default() -> None:
    lock = (ROOT / "toolchain/versions.lock").read_text(encoding="utf-8")
    installer = (ROOT / "toolchain/install.sh").read_text(encoding="utf-8")
    service = (ROOT / "toolchain/bin/codebadger-service").read_text(encoding="utf-8")

    assert "CODEBADGER_REPO_URL=https://github.com/Lekssays/codebadger.git" in lock
    assert "CODEBADGER_GIT_REF=a0b63512d54b19e78c2aba2c77cc6948fa13b1a5" in lock
    assert "CODEBADGER_MCP_PORT=4242" in lock
    assert "CODEBADGER_MCP_PUBLISH_HOST=127.0.0.1" in lock
    assert "install_codebadger" in installer
    assert "select(.autostart // true)" in (ROOT / "toolchain/ctl.sh").read_text(encoding="utf-8")
    assert "MCP_PUBLISH_HOST=${REFALL_CODEBADGER_BIND_HOST:-$CODEBADGER_MCP_PUBLISH_HOST}" in service
    assert "ALLOWED_SOURCE_ROOTS=/app/playground" in service
    assert "CHAT_DEPLOY=${REFALL_CODEBADGER_CHAT_DEPLOY:-false}" in service
    assert "source_type='local'" in service


def test_codebadger_is_documented_for_manager_and_reporting() -> None:
    manager = (ROOT / "docs/manager/AGENTS.md").read_text(encoding="utf-8")
    operating = (ROOT / "REFALL-MANAGER-OPERATING-GUIDE.md").read_text(encoding="utf-8")
    modules = (ROOT / "arcticbase/backend/src/arctic_base/refall_report/modules/README.md").read_text(
        encoding="utf-8"
    )

    assert "Codebadger" in manager
    assert "toolchain/ctl.sh up codebadger-mcp" in manager
    assert "generate_cpg" in manager
    assert "visual evidence pack" in manager
    assert "Codebadger" in operating
    assert "codecharta" in operating.lower()
    assert "vendor-cna" in modules
    assert "visual-evidence-pack" in modules
    assert "codebadger" in modules.lower()
