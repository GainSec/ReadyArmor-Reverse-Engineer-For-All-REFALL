#!/usr/bin/env python3
"""REF-All binary validation/visualization driver.

After adversarial review, every non-rejected retained finding needs a concrete trace artifact
and runtime proof. This driver shards VALID / NEEDS_RESEARCH findings that are not yet
runtime-confirmed across Claude/Codex agents, so inconclusive PoCs stay in the loop until
they reproduce or are rejected with evidence.

  PYTHONPATH=. python3 drive_binvalidate.py --subject example \
      --binrel "bin/target" --claude 2 --codex 2
"""
import argparse
import json
import os
import threading
import time

from ref_all_executor.oh_client import OHClient
from ref_all_executor.coverage_client import CoverageClient
from ref_all_executor import config
from ref_all_executor.usage import record_and_delete
from ref_all_executor.wishlist import format_provided_wishlist, provided_wishes_from
from coverage_service.tools.final_visual import publish_final_visual
from coverage_service.tools.vendor_disclosure import publish as publish_vendor_disclosure
from drive_characterize import log, _lock, CIDS_FILE, STOP_FILE, PID_FILE

_PROVIDED_WISHES = {}


NON_REJECTED = {"VALID", "NEEDS_RESEARCH"}
RUNTIME_COMPLETE = {"runtime_confirmed", "reproduced"}


def needs_validation(finding):
    if finding.get("status") not in NON_REJECTED:
        return False
    repro_status = (finding.get("repro_status") or "").strip().lower()
    return repro_status not in RUNTIME_COMPLETE


