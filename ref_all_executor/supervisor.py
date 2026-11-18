"""REFALL loop supervisor.

Runs on a tiered cron cadence next to a live standing loop:

- fast tick (every minute): liveness only. Probes REFALL AB, Agent Canvas, and
  the standing loop process, and recovers whichever one is down.
- full tick (every 3 minutes): the fast tick plus the full `RefallWatchdog`
  pass (agent health, wishlist installs, token/cost/runtime ceilings), a
  subject-relevance check over active agents, and a status report.

Escalation: if recovery fires `recover_max` times inside `recover_window_s`,
the supervisor stops the loop, writes a HOLD file, and refuses to restart
anything until an operator clears it. That converts a crash *loop* into a
single stop plus a report, which is the behaviour a teardown policy gets wrong.

The supervisor never tears the stack down and never deletes its own cron entry.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .watchdog import (
    RefallWatchdog,
    append_jsonl,
    append_text,
    iso_now,
    load_json,
    request_json,
    save_json,
)

DEFAULT_REPO_ROOT = os.environ.get("REFALL_REPO_ROOT", str(Path(__file__).resolve().parents[1]))
DEFAULT_BASE_URL = os.environ.get("REFALL_PUBLIC_BASE_URL", "http://127.0.0.1:7673")
DEFAULT_OH_BASE = os.environ.get("REFALL_OPENHANDS_BASE", "http://127.0.0.1:8000")

CRON_MARKER_FAST = "REFALL_V10_SUPERVISOR_FAST"
CRON_MARKER_FULL = "REFALL_V10_SUPERVISOR_FULL"
CANVAS_CONTAINER = "refall-agent-canvas"
LAUNCHD_LABEL = "com.gainpalfam.refall-v10.arcticbase"

STATUS_HEALTHY = "healthy"
STATUS_DEGRADED = "degraded"
STATUS_RECOVERED = "recovered"
STATUS_ESCALATED = "escalated"


@dataclass
class SupervisorConfig:
    subject: str
    repo_root: Path = field(default_factory=lambda: Path(DEFAULT_REPO_ROOT))
    base_url: str = DEFAULT_BASE_URL
    oh_base: str = DEFAULT_OH_BASE
    # Escalation: N recoveries inside the window stops the loop and holds.
    recover_max: int = 3
    recover_window_s: int = 3600
    # An agent must produce a subject-shaped write within this many full ticks.
    relevance_grace_ticks: int = 2
    # If agents are active but tagged intel (fact/lead/finding) does not grow in
    # the ledger for this many full ticks, the tag->ledger->report pipeline is
    # likely broken (agents not emitting tags, or ingest dropping them).
    intel_stall_ticks: int = 3
    # If tagged intel is growing but the report object has not been rewritten in
    # this many minutes, the report is not being refreshed from the ledger.
    report_stale_minutes: int = 30
    dry_run: bool = False

    def paths(self) -> dict[str, Path]:
        root = Path(self.repo_root).expanduser()
        logs = root / "logs"
        return {
            "logs": logs,
            "state": logs / "refall-supervisor-state.json",
            "status": logs / "refall-supervisor-status.md",
            "hold": logs / "refall-supervisor-HOLD",
            "log": logs / "refall-supervisor.log",
            "audit": logs / "refall-supervisor.jsonl",
        }


# cron runs with a minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin), which excludes
# the usual docker and launchctl locations. An unresolved `docker` would make
# every probe report the canvas container as "absent" and turn recovery into a
# no-op exactly when it is needed, so binaries are resolved by absolute path.
_BIN_CANDIDATES = {
    "docker": ["/usr/local/bin/docker", "/opt/homebrew/bin/docker", "/usr/bin/docker"],
    "launchctl": ["/bin/launchctl", "/usr/bin/launchctl"],
    "pgrep": ["/usr/bin/pgrep", "/bin/pgrep"],
    "ps": ["/bin/ps", "/usr/bin/ps"],
    "crontab": ["/usr/bin/crontab", "/bin/crontab"],
    "kill": ["/bin/kill", "/usr/bin/kill"],
}


def resolve_binary(name: str) -> str:
    """Absolute path for a binary, falling back to the bare name."""
    from shutil import which

    for candidate in _BIN_CANDIDATES.get(name, []):
        if Path(candidate).exists():
            return candidate
    return which(name) or name


def watchdog_active_agents(sample: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-agent rows from a watchdog sample.

    `run_once()` reports `active_count` and `active_cids` at the top level but
    keeps the agent detail in the raw ops/agents payload, so the rows are read
    from there and fall back to bare CIDs when the endpoint failed.
    """
    endpoints = sample.get("endpoints")
    if isinstance(endpoints, dict):
        ops = endpoints.get("ops_agents")
        data = ops.get("data") if isinstance(ops, dict) else None
        rows = data.get("active") if isinstance(data, dict) else None
        if isinstance(rows, list) and rows:
            return [r for r in rows if isinstance(r, dict)]
    cids = sample.get("active_cids")
    if isinstance(cids, list):
        return [{"cid": c} for c in cids if c]
    return []


