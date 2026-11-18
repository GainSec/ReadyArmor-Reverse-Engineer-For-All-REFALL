from pathlib import Path

from ref_all_executor.infra import RefallInfra


class FakeRunner:
    def __init__(self):
        self.calls = []

    def run(self, cmd, capture_output=True, text=True, timeout=10):
        self.calls.append(cmd)
        joined = " ".join(str(part) for part in cmd)
        if cmd[:2] == ["lsof", "-tiTCP:8900"]:
            return _result("", 1)
        if cmd[:2] == ["docker", "ps"] and "-a" in cmd:
            return _result("refall-agent-canvas\tExited (0) 2 hours ago\n")
        if cmd[:2] == ["docker", "ps"]:
            return _result("")
        if "toolchain/ctl.sh status" in joined:
            return _result("serena running\npython-lsp-server running\n")
        if cmd[:3] == ["tmux", "has-session", "-t"]:
            return _result("", 1)
        return _result("")


def _result(stdout="", returncode=0, stderr=""):
    class Result:
        pass

    r = Result()
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


def test_infra_up_removes_stop_starts_coverage_openhands_and_toolchain(tmp_path):
    data_dir = tmp_path / "coverage_service" / "data"
    data_dir.mkdir(parents=True)
    ctl = tmp_path / "toolchain" / "ctl.sh"
    ctl.parent.mkdir()
    ctl.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (data_dir / "STOP").touch()
    runner = FakeRunner()

    out = RefallInfra(repo_root=tmp_path, data_dir=data_dir, runner=runner).up(dry_run=False)

    assert not (data_dir / "STOP").exists()
    assert out["coverage"]["action"] == "started"
    assert out["openhands"]["action"] == "started"
    assert out["toolchain"]["action"] == "started"
    assert ["docker", "start", "refall-agent-canvas"] in runner.calls
    coverage_cmd = next(" ".join(cmd) for cmd in runner.calls if "python3 -m coverage_service" in " ".join(cmd))
    assert "tmux new-session" in coverage_cmd
    assert "refall-coverage" in coverage_cmd
    assert "python3 -m coverage_service" in coverage_cmd
    assert "&& nohup" not in coverage_cmd
    toolchain_cmd = next(" ".join(cmd) for cmd in runner.calls if "tmux new-session" in " ".join(cmd) and "refall-toolchain" in " ".join(cmd))
    assert "python-lsp-server serena" in toolchain_cmd
    assert "codebase-memory" not in toolchain_cmd


def test_infra_status_reports_coverage_openhands_and_toolchain(tmp_path):
    class StatusRunner(FakeRunner):
        def run(self, cmd, capture_output=True, text=True, timeout=10):
            self.calls.append(cmd)
            if cmd[:2] == ["lsof", "-tiTCP:8900"]:
                return _result("123\n")
            if cmd[:2] == ["docker", "ps"]:
                return _result("refall-agent-canvas\tUp 5 minutes\n")
            if "toolchain/ctl.sh status" in " ".join(str(part) for part in cmd):
                return _result("serena running\n")
            return _result("")

    ctl = tmp_path / "toolchain" / "ctl.sh"
    ctl.parent.mkdir()
    ctl.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    out = RefallInfra(repo_root=tmp_path, data_dir=tmp_path / "data", runner=StatusRunner()).status()

    assert out["coverage"]["state"] == "running"
    assert out["coverage"]["pids"] == [123]
    assert out["openhands"]["state"] == "running"
    assert out["toolchain"]["state"] == "reported"


def test_infra_status_uses_openhands_proxy_when_docker_socket_is_unavailable(tmp_path):
    class ProxyOnlyRunner(FakeRunner):
        def run(self, cmd, capture_output=True, text=True, timeout=10):
            self.calls.append(cmd)
            joined = " ".join(str(part) for part in cmd)
            if cmd[:2] == ["docker", "ps"]:
                return _result("", 1, "docker socket unavailable")
            if "curl" in joined and "127.0.0.1:8000" in joined:
                return _result("200\n")
            if "toolchain/ctl.sh status" in joined:
                return _result("serena running\n")
            return _result("")

    ctl = tmp_path / "toolchain" / "ctl.sh"
    ctl.parent.mkdir()
    ctl.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    out = RefallInfra(repo_root=tmp_path, data_dir=tmp_path / "data", runner=ProxyOnlyRunner()).status()

    assert out["openhands"]["state"] == "running"
    assert out["openhands"]["source"] == "proxy"


def test_infra_up_restarts_stale_toolchain_tmux_session(tmp_path):
    class StaleToolchainRunner(FakeRunner):
        def __init__(self):
            super().__init__()
            self.toolchain_session_exists = True

        def run(self, cmd, capture_output=True, text=True, timeout=10):
            self.calls.append(cmd)
            joined = " ".join(str(part) for part in cmd)
            if cmd[:2] == ["lsof", "-tiTCP:8900"]:
                return _result("123\n")
            if cmd[:2] == ["docker", "ps"]:
                return _result("refall-agent-canvas\tUp 5 minutes\n")
            if "command -v tmux" in joined:
                return _result("/opt/homebrew/bin/tmux\n")
            if cmd[:3] == ["tmux", "has-session", "-t"]:
                return _result("") if self.toolchain_session_exists else _result("", 1)
            if cmd[:3] == ["tmux", "kill-session", "-t"]:
                self.toolchain_session_exists = False
                return _result("")
            if "toolchain/ctl.sh status" in joined:
                return _result(
                    "SERVICE                  STATE\n"
                    "python-lsp-server        down\n"
                    "serena                   down\n"
                    "codebase-memory          down\n"
                )
            return _result("")

    ctl = tmp_path / "toolchain" / "ctl.sh"
    ctl.parent.mkdir()
    ctl.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    runner = StaleToolchainRunner()

    out = RefallInfra(repo_root=tmp_path, data_dir=tmp_path / "data", runner=runner).up()

    assert out["toolchain"]["action"] == "started"
    assert ["tmux", "kill-session", "-t", "refall-toolchain"] in runner.calls
    assert any("tmux new-session" in " ".join(cmd) and "refall-toolchain" in " ".join(cmd) for cmd in runner.calls)
