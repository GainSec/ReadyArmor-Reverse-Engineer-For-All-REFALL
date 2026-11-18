#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATH="$ROOT/bin:$ROOT/.venv/bin:$ROOT/node_modules/.bin:$PATH"
export PATH
export SEMGREP_USER_AGENT_APPEND="refallinfr-toolchain"

usage() {
  cat <<'EOF'
usage:
  run.sh <TARGET_DIR> <OUTPUT_DIR>
  run.sh --dry-run <TARGET_DIR> <OUTPUT_DIR>
  run.sh --help

Runs the persistent code-understanding toolchain against TARGET_DIR and writes:
  graphs/*.dot|*.json
  indexes/*.json
  metrics/*
  semgrep/*.json
  scip/index.scip
  run_manifest.json
  logs/*

The runner is resilient: each tool logs independently and failures do not stop
later tools from running.
EOF
}

if [ "${1:-}" = "--help" ] || [ "$#" -eq 0 ]; then
  usage
  exit 0
fi

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=1
  shift
fi

if [ "$#" -ne 2 ]; then
  usage >&2
  exit 2
fi

TARGET="$(cd "$1" 2>/dev/null && pwd)"
if [ -z "${TARGET:-}" ]; then
  echo "Target directory does not exist: $1" >&2
  exit 2
fi
OUT="$(mkdir -p "$2" && cd "$2" && pwd)"

mkdir -p "$OUT/graphs" "$OUT/indexes" "$OUT/metrics" "$OUT/semgrep" "$OUT/scip" "$OUT/logs"
mkdir -p "$OUT/codecharta"
STATUS_TSV="$OUT/run_status.tsv"
: > "$STATUS_TSV"

steps() {
  cat <<EOF
repo-manifest|python3 "$ROOT/bin/module-import-index" "$TARGET" "$OUT/indexes/module-imports.json"
jedi-symbol-index|python3 "$ROOT/bin/jedi-symbol-index" "$TARGET" "$OUT/indexes/jedi-python-symbols.json"
semgrep-auto|semgrep scan --config auto --json --output "$OUT/semgrep/semgrep-auto.json" "$TARGET"
ast-grep-python-eval|sg --lang python --pattern 'eval(\$\$\$)' --json "$TARGET" > "$OUT/indexes/ast-grep-python-eval.json"
ast-grep-python-subprocess|sg --lang python --pattern 'subprocess.\$METHOD(\$\$\$)' --json "$TARGET" > "$OUT/indexes/ast-grep-python-subprocess.json"
ast-grep-ts-exec|sg --lang ts --pattern 'exec(\$\$\$)' --json "$TARGET" > "$OUT/indexes/ast-grep-ts-exec.json"
scip-python|scip-python index --cwd "$TARGET" --project-name "$(basename "$TARGET")" --output "$OUT/scip/index.scip"
scip-typescript|scip-typescript index --cwd "$TARGET" --infer-tsconfig --output "$OUT/scip/typescript.scip"
code2flow-python|code2flow "$TARGET" --language py --skip-parse-errors --output "$OUT/graphs/code2flow-python.dot"
code2flow-js|code2flow "$TARGET" --language js --skip-parse-errors --output "$OUT/graphs/code2flow-js.dot"
pyan3|find "$TARGET" -name '*.py' -not -path '*/.venv/*' -not -path '*/node_modules/*' -print0 | xargs -0 --no-run-if-empty pyan3 --uses --defines --dot > "$OUT/graphs/pyan3-python.dot"
dependency-cruiser-json|depcruise --no-config "$TARGET" --output-type json > "$OUT/graphs/dependency-cruiser.json"
dependency-cruiser-dot|depcruise --no-config "$TARGET" --output-type dot > "$OUT/graphs/dependency-cruiser.dot"
madge-json|madge --json "$TARGET" > "$OUT/graphs/madge.json"
madge-dot|madge --dot "$TARGET" > "$OUT/graphs/madge.dot"
lizard-csv|lizard "$TARGET" -o "$OUT/metrics/lizard.csv"
radon-cc|radon cc -j "$TARGET" > "$OUT/metrics/radon-cc.json"
radon-mi|radon mi -j "$TARGET" > "$OUT/metrics/radon-mi.json"
graphviz-render|"$ROOT/bin/render-dot-graphs" "$OUT/graphs"
codecharta-lizard|"$ROOT/bin/lizard-to-codecharta" "$OUT/metrics/lizard.csv" "$OUT/codecharta/lizard.cc.json" "$(basename "$TARGET")"
semgrep-report-viewer|cp "$ROOT/viewers/semgrep-report.html" "$OUT/semgrep/semgrep-report.html"
python-lsp-version|pylsp --version > "$OUT/indexes/python-lsp-server.version.txt"
tool-versions|python3 -m pip freeze > "$OUT/metrics/pip-freeze.txt" && npm ls --prefix "$ROOT" --depth=0 --json > "$OUT/metrics/npm-ls.json"
EOF
}

if [ "$DRY_RUN" -eq 1 ]; then
  echo "DRY RUN target=$TARGET output=$OUT"
  steps
  exit 0
fi

run_step() {
  local name="$1"
  local cmd="$2"
  local log="$OUT/logs/$name.log"
  local start end rc status
  start="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  if bash -lc "$cmd" >"$log" 2>&1; then
    rc=0
    status="ok"
  else
    rc=$?
    status="failed"
  fi
  end="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$status" "$rc" "$start" "$end" "$log" >> "$STATUS_TSV"
  printf '%-28s %s rc=%s log=%s\n' "$name" "$status" "$rc" "$log"
}

while IFS='|' read -r name cmd; do
  [ -n "$name" ] || continue
  run_step "$name" "$cmd"
done < <(steps)

python3 - "$TARGET" "$OUT" "$STATUS_TSV" "$ROOT/versions.lock" > "$OUT/run_manifest.json" <<'PY'
import json
import sys
from pathlib import Path

target, out, status_tsv, lock = map(Path, sys.argv[1:])
runs = []
for line in status_tsv.read_text(encoding="utf-8").splitlines():
    name, status, rc, start, end, log = line.split("\t")
    runs.append(
        {
            "name": name,
            "status": status,
            "return_code": int(rc),
            "started_at": start,
            "ended_at": end,
            "log": log,
        }
    )
data = {
    "target": str(target),
    "output_dir": str(out),
    "versions_lock": str(lock),
    "tools_attempted": len(runs),
    "ok": [item["name"] for item in runs if item["status"] == "ok"],
    "failed": [item for item in runs if item["status"] != "ok"],
    "runs": runs,
}
print(json.dumps(data, indent=2, sort_keys=True))
PY

echo
echo "SUMMARY"
python3 - "$OUT/run_manifest.json" <<'PY'
import json
import sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
print(f"OK: {len(data['ok'])}")
print(f"FAILED: {len(data['failed'])}")
for item in data["failed"]:
    print(f"- {item['name']}: rc={item['return_code']} log={item['log']}")
PY
