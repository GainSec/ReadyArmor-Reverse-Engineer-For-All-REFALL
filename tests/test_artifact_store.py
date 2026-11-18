from pathlib import Path

from ref_all_executor.artifact_store import save_artifact
from ref_all_executor.runtime_state import connect_runtime, list_artifacts


def test_artifact_store_hashes_and_records_content(tmp_path: Path) -> None:
    subject_path = tmp_path / "alpha"
    conn = connect_runtime(subject_path)

    artifact = save_artifact(
        conn,
        subject_path,
        subject="alpha",
        kind="worker-output",
        content="raw output",
        mime="text/plain",
        task_id="task_1",
    )

    assert Path(artifact["path"]).read_text(encoding="utf-8") == "raw output"
    assert artifact["sha256"]
    assert list_artifacts(conn, "alpha")[0]["id"] == artifact["id"]
