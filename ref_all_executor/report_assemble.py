from __future__ import annotations

import html
import json

from . import config
from .report_draft import (
    _optional_req,
    _record_structural_downgrade,
    _req,
    _structural_downgrade_sections,
)
from .workbench import _urllib_transport


def assemble_report(
    workbench: str,
    subject: str,
    enriched: dict,
    *,
    base: str | None = None,
    transport=None,
    allow_structural_downgrade: bool = False,
) -> dict:
    base = (base or config.WB_BASE).rstrip("/")
    transport = transport or _urllib_transport
    template = _req(transport, "GET", f"{base}/api/refall/reports/template")
    if isinstance(template, bytes):
        template_text = template.decode("utf-8", errors="replace")
    else:
        template_text = str(template)
    content = render_enriched_report(subject, template_text, enriched)
    meta = _req(transport, "GET", f"{base}/api/workbenches/{workbench}")
    if not isinstance(meta, dict):
        raise RuntimeError("workbench metadata response was not JSON")
    current_id = (meta.get("custom_fields") or {}).get("refall_current_report_object_id")
    if not current_id:
        raise RuntimeError("refall_current_report_object_id is not set")
    wb_url = f"{base}/api/workbenches/{workbench}"
    current = _optional_req(transport, "GET", f"{wb_url}/refall-report", {})
    existing_content = (
        str(current.get("content") or "") if isinstance(current, dict) else ""
    )
    lost_sections = (
        _structural_downgrade_sections(existing_content, content)
        if existing_content and not allow_structural_downgrade
        else []
    )
    if lost_sections:
        diagnostic_id = _record_structural_downgrade(
            transport,
            wb_url,
            subject=subject,
            candidate=content,
            lost_sections=lost_sections,
            source="report_enrich_assemble",
        )
        return {
            "workbench": workbench,
            "object_id": current_id,
            "mode": "downgrade_refused",
            "lost_sections": lost_sections,
            "candidate_object_id": diagnostic_id,
        }
    _req(
        transport,
        "PUT",
        f"{wb_url}/objects/{current_id}/content",
        content.encode("utf-8"),
    )
    return {"workbench": workbench, "object_id": current_id, "mode": "updated"}


