from __future__ import annotations

import math

from .arcticbase_client import ArcticBaseClient
from .doctor import doctor


def estimate_subject(
    subject: str,
    *,
    arcticbase=None,
    check_network: bool = True,
) -> dict:
    client = arcticbase or ArcticBaseClient()
    coverage = _optional(lambda: client.coverage_stats(subject), {})
    inventory = _optional(lambda: client.get_source_inventory(subject), {})
    pending = _optional(lambda: client.list_pending_actions(subject, include_terminal=False), [])
    funnel = _optional(lambda: client.coverage_funnel(subject), {})
    capabilities = _optional(lambda: client.capabilities(subject), {"grants": [], "requests": []})
    closeout_gate = _optional(lambda: client.closeout_gate(subject), {})
    readiness = doctor(subject=subject, check_network=check_network, arcticbase=client)
    files = inventory.get("files") if isinstance(inventory, dict) and isinstance(inventory.get("files"), list) else []
    lines_total = int(coverage.get("lines_total") or sum(int(item.get("total_lines") or 0) for item in files))
    resolved_pct = float(coverage.get("resolved_pct") or 0)
    symbols_total = int(coverage.get("symbols_total") or 0)
    estimated_open_units = _estimated_open_units(symbols_total, lines_total, resolved_pct)
    open_pending = [item for item in pending if isinstance(item, dict) and item.get("status") in {"open", "claimed"}]
    missing = _missing_prerequisites(readiness, coverage, inventory)
    dynamic_testing = _dynamic_testing_state(capabilities, inventory)
    return {
        "subject": subject,
        "coverage": coverage,
        "source_inventory": {
            "inventory_id": inventory.get("inventory_id") if isinstance(inventory, dict) else None,
            "files_total": len(files),
            "lines_total": lines_total,
            "size_bytes": sum(int(item.get("size_bytes") or 0) for item in files),
        },
        "pending_actions_open": len(open_pending),
        "findings": funnel.get("findings", {}) if isinstance(funnel, dict) else {},
        "closeout": closeout_gate,
        "doctor": readiness,
        "estimated_open_units": estimated_open_units,
        "estimated_agent_tasks": max(estimated_open_units, 1) + len(open_pending),
        "missing_prerequisites": missing,
        "dynamic_testing": dynamic_testing,
    }


def _estimated_open_units(symbols_total: int, lines_total: int, resolved_pct: float) -> int:
    unresolved_ratio = max(0.0, min(1.0, 1.0 - (resolved_pct / 100.0)))
    if symbols_total > 0:
        return max(0, math.ceil(symbols_total * unresolved_ratio))
    if lines_total > 0:
        return max(1, math.ceil((lines_total / 200.0) * unresolved_ratio))
    return 0


def _missing_prerequisites(readiness: dict, coverage: dict, inventory: dict) -> list[str]:
    missing: list[str] = []
    if not coverage or int(coverage.get("lines_total") or 0) <= 0:
        missing.append("coverage.enumerate")
    if not inventory or not inventory.get("files"):
        missing.append("source_inventory")
    provider_ok = any(
        str(check.get("id") or "").startswith("provider.")
        and check.get("status") == "ok"
        for check in readiness.get("checks", [])
    )
    if not provider_ok:
        missing.append("provider_command")
    return missing


def _dynamic_testing_state(capabilities: dict, inventory: dict) -> str:
    if not inventory or not inventory.get("files"):
        return "not_applicable"
    grants = capabilities.get("grants") if isinstance(capabilities, dict) else []
    for grant in grants or []:
        capability = str(grant.get("class") or grant.get("capability_class") or "").lower()
        if capability in {"lan_network_probe", "web_dynamic_testing", "external_network_probe"}:
            return "available"
    return "scope_required"


def _optional(call, default):
    try:
        value = call()
    except Exception:
        return default
    return value if value is not None else default
