from __future__ import annotations

import argparse
import html
import json
import re
from datetime import UTC, datetime

from . import config
from .workbench import _urllib_transport


def _req(transport, method: str, url: str, body: dict | bytes | None = None) -> dict | bytes:
    headers = {"Content-Type": "application/json"}
    if isinstance(body, bytes):
        data = body
        headers = {"Content-Type": "text/html"}
    elif body is None:
        data = None
    else:
        data = json.dumps(body).encode("utf-8")
    status, raw = transport(method, url, headers, data)
    if status >= 400:
        raise RuntimeError(f"{method} {url} -> {status}: {raw[:300]!r}")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _optional_req(transport, method: str, url: str, default):
    try:
        value = _req(transport, method, url)
    except Exception:
        return default
    return value


def draft_report(
    workbench: str,
    subject: str,
    *,
    base: str | None = None,
    transport=None,
    allow_structural_downgrade: bool = False,
) -> dict:
    base = (base or config.WB_BASE).rstrip("/")
    transport = transport or _urllib_transport
    wb_url = f"{base}/api/workbenches/{workbench}"
    meta = _req(transport, "GET", wb_url)
    coverage = _req(transport, "GET", f"{wb_url}/coverage/stats")
    ledger_entries = _req(transport, "GET", f"{wb_url}/ledger/entries")
    ledger_stats = _req(transport, "GET", f"{wb_url}/ledger/stats")
    closeout_gate = _optional_req(transport, "GET", f"{wb_url}/closeout/gate", {})
    runtime_observations = _optional_req(transport, "GET", f"{wb_url}/runtime/observations", [])
    runtime_artifacts = _optional_req(transport, "GET", f"{wb_url}/runtime/artifacts", [])
    evidence_graph = _optional_req(transport, "GET", f"{wb_url}/runtime/evidence-graph", {"nodes": [], "edges": []})
    run_manifest = _optional_req(transport, "GET", f"{wb_url}/runtime/manifest", {})
    nonfatal_errors = _optional_req(transport, "GET", f"{wb_url}/runtime/nonfatal-errors", {"errors": []})
    capabilities = _optional_req(transport, "GET", f"{wb_url}/capabilities", {"grants": [], "requests": []})
    if not isinstance(meta, dict):
        raise RuntimeError("workbench metadata response was not JSON")
    custom_fields = dict(meta.get("custom_fields") or {})
    mapping_mode = str(custom_fields.get("refall_no_findings") or "").strip().lower() in {"1", "true", "yes"}
    pending_url = f"{wb_url}/pending-actions"
    if mapping_mode:
        pending_url += "?include_terminal=true"
    pending_actions = _optional_req(transport, "GET", pending_url, [])
    content = build_html_report(
        workbench=workbench,
        subject=subject,
        coverage=coverage if isinstance(coverage, dict) else {},
        ledger_entries=ledger_entries if isinstance(ledger_entries, list) else [],
        ledger_stats=ledger_stats if isinstance(ledger_stats, dict) else {},
        closeout_gate=closeout_gate if isinstance(closeout_gate, dict) else {},
        runtime_observations=runtime_observations if isinstance(runtime_observations, list) else [],
        runtime_artifacts=runtime_artifacts if isinstance(runtime_artifacts, list) else [],
        evidence_graph=evidence_graph if isinstance(evidence_graph, dict) else {"nodes": [], "edges": []},
        run_manifest=run_manifest if isinstance(run_manifest, dict) else {},
        nonfatal_errors=(
            nonfatal_errors.get("errors")
            if isinstance(nonfatal_errors, dict) and isinstance(nonfatal_errors.get("errors"), list)
            else []
        ),
        pending_actions=pending_actions if isinstance(pending_actions, list) else [],
        capabilities=capabilities if isinstance(capabilities, dict) else {"grants": [], "requests": []},
        mapping_mode=mapping_mode,
    )
    current_id = (meta.get("custom_fields") or {}).get("refall_current_report_object_id")
    if current_id:
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
                source="report_draft",
            )
            return {
                "workbench": workbench,
                "object_id": current_id,
                "mode": "downgrade_refused",
                "lost_sections": lost_sections,
                "candidate_object_id": diagnostic_id,
            }
        _req(transport, "PUT", f"{wb_url}/objects/{current_id}/content", content.encode("utf-8"))
        return {"workbench": workbench, "object_id": current_id, "mode": "updated"}

    created = _req(
        transport,
        "POST",
        f"{wb_url}/objects",
        {
            "kind": "html",
            "title": f"{subject} REFALL Draft Report",
            "drawer": "Report",
            "filename": "refall-draft-report.html",
            "mime": "text/html",
            "description": "Current REFALL draft report generated from workbench coverage and ledger state.",
            "content": content,
        },
    )
    if not isinstance(created, dict) or not created.get("id"):
        raise RuntimeError(f"report object creation returned unexpected payload: {created!r}")
    object_id = str(created["id"])
    custom_fields["refall_current_report_object_id"] = object_id
    _req(transport, "PATCH", wb_url, {"custom_fields": custom_fields})
    return {"workbench": workbench, "object_id": object_id, "mode": "created"}


_SEVS = ["critical", "high", "medium", "low", "info"]


def _sev(item: dict, default: str = "") -> str:
    value = str(item.get("severity") or default).strip().lower()
    return value if value in _SEVS else (default or "unrated")


def _finding_sort_key(finding: dict) -> tuple:
    sev = _sev(finding)
    rank = _SEVS.index(sev) if sev in _SEVS else len(_SEVS)
    return (rank, str(finding.get("title") or ""))


def _finding_refs(finding: dict) -> list[str]:
    refs = finding.get("refs") or finding.get("code_paths") or finding.get("source_anchors") or []
    return [str(r) for r in refs if str(r).strip()]


def _panel(inner: str, anchor: str) -> str:
    """Wrap a legacy section (which starts with its own <h2>) in an anchored card."""
    if not inner or not inner.strip():
        return ""
    return f'<section class="panel" id="{anchor}">{inner}</section>'


def _exec_summary_section(findings: list[dict]) -> str:
    if not findings:
        return (
            '<section class="panel" id="exec-summary"><h2>Executive Summary</h2>'
            '<p class="empty">No findings have been compiled into the ledger yet. '
            "Findings, facts, leads, and flows appear here as loop agents emit them.</p></section>"
        )
    rows = ""
    for i, finding in enumerate(findings, 1):
        sev = _sev(finding)
        refs = _finding_refs(finding)
        affected = ", ".join(f"<code>{html.escape(r)}</code>" for r in refs[:3]) or '<span class="muted">—</span>'
        rows += (
            f"<tr><td>{i}</td>"
            f'<td><a href="#finding-{i}">{html.escape(str(finding.get("title") or finding.get("name") or "(untitled)"))}</a></td>'
            f'<td><span class="badge {html.escape(sev)}">{html.escape(sev.title())}</span></td>'
            f'<td>{html.escape(str(finding.get("impact") or finding.get("summary") or "—"))}</td>'
            f"<td>{affected}</td>"
            f'<td>{html.escape(str(finding.get("status") or "PROVISIONALLY_VALID"))}</td></tr>'
        )
    return (
        '<section class="panel" id="exec-summary"><h2>Executive Summary</h2>'
        "<table><thead><tr><th>#</th><th>Finding</th><th>Severity</th>"
        "<th>Primary Impact</th><th>Affected Artifact(s)</th><th>State</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></section>"
    )


def _fstr(f: dict, *keys: str) -> str:
    for k in keys:
        v = f.get(k)
        if isinstance(v, str) and v.strip():
            return v
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
    return ""


def _flist(f: dict, *keys: str) -> list[str]:
    out: list[str] = []
    for k in keys:
        v = f.get(k)
        if isinstance(v, list):
            out += [str(x) for x in v if str(x).strip()]
        elif isinstance(v, str) and v.strip():
            out.append(v)
    return out


