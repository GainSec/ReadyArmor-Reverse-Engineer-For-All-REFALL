# REFALL Manager Agent Instructions

The manager operates REFALL AB infrastructure and coordinates the research loop.
Codex or Claude Code can supply the manager role.
Use the standing loop for research execution.
Do not replace it with undocumented work in chat.

## Authority

Use `REFALL AB` as the product name in status messages and lifecycle instructions.
ArcticBase identifies the backend implementation, APIs, paths, and processes.
Use the backend APIs for authoritative research state.

A REFALL AB lifecycle request applies to its configured services.
These can include the backend, research loop, Agent Canvas/OpenHands, coverage, watchdog, and analysis tools.
A separately deployed ArcticBase instance belongs to its own service configuration.
Include that instance only when the operator requests it.

Read these documents before operation:

1. Read `starthere/` in numeric order.
2. Read `AGENTS.md`.
3. Read `REFALL-MANAGER-OPERATING-GUIDE.md`.
4. Read `OPERATING_GUIDE.md`.
5. Read `CODEX.md` or `CLAUDE.md` for the selected role.

The alternate startup pack is `docs/codex-startup/*.md`.
The index is `docs/README.md`.

Examine these operation records:

- `/api/refall/ops/status`.
- `/api/refall/ops/infra`.
- `/api/refall/ops/agents`.

Examine the workbench at `/api/workbenches/{slug}`.
The following subject routes use that path as their prefix:

- `/coverage/context`.
- `/coverage/source-inventory`.
- `/coverage/scope-overlay`.
- `/coverage/threat-model`.
- `/coverage/stats`.
- `/coverage/gate`.
- `/pending-actions`.
- `/runtime/events`.
- `/runtime/manifest`.
- `/runtime/nonfatal-errors`.
- `/runtime/observations`.
- `/runtime/artifacts`.
- `/runtime/evidence-graph`.
- `/capabilities`.
- `/closeout/gate`.
- `/ledger/entries`.

## Boot Rules

Run these configuration commands from the repository directory.
Use the selected deployment addresses when the services are remote.

```bash
export REFALL_REPO_ROOT="$PWD"
export REFALL_PUBLIC_BASE_URL="http://127.0.0.1:7673"
export REFALL_WORKBENCH_BASE="$REFALL_PUBLIC_BASE_URL"
export REFALL_OPENHANDS_BASE="http://127.0.0.1:8000"
export REFALL_ENABLE_OPS=true
export REFALL_ENABLE_OPS_COMMANDS=true
export REFALL_ENABLE_LOOP_LAUNCH=true
```

Before the first subject cycle:

1. Examine REFALL AB health.
2. Examine Ops status.
3. Examine Agent Canvas/OpenHands connectivity.
4. Examine remote resource access when the task requires it.
5. Confirm that the subject workbench exists.
6. Create or update its theme through `PUT /api/workbenches/{slug}/theme`.
7. Confirm that the backend can read the source path.
8. Run Doctor and Estimate when readiness is uncertain.
9. Generate or save `context.md`.
10. Confirm that `/api/workbenches/{slug}/coverage/context` contains nonempty `info_md`.
11. Obtain a subject-scoped `run_local_command` operator grant when loop launch is enabled.

Create the theme before context generation.
With `REFALL_ENABLE_LOOP_LAUNCH=true`, Start Loop and Update require the launch grant.
The current remote aliases are `sectortw` and `sectortl`.

## Lifecycle

1. Create or update the subject theme.
2. Generate Context.
3. Start Loop.
4. Examine Ops.
5. Request Update for a bounded cycle when necessary.
6. Resolve closeout conditions.
7. Request Closeout.

The named commands are:

```text
context {subject}
doctor {subject}
estimate {subject}
threat-model {subject}
start {subject}
update {subject}
closeout {subject}
coverage {subject}
logs {subject}
agents
```

Use the API command route:

```bash
curl -sS -X POST "$REFALL_PUBLIC_BASE_URL/api/refall/ops/command" \
  -H 'content-type: application/json' \
  -d '{"command":"start {subject}"}'
```

Use the equivalent CLI commands:

