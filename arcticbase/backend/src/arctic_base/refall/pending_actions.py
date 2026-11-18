from __future__ import annotations

from arctic_base.refall.coverage_store import CoverageStore


def create(store: CoverageStore, subject: str, data: dict) -> dict:
    return store.create_pending_action(subject, data)


def list_actions(
    store: CoverageStore,
    subject: str,
    *,
    status: str | None = None,
    kind: str | None = None,
    include_terminal: bool = True,
) -> list[dict]:
    return store.list_pending_actions(
        subject,
        status=status,
        kind=kind,
        include_terminal=include_terminal,
    )
