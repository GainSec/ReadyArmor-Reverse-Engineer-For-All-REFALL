#!/usr/bin/env python3
"""Generate a subject's INFO.md context briefing (deepsec-style) and store it in the service.

One strong agent reads the subject and writes a lean, concrete project briefing that every
researcher reads first — cutting false positives by giving them the subject's auth model,
conventions, and known-safe patterns up front.

  PYTHONPATH=. python3 drive_context.py --subject example
"""
import argparse

from ref_all_executor.oh_client import OHClient
from ref_all_executor.coverage_client import CoverageClient
from ref_all_executor import config
from ref_all_executor.usage import record_and_delete
from drive_characterize import log


def _objective(subject):
    subject_ws = config.subject_workspace(subject)
    context_url = f"{config.WB_BASE.rstrip('/')}/api/workbenches/{subject}/coverage/context"
    return f"""You are a REF-All CONTEXT WRITER. Produce a concise project briefing (INFO.md) for subject
"{subject}" that every security researcher reads FIRST. Target 60-120 lines of Markdown — lean, concrete,
specific to THIS codebase. Do NOT dump code.

Source: {subject_ws}   Toolchain (if built): {config.REFALL_WORKSPACE}/toolchain/output/{subject}/

Read enough of {subject_ws} to understand it (start with READMEs, entry points, config, and the
architecture.md under the toolchain output if present). Then write these sections:

- **What it is** — purpose in one short paragraph.
- **Architecture & entry points** — major components and where execution starts (cite real files).
- **Trust boundaries & auth model** — who is trusted, where untrusted input enters, how authz is enforced.
- **Framework primitives & conventions** — how they do routing, input handling, sanitization, config, secrets,
  subprocess/shell, file I/O. Name the helper functions/modules researchers will see repeatedly.
- **Known-safe patterns** — idioms that look scary but are safe here, so researchers don't false-positive them.
- **Likely-risky areas** — where you'd hunt first.
- **Deployment intent** — state clearly: PRODUCTION or SAMPLE_OR_TEST.

Store it (do not print the whole thing in chat):
POST {context_url} with JSON
  {{"subject":"{subject}","info_md":"<your markdown>","generated_by":"context-writer","root_container":"{subject_ws}"}}

Report only the number of lines written and the section titles."""


def run(subject):
    oh = OHClient()
    log(f"context: generating INFO.md for {subject} (one Claude agent) ...")
    cid = oh.start_conversation(workspace=config.local_workspace(config.subject_workspace(subject)),
        agent_settings=config.LANES["A"], text=_objective(subject), max_iterations=60)
    oh.run(cid)
    st = oh.wait_until_done(cid, timeout_s=2400, poll_s=12)
    record_and_delete(oh, cid, {"driver": "context", "agent_id": "context-writer",
                                "subject": subject, "lane": "A", "status": st})
    ctx = CoverageClient().get_context(subject)
    log(f"context: agent {st}. stored context present: {bool(ctx and ctx.get('info_md'))}")
    return st


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", default="example")
    a = ap.parse_args()
    run(a.subject)
