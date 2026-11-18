from pathlib import Path

from ref_all_executor.evidence_graph import graph_from_deltas
import ref_all_executor.projection as projection
from ref_all_executor.projection import project_runtime_events
from ref_all_executor.runtime_state import append_event, connect_runtime, list_deltas, list_observations


def test_projection_is_idempotent_and_replayable(tmp_path: Path) -> None:
    conn = connect_runtime(tmp_path / "alpha")
    append_event(
        conn,
        subject="alpha",
        workbench="alpha",
        event_type="worker_submit",
        task_id="task_1",
        session_id="cid_1",
        payload={
            "summary": "Reviewed parser",
            "evidence": [{"kind": "source_anchor", "ref": "parser.py:7", "claim": "input parsed"}],
        },
    )

    first = project_runtime_events(conn, "alpha")
    second = project_runtime_events(conn, "alpha")

    assert first["events_projected"] == 1
    assert second["events_projected"] == 0
    observations = list_observations(conn, "alpha")
    assert observations[0]["kind"] == "source_fact"
    graph = graph_from_deltas(list_deltas(conn))
    assert graph["nodes"][0]["type"] == "observation"


def test_projection_watermark_advances_only_after_successful_commit(tmp_path: Path, monkeypatch) -> None:
    conn = connect_runtime(tmp_path / "alpha")
    append_event(
        conn,
        subject="alpha",
        workbench="alpha",
        event_type="worker_submit",
        payload={"summary": "Reviewed parser"},
    )

    def fail_delta(conn, observation):
        raise RuntimeError("projector failed")

    monkeypatch.setattr(projection, "_delta_from_observation", fail_delta)

    try:
        project_runtime_events(conn, "alpha")
    except RuntimeError:
        pass

    watermark = conn.execute("SELECT * FROM projection_watermarks WHERE projector=?", (projection.PROJECTOR,)).fetchone()
    assert watermark is None
