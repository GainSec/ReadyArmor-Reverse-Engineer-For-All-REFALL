from ref_all_executor.entrypoint import Task, run_pass, Clients
from ref_all_executor import config
from ref_all_executor.config import Tier


class FakeOH:
    def __init__(self):
        self.started = []
        self.deleted = []

    def start_conversation(self, workspace, agent_settings, text, max_iterations=30):
        self.started.append((agent_settings.get("acp_server"), workspace, text))
        return f"cid-{len(self.started)}"

    def run(self, cid):
        pass

    def wait_until_done(self, cid, **kw):
        return "finished"

    def final_response(self, cid):
        return "did the work. REPRODUCED: yes offset 0x10"

    def download_trajectory(self, cid):
        return b"{}"

    def delete(self, cid):
        self.deleted.append(cid)


class FakeWB:
    def __init__(self):
        self.findings = []
        self.logs = []

    def write_finding(self, title, markdown, description="", tags=None):
        self.findings.append((title, description))
        return f"obj_{len(self.findings)}"

    def log_run(self, oid, payload):
        self.logs.append((oid, payload))


class FakeKV:
    def __init__(self):
        self.pushes = []

    def kv_lpush(self, key, value):
        self.pushes.append((key, value))


def test_recon_uses_claude_not_spark():
    oh, wb = FakeOH(), FakeWB()
    run_pass("/projects/bra", [Task("recon", "look around")], clients=Clients(oh, wb))
    # recon must run on the claude-code brain, never spark
    assert oh.started[0][0] == "claude-code"


def test_patch_uses_codex_and_is_verified_and_tiered():
    oh, wb = FakeOH(), FakeWB()
    results = run_pass("/projects/bra", [Task("patch", "fix parser")], clients=Clients(oh, wb))
    assert oh.started[0][0] == "codex"
    assert results[0].verified is True
    assert results[0].tier == Tier.T2


def test_every_task_writes_one_finding_and_log():
    oh, wb = FakeOH(), FakeWB()
    tasks = [Task("decompose", "a"), Task("recon", "b")]
    run_pass("/projects/bra", tasks, clients=Clients(oh, wb))
    assert len(wb.findings) == 2 and len(wb.logs) == 2


def test_blackboard_pushed_to_kv_and_prior_findings_in_next_prompt():
    oh, wb, kv = FakeOH(), FakeWB(), FakeKV()
    run_pass("/projects/bra", [Task("decompose", "map"), Task("review", "review it")],
             clients=Clients(oh, wb, kv))
    assert len(kv.pushes) == 2 and kv.pushes[0][0] == "refall:blackboard"
    assert "PRIOR FINDINGS" in oh.started[1][2]


def test_ssh_host_prepends_ssh_instruction(monkeypatch):
    oh, wb = FakeOH(), FakeWB()
    monkeypatch.setattr(config, "HOSTS", {**config.HOSTS, "remote-test": {"kind": "ssh", "target": "remote-test"}})
    run_pass("/projects/target", [Task("recon", "inspect")], host="remote-test", clients=Clients(oh, wb))
    assert "ssh remote-test" in oh.started[0][2]
