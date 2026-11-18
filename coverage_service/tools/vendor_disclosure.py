"""Build and publish a self-contained vendor disclosure report for a subject.

  PYTHONPATH=. python3 -m coverage_service.tools.vendor_disclosure example \
      --title "Example Subject - Vendor Disclosure Report"
"""
import argparse
import datetime as _dt
import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

WB = os.environ.get("REFALL_WORKBENCH_BASE", "http://127.0.0.1:7673")
SLUG = os.environ.get("REFALL_WORKBENCH_SLUG", "ref-all")
COV = os.environ.get("COVERAGE_BASE", "http://localhost:8900")
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
REPORT_DIR = os.path.join(STATE_DIR, "reports")

SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
REJECTED = {"FALSE_POSITIVE", "DUPLICATE"}
TEXT_ARTIFACT_EXTS = {".txt", ".log", ".test", ".http", ".json", ".md", ".stdout", ".stderr"}
LOCAL_PATH_RE = re.compile(r"(?:(?:/Users/|/projects/)[^\s,;)'\"<>]+)")


def _get(path):
    with urllib.request.urlopen(COV + path, timeout=30) as r:
        return json.loads(r.read())


def _maybe_get(path, default):
    try:
        return _get(path)
    except Exception:
        return default


def _clip(text, limit=1200):
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + "..."


def _public_text(text):
    """Remove host-local paths from report text while preserving useful artifact hints."""
    def repl(match):
        raw = match.group(0)
        suffix = ""
        path = raw
        while path and path[-1] in ".:":
            suffix = path[-1] + suffix
            path = path[:-1]
        if path.startswith("/projects/REFALL-V10/"):
            label = path[len("/projects/REFALL-V10/"):]
        elif path.startswith("/projects/"):
            parts = path.split("/")
            label = "/".join(parts[3:]) if len(parts) > 3 else os.path.basename(path)
        else:
            label = os.path.basename(path) or "artifact"
        return label + suffix

    return LOCAL_PATH_RE.sub(repl, str(text or ""))


def _esc(text):
    return html.escape(_public_text(text))


def _first(value, fallback="Not specified"):
    value = (value or "").strip() if isinstance(value, str) else value
    return value or fallback


def _quoted_subject(subject):
    return urllib.parse.quote(subject, safe="")


def _generated_at(value=None):
    if value:
        return value
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _severity_key(finding):
    return (SEV_ORDER.get(finding.get("severity"), 9), finding.get("title") or "")


def _sentence(text, fallback="Not recorded.", limit=420):
    text = _clip(text or "", limit)
    return text or fallback


def _extract_command_block(finding):
    hints = finding.get("repro_hints") or ""
    if not hints:
        return ""
    run_idx = hints.lower().find("run:")
    if run_idx >= 0:
        return _clip(hints[run_idx + 4:].strip(), 900)
    return _clip(hints, 900)


def _trace_nodes(finding):
    text = finding.get("critic_reasoning") or finding.get("repro_hints") or ""
    match = re.search(r"Visual trace:\s*(.+?)(?:\.\s+[A-Z][a-z ]+:|$)", text, re.I | re.S)
    raw = match.group(1) if match else ""
    nodes = [p.strip(" .") for p in re.split(r"\s*(?:->|=>|-->)\s*", raw) if p.strip(" .")]
    if len(nodes) >= 2:
        return nodes[:5]
    return [
        "Attacker input",
        "Parser / state update",
        "Vulnerable sink",
        "Security impact",
    ]


def _trace_svg(finding):
    nodes = _trace_nodes(finding)
    width = max(720, 180 * len(nodes))
    parts = [
        f'<svg class="trace-svg" viewBox="0 0 {width} 140" role="img" '
        f'aria-label="Evidence trace for {_esc(finding.get("title"))}">',
        "<defs><marker id=\"arrow\" viewBox=\"0 0 10 10\" refX=\"9\" refY=\"5\" "
        "markerWidth=\"6\" markerHeight=\"6\" orient=\"auto-start-reverse\">"
        "<path d=\"M 0 0 L 10 5 L 0 10 z\" /></marker></defs>",
    ]
    for idx, node in enumerate(nodes):
        x = 18 + idx * 180
        parts.append(f'<rect x="{x}" y="34" width="142" height="70" rx="7" />')
        parts.append(f'<text x="{x + 71}" y="60" text-anchor="middle">{_esc(_clip(node, 34))}</text>')
        parts.append(f'<text x="{x + 71}" y="82" text-anchor="middle" class="trace-small">step {idx + 1}</text>')
        if idx < len(nodes) - 1:
            parts.append(
                f'<line x1="{x + 146}" y1="69" x2="{x + 174}" y2="69" marker-end="url(#arrow)" />'
            )
    parts.append("</svg>")
    return "".join(parts)


