import json
from ref_all_executor.coverage_client import CoverageClient
from ref_all_executor.router import route


class Fake:
    def __init__(self, script):
        self.script, self.calls = script, []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, body))
        for (m, suffix), resp in self.script.items():
            if method == m and url.endswith(suffix):
                return resp[0], json.dumps(resp[1]).encode()
        # default ok
        return 200, b"{}"


def client(script):
    return CoverageClient(base="http://x", transport=Fake(script))


def test_submit_sends_evidence():
    t = Fake({("POST", "/submit"): (200, {"state": "characterized"})})
    c = CoverageClient(base="http://x", transport=t)
    c.submit("uid", "A", "did it", evidence=[{"file": "a.py", "line_start": 1, "line_end": 3}], sensitivity="auth")
    body = json.loads(t.calls[-1][2])
    assert body["evidence"][0]["file"] == "a.py" and body["sensitivity"] == "auth"


def test_claim_and_gate_paths():
    c = client({("POST", "/claim_next"): (200, {"id": "u1", "type": "symbol"}),
                ("GET", "/gate?subject=bra&threshold=0.95"): (200, {"locked": True})})
    assert c.claim_next("bra", "A")["id"] == "u1"


def test_workbench_coverage_paths():
    t = Fake({
        ("POST", "/api/workbenches/alpha/coverage/claim"): (200, {"id": "u1", "type": "symbol"}),
        ("GET", "/api/workbenches/alpha/coverage/gate?threshold=0.95"): (
            200,
            {"locked": False},
        ),
    })
    c = CoverageClient(workbench_base="http://ab", workbench_slug="alpha", transport=t)

    assert c.claim_next("alpha", "A")["id"] == "u1"
    assert c.gate("alpha")["locked"] is False


def test_workbench_submit_uses_subject_workbench_path():
    t = Fake({
        ("POST", "/api/workbenches/alpha/coverage/submit"): (
            200,
            {"id": "unit1", "state": "characterized"},
        ),
    })
    c = CoverageClient(workbench_base="http://ab", transport=t)

    assert c.submit(
        "unit1",
        "refall-head-codex",
        "handled",
        [{"file": "a.py"}],
        subject="alpha",
    )["state"] == "characterized"
    body = json.loads(t.calls[-1][2])
    assert "subject" not in body


def test_workbench_add_finding_uses_coverage_findings_endpoint():
    t = Fake({
        ("POST", "/api/workbenches/alpha/coverage/findings"): (
            201,
            {"id": "find_1", "title": "SQL injection"},
        ),
    })
    c = CoverageClient(workbench_base="http://ab", transport=t)

    assert c.add_finding("alpha", {"id": "find_1", "title": "SQL injection", "code_paths": ["app.py:1"]})["id"] == "find_1"
    body = json.loads(t.calls[-1][2])
    assert body["subject"] == "alpha"
    assert body["code_paths"] == ["app.py:1"]


def test_legacy_add_finding_uses_nested_finding_endpoint():
    t = Fake({
        ("POST", "/finding"): (
            200,
            {"id": "find_1", "title": "SQL injection"},
        ),
    })
    c = CoverageClient(base="http://cov", mode="legacy", transport=t)

    assert c.add_finding("alpha", {"id": "find_1", "title": "SQL injection"})["id"] == "find_1"
    body = json.loads(t.calls[-1][2])
    assert body["finding"]["subject"] == "alpha"


def test_default_coverage_client_uses_subject_workbench(monkeypatch):
    monkeypatch.setenv("REFALL_WORKBENCH_BASE", "http://ab")
    t = Fake({
        ("GET", "/api/workbenches/alpha/coverage/wishlist?status=provided"): (
            200,
            [{"item": "rizin", "status": "provided"}],
        ),
        ("GET", "/api/workbenches/alpha/coverage/findings/summary"): (
            200,
            {"total": 1},
        ),
    })
    c = CoverageClient(transport=t)

    assert c.wishlist("alpha", status="provided")[0]["item"] == "rizin"
    assert c.findings_summary("alpha")["total"] == 1


def test_legacy_coverage_mode_is_explicit():
    c = CoverageClient(
        base="http://x",
        mode="legacy",
        transport=Fake({
            ("GET", "/wishlist?subject=example-binary&status=provided"): (
                200,
                [{"item": "r2ghidra", "status": "provided"}],
            )
        }),
    )

    assert c.wishlist("example-binary", status="provided")[0]["item"] == "r2ghidra"


def test_wishlist_status_path():
    c = CoverageClient(base="http://x", mode="legacy", transport=Fake({
        ("GET", "/wishlist?subject=example-binary&status=provided"): (
            200,
            [{"item": "r2ghidra", "status": "provided"}],
        )
    }))

    assert c.wishlist("example-binary", status="provided")[0]["item"] == "r2ghidra"


def test_router_has_enumerate_and_characterize():
    assert route("enumerate").lane == "B"      # mechanical -> Codex
    assert route("characterize").lane == "A"   # judgment -> Claude
