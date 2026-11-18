// Arctic Base API client. Single-origin; relative URLs.

export type Banner =
  | { kind: "upload"; ref: string }
  | { kind: "url"; ref: string };

export interface WorkbenchMeta {
  version: number;
  slug: string;
  title: string;
  description: string;
  url: string | null;
  ip: string | null;
  local_path: string | null;
  tags: string[];
  banner: Banner | null;
  custom_fields: Record<string, string>;
  created_at: string;
  updated_at: string;
  last_accessed_at: string | null;
}

export type ObjectKind = "md" | "html" | "approval-html" | "image" | "qa-form" | "file" | "runbook";

export interface ObjectMeta {
  version: number;
  id: string;
  kind: ObjectKind;
  title: string;
  description: string;
  drawer: string;
  filename: string;
  mime: string;
  size_bytes: number;
  etag: string;
  created_at: string;
  updated_at: string;
  state_version: number;
  order: number;
  last_accessed_at: string | null;
  pinned: boolean;
  archived: boolean;
}

export interface TypographyStyle {
  fontFamily?: string;
  fontSize?: string;
  fontWeight?: string;
  lineHeight?: string;
  letterSpacing?: string;
}

export interface ThemeTokens {
  name?: string;
  core: Record<string, string>;
  typography: Record<string, TypographyStyle>;
  rounded: Record<string, string>;
  spacing: Record<string, string>;
  custom: Record<string, string>;
}

export interface Theme {
  tokens: ThemeTokens;
  prose: string;
  assets: string[];
}

export type ResponseKind = "submit" | "autosave" | "agent-edit";
export type Submitter = "user" | "agent" | "system";

export interface ResponseEvent {
  version: number;
  object_id: string;
  submitted_at: string;
  submitted_by: Submitter;
  kind: ResponseKind;
  payload: Record<string, unknown>;
}

export interface RefallOpsStatus {
  enabled: boolean;
  commands_enabled: boolean;
  deployment_mode: string;
  public_base_url: string;
  openhands_base: string;
  head_provider: string;
  allowed_head_providers: string[];
}

export interface RefallOpsInfra {
  deployment_mode: string;
  checks: { id: string; status: string }[];
}

export interface RefallDoctorCheck {
  id: string;
  status: string;
  summary: string;
  [key: string]: unknown;
}

export interface RefallDoctorPayload {
  status: string;
  subject?: string | null;
  checks: RefallDoctorCheck[];
}

export interface RefallEstimatePayload {
  subject: string;
  coverage: Record<string, unknown>;
  source_inventory: Record<string, unknown>;
  pending_actions_open: number;
  estimated_open_units: number;
  estimated_agent_tasks: number;
  missing_prerequisites: string[];
  dynamic_testing: string;
  [key: string]: unknown;
}

export interface RefallDoctorCommandResult {
  status: string;
  command: "doctor";
  subject?: string | null;
  doctor: RefallDoctorPayload;
  ledger_id?: string;
}

export interface RefallEstimateCommandResult {
  status: string;
  command: "estimate";
  subject: string;
  estimate: RefallEstimatePayload;
  ledger_id?: string;
}

export interface RefallCoverageStats {
  subject: string;
  lines_total: number;
  lines_covered: number;
  lines_dead: number;
  indexed_pct: number;
  characterized_pct: number;
  resolved_pct: number;
  files_total: number;
  files_done: number;
  symbols_total: number;
}

export interface RefallLedgerStats {
  workbench_slug: string;
  total: number;
  by_kind: Record<string, number>;
  by_lane: Record<string, number>;
  by_severity: Record<string, number>;
}

export interface RefallCoverageContext {
  subject: string;
  info_md: string | null;
  generated_by?: string | null;
  root_container?: string | null;
  updated_at?: number | null;
}

