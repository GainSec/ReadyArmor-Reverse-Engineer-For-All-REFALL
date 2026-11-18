from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def stable_id(prefix: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(raw).hexdigest()[:24]}"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class RefallContract(BaseModel):
    model_config = ConfigDict(extra="allow")


class EvidenceReceipt(RefallContract):
    receipt_type: str
    evidence_refs: list[str] = Field(default_factory=list)
    source_anchors: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    source_hashes: dict[str, str] = Field(default_factory=dict)
    commands: list[str] = Field(default_factory=list)
    negative_tests: list[str] = Field(default_factory=list)
    summary: str = ""

    @model_validator(mode="after")
    def require_material(self) -> "EvidenceReceipt":
        if not any([
            self.evidence_refs,
            self.source_anchors,
            self.artifact_refs,
            self.commands,
            self.negative_tests,
        ]):
            raise ValueError(
                "receipt requires evidence_refs, source_anchors, artifact_refs, commands, or negative_tests"
            )
        return self


class ContextPackage(RefallContract):
    subject: str
    info_md: str
    context_id: str | None = None
    generated_by: str | None = None
    root_container: str | None = None
    source_inventory_id: str | None = None
    scope_overlay_id: str | None = None
    threat_model_id: str | None = None
    operator_input: str = ""
    created_at: str = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def set_id(self) -> "ContextPackage":
        if not self.context_id:
            self.context_id = stable_id("ctx", {
                "subject": self.subject,
                "info_md": self.info_md,
                "source_inventory_id": self.source_inventory_id,
                "scope_overlay_id": self.scope_overlay_id,
                "threat_model_id": self.threat_model_id,
            })
        return self


class SourceInventoryPackage(RefallContract):
    subject: str
    root: str
    inventory_id: str | None = None
    files: list[dict[str, Any]] = Field(default_factory=list)
    skipped: list[dict[str, Any]] = Field(default_factory=list)
    observations: list[dict[str, Any]] = Field(default_factory=list)
    git: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def set_id(self) -> "SourceInventoryPackage":
        if not self.inventory_id:
            self.inventory_id = stable_id("inv", {
                "subject": self.subject,
                "root": self.root,
                "files": sorted(
                    (
                        {
                            "path": item.get("path"),
                            "sha256": item.get("sha256"),
                            "size_bytes": item.get("size_bytes"),
                            "total_lines": item.get("total_lines"),
                        }
                        for item in self.files
                    ),
                    key=lambda item: str(item.get("path") or ""),
                ),
            })
        return self


class ScopeOverlay(RefallContract):
    subject: str
    overlay_id: str | None = None
    local_roots: list[str] = Field(default_factory=list)
    lan_targets: list[dict[str, Any]] = Field(default_factory=list)
    external_targets: list[dict[str, Any]] = Field(default_factory=list)
    excluded_paths: list[dict[str, Any]] = Field(default_factory=list)
    evidence_rules: list[str] = Field(default_factory=list)
    operator_notes: str = ""
    dynamic_testing: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def set_id(self) -> "ScopeOverlay":
        if not self.overlay_id:
            self.overlay_id = stable_id("scope", {
                "subject": self.subject,
                "local_roots": self.local_roots,
                "lan_targets": self.lan_targets,
                "external_targets": self.external_targets,
                "excluded_paths": self.excluded_paths,
                "evidence_rules": self.evidence_rules,
                "operator_notes": self.operator_notes,
                "dynamic_testing": self.dynamic_testing,
            })
        return self


class ThreatModelPackage(RefallContract):
    subject: str
    threat_model_id: str | None = None
    assets: list[dict[str, Any]] = Field(default_factory=list)
    ingress_points: list[dict[str, Any]] = Field(default_factory=list)
    trust_boundaries: list[dict[str, Any]] = Field(default_factory=list)
    threats: list[dict[str, Any]] = Field(default_factory=list)
    hunt_prompts: list[str] = Field(default_factory=list)
    status: Literal["active", "skipped", "superseded"] = "active"
    created_by: str | None = None
    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def set_id(self) -> "ThreatModelPackage":
        if not self.threat_model_id:
            self.threat_model_id = stable_id("tm", {
                "subject": self.subject,
                "assets": self.assets,
                "ingress_points": self.ingress_points,
                "trust_boundaries": self.trust_boundaries,
                "threats": self.threats,
                "hunt_prompts": self.hunt_prompts,
                "status": self.status,
            })
        return self


