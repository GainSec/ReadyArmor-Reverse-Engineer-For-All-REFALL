import json
import time
import threading
import uuid


def _now():
    return time.time()


# Mantis schema.json enums (finding lifecycle).
FINDING_STATUS = {
    "VALID",
    "FALSE_POSITIVE",
    "PROVISIONALLY_VALID",
    "NEEDS_RESEARCH",
    "DUPLICATE",
    "CHAINABLE_DEFERRED",
}
SEVERITY = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
# Columns that hold JSON-encoded arrays/objects on disk.
_FINDING_JSON = ("code_paths", "constituent_findings", "history")
_INV_JSON = ("target_files", "kb_references")


def _decode(row, json_cols):
    d = dict(row)
    for c in json_cols:
        if c in d and isinstance(d[c], str) and d[c]:
            try:
                d[c] = json.loads(d[c])
            except (ValueError, TypeError):
                pass
    return d


class Store:
    """Single-writer data access over a SQLite (WAL) connection. Writes go through a
    lock; claim_next uses BEGIN IMMEDIATE so no two agents ever get the same unit."""

    def __init__(self, conn):
        self.conn = conn
        self._wlock = threading.Lock()

    def upsert_units(self, units):
        cols = ["id", "subject", "type", "path", "name", "line_start", "line_end", "parent_id",
                "total_lines", "indexed_src"]
        with self._wlock:
            for u in units:
                self.conn.execute(
                    f"INSERT INTO units({','.join(cols)},indexed,updated_at) "
                    f"VALUES({','.join('?' for _ in cols)},1,?) "
                    "ON CONFLICT(id) DO UPDATE SET indexed=1, indexed_src=excluded.indexed_src",
                    [u.get(c) for c in cols] + [_now()])
            self.conn.commit()
        return len(units)

    def set_surface(self, subject, dimension, items, covered=None):
        """Register a NON-CODE coverage surface for a behavioral/cartography subject: one unit per
        enumerable target item under a named dimension, marking `covered` items characterized. Lets a
        subloop that has no source-line surface still report real coverage % via the existing model."""
        cov = set(str(x) for x in (covered or []))
        now = _now()
        with self._wlock:
            for i, name in enumerate(items):
                uid = f"{subject}::surface::{dimension}::{i}"
                st = "characterized" if str(name) in cov else "open"
                self.conn.execute(
                    "INSERT INTO units(id,subject,type,path,name,line_start,line_end,total_lines,"
                    "indexed,indexed_src,state,characterized_by,updated_at) "
                    "VALUES(?,?,'symbol',?,?,?,?,1,1,'surface',?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET state=excluded.state, "
                    "characterized_by=excluded.characterized_by, updated_at=excluded.updated_at",
                    (uid, subject, f"surface/{dimension}", str(name)[:200], i + 1, i + 1, st,
                     "subloop" if st == "characterized" else None, now))
            self.conn.commit()
        return {"dimension": dimension, "items": len(items), "covered": len(cov)}

    def claim_next(self, subject, agent, lease_s=900):
        with self._wlock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                row = self.conn.execute(
                    "SELECT * FROM units WHERE subject=? AND type IN ('symbol','line_range') "
                    "AND (state='open' OR (state='claimed' AND lease_expires < ?)) "
                    "ORDER BY (type='symbol') DESC, path, line_start LIMIT 1",
                    (subject, _now())).fetchone()
                if not row:
                    self.conn.execute("ROLLBACK")
                    return None
                self.conn.execute(
                    "UPDATE units SET state='claimed', claimed_by=?, lease_expires=? WHERE id=?",
                    (agent, _now() + lease_s, row["id"]))
                self.conn.execute("COMMIT")
                return dict(row)
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def submit(self, unit_id, agent, summary, sensitivity=None, data_touched=None,
               flows_in=None, flows_out=None, leads=None, evidence=()):
        evidence = list(evidence or [])
        if not evidence or not all(e.get("file") for e in evidence):
            raise ValueError("submit requires >=1 evidence anchor with a file")
        return self._resolve(unit_id, agent, "characterized", summary, sensitivity,
                             data_touched, flows_in, flows_out, leads, evidence)

    def mark_dead(self, unit_id, agent, evidence):
        evidence = list(evidence or [])
        if not evidence or not all(e.get("file") for e in evidence):
            raise ValueError("mark_dead requires evidence")
        return self._resolve(unit_id, agent, "dead", "dead code", None, None, None, None, None, evidence)

    def _resolve(self, unit_id, agent, state, summary, sensitivity, data_touched,
                 flows_in, flows_out, leads, evidence):
        with self._wlock:
            self.conn.execute(
                "UPDATE units SET state=?, summary=?, sensitivity=?, data_touched=?, flows_in=?, "
                "flows_out=?, leads=?, characterized_by=?, claimed_by=NULL, lease_expires=NULL, updated_at=? "
                "WHERE id=?",
                (state, summary, sensitivity, json.dumps(data_touched), json.dumps(flows_in),
                 json.dumps(flows_out), json.dumps(leads), agent, _now(), unit_id))
            for e in evidence:
                self.conn.execute(
                    "INSERT INTO evidence(unit_id,file,line_start,line_end,snippet,kind) VALUES(?,?,?,?,?,?)",
                    (unit_id, e["file"], e.get("line_start"), e.get("line_end"),
                     e.get("snippet"), e.get("kind", "proof")))
            self.conn.commit()
        return self.get_unit(unit_id)

    def release(self, unit_id):
        with self._wlock:
            self.conn.execute("UPDATE units SET state='open', claimed_by=NULL, lease_expires=NULL WHERE id=?",
                              (unit_id,))
            self.conn.commit()

    def sweep(self):
        with self._wlock:
            n = self.conn.execute(
                "UPDATE units SET state='open', claimed_by=NULL, lease_expires=NULL "
                "WHERE state='claimed' AND lease_expires < ?", (_now(),)).rowcount
            self.conn.commit()
        return n

    def _leaf_stats(self, subject):
        return self.conn.execute(
            "SELECT COALESCE(SUM(total_lines),0) total, "
            "COALESCE(SUM(CASE WHEN state IN('characterized','dead') THEN total_lines END),0) resolved, "
            "COALESCE(SUM(CASE WHEN state='characterized' THEN total_lines END),0) chars, "
            "COALESCE(SUM(CASE WHEN state='dead' THEN total_lines END),0) dead "
            "FROM units WHERE subject=? AND type IN('symbol','line_range')", (subject,)).fetchone()

    def coverage(self, subject):
        r = self._leaf_stats(subject)
        files = self.conn.execute(
            "SELECT COUNT(*) FROM units WHERE subject=? AND type='file'", (subject,)).fetchone()[0]
        done = self.conn.execute(
            "SELECT COUNT(*) FROM units f WHERE f.subject=? AND f.type='file' AND NOT EXISTS "
            "(SELECT 1 FROM units c WHERE c.parent_id=f.id AND c.state NOT IN('characterized','dead'))",
            (subject,)).fetchone()[0]
        total = r["total"] or 0
        pct = lambda x: round(100.0 * x / total, 1) if total else 0.0
        return {"lines_total": total, "lines_covered": r["resolved"], "lines_dead": r["dead"],
                "indexed_pct": 100.0 if total else 0.0,
                "characterized_pct": pct(r["chars"]), "resolved_pct": pct(r["resolved"]),
                "files_total": files, "files_done": done,
                "symbols_total": self.conn.execute(
                    "SELECT COUNT(*) FROM units WHERE subject=? AND type='symbol'", (subject,)).fetchone()[0]}

    def gate(self, subject, threshold=0.95):
        cov = self.coverage(subject)
        rp = cov["resolved_pct"] / 100.0
        return {"subject": subject, "resolved_pct": cov["resolved_pct"],
                "threshold": threshold * 100, "locked": rp < threshold,
                "phase": "research" if rp >= threshold else "discovery"}

    def search(self, subject, type=None, state=None, sensitivity=None, path=None, q=None, limit=200):
        sql = "SELECT id,type,path,name,line_start,line_end,state,sensitivity,summary FROM units WHERE subject=?"
        args = [subject]
        for col, val in (("type", type), ("state", state), ("sensitivity", sensitivity)):
            if val:
                sql += f" AND {col}=?"
                args.append(val)
        if path:
            sql += " AND path LIKE ?"
            args.append(f"%{path}%")
        if q:
            sql += " AND (name LIKE ? OR summary LIKE ?)"
            args += [f"%{q}%", f"%{q}%"]
        sql += " ORDER BY updated_at DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.conn.execute(sql, args)]

    def get_unit(self, unit_id):
        r = self.conn.execute("SELECT * FROM units WHERE id=?", (unit_id,)).fetchone()
        if not r:
            return None
        u = dict(r)
        u["evidence"] = [dict(e) for e in self.conn.execute(
            "SELECT file,line_start,line_end,snippet,kind FROM evidence WHERE unit_id=?", (unit_id,))]
        return u

    # ---- FINDINGS (Mantis finding schema) --------------------------------------
    # A finding is a sparse security issue, distinct from a coverage unit. It MUST
    # carry >=1 code_paths anchor (file:line) — the same evidence discipline as units.

    _FIND_COLS = ("id", "subject", "title", "description", "impact", "severity",
                  "privileges_required", "attacker_position", "user_interaction", "status",
                  "production_viability", "repro_status", "patch_status", "code_paths",
                  "mitigation", "reasoning", "repro_hints", "critic_reasoning", "vuln_class",
                  "source_unit_id", "investigation_id", "pass_number", "impact_score",
                  "likelihood_score", "mantis_risk_score", "priority", "inferred_exposure",
                  "availability_tier", "duplicate_of", "constituent_findings", "history",
                  "created_by", "created_at", "updated_at")

    def add_finding(self, finding):
        f = dict(finding)
        if not f.get("subject") or not f.get("title"):
            raise ValueError("finding requires subject and title")
        paths = f.get("code_paths") or []
        if not isinstance(paths, list) or not paths:
            raise ValueError("finding requires >=1 code_paths anchor (file:line)")
        fid = f.get("id") or uuid.uuid4().hex
        now = _now()
        status = f.get("status") or "PROVISIONALLY_VALID"
        if status not in FINDING_STATUS:
            raise ValueError(f"bad status {status}")
        hist = f.get("history") or [{"stage": f.get("created_by_stage", "researcher"),
                                     "action": "created", "details": "Initial audit finding recorded.",
                                     "pass_number": f.get("pass_number", 1), "timestamp": now}]
        row = {c: f.get(c) for c in self._FIND_COLS}
        row.update(id=fid, status=status, created_at=now, updated_at=now,
                   repro_status=f.get("repro_status") or "not_attempted",
                   pass_number=f.get("pass_number", 1))
        for jc in _FINDING_JSON:
            row[jc] = json.dumps(paths if jc == "code_paths" else (hist if jc == "history" else f.get(jc)))
        with self._wlock:
            self.conn.execute(
                f"INSERT INTO findings({','.join(self._FIND_COLS)}) "
                f"VALUES({','.join('?' for _ in self._FIND_COLS)})",
                [row[c] for c in self._FIND_COLS])
            self.conn.commit()
        return self.get_finding(fid)

    def get_finding(self, finding_id):
        r = self.conn.execute("SELECT * FROM findings WHERE id=?", (finding_id,)).fetchone()
        return _decode(r, _FINDING_JSON) if r else None

    def review_finding(self, finding_id, agent, status, reasoning=None, repro_hints=None,
                       pass_number=1, stage="reviewer"):
        """The review/critic gate: set validity + append a history entry (Mantis mantis-review)."""
        if status not in FINDING_STATUS:
            raise ValueError(f"bad status {status}")
        cur = self.get_finding(finding_id)
        if not cur:
            raise ValueError("no such finding")
        hist = cur.get("history") or []
        hist.append({"stage": stage, "action": "reviewed", "by": agent,
                     "details": f"status={status}: {reasoning or ''}"[:500],
                     "pass_number": pass_number, "timestamp": _now()})
        with self._wlock:
            self.conn.execute(
                "UPDATE findings SET status=?, reasoning=?, repro_hints=COALESCE(?,repro_hints), "
                "history=?, updated_at=? WHERE id=?",
                (status, reasoning, repro_hints, json.dumps(hist), _now(), finding_id))
            self.conn.commit()
        return self.get_finding(finding_id)

    def update_finding_validation(self, finding_id, agent, production_viability=None,
                                  repro_status=None, repro_hints=None, critic_reasoning=None,
                                  patch_status=None, pass_number=1):
        """Attach runtime-validation and visualization/proof notes to a non-rejected finding."""
        cur = self.get_finding(finding_id)
        if not cur:
            raise ValueError("no such finding")
        if cur.get("status") in ("FALSE_POSITIVE", "DUPLICATE"):
            raise ValueError("rejected findings do not accept validation artifacts")
        if not any(v is not None for v in (production_viability, repro_status, repro_hints,
                                           critic_reasoning, patch_status)):
            raise ValueError("validation update requires at least one field")
        hist = cur.get("history") or []
        detail_bits = []
        if repro_status:
            detail_bits.append(f"repro_status={repro_status}")
        if production_viability:
            detail_bits.append(production_viability)
        hist.append({"stage": "runtime-validation", "action": "validation-updated", "by": agent,
                     "details": "; ".join(detail_bits)[:500],
                     "pass_number": pass_number, "timestamp": _now()})
        with self._wlock:
            self.conn.execute(
                "UPDATE findings SET production_viability=COALESCE(?,production_viability), "
                "repro_status=COALESCE(?,repro_status), repro_hints=COALESCE(?,repro_hints), "
                "critic_reasoning=COALESCE(?,critic_reasoning), patch_status=COALESCE(?,patch_status), "
                "history=?, updated_at=? WHERE id=?",
                (production_viability, repro_status, repro_hints, critic_reasoning, patch_status,
                 json.dumps(hist), _now(), finding_id))
            self.conn.commit()
        return self.get_finding(finding_id)

    def list_findings(self, subject, status=None, priority=None, severity=None, limit=500):
        sql = "SELECT * FROM findings WHERE subject=?"
        args = [subject]
        for col, val in (("status", status), ("priority", priority), ("severity", severity)):
            if val:
                sql += f" AND {col}=?"
                args.append(val)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        args.append(limit)
        return [_decode(r, _FINDING_JSON) for r in self.conn.execute(sql, args)]

    def findings_summary(self, subject):
        def counts(col):
            return {r[0]: r[1] for r in self.conn.execute(
                f"SELECT {col}, COUNT(*) FROM findings WHERE subject=? AND {col} IS NOT NULL "
                f"GROUP BY {col}", (subject,))}
        total = self.conn.execute("SELECT COUNT(*) FROM findings WHERE subject=?", (subject,)).fetchone()[0]
        return {"total": total, "by_status": counts("status"),
                "by_severity": counts("severity"), "by_priority": counts("priority")}

    # ---- PLAN / INVESTIGATIONS (Mantis mantis-plan) ----------------------------

    def put_plan(self, subject, investigations, pass_number=1, replace=True):
        """Write the plan: a list of {title,target_files,kb_references,question,priority}."""
        now = _now()
        with self._wlock:
            if replace:
                self.conn.execute("DELETE FROM investigations WHERE subject=? AND state='open'", (subject,))
            n = 0
            for inv in investigations:
                self.conn.execute(
                    "INSERT INTO investigations(id,subject,pass_number,title,target_files,"
                    "kb_references,question,priority,kind,parent_id,state,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,'open',?,?)",
                    (inv.get("id") or uuid.uuid4().hex, subject, pass_number, inv.get("title"),
                     json.dumps(inv.get("target_files") or []),
                     json.dumps(inv.get("kb_references") or []), inv.get("question"),
                     inv.get("priority", 100), inv.get("kind"), inv.get("parent_id"), now, now))
                n += 1
            self.conn.commit()
        return n

    def claim_investigation(self, subject, agent, lease_s=1800):
        with self._wlock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                row = self.conn.execute(
                    "SELECT * FROM investigations WHERE subject=? "
                    "AND (state='open' OR (state='claimed' AND lease_expires < ?)) "
                    "ORDER BY priority, created_at LIMIT 1", (subject, _now())).fetchone()
                if not row:
                    self.conn.execute("ROLLBACK")
                    return None
                self.conn.execute(
                    "UPDATE investigations SET state='claimed', claimed_by=?, lease_expires=?, updated_at=? "
                    "WHERE id=?", (agent, _now() + lease_s, _now(), row["id"]))
                self.conn.execute("COMMIT")
                return _decode(row, _INV_JSON)
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def complete_investigation(self, inv_id, agent):
        with self._wlock:
            self.conn.execute(
                "UPDATE investigations SET state='done', claimed_by=?, lease_expires=NULL, updated_at=? "
                "WHERE id=?", (agent, _now(), inv_id))
            self.conn.commit()

    def _release_expired_investigation_claims(self):
        now = _now()
        self.conn.execute(
            "UPDATE investigations SET state='open', claimed_by=NULL, lease_expires=NULL, updated_at=? "
            "WHERE state='claimed' AND lease_expires < ?", (now, now))

    def list_investigations(self, subject, state=None, limit=500):
        sql = "SELECT * FROM investigations WHERE subject=?"
        args = [subject]
        if state:
            sql += " AND state=?"
            args.append(state)
        sql += " ORDER BY priority, created_at LIMIT ?"
        args.append(limit)
        return [_decode(r, _INV_JSON) for r in self.conn.execute(sql, args)]

    def plan_progress(self, subject):
        with self._wlock:
            self._release_expired_investigation_claims()
            self.conn.commit()
        rows = {r[0]: r[1] for r in self.conn.execute(
            "SELECT state, COUNT(*) FROM investigations WHERE subject=? GROUP BY state", (subject,))}
        total = sum(rows.values())
        return {"total": total, "open": rows.get("open", 0), "claimed": rows.get("claimed", 0),
                "done": rows.get("done", 0)}

    # ---- SUBJECT CONTEXT (INFO.md) ---------------------------------------------

    def set_context(self, subject, info_md, generated_by=None, root_container=None):
        with self._wlock:
            self.conn.execute(
                "INSERT INTO subject_meta(subject,info_md,root_container,updated_at,generated_by) "
                "VALUES(?,?,?,?,?) ON CONFLICT(subject) DO UPDATE SET info_md=excluded.info_md, "
                "root_container=COALESCE(excluded.root_container,root_container), "
                "updated_at=excluded.updated_at, generated_by=excluded.generated_by",
                (subject, info_md, root_container, _now(), generated_by))
            self.conn.commit()
        return self.get_context(subject)

    def get_context(self, subject):
        r = self.conn.execute("SELECT * FROM subject_meta WHERE subject=?", (subject,)).fetchone()
        return dict(r) if r else None

    # ---- WISHLIST --------------------------------------------------------------

    def add_wish(self, subject, item, kind=None, reason=None, requested_by=None):
        if not item:
            raise ValueError("wishlist item required")
        wid = uuid.uuid4().hex
        with self._wlock:
            self.conn.execute(
                "INSERT INTO wishlist(id,subject,kind,item,reason,requested_by,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,'open',?,?)",
                (wid, subject, kind, item, reason, requested_by, _now(), _now()))
            self.conn.commit()
        return self.get_wish(wid)

    def get_wish(self, wid):
        r = self.conn.execute("SELECT * FROM wishlist WHERE id=?", (wid,)).fetchone()
        return dict(r) if r else None

    def list_wishes(self, subject, status=None, limit=500):
        sql, args = "SELECT * FROM wishlist WHERE subject=?", [subject]
        if status:
            sql += " AND status=?"
            args.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.conn.execute(sql, args)]

    def resolve_wish(self, wid, status):
        with self._wlock:
            self.conn.execute("UPDATE wishlist SET status=?, updated_at=? WHERE id=?", (status, _now(), wid))
            self.conn.commit()
        return self.get_wish(wid)

    # ---- FUNNEL METRICS (Cloudflare) -------------------------------------------

    def funnel(self, subject):
        by = {r[0]: r[1] for r in self.conn.execute(
            "SELECT status, COUNT(*) FROM findings WHERE subject=? GROUP BY status", (subject,))}
        valid = by.get("VALID", 0)
        fp = by.get("FALSE_POSITIVE", 0)
        judged = valid + fp
        return {"candidates": sum(by.values()), "provisional": by.get("PROVISIONALLY_VALID", 0),
                "valid": valid, "false_positive": fp, "needs_research": by.get("NEEDS_RESEARCH", 0),
                "duplicate": by.get("DUPLICATE", 0),
                "chainable_deferred": by.get("CHAINABLE_DEFERRED", 0),
                "rejection_rate": round(fp / judged, 3) if judged else None,
                "precision": round(valid / judged, 3) if judged else None}

    # ---- ATTACK-PATTERN KB + PER-CLASS EXHAUSTIVENESS (#5) ----------------------

    def add_attack_pattern(self, vuln_class, title, description=None, leads=None,
                           sources=None, sinks=None, refs=None):
        pid = uuid.uuid4().hex
        with self._wlock:
            self.conn.execute(
                "INSERT INTO attack_patterns(id,vuln_class,title,description,leads,sources,sinks,refs,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (pid, vuln_class, title, description, json.dumps(leads), json.dumps(sources),
                 json.dumps(sinks), json.dumps(refs), _now()))
            self.conn.commit()
        return pid

    def list_attack_patterns(self, vuln_class=None):
        if vuln_class:
            rows = self.conn.execute("SELECT * FROM attack_patterns WHERE vuln_class=?", (vuln_class,))
        else:
            rows = self.conn.execute("SELECT * FROM attack_patterns")
        return [_decode(r, ("leads", "sources", "sinks", "refs")) for r in rows]

    def set_class_coverage(self, subject, vuln_class, state, checked_by=None, notes=None):
        with self._wlock:
            self.conn.execute(
                "INSERT INTO class_coverage(subject,vuln_class,state,checked_by,notes,updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(subject,vuln_class) DO UPDATE SET state=excluded.state, "
                "checked_by=excluded.checked_by, notes=excluded.notes, updated_at=excluded.updated_at",
                (subject, vuln_class, state, checked_by, notes, _now()))
            self.conn.commit()

    def class_coverage(self, subject):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM class_coverage WHERE subject=? ORDER BY vuln_class", (subject,))]