export interface RefallScopeOverlay {
  subject?: string;
  overlay_id?: string | null;
  local_roots: string[];
  lan_targets: Record<string, unknown>[];
  external_targets: Record<string, unknown>[];
  excluded_paths: Record<string, unknown>[];
  evidence_rules: string[];
  operator_notes: string;
  dynamic_testing?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface RefallThreatModel {
  subject?: string;
  threat_model_id?: string | null;
  assets: Record<string, unknown>[];
  ingress_points: Record<string, unknown>[];
  trust_boundaries: Record<string, unknown>[];
  threats: Record<string, unknown>[];
  hunt_prompts: string[];
  status: "active" | "skipped" | "superseded";
  created_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  [key: string]: unknown;
}

export interface RefallLedgerEntry {
  id: string;
  kind?: string;
  action?: string;
  title?: string;
  summary?: string;
  status?: string;
  lane?: string;
  provider?: string;
  created_at?: string;
  [key: string]: unknown;
}

export interface RefallPendingAction {
  id: string;
  kind: string;
  title: string;
  description?: string | null;
  priority?: string | null;
  status: string;
  source_event_id?: string | null;
  source_finding_id?: string | null;
  source_unit_id?: string | null;
  required_receipt_type?: string | null;
  assigned_lane?: string | null;
  claimed_by?: string | null;
  lease_expires_at?: number | null;
  resolution_receipt?: Record<string, unknown> | null;
  created_at?: number | null;
  updated_at?: number | null;
}

export interface RefallCloseoutGateCheck {
  id: string;
  status: string;
  count: number;
  blocking: boolean;
  overridden?: boolean;
  override_ledger_id?: string | null;
  override_reason?: string | null;
  details: unknown[];
}

export interface RefallCloseoutGate {
  subject: string;
  passed: boolean;
  severity: string;
  checks: RefallCloseoutGateCheck[];
  summary: Record<string, unknown>;
}

export interface RefallCapabilityState {
  subject: string;
  grants: Record<string, unknown>[];
  requests: Record<string, unknown>[];
}

export interface RefallCapabilityBody {
  class: string;
  scope?: Record<string, unknown>;
  reason?: string | null;
  granted_by?: string | null;
  requested_by?: string | null;
  expires_at?: number | null;
  dry_run_required?: boolean;
  destructive_token_required?: boolean;
}

export interface RefallRuntimeEvent {
  id: string;
  type: string;
  subject: string;
  workbench?: string | null;
  run_id?: string | null;
  task_id?: string | null;
  session_id?: string | null;
  payload?: Record<string, unknown>;
  artifact_refs?: string[];
  created_at?: number | null;
}

export interface RefallRuntimeArtifact {
  id: string;
  subject: string;
  run_id?: string | null;
  task_id?: string | null;
  kind: string;
  path: string;
  mime?: string | null;
  sha256?: string | null;
  size_bytes?: number | null;
  source_event_id?: string | null;
  workbench_object_id?: string | null;
  created_at?: number | null;
}

export interface RefallRuntimeObservation {
  id: string;
  source_event_id: string;
  subject: string;
  kind: string;
  claim?: string | null;
  evidence_refs?: string[];
  source_anchors?: string[];
  confidence?: string | null;
  limitations?: unknown[];
  created_at?: number | null;
}

export interface RefallNonfatalError {
  id: string;
  source: string;
  type: string;
  created_at?: number | string | null;
  run_id?: string | null;
  task_id?: string | null;
  session_id?: string | null;
  summary?: string | null;
  failure_class?: string | null;
  refusal_reasons?: string[];
  artifact_refs?: string[];
}

export interface RefallEvidenceGraph {
  nodes: Record<string, unknown>[];
  edges: Record<string, unknown>[];
}

export interface RefallSubjectCreate {
  subject: string;
  title?: string | null;
  description?: string;
  source_path?: string | null;
  tags?: string[];
}

export interface RefallSubjectCreateResponse {
  subject: string;
  workbench_slug: string;
  subject_path: string;
  created: boolean;
}

class HttpError extends Error {
  constructor(public status: number, public body: unknown, message: string) {
    super(message);
  }
}

async function req<T>(method: string, url: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(url, { method, ...init });
  if (!r.ok) {
    let body: unknown = null;
    try {
      body = await r.json();
    } catch {
      body = await r.text();
    }
    throw new HttpError(r.status, body, `${method} ${url} failed: ${r.status}`);
  }
  if (r.status === 204) return undefined as T;
  const ct = r.headers.get("content-type") || "";
  if (ct.includes("json")) return (await r.json()) as T;
  return (await r.text()) as unknown as T;
}

export const api = {
  // workbenches
  listWorkbenches: () => req<WorkbenchMeta[]>("GET", "/api/workbenches"),
  getWorkbench: (slug: string) => req<WorkbenchMeta>("GET", `/api/workbenches/${slug}`),
  createWorkbench: (body: { title: string; slug?: string; description?: string; tags?: string[]; url?: string; ip?: string; local_path?: string; }) =>
    req<WorkbenchMeta>("POST", "/api/workbenches", {
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),
  patchWorkbench: (slug: string, patch: Partial<WorkbenchMeta>) =>
    req<WorkbenchMeta>("PATCH", `/api/workbenches/${slug}`, {
      headers: { "content-type": "application/json" },
      body: JSON.stringify(patch),
    }),
  archiveWorkbench: (slug: string) =>
    req<{ archive: string }>("DELETE", `/api/workbenches/${slug}`),
  listTrash: () =>
    req<{ archive: string }[]>("GET", "/api/workbenches/_trash/list"),
  restoreWorkbench: (archive: string) =>
    req<{ slug: string }>("POST", "/api/workbenches/_trash/restore", {
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ archive }),
    }),
  duplicateWorkbench: (slug: string, newSlug?: string) =>
    req<WorkbenchMeta>("POST", `/api/workbenches/${slug}/duplicate`, {
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ new_slug: newSlug }),
    }),
  // Returns blob URLs for client-side download buttons.
  exportWorkbenchUrl: (slug: string) => `/api/workbenches/${slug}/export`,
  bannerUrl: (slug: string) => `/api/workbenches/${slug}/banner`,
  trashDownloadUrl: (archive: string) => `/api/workbenches/_trash/${encodeURIComponent(archive)}/download`,
  purgeTrash: (archive: string) =>
    req<void>("DELETE", `/api/workbenches/_trash/${encodeURIComponent(archive)}`),

  // Response export helpers
  latestPayload: (slug: string, oid: string) =>
    req<Record<string, unknown>>("GET", `/api/workbenches/${slug}/objects/${oid}/responses/latest/payload`),
  responsesExportUrl: (slug: string, oid: string) =>
    `/api/workbenches/${slug}/objects/${oid}/responses/export`,

  // Snapshots
  listSnapshots: (slug: string) =>
    req<{ name: string; label: string; size_bytes: number; created_at: string }[]>(
      "GET",
      `/api/workbenches/${slug}/snapshots`,
    ),
  createSnapshot: (slug: string, label: string) =>
    req<{ name: string; label: string; size_bytes: number; created_at: string }>(
      "POST",
      `/api/workbenches/${slug}/snapshot`,
      {
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ label }),
      },
    ),
  snapshotDownloadUrl: (slug: string, name: string) =>
    `/api/workbenches/${slug}/snapshots/${encodeURIComponent(name)}/download`,
  restoreSnapshot: (slug: string, name: string, newSlug: string) =>
    req<WorkbenchMeta>(
      "POST",
      `/api/workbenches/${slug}/snapshots/${encodeURIComponent(name)}/restore`,
      {
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ new_slug: newSlug }),
      },
    ),
  deleteSnapshot: (slug: string, name: string) =>
    req<void>(
      "DELETE",
      `/api/workbenches/${slug}/snapshots/${encodeURIComponent(name)}`,
    ),

  // Audit log + static export
  auditLogUrl: (slug: string, download = true) =>
    `/api/workbenches/${slug}/audit${download ? "?download=true" : ""}`,
  staticExportUrl: (slug: string) => `/api/workbenches/${slug}/static-export`,

  // Self-test
  agentSelfTest: () =>
    req<{
      pass: boolean;
      steps: { name: string; ok: boolean; elapsed_ms: number; detail: string }[];
      total_ms: number;
    }>("POST", "/api/agent/self-test"),

  // REFALL ops/control plane
  createRefallSubject: (body: RefallSubjectCreate) =>
    req<RefallSubjectCreateResponse>("POST", "/api/refall/subjects", {
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),
  refallOpsStatus: () => req<RefallOpsStatus>("GET", "/api/refall/ops/status"),
  refallOpsInfra: () => req<RefallOpsInfra>("GET", "/api/refall/ops/infra"),
  refallOpsFeedHistory: () =>
    req<{ events: Record<string, unknown>[] }>("GET", "/api/refall/ops/feed/history"),
  refallOpsDebug: (subject: string) =>
    req<Record<string, unknown>>("GET", `/api/refall/ops/debug/${encodeURIComponent(subject)}`),
  refallOpsDebugLive: (subject: string) =>
    req<Record<string, unknown>>("GET", `/api/refall/ops/debug/${encodeURIComponent(subject)}/live`),
  refallOpsCommand: (command: string) =>
    req<Record<string, unknown>>("POST", "/api/refall/ops/command", {
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ command }),
    }),
  refallDoctor: (subject: string) =>
    req<RefallDoctorCommandResult>("POST", "/api/refall/ops/command", {
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ command: `doctor ${subject}` }),
    }),
  refallEstimate: (subject: string) =>
    req<RefallEstimateCommandResult>("POST", "/api/refall/ops/command", {
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ command: `estimate ${subject}` }),
    }),
  refallGenerateContext: (slug: string, operatorInput = "") =>
    req<Record<string, unknown>>("POST", "/api/refall/ops/context/generate", {
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ slug, operator_input: operatorInput }),
    }),
  refallSaveContext: (slug: string, context: string) =>
    req<Record<string, unknown>>("POST", "/api/refall/ops/context/save", {
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ slug, context }),
    }),
  refallCoverageStats: (slug: string) =>
    req<RefallCoverageStats>("GET", `/api/workbenches/${slug}/coverage/stats`),
  refallCoverageContext: (slug: string) =>
    req<RefallCoverageContext>("GET", `/api/workbenches/${slug}/coverage/context`),
  refallScopeOverlay: (slug: string) =>
    req<RefallScopeOverlay>("GET", `/api/workbenches/${slug}/coverage/scope-overlay`),
  refallPutScopeOverlay: (slug: string, overlay: RefallScopeOverlay) =>
    req<RefallScopeOverlay>("PUT", `/api/workbenches/${slug}/coverage/scope-overlay`, {
      headers: { "content-type": "application/json" },
      body: JSON.stringify(overlay),
    }),
  refallThreatModel: (slug: string) =>
    req<RefallThreatModel>("GET", `/api/workbenches/${slug}/coverage/threat-model`),
  refallPutThreatModel: (slug: string, threatModel: RefallThreatModel) =>
    req<RefallThreatModel>("PUT", `/api/workbenches/${slug}/coverage/threat-model`, {
      headers: { "content-type": "application/json" },
      body: JSON.stringify(threatModel),
    }),
  refallLedgerStats: (slug: string) =>
    req<RefallLedgerStats>("GET", `/api/workbenches/${slug}/ledger/stats`),
  refallLedgerEntries: (slug: string) =>
    req<RefallLedgerEntry[]>("GET", `/api/workbenches/${slug}/ledger/entries`),
  refallPendingActions: (slug: string, includeTerminal = true) =>
    req<RefallPendingAction[]>(
      "GET",
      `/api/workbenches/${slug}/pending-actions?include_terminal=${includeTerminal ? "true" : "false"}`,
    ),
  refallClaimPendingAction: (slug: string, actionId: string, claimedBy = "refall-manager", leaseS = 900) =>
    req<RefallPendingAction>("POST", `/api/workbenches/${slug}/pending-actions/${actionId}/claim`, {
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ claimed_by: claimedBy, lease_s: leaseS }),
    }),
  refallResolvePendingAction: (
    slug: string,
    actionId: string,
    receipt: Record<string, unknown> = {},
    receiptType = "operator_receipt",
    resolvedBy = "refall-manager",
  ) =>
    req<RefallPendingAction>("POST", `/api/workbenches/${slug}/pending-actions/${actionId}/resolve`, {
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ resolved_by: resolvedBy, receipt_type: receiptType, receipt }),
    }),
  refallDeferPendingAction: (
    slug: string,
    actionId: string,
    receipt: Record<string, unknown> = {},
    receiptType = "operator_defer",
    resolvedBy = "refall-manager",
  ) =>
    req<RefallPendingAction>("POST", `/api/workbenches/${slug}/pending-actions/${actionId}/defer`, {
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ resolved_by: resolvedBy, receipt_type: receiptType, receipt }),
    }),
  refallCancelPendingAction: (
    slug: string,
    actionId: string,
    receipt: Record<string, unknown> = {},
    receiptType = "operator_cancel",
    resolvedBy = "refall-manager",
  ) =>
    req<RefallPendingAction>("POST", `/api/workbenches/${slug}/pending-actions/${actionId}/cancel`, {
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ resolved_by: resolvedBy, receipt_type: receiptType, receipt }),
    }),
  refallCloseoutGate: (slug: string) =>
    req<RefallCloseoutGate>("GET", `/api/workbenches/${slug}/closeout/gate`),
  refallCapabilities: (slug: string, includeRevoked = false) =>
    req<RefallCapabilityState>(
      "GET",
      `/api/workbenches/${slug}/capabilities?include_revoked=${includeRevoked ? "true" : "false"}`,
    ),
  refallRequestCapability: (slug: string, body: RefallCapabilityBody) =>
    req<Record<string, unknown>>("POST", `/api/workbenches/${slug}/capabilities/request`, {
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),
  refallGrantCapability: (slug: string, body: RefallCapabilityBody) =>
    req<Record<string, unknown>>("POST", `/api/workbenches/${slug}/capabilities/grant`, {
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),
  refallRevokeCapability: (slug: string, grantId: string) =>
    req<Record<string, unknown>>("POST", `/api/workbenches/${slug}/capabilities/revoke/${grantId}`),
  refallRuntimeEvents: (slug: string) =>
    req<RefallRuntimeEvent[]>("GET", `/api/workbenches/${slug}/runtime/events`),
  refallRuntimeArtifacts: (slug: string) =>
    req<RefallRuntimeArtifact[]>("GET", `/api/workbenches/${slug}/runtime/artifacts`),
  refallRuntimeObservations: (slug: string) =>
    req<RefallRuntimeObservation[]>("GET", `/api/workbenches/${slug}/runtime/observations`),
  refallRuntimeEvidenceGraph: (slug: string) =>
    req<RefallEvidenceGraph>("GET", `/api/workbenches/${slug}/runtime/evidence-graph`),
  refallNonfatalErrors: (slug: string) =>
    req<{ subject: string; count: number; errors: RefallNonfatalError[] }>(
      "GET",
      `/api/workbenches/${slug}/runtime/nonfatal-errors`,
    ),
  refallNonfatalErrorsNdjsonUrl: (slug: string) =>
    `/api/workbenches/${slug}/runtime/nonfatal-errors.ndjson`,
  refallProjectRuntime: (slug: string) =>
    req<Record<string, unknown>>("POST", `/api/workbenches/${slug}/runtime/project`),

  reorderWorkbenches: (slugs: string[]) =>
    req<void>("POST", "/api/workbenches/_reorder", {
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ slugs }),
    }),
  reorderObjects: (slug: string, ids: string[]) =>
    req<void>("POST", `/api/workbenches/${slug}/objects/_reorder`, {
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ids }),
    }),

  uploadThemeAsset: async (slug: string, path: string, file: File): Promise<void> => {
    const fd = new FormData();
    fd.set("upload", file);
    const r = await fetch(`/api/workbenches/${slug}/theme/assets/${encodeURIComponent(path)}`, {
      method: "PUT",
      body: fd,
    });
    if (!r.ok) throw new Error(`upload failed: ${r.status}`);
  },

  agentActivity: (limit = 100, agentOnly = true) =>
    req<{ events: { ts: number; method: string; path: string; status: number; elapsed_ms: number; request_id: string; is_agent: boolean }[] }>(
      "GET",
      `/api/agent/activity?limit=${limit}&agent_only=${agentOnly}`,
    ),

  // theme
  getTheme: (slug: string) => req<Theme>("GET", `/api/workbenches/${slug}/theme`),
  getThemeRaw: (slug: string) => req<string>("GET", `/api/workbenches/${slug}/theme/raw`),
  putTheme: (slug: string, raw: string) =>
    req<Theme>("PUT", `/api/workbenches/${slug}/theme`, {
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ raw }),
    }),

  // objects
  listObjects: (slug: string, opts?: { includeArchived?: boolean }) =>
    req<ObjectMeta[]>(
      "GET",
      `/api/workbenches/${slug}/objects${opts?.includeArchived ? "?include_archived=true" : ""}`,
    ),
  getObject: (slug: string, oid: string) =>
    req<ObjectMeta>("GET", `/api/workbenches/${slug}/objects/${oid}`),
  createObject: (slug: string, body: { kind: ObjectKind; title: string; description?: string; drawer?: string; filename?: string; mime?: string; }) =>
    req<ObjectMeta>("POST", `/api/workbenches/${slug}/objects`, {
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),
  uploadObject: async (
    slug: string,
    meta: { kind: ObjectKind; title: string; description?: string; drawer?: string; },
    file: File,
  ): Promise<ObjectMeta> => {
    const fd = new FormData();
    fd.set("meta", JSON.stringify(meta));
    fd.set("file", file);
    return req<ObjectMeta>("POST", `/api/workbenches/${slug}/objects`, { body: fd });
  },
  patchObject: (slug: string, oid: string, patch: Partial<ObjectMeta>) =>
    req<ObjectMeta>("PATCH", `/api/workbenches/${slug}/objects/${oid}`, {
      headers: { "content-type": "application/json" },
      body: JSON.stringify(patch),
    }),
  deleteObject: (slug: string, oid: string) =>
    req<void>("DELETE", `/api/workbenches/${slug}/objects/${oid}`),

  getObjectContentText: async (slug: string, oid: string): Promise<{ text: string; etag: string }> => {
    const r = await fetch(`/api/workbenches/${slug}/objects/${oid}/content`);
    if (!r.ok) throw new HttpError(r.status, null, `content fetch failed: ${r.status}`);
    return { text: await r.text(), etag: r.headers.get("etag") || "" };
  },
  getObjectContentBlob: async (slug: string, oid: string): Promise<{ blob: Blob; etag: string }> => {
    const r = await fetch(`/api/workbenches/${slug}/objects/${oid}/content`);
    if (!r.ok) throw new HttpError(r.status, null, `content fetch failed: ${r.status}`);
    return { blob: await r.blob(), etag: r.headers.get("etag") || "" };
  },
  putObjectContent: (slug: string, oid: string, body: BodyInit, ifMatch?: string) =>
    req<{ meta: ObjectMeta; etag: string }>("PUT", `/api/workbenches/${slug}/objects/${oid}/content`, {
      headers: ifMatch ? { "if-match": ifMatch } : {},
      body,
    }),

  // responses
  listResponses: (slug: string, oid: string, sinceVersion = 0) =>
    req<ResponseEvent[]>("GET", `/api/workbenches/${slug}/objects/${oid}/responses?since_version=${sinceVersion}`),
  latestResponse: (slug: string, oid: string) =>
    req<ResponseEvent | null>("GET", `/api/workbenches/${slug}/objects/${oid}/responses/latest`),
  appendResponse: (slug: string, oid: string, body: { kind: ResponseKind; payload: unknown; submitted_by?: Submitter }) =>
    req<ResponseEvent>("POST", `/api/workbenches/${slug}/objects/${oid}/responses`, {
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),
};
