#!/usr/bin/env python3
"""REF-All BINARY security-researcher driver — the juicy path for compiled subjects.

Same shape as drive_research.py, but each researcher DECOMPILES functions with radare2
(pdc/pdf) instead of reading source, and traces untrusted input through the binary's
xrefs. Seeded by coverage_service.binary (dangerous imports → per-function investigations).

  # seed first (in container): python3 -m coverage_service.tools.seed_binary example "<binrel>"
  PYTHONPATH=. python3 drive_binresearch.py run --subject example \
      --binrel "bin/target" --claude 2 --codex 1 --units 3
  PYTHONPATH=. python3 drive_binresearch.py status --subject example
  PYTHONPATH=. python3 drive_binresearch.py kill
"""
import os, time, json, threading, argparse

from ref_all_executor.oh_client import OHClient
from ref_all_executor.coverage_client import CoverageClient
from ref_all_executor import config
from ref_all_executor.usage import record_and_delete
from ref_all_executor.wishlist import format_provided_wishlist, provided_wishes_from
from coverage_service.tools.final_visual import publish_final_visual
from drive_characterize import log, kill, _lock, CIDS_FILE, STOP_FILE, PID_FILE

_PROVIDED_WISHES = {}


def _objective(agent_id, subject, binrel, n, provided_wishes=None):
    binpath = f"{config.subject_workspace(subject)}/{binrel}"
    delivered = format_provided_wishlist(subject, provided_wishes)
    return f"""You are a REF-All BINARY SECURITY RESEARCHER (id: {agent_id}). The subject is a compiled binary.
You hunt memory-corruption / injection / auth-bypass vulns by DECOMPILING functions and tracing
attacker-controlled data. Not source — you read radare2 output.
Do up to {n} investigations, then STOP.

Service: http://host.docker.internal:8900     Subject: "{subject}"
Binary:  "{binpath}"
radare2: run `export PATH=$PATH:/usr/local/bin` first, then use `r2`. Keep YOUR context lean.

{delivered}

0. PREFLIGHT:
   - GET http://host.docker.internal:8900/context?subject={subject} (read info_md if present).
   - GET http://host.docker.internal:8900/wishlist?subject={subject}. Treat status=provided items as delivered
     tools/env/access you should use now, and do not re-request them. For example, if r2ghidra is provided,
     prefer `pdg` before falling back to `pdc`/`pdf`. Do not set `dir.plugins=~...`; radare2 does not expand
     that tilde here. Plain `pdg` should load r2ghidra, and if you must set a plugin dir use the absolute
     `/home/openhands/.local/share/radare2/plugins`.
   - Evidence handoff for later validation/reporting loops: follow the REF-All report spec at
     {config.REFALL_WORKSPACE}/docs/superpowers/specs/2026-07-16-refall-report-format-spec.md. You are not writing
     the disclosure now, but every emitted finding should have enough root cause, impact, code anchors, and
     `repro_hints` for a validator to build a canonical payload, runtime proof, visual trace, and vendor-ready
     repro package without guessing.

Repeat up to {n} times:

1. CLAIM: POST /claim_investigation {{"subject":"{subject}","agent":"{agent_id}"}}
   -> {{id,title,kind,target_files,question,priority}}. The question names a function (sym.func.<addr> or a
   name) and the dangerous imports it calls. HTTP 404 => STOP.

2. DECOMPILE that function (substitute <FCN> = the sym.func.<addr> or address from the question).
   Prefer the Ghidra decompiler (clean C pseudocode):
   r2 -q -e scr.color=0 -c "aa; s <FCN>; pdg" "{binpath}"
   If pdg is unavailable/empty, fall back to: r2 -q -c "aa; s <FCN>; pdc" "{binpath}"  (r2 pseudo-C),
   and  r2 -q -c "aa; s <FCN>; pdf" "{binpath}"  (annotated disassembly; resolves strings/calls),
   and  r2 -q -c "aa; s <FCN>; afvd" "{binpath}"  (locals/args).

3. AUDIT for the investigation's kind, grounded in the decompilation:
   - mem-corruption: does an attacker-controlled length/size/offset reach memcpy/memmove/strcpy/sprintf
     WITHOUT a bounds check? Classic overflow. Note the source of the size.
   - ipp-parse / http-parse: how are request tag/length/value fields handled — over-reads, type confusion,
     integer truncation, unbounded copies from the wire.
   - command-exec: does any argument to posix_spawn/system derive from request data? injection.
   - format-string: is the printf-family FORMAT argument attacker-controlled?
   - alloc-size: can an integer overflow/underflow produce an undersized malloc/calloc/realloc?
   Trace where the tainted data enters (function args, globals, recv/httpRead) using the decompilation.

4. BRANCH — trace the data flow through xrefs and enqueue real leads:
   r2 -q -c "aa; axt @ <FCN>" "{binpath}"   (callers — who feeds this function)
   r2 -q -c "aa; s <FCN>; aff; pdf~call" "{binpath}"  (callees). For a concrete lead (a caller that passes
   untrusted request bytes/length into this function), enqueue:
   POST /plan {{"subject":"{subject}","replace":false,"investigations":[{{"title":"[branch] <what>",
     "target_files":["{binrel}"],"kind":"branch","parent_id":"<this id>","priority":<this priority>,
     "question":"Decompile <caller sym.func.addr> and trace how <data> reaches <FCN>."}}]}}.

5. EMIT findings for anything real (0 is fine — do not manufacture):
   POST /finding {{"finding":{{"subject":"{subject}","title":"<vuln in function>","description":"<root cause: what
     tainted data, what sink, why unsafe>","impact":"<RCE / info-leak / DoS>","severity":"CRITICAL|HIGH|MEDIUM|LOW",
     "privileges_required":"NONE","attacker_position":"EXTERNAL","user_interaction":"NONE","vuln_class":"CWE-XXX",
     "code_paths":["{binrel}:<FCN>@<addr>"],"mitigation":"<fix>","investigation_id":"<id>",
     "repro_hints":"<direct repro idea, expected proof target, and raw artifact/payload names if known>",
     "status":"PROVISIONALLY_VALID"}}}}. code_paths REQUIRED (>=1 real function@addr anchor) or HTTP 422.

6. COMPLETE: POST /complete_investigation {{"investigation_id":"<id>","agent":"{agent_id}"}}.
   Blocked on a missing tool/env (need a decompiler feature, a runnable host, a symbol)? POST /wishlist
   {{"subject":"{subject}","item":"<need>","kind":"tool|env|access","reason":"<why>","requested_by":"{agent_id}"}}.
   Do NOT file blind/inference-only findings — ground every claim in the decompilation you read.

Report: investigations audited, findings emitted, branches enqueued, wishlist items."""


