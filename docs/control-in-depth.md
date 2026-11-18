# REFALL AB control in depth

REFALL controls a research campaign through several distinct decisions.
It selects work, checks brokered authority, captures results, validates record changes, and evaluates completion.
Each decision has a defined boundary.

The execution environment controls process permissions, filesystem mounts, network access, and available tools.
REFALL supplies campaign coordination and evidence controls above that environment.
This separation makes the reason for each refusal visible.
It also shows which component must enforce an execution restriction.

## Read the layers from resources to decisions

| Layer | Control type | Decision or result |
| --- | --- | --- |
| Source projection | Operation gate | Validate the projection request and prepare the configured container workspace. |
| Inventory | Observation | Record source identity, unreadable files, and symlink relationships. |
| Capability changes | Operator authority | Authenticate grant and revoke requests when token protection is configured. |
| Capability matching | Policy gate | Accept or refuse the request presented to the broker. |
| Backend launch | Operation gate | Refuse loop process release when authorization fails. |
| Work selection | Task gate | Select the next eligible assignment and allocate work claims. |
| Conversation bounds | Task gate | Send an iteration limit and classify outcomes before retry. |
| Context and scope | Model guidance | State the assignment, boundaries, resources, and expected evidence. |
| Resume preflight | Task gate | Compare checkpoint inputs on supported continuation paths. |
| Continuous capture | Observation | Preserve worker results and execution records. |
| Finding admission | Record gate | Check evidence references and declared external scope. |
| Finding disposition | Record gate | Check typed receipts before status or quality changes. |
| Pending resolution | Record gate | Check required receipts for unresolved obligations. |
| Report replacement | Record gate | Preserve populated report sections through the assembly path. |
| Closeout | Record gate | Accept or block the closed campaign result. |
| Closeout exceptions | Operator authority | Record an explicit exception for identified checks. |

This order describes responsibility from resources to campaign decisions.
A particular command can visit these layers in a different order.

## 1. Establish the execution resources

A subject has a host source path and a container source location.
The projection helper resolves the host path and requires a directory.
It rejects empty subject names, slash-containing names, `.` and `..`.
It also checks that the configured Agent Canvas container runs.
A failed check prevents this synchronization operation from completing.

The helper first looks for a matching Docker mount.
When a matching mount exists, the result records its actual read-only or writable mode.
Otherwise, the helper copies the source into the container with `docker cp`.
A copied directory has the container's ordinary file permissions.
The copy path does not create a read-only mount.

Each dispatched task also receives a separate writable scratch directory.
Its name derives from the subject, lane, task class, and unit identity or objective hash.
The initial message identifies that directory and instructs the worker to preserve the subject source.
Read-only mount configuration supplies mechanical write prevention where that restriction is required.

REFALL does not install a general interceptor around worker shell, network, SSH, or external tool calls.
Agent Canvas, container configuration, process credentials, and tool services supply those execution boundaries.
The standalone source and binary drivers also depend on their configured execution environments.

