import pytest

from ref_all_executor.agent_profiles import HEAD_PROVIDERS, SPECIALIST_LANES, head_profile
from ref_all_executor.head_orchestrator import HeadCycleResult, RefallHeadOrchestrator


class FakeCoverage:
    def __init__(self, *, gate_locked: bool = False, context: str = "# Alpha context\n"):
        self.calls = []
        self.gate_locked = gate_locked
        self.context = context

    def gate(self, subject):
        self.calls.append(("gate", subject))
        return {"locked": self.gate_locked}

    def claim_next(self, subject, agent):
        self.calls.append(("claim_next", subject, agent))
        return {"id": "unit1", "path": "a.py", "line_start": 1, "line_end": 3}

    def get_context(self, subject):
        self.calls.append(("get_context", subject))
        return {"subject": subject, "info_md": self.context}

    def submit(self, unit_id, agent, summary, evidence, **kw):
        self.calls.append(("submit", unit_id, agent, summary, evidence, kw))
        return {"id": unit_id, "state": "characterized"}


class FakeLedger:
    def __init__(self):
        self.entries = []

    def append(self, entry):
        self.entries.append(entry)
        return {"id": "led1", **entry}


class FakeDispatcher:
    def __init__(self):
        self.tasks = []

    def dispatch(self, lane, objective):
        self.tasks.append((lane, objective))
        return {"status": "finished", "summary": f"handled {lane}", "evidence": [{"file": "a.py"}]}


class FakeWishlist:
    def __init__(self):
        self.calls = []

    def provided(self, subject):
        self.calls.append(subject)
        return [{"item": "rizin", "status": "provided"}]


class FakeUsage:
    def __init__(self):
        self.rows = []

    def record(self, subject, lane, dispatch):
        self.rows.append((subject, lane, dispatch))
        return {"ok": True}


class FakeVerifier:
    def __init__(self):
        self.calls = []

    def verify(self, subject, claim, evidence):
        self.calls.append((subject, claim, evidence))
        return {"verified": True, "response": "REPRODUCED: yes"}


class FakeReporter:
    def __init__(self):
        self.calls = []

    def refresh(self, subject):
        self.calls.append(subject)
        return {"object_id": "obj_report"}


def test_head_profiles_support_codex_claude_grok() -> None:
    assert HEAD_PROVIDERS == {"codex", "claude", "grok"}
    assert head_profile("codex").provider == "codex"
    assert head_profile("claude").provider == "claude"
    assert head_profile("grok").provider == "grok"
    with pytest.raises(ValueError):
        head_profile("bedrock-claude")


def test_specialist_lanes_cover_refall_workflow() -> None:
    assert {
        "source-review",
        "binary-review",
        "dynamic-validation",
        "exploit-poc",
        "report-draft",
        "report-enrich",
        "visualization",
        "tooling",
        "cleanup",
    } <= SPECIALIST_LANES


def test_head_cycle_claims_dispatches_ledgers_and_submits() -> None:
    coverage = FakeCoverage()
    ledger = FakeLedger()
    dispatcher = FakeDispatcher()
    orch = RefallHeadOrchestrator(
        head_provider="codex",
        coverage=coverage,
        ledger=ledger,
        dispatcher=dispatcher,
    )

    result = orch.run_cycle("alpha", "source-review")

    assert isinstance(result, HeadCycleResult)
    assert result.provider == "codex"
    assert dispatcher.tasks[0][0] == "source-review"
    assert ledger.entries[0]["kind"] == "coverage"
    assert coverage.calls[-1][0] == "submit"
    assert "# Alpha context" in dispatcher.tasks[0][1]


def test_head_cycle_still_dispatches_when_coverage_gate_is_locked() -> None:
    coverage = FakeCoverage(gate_locked=True)
    ledger = FakeLedger()
    dispatcher = FakeDispatcher()
    orch = RefallHeadOrchestrator(
        head_provider="codex",
        coverage=coverage,
        ledger=ledger,
        dispatcher=dispatcher,
    )

    result = orch.run_cycle("alpha", "source-review")

    assert result.status == "finished"
    assert ("claim_next", "alpha", "refall-head-codex") in coverage.calls
    assert dispatcher.tasks


def test_head_cycle_integrates_wishlist_usage_verifier_and_reporter() -> None:
    coverage = FakeCoverage()
    ledger = FakeLedger()
    dispatcher = FakeDispatcher()
    wishlist = FakeWishlist()
    usage = FakeUsage()
    verifier = FakeVerifier()
    reporter = FakeReporter()
    orch = RefallHeadOrchestrator(
        head_provider="claude",
        coverage=coverage,
        ledger=ledger,
        dispatcher=dispatcher,
        wishlist=wishlist,
        usage=usage,
        verifier=verifier,
        reporter=reporter,
    )

    result = orch.run_cycle("alpha", "dynamic-validation", refresh_report=True, verify=True)

    assert result.provider == "claude"
    assert wishlist.calls == ["alpha"]
    assert "Provided wishlist" in dispatcher.tasks[0][1]
    assert usage.rows[0][0:2] == ("alpha", "dynamic-validation")
    assert verifier.calls[0][0] == "alpha"
    assert any(entry["kind"] == "validation" for entry in ledger.entries)
    assert reporter.calls == ["alpha"]
