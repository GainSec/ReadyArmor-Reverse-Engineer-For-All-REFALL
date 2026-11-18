from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

from .arcticbase_client import ArcticBaseClient
from . import config
from .report_draft import draft_report
from .report_enrich import enrich_workbench_report


ReportCallback = Callable[[str, str], dict]
LoopLauncher = Callable[..., dict]


class RefallLoopManager:
    def __init__(
        self,
        *,
        arcticbase: ArcticBaseClient | None = None,
        draft_report: ReportCallback | None = None,
        enrich_report: ReportCallback | None = None,
        loop_launcher: LoopLauncher | None = None,
    ) -> None:
        self.arcticbase = arcticbase or ArcticBaseClient()
        self._draft_report = draft_report
        self._enrich_report = enrich_report
        # Production lifecycle launches must go through REFALL AB's ops API so
        # source projection and capability authorization cannot be bypassed.
        # A launcher remains injectable for focused unit tests and embedders.
        self._loop_launcher = loop_launcher

    def start(self, name: str) -> dict:
        created = self.arcticbase.create_subject(name)
        slug = created.get("workbench_slug") or created.get("subject") or name
        subject = created.get("subject") or slug
        self._require_context(slug)
        if self._loop_launcher is None:
            return self.arcticbase.ops_command(f"start {slug}")
        loop = self._loop_launcher(subject=subject, workbench=slug, max_cycles=0)
        ledger = self._record(slug, "loop.start", "REFALL loop started", status="started")
        return {
            "subject": subject,
            "workbench": slug,
            "status": "started",
            "subject_path": created.get("subject_path"),
            "ledger_id": ledger.get("id"),
            "loop": loop,
        }

    def update(self, name: str) -> dict:
        slug = name
        if self._loop_launcher is None:
            return self.arcticbase.ops_command(f"update {slug}")
        workbench = self.arcticbase.get_workbench(slug)
        coverage = self.arcticbase.coverage_stats(slug)
        ledger_stats = self.arcticbase.ledger_stats(slug)
        subject = (workbench.get("custom_fields") or {}).get("refall_subject") or slug
        loop = self._loop_launcher(subject=subject, workbench=slug, max_cycles=1)
        ledger = self._record(
            slug,
            "loop.update",
            "REFALL loop state updated",
            status="updated",
            coverage=coverage,
            ledger_stats=ledger_stats,
        )
        return {
            "subject": subject,
            "workbench": slug,
            "status": "updated",
            "coverage": coverage,
            "ledger_stats": ledger_stats,
            "ledger_id": ledger.get("id"),
            "loop": loop,
        }

    def closeout(self, name: str) -> dict:
        slug = name
        workbench = self.arcticbase.get_workbench(slug)
        subject = (workbench.get("custom_fields") or {}).get("refall_subject") or slug
        coverage = self.arcticbase.coverage_stats(slug)
        ledger_stats = self.arcticbase.ledger_stats(slug)
        draft = (self._draft_report or draft_report)(slug, subject)
        enriched = (self._enrich_report or enrich_workbench_report)(slug, subject)
        # Enrichment persists artifacts and may append ledger evidence even when
        # structural-downgrade protection refuses to replace the richer formal
        # report. Refresh the authoritative draft after enrichment so the
        # report freshness high-water mark includes those writes before the
        # closeout gate is evaluated.
        draft = (self._draft_report or draft_report)(slug, subject)
        closeout_gate = (
            self.arcticbase.closeout_gate(slug)
            if hasattr(self.arcticbase, "closeout_gate")
            else {"passed": True, "checks": []}
        )
        if not closeout_gate.get("passed"):
            ledger = self._record(
                slug,
                "loop.closeout.blocked",
                "REFALL closeout blocked by required gates",
                status="blocked",
                coverage=coverage,
                ledger_stats=ledger_stats,
                draft_report=draft,
                enrichment=enriched,
                closeout_gate=closeout_gate,
            )
            return {
                "subject": subject,
                "workbench": slug,
                "status": "blocked",
                "coverage": coverage,
                "ledger_stats": ledger_stats,
                "draft_report": draft,
                "enrichment": enriched,
                "closeout_gate": closeout_gate,
                "ledger_id": ledger.get("id"),
            }
        ledger = self._record(
            slug,
            "loop.closeout",
            "REFALL loop closed out",
            status="closed",
            coverage=coverage,
            ledger_stats=ledger_stats,
            draft_report=draft,
            enrichment=enriched,
            closeout_gate=closeout_gate,
        )
        return {
            "subject": subject,
            "workbench": slug,
            "status": "closed",
            "coverage": coverage,
            "ledger_stats": ledger_stats,
            "draft_report": draft,
            "enrichment": enriched,
            "closeout_gate": closeout_gate,
            "ledger_id": ledger.get("id"),
        }

    def _record(self, slug: str, action: str, summary: str, **fields) -> dict:
        event = {
            "kind": "ops-event",
            "action": action,
            "summary": summary,
            "status": fields.get("status"),
            "created_by": "refall-loop",
            **{k: v for k, v in fields.items() if v is not None},
        }
        ledger = self.arcticbase.append_ledger(slug, event)
        self.arcticbase.push_ops_event({"subject": slug, "action": action, "summary": summary, **fields})
        return ledger

    def _require_context(self, slug: str) -> dict:
        context = self.arcticbase.get_coverage_context(slug)
        if not str((context or {}).get("info_md") or "").strip():
            raise RuntimeError(
                "Generate Context before starting REFALL; context.md is required for the head and specialist agents."
            )
        return context


def launch_standing_loop(*, subject: str, workbench: str, max_cycles: int = 0) -> dict:
    repo_root = Path(os.environ.get("REFALL_REPO_ROOT", Path(__file__).resolve().parents[1]))
    log_root = Path(os.environ.get("REFALL_LOOP_LOG_ROOT", repo_root / "logs" / "standing-loop"))
    log_root.mkdir(parents=True, exist_ok=True)
    log_path = log_root / f"{workbench}-{int(os.times().elapsed * 1000)}.log"
    env = os.environ.copy()
    env["REFALL_WORKBENCH_BASE"] = config.resolve_public_base()
    env["REFALL_COVERAGE_WORKBENCH_SLUG"] = workbench
    env["PYTHONPATH"] = str(repo_root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    argv = [
        sys.executable,
        "-m",
        "ref_all_executor.standing_loop",
        "--subject",
        subject,
        "--workbench",
        workbench,
        "--max-cycles",
        str(max_cycles),
    ]
    with log_path.open("ab") as log:
        proc = subprocess.Popen(
            argv,
            cwd=str(repo_root),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return {
        "status": "launched",
        "pid": proc.pid,
        "mode": "continuous" if max_cycles == 0 else "bounded",
        "max_cycles": max_cycles,
        "log": str(log_path),
    }
