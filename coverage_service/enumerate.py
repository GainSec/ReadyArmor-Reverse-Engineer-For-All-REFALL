from .ids import unit_id


def partition_file(total_lines, symbols):
    """Return disjoint leaf units covering lines 1..total_lines exactly once.

    A leaf is either a `symbol` (a symbol body) or a `line_range` (the gaps
    between symbols: imports, module-level code, comments, blanks). Overlapping
    or nested symbols are clamped to the running cursor so the partition stays
    disjoint (first-wins), which keeps covered_lines exact.
    """
    syms = sorted((s for s in symbols if s["line_start"] <= s["line_end"]),
                  key=lambda s: s["line_start"])
    leaves, cursor = [], 1
    for s in syms:
        ls, le = max(1, s["line_start"]), min(total_lines, s["line_end"])
        if le < cursor:
            continue  # fully inside an already-covered region
        ls = max(ls, cursor)
        if ls > cursor:
            leaves.append({"type": "line_range", "line_start": cursor, "line_end": ls - 1, "name": ""})
        leaves.append({"type": "symbol", "line_start": ls, "line_end": le, "name": s["name"]})
        cursor = le + 1
    if cursor <= total_lines:
        leaves.append({"type": "line_range", "line_start": cursor, "line_end": total_lines, "name": ""})
    return leaves


def build_units(subject, files):
    subj_id = unit_id(subject, "subject", None, None, None)
    units = [{"id": subj_id, "subject": subject, "type": "subject", "path": None,
              "line_start": None, "line_end": None, "parent_id": None, "total_lines": None,
              "indexed_src": "enumerate", "name": subject}]
    for f in files:
        path, n = f["path"], f["total_lines"]
        fid = unit_id(subject, "file", path, None, None)
        units.append({"id": fid, "subject": subject, "type": "file", "path": path,
                      "line_start": 1, "line_end": n, "parent_id": subj_id, "total_lines": n,
                      "indexed_src": "enumerate", "name": path})
        for lf in partition_file(n, f.get("symbols", [])):
            lid = unit_id(subject, lf["type"], path, lf["line_start"], lf["line_end"], lf["name"])
            units.append({"id": lid, "subject": subject, "type": lf["type"], "path": path,
                          "name": lf["name"], "line_start": lf["line_start"], "line_end": lf["line_end"],
                          "parent_id": fid, "total_lines": lf["line_end"] - lf["line_start"] + 1,
                          "indexed_src": f.get("src", "enumerate")})
    return units
