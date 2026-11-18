from pathlib import Path

from ref_all_executor.source_inventory import build_source_inventory


def test_executor_source_inventory_includes_hidden_config_and_ci_files(tmp_path: Path) -> None:
    root = tmp_path / "subject"
    workflow = root / ".github" / "workflows"
    workflow.mkdir(parents=True)
    (root / ".env").write_text("TOKEN=redacted\n", encoding="utf-8")
    (workflow / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]\n", encoding="utf-8")

    inventory = build_source_inventory("alpha", root)
    paths = {item["path"] for item in inventory["files"]}

    assert ".env" in paths
    assert ".github/workflows/ci.yml" in paths
    assert ".git/config" not in paths


def test_executor_source_inventory_includes_large_binary_and_unknown_files(tmp_path: Path) -> None:
    root = tmp_path / "subject"
    root.mkdir()
    (root / "firmware.bin").write_bytes(b"\x00FW" + (b"x" * 6_000_000))
    (root / "media.haf").write_bytes(b"HAF\x00payload")
    (root / "opaque").write_text("unknown extension still in scope\n", encoding="utf-8")

    inventory = build_source_inventory("alpha", root)
    files = {item["path"]: item for item in inventory["files"]}

    assert set(files) == {"firmware.bin", "media.haf", "opaque"}
    assert inventory["skipped"] == []
    assert files["firmware.bin"]["kind"] == "binary"
    assert files["firmware.bin"]["total_lines"] >= 1
    assert files["media.haf"]["kind"] == "binary"
    assert files["opaque"]["kind"] == "unknown"
