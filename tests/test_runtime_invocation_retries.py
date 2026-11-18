import json
from pathlib import Path

from ref_all_executor.runtime_invocation import classify_invocation, record_retry_failure
from ref_all_executor.runtime_state import connect_runtime


def test_missing_submit_schedules_repair_retry(tmp_path: Path) -> None:
    outcome = classify_invocation("finished", "legacy output", require_structured_submit=True, attempt=1)

    assert outcome.state == "retry_scheduled"
    assert outcome.failure_class == "missing_terminal_submit"
    assert outcome.next_action == "retry_with_repair_prompt"


def test_malformed_submit_schedules_repair_retry(tmp_path: Path) -> None:
    outcome = classify_invocation("finished", "```refall-submit\n{\"schema\":\n```", require_structured_submit=True)

    assert outcome.state == "retry_scheduled"
    assert outcome.failure_class == "malformed_terminal_submit"


def test_retry_exhaustion_records_pending_operator_attention(tmp_path: Path) -> None:
    conn = connect_runtime(tmp_path / "alpha")
    outcome = classify_invocation("finished", "legacy output", require_structured_submit=True, attempt=2, max_attempts=2)

    record = record_retry_failure(conn, "task_1", "cid_1", outcome)

    assert outcome.state == "operator_attention"
    assert record["status"] == "exhausted"


def test_retry_failure_records_artifact_refs(tmp_path: Path) -> None:
    conn = connect_runtime(tmp_path / "alpha")
    outcome = classify_invocation("finished", "legacy output", require_structured_submit=True, attempt=1, max_attempts=2)

    record = record_retry_failure(conn, "task_1", "cid_1", outcome, artifact_refs=["art_1"])
    row = conn.execute("SELECT artifact_refs FROM retry_state WHERE id=?", (record["id"],)).fetchone()

    assert record["artifact_refs"] == ["art_1"]
    assert json.loads(row["artifact_refs"]) == ["art_1"]


def test_output_truncated_schedules_compact_submit_retry() -> None:
    outcome = classify_invocation(
        "output_truncated",
        "partial response",
        require_structured_submit=True,
        attempt=1,
        max_attempts=2,
    )

    assert outcome.state == "retry_scheduled"
    assert outcome.failure_class == "output_truncated"
    assert outcome.next_action == "retry_with_compact_submit"


def test_capability_missing_does_not_auto_retry() -> None:
    outcome = classify_invocation(
        "capability_missing",
        "worker needs network scope",
        require_structured_submit=True,
        attempt=1,
        max_attempts=3,
    )

    assert outcome.state == "pending_capability"
    assert outcome.retryable is False
    assert outcome.failure_class == "capability_missing"
    assert outcome.next_action == "request_capability"


def test_scope_blocked_requires_operator_attention_without_retry() -> None:
    outcome = classify_invocation(
        "scope_blocked",
        "target outside approved scope",
        require_structured_submit=True,
        attempt=1,
        max_attempts=3,
    )

    assert outcome.state == "operator_attention"
    assert outcome.retryable is False
    assert outcome.failure_class == "scope_blocked"
