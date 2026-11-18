from __future__ import annotations

import json
from urllib.parse import urlencode

from . import config
from .http_retry import with_retry
from .workbench import _urllib_transport


class ArcticBaseClient:
    def __init__(self, base: str | None = None, transport=None, *, retry: bool = True) -> None:
        self.base = (base or config.WB_BASE).rstrip("/")
        # REFALL AB restarts (launchd kickstart, reload) must not end a run.
        raw = transport or _urllib_transport
        self.raw_transport = raw
        self.transport = with_retry(raw, label="refall-ab") if retry else raw

    def _req(self, method: str, path: str, body: dict | None = None):
        status, raw = self._raw(method, path, body)
        if status >= 400:
            raise RuntimeError(f"{method} {path} -> {status}: {raw[:300]!r}")
        return json.loads(raw) if raw else {}

    def _raw(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        return self.transport(
            method,
            self.base + path,
            {"Content-Type": "application/json"},
            data,
        )

    def _req_once(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        status, raw = self.raw_transport(
            method,
            self.base + path,
            {"Content-Type": "application/json"},
            data,
        )
        if status >= 400:
            raise RuntimeError(f"{method} {path} -> {status}: {raw[:300]!r}")
        return json.loads(raw) if raw else {}

    def create_subject(
        self,
        name: str,
        *,
        source_path: str | None = None,
        title: str | None = None,
        description: str = "",
        tags: list[str] | None = None,
    ):
        body = {
            "subject": name,
            "source_path": source_path,
            "title": title,
            "description": description,
            "tags": tags or [],
        }
        return self._req("POST", "/api/refall/subjects", body)

    def get_workbench(self, slug: str):
        return self._req("GET", f"/api/workbenches/{slug}")

    def patch_workbench(self, slug: str, patch: dict):
        return self._req("PATCH", f"/api/workbenches/{slug}", patch)

    def list_subjects(self):
        workbenches = self._req("GET", "/api/workbenches")
        return [
            wb
            for wb in workbenches
            if "refall" in wb.get("tags", []) or wb.get("custom_fields", {}).get("refall_subject")
        ]

    def mirror_subject(self, name: str):
        return self._req("POST", f"/api/refall/subjects/{name}/mirror-workbench")

    def ops_status(self):
        return self._req("GET", "/api/refall/ops/status")

    def ops_agents(self):
        return self._req("GET", "/api/refall/ops/agents")

    def ops_debug_live(self, slug: str):
        return self._req("GET", f"/api/refall/ops/debug/{slug}/live")

    def ops_command(self, command: str):
        # Named Ops commands can launch long-running, non-idempotent work. If
        # the client times out after the backend accepted the command, retrying
        # can dispatch duplicate context writers or loop cycles. Managers must
        # inspect canonical state after an ambiguous timeout instead.
        return self._req_once("POST", "/api/refall/ops/command", {"command": command})

    def append_ledger(self, slug: str, entry: dict):
        return self._req("POST", f"/api/workbenches/{slug}/ledger/entries", entry)

    def list_ledger(self, slug: str, **filters):
        query = urlencode({k: v for k, v in filters.items() if v is not None})
        suffix = f"?{query}" if query else ""
        return self._req("GET", f"/api/workbenches/{slug}/ledger/entries{suffix}")

    def ledger_stats(self, slug: str):
        return self._req("GET", f"/api/workbenches/{slug}/ledger/stats")

    def coverage_stats(self, slug: str):
        return self._req("GET", f"/api/workbenches/{slug}/coverage/stats")

    def coverage_funnel(self, slug: str):
        return self._req("GET", f"/api/workbenches/{slug}/coverage/funnel")

    def get_source_inventory(self, slug: str):
        return self._req("GET", f"/api/workbenches/{slug}/coverage/source-inventory")

    def get_coverage_context(self, slug: str):
        return self._req("GET", f"/api/workbenches/{slug}/coverage/context")

    def list_wishlist(self, slug: str, **filters):
        query = urlencode({k: v for k, v in filters.items() if v is not None})
        suffix = f"?{query}" if query else ""
        return self._req("GET", f"/api/workbenches/{slug}/coverage/wishlist{suffix}")

    def create_wishlist_item(self, slug: str, item: dict):
        return self._req("POST", f"/api/workbenches/{slug}/coverage/wishlist", item)

    def set_coverage_context(
        self,
        slug: str,
        info_md: str,
        *,
        generated_by: str | None = None,
        root_container: str | None = None,
    ):
        return self._req(
            "POST",
            f"/api/workbenches/{slug}/coverage/context",
            {
                "subject": slug,
                "info_md": info_md,
                "generated_by": generated_by,
                "root_container": root_container,
            },
        )

    def get_threat_model(self, slug: str):
        return self._req("GET", f"/api/workbenches/{slug}/coverage/threat-model")

    def put_threat_model(self, slug: str, threat_model: dict):
        return self._req("PUT", f"/api/workbenches/{slug}/coverage/threat-model", {**dict(threat_model), "subject": slug})

    def transition_finding(self, slug: str, finding_id: str, transition: dict):
        return self._req("POST", f"/api/workbenches/{slug}/findings/{finding_id}/transitions", transition)

    def list_pending_actions(self, slug: str, **filters):
        query = urlencode({k: v for k, v in filters.items() if v is not None})
        suffix = f"?{query}" if query else ""
        return self._req("GET", f"/api/workbenches/{slug}/pending-actions{suffix}")

    def create_pending_action(self, slug: str, action: dict):
        return self._req("POST", f"/api/workbenches/{slug}/pending-actions", action)

    def claim_pending_action(self, slug: str, action_id: str, claimed_by: str = "refall-manager"):
        return self._req(
            "POST",
            f"/api/workbenches/{slug}/pending-actions/{action_id}/claim",
            {"claimed_by": claimed_by},
        )

    def resolve_pending_action(
        self,
        slug: str,
        action_id: str,
        receipt: dict,
        receipt_type: str = "agent_resolution",
        resolved_by: str = "refall-standing-loop",
    ):
        return self._req(
            "POST",
            f"/api/workbenches/{slug}/pending-actions/{action_id}/resolve",
            {
                "resolved_by": resolved_by,
                "receipt_type": receipt_type,
                "receipt": receipt,
            },
        )

    def cancel_pending_action(
        self,
        slug: str,
        action_id: str,
        receipt: dict,
        receipt_type: str | None = None,
        resolved_by: str = "refall-manager",
    ):
        return self._req(
            "POST",
            f"/api/workbenches/{slug}/pending-actions/{action_id}/cancel",
            {
                "resolved_by": resolved_by,
                "receipt_type": receipt_type,
                "receipt": receipt,
            },
        )

    def closeout_gate(self, slug: str):
        return self._req("GET", f"/api/workbenches/{slug}/closeout/gate")

    def capabilities(self, slug: str):
        return self._req("GET", f"/api/workbenches/{slug}/capabilities")

    def request_capability(self, slug: str, request: dict):
        return self._req("POST", f"/api/workbenches/{slug}/capabilities/request", request)

    def authorize_execution(self, slug: str, request: dict):
        return self._req("POST", f"/api/workbenches/{slug}/execution/authorize", request)

    def append_runtime_event(self, slug: str, event: dict):
        return self._req("POST", f"/api/workbenches/{slug}/runtime/events", event)

    def list_runtime_events(self, slug: str):
        return self._req("GET", f"/api/workbenches/{slug}/runtime/events")

    def create_runtime_artifact(self, slug: str, artifact: dict):
        return self._req("POST", f"/api/workbenches/{slug}/runtime/artifacts", artifact)

    def put_runtime_manifest(self, slug: str, manifest: dict):
        return self._req("PUT", f"/api/workbenches/{slug}/runtime/manifest", manifest)

    def get_runtime_manifest(self, slug: str):
        return self._req("GET", f"/api/workbenches/{slug}/runtime/manifest")

    def put_runtime_checkpoint(self, slug: str, checkpoint: dict):
        return self._req("POST", f"/api/workbenches/{slug}/runtime/checkpoints", checkpoint)

    def list_runtime_checkpoints(self, slug: str):
        return self._req("GET", f"/api/workbenches/{slug}/runtime/checkpoints")

    def list_nonfatal_errors(self, slug: str, limit: int = 500):
        return self._req("GET", f"/api/workbenches/{slug}/runtime/nonfatal-errors?limit={int(limit)}")

    def resume_preflight(self, slug: str, input_hashes: dict):
        return self._req("POST", f"/api/workbenches/{slug}/runtime/resume-preflight", {"input_hashes": input_hashes})

    def push_ops_event(self, event: dict):
        status, raw = self._raw("POST", "/api/refall/ops/events/push", event)
        if status in {403, 404}:
            return {"ok": False, "disabled": True}
        if status >= 400:
            raise RuntimeError(f"POST /api/refall/ops/events/push -> {status}: {raw[:300]!r}")
        return json.loads(raw) if raw else {"ok": True}
