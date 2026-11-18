from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS units (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL, type TEXT NOT NULL,
  path TEXT, name TEXT, line_start INTEGER, line_end INTEGER, parent_id TEXT,
  total_lines INTEGER, indexed INTEGER DEFAULT 1, indexed_src TEXT,
  state TEXT DEFAULT 'open', claimed_by TEXT, lease_expires REAL,
  summary TEXT, sensitivity TEXT, data_touched TEXT, flows_in TEXT, flows_out TEXT,
  leads TEXT, characterized_by TEXT, updated_at REAL
);
CREATE INDEX IF NOT EXISTS ix_units_subject_state ON units(subject, state);
CREATE INDEX IF NOT EXISTS ix_units_parent ON units(parent_id);
CREATE INDEX IF NOT EXISTS ix_units_path ON units(subject, path);

CREATE TABLE IF NOT EXISTS evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id TEXT NOT NULL,
  file TEXT NOT NULL, line_start INTEGER, line_end INTEGER, snippet TEXT, kind TEXT
);
CREATE INDEX IF NOT EXISTS ix_evidence_unit ON evidence(unit_id);

CREATE TABLE IF NOT EXISTS investigations (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL, pass_number INTEGER DEFAULT 1,
  title TEXT, target_files TEXT, kb_references TEXT, question TEXT,
  priority INTEGER DEFAULT 100, kind TEXT, parent_id TEXT,
  state TEXT DEFAULT 'open', claimed_by TEXT, lease_expires REAL,
  created_at REAL, updated_at REAL
);
CREATE INDEX IF NOT EXISTS ix_inv_subject_state ON investigations(subject, state);

CREATE TABLE IF NOT EXISTS findings (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL,
  title TEXT NOT NULL, description TEXT, impact TEXT,
  severity TEXT, privileges_required TEXT, attacker_position TEXT, user_interaction TEXT,
  status TEXT DEFAULT 'PROVISIONALLY_VALID',
  quality_tier TEXT DEFAULT 'HYPOTHESIS',
  production_viability TEXT, repro_status TEXT DEFAULT 'not_attempted', patch_status TEXT,
  code_paths TEXT NOT NULL, mitigation TEXT, reasoning TEXT, repro_hints TEXT,
  critic_reasoning TEXT, vuln_class TEXT, source_unit_id TEXT, investigation_id TEXT,
  pass_number INTEGER DEFAULT 1, impact_score INTEGER, likelihood_score INTEGER,
  mantis_risk_score REAL, priority TEXT, inferred_exposure TEXT, availability_tier TEXT,
  duplicate_of TEXT, constituent_findings TEXT, dedup_key TEXT, canonical_finding_id TEXT,
  related_locations TEXT, history TEXT, payload TEXT,
  created_by TEXT, created_at REAL, updated_at REAL
);
CREATE INDEX IF NOT EXISTS ix_find_subject_status ON findings(subject, status);
CREATE INDEX IF NOT EXISTS ix_find_source_unit ON findings(source_unit_id);

CREATE TABLE IF NOT EXISTS subject_meta (
  subject TEXT PRIMARY KEY, info_md TEXT, root_container TEXT, updated_at REAL, generated_by TEXT
);

