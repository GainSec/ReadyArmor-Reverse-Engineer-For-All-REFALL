from __future__ import annotations

import json
from pathlib import Path

from ref_all_executor.watchdog import (
    RefallWatchdog,
    WatchdogConfig,
    failure_refusal_count,
    merge_crontab,
    numeric_usage,
    render_cron_entry,
)


class FakeArcticBase:
    def __init__(self):
        self.subjects = [{"slug": "alpha", "subject": "alpha"}]
        self.agents = {
            "active": [
                {
                    "workbench": "alpha",
                    "subject": "alpha",
                    "cid": "cid-1",
                    "lane": "A",
                    "phase": "characterize",
                    "unit_id": "unit-1",
                    "path": "src/app.py",
                }
            ]
        }
        self.context = {"subject": "alpha", "info_md": "# context"}
        self.coverage = {
            "subject": "alpha",
            "lines_total": 100,
            "lines_covered": 10,
            "resolved_pct": 10.0,
            "files_done": 1,
        }
        self.runtime_events = []
        self.nonfatal = {"subject": "alpha", "count": 0, "errors": []}
        self.wishlist_items = []
        self.created_pending = []
        self.pending_actions = []
        self.cancelled_pending = []
        self.raise_cancel = False
        self.runtime_appends = []
        self.ledger_appends = []

    def list_subjects(self):
        return self.subjects

    def get_workbench(self, slug):
        return next(item for item in self.subjects if item["slug"] == slug)

    def ops_agents(self):
        return self.agents

    def ops_debug_live(self, slug):
        return {"subject": slug, "live": True, "active": []}

    def get_coverage_context(self, slug):
        return self.context

    def coverage_stats(self, slug):
        return self.coverage

    def list_runtime_events(self, slug):
        return self.runtime_events

    def get_runtime_manifest(self, slug):
        return {"run_id": "run-1", "stage_status": {"loop": "running"}}

    def list_nonfatal_errors(self, slug, limit=500):
        return self.nonfatal

    def list_wishlist(self, slug, **filters):
        status = filters.get("status")
        if status is None:
            return self.wishlist_items
        return [item for item in self.wishlist_items if item.get("status") == status]

    def create_wishlist_item(self, slug, item):
        created = {"id": f"wish-{len(self.wishlist_items) + 1}", "subject": slug, **item}
        self.wishlist_items.append(created)
        return created

    def create_pending_action(self, slug, action):
        created = {"id": f"pa-{len(self.created_pending) + 1}", "status": "open", **action}
        self.created_pending.append((slug, created))
        return created

    def list_pending_actions(self, slug, **filters):
        del slug
        status = filters.get("status")
        if status is None:
            return self.pending_actions
        return [item for item in self.pending_actions if item.get("status") == status]

    def cancel_pending_action(
        self,
        slug,
        action_id,
        receipt,
        receipt_type=None,
        resolved_by="refall-manager",
    ):
        if self.raise_cancel:
            raise RuntimeError("cancel failed")
        row = next(item for item in self.pending_actions if item["id"] == action_id)
        row["status"] = "cancelled"
        call = {
            "slug": slug,
            "action_id": action_id,
            "receipt": receipt,
            "receipt_type": receipt_type,
            "resolved_by": resolved_by,
        }
        self.cancelled_pending.append(call)
        return dict(row)

    def append_runtime_event(self, slug, event):
        created = {"id": f"rte-{len(self.runtime_appends) + 1}", **event}
        self.runtime_appends.append((slug, created))
        return created

    def append_ledger(self, slug, entry):
        created = {"id": f"led-{len(self.ledger_appends) + 1}", **entry}
        self.ledger_appends.append((slug, created))
        return created


class DownArcticBase(FakeArcticBase):
    def _down(self, *_args, **_kwargs):
        raise RuntimeError("connection refused")

    ops_agents = _down
    ops_debug_live = _down
    get_coverage_context = _down
    coverage_stats = _down
    list_runtime_events = _down
    get_runtime_manifest = _down
    list_pending_actions = _down


class FakeOpenHands:
    def __init__(self, info=None, probe_status=None):
        self.info = info or {}
        self.probe_status = probe_status or {}
        self.deleted = []
        self.raise_info = False

    def conversation_probe(self, cid):
        if self.raise_info:
            raise RuntimeError("GET /api/conversations/cid-1 -> 502: Bad Gateway")
        status = self.probe_status.get(cid, 200 if cid in self.info else 404)
        return status, self.info.get(cid, {})

    def conversation_info(self, cid):
        if self.raise_info:
            raise RuntimeError("GET /api/conversations/cid-1 -> 502: Bad Gateway")
        return self.info.get(cid, {})

    def delete(self, cid):
        self.deleted.append(cid)


