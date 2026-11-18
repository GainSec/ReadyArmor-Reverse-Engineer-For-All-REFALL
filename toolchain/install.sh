#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK="$ROOT/versions.lock"
LOG_DIR="$ROOT/logs"
SUMMARY="$ROOT/install-summary.txt"
mkdir -p "$ROOT/bin" "$ROOT/config" "$ROOT/viewers" "$LOG_DIR"

# shellcheck source=/dev/null
source "$LOCK"

: > "$SUMMARY"

record() {
  printf '%-28s %s\n' "$1" "$2" | tee -a "$SUMMARY"
}

have_python_package() {
  "$ROOT/.venv/bin/python" - "$1" "$2" <<'PY'
import importlib.metadata as md
import sys
name, want = sys.argv[1], sys.argv[2]
try:
    got = md.version(name)
except md.PackageNotFoundError:
    raise SystemExit(1)
raise SystemExit(0 if got == want else 1)
PY
}

have_npm_package() {
  local name="$1"
  local want="$2"
  node - "$ROOT" "$name" "$want" <<'JS' >/dev/null 2>&1
const fs = require("fs");
const path = require("path");
const root = process.argv[2];
const name = process.argv[3];
const want = process.argv[4];
let pkgPath;
if (name.startsWith("@")) {
  const [scope, pkg] = name.split("/");
  pkgPath = path.join(root, "node_modules", scope, pkg, "package.json");
} else {
  pkgPath = path.join(root, "node_modules", name, "package.json");
}
const got = JSON.parse(fs.readFileSync(pkgPath, "utf8")).version;
process.exit(got === want ? 0 : 1);
JS
}

run_logged() {
  local name="$1"
  shift
  local log="$LOG_DIR/install-$name.log"
  if "$@" >"$log" 2>&1; then
    return 0
  fi
  return $?
}

sha256_matches() {
  local file="$1"
  local want="$2"
  [ -f "$file" ] || return 1
  command -v sha256sum >/dev/null 2>&1 || return 1
  got="$(sha256sum "$file" | awk '{print $1}')"
  [ "$got" = "$want" ]
}

have_codebase_memory() {
  [ -x "$ROOT/bin/codebase-memory-mcp" ] || return 1
  "$ROOT/bin/codebase-memory-mcp" --version 2>/dev/null | grep -qx "codebase-memory-mcp $CODEBASE_MEMORY_MCP_VERSION"
}

install_codebase_memory() {
  local os arch asset url sha tmp archive
  os="$(uname -s)"
  arch="$(uname -m)"
  if [ "$os" != "Linux" ]; then
    rm -f "$ROOT/bin/codebase-memory-mcp"
    record "codebase-memory-mcp" "SKIPPED unsupported OS $os for pinned Linux asset"
    return 0
  fi
  case "$arch" in
    aarch64|arm64)
      asset="$CODEBASE_MEMORY_MCP_LINUX_ARM64_ASSET"
      url="$CODEBASE_MEMORY_MCP_LINUX_ARM64_URL"
      sha="$CODEBASE_MEMORY_MCP_LINUX_ARM64_SHA256"
      ;;
    *)
      record "codebase-memory-mcp" "FAILED unsupported arch $arch; expected aarch64/arm64"
      return 0
      ;;
  esac

  if have_codebase_memory; then
    record "codebase-memory-mcp" "OK existing $CODEBASE_MEMORY_MCP_VERSION $arch"
    return 0
  fi

  tmp="$(mktemp -d)"
  archive="$tmp/$asset"
  if curl -fsSL "$url" -o "$archive" &&
    printf '%s  %s\n' "$sha" "$archive" | sha256sum -c - >/dev/null &&
    tar -xzf "$archive" -C "$tmp" &&
    [ -f "$tmp/codebase-memory-mcp" ]; then
    cp "$tmp/codebase-memory-mcp" "$ROOT/bin/codebase-memory-mcp"
    chmod 755 "$ROOT/bin/codebase-memory-mcp"
    rm -rf "$tmp"
    if have_codebase_memory; then
      record "codebase-memory-mcp" "INSTALLED $CODEBASE_MEMORY_MCP_VERSION $asset"
    else
      record "codebase-memory-mcp" "FAILED installed binary did not report $CODEBASE_MEMORY_MCP_VERSION"
    fi
  else
    rm -rf "$tmp"
    record "codebase-memory-mcp" "FAILED $CODEBASE_MEMORY_MCP_VERSION see $url"
  fi
}

