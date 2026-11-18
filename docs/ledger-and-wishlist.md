# Evidence ledger and resource wishlist

REFALL AB keeps research results and resource needs with the subject workbench.
The evidence ledger preserves findings, facts, leads, decisions, and operational history.
The wishlist records missing tools, environments, dependencies, access, and data.
Together, these records help the next worker continue useful work with the resources already available.

A ledger entry records what happened or what the research supports.
A wishlist item records what a researcher needs.
A pending action records an obligation for a worker or manager.
A capability request asks for permission to perform a scoped action.
These records have separate APIs and lifecycles.

## Select the correct record

| Need | Record | Result |
| --- | --- | --- |
| Preserve a source fact or a possible research path. | Ledger `fact` or `lead`. | Later workers and reports can reuse the evidence. |
| Preserve a proposed vulnerability. | Ledger `finding` and the coverage finding API. | The evidence history and finding lifecycle remain available. |
| Request a missing executable or analysis environment. | Wishlist item. | The watchdog or operator can examine the need. |
| Track work that must receive a decision or receipt. | Pending action. | Eligible actions enter the standing loop before ordinary coverage work. |
| Request a live action outside current permissions. | Capability request. | An operator can grant the necessary scoped capability. |
| Record a grant, refusal, transition, or exception. | Corresponding decision API. | The API updates its own state and appends a ledger record. |

The ledger accepts rich JSON records.
Its append route validates the entry kind, rather than the complete evidence contract.
Use the finding, disposition, capability, and pending-action APIs for their state changes.
Appending a ledger entry alone does not perform those changes.
See [evidence procedures](evidence.md) and [Control in Depth](control-in-depth.md).