def _finding_articles_section(findings: list[dict]) -> str:
    """Full per-finding disclosure package: everything a Hyundai + CVE/CNA
    submission needs -- CWE, CVSS, affected product/version, impact, likelihood,
    affected code paths, reproduction, PoC status, remediation, evidence."""
    if not findings:
        return ""
    articles = []
    for i, finding in enumerate(findings, 1):
        sev = _sev(finding)
        title = _fstr(finding, "title", "name") or "(untitled finding)"
        desc = _fstr(finding, "description", "summary", "impact")
        cwe = _fstr(finding, "cwe", "vuln_class")
        cvss_score = _fstr(finding, "cvss_score", "cvss")
        cvss_vec = _fstr(finding, "cvss_vector", "vector")

        kvs: list[str] = []

        def kv(label: str, val: str, mono: bool = False) -> None:
            if not val:
                return
            inner = f"<code>{html.escape(val)}</code>" if mono else html.escape(val)
            kvs.append(f'<div class="kv"><strong>{label}</strong>{inner}</div>')

        kv("CWE", cwe)
        if cvss_score or cvss_vec:
            parts = []
            if cvss_score:
                parts.append(html.escape(cvss_score))
            if cvss_vec:
                parts.append(f"<code>{html.escape(cvss_vec)}</code>")
            kvs.append(f'<div class="kv"><strong>CVSS v3.1</strong>{" · ".join(parts)}</div>')
        kv("Impact", _fstr(finding, "impact"))
        kv("Likelihood", _fstr(finding, "likelihood"))
        kv("Confidence", _fstr(finding, "confidence"))
        kv("Affected component", _fstr(finding, "affected_component", "component"))
        kv("Affected product", _fstr(finding, "affected_product"))
        av = _flist(finding, "affected_versions")
        kv("Affected version(s)", ", ".join(av) if av else _fstr(finding, "affected_versions"))
        kv("PoC status", _fstr(finding, "poc_status"))
        kv("Verification", _fstr(finding, "verification_status"))
        status = _fstr(finding, "status") or "PROVISIONALLY_VALID"
        quality = _fstr(finding, "quality_tier")
        kvs.append(
            f'<div class="kv"><strong>State</strong>{html.escape(status)}'
            + (f" · {html.escape(quality)}" if quality else "") + "</div>"
        )

        def block(label: str, items: list[str], ordered: bool = False) -> str:
            if not items:
                return ""
            tag = "ol" if ordered else "ul"
            lis = "".join(f"<li><code>{html.escape(x)}</code></li>" if not ordered
                          else f"<li>{html.escape(x)}</li>" for x in items)
            return f"<h4>{label}</h4><{tag} class=\"f-list\">{lis}</{tag}>"

        refs = _finding_refs(finding)
        affected_html = block("Affected code paths", refs)
        repro = _flist(finding, "reproduction", "reproduction_steps", "repro_steps", "repro")
        repro_html = block("Reproduction", repro, ordered=True)
        # Proof of Concept = a payload/exploit that PROVES exploitability -- distinct
        # from Reproduction (static confirmation of the condition). Only render an
        # explicit poc field; never repurpose static confirmation scripts as a PoC.
        poc_text = _fstr(finding, "poc", "poc_payload", "proof_of_concept", "exploit")
        poc_status = _fstr(finding, "poc_status")
        poc_refs = _flist(finding, "poc_refs")
        poc_inner = ""
        if poc_status:
            poc_inner += f'<p class="poc-status">Status: {html.escape(poc_status)}</p>'
        if poc_text:
            poc_inner += f"<pre>{html.escape(poc_text)}</pre>"
        if poc_refs:
            poc_inner += ('<ul class="f-list">'
                          + "".join(f"<li><code>{html.escape(r)}</code></li>" for r in poc_refs)
                          + "</ul>")
        if not poc_inner:
            poc_inner = ('<p class="empty">No exploit PoC produced (static-only scope). '
                         'See Reproduction for static confirmation; a live PoC requires an '
                         'operator-granted dynamic phase.</p>')
        poc_html = f"<h4>Proof of Concept</h4>{poc_inner}"
        data_touched = _flist(finding, "data_touched")
        dt_html = (f"<h4>Data touched</h4><p>{html.escape(', '.join(data_touched))}</p>"
                   if data_touched else "")
        remediation = _fstr(finding, "remediation", "remediation_summary", "fix")
        remediation_html = f"<h4>Remediation</h4><p>{html.escape(remediation)}</p>" if remediation else ""
        arts_html = block("Evidence artifacts", _flist(finding, "artifact_refs"))
        related = _related_locations_html(finding.get("related_locations") or [])

        badge_label = (f"CVSS {cvss_score} · {sev.title()}" if cvss_score else sev.title())
        desc_html = html.escape(desc) if desc else '<span class="empty">No description provided.</span>'
        articles.append(
            f'<article class="finding {html.escape(sev)}" id="finding-{i}">'
            f'<div class="finding-header"><span class="badge {html.escape(sev)}">{html.escape(badge_label)}</span>'
            f"<h3>Finding {i}: {html.escape(title)}</h3></div>"
            f'<div class="finding-body">'
            f'<div class="grid">{"".join(kvs)}</div>'
            f"<h4>Summary</h4><p>{desc_html}</p>"
            f"{affected_html}{repro_html}{poc_html}{remediation_html}{dt_html}{arts_html}{related}"
            f"</div></article>"
        )
    return f'<section id="findings-provisional"><h2>Findings <small>({len(findings)})</small></h2>{"".join(articles)}</section>'


def _architecture_section(entries: list[dict]) -> str:
    arch = [e for e in entries if e.get("kind") == "fact" and str(e.get("title") or "").startswith("arch:")]
    seen, uniq = set(), []
    for a in arch:
        t = str(a.get("title") or "")
        if t and t not in seen:
            seen.add(t); uniq.append(a)
    if not uniq:
        return ""
    rows = "".join(
        f'<tr><td><code>{html.escape(str(a.get("title"))[5:])}</code></td>'
        f'<td>{html.escape(str(a.get("description") or a.get("summary") or ""))}</td></tr>'
        for a in uniq
    )
    return (
        f'<section class="panel" id="architecture"><h2>Architecture &amp; Attack Surface <small>({len(uniq)})</small></h2>'
        "<table><thead><tr><th>Aspect</th><th>Value</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></section>"
    )


def _flows_section(entries: list[dict]) -> str:
    flows = [e for e in entries if e.get("kind") == "fact" and e.get("fact_kind") == "flow"]
    seen, uniq = set(), []
    for e in flows:
        t = str(e.get("title") or "")
        if t and t not in seen:
            seen.add(t); uniq.append(e)
    if not uniq:
        return ""
    rows = ""
    for e in uniq:
        flow = e.get("flow") or {}
        rows += (
            f'<tr><td><code>{html.escape(str(flow.get("from") or ""))}</code></td>'
            f'<td class="rel">{html.escape(str(flow.get("relation") or ""))}</td>'
            f'<td><code>{html.escape(str(flow.get("to") or ""))}</code></td>'
            f'<td>{html.escape(str(flow.get("evidence") or ""))}</td></tr>'
        )
    return (
        f'<section class="panel" id="flows"><h2>Data &amp; Control Flows <small>({len(uniq)})</small></h2>'
        "<table><thead><tr><th>From</th><th>Rel</th><th>To</th><th>Evidence</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></section>"
    )


def _leads_section(entries: list[dict]) -> str:
    leads = [e for e in entries if e.get("kind") == "lead"]
    seen, uniq = set(), []
    for e in leads:
        t = str(e.get("title") or "")
        if t and t not in seen:
            seen.add(t); uniq.append(e)
    if not uniq:
        return ""
    items = ""
    for lead in uniq:
        sev = _sev(lead, "medium")
        plan = str(lead.get("investigation_plan") or "")
        items += (
            f'<div class="lead"><div class="fhead"><span class="badge {html.escape(sev)}">{html.escape(sev.title())}</span>'
            f'<b>{html.escape(str(lead.get("title") or ""))}</b></div>'
            f'<p>{html.escape(str(lead.get("description") or ""))}</p>'
            + (f'<p class="plan">→ {html.escape(plan)}</p>' if plan else "")
            + "</div>"
        )
    return f'<section class="panel" id="leads"><h2>Open Leads <small>({len(uniq)})</small></h2>{items}</section>'


def _facts_section(entries: list[dict]) -> str:
    facts = [
        e for e in entries
        if e.get("kind") == "fact"
        and e.get("fact_kind") != "flow"
        and not str(e.get("title") or "").startswith("arch:")
    ]
    seen, uniq = set(), []
    for e in facts:
        t = str(e.get("title") or "")
        if t and t not in seen:
            seen.add(t); uniq.append(e)
    if not uniq:
        return ""
    rows = "".join(
        f'<tr><td><b>{html.escape(str(f.get("title") or ""))}</b></td>'
        f'<td>{html.escape(str(f.get("description") or f.get("summary") or ""))}</td></tr>'
        for f in uniq[:150]
    )
    return (
        f'<section class="panel" id="facts"><h2>Key Facts <small>({len(uniq)})</small></h2>'
        f"<table><tbody>{rows}</tbody></table></section>"
    )


