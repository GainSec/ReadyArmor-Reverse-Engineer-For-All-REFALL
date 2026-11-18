import pytest
from coverage_service.store import Store


def store(conn):
    return Store(conn)


def _finding(**over):
    f = {"subject": "bra", "title": "Auth bypass in login", "severity": "HIGH",
         "code_paths": ["auth/login.py:42"], "description": "no token check",
         "impact": "privilege escalation"}
    f.update(over)
    return f


# ---- findings ----

def test_add_finding_defaults_and_history(conn):
    s = store(conn)
    f = s.add_finding(_finding())
    assert f["id"] and f["subject"] == "bra"
    assert f["status"] == "PROVISIONALLY_VALID"      # researcher default
    assert f["repro_status"] == "not_attempted"
    assert f["code_paths"] == ["auth/login.py:42"]   # decoded from json
    assert f["history"][0]["action"] == "created"


def test_add_finding_requires_code_paths(conn):
    s = store(conn)
    with pytest.raises(ValueError):
        s.add_finding(_finding(code_paths=[]))


def test_add_finding_requires_title(conn):
    s = store(conn)
    with pytest.raises(ValueError):
        s.add_finding(_finding(title=None))


def test_add_finding_rejects_bad_status(conn):
    s = store(conn)
    with pytest.raises(ValueError):
        s.add_finding(_finding(status="MADE_UP"))


def test_review_promotes_and_appends_history(conn):
    s = store(conn)
    f = s.add_finding(_finding())
    r = s.review_finding(f["id"], "reviewer-A", "VALID", reasoning="clear triggerable flaw",
                         repro_hints="POST /login with empty token")
    assert r["status"] == "VALID"
    assert r["repro_hints"] == "POST /login with empty token"
    last = r["history"][-1]
    assert last["stage"] == "reviewer" and last["by"] == "reviewer-A"


def test_update_finding_validation_adds_runtime_viability_and_history(conn):
    s = store(conn)
    f = s.add_finding(_finding(status="VALID"))

    r = s.update_finding_validation(
        f["id"],
        "validator-A",
        production_viability="Runtime validation is directly actionable with a crafted IPP request.",
        repro_status="runtime_viable",
        repro_hints="Dynamic repro: send crafted IPP request. Expected dynamic proof: crash.",
        critic_reasoning="Visual trace: IPP request -> parser -> unchecked sink.",
        patch_status="unpatched",
    )

    assert r["status"] == "VALID"
    assert r["production_viability"] == "Runtime validation is directly actionable with a crafted IPP request."
    assert r["repro_status"] == "runtime_viable"
    assert r["repro_hints"] == "Dynamic repro: send crafted IPP request. Expected dynamic proof: crash."
    assert r["critic_reasoning"] == "Visual trace: IPP request -> parser -> unchecked sink."
    assert r["patch_status"] == "unpatched"
    last = r["history"][-1]
    assert last["stage"] == "runtime-validation"
    assert last["action"] == "validation-updated"
    assert last["by"] == "validator-A"


def test_update_finding_validation_replaces_prior_runtime_verdict(conn):
    s = store(conn)
    f = s.add_finding(_finding(status="VALID"))
    s.update_finding_validation(
        f["id"],
        "validator-A",
        production_viability="First PoC attempt was blocked by document parser rejection.",
        repro_status="NOT_PROVEN",
        repro_hints="Run the original PoC.",
        critic_reasoning="Raw output: document-format-error.",
        patch_status="unpatched",
    )

    replaced = s.update_finding_validation(
        f["id"],
        "validator-B",
        production_viability="Second attempt found runtime evidence.",
        repro_status="runtime_confirmed",
        repro_hints="Run the improved PoC.",
        critic_reasoning="Raw output: injected marker appeared in web UI.",
        patch_status="unpatched",
    )

    assert replaced["repro_status"] == "runtime_confirmed"
    assert replaced["production_viability"].startswith("Second attempt")
    assert replaced["critic_reasoning"].startswith("Raw output: injected marker")


