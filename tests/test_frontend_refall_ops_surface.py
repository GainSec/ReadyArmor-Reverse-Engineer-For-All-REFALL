from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_api_exposes_runtime_discipline_endpoints() -> None:
    api = (ROOT / "arcticbase/frontend/src/lib/api.ts").read_text()

    for name in [
        "refallPendingActions",
        "refallClaimPendingAction",
        "refallResolvePendingAction",
        "refallCloseoutGate",
        "refallCapabilities",
        "refallGrantCapability",
        "refallRuntimeEvents",
        "refallRuntimeArtifacts",
        "refallRuntimeObservations",
        "refallRuntimeEvidenceGraph",
        "refallProjectRuntime",
        "refallNonfatalErrors",
        "refallScopeOverlay",
        "refallPutScopeOverlay",
        "refallThreatModel",
        "refallPutThreatModel",
        "refallDoctor",
        "refallEstimate",
    ]:
        assert name in api


def test_workbench_ops_panel_surfaces_runtime_discipline_views() -> None:
    panel = (ROOT / "arcticbase/frontend/src/lib/refall/WorkbenchOpsPanel.svelte").read_text()

    for label in [
        "Pending",
        "Runtime",
        "Nonfatal Errors",
        "NDJSON",
        "Artifacts",
        "Capabilities",
        "Closeout",
        "Scope",
        "Threat Model",
        "Doctor",
        "Estimate",
        "Readiness",
        "Project Runtime",
        "Claim",
        "Resolve",
        "Defer",
        "Cancel",
    ]:
        assert label in panel

    assert "scopeText" in panel
    assert "saveScopeOverlay" in panel
    assert "threatText" in panel
    assert "requestThreatModel" in panel


def test_start_loop_auto_authorizes_launch_capability_from_ops_panel() -> None:
    dashboard = (ROOT / "arcticbase/frontend/src/lib/themed/WorkbenchDashboard.svelte").read_text()
    panel = (ROOT / "arcticbase/frontend/src/lib/refall/WorkbenchOpsPanel.svelte").read_text()

    assert "refallLaunchPath" in dashboard
    assert "launchPath={refallLaunchPath}" in dashboard
    assert "runCommand(\"start\", { autoGrantLoopLaunch: true })" in panel
    assert "ensureLoopLaunchGrant" in panel
    assert "loopLaunchGrantPayload" in panel
    assert "Loop launch for this subject" in panel


def test_workbench_ops_panel_sends_typed_evidence_receipts_for_pending_actions() -> None:
    panel = (ROOT / "arcticbase/frontend/src/lib/refall/WorkbenchOpsPanel.svelte").read_text()

    assert "action.required_receipt_type" in panel
    assert "evidence_refs" in panel
    assert "receiptType" in panel


def test_workbench_ops_panel_surfaces_closeout_override_metadata() -> None:
    api = (ROOT / "arcticbase/frontend/src/lib/api.ts").read_text()
    panel = (ROOT / "arcticbase/frontend/src/lib/refall/WorkbenchOpsPanel.svelte").read_text()

    assert "overridden?" in api
    assert "override_ledger_id?" in api
    assert "override_reason?" in api
    assert "check.overridden" in panel
    assert "check.override_ledger_id" in panel


def test_workbench_ops_panel_has_closeout_navigation_links() -> None:
    panel = (ROOT / "arcticbase/frontend/src/lib/refall/WorkbenchOpsPanel.svelte").read_text()

    assert "Pending Actions" in panel
    assert "Findings JSON" in panel
    assert "Ledger" in panel
    assert "Current Report" in panel
    assert "/api/workbenches/${slug}/coverage/findings" in panel
    assert "/api/workbenches/${slug}/refall-report" in panel


def test_refall_arcticbase_shell_uses_refall_ab_branding() -> None:
    index = (ROOT / "arcticbase/frontend/index.html").read_text()
    top_nav = (ROOT / "arcticbase/frontend/src/lib/chrome/TopNav.svelte").read_text()
    dashboard = (ROOT / "arcticbase/frontend/src/lib/chrome/Dashboard.svelte").read_text()

    assert "<title>Refall AB - REFALL V10</title>" in index
    assert 'aria-label="Refall AB — Home"' in top_nav
    assert 'alt="Refall AB"' in top_nav
    assert "REFALL_AB :: STATUS_REPORT" in dashboard
