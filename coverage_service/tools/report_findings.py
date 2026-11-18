"""Publish a polished, evidence-anchored findings report for a subject to the workbench.

  PYTHONPATH=. python3 -m coverage_service.tools.report_findings example \
      --title "Example Subject - Security Research"
"""
import argparse
import html
import json
import os
import urllib.request
import urllib.error

WB = os.environ.get("REFALL_WORKBENCH_BASE", "http://127.0.0.1:7673")
SLUG = os.environ.get("REFALL_WORKBENCH_SLUG", "ref-all")
COV = os.environ.get("COVERAGE_BASE", "http://localhost:8900")
STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def _get(path):
    with urllib.request.urlopen(COV + path, timeout=30) as r:
        return json.loads(r.read())


def _clip(text, limit):
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + "..."


def _first_sentence(text, fallback="", limit=220):
    text = (text or fallback or "").strip()
    if not text:
        return fallback
    for marker in (". ", ".\n"):
        idx = text.find(marker)
        if 0 < idx < limit:
            return text[:idx + 1]
    return _clip(text, limit)


def _repro_sentence(repro_hints, prefix):
    for part in (repro_hints or "").replace("\n", " ").split(". "):
        if part.strip().lower().startswith(prefix.lower()):
            return part.strip().rstrip(".") + "."
    return ""


def _runtime_viability(f):
    if f.get("production_viability"):
        return _clip(f.get("production_viability"), 420)

    repro = f.get("repro_hints") or ""
    dynamic = _repro_sentence(repro, "Dynamic repro")
    expected = _repro_sentence(repro, "Expected dynamic proof")
    status = f.get("repro_status") or "not_attempted"
    if dynamic:
        return _clip(f"Runtime validation is directly actionable. {dynamic}", 420)
    if expected:
        return _clip(f"Runtime validation is viable but not yet executed. {expected}", 420)
    if status == "evidence_anchored":
        return "Runtime validation still needs execution; the static code anchors and reviewer note are sufficient to define the next dynamic proof step."
    return "Runtime validation has not been attempted yet; use the trace, code anchor, and repro/proof note above as the starting point."


def _attacker_input(f):
    repro = f.get("repro_hints") or ""
    dynamic = _repro_sentence(repro, "Dynamic repro")
    if dynamic:
        return _clip(dynamic, 180)
    plan = _repro_sentence(repro, "Evidence-anchored repro plan")
    if plan:
        return _clip(plan, 180)
    return _clip(
        f"{f.get('attacker_position') or 'Attacker'} input reaches the component with privileges "
        f"{f.get('privileges_required') or '?'}.",
        180,
    )


def _trace_steps(f):
    paths = f.get("code_paths") or []
    anchors = " -> ".join(paths[:3]) if paths else "no code path recorded"
    if len(paths) > 3:
        anchors += f" -> +{len(paths) - 3} more anchors"
    static = _repro_sentence(f.get("repro_hints") or "", "Static proof")
    expected = _repro_sentence(f.get("repro_hints") or "", "Expected dynamic proof")
    steps = [
        ("Attacker input", _attacker_input(f)),
        ("Source to sink", _first_sentence(f.get("description"), "Root cause not recorded.")),
        ("Code anchor", anchors),
        ("Review gate", _first_sentence(f.get("reasoning"), "Reviewer rationale not recorded.")),
    ]
    if static:
        steps.append(("Static proof", _clip(static, 220)))
    if expected:
        steps.append(("Runtime proof target", _clip(expected, 220)))
    return steps


def _trace_html(f):
    parts = []
    for idx, (label, body) in enumerate(_trace_steps(f), start=1):
        parts.append(
            f"<div class=trace-step><div class=trace-num>{idx}</div>"
            f"<div><div class=trace-label>{html.escape(label)}</div>"
            f"<div class=trace-body>{html.escape(body)}</div></div></div>"
        )
    return "".join(parts)


def _poc_pack_html(subject):
    state = os.path.join(STATE_DIR, f"{subject}_poc_oid.txt")
    if not os.path.exists(state):
        return ""
    oid = open(state).read().strip()
    if not oid:
        return ""
    url = f"{WB}/wb/{SLUG}/o/{oid}"
    return (
        f"<div class=lede><b>PoC pack.</b> Deterministic runtime-validation scripts for retained "
        f"{html.escape(subject)} findings are published here: "
        f"<a href=\"{html.escape(url)}\">{html.escape(url)}</a></div>"
    )


