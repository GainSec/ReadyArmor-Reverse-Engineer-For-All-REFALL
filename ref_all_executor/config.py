import hashlib
import os
import re
import socket
from pathlib import Path

REFALL_WORKSPACE = os.environ.get("REFALL_WORKSPACE", "/projects/REFALL-V10")
SUBJECT_WORKSPACE_ROOT = os.environ.get("REFALL_SUBJECT_WORKSPACE_ROOT", "/projects")
AGENT_WORKSPACE_CONTAINER_ROOT_DEFAULT = "/projects/refallsub"
AGENT_WORKSPACE_HOST_ROOT_DEFAULT = "~/refallsub"

OH_BASE = os.environ.get("REFALL_OPENHANDS_BASE", "http://localhost:8000")
AUTO_BASE = OH_BASE + "/api/automation/v1"
def _private_lan_ipv4():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 1))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def resolve_public_base(value=None):
    raw = value or os.environ.get("REFALL_WORKBENCH_BASE") or os.environ.get("REFALL_PUBLIC_BASE_URL", "auto-lan")
    if raw in {"auto-lan", "auto"}:
        port = os.environ.get("REFALL_ARCTICBASE_PORT", "7673")
        return f"http://{_private_lan_ipv4()}:{port}"
    return raw


WB_BASE = resolve_public_base()
WB_SLUG = os.environ.get("REFALL_WORKBENCH_SLUG", "ref-all")
API_KEY_PATH = os.path.expanduser(
    os.environ.get("REFALL_OPENHANDS_API_KEY_PATH", "~/.openhands/agent-canvas/api-key.txt")
)

# Host-side directory where the Agent Canvas keeps per-conversation state. It is
# bind-mounted into the container read-write, so deleting a conversation removes
# its event stream from here too — archive the events before reaping a CID.
OPENHANDS_CONVERSATIONS_DIR = os.path.expanduser(
    os.environ.get("REFALL_OPENHANDS_CONVERSATIONS_DIR", "~/.openhands/agent-canvas/conversations")
)


def session_api_key() -> str:
    with open(API_KEY_PATH) as fh:
        return fh.read().strip()


SERENA_MCP_CONFIG = {
    "mcpServers": {
        "serena": {
            "transport": "streamable-http",
            "url": os.environ.get("REFALL_SERENA_MCP_URL", "http://127.0.0.1:20872/mcp"),
            "timeout": int(os.environ.get("REFALL_SERENA_MCP_TIMEOUT", "30")),
            "description": "Serena semantic code understanding MCP service managed by REFALL toolchain/ctl.sh",
        }
    }
}


LANES = {
    "A": {"agent_kind": "acp", "acp_server": "claude-code", "acp_command": [],
          "acp_model": os.environ.get("REFALL_CLAUDE_ACP_MODEL", "opus"),
          "acp_prompt_timeout": 1800, "mcp_config": SERENA_MCP_CONFIG},
    "B": {"agent_kind": "acp", "acp_server": "codex", "acp_command": [],
          "acp_model": "gpt-5.5", "acp_prompt_timeout": 1800, "mcp_config": SERENA_MCP_CONFIG},
    # Lane G is an optional host-orchestrated sandbox lane. Enable/configure only when a
    # local sandbox container is intentionally available for the subject.
    # NOT a normal OpenHands ACP lane, BY DESIGN — the sandbox that keeps Grok safe also keeps it out of
    # the lane model: (1) OpenHands driving it would spawn `grok agent stdio` locally (defeats the sandbox
    # → full host access) or need a docker socket in the agent-canvas (a hole it doesn't have); (2) on
    # 'no-lan' Grok CANNOT reach the coverage service (host.docker.internal:8900) to claim/record, which is
    # how real lanes work. So Grok is a HOST-ORCHESTRATED worker, not an agent-canvas lane.
    # PATTERN: manager puts subject material in /work, calls `docker exec grok-build grok -p "<task>"`
    # (+ --output-format json / --check / --always-approve) — always via the container, never local — then
    # the MANAGER bridges Grok's output back into REFALL (files findings, hands probe code to Lane A).
    # ROLE: theorize / web search / deep research / codegen / analysis + in-sandbox execution on /work.
    # DATA POLICY (per operator): subject material OK in /work; FORBIDDEN host-fs / creds / LAN / REFALL
    # infra. Grok Build exfiltrates /work to xAI — fine for subject artifacts, never for anything else.
    "G": {"runner": "host-orchestrated",
          "sandbox": os.environ.get("REFALL_GROK_SANDBOX", ""),
          "network_profile": os.environ.get("REFALL_GROK_NETWORK_PROFILE", "no-lan"),
          "drive": os.environ.get("REFALL_GROK_DRIVE", "docker exec -i grok-build grok -p").split(),
          "model": os.environ.get("REFALL_GROK_MODEL", "grok-0.2.103"),
          "data_policy": "subject-material-ok; no host-fs / no creds / no LAN"},
}
WORKSPACES = {"refall": REFALL_WORKSPACE}

