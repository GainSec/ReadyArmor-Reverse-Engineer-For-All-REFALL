#!/usr/bin/env python3
"""REF-All SECURITY RESEARCHER driver — the 'juicy path'.

Classical security research: claim sensitive-surface investigations (seeded by
coverage_service.seeds), audit each anchor, BRANCH along the code's connections
(callers/callees/data-flow via the toolchain graphs), and emit findings (Mantis
schema) with evidence. The plan frontier grows as researchers branch and shrinks
as they complete — the loop runs until the frontier is exhausted or stopped.

Seed the plan first (inside the container):
  PYTHONPATH=/projects/REFALL-V10 python3 -m coverage_service.tools.seed_subject example /projects/example

Then:
  PYTHONPATH=. python3 drive_research.py run --subject example --claude 3 --codex 1 --units 4
  PYTHONPATH=. python3 drive_research.py status --subject example
  PYTHONPATH=. python3 drive_research.py kill
"""
import os, time, json, threading, argparse

from ref_all_executor.oh_client import OHClient
from ref_all_executor.coverage_client import CoverageClient
from ref_all_executor import config
from ref_all_executor.usage import record_and_delete
from ref_all_executor.wishlist import format_provided_wishlist, provided_wishes_from
from coverage_service.tools.final_visual import publish_final_visual
# reuse the battle-tested scaffolding (data-dir files, logging, L1 bringup, kill)
from drive_characterize import (log, ensure_l1, kill, _lock,
                                CIDS_FILE, STOP_FILE, PID_FILE)

_PROVIDED_WISHES = {}


def _objective(agent_id, subject, n, provided_wishes=None):
    delivered = format_provided_wishlist(subject, provided_wishes)
    subject_ws = config.subject_workspace(subject)
    return f"""You are a REF-All SECURITY RESEARCHER (id: {agent_id}). You hunt REAL vulnerabilities by
claiming sensitive-surface investigations and BRANCHING along the code's connections. This is classical
security research, not summarization. Do up to {n} investigations, then STOP.

Coverage/Plan Service: http://host.docker.internal:8900     Subject: "{subject}"     Source: {subject_ws}
Toolchain (call graphs/scip/metrics): {config.REFALL_WORKSPACE}/toolchain/output/{subject}/   Serena: http://host.docker.internal:20872

{delivered}

0. PREFLIGHT (once, first):
   - GET http://host.docker.internal:8900/context?subject={subject} and read info_md — the project briefing
     (what this subject IS, its auth model, framework primitives, conventions). Ground every judgement in it;
     it is your first defense against false positives.
   - GET http://host.docker.internal:8900/wishlist?subject={subject}. Treat status=provided items as delivered
     tools/env/access you should use now, and do not re-request them.
   - Evidence handoff for later validation/reporting loops: follow the REF-All report spec at
     {config.REFALL_WORKSPACE}/docs/superpowers/specs/2026-07-16-refall-report-format-spec.md. You are not writing
     the disclosure now, but every emitted finding should have enough root cause, impact, code anchors, and
     `repro_hints` for a validator to build a canonical payload, runtime proof, visual trace, and vendor-ready
     repro package without guessing.
   Keep YOUR OWN context lean — externalize everything to the service; do not hold whole large files in memory.

Repeat up to {n} times:

1. CLAIM: POST /claim_investigation {{"subject":"{subject}","agent":"{agent_id}"}}
   -> {{id,title,kind,target_files,question,priority,parent_id}}.  HTTP 404 => STOP (frontier exhausted).

2. READ the anchors: the question cites file:line anchors. For each, run
   sed -n "<start>,<end>p" "{subject_ws}/<file>" reading +/-30 lines of context around each cited line.
   Understand the sink/source/secret/auth precisely. Do not read whole huge files blindly.

3. AUDIT (grounded ONLY in what you read):
   - SINK (exec/deserialize/sql/file/net): can attacker-controlled input reach it WITHOUT sanitization?
     Trace each dangerous argument backwards to its origin.
   - SOURCE (input-source): follow the untrusted data FORWARD — does it reach a dangerous sink unsanitized?
   - secret/auth: hardcoded secrets, weak crypto (MD5/SHA1/DES), predictable randomness, missing or
     bypassable authorization, weak token/signature checks.
   Reviewer discipline — do NOT report: hypothetical misuse of an otherwise-safe API; missing-hygiene /
   defense-in-depth; pedantic linting of standard safe libraries; test/mock-only code UNLESS reachable in
   production. Intrinsic flaws (MD5, hardcoded secrets, direct injection) ARE valid even if never called.
   Verify every file:line you cite actually exists before citing it.

4. BRANCH — grow the frontier (this is what makes it real research):
   - grep the call graphs at {config.REFALL_WORKSPACE}/toolchain/output/{subject}/graphs/*.dot and the scip index
     for the involved symbol names to find callers/callees and imports;
   - GET http://host.docker.internal:8900/search?subject={subject}&q=<symbol> for related coverage units;
     if reachable, use Serena for symbol references.
   For each REAL, code-grounded lead (a caller feeding untrusted input into this sink; a source that reaches
   it; a parser/helper on the path), enqueue a follow-up:
   POST /plan {{"subject":"{subject}","replace":false,"investigations":[{{"title":"[branch] <what>",
     "target_files":["<file>"],"kind":"branch","parent_id":"<this investigation id>","priority":<this priority>,
     "question":"<specific trace instruction>"}}]}}.
   Branch ONLY on concrete leads found in the graphs/code — never invent target files.

5. EMIT findings for anything real (0 is fine — do not manufacture):
   POST /finding {{"finding":{{"subject":"{subject}","title":"<vuln in function>","description":"<root cause>",
     "impact":"<exploit outcome>","severity":"CRITICAL|HIGH|MEDIUM|LOW","privileges_required":"NONE|LOW|HIGH",
     "attacker_position":"EXTERNAL|INTERNAL_NETWORK|LOCAL|...","user_interaction":"NONE|REQUIRED",
     "vuln_class":"CWE-XXX","code_paths":["<file>:<line>", ...],"mitigation":"<fix>",
     "repro_hints":"<direct repro idea, expected proof target, and raw artifact/payload names if known>",
     "investigation_id":"<id>","status":"PROVISIONALLY_VALID"}}}}.
   code_paths REQUIRED (>=1 real file:line anchor) or you get HTTP 422.

6. COMPLETE: POST /complete_investigation {{"investigation_id":"<id>","agent":"{agent_id}"}}.

If you are BLOCKED on a missing tool/environment/dependency/access (e.g. need a decompiler, a running
service, a credential, a sandbox to execute) — do NOT guess or fabricate. Log it:
POST /wishlist {{"subject":"{subject}","item":"<what you need>","kind":"tool|env|dep|access|data",
  "reason":"<why, which investigation>","requested_by":"{agent_id}"}}, then move on to the next investigation.
Do NOT file inference-only / blind findings you cannot ground in the code you read.

When done, report: investigations audited, findings emitted, branches enqueued, wishlist items logged."""


