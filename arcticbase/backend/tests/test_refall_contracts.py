import pytest
from pydantic import ValidationError

from arctic_base.refall.contracts import (
    CloseoutPackage,
    ContextPackage,
    EvidenceReceipt,
    FindingCandidate,
    RunManifest,
    ScopeOverlay,
    SourceInventoryPackage,
    TaskManifest,
    ThreatModelPackage,
    VerificationResult,
)


def test_evidence_receipt_requires_reference_material() -> None:
    receipt = EvidenceReceipt(
        receipt_type="code_anchor",
        source_anchors=["app.py:10"],
        source_hashes={"app.py": "sha256:" + "a" * 64},
    )

    assert receipt.receipt_type == "code_anchor"
    assert receipt.source_anchors == ["app.py:10"]


def test_evidence_receipt_rejects_empty_material() -> None:
    with pytest.raises(ValidationError, match="receipt requires"):
        EvidenceReceipt(receipt_type="code_anchor")


def test_finding_candidate_requires_code_path_or_artifact() -> None:
    finding = FindingCandidate(
        title="Command injection",
        severity="HIGH",
        vuln_class="command-injection",
        code_paths=["app.py:10"],
        evidence=[{"kind": "source_anchor", "ref": "app.py:10"}],
        confidence="medium",
    )

    assert finding.status == "PROVISIONALLY_VALID"


def test_finding_candidate_rejects_missing_location() -> None:
    with pytest.raises(ValidationError, match="requires code_paths"):
        FindingCandidate(
            title="Command injection",
            severity="HIGH",
            evidence=[{"kind": "source_anchor", "ref": "app.py:10"}],
            confidence="medium",
        )


def test_context_source_scope_threat_task_manifest_and_closeout_contracts_round_trip() -> None:
    source = SourceInventoryPackage(
        subject="alpha",
        root="/subjects/alpha",
        files=[{"path": "app.py", "sha256": "b" * 64, "size_bytes": 12, "total_lines": 1}],
        skipped=[{"path": "locked.log", "reason": "unreadable"}],
    )
    scope = ScopeOverlay(
        subject="alpha",
        local_roots=["/subjects/alpha"],
        lan_targets=[{"host": "192.0.2.10", "ports": [80, 81]}],
        external_targets=[],
    )
    context = ContextPackage(
        subject="alpha",
        info_md="# Alpha",
        source_inventory_id=source.inventory_id,
        scope_overlay_id=scope.overlay_id,
    )
    threat = ThreatModelPackage(
        subject="alpha",
        assets=[{"id": "asset:web", "name": "web app"}],
        ingress_points=[{"id": "ingress:http", "description": "HTTP"}],
        trust_boundaries=[{"id": "tb:user-service", "description": "input to service"}],
        threats=[{"id": "thr:cmd", "title": "Command injection"}],
        hunt_prompts=["Trace user input to subprocess calls."],
    )
    task = TaskManifest(subject="alpha", task_id="task_1", task_class="characterize")
    verification = VerificationResult(
        subject="alpha",
        finding_id="find_1",
        status="static_only",
        evidence_receipt=EvidenceReceipt(receipt_type="code_anchor", source_anchors=["app.py:10"]),
    )
    manifest = RunManifest(
        subject="alpha",
        workbench="alpha",
        run_id="run_1",
        provider_roles={"manager": "codex"},
        source_inventory_id=source.inventory_id,
        scope_overlay_id=scope.overlay_id,
        threat_model_id=threat.threat_model_id,
        git={"sha": None},
        dynamic_testing={"status": "not_applicable"},
    )
    closeout = CloseoutPackage(
        subject="alpha",
        run_id="run_1",
        manifest_id=manifest.manifest_id,
        passed=False,
        checks=[{"id": "context-present", "status": "pass"}],
    )

    assert source.files[0]["path"] == "app.py"
    assert context.source_inventory_id == source.inventory_id
    assert scope.external_targets == []
    assert threat.threats[0]["id"] == "thr:cmd"
    assert task.task_class == "characterize"
    assert verification.evidence_receipt.receipt_type == "code_anchor"
    assert manifest.git["sha"] is None
    assert closeout.manifest_id == manifest.manifest_id
