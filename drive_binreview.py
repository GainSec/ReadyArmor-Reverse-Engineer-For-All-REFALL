#!/usr/bin/env python3
"""REF-All adversarial REVIEW gate for binary findings (Mantis mantis-review).

Every PROVISIONALLY_VALID finding is guilty until proven innocent. Reviewers re-decompile
the cited function and apply Mantis's 12 negative constraints — with binary-specific emphasis
on FORTIFY (`__memcpy_chk`) / bounded sinks, real attacker reachability, and severity honesty —
then set VALID / FALSE_POSITIVE / NEEDS_RESEARCH. Reviewers are a different, independent pass
from the finders (they can only judge, never add findings).

  PYTHONPATH=. python3 drive_binreview.py --subject example \
      --binrel "bin/target" --claude 2 --codex 2
"""
import os, threading, json, argparse

from ref_all_executor.oh_client import OHClient
from ref_all_executor.coverage_client import CoverageClient
from ref_all_executor import config
from ref_all_executor.usage import record_and_delete
from ref_all_executor.wishlist import format_provided_wishlist, provided_wishes_from
from coverage_service.tools.final_visual import publish_final_visual
from drive_characterize import log, _lock, CIDS_FILE, STOP_FILE, PID_FILE
from drive_binvalidate import run as _run_validation_driver

_PROVIDED_WISHES = {}


def run_validation(subject, binrel, claude, codex):
    return _run_validation_driver(subject, binrel, claude, codex, publish=False)


def _objective(agent_id, subject, binrel, finding_ids, provided_wishes=None):
    binpath = f"{config.subject_workspace(subject)}/{binrel}"
    ids = ", ".join(finding_ids)
    delivered = format_provided_wishlist(subject, provided_wishes)
    return f"""You are a REF-All ADVERSARIAL REVIEWER (id: {agent_id}). Assume every finding is a FALSE POSITIVE
until the CODE proves otherwise. Ignore the finder's prose reasoning — judge only the decompilation and the
raw claim. Review EXACTLY these finding IDs for subject "{subject}": {ids}

Binary: "{binpath}"     radare2: run `export PATH=$PATH:/usr/local/bin` first.
Service: http://host.docker.internal:8900
{delivered}

Report/evidence handoff: use the REF-All report spec at
{config.REFALL_WORKSPACE}/docs/superpowers/specs/2026-07-16-refall-report-format-spec.md to keep review output useful
for the later validation/disclosure loop. You are not writing the disclosure now, but VALID and NEEDS_RESEARCH
decisions must leave concrete trace/proof guidance rather than vague prose.

For EACH finding id above:
1. GET http://host.docker.internal:8900/finding/<id>  -> {{title,description,code_paths,severity,vuln_class,...}}.
   code_paths look like "{binrel}:sym.func.<addr>@<insn_addr>".
2. RE-DECOMPILE the cited function yourself (do not trust the finder):
   r2 -q -e scr.color=0 -c "aa; s <sym.func.addr>; pdc" "{binpath}"   (and pdf for the exact instructions).
3. Apply Mantis's 12 negative constraints. For THIS binary, weight these heavily:
   - FORTIFY / bounded sink: does the copy actually go through __memcpy_chk, __strcpy_chk, __sprintf_chk,
     snprintf, strlcpy, or an explicit bounds check? If the real sink is a _chk/bounded variant that aborts
     on overflow, the "overflow" is caught at runtime => FALSE_POSITIVE (mitigated).
   - Reachability: is the tainted size/data GENUINELY attacker-controlled from an external IPP/HTTP request,
     with a concrete path from recv/httpRead/ippRead to the sink? If the finder assumed it or it's only
     reachable from trusted/local config => NEEDS_RESEARCH or FALSE_POSITIVE.
   - Severity honesty: an unreachable, DoS-only, or heavily-conditioned bug is NOT CRITICAL. Note if severity
     is inflated (still VALID, but say so in reasoning).
   - Anti-hallucination: verify the cited function/addresses actually exist in the decompilation. If not =>
     FALSE_POSITIVE.
   - Also drop: hypothetical caller misuse of a safe function; pedantic linting; test-only unreachable paths.
4. DECIDE: VALID (clear, triggerable, reachable, real), FALSE_POSITIVE (mitigated / unreachable / hallucinated
   / violates a constraint), NEEDS_RESEARCH (genuinely inconclusive without dynamic proof), or
   CHAINABLE_DEFERRED (real technical primitive, but no proven standalone exploitability; useful only if
   chained with another primitive such as a planting path, auth bypass, CSRF/local-request path, or exposure change).
   If NEEDS_RESEARCH, include the exact missing runtime/static proof target in repro_hints so the validation
   loop can continue without rediscovering the blocker. If FALSE_POSITIVE/DUPLICATE-equivalent, name the
   disproving evidence so it can stay in the collapsed rejected appendix. If CHAINABLE_DEFERRED, name the
   missing chain primitive and why it should not be sent as a standalone vendor/client finding.
5. POST http://host.docker.internal:8900/review_finding
   {{"finding_id":"<id>","agent":"{agent_id}","status":"VALID|FALSE_POSITIVE|NEEDS_RESEARCH|CHAINABLE_DEFERRED",
     "reasoning":"<2-4 sentences grounded in what you decompiled: name the actual sink (memcpy vs __memcpy_chk),
     the size source, and the reachability verdict>",
     "repro_hints":"<for VALID/NEEDS_RESEARCH: direct proof target; for CHAINABLE_DEFERRED: missing chain primitive needed for promotion>"}}.
Be skeptical and precise. Report each id's verdict + one-line why."""