def test_watchdog_reconciles_missing_conversations_and_matching_pending_actions(tmp_path: Path) -> None:
    subject_root = tmp_path / "alpha"
    state_path = subject_root / ".refall" / "loop_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        '{"status":"running","active_count":2,"active":['
        '{"cid":"missing","lane":"A","task_class":"identify"},'
        '{"cid":"existing","lane":"B","task_class":"verify"}]}'
    )
    ab = FakeArcticBase()
    ab.subjects = [{"slug": "alpha", "subject": "alpha", "local_path": str(subject_root)}]
    ab.agents["active"] = [
        {"workbench": "alpha", "subject": "alpha", "cid": "missing", "status": "running"},
        {"workbench": "alpha", "subject": "alpha", "cid": "existing", "status": "running"},
    ]
    ab.pending_actions = [
        {
            "id": "pa-stop",
            "kind": "watchdog_conversation_stopped",
            "status": "open",
            "title": "Review stopped Canvas conversation missing",
            "description": "missing was stopped",
            "required_receipt_type": "watchdog_stop_review",
        },
        {
            "id": "pa-alert",
            "kind": "watchdog_alert",
            "status": "claimed",
            "title": "Review watchdog alert",
            "description": "Canvas conversation missing became stale",
            "required_receipt_type": "watchdog_alert_review",
        },
        {
            "id": "pa-unrelated",
            "kind": "operator_decision_needed",
            "status": "claimed",
            "title": "Unrelated decision",
            "description": "missing is mentioned but this is not a watchdog action",
        },
    ]
    ab.runtime_events = [{"id": "rte-loop", "type": "loop_cycle", "created_at": 999.0, "payload": {"cycle": 1}}]
    oh = FakeOpenHands(
        {"existing": {"execution_status": "running", "updated_at": 999.0}},
        probe_status={"missing": 404, "existing": 200},
    )
    watchdog = RefallWatchdog(
        arcticbase=ab,
        openhands=oh,
        config=WatchdogConfig(
            state_path=tmp_path / "watchdog.json",
            audit_path=tmp_path / "audit.jsonl",
            subject="alpha",
            enforce=True,
        ),
        now=lambda: 1000.0,
    )

    result = watchdog.run_once()

    saved = json.loads(state_path.read_text())
    assert [item["cid"] for item in saved["active"]] == ["existing"]
    assert saved["active_count"] == 1
    assert saved["status"] == "running"
    assert result["reconciled_absent_cids"] == ["missing"]
    assert result["active_cids"] == ["existing"]
    assert ab.runtime_appends[-1][1]["type"] == "canvas_state_reconciled"
    assert ab.ledger_appends[-1][1]["action"] == "watchdog.canvas_state.reconciled"
    assert [item["action_id"] for item in ab.cancelled_pending] == ["pa-stop", "pa-alert"]
    assert [item["receipt_type"] for item in ab.cancelled_pending] == [
        "watchdog_stop_review",
        "watchdog_alert_review",
    ]
    assert ab.pending_actions[-1]["status"] == "claimed"
    assert len(result["reconciliation"][0]["pending_action_cancellations"]) == 2


def test_watchdog_reconcile_records_pending_cancellation_failure_without_restoring_loop_state(tmp_path: Path) -> None:
    subject_root = tmp_path / "alpha"
    state_path = subject_root / ".refall" / "loop_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text('{"status":"running","active_count":1,"active":[{"cid":"missing"}]}')
    ab = FakeArcticBase()
    ab.subjects = [{"slug": "alpha", "subject": "alpha", "local_path": str(subject_root)}]
    ab.agents["active"] = [
        {"workbench": "alpha", "subject": "alpha", "cid": "missing", "status": "running"},
    ]
    ab.pending_actions = [{
        "id": "pa-stop",
        "kind": "watchdog_conversation_stopped",
        "status": "open",
        "title": "Review stopped Canvas conversation missing",
        "required_receipt_type": "watchdog_stop_review",
    }]
    ab.raise_cancel = True
    watchdog = RefallWatchdog(
        arcticbase=ab,
        openhands=FakeOpenHands(probe_status={"missing": 404}),
        config=WatchdogConfig(
            state_path=tmp_path / "watchdog.json",
            audit_path=tmp_path / "audit.jsonl",
            subject="alpha",
            enforce=True,
        ),
        now=lambda: 1000.0,
    )

    result = watchdog.run_once()

    saved = json.loads(state_path.read_text())
    assert saved["active"] == []
    assert saved["status"] == "idle"
    cancellations = result["reconciliation"][0]["pending_action_cancellations"]
    assert cancellations == [{"action_id": "pa-stop", "ok": False, "error": "RuntimeError('cancel failed')"}]