_REQUIRED_REPORT_SECTIONS = [
    ("scope", "Tested Scope & Exclusions"),
    ("methodology", "Methodology"),
    ("coverage", "Coverage Summary"),
    ("evidence-ledger", "Evidence Ledger Summary"),
    ("findings-validated", "Validated Findings"),
    ("findings-provisional", "Provisional Findings"),
    ("false-positives", "False Positives & Duplicates"),
    ("attack-chains", "Attack Chains"),
    ("architecture", "Architecture & Attack Surface"),
    ("flows", "Data & Control Flows"),
    ("repro", "Reproduction & PoC Notes"),
    ("remediation", "Remediation Guidance"),
    ("pending-actions", "Pending, Deferred & Resolved Actions"),
    ("runtime-evidence", "Runtime Evidence"),
    ("runtime-warnings", "Runtime Warnings"),
    ("capability-decisions", "Capability Decisions"),
    ("freshness", "Source / Config Freshness Receipts"),
    ("visual-evidence", "Visual Evidence"),
    ("provenance", "Workbench Object Provenance"),
    ("closeout-gate", "Closeout Gate State"),
]

_REPORT_PLACEHOLDER_PHRASES = (
    "none recorded",
    "none synthesized",
    "no findings have been compiled",
    "no facts grouped yet",
)


