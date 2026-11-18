# REFALL AB development

## Install development dependencies

1. Install the backend development environment.

   ```bash
   uv sync --project arcticbase/backend --group dev
   ```

2. Install the executor dependencies.

   ```bash
   uv pip install --python arcticbase/backend/.venv/bin/python -r coverage_service/requirements.txt
   ```

## Do the tests

Run these commands from the repository directory.

1. Do the repository tests.

   ```bash
   PYTHONPATH="$PWD:$PWD/arcticbase/backend/src" arcticbase/backend/.venv/bin/python -m pytest -q
   ```

2. Do the backend tests.

   ```bash
   uv run --project arcticbase/backend pytest arcticbase/backend/tests -q
   ```

The repository tests cover coverage storage, work claims, executor clients, routing, submissions, reports, and lifecycle behavior.
Documentation checks cover navigation and the operating contract.
Tests marked `live` require the external services named by the test.

## Frontend build

```bash
pnpm --dir arcticbase/frontend install --frozen-lockfile
pnpm --dir arcticbase/frontend build
```

## Source organization

Use `ref_all_executor/` for reusable loop behavior.
Use `coverage_service/` for compatibility coverage behavior.
Use `arcticbase/backend/src/arctic_base/` for workbench APIs and storage.
Use `arcticbase/frontend/src/` for the web interface.
Keep subject-specific harnesses and generated research results in subject workspaces.

## Documentation terms

Use REFALL AB as the product name.
Use ArcticBase only for implementation paths and backend component names.
Define specialist terms at first use.
Write procedures as short commands with one action in each sentence.
Keep descriptive sentences at 25 words or fewer.
Keep procedural sentences at 20 words or fewer.
The writing standard is [ASD-STE100 Issue 9](https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf).
