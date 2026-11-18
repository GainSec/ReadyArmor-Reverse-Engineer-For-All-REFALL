from dataclasses import dataclass

from .config import LANES, Tier


@dataclass
class TaskResult:
    task_class: str
    lane: str
    objective: str
    response: str
    trajectory: bytes
    status: str
    tier: str
    verified: bool
    reason: str


def assign_tier(route, verified, lane):
    """Tier the result. Lane C (Spark) alone is capped at T3 regardless of floor."""
    if lane == "C":
        return Tier.T3
    if not verified:
        return Tier.T3
    return route.tier_floor


_VERIFIER_PROMPT = (
    "You are a verification worker. Attempt to REPRODUCE the following claim by real execution "
    "in this workspace. Do not accept it on inspection alone. End your reply with a line "
    "'REPRODUCED: yes' or 'REPRODUCED: no' followed by one sentence of evidence.\n\nCLAIM:\n{claim}\n"
)


def run_verifier(client, workspace, claim, max_iterations=15):
    """Runs a Codex (Lane B) execution task that tries to reproduce `claim`.
    `workspace` is a workspace dict (config.local_workspace/remote_workspace)."""
    cid = client.start_conversation(
        workspace=workspace,
        agent_settings=LANES["B"],
        text=_VERIFIER_PROMPT.format(claim=claim),
        max_iterations=max_iterations,
    )
    try:
        client.run(cid)
        client.wait_until_done(cid, timeout_s=1800, poll_s=3)
        resp = client.final_response(cid)
    finally:
        client.delete(cid)
    reproduced = "reproduced: yes" in resp.lower()
    return reproduced, resp