install_codebadger() {
  if run_logged codebadger bash "$ROOT/bin/codebadger-service" ensure; then
    record "codebadger" "INSTALLED checkout $CODEBADGER_GIT_REF MCP port $CODEBADGER_MCP_PORT"
  else
    record "codebadger" "FAILED checkout $CODEBADGER_GIT_REF see $LOG_DIR/install-codebadger.log"
  fi
}

APT_UPDATED=0
apt_update_once() {
  [ "$APT_UPDATED" -eq 1 ] && return 0
  if [ "$(id -u)" -eq 0 ]; then
    env -u LD_LIBRARY_PATH DEBIAN_FRONTEND=noninteractive apt-get update
  elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    sudo -n env -u LD_LIBRARY_PATH DEBIAN_FRONTEND=noninteractive apt-get update
  else
    return 1
  fi
  APT_UPDATED=1
}

apt_install_package() {
  local pkg="$1"
  if [ "$(id -u)" -eq 0 ]; then
    env -u LD_LIBRARY_PATH DEBIAN_FRONTEND=noninteractive apt-get install -y "$pkg"
  elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    sudo -n env -u LD_LIBRARY_PATH DEBIAN_FRONTEND=noninteractive apt-get install -y "$pkg"
  else
    return 1
  fi
}

ensure_deb_package() {
  local name="$1"
  local pkg="$2"
  local got
  if got="$(dpkg-query -W -f='${Version}' "$pkg" 2>/dev/null)"; then
    record "$name" "OK existing $pkg==$got"
    return 0
  fi
  if command -v apt-get >/dev/null 2>&1 &&
    apt_update_once >/dev/null 2>&1 &&
    apt_install_package "$pkg" >/dev/null 2>&1; then
    got="$(dpkg-query -W -f='${Version}' "$pkg" 2>/dev/null || true)"
    record "$name" "INSTALLED $pkg==$got"
  else
    record "$name" "FAILED install $pkg; apt-get/sudo unavailable or package install failed"
  fi
}

install_semgrep_report_viewer() {
  local dest="$ROOT/viewers/semgrep-report.html"
  local css="$ROOT/viewers/semgrep-report-offline.css"
  if sha256_matches "$dest" "$SEMGREP_REPORT_SHA256"; then
    record "semgrep-report" "OK existing $SEMGREP_REPORT_COMMIT"
    return 0
  fi
  if curl -fsSL "$SEMGREP_REPORT_URL" -o "$dest" &&
    sha256_matches "$dest" "$SEMGREP_REPORT_UPSTREAM_SHA256" &&
    python3 - "$dest" "$css" <<'PY' &&
from pathlib import Path
import sys

dest = Path(sys.argv[1])
css = Path(sys.argv[2])
text = dest.read_text(encoding="utf-8")
style = css.read_text(encoding="utf-8")
needle = '    <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">\n    <style>\n'
if needle not in text:
    raise SystemExit("semgrep-report upstream template changed")
dest.write_text(text.replace(needle, "    <style>\n" + style, 1), encoding="utf-8")
PY
    sha256_matches "$dest" "$SEMGREP_REPORT_SHA256"; then
    record "semgrep-report" "INSTALLED $SEMGREP_REPORT_COMMIT"
  else
    rm -f "$dest"
    record "semgrep-report" "FAILED fetch/verify $SEMGREP_REPORT_COMMIT"
  fi
}

