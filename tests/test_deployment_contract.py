from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_ENV_KEYS = {
    "REFALL_DEPLOYMENT_MODE",
    "REFALL_DATA_ROOT",
    "REFALL_SUBJECT_ROOT",
    "REFALL_ARCTICBASE_DATA",
    "REFALL_LAN_BIND_IP",
    "REFALL_ARCTICBASE_HOST",
    "REFALL_ARCTICBASE_PORT",
    "REFALL_PUBLIC_BASE_URL",
    "REFALL_OPENHANDS_BASE",
    "REFALL_OPENHANDS_API_KEY_PATH",
    "REFALL_ENABLE_OPS",
    "REFALL_ENABLE_OPS_COMMANDS",
    "REFALL_OPS_ALLOWED_COMMANDS",
    "REFALL_HEAD_PROVIDER",
    "REFALL_ALLOWED_HEAD_PROVIDERS",
    "REFALL_CODEX_COMMAND",
    "REFALL_CLAUDE_COMMAND",
    "REFALL_GROK_COMMAND",
    "REFALL_CONTEXT_MANAGER_TIMEOUT_S",
    "REFALL_REPO_ROOT",
    "REFALL_ENABLE_LOOP_LAUNCH",
    "REFALL_LOOP_MAX_PARALLEL",
    "REFALL_LOOP_POLL_INTERVAL_S",
    "REFALL_LOOP_REPORT_INTERVAL_CYCLES",
    "REFALL_LOOP_STALL_CYCLES",
}

def _parse_env_example(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        values[key] = value
    return values


def test_portable_deployment_artifacts_exist() -> None:
    assert (ROOT / "docs/configuration.md").is_file()
    assert (ROOT / "deploy/refall-arcticbase.env.example").is_file()
    assert (ROOT / "deploy/docker-compose.refall-arcticbase.yml").is_file()
    assert (ROOT / "deploy/README.md").is_file()


def test_env_example_contains_required_portable_settings() -> None:
    env_path = ROOT / "deploy/refall-arcticbase.env.example"
    values = _parse_env_example(env_path)

    missing = REQUIRED_ENV_KEYS - set(values)
    assert missing == set()


def test_env_example_has_no_machine_specific_defaults() -> None:
    env_path = ROOT / "deploy/refall-arcticbase.env.example"
    text = env_path.read_text(encoding="utf-8")

    assert re.search(r"/(?:Users|home)/[^/\s\"'`<>]+", text) is None
    assert re.search(r"~[\\/][^\s\"'`<>]+", text) is None


def test_compose_uses_refall_runtime_variables() -> None:
    compose_path = ROOT / "deploy/docker-compose.refall-arcticbase.yml"
    text = compose_path.read_text(encoding="utf-8")

    assert "${REFALL_LAN_BIND_IP:-0.0.0.0}:${REFALL_ARCTICBASE_PORT:-7673}:7673" in text
    assert "ARCTIC_BASE_PORT: 7673" in text
    assert "REFALL_ARCTICBASE_HOST: ${REFALL_ARCTICBASE_HOST:-auto-lan}" in text
    assert "required: false" in text
    assert "${REFALL_SUBJECT_ROOT:-./subjects}" in text
    assert "refall_arcticbase_data" in text
