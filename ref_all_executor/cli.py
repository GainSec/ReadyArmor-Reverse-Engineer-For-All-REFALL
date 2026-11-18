import argparse
import json
import os
import sys
from pathlib import Path

from .auto_client import AutoClient
from .arcticbase_client import ArcticBaseClient
from .cleanup import RefallCleanup
from .doctor import doctor
from .estimate import estimate_subject
from .infra import RefallInfra
from .loop_manager import RefallLoopManager
from .prompts import build_prompt
from .report_draft import draft_report
from .report_enrich import enrich_workbench_report
from .watchdog import install_cron as install_watchdog_cron
from .watchdog import run_watchdog_subjects
from .context_fingerprint import fingerprint_directory
from . import config


def _parse_process_patterns(values):
    if not values:
        return None
    out = {}
    for raw in values or []:
        if "=" not in raw:
            raise SystemExit(f"--process-pattern must be name=regex, got {raw!r}")
        name, pattern = raw.split("=", 1)
        out[name.strip()] = pattern.strip()
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    p = argparse.ArgumentParser(prog="ref_all_executor")
    sub = p.add_subparsers(dest="cmd", required=True)

    cp = sub.add_parser("create-prompt")
    cp.add_argument("--target", required=True)
    cp.add_argument("--name", default="refall-research-loop")
    cp.add_argument("--model", default=None)
    cp.add_argument("--cron", default="0 3 * * *")  # daily 03:00; dispatch manually meanwhile
    cp.add_argument("--repo", default=None, help="optional git RepoSource url")

    for name in ("dispatch", "runs", "get", "delete"):
        sp = sub.add_parser(name)
        sp.add_argument("id")
    sub.add_parser("list")
    down = sub.add_parser("down")
    down.add_argument("--dry-run", action="store_true")
    down.add_argument("--include-serena", action="store_true")
    down.add_argument("--port", action="append", type=int, dest="ports")
    down.add_argument("--container-pattern", action="append", dest="container_patterns")
    down.add_argument("--process-pattern", action="append", dest="process_patterns",
                      help="extra process target as name=regex")
    infra = sub.add_parser("infra")
    infra.add_argument("action", choices=("status", "up", "down", "restart"))
    infra.add_argument("--dry-run", action="store_true")
    infra.add_argument("--include-serena", action="store_true", default=True)

    subject = sub.add_parser("subject")
    subject_sub = subject.add_subparsers(dest="subject_cmd", required=True)
    subject_create = subject_sub.add_parser("create")
    subject_create.add_argument("name")
    subject_create.add_argument("--source-path", default=None)
    subject_create.add_argument("--title", default=None)
    subject_create.add_argument("--description", default="")
    subject_create.add_argument("--tag", action="append", dest="tags", default=[])
    subject_sub.add_parser("list")
    subject_mirror = subject_sub.add_parser("mirror")
    subject_mirror.add_argument("name")

    loop = sub.add_parser("loop")
    loop_sub = loop.add_subparsers(dest="loop_cmd", required=True)
    for action in ("start", "update", "closeout"):
        sp = loop_sub.add_parser(action)
        sp.add_argument("name")

    ops = sub.add_parser("ops")
    ops_sub = ops.add_subparsers(dest="ops_cmd", required=True)
    ops_sub.add_parser("status")
    ops_command = ops_sub.add_parser("command")
    ops_command.add_argument("parts", nargs="+")

    report = sub.add_parser("report")
    report_sub = report.add_subparsers(dest="report_cmd", required=True)
    report_draft = report_sub.add_parser("draft")
    report_draft.add_argument("name")
    report_draft.add_argument("--allow-structural-downgrade", action="store_true")
    report_enrich = report_sub.add_parser("enrich")
    report_enrich.add_argument("name")
    report_enrich.add_argument("--allow-structural-downgrade", action="store_true")

    doctor_parser = sub.add_parser("doctor")
    doctor_parser.add_argument("--subject", default=None)
    doctor_parser.add_argument("--no-network", action="store_true")
    estimate = sub.add_parser("estimate")
    estimate.add_argument("subject")

    fingerprint = sub.add_parser("context-fingerprint")
    fingerprint.add_argument("root")
    fingerprint.add_argument("--no-binwalk", action="store_true")

    watchdog = sub.add_parser("watchdog")
    watchdog_sub = watchdog.add_subparsers(dest="watchdog_cmd", required=True)
    watchdog_run = watchdog_sub.add_parser("run")
    watchdog_run.add_argument("--subject", default="all")
    watchdog_run.add_argument("--repo-root", default=None)
    watchdog_run.add_argument("--base-url", default=None)
    watchdog_run.add_argument("--oh-base", default=None)
    watchdog_run.add_argument("--dry-run", action="store_true")
    watchdog_install = watchdog_sub.add_parser("install-cron")
    watchdog_install.add_argument("--subject", default="all")
    watchdog_install.add_argument("--repo-root", default=None)
    watchdog_install.add_argument("--base-url", default=None)
    watchdog_install.add_argument("--oh-base", default=None)
    watchdog_install.add_argument("--interval-minutes", type=int, default=5)

    args = p.parse_args(argv)

    if args.cmd == "down":
        out = RefallCleanup().run(
            dry_run=args.dry_run,
            include_serena=args.include_serena,
            ports=args.ports,
            container_patterns=args.container_patterns,
            extra_process_patterns=_parse_process_patterns(args.process_patterns),
        )
        print(json.dumps(out, indent=2))
        return 0
    if args.cmd == "infra":
        manager = RefallInfra()
        if args.action == "status":
            out = manager.status()
        elif args.action == "up":
            out = manager.up(dry_run=args.dry_run)
        elif args.action == "down":
            out = manager.down(dry_run=args.dry_run, include_serena=args.include_serena)
        elif args.action == "restart":
            out = manager.restart(dry_run=args.dry_run, include_serena=args.include_serena)
        else:
            return 2
        print(json.dumps(out, indent=2))
        return 0
    if args.cmd == "subject":
        ab = ArcticBaseClient()
        if args.subject_cmd == "create":
            out = ab.create_subject(
                args.name,
                source_path=args.source_path,
                title=args.title,
                description=args.description,
                tags=args.tags,
            )
        elif args.subject_cmd == "list":
            out = ab.list_subjects()
        elif args.subject_cmd == "mirror":
            out = ab.mirror_subject(args.name)
        else:
            return 2
        print(json.dumps(out, indent=2))
        return 0
    if args.cmd == "loop":
        manager = RefallLoopManager()
        if args.loop_cmd == "start":
            out = manager.start(args.name)
        elif args.loop_cmd == "update":
            out = manager.update(args.name)
        elif args.loop_cmd == "closeout":
            out = manager.closeout(args.name)
        else:
            return 2
        print(json.dumps(out, indent=2))
        return 0
    if args.cmd == "ops":
        ab = ArcticBaseClient()
        if args.ops_cmd == "status":
            out = ab.ops_status()
        elif args.ops_cmd == "command":
            out = ab.ops_command(" ".join(args.parts))
        else:
            return 2
        print(json.dumps(out, indent=2))
        return 0
    if args.cmd == "report":
        if args.report_cmd == "draft":
            kwargs = (
                {"allow_structural_downgrade": True}
                if args.allow_structural_downgrade
                else {}
            )
            out = draft_report(args.name, args.name, **kwargs)
        elif args.report_cmd == "enrich":
            kwargs = (
                {"allow_structural_downgrade": True}
                if args.allow_structural_downgrade
                else {}
            )
            out = enrich_workbench_report(args.name, args.name, **kwargs)
        else:
            return 2
        print(json.dumps(out, indent=2))
        return 0
    if args.cmd == "doctor":
        out = doctor(subject=args.subject, check_network=not args.no_network)
        print(json.dumps(out, indent=2))
        return 0
    if args.cmd == "estimate":
        out = estimate_subject(args.subject)
        print(json.dumps(out, indent=2))
        return 0
    if args.cmd == "context-fingerprint":
        out = fingerprint_directory(args.root, run_binwalk=not args.no_binwalk)
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0
    if args.cmd == "watchdog":
        repo_root = Path(args.repo_root or os.environ.get("REFALL_REPO_ROOT", Path(__file__).resolve().parents[1]))
        base_url = args.base_url or config.WB_BASE
        oh_base = args.oh_base or config.OH_BASE
        if args.watchdog_cmd == "install-cron":
            out = install_watchdog_cron(
                repo_root=repo_root,
                interval_minutes=args.interval_minutes,
                subject=args.subject,
                base_url=base_url,
                oh_base=oh_base,
            )
        elif args.watchdog_cmd == "run":
            samples = run_watchdog_subjects(
                subject=args.subject,
                repo_root=repo_root,
                base_url=base_url,
                oh_base=oh_base,
                log_path=None,
                jsonl_path=None,
                state_path=None,
                dry_run=args.dry_run,
            )
            out = {
                "subjects_checked": [sample["subject"] for sample in samples],
                "active_count": sum(int(sample["active_count"]) for sample in samples),
                "issues": [issue for sample in samples for issue in sample["issues"]],
                "stops": [stop for sample in samples for stop in sample["stops"]],
            }
        else:
            return 2
        print(json.dumps(out, indent=2, sort_keys=True, default=str))
        return 0

    ac = AutoClient()

    if args.cmd == "create-prompt":
        prompt = build_prompt(args.target, config.WB_BASE, config.WB_SLUG)
        repos = [{"url": args.repo}] if args.repo else None
        out = ac.create_prompt_automation(
            name=args.name, prompt=prompt, trigger=ac.cron(args.cron),
            model=args.model, keep_alive=False, repos=repos)
        print(json.dumps(out, indent=2))
        return 0
    if args.cmd == "dispatch":
        print(json.dumps(ac.dispatch(args.id), indent=2))
        return 0
    if args.cmd == "runs":
        print(json.dumps(ac.list_runs(args.id), indent=2))
        return 0
    if args.cmd == "get":
        print(json.dumps(ac.get_automation(args.id), indent=2))
        return 0
    if args.cmd == "delete":
        ac.delete_automation(args.id)
        print("deleted", args.id)
        return 0
    if args.cmd == "list":
        print(json.dumps(ac.list_automations(), indent=2))
        return 0
    return 1
