from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import config
from .report_assemble import assemble_report
from .report_draft import _optional_req, _req, draft_report
from .workbench import _urllib_transport


HIGH_IMPACT = {"CRITICAL", "HIGH"}
SOFTWARE_FACT_KEYWORDS = {"binary", "elf", "compiler", "rust", "version", "firmware", "build", "archive"}
ARCHITECTURE_FACT_KEYWORDS = {"task", "ipc", "peripheral", "bus", "spi", "i2c", "flash", "memory", "dma"}


def enrich_findings(
    entries: list[dict],
    *,
    runtime_observations: list[dict] | None = None,
    runtime_artifacts: list[dict] | None = None,
    evidence_graph: dict | None = None,
    closeout_gate: dict | None = None,
    pending_actions: list[dict] | None = None,
    capabilities: dict | None = None,
) -> dict:
    canonical_by_key: dict[str, dict] = {}
    findings: list[dict] = []
    leads: list[dict] = []
    facts: list[dict] = []
    for entry in entries:
        kind = entry.get("kind")
        if kind == "fact":
            if entry.get("title"):
                facts.append(dict(entry))
            continue
        if kind == "lead":
            title = str(entry.get("title") or "").strip()
            if title:
                leads.append(dict(entry, title=title))
            continue
        if kind != "finding":
            continue
        if _is_garbage(entry):
            continue
        title = str(entry.get("title") or "").strip()
        if not title:
            continue
        item = dict(entry, title=title)
        item["related_locations"] = _merge_related_locations(
            item.get("related_locations") or [],
            _related_locations_from_entry(item),
        )
        canonical_key = _finding_canonical_key(item)
        if canonical_key in canonical_by_key:
            canonical = canonical_by_key[canonical_key]
            canonical["related_locations"] = _merge_related_locations(
                canonical.get("related_locations") or [],
                item.get("related_locations") or [],
            )
            continue
        canonical_by_key[canonical_key] = item
        findings.append(item)

    resolved_leads = [
        dict(lead, status=_resolve_lead_status(lead, findings))
        for lead in leads
    ]
    grouped_facts = _group_facts_into_sections(facts)
    capability_decisions = [
        dict(entry) for entry in entries
        if entry.get("kind") == "capability-decision"
    ]
    disposition_transitions = [
        dict(entry) for entry in entries
        if entry.get("kind") == "disposition-transition"
    ]
    closeout_overrides = [
        dict(entry) for entry in entries
        if entry.get("kind") == "ops-event" and entry.get("action") == "closeout.override"
    ]
    promotion_gate_refusals = [
        dict(entry) for entry in entries
        if entry.get("kind") == "ops-event" and entry.get("action") == "finding.promotion.refused"
    ]
    runtime = {
        "observations": runtime_observations or [],
        "artifacts": runtime_artifacts or [],
        "visual_artifacts": _visual_artifacts(runtime_artifacts or []),
        "evidence_graph": evidence_graph or {"nodes": [], "edges": []},
        "closeout_gate": closeout_gate or {},
        "pending_actions": pending_actions or [],
        "capabilities": capabilities or {"grants": [], "requests": []},
        "capability_decisions": capability_decisions,
        "disposition_transitions": disposition_transitions,
        "closeout_overrides": closeout_overrides,
        "promotion_gate_refusals": promotion_gate_refusals,
    }
    high = [finding for finding in findings if _severity(finding) in HIGH_IMPACT]
    other = [finding for finding in findings if _severity(finding) not in HIGH_IMPACT]
    chains = []
    if len(findings) > 1:
        chains.append({
            "title": "Potential multi-finding attack chain",
            "findings": [finding["title"] for finding in findings],
        })
    return {
        "findings": findings,
        "leads": resolved_leads,
        "sections": {
            "high-impact": high,
            "other": other,
            "recon": grouped_facts["recon"],
            "architecture": grouped_facts["architecture"],
            "software": grouped_facts["software"],
            "runtime": _runtime_facts(runtime["observations"]),
        },
        "attack_chains": chains,
        "runtime": runtime,
    }


