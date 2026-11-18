<script lang="ts">
  import { onMount } from "svelte";
  import {
    api,
    type RefallCapabilityState,
    type RefallCloseoutGate,
    type RefallCoverageContext,
    type RefallCoverageStats,
    type RefallDoctorPayload,
    type RefallEvidenceGraph,
    type RefallEstimatePayload,
    type RefallLedgerEntry,
    type RefallLedgerStats,
    type RefallNonfatalError,
    type RefallPendingAction,
    type RefallRuntimeArtifact,
	    type RefallRuntimeEvent,
	    type RefallRuntimeObservation,
	    type RefallScopeOverlay,
	    type RefallThreatModel,
	  } from "../api";

  export let slug: string;
  export let subject: string;
  export let launchPath: string | null = null;
  export let sourcePath: string | null = null;

	  type View =
	    | "debug"
	    | "readiness"
	    | "context"
	    | "scope"
	    | "threat"
	    | "pending"
    | "runtime"
    | "artifacts"
    | "capabilities"
    | "closeout"
    | "ledger"
    | "output"
    | "logs";

  let debug: Record<string, unknown> | null = null;
  let live: Record<string, unknown> | null = null;
  let coverage: RefallCoverageStats | null = null;
	  let context: RefallCoverageContext | null = null;
	  let scopeOverlay: RefallScopeOverlay | null = null;
	  let threatModel: RefallThreatModel | null = null;
	  let ledger: RefallLedgerStats | null = null;
  let ledgerEntries: RefallLedgerEntry[] = [];
  let pendingActions: RefallPendingAction[] = [];
  let closeoutGate: RefallCloseoutGate | null = null;
  let capabilities: RefallCapabilityState | null = null;
  let runtimeEvents: RefallRuntimeEvent[] = [];
  let runtimeArtifacts: RefallRuntimeArtifact[] = [];
  let runtimeObservations: RefallRuntimeObservation[] = [];
  let nonfatalErrors: RefallNonfatalError[] = [];
  let nonfatalProjection: { errors?: RefallNonfatalError[] } | null = null;
  let evidenceGraph: RefallEvidenceGraph | null = null;
  let commandResult: Record<string, unknown> | null = null;
  let doctorResult: RefallDoctorPayload | null = null;
  let estimateResult: RefallEstimatePayload | null = null;
  let disabled = false;
  let error: string | null = null;
  let busy: string | null = null;
  let activeView: View = "context";
  let operatorInput = "";
  let contextText = "";
  let contextDirty = false;
	  let scopeText = "";
	  let scopeDirty = false;
	  let threatText = "";
	  let threatDirty = false;
  let capabilityPresetInput = "loop-launch";
  let capabilityClassInput = "lan_network_probe";
  let capabilityReason = "";
  let capabilityScopeText = '{ "hosts": ["192.0.2.10"], "ports": [80, 81] }';
  let capabilityDryRunRequired = true;
  let capabilityDestructiveTokenRequired = false;

  onMount(() => {
    applyCapabilityPreset();
    void load();
  });

  async function load() {
    error = null;
    try {
      [
        debug,
        live,
	        coverage,
	        context,
	        scopeOverlay,
	        threatModel,
	        ledger,
        ledgerEntries,
        pendingActions,
        closeoutGate,
        capabilities,
        runtimeEvents,
        runtimeArtifacts,
        runtimeObservations,
        nonfatalProjection,
        evidenceGraph,
      ] = await Promise.all([
        api.refallOpsDebug(subject),
        api.refallOpsDebugLive(subject),
	        api.refallCoverageStats(slug),
	        api.refallCoverageContext(slug),
	        api.refallScopeOverlay(slug),
	        api.refallThreatModel(slug),
	        api.refallLedgerStats(slug),
        api.refallLedgerEntries(slug),
        api.refallPendingActions(slug),
        api.refallCloseoutGate(slug),
        api.refallCapabilities(slug),
        api.refallRuntimeEvents(slug),
        api.refallRuntimeArtifacts(slug),
        api.refallRuntimeObservations(slug),
        api.refallNonfatalErrors(slug),
        api.refallRuntimeEvidenceGraph(slug),
      ]);
      nonfatalErrors = nonfatalProjection?.errors || [];
	      if (!contextDirty) contextText = context?.info_md || "";
	      if (!scopeDirty) scopeText = jsonString(scopeOverlay || defaultScopeOverlay());
	      if (!threatDirty) threatText = jsonString(threatModel || defaultThreatModel());
    } catch (e) {
      const msg = String(e);
      disabled = msg.includes("404");
      if (!disabled) error = msg;
    }
  }

  async function runCommand(
    action: "start" | "update" | "closeout" | "logs",
    options: { autoGrantLoopLaunch?: boolean } = {},
  ) {
    busy = action;
    error = null;
    try {
      if (action === "start" && options.autoGrantLoopLaunch) {
        await ensureLoopLaunchGrant();
      }
      commandResult = await api.refallOpsCommand(`${action} ${subject}`);
      if (action === "logs") activeView = "logs";
      if (action === "closeout") activeView = "closeout";
      await load();
    } catch (e) {
      error = String(e);
    } finally {
      busy = null;
    }
  }

  async function runDoctor() {
    busy = "doctor";
    error = null;
    try {
      const result = await api.refallDoctor(subject);
      commandResult = result as unknown as Record<string, unknown>;
      doctorResult = result.doctor;
      activeView = "readiness";
      await load();
    } catch (e) {
      error = String(e);
    } finally {
      busy = null;
    }
  }

  async function runEstimate() {
    busy = "estimate";
    error = null;
    try {
      const result = await api.refallEstimate(subject);
      commandResult = result as unknown as Record<string, unknown>;
      estimateResult = result.estimate;
      doctorResult = result.estimate.doctor as RefallDoctorPayload | null;
      activeView = "readiness";
      await load();
    } catch (e) {
      error = String(e);
    } finally {
      busy = null;
    }
  }

  async function generateContext() {
    busy = "context";
    error = null;
    try {
      commandResult = await api.refallGenerateContext(slug, operatorInput);
      const next = commandResult.context as RefallCoverageContext | undefined;
      if (next) {
        context = next;
        contextText = next.info_md || "";
        contextDirty = false;
      }
      activeView = "context";
      await load();
    } catch (e) {
      error = String(e);
    } finally {
      busy = null;
    }
  }

  async function saveContext() {
    busy = "save-context";
    error = null;
    try {
      commandResult = await api.refallSaveContext(slug, contextText);
      const next = commandResult.context as RefallCoverageContext | undefined;
      if (next) {
        context = next;
        contextText = next.info_md || "";
        contextDirty = false;
      }
      activeView = "context";
      await load();
    } catch (e) {
      error = String(e);
    } finally {
      busy = null;
    }
  }

	  async function saveScopeOverlay() {
	    busy = "save-scope";
	    error = null;
	    try {
	      const parsed = JSON.parse(scopeText || "{}") as RefallScopeOverlay;
      commandResult = await api.refallPutScopeOverlay(slug, parsed) as unknown as Record<string, unknown>;
      scopeOverlay = commandResult as unknown as RefallScopeOverlay;
      scopeText = jsonString(scopeOverlay);
      scopeDirty = false;
      activeView = "scope";
      await load();
    } catch (e) {
      error = String(e);
    } finally {
	      busy = null;
	    }
	  }

	  async function saveThreatModel() {
	    busy = "save-threat";
	    error = null;
	    try {
	      const parsed = JSON.parse(threatText || "{}") as RefallThreatModel;
	      commandResult = await api.refallPutThreatModel(slug, parsed) as unknown as Record<string, unknown>;
	      threatModel = commandResult as unknown as RefallThreatModel;
	      threatText = jsonString(threatModel);
	      threatDirty = false;
	      activeView = "threat";
	      await load();
	    } catch (e) {
	      error = String(e);
	    } finally {
	      busy = null;
	    }
	  }

	  async function requestThreatModel() {
	    busy = "threat-model";
	    error = null;
	    try {
	      commandResult = await api.refallOpsCommand(`threat-model ${subject}`);
	      activeView = "threat";
	      await load();
	    } catch (e) {
	      error = String(e);
	    } finally {
	      busy = null;
	    }
	  }

  async function projectRuntime() {
    busy = "project-runtime";
    error = null;
    try {
      commandResult = await api.refallProjectRuntime(slug);
      activeView = "runtime";
      await load();
    } catch (e) {
      error = String(e);
    } finally {
      busy = null;
    }
  }

  async function claimPending(action: RefallPendingAction) {
    busy = `claim:${action.id}`;
    error = null;
    try {
      commandResult = await api.refallClaimPendingAction(slug, action.id) as unknown as Record<string, unknown>;
      activeView = "pending";
      await load();
    } catch (e) {
      error = String(e);
    } finally {
      busy = null;
    }
  }

  async function finishPending(action: RefallPendingAction, outcome: "done" | "deferred" | "cancelled") {
    const note = window.prompt(`${outcome} receipt`, "");
    if (note === null) return;
    busy = `${outcome}:${action.id}`;
    error = null;
    const receiptText = note.trim() || `${outcome}:${action.id}`;
    const receiptType = action.required_receipt_type || (
      outcome === "done" ? "operator_receipt" : outcome === "deferred" ? "operator_defer" : "operator_cancel"
    );
    const receipt = {
      summary: receiptText,
      evidence_refs: [receiptText],
      pending_action_id: action.id,
      pending_action_kind: action.kind,
      recorded_by: "refall-ops-panel",
      recorded_at: new Date().toISOString(),
    };
    try {
      if (outcome === "done") {
        commandResult = await api.refallResolvePendingAction(slug, action.id, receipt, receiptType) as unknown as Record<string, unknown>;
      } else if (outcome === "deferred") {
        commandResult = await api.refallDeferPendingAction(slug, action.id, receipt, receiptType) as unknown as Record<string, unknown>;
      } else {
        commandResult = await api.refallCancelPendingAction(slug, action.id, receipt, receiptType) as unknown as Record<string, unknown>;
      }
      activeView = "pending";
      await load();
    } catch (e) {
      error = String(e);
    } finally {
      busy = null;
    }
  }

  async function requestCapability() {
    await submitCapability("request");
  }

  async function grantCapability() {
    await submitCapability("grant");
  }

  async function ensureLoopLaunchGrant() {
    const current = await api.refallCapabilities(slug);
    capabilities = current;
    if (hasLoopLaunchGrant(current)) return;
    await api.refallGrantCapability(slug, loopLaunchGrantPayload());
    capabilities = await api.refallCapabilities(slug);
  }

  async function submitCapability(mode: "request" | "grant") {
    busy = `capability-${mode}`;
    error = null;
    try {
      const body = capabilityPayload();
      commandResult =
        mode === "request"
          ? await api.refallRequestCapability(slug, body)
          : await api.refallGrantCapability(slug, body);
      activeView = "capabilities";
      capabilityReason = "";
      await load();
    } catch (e) {
      error = String(e);
    } finally {
      busy = null;
    }
  }

  async function revokeCapability(grant: Record<string, unknown>) {
    const grantId = String(grant.id || "");
    if (!grantId) return;
    busy = `revoke:${grantId}`;
    error = null;
    try {
      commandResult = await api.refallRevokeCapability(slug, grantId);
      activeView = "capabilities";
      await load();
    } catch (e) {
      error = String(e);
    } finally {
      busy = null;
    }
  }

  function capabilityPayload() {
    const capabilityClass = capabilityClassInput.trim();
    if (!capabilityClass) throw new Error("Capability class is required.");
    let scope: Record<string, unknown>;
    try {
      scope = JSON.parse(capabilityScopeText || "{}") as Record<string, unknown>;
    } catch {
      throw new Error("Capability scope must be valid JSON.");
    }
    return {
      class: capabilityClass,
      scope,
      reason: capabilityReason.trim() || null,
      granted_by: "refall-ops-panel",
      requested_by: "refall-ops-panel",
      dry_run_required: capabilityDryRunRequired,
      destructive_token_required: capabilityDestructiveTokenRequired,
    };
  }

  function applyCapabilityPreset() {
    if (capabilityPresetInput === "loop-launch") {
      const path = loopLaunchPath();
      capabilityClassInput = "run_local_command";
      capabilityReason = `Operator approved REFALL loop launch for ${subject}`;
      capabilityScopeText = jsonString({ paths: path ? [path] : [] });
      capabilityDryRunRequired = false;
      capabilityDestructiveTokenRequired = false;
    } else if (capabilityPresetInput === "lan-probe") {
      capabilityClassInput = "lan_network_probe";
      capabilityReason = "Operator approved scoped LAN probing for this subject";
      capabilityScopeText = '{ "hosts": ["192.0.2.10"], "ports": [80, 81] }';
      capabilityDryRunRequired = true;
      capabilityDestructiveTokenRequired = false;
    }
  }

  function loopLaunchPath(): string {
    return String(launchPath || sourcePath || "").trim();
  }

  function loopLaunchGrantPayload() {
    const path = loopLaunchPath();
    if (!path) throw new Error("Loop launch path is not recorded on this workbench.");
    return {
      class: "run_local_command",
      scope: { paths: [path] },
      reason: `Operator approved REFALL loop launch for ${subject}`,
      granted_by: "refall-ops-panel",
      requested_by: "refall-ops-panel",
      dry_run_required: false,
      destructive_token_required: false,
    };
  }

  function hasLoopLaunchGrant(state: RefallCapabilityState | null = capabilities): boolean {
    const path = loopLaunchPath();
    if (!path) return false;
    return Boolean(
      state?.grants?.some((grant) => {
        const scope = grant.scope as { paths?: unknown[] } | undefined;
        const paths = Array.isArray(scope?.paths) ? scope.paths.map((item) => String(item)) : [];
        return (
          String(grant["class"] || "") === "run_local_command" &&
          !grant.revoked_at &&
          paths.includes(path) &&
          !grant.dry_run_required &&
          !grant.destructive_token_required
        );
      }),
    );
  }

  function logs(): { path?: string; tail?: string[] }[] {
    const raw = commandResult?.logs;
    return Array.isArray(raw) ? raw as { path?: string; tail?: string[] }[] : [];
  }

  function loopResult(): Record<string, unknown> | null {
    const raw = commandResult?.loop;
    return raw && typeof raw === "object" ? raw as Record<string, unknown> : null;
  }

  function titleFor(entry: RefallLedgerEntry): string {
    return entry.action || entry.title || entry.kind || entry.id;
  }

  // ---- Output view: facts / leads / findings only -------------------------
  const OUTPUT_KINDS = ["fact", "lead", "finding"] as const;
  type OutputKind = (typeof OUTPUT_KINDS)[number];
  let outputFilter: "all" | OutputKind = "all";
  let expandedOutput: Record<string, boolean> = {};

  function toggleOutput(id: string): void {
    expandedOutput[id] = !expandedOutput[id];
    expandedOutput = expandedOutput;
  }

  function ostr(v: unknown): string {
    if (v == null) return "";
    if (typeof v === "string") return v;
    if (typeof v === "number" || typeof v === "boolean") return String(v);
    return "";
  }

  function oarr(v: unknown): string[] {
    if (Array.isArray(v)) return v.map((x) => ostr(x) || JSON.stringify(x)).filter(Boolean);
    return [];
  }

  function sevOf(entry: RefallLedgerEntry): string {
    const s = ostr(entry.severity).toLowerCase();
    return ["critical", "high", "medium", "low", "info"].includes(s) ? s : "";
  }

  function outputTitle(entry: RefallLedgerEntry): string {
    return ostr(entry.title) || ostr(entry.action) || ostr(entry.summary) || entry.id;
  }

  function outputDesc(entry: RefallLedgerEntry): string {
    return (
      ostr(entry.description) ||
      ostr(entry.summary) ||
      ostr(entry.impact) ||
      ostr((entry as Record<string, unknown>).claim) ||
      ""
    );
  }

  function outputAnchors(entry: RefallLedgerEntry): string[] {
    return [
      ...oarr((entry as Record<string, unknown>).code_paths),
      ...oarr((entry as Record<string, unknown>).source_anchors),
      ...oarr((entry as Record<string, unknown>).artifact_refs),
    ];
  }

  $: outputEntries = ledgerEntries.filter((e) =>
    OUTPUT_KINDS.includes(String(e.kind) as OutputKind),
  );
  $: outputCounts = {
    fact: outputEntries.filter((e) => e.kind === "fact").length,
    lead: outputEntries.filter((e) => e.kind === "lead").length,
    finding: outputEntries.filter((e) => e.kind === "finding").length,
  };
  // newest first; findings surfaced above leads above facts within the "all" view
  $: shownOutput = (
    outputFilter === "all"
      ? outputEntries
      : outputEntries.filter((e) => e.kind === outputFilter)
  )
    .slice()
    .reverse();

  function terminal(status: string): boolean {
    return ["done", "deferred", "cancelled"].includes(status);
  }

  function jsonString(value: unknown): string {
    return JSON.stringify(value ?? {}, null, 2);
  }

	  function defaultScopeOverlay(): RefallScopeOverlay {
	    return {
	      local_roots: [],
	      lan_targets: [],
	      external_targets: [],
      excluded_paths: [],
      evidence_rules: [],
      operator_notes: "",
	      dynamic_testing: {},
	    };
	  }

	  function defaultThreatModel(): RefallThreatModel {
	    return {
	      assets: [],
	      ingress_points: [],
	      trust_boundaries: [],
	      threats: [],
	      hunt_prompts: [],
	      status: "skipped",
	    };
	  }

  function timeLabel(value?: number | null): string {
    if (!value) return "";
    return new Date(value * 1000).toLocaleString();
  }

  function eventSummary(event: RefallRuntimeEvent): string {
    const summary = event.payload?.summary;
    return typeof summary === "string" && summary.trim() ? summary : event.type;
  }

  function nonfatalCreatedAt(error: RefallNonfatalError): string {
    const value = error.created_at;
    if (typeof value === "number") return timeLabel(value);
    return value ? String(value) : "";
  }

  function capabilityId(item: Record<string, unknown>): string {
    return String(item.id || item["class"] || "capability");
  }

  function capabilityClass(item: Record<string, unknown>): string {
    return String(item["class"] || "capability");
  }

  function capabilityStatus(item: Record<string, unknown>): string {
    return String(item.status || (item.revoked_at ? "revoked" : "active"));
  }

  $: hasStoredContext = !!context?.info_md?.trim();
  $: openPendingCount = pendingActions.filter((action) => ["open", "claimed"].includes(action.status)).length;
  $: blockingCloseoutCount = closeoutGate
    ? closeoutGate.checks.filter((check) => check.blocking && check.status === "fail").length
    : 0;
  $: gateLabel = closeoutGate ? (closeoutGate.passed ? "pass" : "blocked") : "unknown";
