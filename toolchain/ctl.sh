#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY="$ROOT/config/services.json"
RUN_DIR="$ROOT/run"
LOG_DIR="$ROOT/logs"
PATH="$ROOT/bin:$ROOT/.venv/bin:$ROOT/node_modules/.bin:$PATH"
export PATH
export TOOLCHAIN_ROOT="$ROOT"

usage() {
  cat <<'EOF'
usage:
  ctl.sh up [service...]
  ctl.sh down [service...]
  ctl.sh restart [service...]
  ctl.sh status [service...]
  ctl.sh --help

Controls only registered long-running toolchain services. Invoke-and-exit tools
such as semgrep, ast-grep, code2flow, pyan3, lizard, radon, SCIP indexers,
madge, and dependency-cruiser are not services and are intentionally excluded.

With no service arguments, status/down act on all registered services. up/restart
act on services where autostart is true or omitted. Heavy opt-in services such
as codebadger-mcp must be named explicitly. Service definitions live in
config/services.json. Extension slots for future daemons are documented there
but ignored until copied into services[] with real commands and health checks.
EOF
}

die() {
  echo "ctl.sh: $*" >&2
  exit 1
}

require_registry() {
  command -v jq >/dev/null 2>&1 || die "jq is required to read $REGISTRY"
  [ -f "$REGISTRY" ] || die "missing service registry: $REGISTRY"
  jq -e '.services | type == "array"' "$REGISTRY" >/dev/null || die "invalid registry: .services must be an array"
}

service_names() {
  jq -r '.services[].name' "$REGISTRY"
}

autostart_service_names() {
  jq -r '.services[] | select(.autostart // true) | .name' "$REGISTRY"
}

service_exists() {
  local name="$1"
  jq -e --arg name "$name" '.services[] | select(.name == $name)' "$REGISTRY" >/dev/null
}

selected_services() {
  local default_mode="${1:-all}"
  shift || true
  if [ "$#" -eq 0 ]; then
    if [ "$default_mode" = "autostart" ]; then
      autostart_service_names
    else
      service_names
    fi
    return
  fi

  local name
  for name in "$@"; do
    service_exists "$name" || die "unknown service: $name"
    printf '%s\n' "$name"
  done
}

service_json() {
  local name="$1"
  jq -c --arg name "$name" '.services[] | select(.name == $name)' "$REGISTRY"
}

service_field() {
  local name="$1"
  local field="$2"
  jq -r --arg name "$name" --arg field "$field" '.services[] | select(.name == $name) | .[$field] // empty' "$REGISTRY"
}

pid_file() {
  printf '%s/%s.pid\n' "$RUN_DIR" "$1"
}

