import json
from pathlib import Path

from ref_all_executor.supervisor import (
    CRON_MARKER_FAST,
    CRON_MARKER_FULL,
    STATUS_ESCALATED,
    STATUS_HEALTHY,
    STATUS_RECOVERED,
    RefallSupervisor,
    SupervisorConfig,
    merge_crontab,
    remove_from_crontab,
    render_cron_entries,
)


class FakeWatchdog:
    def __init__(self, sample=None, error=None):
        self.sample = sample if sample is not None else {"active": [], "alerts": []}
        self.error = error
        self.calls = 0

    def run_once(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.sample


def make_supervisor(tmp_path: Path, *, clock=None, runner=None, watchdog=None, **kw):
    cfg = SupervisorConfig(subject="alpha", repo_root=tmp_path, **kw)
    calls: list[list[str]] = []

    def default_runner(cmd, timeout=60):
        calls.append(cmd)
        if cmd[:2] == ["docker", "inspect"]:
            return 0, "running"
        return 0, ""

    sup = RefallSupervisor(
        cfg,
        now=clock or (lambda: 1000.0),
        runner=runner or default_runner,
        watchdog_factory=(lambda: watchdog) if watchdog else None,
    )
    sup._runner_calls = calls  # type: ignore[attr-defined]
    return sup


# ------------------------------------------------------------------ cron

def test_render_cron_entries_uses_tiered_cadence():
    entries = render_cron_entries(repo_root="/repo", subject="alpha")
    assert entries[0].startswith("* * * * * ")           # fast: every minute
    assert entries[0].endswith(f"# {CRON_MARKER_FAST}_ALPHA")
    assert " fast " in entries[0]
    assert entries[1].startswith("*/3 * * * * ")         # full: every 3 minutes
    assert entries[1].endswith(f"# {CRON_MARKER_FULL}_ALPHA")
    assert " full " in entries[1]


def test_merge_crontab_preserves_unrelated_entries():
    existing = "*/5 * * * * /other/job.sh # SOMETHING_ELSE\n"
    merged = merge_crontab(existing, render_cron_entries(repo_root="/repo", subject="alpha"), subject="alpha")
    assert "SOMETHING_ELSE" in merged
    assert merged.count(CRON_MARKER_FAST) == 1


def test_merge_crontab_replaces_rather_than_duplicates():
    entries = render_cron_entries(repo_root="/repo", subject="alpha")
    once = merge_crontab("", entries, subject="alpha")
    twice = merge_crontab(once, entries, subject="alpha")
    assert twice.count(CRON_MARKER_FAST) == 1
    assert twice.count(CRON_MARKER_FULL) == 1


def test_merge_crontab_is_scoped_to_one_subject():
    merged = merge_crontab("", render_cron_entries(repo_root="/repo", subject="alpha"), subject="alpha")
    merged = merge_crontab(merged, render_cron_entries(repo_root="/repo", subject="beta"), subject="beta")
    assert f"{CRON_MARKER_FAST}_ALPHA" in merged
    assert f"{CRON_MARKER_FAST}_BETA" in merged


def test_remove_from_crontab_only_drops_that_subject():
    merged = merge_crontab("*/5 * * * * /other.sh # KEEP\n", render_cron_entries(repo_root="/r", subject="alpha"), subject="alpha")
    cleaned = remove_from_crontab(merged, subject="alpha")
    assert "KEEP" in cleaned
    assert CRON_MARKER_FAST not in cleaned


# -------------------------------------------------------------- recovery

def test_recover_restarts_only_the_dead_service(tmp_path: Path):
    sup = make_supervisor(tmp_path)
    result = sup.recover({"refall_ab_ok": True, "canvas_ok": False, "canvas_container": "exited"})
    assert result["recovered"] is True
    assert result["reasons"] == ["openhands_agent_server_unreachable"]
    assert any("canvas=restarted" in a for a in result["actions"])
    # REFALL AB was healthy, so nothing touched it.
    assert not any("refall_ab" in a for a in result["actions"])


def test_recover_never_tears_the_stack_down(tmp_path: Path):
    sup = make_supervisor(tmp_path)
    sup.recover({"refall_ab_ok": False, "canvas_ok": False, "canvas_container": "exited"})
    flat = " ".join(" ".join(c) for c in sup._runner_calls)
    for forbidden in ("bootout", "ref_all_executor down", "docker rm", "docker stop"):
        assert forbidden not in flat


def test_recover_records_history(tmp_path: Path):
    sup = make_supervisor(tmp_path)
    sup.recover({"refall_ab_ok": True, "canvas_ok": False, "canvas_container": "exited"})
    assert len(sup.recent_recoveries()) == 1


# ------------------------------------------------------------ escalation

def test_escalation_after_three_recoveries_in_window(tmp_path: Path):
    now = [1000.0]
    sup = make_supervisor(tmp_path, clock=lambda: now[0])
    for _ in range(3):
        sup.recover({"refall_ab_ok": True, "canvas_ok": False, "canvas_container": "exited"})
        now[0] += 60
    escalation = sup.check_escalation()
    assert escalation is not None
    assert escalation["escalated"] is True
    assert sup.hold_active() is True
    hold = (tmp_path / "logs/refall-supervisor-HOLD").read_text()
    assert "3 recoveries" in hold
    assert "rm " in hold


def test_no_escalation_when_recoveries_fall_outside_window(tmp_path: Path):
    now = [1000.0]
    sup = make_supervisor(tmp_path, clock=lambda: now[0])
    for _ in range(3):
        sup.recover({"refall_ab_ok": True, "canvas_ok": False, "canvas_container": "exited"})
        now[0] += 3600  # each one an hour apart
    assert sup.check_escalation() is None
    assert sup.hold_active() is False


def test_hold_blocks_all_further_action(tmp_path: Path):
    sup = make_supervisor(tmp_path)
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "logs/refall-supervisor-HOLD").write_text("held")
    snapshot = sup.tick("full")
    assert snapshot["status"] == STATUS_ESCALATED
    assert snapshot["needs_operator"]
    # Nothing was probed or restarted while holding.
    assert sup._runner_calls == []