def _objective(agent_id, subject, binrel, finding_ids, provided_wishes=None):
    binpath = f"{config.subject_workspace(subject)}/{binrel}"
    ids = ", ".join(finding_ids)
    delivered = format_provided_wishlist(subject, provided_wishes)
    return f"""You are a REF-All BINARY VALIDATION + VISUALIZATION AGENT (id: {agent_id}).
Your job is not to find new bugs. Your job is to take retained non-rejected findings and make each one
operationally useful: complete trace visualization, reproducibility notes, raw evidence/proof, and runtime
validation viability.

Subject: "{subject}"
Binary: "{binpath}"
Service: http://host.docker.internal:8900
Finding IDs assigned to you: {ids}

{delivered}

Reporting/evidence contract:
- Follow the reusable REF-All report spec at
  {config.REFALL_WORKSPACE}/docs/superpowers/specs/2026-07-16-refall-report-format-spec.md before calling
  any finding validated, submission-ready, or closed out.
- Each retained finding needs one canonical payload/request, one direct repro command or script, raw
  request/payload files, raw stdout/stderr or response bytes, and a compact attacker-input-to-impact trace.
  If you change the payload, regenerate the artifacts and remove or explicitly demote stale alternatives.
- Visual proof must prove the claim. For browser/script injection, marker text only proves reflection;
  capture a real browser-observed JavaScript effect such as an alert/dialog event, DOM mutation from the
  handler, screenshot/video, or DevTools event log before claiming script execution/XSS. For crashes,
  attach crash logs and the crashing frame/signal when available. For resource exhaustion, include
  before/after memory or CPU measurements and expected timeout behavior.
- Vendor repro must be direct and archive-relative. Do not rely on workbench links, host.docker.internal,
  /Users/... paths, /projects/... paths, or Coverage Service endpoints as the primary repro. Harness output
  is useful supporting evidence, but the final README must tell the vendor how to run the included script.
- False positives and duplicates should be demoted with evidence and kept out of the main finding flow;
  if surfaced in a report, they belong at the bottom in a collapsed appendix.
- Use CHAINABLE_DEFERRED for a real technical primitive but no proven standalone exploitability. Examples:
  browser/script injection that is only same-user self-XSS without a non-self planting path, local-only sinks that
  need CSRF/local-request proof, or primitives that matter only when combined with a separate exposure/auth bypass.
  These are preserved for future chain analysis but are not vendor/client submission-ready by themselves.

Important constraints:
- First discover loop capabilities:
  GET http://host.docker.internal:8900/loop/capabilities?subject={subject}
  Route: GET /loop/capabilities
  Use returned host_actions before claiming runtime execution is blocked. The base install does not
  ship target-specific host actions; add them in the target module when a subject needs a host-side
  runner, debugger, device controller, or emulator harness.
- Do not repost NOT_PROVEN as a no-op. If a finding is already NOT_PROVEN, your pass must either
  create or improve a PoC/script and run it through available host_actions, demote it with
  /review_finding when static/runtime evidence disproves reachability, or record a concrete
  missing host primitive with the exact endpoint/script needed.
- You may use r2/r2ghidra for static confirmation. Run `export PATH=$PATH:/usr/local/bin` first.
  Prefer `pdg`, then fall back to `pdc`/`pdf`. Do not set `dir.plugins=~...`.
- Do not mark a finding false positive unless runtime/static validation disproves it. If a PoC is merely
  inconclusive, keep it non-rejected and record the exact blocker/output so the next loop can continue.
- Demote transport-unreachable findings. If repeated host_action payloads across advertised document
  formats reject before the cited parser/sink, no printer queue advertises the needed document format,
  and debug_capability says debugger proof is unavailable, POST /review_finding with FALSE_POSITIVE.
  Explain that the static primitive exists but the exposed IPP production surface cannot reach it, and
  include raw rejection outputs/artifact paths.
- If a NEEDS_RESEARCH finding is resolved, POST /review_finding with VALID or FALSE_POSITIVE and explain why.
  If the root cause is real but only chainable, POST /review_finding with CHAINABLE_DEFERRED and explain the
  missing primitive needed to promote it.

For EACH assigned finding:
1. GET /finding/<id>. Read title, status, code_paths, reasoning, repro_hints, and existing fields.
2. Re-open the cited code anchors with radare2:
   r2 -q -e scr.color=0 -c "aa; s <sym_or_addr>; pdg" "{binpath}"
   r2 -q -e scr.color=0 -c "aa; s <sym_or_addr>; pdf" "{binpath}"
3. Build a compact visualization artifact in text:
   Visual trace: attacker input -> parser/state field -> arithmetic/copy/HTML sink -> impact.
   Static evidence: exact instruction/function addresses and the data/control-flow fact they prove.
   Runtime validation: run or improve the PoC where possible; otherwise give the exact macOS command needed.
   Repro script/commands: concrete commands or a short script outline. Include raw output if you ran anything.
4. POST /finding_validation:
   {{
     "finding_id":"<id>",
     "agent":"{agent_id}",
     "production_viability":"<runtime viability verdict in 2-4 concrete sentences>",
     "repro_status":"runtime_confirmed|NOT_PROVEN|runtime_blocked|static_only",
     "repro_hints":"<updated repro steps, including commands/script and expected proof>",
     "critic_reasoning":"<the visualization artifact: visual trace, static evidence, runtime validation, raw output>",
     "patch_status":"unpatched"
   }}
   Use repro_status=runtime_confirmed only when there is runtime evidence such as a crash, sanitizer/lldb
   proof, or observable exploit effect. Use NOT_PROVEN/runtime_blocked for rejected payloads or missing
   execution surface; those findings will remain in the loop. If evidence disproves exploitability, POST
   /review_finding with FALSE_POSITIVE instead. If evidence supports the sink but disproves standalone
   exploitability, POST /review_finding with CHAINABLE_DEFERRED instead.

Report finding ids updated and any blocker/wishlist item. Keep it precise and stop when your assigned ids are done."""


