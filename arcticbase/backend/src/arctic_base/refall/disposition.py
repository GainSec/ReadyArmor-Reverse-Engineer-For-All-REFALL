from __future__ import annotations

from arctic_base.refall.coverage_store import CoverageStore


def transition_finding(store: CoverageStore, subject: str, finding_id: str, data: dict) -> dict:
    return store.transition_finding(subject, finding_id, data)


def list_transitions(
    store: CoverageStore,
    subject: str,
    *,
    finding_id: str | None = None,
    status: str | None = None,
) -> list[dict]:
    return store.list_transitions(subject, finding_id=finding_id, status=status)
