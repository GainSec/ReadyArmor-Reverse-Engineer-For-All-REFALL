from __future__ import annotations

import os
import json
import subprocess
from pathlib import Path


DEFAULT_CONTAINER = "refall-agent-canvas"
DEFAULT_WORKSPACE_ROOT = "/projects"


class AgentWorkspaceError(RuntimeError):
    pass


def sync_agent_canvas_workspace(
    subject: str,
    source_path: str | Path,
    *,
    runner=subprocess,
    container: str | None = None,
    workspace_root: str | None = None,
    timeout_s: int = 300,
) -> dict:
    """Copy the host subject source into the Agent Canvas /projects workspace."""
    source = Path(source_path).expanduser().resolve()
    if not source.is_dir():
        raise AgentWorkspaceError(f"REFALL source path is not a directory: {source}")

    name = container or os.environ.get("REFALL_OPENHANDS_CONTAINER", DEFAULT_CONTAINER)
    root = (workspace_root or os.environ.get("REFALL_SUBJECT_WORKSPACE_ROOT", DEFAULT_WORKSPACE_ROOT)).rstrip("/")
    dest = f"{root}/{_safe_subject_name(subject)}"
    marker_path = f"{dest}/.refall-workspace-sync.json"
    snapshot = _source_snapshot(source)

    _run(
        runner,
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        timeout=20,
        error=f"Agent Canvas container is not running: {name}",
        expect_stdout="true",
    )
    existing_mount = _existing_source_mount(runner, name, source, dest)
    if existing_mount is not None:
        _run(
            runner,
            ["docker", "exec", name, "test", "-d", dest],
            timeout=20,
            error=f"Agent Canvas workspace verification failed: {dest}",
        )
        return {
            "status": "mounted",
            "container": name,
            "source_path": str(source),
            "workspace": dest,
            "read_only": not bool(existing_mount.get("RW", True)),
        }

    if _marker_matches(_read_marker(runner, name, marker_path), snapshot):
        _run(
            runner,
            ["docker", "exec", name, "test", "-d", dest],
            timeout=20,
            error=f"Agent Canvas workspace verification failed: {dest}",
        )
        return {
            "status": "already-synced",
            "container": name,
            "source_path": str(source),
            "workspace": dest,
        }

    _remove_existing_workspace(runner, name, dest)
    _run(runner, ["docker", "exec", name, "mkdir", "-p", dest], timeout=20)
    _run(
        runner,
        ["docker", "cp", f"{source}/.", f"{name}:{dest}"],
        timeout=timeout_s,
        error=f"failed to copy REFALL source into Agent Canvas workspace: {source} -> {dest}",
    )
    _run(
        runner,
        ["docker", "exec", "-i", name, "tee", marker_path],
        timeout=20,
        error=f"failed to write REFALL Agent Canvas workspace marker: {marker_path}",
        input_text=json.dumps(snapshot, sort_keys=True) + "\n",
    )
    _run(
        runner,
        ["docker", "exec", name, "test", "-d", dest],
        timeout=20,
        error=f"Agent Canvas workspace verification failed: {dest}",
    )
    return {
        "status": "synced",
        "container": name,
        "source_path": str(source),
        "workspace": dest,
    }


def _safe_subject_name(subject: str) -> str:
    value = str(subject or "").strip()
    if not value or "/" in value or value in {".", ".."}:
        raise AgentWorkspaceError(f"unsafe REFALL subject name for Agent Canvas workspace: {subject!r}")
    return value


def _source_snapshot(source: Path) -> dict:
    files = 0
    total_bytes = 0
    latest_mtime_ns = 0
    for root, dirs, names in os.walk(source):
        dirs.sort()
        names.sort()
        for name in names:
            path = Path(root) / name
            try:
                stat = path.stat()
            except OSError:
                continue
            files += 1
            total_bytes += stat.st_size
            latest_mtime_ns = max(latest_mtime_ns, stat.st_mtime_ns)
    return {
        "version": 1,
        "source_path": str(source),
        "files": files,
        "bytes": total_bytes,
        "latest_mtime_ns": latest_mtime_ns,
    }


def _read_marker(runner, container: str, marker_path: str) -> dict | None:
    try:
        result = runner.run(
            ["docker", "exec", container, "cat", marker_path],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _existing_source_mount(runner, container: str, source: Path, dest: str) -> dict | None:
    try:
        result = runner.run(
            ["docker", "inspect", "-f", "{{json .Mounts}}", container],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    try:
        mounts = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return None
    if not isinstance(mounts, list):
        return None
    for mount in mounts:
        if not isinstance(mount, dict) or mount.get("Destination") != dest:
            continue
        try:
            mounted_source = Path(str(mount.get("Source") or "")).expanduser().resolve()
        except OSError:
            continue
        if mounted_source == source:
            return mount
    return None


def _marker_matches(marker: dict | None, snapshot: dict) -> bool:
    if not marker:
        return False
    return all(marker.get(key) == snapshot.get(key) for key in snapshot)


def _remove_existing_workspace(runner, container: str, dest: str) -> None:
    try:
        _run(runner, ["docker", "exec", container, "rm", "-rf", dest], timeout=60)
    except AgentWorkspaceError as exc:
        if "Permission denied" not in str(exc):
            raise
        _run(runner, ["docker", "exec", "-u", "root", container, "rm", "-rf", dest], timeout=60)


def _run(
    runner,
    cmd: list[str],
    *,
    timeout: int,
    error: str | None = None,
    expect_stdout: str | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess:
    try:
        result = runner.run(cmd, capture_output=True, text=True, timeout=timeout, input=input_text)
    except OSError as exc:
        raise AgentWorkspaceError(error or f"command failed: {' '.join(cmd)}: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        raise AgentWorkspaceError((error or f"command failed: {' '.join(cmd)}") + suffix)
    if expect_stdout is not None and (result.stdout or "").strip() != expect_stdout:
        raise AgentWorkspaceError(error or f"unexpected command output from {' '.join(cmd)}")
    return result
