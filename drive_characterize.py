#!/usr/bin/env python3
"""Sustained characterize driver for the REF-All Coverage Service.

Loops: dispatch batches of parallel Claude `characterize` agents (each claims+characterizes
several coverage units with evidence) until the subject's gate opens (fully characterized) or
a STOP is requested. Killable — see kill().

Usage:
  PYTHONPATH=. python3 drive_characterize.py run   --subject example --agents 5 --units 10
  PYTHONPATH=. python3 drive_characterize.py status --subject example
  PYTHONPATH=. python3 drive_characterize.py kill          # graceful+forceful stop
"""
import os, sys, time, json, threading, signal, argparse

from ref_all_executor.oh_client import OHClient
from ref_all_executor.coverage_client import CoverageClient
from ref_all_executor import config
from ref_all_executor.usage import record_and_delete
from coverage_service.tools.final_visual import publish_coverage_visual

DATA = os.path.join(os.path.dirname(__file__), "coverage_service", "data")
os.makedirs(DATA, exist_ok=True)
STOP_FILE = os.path.join(DATA, "STOP")
CIDS_FILE = os.path.join(DATA, "active_cids.txt")   # live conversation ids (for kill)
PID_FILE = os.path.join(DATA, "driver.pid")
LOG = os.path.join(DATA, "driver.log")

_lock = threading.Lock()


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def _objective(agent_id, subject, n):
    subject_ws = config.subject_workspace(subject)
    return f"""You are a REF-All CHARACTERIZE worker (id: {agent_id}). Pull uncharacterized coverage units
from the Coverage Service and characterize each WITH EVIDENCE, one at a time. Do up to {n} units then STOP.

Coverage Service: http://host.docker.internal:8900   Subject: "{subject}"   Files at: {subject_ws}

Repeat up to {n} times:
1. CLAIM: POST /claim_next  {{"subject":"{subject}","agent":"{agent_id}"}}  -> unit {{id,path,line_start,line_end,type,name}}.
   HTTP 404 => STOP (nothing left).
2. READ exactly:  sed -n "<line_start>,<line_end>p" "{subject_ws}/<path>"
3. CHARACTERIZE grounded in what you read: summary; sensitivity (one of none|data-change|auth|crypto|io|exec|net|secret);
   data_touched; leads (record risky patterns/bugs, do NOT chase).
3b. CONNECT it to the rest of the codebase using the semantic substrate (this is what makes the graph):
   - grep the toolchain outputs at {config.REFALL_WORKSPACE}/toolchain/output/{subject}/ (graphs/*.dot, indexes/*.json,
     scip/) for the symbol name to find its callers/callees and imports;
   - query the Coverage Service: GET http://host.docker.internal:8900/search?subject={subject}&q=<name> for related units;
   - if reachable, use Serena (http://host.docker.internal:20872) or Codebase-Memory for symbol references.
   Record the concrete callers/callees and cross-file data flows in flows_in / flows_out (these are the edges).
4. SUBMIT (evidence anchor REQUIRED or 422): POST /submit {{"unit_id":..,"agent":"{agent_id}","summary":..,"sensitivity":..,
   "data_touched":..,"flows_in":..,"flows_out":..,"leads":..,"evidence":[{{"file":"<path>","line_start":<ls>,"line_end":<le>,"snippet":"<real snippet>"}}]}}.
Be accurate. Report how many you characterized."""


def _dex(cmd, timeout=3600):
    import subprocess
    return subprocess.run(["docker", "exec", "refall-agent-canvas", "sh", "-lc", cmd],
                          capture_output=True, text=True, timeout=timeout)


def ensure_l1(subject):
    """Build the L1 mechanical substrate BEFORE characterize: toolchain graphs/scip/metrics
    (visualizations + symbol indexes) + bring up the semantic-storage services (Serena,
    Codebase-Memory). So discovery builds the whole toolchain substrate, not just coverage."""
    out = f"{config.REFALL_WORKSPACE}/toolchain/output/{subject}"
    ws = config.subject_workspace(subject)
    r = _dex(f"test -d {out}/graphs && test -f {out}/scip/index.scip && echo present || echo missing")
    if "missing" in (r.stdout or ""):
        log(f"L1: toolchain outputs missing -> running run.sh on {subject} (graphs/scip/metrics) ...")
        _dex(f"cd {config.REFALL_WORKSPACE}/toolchain && ./run.sh {ws} {out}", timeout=5400)
    else:
        log("L1: toolchain graphs/scip/metrics present.")
    log("L1: bringing up semantic-storage services (serena + codebase-memory) ...")
    _dex(f"cd {config.REFALL_WORKSPACE}/toolchain && ./ctl.sh up serena codebase-memory")
    st = _dex(f"cd {config.REFALL_WORKSPACE}/toolchain && ./ctl.sh status")
    log("L1 services:\n" + (st.stdout or "")[-500:])


