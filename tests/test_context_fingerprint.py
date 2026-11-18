from pathlib import Path

from ref_all_executor.context_fingerprint import fingerprint_directory


def test_fingerprint_directory_hashes_deduplicates_and_classifies(monkeypatch, tmp_path: Path):
    (tmp_path / "notes.md").write_text("hello\n", encoding="utf-8")
    payload = b"\x7fELF\x00firmware"
    (tmp_path / "a.bin").write_bytes(payload)
    (tmp_path / "copy.bin").write_bytes(payload)

    def fake_run(args, **kwargs):
        assert args[:2] == ["file", "-b"]
        name = Path(args[-1]).name
        output = "ELF 64-bit LSB executable" if name.endswith(".bin") else "UTF-8 Unicode text"
        return type("Result", (), {"returncode": 0, "stdout": output + "\n", "stderr": ""})()

    monkeypatch.setattr("ref_all_executor.context_fingerprint.subprocess.run", fake_run)
    result = fingerprint_directory(tmp_path, run_binwalk=False)

    assert result["files_total"] == 3
    assert result["deduplicated_files"] == 2
    assert len(result["duplicate_groups"]) == 1
    assert result["files"][0]["sha256"]
    assert {item["file_type"] for item in result["files"]} == {
        "UTF-8 Unicode text", "ELF 64-bit LSB executable"
    }
    assert result["binwalk"]["requested"] is False


def test_fingerprint_runs_binwalk_only_for_selected_unique_files(monkeypatch, tmp_path: Path):
    (tmp_path / "firmware.bin").write_bytes(b"\x00\x01firmware")
    (tmp_path / "readme.txt").write_text("read me\n", encoding="utf-8")
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "file":
            output = "data" if args[-1].endswith("firmware.bin") else "ASCII text"
            return type("Result", (), {"returncode": 0, "stdout": output + "\n", "stderr": ""})()
        assert args[0] == "binwalk"
        assert "--extract" not in args and "--matryoshka" not in args
        assert "--entropy" not in args
        return type("Result", (), {"returncode": 0, "stdout": "signature\n", "stderr": ""})()

    monkeypatch.setattr("ref_all_executor.context_fingerprint.subprocess.run", fake_run)
    result = fingerprint_directory(tmp_path, run_binwalk=True)

    assert result["binwalk"]["requested"] is True
    assert result["binwalk"]["scanned"] == 1
    assert [call[0][0] for call in calls] == ["file", "file", "binwalk"]
    assert result["files"][0]["binwalk"]["status"] == "ok"


def test_manifest_hash_ignores_binwalk_elapsed_time(monkeypatch, tmp_path: Path):
    (tmp_path / "firmware.bin").write_bytes(b"\x00\x01firmware")
    elapsed = iter(("430.0", "518.0"))

    def fake_run(args, **kwargs):
        if args[0] == "file":
            return type("Result", (), {"returncode": 0, "stdout": "data\n", "stderr": ""})()
        duration = next(elapsed)
        stdout = (
            "DECIMAL HEXADECIMAL DESCRIPTION\n"
            "140771328 0x8640000 UBI image, version: 1\n"
            f"Analyzed 1 file for 85 file signatures (196 magic patterns) in {duration} milliseconds\n"
        )
        return type("Result", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

    monkeypatch.setattr("ref_all_executor.context_fingerprint.subprocess.run", fake_run)
    first = fingerprint_directory(tmp_path, run_binwalk=True)
    second = fingerprint_directory(tmp_path, run_binwalk=True)

    assert first["files"][0]["binwalk"]["stdout"] != second["files"][0]["binwalk"]["stdout"]
    assert first["manifest_sha256"] == second["manifest_sha256"]