service_log_file() {
  local name="$1"
  local log
  log="$(service_field "$name" log_file)"
  [ -n "$log" ] || log="logs/$name.log"
  case "$log" in
    /*) printf '%s\n' "$log" ;;
    *) printf '%s/%s\n' "$ROOT" "$log" ;;
  esac
}

service_port() {
  local name="$1"
  jq -r --arg name "$name" '.services[] | select(.name == $name) | .port // "-"' "$REGISTRY"
}

read_pid() {
  local file="$1"
  [ -f "$file" ] || return 1
  read -r pid < "$file" || return 1
  case "$pid" in
    ''|*[!0-9]*) return 1 ;;
    *) printf '%s\n' "$pid" ;;
  esac
}

pid_alive() {
  local pid="$1"
  kill -0 "$pid" >/dev/null 2>&1
}

service_pgid() {
  local pid="$1"
  ps -p "$pid" -o pgid= 2>/dev/null | awk '{print $1}'
}

health_ok() {
  local name="$1"
  local type host port
  type="$(jq -r --arg name "$name" '.services[] | select(.name == $name) | .health_check.type // "pid"' "$REGISTRY")"

  case "$type" in
    pid)
      local pid
      pid="$(read_pid "$(pid_file "$name")" 2>/dev/null)" || return 1
      pid_alive "$pid"
      ;;
    tcp)
      host="$(jq -r --arg name "$name" '.services[] | select(.name == $name) | .health_check.host // "127.0.0.1"' "$REGISTRY")"
      port="$(jq -r --arg name "$name" '.services[] | select(.name == $name) | .health_check.port // empty' "$REGISTRY")"
      [ -n "$port" ] || return 1
      if command -v timeout >/dev/null 2>&1; then
        timeout 1 bash -c "</dev/tcp/$host/$port" >/dev/null 2>&1
      else
        bash -c "</dev/tcp/$host/$port" >/dev/null 2>&1
      fi
      ;;
    command)
      local cmd
      cmd="$(jq -r --arg name "$name" '.services[] | select(.name == $name) | .health_check.cmd // empty' "$REGISTRY")"
      [ -n "$cmd" ] || return 1
      bash -lc "$cmd" >/dev/null 2>&1
      ;;
    *)
      return 1
      ;;
  esac
}

service_state() {
  local name="$1"
  local file pid
  file="$(pid_file "$name")"
  pid="$(read_pid "$file" 2>/dev/null)" || {
    [ -f "$file" ] && rm -f "$file"
    echo "down"
    return
  }

  if ! pid_alive "$pid"; then
    rm -f "$file"
    echo "down"
    return
  fi

  if health_ok "$name"; then
    echo "running"
  else
    echo "unhealthy"
  fi
}

wait_for_health() {
  local name="$1"
  local timeout_sec start now
  timeout_sec="$(jq -r --arg name "$name" '.services[] | select(.name == $name) | .health_check.timeout_sec // 10' "$REGISTRY")"
  case "$timeout_sec" in
    ''|*[!0-9]*) timeout_sec=10 ;;
  esac
  start="$(date +%s)"
  while true; do
    health_ok "$name" && return 0
    now="$(date +%s)"
    [ $((now - start)) -ge "$timeout_sec" ] && return 1
    sleep 0.2
  done
}

start_service() {
  local name="$1"
  local state file pid cmd log
  mkdir -p "$RUN_DIR" "$LOG_DIR"

  state="$(service_state "$name")"
  if [ "$state" = "running" ]; then
    pid="$(read_pid "$(pid_file "$name")")"
    printf '%-24s already running pid=%s\n' "$name" "$pid"
    return 0
  fi
  if [ "$state" = "unhealthy" ]; then
    pid="$(read_pid "$(pid_file "$name")")"
    printf '%-24s unhealthy pid=%s; use restart to replace it\n' "$name" "$pid" >&2
    return 1
  fi

  cmd="$(service_field "$name" start_cmd)"
  [ -n "$cmd" ] || die "service $name has no start_cmd"
  log="$(service_log_file "$name")"
  mkdir -p "$(dirname "$log")"
  : >> "$log"

  file="$(pid_file "$name")"
  if command -v setsid >/dev/null 2>&1; then
    setsid bash -lc "$cmd" </dev/null >>"$log" 2>&1 &
    pid="$!"
    printf '%s\n' "$pid" > "$file"
  elif command -v tmux >/dev/null 2>&1; then
    local session quoted_cmd quoted_file quoted_log quoted_root
    session="refall-toolchain-$name"
    quoted_cmd="$(printf '%q' "$cmd")"
    quoted_file="$(printf '%q' "$file")"
    quoted_log="$(printf '%q' "$log")"
    quoted_root="$(printf '%q' "$ROOT")"
    tmux has-session -t "$session" 2>/dev/null && tmux kill-session -t "$session" >/dev/null 2>&1 || true
    tmux new-session -d -s "$session" "TOOLCHAIN_ROOT=$quoted_root bash -lc 'export TOOLCHAIN_ROOT; printf \"%s\\n\" \"\$\$\" > $quoted_file; exec bash -lc $quoted_cmd' >> $quoted_log 2>&1"
    sleep 0.2
    pid="$(read_pid "$file" 2>/dev/null)" || pid="-"
  else
    nohup bash -lc "$cmd" </dev/null >>"$log" 2>&1 &
    pid="$!"
    printf '%s\n' "$pid" > "$file"
  fi

  if wait_for_health "$name"; then
    printf '%-24s started pid=%s log=%s\n' "$name" "$pid" "$log"
    return 0
  fi

  printf '%-24s failed health check pid=%s log=%s\n' "$name" "$pid" "$log" >&2
  return 1
}

stop_service() {
  local name="$1"
  local file pid pgid target waited
  file="$(pid_file "$name")"
  pid="$(read_pid "$file" 2>/dev/null)" || {
    rm -f "$file"
    printf '%-24s already down\n' "$name"
    return 0
  }

  if ! pid_alive "$pid"; then
    rm -f "$file"
    printf '%-24s already down (removed stale pid=%s)\n' "$name" "$pid"
    return 0
  fi

  pgid="$(service_pgid "$pid")"
  if [ -n "$pgid" ] && [ "$pgid" = "$pid" ]; then
    target="-$pgid"
  else
    target="$pid"
  fi

  kill -TERM "$target" >/dev/null 2>&1 || true
  waited=0
  while pid_alive "$pid" && [ "$waited" -lt 50 ]; do
    sleep 0.1
    waited=$((waited + 1))
  done

  if pid_alive "$pid"; then
    kill -KILL "$target" >/dev/null 2>&1 || true
    waited=0
    while pid_alive "$pid" && [ "$waited" -lt 20 ]; do
      sleep 0.1
      waited=$((waited + 1))
    done
  fi

  if pid_alive "$pid"; then
    printf '%-24s failed to stop pid=%s\n' "$name" "$pid" >&2
    return 1
  fi

  rm -f "$file"
  printf '%-24s stopped\n' "$name"
}

format_uptime() {
  local seconds="$1"
  local days hours mins secs
  case "$seconds" in
    ''|*[!0-9]*) echo "-" ; return ;;
  esac
  days=$((seconds / 86400))
  hours=$(((seconds % 86400) / 3600))
  mins=$(((seconds % 3600) / 60))
  secs=$((seconds % 60))
  if [ "$days" -gt 0 ]; then
    printf '%dd%02dh%02dm\n' "$days" "$hours" "$mins"
  elif [ "$hours" -gt 0 ]; then
    printf '%dh%02dm%02ds\n' "$hours" "$mins" "$secs"
  elif [ "$mins" -gt 0 ]; then
    printf '%dm%02ds\n' "$mins" "$secs"
  else
    printf '%ds\n' "$secs"
  fi
}

service_usage() {
  local pid="$1"
  local pgid etimes
  pgid="$(service_pgid "$pid")"
  [ -n "$pgid" ] || {
    printf -- '- - -\n'
    return
  }
  etimes="$(ps -p "$pid" -o etimes= 2>/dev/null | awk 'NR == 1 && $1 ~ /^[0-9]+$/ { print $1 }')"
  [ -n "$etimes" ] || etimes="-"
  ps -eo pgid=,pcpu=,rss= 2>/dev/null | awk -v pgid="$pgid" -v etimes="$etimes" '
    $1 == pgid { cpu += $2; rss += $3 }
    END { printf "%.1f %.1f %s\n", cpu, rss / 1024, etimes }
  '
}

status_services() {
  local name state file pid port log cpu ram etimes uptime usage
  printf '%-24s %-10s %-8s %-7s %-10s %-6s %-8s %s\n' "SERVICE" "STATE" "PID" "PORT" "UPTIME" "CPU%" "RAM_MB" "LOG"
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    state="$(service_state "$name")"
    file="$(pid_file "$name")"
    port="$(service_port "$name")"
    log="$(service_log_file "$name")"
    if [ "$state" = "running" ] || [ "$state" = "unhealthy" ]; then
      pid="$(read_pid "$file" 2>/dev/null || true)"
      usage="$(service_usage "$pid")"
      cpu="$(printf '%s\n' "$usage" | awk '{print $1}')"
      ram="$(printf '%s\n' "$usage" | awk '{print $2}')"
      etimes="$(printf '%s\n' "$usage" | awk '{print $3}')"
      uptime="$(format_uptime "$etimes")"
      printf '%-24s %-10s %-8s %-7s %-10s %-6s %-8s %s\n' "$name" "$state" "$pid" "$port" "$uptime" "$cpu" "$ram" "$log"
    else
      printf '%-24s %-10s %-8s %-7s %-10s %-6s %-8s %s\n' "$name" "down" "-" "$port" "-" "-" "-" "$log"
    fi
  done
}

main() {
  local cmd="${1:-}"
  case "$cmd" in
    --help|-h|help|'')
      usage
      exit 0
      ;;
  esac
  shift
  require_registry

  case "$cmd" in
    up)
      selected_services autostart "$@" | while IFS= read -r name; do start_service "$name"; done
      ;;
    down)
      selected_services all "$@" | while IFS= read -r name; do stop_service "$name"; done
      ;;
    restart)
      selected_services autostart "$@" | while IFS= read -r name; do stop_service "$name" && start_service "$name"; done
      ;;
    status)
      selected_services all "$@" | status_services
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
}

main "$@"