def _run_agent(agent_id, subject, n, results, lane="A"):
    oh = OHClient()
    try:
        cid = oh.start_conversation(workspace=config.local_workspace(config.subject_workspace(subject)),
            agent_settings=config.LANES[lane], text=_objective(agent_id, subject, n), max_iterations=max(20, n * 6))
        with _lock:
            open(CIDS_FILE, "a").write(cid + "\n")
        oh.run(cid)
        st = oh.wait_until_done(cid, timeout_s=5400, poll_s=12)
        results[agent_id] = st
        record_and_delete(oh, cid, {"driver": "characterize", "agent_id": agent_id,
                                    "subject": subject, "lane": lane, "status": st})
    except Exception as e:
        results[agent_id] = f"error:{e}"


def run(subject, claude, codex, units, threshold, fail_fast=True):
    open(PID_FILE, "w").write(str(os.getpid()))
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
    ensure_l1(subject)   # build graphs/symbols/semantic storage first, then characterize on top
    cov = CoverageClient()
    batch = 0
    while True:
        if os.path.exists(STOP_FILE):
            log("STOP requested — exiting."); break
        g = cov.gate(subject, threshold)
        c = cov.coverage(subject)
        log(f"batch {batch}: characterized={c['characterized_pct']}% lines={c['lines_covered']}/{c['lines_total']} "
            f"files_done={c['files_done']}/{c['files_total']} gate={'LOCKED' if g['locked'] else 'OPEN'}")
        if not g["locked"]:
            visual = publish_coverage_visual(subject)
            log(f"GATE OPEN — {subject} characterized to threshold. Final visual: {visual['url']}. Done."); break
        open(CIDS_FILE, "w").close()  # reset per-batch cid list
        results = {}
        # Both strong subscriptions in parallel, but Codex concurrency is capped low: a solo
        # Codex agent works, 3-concurrent Codex errors (shared .codex session/rate-limit). So run
        # `claude` Claude agents wide + `codex` Codex agents (keep codex small, e.g. 1).
        specs = [("A", i) for i in range(claude)] + [("B", i) for i in range(codex)]
        threads = [threading.Thread(target=_run_agent,
                   args=(f"drv-{batch}-{lane}{i}", subject, units, results, lane))
                   for (lane, i) in specs]
        for t in threads: t.start()
        for t in threads: t.join()
        log(f"batch {batch} agents: {results}")
        # FAIL-FAST (default on while stabilizing): any agent not 'finished' halts the run so we
        # don't waste usage on a broken lane. Disable with --no-fail-fast once stable.
        errored = [a for a, s in results.items() if str(s) != "finished"]
        if fail_fast and errored:
            log(f"FAIL-FAST: agents errored {errored} -> stopping run (no more spend).")
            open(STOP_FILE, "w").close()
            break
        batch += 1
        time.sleep(1)


def status(subject):
    c = CoverageClient()
    print(json.dumps({"coverage": c.coverage(subject), "gate": c.gate(subject)}, indent=2))


def kill():
    open(STOP_FILE, "w").close()
    # interrupt+delete active conversations
    oh = OHClient()
    try:
        cids = [x.strip() for x in open(CIDS_FILE) if x.strip()] if os.path.exists(CIDS_FILE) else []
    except OSError:
        cids = []
    for cid in cids:
        try:
            oh.request("POST", f"/api/conversations/{cid}/interrupt", {})
            oh.delete(cid)
            print("stopped", cid)
        except Exception as e:
            print("stop-fail", cid, e)
    # kill the driver process
    if os.path.exists(PID_FILE):
        pid = int(open(PID_FILE).read().strip())
        try:
            os.kill(pid, signal.SIGTERM); print("killed driver pid", pid)
        except ProcessLookupError:
            print("driver not running")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "status", "kill"])
    ap.add_argument("--subject", default="example")
    ap.add_argument("--claude", type=int, default=3, help="parallel Claude (Lane A) agents per batch")
    ap.add_argument("--codex", type=int, default=1, help="parallel Codex (Lane B) agents per batch (keep low)")
    ap.add_argument("--units", type=int, default=10)
    ap.add_argument("--threshold", type=float, default=0.95)
    ap.add_argument("--no-fail-fast", dest="fail_fast", action="store_false",
                    help="keep running even if agents error (default: stop on any error)")
    ap.set_defaults(fail_fast=True)
    a = ap.parse_args()
    if a.cmd == "run":
        run(a.subject, a.claude, a.codex, a.units, a.threshold, a.fail_fast)
    elif a.cmd == "status":
        status(a.subject)
    else:
        kill()
