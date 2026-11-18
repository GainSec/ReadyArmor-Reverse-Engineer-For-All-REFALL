import pytest

from ref_all_executor.work_modules import (
    SOURCE_FINDINGS,
    SOURCE_SUBJECT,
    SOURCE_UNITS,
    ModuleError,
    ModuleRegistry,
    WorkModule,
    eligible_modules,
    load_subject_config,
    pack_names,
)


# ------------------------------------------------------------ definitions

def test_module_rejects_unknown_task_class():
    with pytest.raises(ModuleError, match="unknown task_class"):
        WorkModule(id="x", task_class="not_a_real_class").validate()


def test_module_rejects_unknown_source():
    with pytest.raises(ModuleError, match="unknown source"):
        WorkModule(id="x", task_class="characterize", source="nowhere").validate()


def test_from_dict_rejects_unknown_keys():
    with pytest.raises(ModuleError, match="unknown keys"):
        WorkModule.from_dict({"id": "x", "task_class": "characterize", "bogus": 1})


# ---------------------------------------------------------------- registry

def test_default_is_a_security_assessment():
    """An unconfigured subject gets a security assessment (operator decision),
    which still includes characterize via dependency auto-resolution."""
    reg = ModuleRegistry.from_config(None)
    ids = {m.id for m in reg.active}
    assert "characterize" in ids     # baseline pulled in by dependency
    assert "sec_recon" in ids
    assert "sec_review" in ids


def test_packs_combine_without_ordering_between_them():
    """The user's core requirement: combine RE + security + research on one
    subject, no global phase between packs."""
    reg = ModuleRegistry.from_config({
        "packs": ["baseline", "reverse_engineering", "security_assessment", "research"],
    })
    ids = {m.id for m in reg.active}
    assert "characterize" in ids
    assert "re_decompose" in ids
    assert "sec_recon" in ids
    assert "res_research" in ids


def test_custom_subloop_module_slots_in_at_runtime():
    """A subject-specific subloop is just data added to the config."""
    reg = ModuleRegistry.from_config({
        "packs": ["baseline"],
        "modules": [{
            "id": "hyundai_ivi_recon",
            "task_class": "recon",
            "after": ["characterize"],
            "path_globs": ["*/ivi/*", "*/telematics/*"],
            "objective": "Focus on the IVI and telematics subsystems.",
        }],
    })
    m = reg.by_id("hyundai_ivi_recon")
    assert m is not None
    assert m.after == ["characterize"]
    assert m.path_globs == ["*/ivi/*", "*/telematics/*"]


def test_overrides_and_disabled():
    reg = ModuleRegistry.from_config({
        "packs": ["baseline", "security_assessment"],
        "overrides": {"characterize": {"priority": 5}},
        "disabled": ["sec_verify"],
    })
    assert reg.by_id("characterize").priority == 5
    assert reg.by_id("sec_verify").enabled is False
    assert "sec_verify" not in {m.id for m in reg.active}


def test_dependency_on_disabled_module_is_rejected():
    with pytest.raises(ModuleError, match="depends on"):
        ModuleRegistry.from_config({
            "packs": [],
            "modules": [{"id": "a", "task_class": "review", "after": ["missing"]}],
        })


def test_dependency_cycle_is_rejected():
    with pytest.raises(ModuleError, match="cycle"):
        ModuleRegistry.from_config({
            "packs": [],
            "modules": [
                {"id": "a", "task_class": "review", "after": ["b"]},
                {"id": "b", "task_class": "recon", "after": ["a"]},
            ],
        })


def test_unknown_pack_is_rejected():
    with pytest.raises(ModuleError, match="unknown pack"):
        ModuleRegistry.from_config({"packs": ["not_a_pack"]})


# --------------------------------------------------------------- selection

def _reg():
    return ModuleRegistry.from_config({"packs": ["baseline", "security_assessment"]})


def test_eligibility_is_local_not_a_global_phase():
    """sec_recon requires characterize ON THIS TARGET. A target that has been
    characterized is eligible even if other targets have not."""
    reg = _reg()
    # Fresh target: only characterize is eligible (no deps).
    fresh = eligible_modules(reg, target_kind=SOURCE_UNITS, completed=set())
    assert [m.id for m in fresh] == ["characterize"]

    # Same target after characterize: recon unlocks, characterize is done.
    after = eligible_modules(reg, target_kind=SOURCE_UNITS, completed={"characterize"})
    assert "sec_recon" in {m.id for m in after}
    assert "characterize" not in {m.id for m in after}