install_codebase_memory
install_codebadger
ensure_deb_package "graphviz" "$GRAPHVIZ_DEBIAN_PACKAGE"
ensure_deb_package "java-runtime" "$JAVA_RUNTIME_DEBIAN_PACKAGE"
install_semgrep_report_viewer

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  if run_logged venv python3 -m venv "$ROOT/.venv"; then
    record "python-venv" "INSTALLED $ROOT/.venv"
  else
    record "python-venv" "FAILED see $LOG_DIR/install-venv.log"
  fi
else
  record "python-venv" "OK existing $ROOT/.venv"
fi

if [ -x "$ROOT/.venv/bin/python" ]; then
  if have_python_package pip "$PIP_VERSION" &&
    have_python_package setuptools "$SETUPTOOLS_VERSION" &&
    have_python_package wheel "$WHEEL_VERSION"; then
    record "pip-bootstrap" "OK existing pip==$PIP_VERSION setuptools==$SETUPTOOLS_VERSION wheel==$WHEEL_VERSION"
  elif run_logged pip-bootstrap "$ROOT/.venv/bin/python" -m pip install --upgrade \
    "pip==$PIP_VERSION" "setuptools==$SETUPTOOLS_VERSION" "wheel==$WHEEL_VERSION"; then
    record "pip-bootstrap" "INSTALLED pip==$PIP_VERSION setuptools==$SETUPTOOLS_VERSION wheel==$WHEEL_VERSION"
  else
    record "pip-bootstrap" "FAILED see $LOG_DIR/install-pip-bootstrap.log"
  fi

  PY_PACKAGES=(
    "semgrep:$SEMGREP_VERSION"
    "jedi:$JEDI_VERSION"
    "python-lsp-server:$PYTHON_LSP_SERVER_VERSION"
    "code2flow:$CODE2FLOW_VERSION"
    "pyan3:$PYAN3_VERSION"
    "lizard:$LIZARD_VERSION"
    "radon:$RADON_VERSION"
  )

  for spec in "${PY_PACKAGES[@]}"; do
    name="${spec%%:*}"
    version="${spec##*:}"
    if have_python_package "$name" "$version"; then
      record "$name" "OK existing $version"
      continue
    fi
    if run_logged "pip-$name" "$ROOT/.venv/bin/python" -m pip install "$name==$version"; then
      record "$name" "INSTALLED $version"
    else
      record "$name" "FAILED $version see $LOG_DIR/install-pip-$name.log"
    fi
  done
fi

have_uv_tool_package() {
  local name="$1"
  local want="$2"
  local py="$ROOT/uv-tools/serena-agent/bin/python"
  [ -x "$py" ] || return 1
  "$py" - "$name" "$want" <<'PY'
import importlib.metadata as md
import sys
name, want = sys.argv[1], sys.argv[2]
try:
    got = md.version(name)
except md.PackageNotFoundError:
    raise SystemExit(1)
raise SystemExit(0 if got == want else 1)
PY
}

ensure_serena_config() {
  local cfg="$ROOT/serena-home/serena_config.yml"
  [ -f "$cfg" ] || return 0
  "$ROOT/.venv/bin/python" - "$cfg" "$ROOT" <<'PY'
from pathlib import Path
import sys

cfg = Path(sys.argv[1])
root = Path(sys.argv[2])
text = cfg.read_text(encoding="utf-8")
old = "ls_specific_settings: {}\n"
new = f"""ls_specific_settings:
  python:
    ls_path: "{root}/uv-tools/serena-agent/bin/python"
  typescript:
    ls_path: "{root}/node_modules/.bin/typescript-language-server"

"""
if old in text:
    cfg.write_text(text.replace(old, new, 1), encoding="utf-8")
PY
}

