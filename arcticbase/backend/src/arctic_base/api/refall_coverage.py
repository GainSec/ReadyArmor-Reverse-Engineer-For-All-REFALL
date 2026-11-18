from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from arctic_base.api.deps import get_storage
from arctic_base.refall.contracts import (
    ContextPackage,
    FindingCandidate,
    ScopeOverlay,
    SourceInventoryPackage,
    ThreatModelPackage,
)
from arctic_base.refall import ledger
from arctic_base.refall.coverage_store import (
    CREATABLE_FINDING_STATUSES,
    FINDING_STATUSES,
    build_units,
    store_for_workbench,
)
from arctic_base.storage.filesystem import FilesystemStorage

router = APIRouter(prefix="/workbenches/{slug}/coverage", tags=["refall-coverage"])


class EnumerateReq(BaseModel):
    subject: str | None = None
    files: list[dict]


class SurfaceReq(BaseModel):
    subject: str | None = None
    dimension: str
    items: list[str]
    covered: list[str] = Field(default_factory=list)


class ClaimReq(BaseModel):
    subject: str | None = None
    agent: str
    lease_s: int = 900


class SubmitReq(BaseModel):
    unit_id: str
    agent: str
    summary: str = ""
    sensitivity: str | None = None
    data_touched: object = None
    flows_in: list | None = None
    flows_out: list | None = None
    leads: list | None = None
    evidence: list[dict] = Field(default_factory=list)


class ReleaseReq(BaseModel):
    unit_id: str


class PlanReq(BaseModel):
    subject: str | None = None
    investigations: list[dict]
    pass_number: int = 1
    replace: bool = True


class ContextReq(BaseModel):
    subject: str | None = None
    info_md: str
    generated_by: str | None = None
    root_container: str | None = None


class FindingReq(BaseModel):
    subject: str | None = None
    id: str | None = None
    title: str
    description: str | None = None
    impact: str | None = None
    likelihood: str | None = None
    severity: str | None = None
    privileges_required: str | None = None
    attacker_position: str | None = None
    user_interaction: str | None = None
    status: str = "PROVISIONALLY_VALID"
    quality_tier: str = "HYPOTHESIS"
    production_viability: str | None = None
    repro_status: str | None = None
    patch_status: str | None = None
    affected_component: str | None = None
    component: str | None = None
    affected_product: str | None = None
    affected_versions: list[str] = Field(default_factory=list)
    code_paths: list[str] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    source_anchors: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    confidence: str | None = None
    limitations: list[str] = Field(default_factory=list)
    verification_status: str | None = None
    proposed_transition: dict | None = None
    mitigation: str | None = None
    remediation: str | None = None
    poc: str | None = None
    poc_status: str | None = None
    poc_refs: list[str] = Field(default_factory=list)
    cwe: str | None = None
    cvss_vector: str | None = None
    cvss_score: float | str | None = None
    references: list[str] = Field(default_factory=list)
    discovery: str | None = None
    credit: str | None = None
    data_touched: list[str] = Field(default_factory=list)
    reasoning: str | None = None
    repro_hints: list[str] = Field(default_factory=list)
    reproduction_steps: list[str] = Field(default_factory=list)
    critic_reasoning: str | None = None
    vuln_class: str | None = None
    source_unit_id: str | None = None
    investigation_id: str | None = None
    pass_number: int = 1
    impact_score: int | None = None
    likelihood_score: int | None = None
    mantis_risk_score: float | None = None
    priority: str | None = None
    inferred_exposure: str | None = None
    availability_tier: str | None = None
    duplicate_of: str | None = None
    constituent_findings: list[str] = Field(default_factory=list)
    dedup_key: str | None = None
    canonical_finding_id: str | None = None
    history: list[dict] = Field(default_factory=list)
    related_locations: list[dict] = Field(default_factory=list)
    created_by: str | None = None


