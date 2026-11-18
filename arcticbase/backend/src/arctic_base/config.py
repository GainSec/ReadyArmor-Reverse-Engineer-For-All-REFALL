import os
import socket
from ipaddress import ip_address
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AUTO_LAN_HOST = "auto-lan"
DEFAULT_REFALL_REPO_ROOT = Path(__file__).resolve().parents[4]


def _is_private_lan_ipv4(value: str) -> bool:
    try:
        address = ip_address(value)
    except ValueError:
        return False
    return (
        address.version == 4
        and address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_unspecified
    )


def _detect_private_lan_ipv4() -> str:
    candidates: list[str] = []

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 1))
            candidates.append(sock.getsockname()[0])
    except OSError:
        pass

    try:
        for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidates.append(result[4][0])
    except OSError:
        pass

    for candidate in candidates:
        if _is_private_lan_ipv4(candidate):
            return candidate

    return "127.0.0.1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARCTIC_BASE_", env_file=".env", extra="ignore")

    data: Path = Field(default=Path("./data"))
    port: int = 7673
    host: str = AUTO_LAN_HOST
    max_upload_bytes: int = 2 * 1024 * 1024 * 1024  # 2 GB
    frontend_dist: Path = Field(default=Path("../frontend/dist"))
    seed_data: Path = Field(default=Path("./seed"))

    refall_enable_ops: bool = Field(default=False, validation_alias="REFALL_ENABLE_OPS")
    refall_enable_ops_commands: bool = Field(
        default=False,
        validation_alias="REFALL_ENABLE_OPS_COMMANDS",
    )
    refall_deployment_mode: str = Field(
        default="local-dev",
        validation_alias="REFALL_DEPLOYMENT_MODE",
    )
    refall_data_root: Path = Field(
        default=Path("/var/lib/refall"),
        validation_alias="REFALL_DATA_ROOT",
    )
    refall_subject_root: Path | None = Field(
        default=None,
        validation_alias="REFALL_SUBJECT_ROOT",
    )
    refall_arcticbase_data: Path = Field(
        default=Path("/var/lib/refall/arcticbase"),
        validation_alias="REFALL_ARCTICBASE_DATA",
    )
    refall_arcticbase_host: str = Field(
        default=AUTO_LAN_HOST,
        validation_alias="REFALL_ARCTICBASE_HOST",
    )
    refall_arcticbase_port: int = Field(default=7673, validation_alias="REFALL_ARCTICBASE_PORT")
    refall_public_base_url: str = Field(
        default=AUTO_LAN_HOST,
        validation_alias="REFALL_PUBLIC_BASE_URL",
    )
    refall_openhands_base: str = Field(
        default="http://127.0.0.1:8000",
        validation_alias="REFALL_OPENHANDS_BASE",
    )
    refall_openhands_api_key_path: Path | None = Field(
        default=None,
        validation_alias="REFALL_OPENHANDS_API_KEY_PATH",
    )
    refall_capability_operator_token_path: Path | None = Field(
        default=None,
        validation_alias="REFALL_CAPABILITY_OPERATOR_TOKEN_PATH",
    )
    refall_ops_allowed_commands: str = Field(
        default="status,subjects,agents,infra,start,update,closeout,context,coverage,threat-model,doctor,estimate,logs",
        validation_alias="REFALL_OPS_ALLOWED_COMMANDS",
    )
    refall_workbench_tag: str = Field(default="refall", validation_alias="REFALL_WORKBENCH_TAG")
    refall_head_agent_name: str = Field(
        default="refall-head",
        validation_alias="REFALL_HEAD_AGENT_NAME",
    )
    refall_head_provider: str = Field(default="codex", validation_alias="REFALL_HEAD_PROVIDER")
    refall_allowed_head_providers: str = Field(
        default="codex,claude,grok",
        validation_alias="REFALL_ALLOWED_HEAD_PROVIDERS",
    )
    refall_codex_command: str = Field(default="codex", validation_alias="REFALL_CODEX_COMMAND")
    refall_claude_command: str = Field(default="claude", validation_alias="REFALL_CLAUDE_COMMAND")
    refall_grok_command: str = Field(default="grok", validation_alias="REFALL_GROK_COMMAND")
    refall_context_manager_timeout_s: int = Field(
        default=1800,
        validation_alias="REFALL_CONTEXT_MANAGER_TIMEOUT_S",
    )
    refall_repo_root: Path = Field(
        default=DEFAULT_REFALL_REPO_ROOT,
        validation_alias="REFALL_REPO_ROOT",
    )
    refall_enable_loop_launch: bool = Field(
        default=True,
        validation_alias="REFALL_ENABLE_LOOP_LAUNCH",
    )
    refall_enable_loop_supervisor_cron: bool = Field(
        default=True,
        validation_alias="REFALL_ENABLE_LOOP_SUPERVISOR_CRON",
    )
    refall_loop_max_parallel: int = Field(
        default=4,
        validation_alias="REFALL_LOOP_MAX_PARALLEL",
    )
    refall_loop_poll_interval_s: float = Field(
        default=5,
        validation_alias="REFALL_LOOP_POLL_INTERVAL_S",
    )
    refall_loop_report_interval_cycles: int = Field(
        default=10,
        validation_alias="REFALL_LOOP_REPORT_INTERVAL_CYCLES",
    )
    refall_loop_stall_cycles: int = Field(
        default=36,
        validation_alias="REFALL_LOOP_STALL_CYCLES",
    )

    @model_validator(mode="after")
    def derive_refall_paths(self) -> "Settings":
        lan_ip: str | None = None

        def resolve_auto_lan(value: str) -> str:
            nonlocal lan_ip
            if value.strip().lower() != AUTO_LAN_HOST:
                return value
            if lan_ip is None:
                lan_ip = _detect_private_lan_ipv4()
            return lan_ip

        self.host = resolve_auto_lan(self.host)
        self.refall_arcticbase_host = resolve_auto_lan(self.refall_arcticbase_host)
        if self.refall_public_base_url.strip().lower() in {AUTO_LAN_HOST, "auto"}:
            public_host = self.refall_arcticbase_host
            if public_host in {"0.0.0.0", "::"}:
                public_host = resolve_auto_lan(AUTO_LAN_HOST)
            self.refall_public_base_url = f"http://{public_host}:{self.refall_arcticbase_port}"
        if "REFALL_DATA_ROOT" not in os.environ:
            self.refall_data_root = self.data / "refall"
        if self.refall_subject_root is None:
            self.refall_subject_root = self.refall_data_root / "subjects"
        return self


def get_settings() -> Settings:
    return Settings()
