import pytest


class FakeCoverage:
    def plan_progress(self, subject):
        return {"total": 1, "open": 0, "claimed": 0, "done": 1}

    def findings_summary(self, subject):
        return {"total": 0, "by_severity": {}}


def test_binresearch_publishes_visual_before_logging_complete(monkeypatch):
    import drive_binresearch

    events = []
    monkeypatch.setattr(drive_binresearch, "ensure_r2", lambda: True)
    monkeypatch.setattr(drive_binresearch, "CoverageClient", lambda: FakeCoverage())
    monkeypatch.setattr(drive_binresearch, "log", lambda msg: events.append(("log", msg)))
    monkeypatch.setattr(
        drive_binresearch,
        "publish_final_visual",
        lambda subject, title: events.append(("visual", subject, title)) or {"oid": "obj_test", "url": "http://wb/o/obj_test"},
    )

    drive_binresearch.run("example-binary", "bin", claude=0, codex=0, units=0)

    visual_idx = next(i for i, event in enumerate(events) if event[0] == "visual")
    complete_idx = next(i for i, event in enumerate(events) if "binary research complete" in event[1])
    assert visual_idx < complete_idx


def test_source_research_publishes_visual_before_logging_complete(monkeypatch):
    import drive_research

    events = []
    monkeypatch.setattr(drive_research, "ensure_l1", lambda subject: None)
    monkeypatch.setattr(drive_research, "CoverageClient", lambda: FakeCoverage())
    monkeypatch.setattr(drive_research, "log", lambda msg: events.append(("log", msg)))
    monkeypatch.setattr(
        drive_research,
        "publish_final_visual",
        lambda subject, title: events.append(("visual", subject, title)) or {"oid": "obj_test", "url": "http://wb/o/obj_test"},
    )

    drive_research.run("some-subject", claude=0, codex=0, units=0)

    visual_idx = next(i for i, event in enumerate(events) if event[0] == "visual")
    complete_idx = next(i for i, event in enumerate(events) if "research complete" in event[1])
    assert visual_idx < complete_idx


def test_binresearch_runs_without_default_batch_cap_until_frontier_exhausted(monkeypatch):
    import drive_binresearch

    class ProgressingCoverage:
        def __init__(self):
            self.calls = 0

        def plan_progress(self, subject):
            self.calls += 1
            if self.calls < 3:
                return {"total": 1, "open": 1, "claimed": 0, "done": 0}
            return {"total": 1, "open": 0, "claimed": 0, "done": 1}

        def findings_summary(self, subject):
            return {"total": 0, "by_severity": {}}

    events = []
    monkeypatch.setattr(drive_binresearch, "ensure_r2", lambda: True)
    monkeypatch.setattr(drive_binresearch, "CoverageClient", ProgressingCoverage)
    monkeypatch.setattr(drive_binresearch, "log", lambda msg: events.append(msg))
    monkeypatch.setattr(drive_binresearch.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        drive_binresearch,
        "publish_final_visual",
        lambda subject, title: {"oid": "obj_test", "url": "http://wb/o/obj_test"},
    )

    drive_binresearch.run("example-binary", "bin", claude=0, codex=0, units=0)

    assert any("binary research complete" in msg for msg in events)
    assert not any("max_batches" in msg for msg in events)


def test_binresearch_does_not_fail_fast_by_default(monkeypatch):
    import drive_binresearch

    class ProgressingCoverage:
        def __init__(self):
            self.calls = 0

        def plan_progress(self, subject):
            self.calls += 1
            if self.calls < 3:
                return {"total": 1, "open": 1, "claimed": 0, "done": 0}
            return {"total": 1, "open": 0, "claimed": 0, "done": 1}

        def findings_summary(self, subject):
            return {"total": 0, "by_severity": {}}

    events = []
    monkeypatch.setattr(drive_binresearch, "ensure_r2", lambda: True)
    monkeypatch.setattr(drive_binresearch, "CoverageClient", ProgressingCoverage)
    monkeypatch.setattr(drive_binresearch, "log", lambda msg: events.append(msg))
    monkeypatch.setattr(drive_binresearch.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        drive_binresearch,
        "_run_agent",
        lambda agent_id, subject, binrel, units, results, lane="A": results.update({agent_id: "error:boom"}),
    )
    monkeypatch.setattr(
        drive_binresearch,
        "publish_final_visual",
        lambda subject, title: {"oid": "obj_test", "url": "http://wb/o/obj_test"},
    )

    drive_binresearch.run("example-binary", "bin", claude=1, codex=0, units=0)

    assert any("binary research complete" in msg for msg in events)
    assert not any("FAIL-FAST" in msg for msg in events)


