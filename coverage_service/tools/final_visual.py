"""Final visual-report gate for REF-All research loops."""
import urllib.request

from coverage_service import project
from . import report_findings


def _content_type(headers):
    if hasattr(headers, "get_content_type"):
        return headers.get_content_type()
    return (headers.get("Content-Type", "") or "").split(";", 1)[0].strip().lower()


def verify_rendered_html(oid, *, timeout=30):
    url = f"{report_findings.WB}/api/workbenches/{report_findings.SLUG}/objects/{oid}/render"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ctype = _content_type(r.headers)
        body = r.read(256).lower()
    if ctype != "text/html" or b"<html" not in body:
        raise RuntimeError(f"final visual report {oid} is not renderable HTML: content-type={ctype!r}")
    return {"oid": oid, "url": f"{report_findings.WB}/wb/{report_findings.SLUG}/o/{oid}"}


def publish_final_visual(subject, title, *, timeout=30):
    """Publish the subject findings report and verify the workbench render path is HTML."""
    oid = report_findings.publish(subject, title)
    return verify_rendered_html(oid, timeout=timeout)


def publish_coverage_visual(subject, *, timeout=30):
    """Publish the subject coverage report and verify the workbench render path is HTML."""
    oid = project.publish(subject)
    return verify_rendered_html(oid, timeout=timeout)