class FindingValidationReq(BaseModel):
    finding_id: str
    agent: str
    production_viability: str | None = None
    repro_status: str | None = None
    patch_status: str | None = None
    critic_reasoning: str | None = None
    status: str | None = None


class WishlistReq(BaseModel):
    subject: str | None = None
    id: str | None = None
    kind: str | None = None
    item: str
    reason: str | None = None
    requested_by: str | None = None
    status: str = "open"


class AttackPatternReq(BaseModel):
    id: str | None = None
    vuln_class: str
    title: str | None = None
    description: str | None = None
    leads: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    sinks: list[str] = Field(default_factory=list)
    refs: list[str] = Field(default_factory=list)


class ClassCoverageReq(BaseModel):
    subject: str | None = None
    vuln_class: str
    state: str = "open"
    checked_by: str | None = None
    notes: str | None = None


def _subject(slug: str, supplied: str | None = None) -> str:
    return supplied or slug


def _store(storage: FilesystemStorage, slug: str):
    return store_for_workbench(storage, slug)


def _append_pending_ledgers(storage: FilesystemStorage, slug: str, actions: list[dict]) -> None:
    for action in actions:
        ledger.append_entry(
            storage,
            slug,
            {
                "kind": "pending-action",
                "subject": slug,
                "action": "pending.create",
                "status": action["status"],
                "pending_action_id": action["id"],
                "title": action["title"],
                "summary": action.get("description") or action["title"],
            },
        )


def _contract_payload(data: dict) -> dict:
    return {key: value for key, value in data.items() if value is not None}


def _context_response(row: dict) -> dict:
    contract = ContextPackage(
        subject=str(row.get("subject") or ""),
        info_md=str(row.get("info_md") or ""),
        generated_by=row.get("generated_by"),
        root_container=row.get("root_container"),
    )
    return {**row, "context_id": contract.context_id}


def _normalize_finding_contract(data: dict) -> dict:
    payload = _contract_payload(data)
    status = str(payload.get("status") or "PROVISIONALLY_VALID")
    if status not in FINDING_STATUSES:
        raise HTTPException(422, f"bad status {status}")
    if status not in CREATABLE_FINDING_STATUSES:
        raise HTTPException(422, f"status {status} requires disposition transition")
    code_paths = _clean_refs(payload.get("code_paths") or [])
    source_anchors = _clean_refs(payload.get("source_anchors") or [])
    artifact_refs = _clean_refs(payload.get("artifact_refs") or [])
    locations = code_paths or source_anchors or artifact_refs
    if not code_paths and locations:
        payload["code_paths"] = locations
    if not source_anchors and code_paths:
        payload["source_anchors"] = code_paths
    if locations and not payload.get("evidence"):
        payload["evidence"] = [{"kind": "source_anchor", "ref": ref} for ref in locations]
    try:
        FindingCandidate(**payload)
    except ValidationError as exc:
        raise HTTPException(422, f"finding contract invalid: {exc.errors()[0]['msg']}") from exc
    return {**data, "code_paths": payload.get("code_paths") or []}


