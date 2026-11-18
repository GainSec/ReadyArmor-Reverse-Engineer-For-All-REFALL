from __future__ import annotations

import json
import os
import shutil
import urllib.error
import urllib.request
from pathlib import Path

from . import config


PROVIDER_ENV = {
    "codex": "REFALL_CODEX_COMMAND",
    "claude": "REFALL_CLAUDE_COMMAND",
    "grok": "REFALL_GROK_COMMAND",
}
SECRET_ENV = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "GROK_API_KEY",
)


def doctor(
    *,
    subject: str | None = None,
    check_network: bool = True,
    arcticbase=None,
    repo_root: Path | None = None,
) -> dict:
    root = repo_root or Path(__file__).resolve().parents[1]
    checks: list[dict] = []
    _add(checks, "arcticbase_base", "ok", f"base URL configured: {_base_url()}")
    _add(checks, "agent_canvas", "ok", f"Agent Canvas URL configured: {_openhands_base()}")
    if check_network:
        _network_checks(checks)
    for provider in _allowed_providers():
        command = _provider_command(provider)
        _add(
            checks,
            f"provider.{provider}",
            "ok" if shutil.which(command) else "warn",
            f"{provider} command {'available' if shutil.which(command) else 'not found'}",
            command=command,
        )
    _secret_checks(checks)
    _filesystem_checks(checks, root, subject)
    _arcticbase_subject_checks(checks, subject, arcticbase)
    return {
        "status": _aggregate_status(checks),
        "subject": subject,
        "checks": checks,
    }


def _network_checks(checks: list[dict]) -> None:
    base = _base_url().rstrip("/")
    for check_id, path in (
        ("arcticbase_http", "/api/refall/ops/status"),
        ("agent_canvas_http", ""),
    ):
        url = f"{base}{path}" if check_id == "arcticbase_http" else _openhands_base()
        try:
            status, _body = _http_get(url)
        except Exception as exc:
            _add(checks, check_id, "warn", f"{url} unreachable: {exc}")
            continue
        _add(checks, check_id, "ok" if status < 500 else "warn", f"{url} returned HTTP {status}")


def _filesystem_checks(checks: list[dict], root: Path, subject: str | None) -> None:
    for check_id, path in (
        ("toolchain.install", root / "toolchain" / "install.sh"),
        ("toolchain.codebadger", root / "toolchain" / "bin" / "codebadger-service"),
        ("toolchain.codecharta", root / "toolchain" / "bin" / "lizard-to-codecharta"),
        ("report.spec.findings", root / "arcticbase" / "backend" / "src" / "arctic_base" / "refall_report" / "spec" / "findings-standard.md"),
        ("report.template", root / "arcticbase" / "backend" / "src" / "arctic_base" / "refall_report" / "template.html"),
    ):
        _add(
            checks,
            check_id,
            "ok" if path.exists() else "warn",
            f"{path} {'exists' if path.exists() else 'missing'}",
        )
    if subject:
        root_path = _subject_root() / subject
        probe = root_path if root_path.exists() else root_path.parent
        writable = probe.exists() and os.access(probe, os.W_OK)
        _add(
            checks,
            "subject_runtime_root",
            "ok" if writable else "warn",
            f"{root_path} {'writable' if writable else 'not writable or missing'}",
        )


def _arcticbase_subject_checks(checks: list[dict], subject: str | None, arcticbase) -> None:
    if not subject or arcticbase is None:
        return
    for check_id, call in (
        ("coverage.stats", lambda: arcticbase.coverage_stats(subject)),
        ("coverage.source_inventory", lambda: arcticbase.get_source_inventory(subject)),
        ("pending_actions", lambda: arcticbase.list_pending_actions(subject, include_terminal=False)),
        ("capabilities", lambda: arcticbase.capabilities(subject)),
        ("closeout_gate", lambda: arcticbase.closeout_gate(subject)),
    ):
        try:
            value = call()
        except Exception as exc:
            _add(checks, check_id, "warn", f"{check_id} unavailable: {exc}")
            continue
        _add(checks, check_id, "ok", f"{check_id} available", count=_count(value))


def _secret_checks(checks: list[dict]) -> None:
    api_key_path = Path(os.environ.get("REFALL_OPENHANDS_API_KEY_PATH", config.API_KEY_PATH)).expanduser()
    present = False
    try:
        present = api_key_path.is_file() and bool(api_key_path.read_text(encoding="utf-8").strip())
    except OSError:
        present = False
    _add(
        checks,
        "openhands_api_key",
        "ok" if present else "warn",
        "OpenHands API key file present" if present else "OpenHands API key file missing or empty",
    )
    for name in SECRET_ENV:
        _add(
            checks,
            f"secret.{name.lower()}",
            "ok" if os.environ.get(name) else "warn",
            f"{name} {'present' if os.environ.get(name) else 'not set'}",
        )


def _allowed_providers() -> list[str]:
    raw = os.environ.get("REFALL_ALLOWED_HEAD_PROVIDERS", "codex,claude,grok")
    providers = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return providers or ["codex"]


def _provider_command(provider: str) -> str:
    env_name = PROVIDER_ENV.get(provider, f"REFALL_{provider.upper()}_COMMAND")
    return os.environ.get(env_name, provider)


def _base_url() -> str:
    return config.resolve_public_base(os.environ.get("REFALL_WORKBENCH_BASE") or os.environ.get("REFALL_PUBLIC_BASE_URL"))


def _openhands_base() -> str:
    return os.environ.get("REFALL_OPENHANDS_BASE", config.OH_BASE)


def _subject_root() -> Path:
    return Path(os.environ.get("REFALL_SUBJECT_ROOT", os.environ.get("REFALL_DATA_ROOT", "/var/lib/refall") + "/subjects")).expanduser()


def _http_get(url: str) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, response.read(10000)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(10000)


def _add(checks: list[dict], check_id: str, status: str, summary: str, **fields) -> None:
    checks.append({
        "id": check_id,
        "status": status,
        "summary": summary,
        **fields,
    })


def _count(value) -> int | None:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        if isinstance(value.get("files"), list):
            return len(value["files"])
        if isinstance(value.get("checks"), list):
            return len(value["checks"])
        return len(value)
    return None


def _aggregate_status(checks: list[dict]) -> str:
    statuses = {str(check.get("status") or "") for check in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "ok"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="ref_all_executor.doctor")
    parser.add_argument("--subject")
    parser.add_argument("--no-network", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(doctor(subject=args.subject, check_network=not args.no_network), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