Source: [ledger append](../arcticbase/backend/src/arctic_base/refall/ledger.py#L41),
[pending action creation](../arcticbase/backend/src/arctic_base/api/refall_pending_actions.py#L58),
and [finding persistence](../ref_all_executor/standing_loop.py#L2457).

## Evidence ledger

### Storage and entry fields

Each workbench has a `refall_ledger.jsonl` file beneath its storage directory.
Each nonempty line contains one JSON entry.
The append API writes a new line and records a storage audit event.

| Field | Behavior |
| --- | --- |
| `kind` | Defaults to `fact`. The value must be a supported kind. |
| `id` | Defaults to a new identifier with the `led_` prefix. |
| `workbench_slug` | Defaults to the slug from the route. |
| `created_at` | Defaults to the current UTC timestamp. |
| `updated_at` | Receives the current UTC timestamp on append. |
| Other fields | Remain in the JSON entry. |

Useful evidence fields include `title`, `summary`, `evidence`, `confidence`, `limitations`, `source_anchors`, and `artifact_refs`.
Use `lane`, `severity`, `subject`, `agent`, and `unit_id` when they identify the work.
Preserve exact source references and artifact identifiers.
Record secret presence without the secret value.

The supported kinds are:

- `fact`, `lead`, `finding`, `observation`, and `hypothesis`.
- `remediation`, `attack-chain`, `ask`, `coverage`, `validation`, and `artifact`.
- `ops-event`, `disposition-transition`, and `pending-action`.
- `capability-grant`, `capability-request`, and `capability-decision`.
- `runtime-event` and `closeout-gate`.

Source: [entry kinds and storage](../arcticbase/backend/src/arctic_base/refall/ledger.py#L13).

### Append, correction, and order

The ledger API exposes append, list, lookup, and statistics operations.
It has no entry update or delete route.
To correct a result, append a new entry with a new identifier.
Include the earlier identifier and explain the correction.
Use the relevant state API when the correction changes a finding or decision.

List responses preserve file order.
The implementation generates no numeric sequence, previous-entry hash, or ledger hash chain.
`created_at` can come from the submitted record.
Use the entry identifier to cite evidence, rather than treating its timestamp as a trusted sequence number.

A repeated caller-supplied identifier can produce multiple lines.
Lookup by identifier returns the first matching entry.
A repeated append is therefore not an update operation.

Source hashes serve a different purpose.
Receipts can carry `source_hashes`, and the run manifest records source and configuration hashes.
Those hashes identify input bytes; they do not authenticate the JSONL ledger.

Source: [append and lookup](../arcticbase/backend/src/arctic_base/refall/ledger.py#L41),
[evidence receipts](../arcticbase/backend/src/arctic_base/refall/contracts.py#L24),
and [manifest hashes](../ref_all_executor/standing_loop.py#L2206).

### Other ledger files

Subject bootstrap also creates `.refall/evidence_ledger.json` with an empty `entries` array.
The workbench ledger API uses `refall_ledger.jsonl` instead.
Runtime events and checkpoints have their own storage and APIs.
Use the workbench ledger routes for shared evidence and decisions.

Source: [subject bootstrap](../arcticbase/backend/src/arctic_base/refall/subjects.py#L114)
and [ledger path](../arcticbase/backend/src/arctic_base/refall/ledger.py#L36).

### Read before work

1. Read the stored subject context and scope.
2. Read the coverage summary for the assigned unit.
3. Read prior facts, leads, and findings for that unit.
4. Examine referenced artifacts and saved analysis.
5. Extend the evidence and record the new result.

The standing loop puts these reuse instructions in objectives for later unit modules.
They tell workers to use prior coverage, ledger records, and the shared blackboard.
This is worker guidance; the ledger API does not enforce a mandatory read before a write.

The loop also ingests evidence during active conversations and at completion.
It reads tagged output and saved workspace results.
Its in-memory identity set suppresses repeated facts, leads, findings, and flows during that run.
A backend failure removes staged identities so a later attempt can retry persistence.
This process does not add a general deduplication rule to the ledger API.

Flow evidence uses `kind: "fact"` with `fact_kind: "flow"` and a nested `flow` object.
The loop separately submits findings to the coverage finding store.
Finding promotion can refuse a candidate even when its ledger evidence remains available.

Source: [reuse instructions](../ref_all_executor/standing_loop.py#L676),
[incremental ingestion](../ref_all_executor/standing_loop.py#L1115),
[ingestion identities](../ref_all_executor/standing_loop.py#L1053),
and [entry conversion](../ref_all_executor/standing_loop.py#L3561).

### Read and append through the API

Set `REFALL_PUBLIC_BASE_URL` to the backend address.
Set `REFALL_WORKBENCH` to an existing workbench slug.
The examples use a fictional source file and artifact identifier.

```bash
export REFALL_PUBLIC_BASE_URL="http://127.0.0.1:7673"
export REFALL_WORKBENCH="example"

curl -fsS "$REFALL_PUBLIC_BASE_URL/api/workbenches/$REFALL_WORKBENCH/ledger/stats"

curl -fsS --get \
  "$REFALL_PUBLIC_BASE_URL/api/workbenches/$REFALL_WORKBENCH/ledger/entries" \
  --data-urlencode 'kind=fact' \
  --data-urlencode 'lane=source-review'

curl -fsS -X POST \
  "$REFALL_PUBLIC_BASE_URL/api/workbenches/$REFALL_WORKBENCH/ledger/entries" \
  -H 'Content-Type: application/json' \
  --data-binary '{
    "kind": "fact",
    "subject": "example",
    "lane": "source-review",
    "unit_id": "unit-example",
    "title": "Configuration reaches the parser",
    "summary": "The loader passes the configuration to parse_config.",
    "evidence": "The call passes the loaded byte buffer.",
    "confidence": "high",
    "limitations": ["Runtime behavior was not examined."],
    "source_anchors": ["src/config.py:42"],
    "artifact_refs": ["artifact-example"]
  }'
```

The append response contains the entry identifier.
Use it with `GET /api/workbenches/{slug}/ledger/entries/{entry_id}`.

| Route | Result |
| --- | --- |
| `POST /api/workbenches/{slug}/ledger/entries` | Appends an entry; returns HTTP 201. |
| `GET /api/workbenches/{slug}/ledger/entries` | Lists entries in file order. |
| `GET /api/workbenches/{slug}/ledger/entries/{entry_id}` | Returns the first matching entry, or HTTP 404. |
| `GET /api/workbenches/{slug}/ledger/stats` | Returns totals by kind, lane, and severity. |

List filters are `kind`, `lane`, `severity`, and `since`.
The first three use exact matches.
`since` compares the stored `created_at` strings with the supplied value.
Use consistent UTC timestamp formats for time queries.
An unsupported kind returns HTTP 422.

Source: [ledger routes](../arcticbase/backend/src/arctic_base/api/refall_ledger.py#L14)
and [list filters](../arcticbase/backend/src/arctic_base/refall/ledger.py#L60).

### Interface and report use

Open the workbench Ops panel and select **Ledger**.
The panel shows the latest 80 appended entries in reverse file order.
Each row shows its title, kind, timestamp, status, provider or lane, and summary when available.
Select **Output** to examine facts, leads, and findings with source or artifact references.
Use the API for the complete ledger.

Report drafting reads ledger entries, ledger statistics, coverage, runtime evidence, pending actions, and capability state.
Report enrichment also reads the stored ledger.
The report combines recorded evidence; a narrative alone does not perform finding verification.

Source: [Ledger view](../arcticbase/frontend/src/lib/refall/WorkbenchOpsPanel.svelte#L953),
[Output filters](../arcticbase/frontend/src/lib/refall/WorkbenchOpsPanel.svelte#L529),
[report drafting](../ref_all_executor/report_draft.py#L51),
and [report enrichment](../ref_all_executor/report_enrich.py#L276).

## Resource wishlist

### Workbench records

The current coverage client defaults to workbench coverage.
Its wishlist records reside in the workbench `refall_coverage.db` database.

| Field | Purpose |
| --- | --- |
| `id` | Request identifier. The backend generates a `wish_` identifier when absent. |
| `subject` | Subject name. The route slug supplies the default. |
| `kind` | Resource category, such as `tool`, `env`, `dep`, `access`, or `data`. |
| `item` | Necessary resource. This field must be nonempty. |
| `reason` | Work that the resource will support. |
| `requested_by` | Researcher or operator identifier. |
| `status` | Defaults to `open`; `provided` identifies delivery records. |
| `created_at`, `updated_at` | Database timestamps. |

`kind` and `status` are string fields rather than fixed enums.
The automation specifically interprets `open` and `provided`.
A custom status does not introduce an automatic workflow.

The workbench API creates rows and lists them.
It exposes no wishlist update or resolve route.
A delivery record is a new row with `status: "provided"`.
Keep the original request identifier in its reason or in a related ledger entry.

Source: [wishlist request fields](../arcticbase/backend/src/arctic_base/api/refall_coverage.py#L149),
[database operations](../arcticbase/backend/src/arctic_base/refall/coverage_store.py#L1490),
and [client mode](../ref_all_executor/coverage_client.py#L20).

### Record and examine a request

1. Check the `provided` list before requesting a resource.
2. Name one resource and the work it will support.
3. Create an `open` wishlist item.
4. Examine watchdog results or arrange operator provision.
5. Record delivery and verify availability in the worker environment.
6. Obtain any necessary capability grant before live use.

```bash
curl -fsS --get \
  "$REFALL_PUBLIC_BASE_URL/api/workbenches/$REFALL_WORKBENCH/coverage/wishlist" \
  --data-urlencode 'status=provided'

curl -fsS -X POST \
  "$REFALL_PUBLIC_BASE_URL/api/workbenches/$REFALL_WORKBENCH/coverage/wishlist" \
  -H 'Content-Type: application/json' \
  --data-binary '{
    "kind": "tool",
    "item": "exiftool",
    "reason": "Read metadata from the assigned sample files.",
    "requested_by": "research-worker",
    "status": "open"
  }'

curl -fsS --get \
  "$REFALL_PUBLIC_BASE_URL/api/workbenches/$REFALL_WORKBENCH/coverage/wishlist" \
  --data-urlencode 'status=open'
```

Both list requests can also use `subject`.
The backend lists matching rows by `updated_at`, newest first.
There is no separate automatic approval state in this wishlist API.

For manual provision, create another row through the same POST route.
Set `status` to `provided` and identify the original request in `reason`.
For example, a delivered test environment can use this body:

```json
{
  "kind": "env",
  "item": "isolated parser environment",
  "reason": "Provided for request wish-example; use the assigned worker environment.",
  "requested_by": "operator",
  "status": "provided"
}
```

This row records delivery.
Configure the worker environment separately before its next task.

Source: [wishlist routes](../arcticbase/backend/src/arctic_base/api/refall_coverage.py#L646).

### Watchdog provision

When the watchdog runs, it collects the workbench's open and provided wishlist rows.
It normalizes the first token of each resource name to an executable name.
It skips names already represented in the provided list.

For an eligible request, it first checks `shutil.which` on the watchdog host.
If the executable exists, the watchdog records delivery.
Otherwise, an enabled installation path can use the fixed Homebrew commands below.

| Requested executable | Homebrew package |
| --- | --- |
| `binwalk` | `binwalk` |
| `exiftool` | `exiftool` |
| `radare2` or `r2` | `radare2` |
| `rizin` or `rz-bin` | `rizin` |
| `yara` | `yara` |

The eligible categories are `tool`, `cli`, `binary`, `package`, `dependency`, or an empty kind.
The installation setting defaults to enabled.
Without an explicit watchdog configuration, `REFALL_WATCHDOG_INSTALL_WISHLIST` controls that setting.
`REFALL_WATCHDOG_WISHLIST_INSTALL_TIMEOUT_S` defaults to 900 seconds.
An explicit `WatchdogConfig` supplies its own installation values.

A successful command must also make the executable discoverable through `shutil.which`.
The watchdog then creates a new provided row.
It appends an `ops-event` with action `watchdog.wishlist.provided`.
The event links the request and delivery identifiers and includes an availability or installation receipt.
The original open row remains unchanged.
Thus, an open count can include a request that already has a separate delivery record.

Dry-run mode skips installation and returns proposed delivery records without writing them.
Unsupported categories, disabled installation, missing installers, and failed installation appear in the result's `unhandled` list.
A host executable check establishes availability on the watchdog host.
Check its path or mount separately before use inside a worker container or remote environment.

Source: [installer table](../ref_all_executor/watchdog.py#L39),
[configuration](../ref_all_executor/watchdog.py#L635),
[provision decisions](../ref_all_executor/watchdog.py#L903),
and [delivery receipt](../ref_all_executor/watchdog.py#L966).

### Delivered resources reach agents

The head orchestrator reads provided items during each cycle.
It inserts them into the specialist objective under `DELIVERED WISHLIST ITEMS`.
The research, binary research, binary review, and binary validation drivers also insert this information into their prompts.
They tell workers to check delivered resources before requesting duplicates.
A failed provided-list read returns an empty list in the shared helper.

The standing loop uses a separate scheduler.
It does not directly turn wishlist rows into tasks or insert the shared delivered-item block.
Its pending-action path selects claimable obligations before ordinary research modules.
Some review actions remain manager work and are excluded from worker dispatch.

Source: [head cycle](../ref_all_executor/head_orchestrator.py#L40),
[prompt formatter](../ref_all_executor/wishlist.py#L4),
[research driver](../drive_research.py#L33),
[binary drivers](../drive_binresearch.py#L27),
[scheduler order](../ref_all_executor/standing_loop.py#L590),
and [manager-only exclusions](../ref_all_executor/standing_loop.py#L3451).

### Compatibility dashboard

The separate coverage service retains its own wishlist API and SQLite store.
Its subject dashboard shows wishlist items and a **provided** button for open items.
That button calls `POST /wishlist_resolve` and updates the existing row.
This differs from the workbench API's separate delivery row.

| Compatibility route | Behavior |
| --- | --- |
| `POST /wishlist` | Creates an open item with `subject`, `item`, optional `kind`, `reason`, and `requested_by`. |
| `GET /wishlist?subject=example&status=provided` | Lists matching items; the store returns at most 500. |
| `POST /wishlist_resolve` | Updates an existing row from a body with `id` and `status`. |

Use these routes only with the standalone coverage service.
They operate on that service's database, rather than automatically mirroring workbench rows.
The native workbench Ops panel provides ledger, pending-action, and capability controls.
It does not provide this compatibility wishlist button.

Source: [compatibility routes](../coverage_service/app.py#L414),
[update behavior](../coverage_service/store.py#L415),
and [dashboard action](../coverage_service/dashboard.py#L159).

## From a resource need to completed work

Consider a worker that needs metadata extraction and later needs a live network check.

1. The worker reads earlier evidence and the provided wishlist.
2. It records an open `exiftool` request with the research reason.
3. The watchdog finds the host executable or uses its configured installation path.
4. The watchdog writes a delivery row and a ledger receipt.
5. A supported head or driver prompt includes the delivered tool on its next dispatch.
6. The worker checks tool availability in its execution environment and records source or artifact evidence.
7. The worker requests a scoped capability before the live network action.
8. The operator examines the capability request and supplies an appropriate grant.
9. The supported execution path requests authorization for the intended action.
10. The worker submits the result and resolves related pending work with the necessary receipt.

A provided wishlist item records resource availability, rather than permission to use that resource against any target.
A capability grant carries the class, scope, expiry, and execution conditions used by the authorization decision.
Operator-token authentication applies to capability mutations when the deployment configures that credential.
The decision API records its result; it does not execute an arbitrary submitted command.
See [execution boundaries](control-in-depth.md).

A direct `capability_missing` failure can create a capability request and an operator-decision pending action.
A direct `scope_blocked` failure can create a pending action with a `scope_decision` receipt type.
Neither path creates a wishlist item automatically.
The operator can track a related resource need in the wishlist and keep the decision in its own queue.
A capability grant creates a separate grant record; it does not update the request row or a wishlist item.

Source: [failure routing](../ref_all_executor/standing_loop.py#L2837),
[capability API](../arcticbase/backend/src/arctic_base/api/refall_capabilities.py#L18),
and [pending-action receipt routes](../arcticbase/backend/src/arctic_base/api/refall_pending_actions.py#L116).

## Related guides

- [Evidence and verification](evidence.md).
- [Control in Depth](control-in-depth.md).
- [API reference](api.md).
- [Operating guide](../OPERATING_GUIDE.md).
- [Feature codex](codex.md).
