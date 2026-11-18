from pathlib import Path

from arctic_base.refall.source_inventory import build_source_inventory


def test_source_inventory_hashes_files_without_excluding_large_or_binary_inputs(tmp_path: Path) -> None:
    root = tmp_path / "subject"
    root.mkdir()
    (root / "app.py").write_text("print('x')\n", encoding="utf-8")
    (root / "big.bin").write_bytes(b"\x00" + (b"x" * 6_000_000))
    (root / "payload.haf").write_bytes(b"HAF\x00payload")
    (root / "opaque").write_text("unknown extension still in scope\n", encoding="utf-8")

    inventory = build_source_inventory("alpha", root)
    files = {item["path"]: item for item in inventory["files"]}

    assert inventory["subject"] == "alpha"
    assert inventory["root"] == str(root)
    assert set(files) == {"app.py", "big.bin", "payload.haf", "opaque"}
    assert len(files["app.py"]["sha256"]) == 64
    assert files["app.py"]["total_lines"] == 1
    assert files["app.py"]["kind"] == "python"
    assert files["big.bin"]["kind"] == "binary"
    assert files["big.bin"]["total_lines"] >= 1
    assert files["payload.haf"]["kind"] == "binary"
    assert files["opaque"]["kind"] == "unknown"
    assert inventory["skipped"] == []


def test_source_inventory_includes_hidden_config_and_ci_files(tmp_path: Path) -> None:
    root = tmp_path / "subject"
    workflow = root / ".github" / "workflows"
    workflow.mkdir(parents=True)
    root.mkdir(exist_ok=True)
    (root / ".env").write_text("TOKEN=redacted\n", encoding="utf-8")
    (workflow / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]\n", encoding="utf-8")

    inventory = build_source_inventory("alpha", root)
    paths = {item["path"] for item in inventory["files"]}

    assert ".env" in paths
    assert ".github/workflows/ci.yml" in paths
    assert ".git/config" not in paths
    assert ".env" not in {item.get("path") for item in inventory["skipped"]}
