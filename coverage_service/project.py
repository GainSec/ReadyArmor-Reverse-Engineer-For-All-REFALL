"""Project the Coverage Service knowledge base into other toolchain layers.

Layer 1 (now): a LIVE operator report on the ref-all workbench, generated from the coverage DB,
so the expensive characterization understanding shows up for the operator — not siloed in :8900.
Updates the SAME workbench object in place (mime text/html per the report spec).
"""
import json
import html
import os
import urllib.request
import urllib.error

WB = os.environ.get("REFALL_WORKBENCH_BASE", "http://127.0.0.1:7673")
SLUG = os.environ.get("REFALL_WORKBENCH_SLUG", "ref-all")
COV = os.environ.get("COVERAGE_BASE", "http://localhost:8900")


def _state_path(subject):
    name = f"coverage_report_{subject}_oid.txt"
    return os.path.join(os.path.dirname(__file__), "data", name)


def _get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def _h(value):
    return html.escape(str(value or ""), quote=True)


def _finding_rows(findings):
    rows = []
    for f in findings[:20]:
        desc = (f.get("description") or "").strip()
        if len(desc) > 220:
            desc = desc[:220] + "..."
        rows.append(
            "<tr>"
            f"<td><span class=sev>{_h(f.get('severity') or '')}</span><br><span class=mono>{_h(f.get('status') or '')}</span></td>"
            f"<td>{_h(f.get('title') or '')}<br><span class=mono>{_h(f.get('id') or '')}</span></td>"
            f"<td>{_h(desc)}</td>"
            "</tr>"
        )
    return "".join(rows) or "<tr><td colspan=3 class=mono>none recorded yet</td></tr>"


def build_report(subject):
    cov = _get(f"{COV}/coverage?subject={subject}")
    gate = _get(f"{COV}/gate?subject={subject}")
    findings_summary = _get(f"{COV}/findings_summary?subject={subject}")
    findings = _get(f"{COV}/findings?subject={subject}")
    # highest-value characterized units: anything flagged sensitive
    sensitive = []
    for s in ("auth", "crypto", "secret", "exec", "net", "data-change"):
        sensitive += _get(f"{COV}/search?subject={subject}&state=characterized&sensitivity={s}")
    sensitive = sensitive[:40]
    dead = _get(f"{COV}/search?subject={subject}&state=dead")
    lock = "LOCKED" if gate["locked"] else "OPEN"
    gate_bg = "var(--wb-accent,#e51b2d)" if gate["locked"] else "var(--wb-accent-2,#6ee85a)"
    frows = _finding_rows(findings)
    sev_summary = ", ".join(
        f"{_h(k)}:{_h(v)}" for k, v in sorted((findings_summary.get("by_severity") or {}).items())
    ) or "none"
    srows = "".join(
        f"<tr><td><span class=sev>{(u.get('sensitivity') or '')}</span></td>"
        f"<td class=mono>{(u.get('path') or '')}:{u.get('line_start') or ''}</td>"
        f"<td>{u.get('name') or ''}</td><td>{(u.get('summary') or '')[:80]}</td></tr>"
        for u in sensitive) or "<tr><td colspan=4 class=mono>none characterized yet</td></tr>"
    title = f"{subject} — Coverage (live)"
    return f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>{title}</title><style>