def _clean_refs(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _record_promotion_refusal(
    storage: FilesystemStorage,
    slug: str,
    subject: str,
    store,
    candidate: dict,
    message: str,
) -> None:
    title = str(candidate.get("title") or "Finding candidate").strip()
    reasons = _promotion_refusal_reasons(message)
    action = store.create_pending_action(
        subject,
        {
            "identity_key": f"{subject}:finding-candidate-review:{title.lower()}",
            "kind": "finding_candidate_review",
            "title": f"Review refused finding candidate: {title}",
            "description": message,
            "priority": "high" if str(candidate.get("severity") or "").upper() in {"HIGH", "CRITICAL"} else "medium",
            "required_receipt_type": "manager_review",
            "assigned_lane": "source-analysis",
            "created_by": "refall-promotion-gate",
        },
    )
    ledger.append_entry(
        storage,
        slug,
        {
            "kind": "ops-event",
            "subject": subject,
            "action": "finding.promotion.refused",
            "status": "blocked",
            "summary": message,
            "candidate": candidate,
            "reasons": reasons,
            "pending_action_id": action["id"],
        },
    )
    _append_pending_ledgers(storage, slug, [action])


def _promotion_refusal_reasons(message: str) -> list[str]:
    _, _, detail = message.partition(":")
    return [part.strip() for part in detail.split(";") if part.strip()]


@router.post("/enumerate", operation_id="enumerateRefallCoverage")
def enumerate_coverage(
    slug: str,
    body: EnumerateReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    subject = _subject(slug, body.subject)
    store = _store(storage, slug)
    count = store.upsert_units(build_units(subject, body.files))
    return {"subject": subject, "units": count}


@router.put("/source-inventory", operation_id="putRefallCoverageSourceInventory")
def put_source_inventory(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
    body: dict = Body(...),
) -> dict:
    subject = _subject(slug, body.get("subject"))
    try:
        contract = SourceInventoryPackage(subject=subject, **{k: v for k, v in body.items() if k != "subject"})
    except ValidationError as exc:
        raise HTTPException(422, f"source inventory invalid: {exc.errors()[0]['msg']}") from exc
    stored = _store(storage, slug).put_source_inventory(subject, contract.model_dump(mode="json"))
    ledger.append_entry(
        storage,
        slug,
        {
            "kind": "ops-event",
            "subject": subject,
            "action": "source_inventory.update",
            "status": "accepted",
            "summary": f"Source inventory updated for {subject}",
            "source_inventory_id": stored["inventory_id"],
            "files": len(stored.get("files") or []),
            "skipped": len(stored.get("skipped") or []),
        },
    )
    return stored


@router.get("/source-inventory", operation_id="getRefallCoverageSourceInventory")
def get_source_inventory(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    stored = _store(storage, slug).get_latest_source_inventory(slug)
    if not stored:
        raise HTTPException(404, "no source inventory")
    return stored


@router.put("/scope-overlay", operation_id="putRefallCoverageScopeOverlay")
def put_scope_overlay(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
    body: dict = Body(...),
) -> dict:
    subject = _subject(slug, body.get("subject"))
    try:
        contract = ScopeOverlay(subject=subject, **{k: v for k, v in body.items() if k != "subject"})
    except ValidationError as exc:
        raise HTTPException(422, f"scope overlay invalid: {exc.errors()[0]['msg']}") from exc
    stored = _store(storage, slug).set_scope_overlay(subject, contract.model_dump(mode="json"), updated_by=body.get("updated_by"))
    ledger.append_entry(
        storage,
        slug,
        {
            "kind": "ops-event",
            "subject": subject,
            "action": "scope-overlay.update",
            "status": "accepted",
            "summary": f"Scope overlay updated for {subject}",
            "scope_overlay_id": stored["overlay_id"],
        },
    )
    return stored


@router.get("/scope-overlay", operation_id="getRefallCoverageScopeOverlay")
def get_scope_overlay(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    stored = _store(storage, slug).get_scope_overlay(slug)
    if stored:
        return stored
    return ScopeOverlay(subject=slug).model_dump(mode="json")


@router.put("/threat-model", operation_id="putRefallCoverageThreatModel")
def put_threat_model(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
    body: dict = Body(...),
) -> dict:
    subject = _subject(slug, body.get("subject"))
    try:
        contract = ThreatModelPackage(subject=subject, **{k: v for k, v in body.items() if k != "subject"})
    except ValidationError as exc:
        raise HTTPException(422, f"threat model invalid: {exc.errors()[0]['msg']}") from exc
    stored = _store(storage, slug).put_threat_model(
        subject,
        contract.model_dump(mode="json"),
        created_by=body.get("created_by"),
    )
    ledger.append_entry(
        storage,
        slug,
        {
            "kind": "ops-event",
            "subject": subject,
            "action": "threat-model.update",
            "status": "accepted",
            "summary": f"Threat model updated for {subject}",
            "threat_model_id": stored["threat_model_id"],
            "threats": len(stored.get("threats") or []),
            "assets": len(stored.get("assets") or []),
        },
    )
    return stored


@router.get("/threat-model", operation_id="getRefallCoverageThreatModel")
def get_threat_model(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    stored = _store(storage, slug).get_latest_threat_model(slug)
    if stored:
        return stored
    return ThreatModelPackage(subject=slug, status="skipped").model_dump(mode="json")


@router.post("/surface", operation_id="setRefallCoverageSurface")
def surface_coverage(
    slug: str,
    body: SurfaceReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    store = _store(storage, slug)
    return store.set_surface(_subject(slug, body.subject), body.dimension, body.items, body.covered)


@router.post("/claim", operation_id="claimRefallCoverage")
def claim_coverage(
    slug: str,
    body: ClaimReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    store = _store(storage, slug)
    unit = store.claim_next(_subject(slug, body.subject), body.agent, body.lease_s)
    if not unit:
        raise HTTPException(404, "no open units")
    return unit


@router.post("/submit", operation_id="submitRefallCoverage")
def submit_coverage(
    slug: str,
    body: SubmitReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    store = _store(storage, slug)
    try:
        return store.submit(
            body.unit_id,
            body.agent,
            body.summary,
            body.evidence,
            sensitivity=body.sensitivity,
            data_touched=body.data_touched,
            flows_in=body.flows_in,
            flows_out=body.flows_out,
            leads=body.leads,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/release", operation_id="releaseRefallCoverage")
def release_coverage(
    slug: str,
    body: ReleaseReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    _store(storage, slug).release(body.unit_id)
    return {"ok": True}


@router.post("/mark-dead", operation_id="markDeadRefallCoverage")
def mark_dead_coverage(
    slug: str,
    body: SubmitReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    store = _store(storage, slug)
    try:
        return store.mark_dead(body.unit_id, body.agent, body.evidence)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/stats", operation_id="getRefallCoverageStats")
def coverage_stats(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    return _store(storage, slug).coverage(slug)


@router.get("/gate", operation_id="getRefallCoverageGate")
def coverage_gate(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
    threshold: float = 0.95,
) -> dict:
    return _store(storage, slug).gate(slug, threshold)


@router.get("/search", operation_id="searchRefallCoverage")
def coverage_search(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
    type: str | None = None,
    state: str | None = None,
    sensitivity: str | None = None,
    path: str | None = None,
    q: str | None = None,
) -> list[dict]:
    return _store(storage, slug).search(slug, type=type, state=state, sensitivity=sensitivity, path=path, q=q)


@router.post("/plan", operation_id="putRefallCoveragePlan")
def put_plan(
    slug: str,
    body: PlanReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    subject = _subject(slug, body.subject)
    count = _store(storage, slug).put_plan(subject, body.investigations, body.pass_number, body.replace)
    return {"subject": subject, "investigations": count}


@router.get("/plan", operation_id="getRefallCoveragePlan")
def get_plan(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    return _store(storage, slug).plan_progress(slug)


@router.post("/context", operation_id="putRefallCoverageContext")
def put_context(
    slug: str,
    body: ContextReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    subject = _subject(slug, body.subject)
    contract = ContextPackage(
        subject=subject,
        info_md=body.info_md,
        generated_by=body.generated_by,
        root_container=body.root_container,
    )
    stored = _store(storage, slug).set_context(
        subject,
        body.info_md,
        body.generated_by,
        body.root_container,
    )
    return _context_response({**stored, "context_id": contract.context_id})


@router.get("/context", operation_id="getRefallCoverageContext")
def get_context(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    stored = _store(storage, slug).get_context(slug)
    return _context_response(stored) if stored else {"subject": slug, "info_md": None}


@router.post("/findings", status_code=201, operation_id="createRefallCoverageFinding")
def create_finding(
    slug: str,
    body: FindingReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    data = body.model_dump()
    subject = _subject(slug, data.pop("subject"))
    data = _normalize_finding_contract(data)
    store = _store(storage, slug)
    try:
        finding = store.add_finding(subject, data)
    except ValueError as exc:
        if str(exc).startswith("finding promotion refused:"):
            _record_promotion_refusal(storage, slug, subject, store, data, str(exc))
        raise HTTPException(422, str(exc)) from exc
    _append_pending_ledgers(storage, slug, store.trigger_pending_actions_for_finding(slug, finding, data))
    return finding


@router.get("/findings/summary", operation_id="getRefallCoverageFindingsSummary")
def findings_summary(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
    subject: str | None = None,
) -> dict:
    return _store(storage, slug).findings_summary(_subject(slug, subject))


@router.get("/findings", operation_id="listRefallCoverageFindings")
def list_findings(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
    subject: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    vuln_class: str | None = None,
) -> list[dict]:
    return _store(storage, slug).list_findings(
        _subject(slug, subject),
        status=status,
        severity=severity,
        vuln_class=vuln_class,
    )


@router.post("/finding-validation", operation_id="updateRefallCoverageFindingValidation")
@router.post("/finding_validation", operation_id="updateRefallCoverageFindingValidationCompat")
def update_finding_validation(
    slug: str,
    body: FindingValidationReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    store = _store(storage, slug)
    try:
        updated = store.update_finding_validation(
            body.finding_id,
            body.agent,
            body.model_dump(exclude={"finding_id", "agent"}),
        )
    except ValueError as exc:
        status_code = 404 if str(exc) == "no such finding" else 422
        raise HTTPException(status_code, str(exc)) from exc
    _append_pending_ledgers(
        storage,
        slug,
        store.trigger_pending_actions_for_finding(slug, updated, body.model_dump(exclude={"finding_id", "agent"})),
    )
    return updated


@router.post("/wishlist", status_code=201, operation_id="createRefallCoverageWishlistItem")
def create_wishlist_item(
    slug: str,
    body: WishlistReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    data = body.model_dump()
    subject = _subject(slug, data.pop("subject"))
    try:
        return _store(storage, slug).add_wishlist_item(subject, data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/wishlist", operation_id="listRefallCoverageWishlist")
def list_wishlist(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
    subject: str | None = None,
    status: str | None = None,
) -> list[dict]:
    return _store(storage, slug).list_wishlist(_subject(slug, subject), status=status)


@router.post("/attack-patterns", status_code=201, operation_id="createRefallAttackPattern")
def create_attack_pattern(
    slug: str,
    body: AttackPatternReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    try:
        return _store(storage, slug).add_attack_pattern(body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/attack-patterns", operation_id="listRefallAttackPatterns")
def list_attack_patterns(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
    vuln_class: str | None = None,
) -> list[dict]:
    return _store(storage, slug).list_attack_patterns(vuln_class=vuln_class)


@router.post("/class-coverage", operation_id="setRefallClassCoverage")
def set_class_coverage(
    slug: str,
    body: ClassCoverageReq,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
) -> dict:
    data = body.model_dump()
    subject = _subject(slug, data.pop("subject"))
    try:
        return _store(storage, slug).set_class_coverage(subject, data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/class-coverage", operation_id="listRefallClassCoverage")
def list_class_coverage(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
    subject: str | None = None,
    vuln_class: str | None = None,
) -> list[dict]:
    return _store(storage, slug).list_class_coverage(_subject(slug, subject), vuln_class)


@router.get("/funnel", operation_id="getRefallCoverageFunnel")
def coverage_funnel(
    slug: str,
    storage: Annotated[FilesystemStorage, Depends(get_storage)],
    subject: str | None = None,
) -> dict:
    return _store(storage, slug).funnel(_subject(slug, subject))