# Coverage Service. Host-side callers (the executor) use localhost; agents inside the
# OpenHands container reach it via host.docker.internal (same pattern as searxng/firecrawl).
COVERAGE_MODE = os.environ.get("REFALL_COVERAGE_MODE", "workbench")
COVERAGE_BASE = os.environ.get("COVERAGE_BASE", "http://localhost:8900")
COVERAGE_BASE_CONTAINER = "http://host.docker.internal:8900"
REQUIRE_STRUCTURED_SUBMIT = os.environ.get("REFALL_REQUIRE_STRUCTURED_SUBMIT", "false").lower() in {
    "1",
    "true",
    "yes",
}
RETRY_MAX_ATTEMPTS = int(os.environ.get("REFALL_RETRY_MAX_ATTEMPTS", "2"))
RETRY_BACKOFF_S = float(os.environ.get("REFALL_RETRY_BACKOFF_S", "5"))
RETRY_MAX_REPAIR_PROMPT_CHARS = int(os.environ.get("REFALL_RETRY_MAX_REPAIR_PROMPT_CHARS", "4000"))


def local_workspace(working_dir):
    """A workspace whose tools run inside the main Agent Server container (/projects mounts)."""
    return {"kind": "LocalWorkspace", "working_dir": working_dir}


def remote_workspace(host, api_key, working_dir):
    """A workspace whose tools run on ANOTHER machine running its own OpenHands Agent Server.

    This is how a task reaches an operator-approved remote execution surface.
    host+api_key point at that box's agent-server.
    Not wired yet in Phase 1 (no remote agent-servers registered); the mechanism is ready.
    """
    return {"kind": "RemoteWorkspace", "host": host, "api_key": api_key,
            "working_dir": working_dir}


# host name -> how a task reaches that box's execution surface.
# Three mechanisms (decide per box in Phase 1c/2; none needed for local /projects work):
#   "local"  -> tools run in this container (the /projects mounts).
#   "ssh"    -> a LOCAL conversation whose bash does `ssh <target> <cmd>`. Lightest: nothing
#               runs on the other box, just needs SSH access+keys from this container.
#   "remote" -> RemoteWorkspace: an OpenHands Agent Server runs ON that box; tools execute there
#               natively. Heaviest (install per box; awkward on Windows). Use only where you want
#               full native tooling on the target.
# NOTE: do NOT route execution through Hermes here — it stays out of the critical path in Phase 1.
# Phase 2 Hermes-as-manager may CHOOSE the host, but execution stays deterministic (ssh/remote).
# PREREQUISITE to use SSH resources from Agent Canvas:
# mount ~/.ssh into the OpenHands container (agent bash runs there) as read-only.
ALLOWED_SSH_RESOURCE_ALIASES = (
    "sectortw",
    "sectortl",
)

DEFAULT_SSH_RESOURCE_ALIASES = (
    "sectortw",
    "sectortl",
)


def _ssh_resource_aliases() -> tuple[str, ...]:
    raw = os.environ.get("REFALL_SSH_RESOURCE_ALIASES")
    aliases = raw.split(",") if raw is not None else DEFAULT_SSH_RESOURCE_ALIASES
    allowed = set(ALLOWED_SSH_RESOURCE_ALIASES)
    out: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        item = alias.strip()
        if not item or item in seen or item not in allowed:
            continue
        seen.add(item)
        out.append(item)
    return tuple(out)


def _build_hosts() -> dict:
    hosts = {"local": {"kind": "local"}}
    for alias in _ssh_resource_aliases():
        hosts[alias] = {"kind": "ssh", "target": alias}
    return hosts


HOSTS = _build_hosts()