Sources: [projection](../ref_all_executor/agent_workspace.py#L17), [workspace creation](../ref_all_executor/config.py#L207), [workspace instructions](../ref_all_executor/standing_loop.py#L187).

## 2. Record source identity

The inventory records file paths, hashes, sizes, line counts, and kinds.
Unreadable files remain in a skipped-file record.
Symlink observations identify relationships that resolve outside the configured root.
Directory traversal does not descend through directory symlinks.
A file symlink can still supply content through its resolved target.

Inventory collection establishes examination identity.
It does not confine later file access.
Finding admission can compare source anchors with this inventory.
Receipt validation can compare supplied source hashes with the current files.
These controls detect record inconsistencies at their respective acceptance points.

Source: [inventory and symlink observations](../ref_all_executor/source_inventory.py).

## 3. Give capability changes an authenticated operator boundary

Capability grants define an action class, scope, grantor, expiry, and optional additional requirements.
Grant and revoke routes support a host-managed operator token.
Set `REFALL_CAPABILITY_OPERATOR_TOKEN_PATH` to activate this authentication.
The request must supply `X-REFALL-Operator-Token` with the file's token value.
Successful authentication sets the grantor to `operator`.
A missing or invalid token gives HTTP 403.
An unavailable credential file gives HTTP 503.

The token path defaults to unset.
In that mode, grant and revoke routes do not authenticate the operator token.
The grant route retains the supplied grantor identity.
The browser capability client does not attach the operator token automatically.
A protected deployment can issue grants through an authenticated host-side client.

The token file, API reachability, and host-side client belong to the deployment's authority boundary.
Restrict their access to the intended operators.
String fields such as `granted_by` and `requested_by` do not establish authenticated identity by themselves.

Source: [operator authentication and capability routes](../arcticbase/backend/src/arctic_base/api/refall_capabilities.py#L18).

## 4. Evaluate the action presented to the broker

An authorization request includes a capability class, declared effects, command, requester, and target.
The broker requires a class and nonempty effects.
It searches active grants of the same class and excludes expired grants.
Revoked grants are excluded from that search.
No matching grant means refusal.

The matcher applies host and port lists when both the relevant request value and grant restriction exist.
A restricted HTTP method requires a matching declared method.
A local-command request with a target path requires path scope.
Applicable path scope compares the requested target with permitted roots.
The matcher uses resolved paths, with a textual containment fallback for resolution errors.

Network, Docker, Codebadger, and secret checks connect applicable effects with their capability classes.
Recognized destructive commands require `destructive_action`.
Destructive declarations also activate configured dry-run and approval-token checks.
These checks examine declared values and recognized command forms.
They are not a complete shell parser or an inspection of every later process effect.

The self-grant rule compares requester and grantor strings.
Matching nonoperator strings are refused.
The protected grant route supplies the authenticated operator identity when token protection is active.

`POST /api/workbenches/{slug}/execution/authorize` returns the decision and records it in the ledger.
It does not execute the proposed command.
The caller must use the decision before it releases the action.
A direct worker tool invocation does not automatically pass through this route.

Sources: [matching](../arcticbase/backend/src/arctic_base/refall/coverage_store.py#L1458), [conditions](../arcticbase/backend/src/arctic_base/refall/coverage_store.py#L1764), [decision route](../arcticbase/backend/src/arctic_base/api/refall_capabilities.py#L171).

## 5. Release the backend loop process

The named operation route supplies a concrete caller that obeys the broker decision.
Operation routes default to disabled through `REFALL_ENABLE_OPS`.
Named commands also require `REFALL_ENABLE_OPS_COMMANDS`.
The command name must appear in `REFALL_OPS_ALLOWED_COMMANDS`.
These switches enable functionality; they do not authenticate an operator.

Start requires stored, nonempty subject context.
Its absence gives HTTP 409.
When loop launch is enabled, Start and Update construct a `run_local_command` request for the standing loop.
The request includes the subject path and a declared process effect.
The backend records the authorization decision.
Refusal gives HTTP 403 before the loop process starts.

Loop launch defaults to enabled once the operation route is enabled.
Setting `REFALL_ENABLE_LOOP_LAUNCH=false` skips actual launch and its authorization check.
Direct executor entry points and embedded launcher callbacks have their own calling paths.
This launch gate describes the backend lifecycle route.

Source: [backend lifecycle release](../arcticbase/backend/src/arctic_base/api/refall_ops_commands.py#L266).

## 6. Bound the assigned work

The scheduler prioritizes pending actions, subject setup, fresh coverage, finding work, and later unit passes.
Claims and per-target progress coordinate allocation.
Eligible module selection checks dependencies, completed work, active target work, and module concurrency.
Recorded paths allow applicable inclusion and exclusion checks.

Fresh characterization claims coverage directly.
It uses the `characterize` task class and a 30-iteration conversation request.
It does not use the later module eligibility branch.
Later unit selection supplies the recorded path, but it does not supply `unit_state`.
Module fields therefore have specific selection paths, as described in [Work modules](work-modules.md).

The dispatcher sends the workspace, objective, provider settings, and iteration limit to Agent Canvas.
Global loop parallelism defaults to four work items.
The runtime classifies recognized capability, scope, and operator-stop outcomes before retry.
Those outcomes create decision obligations rather than ordinary automatic retries.
Recoverable worker failures use the configured retry limit, which defaults to two attempts.

Context and scope also appear in the worker's objective.
These instructions guide reasoning, target selection, resource use, and evidence submission.
They do not turn an assignment path into a filesystem or network access restriction.

Sources: [selection order](../ref_all_executor/standing_loop.py#L590), [eligibility](../ref_all_executor/work_modules.py#L333), [dispatch](../ref_all_executor/standing_loop.py#L205), [outcome classification](../ref_all_executor/runtime_invocation.py#L23).

## 7. Check continuation and preserve observations

Resume preflight compares checkpoint input hashes with current source and configuration identities.
A returned drift refusal stops the supported continuation path.
The runtime retains a visible refusal event and decision state.
This comparison requires prior checkpoints and the relevant API support.
Missing optional support and some unavailable-service paths continue without a refusal.

During execution, polling reads available conversation events and workspace results.
Completion handling first classifies the invocation, parses its output, and checks submission identity.
It preserves available observations before handling the classified outcome or scheduling retry.
Useful observations can therefore survive a failed conversation.
A subject module without durable canonical observations remains unfinished.

Capture records what the worker supplied or what the runtime observed.
It does not prove every recorded assertion or prevent the original tool action.
Structured terminal submission is optional by default.
Enable `REFALL_REQUIRE_STRUCTURED_SUBMIT` to require its contract during terminal validation.

Sources: [resume comparison](../arcticbase/backend/src/arctic_base/refall/runtime_state.py#L346), [resume caller](../ref_all_executor/standing_loop.py#L2250), [incremental ingestion](../ref_all_executor/standing_loop.py#L1115).

## 8. Accept evidence and finding decisions separately

Finding admission requires evidence, confidence, and source or artifact references.
When an inventory is available, source anchors must belong to it.
Without inventory, anchor membership produces a warning.
External URL hosts require explicit inclusion in the scope overlay's `external_targets`.
A candidate outside that declared scope is refused admission.
The API records the refusal and creates review work.

This check acts on a proposed finding after worker activity.
It does not intercept the network operation that might have produced the evidence.
The scope overlay and a capability grant are separate records.
Changing one does not automatically change the other.

Existing finding decisions use typed transitions.
Direct validation updates cannot change finding status.
False-positive, duplicate, downgrade, chain deferral, and live-validation decisions have distinct receipt requirements.
Unresolved contradictory obligations can block suppressive transitions.
Receipts with supplied hashes also receive source-root containment and current-content checks.
An unhashed receipt does not activate those hash checks.

A refused transition preserves finding state and stores the refused attempt.
A receipt establishes the required decision record and evidence references.
It does not independently prove all factual claims or authenticate its declared author.

Sources: [finding admission](../arcticbase/backend/src/arctic_base/refall/promotion_gates.py#L12), [typed transitions](../arcticbase/backend/src/arctic_base/refall/coverage_store.py#L1008), [hash checks](../arcticbase/backend/src/arctic_base/refall/coverage_store.py#L112).

## 9. Require resolution and review completion

Pending actions preserve access requests, blocked scope, incomplete evidence, and decisions that still need attention.
A required receipt type must match and include evidence references.
Deferral and cancellation require receipt evidence.
An untyped action completed as `done` does not universally require evidence.

Report assembly protects populated sections against structural downgrade.
The default assembly path retains the current report and stores a diagnostic candidate when protected sections would disappear.
An explicit `allow_structural_downgrade` argument bypasses that replacement guard.
Generic object-content writes use a separate API path.

Closeout evaluates pending work, receipts, refused transitions, finding proof, expired claims, context, and report freshness.
Blocking failures produce a blocked lifecycle result.
Coverage below the default 95-percent threshold is advisory.
Draft reports and current report objects can exist before closeout succeeds.
The closeout gate does not control every object write, download, or external publication.

A closeout override requires identified checks and a nonempty receipt.
An accepted override converts a matching failed check into a nonblocking warning.
The ledger retains the exception and its stated reason.
The override route records the supplied operator name without the capability-token authentication dependency.
Deployment access control establishes who can reach that authority.

Sources: [pending resolution](../arcticbase/backend/src/arctic_base/refall/coverage_store.py#L1243), [report protection](../ref_all_executor/report_assemble.py#L16), [closeout](../arcticbase/backend/src/arctic_base/refall/closeout_gate.py#L14), [override route](../arcticbase/backend/src/arctic_base/api/refall_closeout.py#L33).

## Worked example: an out-of-scope operation

Assume the subject is `alpha`.
Its `write_subject` grant permits `/tmp/refall-subject`.
An agent proposes `touch /etc/passwd` with the target path `/etc/passwd`.

1. Submit the action to the authorization route with its class, effects, command, and target.
2. The broker compares the target with the grant's permitted path.
3. The broker returns `accepted: false` and records the refusal.
4. The calling executor keeps the action unreleased.
5. The operator examines the requested target and the actual research need.
6. Keep the refusal, or issue a separate grant for an approved operation.
7. Submit a new authorization request after any approved change.

The authorization route itself never launches `touch`.
Step 4 belongs to the caller that releases the operation.
The backend standing-loop launch implements this release discipline directly.
Worker tools need their own runtime enforcement or an integration that obeys broker decisions.

The existing [broker tests](../arcticbase/backend/tests/test_refall_capability_broker.py) cover path refusal, host refusal, method restrictions, expiry, and protected grant authentication.

An external validation request uses two additional campaign decisions.
The operator can add an approved host to the scope overlay and grant the necessary network capability separately.
A later finding can then cite that host under the admission rules.
The runtime still needs an executor that obeys authorization and an environment with the intended network restrictions.

## How this expresses the Ready Armor approach

A useful control has a named authority, an explicit boundary, and an observable decision.
REFALL applies that principle to campaign resources, brokered operations, assignments, evidence, and completion.
Its controls make research progress and unfinished authority decisions reviewable across workers and sessions.

ARA and BRA describe related control principles through their own runtime and assessment architectures.
REFALL implements its own scheduler, capability matcher, evidence records, and acceptance gates.
It does not import their policy engines or supply their execution interception mechanisms.
Read [Research architecture](research-architecture.md) for the wider system model.
