# REFALL AB operating procedures

Use these procedures from the repository directory.
Complete Installation (`BASE-INSTALLATION.md`) first.
The CLI uses `REFALL_WORKBENCH_BASE` or `REFALL_PUBLIC_BASE_URL` to select the workbench service.

## Create a subject

A subject is the source tree, binary, or system under examination.
A workbench stores the subject context, research records, and reports.
Use one workbench for each subject.

1. Create the subject workbench.

   ```bash
   python3 -m ref_all_executor subject create example --source-path /absolute/path/to/example
   ```

2. Generate the shared context.

   ```bash
   python3 -m ref_all_executor ops command context example
   ```

3. Examine the stored context in the workbench.
4. Examine the source inventory and scope.
5. Run the diagnosis command.

   ```bash
   python3 -m ref_all_executor ops command doctor example
   ```

6. Get the workload estimate.

   ```bash
   python3 -m ref_all_executor ops command estimate example
   ```

## Grant a launch capability

A capability is an operator grant for a specified action and scope.
A loop launch requires a subject-scoped `run_local_command` grant when launch execution is enabled.
The operator token comes from `REFALL_CAPABILITY_OPERATOR_TOKEN_PATH` when that setting is configured.

1. Submit the launch grant through the workbench capability interface.
2. Select `run_local_command` as the action class.
3. Set the scope to the subject source path.
4. Record the reason for the grant.

The capability endpoint is `/api/workbenches/{slug}/capabilities/grant`.
Agents cannot grant themselves permission for live actions.

## Run research

Stored context is necessary before the first loop launch.

1. Start the loop.

   ```bash
   python3 -m ref_all_executor loop start example
   ```

2. Examine the operation status.

   ```bash
   python3 -m ref_all_executor ops status
   ```

3. Examine coverage, ledger records, findings, and pending actions in the workbench.
4. Resolve open capability requests and scope decisions.
5. Run a bounded update when necessary.

   ```bash
   python3 -m ref_all_executor loop update example
   ```

`Start Loop` and `Update` in the web interface use the same operation routes.
`Doctor` examines services, paths, capabilities, provider commands, and supporting tools.
`Estimate` measures the work represented by the current subject inventory.

## Prepare a report

1. Create the report draft.

   ```bash
   python3 -m ref_all_executor report draft example
   ```

2. Enrich the report.

   ```bash
   python3 -m ref_all_executor report enrich example
   ```

3. Examine the current report in the workbench.
4. Examine the closeout gate.

   ```bash
   curl -fsS "$REFALL_PUBLIC_BASE_URL/api/workbenches/example/closeout/gate"
   ```

5. Resolve each open condition.
6. Request closeout.

   ```bash
   python3 -m ref_all_executor loop closeout example
   ```

Report enrichment adds evidence context, related findings, remediation information, and visual evidence.
The closeout gate identifies pending actions, refused transitions, incomplete validation, stale reports, and missing receipts.

## Examine the ledger

The ledger is a sequence of evidence and decision records.
Each significant research result, disposition, capability decision, and report change belongs in the ledger.

```bash
curl -fsS "$REFALL_PUBLIC_BASE_URL/api/workbenches/example/ledger/entries"
```

## Stop local services

1. Examine the shutdown actions.

   ```bash
   python3 refall_down.py --dry-run --include-serena
   ```

2. Stop the local runtime.

   ```bash
   python3 refall_down.py --include-serena
   ```

## References

- API reference (`docs/api.md`).
- Evidence requirements (`docs/evidence.md`).
- Troubleshooting (`docs/troubleshooting.md`).
- Manager procedures (`REFALL-MANAGER-OPERATING-GUIDE.md`).
- Startup sequence (`starthere/README.md`).

The alternate startup sequence is in `docs/codex-startup/*.md`.
