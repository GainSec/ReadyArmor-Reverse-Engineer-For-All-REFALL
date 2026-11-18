from pathlib import Path

from ref_all_executor.cleanup import RefallCleanup


class FakeOH:
    def __init__(self):
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        return 200, {}

    def delete(self, cid):
        self.calls.append(("DELETE", cid, None))


class FakeRunner:
    def __init__(self):
        self.calls = []

    def run(self, cmd, capture_output=True, text=True, timeout=10):
        self.calls.append(cmd)
        joined = " ".join(cmd)
        if cmd[:2] == ["docker", "ps"]:
            return _result("refall-agent-canvas\nother-container\n")
        if cmd[:2] == ["pgrep", "-f"] and "coverage_service" in joined:
            return _result("111\n")
        if cmd[:2] == ["pgrep", "-f"] and "drive_" in joined:
            return _result("222\n")
        if cmd[:2] == ["pgrep", "-f"]:
            return _result("", 1)
        if cmd[:2] == ["lsof", "-tiTCP:8900"]:
            return _result("333\n")
        return _result("")


def _result(stdout="", returncode=0, stderr=""):
    class Result:
        pass

    r = Result()
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


def test_cleanup_marks_stop_interrupts_conversations_and_clears_active_ids(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "active_cids.txt").write_text("cid-1\n\ncid-2\n")
    fake_oh = FakeOH()

    out = RefallCleanup(data_dir=data_dir, oh_factory=lambda: fake_oh, runner=FakeRunner()).run(
        stop_containers=False,
        stop_processes=False,
    )

    assert (data_dir / "STOP").exists()
    assert (data_dir / "active_cids.txt").read_text() == ""
    assert ("POST", "/api/conversations/cid-1/interrupt", {}) in fake_oh.calls
    assert ("DELETE", "cid-1", None) in fake_oh.calls
    assert out["conversations"] == ["cid-1", "cid-2"]


def test_cleanup_dry_run_discovers_targets_without_stopping_them(tmp_path):
    runner = FakeRunner()

    out = RefallCleanup(data_dir=tmp_path, oh_factory=lambda: FakeOH(), runner=runner).run(
        dry_run=True,
        include_serena=False,
    )

    assert out["dry_run"] is True
    assert "refall-agent-canvas" in out["containers"]
    assert out["pids"]["patterns"]["coverage_service"] == [111]
    assert out["pids"]["ports"][8900] == [333]
    assert ["docker", "stop", "refall-agent-canvas"] not in runner.calls
    assert ["kill", "111"] not in runner.calls


def test_cleanup_can_include_serena_when_requested(tmp_path):
    runner = FakeRunner()

    RefallCleanup(data_dir=tmp_path, oh_factory=lambda: FakeOH(), runner=runner).run(
        dry_run=True,
        include_serena=True,
    )

    assert any(cmd[:2] == ["pgrep", "-f"] and "serena start-mcp-server" in cmd[-1] for cmd in runner.calls)


def test_cleanup_tolerates_missing_host_tools(tmp_path):
    class MissingRunner:
        def run(self, *args, **kwargs):
            raise FileNotFoundError(args[0][0])

    out = RefallCleanup(data_dir=tmp_path, oh_factory=lambda: FakeOH(), runner=MissingRunner()).run(
        dry_run=True,
    )

    assert out["containers"] == []
    assert out["pids"]["patterns"]["coverage_service"] == []
    assert out["pids"]["ports"][8900] == []
