# REFALL AB analysis toolchain

The toolchain creates source indexes, graphs, metrics, and static analysis results.
Optional MCP services give specialist agents access to additional analysis tools.
Pinned versions are defined in `versions.lock`.

## Install

1. Open the toolchain directory.
2. Run `./install.sh`.
3. Examine the installation result.

The installer creates local Python and Node.js environments.
It also installs the configured tool shims and supporting resources.

## Analyze source

Run these commands from the repository directory.

1. Examine the proposed analysis steps.

   ```bash
   toolchain/run.sh --dry-run /path/to/subject toolchain/output/example
   ```

2. Run the analysis.

   ```bash
   toolchain/run.sh /path/to/subject toolchain/output/example
   ```

3. Examine `run_manifest.json` in the output directory.
4. Link useful results to the subject workbench.

## Tools and outputs

| Tool | Output or function |
| --- | --- |
| Semgrep | Rule findings in JSON. |
| ast-grep | Structural source matches. |
| SCIP Python and TypeScript | Symbol indexes. |
| Jedi | Python symbols. |
| code2flow and pyan3 | Call graphs. |
| dependency-cruiser and madge | JavaScript dependency graphs. |
| Lizard | Function complexity measurements. |
| Radon | Python complexity and maintainability measurements. |
| Graphviz | SVG and PNG graph images. |
| CodeCharta | Code-city data from complexity measurements. |
| Serena | Semantic source tools through MCP. |
| Codebase-Memory | Persistent source graph through MCP. |
| Codebadger | Code property graphs, data flow, taint analysis, and slicing. |

## Output directories

| Path | Contents |
| --- | --- |
| `graphs/` | Graph data and rendered images. |
| `indexes/` | Symbol, import, and pattern indexes. |
| `metrics/` | Complexity and package measurements. |
| `codecharta/` | CodeCharta `.cc.json` files. |
| `semgrep/` | Findings and the local report viewer. |
| `scip/` | SCIP indexes. |
| `logs/` | Per-tool output. |
| `run_manifest.json` | Step results and return codes. |

## Manage optional services

```bash
toolchain/ctl.sh status
toolchain/ctl.sh up serena
toolchain/ctl.sh down serena
toolchain/ctl.sh up codebadger-mcp
toolchain/ctl.sh restart python-lsp-server
toolchain/ctl.sh down
```

`ctl.sh up` preserves an already healthy service.
`ctl.sh down` first sends TERM to the service process group.
It sends KILL if the process does not exit.
The registry is `config/services.json`.
Only entries in `services[]` are active.

## Codebadger

Start Codebadger when the subject needs property graphs, taint analysis, or slicing.
The installer or first start obtains the pinned Codebadger source.
Docker supplies its supporting services.

Place local source under `toolchain/third_party/codebadger/playground/subjects/<subject>`.
Use `/app/playground/subjects/<subject>` as the corresponding container path.
The MCP service binds to loopback on port `4242`.
Its configuration is available through `toolchain/bin/codebadger-service mcp-config`.

## Agent configuration

MCP configuration examples are in `config/`.
Use `serena-mcp-config.json`, `codebase-memory-mcp-config.json`, or `codebadger-mcp-config.json` for the required service.
The service registry also contains disabled extension slots.
Copy a slot into `services[]` only after its command and health check are configured.
