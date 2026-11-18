# REFALL AB installation

## Requirements

Use Python 3.12 or later for the backend.
Use uv to install the backend dependencies.
The frontend uses pnpm and Node.js.
The Docker build uses Node.js 24 and Python 3.13.

Research execution requires an Agent Canvas/OpenHands service with its Automation API.
A manager also requires the selected provider CLI.
Docker is necessary for container deployment and Codebadger.

## Install the backend

Run these commands from the `refall` directory.

1. Install the backend and development dependencies.

   ```bash
   uv sync --project arcticbase/backend --group dev
   ```

2. Install the executor dependencies in the same environment.

   ```bash
   uv pip install --python arcticbase/backend/.venv/bin/python -r coverage_service/requirements.txt
   ```

3. Select the repository directory.

   ```bash
   export REFALL_REPO_ROOT="$PWD"
   export PYTHONPATH="$PWD:$PWD/arcticbase/backend/src"
   export PATH="$PWD/arcticbase/backend/.venv/bin:$PATH"
   ```

## Build the web interface

1. Install the frontend dependencies.

   ```bash
   pnpm --dir arcticbase/frontend install --frozen-lockfile
   ```

2. Build the web interface.

   ```bash
   pnpm --dir arcticbase/frontend build
   ```

## Configure local services

1. Select the local service address.

   ```bash
   export ARCTIC_BASE_HOST=127.0.0.1
   export ARCTIC_BASE_PORT=7673
   export REFALL_PUBLIC_BASE_URL=http://127.0.0.1:7673
   export REFALL_WORKBENCH_BASE="$REFALL_PUBLIC_BASE_URL"
   ```

2. Select writable storage paths.

   ```bash
   export ARCTIC_BASE_DATA="$PWD/data/arcticbase"
   export REFALL_DATA_ROOT="$PWD/data/refall"
   export REFALL_SUBJECT_ROOT="$REFALL_DATA_ROOT/subjects"
   export ARCTIC_BASE_FRONTEND_DIST="$PWD/arcticbase/frontend/dist"
   export ARCTIC_BASE_SEED_DATA="$PWD/arcticbase/backend/seed"
   ```

3. Set the Agent Canvas address and API key path.

   ```bash
   export REFALL_OPENHANDS_BASE=http://127.0.0.1:8000
   export REFALL_OPENHANDS_API_KEY_PATH="$HOME/.openhands/agent-canvas/api-key.txt"
   ```

4. Enable the operation routes.

   ```bash
   export REFALL_ENABLE_OPS=true
   export REFALL_ENABLE_OPS_COMMANDS=true
   ```

5. Start the backend.

   ```bash
   python -m arctic_base
   ```

6. Open `http://127.0.0.1:7673`.

7. Read the health response.

   ```bash
   curl -fsS http://127.0.0.1:7673/api/health
   ```

The default backend address uses a detected LAN address when no host override is set.
The explicit local address above keeps all local examples consistent.
For remote access, set the public URL and listen address for that deployment.

## Configure execution

1. Install and configure Agent Canvas/OpenHands separately.
2. Mount the repository and subject directories in the agent container.
3. Set `REFALL_WORKSPACE` to the container repository path.
4. Set `REFALL_SUBJECT_WORKSPACE_ROOT` to the container subject parent.
5. Configure the selected provider CLI.
6. Run the subject diagnosis procedure before the first research loop.

The default container repository path is `/projects/REFALL-V10`.
The default container subject parent is `/projects`.
The host source path and container source path must refer to the same subject files.

## Optional source tools

Install the analysis tools with `toolchain/install.sh`.
Read Toolchain (`toolchain/MANIFEST.md`) before you start optional services.

## Container deployment

Read Deployment (`deploy/README.md`) for the Docker Compose configuration.
Read Configuration (`docs/configuration.md`) for the complete service settings.
Read `starthere/` or `docs/codex-startup/` for the manager startup sequence.
