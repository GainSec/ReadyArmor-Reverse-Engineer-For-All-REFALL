"""Mechanical sensitive-anchor finder — the seed set for the 'juicy path'.

Classical security research starts at the interesting surface (dangerous sinks,
untrusted sources, secrets, auth) and branches out along the connections. This
module finds those anchors deterministically (regex/AST-free scan, no model, no
tokens) so researchers can start from real attack surface instead of file order.

Output feeds the Coverage Service `investigations` plan: one investigation per
(file, category) cluster, priority = category risk (lower = more dangerous =
claimed first). Recall over precision — the researcher validates each seed.
"""
import os
import re

from .extract import TEXT_EXTS, SKIP_DIRS

# category -> (risk_priority, guidance, [patterns]).  Lower risk => claimed first.
CATEGORIES = {
    "exec-sink": (1,
        "command/code execution",
        [r"\bos\.system\s*\(", r"\bsubprocess\.(?:Popen|call|run|check_output|check_call)\b",
         r"\bshell\s*=\s*True\b", r"\beval\s*\(", r"\bexec\s*\(", r"\bpty\.spawn\b",
         r"\bcommands\.(?:getoutput|getstatusoutput)\b", r"\bos\.popen\s*\(",
         r"\bchild_process\.(?:exec|spawn)\b", r"\bnew\s+Function\s*\("]),
    "deserialize-sink": (2,
        "unsafe deserialization",
        [r"\bpickle\.(?:load|loads)\b", r"\byaml\.load\s*\((?![^)]*Loader)", r"\bmarshal\.(?:load|loads)\b",
         r"\bcPickle\b", r"\bjsonpickle\b", r"\b__reduce__\b", r"\bunserialize\s*\(",
         r"\bObjectInputStream\b"]),
    "sql-sink": (3,
        "SQL / query construction",
        [r"\bexecute(?:many)?\s*\(", r"\bcursor\s*\(", r"\.raw\s*\(",
         r"(?:SELECT|INSERT|UPDATE|DELETE)\b.*(?:\+|%|\.format|f[\"'])", r"\.query\s*\("]),
    "file-sink": (4,
        "filesystem access / path handling",
        [r"\bopen\s*\(", r"\bos\.(?:remove|unlink|rename|rmdir|mkdir)\b",
         r"\bshutil\.(?:rmtree|move|copy\w*)\b", r"\bsend_file\b", r"\bos\.path\.join\s*\(",
         r"\bPath\s*\(", r"\.save\s*\(", r"\bsendfile\b", r"\bfs\.(?:readFile|writeFile|unlink)\b"]),
    "secret": (5,
        "secrets / weak crypto",
        [r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?key|token|private[_-]?key|credential)s?\s*[=:]",
         r"\bhashlib\.(?:md5|sha1)\b", r"\b(?:MD5|SHA1|DES|RC4)\b",
         r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", r"\brandom\.(?:random|randint)\b"]),
    "net-sink": (6,
        "network / SSRF surface",
        [r"\brequests\.(?:get|post|put|delete|patch|request|head)\b",
         r"\burllib\.?(?:request)?\.(?:urlopen|urlretrieve)\b", r"\bsocket\.(?:socket|connect)\b",
         r"\bhttp\.client\b", r"\baiohttp\b", r"\bfetch\s*\(", r"\baxios\."]),
    "auth": (8,
        "authentication / authorization",
        [r"@(?:login_required|permission_required|requires_auth|authenticated|roles_required)\b",
         r"\bis_admin\b", r"\b(?:verify|validate|check|require)_(?:token|password|signature|permission|auth\w*)\b",
         r"\bjwt\.(?:decode|encode)\b", r"\bsession\[", r"\bcurrent_user\b", r"\bcheck_password\b"]),
    "input-source": (12,
        "untrusted input source",
        [r"\brequest\.(?:args|form|json|files|data|values|cookies|headers|GET|POST|body|params|query)\b",
         r"\bflask\.request\b", r"\binput\s*\(", r"\bsys\.argv\b", r"\bos\.environ\b",
         r"\bos\.getenv\s*\(", r"\.files\[", r"\brecv\s*\(", r"\breq\.(?:body|query|params|headers)\b"]),
}

_COMPILED = {c: (risk, guide, [re.compile(p) for p in pats]) for c, (risk, guide, pats) in CATEGORIES.items()}

# Noisy paths keep their seeds (for the optional 100% mode) but get a priority PENALTY so real
# application code leads. Higher penalty => claimed later. Docs > vendored/minified > tests.
_DOC_RX = re.compile(r"\.(?:md|markdown|rst|txt)$|(?:^|/)docs?/")
_VENDOR_RX = re.compile(r"\.min\.(?:js|css)$|(?:^|/)(?:static|vendor|dist|build|assets|third[_-]?party|node_modules)/"
                        r"|(?:three|tailwind|jquery|bootstrap|lodash|d3|chart|moment|webpack)\b")
_TEST_RX = re.compile(r"(?:^|/)(?:tests?|__tests__|spec)(?:/|$)|(?:^|_)test_|_test\.|\.spec\.")


def path_penalty(path):
    p = path.lower()
    if _DOC_RX.search(p):
        return 100
    if _VENDOR_RX.search(p):
        return 80
    if _TEST_RX.search(p):
        return 50
    return 0  # real application code — no penalty


def scan_source(path, src):
    """Return anchors [{category, path, line, risk, snippet}] for one file's source text."""
    anchors = []
    for i, line in enumerate(src.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "*")):
            continue  # skip blank / comment-only lines (cheap FP reduction)
        for cat, (risk, _guide, regexes) in _COMPILED.items():
            if any(rx.search(line) for rx in regexes):
                anchors.append({"category": cat, "path": path, "line": i, "risk": risk,
                                "snippet": stripped[:200]})
    return anchors