def _run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    if cmd:
        cmd = [resolve_binary(cmd[0]), *cmd[1:]]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return 1, str(exc)[:300]
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()[:500]


def loop_process_pids(subject: str) -> list[int]:
    """PIDs of standing loops for this subject (empty when none are running)."""
    rc, out = _run(["pgrep", "-f", r"ref_all_executor\.standing_loop"])
    if rc != 0 or not out:
        return []
    pids: list[int] = []
    for line in out.splitlines():
        line = line.strip()
        if not line.isdigit():
            continue
        _, argv = _run(["ps", "-p", line, "-o", "command="])
        if subject in argv or subject in {"all", "*"}:
            pids.append(int(line))
    return pids


class RefallSupervisor:
    def __init__(
        self,
        config: SupervisorConfig,
        *,
        now: Callable[[], float] = time.time,
        watchdog_factory: Callable[[], RefallWatchdog] | None = None,
        runner: Callable[[list[str], int], tuple[int, str]] = _run,
    ) -> None:
        self.cfg = config
        self.subject = config.subject
        self.now = now
        self.run_cmd = runner
        self.paths = config.paths()
        self.paths["logs"].mkdir(parents=True, exist_ok=True)
        # The embedded watchdog runs in DRY-RUN: it observes agent health,
        # wishlist, and ceilings, but must NOT stop conversations or file
        # watchdog_conversation_stopped pending actions. The standing loop owns
        # conversation lifecycle now (reap on completion, retry on failure); a
        # watchdog that also stops "runaway" agents kills legitimate long RE
        # tasks and clogs the pending queue. Supervision observes; the loop acts.
        self._watchdog_factory = watchdog_factory or (
            lambda: RefallWatchdog(
                subject=self.subject,
                repo_root=Path(self.cfg.repo_root),
                base_url=self.cfg.base_url,
                oh_base=self.cfg.oh_base,
                dry_run=True,
            )
        )

    # ---------------------------------------------------------------- state

    def _state(self) -> dict[str, Any]:
        return load_json(self.paths["state"], {"recoveries": [], "relevance": {}, "last_status": None})

    def _save_state(self, state: dict[str, Any]) -> None:
        save_json(self.paths["state"], state)

    def hold_active(self) -> bool:
        return self.paths["hold"].exists()

    def _log(self, line: str) -> None:
        append_text(self.paths["log"], f"{iso_now()} subject={self.subject} {line}")

    # --------------------------------------------------------------- probes

    def probe(self) -> dict[str, Any]:
        """Liveness of the three things a loop needs. Cheap enough for 1/min."""
        ab = request_json("GET", f"{self.cfg.base_url}/api/health", timeout=8)
        canvas = request_json("GET", f"{self.cfg.oh_base}/api/conversations", timeout=8)
        # 401 means the canvas backend is alive and demanding auth, which is healthy.
        canvas_ok = bool(canvas.get("ok")) or canvas.get("status") == 401
        pids = loop_process_pids(self.subject)
        rc, canvas_state = self.run_cmd(
            ["docker", "inspect", CANVAS_CONTAINER, "--format", "{{.State.Status}}"], 20
        )
        return {
            "refall_ab_ok": bool(ab.get("ok")),
            "canvas_ok": canvas_ok,
            "canvas_container": canvas_state if rc == 0 else "absent",
            "loop_pids": pids,
            "loop_alive": bool(pids),
        }

    # ------------------------------------------------------------- recovery

    def recover(self, probe: dict[str, Any]) -> dict[str, Any]:
        """Restart whichever service is down. Never a stack-wide teardown."""
        actions: list[str] = []
        reasons: list[str] = []

        if not probe["refall_ab_ok"]:
            reasons.append("refall_api_unreachable")
            if self.cfg.dry_run:
                actions.append("refall_ab=would_reload")
            else:
                rc, _ = self.run_cmd(["launchctl", "list", LAUNCHD_LABEL], 20)
                if rc == 0:
                    self.run_cmd(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"], 60)
                    actions.append("refall_ab=kickstarted")
                else:
                    plist = Path.home() / "Library/LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
                    if plist.exists():
                        self.run_cmd(["launchctl", "load", "-w", str(plist)], 60)
                        actions.append("refall_ab=launchd_reloaded")
                    else:
                        actions.append("refall_ab=plist_missing")

        if not probe["canvas_ok"]:
            reasons.append("openhands_agent_server_unreachable")
            state = probe.get("canvas_container")
            if self.cfg.dry_run:
                actions.append("canvas=would_restart")
            elif state == "absent":
                actions.append("canvas=absent_operator_must_recreate")
            elif state == "running":
                self.run_cmd(["docker", "restart", CANVAS_CONTAINER], 120)
                actions.append("canvas=bounced")
            else:
                self.run_cmd(["docker", "start", CANVAS_CONTAINER], 120)
                actions.append("canvas=restarted")

        if not actions:
            return {"recovered": False, "actions": [], "reasons": []}

        state = self._state()
        state.setdefault("recoveries", []).append(
            {"ts": self.now(), "iso": iso_now(), "reasons": reasons, "actions": actions}
        )
        self._save_state(state)
        self._log(f"status=recovered reasons={','.join(reasons)} actions={','.join(actions)}")
        return {"recovered": True, "actions": actions, "reasons": reasons}

    def recent_recoveries(self) -> list[dict[str, Any]]:
        cutoff = self.now() - self.cfg.recover_window_s
        return [r for r in self._state().get("recoveries", []) if float(r.get("ts", 0)) >= cutoff]

    # ----------------------------------------------------------- escalation

    def check_escalation(self) -> dict[str, Any] | None:
        """N recoveries inside the window -> stop the loop and hold."""
        recent = self.recent_recoveries()
        if len(recent) < self.cfg.recover_max:
            return None
        return self.engage_hold(recent)

    def engage_hold(self, history: list[dict[str, Any]]) -> dict[str, Any]:
        pids = loop_process_pids(self.subject)
        stopped: list[int] = []
        if not self.cfg.dry_run:
            for pid in pids:
                rc, _ = self.run_cmd(["kill", "-TERM", str(pid)], 20)
                if rc == 0:
                    stopped.append(pid)

        window_m = self.cfg.recover_window_s // 60
        lines = [
            "REFALL SUPERVISOR HOLD",
            "",
            f"escalated : {iso_now()}",
            f"subject   : {self.subject}",
            f"reason    : {len(history)} recoveries within {window_m}m",
            f"loop      : stopped pids {stopped}" if stopped else "loop      : no running loop found",
            "",
            "recovery history:",
        ]
        for item in history:
            lines.append(f"  {item.get('iso')}  {','.join(item.get('reasons') or [])}  ->  {','.join(item.get('actions') or [])}")
        lines += [
            "",
            "The supervisor will not restart anything while this file exists.",
            f"Report: {self.paths['status']}",
            "",
            "To resume once the underlying fault is fixed:",
            f"  rm {self.paths['hold']}",
        ]
        self.paths["hold"].write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._log(f"status=escalated recoveries={len(history)} stopped_pids={stopped}")

        # Durable record in REFALL AB when it is reachable. The file is the real
        # gate: escalation often happens precisely because REFALL AB is down.
        try:
            request_json(
                "POST",
                f"{self.cfg.base_url}/api/workbenches/{self.subject}/pending-actions",
                body={
                    "kind": "supervisor_escalation",
                    "title": f"REFALL loop stopped: {len(history)} recoveries within {window_m}m",
                    "description": (
                        f"The supervisor recovered REFALL infrastructure {len(history)} times "
                        f"within {window_m} minutes for subject {self.subject}. The loop has been "
                        f"stopped and the supervisor is holding. Operator review required."
                    ),
                    "priority": "critical",
                    "created_by": "refall-supervisor",
                    "required_receipt_type": "supervisor_escalation_review",
                },
                timeout=10,
            )
        except Exception:
            pass

        return {"escalated": True, "stopped_pids": stopped, "history": history}

    # ------------------------------------------------------------ relevance

    def check_relevance(self, agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Flag active agents that are not producing subject-shaped work.

        Deterministic and free: an agent is on-subject when its unit belongs to
        this subject and it has produced a coverage/ledger write recently. An
        agent that shows neither for `relevance_grace_ticks` full ticks is
        flagged for review rather than killed -- long analysis is legitimate.
        """
        state = self._state()
        tracked: dict[str, Any] = state.setdefault("relevance", {})
        flags: list[dict[str, Any]] = []
        seen: set[str] = set()

        for agent in agents:
            cid = str(agent.get("cid") or "")
            if not cid:
                continue
            seen.add(cid)
            entry = tracked.setdefault(cid, {"idle_ticks": 0, "last_iteration": None})

            unit_id = agent.get("unit_id")
            on_subject_unit = bool(unit_id) and str(agent.get("subject") or self.subject) == self.subject
            iteration = agent.get("iteration")
            progressed = iteration is not None and iteration != entry.get("last_iteration")
            entry["last_iteration"] = iteration

            if progressed and on_subject_unit:
                entry["idle_ticks"] = 0
            else:
                entry["idle_ticks"] = int(entry.get("idle_ticks", 0)) + 1

            if entry["idle_ticks"] > self.cfg.relevance_grace_ticks:
                flags.append({
                    "cid": cid,
                    "unit_id": unit_id,
                    "lane": agent.get("lane"),
                    "idle_ticks": entry["idle_ticks"],
                    "on_subject_unit": on_subject_unit,
                    "reason": "no subject-shaped progress",
                })

        for cid in list(tracked):
            if cid not in seen:
                tracked.pop(cid, None)
        self._save_state(state)
        return flags

    # ------------------------------------------------------- intel/report flow

    def _intel_subjects(self, agents: list[dict[str, Any]]) -> list[str]:
        if self.subject and self.subject != "all":
            return [self.subject]
        subs = {str(a.get("subject")) for a in agents if isinstance(a, dict) and a.get("subject")}
        return sorted(s for s in subs if s and s != "None")

    def check_intel_flow(
        self, snapshot: dict[str, Any], agents: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Confirm the tag -> ledger -> report pipeline is actually flowing.

        Two failures the operator must hear about:
          1. Agents are active but tagged intel (fact/lead/finding) is NOT
             growing in the ledger for `intel_stall_ticks` full ticks -- agents
             may not be emitting [FACT]/[FLOW]/[LEAD]/```refall-submit tags, or
             ingest is dropping them before they reach the ledger.
          2. Intel IS growing but the report object has not been rewritten for
             `report_stale_minutes` -- the report is not being refreshed from
             the ledger as expected.
        Deterministic and read-only: it only reads ledger stats and the report
        object's timestamp.
        """
        active = int(snapshot.get("active_count") or 0)
        subjects = self._intel_subjects(agents)
        if not subjects:
            return []
        state = self._state()
        track: dict[str, Any] = state.setdefault("intel_flow", {})
        flags: list[dict[str, Any]] = []
        for subj in subjects:
            stats = request_json(
                "GET", f"{self.cfg.base_url}/api/workbenches/{subj}/ledger/stats", timeout=8
            )
            by_kind = ((stats.get("data") or {}).get("by_kind") or {}) if stats.get("ok") else {}
            intel = sum(int(by_kind.get(k, 0) or 0) for k in ("fact", "lead", "finding"))
            rec = track.setdefault(subj, {"count": None, "stalled": 0})
            grew = rec.get("count") is None or intel > int(rec["count"])
            rec["stalled"] = 0 if (grew or active == 0) else int(rec.get("stalled", 0)) + 1
            rec["count"] = intel
            rec["iso"] = iso_now()

            if active > 0 and rec["stalled"] >= self.cfg.intel_stall_ticks:
                flags.append({
                    "subject": subj, "kind": "intel_not_landing",
                    "active_agents": active, "intel": intel, "stalled_ticks": rec["stalled"],
                    "message": (
                        f"{active} agent(s) active on {subj} but tagged intel "
                        f"(fact/lead/finding) has not grown for {rec['stalled']} full ticks "
                        f"(stuck at {intel}) — verify agents emit "
                        f"[FACT]/[FLOW]/[LEAD]/```refall-submit and that ingest persists them"
                    ),
                })
            elif grew and intel > 0:
                age_min = self._report_age_minutes(subj)
                if age_min is not None and age_min >= self.cfg.report_stale_minutes:
                    flags.append({
                        "subject": subj, "kind": "report_stale",
                        "intel": intel, "report_age_minutes": round(age_min, 1),
                        "message": (
                            f"tagged intel is growing on {subj} (now {intel}) but the report "
                            f"object has not been rewritten for {round(age_min)}m — the report "
                            f"is not refreshing from the ledger"
                        ),
                    })
        state["intel_flow"] = track
        self._save_state(state)
        return flags

    def _report_age_minutes(self, subject: str) -> float | None:
        """Minutes since the current report object was last written, or None."""
        wb = request_json("GET", f"{self.cfg.base_url}/api/workbenches/{subject}", timeout=8)
        cf = ((wb.get("data") or {}).get("custom_fields") or {}) if wb.get("ok") else {}
        oid = cf.get("refall_current_report_object_id")
        if not oid:
            return None
        obj = request_json(
            "GET", f"{self.cfg.base_url}/api/workbenches/{subject}/objects/{oid}", timeout=8
        )
        updated = ((obj.get("data") or {}).get("updated_at") or "") if obj.get("ok") else ""
        if not updated:
            return None
        try:
            ts = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
            now = datetime.now(ts.tzinfo) if ts.tzinfo else datetime.utcnow()
            return max(0.0, (now - ts).total_seconds() / 60.0)
        except (ValueError, TypeError):
            return None

    # --------------------------------------------------------------- report

    def write_status(self, snapshot: dict[str, Any]) -> Path:
        p = snapshot.get("probe", {})
        wd = snapshot.get("watchdog") or {}
        flags = snapshot.get("relevance_flags") or []
        alerts = wd.get("alerts") or []
        status = snapshot.get("status", STATUS_HEALTHY)
        usage = snapshot.get("usage") or {}

        icon = {
            STATUS_HEALTHY: "OK",
            STATUS_DEGRADED: "DEGRADED",
            STATUS_RECOVERED: "RECOVERED",
            STATUS_ESCALATED: "ESCALATED - NEEDS YOU",
        }.get(status, status.upper())

        lines = [
            f"# REFALL supervisor — {self.subject}",
            "",
            f"updated: {iso_now()}    mode: {snapshot.get('mode')}    status: **{icon}**",
            "",
            "## Infrastructure",
            "",
            f"- REFALL AB: {'up' if p.get('refall_ab_ok') else 'DOWN'}",
            f"- Agent Canvas: {'up' if p.get('canvas_ok') else 'DOWN'} (container: {p.get('canvas_container')})",
            f"- Standing loop: {'running ' + str(p.get('loop_pids')) if p.get('loop_alive') else 'NOT RUNNING'}",
            "",
            "## Agents",
            "",
            (
                f"- active: {snapshot.get('active_count', 0)}"
                + (f"  (as of {snapshot['active_count_as_of']}, last full pass)"
                   if snapshot.get("active_count_as_of") else "")
            ),
        ]
        if usage:
            lines.append(f"- tokens: {usage.get('tokens', 'n/a')}    cost: {usage.get('cost_usd', 'n/a')}")
        if flags:
            lines += ["", "### Off-track agents", ""]
            for f in flags:
                lines.append(f"- `{f['cid']}` lane {f.get('lane')} — {f['reason']} ({f['idle_ticks']} ticks)")

        intel_flags = snapshot.get("intel_flow_flags") or []
        if intel_flags:
            lines += ["", "## Tag → ledger → report flow", ""]
            for f in intel_flags:
                lines.append(f"- **{f.get('kind')}** ({f.get('subject')}): {f.get('message')}")
        if alerts:
            lines += ["", "## Watchdog alerts", ""]
            for a in alerts[:10]:
                issue = a.get("issue", {}) if isinstance(a, dict) else {}
                lines.append(f"- {issue.get('reason')} (severity {issue.get('severity')}) cid={issue.get('cid')}")

        wish = (wd.get("wishlist") or {}) if isinstance(wd, dict) else {}
        if wish:
            lines += ["", "## Wishlist", "", f"- open: {wish.get('open_count', 0)}    installed this pass: {wish.get('installed_count', 0)}"]

        recent = self.recent_recoveries()
        lines += [
            "",
            "## Recoveries",
            "",
            f"- last {self.cfg.recover_window_s // 60}m: {len(recent)} / {self.cfg.recover_max} before escalation",
        ]
        for r in recent:
            lines.append(f"  - {r.get('iso')} {','.join(r.get('reasons') or [])} -> {','.join(r.get('actions') or [])}")

        if snapshot.get("actions"):
            lines += ["", "## Actions taken this tick", ""] + [f"- {a}" for a in snapshot["actions"]]

        needs = snapshot.get("needs_operator")
        lines += ["", "## Needs you", "", (f"**YES** — {needs}" if needs else "no")]
        lines.append("")
        self.paths["status"].write_text("\n".join(lines), encoding="utf-8")
        return self.paths["status"]

    # ----------------------------------------------------------------- tick

    def tick(self, mode: str = "full") -> dict[str, Any]:
        snapshot: dict[str, Any] = {
            "mode": mode,
            "subject": self.subject,
            "ts": iso_now(),
            "actions": [],
            "status": STATUS_HEALTHY,
        }

        if self.hold_active():
            snapshot["status"] = STATUS_ESCALATED
            snapshot["needs_operator"] = (
                f"supervisor is holding; clear {self.paths['hold']} after fixing the fault"
            )
            snapshot["probe"] = {}
            self.write_status(snapshot)
            append_jsonl(self.paths["audit"], snapshot)
            return snapshot

        probe = self.probe()
        snapshot["probe"] = probe

        degraded = not (probe["refall_ab_ok"] and probe["canvas_ok"])
        if degraded:
            snapshot["status"] = STATUS_DEGRADED
            result = self.recover(probe)
            snapshot["actions"] += result["actions"]
            if result["recovered"]:
                snapshot["status"] = STATUS_RECOVERED
            escalation = self.check_escalation()
            if escalation:
                snapshot["status"] = STATUS_ESCALATED
                snapshot["escalation"] = escalation
                snapshot["needs_operator"] = (
                    f"{len(escalation['history'])} recoveries within "
                    f"{self.cfg.recover_window_s // 60}m — loop stopped, supervisor holding"
                )
                self.write_status(snapshot)
                append_jsonl(self.paths["audit"], snapshot)
                return snapshot

        if mode == "full":
            try:
                wd = self._watchdog_factory().run_once()
            except Exception as exc:  # a watchdog failure must not stop supervision
                wd = {"error": str(exc)[:300]}
                self._log(f"status=watchdog_error error={str(exc)[:200]}")
            snapshot["watchdog"] = wd
            agents = watchdog_active_agents(wd)
            count = wd.get("active_count")
            snapshot["active_count"] = int(count) if isinstance(count, int) else len(agents)
            if agents:
                snapshot["relevance_flags"] = self.check_relevance(agents)
            # Tag -> ledger -> report pipeline health (agents emitting tags,
            # tagged intel landing in the ledger/report). Runs even at 0 agents
            # so it can also catch a stale report while work is idle.
            try:
                snapshot["intel_flow_flags"] = self.check_intel_flow(snapshot, agents)
            except Exception as exc:
                snapshot["intel_flow_flags"] = []
                self._log(f"status=intel_flow_error error={str(exc)[:200]}")
            state = self._state()
            state["last_agents"] = {"count": snapshot["active_count"], "iso": iso_now()}
            self._save_state(state)
            if wd.get("alerts") and snapshot["status"] == STATUS_HEALTHY:
                snapshot["status"] = STATUS_DEGRADED
            if snapshot.get("intel_flow_flags") and snapshot["status"] == STATUS_HEALTHY:
                snapshot["status"] = STATUS_DEGRADED
        else:
            # A fast tick does not enumerate agents. Carry the last full-tick
            # count forward instead of reporting 0, which would read as "all
            # agents died" on every minute between full passes.
            last = self._state().get("last_agents") or {}
            if last:
                snapshot["active_count"] = last.get("count", 0)
                snapshot["active_count_as_of"] = last.get("iso")

        if probe.get("loop_alive") is False and snapshot["status"] == STATUS_HEALTHY:
            snapshot["status"] = STATUS_HEALTHY
            snapshot["note"] = "no standing loop running (idle)"

        self.write_status(snapshot)
        append_jsonl(self.paths["audit"], snapshot)
        return snapshot


# ------------------------------------------------------------------- cron

def render_cron_entries(
    *,
    repo_root: Path | str,
    subject: str,
    base_url: str = DEFAULT_BASE_URL,
    oh_base: str = DEFAULT_OH_BASE,
    fast_minutes: int = 1,
    full_minutes: int = 3,
) -> list[str]:
    root = str(Path(repo_root).expanduser())
    script = f"{root}/deploy/cron/refall-supervisor.sh"
    fast = "* * * * *" if fast_minutes <= 1 else f"*/{fast_minutes} * * * *"
    # Keep each line SHORT. macOS crontab truncates long entries, and a truncated
    # line loses its trailing "# MARKER" -- which makes the entry both broken and
    # unremovable by marker, so uninstall silently succeeds while the cron keeps
    # firing. Configuration therefore goes in a sidecar env file that the wrapper
    # sources, not inline on the crontab line.
    return [
        f"{fast} {script} fast {subject} # {CRON_MARKER_FAST}_{subject.upper()}",
        f"*/{full_minutes} * * * * {script} full {subject} # {CRON_MARKER_FULL}_{subject.upper()}",
    ]


def write_env_file(
    *,
    repo_root: Path | str,
    subject: str,
    base_url: str = DEFAULT_BASE_URL,
    oh_base: str = DEFAULT_OH_BASE,
) -> Path:
    """Sidecar config the cron wrapper sources, keeping crontab lines short."""
    root = Path(repo_root).expanduser()
    path = root / "logs" / f"refall-supervisor-{subject}.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"REFALL_REPO_ROOT={root}\n"
        f"REFALL_PUBLIC_BASE_URL={base_url}\n"
        f"REFALL_WORKBENCH_BASE={base_url}\n"
        f"REFALL_OPENHANDS_BASE={oh_base}\n"
        f"REFALL_SUPERVISOR_SUBJECT={subject}\n",
        encoding="utf-8",
    )
    return path


def _is_supervisor_line(line: str, subject: str) -> bool:
    """True for this subject's supervisor entries, marker present or not.

    Truncated entries lose their trailing marker, so the script path is matched
    as a second anchor. Without it a truncated line survives every uninstall.
    """
    tags = (f"{CRON_MARKER_FAST}_{subject.upper()}", f"{CRON_MARKER_FULL}_{subject.upper()}")
    if any(tag in line for tag in tags):
        return True
    return "refall-supervisor.sh" in line and (
        f" {subject} " in line or line.rstrip().endswith(f" {subject}")
    )


def merge_crontab(existing: str, entries: list[str], *, subject: str) -> str:
    """Replace this subject's supervisor lines, leaving every other line alone."""
    keep = [
        line.rstrip()
        for line in existing.splitlines()
        if line.strip() and not _is_supervisor_line(line, subject)
    ]
    keep.extend(entry.rstrip() for entry in entries)
    return "\n".join(keep) + "\n"


def remove_from_crontab(existing: str, *, subject: str) -> str:
    keep = [
        l.rstrip() for l in existing.splitlines()
        if l.strip() and not _is_supervisor_line(l, subject)
    ]
    return ("\n".join(keep) + "\n") if keep else ""


def _read_crontab() -> str:
    rc, out = _run(["crontab", "-l"], 20)
    return out if rc == 0 else ""


def _write_crontab(content: str) -> tuple[bool, str]:
    # crontab(1) truncates long paths, so stage in a short one.
    tmp = Path("/tmp/refall-supervisor-crontab")
    tmp.write_text(content, encoding="utf-8")
    rc, out = _run(["crontab", str(tmp)], 20)
    tmp.unlink(missing_ok=True)
    return rc == 0, out


def install_cron(
    *,
    repo_root: Path | str,
    subject: str,
    base_url: str = DEFAULT_BASE_URL,
    oh_base: str = DEFAULT_OH_BASE,
    fast_minutes: int = 1,
    full_minutes: int = 3,
    dry_run: bool = False,
) -> dict[str, Any]:
    entries = render_cron_entries(
        repo_root=repo_root, subject=subject, base_url=base_url, oh_base=oh_base,
        fast_minutes=fast_minutes, full_minutes=full_minutes,
    )
    write_env_file(repo_root=repo_root, subject=subject, base_url=base_url, oh_base=oh_base)
    merged = merge_crontab(_read_crontab(), entries, subject=subject)
    if dry_run:
        return {"installed": False, "dry_run": True, "entries": entries}
    ok, out = _write_crontab(merged)
    return {"installed": ok, "entries": entries, "error": None if ok else out}


def uninstall_cron(*, subject: str, dry_run: bool = False) -> dict[str, Any]:
    merged = remove_from_crontab(_read_crontab(), subject=subject)
    if dry_run:
        return {"removed": False, "dry_run": True}
    ok, out = _write_crontab(merged)
    return {"removed": ok, "error": None if ok else out}


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="refall-supervisor")
    parser.add_argument("mode", nargs="?", default="full", choices=["fast", "full"])
    parser.add_argument("--subject", default=os.environ.get("REFALL_SUPERVISOR_SUBJECT", "all"))
    parser.add_argument("--repo-root", default=DEFAULT_REPO_ROOT)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--oh-base", default=DEFAULT_OH_BASE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    cfg = SupervisorConfig(
        subject=args.subject,
        repo_root=Path(args.repo_root),
        base_url=args.base_url,
        oh_base=args.oh_base,
        dry_run=args.dry_run,
    )
    snapshot = RefallSupervisor(cfg).tick(args.mode)
    print(json.dumps(snapshot, indent=2, default=str))
    return 0 if snapshot.get("status") != STATUS_ESCALATED else 2


if __name__ == "__main__":
    raise SystemExit(main())