def _artifact_paths(finding):
    text = "\n".join(
        str(finding.get(k) or "")
        for k in ("repro_hints", "critic_reasoning", "production_viability", "reasoning")
    )
    candidates = []
    for match in re.findall(r"(?:(?:/Users/|/projects/|poc/out/|coverage_service/data/)[^\s,;)'\"<>]+)", text):
        path = match.rstrip(".")
        if path.startswith("/projects/REFALL-V10/"):
            path = os.path.join(REPO_ROOT, path[len("/projects/REFALL-V10/"):])
        elif path.startswith("poc/out/") or path.startswith("coverage_service/data/"):
            path = os.path.join(REPO_ROOT, path)
        candidates.append(path)
    seen = set()
    out = []
    for path in candidates:
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out[:8]


def _artifact_excerpt(path):
    if not os.path.exists(path) or not os.path.isfile(path):
        return None
    size = os.path.getsize(path)
    ext = os.path.splitext(path)[1].lower()
    if size > 65536 or (ext and ext not in TEXT_ARTIFACT_EXTS):
        return {"path": path, "size": size, "text": None}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return {"path": path, "size": size, "text": _clip(fh.read(), 12000)}
    except OSError:
        return None


def _artifact_html(finding):
    artifacts = [_artifact_excerpt(path) for path in _artifact_paths(finding)]
    artifacts = [a for a in artifacts if a]
    if not artifacts:
        return ""
    rows = []
    for art in artifacts:
        if art["text"] is None:
            rows.append(
                f"<li><span class=mono>{_esc(art['path'])}</span> "
                f"({art['size']} bytes, not embedded)</li>"
            )
        else:
            rows.append(
                f"<li><span class=mono>{_esc(art['path'])}</span> "
                f"({art['size']} bytes)<pre>{_esc(art['text'])}</pre></li>"
            )
    return "<h4>Evidence Artifacts</h4><ul class=artifacts>" + "".join(rows) + "</ul>"


def _kv(label, value):
    return f"<tr><th>{_esc(label)}</th><td>{_esc(_first(value))}</td></tr>"


def _finding_section(finding, idx):
    title = finding.get("title") or f"Finding {idx}"
    command = _extract_command_block(finding)
    code_paths = finding.get("code_paths") or []
    code_list = "".join(f"<li><span class=mono>{_esc(path)}</span></li>" for path in code_paths)
    command_html = f"<pre>{_esc(command)}</pre>" if command else "<p class=muted>No command recorded.</p>"
    raw_evidence = finding.get("critic_reasoning") or finding.get("reasoning") or ""
    return f"""<article class="finding sev-{_esc(finding.get('severity'))}" id="finding-{idx}">
  <div class=finding-head>
    <div>
      <p class=eyebrow>Confirmed vulnerability {idx}</p>
      <h3>{_esc(title)}</h3>
    </div>
    <span class="sev {_esc(finding.get('severity'))}">{_esc(finding.get('severity') or 'UNKNOWN')}</span>
  </div>
  <table class=meta>
    {_kv('Status', finding.get('status'))}
    {_kv('Severity', finding.get('severity'))}
    {_kv('Vulnerability class', finding.get('vuln_class'))}
    {_kv('Privileges required', finding.get('privileges_required'))}
    {_kv('Attacker position', finding.get('attacker_position'))}
    {_kv('User interaction', finding.get('user_interaction'))}
    {_kv('Runtime validation', finding.get('repro_status'))}
    {_kv('Patch status', finding.get('patch_status'))}
  </table>
  <div class=trace-wrap>{_trace_svg(finding)}</div>
  <div class=cols>
    <section><h4>Impact</h4><p>{_esc(_sentence(finding.get('impact')))}</p></section>
    <section><h4>Root Cause</h4><p>{_esc(_sentence(finding.get('description')))}</p></section>
  </div>
  <section><h4>Affected Code Paths</h4><ul>{code_list or '<li class=muted>No code path recorded.</li>'}</ul></section>
  <section><h4>Runtime Proof and Exploitability</h4>
    <p>{_esc(_sentence(finding.get('production_viability')))}</p>
  </section>
  <section><h4>Reproduction Steps</h4>{command_html}</section>
  <section><h4>Evidence and Raw Output</h4><pre>{_esc(_clip(raw_evidence, 5000))}</pre>{_artifact_html(finding)}</section>
  <section><h4>Recommended Remediation</h4><p>{_esc(_sentence(finding.get('mitigation')))}</p></section>
</article>"""


