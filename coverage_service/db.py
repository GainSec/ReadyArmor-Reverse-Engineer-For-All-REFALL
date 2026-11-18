import sqlite3

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

-- The PLAN (Mantis mantis-plan): investigations the researcher claims and answers.
-- Distinct from `units`: units are the mechanical completeness map (every line);
-- investigations are targeted security questions against specific files.
CREATE TABLE IF NOT EXISTS investigations (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL, pass_number INTEGER DEFAULT 1,
  title TEXT, target_files TEXT, kb_references TEXT, question TEXT,
  priority INTEGER DEFAULT 100,          -- lower = claimed first (sensitivity-first ordering)
  kind TEXT,                             -- seed category (exec-sink/secret/auth/...) or 'branch'
  parent_id TEXT,                        -- branch lineage: which investigation spawned this one
  state TEXT DEFAULT 'open', claimed_by TEXT, lease_expires REAL,
  created_at REAL, updated_at REAL
);
CREATE INDEX IF NOT EXISTS ix_inv_subject_state ON investigations(subject, state);

-- FINDINGS (Mantis schema.json #/$defs/finding): sparse security issues, full lifecycle.
-- Separate from `units`; a finding links back to the coverage unit that spawned it.
CREATE TABLE IF NOT EXISTS findings (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL,
  title TEXT NOT NULL, description TEXT, impact TEXT,
  severity TEXT, privileges_required TEXT, attacker_position TEXT, user_interaction TEXT,
  status TEXT DEFAULT 'PROVISIONALLY_VALID',
  production_viability TEXT, repro_status TEXT DEFAULT 'not_attempted', patch_status TEXT,
  code_paths TEXT NOT NULL,              -- json array of "file:line" anchors (evidence)
  mitigation TEXT, reasoning TEXT, repro_hints TEXT, critic_reasoning TEXT,
  vuln_class TEXT,                       -- CWE id or class label
  source_unit_id TEXT, investigation_id TEXT, pass_number INTEGER DEFAULT 1,
  impact_score INTEGER, likelihood_score INTEGER, mantis_risk_score REAL,
  priority TEXT, inferred_exposure TEXT, availability_tier TEXT,
  duplicate_of TEXT, constituent_findings TEXT,
  history TEXT,                          -- json array of stage/action/details/pass/timestamp
  created_by TEXT, created_at REAL, updated_at REAL
);
CREATE INDEX IF NOT EXISTS ix_find_subject_status ON findings(subject, status);
CREATE INDEX IF NOT EXISTS ix_find_source_unit ON findings(source_unit_id);

-- SUBJECT CONTEXT (deepsec INFO.md): per-subject briefing injected into every researcher —
-- what the subject IS, its auth model, framework primitives, conventions. Cuts false positives.
CREATE TABLE IF NOT EXISTS subject_meta (
  subject TEXT PRIMARY KEY, info_md TEXT, root_container TEXT, updated_at REAL, generated_by TEXT
);

-- WISHLIST (Cloudflare): researchers log what they NEED (tool/env/dep/access) instead of guessing;
-- the operator sees a live list of what to provision.
CREATE TABLE IF NOT EXISTS wishlist (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL, kind TEXT, item TEXT NOT NULL, reason TEXT,
  requested_by TEXT, status TEXT DEFAULT 'open', created_at REAL, updated_at REAL
);
CREATE INDEX IF NOT EXISTS ix_wish_subject ON wishlist(subject, status);

-- ATTACK-PATTERN KB (#5): harvested per-vuln-class leads ('what to look for') that feed researchers
-- and drive per-class exhaustiveness. Populated later from external resources.
CREATE TABLE IF NOT EXISTS attack_patterns (
  id TEXT PRIMARY KEY, vuln_class TEXT NOT NULL, title TEXT, description TEXT,
  leads TEXT, sources TEXT, sinks TEXT, refs TEXT, updated_at REAL
);
CREATE INDEX IF NOT EXISTS ix_attack_class ON attack_patterns(vuln_class);

-- PER-CLASS EXHAUSTIVENESS (#5): has vuln-class C been exhaustively checked on subject S's surface?
-- The vuln-class analogue of line coverage — "have you checked for XSS/SSRF/... exhaustively".
CREATE TABLE IF NOT EXISTS class_coverage (
  subject TEXT NOT NULL, vuln_class TEXT NOT NULL, state TEXT DEFAULT 'open',
  checked_by TEXT, notes TEXT, updated_at REAL, PRIMARY KEY(subject, vuln_class)
);
"""


def connect(path):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# Idempotent column adds for tables that predate a column (CREATE TABLE IF NOT EXISTS
# won't alter an existing table). Each entry: (table, column, definition).
MIGRATIONS = [
    ("investigations", "kind", "TEXT"),
    ("investigations", "parent_id", "TEXT"),
]


def _migrate(conn):
    for table, col, decl in MIGRATIONS:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        if cols and col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    conn.commit()


def init_schema(conn):
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)