def test_eligibility_orders_by_priority():
    reg = ModuleRegistry.from_config({
        "packs": ["baseline", "security_assessment"],
    })
    after = eligible_modules(reg, target_kind=SOURCE_UNITS,
                             completed={"characterize", "sec_recon"})
    # sec_review (priority 45) should precede anything higher-numbered.
    ids = [m.id for m in after]
    assert ids == sorted(ids, key=lambda i: reg.by_id(i).priority)


def test_max_parallel_caps_a_module():
    reg = ModuleRegistry.from_config({
        "packs": ["baseline"],
        "overrides": {"characterize": {"max_parallel": 2}},
    })
    capped = eligible_modules(reg, target_kind=SOURCE_UNITS, completed=set(),
                              in_flight={"characterize": 2})
    assert capped == []
    ok = eligible_modules(reg, target_kind=SOURCE_UNITS, completed=set(),
                          in_flight={"characterize": 1})
    assert [m.id for m in ok] == ["characterize"]


def test_path_globs_filter_targets():
    reg = ModuleRegistry.from_config({
        "packs": [],
        "modules": [{"id": "only_c", "task_class": "review",
                     "path_globs": ["*.c"], "source": "coverage_units"}],
    })
    assert eligible_modules(reg, target_kind=SOURCE_UNITS, completed=set(), path="a/b.c")
    assert not eligible_modules(reg, target_kind=SOURCE_UNITS, completed=set(), path="a/b.py")


def test_finding_and_subject_sourced_modules_are_separate():
    reg = ModuleRegistry.from_config({"packs": ["security_assessment", "research"]})
    unit_mods = {m.id for m in eligible_modules(reg, target_kind=SOURCE_UNITS,
                                                completed={"characterize", "sec_recon"})}
    finding_mods = {m.id for m in eligible_modules(reg, target_kind=SOURCE_FINDINGS,
                                                   completed=set())}
    subject_mods = {m.id for m in eligible_modules(reg, target_kind=SOURCE_SUBJECT,
                                                   completed=set())}
    assert "sec_verify" in finding_mods       # verify runs on findings
    assert "sec_verify" not in unit_mods
    assert "res_research" in subject_mods      # research runs once on the subject


# ----------------------------------------------------------------- config

def test_load_subject_config_from_json_string():
    wb = {"custom_fields": {"refall_modules": '{"packs": ["baseline"]}'}}
    assert load_subject_config(wb) == {"packs": ["baseline"]}


def test_load_subject_config_from_dict():
    wb = {"custom_fields": {"refall_modules": {"packs": ["research"]}}}
    assert load_subject_config(wb) == {"packs": ["research"]}


def test_load_subject_config_absent_is_empty():
    assert load_subject_config({"custom_fields": {}}) == {}
    assert load_subject_config(None) == {}


def test_all_builtin_packs_validate():
    for pack in pack_names():
        ModuleRegistry.from_config({"packs": [pack]})


# ---------------------------------------------------------- scheduler

from ref_all_executor.work_modules import ModuleScheduler, SUBJECT_TARGET


def _sched(cfg=None):
    reg = ModuleRegistry.from_config(cfg or {"packs": ["security_assessment", "reverse_engineering"]})
    return ModuleScheduler(reg)


def test_scheduler_breadth_is_characterize():
    s = _sched()
    breadth = {m.id for m in s.breadth_modules()}
    assert breadth == {"characterize"}   # only dep-free unit module claims new units


def test_scheduler_no_unit_work_until_characterized():
    s = _sched()
    assert s.next_unit_module({}) is None   # nothing characterized yet


def test_scheduler_unlocks_followon_after_characterize():
    s = _sched()
    s.record_characterized({"id": "unit-1", "path": "a/b.c"})
    picked = s.next_unit_module({})
    assert picked is not None
    module, unit = picked
    assert unit["id"] == "unit-1"
    assert module.after   # a follow-on, not characterize
    assert module.id in ("sec_recon", "re_decompose")


def test_scheduler_marks_progress_and_advances():
    s = _sched()
    s.record_characterized({"id": "unit-1"})
    first = s.next_unit_module({})[0]
    s.mark_done(first.id, "unit-1")
    second = s.next_unit_module({})
    # second pick differs from the first (progress advanced) or unlocks deeper work
    if second is not None:
        assert second[0].id != first.id or second[1]["id"] != "unit-1"


def test_scheduler_subject_modules_run_once():
    s = _sched({"packs": ["research"]})
    m = s.next_subject_module({})
    assert m is not None and m.source == "subject"
    s.mark_done(m.id, SUBJECT_TARGET)
    # after marking, a different subject module (or none) comes next
    nxt = s.next_subject_module({})
    assert nxt is None or nxt.id != m.id