def _rejected_item(finding):
    return (
        f"<li><b>{_esc(finding.get('status'))}</b> - {_esc(finding.get('title'))}"
        f"<br><span class=muted>{_esc(_clip(finding.get('reasoning'), 360))}</span></li>"
    )


def build(subject, title=None, generated_at=None):
    title = title or f"{subject} - Vendor Disclosure Report"
    qsubject = _quoted_subject(subject)
    findings = _get(f"/findings?subject={qsubject}")
    funnel = _maybe_get(f"/funnel?subject={qsubject}", {})
    plan = _maybe_get(f"/plan_progress?subject={qsubject}", {})
    context = _maybe_get(f"/context?subject={qsubject}", {})
    valid = sorted([f for f in findings if f.get("status") == "VALID"], key=_severity_key)
    rejected = [f for f in findings if f.get("status") in REJECTED]
    needs_research = [f for f in findings if f.get("status") == "NEEDS_RESEARCH"]
    generated = _generated_at(generated_at)
    valid_html = "".join(_finding_section(f, idx) for idx, f in enumerate(valid, start=1))
    if not valid_html:
        valid_html = "<p class=empty>No confirmed vulnerabilities are ready for vendor disclosure.</p>"
    rejected_html = "".join(_rejected_item(f) for f in rejected) or "<li class=empty>None recorded.</li>"
    needs_html = "".join(_rejected_item(f) for f in needs_research) or "<li class=empty>None recorded.</li>"
    root = context.get("root_container") or f"/projects/{subject}"
    summary = context.get("info_md") or "No subject context was recorded by the loop."
    return f"""<!doctype html>
<html lang=en>
<head>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<style>
:root{{--bg:var(--wb-bg,#0d1020);--surface:var(--wb-surface,#171b31);--surface2:var(--wb-surface-2,#1e2440);--ink:var(--wb-ink,#f4f7ff);--muted:var(--wb-muted,#9aa6c7);--rule:var(--wb-rule,#2b3156);--accent:var(--wb-accent,#e51b2d);--accent2:var(--wb-accent-2,#6ee85a);--radius:var(--wb-card-radius,8px);--crit:#ff4d5e;--high:#ff9f40;--med:#ffce54;--low:#7a83a6}}
*{{box-sizing:border-box}}html,body{{margin:0;max-width:100%;overflow-x:hidden}}body{{background:var(--bg);color:var(--ink);font:15px/1.55 Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:22px}}main{{max-width:1120px;margin:0 auto}}h1{{font-size:clamp(28px,5vw,44px);line-height:1.05;margin:.15em 0 .2em;color:var(--ink)}}h2{{font-size:23px;margin:30px 0 12px;border-bottom:1px solid var(--rule);padding-bottom:8px}}h3{{font-size:20px;margin:0}}h4{{font-size:13px;letter-spacing:.04em;text-transform:uppercase;color:var(--accent2);margin:16px 0 6px}}p{{margin:8px 0}}a{{color:var(--accent2)}}pre{{white-space:pre-wrap;overflow:auto;max-width:100%;background:#070a14;border:1px solid var(--rule);border-radius:7px;padding:10px;color:#dfe7ff;font:12px/1.45 Menlo,Consolas,monospace}}ul{{padding-left:20px}}li{{margin:7px 0}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;vertical-align:top;border-bottom:1px solid var(--rule);padding:7px 8px}}th{{width:190px;color:var(--muted);font-weight:600}}.mono{{font:12px/1.4 Menlo,Consolas,monospace;overflow-wrap:anywhere}}.muted,.empty{{color:var(--muted)}}.hero{{display:grid;grid-template-columns:1.4fr .8fr;gap:18px;align-items:stretch;margin-bottom:18px}}.panel,.finding,details{{background:var(--surface);border:1px solid var(--rule);border-radius:var(--radius);padding:16px}}.panel.accent{{border-left:4px solid var(--accent2)}}.eyebrow{{margin:0 0 4px;color:var(--accent2);font:700 11px/1.2 Menlo,Consolas,monospace;text-transform:uppercase;letter-spacing:.08em}}.stats{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:16px 0}}.stat{{background:var(--surface2);border:1px solid var(--rule);border-radius:7px;padding:11px}}.stat b{{display:block;font-size:25px;color:var(--accent2)}}.finding{{margin:16px 0;border-left:4px solid var(--low)}}.finding.sev-CRITICAL{{border-left-color:var(--crit)}}.finding.sev-HIGH{{border-left-color:var(--high)}}.finding.sev-MEDIUM{{border-left-color:var(--med)}}.finding-head{{display:flex;gap:12px;justify-content:space-between;align-items:flex-start;margin-bottom:12px}}.sev{{display:inline-flex;align-items:center;border-radius:4px;padding:4px 8px;color:#0a0d18;background:var(--low);font:800 11px/1 Menlo,Consolas,monospace}}.sev.CRITICAL{{background:var(--crit)}}.sev.HIGH{{background:var(--high)}}.sev.MEDIUM{{background:var(--med)}}.sev.LOW{{background:var(--low);color:#eef3ff}}.cols{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}.trace-wrap{{overflow:auto;border:1px solid var(--rule);background:var(--surface2);border-radius:7px;margin:12px 0}}.trace-svg{{display:block;min-width:680px;width:100%;height:140px}}.trace-svg rect{{fill:#10162b;stroke:var(--accent2);stroke-width:1.4}}.trace-svg line{{stroke:var(--accent2);stroke-width:1.4}}.trace-svg marker path{{fill:var(--accent2)}}.trace-svg text{{fill:var(--ink);font:12px Menlo,Consolas,monospace}}.trace-svg .trace-small{{fill:var(--muted);font-size:10px}}details{{margin:14px 0;padding:4px 16px}}summary{{cursor:pointer;padding:12px 0;font-weight:800}}.checklist{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}}.check{{background:var(--surface2);border:1px solid var(--rule);border-radius:7px;padding:9px}}.artifacts pre{{margin-top:6px}}@media(max-width:760px){{body{{padding:12px}}.hero,.cols,.stats,.checklist{{grid-template-columns:1fr}}.finding-head{{display:block}}th{{width:130px}}}}
</style>
</head>
<body>
<main>
  <section class=hero>
    <div class="panel accent">
      <p class=eyebrow>Vendor Disclosure Report</p>
      <h1>{_esc(title)}</h1>
      <p>{_esc(_clip(summary, 900))}</p>
    </div>
    <div class=panel>
      <table>
        {_kv('Generated', generated)}
        {_kv('Subject', subject)}
        {_kv('Target root', root)}
        {_kv('Prepared for', 'Client / vendor security team')}
        {_kv('Prepared by', 'REF-All security research loop')}
      </table>
    </div>
  </section>

  <section class=stats aria-label="Disclosure summary">
    <div class=stat><span>Confirmed</span><b>{len(valid)}</b></div>
    <div class=stat><span>Candidates reviewed</span><b>{funnel.get('candidates', len(findings))}</b></div>
    <div class=stat><span>Rejected/duplicate</span><b>{len(rejected)}</b></div>
    <div class=stat><span>Plan items done</span><b>{plan.get('done', 0)}</b></div>
  </section>

  <section class=panel>
    <h2>Executive Summary</h2>
    <p>The main body of this report contains only findings marked <b>VALID</b> by the REF-All review and validation loop. Items rejected as false positives or duplicates are retained in a collapsed appendix for transparency. Chainable/deferred primitives are preserved in the internal workbench and are intentionally excluded from this vendor submission package.</p>
    <p>Runtime validation status, reproduction notes, raw output, code anchors, and remediation guidance are included per finding so the report can be submitted as a self-contained disclosure package.</p>
  </section>

  <section class=panel>
    <h2>Scope and Methodology</h2>
    <ul>
      <li>Static reverse engineering reviewed concrete code anchors and sink paths in the target binary/source corpus.</li>
      <li>Adversarial review demoted findings with unreachable inputs, mitigated sinks, duplicate root causes, or insufficient evidence.</li>
      <li>Valid technical primitives without proven standalone exploitability are kept out of this vendor package until a standalone exploit path is proven.</li>
      <li>Runtime validation used loop-provided host actions and PoC scripts where available; raw command output is embedded below when recorded.</li>
      <li>Findings without runtime proof remain out of the submission body until reproduced or demoted.</li>
    </ul>
  </section>

  <section>
    <h2>Confirmed Vulnerabilities ({len(valid)})</h2>
    {valid_html}
  </section>

  <section class=panel>
    <h2>Disclosure Timeline</h2>
    <table>
      {_kv('Report generated', generated)}
      {_kv('Vendor notified', 'Pending submission')}
      {_kv('Vendor acknowledged', 'Pending vendor response')}
      {_kv('Fix available', 'Pending vendor response')}
      {_kv('Public disclosure', 'Coordinate with client/vendor policy')}
    </table>
  </section>

  <section class=panel>
    <h2>Submission Checklist</h2>
    <div class=checklist>
      <div class=check>Confirmed affected target and tested environment are listed.</div>
      <div class=check>Each submitted finding has impact, root cause, and remediation.</div>
      <div class=check>Runtime proof or the current validation status is embedded.</div>
      <div class=check>False positives and duplicates are excluded from the main submission body.</div>
    </div>
  </section>

  <details>
    <summary>False positives / duplicates appendix ({len(rejected)})</summary>
    <ul>{rejected_html}</ul>
  </details>

  <details>
    <summary>Needs research appendix ({len(needs_research)})</summary>
    <ul>{needs_html}</ul>
  </details>
</main>
</body>
</html>"""