```bash
PYTHONPATH="$REFALL_REPO_ROOT" python3 -m ref_all_executor ops command context {subject}
PYTHONPATH="$REFALL_REPO_ROOT" python3 -m ref_all_executor loop start {subject}
PYTHONPATH="$REFALL_REPO_ROOT" python3 -m ref_all_executor loop update {subject}
PYTHONPATH="$REFALL_REPO_ROOT" python3 -m ref_all_executor loop closeout {subject}
```

Replace the subject placeholder with the selected slug.
Start launches `ref_all_executor.standing_loop` with `--max-cycles 0`.
Update launches the same runner with `--max-cycles 1`.

Assign a remote resource only when the task requires it.
Require `ssh <alias> <command>` for remote commands.
Include the alias, exact command, evidence references, and limitations in terminal `refall-submit` output.
SSH access does not expand the external target scope.

Grok is not an SSH resource.
It is an optional host-orchestrated provider lane for subject-material tasks selected by the manager.
Grok must not receive host credentials, SSH aliases, LAN authority, unrestricted host access, or operator secrets.
The manager records accepted sandbox results through the backend APIs.

## Monitoring

Read these records while the loop runs:

```bash
curl -sS "$REFALL_PUBLIC_BASE_URL/api/refall/ops/agents"
curl -sS "$REFALL_PUBLIC_BASE_URL/api/refall/ops/debug/{subject}"
curl -sS "$REFALL_PUBLIC_BASE_URL/api/refall/ops/debug/{subject}/live"
curl -sS "$REFALL_PUBLIC_BASE_URL/api/workbenches/{subject}/coverage/stats"
curl -sS "$REFALL_PUBLIC_BASE_URL/api/workbenches/{subject}/pending-actions"
curl -sS "$REFALL_PUBLIC_BASE_URL/api/workbenches/{subject}/runtime/nonfatal-errors"
curl -sS "$REFALL_PUBLIC_BASE_URL/api/workbenches/{subject}/runtime/observations"
curl -sS "$REFALL_PUBLIC_BASE_URL/api/workbenches/{subject}/runtime/evidence-graph"
curl -sS "$REFALL_PUBLIC_BASE_URL/api/workbenches/{subject}/capabilities"
curl -sS "$REFALL_PUBLIC_BASE_URL/api/workbenches/{subject}/closeout/gate"
curl -sS "$REFALL_PUBLIC_BASE_URL/api/workbenches/{subject}/ledger/stats"
```

Install one watchdog cron entry for each REFALL host through the supported command:

```bash
PYTHONPATH="$REFALL_REPO_ROOT" python3 -m ref_all_executor watchdog install-cron --subject all
crontab -l | rg 'REFALL_V10_WATCHDOG|refall-watchdog-cron'
```

Use a dry pass for manual diagnosis:

```bash
PYTHONPATH="$REFALL_REPO_ROOT" python3 -m ref_all_executor watchdog run --subject {subject} --dry-run
```

The watchdog records `watchdog_alert` events and pending actions.
It detects stale agents, dead loop state, missing active context, and no-progress samples.
It also detects repeated failures, refused actions, degraded OpenHands control, and runtime, token, or cost limits.
A live watchdog pass can stop or delete only the specific runaway Agent Canvas conversation.
That action requires a `watchdog_conversation_stopped` receipt.

Install the schedule only through `watchdog install-cron`.
The installed entry records alerts.
Do not add environment variables through manual crontab edits.

With `REFALL_WATCHDOG_CRASH_POLICY=recover`, the watchdog can restart the failed Agent Canvas container or REFALL AB launchd service.
It must not restart the standing loop or stop the entire stack.
The obsolete `REFALL_WATCHDOG_CRASH_POLICY=shutdown` value is refused.

Read local state when necessary:

```text
<subject-path>/.refall/loop_state.json
<subject-path>/.refall/blackboard.json
<subject-path>/.refall/runtime/state.sqlite
<subject-path>/.refall/runtime/artifacts/
<subject-path>/refallsubloop/logs/events/events.jsonl
<subject-path>/refallsubloop/logs/loop/standing-loop-*.log
```

Before you declare a stall, examine active conversation identifiers, event logs, loop logs, coverage, ledger statistics, and Agent Canvas status.

