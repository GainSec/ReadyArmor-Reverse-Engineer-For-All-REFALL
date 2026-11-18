import os
import asyncio
import json as _json
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from . import db as dbmod
from .store import Store
from .enumerate import build_units
from .dashboard import render

DB_PATH = os.environ.get("COVERAGE_DB", os.path.join(os.path.dirname(__file__), "data", "coverage.db"))
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
# Subjects live here on the host; each maps to /projects/<name> in the agent container.
SUBJECTS_ROOT = os.environ.get("COVERAGE_SUBJECTS_ROOT", os.path.expanduser("~/refallsub"))
_conn = dbmod.connect(DB_PATH)
dbmod.init_schema(_conn)
STORE = Store(_conn)

GLOBAL_LOOP_CAPABILITIES = [
    {
        "id": "saleae_logic_mcp",
        "class": "physical_capture",
        "name": "Saleae Logic MCP",
        "access": "Manager-mediated local MCP service when configured; not started or required by the base install.",
        "purpose": "Capture read-only hardware bus evidence from operator-placed probes when software work reaches UART/SPI/I2C/JTAG/test-pad validation.",
        "protocols": ["UART async serial", "SPI flash", "I2C", "JTAG/SWD candidate pads", "GPIO/reset/boot strap timing"],
        "operator_prompt": "Tell the operator exactly where to put the probes on the pads, then use the Logic MCP to capture and export traces.",
        "guardrails": [
            "Read-only capture only: do not drive pins, short pads, attach VCC, or change target wiring from the agent side.",
            "Ask the operator to identify ground and target voltage before capture; use appropriate logic-level thresholds.",
            "Do not assume a pinout; capture candidate pads and label confidence from observed traffic.",
            "Keep captures bounded and record sample rate, channel labels, trigger condition, and artifact path in findings or workbench updates.",
        ],
        "when_to_use": [
            "Software/network/static frontier is exhausted and the next evidence requires physical bus observation.",
            "A subject has visible test pads, UART boot console candidates, SPI/eMMC flash, I2C peripherals, or reset/boot timing questions.",
            "The worker can tell the manager/operator which pads/probes are needed and what trace would confirm the hypothesis.",
        ],
    },
    {
        "id": "glasgow_interface_explorer",
        "class": "physical_probe",
        "name": "Glasgow Interface Explorer",
        "access": "Manager-mediated local `glasgow` CLI when installed and explicitly enabled for a target.",
        "purpose": "High-impedance digital probing and protocol classification for unknown board headers, boot/download pads, UART/SPI/I2C/JTAG/SWD candidates, and flash-access experiments.",
        "known_devices": [
            {
                "serial": "operator-supplied",
                "hardware": "revC3",
                "observed_usb_name": "Glasgow Interface Explorer (git f050f518)",
                "firmware_note": "Record firmware/software version before use.",
            }
        ],
        "safe_actions": [
            "`glasgow list` to enumerate connected devices.",
            "`glasgow safe` before and after wiring to disable I/O drivers and voltage outputs.",
            "Passive/high-Z capture of unknown signal pins after target voltage is measured.",
            "Use analyzer or protocol-specific applets only after line voltage and idle state are known.",
        ],
        "guardrails": [
            "Never connect target VCC to Glasgow VIO/power rails until the target voltage is measured and the experiment explicitly requires it.",
            "Do not drive BOOT, WDOG, reset, flash, or download pads during first-pass classification.",
            "Power the target independently; use Glasgow GND plus signal inputs only for initial sniffing.",
            "If any target pad measures above 5 V, do not connect it to Glasgow I/O.",
            "Record physical pad order, Glasgow channel mapping, target voltage, outlet state, and capture artifact paths in findings or workbench notes.",
        ],
        "when_to_use": [
            "An unknown 4-pin/2-pin board header needs pin classification and no public pinout is available.",
            "A BGA SoC blocks direct pin access and the useful evidence is likely on factory/debug headers or test pads.",
            "The loop needs to distinguish UART, SPI, I2C, JTAG/SWD, reset/watchdog, boot strap, or inactive pads from observed line behavior.",
        ],
    },
    {
        "id": "autoprober_smart_powerstrip",
        "class": "power_control",
        "name": "Autoprober Smart Powerstrip",
        "access": "Manager-mediated only; do not select this as an analysis/source lane. Configure endpoint mapping per target before any power action.",
        "purpose": "Provide outlet-level power control for bounded hardware experiments, recovery cycles, and repeatable boot/UART/network observations.",
        "matter_node_id": 1,
        "device": "UseeLink Matter Smart Power Strip",
        "endpoints": {
            1: "Outlet 1",
            2: "Outlet 2",
            3: "Outlet 3",
            4: "Outlet 4",
            5: "USB ports",
        },
        "safe_actions": [
            "Read outlet state: `sudo chip-tool onoff read on-off 1 <endpoint>`.",
            "Turn an operator-approved endpoint on or off.",
            "Perform a bounded power-cycle with recorded off/on timing when reboot evidence is needed.",
        ],
        "recovery_notes": [
            "When the strip is missing from operational discovery, require operator recommissioning before any manager-mediated power action.",
            "Do not run multiple `chip-tool` commands concurrently; the snap controller storage can fail with `CHIP Error 0x000000AF: Write to file failed` under parallel access.",
        ],
        "operator_prompt": "Ask which physical device is connected to the outlet endpoint before switching it, unless the endpoint mapping is already confirmed in the current workbench or finding.",
        "guardrails": [
            "Use only for explicit task need or operator-approved power cycling; do not toggle outlets speculatively.",
            "Do not switch shared infrastructure, routers, manager hosts, storage, or unrelated lab gear unless the operator explicitly approves that endpoint.",
            "Record endpoint, requested state, timing, reason, and observed result in the finding or workbench update.",
            "Prefer read-state before and after switching; keep off intervals bounded and suitable for the target hardware.",
        ],
        "when_to_use": [
            "A loop needs repeatable cold-boot, UART interruption, DHCP, or network bring-up observations.",
            "A target is wedged and the next safe recovery step is an operator-approved power cycle.",
            "An experiment needs synchronized capture with Saleae, tcpdump, serial console, or service logs across a reboot.",
        ],
    }
]


