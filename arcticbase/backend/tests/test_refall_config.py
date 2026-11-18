from pathlib import Path

import arctic_base.config as config
from arctic_base.config import get_settings


def test_default_host_resolves_to_lan_ip(monkeypatch) -> None:
    monkeypatch.delenv("ARCTIC_BASE_HOST", raising=False)
    monkeypatch.delenv("REFALL_ARCTICBASE_HOST", raising=False)
    monkeypatch.delenv("REFALL_PUBLIC_BASE_URL", raising=False)
    monkeypatch.setattr(config, "_detect_private_lan_ipv4", lambda: "192.168.30.13")

    settings = get_settings()

    assert settings.host == "192.168.30.13"
    assert settings.refall_arcticbase_host == "192.168.30.13"
    assert settings.refall_public_base_url == "http://192.168.30.13:7673"


def test_explicit_host_override_is_preserved(monkeypatch) -> None:
    monkeypatch.setenv("ARCTIC_BASE_HOST", "0.0.0.0")
    monkeypatch.delenv("REFALL_ARCTICBASE_HOST", raising=False)
    monkeypatch.delenv("REFALL_PUBLIC_BASE_URL", raising=False)
    monkeypatch.setattr(config, "_detect_private_lan_ipv4", lambda: "192.168.30.13")

    settings = get_settings()

    assert settings.host == "0.0.0.0"
    assert settings.refall_arcticbase_host == "192.168.30.13"
    assert settings.refall_public_base_url == "http://192.168.30.13:7673"


def test_refall_ops_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("REFALL_ENABLE_OPS", raising=False)

    settings = get_settings()

    assert settings.refall_enable_ops is False


def test_refall_subject_root_default_follows_data_root(monkeypatch) -> None:
    monkeypatch.delenv("REFALL_SUBJECT_ROOT", raising=False)
    monkeypatch.setenv("REFALL_DATA_ROOT", "/tmp/refall-portable")

    settings = get_settings()

    assert settings.refall_subject_root == Path("/tmp/refall-portable/subjects")


def test_refall_data_root_defaults_under_arcticbase_data(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("REFALL_DATA_ROOT", raising=False)
    monkeypatch.delenv("REFALL_SUBJECT_ROOT", raising=False)
    monkeypatch.setenv("ARCTIC_BASE_DATA", str(tmp_path / "arcticbase-data"))

    settings = get_settings()

    assert settings.refall_data_root == tmp_path / "arcticbase-data" / "refall"
    assert settings.refall_subject_root == tmp_path / "arcticbase-data" / "refall" / "subjects"


def test_refall_subject_root_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("REFALL_DATA_ROOT", "/tmp/refall-portable")
    monkeypatch.setenv("REFALL_SUBJECT_ROOT", "/srv/refall/subjects")

    settings = get_settings()

    assert settings.refall_subject_root == Path("/srv/refall/subjects")


def test_refall_provider_defaults_are_portable(monkeypatch) -> None:
    monkeypatch.delenv("REFALL_HEAD_PROVIDER", raising=False)
    monkeypatch.delenv("REFALL_ALLOWED_HEAD_PROVIDERS", raising=False)
    monkeypatch.delenv("REFALL_CODEX_COMMAND", raising=False)
    monkeypatch.delenv("REFALL_CLAUDE_COMMAND", raising=False)
    monkeypatch.delenv("REFALL_GROK_COMMAND", raising=False)
    monkeypatch.delenv("REFALL_CONTEXT_MANAGER_TIMEOUT_S", raising=False)

    settings = get_settings()

    assert settings.refall_head_provider == "codex"
    assert settings.refall_allowed_head_providers == "codex,claude,grok"
    assert settings.refall_codex_command == "codex"
    assert settings.refall_claude_command == "claude"
    assert settings.refall_grok_command == "grok"
    assert settings.refall_context_manager_timeout_s == 1800


def test_refall_standing_loop_defaults_are_portable(monkeypatch) -> None:
    monkeypatch.delenv("REFALL_REPO_ROOT", raising=False)
    monkeypatch.delenv("REFALL_ENABLE_LOOP_LAUNCH", raising=False)
    monkeypatch.delenv("REFALL_LOOP_MAX_PARALLEL", raising=False)
    monkeypatch.delenv("REFALL_LOOP_POLL_INTERVAL_S", raising=False)
    monkeypatch.delenv("REFALL_LOOP_REPORT_INTERVAL_CYCLES", raising=False)
    monkeypatch.delenv("REFALL_LOOP_STALL_CYCLES", raising=False)

    settings = get_settings()

    assert settings.refall_repo_root.resolve() == Path(__file__).resolve().parents[3]
    assert settings.refall_enable_loop_launch is True
    assert settings.refall_loop_max_parallel == 4
    assert settings.refall_loop_poll_interval_s == 5
    assert settings.refall_loop_report_interval_cycles == 10
    assert settings.refall_loop_stall_cycles == 36
