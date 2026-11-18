from ref_all_executor import config


def test_auto_base_is_agent_canvas_automation_prefix():
    assert config.AUTO_BASE.endswith("/api/automation/v1")


def test_session_api_key_is_stripped(tmp_path, monkeypatch):
    f = tmp_path / "api-key.txt"
    f.write_text("abc\n")
    monkeypatch.setattr(config, "API_KEY_PATH", str(f))
    assert config.session_api_key() == "abc"


def test_lane_a_is_claude_no_hermes():
    a = config.LANES["A"]
    assert a["acp_server"] == "claude-code" and a["acp_command"] == []
    assert a["acp_model"] == "opus"
    assert a["mcp_config"]["mcpServers"]["serena"]["url"] == "http://127.0.0.1:20872/mcp"


def test_lane_b_is_codex_with_serena_mcp():
    b = config.LANES["B"]
    assert b["acp_server"] == "codex"
    assert b["mcp_config"]["mcpServers"]["serena"]["url"] == "http://127.0.0.1:20872/mcp"


def test_default_ssh_resource_hosts_are_registered():
    assert config.DEFAULT_SSH_RESOURCE_ALIASES == ("sectortw", "sectortl")
    assert config.HOSTS["sectortw"] == {"kind": "ssh", "target": "sectortw"}
    assert config.HOSTS["sectortl"] == {"kind": "ssh", "target": "sectortl"}
    for host in ("snow", "sectorpln", "sectorpt", "sectorttk", "winbox"):
        assert host not in config.HOSTS


def test_forbidden_ssh_resource_aliases_are_filtered_from_env(monkeypatch):
    monkeypatch.setenv(
        "REFALL_SSH_RESOURCE_ALIASES",
        "sectortw,snow,sectorpln,sectorpt,sectorttk,winbox,sectortl",
    )

    assert config._ssh_resource_aliases() == ("sectortw", "sectortl")


def test_ssh_resource_instructions_are_actionable():
    instructions = config.ssh_resource_instructions()
    assert "## Remote SSH Resources" in instructions
    assert "ssh sectortw <command>" in instructions
    assert "ssh sectortl <command>" in instructions
    for host in ("snow", "sectorpln", "sectorpt", "sectorttk", "winbox"):
        assert host not in instructions
    assert "terminal REFALL submission" in instructions


def test_subject_agent_workspace_uses_refallsub_container_root(monkeypatch):
    monkeypatch.delenv("REFALL_AGENT_WORKSPACE_CONTAINER_ROOT", raising=False)

    assert config.subject_agent_workspace(
        "hyundai",
        lane="A",
        task_class="characterize",
        unit={"id": "unit/one"},
    ) == "/projects/refallsub/hyundai/A-characterize-unit-one"
