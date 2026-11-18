"""The multi-lane REF-All loop. In Phase 1b this runs as the code-automation entrypoint;
it can also be driven directly. Real analysis goes to Claude/Codex conversations (subscriptions);
findings are written to the workbench deterministically; the blackboard lives in the native KV store."""
from dataclasses import dataclass

from . import config
from .oh_client import OHClient
from .workbench import Workbench
from .router import route
from .verify import run_verifier, assign_tier, TaskResult


@dataclass
class Task:
    task_class: str
    objective: str


@dataclass
class Clients:
    oh: object
    wb: object
    kv: object = None            # AutoClient for the native KV blackboard (optional)


def _workspace_for(host, working_dir):
    h = config.HOSTS.get(host, {"kind": "local"})
    if h.get("kind") == "remote":
        return config.remote_workspace(h["host"], h["api_key"], working_dir)
    # local and ssh both run a LocalWorkspace in this container; ssh shells out per ssh_preamble.
    return config.local_workspace(working_dir)


def _objective(host, task, blackboard):
    text = config.ssh_preamble(host) + task.objective
    if blackboard:
        prior = "\n\n".join(blackboard[-5:])
        text = f"PRIOR FINDINGS (blackboard):\n{prior}\n\n---\nYOUR TASK:\n{text}"
    return text


def execute_task(clients, working_dir, task, blackboard, host="local", max_iterations=30):
    decision = route(task.task_class)
    agent_settings = config.LANES[decision.lane]
    workspace = _workspace_for(host, working_dir)

    cid = clients.oh.start_conversation(
        workspace=workspace, agent_settings=agent_settings,
        text=_objective(host, task, blackboard), max_iterations=max_iterations)
    try:
        clients.oh.run(cid)
        status = clients.oh.wait_until_done(cid, timeout_s=1800, poll_s=3)
        response = clients.oh.final_response(cid)
        trajectory = clients.oh.download_trajectory(cid)
    finally:
        clients.oh.delete(cid)

    verified = False
    if decision.needs_verify and status == "finished":
        verified, _ = run_verifier(clients.oh, workspace, claim=response)

    tier = assign_tier(decision, verified, decision.lane)
    result = TaskResult(
        task_class=task.task_class, lane=decision.lane, objective=task.objective,
        response=response, trajectory=trajectory, status=status,
        tier=tier, verified=verified, reason=decision.reason)

    lane_name = {"A": "Claude", "B": "Codex", "C": "Spark"}[decision.lane]
    markdown = (
        f"# {task.task_class} — {tier}\n\n"
        f"**Lane:** {decision.lane}/{lane_name} — {decision.reason}  \n"
        f"**Host:** {host}  |  **Status:** {status}  |  **Verified:** {verified}\n\n"
        f"## Objective\n{task.objective}\n\n## Agent output\n{response}\n")
    oid = clients.wb.write_finding(
        title=f"[loop] {task.task_class} ({tier})", markdown=markdown,
        description=f"lane={decision.lane}/{lane_name} host={host} verified={verified} tier={tier}",
        tags=["ref-all", "openhands-loop", task.task_class])
    clients.wb.log_run(oid, {"task_class": task.task_class, "lane": decision.lane,
                             "host": host, "status": status, "verified": verified, "tier": tier})
    if clients.kv is not None:
        # Native KV is a per-run store (wants the automation's callback Authorization creds);
        # it works when this runs INSIDE an automation. Never let a blackboard hiccup kill the pass.
        try:
            clients.kv.kv_lpush("refall:blackboard", f"[{task.task_class}->{tier}] {response[:600]}")
        except Exception as exc:
            print(f"[warn] KV blackboard push skipped: {exc}")
    return result


def run_pass(working_dir, tasks, host="local", clients=None, max_iterations=30):
    if clients is None:
        clients = Clients(OHClient(), Workbench())
    blackboard = []
    results = []
    for task in tasks:
        r = execute_task(clients, working_dir, task, blackboard, host=host, max_iterations=max_iterations)
        results.append(r)
        blackboard.append(f"[{task.task_class}->{r.tier}] {r.response[:600]}")
    return results
