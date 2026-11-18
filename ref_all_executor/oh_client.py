import json
import os
import time
import urllib.request
import urllib.error

from . import config

TERMINAL = {"finished", "error", "stopped", "paused"}


def _urllib_transport(method, url, headers, body):
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# The agent-server backend can drop out from under the static proxy (OOM kill,
# restart), which surfaces as a 5xx or a raw socket timeout. Those are transient:
# retry instead of letting the exception unwind the whole standing loop.
TRANSIENT_EXC = (urllib.error.URLError, TimeoutError, ConnectionError, OSError)
REQUEST_MAX_ATTEMPTS = int(os.environ.get("REFALL_OH_REQUEST_MAX_ATTEMPTS", "4"))
REQUEST_BACKOFF_S = float(os.environ.get("REFALL_OH_REQUEST_BACKOFF_S", "3"))


class OHClient:
    """Agent Server client. Conversations run on the subscription ACP brains
    (codex / claude-code) or, via workspace, on remote hosts. This is where the
    Codex/Claude subscriptions are actually spent — NOT the automation litellm path."""

    def __init__(self, base=None, api_key=None, transport=None, *,
                 request_max_attempts=None, request_backoff_s=None, sleep=None):
        self.base = base or config.OH_BASE
        self._api_key = api_key
        self.transport = transport or _urllib_transport
        self.request_max_attempts = (
            REQUEST_MAX_ATTEMPTS if request_max_attempts is None else request_max_attempts
        )
        self.request_backoff_s = (
            REQUEST_BACKOFF_S if request_backoff_s is None else request_backoff_s
        )
        self.sleep = sleep or time.sleep

    @property
    def api_key(self):
        if self._api_key is None:
            self._api_key = config.session_api_key()
        return self._api_key

    def request(self, method, path, body=None):
        url = self.base + path
        data = json.dumps(body).encode() if body is not None else None
        headers = {"X-Session-API-Key": self.api_key, "Content-Type": "application/json"}
        status, raw = self._transport_with_retry(method, url, headers, data)
        if status >= 500:
            raise RuntimeError(f"{method} {path} -> {status}: {raw[:300]!r}")
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw
        return status, parsed

    def _transport_with_retry(self, method, url, headers, data):
        """Call the transport, retrying 5xx and socket errors with linear backoff.

        On the final attempt the outcome is passed through unchanged: a 5xx is
        returned so the caller raises its usual RuntimeError, and a raw socket
        error is re-raised. Transient backend drops (OOM kill, restart) are
        therefore survivable instead of unwinding the whole standing loop.
        """
        attempts = max(1, self.request_max_attempts)
        for attempt in range(1, attempts + 1):
            last = attempt >= attempts
            try:
                status, raw = self.transport(method, url, headers, data)
            except TRANSIENT_EXC:
                if last:
                    raise
            else:
                if status < 500 or last:
                    return status, raw
            if self.request_backoff_s:
                self.sleep(self.request_backoff_s * attempt)
        raise RuntimeError(f"{method} {url} exhausted {attempts} attempts")  # pragma: no cover

    def start_conversation(self, workspace, agent_settings, text, max_iterations=30):
        """workspace: a dict from config.local_workspace()/remote_workspace()."""
        body = {
            "workspace": workspace,
            "agent_settings": agent_settings,
            "initial_message": {
                "role": "user",
                "content": [{"type": "text", "text": text}],
                "run": True,
            },
            "max_iterations": max_iterations,
        }
        status, data = self.request("POST", "/api/conversations", body)
        if status != 201 or not isinstance(data, dict) or "id" not in data:
            raise RuntimeError(f"start_conversation failed {status}: {data!r}")
        return data["id"]

    def run(self, cid):
        self.request("POST", f"/api/conversations/{cid}/run", {})

    def execution_status(self, cid):
        status, data = self.request("GET", f"/api/conversations/{cid}")
        if status == 404:
            return "stopped"
        if isinstance(data, dict) and data.get("detail") == "Not Found":
            return "stopped"
        return (data or {}).get("execution_status")

    def conversation_info(self, cid):
        _, data = self.request("GET", f"/api/conversations/{cid}")
        return data or {}

    def conversation_probe(self, cid):
        """Return the HTTP status as well as conversation data.

        Callers that reconcile external state must distinguish a definitive 404
        from a transient request failure.  ``conversation_info`` intentionally
        keeps its historical data-only contract for ordinary loop callers.
        """
        return self.request("GET", f"/api/conversations/{cid}")

    def wait_until_done(self, cid, timeout_s=1800, poll_s=3):
        deadline = time.monotonic() + timeout_s
        while True:
            status = self.execution_status(cid)
            if status in TERMINAL:
                return status
            if time.monotonic() > deadline:
                raise TimeoutError(f"conversation {cid} not terminal after {timeout_s}s (last={status})")
            if poll_s:
                time.sleep(poll_s)

    def final_response(self, cid):
        _, data = self.request("GET", f"/api/conversations/{cid}/agent_final_response")
        return (data or {}).get("response", "") if isinstance(data, dict) else ""

    def download_trajectory(self, cid):
        path = f"/api/file/download-trajectory/{cid}"
        try:
            status, raw = self._transport_with_retry(
                "GET", f"{self.base}{path}", {"X-Session-API-Key": self.api_key}, None,
            )
        except TRANSIENT_EXC:
            return b""
        return raw if status == 200 else b""

    def delete(self, cid):
        self.request("DELETE", f"/api/conversations/{cid}")
