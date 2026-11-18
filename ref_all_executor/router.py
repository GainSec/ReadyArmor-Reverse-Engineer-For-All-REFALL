from dataclasses import dataclass

from .config import Tier

# triage_trivial is the ONLY class that may use Spark, and only for throwaway work.
TASK_CLASSES = (
    "research", "identify", "select", "enumerate", "characterize", "build_toolchain",
    "run_toolchain", "decompose", "recon", "harness_draft", "patch", "review", "verify",
    "doc_synthesis", "threat_model", "triage_trivial",
)


@dataclass(frozen=True)
class RouteDecision:
    lane: str
    needs_verify: bool
    tier_floor: str
    reason: str


# task_class -> (lane, needs_verify, tier_floor, reason)
# Lane A = Claude (subscription), Lane B = Codex (subscription), Lane C = Spark (trivial only).
_TABLE = {
    "research":      ("A", False, Tier.T3, "deep multi-source web research (GitHub/blogs/papers/X/tutorials); "
                                           "take notes, curate + justify a toolchain — 'possible everything', not 'everything possible' (Claude)"),
    "select":        ("A", False, Tier.T3, "given the toolchain MANIFEST + the target, determine WHICH tools apply "
                                           "and WHY, and produce a concrete run plan — confirms agents self-select tools (Claude)"),
    "identify":      ("A", False, Tier.T3, "identify the target (languages, frameworks, entry points, build, "
                                           "and which code-understanding tools apply) — foundational, shapes everything"),
    "enumerate":     ("B", False, Tier.T3, "mechanically enumerate the subject (files/symbols/line-counts) into the "
                                           "Coverage Service denominator — no judgment, exhaustive (Codex)"),
    "characterize":  ("A", False, Tier.T3, "claim+characterize coverage units with file:line evidence; the deep, "
                                           "gated understanding pass — one claim at a time, no toe-stepping (Claude)"),
    "build_toolchain":("B", False, Tier.T3, "stand up the PERSISTENT reusable code-understanding toolchain infra "
                                            "in /projects/REFALL-V10 — install once, used by all loops (Codex)"),
    "run_toolchain": ("B", False, Tier.T3, "run the persistent toolchain against a target, emit graphs/indexes (Codex)"),
    "decompose":     ("A", False, Tier.T3, "high-value reasoning: break target into subtasks (Claude)"),
    "recon":         ("A", False, Tier.T3, "reconnaissance shapes direction — real analysis on Claude, NOT Spark"),
    "harness_draft": ("B", True,  Tier.T2, "implementation-heavy; a working harness is a claim (Codex)"),
    "patch":         ("B", True,  Tier.T2, "code change is a claim; must be verified (Codex)"),
    "review":        ("A", False, Tier.T3, "nuanced review/critique (Claude)"),
    "verify":        ("B", True,  Tier.T1, "execution/reproduction; target is live confirmation (Codex)"),
    "doc_synthesis": ("A", False, Tier.T3, "synthesis/write-up of already-gated findings (Claude)"),
    "threat_model":  ("A", False, Tier.T3, "optional threat model synthesis from context, source inventory, and scope overlay (Claude)"),
    "triage_trivial":("C", False, Tier.T3, "genuinely trivial throwaway (dedup/one-line summary) — Spark only"),
}


def route(task_class: str) -> RouteDecision:
    if task_class not in _TABLE:
        raise ValueError(f"unknown task_class: {task_class!r}")
    lane, needs_verify, floor, reason = _TABLE[task_class]
    return RouteDecision(lane=lane, needs_verify=needs_verify, tier_floor=floor, reason=reason)