An `ECONNREFUSED 127.0.0.1:18000` response from the proxy on port 8000 indicates an unavailable internal Agent Server.
The proxy itself can remain available.
Treat conversation statistics and deletion as degraded until the server recovers.
Record the condition through the watchdog or pending actions.

## Specialist Contract

Require parseable specialist output:

````text
```refall-submit
{"schema":"refall.submit.v1","type":"task_result_submit","subject":"SUBJECT","submission_id":"stable-submit-id","task_id":"task_1","unit_id":"unit_1","status":"done","summary":"...","produced_by":"agent-session","created_at":"2026-07-24T00:00:00Z","evidence":[{"kind":"source_anchor","ref":"path/to/file:10","claim":"..."}],"source_anchors":["path/to/file:10"],"confidence":"medium","limitations":[],"findings":[]}
```

```finding
{"title":"...","severity":"HIGH","impact":"...","evidence":["path:line"],"reproduction_steps":"...","remediation":"..."}
```
[FACT] Title | evidence-backed fact
[LEAD:medium] Title | reason | next step
[ASK] Needed tool or access | reason
[COVERAGE] path/to/file
[DONE] summary
````

The standing loop parses `[FACT]`, `[LEAD]`, `[ASK]`, `[COVERAGE]`, `[DONE]`, `finding JSON`, and preferred `refall-submit` blocks.
Set `REFALL_REQUIRE_STRUCTURED_SUBMIT=true` when valid structured results are mandatory.
Malformed or missing results then create pending actions instead of completed coverage.

Typed contracts are in `arcticbase/backend/src/arctic_base/refall/contracts.py`.
Payload helpers are in `ref_all_executor/contract_payloads.py`.
Evidence-bearing submissions require `evidence`, `confidence`, `limitations`, and `source_anchors` or `artifact_refs`.
Nested findings require a concrete location through `code_paths`, `source_anchors`, or `artifact_refs`.
They can inherit evidence from the parent `task_result_submit`.

A structured `control_submit` with `status: "needs_capability"` creates pending actions and capability requests.
It does not complete the coverage unit.
A direct `capability_missing` result creates a capability request and a `capability_decision` pending action.
A direct `scope_blocked` result creates a `scope_decision` pending action.
Neither direct state completes coverage.

Use a stable `submission_id` when one can be generated.
The executor ignores duplicate submissions by that identifier, or by task and unit identity when it is absent.

The standing loop writes `/api/workbenches/{slug}/runtime/manifest` at startup and when it returns to an idle or running state.
It stores the same manifest in runtime SQLite.
It also publishes the `REFALL Run Manifest` runbook object.
Draft reports show the manifest when present.

The nonfatal error projection normalizes existing runtime events and ledger refusals or blockers into JSON or NDJSON.
It is available at `/api/workbenches/{slug}/runtime/nonfatal-errors`.
Keep authoritative evidence in the original records.

Submit suppressive finding changes through the disposition gate with typed receipts.
Pending actions remain visible to the closeout gate.
The authorization route is `/api/workbenches/{slug}/execution/authorize`.
Capabilities control live network, file write, Docker, Codebadger, and destructive actions.
Start and Update are `run_local_command` actions when process launch is enabled.

Use `source_hashes` when transition evidence depends on exact source or configuration bytes.
Stale hashes are refused against the workbench `refall_source_path`.
Agents cannot authorize their own live actions.
Self-issued grants are refused.

Create findings only as `PROVISIONALLY_VALID` or `NEEDS_RESEARCH`.
Propose `VALID`, `FALSE_POSITIVE`, `DUPLICATE`, and `CHAINABLE_DEFERRED` through the transition endpoint.
Include nested `proposed_transition` blocks only when the required receipt is present.
Canonical deduplication uses `dedup_key`, `canonical_finding_id`, and `related_locations`.
Preserve variant paths as related locations in one canonical finding.

## Evidence Rules

Each finding requires:

- Affected component.
- Source path and available line or function references.
- Relevant request, response, log, or binary offset evidence.
- Proof or reproduction steps.
- Impact and likelihood.
- Remediation.
- Validation status.

Record important negative results and blocked paths in the ledger.
Describe coverage gaps explicitly.

## Optional Deep Analysis

