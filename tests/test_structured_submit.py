from ref_all_executor.contract_payloads import task_result_submit
from ref_all_executor.structured_submit import (
    backfill_submission_envelope,
    parse_refall_submissions,
    primary_submission,
    validate_submission_contract,
)


def test_contract_payload_builder_emits_refall_submit_v1() -> None:
    payload = task_result_submit(
        subject="alpha",
        task_id="task_1",
        produced_by="codex",
        summary="reviewed app",
        source_anchors=["app.py:10"],
        evidence=[{"kind": "source_anchor", "ref": "app.py:10"}],
    )

    assert payload["schema"] == "refall.submit.v1"
    assert payload["type"] == "task_result_submit"
    assert payload["confidence"] == "medium"
    assert payload["limitations"] == []


def test_contract_validator_rejects_evidence_submit_without_location() -> None:
    errors = validate_submission_contract({
        "schema": "refall.submit.v1",
        "type": "task_result_submit",
        "subject": "alpha",
        "task_id": "task_1",
        "status": "done",
        "summary": "Reviewed app",
        "produced_by": "codex",
        "created_at": "2026-07-24T00:00:00Z",
        "evidence": [{"kind": "source_anchor", "ref": "app.py:10"}],
        "confidence": "medium",
        "limitations": [],
    })

    assert any("source_anchors or artifact_refs" in error for error in errors)


def test_envelope_backfill_makes_underspecified_submit_valid() -> None:
    # Agent omits the envelope the loop owns (produced_by/created_at/task_id)
    # and provides source_anchors but no explicit evidence array. With loop
    # defaults, the submission must validate — evidence is derived from the
    # anchors the agent DID give, never fabricated from nothing.
    block = """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "task_result_submit",
  "subject": "alpha",
  "status": "done",
  "summary": "Characterized hyperion.exe update path.",
  "source_anchors": ["hyperion.exe:0x18c60"]
}
```
"""
    defaults = {
        "produced_by": "cid_abc",
        "created_at": "2026-07-27T00:00:00Z",
        "subject": "alpha",
        "task_id": "unit_42",
        "unit_id": "unit_42",
    }
    parsed = parse_refall_submissions(block, defaults)
    assert parsed.valid, parsed.errors
    sub = parsed.submissions[0]
    assert sub["produced_by"] == "cid_abc"
    assert sub["task_id"] == "unit_42"
    assert sub["confidence"] == "low"
    assert sub["evidence"][0]["ref"] == "hyperion.exe:0x18c60"


def test_envelope_backfill_never_fabricates_evidence() -> None:
    # No anchors, no artifacts -> evidence cannot be derived, so the submission
    # stays invalid. The loop fills bookkeeping, not substance.
    payload = {
        "schema": "refall.submit.v1",
        "type": "task_result_submit",
        "subject": "alpha",
        "status": "done",
        "summary": "claim with no evidence",
    }
    patched = backfill_submission_envelope(
        payload, {"produced_by": "cid_abc", "created_at": "t", "task_id": "u1"}
    )
    assert "evidence" not in patched


def test_valid_task_result_submit_parses() -> None:
    parsed = parse_refall_submissions(
        """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "task_result_submit",
  "subject": "alpha",
  "task_id": "task_1",
  "unit_id": "unit_1",
  "status": "done",
  "summary": "Reviewed login.",
  "produced_by": "cid_1",
  "created_at": "2026-07-24T00:00:00Z",
  "evidence": [{"kind":"source_anchor","ref":"app.py:10","claim":"input reaches sink"}],
  "source_anchors": ["app.py:10"],
  "confidence": "medium",
  "limitations": []
}
```
"""
    )

    assert parsed.valid
    assert parsed.submissions[0]["type"] == "task_result_submit"
    assert primary_submission(parsed)["summary"] == "Reviewed login."


def test_valid_threat_model_submit_parses() -> None:
    parsed = parse_refall_submissions(
        """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "threat_model_submit",
  "subject": "alpha",
  "task_id": "threat_model",
  "status": "done",
  "summary": "Threat model drafted.",
  "produced_by": "cid_1",
  "created_at": "2026-07-24T00:00:00Z",
  "threat_model": {
    "assets": [{"id":"asset:web","name":"web app"}],
    "ingress_points": [{"id":"ingress:http","description":"HTTP service"}],
    "trust_boundaries": [{"id":"tb:user-service","description":"user input to service"}],
    "threats": [{"id":"thr:cmd","title":"Command injection","vuln_class":"command-injection"}],
    "hunt_prompts": ["Trace user input to subprocess calls."],
    "status": "active"
  }
}
```
"""
    )

    assert parsed.valid
    assert primary_submission(parsed)["type"] == "threat_model_submit"
    assert primary_submission(parsed)["threat_model"]["threats"][0]["id"] == "thr:cmd"


def test_malformed_submit_returns_validation_error() -> None:
    parsed = parse_refall_submissions("```refall-submit\n{\"schema\": \n```")

    assert parsed.valid is False
    assert parsed.errors


def test_missing_submit_is_reported() -> None:
    parsed = parse_refall_submissions("[DONE] legacy only")

    assert parsed.valid is False
    assert parsed.missing is True


def test_suppressive_submit_requires_receipt() -> None:
    parsed = parse_refall_submissions(
        """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "finding_submit",
  "subject": "alpha",
  "task_id": "task_1",
  "status": "done",
  "summary": "Reject finding",
  "produced_by": "cid_1",
  "created_at": "2026-07-24T00:00:00Z",
  "proposed_transition": {"to_status": "FALSE_POSITIVE"}
}
```
"""
    )

    assert parsed.valid is False
    assert "receipt" in " ".join(parsed.errors)


def test_suppressive_submit_accepts_embedded_transition_receipt() -> None:
    parsed = parse_refall_submissions(
        """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "finding_submit",
  "subject": "alpha",
  "task_id": "task_1",
  "status": "done",
  "summary": "Reject finding with transition receipt",
  "produced_by": "cid_1",
  "created_at": "2026-07-24T00:00:00Z",
  "evidence": [{"kind":"source_anchor","ref":"app.py:10","claim":"route absent"}],
  "source_anchors": ["app.py:10"],
  "confidence": "high",
  "limitations": [],
  "proposed_transition": {
    "finding_id": "find_1",
    "to_status": "FALSE_POSITIVE",
    "receipt_type": "non_reachability_proof",
    "receipt": {"source_anchors":["app.py:10"]}
  }
}
```
"""
    )

    assert parsed.valid


def test_nested_suppressive_finding_transition_requires_receipt() -> None:
    parsed = parse_refall_submissions(
        """
```refall-submit
{
  "schema": "refall.submit.v1",
  "type": "task_result_submit",
  "subject": "alpha",
  "task_id": "task_1",
  "status": "done",
  "summary": "Reviewed finding.",
  "produced_by": "cid_1",
  "created_at": "2026-07-24T00:00:00Z",
  "evidence": [{"kind":"source_anchor","ref":"app.py:10","claim":"route absent"}],
  "source_anchors": ["app.py:10"],
  "confidence": "high",
  "limitations": [],
  "findings": [
    {
      "id": "find_1",
      "title": "Candidate issue",
      "code_paths": ["app.py:10"],
      "proposed_transition": {"to_status": "FALSE_POSITIVE"}
    }
  ]
}
```
"""
    )

    assert parsed.valid is False
    assert "receipt" in " ".join(parsed.errors)
