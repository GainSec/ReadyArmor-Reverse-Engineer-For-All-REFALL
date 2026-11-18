from ref_all_executor.loop_manager import RefallLoopManager


class FakeAB:
    def __init__(self):
        self.calls = []
        self.context = {"subject": "alpha", "info_md": "# Alpha briefing\n"}

    def create_subject(self, name):
        self.calls.append(("create_subject", name))
        return {"subject": name, "workbench_slug": name, "subject_path": f"/tmp/{name}"}

    def set_coverage_context(self, slug, info_md, **kwargs):
        self.calls.append(("set_context", slug, info_md, kwargs))
        return {"subject": slug, "info_md": info_md}

    def get_coverage_context(self, slug):
        self.calls.append(("get_context", slug))
        return self.context

    def append_ledger(self, slug, entry):
        self.calls.append(("ledger", slug, entry))
        return {"id": f"led-{entry['action']}", **entry}

    def push_ops_event(self, event):
        self.calls.append(("ops_event", event))
        return {"ok": True}

    def get_workbench(self, slug):
        self.calls.append(("get_workbench", slug))
        return {"slug": slug, "custom_fields": {"refall_subject_path": f"/tmp/{slug}"}}

    def coverage_stats(self, slug):
        self.calls.append(("coverage_stats", slug))
        return {"resolved_pct": 75.0}

    def ledger_stats(self, slug):
        self.calls.append(("ledger_stats", slug))
        return {"total": 2}

    def closeout_gate(self, slug):
        self.calls.append(("closeout_gate", slug))
        return {"passed": True, "checks": [], "summary": {}}

    def ops_command(self, command):
        self.calls.append(("ops_command", command))
        action, subject = command.split(" ", 1)
        return {
            "command": action,
            "subject": subject,
            "workbench": subject,
            "status": "started" if action == "start" else "updated",
            "loop": {"pid": 9001, "agent_workspace": {"workspace": f"/projects/{subject}"}},
        }


def test_loop_start_requires_existing_context_and_records_ledger_ops_event():
    ab = FakeAB()
    launches = []
    manager = RefallLoopManager(arcticbase=ab, loop_launcher=lambda **kw: launches.append(kw) or {"pid": 123})

    out = manager.start("alpha")

    assert out["status"] == "started"
    assert out["loop"]["pid"] == 123
    assert ("create_subject", "alpha") in ab.calls
    assert ("get_context", "alpha") in ab.calls
    assert not any(call[0] == "set_context" for call in ab.calls)
    assert any(call[0] == "ledger" and call[2]["action"] == "loop.start" for call in ab.calls)
    assert any(call[0] == "ops_event" and call[1]["action"] == "loop.start" for call in ab.calls)
    assert launches == [{"subject": "alpha", "workbench": "alpha", "max_cycles": 0}]


def test_loop_start_rejects_missing_context():
    ab = FakeAB()
    ab.context = {"subject": "alpha", "info_md": None}
    manager = RefallLoopManager(arcticbase=ab)

    try:
        manager.start("alpha")
    except RuntimeError as exc:
        assert "Generate Context" in str(exc)
    else:
        raise AssertionError("start should reject a subject with no generated context")


def test_loop_update_records_current_stats():
    ab = FakeAB()
    launches = []
    manager = RefallLoopManager(arcticbase=ab, loop_launcher=lambda **kw: launches.append(kw) or {"pid": 124})

    out = manager.update("alpha")

    assert out["status"] == "updated"
    assert out["loop"]["pid"] == 124
    assert out["coverage"]["resolved_pct"] == 75.0
    assert not any(call[0] == "set_context" for call in ab.calls)
    assert any(call[0] == "ledger" and call[2]["action"] == "loop.update" for call in ab.calls)
    assert launches == [{"subject": "alpha", "workbench": "alpha", "max_cycles": 1}]


def test_loop_update_uses_canonical_ops_launch_by_default():
    ab = FakeAB()

    out = RefallLoopManager(arcticbase=ab).update("alpha")

    assert out["status"] == "updated"
    assert out["loop"]["agent_workspace"]["workspace"] == "/projects/alpha"
    assert ("ops_command", "update alpha") in ab.calls
    assert not any(call[0] == "ledger" for call in ab.calls)


def test_loop_start_uses_canonical_ops_launch_by_default():
    ab = FakeAB()

    out = RefallLoopManager(arcticbase=ab).start("alpha")

    assert out["status"] == "started"
    assert out["loop"]["agent_workspace"]["workspace"] == "/projects/alpha"
    assert ("ops_command", "start alpha") in ab.calls
    assert not any(call[0] == "ledger" for call in ab.calls)


def test_loop_closeout_refreshes_report_when_callbacks_are_supplied():
    ab = FakeAB()
    drafts = []
    enrichments = []

    manager = RefallLoopManager(
        arcticbase=ab,
        draft_report=lambda workbench, subject: drafts.append((workbench, subject)) or {"object_id": "obj1"},
        enrich_report=lambda workbench, subject: enrichments.append((workbench, subject)) or {"assembled": {"mode": "updated"}},
    )

    out = manager.closeout("alpha")

    assert out["status"] == "closed"
    assert drafts == [("alpha", "alpha"), ("alpha", "alpha")]
    assert enrichments == [("alpha", "alpha")]
    assert not any(call[0] == "set_context" for call in ab.calls)
    assert any(call[0] == "ledger" and call[2]["action"] == "loop.closeout" for call in ab.calls)


def test_loop_closeout_refreshes_draft_after_enrichment_before_gate():
    ab = FakeAB()
    order = []

    def draft(workbench, subject):
        order.append("draft")
        return {"object_id": "obj1"}

    def enrich(workbench, subject):
        order.append("enrich")
        return {"assembled": {"mode": "downgrade_refused"}}

    def gate(slug):
        order.append("gate")
        return {"passed": True, "checks": []}

    ab.closeout_gate = gate
    out = RefallLoopManager(
        arcticbase=ab,
        draft_report=draft,
        enrich_report=enrich,
    ).closeout("alpha")

    assert out["status"] == "closed"
    assert order == ["draft", "enrich", "draft", "gate"]


def test_loop_closeout_blocks_when_gate_fails_but_refreshes_report():
    ab = FakeAB()
    ab.closeout_gate = lambda slug: ab.calls.append(("closeout_gate", slug)) or {
        "passed": False,
        "checks": [{"id": "pending-actions-open", "status": "fail", "blocking": True}],
        "summary": {"pending_actions_open": 1},
    }
    drafts = []
    enrichments = []
    manager = RefallLoopManager(
        arcticbase=ab,
        draft_report=lambda workbench, subject: drafts.append((workbench, subject)) or {"object_id": "obj1"},
        enrich_report=lambda workbench, subject: enrichments.append((workbench, subject)) or {"assembled": {"mode": "updated"}},
    )

    out = manager.closeout("alpha")

    assert out["status"] == "blocked"
    assert drafts == [("alpha", "alpha"), ("alpha", "alpha")]
    assert enrichments == [("alpha", "alpha")]
    assert out["closeout_gate"]["passed"] is False
    assert any(call[0] == "ledger" and call[2]["action"] == "loop.closeout.blocked" for call in ab.calls)
