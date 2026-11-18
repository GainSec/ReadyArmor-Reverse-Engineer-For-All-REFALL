#!/bin/zsh
set -u

export REFALL_REPO_ROOT="${REFALL_REPO_ROOT:-/opt/refall/REFALL-V10}"
export REFALL_PUBLIC_BASE_URL="${REFALL_PUBLIC_BASE_URL:-http://127.0.0.1:7673}"
export REFALL_WORKBENCH_BASE="${REFALL_WORKBENCH_BASE:-$REFALL_PUBLIC_BASE_URL}"
export REFALL_OPENHANDS_BASE="${REFALL_OPENHANDS_BASE:-http://127.0.0.1:8000}"
export REFALL_WATCHDOG_SUBJECT="${REFALL_WATCHDOG_SUBJECT:-all}"
export REFALL_PYTHON="${REFALL_PYTHON:-/opt/homebrew/bin/python3}"
export PYTHONPATH="$REFALL_REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p "$REFALL_REPO_ROOT/logs"
cd "$REFALL_REPO_ROOT" || exit 1

tmp_out="$(mktemp -t refall-watchdog.XXXXXX)"
cleanup_tmp() {
  rm -f "$tmp_out"
}
trap cleanup_tmp EXIT

set +e
"$REFALL_PYTHON" -m ref_all_executor.watchdog \
  --subject "$REFALL_WATCHDOG_SUBJECT" \
  --repo-root "$REFALL_REPO_ROOT" \
  --base-url "$REFALL_PUBLIC_BASE_URL" \
  --oh-base "$REFALL_OPENHANDS_BASE" \
  > "$tmp_out" 2>&1
watchdog_rc=$?
set -e

cat "$tmp_out" >> "$REFALL_REPO_ROOT/logs/refall-watchdog-cron.log"

crash_reason=""
if grep -q '"reason": "openhands_agent_server_unreachable"' "$tmp_out"; then
  crash_reason="openhands_agent_server_unreachable"
elif grep -q '"reason": "dead_or_stuck_loop_state"' "$tmp_out"; then
  crash_reason="dead_or_stuck_loop_state"
elif grep -q '"reason": "refall_api_unreachable"' "$tmp_out"; then
  crash_reason="refall_api_unreachable"
fi

# A crash reason means a REFALL service is unreachable or loop state is dead. The
# correct response is to bring the service BACK, never to tear the stack down.
#
# `REFALL_WATCHDOG_CRASH_POLICY=shutdown` previously ran `ref_all_executor down`
# across the canvas, the standing loop, and ports 7673/8900/20871/20872, then
# `launchctl bootout` the REFALL AB job and tried to delete its own crontab line.
# On macOS that self-removal fails with "Operation not permitted", so a single
# transient 502 became a permanent stack teardown repeating every interval. It is
# refused here, loudly, so an old crontab entry carrying it cannot resurrect it.
if [[ "${REFALL_WATCHDOG_CRASH_POLICY:-}" == "shutdown" ]]; then
  printf '%s subject=%s status=crash_policy_refused note=%s\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$REFALL_WATCHDOG_SUBJECT" \
    'shutdown policy removed; use REFALL_WATCHDOG_CRASH_POLICY=recover' \
    >> "$REFALL_REPO_ROOT/logs/refall-watchdog-cron.log"
fi

if [[ "${REFALL_WATCHDOG_CRASH_POLICY:-}" == "recover" && -n "$crash_reason" ]]; then
  {
    printf '\n%s subject=%s status=crash_policy_recover reason=%s\n' \
      "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$REFALL_WATCHDOG_SUBJECT" "$crash_reason"

    # Agent Canvas. Docker's own `--restart unless-stopped` handles most exits;
    # this covers a hard OOM kill that left the container down.
    if [[ "$crash_reason" == "openhands_agent_server_unreachable" ]]; then
      canvas_state="$(docker inspect refall-agent-canvas --format '{{.State.Status}}' 2>/dev/null || echo absent)"
      printf 'canvas_state=%s\n' "$canvas_state"
      case "$canvas_state" in
        running) docker restart refall-agent-canvas >/dev/null 2>&1 && printf 'canvas=bounced\n' ;;
        absent)  printf 'canvas=absent note=container missing, operator must recreate\n' ;;
        *)       docker start refall-agent-canvas >/dev/null 2>&1 && printf 'canvas=restarted\n' ;;
      esac
    fi

    # REFALL AB. KeepAlive restarts the process on its own, so this only matters
    # when the launchd job was booted out of the domain entirely.
    if [[ "$crash_reason" == "refall_api_unreachable" ]]; then
      ab_plist="$HOME/Library/LaunchAgents/com.gainpalfam.refall-v10.arcticbase.plist"
      if launchctl list 2>/dev/null | grep -q com.gainpalfam.refall-v10.arcticbase; then
        launchctl kickstart -k "gui/$(id -u)/com.gainpalfam.refall-v10.arcticbase" 2>&1 \
          && printf 'refall_ab=kickstarted\n'
      elif [[ -f "$ab_plist" ]]; then
        launchctl load -w "$ab_plist" 2>&1 && printf 'refall_ab=launchd_reloaded\n'
      else
        printf 'refall_ab=plist_missing note=operator must reinstall launchd job\n'
      fi
    fi

    # Stale loop state is a REFALL-level condition, not an infra one. Record it
    # and stop: restarting a loop can re-dispatch work that is still in flight,
    # so a bounded `loop update` stays the operator's call.
    if [[ "$crash_reason" == "dead_or_stuck_loop_state" ]]; then
      printf 'loop_state=stale note=no automatic loop restart; run `loop update %s` after review\n' \
        "$REFALL_WATCHDOG_SUBJECT"
    fi

    printf '%s subject=%s status=crash_policy_recover_complete\n' \
      "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$REFALL_WATCHDOG_SUBJECT"
  } >> "$REFALL_REPO_ROOT/logs/refall-watchdog-cron.log" 2>&1
fi

exit "$watchdog_rc"