:root{{--bg:var(--wb-bg,#0d1020);--surf:var(--wb-surface,#171b31);--ink:var(--wb-ink,#f4f7ff);
--mut:var(--wb-muted,#9aa6c7);--acc:var(--wb-accent,#e51b2d);--acc2:var(--wb-accent-2,#6ee85a);--rule:var(--wb-rule,#2b3156)}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Trebuchet MS,Verdana,sans-serif;padding:18px;max-width:1100px;margin:auto}}
.mono{{font-family:JetBrains Mono,Menlo,monospace;font-size:12px;color:var(--mut);word-break:break-all}}
h1{{color:var(--acc);margin:.1em 0}} .sub{{color:var(--mut)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0}}
@media(max-width:700px){{.grid{{grid-template-columns:1fr 1fr}}}}
.card{{background:var(--surf);border:1px solid var(--rule);border-left:3px solid var(--acc2);border-radius:8px;padding:14px}}
.big{{font-size:30px;color:var(--acc2);font-weight:700}} .lab{{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.05em}}
.bar{{height:10px;background:var(--rule);border-radius:6px;overflow:hidden;margin-top:8px}}.bar>i{{display:block;height:100%;background:var(--acc2)}}
.gate{{display:inline-block;padding:4px 10px;border-radius:6px;background:{gate_bg};color:#000;font-weight:700}}
.tablewrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse}}td{{border-bottom:1px solid var(--rule);padding:6px;font-size:13px;text-align:left;vertical-align:top}}
.sev{{font-family:JetBrains Mono,monospace;font-size:11px;color:var(--acc)}}
</style></head><body>
<h1>{subject} &mdash; Coverage (live)</h1>
<p class=sub>Enumeration/discovery pass &middot; security phase <span class=gate>{lock}</span> &middot; resolved {cov['resolved_pct']}% (gate {gate['threshold']}%)
&middot; live source: <span class=mono>{_h(COV)}</span></p>
<div class=grid>
<div class=card><div class=lab>Characterized</div><div class=big>{cov['characterized_pct']}%</div><div class=bar><i style="width:{cov['characterized_pct']}%"></i></div></div>
<div class=card><div class=lab>Lines understood</div><div class=big>{cov['lines_covered']}</div><div class=mono>/ {cov['lines_total']}</div></div>
<div class=card><div class=lab>Files done</div><div class=big>{cov['files_done']}</div><div class=mono>/ {cov['files_total']}</div></div>
<div class=card><div class=lab>Symbols</div><div class=big>{cov['symbols_total']}</div></div>
<div class=card><div class=lab>Dead lines</div><div class=big>{cov['lines_dead']}</div><div class=mono>{len(dead)} units</div></div>
<div class=card><div class=lab>Findings</div><div class=big>{findings_summary['total']}</div><div class=mono>{sev_summary}</div></div>
</div>
<h3>Recent findings ({min(len(findings), 20)} of {findings_summary['total']})</h3>
<div class=tablewrap><table><tr><td>severity/status</td><td>finding</td><td>evidence summary</td></tr>{frows}</table></div>
<h3>Sensitive units surfaced ({len(sensitive)})</h3>
<div class=tablewrap><table><tr><td>sens</td><td>anchor</td><td>name</td><td>what it does</td></tr>{srows}</table></div>
<p class=sub style="margin-top:16px">This report is projected live from the coverage knowledge base as agents characterize {subject}. Understanding is stored evidence-anchored and re-projectable into other toolchain layers.</p>
</body></html>"""


def publish(subject):
    html = build_report(subject)
    state = _state_path(subject)
    oid = open(state).read().strip() if os.path.exists(state) else None
    if oid:
        req = urllib.request.Request(f"{WB}/api/workbenches/{SLUG}/objects/{oid}/content",
                                     data=html.encode(), method="PUT", headers={"Content-Type": "text/html"})
        try:
            urllib.request.urlopen(req, timeout=30)
            return oid
        except urllib.error.HTTPError:
            oid = None  # object gone -> recreate
    title = f"{subject} — Coverage (live)"
    body = json.dumps({"kind": "html", "title": title, "mime": "text/html",
                       "description": f"Live operator view of the {subject} discovery pass, projected from the coverage knowledge base.",
                       "content": html}).encode()
    req = urllib.request.Request(f"{WB}/api/workbenches/{SLUG}/objects", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    oid = json.loads(urllib.request.urlopen(req, timeout=30).read())["id"]
    open(state, "w").write(oid)
    return oid


if __name__ == "__main__":
    import sys
    subj = sys.argv[1] if len(sys.argv) > 1 else "example"
    print("published/updated:", publish(subj))
