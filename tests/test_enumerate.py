from coverage_service.enumerate import partition_file, build_units


def _covers_exactly(leaves, n):
    seen = []
    for lf in leaves:
        seen.extend(range(lf["line_start"], lf["line_end"] + 1))
    return sorted(seen) == list(range(1, n + 1))  # every line once, disjoint


def test_partition_covers_every_line_once_with_gaps():
    leaves = partition_file(20, [{"name": "f", "line_start": 5, "line_end": 10}])
    assert _covers_exactly(leaves, 20)
    kinds = sorted(l["type"] for l in leaves)
    assert "symbol" in kinds and "line_range" in kinds


def test_partition_adjacent_symbols_no_overlap():
    leaves = partition_file(10, [
        {"name": "a", "line_start": 1, "line_end": 4},
        {"name": "b", "line_start": 5, "line_end": 10},
    ])
    assert _covers_exactly(leaves, 10)


def test_partition_overlapping_symbols_stay_disjoint():
    # overlapping/nested symbols must not double-count lines
    leaves = partition_file(12, [
        {"name": "outer", "line_start": 1, "line_end": 12},
        {"name": "inner", "line_start": 4, "line_end": 6},
    ])
    assert _covers_exactly(leaves, 12)


def test_build_units_makes_subject_file_and_leaves():
    units = build_units("bra", [{"path": "x.py", "total_lines": 6,
                                  "symbols": [{"name": "g", "line_start": 2, "line_end": 4}]}])
    types = [u["type"] for u in units]
    assert types.count("subject") == 1 and types.count("file") == 1
    assert all(u.get("parent_id") for u in units if u["type"] != "subject")
