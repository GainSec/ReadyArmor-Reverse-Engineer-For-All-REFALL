from __future__ import annotations

import re
from urllib.parse import urlparse


VALIDATED_STATUSES = {"VALID"}
VALIDATED_QUALITIES = {"CODE_CONFIRMED", "LIVE_CONFIRMED"}
VALIDATED_REPRO = {"reproduced", "confirmed", "live_reproduced"}


def evaluate_finding_candidate(
    candidate: dict,
    *,
    source_inventory: dict | None = None,
    scope_overlay: dict | None = None,
) -> dict:
    reasons: list[str] = []
    warnings: list[str] = []
    refs = _source_refs(candidate)
    artifacts = _artifact_refs(candidate)
    evidence = _evidence_items(candidate)

    if not evidence and not refs and not artifacts:
        reasons.append("missing evidence, source anchors, or artifact refs")
    elif not evidence:
        reasons.append("missing evidence")
    if not str(candidate.get("confidence") or "").strip():
        reasons.append("missing confidence")
    if not refs and not artifacts:
        reasons.append("missing source anchors or artifact refs")

    inventory_paths = _inventory_paths(source_inventory)
    if inventory_paths is None and refs:
        warnings.append("source inventory unavailable; source anchor membership was not checked")
    elif inventory_paths is not None:
        for ref in refs:
            path = _source_path(ref)
            if path and path not in inventory_paths:
                reasons.append(f"source anchor not in source inventory: {path}")

    for host in _external_hosts([*_location_refs(candidate), *artifacts, *_freeform_refs(candidate)]):
        if not _external_host_allowed(host, scope_overlay):
            reasons.append(f"external target outside explicit scope: {host}")

    if _claims_validation(candidate) and not _has_verification_material(candidate):
        reasons.append("validated status requires verification material")

    return {"accepted": not reasons, "reasons": reasons, "warnings": warnings}


def _source_refs(candidate: dict) -> list[str]:
    refs: list[str] = _location_refs(candidate)
    for item in candidate.get("evidence") or []:
        if isinstance(item, dict):
            ref = item.get("ref") or item.get("file")
            if ref:
                refs.append(str(ref))
        elif isinstance(item, str):
            refs.append(item)
    return sorted({ref.strip() for ref in refs if _source_path(ref)})


def _location_refs(candidate: dict) -> list[str]:
    refs: list[str] = []
    for key in ("code_paths", "source_anchors", "refs"):
        refs.extend(_string_list(candidate.get(key)))
    return refs


def _artifact_refs(candidate: dict) -> list[str]:
    refs = _string_list(candidate.get("artifact_refs"))
    for item in candidate.get("evidence") or []:
        if isinstance(item, dict) and item.get("artifact_ref"):
            refs.append(str(item["artifact_ref"]))
    return sorted({ref.strip() for ref in refs if ref.strip()})


def _evidence_items(candidate: dict) -> list[object]:
    evidence = list(candidate.get("evidence") or [])
    evidence.extend(_string_list(candidate.get("source_anchors")))
    evidence.extend(_string_list(candidate.get("artifact_refs")))
    return [item for item in evidence if item]


def _freeform_refs(candidate: dict) -> list[str]:
    refs: list[str] = []
    for key in ("description", "impact", "reasoning"):
        value = candidate.get(key)
        if isinstance(value, str):
            refs.extend(re.findall(r"https?://[^\s)>\"]+", value))
    for key in ("repro_hints", "reproduction_steps"):
        for item in candidate.get(key) or []:
            if isinstance(item, str):
                refs.extend(re.findall(r"https?://[^\s)>\"]+", item))
    return refs


def _inventory_paths(source_inventory: dict | None) -> set[str] | None:
    if not isinstance(source_inventory, dict):
        return None
    files = source_inventory.get("files")
    if not isinstance(files, list):
        return None
    paths = {
        str(item.get("path") or "").strip().lstrip("/")
        for item in files
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    }
    return paths


def _source_path(ref: object) -> str:
    text = str(ref or "").strip()
    if not text or _url_host(text):
        return ""
    if text.startswith("source:"):
        text = text.split(":", 1)[1]
    if "::" in text:
        text = text.split("::", 1)[0]
    match = re.match(r"^(.*?):\d+(?:(?:-\d+)|(?::\d+))?$", text)
    if match:
        text = match.group(1)
    text = text.lstrip("/")
    if not text or text.startswith("../") or "/../" in f"/{text}":
        return ""
    if text.startswith(("obj_", "artifact:", "http:", "https:")):
        return ""
    return text


def _external_hosts(refs: list[str]) -> set[str]:
    hosts: set[str] = set()
    for ref in refs:
        host = _url_host(ref)
        if host:
            hosts.add(host.lower())
    return hosts


def _url_host(ref: object) -> str:
    parsed = urlparse(str(ref or ""))
    return parsed.hostname or ""


def _external_host_allowed(host: str, scope_overlay: dict | None) -> bool:
    if not isinstance(scope_overlay, dict):
        return False
    allowed = set()
    for item in scope_overlay.get("external_targets") or []:
        if isinstance(item, dict):
            value = item.get("host") or item.get("domain") or item.get("url")
        else:
            value = item
        parsed_host = _url_host(value)
        allowed.add((parsed_host or str(value or "")).strip().lower())
    return host.lower() in allowed


def _claims_validation(candidate: dict) -> bool:
    status = str(candidate.get("status") or "").upper()
    quality = str(candidate.get("quality_tier") or "").upper()
    repro = str(candidate.get("repro_status") or "").lower()
    return status in VALIDATED_STATUSES or quality in VALIDATED_QUALITIES or repro in VALIDATED_REPRO


def _has_verification_material(candidate: dict) -> bool:
    if _artifact_refs(candidate):
        return True
    if _string_list(candidate.get("source_anchors")) and _evidence_items(candidate):
        return True
    for key in ("commands", "negative_tests", "reproduction_steps"):
        value = candidate.get(key)
        if isinstance(value, list) and value:
            return True
    return False


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