Use the analysis toolchain when it supplies concrete evidence for the subject.
The default output directory is `toolchain/output/{subject}`.
Outputs can include Semgrep JSON, rendered graphs, CodeCharta data, complexity measurements, SCIP indexes, and offline viewers.

Codebadger service support is included in the toolchain.
Its use remains optional for each subject.

```bash
cd "$REFALL_REPO_ROOT"
toolchain/ctl.sh up codebadger-mcp
toolchain/bin/codebadger-service status
toolchain/bin/codebadger-service mcp-config
```

Use Codebadger for property graphs, data flow, taint analysis, slicing, or useful visual evidence.
Start it when those results can change research direction, support exploit validation, or reduce a large code path.

1. Put local source under `toolchain/third_party/codebadger/playground/subjects/{subject}`.
2. Call `generate_cpg` with `source_type='local'` and `/app/playground/subjects/{subject}`.
3. Poll `get_cpg_status`.
4. Run focused graph, taint, variable-flow, control-flow, or program-slice queries.

Use simpler tools when Semgrep, Serena, SCIP, or Graphviz can answer the question.
Codebase-Memory is optional.
Its absence or host incompatibility must not block startup.

## Recovery Rules

If Start Loop fails:

1. Read the HTTP response.
2. Confirm that stored context exists.
3. Examine `REFALL_REPO_ROOT`.
4. Examine `REFALL_ENABLE_LOOP_LAUNCH`.
5. Examine `REFALL_OPENHANDS_BASE`.
6. Examine the subject source path.
7. Read the Ops audit and standing-loop logs.

Start and Update require the workbench `refall_source_path` to be visible in Agent Canvas as `/projects/<subject>`.
Use a matching Docker bind mount when available.
The source mount can be read-only.
Without a matching mount, REFALL can copy the source into the Agent Canvas `/projects` volume.
A snapshot marker prevents unnecessary later copies.

Conversations require writable scratch workspaces.
The default container path is `/projects/refallsub/<subject>/...`.
The default host path is `~/refallsub/<subject>/...`.
Read source from `/projects/<subject>`.
Use the configured workspace roots when the deployment overrides these defaults.

If the proxy returns `502 Bad Gateway` because its Agent Server is unavailable, stop new conversation launches.
Recover the failed execution service before further dispatch.

If agents are active without ledger progress:

1. Read `/api/refall/ops/agents`.
2. Read `/api/refall/ops/debug/{subject}/live`.
3. Examine `events.jsonl`.
4. Examine `standing-loop-*.log`.
5. Request `update {subject}` once.
6. Restart Agent Canvas only after you confirm that it is the failed component.

Obtain explicit operator approval before destructive cleanup.
Examine the dry-run result before cleanup.

## Closeout

Closeout requires these records and conditions:

- An existing current report object.
- A passing closeout gate or an operator override receipt.
- Ledger findings, facts, leads, validation, and limitations.
- Explicit unresolved leads.
- Pending actions completed, cancelled, or deferred with receipts.
- Resolved disposition refusals.
- Available runtime observations, artifacts, and evidence graph state reflected in the report.
- Available Runtime Warnings from the nonfatal error projection reflected in the report.
- Capability decisions that affected validation reflected in the report.
- Explicit negative coverage.
- Labeled false positives.
- Recorded proof-of-concept or reproduction status.
- A represented coverage funnel.

Include visuals when they explain scope, architecture, exploit paths, data flow, control flow, validation proof, or coverage gaps.

Prepare the report before you request closeout:

```bash
PYTHONPATH="$REFALL_REPO_ROOT" python3 -m ref_all_executor report draft {subject}
PYTHONPATH="$REFALL_REPO_ROOT" python3 -m ref_all_executor report enrich {subject}
PYTHONPATH="$REFALL_REPO_ROOT" python3 -m ref_all_executor loop closeout {subject}
```

## Hard Boundaries

- Do not start without `context.md`.
- Store evidence in the workbench before you treat it as durable.
- Use backend coverage and ledger APIs for ordinary research work.
- Redact secret values.
- Obtain explicit operator approval before destructive cleanup.
- Contact external or cloud targets only within signed scope.
- Use the REFALL report standard and its module contracts.
