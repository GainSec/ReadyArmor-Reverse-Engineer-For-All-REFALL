from __future__ import annotations

from dataclasses import dataclass

from .agent_profiles import SPECIALIST_LANES, head_profile
from .wishlist import format_provided_wishlist, provided_wishes_from


@dataclass(frozen=True)
class HeadCycleResult:
    provider: str
    subject: str
    specialist_lane: str
    unit_id: str | None
    status: str


class RefallHeadOrchestrator:
    def __init__(
        self,
        *,
        head_provider: str,
        coverage,
        ledger,
        dispatcher,
        wishlist=None,
        usage=None,
        verifier=None,
        reporter=None,
    ) -> None:
        self.profile = head_profile(head_provider)
        self.coverage = coverage
        self.ledger = ledger
        self.dispatcher = dispatcher
        self.wishlist = wishlist
        self.usage = usage
        self.verifier = verifier
        self.reporter = reporter

    def run_cycle(
        self,
        subject: str,
        specialist_lane: str,
        *,
        refresh_report: bool = False,
        verify: bool = False,
    ) -> HeadCycleResult:
        if specialist_lane not in SPECIALIST_LANES:
            raise ValueError(f"unknown specialist lane: {specialist_lane}")
        gate = self.coverage.gate(subject)
        unit = self.coverage.claim_next(subject, self.profile.name)
        provided = self._provided_wishlist(subject)
        objective = _objective(subject, specialist_lane, unit, provided, self._coverage_context(subject))
        dispatch = self.dispatcher.dispatch(specialist_lane, objective)
        self.ledger.append({
            "kind": "coverage",
            "subject": subject,
            "lane": specialist_lane,
            "title": f"{specialist_lane} cycle",
            "summary": dispatch.get("summary", ""),
            "unit_id": unit.get("id") if unit else None,
            "provider": self.profile.provider,
            "coverage_gate": gate,
        })
        if unit:
            self.coverage.submit(
                unit["id"],
                self.profile.name,
                dispatch.get("summary", ""),
                dispatch.get("evidence") or [{"file": unit.get("path") or "unknown"}],
                subject=subject,
            )
        if self.usage is not None:
            self.usage.record(subject, specialist_lane, dispatch)
        if verify and self.verifier is not None:
            validation = self.verifier.verify(
                subject,
                dispatch.get("summary", ""),
                dispatch.get("evidence") or [],
            )
            self.ledger.append({
                "kind": "validation",
                "subject": subject,
                "lane": specialist_lane,
                "summary": validation.get("response", ""),
                "status": "verified" if validation.get("verified") else "not-verified",
                "provider": self.profile.provider,
                "unit_id": unit.get("id") if unit else None,
            })
        if refresh_report and self.reporter is not None:
            report = self.reporter.refresh(subject)
            self.ledger.append({
                "kind": "artifact",
                "subject": subject,
                "lane": "report-draft",
                "summary": "REFALL report refreshed",
                "provider": self.profile.provider,
                "report": report,
            })
        return HeadCycleResult(
            provider=self.profile.provider,
            subject=subject,
            specialist_lane=specialist_lane,
            unit_id=unit.get("id") if unit else None,
            status=dispatch.get("status", "unknown"),
        )

    def _provided_wishlist(self, subject: str) -> list[dict]:
        if self.wishlist is not None:
            return list(self.wishlist.provided(subject))
        return list(provided_wishes_from(self.coverage, subject))

    def _coverage_context(self, subject: str) -> str:
        getter = getattr(self.coverage, "get_context", None)
        if getter is None:
            return ""
        context = getter(subject) or {}
        return str(context.get("info_md") or "").strip()


def _objective(
    subject: str,
    specialist_lane: str,
    unit: dict | None,
    provided_wishlist: list[dict] | None = None,
    context_md: str = "",
) -> str:
    context = f"## REFALL context.md\n{context_md}\n\n" if context_md else ""
    wishlist = "\n\nProvided wishlist:\n" + format_provided_wishlist(subject, provided_wishlist)
    if not unit:
        return (
            context +
            f"Run {specialist_lane} for REFALL subject {subject}; no coverage unit was available."
            f"{wishlist}"
        )
    return (
        context +
        f"Run {specialist_lane} for REFALL subject {subject}. "
        f"Coverage unit {unit.get('id')} {unit.get('path')}:{unit.get('line_start')}-{unit.get('line_end')}."
        f"{wishlist}"
    )
