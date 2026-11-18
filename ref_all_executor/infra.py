import os
import subprocess
from pathlib import Path

from .cleanup import DEFAULT_DATA_DIR, RefallCleanup


REPO_ROOT = Path(__file__).resolve().parents[1]
OPENHANDS_CONTAINER = "refall-agent-canvas"
COVERAGE_SESSION = "refall-coverage"
TOOLCHAIN_SESSION = "refall-toolchain"
TOOLCHAIN_REQUIRED_SERVICES = ("python-lsp-server", "serena")


class RefallInfra:
    """Umbrella lifecycle helper for local reusable REF-All infrastructure."""

    def __init__(self, repo_root=None, data_dir=None, runner=subprocess):
        self.repo_root = Path(repo_root or REPO_ROOT)
        self.data_dir = Path(data_dir or DEFAULT_DATA_DIR)
        self.runner = runner

    def status(self):
        return {
            "coverage": self._coverage_status(),
            "openhands": self._openhands_status(),
            "toolchain": self._toolchain_status(),
        }

    def up(self, *, dry_run=False):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        stop_file = self.data_dir / "STOP"
        if stop_file.exists() and not dry_run:
            stop_file.unlink()
        return {
            "dry_run": dry_run,
            "stop_file": str(stop_file),
            "coverage": self._ensure_coverage(dry_run),
            "openhands": self._ensure_openhands(dry_run),
            "toolchain": self._ensure_toolchain(dry_run),
        }

    def down(self, *, dry_run=False, include_serena=True):
        return RefallCleanup(data_dir=self.data_dir, runner=self.runner).run(
            dry_run=dry_run,
            include_serena=include_serena,
            ports=[8900, 20871, 20872],
        )

    def restart(self, *, dry_run=False, include_serena=True):
        return {
            "down": self.down(dry_run=dry_run, include_serena=include_serena),
            "up": self.up(dry_run=dry_run),
        }

    def _cmd(self, cmd, timeout=10):
        try:
            return self.runner.run(cmd, capture_output=True, text=True, timeout=timeout)
        except OSError as exc:
            return subprocess.CompletedProcess(cmd, 127, "", str(exc))

    def _tmux_available(self):
        return self._cmd(["bash", "-lc", "command -v tmux"], timeout=5).returncode == 0

    def _tmux_has_session(self, name):
        return self._cmd(["tmux", "has-session", "-t", name], timeout=5).returncode == 0

    def _tmux_start(self, name, command, dry_run):
        if self._tmux_has_session(name):
            return "tmux-already-running"
        if not dry_run:
            self._cmd(["tmux", "new-session", "-d", "-s", name, command], timeout=10)
        return "tmux-would-start" if dry_run else "tmux-started"

    def _port_pids(self, port):
        result = self._cmd(["lsof", f"-tiTCP:{port}", "-sTCP:LISTEN"])
        if result.returncode not in (0, 1):
            return []
        pids = []
        for line in (result.stdout or "").splitlines():
            try:
                pid = int(line.strip())
            except ValueError:
                continue
            if pid not in pids:
                pids.append(pid)
        return pids

    def _coverage_status(self):
        pids = self._port_pids(8900)
        return {
            "state": "running" if pids else "down",
            "url": "http://localhost:8900",
            "pids": pids,
            "log": str(self.data_dir / "service.log"),
        }

    def _ensure_coverage(self, dry_run):
        status = self._coverage_status()
        if status["state"] == "running":
            return {**status, "action": "already-running"}
        if self._tmux_available():
            cmd = (
                f"cd {_sh(str(self.repo_root))} || exit 1; "
                "mkdir -p coverage_service/data || exit 1; "
                "echo $$ > coverage_service/data/service.pid; "
                "exec python3 -m coverage_service >> coverage_service/data/service.log 2>&1"
            )
            action = self._tmux_start(COVERAGE_SESSION, cmd, dry_run)
            return {**status, "action": "would-start" if dry_run else "started", "launcher": action}
        cmd = (
            f"cd {_sh(str(self.repo_root))} || exit 1; "
            "mkdir -p coverage_service/data || exit 1; "
            "nohup python3 -m coverage_service </dev/null > coverage_service/data/service.log 2>&1 & "
            "echo $! > coverage_service/data/service.pid"
        )
        if not dry_run:
            self._cmd(["bash", "-lc", cmd], timeout=5)
        return {**status, "action": "would-start" if dry_run else "started"}

    def _openhands_status(self):
        running = self._cmd(["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"])
        if running.returncode == 0:
            for line in (running.stdout or "").splitlines():
                name, _, state = line.partition("\t")
                if name == OPENHANDS_CONTAINER:
                    return {"state": "running", "container": name, "docker_status": state, "source": "docker"}
        all_containers = self._cmd(["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"])
        if all_containers.returncode == 0:
            for line in (all_containers.stdout or "").splitlines():
                name, _, state = line.partition("\t")
                if name == OPENHANDS_CONTAINER:
                    return {"state": "stopped", "container": name, "docker_status": state}
        # Manager sessions may not have access to the Docker socket even while
        # the existing Canvas proxy is healthy.  The proxy/API is the
        # authoritative runtime boundary for REFALL, so use a read-only HTTP
        # probe before declaring Canvas missing.
        proxy = os.environ.get("REFALL_OPENHANDS_BASE", "http://127.0.0.1:8000").rstrip("/")
        probe = self._cmd(
            ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "5", proxy + "/"],
            timeout=8,
        )
        if probe.returncode == 0 and str(probe.stdout or "").strip() in {"200", "401", "404"}:
            return {"state": "running", "container": OPENHANDS_CONTAINER, "docker_status": "proxy reachable", "source": "proxy"}
        return {"state": "missing", "container": OPENHANDS_CONTAINER, "docker_status": ""}

    def _ensure_openhands(self, dry_run):
        status = self._openhands_status()
        if status["state"] == "running":
            return {**status, "action": "already-running"}
        if status["state"] == "stopped":
            if not dry_run:
                self._cmd(["docker", "start", OPENHANDS_CONTAINER], timeout=60)
            return {**status, "action": "would-start" if dry_run else "started"}
        return {
            **status,
            "action": "missing",
            "hint": "create/start the OpenHands agent-canvas container named refall-agent-canvas",
        }

    def _toolchain_status(self):
        ctl = self.repo_root / "toolchain" / "ctl.sh"
        if not ctl.exists():
            return {"state": "missing", "ctl": str(ctl), "stdout": "", "stderr": ""}
        result = self._cmd(["bash", "-lc", f"{_sh(str(ctl))} status"], timeout=20)
        return {
            "state": "reported" if result.returncode == 0 else "error",
            "ctl": str(ctl),
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def _ensure_toolchain(self, dry_run):
        ctl = self.repo_root / "toolchain" / "ctl.sh"
        if not ctl.exists():
            return {"state": "missing", "ctl": str(ctl), "action": "missing"}
        cmd = f"{_sh(str(ctl))} up python-lsp-server serena"
        status = self._toolchain_status()
        if status["state"] == "reported" and _toolchain_required_running(status["stdout"]):
            return {**status, "action": "already-running"}
        if self._tmux_available():
            if self._tmux_has_session(TOOLCHAIN_SESSION) and not _toolchain_required_running(status["stdout"]):
                if not dry_run:
                    self._cmd(["tmux", "kill-session", "-t", TOOLCHAIN_SESSION], timeout=5)
            tmux_cmd = (
                f"cd {_sh(str(self.repo_root))} || exit 1; "
                f"{cmd}; "
                f"{_sh(str(ctl))} status; "
                "exec tail -f /dev/null"
            )
            action = self._tmux_start(TOOLCHAIN_SESSION, tmux_cmd, dry_run)
            status = self._toolchain_status()
            return {**status, "action": "would-start" if dry_run else "started", "launcher": action}
        if not dry_run:
            self._cmd(["bash", "-lc", cmd], timeout=60)
        status = self._toolchain_status()
        return {**status, "action": "would-start" if dry_run else "started"}


def _sh(value):
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def _toolchain_required_running(stdout):
    states = {}
    for line in (stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in TOOLCHAIN_REQUIRED_SERVICES:
            states[parts[0]] = parts[1]
    return all(states.get(service) == "running" for service in TOOLCHAIN_REQUIRED_SERVICES)
