"""Modular, phaseless work generation for the REFALL standing loop.

The loop used to hardcode `task_class = "characterize"` for every coverage unit,
so 12 of the 16 routed task classes were never dispatched and a run produced no
findings unless an operator hand-fed it pending actions.

This replaces that with **work modules**. A module is a small declaration that
says: for targets matching this predicate, dispatch this task class with this
extra objective. Modules are independent and evaluated every claim, so:

- **Phaseless.** There is no global stage counter. A target is eligible for a
  module the moment its predicate holds. Two modules can be eligible for the
  same target at once.
- **Ordered where it matters.** A module can require `after=["characterize"]`,
  which orders it *per target* without imposing a pipeline on the whole run.
- **Combinable.** A subject enables any set of modules. Hyundai can run
  reverse-engineering, security, research, and development modules together.
- **Slot-in.** Modules are data, not code. Built-ins ship in PACKS; a manager or
  operator can add subject-specific modules ("subloops") at runtime by writing
  definitions to the workbench -- no deploy, no code change.

Modules generate *investigations* (the existing planned-work table), which the
loop claims alongside coverage units. That keeps one inspectable work queue.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .router import _TABLE as ROUTER_TABLE

# Where a module draws its targets from.
SOURCE_UNITS = "coverage_units"
SOURCE_FINDINGS = "findings"
SOURCE_SUBJECT = "subject"  # one-shot, target is the subject itself
SOURCES = {SOURCE_UNITS, SOURCE_FINDINGS, SOURCE_SUBJECT}


class ModuleError(ValueError):
    """A module definition is not usable."""


@dataclass
class WorkModule:
    """One slot-in unit of work generation."""

    id: str
    task_class: str
    source: str = SOURCE_UNITS
    # Per-target ordering. NOT a global phase: "run me on a target only after
    # these modules have completed on that same target".
    after: list[str] = field(default_factory=list)
    # Coverage unit state a target must be in (None = any).
    unit_state: str | None = None
    # Only consider targets whose path matches one of these globs (None = all).
    path_globs: list[str] | None = None
    # Skip targets whose path matches any of these globs, even if path_globs
    # matched. Used to keep deep/expensive modules off bulk media and metadata-
    # only corpora (HAF/GPS/image/voice), which should be characterized but not
    # deeply analysed unless a concrete lead escalates them.
    exclude_globs: list[str] | None = None
    priority: int = 100  # lower runs first when several modules are eligible
    max_parallel: int | None = None  # cap concurrent agents for this module
    objective: str = ""  # appended to the dispatched objective
    enabled: bool = True
    pack: str = "custom"
    once_per_target: bool = True

    def validate(self) -> None:
        if not self.id:
            raise ModuleError("module id is required")
        if self.task_class not in ROUTER_TABLE:
            raise ModuleError(
                f"module {self.id!r}: unknown task_class {self.task_class!r}; "
                f"known: {sorted(ROUTER_TABLE)}"
            )
        if self.source not in SOURCES:
            raise ModuleError(f"module {self.id!r}: unknown source {self.source!r}")
        if self.max_parallel is not None and self.max_parallel < 1:
            raise ModuleError(f"module {self.id!r}: max_parallel must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_class": self.task_class,
            "source": self.source,
            "after": list(self.after),
            "unit_state": self.unit_state,
            "path_globs": list(self.path_globs) if self.path_globs else None,
            "exclude_globs": list(self.exclude_globs) if self.exclude_globs else None,
            "priority": self.priority,
            "max_parallel": self.max_parallel,
            "objective": self.objective,
            "enabled": self.enabled,
            "pack": self.pack,
            "once_per_target": self.once_per_target,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkModule":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        unknown = set(data) - known
        if unknown:
            raise ModuleError(f"module {data.get('id')!r}: unknown keys {sorted(unknown)}")
        module = cls(**{k: v for k, v in data.items() if k in known})
        module.validate()
        return module


# ---------------------------------------------------------------- built-ins
#
# Packs are a convenience for enabling a coherent group; they are NOT phases and
# carry no ordering between them. Enable any combination.

def _m(**kw: Any) -> WorkModule:
    module = WorkModule(**kw)
    module.validate()
    return module


PACKS: dict[str, list[WorkModule]] = {
    # Breadth: build the map. Almost every subject wants this.
    "baseline": [
        _m(id="characterize", task_class="characterize", priority=100, pack="baseline",
           objective="Describe what this unit is and does, with file:line evidence."),
    ],
    "reverse_engineering": [
        _m(id="re_identify", task_class="identify", source=SOURCE_SUBJECT, priority=10,
           pack="reverse_engineering",
           objective="Identify languages, frameworks, entry points, build system, and "
                     "which code-understanding tools apply to this target."),
        _m(id="re_decompose", task_class="decompose", after=["characterize"], priority=40,
           pack="reverse_engineering",
           objective="Break this component into its constituent behaviours and data flows. "
                     "Name the abstractions and how control reaches them."),
        _m(id="re_review", task_class="review", after=["re_decompose"], priority=60,
           pack="reverse_engineering",
           objective="Review the decomposition for correctness and gaps. What is still opaque?"),
    ],
    "security_assessment": [
        _m(id="sec_recon", task_class="recon", after=["characterize"], priority=30,
           pack="security_assessment",
           objective="Identify the attack surface reachable through this unit: inputs, "
                     "parsers, IPC/network entry, privilege boundaries, persistence, and "
                     "trust assumptions. Record negative results explicitly."),
        _m(id="sec_review", task_class="review", after=["sec_recon"], priority=45,
           pack="security_assessment",
           objective="Assess this unit for security vulnerabilities against the surface "
                     "recon identified. File findings as PROVISIONALLY_VALID with file:line "
                     "evidence, impact, and likelihood. State negative results too."),
        _m(id="sec_verify", task_class="verify", source=SOURCE_FINDINGS, priority=20,
           pack="security_assessment",
           objective="Attempt to reproduce this finding. Give exact repro steps, PoC status, "
                     "observed vs expected behaviour, and whether the claim is verified."),
    ],
    "research": [
        _m(id="res_research", task_class="research", source=SOURCE_SUBJECT, priority=20,
           pack="research",
           objective="Deep multi-source research on this target class: prior work, known "
                     "vulnerability patterns, vendor advisories, teardowns, tooling."),
        _m(id="res_synthesis", task_class="doc_synthesis", source=SOURCE_SUBJECT, priority=90,
           pack="research",
           objective="Synthesise gated findings and research notes into a coherent write-up."),
    ],
    "development": [
        _m(id="dev_harness", task_class="harness_draft", after=["characterize"], priority=50,
           pack="development",
           objective="Draft a working harness that exercises this component in isolation."),
        _m(id="dev_patch", task_class="patch", source=SOURCE_FINDINGS, priority=70,
           pack="development",
           objective="Propose a minimal, verifiable code change addressing this finding."),
    ],
    "dynamic_testing": [
        _m(id="dyn_harness", task_class="harness_draft", after=["characterize"], priority=45,
           pack="dynamic_testing",
           objective="Build a harness that drives this component at runtime with "
                     "operator-approved inputs only."),
        _m(id="dyn_verify", task_class="verify", after=["dyn_harness"], priority=55,
           pack="dynamic_testing",
           objective="Execute the harness and record observed runtime behaviour as evidence."),
    ],
    "static_analysis": [
        _m(id="sa_toolchain", task_class="run_toolchain", source=SOURCE_SUBJECT, priority=15,
           pack="static_analysis",
           objective="Run the persistent toolchain against the target; emit graphs/indexes."),
        _m(id="sa_review", task_class="review", after=["characterize"], priority=65,
           pack="static_analysis",
           objective="Review toolchain output for this unit: data flow, taint, reachability."),
    ],
}


def pack_names() -> list[str]:
    return sorted(PACKS)


def builtin_module(module_id: str) -> WorkModule | None:
    for modules in PACKS.values():
        for module in modules:
            if module.id == module_id:
                return module
    return None


# ---------------------------------------------------------------- registry


@dataclass
class ModuleRegistry:
    """The set of modules active for one subject."""

    modules: list[WorkModule] = field(default_factory=list)

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "ModuleRegistry":
        """Build from a subject's module config.

        Shape (all optional)::

            {
              "packs": ["baseline", "security_assessment"],
              "modules": [ {...custom subloop module...} ],
              "disabled": ["sec_verify"],
              "overrides": {"characterize": {"priority": 5}}
            }

        No config at all yields the baseline pack, which is exactly the loop's
        historical characterize-only behaviour.
        """
        config = config or {}
        if not isinstance(config, dict):
            raise ModuleError("module config must be an object")

        selected: dict[str, WorkModule] = {}
        packs = config.get("packs")
        if packs is None:
            # A subject with no declared intent gets a security assessment, since
            # that is REFALL's most common job. `security_assessment` auto-pulls
            # `characterize` (baseline) through its dependencies, so this stays a
            # superset of the old characterize-only behaviour, not a replacement.
            packs = ["security_assessment"]
        if not isinstance(packs, list):
            raise ModuleError("packs must be a list")
        for pack in packs:
            if pack not in PACKS:
                raise ModuleError(f"unknown pack {pack!r}; known: {pack_names()}")
            for module in PACKS[pack]:
                selected[module.id] = WorkModule(**module.to_dict())

        # Subject-specific subloop modules, authored at runtime.
        for raw in config.get("modules") or []:
            module = WorkModule.from_dict(dict(raw))
            selected[module.id] = module

        for override_id, patch in (config.get("overrides") or {}).items():
            base = selected.get(override_id) or builtin_module(override_id)
            if base is None:
                raise ModuleError(f"override for unknown module {override_id!r}")
            merged = {**base.to_dict(), **dict(patch), "id": override_id}
            selected[override_id] = WorkModule.from_dict(merged)

        # Auto-resolve cross-pack dependencies. Enabling `security_assessment`
        # alone should pull in `characterize` (from baseline) because sec_recon
        # depends on it -- the operator combines packs without memorising which
        # module lives where. Only built-in deps are pulled; an unknown dep is a
        # genuine authoring error and still fails in validate().
        pending = [dep for m in selected.values() for dep in m.after]
        while pending:
            dep = pending.pop()
            if dep in selected:
                continue
            source = builtin_module(dep)
            if source is None:
                continue  # validate() will raise with a clear message
            pulled = WorkModule(**source.to_dict())
            pulled.pack = f"{pulled.pack}+auto"
            selected[dep] = pulled
            pending.extend(pulled.after)

        for disabled_id in config.get("disabled") or []:
            if disabled_id in selected:
                selected[disabled_id].enabled = False

        registry = cls(modules=sorted(selected.values(), key=lambda m: (m.priority, m.id)))
        registry.validate()
        return registry

    def validate(self) -> None:
        ids = {m.id for m in self.modules}
        for module in self.modules:
            module.validate()
            for dep in module.after:
                if dep not in ids:
                    raise ModuleError(
                        f"module {module.id!r} depends on {dep!r}, which is not enabled"
                    )
        self._assert_acyclic()

    def _assert_acyclic(self) -> None:
        by_id = {m.id: m for m in self.modules}
        state: dict[str, int] = {}

        def visit(node: str, trail: list[str]) -> None:
            if state.get(node) == 2:
                return
            if state.get(node) == 1:
                cycle = " -> ".join(trail + [node])
                raise ModuleError(f"module dependency cycle: {cycle}")
            state[node] = 1
            for dep in by_id[node].after:
                visit(dep, trail + [node])
            state[node] = 2

        for module in self.modules:
            visit(module.id, [])

    @property
    def active(self) -> list[WorkModule]:
        return [m for m in self.modules if m.enabled]

    def by_id(self, module_id: str) -> WorkModule | None:
        return next((m for m in self.modules if m.id == module_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {"modules": [m.to_dict() for m in self.modules]}


# --------------------------------------------------------------- selection


def eligible_modules(
    registry: ModuleRegistry,
    *,
    target_kind: str,
    completed: set[str],
    unit_state: str | None = None,
    path: str | None = None,
    in_flight: dict[str, int] | None = None,
    target: str | None = None,
    in_flight_targets: set[tuple[str, str]] | None = None,
) -> list[WorkModule]:
    """Modules that may run on one target right now, best first.

    `completed` is the set of module ids already done **for this target**, which
    is what makes ordering local rather than a global phase.

    `in_flight_targets` is the set of (module_id, target) pairs currently running.
    A `once_per_target` module already in flight for this exact target is skipped,
    so a single-target module (subject/finding identify, research, synthesis) is
    never dispatched to more than one agent at once -- while unit modules still
    parallelise freely across different units.
    """
    import fnmatch

    in_flight = in_flight or {}
    in_flight_targets = in_flight_targets or set()
    out: list[WorkModule] = []
    for module in registry.active:
        if module.source != target_kind:
            continue
        if module.once_per_target and module.id in completed:
            continue
        if module.once_per_target and target is not None and (module.id, target) in in_flight_targets:
            continue
        if any(dep not in completed for dep in module.after):
            continue
        if module.unit_state and unit_state and module.unit_state != unit_state:
            continue
        if module.path_globs and path:
            if not any(fnmatch.fnmatch(path, g) for g in module.path_globs):
                continue
        if module.exclude_globs and path:
            if any(fnmatch.fnmatch(path, g) for g in module.exclude_globs):
                continue
        if module.max_parallel is not None and in_flight.get(module.id, 0) >= module.max_parallel:
            continue
        out.append(module)
    return sorted(out, key=lambda m: (m.priority, m.id))


SUBJECT_TARGET = "__subject__"


class ModuleScheduler:
    """Decides the next module/target to dispatch, and tracks what is done.

    Progress is per-target: `completed[target] = {module_ids}`. That is what
    makes ordering local (a module's `after` is satisfied per target) rather than
    a global phase. State persists so a loop restart resumes where it left off.

    The loop feeds the scheduler facts (a unit was characterized, a finding
    exists) and asks for the next thing to run. The scheduler never does I/O
    except reading/writing its own JSON state.
    """

    def __init__(self, registry: ModuleRegistry, state: dict[str, Any] | None = None) -> None:
        self.registry = registry
        state = state or {}
        # target_key -> list[module_id] completed on that target
        self.completed: dict[str, list[str]] = dict(state.get("completed") or {})
        # unit_id -> compact unit dict, for path-glob matching and re-dispatch
        self.characterized: dict[str, dict[str, Any]] = dict(state.get("characterized") or {})
        # finding id -> compact finding dict, for finding-sourced modules
        self.findings: dict[str, dict[str, Any]] = dict(state.get("findings") or {})

    # -- state ---------------------------------------------------------------

    def to_state(self) -> dict[str, Any]:
        return {
            "completed": self.completed,
            "characterized": self.characterized,
            "findings": self.findings,
        }

    def _done_set(self, target: str) -> set[str]:
        return set(self.completed.get(target) or [])

    # -- facts fed by the loop ----------------------------------------------

    @staticmethod
    def _compact_unit(unit: dict[str, Any]) -> dict[str, Any]:
        return {k: unit.get(k) for k in ("id", "path", "name", "type", "line_start", "line_end")}

    def record_characterized(self, unit: dict[str, Any]) -> None:
        unit_id = str(unit.get("id") or "")
        if not unit_id:
            return
        self.characterized[unit_id] = self._compact_unit(unit)
        # Every breadth (characterize) module is done for this unit.
        for module in self.breadth_modules():
            self.mark_done(module.id, unit_id)

    def record_finding(self, finding: dict[str, Any]) -> None:
        finding_id = str(finding.get("id") or "")
        if finding_id:
            self.findings.setdefault(finding_id, {
                "id": finding_id,
                "path": finding.get("path") or finding.get("file"),
                "title": finding.get("title"),
            })

    def mark_done(self, module_id: str, target: str) -> None:
        done = self.completed.setdefault(target, [])
        if module_id not in done:
            done.append(module_id)

    # -- module categories ---------------------------------------------------

    def breadth_modules(self) -> list[WorkModule]:
        """Unit modules with no deps: these claim NEW coverage units."""
        return [m for m in self.registry.active
                if m.source == SOURCE_UNITS and not m.after]

    def has_breadth(self) -> bool:
        return bool(self.breadth_modules())

    # -- selection -----------------------------------------------------------

    def next_subject_module(
        self, in_flight: dict[str, int],
        in_flight_targets: set[tuple[str, str]] | None = None,
    ) -> WorkModule | None:
        eligible = eligible_modules(
            self.registry, target_kind=SOURCE_SUBJECT,
            completed=self._done_set(SUBJECT_TARGET), in_flight=in_flight,
            target=SUBJECT_TARGET, in_flight_targets=in_flight_targets,
        )
        return eligible[0] if eligible else None

    def next_unit_module(
        self, in_flight: dict[str, int],
        in_flight_targets: set[tuple[str, str]] | None = None,
    ) -> tuple[WorkModule, dict[str, Any]] | None:
        """Highest-priority follow-on module across all characterized units."""
        best: tuple[WorkModule, dict[str, Any]] | None = None
        for unit_id, unit in self.characterized.items():
            eligible = [
                m for m in eligible_modules(
                    self.registry, target_kind=SOURCE_UNITS,
                    completed=self._done_set(unit_id), path=unit.get("path"), in_flight=in_flight,
                    target=unit_id, in_flight_targets=in_flight_targets,
                )
                if m.after  # breadth (characterize) is claimed separately
            ]
            if not eligible:
                continue
            if best is None or eligible[0].priority < best[0].priority:
                best = (eligible[0], unit)
        return best

    def next_finding_module(
        self, in_flight: dict[str, int],
        in_flight_targets: set[tuple[str, str]] | None = None,
    ) -> tuple[WorkModule, dict[str, Any]] | None:
        for finding_id, finding in self.findings.items():
            eligible = eligible_modules(
                self.registry, target_kind=SOURCE_FINDINGS,
                completed=self._done_set(finding_id), path=finding.get("path"), in_flight=in_flight,
                target=finding_id, in_flight_targets=in_flight_targets,
            )
            if eligible:
                return eligible[0], finding
        return None


def describe(registry: ModuleRegistry) -> str:
    """Human-readable summary for status reports and operator review."""
    lines = []
    for module in registry.modules:
        flag = "" if module.enabled else "  (disabled)"
        dep = f"  after={','.join(module.after)}" if module.after else ""
        cap = f"  max={module.max_parallel}" if module.max_parallel else ""
        lines.append(
            f"[{module.priority:3}] {module.id:16} {module.task_class:15} "
            f"src={module.source}{dep}{cap}{flag}"
        )
    return "\n".join(lines)


def load_subject_config(workbench: dict[str, Any] | None) -> dict[str, Any]:
    """Read module config off a workbench's custom fields."""
    custom = (workbench or {}).get("custom_fields") or {}
    raw = custom.get("refall_modules")
    if not raw:
        return {}
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ModuleError(f"refall_modules is not valid JSON: {exc}") from exc
    if isinstance(raw, dict):
        return raw
    raise ModuleError("refall_modules must be an object or JSON string")
