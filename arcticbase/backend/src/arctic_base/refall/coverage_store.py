from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from arctic_base.refall import coverage_db
from arctic_base.refall.contracts import ScopeOverlay, SourceInventoryPackage, ThreatModelPackage
from arctic_base.refall.promotion_gates import evaluate_finding_candidate
from arctic_base.storage.filesystem import FilesystemStorage


def _now() -> float:
    return time.time()


def _json(value: object) -> str:
    return json.dumps(value if value is not None else [])


def _load_json(value: object, default: object = None) -> object:
    if value in (None, ""):
        return [] if default is None else default
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return [] if default is None else default


FINDING_STATUSES = {
    "PROVISIONALLY_VALID",
    "NEEDS_RESEARCH",
    "VALID",
    "FALSE_POSITIVE",
    "DUPLICATE",
    "CHAINABLE_DEFERRED",
}
CREATABLE_FINDING_STATUSES = {"PROVISIONALLY_VALID", "NEEDS_RESEARCH"}
QUALITY_ORDER = {"HYPOTHESIS": 0, "CODE_CONFIRMED": 1, "LIVE_CONFIRMED": 2}
SUPPRESSIVE_STATUSES = {"FALSE_POSITIVE", "DUPLICATE", "CHAINABLE_DEFERRED"}
REPRO_PENDING_STATUSES = {"not_attempted", "static_only", "runtime_blocked", "runtime_viable"}
TRANSITION_PENDING_BLOCKERS = {
    "live_validation_pending",
    "repro_stabilization",
    "trigger_path_enumeration",
    "ingress_enumeration",
    "native_surface_validation",
    "parser_family_sweep",
    "sibling_sweep_required",
}
EVENT_PENDING_RULES = {
    "repro_unstable": {
        "kind": "repro_stabilization",
        "title": "Stabilize runtime reproduction",
        "priority": "high",
        "required_receipt_type": "live_repro",
        "assigned_lane": "dynamic-validation",
    },
    "new_sink_reached": {
        "kind": "ingress_enumeration",
        "title": "Enumerate ingress for newly reached sink",
        "priority": "high",
        "required_receipt_type": "code_anchor",
        "assigned_lane": "source-analysis",
    },
    "confirmed_parser_bug": {
        "kind": "parser_family_sweep",
        "title": "Sweep parser family for siblings",
        "priority": "high",
        "required_receipt_type": "code_anchor",
        "assigned_lane": "source-analysis",
    },
    "confirmed_memory_bug": {
        "kind": "sibling_sweep_required",
        "title": "Sweep sibling memory primitives",
        "priority": "high",
        "required_receipt_type": "code_anchor",
        "assigned_lane": "source-analysis",
    },
    "native_fidelity_gap_detected": {
        "kind": "native_surface_validation",
        "title": "Validate native surface fidelity gap",
        "priority": "high",
        "required_receipt_type": "live_repro",
        "assigned_lane": "dynamic-validation",
    },
}


def _now_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _receipt_has_evidence(receipt: object) -> bool:
    if not isinstance(receipt, dict):
        return False
    for key in ("evidence_refs", "source_anchors", "artifact_refs", "commands", "negative_tests"):
        value = receipt.get(key)
        if isinstance(value, list) and value:
            return True
        if isinstance(value, str) and value.strip():
            return True
    return False


def _receipt_stale_reasons(receipt: object, source_root: object) -> list[str]:
    if not isinstance(receipt, dict):
        return []
    hashes: dict[str, object] = {}
    for key in ("source_hashes", "source_anchor_hashes", "file_hashes", "config_hashes"):
        value = receipt.get(key)
        if isinstance(value, dict):
            hashes.update(value)
    if not hashes:
        return []
    if not source_root:
        return ["stale evidence check requires recorded source root"]
    try:
        root = Path(str(source_root)).expanduser().resolve()
    except OSError:
        return ["stale evidence check source root is not resolvable"]
    reasons: list[str] = []
    for anchor, expected_hash in hashes.items():
        expected = _normalize_sha256(expected_hash)
        rel_path = _source_anchor_path(str(anchor))
        if not expected or not rel_path:
            reasons.append(f"stale evidence receipt has unusable source hash for {anchor}")
            continue
        try:
            candidate = (root / rel_path).resolve()
            candidate.relative_to(root)
        except (OSError, ValueError):
            reasons.append(f"stale evidence source anchor escapes source root: {anchor}")
            continue
        if not candidate.is_file():
            reasons.append(f"stale evidence source anchor is missing: {anchor}")
            continue
        actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if actual.lower() != expected:
            reasons.append(f"stale evidence source hash mismatch: {anchor}")
    return reasons


def _normalize_sha256(value: object) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text.split(":", 1)[1]
    if len(text) == 64 and all(ch in "0123456789abcdef" for ch in text):
        return text
    return ""


def _source_anchor_path(anchor: str) -> str:
    text = anchor.strip()
    if not text:
        return ""
    if "::" in text:
        text = text.split("::", 1)[0]
    match = re.match(r"^(.*?):\d+(?::\d+)?$", text)
    if match:
        text = match.group(1)
    text = text.lstrip("/")
    if not text or text.startswith("../") or "/../" in f"/{text}":
        return ""
    return text


def _receipt_summary(receipt_type: str | None, receipt: object) -> dict:
    return {
        "receipt_type": receipt_type,
        "receipt": receipt if isinstance(receipt, dict) else {},
    }


def _finding_has_visual_or_proof_artifact(finding: dict) -> bool:
    haystack = " ".join(
        json.dumps(finding.get(key) or "", sort_keys=True).lower()
        for key in ("history", "code_paths", "repro_hints", "reproduction_steps", "critic_reasoning")
    )
    return any(
        marker in haystack
        for marker in ("visual", "diagram", "screenshot", "codebadger", "codecharta", "artifact_refs", "obj_")
    )


def _pending_identity(subject: str, data: dict) -> str:
    source_parts = [
        str(data.get("source_finding_id") or ""),
        str(data.get("source_unit_id") or ""),
        str(data.get("source_event_id") or ""),
    ]
    parts = [
        subject,
        str(data.get("kind") or ""),
        *source_parts,
    ]
    if not any(source_parts):
        parts.append(str(data.get("title") or ""))
    return hashlib.sha1("|".join(parts).encode()).hexdigest()


def _scope_list(scope: dict, key: str) -> list:
    value = scope.get(key)
    return value if isinstance(value, list) else []


def _path_in_scope(path: str, allowed: list) -> bool:
    if not path or not allowed:
        return False
    target = Path(path).expanduser()
    for raw in allowed:
        base = Path(str(raw)).expanduser()
        try:
            target.resolve().relative_to(base.resolve())
            return True
        except (OSError, ValueError):
            if str(target).startswith(str(base).rstrip("/") + "/") or str(target) == str(base):
                return True
    return False


def unit_id(
    subject: str,
    kind: str,
    path: str | None,
    line_start: int | None,
    line_end: int | None,
    name: str = "",
) -> str:
    key = f"{subject}|{kind}|{path}|{line_start}|{line_end}|{name}"
    return hashlib.sha1(key.encode()).hexdigest()


def partition_file(total_lines: int, symbols: list[dict]) -> list[dict]:
    syms = sorted(
        (s for s in symbols if int(s["line_start"]) <= int(s["line_end"])),
        key=lambda s: int(s["line_start"]),
    )
    leaves: list[dict] = []
    cursor = 1
    for symbol in syms:
        ls = max(1, int(symbol["line_start"]))
        le = min(total_lines, int(symbol["line_end"]))
        if le < cursor:
            continue
        ls = max(ls, cursor)
        if ls > cursor:
            leaves.append({"type": "line_range", "line_start": cursor, "line_end": ls - 1, "name": ""})
        leaves.append({
            "type": "symbol",
            "line_start": ls,
            "line_end": le,
            "name": str(symbol.get("name") or ""),
        })
        cursor = le + 1
    if cursor <= total_lines:
        leaves.append({"type": "line_range", "line_start": cursor, "line_end": total_lines, "name": ""})
    return leaves


