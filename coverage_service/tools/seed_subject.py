"""Scan a subject's source for sensitive anchors and load them as the seed plan.

Run inside the agent container (where the subject source lives):
  PYTHONPATH=/projects/REFALL-V10 python3 -m coverage_service.tools.seed_subject example /projects/example
"""
import json
import sys
import urllib.request

from coverage_service.seeds import scan_dir, summarize, seeds_to_investigations

COV = "http://host.docker.internal:8900"


def main(subject, root, load=True, cov=COV):
    anchors = scan_dir(root)
    summ = summarize(anchors)
    invs = seeds_to_investigations(anchors)
    print("=== SENSITIVE SURFACE:", subject, "===")
    print("total anchors:", summ["total"], "| files touched:", summ["files_touched"],
          "| seed investigations:", len(invs))
    print("by category:", json.dumps(summ["by_category"]))
    print("hottest files:")
    for f, n in summ["hottest_files"][:12]:
        print("  {:4d}  {}".format(n, f))
    print("top seed investigations (by risk):")
    for v in invs[:15]:
        print("  p{:<2} {}".format(v["priority"], v["title"][:80]))
    if load:
        body = json.dumps({"subject": subject, "investigations": invs, "replace": True}).encode()
        req = urllib.request.Request(cov + "/plan", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        print("loaded plan:", json.loads(urllib.request.urlopen(req, timeout=60).read()))
    return summ, invs


if __name__ == "__main__":
    subj = sys.argv[1] if len(sys.argv) > 1 else "example"
    root = sys.argv[2] if len(sys.argv) > 2 else f"/projects/{subj}"
    load = "--no-load" not in sys.argv
    main(subj, root, load=load)