def test_binresearch_waits_when_only_claimed_work_remains(monkeypatch):
    import drive_binresearch

    class ClaimedThenDoneCoverage:
        def __init__(self):
            self.calls = 0

        def plan_progress(self, subject):
            self.calls += 1
            if self.calls <= 2:
                return {"total": 1, "open": 0, "claimed": 1, "done": 0}
            return {"total": 1, "open": 0, "claimed": 0, "done": 1}

        def findings_summary(self, subject):
            return {"total": 0, "by_severity": {}}

    events = []
    monkeypatch.setattr(drive_binresearch, "ensure_r2", lambda: True)
    monkeypatch.setattr(drive_binresearch, "CoverageClient", ClaimedThenDoneCoverage)
    monkeypatch.setattr(drive_binresearch, "log", lambda msg: events.append(msg))
    monkeypatch.setattr(drive_binresearch.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        drive_binresearch,
        "_run_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not launch agents")),
    )
    monkeypatch.setattr(
        drive_binresearch,
        "publish_final_visual",
        lambda subject, title: {"oid": "obj_test", "url": "http://wb/o/obj_test"},
    )

    drive_binresearch.run("example-binary", "bin", claude=2, codex=2, units=1)

    assert any("waiting for 1 claimed" in msg for msg in events)
    assert any("binary research complete" in msg for msg in events)


def test_source_research_waits_when_only_claimed_work_remains(monkeypatch):
    import drive_research

    class ClaimedThenDoneCoverage:
        def __init__(self):
            self.calls = 0

        def plan_progress(self, subject):
            self.calls += 1
            if self.calls <= 2:
                return {"total": 1, "open": 0, "claimed": 1, "done": 0}
            return {"total": 1, "open": 0, "claimed": 0, "done": 1}

        def findings_summary(self, subject):
            return {"total": 0, "by_severity": {}}

    events = []
    monkeypatch.setattr(drive_research, "ensure_l1", lambda subject: None)
    monkeypatch.setattr(drive_research, "CoverageClient", ClaimedThenDoneCoverage)
    monkeypatch.setattr(drive_research, "log", lambda msg: events.append(msg))
    monkeypatch.setattr(drive_research.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        drive_research,
        "_run_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not launch agents")),
    )
    monkeypatch.setattr(
        drive_research,
        "publish_final_visual",
        lambda subject, title: {"oid": "obj_test", "url": "http://wb/o/obj_test"},
    )

    drive_research.run("some-subject", claude=2, codex=2, units=1)

    assert any("waiting for 1 claimed" in msg for msg in events)
    assert any("research complete" in msg for msg in events)


def test_characterize_publishes_coverage_visual_before_done(monkeypatch):
    import drive_characterize

    class CharacterizeCoverage:
        def gate(self, subject, threshold):
            return {"locked": False}

        def coverage(self, subject):
            return {
                "characterized_pct": 100.0,
                "lines_covered": 10,
                "lines_total": 10,
                "files_done": 1,
                "files_total": 1,
            }

    events = []
    monkeypatch.setattr(drive_characterize, "ensure_l1", lambda subject: None)
    monkeypatch.setattr(drive_characterize, "CoverageClient", lambda: CharacterizeCoverage())
    monkeypatch.setattr(drive_characterize, "log", lambda msg: events.append(("log", msg)))
    monkeypatch.setattr(
        drive_characterize,
        "publish_coverage_visual",
        lambda subject: events.append(("visual", subject)) or {"oid": "obj_test", "url": "http://wb/o/obj_test"},
    )

    drive_characterize.run("some-subject", claude=0, codex=0, units=0, threshold=0.95)

    visual_idx = next(i for i, event in enumerate(events) if event[0] == "visual")
    done_idx = next(i for i, event in enumerate(events) if "GATE OPEN" in event[1])
    assert visual_idx < done_idx