def _list_subjects():
    """Directories under SUBJECTS_ROOT, annotated with what the service knows about each."""
    out = []
    try:
        names = sorted(d for d in os.listdir(SUBJECTS_ROOT)
                       if os.path.isdir(os.path.join(SUBJECTS_ROOT, d)) and not d.startswith("."))
    except OSError:
        names = []
    for name in names:
        ctx = STORE.get_context(name)
        out.append({"subject": name, "root_container": f"/projects/{name}",
                    "has_context": bool(ctx and ctx.get("info_md")),
                    "coverage": STORE.coverage(name).get("lines_total", 0),
                    "plan": STORE.plan_progress(name)["total"],
                    "findings": STORE.findings_summary(name)["total"]})
    return out

app = FastAPI(title="REF-All Coverage Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class EnumReq(BaseModel):
    subject: str
    files: list


class ClaimReq(BaseModel):
    subject: str
    agent: str
    lease_s: int = 900


class SubmitReq(BaseModel):
    unit_id: str
    agent: str
    summary: str = ""
    sensitivity: Optional[str] = None
    data_touched: object = None
    flows_in: Optional[list] = None
    flows_out: Optional[list] = None
    leads: Optional[list] = None
    evidence: list = []


@app.post("/enumerate")
def enumerate_ep(r: EnumReq):
    n = STORE.upsert_units(build_units(r.subject, r.files))
    return {"subject": r.subject, "units": n}


class SurfaceReq(BaseModel):
    subject: str
    dimension: str            # e.g. "unicode-catalog", "native-tools", "file-type-handlers"
    items: List[str]          # every enumerable target on the surface
    covered: List[str] = []   # the subset actually probed/covered


@app.post("/surface")
def surface_ep(r: SurfaceReq):
    """Register a non-code coverage surface so behavioral/cartography subjects report real coverage %.
    Subloops with no source-line surface call this at seed time and as items are covered."""
    return STORE.set_surface(r.subject, r.dimension, r.items, r.covered)


@app.post("/claim_next")
def claim_ep(r: ClaimReq):
    u = STORE.claim_next(r.subject, r.agent, r.lease_s)
    if not u:
        raise HTTPException(404, "no open units")
    return u


@app.post("/submit")
def submit_ep(r: SubmitReq):
    try:
        return STORE.submit(r.unit_id, r.agent, r.summary, r.sensitivity, r.data_touched,
                            r.flows_in, r.flows_out, r.leads, r.evidence)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/release")
def release_ep(unit_id: str):
    STORE.release(unit_id)
    return {"ok": True}


@app.post("/mark_dead")
def dead_ep(r: SubmitReq):
    try:
        return STORE.mark_dead(r.unit_id, r.agent, r.evidence)
    except ValueError as e:
        raise HTTPException(422, str(e))


class FindingReq(BaseModel):
    finding: dict


class ReviewReq(BaseModel):
    finding_id: str
    agent: str
    status: str
    reasoning: Optional[str] = None
    repro_hints: Optional[str] = None
    pass_number: int = 1
    stage: str = "reviewer"


class FindingValidationReq(BaseModel):
    finding_id: str
    agent: str
    production_viability: Optional[str] = None
    repro_status: Optional[str] = None
    repro_hints: Optional[str] = None
    critic_reasoning: Optional[str] = None
    patch_status: Optional[str] = None
    pass_number: int = 1


class PlanReq(BaseModel):
    subject: str
    investigations: list
    pass_number: int = 1
    replace: bool = True


class ClaimInvReq(BaseModel):
    subject: str
    agent: str
    lease_s: int = 1800


class CompleteInvReq(BaseModel):
    investigation_id: str
    agent: str


@app.post("/finding")
def finding_ep(r: FindingReq):
    try:
        return STORE.add_finding(r.finding)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/review_finding")
def review_finding_ep(r: ReviewReq):
    try:
        return STORE.review_finding(r.finding_id, r.agent, r.status, r.reasoning,
                                    r.repro_hints, r.pass_number, r.stage)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/finding_validation")
def finding_validation_ep(r: FindingValidationReq):
    try:
        return STORE.update_finding_validation(
            r.finding_id, r.agent, r.production_viability, r.repro_status,
            r.repro_hints, r.critic_reasoning, r.patch_status, r.pass_number,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/loop/capabilities")
def loop_capabilities_ep(subject: str = ""):
    return {
        "subject": subject,
        "workflow": [
            "inspect_finding",
            "create_or_improve_script",
            "run_host_action",
            "capture_raw_output",
            "record_validation_or_demote",
        ],
        "global_capabilities": GLOBAL_LOOP_CAPABILITIES,
        "host_actions": [],
    }


@app.get("/findings")
def findings_ep(subject: str, status: Optional[str] = None, priority: Optional[str] = None,
                severity: Optional[str] = None):
    return STORE.list_findings(subject, status, priority, severity)


@app.get("/finding/{finding_id}")
def finding_get_ep(finding_id: str):
    f = STORE.get_finding(finding_id)
    if not f:
        raise HTTPException(404, "not found")
    return f


@app.get("/findings_summary")
def findings_summary_ep(subject: str):
    return STORE.findings_summary(subject)


@app.post("/plan")
def plan_ep(r: PlanReq):
    n = STORE.put_plan(r.subject, r.investigations, r.pass_number, r.replace)
    return {"subject": r.subject, "investigations": n}


@app.post("/claim_investigation")
def claim_inv_ep(r: ClaimInvReq):
    inv = STORE.claim_investigation(r.subject, r.agent, r.lease_s)
    if not inv:
        raise HTTPException(404, "no open investigations")
    return inv


@app.post("/complete_investigation")
def complete_inv_ep(r: CompleteInvReq):
    STORE.complete_investigation(r.investigation_id, r.agent)
    return {"ok": True}


@app.get("/investigations")
def investigations_ep(subject: str, state: Optional[str] = None):
    return STORE.list_investigations(subject, state)


@app.get("/plan_progress")
def plan_progress_ep(subject: str):
    return STORE.plan_progress(subject)


class ContextReq(BaseModel):
    subject: str
    info_md: str
    generated_by: Optional[str] = None
    root_container: Optional[str] = None


class WishReq(BaseModel):
    subject: str
    item: str
    kind: Optional[str] = None
    reason: Optional[str] = None
    requested_by: Optional[str] = None


class WishResolveReq(BaseModel):
    id: str
    status: str


class ClassCovReq(BaseModel):
    subject: str
    vuln_class: str
    state: str
    checked_by: Optional[str] = None
    notes: Optional[str] = None


@app.get("/subjects")
def subjects_ep():
    return _list_subjects()


class GenContextReq(BaseModel):
    subject: str


@app.post("/generate_context")
def generate_context_ep(r: GenContextReq):
    """Launch the context writer (one agent) in the background; it POSTs /context when done."""
    import subprocess
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        subprocess.Popen(["python3", "drive_context.py", "--subject", r.subject],
                         cwd=repo, env={**os.environ, "PYTHONPATH": repo},
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        raise HTTPException(500, f"could not launch context writer: {e}")
    return {"launched": True, "subject": r.subject}


@app.get("/context")
def get_context_ep(subject: str):
    ctx = STORE.get_context(subject)
    return ctx or {"subject": subject, "info_md": None}


@app.post("/context")
def set_context_ep(r: ContextReq):
    return STORE.set_context(r.subject, r.info_md, r.generated_by, r.root_container)


@app.post("/wishlist")
def add_wish_ep(r: WishReq):
    try:
        return STORE.add_wish(r.subject, r.item, r.kind, r.reason, r.requested_by)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/wishlist")
def list_wish_ep(subject: str, status: Optional[str] = None):
    return STORE.list_wishes(subject, status)


@app.post("/wishlist_resolve")
def resolve_wish_ep(r: WishResolveReq):
    return STORE.resolve_wish(r.id, r.status)


@app.get("/funnel")
def funnel_ep(subject: str):
    return STORE.funnel(subject)


@app.get("/attack_patterns")
def attack_patterns_ep(vuln_class: Optional[str] = None):
    return STORE.list_attack_patterns(vuln_class)


@app.get("/class_coverage")
def class_coverage_ep(subject: str):
    return STORE.class_coverage(subject)


@app.post("/class_coverage")
def set_class_coverage_ep(r: ClassCovReq):
    STORE.set_class_coverage(r.subject, r.vuln_class, r.state, r.checked_by, r.notes)
    return {"ok": True}


@app.get("/coverage")
def coverage_ep(subject: str):
    return STORE.coverage(subject)


@app.get("/gate")
def gate_ep(subject: str, threshold: float = 0.95):
    return STORE.gate(subject, threshold)


@app.get("/search")
def search_ep(subject: str, type: Optional[str] = None, state: Optional[str] = None,
              sensitivity: Optional[str] = None, path: Optional[str] = None, q: Optional[str] = None):
    return STORE.search(subject, type, state, sensitivity, path, q)


@app.get("/unit/{unit_id}")
def unit_ep(unit_id: str):
    u = STORE.get_unit(unit_id)
    if not u:
        raise HTTPException(404, "not found")
    return u


@app.get("/", response_class=HTMLResponse)
def dashboard_ep():
    return render()


@app.get("/events")
async def events_ep(subject: str = "bra"):
    async def gen():
        last = None
        while True:
            cov = STORE.coverage(subject)
            cur = (cov["lines_covered"], cov["files_done"])
            if cur != last:
                last = cur
                yield f"data: {_json.dumps(cov)}\n\n"
            await asyncio.sleep(2)
    return StreamingResponse(gen(), media_type="text/event-stream")