class TaskManifest(RefallContract):
    subject: str
    task_id: str
    task_class: str
    lane: str | None = None
    unit_id: str | None = None
    run_id: str | None = None
    objective: str = ""
    context_id: str | None = None
    source_inventory_id: str | None = None
    scope_overlay_id: str | None = None
    threat_model_id: str | None = None
    required_outputs: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_utc_now)


class FindingCandidate(RefallContract):
    title: str
    description: str = ""
    impact: str = ""
    severity: str = "INFO"
    vuln_class: str = ""
    status: Literal["PROVISIONALLY_VALID", "NEEDS_RESEARCH"] = "PROVISIONALLY_VALID"
    quality_tier: Literal["HYPOTHESIS", "CODE_CONFIRMED", "LIVE_CONFIRMED"] = "HYPOTHESIS"
    code_paths: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    source_anchors: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    confidence: str = ""
    limitations: list[str] = Field(default_factory=list)
    duplicate_of: str | None = None
    related_locations: list[dict[str, Any]] = Field(default_factory=list)
    proposed_transition: dict[str, Any] | None = None

    @model_validator(mode="after")
    def require_location_and_evidence(self) -> "FindingCandidate":
        if not (self.code_paths or self.source_anchors or self.artifact_refs):
            raise ValueError("finding candidate requires code_paths, source_anchors, or artifact_refs")
        if not (self.evidence or self.source_anchors or self.artifact_refs):
            raise ValueError("finding candidate requires evidence")
        return self


class VerificationResult(RefallContract):
    subject: str
    finding_id: str
    status: Literal[
        "not_attempted",
        "static_only",
        "runtime_blocked",
        "runtime_viable",
        "reproduced",
        "live_reproduced",
        "failed",
    ] = "not_attempted"
    verified_by: str | None = None
    evidence_receipt: EvidenceReceipt | None = None
    limitations: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_utc_now)


class RunManifest(RefallContract):
    subject: str
    workbench: str
    run_id: str
    manifest_id: str | None = None
    refall_version: str | None = None
    provider_roles: dict[str, Any] = Field(default_factory=dict)
    runtime_host: dict[str, Any] = Field(default_factory=dict)
    config_hashes: dict[str, str] = Field(default_factory=dict)
    source_hashes: dict[str, str] = Field(default_factory=dict)
    source_inventory_id: str | None = None
    scope_overlay_id: str | None = None
    threat_model_id: str | None = None
    capability_grant_ids: list[str] = Field(default_factory=list)
    capability_request_ids: list[str] = Field(default_factory=list)
    checkpoint_ids: list[str] = Field(default_factory=list)
    output_object_ids: list[str] = Field(default_factory=list)
    git: dict[str, Any] = Field(default_factory=dict)
    dynamic_testing: dict[str, Any] = Field(default_factory=dict)
    stage_status: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def set_id(self) -> "RunManifest":
        if not self.manifest_id:
            self.manifest_id = stable_id("manifest", {
                "subject": self.subject,
                "workbench": self.workbench,
                "run_id": self.run_id,
            })
        return self


class CloseoutPackage(RefallContract):
    subject: str
    run_id: str | None = None
    closeout_id: str | None = None
    manifest_id: str | None = None
    passed: bool = False
    checks: list[dict[str, Any]] = Field(default_factory=list)
    report_object_ids: list[str] = Field(default_factory=list)
    override_receipts: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def set_id(self) -> "CloseoutPackage":
        if not self.closeout_id:
            self.closeout_id = stable_id("closeout", {
                "subject": self.subject,
                "run_id": self.run_id,
                "manifest_id": self.manifest_id,
                "checks": self.checks,
            })
        return self
