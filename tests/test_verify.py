from ref_all_executor.verify import assign_tier, run_verifier
from ref_all_executor.router import route
from ref_all_executor.config import Tier


def test_verified_claim_reaches_tier_floor():
    assert assign_tier(route("patch"), verified=True, lane="B") == Tier.T2


def test_unverified_claim_drops_to_hypothesis():
    assert assign_tier(route("patch"), verified=False, lane="B") == Tier.T3


def test_verify_task_targets_live_confirmation():
    assert assign_tier(route("verify"), verified=True, lane="B") == Tier.T1


def test_spark_output_capped_at_t3_even_if_floor_higher():
    assert assign_tier(route("patch"), verified=True, lane="C") == Tier.T3


class FakeClient:
    def __init__(self, response):
        self._response = response
        self.deleted = []

    def start_conversation(self, **kw):
        return "vcid"

    def run(self, cid):
        pass

    def wait_until_done(self, cid, **kw):
        return "finished"

    def final_response(self, cid):
        return self._response

    def delete(self, cid):
        self.deleted.append(cid)


def test_run_verifier_detects_reproduced_marker():
    client = FakeClient("... REPRODUCED: yes, crash triggers at offset 0x40 ...")
    ok, resp = run_verifier(client, {"kind": "LocalWorkspace", "working_dir": "/projects/bra"}, "overflow in parse()")
    assert ok is True and "vcid" in client.deleted


def test_run_verifier_returns_false_when_not_reproduced():
    client = FakeClient("REPRODUCED: no — could not trigger")
    ok, _ = run_verifier(client, {"kind": "LocalWorkspace", "working_dir": "/projects/bra"}, "some claim")
    assert ok is False
