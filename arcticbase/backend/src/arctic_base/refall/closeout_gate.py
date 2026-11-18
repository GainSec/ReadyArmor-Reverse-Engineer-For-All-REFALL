from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from arctic_base.refall import ledger
from arctic_base.refall.coverage_store import store_for_workbench
from arctic_base.refall.runtime_state import connect_runtime, list_artifacts, list_events
from arctic_base.storage.filesystem import FilesystemStorage


def evaluate_closeout_gate(
    storage: FilesystemStorage,
    slug: str,
    *,
    threshold: float = 0.95,
) -> dict[str, Any]:
    store = store_for_workbench(storage, slug)
    coverage = store.coverage(slug)
    findings = store.list_findings(slug, limit=10000)
    pending = store.list_pending_actions(slug, include_terminal=True)
    transitions = store.list_transitions(slug)
    entries = ledger.list_entries(storage, slug)
    subject_path = _subject_path(storage, slug)
    runtime_events, runtime_artifacts = _runtime_records(subject_path, slug)
    overrides = _closeout_overrides(entries)
    checks: list[dict[str, Any]] = []

    open_pending = [
        action for action in pending
        if action.get("status") in {"open", "claimed"}
    ]
    deferred_missing_receipt = [
        action for action in pending
        if action.get("status") == "deferred" and not action.get("resolution_receipt")
    ]
    checks.append(_check("pending-actions-open", not open_pending, True, open_pending))
    checks.append(_check("pending-actions-deferred-receipts", not deferred_missing_receipt, True, deferred_missing_receipt))
    resume_drift_pending = [
        action for action in open_pending
        if action.get("kind") == "resume_drift_decision"
    ]
    checks.append({
        "id": "resume-drift-decision",
        "status": "warn" if resume_drift_pending else "not_applicable",
        "count": len(resume_drift_pending),
        "blocking": False,
        "details": [action.get("id") for action in resume_drift_pending],
    })

    refused = [transition for transition in transitions if transition.get("status") == "refused"]
    checks.append(_check("refused-transitions-unresolved", not refused, True, refused))

    valid_missing_proof = [
        finding for finding in findings
        if str(finding.get("status") or "").upper() in {"VALID", "VALIDATED"}
        and str(finding.get("repro_status") or "").lower() not in {"reproduced", "live_reproduced"}
        and str(finding.get("quality_tier") or "") != "LIVE_CONFIRMED"
    ]
    checks.append(_check("valid-findings-missing-proof", not valid_missing_proof, True, valid_missing_proof))

    false_positive_ids = _accepted_transition_finding_ids(transitions, "FALSE_POSITIVE")
    false_positive_missing = [
        finding for finding in findings
        if finding.get("status") == "FALSE_POSITIVE" and finding.get("id") not in false_positive_ids
    ]
    checks.append(_check("false-positive-without-receipt", not false_positive_missing, True, false_positive_missing))

    duplicate_ids = _accepted_transition_finding_ids(transitions, "DUPLICATE")
    duplicate_missing = [
        finding for finding in findings
        if finding.get("status") == "DUPLICATE"
        and (finding.get("id") not in duplicate_ids or not finding.get("duplicate_of"))
    ]
    checks.append(_check("duplicate-without-receipt", not duplicate_missing, True, duplicate_missing))

    chainable = [finding for finding in findings if finding.get("status") == "CHAINABLE_DEFERRED"]
    checks.append({
        "id": "chainable-deferred-internal-only",
        "status": "warn" if chainable else "not_applicable",
        "count": len(chainable),
        "blocking": False,
        "details": [item.get("id") for item in chainable],
    })

    expired_claims = store.expired_claimed_units(slug)
    checks.append(_check("coverage-claims-expired", not expired_claims, True, expired_claims))

    context = store.get_context(slug)
    checks.append(_check("context-present", bool(context and str(context.get("info_md") or "").strip()), True, []))

    report_check = _report_check(storage, slug, entries)
    checks.append(report_check)

    resolved = (coverage.get("resolved_pct", 0) or 0) / 100.0
    checks.append({
        "id": "coverage-threshold",
        "status": "pass" if resolved >= threshold else "warn",
        "count": coverage.get("lines_covered", 0),
        "blocking": False,
        "details": [f"{coverage.get('resolved_pct', 0)}% resolved below {threshold * 100:.1f}%"] if resolved < threshold else [],
    })

    high_without_visual = [
        finding for finding in findings
        if str(finding.get("severity") or "").upper() in {"HIGH", "CRITICAL"}
        and not _visual_evidence_available(finding, entries, runtime_artifacts)
    ]
    checks.append({
        "id": "visual-evidence-high-impact",
        "status": "warn" if high_without_visual else "not_applicable",
        "count": len(high_without_visual),
        "blocking": False,
        "details": [item.get("id") for item in high_without_visual],
    })

    toolchain_needed = [
        finding for finding in findings
        if str(finding.get("severity") or "").upper() in {"HIGH", "CRITICAL"}
        or bool(finding.get("code_paths"))
    ]
    toolchain_seen = _toolchain_has_run(entries, runtime_artifacts)
    checks.append({
        "id": "codebadger-toolchain-not-run",
        "status": "pass" if toolchain_seen else "warn" if toolchain_needed else "not_applicable",
        "count": 0 if toolchain_seen else len(toolchain_needed),
        "blocking": False,
        "details": [item.get("id") for item in toolchain_needed] if toolchain_needed and not toolchain_seen else [],
    })

    vendor_report = _vendor_cna_report(storage, slug, entries)
    checks.append({
        "id": "vendor-cna-report-generated",
        "status": "pass" if vendor_report else "warn",
        "count": 1 if vendor_report else 0,
        "blocking": False,
        "details": [vendor_report] if vendor_report else ["missing"],
    })

    scope_blockers = _external_scope_blockers(entries, runtime_events)
    checks.append({
        "id": "external-validation-scope-blocked",
        "status": "warn" if scope_blockers else "not_applicable",
        "count": len(scope_blockers),
        "blocking": False,
        "details": scope_blockers,
    })

    checks.extend(_informational_checks(coverage, findings, entries, runtime_events, runtime_artifacts))

    checks = [_apply_override(check, overrides) for check in checks]
    blockers = [check for check in checks if check.get("blocking") and check.get("status") == "fail"]
    return {
        "subject": slug,
        "passed": not blockers,
        "severity": "blocker" if blockers else "pass",
        "checks": checks,
        "summary": {
            "coverage_resolved_pct": coverage.get("resolved_pct", 0),
            "findings_total": len(findings),
            "pending_actions_open": len(open_pending),
            "pending_actions_deferred": len([a for a in pending if a.get("status") == "deferred"]),
            "unvalidated_findings": len(valid_missing_proof),
            "refused_transitions": len(refused),
            "ledger_entries": len(entries),
            "closeout_overrides": len(overrides),
            "runtime_events": len(runtime_events),
            "runtime_artifacts": len(runtime_artifacts),
        },
    }


