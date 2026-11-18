from pathlib import Path
import subprocess

import pytest

from ref_all_executor.agent_workspace import AgentWorkspaceError, sync_agent_canvas_workspace


def test_sync_agent_canvas_workspace_copies_source_into_subject_workspace(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("print('ok')\n", encoding="utf-8")
    calls = []

    class Runner:
        @staticmethod
        def run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            if cmd[:4] == ["docker", "inspect", "-f", "{{json .Mounts}}"]:
                return subprocess.CompletedProcess(cmd, 0, "[]\n", "")
            if cmd[:4] == ["docker", "exec", "refall-agent-canvas", "cat"]:
                return subprocess.CompletedProcess(cmd, 1, "", "missing")
            return subprocess.CompletedProcess(cmd, 0, "true\n", "")

    result = sync_agent_canvas_workspace("alpha", source, runner=Runner)

    commands = [cmd for cmd, _ in calls]
    assert commands == [
        ["docker", "inspect", "-f", "{{.State.Running}}", "refall-agent-canvas"],
        ["docker", "inspect", "-f", "{{json .Mounts}}", "refall-agent-canvas"],
        ["docker", "exec", "refall-agent-canvas", "cat", "/projects/alpha/.refall-workspace-sync.json"],
        ["docker", "exec", "refall-agent-canvas", "rm", "-rf", "/projects/alpha"],
        ["docker", "exec", "refall-agent-canvas", "mkdir", "-p", "/projects/alpha"],
        ["docker", "cp", f"{source.resolve()}/.", "refall-agent-canvas:/projects/alpha"],
        ["docker", "exec", "-i", "refall-agent-canvas", "tee", "/projects/alpha/.refall-workspace-sync.json"],
        ["docker", "exec", "refall-agent-canvas", "test", "-d", "/projects/alpha"],
    ]
    assert result == {
        "status": "synced",
        "container": "refall-agent-canvas",
        "source_path": str(source.resolve()),
        "workspace": "/projects/alpha",
    }


def test_sync_agent_canvas_workspace_skips_current_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    payload = "print('ok')\n"
    file_path = source / "app.py"
    file_path.write_text(payload, encoding="utf-8")
    stat = file_path.stat()
    marker = (
        '{"version":1,'
        f'"source_path":"{source.resolve()}",'
        '"files":1,'
        f'"bytes":{len(payload.encode("utf-8"))},'
        f'"latest_mtime_ns":{stat.st_mtime_ns}'
        "}"
    )
    calls = []

    class Runner:
        @staticmethod
        def run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            if cmd[:4] == ["docker", "inspect", "-f", "{{json .Mounts}}"]:
                return subprocess.CompletedProcess(cmd, 0, "[]\n", "")
            if cmd[:4] == ["docker", "exec", "refall-agent-canvas", "cat"]:
                return subprocess.CompletedProcess(cmd, 0, marker, "")
            return subprocess.CompletedProcess(cmd, 0, "true\n", "")

    result = sync_agent_canvas_workspace("alpha", source, runner=Runner)

    commands = [cmd for cmd, _ in calls]
    assert commands == [
        ["docker", "inspect", "-f", "{{.State.Running}}", "refall-agent-canvas"],
        ["docker", "inspect", "-f", "{{json .Mounts}}", "refall-agent-canvas"],
        ["docker", "exec", "refall-agent-canvas", "cat", "/projects/alpha/.refall-workspace-sync.json"],
        ["docker", "exec", "refall-agent-canvas", "test", "-d", "/projects/alpha"],
    ]
    assert result["status"] == "already-synced"
    assert result["workspace"] == "/projects/alpha"


def test_sync_agent_canvas_workspace_retries_stale_snapshot_delete_as_root(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("print('ok')\n", encoding="utf-8")
    calls = []

    class Runner:
        @staticmethod
        def run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            if cmd[:4] == ["docker", "inspect", "-f", "{{json .Mounts}}"]:
                return subprocess.CompletedProcess(cmd, 0, "[]\n", "")
            if cmd[:4] == ["docker", "exec", "refall-agent-canvas", "cat"]:
                return subprocess.CompletedProcess(cmd, 1, "", "missing")
            if cmd == ["docker", "exec", "refall-agent-canvas", "rm", "-rf", "/projects/alpha"]:
                return subprocess.CompletedProcess(cmd, 1, "", "Permission denied")
            return subprocess.CompletedProcess(cmd, 0, "true\n", "")

    result = sync_agent_canvas_workspace("alpha", source, runner=Runner)

    commands = [cmd for cmd, _ in calls]
    assert ["docker", "exec", "refall-agent-canvas", "rm", "-rf", "/projects/alpha"] in commands
    assert ["docker", "exec", "-u", "root", "refall-agent-canvas", "rm", "-rf", "/projects/alpha"] in commands
    assert result["status"] == "synced"


def test_sync_agent_canvas_workspace_uses_existing_subject_bind_mount(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    calls = []

    class Runner:
        @staticmethod
        def run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            if cmd[:4] == ["docker", "inspect", "-f", "{{json .Mounts}}"]:
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    f'[{{"Source":"{source.resolve()}","Destination":"/projects/alpha","RW":false}}]\n',
                    "",
                )
            return subprocess.CompletedProcess(cmd, 0, "true\n", "")

    result = sync_agent_canvas_workspace("alpha", source, runner=Runner)

    commands = [cmd for cmd, _ in calls]
    assert commands == [
        ["docker", "inspect", "-f", "{{.State.Running}}", "refall-agent-canvas"],
        ["docker", "inspect", "-f", "{{json .Mounts}}", "refall-agent-canvas"],
        ["docker", "exec", "refall-agent-canvas", "test", "-d", "/projects/alpha"],
    ]
    assert result["status"] == "mounted"
    assert result["read_only"] is True
    assert result["workspace"] == "/projects/alpha"


def test_sync_agent_canvas_workspace_refuses_missing_source(tmp_path: Path) -> None:
    with pytest.raises(AgentWorkspaceError, match="source path is not a directory"):
        sync_agent_canvas_workspace("alpha", tmp_path / "missing")


def test_sync_agent_canvas_workspace_refuses_unavailable_container(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()

    class Runner:
        @staticmethod
        def run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, "", "no such container")

    with pytest.raises(AgentWorkspaceError, match="not running"):
        sync_agent_canvas_workspace("alpha", source, runner=Runner)
