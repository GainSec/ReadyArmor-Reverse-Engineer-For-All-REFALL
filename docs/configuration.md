# REFALL AB configuration

Set environment variables before the process starts.
The backend settings are defined in `arcticbase/backend/src/arctic_base/config.py`.
The executor settings are defined in `ref_all_executor/config.py`.

## Backend and storage

| Variable | Default | Purpose |
| --- | --- | --- |
| `ARCTIC_BASE_HOST` | `auto-lan` | Backend listen address. |
| `ARCTIC_BASE_PORT` | `7673` | Backend listen port. |
| `ARCTIC_BASE_DATA` | `./data` | Workbench storage directory. |
| `ARCTIC_BASE_FRONTEND_DIST` | `../frontend/dist` | Built frontend directory. |
| `ARCTIC_BASE_SEED_DATA` | `./seed` | Initial workbench data. |
| `REFALL_DATA_ROOT` | `/var/lib/refall` | REFALL data parent. |
| `REFALL_SUBJECT_ROOT` | Derived from the data root | Subject storage parent. |
| `REFALL_ARCTICBASE_DATA` | `/var/lib/refall/arcticbase` | Deployment storage path. |
| `REFALL_ARCTICBASE_HOST` | `auto-lan` | Advertised service host. |
| `REFALL_ARCTICBASE_PORT` | `7673` | Advertised service port. |
| `REFALL_PUBLIC_BASE_URL` | `auto-lan` | Public service URL. |
| `REFALL_REPO_ROOT` | Derived from the backend location | Repository path used by operation commands. |

`auto-lan` selects a private LAN address.
The fallback address is `127.0.0.1`.
Set explicit paths for portable deployments.

## Execution and operations

| Variable | Default | Purpose |
| --- | --- | --- |
| `REFALL_ENABLE_OPS` | `false` | Enable operation routes. |
| `REFALL_ENABLE_OPS_COMMANDS` | `false` | Enable named operation commands. |
| `REFALL_ENABLE_LOOP_LAUNCH` | `true` | Permit capability-checked process launch. |
| `REFALL_ENABLE_LOOP_SUPERVISOR_CRON` | `true` | Enable supervisor cron support. |
| `REFALL_OPS_ALLOWED_COMMANDS` | See the deployment example | Allowlist for named commands. |
| `REFALL_LOOP_MAX_PARALLEL` | `4` | Maximum concurrent work items. |
| `REFALL_LOOP_POLL_INTERVAL_S` | `5` | Poll interval in seconds. |
| `REFALL_LOOP_REPORT_INTERVAL_CYCLES` | `10` | Report interval in loop cycles. |
| `REFALL_LOOP_STALL_CYCLES` | `36` | Stall threshold in loop cycles. |
| `REFALL_CAPABILITY_OPERATOR_TOKEN_PATH` | Unset | Operator token file for capability changes. |

The named command allowlist is in `deploy/refall-arcticbase.env.example`.
It includes status, subject, agent, lifecycle, context, coverage, diagnosis, estimate, and log commands.

### Operator authentication and action release

Set `REFALL_CAPABILITY_OPERATOR_TOKEN_PATH` to a host-managed token file to authenticate capability grant and revoke requests.
Keep this file outside worker access.
Send its value in `X-REFALL-Operator-Token` from the authenticated operator client.
The backend uses constant-time comparison and records the authenticated grantor as `operator`.
An unavailable token file gives HTTP 503; an invalid token gives HTTP 403.

The default unset value disables token authentication on these routes.
Grantor fields then come from the request body.
The browser capability client does not attach this token automatically.
Use a host-side authenticated client to establish grants in a protected deployment.
Operation enable switches control functionality rather than caller identity.
The closeout override route records the supplied operator name and has no capability-token authentication dependency.
Restrict API reachability to the intended callers.

The authorization endpoint returns a decision without executing commands.
Backend Start and Update obey that decision before process launch.
Worker tools need their actual runtime permissions or an executor integration that obeys the broker.
Read [Control in depth](control-in-depth.md) for applicable scope fields, defaults, and record gates.

## Agent execution

| Variable | Default | Purpose |
| --- | --- | --- |
| `REFALL_OPENHANDS_BASE` | Local port `8000` | Agent Canvas service URL. |
| `REFALL_OPENHANDS_API_KEY_PATH` | `~/.openhands/agent-canvas/api-key.txt` in the executor | API key file. |
| `REFALL_WORKSPACE` | `/projects/REFALL-V10` | Container repository path. |
| `REFALL_SUBJECT_WORKSPACE_ROOT` | `/projects` | Container subject parent. |
| `REFALL_AGENT_WORKSPACE_HOST_ROOT` | `~/refallsub` | Host workspaces for agent output. |
| `REFALL_AGENT_WORKSPACE_CONTAINER_ROOT` | `/projects/refallsub` | Container workspaces for agent output. |
| `REFALL_HEAD_PROVIDER` | `codex` | Manager provider. |
| `REFALL_ALLOWED_HEAD_PROVIDERS` | `codex,claude,grok` | Permitted manager providers. |
| `REFALL_CODEX_COMMAND` | `codex` | Codex executable. |
| `REFALL_CLAUDE_COMMAND` | `claude` | Claude executable. |
| `REFALL_GROK_COMMAND` | `grok` | Grok executable. |
| `REFALL_CONTEXT_MANAGER_TIMEOUT_S` | `1800` | Context generation timeout in seconds. |
| `REFALL_WORKBENCH_BASE` | Public URL or detected LAN URL | Executor workbench URL. |
| `REFALL_WORKBENCH_SLUG` | `ref-all` | Default publishing workbench. |

The backend API key path defaults to unset.
Configure the same key file for the backend and executor when both call Agent Canvas.
The Automation API prefix is `/api/automation/v1`.

Source projection reuses matching Docker mounts with their existing access mode.
Its copy fallback creates an ordinary container directory.
Configure read-only source mounts when mechanical write protection is required.
The dispatcher identifies separate source and scratch locations in the worker objective.
Those instructions do not replace mount permissions or network restrictions.

## Result validation and retries

| Variable | Default | Purpose |
| --- | --- | --- |
| `REFALL_REQUIRE_STRUCTURED_SUBMIT` | `false` | Reject missing or malformed structured results when enabled. |
| `REFALL_RETRY_MAX_ATTEMPTS` | `2` | Retry limit for recoverable failures. |
| `REFALL_RETRY_BACKOFF_S` | `5` | Delay between retries in seconds. |
| `REFALL_RETRY_MAX_REPAIR_PROMPT_CHARS` | `4000` | Maximum prior output in a repair prompt. |

## Optional services

| Service | Address or configuration |
| --- | --- |
| Compatibility coverage API | `http://localhost:8900` |
| Coverage from an agent container | `http://host.docker.internal:8900` |
| Serena MCP | `http://127.0.0.1:20872/mcp` |
| Python LSP | `127.0.0.1:20871` |
| Codebadger MCP | `http://127.0.0.1:4242/mcp` |
| Codebase-Memory MCP | Standard input and output. |

`REFALL_SSH_RESOURCE_ALIASES` selects configured remote resources from the built-in allowlist.
The current allowlist contains `sectortw` and `sectortl`.
Set an empty value to disable these resources.
Read [Remote resources](codex-startup/04-REMOTE-SSH-RESOURCES.md) before remote execution.
