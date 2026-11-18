#!/bin/zsh
# REFALL loop supervisor cron wrapper.
#
#   refall-supervisor.sh fast   -> liveness + recovery only (cheap, every minute)
#   refall-supervisor.sh full   -> + watchdog pass, wishlist, relevance, report
#
# Installed and removed automatically when a standing loop starts/stops. It
# never tears the stack down and never edits its own crontab entry.
set -u

mode="${1:-full}"
subject="${2:-${REFALL_SUPERVISOR_SUBJECT:-all}}"

export REFALL_REPO_ROOT="${REFALL_REPO_ROOT:-/opt/refall/REFALL-V10}"

# Config lives in a sidecar env file, NOT inline on the crontab line. macOS
# crontab truncates long entries; a truncated line loses its trailing marker,
# which leaves it both broken and unremovable by marker so uninstall silently
# succeeds while the cron keeps firing. Keep the crontab line short.
env_file="$REFALL_REPO_ROOT/logs/refall-supervisor-${subject}.env"
if [ -f "$env_file" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$env_file"
  set +a
fi

export REFALL_PUBLIC_BASE_URL="${REFALL_PUBLIC_BASE_URL:-http://127.0.0.1:7673}"
export REFALL_WORKBENCH_BASE="${REFALL_WORKBENCH_BASE:-$REFALL_PUBLIC_BASE_URL}"
export REFALL_OPENHANDS_BASE="${REFALL_OPENHANDS_BASE:-http://127.0.0.1:8000}"
export REFALL_SUPERVISOR_SUBJECT="$subject"
export REFALL_PYTHON="${REFALL_PYTHON:-/opt/homebrew/bin/python3}"
export PYTHONPATH="$REFALL_REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p "$REFALL_REPO_ROOT/logs"
cd "$REFALL_REPO_ROOT" || exit 1

"$REFALL_PYTHON" -m ref_all_executor.supervisor "$mode" \
  --subject "$REFALL_SUPERVISOR_SUBJECT" \
  --repo-root "$REFALL_REPO_ROOT" \
  --base-url "$REFALL_PUBLIC_BASE_URL" \
  --oh-base "$REFALL_OPENHANDS_BASE" \
  >> "$REFALL_REPO_ROOT/logs/refall-supervisor.log" 2>&1

exit $?
