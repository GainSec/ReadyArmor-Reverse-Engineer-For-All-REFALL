"""Binary (Mach-O) intake — the seed finder for compiled subjects.

Front-end swap for the source seed finder: instead of grepping source text, we
enumerate a binary's functions and its **dangerous imported functions** (the binary
analog of sinks: memcpy/strcpy/sprintf/system/ippReadIO/httpRead/…), then seed one
investigation per function that calls a dangerous import — priority by risk. Uses
LIEF for parsing and radare2 for function analysis + xrefs. Deterministic, no tokens.

The researcher then decompiles each function (r2 `pdc`/`pdg`) and audits it.
"""
import os
import subprocess

try:
    import lief
except ImportError:
    lief = None

R2 = os.environ.get("R2_BIN", "r2")

# imported function -> (category, risk). Lower risk = higher priority (claimed first).
DANGEROUS = {
    # memory corruption
    "memcpy": ("mem-corruption", 1), "memmove": ("mem-corruption", 1), "strcpy": ("mem-corruption", 1),
    "strcat": ("mem-corruption", 1), "stpcpy": ("mem-corruption", 1), "sprintf": ("mem-corruption", 1),
    "vsprintf": ("mem-corruption", 1), "gets": ("mem-corruption", 1), "bcopy": ("mem-corruption", 2),
    "strncpy": ("mem-corruption", 2), "strncat": ("mem-corruption", 2), "alloca": ("mem-corruption", 2),
    # command / code execution
    "system": ("command-exec", 1), "popen": ("command-exec", 1), "execl": ("command-exec", 1),
    "execve": ("command-exec", 1), "execvp": ("command-exec", 1), "posix_spawn": ("command-exec", 1),
    # IPP / HTTP protocol parsing (this server's core untrusted-input surface)
    "ippReadIO": ("ipp-parse", 1), "ippRead": ("ipp-parse", 1), "_ippReadIO": ("ipp-parse", 1),
    "httpRead": ("http-parse", 1), "httpGets": ("http-parse", 1), "httpReadRequest": ("http-parse", 1),
    "cupsdReadClient": ("http-parse", 1),
    # format string
    "printf": ("format-string", 3), "fprintf": ("format-string", 3), "syslog": ("format-string", 3),
    "asprintf": ("format-string", 3), "snprintf": ("format-string", 4),
    # parsing untrusted input
    "sscanf": ("parse-input", 2), "scanf": ("parse-input", 2), "strtol": ("parse-input", 4),
    "atoi": ("parse-input", 4),
    # allocation (integer-overflow → undersized buffer)
    "malloc": ("alloc-size", 4), "realloc": ("alloc-size", 4), "calloc": ("alloc-size", 4),
    # network sources
    "recv": ("net-source", 3), "recvfrom": ("net-source", 3), "accept": ("net-source", 3),
    # file
    "fopen": ("file", 4), "unlink": ("file", 4), "rename": ("file", 4),
}

_QUESTION = {
    "mem-corruption": "Memory-corruption sink. Decompile this function and check whether attacker-controlled length/data (from the IPP/HTTP request) reaches the copy without bounds enforcement — classic overflow.",
    "command-exec": "Command/exec sink. Check whether any argument derives from untrusted request data — command injection / arbitrary exec.",
    "ipp-parse": "IPP protocol parsing of untrusted request bytes. Audit length/tag/value handling for over-reads, type confusion, and integer issues.",
    "http-parse": "HTTP request parsing of untrusted bytes. Audit header/body/length handling for overflow, smuggling, and parser confusion.",
    "format-string": "printf-family call. Check whether the format string is attacker-controlled (format-string vulnerability) or the args can overflow the buffer.",
    "parse-input": "Parses untrusted input. Check for missing bounds/validation and integer conversion issues.",
    "alloc-size": "Allocation whose size may derive from untrusted input. Check for integer overflow/underflow producing an undersized buffer.",
    "net-source": "Reads untrusted bytes off the network. Follow this data forward into parsers/sinks it reaches.",
    "file": "Filesystem operation. Check for path traversal or attacker-controlled paths.",
}


def _r2(path, cmds, timeout=180):
    env = {**os.environ, "PATH": os.environ.get("PATH", "") + ":/usr/local/bin:/opt/radare2/binr/radare2"}
    r = subprocess.run([R2, "-q", "-e", "scr.color=0", "-c", cmds, path],
                       capture_output=True, text=True, timeout=timeout, env=env)
    return r.stdout