CREATE TABLE IF NOT EXISTS source_inventories (
  id TEXT PRIMARY KEY,
  subject TEXT NOT NULL,
  root TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_source_inventories_subject ON source_inventories(subject, created_at);

CREATE TABLE IF NOT EXISTS scope_overlays (
  subject TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  updated_by TEXT,
  updated_at REAL
);

CREATE TABLE IF NOT EXISTS threat_models (
  id TEXT PRIMARY KEY,
  subject TEXT NOT NULL,
  payload TEXT NOT NULL,
  status TEXT DEFAULT 'active',
  created_by TEXT,
  created_at REAL,
  updated_at REAL
);
CREATE INDEX IF NOT EXISTS ix_threat_models_subject ON threat_models(subject, updated_at);

CREATE TABLE IF NOT EXISTS wishlist (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL, kind TEXT, item TEXT NOT NULL, reason TEXT,
  requested_by TEXT, status TEXT DEFAULT 'open', created_at REAL, updated_at REAL
);
CREATE INDEX IF NOT EXISTS ix_wish_subject ON wishlist(subject, status);

CREATE TABLE IF NOT EXISTS attack_patterns (
  id TEXT PRIMARY KEY, vuln_class TEXT NOT NULL, title TEXT, description TEXT,
  leads TEXT, sources TEXT, sinks TEXT, refs TEXT, updated_at REAL
);
CREATE INDEX IF NOT EXISTS ix_attack_class ON attack_patterns(vuln_class);

CREATE TABLE IF NOT EXISTS class_coverage (
  subject TEXT NOT NULL, vuln_class TEXT NOT NULL, state TEXT DEFAULT 'open',
  checked_by TEXT, notes TEXT, updated_at REAL, PRIMARY KEY(subject, vuln_class)
);

CREATE TABLE IF NOT EXISTS finding_transitions (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL, finding_id TEXT NOT NULL,
  from_status TEXT, to_status TEXT, from_quality TEXT, to_quality TEXT,
  proposed_by TEXT, reason TEXT, receipt_type TEXT, receipt TEXT,
  duplicate_of TEXT, status TEXT NOT NULL, refusal_reasons TEXT,
  created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_transitions_subject_finding ON finding_transitions(subject, finding_id);
CREATE INDEX IF NOT EXISTS ix_transitions_status ON finding_transitions(subject, status);

CREATE TABLE IF NOT EXISTS transition_receipts (
  id TEXT PRIMARY KEY, transition_id TEXT NOT NULL, finding_id TEXT NOT NULL,
  subject TEXT NOT NULL, receipt_type TEXT NOT NULL, receipt TEXT NOT NULL,
  created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_transition_receipts_finding ON transition_receipts(subject, finding_id);

CREATE TABLE IF NOT EXISTS pending_actions (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL, identity_key TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL, title TEXT NOT NULL, description TEXT,
  status TEXT DEFAULT 'open', priority TEXT DEFAULT 'medium',
  source_event_id TEXT, source_finding_id TEXT, source_unit_id TEXT,
  required_receipt_type TEXT, assigned_lane TEXT, claimed_by TEXT,
  lease_expires REAL, resolution_receipt TEXT, created_by TEXT,
  created_at REAL, updated_at REAL
);
CREATE INDEX IF NOT EXISTS ix_pending_subject_status ON pending_actions(subject, status);
CREATE INDEX IF NOT EXISTS ix_pending_subject_kind ON pending_actions(subject, kind);

CREATE TABLE IF NOT EXISTS capability_grants (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL, class TEXT NOT NULL,
  scope TEXT NOT NULL, granted_by TEXT, reason TEXT, expires_at REAL,
  dry_run_required INTEGER DEFAULT 0, destructive_token_required INTEGER DEFAULT 0,
  revoked_at REAL, created_at REAL, updated_at REAL
);
CREATE INDEX IF NOT EXISTS ix_cap_grants_subject_class ON capability_grants(subject, class);

CREATE TABLE IF NOT EXISTS capability_requests (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL, class TEXT NOT NULL,
  requested_by TEXT, reason TEXT, scope TEXT, status TEXT DEFAULT 'open',
  created_at REAL, updated_at REAL
);
CREATE INDEX IF NOT EXISTS ix_cap_requests_subject_status ON capability_requests(subject, status);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _ensure_column(conn, "findings", "quality_tier", "TEXT DEFAULT 'HYPOTHESIS'")
    _ensure_column(conn, "findings", "dedup_key", "TEXT")
    _ensure_column(conn, "findings", "canonical_finding_id", "TEXT")
    _ensure_column(conn, "findings", "related_locations", "TEXT")
    _ensure_column(conn, "findings", "payload", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_find_subject_dedup ON findings(subject, dedup_key)")
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
