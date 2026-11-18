# REFALL AB API reference

The backend exposes an HTTP API.
Use the configured service URL as the base for each route.
Get the running schema from `/openapi.json`.
Read interactive API documentation at `/docs`.

## Subjects and operations

| Method | Route | Function |
| --- | --- | --- |
| GET | `/api/health` | Read service health. |
| POST | `/api/refall/subjects` | Create a subject workbench. |
| GET | `/api/refall/ops/status` | Read infrastructure state. |
| GET | `/api/refall/ops/agents` | Read agent state. |
| POST | `/api/refall/ops/command` | Run an allowed named command. |

Named commands include `context`, `coverage`, `threat-model`, `doctor`, `estimate`, `start`, `update`, and `closeout`.
Operation commands require the corresponding enable settings.
Enabled process launches through Start and Update also require a scoped capability grant.
A refused authorization returns HTTP 403 before process release.

## Workbench state

The following paths are relative to `/api/workbenches/{slug}`.
Replace `{slug}` with the subject workbench identifier.

| Path | Stored or returned information |
| --- | --- |
| `/coverage/context` | Shared subject briefing. |
| `/coverage/source-inventory` | Source inventory. |
| `/coverage/scope-overlay` | Scope boundaries. |
| `/coverage/threat-model` | Threat model. |
| `/coverage/wishlist` | Resource requests and provided-resource records. |
| `/ledger/entries` | Append and query evidence and decision records. |
| `/ledger/entries/{entry_id}` | Read one ledger entry. |
| `/ledger/stats` | Counts grouped by kind, lane, and severity. |
| `/pending-actions` | Unresolved obligations. |
| `/runtime/events` | Runtime events. |
| `/runtime/manifest` | Current run manifest. |
| `/runtime/nonfatal-errors` | Read-only failure projection. |
| `/runtime/observations` | Projected observations. |
| `/runtime/artifacts` | Artifact records. |
| `/runtime/evidence-graph` | Evidence relationships. |
| `/capabilities` | Capability requests and decisions. |
| `/execution/authorize` | Action authorization. |
| `/closeout/gate` | Closeout conditions. |
| `/refall-report` | Pinned current report. |

Use the running schema for request bodies and supported methods.
The coverage API includes claims, research units, findings, investigations, and statistics.

## Capability and operator boundaries

`POST /api/workbenches/{slug}/execution/authorize` returns and records an authorization decision.
It does not execute the requested command.
Callers must obey the decision before action release.

Capability grant and revoke authentication activates with `REFALL_CAPABILITY_OPERATOR_TOKEN_PATH`.
Protected requests supply `X-REFALL-Operator-Token`.
The unset default accepts caller-supplied identity fields without token authentication.
The closeout override route separately records a supplied operator name, check IDs, reason, and receipt.
It does not use the capability-token dependency.
Read [Control in depth](control-in-depth.md) for route responsibilities and deployment authority.

## Finding transitions

Submit a transition with `POST /api/workbenches/{slug}/findings/{finding_id}/transitions`.
Read transition history with `GET` on the same route.
Read refused transitions at `/api/workbenches/{slug}/disposition/refusals`.

A transition identifies the current state, proposed state, reason, receipt type, and supporting evidence.
Source hashes can bind the receipt to exact source bytes.
Read [Evidence](evidence.md) for the status and receipt models.

## Workbench presentation

Use `PUT /api/workbenches/{slug}/theme` to replace the workbench theme.
The request body contains a `raw` field with YAML frontmatter and Markdown.
Read `/api/agent/conventions` for the theme format.

## Reports

REFALL report routes use `/api/refall/reports/`.
The report module serves the specification and report assembly functions.
The pinned workbench report route selects the current report explicitly.

## Ledger and wishlist procedures

Use `POST /api/workbenches/{slug}/ledger/entries` to append a supported entry kind.
Use GET on the same route to list records.
List filters are `kind`, `lane`, `severity`, and `since`.
The ledger exposes lookup and statistics routes without entry update or delete operations.

Use POST and GET on `/api/workbenches/{slug}/coverage/wishlist` to record and list wishlist rows.
List requests can select `status`.
Delivery records use `provided`; the watchdog appends that row separately from the original open request.
The compatibility coverage service has its own `/wishlist` and `/wishlist_resolve` routes.
Read [Ledger and wishlist](ledger-and-wishlist.md) for payloads and the distinction between the route families.
