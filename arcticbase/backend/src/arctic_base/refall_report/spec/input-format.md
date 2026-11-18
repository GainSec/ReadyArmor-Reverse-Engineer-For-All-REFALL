# REFALL Report Input Format

Generate reports from REFALL workbench state in the backend.

## API inputs

Use these routes with the `/api/workbenches/{slug}` prefix:

- `/coverage/stats`.
- `/ledger/entries`.
- `/ledger/stats`.
- `/pending-actions`.
- `/closeout/gate`.
- `/runtime/events`.
- `/runtime/nonfatal-errors`.
- `/runtime/observations`.
- `/runtime/artifacts`.
- `/runtime/evidence-graph`.
- `/capabilities`.

## Additional records

Include the following records when available:

- Workbench object metadata.
- The `refall_current_report_object_id` custom field.
- Finding and validation records.
- Disposition transition receipts and refusals.
- Capability grants, requests, revocations, and execution decisions.
- Receipt `source_hashes` for source or configuration freshness.
- `capability_missing` and `scope_blocked` states.
- Nonfatal error projections from runtime events and ledger refusals or blockers.
- Visual artifacts and metadata from analysis tools, captures, screenshots, and PoC validation.

Preserve object identifiers, ledger identifiers, source anchors, binary anchors, and endpoint or configuration references in generated output.

## Visual artifact metadata

Preserve these fields:

- Type, title, and purpose.
- Source tool and command or MCP call.
- Input references.
- Output object or path.
- MIME type and size.
- Available hash.
- Inline or linked placement.
- Caption.
- Related finding and ledger identifiers.

Suitable source tools include Graphviz, CodeCharta, Codebadger, Joern, and codegraph tools.
Request or response captures, screenshots, and PoC validation can also produce visual artifacts.

## Runtime artifact metadata

Preserve these fields:

- Artifact identifier and kind.
- Subject and run identifier.
- Task identifier and source event identifier.
- Published workbench object identifier, when available.
- Filesystem path.
- MIME type and size.
- SHA-256 hash.
- Creation timestamp.

## Runtime observations

Preserve the claim, kind, confidence, evidence references, source anchors, limitations, and source event identifier.

## Nonfatal error records

Preserve the source, type, summary, failure class, task and session identifiers, refusal reasons, artifact references, and creation timestamp.
