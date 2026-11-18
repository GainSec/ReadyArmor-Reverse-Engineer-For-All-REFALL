import pytest
from ref_all_executor.router import route, TASK_CLASSES
from ref_all_executor.config import Tier


def test_reasoning_tasks_go_to_claude_lane_a():
    for tc in ("identify", "decompose", "review", "doc_synthesis", "threat_model"):
        assert route(tc).lane == "A"


def test_identify_is_first_class_and_foundational():
    d = route("identify")
    assert d.lane == "A" and "identify" in d.reason.lower()


def test_implementation_tasks_go_to_codex_lane_b():
    for tc in ("harness_draft", "patch", "verify"):
        assert route(tc).lane == "B"


def test_recon_is_real_analysis_not_spark():
    # recon shapes direction -> Claude, never Spark
    assert route("recon").lane == "A"


def test_threat_model_is_optional_doc_synthesis_reasoning():
    d = route("threat_model")
    assert d.lane == "A"
    assert d.needs_verify is False
    assert "threat model" in d.reason.lower()


def test_only_triage_trivial_uses_spark():
    spark_classes = [tc for tc in TASK_CLASSES if route(tc).lane == "C"]
    assert spark_classes == ["triage_trivial"]


def test_claim_bearing_tasks_require_verification():
    for tc in ("harness_draft", "patch", "verify"):
        assert route(tc).needs_verify is True


def test_verify_targets_live_confirmation():
    assert route("verify").tier_floor == Tier.T1


def test_every_task_class_routes_with_reason():
    for tc in TASK_CLASSES:
        d = route(tc)
        assert d.lane in ("A", "B", "C") and d.reason


def test_unknown_task_class_raises():
    with pytest.raises(ValueError):
        route("mine_bitcoin")
