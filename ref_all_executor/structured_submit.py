from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


SUBMIT_RE = re.compile(r"```refall-submit\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)
SUPPORTED_SCHEMA = "refall.submit.v1"
SUPPRESSIVE_STATUSES = {"FALSE_POSITIVE", "DUPLICATE", "CHAINABLE_DEFERRED"}


@dataclass
class SubmitParseResult:
    submissions: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    missing: bool = False

    @property
    def valid(self) -> bool:
        return bool(self.submissions) and not self.errors


ENVELOPE_BACKFILL_FIELDS = ("produced_by", "created_at", "subject", "task_id", "unit_id")


def backfill_submission_envelope(
    payload: dict[str, Any], defaults: dict[str, Any]
) -> dict[str, Any]:
    """Fill bookkeeping the loop owns so an agent can't lose its work over an
    under-specified schema.

    We only supply what the loop legitimately knows (produced_by = the CID/lane,
    created_at = ingest time, subject, task_id/unit_id = the conversation's
    assignment) plus conservative non-evidence defaults (confidence=low,
    limitations=[]). Evidence is NEVER fabricated: if the agent gave
    `source_anchors` but no `evidence`, we restructure those existing anchors
    into evidence entries; with no anchors and no artifacts, evidence stays
    absent and the submission remains (correctly) invalid.
    """
    if not defaults:
        return payload
    patched = dict(payload)
    for key in ENVELOPE_BACKFILL_FIELDS:
        if not patched.get(key) and defaults.get(key):
            patched[key] = defaults[key]
    evidence_bearing = patched.get("type") in {
        "task_result_submit",
        "finding_submit",
        "evidence_delta_submit",
    }
    if evidence_bearing:
        if not patched.get("confidence"):
            patched["confidence"] = "low"
        if "limitations" not in patched:
            patched["limitations"] = []
        if not patched.get("evidence"):
            anchors = [a for a in (patched.get("source_anchors") or []) if isinstance(a, str) and a.strip()]
            if anchors:
                claim = str(patched.get("summary") or "").strip() or "agent submission"
                patched["evidence"] = [
                    {"kind": "source_anchor", "ref": anchor, "claim": claim}
                    for anchor in anchors
                ]
    return patched


def parse_refall_submissions(
    response: str, defaults: dict[str, Any] | None = None
) -> SubmitParseResult:
    blocks = SUBMIT_RE.findall(response or "")
    if not blocks:
        return SubmitParseResult(missing=True, errors=["missing refall-submit block"])
    result = SubmitParseResult()
    for block in blocks:
        try:
            payload = json.loads(block)
        except json.JSONDecodeError as exc:
            result.errors.append(f"malformed refall-submit JSON: {exc}")
            continue
        if not isinstance(payload, dict):
            result.errors.append("refall-submit payload must be an object")
            continue
        if defaults:
            payload = backfill_submission_envelope(payload, defaults)
        result.errors.extend(_validate(payload))
        if not result.errors:
            result.submissions.append(payload)
    return result


def primary_submission(result: SubmitParseResult) -> dict[str, Any]:
    if not result.submissions:
        return {}
    for submission in result.submissions:
        if submission.get("type") == "task_result_submit":
            return submission
    return result.submissions[0]


def _validate(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = ["schema", "type", "subject", "status", "summary", "produced_by", "created_at"]
    for key in required:
        if not payload.get(key):
            errors.append(f"missing required field: {key}")
    if payload.get("schema") != SUPPORTED_SCHEMA:
        errors.append(f"unsupported schema: {payload.get('schema')}")
    if not (payload.get("task_id") or payload.get("unit_id")):
        errors.append("missing task_id or unit_id")
    if payload.get("type") not in {
        "task_result_submit",
        "finding_submit",
        "evidence_delta_submit",
        "control_submit",
        "threat_model_submit",
    }:
        errors.append(f"unsupported submit type: {payload.get('type')}")
    evidence_required = payload.get("type") in {"task_result_submit", "finding_submit", "evidence_delta_submit"}
    if evidence_required:
        if not payload.get("evidence"):
            errors.append("evidence-bearing submission requires evidence")
        if not payload.get("confidence"):
            errors.append("evidence-bearing submission requires confidence")
        if "limitations" not in payload:
            errors.append("evidence-bearing submission requires limitations")
    if payload.get("type") == "threat_model_submit":
        threat_model = payload.get("threat_model")
        if not isinstance(threat_model, dict):
            errors.append("threat_model_submit requires threat_model object")
        elif not any(threat_model.get(key) for key in ("assets", "ingress_points", "trust_boundaries", "threats", "hunt_prompts")):
            errors.append("threat_model_submit requires populated threat model fields")
    errors.extend(_validate_transition_receipt(payload.get("proposed_transition"), payload))
    for finding in payload.get("findings") or []:
        if isinstance(finding, dict):
            errors.extend(_validate_transition_receipt(finding.get("proposed_transition"), finding, payload))
    errors.extend(validate_submission_contract(payload))
    return errors


def validate_submission_contract(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    submit_type = payload.get("type")
    evidence_required = submit_type in {"task_result_submit", "finding_submit", "evidence_delta_submit"}
    if not evidence_required:
        return errors
    if not (payload.get("source_anchors") or payload.get("artifact_refs")):
        errors.append("evidence-bearing submission requires source_anchors or artifact_refs")
    if submit_type in {"task_result_submit", "finding_submit"}:
        parent_evidence = payload.get("evidence") or []
        parent_source_anchors = payload.get("source_anchors") or []
        parent_artifact_refs = payload.get("artifact_refs") or []
        for finding in payload.get("findings") or []:
            if not isinstance(finding, dict):
                continue
            if not (finding.get("code_paths") or finding.get("source_anchors") or finding.get("artifact_refs")):
                errors.append("finding candidate requires code_paths, source_anchors, or artifact_refs")
            if not (
                finding.get("evidence")
                or finding.get("source_anchors")
                or finding.get("artifact_refs")
                or parent_evidence
                or parent_source_anchors
                or parent_artifact_refs
            ):
                errors.append("finding candidate requires evidence")
    return errors


def _validate_transition_receipt(
    proposed: Any,
    owner: dict[str, Any],
    parent: dict[str, Any] | None = None,
) -> list[str]:
    if not isinstance(proposed, dict) or proposed.get("to_status") not in SUPPRESSIVE_STATUSES:
        return []
    receipt_type = owner.get("receipt_type") or proposed.get("receipt_type")
    receipt = owner.get("receipt") or proposed.get("receipt")
    if parent:
        receipt_type = receipt_type or parent.get("receipt_type")
        receipt = receipt or parent.get("receipt")
    if not receipt_type or not receipt:
        return ["suppressive submission requires receipt_type and receipt"]
    return []


def coverage_paths_from_submission(submission: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for anchor in submission.get("source_anchors") or []:
        if isinstance(anchor, str) and anchor.strip():
            paths.append(anchor.split(":", 1)[0])
    for item in submission.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("ref") or item.get("file") or "")
        if ref:
            paths.append(ref.split(":", 1)[0])
    return sorted(set(paths))