def render_enriched_report(subject: str, template: str, enriched: dict) -> str:
    rows = "".join(_row(finding) for finding in enriched.get("findings", []))
    leads = "".join(_lead(lead) for lead in enriched.get("leads", []))
    sections = enriched.get("sections", {})
    fact_sections = "".join([
        _fact_section("Recon", sections.get("recon", [])),
        _fact_section("Architecture", sections.get("architecture", [])),
        _fact_section("Software", sections.get("software", [])),
        _fact_section("Runtime", sections.get("runtime", [])),
    ])
    runtime = _runtime_section(enriched.get("runtime") or {})
    chains = "".join(
        f"<li>{html.escape(chain.get('title', 'Attack chain'))}: "
        f"{html.escape(', '.join(chain.get('findings', [])))}</li>"
        for chain in enriched.get("attack_chains", [])
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>{html.escape(subject)} REFALL Report</title></head>
<body>
{template}
<section>
  <h2>Enriched Findings</h2>
  <table><tbody>{rows}</tbody></table>
</section>
<section>
  <h2>Resolved Leads</h2>
  <table><tbody>{leads}</tbody></table>
</section>
<section>
  <h2>Evidence Sections</h2>
  {fact_sections or '<p>No facts grouped yet.</p>'}
</section>
{runtime}
<section>
  <h2>Attack Chains</h2>
  <ul>{chains or '<li>None synthesized.</li>'}</ul>
</section>
</body>
</html>
"""


def _row(finding: dict) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(str(finding.get('severity') or ''))}</td>"
        f"<td>{html.escape(str(finding.get('title') or ''))}</td>"
        f"<td>{html.escape(str(finding.get('impact') or finding.get('summary') or ''))}</td>"
        "</tr>"
    )


def _lead(lead: dict) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(str(lead.get('severity') or lead.get('priority') or ''))}</td>"
        f"<td>{html.escape(str(lead.get('title') or ''))}</td>"
        f"<td>{html.escape(str(lead.get('status') or 'OPEN'))}</td>"
        "</tr>"
    )


def _fact_section(title: str, facts: list[dict]) -> str:
    if not facts:
        return ""
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(fact.get('title') or ''))}</td>"
        f"<td>{html.escape(str(fact.get('description') or fact.get('summary') or ''))}</td>"
        "</tr>"
        for fact in facts
    )
    return f"<h3>{html.escape(title)}</h3><table><tbody>{rows}</tbody></table>"


def _runtime_section(runtime: dict) -> str:
    if not runtime:
        return ""
    observations = runtime.get("observations") if isinstance(runtime.get("observations"), list) else []
    artifacts = runtime.get("artifacts") if isinstance(runtime.get("artifacts"), list) else []
    visuals = runtime.get("visual_artifacts") if isinstance(runtime.get("visual_artifacts"), list) else []
    graph = runtime.get("evidence_graph") if isinstance(runtime.get("evidence_graph"), dict) else {}
    gate = runtime.get("closeout_gate") if isinstance(runtime.get("closeout_gate"), dict) else {}
    pending_actions = runtime.get("pending_actions") if isinstance(runtime.get("pending_actions"), list) else []
    capabilities = runtime.get("capabilities") if isinstance(runtime.get("capabilities"), dict) else {}
    capability_decisions = (
        runtime.get("capability_decisions")
        if isinstance(runtime.get("capability_decisions"), list)
        else []
    )
    disposition_transitions = (
        runtime.get("disposition_transitions")
        if isinstance(runtime.get("disposition_transitions"), list)
        else []
    )
    closeout_overrides = (
        runtime.get("closeout_overrides")
        if isinstance(runtime.get("closeout_overrides"), list)
        else []
    )
    nodes = len(graph.get("nodes") or [])
    edges = len(graph.get("edges") or [])
    observation_rows = "".join(_runtime_observation_row(item) for item in observations) or (
        "<tr><td colspan=\"3\">No runtime observations projected.</td></tr>"
    )
    artifact_rows = "".join(_runtime_artifact_row(item) for item in artifacts) or (
        "<tr><td colspan=\"3\">No runtime artifacts recorded.</td></tr>"
    )
    visual_rows = "".join(_runtime_artifact_row(item) for item in visuals) or (
        "<tr><td colspan=\"3\">No visual artifacts selected.</td></tr>"
    )
    gate_rows = "".join(_gate_check_row(item) for item in gate.get("checks", [])) or (
        "<tr><td colspan=\"3\">No closeout checks returned.</td></tr>"
    )
    pending_rows = "".join(_pending_action_row(item) for item in pending_actions) or (
        "<tr><td colspan=\"4\">No pending actions recorded.</td></tr>"
    )
    capability_rows = _capability_rows(capabilities, capability_decisions) or (
        "<tr><td colspan=\"5\">No capability grants, requests, or decisions recorded.</td></tr>"
    )
    disposition_rows = "".join(_disposition_transition_row(item) for item in disposition_transitions) or (
        "<tr><td colspan=\"4\">No disposition transitions recorded.</td></tr>"
    )
    override_rows = "".join(_closeout_override_row(item) for item in closeout_overrides) or (
        "<tr><td colspan=\"4\">No closeout overrides recorded.</td></tr>"
    )
    gate_state = "passed" if gate.get("passed") else "blocked"
    return f"""
<section>
  <h2>Runtime Evidence</h2>
  <p>Evidence graph: {nodes} nodes / {edges} edges.</p>
  <table><tbody>{observation_rows}</tbody></table>
</section>
<section>
  <h2>Visual Evidence</h2>
  <table><tbody>{visual_rows}</tbody></table>
</section>
<section>
  <h2>Runtime Artifacts</h2>
  <table><tbody>{artifact_rows}</tbody></table>
</section>
<section>
  <h2>Pending Actions</h2>
  <table><tbody>{pending_rows}</tbody></table>
</section>
<section>
  <h2>Capability Decisions</h2>
  <table><tbody>{capability_rows}</tbody></table>
</section>
<section>
  <h2>Disposition Transitions</h2>
  <table><tbody>{disposition_rows}</tbody></table>
</section>
<section>
  <h2>Closeout Overrides</h2>
  <table><tbody>{override_rows}</tbody></table>
</section>
<section>
  <h2>Closeout Gate</h2>
  <p>State: {html.escape(gate_state)}</p>
  <table><tbody>{gate_rows}</tbody></table>
</section>
"""


def _runtime_observation_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(str(item.get('kind') or ''))}</td>"
        f"<td>{html.escape(str(item.get('claim') or ''))}</td>"
        f"<td>{html.escape(str(item.get('confidence') or ''))}</td>"
        "</tr>"
    )


def _pending_action_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(str(item.get('status') or ''))}</td>"
        f"<td>{html.escape(str(item.get('kind') or ''))}</td>"
        f"<td>{html.escape(str(item.get('title') or ''))}</td>"
        f"<td>{html.escape(str(item.get('required_receipt_type') or ''))}</td>"
        "</tr>"
    )


def _capability_rows(capabilities: dict, decisions: list[dict]) -> str:
    grants = capabilities.get("grants") if isinstance(capabilities.get("grants"), list) else []
    requests = capabilities.get("requests") if isinstance(capabilities.get("requests"), list) else []
    rows = "".join(_capability_row(grant, "grant") for grant in grants)
    rows += "".join(_capability_row(request, "request") for request in requests)
    rows += "".join(_capability_decision_row(decision) for decision in decisions)
    return rows


def _capability_row(item: dict, row_type: str) -> str:
    actor = item.get("granted_by") if row_type == "grant" else item.get("requested_by")
    return (
        "<tr>"
        f"<td>{html.escape(row_type)}</td>"
        f"<td>{html.escape(str(item.get('status') or ('granted' if row_type == 'grant' else 'open')))}</td>"
        f"<td><code>{html.escape(str(item.get('class') or ''))}</code></td>"
        f"<td>{html.escape(str(actor or ''))}</td>"
        f"<td>{html.escape(str(item.get('reason') or ''))}</td>"
        "</tr>"
    )


def _capability_decision_row(item: dict) -> str:
    return (
        "<tr>"
        "<td>decision</td>"
        f"<td>{html.escape(str(item.get('status') or ''))}</td>"
        f"<td><code>{html.escape(str(item.get('capability_class') or ''))}</code></td>"
        f"<td>{html.escape(str(item.get('grant_id') or ''))}</td>"
        f"<td>{html.escape(str(item.get('summary') or ''))}</td>"
        "</tr>"
    )


def _disposition_transition_row(item: dict) -> str:
    details = "; ".join(str(reason) for reason in item.get("refusal_reasons", []))
    if not details:
        details = str(item.get("summary") or "")
    return (
        "<tr>"
        f"<td>{html.escape(str(item.get('status') or ''))}</td>"
        f"<td><code>{html.escape(str(item.get('finding_id') or ''))}</code></td>"
        f"<td><code>{html.escape(str(item.get('receipt_type') or ''))}</code></td>"
        f"<td>{html.escape(details)}</td>"
        "</tr>"
    )


def _closeout_override_row(item: dict) -> str:
    checks = ", ".join(str(check_id) for check_id in item.get("check_ids", []))
    return (
        "<tr>"
        f"<td>{html.escape(str(item.get('status') or ''))}</td>"
        f"<td><code>{html.escape(checks)}</code></td>"
        f"<td>{html.escape(str(item.get('created_by') or ''))}</td>"
        f"<td>{html.escape(str(item.get('summary') or ''))}</td>"
        "</tr>"
    )


def _runtime_artifact_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(str(item.get('kind') or ''))}</td>"
        f"<td><code>{html.escape(str(item.get('path') or ''))}</code></td>"
        f"<td>{html.escape(str(item.get('mime') or ''))}</td>"
        "</tr>"
    )


def _gate_check_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(str(item.get('id') or ''))}</td>"
        f"<td>{html.escape(str(item.get('status') or ''))}</td>"
        f"<td>{html.escape(str(item.get('blocking') or False))}</td>"
        "</tr>"
    )
