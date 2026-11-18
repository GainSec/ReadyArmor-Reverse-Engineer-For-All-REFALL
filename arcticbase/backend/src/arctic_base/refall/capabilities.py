from __future__ import annotations

from arctic_base.refall.coverage_store import CoverageStore


def grant(store: CoverageStore, subject: str, data: dict) -> dict:
    return store.grant_capability(subject, data)


def authorize(store: CoverageStore, subject: str, request: dict) -> dict:
    return store.authorize_execution(subject, request)