def build_units(subject: str, files: list[dict]) -> list[dict]:
    subj_id = unit_id(subject, "subject", None, None, None)
    units = [{
        "id": subj_id,
        "subject": subject,
        "type": "subject",
        "path": None,
        "line_start": None,
        "line_end": None,
        "parent_id": None,
        "total_lines": None,
        "indexed_src": "enumerate",
        "name": subject,
    }]
    for source_file in files:
        path = str(source_file["path"])
        total_lines = int(source_file["total_lines"])
        file_id = unit_id(subject, "file", path, None, None)
        units.append({
            "id": file_id,
            "subject": subject,
            "type": "file",
            "path": path,
            "line_start": 1,
            "line_end": total_lines,
            "parent_id": subj_id,
            "total_lines": total_lines,
            "indexed_src": "enumerate",
            "name": path,
        })
        for leaf in partition_file(total_lines, source_file.get("symbols", [])):
            leaf_id = unit_id(
                subject,
                leaf["type"],
                path,
                leaf["line_start"],
                leaf["line_end"],
                leaf["name"],
            )
            units.append({
                "id": leaf_id,
                "subject": subject,
                "type": leaf["type"],
                "path": path,
                "name": leaf["name"],
                "line_start": leaf["line_start"],
                "line_end": leaf["line_end"],
                "parent_id": file_id,
                "total_lines": leaf["line_end"] - leaf["line_start"] + 1,
                "indexed_src": source_file.get("src", "enumerate"),
            })
    return units


def coverage_db_path(storage: FilesystemStorage, slug: str) -> Path:
    storage.get_workbench(slug)
    return storage.root / "workbenches" / slug / "refall_coverage.db"


def store_for_workbench(storage: FilesystemStorage, slug: str) -> "CoverageStore":
    conn = coverage_db.connect(coverage_db_path(storage, slug))
    coverage_db.init_schema(conn)
    return CoverageStore(conn)


class CoverageStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._wlock = threading.Lock()

    def upsert_units(self, units: list[dict]) -> int:
        cols = [
            "id",
            "subject",
            "type",
            "path",
            "name",
            "line_start",
            "line_end",
            "parent_id",
            "total_lines",
            "indexed_src",
        ]
        with self._wlock:
            for unit in units:
                self.conn.execute(
                    f"INSERT INTO units({','.join(cols)},indexed,updated_at) "
                    f"VALUES({','.join('?' for _ in cols)},1,?) "
                    "ON CONFLICT(id) DO UPDATE SET indexed=1, indexed_src=excluded.indexed_src, "
                    "updated_at=excluded.updated_at",
                    [unit.get(c) for c in cols] + [_now()],
                )
            self.conn.commit()
        return len(units)

    def set_surface(self, subject: str, dimension: str, items: list[str], covered: list[str] | None = None) -> dict:
        covered_set = {str(item) for item in (covered or [])}
        now = _now()
        with self._wlock:
            for index, name in enumerate(items):
                uid = f"{subject}::surface::{dimension}::{index}"
                state = "characterized" if str(name) in covered_set else "open"
                self.conn.execute(
                    "INSERT INTO units(id,subject,type,path,name,line_start,line_end,total_lines,"
                    "indexed,indexed_src,state,characterized_by,updated_at) "
                    "VALUES(?,?,'symbol',?,?,?,?,1,1,'surface',?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET state=excluded.state, "
                    "characterized_by=excluded.characterized_by, updated_at=excluded.updated_at",
                    (
                        uid,
                        subject,
                        f"surface/{dimension}",
                        str(name)[:200],
                        index + 1,
                        index + 1,
                        state,
                        "subloop" if state == "characterized" else None,
                        now,
                    ),
                )
            self.conn.commit()
        return {"dimension": dimension, "items": len(items), "covered": len(covered_set)}

    def claim_next(self, subject: str, agent: str, lease_s: int = 900) -> dict | None:
        with self._wlock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                row = self.conn.execute(
                    "SELECT * FROM units WHERE subject=? AND type IN ('symbol','line_range') "
                    "AND (state='open' OR (state='claimed' AND lease_expires < ?)) "
                    "ORDER BY (type='symbol') DESC, path, line_start LIMIT 1",
                    (subject, _now()),
                ).fetchone()
                if not row:
                    self.conn.execute("ROLLBACK")
                    return None
                self.conn.execute(
                    "UPDATE units SET state='claimed', claimed_by=?, lease_expires=? WHERE id=?",
                    (agent, _now() + lease_s, row["id"]),
                )
                self.conn.execute("COMMIT")
                return dict(row)
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def submit(
        self,
        unit_id: str,
        agent: str,
        summary: str,
        evidence: list[dict],
        sensitivity: str | None = None,
        data_touched: object = None,
        flows_in: list | None = None,
        flows_out: list | None = None,
        leads: list | None = None,
    ) -> dict:
        evidence = list(evidence or [])
        if not evidence or not all(item.get("file") for item in evidence):
            raise ValueError("submit requires >=1 evidence anchor with a file")
        return self._resolve(
            unit_id,
            agent,
            "characterized",
            summary,
            sensitivity,
            data_touched,
            flows_in,
            flows_out,
            leads,
            evidence,
        )

    def mark_dead(self, unit_id: str, agent: str, evidence: list[dict]) -> dict:
        evidence = list(evidence or [])
        if not evidence or not all(item.get("file") for item in evidence):
            raise ValueError("mark_dead requires evidence")
        return self._resolve(unit_id, agent, "dead", "dead code", None, None, None, None, None, evidence)

    def _resolve(
        self,
        unit_id: str,
        agent: str,
        state: str,
        summary: str,
        sensitivity: str | None,
        data_touched: object,
        flows_in: list | None,
        flows_out: list | None,
        leads: list | None,
        evidence: list[dict],
    ) -> dict:
        with self._wlock:
            self.conn.execute(
                "UPDATE units SET state=?, summary=?, sensitivity=?, data_touched=?, flows_in=?, "
                "flows_out=?, leads=?, characterized_by=?, claimed_by=NULL, lease_expires=NULL, updated_at=? "
                "WHERE id=?",
                (
                    state,
                    summary,
                    sensitivity,
                    json.dumps(data_touched),
                    json.dumps(flows_in),
                    json.dumps(flows_out),
                    json.dumps(leads),
                    agent,
                    _now(),
                    unit_id,
                ),
            )
            for item in evidence:
                self.conn.execute(
                    "INSERT INTO evidence(unit_id,file,line_start,line_end,snippet,kind) VALUES(?,?,?,?,?,?)",
                    (
                        unit_id,
                        item["file"],
                        item.get("line_start"),
                        item.get("line_end"),
                        item.get("snippet"),
                        item.get("kind", "proof"),
                    ),
                )
            self.conn.commit()
        unit = self.get_unit(unit_id)
        if unit is None:
            raise ValueError("no such unit")
        return unit

    def release(self, unit_id: str) -> None:
        with self._wlock:
            self.conn.execute(
                "UPDATE units SET state='open', claimed_by=NULL, lease_expires=NULL WHERE id=?",
                (unit_id,),
            )
            self.conn.commit()

    def coverage(self, subject: str) -> dict:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(total_lines),0) total, "
            "COALESCE(SUM(CASE WHEN state IN('characterized','dead') THEN total_lines END),0) resolved, "
            "COALESCE(SUM(CASE WHEN state='characterized' THEN total_lines END),0) chars, "
            "COALESCE(SUM(CASE WHEN state='dead' THEN total_lines END),0) dead "
            "FROM units WHERE subject=? AND type IN('symbol','line_range')",
            (subject,),
        ).fetchone()
        files = self.conn.execute(
            "SELECT COUNT(*) FROM units WHERE subject=? AND type='file'",
            (subject,),
        ).fetchone()[0]
        done = self.conn.execute(
            "SELECT COUNT(*) FROM units f WHERE f.subject=? AND f.type='file' AND NOT EXISTS "
            "(SELECT 1 FROM units c WHERE c.parent_id=f.id AND c.state NOT IN('characterized','dead'))",
            (subject,),
        ).fetchone()[0]
        total = row["total"] or 0

        def pct(value: int) -> float:
            return round(100.0 * value / total, 1) if total else 0.0

        return {
            "subject": subject,
            "lines_total": total,
            "lines_covered": row["resolved"],
            "lines_dead": row["dead"],
            "indexed_pct": 100.0 if total else 0.0,
            "characterized_pct": pct(row["chars"]),
            "resolved_pct": pct(row["resolved"]),
            "files_total": files,
            "files_done": done,
            "symbols_total": self.conn.execute(
                "SELECT COUNT(*) FROM units WHERE subject=? AND type='symbol'",
                (subject,),
            ).fetchone()[0],
        }

    def gate(self, subject: str, threshold: float = 0.95) -> dict:
        coverage = self.coverage(subject)
        resolved = coverage["resolved_pct"] / 100.0
        return {
            "subject": subject,
            "resolved_pct": coverage["resolved_pct"],
            "threshold": threshold * 100,
            "locked": resolved < threshold,
            "phase": "research" if resolved >= threshold else "discovery",
        }

    def search(
        self,
        subject: str,
        type: str | None = None,
        state: str | None = None,
        sensitivity: str | None = None,
        path: str | None = None,
        q: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        sql = "SELECT id,type,path,name,line_start,line_end,state,sensitivity,summary FROM units WHERE subject=?"
        args: list[object] = [subject]
        for col, val in (("type", type), ("state", state), ("sensitivity", sensitivity)):
            if val:
                sql += f" AND {col}=?"
                args.append(val)
        if path:
            sql += " AND path LIKE ?"
            args.append(f"%{path}%")
        if q:
            sql += " AND (name LIKE ? OR summary LIKE ?)"
            args.extend([f"%{q}%", f"%{q}%"])
        sql += " ORDER BY updated_at DESC LIMIT ?"
        args.append(limit)
        return [dict(row) for row in self.conn.execute(sql, args)]

    def get_unit(self, unit_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM units WHERE id=?", (unit_id,)).fetchone()
        if not row:
            return None
        unit = dict(row)
        unit["evidence"] = [
            dict(item)
            for item in self.conn.execute(
                "SELECT file,line_start,line_end,snippet,kind FROM evidence WHERE unit_id=?",
                (unit_id,),
            )
        ]
        return unit

    def put_plan(self, subject: str, investigations: list[dict], pass_number: int = 1, replace: bool = True) -> int:
        now = _now()
        with self._wlock:
            if replace:
                self.conn.execute("DELETE FROM investigations WHERE subject=? AND state='open'", (subject,))
            count = 0
            for investigation in investigations:
                self.conn.execute(
                    "INSERT INTO investigations(id,subject,pass_number,title,target_files,"
                    "kb_references,question,priority,kind,parent_id,state,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,'open',?,?)",
                    (
                        investigation.get("id") or uuid.uuid4().hex,
                        subject,
                        pass_number,
                        investigation.get("title"),
                        json.dumps(investigation.get("target_files") or []),
                        json.dumps(investigation.get("kb_references") or []),
                        investigation.get("question"),
                        investigation.get("priority", 100),
                        investigation.get("kind"),
                        investigation.get("parent_id"),
                        now,
                        now,
                    ),
                )
                count += 1
            self.conn.commit()
        return count

    def plan_progress(self, subject: str) -> dict:
        rows = {
            row[0]: row[1]
            for row in self.conn.execute(
                "SELECT state, COUNT(*) FROM investigations WHERE subject=? GROUP BY state",
                (subject,),
            )
        }
        total = sum(rows.values())
        return {
            "subject": subject,
            "total": total,
            "open": rows.get("open", 0),
            "claimed": rows.get("claimed", 0),
            "done": rows.get("done", 0),
        }

    def set_context(
        self,
        subject: str,
        info_md: str,
        generated_by: str | None = None,
        root_container: str | None = None,
    ) -> dict:
        with self._wlock:
            self.conn.execute(
                "INSERT INTO subject_meta(subject,info_md,root_container,updated_at,generated_by) "
                "VALUES(?,?,?,?,?) ON CONFLICT(subject) DO UPDATE SET info_md=excluded.info_md, "
                "root_container=COALESCE(excluded.root_container,root_container), "
                "updated_at=excluded.updated_at, generated_by=excluded.generated_by",
                (subject, info_md, root_container, _now(), generated_by),
            )
            self.conn.commit()
        return self.get_context(subject) or {"subject": subject, "info_md": info_md}

    def get_context(self, subject: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM subject_meta WHERE subject=?", (subject,)).fetchone()
        return dict(row) if row else None

    def put_source_inventory(self, subject: str, inventory: dict) -> dict:
        payload = dict(inventory or {})
        payload["subject"] = subject
        contract = SourceInventoryPackage(**payload).model_dump(mode="json")
        now = _now()
        with self._wlock:
            self.conn.execute(
                "INSERT INTO source_inventories(id,subject,root,payload,created_at) "
                "VALUES(?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (
                    contract["inventory_id"],
                    subject,
                    contract["root"],
                    json.dumps(contract, sort_keys=True),
                    now,
                ),
            )
            self.conn.commit()
        return contract

    def get_latest_source_inventory(self, subject: str) -> dict | None:
        row = self.conn.execute(
            "SELECT payload FROM source_inventories WHERE subject=? ORDER BY created_at DESC LIMIT 1",
            (subject,),
        ).fetchone()
        if not row:
            return None
        return _load_json(row["payload"], {})

    def set_scope_overlay(self, subject: str, payload: dict, updated_by: str | None = None) -> dict:
        data = dict(payload or {})
        data["subject"] = subject
        contract = ScopeOverlay(**data).model_dump(mode="json")
        with self._wlock:
            self.conn.execute(
                "INSERT INTO scope_overlays(subject,payload,updated_by,updated_at) "
                "VALUES(?,?,?,?) "
                "ON CONFLICT(subject) DO UPDATE SET payload=excluded.payload, "
                "updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                (subject, json.dumps(contract, sort_keys=True), updated_by, _now()),
            )
            self.conn.commit()
        return contract

    def get_scope_overlay(self, subject: str) -> dict | None:
        row = self.conn.execute("SELECT payload FROM scope_overlays WHERE subject=?", (subject,)).fetchone()
        if not row:
            return None
        return _load_json(row["payload"], {})

    def put_threat_model(self, subject: str, payload: dict, created_by: str | None = None) -> dict:
        data = dict(payload or {})
        data["subject"] = subject
        if created_by and not data.get("created_by"):
            data["created_by"] = created_by
        contract = ThreatModelPackage(**data).model_dump(mode="json")
        now = _now()
        with self._wlock:
            self.conn.execute(
                "INSERT INTO threat_models(id,subject,payload,status,created_by,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, status=excluded.status, "
                "created_by=COALESCE(excluded.created_by,created_by), updated_at=excluded.updated_at",
                (
                    contract["threat_model_id"],
                    subject,
                    json.dumps(contract, sort_keys=True),
                    contract.get("status") or "active",
                    contract.get("created_by"),
                    now,
                    now,
                ),
            )
            self.conn.commit()
        return contract

    def get_latest_threat_model(self, subject: str) -> dict | None:
        row = self.conn.execute(
            "SELECT payload FROM threat_models WHERE subject=? ORDER BY updated_at DESC LIMIT 1",
            (subject,),
        ).fetchone()
        if not row:
            return None
        return _load_json(row["payload"], {})

    def add_finding(self, subject: str, data: dict) -> dict:
        now = _now()
        finding_id = str(data.get("id") or f"find_{uuid.uuid4().hex}")
        code_paths = data.get("code_paths") or []
        status = str(data.get("status") or "PROVISIONALLY_VALID")
        quality_tier = str(data.get("quality_tier") or "HYPOTHESIS")
        if not data.get("title"):
            raise ValueError("finding requires title")
        if not code_paths:
            raise ValueError("finding requires code_paths")
        if status not in FINDING_STATUSES:
            raise ValueError(f"bad status {status}")
        if status not in CREATABLE_FINDING_STATUSES:
            raise ValueError(f"status {status} requires disposition transition")
        if quality_tier not in QUALITY_ORDER:
            raise ValueError(f"bad quality_tier {quality_tier}")
        gate_context = self._promotion_gate_context(subject)
        gate = evaluate_finding_candidate(
            data,
            source_inventory=gate_context.get("source_inventory"),
            scope_overlay=gate_context.get("scope_overlay"),
        )
        if not gate["accepted"]:
            raise ValueError("finding promotion refused: " + "; ".join(gate["reasons"]))
        existing = self.get_finding(finding_id)
        if existing is not None:
            if existing.get("subject") != subject:
                raise ValueError("finding id already belongs to another subject")
            merged_payload = _merge_finding_payload(existing, data)
            merged_locations = _merge_related_locations(
                existing.get("related_locations") or [],
                _related_locations_from_finding(data),
            )
            merged_payload["related_locations"] = merged_locations
            with self._wlock:
                self.conn.execute(
                    "UPDATE findings SET code_paths=?, repro_hints=?, related_locations=?, "
                    "constituent_findings=?, history=?, payload=?, updated_at=? WHERE id=?",
                    (
                        _json(merged_payload.get("code_paths") or []),
                        _json(merged_payload.get("repro_hints") or merged_payload.get("reproduction_steps") or []),
                        _json(merged_locations),
                        _json(merged_payload.get("constituent_findings") or []),
                        _json(merged_payload.get("history") or []),
                        _json(merged_payload),
                        now,
                        finding_id,
                    ),
                )
                self.conn.commit()
            return self.get_finding(finding_id) or existing
        dedup_key = str(data.get("dedup_key") or _finding_dedup_key(subject, data))
        related_locations = _related_locations_from_finding(data)
        canonical = self._find_canonical_finding(subject, dedup_key) if dedup_key else None
        if canonical is not None:
            merged_locations = _merge_related_locations(canonical.get("related_locations") or [], related_locations)
            merged_code_paths = _merge_string_lists(canonical.get("code_paths") or [], data.get("code_paths") or [])
            merged_repro_hints = _merge_string_lists(
                canonical.get("repro_hints") or [],
                data.get("repro_hints") or data.get("reproduction_steps") or [],
            )
            merged_history = _merge_json_lists(canonical.get("history") or [], data.get("history") or [])
            constituents = _merge_string_lists(
                canonical.get("constituent_findings") or [],
                data.get("constituent_findings") or ([finding_id] if data.get("id") else []),
            )
            merged_payload = _merge_finding_payload(canonical, data)
            merged_payload.update({
                "id": canonical["id"],
                "canonical_finding_id": canonical["id"],
                "code_paths": merged_code_paths,
                "repro_hints": merged_repro_hints,
                "related_locations": merged_locations,
                "constituent_findings": constituents,
                "history": merged_history,
            })
            with self._wlock:
                self.conn.execute(
                    "UPDATE findings SET code_paths=?, repro_hints=?, related_locations=?, "
                    "constituent_findings=?, history=?, payload=?, updated_at=? WHERE id=?",
                    (
                        _json(merged_code_paths),
                        _json(merged_repro_hints),
                        _json(merged_locations),
                        _json(constituents),
                        _json(merged_history),
                        _json(merged_payload),
                        now,
                        canonical["id"],
                    ),
                )
                self.conn.commit()
            updated = self.get_finding(canonical["id"])
            if updated is None:
                raise ValueError("canonical finding was not stored")
            return updated
        with self._wlock:
            self.conn.execute(
                "INSERT INTO findings(id,subject,title,description,impact,severity,"
                "privileges_required,attacker_position,user_interaction,status,"
                "quality_tier,production_viability,repro_status,patch_status,code_paths,mitigation,"
                "reasoning,repro_hints,critic_reasoning,vuln_class,source_unit_id,"
                "investigation_id,pass_number,impact_score,likelihood_score,mantis_risk_score,"
                "priority,inferred_exposure,availability_tier,duplicate_of,constituent_findings,"
                "dedup_key,canonical_finding_id,related_locations,history,payload,created_by,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    finding_id,
                    subject,
                    data.get("title"),
                    data.get("description"),
                    data.get("impact"),
                    data.get("severity"),
                    data.get("privileges_required"),
                    data.get("attacker_position"),
                    data.get("user_interaction"),
                    status,
                    quality_tier,
                    data.get("production_viability"),
                    data.get("repro_status", "not_attempted"),
                    data.get("patch_status"),
                    _json(code_paths),
                    data.get("mitigation") or data.get("remediation"),
                    data.get("reasoning"),
                    _json(data.get("repro_hints") or data.get("reproduction_steps") or []),
                    data.get("critic_reasoning"),
                    data.get("vuln_class"),
                    data.get("source_unit_id"),
                    data.get("investigation_id"),
                    int(data.get("pass_number", 1)),
                    data.get("impact_score"),
                    data.get("likelihood_score"),
                    data.get("mantis_risk_score"),
                    data.get("priority"),
                    data.get("inferred_exposure"),
                    data.get("availability_tier"),
                    data.get("duplicate_of"),
                    _json(data.get("constituent_findings") or []),
                    dedup_key,
                    finding_id,
                    _json(related_locations),
                    _json(data.get("history") or []),
                    _json({
                        **data,
                        "id": finding_id,
                        "subject": subject,
                        "dedup_key": dedup_key,
                        "canonical_finding_id": finding_id,
                        "related_locations": related_locations,
                    }),
                    data.get("created_by"),
                    now,
                    now,
                ),
            )
            self.conn.commit()
        found = self.get_finding(finding_id)
        if found is None:
            raise ValueError("finding was not stored")
        return found

    def _find_canonical_finding(self, subject: str, dedup_key: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM findings WHERE subject=? AND dedup_key=? "
            "AND (canonical_finding_id IS NULL OR canonical_finding_id=id) "
            "ORDER BY created_at ASC LIMIT 1",
            (subject, dedup_key),
        ).fetchone()
        return _finding_row(row) if row else None

    def _promotion_gate_context(self, subject: str) -> dict:
        context: dict[str, dict] = {}
        source_inventory = self.get_latest_source_inventory(subject)
        if source_inventory:
            context["source_inventory"] = source_inventory
        scope_overlay = self.get_scope_overlay(subject)
        if scope_overlay:
            context["scope_overlay"] = scope_overlay
        return context

    def get_finding(self, finding_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM findings WHERE id=?", (finding_id,)).fetchone()
        return _finding_row(row) if row else None

    def list_findings(
        self,
        subject: str,
        *,
        status: str | None = None,
        severity: str | None = None,
        vuln_class: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        sql = "SELECT * FROM findings WHERE subject=?"
        args: list[object] = [subject]
        for col, val in (("status", status), ("severity", severity), ("vuln_class", vuln_class)):
            if val:
                sql += f" AND {col}=?"
                args.append(val)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        args.append(limit)
        return [_finding_row(row) for row in self.conn.execute(sql, args)]

    def findings_summary(self, subject: str) -> dict:
        rows = self.list_findings(subject, limit=10000)
        by_status: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        by_class: dict[str, int] = {}
        for row in rows:
            for key, bucket in (
                ("status", by_status),
                ("severity", by_severity),
                ("vuln_class", by_class),
            ):
                value = row.get(key)
                if value:
                    bucket[str(value)] = bucket.get(str(value), 0) + 1
        return {
            "subject": subject,
            "total": len(rows),
            "by_status": by_status,
            "by_severity": by_severity,
            "by_class": by_class,
        }

    def update_finding_validation(self, finding_id: str, agent: str, fields: dict) -> dict:
        current = self.get_finding(finding_id)
        if current is None:
            raise ValueError("no such finding")
        if fields.get("status") is not None:
            raise ValueError("finding status changes must use disposition transitions")
        allowed = {
            "production_viability",
            "repro_status",
            "patch_status",
            "critic_reasoning",
        }
        updates = {key: value for key, value in fields.items() if key in allowed and value is not None}
        history = {
            "agent": agent,
            "ts": _now(),
            "fields": updates,
        }
        history_items = list(current.get("history") or [])
        history_items.append(history)
        updates["history"] = _json(history_items)
        updates["updated_at"] = _now()
        assignments = ", ".join(f"{key}=?" for key in updates)
        with self._wlock:
            self.conn.execute(
                f"UPDATE findings SET {assignments} WHERE id=?",
                list(updates.values()) + [finding_id],
            )
            self.conn.commit()
        updated = self.get_finding(finding_id)
        if updated is None:
            raise ValueError("no such finding")
        return updated

    def transition_finding(self, subject: str, finding_id: str, data: dict) -> dict:
        current = self.get_finding(finding_id)
        if current is None or current.get("subject") != subject:
            raise ValueError("no such finding")
        from_status = str(data.get("from_status") or current.get("status") or "")
        to_status = str(data.get("to_status") or current.get("status") or "")
        from_quality = str(data.get("from_quality") or current.get("quality_tier") or "HYPOTHESIS")
        to_quality = str(data.get("to_quality") or from_quality)
        receipt_type = data.get("receipt_type")
        receipt = data.get("receipt") or {}
        duplicate_of = data.get("duplicate_of")
        reasons: list[str] = []

        if from_status and from_status != current.get("status"):
            reasons.append("from_status does not match current state")
        if from_status and from_status not in FINDING_STATUSES:
            reasons.append(f"bad from_status {from_status}")
        if to_status not in FINDING_STATUSES:
            reasons.append(f"bad status {to_status}")
        if from_quality not in QUALITY_ORDER:
            reasons.append(f"bad from_quality {from_quality}")
        if to_quality not in QUALITY_ORDER:
            reasons.append(f"bad to_quality {to_quality}")

        quality_reduced = QUALITY_ORDER.get(to_quality, 0) < QUALITY_ORDER.get(from_quality, 0)
        quality_increased = QUALITY_ORDER.get(to_quality, 0) > QUALITY_ORDER.get(from_quality, 0)
        suppressive = to_status in SUPPRESSIVE_STATUSES or quality_reduced or bool(data.get("severity_reduction"))
        if suppressive and not receipt_type:
            reasons.append("suppressive transition requires receipt_type")
        if suppressive and not _receipt_has_evidence(receipt):
            reasons.append("suppressive transition requires receipt evidence refs or anchors")
        reasons.extend(_receipt_stale_reasons(receipt, data.get("_source_root")))
        if suppressive:
            pending_blockers = [
                action for action in self.list_pending_actions(subject, include_terminal=False)
                if action.get("source_finding_id") == finding_id
                and action.get("kind") in TRANSITION_PENDING_BLOCKERS
            ]
            if pending_blockers:
                reasons.append(
                    "transition contradicts unresolved pending action: "
                    + ", ".join(str(action.get("id")) for action in pending_blockers)
                )
        if to_status == "DUPLICATE" and not duplicate_of:
            reasons.append("DUPLICATE transition requires duplicate_of")
        if to_status == "FALSE_POSITIVE" and receipt_type not in {
            "non_reachability_proof",
            "scope_boundary",
            "operator_override",
        }:
            reasons.append("FALSE_POSITIVE transition requires non-reachability, scope, or override receipt")
        if to_status == "CHAINABLE_DEFERRED" and receipt_type != "chain_preservation":
            reasons.append("CHAINABLE_DEFERRED transition requires chain preservation receipt")
        if quality_reduced and receipt_type != "downgrade_with_trigger_inventory":
            reasons.append("quality downgrade requires trigger inventory receipt")
        if to_status == "VALID":
            if receipt_type != "live_repro" or not _receipt_has_evidence(receipt):
                reasons.append("VALID transition requires positive validation live_repro receipt")
        if quality_increased:
            if to_quality == "LIVE_CONFIRMED" and receipt_type != "live_repro":
                reasons.append("LIVE_CONFIRMED quality requires live_repro receipt")
            elif to_quality == "CODE_CONFIRMED" and receipt_type not in {"code_anchor", "live_repro"}:
                reasons.append("CODE_CONFIRMED quality requires code_anchor or live_repro receipt")
            if not _receipt_has_evidence(receipt):
                reasons.append("quality increase requires receipt evidence refs or anchors")

        transition_id = _now_id("tr")
        status = "refused" if reasons else "accepted"
        now = _now()
        with self._wlock:
            self.conn.execute(
                "INSERT INTO finding_transitions(id,subject,finding_id,from_status,to_status,"
                "from_quality,to_quality,proposed_by,reason,receipt_type,receipt,duplicate_of,"
                "status,refusal_reasons,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    transition_id,
                    subject,
                    finding_id,
                    from_status,
                    to_status,
                    from_quality,
                    to_quality,
                    data.get("proposed_by"),
                    data.get("reason"),
                    receipt_type,
                    json.dumps(receipt),
                    duplicate_of,
                    status,
                    json.dumps(reasons),
                    now,
                ),
            )
            if not reasons:
                history_items = list(current.get("history") or [])
                history_items.append({
                    "type": "disposition-transition",
                    "transition_id": transition_id,
                    "from_status": from_status,
                    "to_status": to_status,
                    "from_quality": from_quality,
                    "to_quality": to_quality,
                    "receipt_type": receipt_type,
                    "ts": now,
                })
                self.conn.execute(
                    "UPDATE findings SET status=?, quality_tier=?, duplicate_of=COALESCE(?,duplicate_of),"
                    "history=?,updated_at=? WHERE id=?",
                    (to_status, to_quality, duplicate_of, _json(history_items), now, finding_id),
                )
                if receipt_type:
                    self.conn.execute(
                        "INSERT INTO transition_receipts(id,transition_id,finding_id,subject,"
                        "receipt_type,receipt,created_at) VALUES(?,?,?,?,?,?,?)",
                        (
                            _now_id("rec"),
                            transition_id,
                            finding_id,
                            subject,
                            receipt_type,
                            json.dumps(receipt),
                            now,
                        ),
                    )
            self.conn.commit()
        out = self.get_transition(transition_id)
        if out is None:
            raise ValueError("transition was not stored")
        out["accepted"] = not reasons
        out["finding"] = self.get_finding(finding_id)
        return out

    def get_transition(self, transition_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM finding_transitions WHERE id=?", (transition_id,)).fetchone()
        return _transition_row(row) if row else None

    def list_transitions(
        self,
        subject: str,
        *,
        finding_id: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM finding_transitions WHERE subject=?"
        args: list[object] = [subject]
        if finding_id:
            sql += " AND finding_id=?"
            args.append(finding_id)
        if status:
            sql += " AND status=?"
            args.append(status)
        sql += " ORDER BY created_at DESC"
        return [_transition_row(row) for row in self.conn.execute(sql, args)]

    def create_pending_action(self, subject: str, data: dict) -> dict:
        now = _now()
        if not data.get("kind"):
            raise ValueError("pending action requires kind")
        if not data.get("title"):
            raise ValueError("pending action requires title")
        identity_key = data.get("identity_key") or _pending_identity(subject, data)
        action_id = str(data.get("id") or _now_id("pa"))
        with self._wlock:
            self.conn.execute(
                "INSERT INTO pending_actions(id,subject,identity_key,kind,title,description,status,"
                "priority,source_event_id,source_finding_id,source_unit_id,required_receipt_type,"
                "assigned_lane,claimed_by,lease_expires,resolution_receipt,created_by,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(identity_key) DO UPDATE SET updated_at=excluded.updated_at",
                (
                    action_id,
                    subject,
                    identity_key,
                    data.get("kind"),
                    data.get("title"),
                    data.get("description"),
                    data.get("status", "open"),
                    data.get("priority", "medium"),
                    data.get("source_event_id"),
                    data.get("source_finding_id"),
                    data.get("source_unit_id"),
                    data.get("required_receipt_type"),
                    data.get("assigned_lane"),
                    data.get("claimed_by"),
                    data.get("lease_expires"),
                    json.dumps(data.get("resolution_receipt") or {}),
                    data.get("created_by", "refall"),
                    now,
                    now,
                ),
            )
            self.conn.commit()
        rows = self.list_pending_actions(subject, identity_key=identity_key, include_terminal=True)
        return rows[0]

    def list_pending_actions(
        self,
        subject: str,
        *,
        status: str | None = None,
        kind: str | None = None,
        identity_key: str | None = None,
        include_terminal: bool = True,
    ) -> list[dict]:
        sql = "SELECT * FROM pending_actions WHERE subject=?"
        args: list[object] = [subject]
        if status:
            sql += " AND status=?"
            args.append(status)
        elif not include_terminal:
            sql += " AND status NOT IN('done','deferred','cancelled')"
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        if identity_key:
            sql += " AND identity_key=?"
            args.append(identity_key)
        sql += " ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, updated_at DESC"
        return [_pending_row(row) for row in self.conn.execute(sql, args)]

    def get_pending_action(self, action_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM pending_actions WHERE id=?", (action_id,)).fetchone()
        return _pending_row(row) if row else None

    def claim_pending_action(self, subject: str, action_id: str, claimed_by: str, lease_s: int = 900) -> dict:
        action = self.get_pending_action(action_id)
        if action is None or action.get("subject") != subject:
            raise ValueError("no such pending action")
        with self._wlock:
            self.conn.execute(
                "UPDATE pending_actions SET status='claimed', claimed_by=?, lease_expires=?, updated_at=? WHERE id=?",
                (claimed_by, _now() + lease_s, _now(), action_id),
            )
            self.conn.commit()
        return self.get_pending_action(action_id) or action

    def finish_pending_action(
        self,
        subject: str,
        action_id: str,
        *,
        status: str,
        receipt_type: str | None,
        receipt: object,
        resolved_by: str | None = None,
    ) -> dict:
        action = self.get_pending_action(action_id)
        if action is None or action.get("subject") != subject:
            raise ValueError("no such pending action")
        if status not in {"done", "deferred", "cancelled"}:
            raise ValueError("invalid pending action terminal status")
        required = action.get("required_receipt_type")
        if required and (receipt_type != required or not _receipt_has_evidence(receipt)):
            raise ValueError(f"pending action requires {required} receipt")
        if status in {"deferred", "cancelled"} and not _receipt_has_evidence(receipt):
            raise ValueError(f"{status} pending action requires receipt")
        resolution = {
            "status": status,
            "resolved_by": resolved_by,
            **_receipt_summary(receipt_type, receipt),
            "resolved_at": _now(),
        }
        with self._wlock:
            self.conn.execute(
                "UPDATE pending_actions SET status=?, claimed_by=NULL, lease_expires=NULL,"
                "resolution_receipt=?, updated_at=? WHERE id=?",
                (status, json.dumps(resolution), _now(), action_id),
            )
            self.conn.commit()
        return self.get_pending_action(action_id) or action

    def trigger_pending_actions_for_finding(self, subject: str, finding: dict, fields: dict) -> list[dict]:
        created: list[dict] = []
        repro_status = str(fields.get("repro_status") or finding.get("repro_status") or "").strip()
        if repro_status in REPRO_PENDING_STATUSES:
            created.append(self.create_pending_action(subject, {
                "kind": "live_validation_pending",
                "title": f"Live validation pending for {finding.get('title') or finding.get('id')}",
                "source_finding_id": finding.get("id"),
                "source_unit_id": finding.get("source_unit_id"),
                "priority": "high" if str(finding.get("severity") or "").upper() in {"HIGH", "CRITICAL"} else "medium",
                "required_receipt_type": "live_repro",
                "assigned_lane": "dynamic-validation",
                "created_by": "refall-validation",
            }))
        if repro_status == "repro_unstable":
            created.append(self.create_pending_action(subject, {
                "kind": "repro_stabilization",
                "title": f"Stabilize reproduction for {finding.get('title') or finding.get('id')}",
                "source_finding_id": finding.get("id"),
                "source_unit_id": finding.get("source_unit_id"),
                "priority": "high",
                "required_receipt_type": "live_repro",
                "assigned_lane": "dynamic-validation",
                "created_by": "refall-validation",
            }))
        if (
            str(finding.get("severity") or "").upper() in {"HIGH", "CRITICAL"}
            and not _finding_has_visual_or_proof_artifact(finding)
        ):
            created.append(self.create_pending_action(subject, {
                "kind": "visual_evidence_needed",
                "title": f"Visual evidence needed for {finding.get('title') or finding.get('id')}",
                "source_finding_id": finding.get("id"),
                "source_unit_id": finding.get("source_unit_id"),
                "priority": "medium",
                "required_receipt_type": "visual_evidence",
                "assigned_lane": "doc-synthesis",
                "created_by": "refall-finding",
            }))
        return created

    def trigger_pending_actions_for_transition(self, subject: str, transition: dict) -> list[dict]:
        created: list[dict] = []
        finding_id = transition.get("finding_id")
        if transition.get("to_status") == "DUPLICATE" and transition.get("status") != "accepted":
            created.append(self.create_pending_action(subject, {
                "kind": "duplicate_equivalence_review",
                "title": f"Duplicate equivalence review for {finding_id}",
                "description": "; ".join(str(reason) for reason in transition.get("refusal_reasons") or []),
                "source_finding_id": finding_id,
                "priority": "high",
                "required_receipt_type": "duplicate_equivalence",
                "assigned_lane": "review",
                "created_by": "refall-disposition",
            }))
        elif transition.get("status") == "refused":
            created.append(self.create_pending_action(subject, {
                "kind": "operator_decision_needed",
                "title": f"Disposition transition refused for {finding_id}",
                "description": "; ".join(str(reason) for reason in transition.get("refusal_reasons") or []),
                "source_finding_id": finding_id,
                "priority": "high",
                "required_receipt_type": "manager_review",
                "assigned_lane": "review",
                "created_by": "refall-disposition",
            }))
        return created

    def trigger_pending_actions_for_runtime_event(self, subject: str, event: dict) -> list[dict]:
        rule = EVENT_PENDING_RULES.get(str(event.get("type") or ""))
        if not rule:
            return []
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        finding_id = payload.get("finding_id") or payload.get("source_finding_id")
        unit_id = event.get("task_id") or payload.get("unit_id") or payload.get("source_unit_id")
        title = str(payload.get("title") or payload.get("summary") or rule["title"])
        return [self.create_pending_action(subject, {
            "kind": rule["kind"],
            "title": title,
            "description": payload.get("description") or payload.get("summary") or "",
            "source_event_id": event.get("id"),
            "source_finding_id": finding_id,
            "source_unit_id": unit_id,
            "priority": rule["priority"],
            "required_receipt_type": rule["required_receipt_type"],
            "assigned_lane": rule["assigned_lane"],
            "created_by": "refall-runtime",
        })]

    def expired_claimed_units(self, subject: str) -> list[dict]:
        return [
            dict(row)
            for row in self.conn.execute(
                "SELECT id,path,name,claimed_by,lease_expires FROM units "
                "WHERE subject=? AND state='claimed' AND lease_expires < ?",
                (subject, _now()),
            )
        ]

    def grant_capability(self, subject: str, data: dict) -> dict:
        now = _now()
        grant_id = str(data.get("id") or _now_id("cap"))
        if not data.get("class"):
            raise ValueError("capability grant requires class")
        with self._wlock:
            self.conn.execute(
                "INSERT INTO capability_grants(id,subject,class,scope,granted_by,reason,expires_at,"
                "dry_run_required,destructive_token_required,revoked_at,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    grant_id,
                    subject,
                    data.get("class"),
                    json.dumps(data.get("scope") or {}),
                    data.get("granted_by"),
                    data.get("reason"),
                    data.get("expires_at"),
                    1 if data.get("dry_run_required") else 0,
                    1 if data.get("destructive_token_required") else 0,
                    None,
                    now,
                    now,
                ),
            )
            self.conn.commit()
        grant = self.get_capability_grant(grant_id)
        if grant is None:
            raise ValueError("capability grant was not stored")
        return grant

    def get_capability_grant(self, grant_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM capability_grants WHERE id=?", (grant_id,)).fetchone()
        return _capability_grant_row(row) if row else None

    def list_capability_grants(self, subject: str, *, include_revoked: bool = False) -> list[dict]:
        sql = "SELECT * FROM capability_grants WHERE subject=?"
        args: list[object] = [subject]
        if not include_revoked:
            sql += " AND revoked_at IS NULL"
        sql += " ORDER BY updated_at DESC"
        return [_capability_grant_row(row) for row in self.conn.execute(sql, args)]

    def request_capability(self, subject: str, data: dict) -> dict:
        now = _now()
        req_id = str(data.get("id") or _now_id("capreq"))
        if not data.get("class"):
            raise ValueError("capability request requires class")
        with self._wlock:
            self.conn.execute(
                "INSERT INTO capability_requests(id,subject,class,requested_by,reason,scope,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    req_id,
                    subject,
                    data.get("class"),
                    data.get("requested_by"),
                    data.get("reason"),
                    json.dumps(data.get("scope") or {}),
                    data.get("status", "open"),
                    now,
                    now,
                ),
            )
            self.conn.commit()
        row = self.conn.execute("SELECT * FROM capability_requests WHERE id=?", (req_id,)).fetchone()
        return _capability_request_row(row)

    def revoke_capability(self, subject: str, grant_id: str) -> dict:
        grant = self.get_capability_grant(grant_id)
        if grant is None or grant.get("subject") != subject:
            raise ValueError("no such capability grant")
        now = _now()
        with self._wlock:
            self.conn.execute(
                "UPDATE capability_grants SET revoked_at=?, updated_at=? WHERE id=?",
                (now, now, grant_id),
            )
            self.conn.commit()
        return self.get_capability_grant(grant_id) or grant

    def authorize_execution(self, subject: str, request: dict) -> dict:
        capability_class = str(request.get("capability_class") or request.get("class") or "")
        declared_effects = request.get("declared_effects") or []
        reasons: list[str] = []
        if not capability_class:
            reasons.append("missing capability_class")
        if not declared_effects:
            reasons.append("request omits declared effects")
        grants = [
            grant for grant in self.list_capability_grants(subject)
            if grant.get("class") == capability_class and not _grant_expired(grant)
        ]
        matched: dict | None = None
        for grant in grants:
            grant_reasons = _grant_refusal_reasons(grant, request)
            if not grant_reasons:
                matched = grant
                break
        if not matched:
            reasons.append("no matching unexpired grant for requested scope")
            if grants:
                reasons.extend(_grant_refusal_reasons(grants[0], request))
        accepted = not reasons
        return {
            "subject": subject,
            "accepted": accepted,
            "status": "accepted" if accepted else "refused",
            "grant_id": matched.get("id") if matched else None,
            "refusal_reasons": sorted(set(reasons)),
            "request": request,
        }

    def add_wishlist_item(self, subject: str, data: dict) -> dict:
        now = _now()
        if not data.get("item"):
            raise ValueError("wishlist item required")
        item_id = str(data.get("id") or f"wish_{uuid.uuid4().hex}")
        with self._wlock:
            self.conn.execute(
                "INSERT INTO wishlist(id,subject,kind,item,reason,requested_by,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    item_id,
                    subject,
                    data.get("kind"),
                    data.get("item"),
                    data.get("reason"),
                    data.get("requested_by"),
                    data.get("status", "open"),
                    now,
                    now,
                ),
            )
            self.conn.commit()
        return self.get_wishlist_item(item_id) or {"id": item_id, "subject": subject}

    def get_wishlist_item(self, item_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM wishlist WHERE id=?", (item_id,)).fetchone()
        return dict(row) if row else None

    def list_wishlist(self, subject: str, status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM wishlist WHERE subject=?"
        args: list[object] = [subject]
        if status:
            sql += " AND status=?"
            args.append(status)
        sql += " ORDER BY updated_at DESC"
        return [dict(row) for row in self.conn.execute(sql, args)]

    def add_attack_pattern(self, data: dict) -> dict:
        now = _now()
        if not data.get("vuln_class"):
            raise ValueError("attack pattern requires vuln_class")
        pattern_id = str(data.get("id") or f"atk_{uuid.uuid4().hex}")
        with self._wlock:
            self.conn.execute(
                "INSERT INTO attack_patterns(id,vuln_class,title,description,leads,sources,sinks,refs,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "vuln_class=excluded.vuln_class,title=excluded.title,description=excluded.description,"
                "leads=excluded.leads,sources=excluded.sources,sinks=excluded.sinks,"
                "refs=excluded.refs,updated_at=excluded.updated_at",
                (
                    pattern_id,
                    data.get("vuln_class"),
                    data.get("title"),
                    data.get("description"),
                    _json(data.get("leads") or []),
                    _json(data.get("sources") or []),
                    _json(data.get("sinks") or []),
                    _json(data.get("refs") or []),
                    now,
                ),
            )
            self.conn.commit()
        return self.list_attack_patterns(vuln_class=data.get("vuln_class"), pattern_id=pattern_id)[0]

    def list_attack_patterns(
        self,
        *,
        vuln_class: str | None = None,
        pattern_id: str | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM attack_patterns WHERE 1=1"
        args: list[object] = []
        if vuln_class:
            sql += " AND vuln_class=?"
            args.append(vuln_class)
        if pattern_id:
            sql += " AND id=?"
            args.append(pattern_id)
        sql += " ORDER BY updated_at DESC"
        return [_attack_pattern_row(row) for row in self.conn.execute(sql, args)]

    def set_class_coverage(self, subject: str, data: dict) -> dict:
        now = _now()
        if not data.get("vuln_class"):
            raise ValueError("class coverage requires vuln_class")
        with self._wlock:
            self.conn.execute(
                "INSERT INTO class_coverage(subject,vuln_class,state,checked_by,notes,updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(subject,vuln_class) DO UPDATE SET "
                "state=excluded.state,checked_by=excluded.checked_by,notes=excluded.notes,"
                "updated_at=excluded.updated_at",
                (
                    subject,
                    data.get("vuln_class"),
                    data.get("state", "open"),
                    data.get("checked_by"),
                    data.get("notes"),
                    now,
                ),
            )
            self.conn.commit()
        return self.list_class_coverage(subject, vuln_class=data.get("vuln_class"))[0]

    def list_class_coverage(self, subject: str, vuln_class: str | None = None) -> list[dict]:
        sql = "SELECT * FROM class_coverage WHERE subject=?"
        args: list[object] = [subject]
        if vuln_class:
            sql += " AND vuln_class=?"
            args.append(vuln_class)
        sql += " ORDER BY updated_at DESC"
        return [dict(row) for row in self.conn.execute(sql, args)]

    def funnel(self, subject: str) -> dict:
        return {
            "subject": subject,
            "coverage": self.coverage(subject),
            "plan": self.plan_progress(subject),
            "findings": self.findings_summary(subject),
            "wishlist_open": len(self.list_wishlist(subject, status="open")),
            "class_coverage": self.list_class_coverage(subject),
        }


def _finding_row(row: sqlite3.Row) -> dict:
    row_data = dict(row)
    payload = _load_json(row_data.pop("payload", None), {})
    data = {**(payload if isinstance(payload, dict) else {}), **row_data}
    for key in ("code_paths", "repro_hints", "constituent_findings", "related_locations", "history"):
        data[key] = _load_json(data.get(key))
    return data


def _merge_finding_payload(existing: dict, incoming: dict) -> dict:
    merged = dict(existing)
    for key, value in incoming.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    for key in (
        "code_paths",
        "source_anchors",
        "artifact_refs",
        "limitations",
        "repro_hints",
        "reproduction_steps",
        "poc_refs",
        "affected_versions",
        "references",
        "data_touched",
        "constituent_findings",
    ):
        merged[key] = _merge_string_lists(existing.get(key) or [], incoming.get(key) or [])
    for key in ("evidence", "related_locations", "history"):
        merged[key] = _merge_json_lists(existing.get(key) or [], incoming.get(key) or [])
    merged["id"] = existing.get("id") or incoming.get("id")
    merged["subject"] = existing.get("subject") or incoming.get("subject")
    return merged


def _finding_dedup_key(subject: str, data: dict) -> str:
    parts = [
        subject,
        _normalized_dedup_text(data.get("vuln_class") or "unknown"),
        _normalized_dedup_text(data.get("title") or ""),
        _normalized_dedup_text(data.get("affected_component") or data.get("component") or ""),
    ]
    return "dedup:" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _related_locations_from_finding(data: dict) -> list[dict]:
    locations: list[dict] = []
    refs: list[str] = []
    for key in ("code_paths", "source_anchors", "artifact_refs", "refs"):
        refs.extend(str(item) for item in data.get(key) or [] if str(item).strip())
    for item in data.get("evidence") or []:
        if isinstance(item, dict):
            ref = item.get("ref") or item.get("file") or item.get("artifact_ref")
            if ref:
                refs.append(str(ref))
        elif isinstance(item, str):
            refs.append(item)
    for ref in refs:
        anchor = str(ref).strip()
        if not anchor:
            continue
        locations.append({"path": _source_anchor_path(anchor) or anchor, "anchor": anchor})
    return _merge_related_locations([], locations)


def _merge_related_locations(existing: list[dict], new_locations: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in [*existing, *new_locations]:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        anchor = str(item.get("anchor") or item.get("ref") or path).strip()
        if not anchor:
            continue
        normalized = {"path": path or _source_anchor_path(anchor) or anchor, "anchor": anchor}
        key = (normalized["path"], normalized["anchor"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(normalized)
    return merged


def _merge_string_lists(existing: list, new_items: list) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in [*existing, *new_items]:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            merged.append(text)
    return merged


def _merge_json_lists(existing: list, new_items: list) -> list:
    merged: list = []
    seen: set[str] = set()
    for item in [*existing, *new_items]:
        key = json.dumps(item, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _normalized_dedup_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _attack_pattern_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    for key in ("leads", "sources", "sinks", "refs"):
        data[key] = _load_json(data.get(key))
    return data


def _transition_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["receipt"] = _load_json(data.get("receipt"), {})
    data["refusal_reasons"] = _load_json(data.get("refusal_reasons"), [])
    data["accepted"] = data.get("status") == "accepted"
    return data


def _pending_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["resolution_receipt"] = _load_json(data.get("resolution_receipt"), {})
    return data


def _capability_grant_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["scope"] = _load_json(data.get("scope"), {})
    data["dry_run_required"] = bool(data.get("dry_run_required"))
    data["destructive_token_required"] = bool(data.get("destructive_token_required"))
    return data


def _capability_request_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["scope"] = _load_json(data.get("scope"), {})
    return data


def _grant_expired(grant: dict) -> bool:
    expires_at = grant.get("expires_at")
    return expires_at is not None and float(expires_at) <= _now()


def _grant_refusal_reasons(grant: dict, request: dict) -> list[str]:
    reasons: list[str] = []
    scope = grant.get("scope") if isinstance(grant.get("scope"), dict) else {}
    target = request.get("target") if isinstance(request.get("target"), dict) else {}
    capability_class = str(request.get("capability_class") or request.get("class") or "")
    command = [str(part) for part in (request.get("command") or [])]
    declared_effects = {str(effect) for effect in (request.get("declared_effects") or [])}
    requested_by = str(request.get("requested_by") or "")
    granted_by = str(grant.get("granted_by") or "")

    if grant.get("class") != capability_class:
        reasons.append("grant class does not match")
    if _grant_expired(grant):
        reasons.append("grant is expired")
    if requested_by and granted_by and requested_by == granted_by and granted_by not in {
        "operator",
        "human-operator",
        "refall-ops-panel",
    }:
        reasons.append("agents cannot authorize their own live actions")

    host = str(target.get("host") or _host_from_command(command) or "")
    if host and _scope_list(scope, "hosts") and host not in {str(item) for item in _scope_list(scope, "hosts")}:
        reasons.append("target host outside grant scope")
    port = target.get("port") or _port_from_command(command)
    if port is not None and _scope_list(scope, "ports"):
        if int(port) not in {int(item) for item in _scope_list(scope, "ports")}:
            reasons.append("target port outside grant scope")

    method = str(target.get("method") or request.get("method") or "").upper()
    allowed_methods = {str(item).upper() for item in _scope_list(scope, "methods")}
    if allowed_methods:
        if not method:
            reasons.append("HTTP method required by grant scope")
        elif method not in allowed_methods:
            reasons.append("HTTP method outside grant scope")

    path = str(target.get("path") or _path_from_command(command) or "")
    path_scope = _scope_list(scope, "paths")
    if capability_class == "run_local_command" and path and not path_scope:
        reasons.append("target path scope required")
    if path and path_scope and not _path_in_scope(path, path_scope):
        reasons.append("target path outside grant scope")

    command_requires_docker = _command_requires_docker(command)
    command_requires_codebadger = _command_requires_codebadger(command)
    command_is_destructive = _command_is_destructive(command)

    if ("network" in declared_effects or _host_from_command(command)) and capability_class not in {
        "lan_network_probe",
        "external_network",
        "dynamic_target_probe",
    }:
        reasons.append("network command requires network capability")
    if ("docker" in declared_effects or command_requires_docker) and capability_class not in {
        "docker_control",
        "codebadger_docker",
    }:
        reasons.append("Docker command requires Docker capability")
    if command_requires_codebadger and capability_class != "codebadger_docker":
        reasons.append("Codebadger command requires codebadger capability")
    if "secret" in declared_effects and capability_class != "secret_use":
        reasons.append("secret use requires secret capability")
    if command_is_destructive and capability_class != "destructive_action":
        reasons.append("destructive command requires destructive capability")
    if "destructive" in declared_effects or command_is_destructive or capability_class == "destructive_action":
        if grant.get("dry_run_required") and not request.get("dry_run"):
            reasons.append("destructive request requires dry-run")
        if grant.get("destructive_token_required") and request.get("destructive_approval_token") != "destructive-approval":
            reasons.append("destructive request requires destructive approval token")
    return reasons


def _host_from_command(command: list[str]) -> str | None:
    for part in command:
        parsed = urlparse(part)
        if parsed.scheme and parsed.hostname:
            return parsed.hostname
    return None


def _port_from_command(command: list[str]) -> int | None:
    for part in command:
        parsed = urlparse(part)
        if parsed.scheme and parsed.hostname:
            if parsed.port:
                return parsed.port
            return 443 if parsed.scheme == "https" else 80
    return None


def _path_from_command(command: list[str]) -> str | None:
    for part in command:
        if part.startswith("/"):
            return part
    return None


def _command_requires_docker(command: list[str]) -> bool:
    names = {Path(part).name.lower() for part in command if part}
    if names & {"docker", "podman", "docker-compose"}:
        return True
    text = f" {' '.join(part.lower() for part in command)} "
    return any(token in text for token in (" docker ", " podman ", " docker-compose "))


def _command_requires_codebadger(command: list[str]) -> bool:
    return any("codebadger" in part.lower() for part in command)


def _command_is_destructive(command: list[str]) -> bool:
    if not command:
        return False
    names = [Path(part).name.lower() if part.startswith("/") else part.lower() for part in command]
    text = f" {' '.join(names)} "
    if " rm " in text and any(part.startswith("-") and "r" in part and "f" in part for part in names):
        return True
    return any(token in text for token in (" mkfs", " shred ", " diskutil erase", " dd if=", " dd of="))
