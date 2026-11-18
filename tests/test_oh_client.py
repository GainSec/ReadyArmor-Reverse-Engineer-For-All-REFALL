import json
import pytest
from ref_all_executor.oh_client import OHClient
from ref_all_executor import config


class FakeTransport:
    def __init__(self, script):
        self.script = script
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        assert headers.get("X-Session-API-Key") == "TESTKEY"
        for (m, suffix), resp in self.script.items():
            if method == m and url.endswith(suffix):
                status, data = resp
                return status, json.dumps(data).encode()
        raise AssertionError(f"unexpected {method} {url}")


def make_client(script):
    return OHClient(base="http://x", api_key="TESTKEY", transport=FakeTransport(script))


def test_start_conversation_posts_expected_body_and_returns_id():
    t = FakeTransport({("POST", "/api/conversations"): (201, {"id": "cid-1"})})
    c = OHClient(base="http://x", api_key="TESTKEY", transport=t)
    cid = c.start_conversation(
        workspace=config.local_workspace("/projects/bra"),
        agent_settings=config.LANES["B"],
        text="hello",
        max_iterations=5,
    )
    assert cid == "cid-1"
    sent = json.loads(t.calls[-1][3])
    assert sent["workspace"] == {"kind": "LocalWorkspace", "working_dir": "/projects/bra"}
    assert sent["agent_settings"]["acp_server"] == "codex"
    assert sent["initial_message"]["run"] is True
    assert sent["max_iterations"] == 5


def test_wait_until_done_polls_until_terminal():
    c = make_client({("GET", "/api/conversations/cid-1"): (200, {"execution_status": "finished"})})
    assert c.wait_until_done("cid-1", timeout_s=5, poll_s=0) == "finished"


def test_wait_until_done_treats_missing_conversation_as_stopped():
    c = make_client({("GET", "/api/conversations/cid-1"): (404, {"detail": "Not Found"})})
    assert c.wait_until_done("cid-1", timeout_s=5, poll_s=0) == "stopped"


def test_wait_until_done_treats_not_found_body_as_stopped():
    c = make_client({("GET", "/api/conversations/cid-1"): (200, {"detail": "Not Found"})})
    assert c.wait_until_done("cid-1", timeout_s=5, poll_s=0) == "stopped"


def test_final_response_unwraps_response_field():
    c = make_client({("GET", "/api/conversations/cid-1/agent_final_response"): (200, {"response": "DONE"})})
    assert c.final_response("cid-1") == "DONE"


def test_conversation_info_returns_stats_before_delete():
    payload = {
        "id": "cid-1",
        "execution_status": "finished",
        "stats": {"usage_to_metrics": {"default": {"model_name": "gpt-5.5"}}},
    }
    c = make_client({("GET", "/api/conversations/cid-1"): (200, payload)})
    assert c.conversation_info("cid-1")["stats"]["usage_to_metrics"]["default"]["model_name"] == "gpt-5.5"


def test_conversation_probe_preserves_not_found_status():
    c = OHClient(
        api_key="test",
        transport=lambda *_args: (404, b'{"detail":"Not Found"}'),
        request_backoff_s=0,
    )

    status, data = c.conversation_probe("gone")

    assert status == 404
    assert data == {"detail": "Not Found"}


def test_request_raises_on_5xx():
    c = make_client({("GET", "/api/conversations/cid-1"): (500, {"detail": "boom"})})
    with pytest.raises(RuntimeError):
        c.execution_status("cid-1")


class FlakyTransport:
    """Fails the first `failures` calls, then serves `final`."""

    def __init__(self, failures, final=(200, b'{"execution_status": "finished"}'), exc=None):
        self.failures = failures
        self.final = final
        self.exc = exc
        self.calls = 0

    def __call__(self, method, url, headers, body):
        self.calls += 1
        if self.calls <= self.failures:
            if self.exc is not None:
                raise self.exc
            return 502, b"Bad Gateway: read ECONNRESET"
        return self.final


def test_request_retries_transient_502_then_succeeds():
    t = FlakyTransport(failures=2)
    c = OHClient(base="http://x", api_key="TESTKEY", transport=t,
                 request_backoff_s=0, sleep=lambda _s: None)
    status, data = c.request("GET", "/api/conversations/cid-1")
    assert status == 200
    assert data == {"execution_status": "finished"}
    assert t.calls == 3


def test_request_retries_socket_timeout_then_succeeds():
    t = FlakyTransport(failures=1, exc=TimeoutError("timed out"))
    c = OHClient(base="http://x", api_key="TESTKEY", transport=t,
                 request_backoff_s=0, sleep=lambda _s: None)
    assert c.execution_status("cid-1") == "finished"
    assert t.calls == 2


def test_request_raises_after_attempts_exhausted():
    t = FlakyTransport(failures=99)
    c = OHClient(base="http://x", api_key="TESTKEY", transport=t,
                 request_max_attempts=3, request_backoff_s=0, sleep=lambda _s: None)
    with pytest.raises(RuntimeError, match="502"):
        c.request("GET", "/api/conversations/cid-1")
    assert t.calls == 3


def test_request_reraises_socket_error_after_attempts_exhausted():
    t = FlakyTransport(failures=99, exc=TimeoutError("timed out"))
    c = OHClient(base="http://x", api_key="TESTKEY", transport=t,
                 request_max_attempts=2, request_backoff_s=0, sleep=lambda _s: None)
    with pytest.raises(TimeoutError):
        c.request("GET", "/api/conversations/cid-1")
    assert t.calls == 2


def test_backoff_is_linear_per_attempt():
    slept = []
    t = FlakyTransport(failures=2)
    c = OHClient(base="http://x", api_key="TESTKEY", transport=t,
                 request_backoff_s=3, sleep=slept.append)
    c.request("GET", "/api/conversations/cid-1")
    assert slept == [3, 6]


def test_download_trajectory_returns_empty_on_persistent_failure():
    t = FlakyTransport(failures=99, exc=TimeoutError("timed out"))
    c = OHClient(base="http://x", api_key="TESTKEY", transport=t,
                 request_max_attempts=2, request_backoff_s=0, sleep=lambda _s: None)
    assert c.download_trajectory("cid-1") == b""
