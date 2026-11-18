import pytest
from coverage_service.store import Store


def store(conn):
    return Store(conn)


def _finding(status, **o):
    f = {"subject": "bra", "title": "t", "code_paths": ["a.py:1"], "status": status}
    f.update(o)
    return f


# ---- subject context (INFO.md) ----

def test_context_set_get_overwrite(conn):
    s = store(conn)
    assert s.get_context("bra") is None
    s.set_context("bra", "# BRA\nGuard system.", generated_by="A", root_container="/projects/bra")
    ctx = s.get_context("bra")
    assert ctx["info_md"].startswith("# BRA") and ctx["root_container"] == "/projects/bra"
    s.set_context("bra", "# BRA v2")
    assert s.get_context("bra")["info_md"] == "# BRA v2"           # overwrite
    assert s.get_context("bra")["root_container"] == "/projects/bra"  # preserved


# ---- wishlist ----

def test_wishlist_add_list_resolve(conn):
    s = store(conn)
    w = s.add_wish("bra", "ghidra for boots/gui binary", kind="tool", reason="need decompiler",
                   requested_by="res-A")
    assert w["status"] == "open" and w["item"].startswith("ghidra")
    assert len(s.list_wishes("bra")) == 1
    assert len(s.list_wishes("bra", status="open")) == 1
    s.resolve_wish(w["id"], "provided")
    assert s.list_wishes("bra", status="open") == []
    assert s.get_wish(w["id"])["status"] == "provided"


def test_wishlist_requires_item(conn):
    with pytest.raises(ValueError):
        store(conn).add_wish("bra", "")


# ---- funnel metrics ----

def test_funnel_rejection_and_precision(conn):
    s = store(conn)
    s.add_finding(_finding("PROVISIONALLY_VALID", title="p"))
    v = s.add_finding(_finding("PROVISIONALLY_VALID", title="v"))
    fp = s.add_finding(_finding("PROVISIONALLY_VALID", title="fp"))
    s.review_finding(v["id"], "rev", "VALID")
    s.review_finding(fp["id"], "rev", "FALSE_POSITIVE")
    f = s.funnel("bra")
    assert f["candidates"] == 3 and f["provisional"] == 1
    assert f["valid"] == 1 and f["false_positive"] == 1
    assert f["rejection_rate"] == 0.5 and f["precision"] == 0.5


def test_funnel_empty(conn):
    f = store(conn).funnel("bra")
    assert f["candidates"] == 0 and f["rejection_rate"] is None


# ---- attack-pattern KB + per-class exhaustiveness (#5) ----

def test_attack_patterns(conn):
    s = store(conn)
    s.add_attack_pattern("CWE-79", "DOM XSS", leads=["innerHTML sink", "location.hash source"],
                         sinks=["innerHTML", "document.write"])
    pats = s.list_attack_patterns("CWE-79")
    assert pats[0]["title"] == "DOM XSS" and "innerHTML sink" in pats[0]["leads"]


def test_class_coverage(conn):
    s = store(conn)
    s.set_class_coverage("bra", "command-injection", "open")
    s.set_class_coverage("bra", "command-injection", "exhausted", checked_by="res-A",
                         notes="all exec sinks traced")
    cc = s.class_coverage("bra")
    assert cc[0]["vuln_class"] == "command-injection" and cc[0]["state"] == "exhausted"
    assert cc[0]["checked_by"] == "res-A"