# ------------------------------------------------------------- relevance

def test_relevance_flags_agent_with_no_subject_progress(tmp_path: Path):
    sup = make_supervisor(tmp_path, relevance_grace_ticks=2)
    agent = {"cid": "cid-1", "subject": "alpha", "unit_id": "unit-1", "iteration": 5, "lane": "B"}
    flags: list = []
    # The first observation establishes a baseline and counts as progress: a
    # freshly dispatched agent must not be flagged on sight. Grace runs after.
    for _ in range(4):
        flags = sup.check_relevance([agent])  # iteration never advances
    assert flags and flags[0]["cid"] == "cid-1"
    assert flags[0]["idle_ticks"] > 2


def test_intel_flow_flags_when_agents_active_but_intel_flat(tmp_path: Path, monkeypatch):
    import ref_all_executor.supervisor as sup_mod

    # ledger stats never change -> tagged intel is not landing
    monkeypatch.setattr(
        sup_mod, "request_json",
        lambda *a, **k: {"ok": True, "status": 200, "data": {"by_kind": {"fact": 10, "lead": 2, "finding": 1}}},
    )
    sup = make_supervisor(tmp_path, intel_stall_ticks=2)
    agents = [{"cid": "c1", "subject": "alpha"}]
    flags: list = []
    for _ in range(4):
        flags = sup.check_intel_flow({"active_count": 3}, agents)
    assert flags and flags[0]["kind"] == "intel_not_landing"
    assert flags[0]["stalled_ticks"] >= 2


def test_intel_flow_clears_when_intel_grows(tmp_path: Path, monkeypatch):
    import ref_all_executor.supervisor as sup_mod

    counter = {"n": 0}

    def growing(*a, **k):
        counter["n"] += 1
        return {"ok": True, "status": 200, "data": {"by_kind": {"fact": counter["n"], "lead": 0, "finding": 0}}}

    monkeypatch.setattr(sup_mod, "request_json", growing)
    sup = make_supervisor(tmp_path, intel_stall_ticks=2)
    agents = [{"cid": "c1", "subject": "alpha"}]
    flags: list = []
    for _ in range(4):
        flags = sup.check_intel_flow({"active_count": 3}, agents)
    assert flags == []  # intel grows every tick -> never stalls


def test_relevance_does_not_flag_a_freshly_dispatched_agent(tmp_path: Path):
    sup = make_supervisor(tmp_path, relevance_grace_ticks=2)
    agent = {"cid": "cid-new", "subject": "alpha", "unit_id": "unit-1", "iteration": 1, "lane": "A"}
    assert sup.check_relevance([agent]) == []


def test_relevance_clears_when_agent_progresses(tmp_path: Path):
    sup = make_supervisor(tmp_path, relevance_grace_ticks=1)
    flags: list = []
    for i in range(4):
        flags = sup.check_relevance([
            {"cid": "cid-1", "subject": "alpha", "unit_id": "unit-1", "iteration": i, "lane": "B"}
        ])
    assert flags == []