def test_review_can_mark_false_positive(conn):
    s = store(conn)
    f = s.add_finding(_finding())
    r = s.review_finding(f["id"], "rev", "FALSE_POSITIVE", reasoning="hypothetical misuse (constraint 1)")
    assert r["status"] == "FALSE_POSITIVE"


def test_review_can_mark_chainable_deferred(conn):
    s = store(conn)
    f = s.add_finding(_finding(vuln_class="CWE-79"))

    r = s.review_finding(
        f["id"],
        "rev",
        "CHAINABLE_DEFERRED",
        reasoning=(
            "Real quote-breakout sink, but only same-user/local planting is proven; "
            "retain for chain analysis instead of vendor submission."
        ),
        repro_hints="Needs a non-self planting primitive such as localhost CSRF before promotion.",
    )

    assert r["status"] == "CHAINABLE_DEFERRED"
    assert "non-self planting primitive" in r["repro_hints"]
    summ = s.findings_summary("bra")
    assert summ["by_status"]["CHAINABLE_DEFERRED"] == 1
    funnel = s.funnel("bra")
    assert funnel["chainable_deferred"] == 1
    assert funnel["valid"] == 0


def test_review_rejects_bad_status(conn):
    s = store(conn)
    f = s.add_finding(_finding())
    with pytest.raises(ValueError):
        s.review_finding(f["id"], "rev", "NOPE")


def test_list_and_summary(conn):
    s = store(conn)
    a = s.add_finding(_finding(title="A", severity="HIGH"))
    s.add_finding(_finding(title="B", severity="LOW"))
    s.review_finding(a["id"], "rev", "VALID")
    assert len(s.list_findings("bra")) == 2
    assert len(s.list_findings("bra", status="VALID")) == 1
    summ = s.findings_summary("bra")
    assert summ["total"] == 2
    assert summ["by_severity"] == {"HIGH": 1, "LOW": 1}
    assert summ["by_status"]["VALID"] == 1


# ---- plan / investigations ----

def _plan():
    return [
        {"title": "Auth surface", "target_files": ["auth/login.py"], "question": "trace token check",
         "priority": 1},
        {"title": "File upload sinks", "target_files": ["upload.py"], "question": "trace path handling",
         "priority": 2},
    ]


def test_put_plan_and_progress(conn):
    s = store(conn)
    n = s.put_plan("bra", _plan())
    assert n == 2
    assert s.plan_progress("bra") == {"total": 2, "open": 2, "claimed": 0, "done": 0}


def test_claim_investigation_priority_order_and_exclusive(conn):
    s = store(conn)
    s.put_plan("bra", _plan())
    i1 = s.claim_investigation("bra", "agentA")
    i2 = s.claim_investigation("bra", "agentB")
    assert i1["title"] == "Auth surface"      # priority 1 first
    assert i2["title"] == "File upload sinks"
    assert i1["id"] != i2["id"]               # never the same investigation
    assert i1["target_files"] == ["auth/login.py"]
    assert s.claim_investigation("bra", "agentC") is None  # nothing left open


def test_complete_investigation(conn):
    s = store(conn)
    s.put_plan("bra", _plan())
    i = s.claim_investigation("bra", "A")
    s.complete_investigation(i["id"], "A")
    prog = s.plan_progress("bra")
    assert prog["done"] == 1
    done = s.list_investigations("bra", state="done")
    assert done[0]["id"] == i["id"]


def test_plan_progress_reopens_expired_investigation_claims(conn):
    s = store(conn)
    s.put_plan("bra", _plan()[:1])
    i = s.claim_investigation("bra", "A", lease_s=-1)

    prog = s.plan_progress("bra")

    assert prog == {"total": 1, "open": 1, "claimed": 0, "done": 0}
    reopened = s.claim_investigation("bra", "B")
    assert reopened["id"] == i["id"]