def _run_agent(agent_id, subject, binrel, n, results, lane="A", provided_wishes=None):
    if provided_wishes is None:
        provided_wishes = _PROVIDED_WISHES.get(subject, [])
    oh = OHClient()
    try:
        cid = oh.start_conversation(workspace=config.local_workspace(config.subject_workspace(subject)),
            agent_settings=config.LANES[lane], text=_objective(agent_id, subject, binrel, n, provided_wishes),
            max_iterations=max(30, n * 14))
        with _lock:
            open(CIDS_FILE, "a").write(cid + "\n")
        oh.run(cid)
        st = oh.wait_until_done(cid, timeout_s=5400, poll_s=12)
        results[agent_id] = st
        record_and_delete(oh, cid, {"driver": "binresearch", "agent_id": agent_id,
                                    "subject": subject, "lane": lane, "status": st})
    except Exception as e:
        results[agent_id] = f"error:{e}"


def ensure_r2():
    """Verify radare2 is reachable in the container before spending agent tokens."""
    import subprocess
    r = subprocess.run(["docker", "exec", "refall-agent-canvas", "sh", "-lc",
                        "export PATH=$PATH:/usr/local/bin; command -v r2 && r2 -v | head -1"],
                       capture_output=True, text=True, timeout=60)
    ok = "radare2" in (r.stdout or "")
    log(f"ensure_r2: {'OK ' + r.stdout.strip() if ok else 'MISSING radare2 in container'}")
    return ok


def run(subject, binrel, claude, codex, units, max_batches=None, fail_fast=False):
    open(PID_FILE, "w").write(str(os.getpid()))
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
    if not ensure_r2():
        log("radare2 missing — cannot run binary research. Install it in the container first.")
        return
    cov = CoverageClient()
    _PROVIDED_WISHES[subject] = provided_wishes_from(cov, subject)
    pp = cov.plan_progress(subject)
    if pp["total"] == 0:
        log(f"No plan for {subject}. Seed it: python3 -m coverage_service.tools.seed_binary {subject} \"{binrel}\"")
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
            visual = publish_final_visual(subject, f"{subject} — Binary Security Research")
            log(f"FRONTIER EXHAUSTED — {subject} binary research complete. {fs['total']} findings. "
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
                   args=(f"bin-{batch}-{lane}{i}", subject, binrel, units, results, lane))
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
    print(json.dumps({"plan": c.plan_progress(subject), "findings": c.findings_summary(subject)}, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "status", "kill"])
    ap.add_argument("--subject", default="example")
    ap.add_argument("--binrel", default="bin/target")
    ap.add_argument("--claude", type=int, default=2)
    ap.add_argument("--codex", type=int, default=1)
    ap.add_argument("--units", type=int, default=3)
    ap.add_argument("--max-batches", type=int, default=None,
                    help="explicit smoke-test cap; default is unlimited until STOP or frontier exhaustion")
    ap.add_argument("--fail-fast", dest="fail_fast", action="store_true",
                    help="stop the run if any worker returns a non-finished status")
    ap.set_defaults(fail_fast=False)
    a = ap.parse_args()
    if a.cmd == "run":
        run(a.subject, a.binrel, a.claude, a.codex, a.units, a.max_batches, a.fail_fast)
    elif a.cmd == "status":
        research_status(a.subject)
    else:
        kill()
