import json
import ssl
import sys
import urllib.request
import urllib.error

from . import config

_UNVERIFIED = None  # set once if the workbench cert is expired/invalid (its own LAN service)


def _urllib_transport(method, url, headers, body):
    global _UNVERIFIED
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60, context=_UNVERIFIED) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        # The workbench is the operator's own LAN service; an expired/invalid TLS cert should NOT block
        # publishes. Fall back to an unverified context ONCE, with a loud warning. (Real fix: renew the
        # Let's Encrypt wildcard *.gainpalfam.com on the box that terminates TLS.)
        if _UNVERIFIED is None and isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
            print(f"WARN workbench TLS cert invalid ({e.reason}); retrying UNVERIFIED (renew the cert).",
                  file=sys.stderr)
            _UNVERIFIED = ssl.create_default_context()
            _UNVERIFIED.check_hostname = False
            _UNVERIFIED.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=60, context=_UNVERIFIED) as r:
                return r.status, r.read()
        raise


class Workbench:
    """Deterministic write-back to the ref-all workbench. Findings are posted by THIS code,
    never left to the agent to curl."""

    def __init__(self, base=None, slug=None, transport=None):
        self.base = base or config.WB_BASE
        self.slug = slug or config.WB_SLUG
        self.transport = transport or _urllib_transport

    def _post(self, path, body):
        data = json.dumps(body).encode()
        status, raw = self.transport("POST", self.base + path, {"Content-Type": "application/json"}, data)
        if status >= 400:
            raise RuntimeError(f"POST {path} -> {status}: {raw[:300]!r}")
        return json.loads(raw) if raw else {}

    def write_finding(self, title, markdown, description="", tags=None):
        body = {"kind": "md", "title": title, "content": markdown, "description": description}
        if tags:
            body["description"] = (description + "  tags: " + ",".join(tags)).strip()
        data = self._post(f"/api/workbenches/{self.slug}/objects", body)
        oid = data.get("id")
        if not oid:
            raise RuntimeError(f"write_finding: no id in {data!r}")
        return oid

    def log_run(self, oid, payload):
        self._post(f"/api/workbenches/{self.slug}/objects/{oid}/responses", payload)

    def delete(self, oid):
        self.transport("DELETE", f"{self.base}/api/workbenches/{self.slug}/objects/{oid}",
                       {"Content-Type": "application/json"}, None)
