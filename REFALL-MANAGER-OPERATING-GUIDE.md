# REFALL Manager Operating Guide

The manager operates REFALL AB and coordinates specialist research.
ArcticBase is the backend implementation name.
Use REFALL AB as the product name in status messages and procedures.

## Read first

1. Read `starthere/` in numeric order.
2. Read `AGENTS.md`.
3. Read `docs/manager/AGENTS.md`.
4. Read `CODEX.md` or `CLAUDE.md` for the selected role.
5. Read the subject context before you claim work.

The alternate startup pack is `docs/codex-startup/*.md`.
Read [Operating procedures](OPERATING_GUIDE.md) for the command sequence.

## Prepare infrastructure

Run these commands from the repository directory.

```bash
export REFALL_REPO_ROOT="$PWD"
export REFALL_PUBLIC_BASE_URL=http://127.0.0.1:7673
export REFALL_WORKBENCH_BASE="$REFALL_PUBLIC_BASE_URL"
export REFALL_OPENHANDS_BASE=http://127.0.0.1:8000
```

1. Complete the installation procedure.
2. Read `/api/health`.
3. Read `/api/refall/ops/status`.
4. Examine `/api/refall/ops/infra` and `/api/refall/ops/agents`.
5. Examine Agent Canvas/OpenHands connectivity.
6. Examine the selected provider CLI and subject mounts.
7. Examine remote resource access when the subject requires it.

Operation routes require `REFALL_ENABLE_OPS=true`.
Named commands require `REFALL_ENABLE_OPS_COMMANDS=true`.
The allowlist must include the requested command.

## Create the subject

1. Create the workbench.

   ```bash
   python3 -m ref_all_executor subject create example --source-path /absolute/path/to/example
   ```

2. Examine the source path from the backend host.
3. Examine the matching source mount from the agent container.
4. Set the subject scope and exclusions.

## Create Workbench Theme

Use `PUT /api/workbenches/{slug}/theme` to set the workbench appearance.
The JSON body contains the complete theme document in `raw`.
The theme document contains YAML frontmatter and Markdown.
Read `/api/agent/conventions` for the required tokens and layout values.

## Generate Context

1. Request context generation.

   ```bash
   python3 -m ref_all_executor ops command context example
   ```

2. Read `/api/workbenches/example/coverage/context`.
3. Examine the stored `context.md` content in `info_md`.
4. Examine source inventory, scope overlay, and the threat model.
5. Run `doctor example` and `estimate example` when readiness is uncertain.

A loop cannot start without stored context.
The manager uses the context to constrain discovery, validation, and report preparation.

## Start Loop

1. Obtain a subject-scoped `run_local_command` capability from the operator.
2. Start the loop.

   ```bash
   python3 -m ref_all_executor loop start example
   ```

3. Examine the operation response and agent state.

With `REFALL_ENABLE_LOOP_LAUNCH=true`, start launches `ref_all_executor.standing_loop` with `--max-cycles 0`.
Update launches the same runner with `--max-cycles 1`.
The manager must not replace this runner with undocumented work in chat.

## Monitor and recover

Examine these records during each manager cycle:

- Coverage statistics, claim leases, and the coverage gate.
- Source inventory and scope overlay.
- Pending actions and capability requests.
- Runtime manifest, observations, artifacts, and the evidence graph.
- Current findings, disposition refusals, and report freshness.

The live diagnosis route is `/api/refall/ops/debug/{subject}/live`.
The run manifest is `/api/workbenches/{slug}/runtime/manifest`.
Local loop state uses `.refall/loop_state.json`.
The nonfatal error route is a read-only projection.

1. Resolve pending actions before ordinary coverage work.
2. Examine failures before you request another cycle.
3. Request a bounded update when recovery is appropriate.

   ```bash
   python3 -m ref_all_executor loop update example
   ```

4. Append important decisions and observations to the ledger.

The watchdog and supervisor preserve liveness information.
The recovery policy restores failed services.
It does not use service failure as a reason to tear down the stack.
Review stale loop state before you start replacement work.

## Specialist output

Specialists return fenced `refall-submit` JSON with schema `refall.submit.v1`.
Use the `task_result_submit` event and a stable `submission_id`.
Evidence-bearing results require evidence, confidence, limitations, and source anchors or artifact references.
Use `REFALL_REQUIRE_STRUCTURED_SUBMIT=true` to require valid structured output.

The executor ignores duplicate structured submissions.
It stores a nested finding before it applies proposed transitions.
New findings begin as `PROVISIONALLY_VALID` or `NEEDS_RESEARCH`.
`VALID` describes finding status.
`LIVE_CONFIRMED` describes evidence quality.
Keep these properties separate.

Submit suppressive changes through `/api/workbenches/{slug}/findings/{finding_id}/transitions`.
Use typed evidence receipts.
Include `source_hashes` when proof depends on exact source or configuration bytes.
A stale receipt is refused.

A `scope_blocked` result creates a scope decision.
A `capability_missing` result creates a capability request.
Neither result completes the unit.
The specialist cannot authorize its own live action.

## Remote SSH Resources

`REFALL_SSH_RESOURCE_ALIASES` selects remote resources from the configured allowlist.
The current allowlist is `sectortw,sectortl`.
Set an empty value to disable remote resources.

1. Assign a remote resource only when the task requires it.
2. Run the command with `ssh <alias> <command>`.
3. Record the alias, command, evidence, and limitations in the submission.

Grok is not an SSH resource.
Its optional worker is host-orchestrated inside a sandbox.
It must not receive host credentials.
The manager transfers permitted subject material into the sandbox and records its results through REFALL APIs.

## Analysis and visual evidence

Run source analysis with `toolchain/run.sh` when it supplies useful evidence.
Start Codebadger for property graphs, data flow, taint analysis, or slicing when necessary.
Preserve the command and input identity with analysis artifacts.
Link screenshots, graphs, CodeCharta views, and other visual evidence to the supported finding.

## Closeout

1. Resolve pending actions and refused transitions.
2. Complete the required validation.
3. Create the report draft.

   ```bash
   python3 -m ref_all_executor report draft example
   ```

4. Enrich the report.

   ```bash
   python3 -m ref_all_executor report enrich example
   ```

5. Read `/api/workbenches/example/closeout/gate`.
6. Resolve each condition or record an operator override receipt.
7. Request closeout.

   ```bash
   python3 -m ref_all_executor loop closeout example
   ```

Read [Evidence requirements](docs/evidence.md) and [API reference](docs/api.md) for the complete contracts.