def _run_agent(agent_id, subject, binrel, finding_ids, results, lane="A", provided_wishes=None):
    if provided_wishes is None:
        provided_wishes = _PROVIDED_WISHES.get(subject, [])
    if not finding_ids:
        results[agent_id] = "finished"
        return
    oh = OHClient()
    try:
        cid = oh.start_conversation(workspace=config.local_workspace(config.subject_workspace(subject)),
            agent_settings=config.LANES[lane], text=_objective(agent_id, subject, binrel, finding_ids, provided_wishes),
            max_iterations=max(30, len(finding_ids) * 10))
        with _lock:
            open(CIDS_FILE, "a").write(cid + "\n")
        oh.run(cid)
        st = oh.wait_until_done(cid, timeout_s=5400, poll_s=12)
        results[agent_id] = st
        record_and_delete(oh, cid, {"driver": "binreview", "agent_id": agent_id,
                                    "subject": subject, "lane": lane, "status": st,
                                    "finding_count": len(finding_ids)})
    except Exception as e:
        results[agent_id] = f"error:{e}"


def run(subject, binrel, claude, codex):
    open(PID_FILE, "w").write(str(os.getpid()))
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
    cov = CoverageClient()
    _PROVIDED_WISHES[subject] = provided_wishes_from(cov, subject)
    pending = [f["id"] for f in cov.findings(subject, status="PROVISIONALLY_VALID")]
    if not pending:
        run_validation(subject, binrel, claude, codex)
        visual = publish_final_visual(subject, f"{subject} — Binary Security Research")
        log(f"No PROVISIONALLY_VALID findings for {subject} to review. Final visual: {visual['url']}")
        return
    log(f"reviewing {len(pending)} findings with {claude} Claude + {codex} Codex reviewers")
    specs = [("A", i) for i in range(claude)] + [("B", i) for i in range(codex)]
    n = len(specs)
    open(CIDS_FILE, "w").close()
    results = {}
    threads = []
    for idx, (lane, i) in enumerate(specs):
        shard = pending[idx::n]                       # deterministic non-overlapping partition
        aid = f"rev-{lane}{i}"
        threads.append(threading.Thread(target=_run_agent, args=(aid, subject, binrel, shard, results, lane)))
    for t in threads: t.start()
    for t in threads: t.join()
    log(f"reviewers: {results}")
    fn = cov.funnel(subject)
    log(f"FUNNEL: {json.dumps(fn)}")
    run_validation(subject, binrel, claude, codex)
    visual = publish_final_visual(subject, f"{subject} — Binary Security Research")
    log(f"Final visual: {visual['url']}")
    print(json.dumps({"reviewers": results, "funnel": fn, "visual": visual}, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", default="example")
    ap.add_argument("--binrel", default="bin/target")
    ap.add_argument("--claude", type=int, default=2)
    ap.add_argument("--codex", type=int, default=2)
    a = ap.parse_args()
    run(a.subject, a.binrel, a.claude, a.codex)