def _accepted_transition_finding_ids(transitions: list[dict], to_status: str) -> set[str]:
    return {
        str(item.get("finding_id"))
        for item in transitions
        if item.get("status") == "accepted" and item.get("to_status") == to_status
    }


def _check(check_id: str, passed: bool, blocking: bool, details: list[dict]) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "pass" if passed else "fail",
        "count": 0 if passed else len(details),
        "blocking": blocking,
        "details": [item.get("id") or item for item in details],
    }


def _report_check(storage: FilesystemStorage, slug: str, entries: list[dict]) -> dict[str, Any]:
    try:
        workbench = storage.get_workbench(slug)
    except Exception:
        return _check("report-current", False, True, [{"id": "workbench-missing"}])
    current_id = workbench.custom_fields.get("refall_current_report_object_id")
    if not current_id:
        return _check("report-current", False, True, [{"id": "missing"}])
    try:
        meta = storage.get_object(slug, current_id)
    except Exception:
        return _check("report-current", False, True, [{"id": current_id}])
    latest_entry = _latest_entry_time(entries)
    if latest_entry and meta.updated_at < latest_entry:
        return {
            "id": "report-stale",
            "status": "fail",
            "count": 1,
            "blocking": True,
            "details": [current_id],
        }
    return {
        "id": "report-current",
        "status": "pass",
        "count": 0,
        "blocking": True,
        "details": [current_id],
    }