def test_binreview_publishes_visual_after_review(monkeypatch, capsys):
    import drive_binreview

    class ReviewCoverage:
        def findings(self, subject, status=None):
            return [{"id": "finding-1"}]

        def funnel(self, subject):
            return {"candidates": 1, "valid": 1}

    events = []
    monkeypatch.setattr(drive_binreview, "CoverageClient", lambda: ReviewCoverage())
    monkeypatch.setattr(drive_binreview, "log", lambda msg: events.append(("log", msg)))
    monkeypatch.setattr(
        drive_binreview,
        "publish_final_visual",
        lambda subject, title: events.append(("visual", subject, title)) or {"oid": "obj_test", "url": "http://wb/o/obj_test"},
    )
    monkeypatch.setattr(drive_binreview, "run_validation", lambda subject, binrel, claude, codex: None)

    monkeypatch.setattr(drive_binreview, "_run_agent", lambda agent_id, subject, binrel, finding_ids, results, lane="A": results.update({agent_id: "finished"}))

    drive_binreview.run("example-binary", "bin", claude=1, codex=0)

    assert ("visual", "example-binary", "example-binary — Binary Security Research") in events
    assert '"visual"' in capsys.readouterr().out


def test_binreview_runs_validation_before_final_visual(monkeypatch):
    import drive_binreview

    class ReviewCoverage:
        def findings(self, subject, status=None):
            return [{"id": "finding-1"}] if status == "PROVISIONALLY_VALID" else []

        def funnel(self, subject):
            return {"candidates": 1, "valid": 1}

    events = []
    monkeypatch.setattr(drive_binreview, "CoverageClient", lambda: ReviewCoverage())
    monkeypatch.setattr(drive_binreview, "log", lambda msg: events.append(("log", msg)))
    monkeypatch.setattr(
        drive_binreview,
        "publish_final_visual",
        lambda subject, title: events.append(("visual", subject, title)) or {"oid": "obj_test", "url": "http://wb/o/obj_test"},
    )
    monkeypatch.setattr(
        drive_binreview,
        "run_validation",
        lambda subject, binrel, claude, codex: events.append(("validation", subject, binrel, claude, codex)),
    )
    monkeypatch.setattr(
        drive_binreview,
        "_run_agent",
        lambda agent_id, subject, binrel, finding_ids, results, lane="A": results.update({agent_id: "finished"}),
    )

    drive_binreview.run("example-binary", "bin", claude=2, codex=2)

    validation_idx = next(i for i, event in enumerate(events) if event[0] == "validation")
    visual_idx = next(i for i, event in enumerate(events) if event[0] == "visual")
    assert validation_idx < visual_idx
    assert events[validation_idx] == ("validation", "example-binary", "bin", 2, 2)


