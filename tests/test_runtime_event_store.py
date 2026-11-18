from pathlib import Path

from ref_all_executor.runtime_state import append_event, connect_runtime, list_events


def test_runtime_events_survive_reopen(tmp_path: Path) -> None:
    subject_path = tmp_path / "alpha"
    conn = connect_runtime(subject_path)
    event = append_event(
        conn,
        subject="alpha",
        workbench="alpha",
        event_type="worker_submit",
        task_id="task_1",
        session_id="cid_1",
        payload={"summary": "done"},
    )
    conn.close()

    reopened = connect_runtime(subject_path)
    events = list_events(reopened, "alpha")

    assert events[0]["id"] == event["id"]
    assert events[0]["payload"]["summary"] == "done"
