import pytest
from coverage_service.store import Store
from coverage_service.enumerate import build_units


def seed(conn):
    s = Store(conn)
    s.upsert_units(build_units("bra", [
        {"path": "a.py", "total_lines": 10, "symbols": [{"name": "f", "line_start": 1, "line_end": 10}]},
        {"path": "b.py", "total_lines": 4, "symbols": []},
    ]))
    return s


def _submit(s, u, agent="A"):
    s.submit(u["id"], agent, "ok", evidence=[{"file": u["path"], "line_start": u["line_start"],
                                              "line_end": u["line_end"], "snippet": "x"}])


def test_claim_is_exclusive(conn):
    s = seed(conn)
    u1 = s.claim_next("bra", "agentA")
    u2 = s.claim_next("bra", "agentB")
    assert u1 and u2 and u1["id"] != u2["id"]  # never the same unit


def test_submit_requires_evidence(conn):
    s = seed(conn)
    u = s.claim_next("bra", "A")
    with pytest.raises(ValueError):
        s.submit(u["id"], "A", "did stuff", evidence=[])


def test_submit_marks_characterized_and_files_done(conn):
    s = seed(conn)
    for _ in range(6):
        u = s.claim_next("bra", "A")
        if not u:
            break
        _submit(s, u)
    cov = s.coverage("bra")
    assert cov["lines_covered"] == cov["lines_total"] == 14
    assert cov["characterized_pct"] == 100.0 and cov["files_done"] == cov["files_total"] == 2


def test_gate_locked_until_threshold(conn):
    s = seed(conn)
    g0 = s.gate("bra", threshold=0.95)
    assert g0["locked"] is True and g0["resolved_pct"] == 0.0
    _submit(s, s.claim_next("bra", "A"))
    assert s.gate("bra", threshold=0.95)["locked"] is True  # still < 95%


def test_expired_lease_is_reclaimable(conn):
    s = seed(conn)
    u = s.claim_next("bra", "A", lease_s=-1)  # already expired
    n = s.sweep()
    assert n >= 1
    again = s.claim_next("bra", "B")
    assert again["id"] == u["id"]


def test_dead_code_resolves_and_search(conn):
    s = seed(conn)
    u = s.claim_next("bra", "A")
    s.mark_dead(u["id"], "A", evidence=[{"file": u["path"], "line_start": 1, "line_end": 1}])
    dead = s.search("bra", state="dead")
    assert len(dead) == 1
    assert s.coverage("bra")["lines_dead"] >= 1
