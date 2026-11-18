# REFALL AB documentation

REFALL coordinates bounded research and preserves its evidence across workers, sessions, and report revisions.
Use the guides below to understand the product, operate a subject, and trace its implementation.

## Understand the product

| Guide | Contents |
| --- | --- |
| [Product overview](../README.md) | Purpose, practical uses, capabilities, and the Ready Armor approach. |
| [Ready Armor in REFALL](ready-armor.md) | Distinctive research composition, practical value, retained knowledge, and actual acceptance boundaries. |
| [Research cycles](research-cycles.md) | Campaign polling, per-target passes, retries, supervision, and closeout. |
| [Ledger and wishlist](ledger-and-wishlist.md) | Evidence history, requested resources, fulfillment, worker briefings, and APIs. |
| [Feature catalog](features.md) | Subject state, scheduling, evidence capture, findings, authority, continuity, and reports. |
| [End-to-end workflows](end-to-end.md) | The complete operator-to-closeout path and source or binary research families. |
| [Technical codex](codex.md) | Source paths, execution order, state ownership, and runtime mechanisms. |
| [Research architecture](research-architecture.md) | Control principles, research memory, evidence boundaries, and product relationships. |
| [Control in depth](control-in-depth.md) | Resource boundaries, brokered release, task guidance, evidence gates, defaults, and exceptions. |
| [Architecture map](architecture.md) | Components, service flow, and persistent stores. |
| [Work modules](work-modules.md) | Packs, target dependencies, custom passes, selection rules, and examples. |

## Install and operate

| Guide | Contents |
| --- | --- |
| [Installation](../BASE-INSTALLATION.md) | Backend dependencies, frontend build, storage, and execution setup. |
| [Operating procedures](../OPERATING_GUIDE.md) | Subject creation, context, readiness, loop commands, reports, and shutdown. |
| [Configuration](configuration.md) | Addresses, storage, providers, execution, and retries. |
| [Manager procedures](../REFALL-MANAGER-OPERATING-GUIDE.md) | Detailed manager operation and decision requirements. |
| [Troubleshooting](troubleshooting.md) | Diagnosis, blocked work, recovery, and closeout failures. |
| [Deployment](../deploy/README.md) | Docker Compose and native service examples. |
| [Toolchain](../toolchain/MANIFEST.md) | Source analysis, outputs, optional MCP services, and lifecycle control. |

## Implement and extend

| Guide | Contents |
| --- | --- |
| [API reference](api.md) | Subject, coverage, runtime, evidence, capability, and report routes. |
| [Evidence requirements](evidence.md) | Submission identities, quality tiers, receipts, and closeout proof. |
| [Runtime contracts](specs/refall-runtime-discipline/README.md) | Individual runtime control references. |
| [Development](development.md) | Environments, existing tests, source organization, and writing conventions. |
| [Report standard](../arcticbase/backend/src/arctic_base/refall_report/spec/deliverable.md) | Required report content and deliverable modes. |

## Fresh manager startup

Read the files in `docs/codex-startup/` in numeric order.
The [starthere/](../starthere/README.md) directory contains the equivalent startup pack.
Read the stored subject context before you assign research work.

## Interactive edition

Open [the technical atlas](index.html) to explore the architecture, capabilities, operating traces, complete guides, and implementation excerpts.
Use [Documentation site](site.md) for the build and publishing procedure.

## Implementation file index

Use the [source file index](source-index.md) to locate implementation modules and their declared interfaces.