def ssh_resource_instructions() -> str:
    ssh_hosts = [
        (name, cfg["target"])
        for name, cfg in HOSTS.items()
        if cfg.get("kind") == "ssh" and cfg.get("target")
    ]
    if not ssh_hosts:
        return ""
    host_lines = "\n".join(f"- `{name}`: run commands with `ssh {target} <command>`." for name, target in ssh_hosts)
    return (
        "## Remote SSH Resources\n"
        "The operator has made these SSH execution surfaces available for loop agents when a task needs "
        "a specific OS, host-local service, hardware, or build/runtime environment. Do not assume a remote "
        "host is needed for ordinary local source review. When the manager assigns one, run the relevant "
        "shell commands through SSH and record the host alias, command, and evidence references in the "
        "terminal REFALL submission.\n"
        f"{host_lines}"
    )


def subject_workspace(subject):
    """Container path for a mounted subject directory."""
    return f"{SUBJECT_WORKSPACE_ROOT.rstrip('/')}/{subject}"


def subject_agent_workspace(
    subject,
    *,
    lane: str = "",
    task_class: str = "",
    unit: dict | None = None,
    objective: str = "",
) -> str:
    """Container path for a writable per-task Agent Canvas workspace."""
    root = os.environ.get("REFALL_AGENT_WORKSPACE_CONTAINER_ROOT", AGENT_WORKSPACE_CONTAINER_ROOT_DEFAULT).rstrip("/")
    return f"{root}/{_safe_path_component(subject)}/{agent_workspace_name(lane=lane, task_class=task_class, unit=unit, objective=objective)}"


def prepare_subject_agent_workspace(
    subject,
    *,
    lane: str = "",
    task_class: str = "",
    unit: dict | None = None,
    objective: str = "",
) -> str:
    """Create the host-side writable workspace and return its container path."""
    host_root = Path(os.environ.get("REFALL_AGENT_WORKSPACE_HOST_ROOT", AGENT_WORKSPACE_HOST_ROOT_DEFAULT)).expanduser()
    subject_name = _safe_path_component(subject)
    workspace_name = agent_workspace_name(lane=lane, task_class=task_class, unit=unit, objective=objective)
    (host_root / subject_name / workspace_name).mkdir(parents=True, exist_ok=True)
    return subject_agent_workspace(
        subject,
        lane=lane,
        task_class=task_class,
        unit=unit,
        objective=objective,
    )


def agent_workspace_host_path(
    subject,
    *,
    lane: str = "",
    task_class: str = "",
    unit: dict | None = None,
    objective: str = "",
) -> Path:
    """Host-side path of an agent's writable workspace, where it saves its
    deliverables (REFALL_SUBMISSION.json, analysis files, disassembly)."""
    host_root = Path(os.environ.get("REFALL_AGENT_WORKSPACE_HOST_ROOT", AGENT_WORKSPACE_HOST_ROOT_DEFAULT)).expanduser()
    return host_root / _safe_path_component(subject) / agent_workspace_name(
        lane=lane, task_class=task_class, unit=unit, objective=objective
    )


def agent_workspace_name(
    *,
    lane: str = "",
    task_class: str = "",
    unit: dict | None = None,
    objective: str = "",
) -> str:
    unit = unit or {}
    identity = str(unit.get("id") or unit.get("path") or unit.get("name") or "").strip()
    if not identity:
        identity = hashlib.sha1((objective or task_class or "task").encode("utf-8")).hexdigest()[:12]
    parts = [lane, task_class, identity]
    return "-".join(_safe_path_component(part) for part in parts if str(part or "").strip())


def _safe_path_component(value) -> str:
    raw = str(value or "").strip()
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip(".-")
    return cleaned[:80] or "task"


def ssh_preamble(host_name):
    """For an ssh host, instruct the agent to run its commands on that box via ssh.
    Returns '' for local hosts. The conversation still uses a LocalWorkspace (in this
    container); the agent shells out with `ssh <target>`."""
    h = HOSTS.get(host_name, {})
    if h.get("kind") == "ssh":
        return (f"IMPORTANT: run every shell command on host '{h['target']}' by prefixing it with "
                f"`ssh {h['target']} ` — the target hardware/OS lives there, not in this sandbox.\n\n")
    return ""


class Tier:
    T1 = "tier_1_live_confirmed"
    T2 = "tier_2_code_confirmed"
    T3 = "tier_3_hypothesis"
