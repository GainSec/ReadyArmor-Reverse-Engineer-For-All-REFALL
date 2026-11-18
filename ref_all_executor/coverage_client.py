import json
import os
import urllib.request
import urllib.error
from urllib.parse import quote, urlencode

from . import config
from .http_retry import with_retry


def _urllib_transport(method, url, headers, body):
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class CoverageClient:
    """Client for REFALL coverage.

    Default mode is ArcticBase workbench-native coverage. Pass ``mode="legacy"``
    or a legacy ``base=`` to use the old standalone coverage service.
    """

    def __init__(
        self,
        base=None,
        transport=None,
        workbench_base=None,
        workbench_slug=None,
        mode=None,
        retry=True,
    ):
        # The coverage surface is served by REFALL AB in workbench mode, so a
        # REFALL AB restart must not end a run mid-claim.
        raw_transport = transport or _urllib_transport
        self.transport = with_retry(raw_transport, label="refall-coverage") if retry else raw_transport
        self.workbench_slug = workbench_slug or os.environ.get("REFALL_COVERAGE_WORKBENCH_SLUG", "")
        explicit_mode = mode or os.environ.get("REFALL_COVERAGE_MODE") or config.COVERAGE_MODE
        self.legacy = explicit_mode == "legacy" or (base is not None and workbench_base is None and not self.workbench_slug)
        if self.legacy:
            self.base = (base or config.COVERAGE_BASE).rstrip("/")
        else:
            self.base = (workbench_base or os.environ.get("REFALL_WORKBENCH_BASE") or config.resolve_public_base()).rstrip("/")
        self.prefix = ""

    def _prefix(self, subject=None):
        if self.legacy:
            return ""
        slug = self.workbench_slug or subject
        if not slug:
            raise ValueError("workbench coverage calls require subject or workbench_slug")
        return f"/api/workbenches/{quote(slug)}/coverage"

    def _req(self, method, path, body=None, subject=None):
        data = json.dumps(body).encode() if body is not None else None
        status, raw = self.transport(
            method,
            self.base + self._prefix(subject) + path,
            {"Content-Type": "application/json"},
            data,
        )
        if status >= 400:
            raise RuntimeError(f"{method} {path} -> {status}: {raw[:200]!r}")
        return json.loads(raw) if raw else {}

    def enumerate(self, subject, files):
        return self._req("POST", "/enumerate", {"subject": subject, "files": files}, subject)

    def claim_next(self, subject, agent, lease_s=900):
        path = "/claim_next" if self.legacy else "/claim"
        return self._req("POST", path, {"subject": subject, "agent": agent, "lease_s": lease_s}, subject)

    def submit(self, unit_id, agent, summary, evidence, **kw):
        subject = kw.pop("subject", None)
        body = {"unit_id": unit_id, "agent": agent, "summary": summary, "evidence": evidence}
        body.update(kw)
        return self._req("POST", "/submit", body, subject=subject)

    def coverage(self, subject):
        if not self.legacy:
            return self._req("GET", "/stats", subject=subject)
        return self._req("GET", f"/coverage?subject={quote(subject)}")

    def gate(self, subject, threshold=0.95):
        if not self.legacy:
            return self._req("GET", f"/gate?threshold={threshold}", subject=subject)
        return self._req("GET", f"/gate?subject={quote(subject)}&threshold={threshold}")

    def search(self, subject, **filters):
        filters = {k: v for k, v in filters.items() if v is not None}
        if not self.legacy:
            return self._req("GET", f"/search?{urlencode(filters)}", subject=subject)
        return self._req("GET", f"/search?subject={subject}&{urlencode(filters)}")

    # ---- plan / findings (juicy path) ----
    def plan_progress(self, subject):
        if not self.legacy:
            return self._req("GET", "/plan", subject=subject)
        return self._req("GET", f"/plan_progress?subject={quote(subject)}")

    def findings_summary(self, subject):
        if not self.legacy:
            return self._req("GET", "/findings/summary", subject=subject)
        return self._req("GET", f"/findings_summary?subject={quote(subject)}")

    def findings(self, subject, status=None):
        q = {"subject": subject}
        if status:
            q["status"] = status
        if not self.legacy:
            q.pop("subject", None)
            suffix = f"?{urlencode(q)}" if q else ""
            return self._req("GET", f"/findings{suffix}", subject=subject)
        return self._req("GET", f"/findings?{urlencode(q)}")

    def add_finding(self, subject, finding):
        if not self.legacy:
            body = {"subject": subject, **dict(finding)}
            return self._req("POST", "/findings", body, subject=subject)
        payload = dict(finding)
        payload.setdefault("subject", subject)
        return self._req("POST", "/finding", {"finding": payload}, subject=subject)

    def funnel(self, subject):
        if not self.legacy:
            return self._req("GET", "/funnel", subject=subject)
        return self._req("GET", f"/funnel?subject={quote(subject)}")

    def set_surface(self, subject, dimension, items, covered=None):
        """Register a non-code coverage surface (behavioral/cartography subjects). One unit per
        enumerable target; `covered` are marked done. Makes coverage % real for subjects with no
        source-line surface. Call at seed time (items) and as items get covered (covered)."""
        return self._req("POST", "/surface", {"subject": subject, "dimension": dimension,
                                              "items": list(items), "covered": list(covered or [])}, subject)

    def put_plan(self, subject, investigations, pass_number=1, replace=True):
        return self._req("POST", "/plan", {"subject": subject, "investigations": investigations,
                                           "pass_number": pass_number, "replace": replace}, subject)

    def update_finding_validation(self, finding_id, agent, **fields):
        body = {"finding_id": finding_id, "agent": agent}
        body.update({k: v for k, v in fields.items() if v is not None})
        subject = fields.get("subject")
        return self._req("POST", "/finding_validation", body, subject=subject)

    def get_context(self, subject):
        if not self.legacy:
            return self._req("GET", "/context", subject=subject)
        return self._req("GET", f"/context?subject={quote(subject)}")

    def set_context(self, subject, info_md, generated_by=None, root_container=None):
        return self._req("POST", "/context", {"subject": subject, "info_md": info_md,
                                              "generated_by": generated_by, "root_container": root_container}, subject)

    def put_source_inventory(self, subject, inventory):
        if self.legacy:
            return {}
        payload = {"subject": subject, **dict(inventory)}
        return self._req("PUT", "/source-inventory", payload, subject)

    def get_source_inventory(self, subject):
        if self.legacy:
            return {}
        return self._req("GET", "/source-inventory", subject=subject)

    def put_scope_overlay(self, subject, overlay):
        if self.legacy:
            return {}
        payload = {"subject": subject, **dict(overlay)}
        return self._req("PUT", "/scope-overlay", payload, subject)

    def get_scope_overlay(self, subject):
        if self.legacy:
            return {}
        return self._req("GET", "/scope-overlay", subject=subject)

    def put_threat_model(self, subject, threat_model):
        if self.legacy:
            return {}
        payload = {**dict(threat_model), "subject": subject}
        return self._req("PUT", "/threat-model", payload, subject)

    def get_threat_model(self, subject):
        if self.legacy:
            return {}
        return self._req("GET", "/threat-model", subject=subject)

    def wishlist(self, subject, status=None):
        q = {"subject": subject}
        if status:
            q["status"] = status
        if not self.legacy:
            q.pop("subject", None)
            suffix = f"?{urlencode(q)}" if q else ""
            return self._req("GET", f"/wishlist{suffix}", subject=subject)
        return self._req("GET", f"/wishlist?{urlencode(q)}")