def classify(path):
    """LIEF: format, fat slices, per-slice function/symbol/import counts."""
    if lief is None:
        raise RuntimeError("LIEF not installed")
    fat = lief.MachO.parse(path)
    slices = []
    for b in fat:
        slices.append({"arch": str(b.header.cpu_type).split(".")[-1],
                       "functions": len(list(b.functions)), "symbols": len(list(b.symbols)),
                       "imports": sorted({f.name for f in b.imported_functions})})
    return {"format": "mach-o", "fat": len(fat) > 1, "slices": slices}


def dangerous_present(imports):
    """Intersect a slice's imports with the DANGEROUS catalog → {name:(category,risk)}."""
    out = {}
    for name in imports:
        key = name.lstrip("_")
        if name in DANGEROUS:
            out[name] = DANGEROUS[name]
        elif key in DANGEROUS:
            out[name] = DANGEROUS[key]
    return out


def import_callers(path, import_names):
    """radare2 (single session): for each dangerous import, the functions that call it.

    Returns {import: [{fcn,addr}]}. Analyzes once (aa), then axtj per import with a
    marker line so we can attribute interleaved output back to each import.
    """
    if not import_names:
        return {}
    # NOTE: '@@' is r2's foreach operator, so the marker must avoid it. axt (text) is
    # more stable than axtj here; line format: "<fcn> <from_addr> [CALL:...] <disasm>".
    parts = ["aa"]
    for n in import_names:
        clean = n.lstrip("_")
        parts.append(f"?e RZMARK {clean}")
        parts.append(f"axt @ sym.imp.{clean}")
    out = _r2(path, "; ".join(parts), timeout=400)
    callers, cur = {}, None
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("RZMARK "):
            cur = s.split(None, 1)[1].strip()
            continue
        if not cur:
            continue
        f = s.split()
        if len(f) >= 2 and f[1].startswith("0x") and ("[CALL" in s or "[CODE" in s):
            callers.setdefault(cur, []).append({"fcn": f[0], "addr": f[1]})
    return callers


def build_investigations(subject, binrel, callers_by_import):
    """Pure: cluster {import:[{fcn,addr}]} into per-function investigations, priority by risk.

    binrel is the binary path relative to the mounted subject workspace.
    """
    subject_root = os.environ.get("REFALL_SUBJECT_WORKSPACE_ROOT", "/projects").rstrip("/")
    binpath = f"{subject_root}/{subject}/{binrel}"
    # gather per function: which dangerous imports it calls
    per_fcn = {}
    for imp, refs in callers_by_import.items():
        cat, risk = DANGEROUS.get(imp, DANGEROUS.get(imp.lstrip("_"), ("parse-input", 5)))
        for r in refs:
            key = r["fcn"] or r["addr"]
            f = per_fcn.setdefault(key, {"fcn": r["fcn"], "addr": r["addr"], "calls": {}, "risk": 99})
            f["calls"].setdefault(cat, []).append(imp)
            f["risk"] = min(f["risk"], risk)
    invs = []
    for key, f in per_fcn.items():
        cats = sorted(f["calls"].keys(), key=lambda c: min(DANGEROUS.get(i, ("", 9))[1] for i in f["calls"][c]))
        lead_cat = cats[0]
        callnames = sorted({i for lst in f["calls"].values() for i in lst})
        invs.append({
            "title": f"[{lead_cat}] {f['fcn'] or f['addr']} — calls {', '.join(callnames[:6])}",
            "target_files": [binrel],
            "kind": lead_cat,
            "priority": f["risk"],
            "question": (f"Function {f['fcn'] or f['addr']} (addr {f['addr']}) in the binary calls "
                         f"dangerous imports: {', '.join(callnames)}. Decompile it: "
                         f"r2 -q -c 'aa; s {f['fcn'] or f['addr']}; pdc' \"{binpath}\". "
                         f"{_QUESTION.get(lead_cat, '')} Branch to callers/callees via r2 axt/axf."),
        })
    invs.sort(key=lambda v: v["priority"])
    return invs


def seed_binary(subject, path, binrel):
    """Full pipeline: classify → dangerous imports → callers → investigations. Picks richest slice."""
    info = classify(path)
    best = max(info["slices"], key=lambda s: s["functions"])
    dang = dangerous_present(best["imports"])
    callers = import_callers(path, list(dang.keys()))
    invs = build_investigations(subject, binrel, callers)
    return {"classify": info, "dangerous": dang, "n_callers": sum(len(v) for v in callers.values()),
            "investigations": invs}