def test_watchdog_leaves_loop_state_untouched_when_canvas_probe_fails(tmp_path: Path) -> None:
    subject_root = tmp_path / "alpha"
    state_path = subject_root / ".refall" / "loop_state.json"
    state_path.parent.mkdir(parents=True)
    original = '{"status":"running","active_count":1,"active":[{"cid":"unknown"}]}\n'
    state_path.write_text(original)
    ab = FakeArcticBase()
    ab.subjects = [{"slug": "alpha", "subject": "alpha", "local_path": str(subject_root)}]
    ab.agents["active"] = [
        {"workbench": "alpha", "subject": "alpha", "cid": "unknown", "status": "running"},
    ]
    oh = FakeOpenHands()
    oh.raise_info = True
    watchdog = RefallWatchdog(
        arcticbase=ab,
        openhands=oh,
        config=WatchdogConfig(
            state_path=tmp_path / "watchdog.json",
            audit_path=tmp_path / "audit.jsonl",
            subject="alpha",
            enforce=True,
        ),
        now=lambda: 1000.0,
    )

    result = watchdog.run_once()

    assert state_path.read_text() == original
    assert result["reconciled_absent_cids"] == []
    assert all(
        entry[1].get("action") != "watchdog.canvas_state.reconciled"
        for entry in ab.ledger_appends
    )


def test_stale_active_agent_creates_alert_without_stop(tmp_path: Path) -> None:
    ab = FakeArcticBase()
    ab.runtime_events = [{"id": "rte-loop", "type": "loop_cycle", "created_at": 990.0, "payload": {"cycle": 1}}]
    oh = FakeOpenHands({"cid-1": {"execution_status": "running", "updated_at": 100.0, "stats": {}}})
    watchdog = RefallWatchdog(
        arcticbase=ab,
        openhands=oh,
        config=WatchdogConfig(
            state_path=tmp_path / "state.json",
            audit_path=tmp_path / "audit.jsonl",
            subject="alpha",
            stale_seconds=300,
            max_runtime_seconds=3600,
            max_total_tokens=0,
            enforce=True,
        ),
        now=lambda: 1000.0,
    )

    result = watchdog.run_once()

    assert [item["reason"] for item in result["findings"]] == ["stale_active_agent"]
    assert oh.deleted == []
    assert ab.created_pending[0][1]["kind"] == "watchdog_alert"
    assert ab.runtime_appends[0][1]["type"] == "watchdog_alert"


def test_token_ceiling_stops_runaway_conversation(tmp_path: Path) -> None:
    ab = FakeArcticBase()
    ab.runtime_events = [{"id": "rte-loop", "type": "loop_cycle", "created_at": 990.0, "payload": {"cycle": 1}}]
    oh = FakeOpenHands(
        {
            "cid-1": {
                "execution_status": "running",
                "created_at": 100.0,
                "updated_at": 990.0,
                "stats": {"usage_to_metrics": {"default": {"total_tokens": 200_000}}},
            }
        }
    )
    watchdog = RefallWatchdog(
        arcticbase=ab,
        openhands=oh,
        config=WatchdogConfig(
            state_path=tmp_path / "state.json",
            audit_path=tmp_path / "audit.jsonl",
            subject="alpha",
            stale_seconds=300,
            max_runtime_seconds=3600,
            max_total_tokens=100_000,
            enforce=True,
        ),
        now=lambda: 1000.0,
    )

    result = watchdog.run_once()

    assert [item["reason"] for item in result["findings"]] == ["token_ceiling"]
    assert oh.deleted == ["cid-1"]
    assert result["stopped"][0]["cid"] == "cid-1"
    assert ab.created_pending[0][1]["kind"] == "watchdog_conversation_stopped"
    assert ab.runtime_appends[0][1]["type"] == "watchdog_conversation_stopped"