def _run_agent(agent_id, subject, binrel, finding_ids, results, lane="A", provided_wishes=None):
    if provided_wishes is None:
        provided_wishes = _PROVIDED_WISHES.get(subject, [])
    if not finding_ids:
        results[agent_id] = "finished"
        return
    oh = OHClient()
    try:
        log(f"{agent_id}: starting validation conversation for {len(finding_ids)} finding(s) on lane {lane}")
        cid = oh.start_conversation(
            workspace=config.local_workspace(config.subject_workspace(subject)),
            agent_settings=config.LANES[lane],
            text=_objective(agent_id, subject, binrel, finding_ids, provided_wishes),
            max_iterations=max(40, len(finding_ids) * 16),
        )
        log(f"{agent_id}: conversation {cid} started")
        with _lock:
            open(CIDS_FILE, "a").write(cid + "\n")
        oh.run(cid)
        st = oh.wait_until_done(cid, timeout_s=5400, poll_s=12)
        results[agent_id] = st
        record_and_delete(oh, cid, {"driver": "binvalidate", "agent_id": agent_id,
                                    "subject": subject, "lane": lane, "status": st,
                                    "finding_count": len(finding_ids)})
    except Exception as e:
        results[agent_id] = f"error:{e}"


def run(subject, binrel, claude=2, codex=2, publish=True, max_concurrent=2):
    open(PID_FILE, "w").write(str(os.getpid()))
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
    cov = CoverageClient()
    _PROVIDED_WISHES[subject] = provided_wishes_from(cov, subject)
    pending = [f["id"] for f in cov.findings(subject) if needs_validation(f)]
    if not pending:
        log(f"No non-rejected findings need validation/visualization for {subject}.")
        visual = publish_final_visual(subject, f"{subject} — Binary Security Research") if publish else None
        vendor_report = publish_vendor_disclosure(subject, f"{subject} — Vendor Disclosure Report") if publish else None
        if visual:
            log(f"Final visual: {visual['url']}")
        if vendor_report:
            log(f"Vendor disclosure: {vendor_report['url']}")
        return {"validators": {}, "pending": 0, "visual": visual, "vendor_report": vendor_report}

    log(
        f"validating/visualizing {len(pending)} retained findings with "
        f"{claude} Claude + {codex} Codex agents (max {max_concurrent} active)"
    )
    specs = [("A", i) for i in range(claude)] + [("B", i) for i in range(codex)]
    n = max(1, len(specs))
    open(CIDS_FILE, "w").close()
    results = {}
    threads = []
    semaphore = threading.Semaphore(max(1, max_concurrent))

    def run_limited(agent_id, subject, binrel, shard, results, lane):
        with semaphore:
            _run_agent(agent_id, subject, binrel, shard, results, lane)

    for idx, (lane, i) in enumerate(specs or [("B", 0)]):
        shard = pending[idx::n]
        aid = f"val-{lane}{i}"
        threads.append(threading.Thread(target=run_limited, args=(aid, subject, binrel, shard, results, lane)))
    for t in threads:
        t.start()
        time.sleep(3)
    for t in threads:
        t.join()
    log(f"validators: {json.dumps(results)}")
    visual = publish_final_visual(subject, f"{subject} — Binary Security Research") if publish else None
    remaining = [f["id"] for f in cov.findings(subject) if needs_validation(f)]
    vendor_report = None
    if publish and not remaining:
        vendor_report = publish_vendor_disclosure(subject, f"{subject} — Vendor Disclosure Report")
    if visual:
        log(f"Final visual: {visual['url']}")
    if vendor_report:
        log(f"Vendor disclosure: {vendor_report['url']}")
    elif remaining:
        log(f"Vendor disclosure not published; {len(remaining)} finding(s) still need validation.")
    return {
        "validators": results,
        "pending": len(pending),
        "remaining_pending": len(remaining),
        "visual": visual,
        "vendor_report": vendor_report,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", default="example")
    ap.add_argument("--binrel", default="bin/target")
    ap.add_argument("--claude", type=int, default=2)
    ap.add_argument("--codex", type=int, default=2)
    ap.add_argument("--max-concurrent", type=int, default=2)
    a = ap.parse_args()
    print(json.dumps(run(a.subject, a.binrel, a.claude, a.codex, max_concurrent=a.max_concurrent), indent=2))
