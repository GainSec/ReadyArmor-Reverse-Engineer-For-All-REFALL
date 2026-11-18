import json

import pytest

from ref_all_executor.arcticbase_client import ArcticBaseClient


class FakeTransport:
    def __init__(self, script):
        self.script = script
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        for (m, suffix), response in self.script.items():
            if method == m and url.endswith(suffix):
                status, data = response
                return status, json.dumps(data).encode() if data is not None else b""
        raise AssertionError(f"unexpected {method} {url}")


class TimeoutThenSuccessTransport:
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        if len(self.calls) == 1:
            raise TimeoutError("request timed out after the server accepted it")
        return 200, b'{"ok": true}'


def test_ops_command_does_not_retry_after_transport_timeout():
    transport = TimeoutThenSuccessTransport()
    client = ArcticBaseClient(base="http://ab", transport=transport)

    with pytest.raises(TimeoutError, match="server accepted"):
        client.ops_command("context alpha")

    assert len(transport.calls) == 1


def test_read_request_still_retries_after_transport_timeout():
    transport = TimeoutThenSuccessTransport()
    client = ArcticBaseClient(base="http://ab", transport=transport)

    assert client.get_workbench("alpha") == {"ok": True}
    assert len(transport.calls) == 2


def test_arcticbase_client_wraps_workbench_ledger_context_and_ops_events():
    t = FakeTransport({
        ("GET", "/api/workbenches/alpha"): (
            200,
            {"slug": "alpha", "custom_fields": {"refall_subject": "alpha"}},
        ),
        ("POST", "/api/workbenches/alpha/ledger/entries"): (
            201,
            {"id": "led1", "kind": "ops-event"},
        ),
        ("GET", "/api/workbenches/alpha/ledger/entries?kind=ops-event"): (
            200,
            [{"id": "led1", "kind": "ops-event"}],
        ),
        ("GET", "/api/workbenches/alpha/ledger/stats"): (
            200,
            {"total": 1, "by_kind": {"ops-event": 1}},
        ),
        ("POST", "/api/workbenches/alpha/coverage/context"): (
            200,
            {"subject": "alpha", "info_md": "# Alpha\n"},
        ),
        ("GET", "/api/workbenches/alpha/coverage/context"): (
            200,
            {"subject": "alpha", "info_md": "# Alpha\n"},
        ),
        ("PUT", "/api/workbenches/alpha/runtime/manifest"): (
            200,
            {"subject": "alpha", "run_id": "run_1", "manifest_id": "manifest_1"},
        ),
        ("GET", "/api/workbenches/alpha/runtime/manifest"): (
            200,
            {"subject": "alpha", "run_id": "run_1", "manifest_id": "manifest_1"},
        ),
        ("POST", "/api/workbenches/alpha/pending-actions/pa_1/resolve"): (
            200,
            {"id": "pa_1", "status": "done"},
        ),
        ("POST", "/api/refall/ops/events/push"): (200, {"ok": True}),
    })
    client = ArcticBaseClient(base="http://ab", transport=t)

    assert client.get_workbench("alpha")["slug"] == "alpha"
    assert client.append_ledger("alpha", {"kind": "ops-event"})["id"] == "led1"
    assert client.list_ledger("alpha", kind="ops-event")[0]["kind"] == "ops-event"
    assert client.ledger_stats("alpha")["total"] == 1
    assert client.set_coverage_context("alpha", "# Alpha\n")["info_md"] == "# Alpha\n"
    assert client.get_coverage_context("alpha")["info_md"] == "# Alpha\n"
    assert client.put_runtime_manifest("alpha", {"run_id": "run_1"})["manifest_id"] == "manifest_1"
    assert client.get_runtime_manifest("alpha")["run_id"] == "run_1"
    resolved = client.resolve_pending_action("alpha", "pa_1", {"summary": "ok"})
    assert resolved["status"] == "done"
    assert client.push_ops_event({"subject": "alpha", "action": "loop.start"}) == {"ok": True}


def test_arcticbase_client_ops_event_is_optional_when_ops_disabled():
    t = FakeTransport({("POST", "/api/refall/ops/events/push"): (404, {"detail": "disabled"})})
    client = ArcticBaseClient(base="http://ab", transport=t)

    assert client.push_ops_event({"subject": "alpha"}) == {"ok": False, "disabled": True}


def test_arcticbase_client_cancel_pending_action_with_typed_receipt():
    t = FakeTransport({
        ("POST", "/api/workbenches/alpha/pending-actions/pa_1/cancel"): (
            200,
            {"id": "pa_1", "status": "cancelled"},
        ),
    })
    client = ArcticBaseClient(base="http://ab", transport=t)

    cancelled = client.cancel_pending_action(
        "alpha",
        "pa_1",
        {"evidence_refs": ["rte_1"], "summary": "orphan reconciled"},
        receipt_type="watchdog_stop_review",
        resolved_by="refall-watchdog-cron",
    )

    assert cancelled["status"] == "cancelled"
    body = json.loads(t.calls[-1][3])
    assert body == {
        "resolved_by": "refall-watchdog-cron",
        "receipt_type": "watchdog_stop_review",
        "receipt": {"evidence_refs": ["rte_1"], "summary": "orphan reconciled"},
    }