def test_numeric_usage_ignores_cost_timestamps() -> None:
    usage = numeric_usage(
        {
            "stats": {
                "usage_to_metrics": {
                    "default": {
                        "accumulated_cost": 0.128,
                        "accumulated_token_usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": 25,
                        },
                        "costs": [
                            {
                                "cost": 0.128,
                                "timestamp": 1_785_129_273.8666427,
                            }
                        ],
                    }
                }
            }
        }
    )

    assert usage["cost_usd"] == 0.256
    assert usage["tokens"] == 125


def test_failure_refusal_count_ignores_successful_tool_output_keywords() -> None:
    successful_event = {
        "kind": "tool_call",
        "status": "completed",
        "title": "grep -oE 'error|failure|refusal' src/app.py",
        "output": "json:\"error,omitempty\"\nrefusal_reasons = []",
    }
    failed_event = {
        "kind": "tool_call",
        "status": "failed",
        "title": "command failed",
        "output": "permission denied",
    }

    assert failure_refusal_count(successful_event) == 0
    assert failure_refusal_count(failed_event) >= 1


def test_failure_refusal_count_flags_workspace_ingest_errors() -> None:
    event = {
        "type": "workspace_ingest_error",
        "error": "[Errno 63] File name too long: .refall-ingested/.refall-ingested",
        "session_id": "cid-1",
    }

    assert failure_refusal_count(event) >= 1


def test_recent_terminal_agent_is_not_alerted_before_loop_poll_grace(tmp_path: Path) -> None:
    ab = FakeArcticBase()
    ab.runtime_events = [{"id": "rte-loop", "type": "loop_cycle", "created_at": 999.0, "payload": {"cycle": 1}}]
    oh = FakeOpenHands(
        {
            "cid-1": {
                "execution_status": "finished",
                "created_at": 900.0,
                "updated_at": 995.0,
                "stats": {"usage_to_metrics": {"default": {"accumulated_cost": 0.01}}},
            }
        }
    )
    watchdog = RefallWatchdog(
        arcticbase=ab,
        openhands=oh,
        config=WatchdogConfig(
            state_path=tmp_path / "state.json",
            audit_path=tmp_path / "audit.jsonl",
            subject="alpha",
            enforce=True,
        ),
        now=lambda: 1000.0,
    )

    result = watchdog.run_once()

    assert result["findings"] == []
    assert oh.deleted == []
    assert ab.created_pending == []


def test_no_progress_requires_repeated_samples(tmp_path: Path) -> None:
    ab = FakeArcticBase()
    ab.runtime_events = [{"id": "rte-loop", "type": "loop_cycle", "created_at": 990.0, "payload": {"cycle": 1}}]
    oh = FakeOpenHands({"cid-1": {"execution_status": "running", "updated_at": 990.0, "stats": {}}})
    cfg = WatchdogConfig(
        state_path=tmp_path / "state.json",
        audit_path=tmp_path / "audit.jsonl",
        subject="alpha",
        stale_seconds=600,
        max_runtime_seconds=3600,
        max_total_tokens=0,
        no_progress_samples=2,
        enforce=True,
    )

    first = RefallWatchdog(arcticbase=ab, openhands=oh, config=cfg, now=lambda: 1000.0).run_once()
    second = RefallWatchdog(arcticbase=ab, openhands=oh, config=cfg, now=lambda: 1300.0).run_once()

    assert first["findings"] == []
    assert [item["reason"] for item in second["findings"]] == ["no_progress"]
    assert oh.deleted == []


def test_openhands_backend_unreachable_creates_subject_alert(tmp_path: Path) -> None:
    ab = FakeArcticBase()
    ab.runtime_events = [{"id": "rte-loop", "type": "loop_cycle", "created_at": 990.0, "payload": {"cycle": 1}}]
    oh = FakeOpenHands()
    oh.raise_info = True
    watchdog = RefallWatchdog(
        arcticbase=ab,
        openhands=oh,
        config=WatchdogConfig(
            state_path=tmp_path / "state.json",
            audit_path=tmp_path / "audit.jsonl",
            subject="alpha",
            stale_seconds=600,
            max_runtime_seconds=3600,
            max_total_tokens=100_000,
            enforce=True,
        ),
        now=lambda: 1000.0,
    )

    result = watchdog.run_once()

    assert [item["reason"] for item in result["findings"]] == ["openhands_agent_server_unreachable"]
    assert ab.created_pending[0][1]["kind"] == "watchdog_alert"
    assert ab.runtime_appends[0][1]["type"] == "watchdog_alert"
    assert oh.deleted == []


