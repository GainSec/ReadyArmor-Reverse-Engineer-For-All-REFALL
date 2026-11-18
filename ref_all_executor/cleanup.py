import os
import subprocess
from pathlib import Path

from .oh_client import OHClient


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = REPO_ROOT / "coverage_service" / "data"
DEFAULT_CONTAINER_PATTERNS = ("refall-agent-canvas", "openhands")
DEFAULT_PROCESS_PATTERNS = {
    "coverage_service": r"python.*-m coverage_service",
    "drivers": r"drive_(characterize|research|binresearch|binreview|binvalidate|context)\.py",
}
SERENA_PROCESS_PATTERN = r"serena start-mcp-server|VueLanguageServer|typescript-language-server|tsserver\.js"


class RefallCleanup:
    """Stop local REF-All loop runtime without relying on stale terminal state."""

    def __init__(self, data_dir=None, oh_factory=OHClient, runner=subprocess):
        self.data_dir = Path(data_dir or DEFAULT_DATA_DIR)
        self.oh_factory = oh_factory
        self.runner = runner

    def run(
        self,
        *,
        dry_run=False,
        include_serena=False,
        stop_conversations=True,
        stop_containers=True,
        stop_processes=True,
        ports=None,
        container_patterns=None,
        extra_process_patterns=None,
    ):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._mark_stop(dry_run)
        conversations = self._stop_conversations(dry_run) if stop_conversations else []

        containers = []
        if stop_containers:
            containers = self._stop_containers(
                dry_run,
                tuple(container_patterns or DEFAULT_CONTAINER_PATTERNS),
            )

        pids = {"patterns": {}, "ports": {}}
        if stop_processes:
            process_patterns = dict(DEFAULT_PROCESS_PATTERNS)
            if include_serena:
                process_patterns["serena"] = SERENA_PROCESS_PATTERN
            if extra_process_patterns:
                process_patterns.update(extra_process_patterns)
            port_list = list(ports if ports is not None else [8900])
            if include_serena and 20872 not in port_list:
                port_list.append(20872)
            pids = self._stop_processes(dry_run, process_patterns, port_list)

        return {
            "dry_run": dry_run,
            "stop_file": str(self.data_dir / "STOP"),
            "conversations": conversations,
            "containers": containers,
            "pids": pids,
        }

    def _mark_stop(self, dry_run):
        if not dry_run:
            (self.data_dir / "STOP").touch()

    def _active_cids_path(self):
        return self.data_dir / "active_cids.txt"

    def _read_active_cids(self):
        path = self._active_cids_path()
        if not path.exists():
            return []
        return [line.strip() for line in path.read_text().splitlines() if line.strip()]

    def _stop_conversations(self, dry_run):
        cids = self._read_active_cids()
        if dry_run or not cids:
            return cids
        oh = self.oh_factory()
        for cid in cids:
            try:
                oh.request("POST", f"/api/conversations/{cid}/interrupt", {})
            except Exception:
                pass
            try:
                oh.delete(cid)
            except Exception:
                pass
        self._active_cids_path().write_text("")
        return cids

    def _cmd(self, cmd, timeout=10):
        try:
            return self.runner.run(cmd, capture_output=True, text=True, timeout=timeout)
        except OSError as e:
            return subprocess.CompletedProcess(cmd, 127, "", str(e))

    def _stop_containers(self, dry_run, patterns):
        result = self._cmd(["docker", "ps", "--format", "{{.Names}}"])
        names = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        targets = [name for name in names if any(pattern in name for pattern in patterns)]
        if not dry_run:
            for name in targets:
                self._cmd(["docker", "stop", name], timeout=60)
        return targets

    def _pgrep(self, pattern):
        result = self._cmd(["pgrep", "-f", pattern])
        if result.returncode not in (0, 1):
            return []
        return self._parse_pids(result.stdout)

    def _lsof_port(self, port):
        result = self._cmd(["lsof", f"-tiTCP:{port}", "-sTCP:LISTEN"])
        if result.returncode not in (0, 1):
            return []
        return self._parse_pids(result.stdout)

    def _parse_pids(self, text):
        current = os.getpid()
        pids = []
        for line in (text or "").splitlines():
            try:
                pid = int(line.strip())
            except ValueError:
                continue
            if pid != current and pid not in pids:
                pids.append(pid)
        return pids

    def _stop_processes(self, dry_run, process_patterns, ports):
        by_pattern = {name: self._pgrep(pattern) for name, pattern in process_patterns.items()}
        by_port = {int(port): self._lsof_port(int(port)) for port in ports}
        all_pids = []
        for group in (by_pattern.values(), by_port.values()):
            for pids in group:
                for pid in pids:
                    if pid not in all_pids:
                        all_pids.append(pid)
        if not dry_run:
            for pid in all_pids:
                self._cmd(["kill", str(pid)])
        return {"patterns": by_pattern, "ports": by_port}