def _run_agent(agent_id, subject, n, results, lane="A", provided_wishes=None):
    if provided_wishes is None:
        provided_wishes = _PROVIDED_WISHES.get(subject, [])
    oh = OHClient()
    try:
        cid = oh.start_conversation(workspace=config.local_workspace(config.subject_workspace(subject)),
            agent_settings=config.LANES[lane], text=_objective(agent_id, subject, n, provided_wishes),
            max_iterations=max(30, n * 12))
        with _lock:
            open(CIDS_FILE, "a").write(cid + "\n")
        oh.run(cid)
        st = oh.wait_until_done(cid, timeout_s=5400, poll_s=12)
        results[agent_id] = st
        record_and_delete(oh, cid, {"driver": "research", "agent_id": agent_id,
                                    "subject": subject, "lane": lane, "status": st})
    except Exception as e:
        results[agent_id] = f"error:{e}"


def run(subject, claude, codex, units, max_batches=None, fail_fast=False):
    open(PID_FILE, "w").write(str(os.getpid()))
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
    ensure_l1(subject)  # graphs/scip/serena — the substrate researchers branch through
    cov = CoverageClient()
    _PROVIDED_WISHES[subject] = provided_wishes_from(cov, subject)
    pp = cov.plan_progress(subject)
    if pp["total"] == 0:
        log(f"No plan for {subject}. Seed it first: "
            f"python3 -m coverage_service.tools.seed_subject {subject} {config.subject_workspace(subject)}")
        return
    batch = 0
    while True:
        if os.path.exists(STOP_FILE):
            log("STOP requested — exiting."); break
        pp = cov.plan_progress(subject)
        fs = cov.findings_summary(subject)
        log(f"batch {batch}: plan open={pp['open']} claimed={pp['claimed']} done={pp['done']}/{pp['total']} "
            f"| findings={fs['total']} {json.dumps(fs['by_severity'])}")
        if pp["open"] == 0 and pp["claimed"] == 0:
            visual = publish_final_visual(subject, f"{subject} — Security Research")
            log(f"FRONTIER EXHAUSTED — {subject} research complete. {fs['total']} findings. "
                f"Final visual: {visual['url']}"); break
        if pp["open"] == 0 and pp["claimed"] > 0:
            log(f"waiting for {pp['claimed']} claimed investigations to finish before launching more agents.")
            time.sleep(60)
            continue
        if max_batches is not None and max_batches > 0 and batch >= max_batches:
            log(f"max_batches={max_batches} reached — stopping "
                f"(open={pp['open']} claimed={pp['claimed']})."); break
        open(CIDS_FILE, "w").close()
        results = {}
        specs = [("A", i) for i in range(claude)] + [("B", i) for i in range(codex)]
        threads = [threading.Thread(target=_run_agent,
                   args=(f"res-{batch}-{lane}{i}", subject, units, results, lane))
                   for (lane, i) in specs]
        for t in threads: t.start()
        for t in threads: t.join()
        log(f"batch {batch} agents: {results}")
        errored = [a for a, s in results.items() if str(s) != "finished"]
        if fail_fast and errored:
            log(f"FAIL-FAST: agents errored {errored} -> stopping run.")
            open(STOP_FILE, "w").close(); break
        batch += 1
        time.sleep(1)


def research_status(subject):
    c = CoverageClient()
    print(json.dumps({"plan": c.plan_progress(subject),
                      "findings": c.findings_summary(subject)}, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "status", "kill"])
    ap.add_argument("--subject", default="example")
    ap.add_argument("--claude", type=int, default=3, help="parallel Claude (Lane A) researchers per batch")
    ap.add_argument("--codex", type=int, default=1, help="parallel Codex (Lane B) researchers per batch (keep low)")
    ap.add_argument("--units", type=int, default=4, help="investigations each researcher does per batch")
    ap.add_argument("--max-batches", type=int, default=None,
                    help="explicit smoke-test cap; default is unlimited until STOP or frontier exhaustion")
    ap.add_argument("--fail-fast", dest="fail_fast", action="store_true",
                    help="stop the run if any worker returns a non-finished status")
    ap.set_defaults(fail_fast=False)
    a = ap.parse_args()
    if a.cmd == "run":
        run(a.subject, a.claude, a.codex, a.units, a.max_batches, a.fail_fast)
    elif a.cmd == "status":
        research_status(a.subject)
    else:
        kill()