def _populated_report_sections(content: str) -> set[str]:
    """Return required section ids containing more than a heading/placeholder."""
    populated: set[str] = set()
    for anchor, _label in _REQUIRED_REPORT_SECTIONS:
        match = re.search(
            rf'<(?P<tag>section|details)\b[^>]*\bid=["\']{re.escape(anchor)}["\'][^>]*>'
            rf'(?P<body>.*?)</(?P=tag)>',
            content or "",
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            continue
        body = match.group("body")
        if re.search(r'class=["\'][^"\']*\bempty\b', body, flags=re.IGNORECASE):
            continue
        without_heading = re.sub(
            r"<h[1-6]\b[^>]*>.*?</h[1-6]>", " ", body,
            flags=re.IGNORECASE | re.DOTALL,
        )
        without_heading = re.sub(
            r"<summary\b[^>]*>.*?</summary>", " ", without_heading,
            flags=re.IGNORECASE | re.DOTALL,
        )
        text = html.unescape(re.sub(r"<[^>]+>", " ", without_heading))
        text = " ".join(text.split()).strip().lower()
        if not text or any(phrase in text for phrase in _REPORT_PLACEHOLDER_PHRASES):
            continue
        populated.add(anchor)
    return populated


def _structural_downgrade_sections(existing: str, candidate: str) -> list[str]:
    """Required sections populated in ``existing`` but absent/sparse in candidate."""
    lost = _populated_report_sections(existing) - _populated_report_sections(candidate)
    order = [anchor for anchor, _label in _REQUIRED_REPORT_SECTIONS]
    return [anchor for anchor in order if anchor in lost]


def _record_structural_downgrade(
    transport,
    wb_url: str,
    *,
    subject: str,
    candidate: str,
    lost_sections: list[str],
    source: str,
) -> str | None:
    """Best-effort preservation of a rejected candidate and its audit event."""
    diagnostic_id = None
    try:
        created = _req(
            transport,
            "POST",
            f"{wb_url}/objects",
            {
                "kind": "html",
                "title": f"{subject} rejected sparse report candidate",
                "drawer": "Artifacts",
                "filename": "refall-report-downgrade-candidate.html",
                "mime": "text/html",
                "description": (
                    "Candidate report preserved because publishing it would remove "
                    f"populated required sections: {', '.join(lost_sections)}."
                ),
                "content": candidate,
            },
        )
        if isinstance(created, dict) and created.get("id"):
            diagnostic_id = str(created["id"])
    except Exception:
        pass
    try:
        _req(
            transport,
            "POST",
            f"{wb_url}/ledger/entries",
            {
                "kind": "ops-event",
                "action": "report.structural_downgrade_refused",
                "status": "refused",
                "subject": subject,
                "summary": (
                    "Report update refused because required populated sections "
                    f"would be lost: {', '.join(lost_sections)}."
                ),
                "lost_sections": lost_sections,
                "source": source,
                "artifact_refs": [diagnostic_id] if diagnostic_id else [],
            },
        )
    except Exception:
        pass
    return diagnostic_id


def _report_toc(findings: list[dict], has: dict, *, mapping_mode: bool = False) -> str:
    if not mapping_mode:
        links = ['<a href="#summary">Executive summary</a>']
        links.extend(
            f'<a href="#{anchor}">{html.escape(label)}</a>'
            for anchor, label in _REQUIRED_REPORT_SECTIONS
        )
        return "".join(links)
    always = {"pending-actions", "runtime-evidence", "capability-decisions", "closeout-gate"}
    links = [
        '<a href="#summary">Executive summary</a>',
        '<a href="#mapping-visual">Coverage-to-codex visual</a>' if mapping_mode else "",
        '<a href="#exec-summary">Mapping overview</a>' if mapping_mode else '<a href="#exec-summary">Findings overview</a>',
    ]
    for anchor, label in [
        ("capability-equipment-map", "Capability/equipment map"),
        ("leads", "Open leads"),
        ("facts", "Key facts"),
        ("architecture", "Architecture & source surface" if mapping_mode else "Architecture & attack surface"),
        ("flows", "Data & control flows"),
    ]:
        if has.get(anchor):
            links.append(f'<a href="#{anchor}">{html.escape(label)}</a>')
    for i, finding in enumerate(findings, 1):
        links.append(f'<a href="#finding-{i}">Finding {i}: {html.escape(str(finding.get("title") or ""))}</a>')
    for anchor, label in [
        ("pending-actions", "Pending actions"),
        ("runtime-evidence", "Runtime evidence"),
        ("capability-decisions", "Capability decisions"),
        ("closeout-gate", "Closeout gate"),
    ]:
        if has.get(anchor, anchor in always):
            links.append(f'<a href="#{anchor}">{html.escape(label)}</a>')
    return "".join(link for link in links if link)


def _ensure_required_report_sections(body: str) -> str:
    present = set(re.findall(r'id="([^"]+)"', body))
    missing = []
    for anchor, label in _REQUIRED_REPORT_SECTIONS:
        if anchor == "closeout-gate" or anchor in present:
            continue
        missing.append(
            f'<section class="panel" id="{anchor}"><h2>{html.escape(label)}</h2>'
            '<p class="empty">None recorded.</p></section>'
        )
    return body + "".join(missing)


def _evidence_summary_sections(
    *,
    findings: list[dict],
    entries: list[dict],
    coverage: dict,
    ledger_stats: dict,
    nonfatal_errors: list[dict],
    manifest: dict,
    runtime_artifacts: list[dict],
) -> str:
    """Populate report-spec summary sections from canonical state.

    The detailed finding, architecture, flow, runtime, and capability panels are
    rendered elsewhere. These compact summaries prevent a data-bearing report
    from shipping with structurally present but content-empty spec sections.
    """
    def section(anchor: str, label: str, content: str) -> str:
        return f'<section class="panel" id="{anchor}"><h2>{html.escape(label)}</h2>{content}</section>'

    def items(values: list[str], empty_text: str) -> str:
        cleaned = [value for value in values if value]
        if not cleaned:
            return f"<p>{html.escape(empty_text)}</p>"
        return "<ul>" + "".join(f"<li>{html.escape(value)}</li>" for value in cleaned) + "</ul>"

    scope_values = [
        str(entry.get("description") or entry.get("text") or entry.get("summary") or "")
        for entry in entries
        if entry.get("kind") == "fact"
        and str(entry.get("title") or "").startswith(("arch:scope", "arch:boundary"))
    ]
    scope = section(
        "scope",
        "Tested Scope & Exclusions",
        items(scope_values, "No explicit scope fact was submitted; only the source inventory and recorded evidence were compiled."),
    )

    phases = sorted({str(entry.get("phase")) for entry in entries if entry.get("phase")})
    anchor_count = len({
        str(anchor)
        for entry in entries
        for anchor in (entry.get("source_anchors") or [])
        if str(anchor).strip()
    })
    methodology = section(
        "methodology",
        "Methodology",
        "<p>Evidence was compiled through a bounded, source-anchored REFALL AB review "
        f"using canonical ledger and runtime state. Recorded phases: <code>{html.escape(', '.join(phases) or 'none')}</code>; "
        f"distinct source anchors: <strong>{anchor_count}</strong>. Live exploitability is not inferred from static or prior local evidence.</p>",
    )

    coverage_section = section(
        "coverage",
        "Coverage Summary",
        "<table><tbody>"
        f"<tr><th>Files indexed</th><td>{html.escape(str(coverage.get('files_total', 0)))}</td></tr>"
        f"<tr><th>Files completed</th><td>{html.escape(str(coverage.get('files_done', 0)))}</td></tr>"
        f"<tr><th>Lines indexed</th><td>{html.escape(str(coverage.get('lines_total', 0)))}</td></tr>"
        f"<tr><th>Lines covered</th><td>{html.escape(str(coverage.get('lines_covered', 0)))}</td></tr>"
        f"<tr><th>Resolved</th><td>{html.escape(str(coverage.get('resolved_pct', 0)))}%</td></tr>"
        "</tbody></table>",
    )

    by_kind = ledger_stats.get("by_kind") or {}
    ledger_rows = "".join(
        f"<tr><td><code>{html.escape(str(kind))}</code></td><td>{html.escape(str(count))}</td></tr>"
        for kind, count in sorted(by_kind.items())
    ) or '<tr><td colspan="2">The evidence ledger contains no entries.</td></tr>'
    evidence_ledger = section(
        "evidence-ledger",
        "Evidence Ledger Summary",
        f"<table><thead><tr><th>Kind</th><th>Count</th></tr></thead><tbody>{ledger_rows}</tbody></table>",
    )

    valid = [finding for finding in findings if str(finding.get("status") or "").upper() == "VALID"]
    validated = section(
        "findings-validated",
        "Validated Findings",
        items(
            [str(finding.get("title") or finding.get("name") or finding.get("id") or "") for finding in valid],
            "No finding reached VALID status in this bounded run; provisional findings remain explicitly separated below.",
        ),
    )
    dispositions = [
        entry for entry in entries
        if str(entry.get("status") or "").upper() in {"FALSE_POSITIVE", "DUPLICATE"}
        or entry.get("kind") == "disposition-transition"
        and str(entry.get("to_status") or "").upper() in {"FALSE_POSITIVE", "DUPLICATE"}
    ]
    false_positives = section(
        "false-positives",
        "False Positives & Duplicates",
        items(
            [str(entry.get("title") or entry.get("finding_id") or entry.get("id") or "") for entry in dispositions],
            "No false-positive or duplicate disposition was recorded in this bounded run.",
        ),
    )

    flows = [entry.get("flow") for entry in entries if entry.get("fact_kind") == "flow" and isinstance(entry.get("flow"), dict)]
    attack_chains = section(
        "attack-chains",
        "Attack Chains",
        items(
            [
                f"Candidate chain: {flow.get('from')} -> {flow.get('to')} ({flow.get('relation')}); evidence: {flow.get('evidence') or 'see source anchors'}."
                for flow in flows
            ],
            "No chainable flow was recorded; open leads remain individual hypotheses.",
        ),
    )
    repro = section(
        "repro",
        "Reproduction & PoC Notes",
        items(
            [
                f"{finding.get('title') or finding.get('name') or finding.get('id')}: {step}"
                for finding in findings
                for step in _flist(finding, "reproduction", "reproduction_steps", "repro_steps", "repro")
            ],
            "No reproduction procedure was accepted in this bounded run.",
        ),
    )
    remediation = section(
        "remediation",
        "Remediation Guidance",
        items(
            [
                f"{finding.get('title') or finding.get('name') or finding.get('id')}: {_fstr(finding, 'remediation', 'remediation_summary', 'fix')}"
                for finding in findings
                if _fstr(finding, "remediation", "remediation_summary", "fix")
            ],
            "No finding-specific remediation was accepted in this bounded run.",
        ),
    )
    runtime_warnings = section(
        "runtime-warnings",
        "Runtime Warnings",
        items(
            [str(error.get("summary") or error.get("failure_class") or error.get("type") or "") for error in nonfatal_errors],
            "No nonfatal runtime warning is projected from canonical state.",
        ),
    )
    source_hashes = manifest.get("source_hashes") or {}
    freshness = section(
        "freshness",
        "Source / Config Freshness Receipts",
        f"<p>Run <code>{html.escape(str(manifest.get('run_id') or 'not recorded'))}</code> captured "
        f"<strong>{len(source_hashes)}</strong> source hashes and <strong>{len(manifest.get('config_hashes') or {})}</strong> config hashes.</p>",
    )
    visual_count = sum(1 for artifact in runtime_artifacts if "visual" in str(artifact.get("kind") or "").lower())
    visual = section(
        "visual-evidence",
        "Visual Evidence",
        f"<p>{visual_count} visual evidence artifact(s) were recorded; none are required for this bounded source-only canary.</p>",
    )
    provenance = section(
        "provenance",
        "Workbench Object Provenance",
        f"<p>This report was deterministically assembled from {len(entries)} ledger entries, "
        f"{len(runtime_artifacts)} runtime artifact(s), the run manifest, coverage state, and closeout state for this workbench.</p>",
    )
    return "".join([
        scope, methodology, coverage_section, evidence_ledger, validated,
        false_positives, attack_chains, repro, remediation, runtime_warnings,
        freshness, visual, provenance,
    ])


def _mapping_visual_section(coverage: dict) -> str:
    files_done = html.escape(str(coverage.get("files_done", 0)))
    files_total = html.escape(str(coverage.get("files_total", 0)))
    lines_done = html.escape(str(coverage.get("lines_covered", 0)))
    lines_total = html.escape(str(coverage.get("lines_total", 0)))
    resolved = html.escape(str(coverage.get("resolved_pct", 0)))
    return f"""
<section class="panel visual-panel" id="mapping-visual">
  <h2>Coverage-To-Codex Visual</h2>
  <div class="visual-wrap">
    <svg viewBox="0 0 920 260" role="img" aria-label="ARA source mapping pipeline from source inventory through characterization, decomposition, visuals, and HTML codex">
      <defs>
        <marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto">
          <path d="M0,0 L0,6 L8,3 z" fill="var(--accent)"></path>
        </marker>
      </defs>
      <rect x="24" y="44" width="160" height="78" rx="8" class="vbox"></rect>
      <text x="104" y="78" text-anchor="middle" class="vtitle">Source Inventory</text>
      <text x="104" y="101" text-anchor="middle" class="vsub">{files_done}/{files_total} files</text>
      <path d="M184 83 H270" class="varrow"></path>
      <rect x="270" y="44" width="170" height="78" rx="8" class="vbox"></rect>
      <text x="355" y="78" text-anchor="middle" class="vtitle">Line Mapping</text>
      <text x="355" y="101" text-anchor="middle" class="vsub">{lines_done}/{lines_total} lines</text>
      <path d="M440 83 H526" class="varrow"></path>
      <rect x="526" y="44" width="170" height="78" rx="8" class="vbox"></rect>
      <text x="611" y="78" text-anchor="middle" class="vtitle">Decompose</text>
      <text x="611" y="101" text-anchor="middle" class="vsub">flows, features, edges</text>
      <path d="M696 83 H782" class="varrow"></path>
      <rect x="782" y="44" width="114" height="78" rx="8" class="vbox"></rect>
      <text x="839" y="78" text-anchor="middle" class="vtitle">HTML Codex</text>
      <text x="839" y="101" text-anchor="middle" class="vsub">{resolved}% resolved</text>
      <rect x="140" y="166" width="640" height="34" rx="8" class="vrail"></rect>
      <rect x="140" y="166" width="640" height="34" rx="8" class="vfill"></rect>
      <text x="460" y="188" text-anchor="middle" class="vtitle">All claims must remain source-backed: files -> lines -> flows -> visuals</text>
    </svg>
  </div>
</section>"""


_ARA_CAPABILITY_TERMS = [
    "Armor",
    "Weapon",
    "Packs",
    "Tempers",
    "Temper",
    "Trim",
    "Forge",
    "Reforge",
    "chunks",
    "bytes",
    "crumbs",
    "alphabets",
    "Rhema",
    "Absolute",
    "Shadow",
    "Canary",
    "Policy",
    "Bulwark",
    "Courtyard",
    "Sew",
    "Tailor",
    "Keep",
    "TOD",
    "Danger",
    "Task",
    "Spoils",
    "Hermes",
]


def _mapping_receipt_payload(action: dict) -> dict:
    receipt = action.get("resolution_receipt")
    if isinstance(receipt, dict):
        nested = receipt.get("receipt")
        if isinstance(nested, dict):
            return nested
        return receipt
    return {}


def _mapping_capability_digest_section(actions: list[dict]) -> str:
    receipts: list[dict] = []
    for action in actions:
        payload = _mapping_receipt_payload(action)
        text = " ".join(
            str(value)
            for value in [
                action.get("kind"),
                action.get("title"),
                action.get("description"),
                payload.get("summary"),
            ]
            if value
        )
        if action.get("kind") == "mapping_report_gap" or any(term.lower() in text.lower() for term in _ARA_CAPABILITY_TERMS):
            receipts.append({"action": action, "payload": payload, "text": text})
    if not receipts:
        return ""

    refs: list[str] = []
    seen_refs: set[str] = set()
    for receipt in receipts:
        for ref in receipt["payload"].get("evidence_refs") or []:
            ref_text = str(ref).strip()
            if not ref_text or ref_text in seen_refs:
                continue
            seen_refs.add(ref_text)
            refs.append(ref_text)

    term_rows = ""
    combined_text = " ".join(receipt["text"] for receipt in receipts)
    for term in _ARA_CAPABILITY_TERMS:
        status = "source-mapped" if term.lower() in combined_text.lower() else "needs report synthesis"
        matching_refs = [ref for ref in refs if term.lower().rstrip("s") in ref.lower()]
        ref_html = ", ".join(f"<code>{html.escape(ref)}</code>" for ref in matching_refs[:3])
        if not ref_html:
            ref_html = '<span class="muted">covered by receipt evidence set</span>'
        term_rows += (
            "<tr>"
            f"<td><strong>{html.escape(term)}</strong></td>"
            f"<td>{html.escape(status)}</td>"
            f"<td>{ref_html}</td>"
            "</tr>"
        )

    receipt_summaries = "".join(
        f"<li>{html.escape(str(receipt['payload'].get('summary') or receipt['action'].get('description') or receipt['action'].get('title') or ''))}</li>"
        for receipt in receipts[:5]
    )
    refs_html = "".join(f"<li><code>{html.escape(ref)}</code></li>" for ref in refs[:40]) or "<li>No source references recorded.</li>"
    return f"""
<section class="panel visual-panel" id="capability-equipment-map">
  <h2>Capability/Equipment Mapping</h2>
  <p>This section is generated from resolved source-backed mapping receipts so the codex includes ARA equipment and capability concepts even when findings are intentionally suppressed.</p>
  <div class="visual-wrap">
    <svg viewBox="0 0 960 360" role="img" aria-label="ARA capability and equipment map from Armory loadout through Forge Reforge chunks guards Hermes task and evidence">
      <defs>
        <marker id="arrow-capability" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto">
          <path d="M0,0 L0,6 L8,3 z" fill="var(--accent)"></path>
        </marker>
      </defs>
      <rect x="28" y="40" width="170" height="78" rx="8" class="vbox"></rect>
      <text x="113" y="72" text-anchor="middle" class="vtitle">Armory Loadout</text>
      <text x="113" y="96" text-anchor="middle" class="vsub">Armor · Weapon · Packs</text>
      <path d="M198 79 H272" class="varrow" marker-end="url(#arrow-capability)"></path>
      <rect x="272" y="40" width="174" height="78" rx="8" class="vbox"></rect>
      <text x="359" y="72" text-anchor="middle" class="vtitle">Forge/Reforge</text>
      <text x="359" y="96" text-anchor="middle" class="vsub">Trim · Tempers · Temper</text>
      <path d="M446 79 H520" class="varrow" marker-end="url(#arrow-capability)"></path>
      <rect x="520" y="40" width="188" height="78" rx="8" class="vbox"></rect>
      <text x="614" y="72" text-anchor="middle" class="vtitle">Context Channels</text>
      <text x="614" y="96" text-anchor="middle" class="vsub">chunks · bytes · crumbs · alphabets</text>
      <path d="M708 79 H782" class="varrow" marker-end="url(#arrow-capability)"></path>
      <rect x="782" y="40" width="150" height="78" rx="8" class="vbox"></rect>
      <text x="857" y="72" text-anchor="middle" class="vtitle">Hermes Task</text>
      <text x="857" y="96" text-anchor="middle" class="vsub">Task · Spoils · evidence</text>
      <rect x="92" y="178" width="194" height="82" rx="8" class="vbox"></rect>
      <text x="189" y="208" text-anchor="middle" class="vtitle">Armor Controls</text>
      <text x="189" y="232" text-anchor="middle" class="vsub">Rhema · Bulwark · Policy</text>
      <path d="M286 219 H382" class="varrow" marker-end="url(#arrow-capability)"></path>
      <rect x="382" y="178" width="196" height="82" rx="8" class="vbox"></rect>
      <text x="480" y="208" text-anchor="middle" class="vtitle">Runtime Gates</text>
      <text x="480" y="232" text-anchor="middle" class="vsub">Absolute · Shadow · Canary · TOD</text>
      <path d="M578 219 H674" class="varrow" marker-end="url(#arrow-capability)"></path>
      <rect x="674" y="178" width="194" height="82" rx="8" class="vbox"></rect>
      <text x="771" y="208" text-anchor="middle" class="vtitle">Operator Review</text>
      <text x="771" y="232" text-anchor="middle" class="vsub">Courtyard · Sew · Tailor · Keep · Danger</text>
      <path d="M857 118 C857 154 812 158 771 178" class="varrow" marker-end="url(#arrow-capability)"></path>
    </svg>
  </div>
  <h3>Resolved Mapping Receipts</h3>
  <ul>{receipt_summaries}</ul>
  <h3>Concept Coverage</h3>
  <table>
    <thead><tr><th>Concept</th><th>Status</th><th>Evidence</th></tr></thead>
    <tbody>{term_rows}</tbody>
  </table>
  <h3>Source Evidence Set</h3>
  <ul>{refs_html}</ul>
</section>"""


_SECTION_RE = re.compile(
    r'<section(?:\s+class="panel")?\s+id="([^"]+)"\s*>\s*<h2>(.*?)</h2>(.*?)</section>',
    re.DOTALL,
)


def _collapse_sections(body: str) -> str:
    """Convert each top-level panel <section> into a <details> collapsed by
    default, keeping its <h2> as the summary. Sections are flat (no nesting),
    so the non-greedy match is safe."""
    def repl(m: "re.Match") -> str:
        anchor, title, inner = m.group(1), m.group(2), m.group(3)
        return (
            f'<details class="panel" id="{anchor}">'
            f'<summary>{title}</summary>'
            f'<div class="sec-body">{inner}</div></details>'
        )
    return _SECTION_RE.sub(repl, body)


def build_html_report(
    *,
    workbench: str,
    subject: str,
    coverage: dict,
    ledger_entries: list[dict],
    ledger_stats: dict,
    closeout_gate: dict | None = None,
    runtime_observations: list[dict] | None = None,
    runtime_artifacts: list[dict] | None = None,
    evidence_graph: dict | None = None,
    run_manifest: dict | None = None,
    nonfatal_errors: list[dict] | None = None,
    pending_actions: list[dict] | None = None,
    capabilities: dict | None = None,
    mapping_mode: bool = False,
) -> str:
    findings = _canonical_findings([entry for entry in ledger_entries if entry.get("kind") == "finding"])
    findings = sorted(findings, key=_finding_sort_key)
    capability_decisions = [
        entry for entry in ledger_entries
        if entry.get("kind") == "capability-decision"
    ]
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    by_kind = ledger_stats.get("by_kind") or {}
    high = sum(1 for f in findings if _sev(f) in {"critical", "high"})
    stat_cards = "".join(
        f'<div class="stat"><b>{html.escape(str(value))}</b><span>{html.escape(label)}</span></div>'
        for label, value in [
            ("Files mapped" if mapping_mode else "Total findings", f'{coverage.get("files_done", 0)}/{coverage.get("files_total", 0)}' if mapping_mode else len(findings)),
            ("Resolved lines" if mapping_mode else "Critical / High", f'{coverage.get("lines_covered", 0)}/{coverage.get("lines_total", 0)}' if mapping_mode else high),
            ("Facts", by_kind.get("fact", 0)),
            ("Leads", by_kind.get("lead", 0)),
            ("Resolved", f'{coverage.get("resolved_pct", 0)}%'),
            ("Lines covered", f'{coverage.get("lines_covered", 0)}/{coverage.get("lines_total", 0)}'),
        ]
    )
    # REFALL intel sections
    exec_summary = _exec_summary_section(findings)
    finding_articles = _finding_articles_section(findings)
    architecture = _architecture_section(ledger_entries)
    flows = _flows_section(ledger_entries)
    leads = _leads_section(ledger_entries)
    facts = _facts_section(ledger_entries)
    mapping_visual = _mapping_visual_section(coverage) if mapping_mode else ""
    capability_equipment_map = _mapping_capability_digest_section(pending_actions or []) if mapping_mode else ""
    # rich state sections (already data-complete; wrapped as cards)
    closeout_section = _panel(_closeout_section(closeout_gate or {}), "closeout-gate")
    if not closeout_section:
        closeout_section = (
            '<section class="panel" id="closeout-gate"><h2>Closeout Gate State</h2>'
            '<p class="empty">None recorded.</p></section>'
        )
    disposition_section = _panel(_disposition_transitions_section(ledger_entries), "disposition")
    override_section = _panel(_closeout_overrides_section(ledger_entries), "overrides")
    manifest_section = _panel(_run_manifest_section(run_manifest or {}), "manifest")
    pending_section = _panel(_pending_actions_section(pending_actions or []), "pending-actions")
    capabilities_section = _panel(
        _capabilities_section(capabilities or {}, capability_decisions), "capability-decisions"
    )
    runtime_section = _panel(
        _runtime_section(
            runtime_observations or [],
            runtime_artifacts or [],
            evidence_graph or {"nodes": [], "edges": []},
            nonfatal_errors or [],
        ),
        "runtime-evidence",
    )
    evidence_summaries = "" if mapping_mode else _evidence_summary_sections(
        findings=findings,
        entries=ledger_entries,
        coverage=coverage,
        ledger_stats=ledger_stats,
        nonfatal_errors=nonfatal_errors or [],
        manifest=run_manifest or {},
        runtime_artifacts=runtime_artifacts or [],
    )
    toc = _report_toc(findings, {
        "capability-equipment-map": bool(capability_equipment_map),
        "architecture": bool(architecture), "flows": bool(flows),
        "leads": bool(leads), "facts": bool(facts),
    }, mapping_mode=mapping_mode)
    core_body = "".join([
        mapping_visual,
        capability_equipment_map,
        exec_summary,          # Executive Summary / findings overview
        leads,                 # Open Leads
        facts,                 # Key Facts
        architecture,          # Architecture & Attack Surface
        flows,                 # Data & Control Flows
        finding_articles,      # Detailed findings listing (Finding 1, 2, ...)
        pending_section,       # Pending Actions
        runtime_section,       # Runtime Evidence
        capabilities_section,  # Capability Decisions
        disposition_section, override_section, manifest_section,  # supporting state
        evidence_summaries,      # required report-spec summaries
    ])
    if not mapping_mode:
        core_body = _ensure_required_report_sections(core_body)
    body = _collapse_sections(core_body + closeout_section)  # Closeout Gate remains last.
    report_title = "ARA Source Mapping Codex" if mapping_mode else "REFALL Security Report"
    report_subtitle = (
        "Source-backed architecture, feature, workflow, and line-level mapping."
        if mapping_mode else
        "Self-contained report compiled from the workbench ledger, findings, coverage, and runtime state. Regenerates as evidence lands."
    )
    sidebar_subtitle = "Source mapping · live evidence" if mapping_mode else "Security assessment · live evidence"
    rendered_from = (
        "rendered from source coverage, facts, leads, flows, and runtime artifacts"
        if mapping_mode else
        "rendered from the workbench ledger & findings"
    )
    root_vars = (
        "--bg:#0a0e18;--panel:#111827;--panel2:#172033;--ink:#f5f7fb;--muted:#9fb0c5;"
        "--line:#263244;--accent:#4aa6cc;--gold:#ffd166;--code-bg:#070b13;--code-ink:#d6ecff;"
        "--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;--crit:#ff5470;--high:#ff8f6b;--med:#ffd166;--low:#5ef2a6"
        if mapping_mode else
        "--bg:#0d1117;--panel:#161b24;--panel2:#1c2230;--ink:#e8edf6;--muted:#93a0b6;"
        "--line:#28313f;--accent:#5cc8ff;--code-bg:#0a0d13;--code-ink:#cfe6ff;"
        "--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;--crit:#ff5470;--high:#ff8f6b;--med:#ffcf6b;--low:#5ef2a6"
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(subject)} — {html.escape(report_title)}</title>
<style>
 :root{{{root_vars}}}
 *{{box-sizing:border-box}}body{{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--ink);line-height:1.5}}
 a{{color:var(--accent);text-decoration:none}}
 .shell{{max-width:1400px;margin:0 auto;display:grid;grid-template-columns:290px 1fr;min-height:100vh}}
 aside{{position:sticky;top:0;height:100vh;overflow:auto;padding:20px 16px;background:#10151f;border-right:1px solid var(--line)}}
 .brand{{background:linear-gradient(#1a2130,#141a26);border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:16px}}
 .brand .kicker{{display:inline-block;background:var(--panel2);border:1px solid var(--line);color:var(--accent);padding:2px 8px;border-radius:5px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}}
 .brand h1{{font-size:17px;margin:0 0 4px}}.brand p{{margin:0;color:var(--muted);font-size:12.5px}}
 .nav-title{{font-size:11px;text-transform:uppercase;color:var(--muted);font-weight:700;margin:16px 0 8px;letter-spacing:.06em}}
 .toc a{{display:block;padding:6px 9px;color:#c4d2ea;border-radius:5px;font-size:12.5px;margin-bottom:2px}}
 .toc a:hover{{background:var(--panel2);color:#fff}}
 main{{padding:28px 32px;min-width:0}}
 h2{{font-size:19px;margin:0 0 14px;padding-bottom:8px;border-bottom:1px solid var(--line)}}h2 small{{color:var(--muted);font-weight:400}}
 h3{{margin:14px 0 8px;font-size:15px}}h4{{margin:16px 0 6px;font-size:14px;color:var(--accent)}}
 .muted{{color:var(--muted)}}code{{font-family:var(--mono);font-size:.85em;color:var(--accent);word-break:break-word}}
 .hero{{background:linear-gradient(#171d29,#121620);border:1px solid var(--line);border-radius:12px;padding:26px}}
 .hero h2{{border:none;font-size:28px;margin:0 0 8px;padding:0}}.hero p{{color:var(--muted);margin:6px 0 0}}
 .stats{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px;margin:18px 0}}
 .stat{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:13px 14px}}
 .stat b{{display:block;font-size:23px}}.stat span{{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em}}
 .panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;margin-top:20px}}
 details.panel{{padding:0;overflow:hidden}}
 details.panel>summary{{list-style:none;cursor:pointer;padding:16px 20px;font-size:18px;font-weight:600;color:var(--ink);display:flex;align-items:center;gap:10px}}
 details.panel>summary::-webkit-details-marker{{display:none}}
 details.panel>summary::before{{content:"\\25B8";color:var(--accent);font-size:13px;transition:transform .15s}}
 details.panel[open]>summary{{border-bottom:1px solid var(--line)}}
 details.panel[open]>summary::before{{transform:rotate(90deg)}}
 details.panel>summary small{{color:var(--muted);font-weight:400}}
 details.panel>summary:hover{{color:var(--accent)}}
 .sec-body{{padding:18px 20px}}
 table{{width:100%;border-collapse:collapse;font-size:13.5px}}
 th,td{{text-align:left;vertical-align:top;padding:9px 10px;border-bottom:1px solid var(--line);word-break:break-word}}
 th{{background:var(--panel2);color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.04em}}
 .badge{{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11.5px;font-weight:700;border:1px solid var(--line);background:var(--panel2);color:var(--muted);text-transform:uppercase;letter-spacing:.03em}}
 .badge.critical{{color:var(--crit);border-color:#5a2f3a;background:#2a1720}}
 .badge.high{{color:var(--high);border-color:#5a3f2f;background:#2a1d16}}
 .badge.medium{{color:var(--med);border-color:#5a4f2f;background:#2a2516}}
 .badge.low{{color:var(--low);border-color:#2f5a44;background:#132a20}}
 .finding{{background:var(--panel);border:1px solid var(--line);border-radius:12px;margin-top:20px;overflow:hidden}}
 .finding.critical{{border-left:4px solid var(--crit)}}.finding.high{{border-left:4px solid var(--high)}}.finding.medium{{border-left:4px solid var(--med)}}.finding.low{{border-left:4px solid var(--low)}}
 .finding-header{{padding:16px 20px;background:linear-gradient(#1a212e,#141a25);border-bottom:1px solid var(--line)}}
 .finding-header .badge{{margin-bottom:8px}}.finding-header h3{{font-size:20px;margin:0}}
 .finding-body{{padding:20px}}
 .grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}
 .kv{{border:1px solid var(--line);border-radius:8px;padding:10px 12px;background:var(--panel2)}}
 .kv strong{{display:block;font-size:11px;text-transform:uppercase;color:var(--muted);margin-bottom:5px;letter-spacing:.04em}}
 .finding-body h4{{margin:18px 0 6px;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);border-bottom:1px solid var(--line);padding-bottom:5px}}
 .f-list{{margin:8px 0 0;padding-left:0;list-style:none;display:flex;flex-direction:column;gap:5px}}
 ol.f-list{{counter-reset:step;gap:8px}}
 ol.f-list li{{counter-increment:step;padding-left:26px;position:relative;line-height:1.5}}
 ol.f-list li::before{{content:counter(step);position:absolute;left:0;top:0;width:18px;height:18px;border-radius:50%;background:var(--panel2);border:1px solid var(--accent);color:var(--accent);font-size:11px;display:flex;align-items:center;justify-content:center}}
 ul.f-list li code{{display:block;font-family:var(--mono);font-size:11.5px;padding:6px 10px;border:1px solid var(--line);border-radius:5px;background:var(--code-bg);color:var(--code-ink);word-break:break-all}}
 .lead{{border:1px solid var(--line);border-left:4px solid var(--med);border-radius:10px;padding:12px 14px;margin-top:12px;background:var(--panel2)}}
 .fhead{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:6px}}
 .rel{{color:var(--accent);font-family:var(--mono);font-size:12px}}.plan{{color:var(--accent);font-size:13px;margin:6px 0 0}}
 .visual-wrap{{overflow:auto}}.visual-wrap svg{{width:100%;min-width:760px;height:auto;display:block}}
 .vbox{{fill:var(--panel2);stroke:var(--gold,var(--accent));stroke-width:1.5}}
 .vrail{{fill:#0c1322;stroke:var(--line)}}.vfill{{fill:rgba(74,166,204,.35);stroke:var(--accent)}}
 .varrow{{stroke:var(--accent);stroke-width:3;fill:none;marker-end:url(#arrow)}}
 .vtitle{{fill:var(--ink);font-weight:700;font-size:15px}}.vsub{{fill:var(--muted);font-size:12px}}
 pre{{overflow:auto;background:var(--code-bg);color:var(--code-ink);padding:13px;border-radius:8px;font-size:12px;line-height:1.45;border:1px solid var(--line)}}
 .empty{{color:var(--muted);font-style:italic}}
 .foot{{color:var(--muted);font-size:12px;margin-top:26px;border-top:1px solid var(--line);padding-top:14px}}
 @media(max-width:980px){{html,body{{max-width:100%;overflow-x:hidden}}.shell{{grid-template-columns:1fr;max-width:100%;overflow-x:hidden}}aside{{position:relative;height:auto}}main{{padding:18px;max-width:100%;overflow-x:hidden}}.stats{{grid-template-columns:repeat(2,1fr)}}.grid{{grid-template-columns:1fr}}table{{display:block;max-width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch}}th,td{{white-space:normal;overflow-wrap:anywhere;word-break:break-word}}code{{white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;max-width:100%;overflow-x:auto}}.visual-wrap{{max-width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch}}.visual-wrap svg{{width:100%;min-width:0}}}}
 @media(max-width:640px){{main{{padding:14px}}.hero{{padding:18px}}.hero h2{{font-size:22px;line-height:1.2}}.stats{{grid-template-columns:1fr}}details.panel>summary{{font-size:16px;padding:14px}}.sec-body{{padding:14px}}}}
</style>
</head>
<body>
<div class="shell">
<aside>
  <div class="brand"><span class="kicker">REFALL-V10</span><h1>{html.escape(subject)}</h1><p>{html.escape(sidebar_subtitle)}</p></div>
  <div class="nav-title">Contents</div>
  <nav class="toc">{toc}</nav>
</aside>
<main>
  <div class="hero" id="summary"><h2>{html.escape(subject)} — {html.escape(report_title)}</h2>
    <p>{html.escape(report_subtitle)}</p>
    <p class="muted">Workbench <code>{html.escape(workbench)}</code> · generated {html.escape(generated_at)}</p>
  </div>
  <div class="stats">{stat_cards}</div>
  {body}
  <div class="foot">REFALL-V10 · self-contained HTML report · {html.escape(rendered_from)}. Sections populate automatically as loop agents emit source-backed facts, leads, flows, artifacts, and maps.</div>
</main>
</div>
</body>
</html>
"""


def _finding_row(entry: dict) -> str:
    refs = ", ".join(str(ref) for ref in entry.get("refs") or entry.get("code_paths") or [])
    related = _related_locations_html(entry.get("related_locations") or [])
    return (
        "<tr>"
        f"<td>{html.escape(str(entry.get('severity') or ''))}</td>"
        f"<td>{html.escape(str(entry.get('title') or ''))}</td>"
        f"<td>{html.escape(str(entry.get('impact') or entry.get('summary') or ''))}</td>"
        f"<td><code>{html.escape(refs)}</code>{related}</td>"
        "</tr>"
    )


def _canonical_findings(entries: list[dict]) -> list[dict]:
    findings: list[dict] = []
    by_key: dict[str, dict] = {}
    for entry in entries:
        item = dict(entry)
        item["related_locations"] = _merge_related_locations(
            item.get("related_locations") or [],
            _related_locations_from_finding(item),
        )
        key = _finding_canonical_key(item)
        if key in by_key:
            canonical = by_key[key]
            canonical["related_locations"] = _merge_related_locations(
                canonical.get("related_locations") or [],
                item.get("related_locations") or [],
            )
            continue
        by_key[key] = item
        findings.append(item)
    return findings


def _finding_canonical_key(entry: dict) -> str:
    explicit = (
        entry.get("canonical_finding_id")
        or entry.get("dedup_key")
        or entry.get("finding_id")
        or entry.get("id")
    )
    if explicit:
        return str(explicit)
    return "|".join([
        str(entry.get("subject") or ""),
        _normalize_key(entry.get("vuln_class") or "unknown"),
        _normalize_key(entry.get("title") or ""),
        _normalize_key(entry.get("affected_component") or entry.get("component") or ""),
    ])


def _related_locations_from_finding(entry: dict) -> list[dict]:
    refs: list[str] = []
    for key in ("code_paths", "source_anchors", "artifact_refs", "refs"):
        refs.extend(str(item) for item in entry.get(key) or [] if str(item).strip())
    return _merge_related_locations([], [{"path": _source_anchor_path(ref) or ref, "anchor": ref} for ref in refs])


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


def _related_locations_html(locations: list[dict]) -> str:
    if not locations:
        return ""
    items = "".join(
        f"<li><code>{html.escape(str(item.get('anchor') or item.get('path') or ''))}</code></li>"
        for item in locations
    )
    return f"<div><strong>Related Locations</strong><ul>{items}</ul></div>"


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


def _normalize_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _closeout_section(closeout_gate: dict) -> str:
    if not closeout_gate:
        return ""
    checks = closeout_gate.get("checks") if isinstance(closeout_gate.get("checks"), list) else []
    check_rows = "".join(_closeout_check_row(check) for check in checks) or (
        "<tr><td colspan=\"4\">No closeout checks returned.</td></tr>"
    )
    summary = html.escape(json.dumps(closeout_gate.get("summary") or {}, sort_keys=True))
    state = "passed" if closeout_gate.get("passed") else "blocked"
    return f"""
  <h2>Closeout Gate</h2>
  <p>State: <strong>{html.escape(state)}</strong></p>
  <p><code>{summary}</code></p>
  <table>
    <thead><tr><th>Check</th><th>Status</th><th>Blocking</th><th>Details</th></tr></thead>
    <tbody>{check_rows}</tbody>
  </table>
"""


def _closeout_check_row(check: dict) -> str:
    details = ", ".join(str(item) for item in check.get("details", []))
    return (
        "<tr>"
        f"<td>{html.escape(str(check.get('id') or ''))}</td>"
        f"<td>{html.escape(str(check.get('status') or ''))}</td>"
        f"<td>{html.escape(str(check.get('blocking') or False))}</td>"
        f"<td><code>{html.escape(details)}</code></td>"
        "</tr>"
    )


def _pending_actions_section(actions: list[dict]) -> str:
    rows = "".join(_pending_action_row(action) for action in actions) or (
        "<tr><td colspan=\"4\">No pending actions recorded.</td></tr>"
    )
    return f"""
  <h2>Pending Actions</h2>
  <table>
    <thead><tr><th>Status</th><th>Kind</th><th>Title</th><th>Receipt</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
"""


def _run_manifest_section(manifest: dict) -> str:
    if not manifest:
        return ""
    interesting = {
        "manifest_id": manifest.get("manifest_id"),
        "run_id": manifest.get("run_id"),
        "provider_roles": manifest.get("provider_roles") or {},
        "runtime_host": manifest.get("runtime_host") or {},
        "dynamic_testing": manifest.get("dynamic_testing") or {},
        "git": manifest.get("git") or {},
        "stage_status": manifest.get("stage_status") or {},
    }
    return f"""
  <h2>Run Manifest</h2>
  <pre><code>{html.escape(json.dumps(interesting, indent=2, sort_keys=True))}</code></pre>
"""


def _disposition_transitions_section(entries: list[dict]) -> str:
    transitions = [entry for entry in entries if entry.get("kind") == "disposition-transition"]
    if not transitions:
        return ""
    rows = "".join(_disposition_transition_row(entry) for entry in transitions)
    return f"""
  <h2>Disposition Transitions</h2>
  <table>
    <thead><tr><th>Status</th><th>Finding</th><th>Receipt</th><th>Details</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
"""


def _disposition_transition_row(entry: dict) -> str:
    details = "; ".join(str(reason) for reason in entry.get("refusal_reasons", []))
    if not details:
        details = str(entry.get("summary") or "")
    return (
        "<tr>"
        f"<td>{html.escape(str(entry.get('status') or ''))}</td>"
        f"<td><code>{html.escape(str(entry.get('finding_id') or ''))}</code></td>"
        f"<td><code>{html.escape(str(entry.get('receipt_type') or ''))}</code></td>"
        f"<td>{html.escape(details)}</td>"
        "</tr>"
    )


def _closeout_overrides_section(entries: list[dict]) -> str:
    overrides = [
        entry for entry in entries
        if entry.get("kind") == "ops-event" and entry.get("action") == "closeout.override"
    ]
    if not overrides:
        return ""
    rows = "".join(_closeout_override_row(entry) for entry in overrides)
    return f"""
  <h2>Closeout Overrides</h2>
  <table>
    <thead><tr><th>Status</th><th>Checks</th><th>Operator</th><th>Reason</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
"""


def _closeout_override_row(entry: dict) -> str:
    checks = ", ".join(str(check_id) for check_id in entry.get("check_ids", []))
    return (
        "<tr>"
        f"<td>{html.escape(str(entry.get('status') or ''))}</td>"
        f"<td><code>{html.escape(checks)}</code></td>"
        f"<td>{html.escape(str(entry.get('created_by') or ''))}</td>"
        f"<td>{html.escape(str(entry.get('summary') or ''))}</td>"
        "</tr>"
    )


def _pending_action_row(action: dict) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(str(action.get('status') or ''))}</td>"
        f"<td>{html.escape(str(action.get('kind') or ''))}</td>"
        f"<td>{html.escape(str(action.get('title') or ''))}</td>"
        f"<td><code>{html.escape(str(action.get('required_receipt_type') or ''))}</code></td>"
        "</tr>"
    )


def _capabilities_section(capabilities: dict, decisions: list[dict]) -> str:
    grants = capabilities.get("grants") if isinstance(capabilities.get("grants"), list) else []
    requests = capabilities.get("requests") if isinstance(capabilities.get("requests"), list) else []
    grant_rows = "".join(_capability_row(grant, "grant") for grant in grants)
    request_rows = "".join(_capability_row(request, "request") for request in requests)
    decision_rows = "".join(_capability_decision_row(decision) for decision in decisions)
    rows = grant_rows + request_rows + decision_rows or (
        "<tr><td colspan=\"5\">No capability grants, requests, or decisions recorded.</td></tr>"
    )
    return f"""
  <h2>Capability Decisions</h2>
  <table>
    <thead><tr><th>Type</th><th>Status</th><th>Class</th><th>Actor</th><th>Summary</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
"""


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
    request = item.get("request") if isinstance(item.get("request"), dict) else {}
    actor = request.get("requested_by") or item.get("agent") or ""
    return (
        "<tr>"
        "<td>decision</td>"
        f"<td>{html.escape(str(item.get('status') or ''))}</td>"
        f"<td><code>{html.escape(str(item.get('capability_class') or ''))}</code></td>"
        f"<td>{html.escape(str(actor))}</td>"
        f"<td>{html.escape(str(item.get('summary') or ''))}</td>"
        "</tr>"
    )


def _runtime_section(observations: list[dict], artifacts: list[dict], evidence_graph: dict, nonfatal_errors: list[dict]) -> str:
    observation_rows = "".join(_observation_row(item) for item in observations) or (
        "<tr><td colspan=\"4\">No runtime observations projected.</td></tr>"
    )
    artifact_rows = "".join(_artifact_row(item) for item in artifacts) or (
        "<tr><td colspan=\"4\">No runtime artifacts recorded.</td></tr>"
    )
    warning_rows = "".join(_nonfatal_error_row(item) for item in nonfatal_errors) or (
        "<tr><td colspan=\"5\">No nonfatal runtime warnings projected.</td></tr>"
    )
    nodes = len(evidence_graph.get("nodes") or [])
    edges = len(evidence_graph.get("edges") or [])
    return f"""
  <h2>Runtime Evidence</h2>
  <p>Evidence graph: <strong>{nodes} nodes / {edges} edges</strong></p>
  <h3>Runtime Warnings</h3>
  <table>
    <thead><tr><th>Source</th><th>Type</th><th>Failure Class</th><th>Task</th><th>Summary</th></tr></thead>
    <tbody>{warning_rows}</tbody>
  </table>
  <h3>Observations</h3>
  <table>
    <thead><tr><th>Kind</th><th>Claim</th><th>Confidence</th><th>Evidence</th></tr></thead>
    <tbody>{observation_rows}</tbody>
  </table>
  <h3>Runtime Artifacts</h3>
  <table>
    <thead><tr><th>Kind</th><th>Path</th><th>MIME</th><th>Size</th></tr></thead>
    <tbody>{artifact_rows}</tbody>
  </table>
"""


def _nonfatal_error_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(str(item.get('source') or ''))}</td>"
        f"<td><code>{html.escape(str(item.get('type') or ''))}</code></td>"
        f"<td>{html.escape(str(item.get('failure_class') or ''))}</td>"
        f"<td><code>{html.escape(str(item.get('task_id') or ''))}</code></td>"
        f"<td>{html.escape(str(item.get('summary') or ''))}</td>"
        "</tr>"
    )


def _observation_row(observation: dict) -> str:
    evidence = ", ".join(str(ref) for ref in observation.get("evidence_refs", []))
    return (
        "<tr>"
        f"<td>{html.escape(str(observation.get('kind') or ''))}</td>"
        f"<td>{html.escape(str(observation.get('claim') or ''))}</td>"
        f"<td>{html.escape(str(observation.get('confidence') or ''))}</td>"
        f"<td><code>{html.escape(evidence)}</code></td>"
        "</tr>"
    )


def _artifact_row(artifact: dict) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(str(artifact.get('kind') or ''))}</td>"
        f"<td><code>{html.escape(str(artifact.get('path') or ''))}</code></td>"
        f"<td>{html.escape(str(artifact.get('mime') or ''))}</td>"
        f"<td>{html.escape(str(artifact.get('size_bytes') or 0))}</td>"
        "</tr>"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbench", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--allow-structural-downgrade", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(draft_report(
        args.workbench,
        args.subject,
        allow_structural_downgrade=args.allow_structural_downgrade,
    ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
