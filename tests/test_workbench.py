import json
from ref_all_executor.workbench import Workbench


class FakeTransport:
    def __init__(self, script):
        self.script, self.calls = script, []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        for (m, suffix), resp in self.script.items():
            if method == m and url.endswith(suffix):
                s, d = resp
                return s, json.dumps(d).encode()
        raise AssertionError(f"unexpected {method} {url}")


def test_write_finding_creates_object_and_returns_oid():
    t = FakeTransport({("POST", "/api/workbenches/ref-all/objects"): (201, {"id": "obj_abc"})})
    wb = Workbench(transport=t)
    oid = wb.write_finding("Title", "# body", description="d", tags=["x"])
    assert oid == "obj_abc"
    sent = json.loads(t.calls[-1][3])
    assert sent["kind"] == "md" and sent["title"] == "Title" and sent["content"] == "# body"


def test_log_run_posts_to_responses():
    t = FakeTransport({("POST", "/api/workbenches/ref-all/objects/obj_abc/responses"): (201, {"ok": True})})
    wb = Workbench(transport=t)
    wb.log_run("obj_abc", {"status": "finished"})
    assert t.calls[-1][1].endswith("/objects/obj_abc/responses")
    assert json.loads(t.calls[-1][3])["status"] == "finished"