def _write_local(subject, doc):
    os.makedirs(REPORT_DIR, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", subject).strip("-") or "subject"
    path = os.path.join(REPORT_DIR, f"{safe}-vendor-disclosure.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return path


def publish(subject, title=None):
    title = title or f"{subject} - Vendor Disclosure Report"
    doc = build(subject, title)
    path = _write_local(subject, doc)
    state = os.path.join(STATE_DIR, f"vendor_disclosure_{subject}_oid.txt")
    oid = open(state).read().strip() if os.path.exists(state) else None
    if oid:
        req = urllib.request.Request(
            f"{WB}/api/workbenches/{SLUG}/objects/{oid}/content",
            data=doc.encode(),
            method="PUT",
            headers={"Content-Type": "text/html"},
        )
        try:
            urllib.request.urlopen(req, timeout=30)
            return {"oid": oid, "url": f"{WB}/wb/{SLUG}/o/{oid}", "path": path}
        except urllib.error.HTTPError:
            oid = None
    body = json.dumps({
        "kind": "html",
        "title": title,
        "mime": "text/html",
        "description": f"Self-contained vendor disclosure report for {subject}.",
        "content": doc,
    }).encode()
    req = urllib.request.Request(
        f"{WB}/api/workbenches/{SLUG}/objects",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    oid = json.loads(urllib.request.urlopen(req, timeout=30).read())["id"]
    with open(state, "w", encoding="utf-8") as fh:
        fh.write(oid)
    return {"oid": oid, "url": f"{WB}/wb/{SLUG}/o/{oid}", "path": path}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("subject")
    ap.add_argument("--title", default=None)
    args = ap.parse_args()
    out = publish(args.subject, args.title)
    print("published:", out["oid"], out["url"])
