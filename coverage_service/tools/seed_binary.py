"""Seed a binary subject's plan from its dangerous imports + call sites (radare2 + LIEF).

Run inside the agent container:
  PYTHONPATH=/projects/REFALL-V10 python3 -m coverage_service.tools.seed_binary example \
    "bin/target"
"""
import json
import sys
import urllib.request

from coverage_service import binary

COV = "http://host.docker.internal:8900"


def main(subject, binrel, root=None, load=True, cov=COV):
    root = root or f"/projects/{subject}"
    path = f"{root}/{binrel}"
    res = binary.seed_binary(subject, path, binrel)
    print("=== classify ===")
    for s in res["classify"]["slices"]:
        print("  arch {} | functions {} | imports {}".format(s["arch"], s["functions"], len(s["imports"])))
    print("=== dangerous imports present: {} ===".format(len(res["dangerous"])))
    print("  " + json.dumps({k: v[0] for k, v in list(res["dangerous"].items())}))
    print("=== caller xrefs: {} | investigations: {} ===".format(res["n_callers"], len(res["investigations"])))
    for v in res["investigations"][:15]:
        print("  p{} {}".format(v["priority"], v["title"][:80]))
    if load:
        body = json.dumps({"subject": subject, "investigations": res["investigations"], "replace": True}).encode()
        req = urllib.request.Request(cov + "/plan", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        print("loaded plan:", json.loads(urllib.request.urlopen(req, timeout=90).read()))
    return res


if __name__ == "__main__":
    subj = sys.argv[1] if len(sys.argv) > 1 else "example"
    binrel = sys.argv[2] if len(sys.argv) > 2 else "bin/target"
    load = "--no-load" not in sys.argv
    main(subj, binrel, load=load)