def test_binvalidate_sends_unconfirmed_non_rejected_findings(monkeypatch):
    import drive_binvalidate

    class ValidationCoverage:
        def findings(self, subject, status=None):
            return [
                {"id": "valid-missing", "status": "VALID", "repro_status": "not_attempted", "production_viability": None, "critic_reasoning": None},
                {"id": "valid-confirmed", "status": "VALID", "repro_status": "runtime_confirmed", "production_viability": "done", "critic_reasoning": "done"},
                {"id": "valid-blocked", "status": "VALID", "repro_status": "runtime_blocked", "production_viability": "attempted", "critic_reasoning": "raw output"},
                {"id": "needs-research", "status": "NEEDS_RESEARCH", "repro_status": "static_only", "production_viability": "static", "critic_reasoning": "trace"},
                {"id": "fp", "status": "FALSE_POSITIVE", "repro_status": "not_attempted", "production_viability": None, "critic_reasoning": None},
                {"id": "dup", "status": "DUPLICATE", "repro_status": "not_attempted", "production_viability": None, "critic_reasoning": None},
                {"id": "chainable", "status": "CHAINABLE_DEFERRED", "repro_status": "static_only", "production_viability": "real sink, no standalone path", "critic_reasoning": "preserve for chains"},
            ]

    events = []
    monkeypatch.setattr(drive_binvalidate, "CoverageClient", lambda: ValidationCoverage())
    monkeypatch.setattr(drive_binvalidate, "log", lambda msg: events.append(("log", msg)))
    monkeypatch.setattr(
        drive_binvalidate,
        "publish_final_visual",
        lambda subject, title: events.append(("visual", subject, title)) or {"oid": "obj_test", "url": "http://wb/o/obj_test"},
    )
    monkeypatch.setattr(
        drive_binvalidate,
        "_run_agent",
        lambda agent_id, subject, binrel, finding_ids, results, lane="A": events.append(("agent", agent_id, finding_ids, lane)) or results.update({agent_id: "finished"}),
    )

    drive_binvalidate.run("example-binary", "bin", claude=1, codex=1)

    sent = [fid for event in events if event[0] == "agent" for fid in event[2]]
    assert sorted(sent) == ["needs-research", "valid-blocked", "valid-missing"]
    assert ("visual", "example-binary", "example-binary — Binary Security Research") in events


def test_binvalidate_publishes_vendor_disclosure_when_validation_is_complete(monkeypatch):
    import drive_binvalidate

    class ValidationCoverage:
        def findings(self, subject, status=None):
            return [
                {"id": "valid-confirmed", "status": "VALID", "repro_status": "runtime_confirmed"},
                {"id": "fp", "status": "FALSE_POSITIVE", "repro_status": "not_attempted"},
            ]

    events = []
    monkeypatch.setattr(drive_binvalidate, "CoverageClient", lambda: ValidationCoverage())
    monkeypatch.setattr(drive_binvalidate, "log", lambda msg: events.append(("log", msg)))
    monkeypatch.setattr(
        drive_binvalidate,
        "publish_final_visual",
        lambda subject, title: events.append(("visual", subject, title)) or {"oid": "obj_visual", "url": "http://wb/o/obj_visual"},
    )
    monkeypatch.setattr(
        drive_binvalidate,
        "publish_vendor_disclosure",
        lambda subject, title: events.append(("vendor", subject, title)) or {"oid": "obj_vendor", "url": "http://wb/o/obj_vendor"},
    )

    out = drive_binvalidate.run("example-binary", "bin", claude=1, codex=1)

    assert ("visual", "example-binary", "example-binary — Binary Security Research") in events
    assert ("vendor", "example-binary", "example-binary — Vendor Disclosure Report") in events
    assert ("log", "Vendor disclosure: http://wb/o/obj_vendor") in events
    assert out["vendor_report"]["oid"] == "obj_vendor"


@pytest.mark.parametrize("repro_status", ["runtime_confirmed", "reproduced", "RUNTIME_CONFIRMED"])
def test_binvalidate_runtime_confirmed_findings_are_complete(repro_status):
    import drive_binvalidate

    assert not drive_binvalidate.needs_validation({
        "id": "confirmed",
        "status": "VALID",
        "repro_status": repro_status,
        "production_viability": "PoC produced runtime evidence.",
        "critic_reasoning": "Raw output captured.",
    })


@pytest.mark.parametrize("repro_status", ["NOT_PROVEN", "not_proven", "runtime_blocked", "runtime_viable", "static_only", "not_attempted", None])
def test_binvalidate_unproven_runtime_states_stay_pending(repro_status):
    import drive_binvalidate

    assert drive_binvalidate.needs_validation({
        "id": "pending",
        "status": "VALID",
        "repro_status": repro_status,
        "production_viability": "Prior PoC attempt was inconclusive.",
        "critic_reasoning": "Raw output showed rejection before the vulnerable path.",
    })


