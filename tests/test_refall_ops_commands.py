from datetime import UTC, datetime
import sys

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "arcticbase/backend/src"))

pytest.importorskip("ruamel.yaml")

from arctic_base.api import refall_ops_commands
from arctic_base.api.refall_ops_commands import _authorize_process_launch
from arctic_base.config import Settings
from arctic_base.models import WorkbenchMeta
from arctic_base.refall.coverage_store import store_for_workbench
from arctic_base.storage.filesystem import FilesystemStorage


def test_process_launch_authorization_auto_grants_loop_start(tmp_path):
    storage = FilesystemStorage(tmp_path / "data")
    subject_path = tmp_path / "subjects" / "alpha"
    subject_path.mkdir(parents=True)
    storage.create_workbench(
        WorkbenchMeta(
            slug="alpha",
            title="Alpha",
            local_path=str(subject_path),
            tags=["refall"],
            custom_fields={"refall_subject": "alpha", "refall_subject_path": str(subject_path)},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    settings = Settings(
        data=tmp_path / "data",
        refall_data_root=tmp_path / "refall",
        refall_repo_root=tmp_path / "repo",
    )

    result = _authorize_process_launch(
        storage=storage,
        slug="alpha",
        settings=settings,
        subject="alpha",
        workbench="alpha",
        max_cycles=0,
        subject_path=subject_path,
        action="loop.start",
    )

    assert result["accepted"] is True
    grants = store_for_workbench(storage, "alpha").list_capability_grants("alpha")
    assert len(grants) == 1
    assert grants[0]["class"] == "run_local_command"
    assert grants[0]["scope"] == {"paths": [str(subject_path)]}
    assert grants[0]["granted_by"] == "refall-ops-panel"


def test_launch_standing_loop_syncs_source_before_process_start(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subject_path = tmp_path / "subjects" / "alpha"
    source = tmp_path / "source"
    source.mkdir(parents=True)
    sync_calls = []
    popen_calls = []

    def fake_sync(**kwargs):
        sync_calls.append(kwargs)
        return {"status": "synced", "workspace": "/projects/alpha"}

    class Proc:
        pid = 4321

    def fake_popen(argv, **kwargs):
        popen_calls.append((argv, kwargs))
        return Proc()

    monkeypatch.setattr(refall_ops_commands, "_sync_agent_canvas_workspace", fake_sync)
    monkeypatch.setattr(refall_ops_commands, "_assert_openhands_api_ready", lambda settings: None)
    monkeypatch.setattr(refall_ops_commands.subprocess, "Popen", fake_popen)
    settings = Settings(
        data=tmp_path / "data",
        refall_data_root=tmp_path / "refall",
        refall_repo_root=repo_root,
    )

    result = refall_ops_commands._launch_standing_loop(
        settings=settings,
        subject="alpha",
        workbench="alpha",
        max_cycles=0,
        subject_path=subject_path,
        source_path=source,
    )

    assert sync_calls[0]["subject"] == "alpha"
    assert sync_calls[0]["source_path"] == source
    assert popen_calls
    assert result["pid"] == 4321
    assert result["agent_workspace"] == {"status": "synced", "workspace": "/projects/alpha"}
