from coverage_service.seeds import (scan_source, scan_dir, summarize,
                                    seeds_to_investigations, path_penalty)


def test_path_penalty_ordering():
    assert path_penalty("boots/main.py") == 0            # app code — leads
    assert path_penalty("tests/test_x.py") == 50
    assert path_penalty("boots/static/lib/three.min.js") == 80
    assert path_penalty("docs/plans/note.md") == 100


def test_app_code_outranks_test_same_category():
    anchors = [
        {"category": "exec-sink", "path": "tests/test_x.py", "line": 3, "risk": 1},
        {"category": "exec-sink", "path": "boots/main.py", "line": 9, "risk": 1},
    ]
    invs = seeds_to_investigations(anchors)
    assert invs[0]["target_files"] == ["boots/main.py"]   # penalty sinks the test file
    assert invs[0]["priority"] == 1 and invs[1]["priority"] == 51


def test_scan_source_finds_categories():
    src = "\n".join([
        "import os, pickle",
        "def run(cmd):",
        "    os.system(cmd)",                       # exec-sink
        "    data = pickle.loads(blob)",            # deserialize-sink
        "    password = 'hunter2'",                 # secret
        "    return request.args.get('x')",         # input-source
    ])
    cats = {a["category"] for a in scan_source("v.py", src)}
    assert {"exec-sink", "deserialize-sink", "secret", "input-source"} <= cats


def test_scan_skips_comments():
    src = "# os.system(evil)\n// eval(x)\nx = 1\n"
    assert scan_source("v.py", src) == []


def test_scan_records_line_and_risk():
    a = scan_source("v.py", "os.system(x)\n")[0]
    assert a["line"] == 1 and a["category"] == "exec-sink" and a["risk"] == 1
    assert "os.system" in a["snippet"]


def test_scan_dir(tmp_path):
    (tmp_path / "a.py").write_text("subprocess.run(user_input, shell=True)\n")
    d = tmp_path / "node_modules"
    d.mkdir()
    (d / "skip.py").write_text("eval(x)\n")
    anchors = scan_dir(str(tmp_path))
    assert any(a["path"] == "a.py" for a in anchors)
    assert not any("skip" in a["path"] for a in anchors)   # node_modules skipped


def test_summarize():
    anchors = [{"category": "exec-sink", "path": "a.py"}, {"category": "exec-sink", "path": "b.py"},
               {"category": "secret", "path": "a.py"}]
    s = summarize(anchors)
    assert s["total"] == 3 and s["by_category"]["exec-sink"] == 2 and s["files_touched"] == 2


def test_seeds_to_investigations_clusters_and_prioritizes():
    anchors = [
        {"category": "auth", "path": "a.py", "line": 5, "risk": 8},
        {"category": "exec-sink", "path": "a.py", "line": 10, "risk": 1},
        {"category": "exec-sink", "path": "a.py", "line": 12, "risk": 1},
    ]
    invs = seeds_to_investigations(anchors)
    assert len(invs) == 2                                   # (a.py,auth) + (a.py,exec-sink)
    assert invs[0]["kind"] == "exec-sink"                   # risk 1 sorts first
    assert invs[0]["priority"] == 1 and invs[0]["target_files"] == ["a.py"]
    assert "10,12" in invs[0]["question"]                   # both anchor lines listed