@pytest.mark.parametrize("status", ["FALSE_POSITIVE", "DUPLICATE", "PROVISIONALLY_VALID", "CHAINABLE_DEFERRED"])
def test_binvalidate_rejected_or_unreviewed_findings_do_not_enter_validation(status):
    import drive_binvalidate

    assert not drive_binvalidate.needs_validation({
        "id": "ignored",
        "status": status,
        "repro_status": "not_attempted",
    })


def test_binvalidate_prompt_tells_agents_to_use_loop_capabilities_before_blocking():
    import drive_binvalidate

    objective = drive_binvalidate._objective(
        "val-test",
        "example-binary",
        "bin/target",
        ["finding-1"],
    )

    assert "GET /loop/capabilities" in objective
    assert "create or improve" in objective
    assert "available host_actions" in objective
    assert "target-specific host actions" in objective
    assert "Demote transport-unreachable findings" in objective
    assert "Do not repost NOT_PROVEN" in objective
    assert "REF-All report spec" in objective
    assert "Visual proof must prove the claim" in objective
    assert "marker text only proves reflection" in objective
    assert "archive-relative" in objective
    assert "False positives and duplicates" in objective
    assert "CHAINABLE_DEFERRED" in objective
    assert "real technical primitive but no proven standalone exploitability" in objective


def test_binvalidate_can_throttle_active_validator_conversations(monkeypatch):
    import threading
    import drive_binvalidate

    class ValidationCoverage:
        def findings(self, subject, status=None):
            return [
                {"id": f"pending-{i}", "status": "VALID", "repro_status": "not_attempted"}
                for i in range(4)
            ]

    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_run_agent(agent_id, subject, binrel, finding_ids, results, lane="A"):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        threading.Event().wait(0.03)
        with lock:
            active -= 1
        results[agent_id] = "finished"

    monkeypatch.setattr(drive_binvalidate, "CoverageClient", lambda: ValidationCoverage())
    monkeypatch.setattr(drive_binvalidate, "log", lambda msg: None)
    monkeypatch.setattr(drive_binvalidate.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        drive_binvalidate,
        "publish_final_visual",
        lambda subject, title: {"oid": "obj_test", "url": "http://wb/o/obj_test"},
    )
    monkeypatch.setattr(drive_binvalidate, "_run_agent", fake_run_agent)

    drive_binvalidate.run("example-binary", "bin", claude=2, codex=2, max_concurrent=2)

    assert max_active == 2


def test_final_visual_gate_requires_renderable_html(monkeypatch):
    from coverage_service.tools import final_visual

    monkeypatch.setattr(final_visual.report_findings, "publish", lambda subject, title: "obj_test")

    class Response:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size=-1):
            return b"<!doctype html><html><body>ok</body></html>"

    seen = []

    def fake_urlopen(req, timeout):
        seen.append((req.full_url, timeout))
        return Response()

    monkeypatch.setattr(final_visual.urllib.request, "urlopen", fake_urlopen)

    out = final_visual.publish_final_visual("example-binary", "Example Binary")

    assert out["oid"] == "obj_test"
    assert seen == [
        ("http://127.0.0.1:7673/api/workbenches/ref-all/objects/obj_test/render", 30)
    ]


def test_final_visual_gate_rejects_non_html_render(monkeypatch):
    from coverage_service.tools import final_visual

    monkeypatch.setattr(final_visual.report_findings, "publish", lambda subject, title: "obj_test")

    class Response:
        headers = {"Content-Type": "application/octet-stream"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size=-1):
            return b"not html"

    monkeypatch.setattr(final_visual.urllib.request, "urlopen", lambda req, timeout: Response())

    with pytest.raises(RuntimeError, match="not renderable HTML"):
        final_visual.publish_final_visual("example-binary", "Example Binary")
