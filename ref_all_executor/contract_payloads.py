from __future__ import annotations

from datetime import UTC, datetime


def _now() -> str:
    return datetime.now(UTC).isoformat()


def task_result_submit(
    *,
    subject: str,
    task_id: str,
    produced_by: str,
    summary: str,
    source_anchors: list[str],
    evidence: list[dict],
    confidence: str = "medium",
    limitations: list[str] | None = None,
    findings: list[dict] | None = None,
    unit_id: str | None = None,
    status: str = "done",
    submission_id: str | None = None,
    artifact_refs: list[str] | None = None,
) -> dict:
    payload = {
        "schema": "refall.submit.v1",
        "type": "task_result_submit",
        "subject": subject,
        "task_id": task_id,
        "status": status,
        "summary": summary,
        "produced_by": produced_by,
        "created_at": _now(),
        "source_anchors": source_anchors,
        "artifact_refs": artifact_refs or [],
        "evidence": evidence,
        "confidence": confidence,
        "limitations": limitations or [],
        "findings": findings or [],
    }
    if unit_id:
        payload["unit_id"] = unit_id
    if submission_id:
        payload["submission_id"] = submission_id
    return payload
