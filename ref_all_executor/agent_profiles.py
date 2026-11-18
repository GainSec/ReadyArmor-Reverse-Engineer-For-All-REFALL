from __future__ import annotations

from dataclasses import dataclass


HEAD_PROVIDERS = {"codex", "claude", "grok"}
SPECIALIST_LANES = {
    "source-review",
    "binary-review",
    "dynamic-validation",
    "exploit-poc",
    "report-draft",
    "report-enrich",
    "visualization",
    "tooling",
    "cleanup",
}


@dataclass(frozen=True)
class HeadProfile:
    provider: str
    name: str
    agent_kind: str


def head_profile(provider: str) -> HeadProfile:
    if provider not in HEAD_PROVIDERS:
        raise ValueError(f"unsupported REFALL head provider: {provider}")
    return HeadProfile(provider=provider, name=f"refall-head-{provider}", agent_kind="acp")