def test_scheduler_finding_modules_target_findings():
    s = _sched()
    assert s.next_finding_module({}) is None
    s.record_finding({"id": "find-1", "path": "a/b.c"})
    picked = s.next_finding_module({})
    assert picked is not None
    module, finding = picked
    assert finding["id"] == "find-1"
    assert module.task_class == "verify"


def test_scheduler_state_roundtrips():
    s = _sched()
    s.record_characterized({"id": "unit-1", "path": "a/b.c"})
    s.mark_done("sec_recon", "unit-1")
    s.record_finding({"id": "find-1"})
    restored = ModuleScheduler(s.registry, s.to_state())
    assert restored.characterized["unit-1"]["path"] == "a/b.c"
    assert "sec_recon" in restored._done_set("unit-1")
    assert "find-1" in restored.findings


def test_scheduler_respects_max_parallel_in_flight():
    s = _sched({"packs": ["baseline", "security_assessment"],
                "overrides": {"sec_recon": {"max_parallel": 1}}})
    s.record_characterized({"id": "unit-1"})
    s.record_characterized({"id": "unit-2"})
    # sec_recon capped at 1 in-flight: only reachable when not already running
    picked = s.next_unit_module({"sec_recon": 1})
    if picked is not None:
        assert picked[0].id != "sec_recon"


def test_exclude_globs_keep_deep_modules_off_media_but_on_binaries():
    """Media/HAF get characterized (metadata) but NOT deep-analysed; binaries do.
    This is the resource-waste guard: no recon/decompile on 15k image files."""
    reg = ModuleRegistry.from_config({
        "packs": ["security_assessment", "reverse_engineering"],
        "overrides": {
            "sec_recon": {"exclude_globs": ["*.bmp", "*/HAF/*", "*.hafp"]},
            "re_decompose": {"exclude_globs": ["*.bmp", "*/HAF/*", "*.hafp"]},
            "sec_review": {"exclude_globs": ["*.bmp", "*/HAF/*", "*.hafp"]},
            "re_review": {"exclude_globs": ["*.bmp", "*/HAF/*", "*.hafp"]},
        },
    })
    done = {"characterize", "sec_recon"}
    # binary: deep modules eligible
    on_bin = {m.id for m in eligible_modules(reg, target_kind=SOURCE_UNITS,
                                             completed=done, path="system/app.exe")}
    assert "re_decompose" in on_bin
    # image: excluded
    on_img = eligible_modules(reg, target_kind=SOURCE_UNITS,
                              completed=done, path="skin/btn.bmp")
    assert on_img == []
    # HAF: excluded
    on_haf = eligible_modules(reg, target_kind=SOURCE_UNITS,
                              completed=done, path="Storage Card4/HAF/x.hafp")
    assert on_haf == []


def test_exclude_globs_round_trips_through_dict():
    m = WorkModule.from_dict({"id": "x", "task_class": "review",
                              "exclude_globs": ["*.bmp", "*/HAF/*"]})
    assert m.exclude_globs == ["*.bmp", "*/HAF/*"]
    assert m.to_dict()["exclude_globs"] == ["*.bmp", "*/HAF/*"]


def test_once_per_target_module_not_redispatched_while_in_flight():
    """A single-target module (subject identify/research) already running must not
    be dispatched to a second agent -- prevents N agents doing the same work."""
    from ref_all_executor.work_modules import SUBJECT_TARGET
    s = _sched({"packs": ["research"]})  # research is subject-sourced, once_per_target
    m = s.next_subject_module({})
    assert m is not None   # eligible when nothing in flight
    # now it's in flight for the subject target -> not offered again
    in_flight_targets = {(m.id, SUBJECT_TARGET)}
    again = s.next_subject_module({}, in_flight_targets)
    assert again is None or again.id != m.id


def test_unit_module_still_parallelises_across_different_units():
    """The dedup is per-(module,target): the SAME module may run on DIFFERENT
    units at once -- only same-unit re-dispatch is blocked."""
    s = _sched({"packs": ["security_assessment"]})
    s.record_characterized({"id": "unit-1"})
    s.record_characterized({"id": "unit-2"})
    # sec_recon running on unit-1 must not block sec_recon on unit-2
    in_flight_targets = {("sec_recon", "unit-1")}
    picked = s.next_unit_module({}, in_flight_targets)
    assert picked is not None
    module, unit = picked
    assert (module.id, unit["id"]) not in in_flight_targets