def scan_dir(root, exts=TEXT_EXTS, skip_dirs=SKIP_DIRS):
    """Walk root; return all sensitive anchors across the subject."""
    anchors = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in skip_dirs]
        for fn in fns:
            if os.path.splitext(fn)[1].lower() not in exts:
                continue
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, root)
            try:
                src = open(full, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            anchors.extend(scan_source(rel, src))
    return anchors


def summarize(anchors):
    """Counts by category + by file, for the operator view."""
    by_cat, by_file = {}, {}
    for a in anchors:
        by_cat[a["category"]] = by_cat.get(a["category"], 0) + 1
        by_file[a["path"]] = by_file.get(a["path"], 0) + 1
    return {"total": len(anchors), "by_category": dict(sorted(by_cat.items(), key=lambda x: -x[1])),
            "files_touched": len(by_file),
            "hottest_files": sorted(by_file.items(), key=lambda x: -x[1])[:15]}


_QUESTION = {
    "exec-sink": "Command/code-execution sink(s) here. Trace every argument back to its origin: can "
                 "untrusted input reach these calls without sanitization? Look for injection. Then branch "
                 "to callers/data sources feeding these lines.",
    "deserialize-sink": "Unsafe-deserialization sink(s). Determine whether attacker-controlled bytes can "
                        "reach them (RCE via gadget chains). Branch to where the serialized data comes from.",
    "sql-sink": "SQL/query construction. Check for string concatenation/format of untrusted input "
                "(injection) vs parameterized queries. Branch to the input sources.",
    "file-sink": "Filesystem/path handling. Check for path traversal, arbitrary read/write/delete, and "
                 "unsafe joins of untrusted input. Branch to where the path/filename originates.",
    "secret": "Secret material or weak crypto. Confirm hardcoded secrets, weak algorithms (MD5/SHA1/DES), "
              "or predictable randomness. Branch to where this value is used/verified.",
    "net-sink": "Outbound network call. Check for SSRF (attacker-controlled URL/host) and unvalidated "
                "destinations. Branch to where the URL/target is derived.",
    "auth": "Auth/authz logic. Check for bypasses, missing checks, weak token/signature validation, and "
            "privilege boundaries. Branch to the protected resources and the identity source.",
    "input-source": "Untrusted input source. Follow this data forward: where does it flow, and does it "
                    "reach any dangerous sink without validation? Branch to the sinks it reaches.",
}


def seeds_to_investigations(anchors):
    """Cluster anchors by (file, category) into prioritized 'seed' investigations."""
    clusters = {}
    for a in anchors:
        clusters.setdefault((a["path"], a["category"]), []).append(a)
    invs = []
    for (path, cat), items in clusters.items():
        risk = _COMPILED[cat][0]
        guide = _COMPILED[cat][1]
        lines = sorted(x["line"] for x in items)
        line_str = ",".join(str(x) for x in lines[:20]) + ("…" if len(lines) > 20 else "")
        invs.append({
            "title": f"[{cat}] {guide} — {path}",
            "target_files": [path],
            "kind": cat,
            "priority": risk + path_penalty(path),   # app code leads; noisy paths sink
            "n_anchors": len(items),
            "question": f"{guide.capitalize()} anchors at {path}:{line_str}. {_QUESTION[cat]}",
        })
    # lowest priority number first (most dangerous app code), then most anchors
    invs.sort(key=lambda v: (v["priority"], -v["n_anchors"]))
    return invs