def _card(f):
    sev = f.get("severity") or "?"
    anchor = (f.get("code_paths") or ["?"])[0]
    artifact = f.get("critic_reasoning")
    artifact_html = (
        f"  <div class=sec><b>Validation artifact.</b> {html.escape(_clip(artifact, 700))}</div>\n"
        if artifact else ""
    )
    return f"""<div class="f sev-{sev}">
  <div class=fh><span class="sev {sev}">{sev}</span><span class=ti>{html.escape(f.get('title') or '')}</span>
    <span class=cwe>{html.escape(f.get('vuln_class') or '')}</span></div>
  <div class=meta><span class=mono>{html.escape(anchor)}</span> &middot; {html.escape(f.get('attacker_position') or '')} &middot;
    priv:{html.escape(f.get('privileges_required') or '?')}</div>
  <div class=sec><b>Root cause.</b> {html.escape((f.get('description') or '')[:600])}</div>
  <div class=sec><b>Impact.</b> {html.escape((f.get('impact') or '')[:300])}</div>
  <div class=sec rev><b>Adversarial review.</b> {html.escape((f.get('reasoning') or '')[:600])}</div>
  <div class=sec><b>Repro / proof.</b> {html.escape((f.get('repro_hints') or 'Static evidence only so far; use the code path and review note above as the proof anchor.')[:600])}</div>
  <div class=sec><b>End-to-end trace.</b></div>
  <div class=trace>{_trace_html(f)}</div>
  <div class=sec><b>Runtime validation viability.</b> {html.escape(_runtime_viability(f))}</div>
{artifact_html.rstrip()}
  <div class=sec><b>Fix.</b> {html.escape((f.get('mitigation') or '')[:300])}</div>
</div>"""