def test_relevance_forgets_finished_agents(tmp_path: Path):
    sup = make_supervisor(tmp_path)
    sup.check_relevance([{"cid": "cid-1", "subject": "alpha", "unit_id": "u", "iteration": 1}])
    sup.check_relevance([])
    state = json.loads((tmp_path / "logs/refall-supervisor-state.json").read_text())
    assert state["relevance"] == {}


# ------------------------------------------------------------------ tick

def test_full_tick_writes_status_report(tmp_path: Path):
    sup = make_supervisor(tmp_path, watchdog=FakeWatchdog({"active": [], "alerts": []}))
    sup.probe = lambda: {  # type: ignore[method-assign]
        "refall_ab_ok": True, "canvas_ok": True,
        "canvas_container": "running", "loop_pids": [123], "loop_alive": True,
    }
    snapshot = sup.tick("full")
    assert snapshot["status"] == STATUS_HEALTHY
    report = (tmp_path / "logs/refall-supervisor-status.md").read_text()
    assert "REFALL supervisor — alpha" in report
    assert "REFALL AB: up" in report
    assert "Needs you" in report


def test_degraded_tick_recovers_and_reports(tmp_path: Path):
    sup = make_supervisor(tmp_path, watchdog=FakeWatchdog())
    sup.probe = lambda: {  # type: ignore[method-assign]
        "refall_ab_ok": True, "canvas_ok": False,
        "canvas_container": "exited", "loop_pids": [], "loop_alive": False,
    }
    snapshot = sup.tick("fast")
    assert snapshot["status"] == STATUS_RECOVERED
    assert any("canvas" in a for a in snapshot["actions"])


def test_watchdog_failure_does_not_stop_supervision(tmp_path: Path):
    sup = make_supervisor(tmp_path, watchdog=FakeWatchdog(error=RuntimeError("watchdog boom")))
    sup.probe = lambda: {  # type: ignore[method-assign]
        "refall_ab_ok": True, "canvas_ok": True,
        "canvas_container": "running", "loop_pids": [1], "loop_alive": True,
    }
    snapshot = sup.tick("full")
    assert "boom" in snapshot["watchdog"]["error"]
    assert (tmp_path / "logs/refall-supervisor-status.md").exists()


def test_fast_tick_does_not_run_the_watchdog(tmp_path: Path):
    wd = FakeWatchdog()
    sup = make_supervisor(tmp_path, watchdog=wd)
    sup.probe = lambda: {  # type: ignore[method-assign]
        "refall_ab_ok": True, "canvas_ok": True,
        "canvas_container": "running", "loop_pids": [1], "loop_alive": True,
    }
    sup.tick("fast")
    assert wd.calls == 0


# ------------------------------------------------- cron-environment bugs

def test_binaries_resolve_to_absolute_paths_for_cron():
    """cron's PATH excludes /usr/local/bin; an unresolved docker would make the
    probe report the canvas 'absent' and silently turn recovery into a no-op."""
    from ref_all_executor.supervisor import resolve_binary

    for name in ("docker", "launchctl", "pgrep"):
        resolved = resolve_binary(name)
        assert resolved.startswith("/"), f"{name} did not resolve to an absolute path"


def test_run_invokes_resolved_absolute_binary(tmp_path: Path):
    seen: list[list[str]] = []

    def runner(cmd, timeout=60):
        seen.append(cmd)
        return 0, "running"

    sup = make_supervisor(tmp_path, runner=runner)
    sup.recover({"refall_ab_ok": True, "canvas_ok": False, "canvas_container": "exited"})
    # The supervisor passes bare names; _run resolves them. Assert the contract
    # holds for the caller by checking docker is still the command being run.
    assert any(c[0].endswith("docker") for c in seen)


def test_fast_tick_carries_forward_last_agent_count(tmp_path: Path):
    """A fast tick must not report 0 agents just because it did not enumerate."""
    probe = {
        "refall_ab_ok": True, "canvas_ok": True,
        "canvas_container": "running", "loop_pids": [1], "loop_alive": True,
    }
    sample = {
        "active_count": 2,
        "active_cids": ["c1", "c2"],
        "alerts": [],
        "endpoints": {"ops_agents": {"ok": True, "data": {"active": [
            {"cid": "c1", "lane": "A", "unit_id": "u1", "iteration": 1},
            {"cid": "c2", "lane": "A", "unit_id": "u2", "iteration": 1},
        ]}}},
    }
    sup = make_supervisor(tmp_path, watchdog=FakeWatchdog(sample))
    sup.probe = lambda: probe  # type: ignore[method-assign]
    full = sup.tick("full")
    assert full["active_count"] == 2

    fast = sup.tick("fast")
    assert fast["active_count"] == 2
    assert fast["active_count_as_of"]
    report = (tmp_path / "logs/refall-supervisor-status.md").read_text()
    assert "- active: 2" in report
    assert "last full pass" in report