def _subject_path(storage: FilesystemStorage, slug: str) -> Path:
    try:
        workbench = storage.get_workbench(slug)
    except Exception:
        return storage.root / "workbenches" / slug
    raw = workbench.custom_fields.get("refall_subject_path") or workbench.local_path
    return Path(raw) if raw else storage.root / "workbenches" / slug


def _runtime_records(subject_path: Path, slug: str) -> tuple[list[dict], list[dict]]:
    try:
        conn = connect_runtime(subject_path)
        return list_events(conn, slug, limit=5000), list_artifacts(conn, slug, limit=5000)
    except Exception:
        return [], []


def _visual_evidence_available(finding: dict, entries: list[dict], artifacts: list[dict]) -> bool:
    local_refs = " ".join(
        str(ref)
        for ref in (
            (finding.get("history") or [])
            + (finding.get("code_paths") or [])
            + (finding.get("artifact_refs") or [])
        )
    ).lower()
    if any(token in local_refs for token in ("visual", "screenshot", "codebadger", "codecharta", "codegraph", "graph")):
        return True
    finding_id = str(finding.get("id") or "")
    for entry in entries:
        haystack = " ".join(
            str(entry.get(key) or "")
            for key in ("action", "title", "summary", "artifact_refs", "finding_id", "source_finding_id")
        ).lower()
        if finding_id and finding_id not in haystack:
            continue
        if any(token in haystack for token in ("visual", "screenshot", "codebadger", "codecharta", "codegraph", "graph")):
            return True
    for artifact in artifacts:
        haystack = " ".join(str(artifact.get(key) or "") for key in ("kind", "path", "mime", "source_event_id")).lower()
        if any(token in haystack for token in ("visual", "screenshot", "codebadger", "codecharta", "codegraph", "graph")):
            return True
    return False


def _toolchain_has_run(entries: list[dict], artifacts: list[dict]) -> bool:
    tokens = ("codebadger", "codecharta", "codegraph", "joern", "graphviz")
    for entry in entries:
        haystack = " ".join(str(entry.get(key) or "") for key in ("kind", "action", "title", "summary", "artifact_refs")).lower()
        if any(token in haystack for token in tokens):
            return True
    for artifact in artifacts:
        haystack = " ".join(str(artifact.get(key) or "") for key in ("kind", "path", "mime", "workbench_object_id")).lower()
        if any(token in haystack for token in tokens):
            return True
    return False


def _vendor_cna_report(storage: FilesystemStorage, slug: str, entries: list[dict]) -> dict[str, Any] | None:
    try:
        workbench = storage.get_workbench(slug)
    except Exception:
        workbench = None
    if workbench:
        for key in ("refall_vendor_cna_report_object_id", "refall_vendor_report_object_id"):
            object_id = workbench.custom_fields.get(key)
            if object_id:
                return {"source": "workbench", "object_id": object_id}
    try:
        objects = storage.list_objects(slug, drawer="Report", include_archived=False)
    except Exception:
        objects = []
    for obj in objects:
        haystack = f"{obj.title} {obj.description} {obj.filename}".lower()
        if "cna" in haystack or ("vendor" in haystack and "report" in haystack):
            return {"source": "object", "object_id": obj.id, "title": obj.title}
    for entry in entries:
        haystack = " ".join(str(entry.get(key) or "") for key in ("kind", "action", "title", "summary")).lower()
        if "report" in haystack and ("vendor" in haystack or "cna" in haystack):
            return {"source": "ledger", "ledger_id": entry.get("id")}
    return None