</script>

<section class="ops-panel" aria-label="REFALL workbench ops">
  <div class="panel-head">
    <div>
      <h2>REFALL Ops</h2>
      <p>{subject}</p>
    </div>
    <button class="secondary" on:click={load} disabled={!!busy}>Refresh</button>
  </div>

  {#if disabled}
    <p class="muted">Ops is disabled for this deployment.</p>
  {:else}
    <div class="actions" aria-label="REFALL loop actions">
      <button on:click={() => runCommand("start", { autoGrantLoopLaunch: true })} disabled={!!busy || !hasStoredContext} title={hasStoredContext ? "Start loop" : "Generate and save context first"}>Start Loop</button>
      <button on:click={() => runCommand("update")} disabled={!!busy}>Update</button>
      <button class="secondary" on:click={runDoctor} disabled={!!busy}>Doctor</button>
      <button class="secondary" on:click={runEstimate} disabled={!!busy}>Estimate</button>
	      <button on:click={generateContext} disabled={!!busy}>Generate Context</button>
	      <button on:click={requestThreatModel} disabled={!!busy || !hasStoredContext}>Threat Model</button>
	      <button on:click={projectRuntime} disabled={!!busy}>Project Runtime</button>
      <button on:click={() => runCommand("closeout")} disabled={!!busy}>Closeout</button>
      <button class="secondary" on:click={() => runCommand("logs")} disabled={!!busy}>Logs</button>
    </div>
    {#if busy}<p class="muted">running {busy} {subject}</p>{/if}
    {#if error}<p class="error">{error}</p>{/if}
    {#if loopResult()}
      <p class="muted">
        loop {loopResult()?.status}
        {#if loopResult()?.pid} pid {loopResult()?.pid}{/if}
        {#if loopResult()?.log} log {loopResult()?.log}{/if}
      </p>
    {/if}

    <div class="metrics">
      <div><b>{coverage?.resolved_pct ?? 0}%</b><span>resolved coverage</span></div>
      <div><b>{coverage?.symbols_total ?? 0}</b><span>symbols</span></div>
      <div><b>{ledger?.total ?? 0}</b><span>ledger entries</span></div>
      <div><b>{openPendingCount}</b><span>open pending</span></div>
      <div><b>{gateLabel}</b><span>closeout gate</span></div>
      <div><b>{String(live?.live ?? false)}</b><span>live debug</span></div>
    </div>

    <div class="tabs" aria-label="REFALL ops views">
	      <button class:active={activeView === "readiness"} on:click={() => (activeView = "readiness")}>Readiness</button>
	      <button class:active={activeView === "context"} on:click={() => (activeView = "context")}>Context</button>
	      <button class:active={activeView === "scope"} on:click={() => (activeView = "scope")}>Scope</button>
	      <button class:active={activeView === "threat"} on:click={() => (activeView = "threat")}>Threat Model</button>
	      <button class:active={activeView === "pending"} on:click={() => (activeView = "pending")}>Pending</button>
      <button class:active={activeView === "runtime"} on:click={() => (activeView = "runtime")}>Runtime</button>
      <button class:active={activeView === "artifacts"} on:click={() => (activeView = "artifacts")}>Artifacts</button>
      <button class:active={activeView === "capabilities"} on:click={() => (activeView = "capabilities")}>Capabilities</button>
      <button class:active={activeView === "closeout"} on:click={() => (activeView = "closeout")}>Closeout</button>
      <button class:active={activeView === "ledger"} on:click={() => (activeView = "ledger")}>Ledger</button>
      <button class:active={activeView === "output"} on:click={() => (activeView = "output")}>Output</button>
      <button class:active={activeView === "logs"} on:click={() => (activeView = "logs")}>Logs</button>
      <button class:active={activeView === "debug"} on:click={() => (activeView = "debug")}>Debug</button>
    </div>

    {#if activeView === "readiness"}
      <div class="view-head">
        <span>Doctor {doctorResult?.status || "not run"} {estimateResult ? `estimate ${estimateResult.estimated_agent_tasks} tasks` : ""}</span>
        <div class="view-actions">
          <button class="secondary" on:click={runDoctor} disabled={!!busy}>Doctor</button>
          <button class="secondary" on:click={runEstimate} disabled={!!busy}>Estimate</button>
        </div>
      </div>
      {#if doctorResult?.checks?.length}
        <ul class="item-list">
          {#each doctorResult.checks as check}
            <li>
              <div class="item-head">
                <strong>{check.id}</strong>
                <span class="badge">{check.status}</span>
              </div>
              <p>{check.summary}</p>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted">Run Doctor or Estimate to load readiness checks.</p>
      {/if}
      {#if estimateResult}
        <h3>Estimate</h3>
        <pre>{jsonString(estimateResult)}</pre>
      {/if}
    {:else if activeView === "context"}
      <div class="view-head">
        <span>{context?.generated_by || "no generator recorded"}</span>
        <div class="view-actions">
          <button class="secondary" on:click={generateContext} disabled={!!busy}>Generate</button>
          <button class="secondary" on:click={saveContext} disabled={!!busy || !contextText.trim()}>Save</button>
        </div>
      </div>
      <textarea
        class="operator-input"
        bind:value={operatorInput}
        placeholder="Operator directives"
        rows="4"
      ></textarea>
      <textarea
        class="context-editor"
        bind:value={contextText}
        on:input={() => (contextDirty = true)}
        placeholder="context.md"
        rows="18"
      ></textarea>
      {#if !context?.info_md}
        <p class="muted">No context has been stored for this subject.</p>
      {/if}
    {:else if activeView === "scope"}
      <div class="view-head">
        <span>{scopeOverlay?.overlay_id || "unsaved scope overlay"}</span>
        <button class="secondary" on:click={saveScopeOverlay} disabled={!!busy || !scopeText.trim()}>Save Scope</button>
      </div>
	      <textarea
	        class="context-editor"
	        bind:value={scopeText}
	        on:input={() => (scopeDirty = true)}
	        placeholder="scope overlay JSON"
	        rows="18"
	      ></textarea>
	    {:else if activeView === "threat"}
	      <div class="view-head">
	        <span>{threatModel?.status === "active" ? threatModel?.threat_model_id : "no active threat model"}</span>
	        <div class="view-actions">
	          <button class="secondary" on:click={requestThreatModel} disabled={!!busy || !hasStoredContext}>Request</button>
	          <button class="secondary" on:click={saveThreatModel} disabled={!!busy || !threatText.trim()}>Save Threat Model</button>
	        </div>
	      </div>
	      <textarea
	        class="context-editor"
	        bind:value={threatText}
	        on:input={() => (threatDirty = true)}
	        placeholder="threat model JSON"
	        rows="18"
	      ></textarea>
	    {:else if activeView === "pending"}
      {#if pendingActions.length}
        <ul class="item-list">
          {#each pendingActions as action}
            <li>
              <div class="item-head">
                <strong>{action.title}</strong>
                <span class="badge">{action.status}</span>
              </div>
              <p>{action.kind} {action.priority ? `priority:${action.priority}` : ""}</p>
              {#if action.description}<p>{action.description}</p>{/if}
              {#if action.source_finding_id}<p>finding {action.source_finding_id}</p>{/if}
              <div class="row-actions">
                <button class="secondary" on:click={() => claimPending(action)} disabled={!!busy || action.status !== "open"}>Claim</button>
                <button class="secondary" on:click={() => finishPending(action, "done")} disabled={!!busy || terminal(action.status)}>Resolve</button>
                <button class="secondary" on:click={() => finishPending(action, "deferred")} disabled={!!busy || terminal(action.status)}>Defer</button>
                <button class="secondary" on:click={() => finishPending(action, "cancelled")} disabled={!!busy || terminal(action.status)}>Cancel</button>
              </div>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted">No pending actions are recorded for this subject.</p>
      {/if}
    {:else if activeView === "runtime"}
      <div class="view-head">
        <span>{runtimeEvents.length} events, {runtimeObservations.length} projected observations, {nonfatalErrors.length} nonfatal errors</span>
        <div class="view-actions">
          <a href={api.refallNonfatalErrorsNdjsonUrl(slug)} target="_blank" rel="noopener">NDJSON</a>
          <button class="secondary" on:click={projectRuntime} disabled={!!busy}>Project Runtime</button>
        </div>
      </div>
      <h3>Nonfatal Errors</h3>
      {#if nonfatalErrors.length}
        <ul class="item-list">
          {#each nonfatalErrors.slice(0, 40) as item}
            <li>
              <div class="item-head">
                <strong>{item.summary || item.type}</strong>
                <span class="badge">{item.source}</span>
              </div>
              <p>{item.type} {item.failure_class || ""} {nonfatalCreatedAt(item)}</p>
              {#if item.artifact_refs?.length}<p>artifacts {item.artifact_refs.join(", ")}</p>{/if}
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted">No nonfatal runtime errors are projected.</p>
      {/if}
      {#if runtimeObservations.length}
        <h3>Observations</h3>
        <ul class="item-list">
          {#each runtimeObservations.slice(0, 80) as observation}
            <li>
              <div class="item-head">
                <strong>{observation.claim || observation.kind}</strong>
                <span class="badge">{observation.confidence || "unknown"}</span>
              </div>
              <p>{observation.kind} {timeLabel(observation.created_at)}</p>
              {#if observation.evidence_refs?.length}<p>evidence {observation.evidence_refs.join(", ")}</p>{/if}
            </li>
          {/each}
        </ul>
      {/if}
      <h3>Events</h3>
      {#if runtimeEvents.length}
        <ul class="item-list">
          {#each runtimeEvents.slice(0, 80) as event}
            <li>
              <div class="item-head">
                <strong>{eventSummary(event)}</strong>
                <span class="badge">{event.type}</span>
              </div>
              <p>{timeLabel(event.created_at)} {event.task_id || ""}</p>
              {#if event.artifact_refs?.length}<p>artifacts {event.artifact_refs.join(", ")}</p>{/if}
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted">No runtime events have been appended.</p>
      {/if}
      <h3>Evidence Graph</h3>
      <pre>{jsonString(evidenceGraph || { nodes: [], edges: [] })}</pre>
    {:else if activeView === "artifacts"}
      {#if runtimeArtifacts.length}
        <ul class="item-list">
          {#each runtimeArtifacts as artifact}
            <li>
              <div class="item-head">
                <strong>{artifact.kind}</strong>
                <span class="badge">{artifact.size_bytes ?? 0} bytes</span>
              </div>
              <p>{artifact.path}</p>
              {#if artifact.sha256}<p>sha256 {artifact.sha256}</p>{/if}
              {#if artifact.workbench_object_id}<p>object {artifact.workbench_object_id}</p>{/if}
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted">No runtime artifacts have been recorded.</p>
      {/if}
    {:else if activeView === "capabilities"}
      <div class="capability-form">
        <label>
          <span>Preset</span>
          <select bind:value={capabilityPresetInput} on:change={applyCapabilityPreset}>
            <option value="loop-launch">Loop launch for this subject</option>
            <option value="lan-probe">LAN dynamic probe</option>
            <option value="custom">Custom</option>
          </select>
        </label>
        <label>
          <span>Class</span>
          <input bind:value={capabilityClassInput} />
        </label>
        <label>
          <span>Reason</span>
          <input bind:value={capabilityReason} />
        </label>
        <label class="wide">
          <span>Scope JSON</span>
          <textarea bind:value={capabilityScopeText} rows="5"></textarea>
        </label>
        <label class="check">
          <input type="checkbox" bind:checked={capabilityDryRunRequired} />
          <span>Dry run required</span>
        </label>
        <label class="check">
          <input type="checkbox" bind:checked={capabilityDestructiveTokenRequired} />
          <span>Destructive token required</span>
        </label>
        <div class="form-actions">
          <button class="secondary" on:click={requestCapability} disabled={!!busy}>Request</button>
          <button on:click={grantCapability} disabled={!!busy}>Grant</button>
        </div>
      </div>
      <h3>Grants</h3>
      {#if capabilities?.grants.length}
        <ul class="item-list">
          {#each capabilities.grants as grant}
            <li>
              <div class="item-head">
                <strong>{capabilityClass(grant)}</strong>
                <span class="badge">{capabilityStatus(grant)}</span>
              </div>
              <p>{capabilityId(grant)}</p>
              <pre>{jsonString(grant.scope)}</pre>
              <div class="row-actions">
                <button class="secondary" on:click={() => revokeCapability(grant)} disabled={!!busy || !!grant.revoked_at}>Revoke</button>
              </div>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted">No capability grants have been recorded.</p>
      {/if}
      <h3>Requests</h3>
      {#if capabilities?.requests.length}
        <ul class="item-list">
          {#each capabilities.requests as request}
            <li>
              <div class="item-head">
                <strong>{capabilityClass(request)}</strong>
                <span class="badge">{capabilityStatus(request)}</span>
              </div>
              <p>{capabilityId(request)}</p>
              <pre>{jsonString(request.scope)}</pre>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted">No capability requests have been recorded.</p>
      {/if}
    {:else if activeView === "closeout"}
      <div class="gate-head" class:ok={!!closeoutGate?.passed} class:bad={!!closeoutGate && !closeoutGate.passed}>
        <strong>{gateLabel}</strong>
        <span>{blockingCloseoutCount} blocking checks failing</span>
      </div>
      <div class="quick-links" aria-label="Closeout related state">
        <button class="secondary" on:click={() => (activeView = "pending")}>Pending Actions</button>
        <a href={`/api/workbenches/${slug}/coverage/findings`} target="_blank" rel="noopener">Findings JSON</a>
        <button class="secondary" on:click={() => (activeView = "ledger")}>Ledger</button>
        <a href={`/api/workbenches/${slug}/refall-report`} target="_blank" rel="noopener">Current Report</a>
      </div>
      {#if closeoutGate}
        <pre>{jsonString(closeoutGate.summary)}</pre>
        <ul class="item-list">
          {#each closeoutGate.checks as check}
            <li>
              <div class="item-head">
                <strong>{check.id}</strong>
                <span class="badge">{check.status}{check.blocking ? " blocking" : ""}</span>
              </div>
              <p>{check.count} affected</p>
              {#if check.overridden}
                <p>override {check.override_ledger_id || "ledger"} {check.override_reason || ""}</p>
              {/if}
              {#if check.details?.length}<pre>{jsonString(check.details)}</pre>{/if}
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted">Closeout gate has not loaded.</p>
      {/if}
    {:else if activeView === "ledger"}
      {#if ledgerEntries.length}
        <ul class="item-list">
          {#each ledgerEntries.slice().reverse().slice(0, 80) as entry}
            <li>
              <div class="item-head">
                <strong>{titleFor(entry)}</strong>
                <span class="badge">{entry.kind || "ledger"}</span>
              </div>
              <p>{entry.created_at || ""} {entry.status || ""} {entry.provider || entry.lane || ""}</p>
              {#if entry.summary}<p>{entry.summary}</p>{/if}
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted">No ledger entries have been written for this subject.</p>
      {/if}
    {:else if activeView === "output"}
      <div class="view-head">
        <span>Agent output — facts, leads &amp; findings compiled to the ledger</span>
        <div class="output-filters">
          <button class:active={outputFilter === "all"} on:click={() => (outputFilter = "all")}>
            All <em>{outputEntries.length}</em>
          </button>
          <button class:active={outputFilter === "finding"} on:click={() => (outputFilter = "finding")}>
            Findings <em>{outputCounts.finding}</em>
          </button>
          <button class:active={outputFilter === "lead"} on:click={() => (outputFilter = "lead")}>
            Leads <em>{outputCounts.lead}</em>
          </button>
          <button class:active={outputFilter === "fact"} on:click={() => (outputFilter = "fact")}>
            Facts <em>{outputCounts.fact}</em>
          </button>
        </div>
      </div>
      {#if shownOutput.length}
        <ul class="output-list">
          {#each shownOutput as entry, i (entry.id + "::" + i)}
            {@const rowKey = entry.id + "::" + i}
            {@const sev = sevOf(entry)}
            {@const anchors = outputAnchors(entry)}
            {@const desc = outputDesc(entry)}
            <li class="output-card kind-{entry.kind}" class:open={expandedOutput[rowKey]}>
              <button class="output-row" on:click={() => toggleOutput(rowKey)} aria-expanded={!!expandedOutput[rowKey]}>
                <span class="caret" aria-hidden="true">▸</span>
                <span class="k-badge kind-{entry.kind}">{entry.kind}</span>
                {#if sev}<span class="sev sev-{sev}">{sev}</span>{/if}
                <span class="o-title">{outputTitle(entry)}</span>
                {#if desc && !expandedOutput[rowKey]}<span class="o-snippet">{desc}</span>{/if}
              </button>
              {#if expandedOutput[rowKey]}
                <div class="output-body">
                  {#if desc}<p class="o-desc">{desc}</p>{/if}
                  {#if ostr(entry.investigation_plan)}
                    <div class="o-field">
                      <span class="o-label">Next step</span>
                      <p class="o-text">{ostr(entry.investigation_plan)}</p>
                    </div>
                  {/if}
                  {#if anchors.length}
                    <div class="o-field">
                      <span class="o-label">Evidence &amp; code paths</span>
                      <ul class="o-anchors">
                        {#each anchors as a}<li><code>{a}</code></li>{/each}
                      </ul>
                    </div>
                  {/if}
                  <div class="o-field">
                    <span class="o-label">Details</span>
                    <dl class="o-meta">
                      {#if sev}<div class="o-kv"><dt>Severity</dt><dd class="sev-text sev-{sev}">{sev}</dd></div>{/if}
                      {#if ostr(entry.status)}<div class="o-kv"><dt>Status</dt><dd>{ostr(entry.status)}</dd></div>{/if}
                      {#if ostr((entry as Record<string, unknown>).quality_tier)}<div class="o-kv"><dt>Quality</dt><dd>{ostr((entry as Record<string, unknown>).quality_tier)}</dd></div>{/if}
                      {#if ostr(entry.lane)}<div class="o-kv"><dt>Lane</dt><dd>{ostr(entry.lane)}</dd></div>{/if}
                      {#if ostr((entry as Record<string, unknown>).phase)}<div class="o-kv"><dt>Phase</dt><dd>{ostr((entry as Record<string, unknown>).phase)}</dd></div>{/if}
                      {#if ostr((entry as Record<string, unknown>).unit_id)}<div class="o-kv"><dt>Unit</dt><dd class="mono">{ostr((entry as Record<string, unknown>).unit_id)}</dd></div>{/if}
                      {#if ostr(entry.agent)}<div class="o-kv"><dt>Agent</dt><dd class="mono">{ostr(entry.agent).slice(0, 8)}</dd></div>{/if}
                      {#if ostr(entry.created_at)}<div class="o-kv"><dt>Time</dt><dd>{ostr(entry.created_at)}</dd></div>{/if}
                      <div class="o-kv"><dt>Ledger ID</dt><dd class="mono muted">{entry.id}</dd></div>
                    </dl>
                  </div>
                </div>
              {/if}
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted">No facts, leads, or findings compiled yet. They appear here as loop agents emit them.</p>
      {/if}
    {:else if activeView === "logs"}
      {#if logs().length}
        {#each logs() as log}
          <h3>{log.path || "log"}</h3>
          <pre>{(log.tail || []).join("\n")}</pre>
        {/each}
      {:else}
        <p class="muted">Run Logs to load the current audit and workbench log tails.</p>
      {/if}
    {:else if activeView === "debug"}
	      <pre>{JSON.stringify({ debug, live, coverage, context, scopeOverlay, threatModel, doctorResult, estimateResult, ledger, pendingActions, closeoutGate, capabilities, runtimeEvents, runtimeArtifacts, runtimeObservations, nonfatalErrors, evidenceGraph, commandResult }, null, 2)}</pre>
    {/if}
  {/if}
</section>

<style>
  .ops-panel {
    margin: 20px 0 28px;
    padding: 16px;
    border: 1px solid var(--wb-rule);
    border-radius: var(--card-radius);
    background: var(--wb-surface);
    color: var(--wb-ink);
  }
  .panel-head {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    align-items: center;
    margin-bottom: 12px;
  }
  h2 {
    margin: 0;
    font-size: 15px;
    text-transform: uppercase;
    letter-spacing: 0;
    color: var(--wb-accent);
  }
  .panel-head p {
    margin: 4px 0 0;
    color: var(--wb-muted);
    font-family: var(--wb-font-mono);
    font-size: 12px;
  }
  button {
    background: var(--wb-accent);
    color: var(--wb-bg);
    border: 0;
    border-radius: var(--card-radius);
    padding: 7px 12px;
    cursor: pointer;
    font: inherit;
    font-weight: 700;
  }
  button:disabled {
    cursor: wait;
    opacity: 0.55;
  }
  button.secondary {
    background: var(--wb-bg);
    color: var(--wb-ink);
    border: 1px solid var(--wb-rule);
  }
  .actions,
  .tabs,
  .quick-links,
  .view-head,
  .item-head,
  .row-actions,
  .form-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    margin-bottom: 12px;
  }
  .tabs button {
    background: var(--wb-bg);
    color: var(--wb-muted);
    border: 1px solid var(--wb-rule);
  }
  .tabs button.active {
    color: var(--wb-bg);
    background: var(--wb-accent);
    border-color: var(--wb-accent);
  }
  .quick-links a {
    display: inline-flex;
    align-items: center;
    min-height: 34px;
    padding: 0 12px;
    border: 1px solid var(--wb-rule);
    border-radius: var(--card-radius);
    background: var(--wb-bg);
    color: var(--wb-ink);
    font-weight: 700;
    text-decoration: none;
  }
  .view-actions a {
    display: inline-flex;
    align-items: center;
    min-height: 32px;
    padding: 0 10px;
    border: 1px solid var(--wb-rule);
    border-radius: var(--wb-rounded-sm, 4px);
    background: var(--wb-bg);
    color: var(--wb-ink);
    font-weight: 700;
    text-decoration: none;
  }
  .view-head,
  .item-head {
    justify-content: space-between;
    color: var(--wb-muted);
    font-size: 12px;
    font-family: var(--wb-font-mono);
  }
  .view-actions {
    display: flex;
    gap: 8px;
  }
  textarea,
  input,
  select {
    width: 100%;
    box-sizing: border-box;
    margin: 0 0 10px;
    padding: 12px;
    border: 1px solid var(--wb-rule);
    border-radius: var(--wb-rounded-sm, 4px);
    background: var(--wb-bg);
    color: var(--wb-ink);
    font: 12px/1.5 var(--wb-font-mono);
  }
  textarea {
    resize: vertical;
  }
  textarea:focus,
  input:focus,
  select:focus {
    outline: 1px solid var(--wb-accent);
    border-color: var(--wb-accent);
  }
  .operator-input {
    min-height: 86px;
  }
  .context-editor {
    min-height: 360px;
  }
  .metrics {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 8px;
    margin-bottom: 12px;
  }
  .metrics div {
    border: 1px solid var(--wb-rule);
    border-radius: var(--wb-rounded-sm, 4px);
    padding: 10px;
    background: var(--wb-bg);
  }
  b {
    display: block;
    font-size: 22px;
    line-height: 1;
    color: var(--wb-success);
  }
  .metrics span {
    display: block;
    margin-top: 5px;
    color: var(--wb-muted);
    font-size: 11px;
  }
  pre {
    max-height: 260px;
    overflow: auto;
    margin: 0;
    padding: 12px;
    border: 1px solid var(--wb-rule);
    border-radius: var(--wb-rounded-sm, 4px);
    background: var(--wb-bg);
    color: var(--wb-muted);
    font-family: var(--wb-font-mono);
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-word;
  }
  h3 {
    margin: 14px 0 6px;
    font-size: 13px;
    color: var(--wb-accent);
  }
  .item-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    gap: 8px;
  }
  .item-list li {
    border: 1px solid var(--wb-rule);
    border-radius: var(--wb-rounded-sm, 4px);
    background: var(--wb-bg);
    padding: 10px;
  }
  .item-list strong {
    display: block;
    color: var(--wb-ink);
    font-size: 13px;
  }
  .item-list p {
    margin: 6px 0 0;
    color: var(--wb-ink);
    font-size: 12px;
  }
  .badge {
    border: 1px solid var(--wb-rule);
    border-radius: var(--wb-rounded-sm, 4px);
    padding: 3px 6px;
    color: var(--wb-muted);
    background: var(--wb-surface);
  }
  .row-actions {
    margin: 10px 0 0;
  }
  .capability-form {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 10px;
    margin-bottom: 12px;
  }
  .capability-form label span {
    display: block;
    margin-bottom: 5px;
    color: var(--wb-muted);
    font-size: 11px;
    font-family: var(--wb-font-mono);
  }
  .capability-form .wide {
    grid-column: 1 / -1;
  }
  .capability-form .check {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .capability-form .check input {
    width: auto;
    margin: 0;
  }
  .capability-form .check span {
    margin: 0;
  }
  .form-actions {
    align-self: end;
    margin: 0 0 10px;
  }
  .gate-head {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    align-items: center;
    border: 1px solid var(--wb-rule);
    border-radius: var(--wb-rounded-sm, 4px);
    padding: 10px;
    margin-bottom: 10px;
    background: var(--wb-bg);
  }
  .gate-head strong {
    font-size: 18px;
    text-transform: uppercase;
  }
  .gate-head.ok strong {
    color: var(--wb-success);
  }
  .gate-head.bad strong {
    color: var(--wb-error);
  }
  .muted { color: var(--wb-muted); }
  .error { color: var(--wb-error); }

  /* ---- Output view (facts / leads / findings) ---- */
  .output-filters { display: flex; gap: 6px; flex-wrap: wrap; }
  .output-filters button {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 11px; font-size: 12.5px; border-radius: 999px;
    border: 1px solid var(--wb-rule); background: var(--wb-bg); color: var(--wb-muted);
    cursor: pointer; transition: all .12s ease;
  }
  .output-filters button:hover { color: var(--wb-ink); border-color: var(--wb-accent); }
  .output-filters button.active { color: var(--wb-bg); background: var(--wb-accent); border-color: var(--wb-accent); }
  .output-filters button em { font-style: normal; font-weight: 700; opacity: .8; font-variant-numeric: tabular-nums; }

  .output-list { list-style: none; margin: 12px 0 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
  .output-card {
    border: 1px solid var(--wb-rule); border-left-width: 3px; border-radius: var(--card-radius);
    background: var(--wb-surface); overflow: hidden; transition: border-color .12s ease;
  }
  .output-card.kind-finding { border-left-color: #ff6f7d; }
  .output-card.kind-lead { border-left-color: #ffcf6b; }
  .output-card.kind-fact { border-left-color: var(--wb-accent); }
  .output-card.open { border-color: var(--wb-accent); }

  .output-row {
    width: 100%; display: flex; align-items: center; gap: 9px; flex-wrap: wrap;
    padding: 10px 13px; background: none; border: none; text-align: left; cursor: pointer;
    color: var(--wb-ink); font: inherit;
  }
  .output-row:hover { background: color-mix(in srgb, var(--wb-accent) 8%, transparent); }
  .output-row .caret { color: var(--wb-accent); font-size: 11px; transition: transform .15s ease; flex: none; }
  .output-card.open .output-row .caret { transform: rotate(90deg); }
  .k-badge {
    flex: none; font-size: 10.5px; text-transform: uppercase; letter-spacing: .05em; font-weight: 700;
    padding: 1px 7px; border-radius: 4px; border: 1px solid var(--wb-rule); color: var(--wb-muted);
  }
  .k-badge.kind-finding { color: #ff6f7d; border-color: #7a3b42; }
  .k-badge.kind-lead { color: #d9a441; border-color: #6f5a2c; }
  .k-badge.kind-fact { color: var(--wb-accent); border-color: color-mix(in srgb, var(--wb-accent) 45%, transparent); }
  .sev {
    flex: none; font-size: 10px; text-transform: uppercase; letter-spacing: .04em; font-weight: 700;
    padding: 1px 7px; border-radius: 999px; border: 1px solid var(--wb-rule); color: var(--wb-muted);
  }
  .sev-critical { color: #ff5470; border-color: #7a3b46; }
  .sev-high { color: #ff8f6b; border-color: #7a4f3b; }
  .sev-medium { color: #ffcf6b; border-color: #6f5f2c; }
  .sev-low { color: #5ef2a6; border-color: #2f6a4c; }
  .o-title { font-weight: 600; font-size: 13.5px; }
  .o-snippet { color: var(--wb-muted); font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 46ch; }

  .output-body {
    padding: 14px 18px 18px 33px;
    border-top: 1px solid var(--wb-rule);
    background: color-mix(in srgb, var(--wb-bg) 55%, transparent);
  }
  .o-desc { margin: 4px 0 0; line-height: 1.6; color: var(--wb-ink); max-width: 78ch; }
  .o-field { margin-top: 18px; }
  .o-label {
    display: block; font-size: 10px; text-transform: uppercase; letter-spacing: .08em;
    font-weight: 700; color: var(--wb-muted); margin-bottom: 8px;
    padding-bottom: 5px; border-bottom: 1px solid color-mix(in srgb, var(--wb-rule) 60%, transparent);
  }
  .o-text { margin: 0; line-height: 1.55; max-width: 78ch; }

  .o-anchors { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 5px; }
  .o-anchors li { display: flex; }
  .o-anchors code {
    display: block; width: 100%;
    font-family: var(--wb-font-mono); font-size: 11.5px; line-height: 1.5;
    padding: 6px 10px; border: 1px solid var(--wb-rule); border-radius: 5px;
    background: var(--wb-bg); color: var(--wb-accent); word-break: break-all;
  }

  .o-meta {
    margin: 0; display: grid; gap: 10px 20px;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  }
  .o-kv { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .o-kv dt { font-size: 9.5px; text-transform: uppercase; letter-spacing: .07em; color: var(--wb-muted); }
  .o-kv dd { margin: 0; font-size: 13px; color: var(--wb-ink); word-break: break-word; }
  .o-kv dd.mono { font-family: var(--wb-font-mono); font-size: 11.5px; }
  .o-kv dd.muted { color: var(--wb-muted); }
  .sev-text { font-weight: 700; text-transform: capitalize; }
  dd.sev-text.sev-critical { color: #ff5470; }
  dd.sev-text.sev-high { color: #ff8f6b; }
  dd.sev-text.sev-medium { color: #d9a441; }
  dd.sev-text.sev-low { color: #5ef2a6; }
</style>