if command -v uv >/dev/null 2>&1; then
  mkdir -p "$ROOT/uv-tools" "$ROOT/uv-bin" "$ROOT/uv-cache" "$ROOT/serena-home"
  if have_uv_tool_package serena-agent "$SERENA_AGENT_VERSION" &&
    have_uv_tool_package pyright "$PYRIGHT_VERSION" &&
    [ -x "$ROOT/uv-bin/serena" ]; then
    record "serena-agent" "OK existing $SERENA_AGENT_VERSION pyright==$PYRIGHT_VERSION"
  elif run_logged serena-agent env \
    UV_TOOL_DIR="$ROOT/uv-tools" \
    UV_TOOL_BIN_DIR="$ROOT/uv-bin" \
    UV_CACHE_DIR="$ROOT/uv-cache" \
    uv tool install -p 3.13 "serena-agent==$SERENA_AGENT_VERSION" --with "pyright==$PYRIGHT_VERSION"; then
    record "serena-agent" "INSTALLED $SERENA_AGENT_VERSION pyright==$PYRIGHT_VERSION"
  else
    record "serena-agent" "FAILED $SERENA_AGENT_VERSION see $LOG_DIR/install-serena-agent.log"
  fi

  if [ -x "$ROOT/uv-bin/serena" ]; then
    if [ ! -f "$ROOT/serena-home/serena_config.yml" ]; then
      if run_logged serena-init env \
        SERENA_HOME="$ROOT/serena-home" \
        PATH="$ROOT/uv-bin:$ROOT/node_modules/.bin:$PATH" \
        "$ROOT/uv-bin/serena" init; then
        record "serena-init" "OK $ROOT/serena-home/serena_config.yml"
      else
        record "serena-init" "FAILED see $LOG_DIR/install-serena-init.log"
      fi
    else
      record "serena-init" "OK existing $ROOT/serena-home/serena_config.yml"
    fi
    ensure_serena_config
  fi
else
  record "uv" "FAILED uv not found; Serena not installed"
fi

if command -v npm >/dev/null 2>&1; then
  if [ ! -f "$ROOT/package.json" ]; then
    cat > "$ROOT/package.json" <<'JSON'
{
  "private": true,
  "name": "refallinfr-code-understanding-toolchain",
  "description": "Persistent local code-understanding tools for container execution",
  "license": "UNLICENSED"
}
JSON
  fi

  NPM_PACKAGES=(
    "@ast-grep/cli:$AST_GREP_CLI_VERSION"
    "@sourcegraph/scip-python:$SCIP_PYTHON_NPM_VERSION"
    "@sourcegraph/scip-typescript:$SCIP_TYPESCRIPT_NPM_VERSION"
    "dependency-cruiser:$DEPENDENCY_CRUISER_VERSION"
    "madge:$MADGE_VERSION"
    "typescript:$TYPESCRIPT_VERSION"
    "typescript-language-server:$TYPESCRIPT_LANGUAGE_SERVER_VERSION"
    "codecharta-analysis:$CODECHARTA_ANALYSIS_VERSION"
  )

  for spec in "${NPM_PACKAGES[@]}"; do
    name="${spec%%:*}"
    version="${spec##*:}"
    if have_npm_package "$name" "$version"; then
      record "$name" "OK existing $version"
      continue
    fi
    if run_logged "npm-${name//\//_}" npm install --prefix "$ROOT" --save-exact "$name@$version"; then
      record "$name" "INSTALLED $version"
    else
      record "$name" "FAILED $version see $LOG_DIR/install-npm-${name//\//_}.log"
    fi
  done
else
  record "npm" "FAILED npm not found"
fi

record "joern" "CODEBADGER Docker stack; no host Joern binary required"

if command -v tree-sitter >/dev/null 2>&1; then
  record "tree-sitter" "EXTERNAL existing $(tree-sitter --version 2>/dev/null | head -1)"
else
  record "tree-sitter" "EXTERNAL not on PATH; not reinstalled per request"
fi

if [ -x "$ROOT/uv-bin/serena" ]; then
  record "serena" "TOOLCHAIN $("$ROOT/uv-bin/serena" --version 2>/dev/null | head -1)"
else
  record "serena" "TODO not installed"
fi

chmod +x "$ROOT/run.sh" "$ROOT/ctl.sh" "$ROOT/bin/"* 2>/dev/null || true

printf '\nSUMMARY written to %s\n' "$SUMMARY"