def build(subject, title):
    findings = _get(f"/findings?subject={subject}")
    funnel = _get(f"/funnel?subject={subject}")
    plan = _get(f"/plan_progress?subject={subject}")
    valid = sorted([f for f in findings if f["status"] == "VALID"], key=lambda f: SEV_ORDER.get(f.get("severity"), 9))
    rejected = [f for f in findings if f["status"] in ("FALSE_POSITIVE", "DUPLICATE")]
    chainable = [f for f in findings if f["status"] == "CHAINABLE_DEFERRED"]
    nr = [f for f in findings if f["status"] == "NEEDS_RESEARCH"]
    poc_html = _poc_pack_html(subject)
    valid_html = "".join(_card(f) for f in valid) or "<p class=empty>None validated.</p>"
    rejected_html = "".join(
        f"<li><span class='sev {f.get('severity')}'>{f.get('severity')}</span> "
        f"<span class=mono>{html.escape(f.get('status') or '')}</span> {html.escape(f.get('title') or '')}"
        f"<br><span class=mono>{html.escape((f.get('reasoning') or '')[:260])}</span></li>" for f in rejected)
    nr_html = "".join(
        f"<li>{html.escape(f.get('title') or '')} &mdash; <span class=mono>{html.escape((f.get('reasoning') or '')[:220])}</span></li>"
        for f in nr)
    chainable_html = "".join(
        f"<li><span class='sev {f.get('severity')}'>{f.get('severity')}</span> "
        f"<span class=mono>{html.escape(f.get('status') or '')}</span> {html.escape(f.get('title') or '')}"
        f"<br><span class=mono>{html.escape((f.get('reasoning') or '')[:260])}</span>"
        f"{('<br><span class=mono>' + html.escape((f.get('repro_hints') or '')[:260]) + '</span>') if f.get('repro_hints') else ''}</li>"
        for f in chainable)
    rej = int(round((funnel.get("rejection_rate") or 0) * 100))
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>
:root{{--bg:var(--wb-bg,#0d1020);--surf:var(--wb-surface,#171b31);--surf2:var(--wb-surface-2,#1e2440);
--ink:var(--wb-ink,#f4f7ff);--mut:var(--wb-muted,#9aa6c7);--acc:var(--wb-accent,#e51b2d);--acc2:var(--wb-accent-2,#6ee85a);
--rule:var(--wb-rule,#2b3156);--crit:#ff4d5e;--high:#ff9f40;--med:#ffce54;--low:#7a83a6}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14.5px/1.55 "Trebuchet MS",Verdana,sans-serif;padding:20px;max-width:1080px;margin:auto}}
h1{{color:var(--acc);margin:.1em 0;font-size:25px}}h2{{font-size:18px;border-bottom:1px solid var(--rule);padding-bottom:6px;margin:1.5em 0 .6em}}
.sub{{color:var(--mut)}}.mono{{font-family:"JetBrains Mono",Menlo,monospace;font-size:11.5px;color:var(--mut);word-break:break-all}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin:14px 0}}
.card{{background:var(--surf);border:1px solid var(--rule);border-left:3px solid var(--acc2);border-radius:8px;padding:11px}}
.card .big{{font-size:26px;color:var(--acc2);font-weight:700}}.card .lab{{color:var(--mut);font-size:10px;text-transform:uppercase;letter-spacing:.05em}}
.f{{background:var(--surf);border:1px solid var(--rule);border-radius:9px;padding:13px;margin:11px 0;border-left:4px solid var(--low)}}
.f.sev-CRITICAL{{border-left-color:var(--crit)}}.f.sev-HIGH{{border-left-color:var(--high)}}.f.sev-MEDIUM{{border-left-color:var(--med)}}
.fh{{display:flex;align-items:center;gap:9px;flex-wrap:wrap}}.ti{{font-weight:700;font-size:15px}}
.cwe{{margin-left:auto;font-family:"JetBrains Mono",monospace;font-size:11px;color:var(--mut)}}
.sev{{font-family:"JetBrains Mono",monospace;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;color:#0a0d18}}
.sev.CRITICAL{{background:var(--crit)}}.sev.HIGH{{background:var(--high)}}.sev.MEDIUM{{background:var(--med)}}.sev.LOW{{background:var(--low);color:#dfe4f5}}
.meta{{margin:6px 0 8px}}.sec{{font-size:13.5px;margin:5px 0}}.sec b{{color:var(--acc2)}}.sec.rev{{color:var(--mut)}}.sec.rev b{{color:var(--ink)}}
.trace{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:7px;margin:8px 0 10px}}
.trace-step{{display:grid;grid-template-columns:24px 1fr;gap:8px;align-items:start;background:var(--surf2);border:1px solid var(--rule);border-radius:7px;padding:8px;min-height:78px}}
.trace-num{{width:22px;height:22px;border-radius:50%;display:grid;place-items:center;background:var(--acc2);color:#0a0d18;font:bold 11px "JetBrains Mono",monospace}}
.trace-label{{font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--acc2);font-weight:700}}
.trace-body{{font-size:11.5px;color:var(--ink);overflow-wrap:anywhere}}
details{{background:var(--surf);border:1px solid var(--rule);border-radius:9px;margin:10px 0;padding:2px 14px}}
summary{{cursor:pointer;font-weight:700;padding:10px 0;color:var(--ink)}}
li{{margin:8px 0}}.empty{{color:var(--mut)}}.lede{{background:var(--surf);border:1px solid var(--rule);border-left:3px solid var(--acc2);border-radius:9px;padding:13px 15px;margin:12px 0}}
.lede b{{color:var(--acc2)}}
</style></head><body>
<h1>{html.escape(title)}</h1>
<p class=sub>Security research + adversarial review &middot; live from the Coverage Service</p>
<div class=lede><b>Honest bottom line.</b> {len(findings)} candidate findings from the RE loop &rarr;
<b>{len(valid)} VALID</b> after an independent adversarial review applied the false-positive constraints.
<b>{rej}% were rejected</b> (mitigated sinks, unreachable inputs, in-buffer copies, hallucinated anchors).
The survivors below are evidence-anchored to concrete code paths.</div>
{poc_html}
<div class=grid>
	<div class=card><div class=lab>Candidates</div><div class=big>{funnel.get('candidates',0)}</div></div>
	<div class=card><div class=lab>Valid</div><div class=big>{funnel.get('valid',0)}</div></div>
	<div class=card><div class=lab>Rejected</div><div class=big>{len(rejected)}</div></div>
	<div class=card><div class=lab>Needs research</div><div class=big>{funnel.get('needs_research',0)}</div></div>
	<div class=card><div class=lab>Rejection rate</div><div class=big>{rej}%</div></div>
	<div class=card><div class=lab>Functions audited</div><div class=big>{plan.get('done',0)}</div></div>
</div>
<h2>Validated findings ({len(valid)})</h2>
{valid_html}
<h2>Needs research ({len(nr)})</h2>
<ul>{nr_html or '<li class=empty>none</li>'}</ul>
	<details><summary>Chainable / deferred findings ({len(chainable)}) — real primitives without standalone exploit proof</summary>
	<ul>{chainable_html or '<li class=empty>none</li>'}</ul></details>
	<details><summary>Rejected as false positives / duplicates ({len(rejected)}) — shown for transparency</summary>
	<ul>{rejected_html or '<li class=empty>none</li>'}</ul></details>
<p class=sub style="margin-top:18px">Every finding was recorded with concrete evidence and adjudicated by an independent
reviewer pass. VALID = a real, reachable, triggerable flaw grounded in the reviewed code.</p>
</body></html>"""


def publish(subject, title):
    doc = build(subject, title)
    state = os.path.join(STATE_DIR, f"report_{subject}_oid.txt")
    oid = open(state).read().strip() if os.path.exists(state) else None
    if oid:
        req = urllib.request.Request(f"{WB}/api/workbenches/{SLUG}/objects/{oid}/content",
                                     data=doc.encode(), method="PUT", headers={"Content-Type": "text/html"})
        try:
            urllib.request.urlopen(req, timeout=30)
            return oid
        except urllib.error.HTTPError:
            oid = None
    body = json.dumps({"kind": "html", "title": title, "mime": "text/html",
                       "description": f"Validated security findings for {subject}, with the adversarial-review funnel.",
                       "content": doc}).encode()
    req = urllib.request.Request(f"{WB}/api/workbenches/{SLUG}/objects", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    oid = json.loads(urllib.request.urlopen(req, timeout=30).read())["id"]
    open(state, "w").write(oid)
    return oid


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("subject")
    ap.add_argument("--title", default=None)
    a = ap.parse_args()
    title = a.title or f"{a.subject} — Binary Security Research"
    oid = publish(a.subject, title)
    print("published:", oid, f"{WB}/wb/{SLUG}/o/{oid}")