def test_dry_run_does_not_write_alerts_or_stop_conversations(tmp_path: Path) -> None:
    ab = FakeArcticBase()
    ab.runtime_events = [{"id": "rte-loop", "type": "loop_cycle", "created_at": 990.0, "payload": {"cycle": 1}}]
    oh = FakeOpenHands()
    oh.raise_info = True
    watchdog = RefallWatchdog(
        arcticbase=ab,
        openhands=oh,
        config=WatchdogConfig(
            state_path=tmp_path / "state.json",
            audit_path=tmp_path / "audit.jsonl",
            subject="alpha",
            enforce=True,
            dry_run=True,
        ),
        now=lambda: 1000.0,
    )

    result = watchdog.run_once()

    assert [item["reason"] for item in result["findings"]] == ["openhands_agent_server_unreachable"]
    assert result["alerts"][0]["dry_run"] is True
    assert ab.created_pending == []
    assert ab.runtime_appends == []
    assert oh.deleted == []


def test_refall_api_unreachable_is_crash_policy_issue(tmp_path: Path) -> None:
    ab = DownArcticBase()
    watchdog = RefallWatchdog(
        arcticbase=ab,
        openhands=FakeOpenHands(),
        config=WatchdogConfig(
            state_path=tmp_path / "state.json",
            audit_path=tmp_path / "audit.jsonl",
            subject="alpha",
            enforce=True,
        ),
        now=lambda: 1000.0,
    )

    result = watchdog.run_once()

    assert [item["reason"] for item in result["findings"]] == ["refall_api_unreachable"]
    assert result["crash_policy_reasons"] == ["refall_api_unreachable"]
    assert ab.created_pending == []
    assert ab.runtime_appends == []


def test_watchdog_records_wishlist_items_and_marks_existing_tools_provided(tmp_path: Path) -> None:
    ab = FakeArcticBase()
    ab.runtime_events = [{"id": "rte-loop", "type": "loop_cycle", "created_at": 990.0, "payload": {"cycle": 1}}]
    ab.wishlist_items = [
        {
            "id": "wish-open-1",
            "subject": "alpha",
            "kind": "tool",
            "item": "python3",
            "reason": "metadata triage helper",
            "requested_by": "cid-1",
            "status": "open",
        }
    ]
    oh = FakeOpenHands({"cid-1": {"execution_status": "running", "updated_at": 990.0, "stats": {}}})
    watchdog = RefallWatchdog(
        arcticbase=ab,
        openhands=oh,
        config=WatchdogConfig(
            state_path=tmp_path / "state.json",
            audit_path=tmp_path / "audit.jsonl",
            subject="alpha",
            enforce=True,
        ),
        now=lambda: 1000.0,
    )

    result = watchdog.run_once()

    assert result["wishlist"]["open_count"] == 1
    assert result["wishlist"]["provided_count"] == 1
    assert ab.wishlist_items[-1]["status"] == "provided"
    assert ab.wishlist_items[-1]["item"] == "python3"
    assert ab.ledger_appends[-1][1]["action"] == "watchdog.wishlist.provided"


def test_crontab_merge_adds_single_refall_watchdog_entry(tmp_path: Path) -> None:
    entry = render_cron_entry(tmp_path / "refall", interval_minutes=5)
    existing = "*/5 * * * * /tmp/other.sh # OTHER\n"

    merged = merge_crontab(existing, entry)
    merged_again = merge_crontab(merged, entry)

    assert "# OTHER" in merged
    assert merged.count("REFALL_V10_WATCHDOG") == 1
    assert merged_again.count("REFALL_V10_WATCHDOG") == 1


def test_stop_receipt_uses_only_recorded_resources():
    from ref_all_executor.watchdog import append_stop_records

    ab = FakeArcticBase()
    resources = ["/srv/refall/alpha/PRJ", "analysis-host"]
    for manifest, expected in [({"run_id": "run-1"}, []), ({"run_id": "run-1", "allowed_resources": resources}, resources)]:
        result = append_stop_records(
            ab, "alpha", manifest,
            {"cid": "cid-1", "reason": "stale_active_agent"}, {}, {"ok": True},
        )
        assert result["runtime_event"]["payload"]["allowed_resources"] == expected