def _is_garbage(entry: dict) -> bool:
    return "fallback parser" in str(entry.get("description") or "").lower()


def _finding_canonical_key(entry: dict) -> str:
    explicit = entry.get("canonical_finding_id") or entry.get("dedup_key")
    if explicit:
        return str(explicit)
    return "|".join([
        str(entry.get("subject") or ""),
        _normalize_title(entry.get("vuln_class") or "unknown"),
        _normalize_title(entry.get("title") or ""),
        _normalize_title(entry.get("affected_component") or entry.get("component") or ""),
    ])


def _related_locations_from_entry(entry: dict) -> list[dict]:
    locations: list[dict] = []
    refs: list[str] = []
    for key in ("code_paths", "source_anchors", "artifact_refs", "refs"):
        refs.extend(str(item) for item in entry.get(key) or [] if str(item).strip())
    for ref in refs:
        anchor = ref.strip()
        locations.append({"path": _source_anchor_path(anchor) or anchor, "anchor": anchor})
    return _merge_related_locations([], locations)


def _merge_related_locations(existing: list[dict], new_locations: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in [*existing, *new_locations]:
        if not isinstance(item, dict):
            continue
        anchor = str(item.get("anchor") or item.get("ref") or "").strip()
        path = str(item.get("path") or "").strip()
        if not anchor and path:
            anchor = path
        if not anchor:
            continue
        row = {"path": path or _source_anchor_path(anchor) or anchor, "anchor": anchor}
        key = (row["path"], row["anchor"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


def _source_anchor_path(anchor: str) -> str:
    text = str(anchor or "").strip()
    if not text or text.startswith(("http://", "https://", "obj_", "artifact:")):
        return ""
    if text.startswith("source:"):
        text = text.split(":", 1)[1]
    if "::" in text:
        text = text.split("::", 1)[0]
    match = re.match(r"^(.*?):\d+(?::\d+)?$", text)
    if match:
        text = match.group(1)
    return text.lstrip("/")


def _severity(entry: dict) -> str:
    return str(entry.get("severity") or "").strip().upper()


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", str(title).lower()).strip()


def _resolve_lead_status(lead: dict, findings: list[dict]) -> str:
    existing = str(lead.get("status") or "").strip().upper()
    if existing in {"DONE", "CLOSED", "REJECTED"}:
        return existing
    lead_words = set(_normalize_title(lead.get("title", "")).split())
    if len(lead_words) <= 2:
        return "OPEN"
    for finding in findings:
        finding_words = set(_normalize_title(finding.get("title", "")).split())
        if lead_words and len(lead_words & finding_words) > len(lead_words) * 0.5:
            return "DONE"
    return "OPEN"


def _group_facts_into_sections(facts: list[dict]) -> dict[str, list[dict]]:
    sections: dict[str, list[dict]] = {"recon": [], "architecture": [], "software": []}
    for fact in facts:
        title = str(fact.get("title") or "").lower()
        if any(keyword in title for keyword in SOFTWARE_FACT_KEYWORDS):
            sections["software"].append(fact)
        elif any(keyword in title for keyword in ARCHITECTURE_FACT_KEYWORDS):
            sections["architecture"].append(fact)
        else:
            sections["recon"].append(fact)
    return sections


def _runtime_facts(observations: list[dict]) -> list[dict]:
    facts: list[dict] = []
    for observation in observations:
        claim = str(observation.get("claim") or "").strip()
        if not claim:
            continue
        facts.append({
            "title": claim,
            "description": observation.get("kind") or "runtime observation",
            "confidence": observation.get("confidence"),
            "evidence_refs": observation.get("evidence_refs") or [],
        })
    return facts


def _visual_artifacts(artifacts: list[dict]) -> list[dict]:
    markers = {"visual", "graph", "codebadger", "codecharta", "flow", "diagram"}
    visuals: list[dict] = []
    for artifact in artifacts:
        text = " ".join(
            str(artifact.get(key) or "").lower()
            for key in ("id", "kind", "path", "mime")
        )
        if any(marker in text for marker in markers) or "image/" in text:
            visuals.append(artifact)
    return visuals


def write_enriched(root: Path, slug: str, enriched: dict) -> dict:
    base = root / slug / "refall" / "enriched"
    outputs = {
        "findings": base / "findings" / "findings.json",
        "leads": base / "leads" / "leads.json",
        "attack_chains": base / "attack-chains" / "attack-chains.json",
        "sections": base / "sections" / "sections.json",
        "runtime": base / "runtime" / "runtime.json",
    }
    payloads = {
        "findings": enriched.get("findings", []),
        "leads": enriched.get("leads", []),
        "attack_chains": enriched.get("attack_chains", []),
        "sections": enriched.get("sections", {}),
        "runtime": enriched.get("runtime", {}),
    }
    result: dict[str, str] = {}
    for key, path in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payloads[key], indent=2, sort_keys=True) + "\n"
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
        result[key] = str(path)
    return result


def enrich_workbench_report(
    workbench: str,
    subject: str,
    *,
    root: Path | str | None = None,
    base: str | None = None,
    transport=None,
    assemble: bool = True,
    allow_structural_downgrade: bool = False,
) -> dict:
    base = (base or config.WB_BASE).rstrip("/")
    transport = transport or _urllib_transport
    entries = _req(transport, "GET", f"{base}/api/workbenches/{workbench}/ledger/entries")
    if not isinstance(entries, list):
        raise RuntimeError("ledger entries response was not JSON list")
    runtime_observations = _optional_req(transport, "GET", f"{base}/api/workbenches/{workbench}/runtime/observations", [])
    runtime_artifacts = _optional_req(transport, "GET", f"{base}/api/workbenches/{workbench}/runtime/artifacts", [])
    evidence_graph = _optional_req(transport, "GET", f"{base}/api/workbenches/{workbench}/runtime/evidence-graph", {"nodes": [], "edges": []})
    closeout_gate = _optional_req(transport, "GET", f"{base}/api/workbenches/{workbench}/closeout/gate", {})
    pending_actions = _optional_req(transport, "GET", f"{base}/api/workbenches/{workbench}/pending-actions", [])
    capabilities = _optional_req(transport, "GET", f"{base}/api/workbenches/{workbench}/capabilities", {"grants": [], "requests": []})
    enriched = enrich_findings(
        entries,
        runtime_observations=runtime_observations if isinstance(runtime_observations, list) else [],
        runtime_artifacts=runtime_artifacts if isinstance(runtime_artifacts, list) else [],
        evidence_graph=evidence_graph if isinstance(evidence_graph, dict) else {"nodes": [], "edges": []},
        closeout_gate=closeout_gate if isinstance(closeout_gate, dict) else {},
        pending_actions=pending_actions if isinstance(pending_actions, list) else [],
        capabilities=capabilities if isinstance(capabilities, dict) else {"grants": [], "requests": []},
    )
    outputs = write_enriched(_default_enriched_root(root), workbench, enriched)
    result = {
        "workbench": workbench,
        "subject": subject,
        "outputs": outputs,
        "enriched": enriched,
    }
    if assemble:
        try:
            result["assembled"] = assemble_report(
                workbench,
                subject,
                enriched,
                base=base,
                transport=transport,
                allow_structural_downgrade=allow_structural_downgrade,
            )
        except RuntimeError as exc:
            if "refall_current_report_object_id" not in str(exc):
                raise
            draft_report(workbench, subject, base=base, transport=transport)
            result["assembled"] = assemble_report(
                workbench,
                subject,
                enriched,
                base=base,
                transport=transport,
                allow_structural_downgrade=allow_structural_downgrade,
            )
    return result


def _default_enriched_root(root: Path | str | None) -> Path:
    if root is not None:
        return Path(root)
    if os.environ.get("REFALL_ENRICHED_ROOT"):
        return Path(os.environ["REFALL_ENRICHED_ROOT"])
    if os.environ.get("REFALL_ARCTICBASE_DATA"):
        return Path(os.environ["REFALL_ARCTICBASE_DATA"]) / "workbenches"
    return Path("arcticbase/backend/data/workbenches")
