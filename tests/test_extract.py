from coverage_service.extract import extract_python, total_lines, extract_dir


def test_extract_python_top_level_symbols():
    src = "import os\n\ndef f(x):\n    return x\n\nclass C:\n    def m(self):\n        pass\n"
    syms = extract_python(src)
    names = {s["name"] for s in syms}
    assert names == {"f", "C"}  # top-level only; C's method is inside C
    f = next(s for s in syms if s["name"] == "f")
    assert f["line_start"] == 3 and f["line_end"] == 4


def test_total_lines():
    assert total_lines("a\nb\nc") == 3
    assert total_lines("a\nb\n") == 2


def test_extract_dir(tmp_path):
    (tmp_path / "a.py").write_text("def g():\n    return 1\n")
    (tmp_path / "b.txt").write_text("hello\nworld\n")
    d = tmp_path / ".venv"
    d.mkdir()
    (d / "skip.py").write_text("def skipped(): pass\n")
    files = {f["path"]: f for f in extract_dir(str(tmp_path))}
    assert "a.py" in files and "b.txt" in files
    assert not any("skip" in p for p in files)  # .venv skipped
    assert files["a.py"]["symbols"][0]["name"] == "g"
