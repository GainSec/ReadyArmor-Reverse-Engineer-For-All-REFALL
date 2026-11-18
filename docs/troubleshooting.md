# REFALL AB troubleshooting

## The web interface is unavailable

1. Read `/api/health` at the configured service URL.
2. Examine the backend listen address and port.
3. Examine `ARCTIC_BASE_FRONTEND_DIST`.
4. Build the frontend if that directory is absent.
5. Examine the backend log for startup failures.

## A subject loop does not start

1. Read the subject context.
2. Generate context if it is absent.
3. Run `python3 -m ref_all_executor ops command doctor example`.
4. Examine `REFALL_ENABLE_OPS` and `REFALL_ENABLE_OPS_COMMANDS`.
5. Examine the named command allowlist.
6. Examine the subject launch capability.
7. Examine the Agent Canvas service and API key path.
8. Examine the provider executable and subject mount paths.

A stored context record and a valid launch grant are necessary when process launch is enabled.

## Progress stops

1. Examine `/api/refall/ops/debug/example/live`.
2. Examine coverage claims and pending actions.
3. Examine the runtime manifest and nonfatal error projection.
4. Resolve expired or orphaned work through the operation interface.
5. Request a bounded loop update.

Recoverable failures use the configured retry limit and delay.
Exhausted retries remain visible as pending work.

## A submission is refused

1. Examine the structured submission validation result.
2. Examine the schema, identity, evidence, confidence, and limitations.
3. Examine the source anchors or artifact references.
4. Resubmit the corrected result with the appropriate identity.

## A finding transition is refused

1. Read the transition refusal.
2. Compare the expected current state with the stored finding.
3. Examine the receipt type and evidence references.
4. Compare source hashes with the current files.
5. Collect the missing proof.
6. Submit a new transition request.

## Closeout is blocked

1. Read the closeout gate response.
2. Resolve pending actions and refused transitions.
3. Complete the required validation.
4. Prepare the report draft.
5. Enrich the report.
6. Request closeout again.

## Optional analysis tools fail

1. Run `toolchain/ctl.sh status`.
2. Examine the tool output and `run_manifest.json`.
3. Examine the service log in `toolchain/logs/`.
4. Run `toolchain/install.sh` to repair installed dependencies when necessary.

Use the toolchain output directory for generated files.
Keep subject evidence in the subject workbench and artifact store.