def _external_scope_blockers(entries: list[dict], events: list[dict]) -> list[dict]:
    blockers: list[dict] = []
    for entry in entries:
        haystack = " ".join(str(entry.get(key) or "") for key in ("action", "event_type", "status", "failure_class", "summary")).lower()
        if "scope_blocked" in haystack or ("external" in haystack and "blocked" in haystack):
            blockers.append({
                "source": "ledger",
                "id": entry.get("id"),
                "summary": entry.get("summary") or entry.get("title") or "scope blocked",
            })
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        haystack = " ".join(
            str(value or "")
            for value in (
                event.get("type"),
                payload.get("status"),
                payload.get("failure_class"),
                payload.get("summary"),
                payload.get("error"),
            )
        ).lower()
        if "scope_blocked" in haystack or ("external" in haystack and "blocked" in haystack):
            blockers.append({
                "source": "runtime",
                "id": event.get("id"),
                "summary": payload.get("summary") or payload.get("error") or event.get("type"),
            })
    return blockers


def _informational_checks(
    coverage: dict,
    findings: list[dict],
    entries: list[dict],
    events: list[dict],
    artifacts: list[dict],
) -> list[dict[str, Any]]:
    finding_status = Counter(str(item.get("status") or "unknown") for item in findings)
    ledger_kind = Counter(str(item.get("kind") or "unknown") for item in entries)
    artifact_kind = Counter(str(item.get("kind") or "unknown") for item in artifacts)
    runtime_type = Counter(str(item.get("type") or "unknown") for item in events)
    return [
        {
            "id": "coverage-units-total",
            "status": "info",
            "count": int(coverage.get("files_total") or 0) + int(coverage.get("symbols_total") or 0),
            "blocking": False,
            "details": [{
                "files_total": coverage.get("files_total", 0),
                "files_done": coverage.get("files_done", 0),
                "symbols_total": coverage.get("symbols_total", 0),
                "lines_total": coverage.get("lines_total", 0),
                "lines_covered": coverage.get("lines_covered", 0),
                "resolved_pct": coverage.get("resolved_pct", 0),
            }],
        },
        {
            "id": "findings-by-status",
            "status": "info",
            "count": len(findings),
            "blocking": False,
            "details": [dict(finding_status)],
        },
        {
            "id": "ledger-entries-by-kind",
            "status": "info",
            "count": len(entries),
            "blocking": False,
            "details": [dict(ledger_kind)],
        },
        {
            "id": "artifacts-by-type",
            "status": "info",
            "count": len(artifacts),
            "blocking": False,
            "details": [dict(artifact_kind)],
        },
        {
            "id": "runtime-sessions",
            "status": "info",
            "count": len(events),
            "blocking": False,
            "details": [dict(runtime_type)],
        },
    ]


def _latest_entry_time(entries: list[dict]) -> datetime | None:
    latest: datetime | None = None
    for entry in entries:
        raw = entry.get("created_at")
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if latest is None or parsed > latest:
            latest = parsed
    return latest


def _closeout_overrides(entries: list[dict]) -> dict[str, dict]:
    overrides: dict[str, dict] = {}
    for entry in entries:
        if entry.get("kind") != "ops-event" or entry.get("action") != "closeout.override":
            continue
        if entry.get("status") != "accepted" or not entry.get("receipt"):
            continue
        for check_id in entry.get("check_ids") or []:
            overrides[str(check_id)] = entry
    return overrides


def _apply_override(check: dict[str, Any], overrides: dict[str, dict]) -> dict[str, Any]:
    override = overrides.get(str(check.get("id") or ""))
    if not override:
        return check
    updated = dict(check)
    updated["overridden"] = True
    updated["override_ledger_id"] = override.get("id")
    updated["override_reason"] = override.get("summary") or override.get("reason")
    if updated.get("status") == "fail":
        updated["status"] = "warn"
        updated["blocking"] = False
    return updated
