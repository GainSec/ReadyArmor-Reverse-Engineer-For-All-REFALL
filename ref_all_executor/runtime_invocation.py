from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass

from .structured_submit import parse_refall_submissions


@dataclass
class InvocationOutcome:
    state: str
    failure_class: str | None = None
    retryable: bool = False
    attempt: int = 1
    max_attempts: int = 2
    last_error: str = ""
    next_action: str = "none"


def classify_invocation(
    status: str,
    response: str,
    *,
    require_structured_submit: bool,
    attempt: int = 1,
    max_attempts: int = 2,
) -> InvocationOutcome:
    if status not in {"finished", "complete", "completed"}:
        failure_class = _status_failure_class(status)
        if failure_class == "capability_missing":
            return InvocationOutcome(
                state="pending_capability",
                failure_class=failure_class,
                retryable=False,
                attempt=attempt,
                max_attempts=max_attempts,
                last_error=response or f"worker status {status}",
                next_action="request_capability",
            )
        if failure_class in {"scope_blocked", "operator_stop", "tool_execution_error"}:
            return InvocationOutcome(
                state="operator_attention",
                failure_class=failure_class,
                retryable=False,
                attempt=attempt,
                max_attempts=max_attempts,
                last_error=response or f"worker status {status}",
                next_action="operator_attention",
            )
        next_action = "retry_with_compact_submit" if failure_class == "output_truncated" else "retry_provider"
        return InvocationOutcome(
            state="retry_scheduled" if attempt < max_attempts else "operator_attention",
            failure_class=failure_class,
            retryable=attempt < max_attempts,
            attempt=attempt,
            max_attempts=max_attempts,
            last_error=response or f"worker status {status}",
            next_action=next_action if attempt < max_attempts else "operator_attention",
        )
    parsed = parse_refall_submissions(response or "")
    if require_structured_submit and parsed.missing:
        return _submit_failure("missing_terminal_submit", "Worker ended without refall-submit block", attempt, max_attempts)
    if require_structured_submit and parsed.errors:
        return _submit_failure("malformed_terminal_submit", "; ".join(parsed.errors), attempt, max_attempts)
    return InvocationOutcome(state="completed", attempt=attempt, max_attempts=max_attempts)


def record_retry_failure(
    conn: sqlite3.Connection,
    task_id: str,
    session_id: str,
    outcome: InvocationOutcome,
    artifact_refs: list[str] | None = None,
) -> dict:
    now = time.time()
    status = "exhausted" if outcome.state == "operator_attention" else "scheduled"
    record = {
        "id": f"retry_{uuid.uuid4().hex}",
        "task_id": task_id,
        "session_id": session_id,
        "attempt": outcome.attempt,
        "max_attempts": outcome.max_attempts,
        "failure_class": outcome.failure_class,
        "last_error": outcome.last_error,
        "next_action": outcome.next_action,
        "status": status,
        "artifact_refs": artifact_refs or [],
        "created_at": now,
        "updated_at": now,
    }
    conn.execute(
        "INSERT INTO retry_state(id,task_id,session_id,attempt,max_attempts,failure_class,last_error,next_action,status,artifact_refs,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            record["id"],
            task_id,
            session_id,
            record["attempt"],
            record["max_attempts"],
            record["failure_class"],
            record["last_error"],
            record["next_action"],
            record["status"],
            json.dumps(record["artifact_refs"]),
            now,
            now,
        ),
    )
    conn.commit()
    return record


def _submit_failure(failure_class: str, message: str, attempt: int, max_attempts: int) -> InvocationOutcome:
    exhausted = attempt >= max_attempts
    return InvocationOutcome(
        state="operator_attention" if exhausted else "retry_scheduled",
        failure_class=failure_class,
        retryable=not exhausted,
        attempt=attempt,
        max_attempts=max_attempts,
        last_error=message,
        next_action="operator_attention" if exhausted else "retry_with_repair_prompt",
    )


def _status_failure_class(status: str) -> str:
    normalized = str(status or "").lower()
    if "truncat" in normalized or "length" in normalized:
        return "output_truncated"
    if "capability" in normalized:
        return "capability_missing"
    if "scope" in normalized:
        return "scope_blocked"
    if "operator" in normalized and "stop" in normalized:
        return "operator_stop"
    if "tool" in normalized:
        return "tool_execution_error"
    if "transport" in normalized:
        return "agent_canvas_transport_error"
    if "unavailable" in normalized:
        return "provider_unavailable"
    if "timeout" in normalized:
        return "provider_timeout"
    if "rate" in normalized:
        return "provider_rate_limited"
    if "lost" in normalized:
        return "agent_canvas_session_lost"
    return "unknown_failure"