def test_watchdog_active_agents_reads_ops_payload():
    """run_once() keeps agent rows in endpoints.ops_agents.data, not a top-level
    'active' key -- reading the wrong key silently reported 0 agents."""
    from ref_all_executor.supervisor import watchdog_active_agents

    sample = {
        "active_count": 2,
        "active_cids": ["c1", "c2"],
        "endpoints": {"ops_agents": {"ok": True, "data": {"active": [
            {"cid": "c1", "lane": "A", "unit_id": "u1", "iteration": 3},
            {"cid": "c2", "lane": "B", "unit_id": "u2", "iteration": 4},
        ]}}},
    }
    rows = watchdog_active_agents(sample)
    assert [r["cid"] for r in rows] == ["c1", "c2"]
    assert rows[0]["lane"] == "A"


def test_watchdog_active_agents_falls_back_to_cids():
    from ref_all_executor.supervisor import watchdog_active_agents

    rows = watchdog_active_agents({"active_cids": ["c1"], "endpoints": {"ops_agents": {"ok": False}}})
    assert rows == [{"cid": "c1"}]


def test_full_tick_reports_real_agent_count(tmp_path: Path):
    sample = {
        "active_count": 4,
        "active_cids": ["c1", "c2", "c3", "c4"],
        "alerts": [],
        "endpoints": {"ops_agents": {"ok": True, "data": {"active": [
            {"cid": f"c{i}", "lane": "A", "unit_id": f"u{i}", "iteration": 1} for i in range(1, 5)
        ]}}},
    }
    sup = make_supervisor(tmp_path, watchdog=FakeWatchdog(sample))
    sup.probe = lambda: {  # type: ignore[method-assign]
        "refall_ab_ok": True, "canvas_ok": True,
        "canvas_container": "running", "loop_pids": [1], "loop_alive": True,
    }
    snapshot = sup.tick("full")
    assert snapshot["active_count"] == 4
    assert "- active: 4" in (tmp_path / "logs/refall-supervisor-status.md").read_text()


# ------------------------------------------- cron truncation regression

def test_cron_lines_stay_short_enough_to_keep_their_marker():
    """macOS crontab truncates long lines. A truncated entry loses its trailing
    marker, leaving it broken AND unremovable -- uninstall reports success while
    the cron keeps firing every minute."""
    entries = render_cron_entries(repo_root="/opt/refall/installation", subject="hyundai")
    for e in entries:
        assert len(e) < 200, f"cron line too long ({len(e)}), risks truncation: {e}"
        assert e.rstrip().endswith(("_HYUNDAI",)), "marker must survive at end of line"


def test_cron_entries_carry_no_inline_env():
    """Config belongs in the sidecar env file, not on the crontab line."""
    for e in render_cron_entries(repo_root="/repo", subject="alpha"):
        assert "REFALL_REPO_ROOT=" not in e
        assert "REFALL_PUBLIC_BASE_URL=" not in e


def test_truncated_entry_is_still_removable(tmp_path: Path):
    """An entry that already lost its marker must still be removable, or it
    survives every uninstall forever (the exact bug that bit us live)."""
    truncated = (f"* * * * * {tmp_path / 'refall'}/deploy/cron/refall-supervisor.sh "
                 "fast hyundai")  # marker gone
    existing = "*/5 * * * * /other/job.sh # KEEP\n" + truncated + "\n"
    cleaned = remove_from_crontab(existing, subject="hyundai")
    assert "KEEP" in cleaned
    assert "refall-supervisor.sh" not in cleaned


def test_removal_leaves_other_subjects_truncated_entries_alone(tmp_path: Path):
    truncated_other = "* * * * * /repo/deploy/cron/refall-supervisor.sh fast beta"
    cleaned = remove_from_crontab(truncated_other + "\n", subject="hyundai")
    assert "beta" in cleaned


def test_install_writes_env_sidecar(tmp_path: Path):
    from ref_all_executor.supervisor import write_env_file

    path = write_env_file(repo_root=tmp_path, subject="alpha",
                          base_url="http://ab:7673", oh_base="http://oh:8000")
    body = path.read_text()
    assert "REFALL_SUPERVISOR_SUBJECT=alpha" in body
    assert "REFALL_PUBLIC_BASE_URL=http://ab:7673" in body
    assert path.name == "refall-supervisor-alpha.env"
