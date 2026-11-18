<script lang="ts">
  import { onMount } from "svelte";
  import { api, type RefallOpsInfra, type RefallOpsStatus } from "../api";

  let status: RefallOpsStatus | null = null;
  let infra: RefallOpsInfra | null = null;
  let events: Record<string, unknown>[] = [];
  let disabled = false;
  let error: string | null = null;

  onMount(async () => {
    try {
      status = await api.refallOpsStatus();
      infra = await api.refallOpsInfra();
      events = (await api.refallOpsFeedHistory()).events;
    } catch (e) {
      const msg = String(e);
      disabled = msg.includes("404");
      if (!disabled) error = msg;
    }
  });

  $: commandState = status?.commands_enabled ? "ENABLED" : "LOCKED";
  $: infraLine = infra
    ? infra.checks.map((check) => `${check.id}:${check.status}`).join(" ")
    : "pending";
</script>

<section class="refall-console" aria-label="REFALL ops terminal">
  <div class="term-head">
    <span>REFALL_OPS :: ARCTICBASE</span>
    <span class="state" class:off={disabled || error}>{disabled ? "DISABLED" : error ? "ERROR" : "ONLINE"}</span>
  </div>
  <pre>{#if disabled}
> ops_enabled......... false
> command_surface..... unavailable
> note................ set REFALL_ENABLE_OPS=true to expose intranet ops
{:else if error}
> ops_status.......... error
> detail.............. {error}
{:else if status}
> deployment_mode..... {status.deployment_mode}
> public_base......... {status.public_base_url}
> openhands_base...... {status.openhands_base}
> head_provider....... {status.head_provider}
> commands............ {commandState}
> infra............... {infraLine}
> feed_events......... {events.length}
{:else}
> ops_status.......... loading
> waiting_for......... /api/refall/ops/status
{/if}</pre>
</section>

<style>
  .refall-console {
    margin: 0 0 24px;
    border: 2.5px solid #000;
    box-shadow: var(--ab-shadow-hard);
    border-radius: var(--ab-radius);
    background: #02080c;
    color: var(--ab-green);
    overflow: hidden;
  }
  .term-head {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    padding: 8px 12px;
    border-bottom: 1px dashed rgba(109, 213, 140, 0.45);
    font-family: var(--ab-font-crt);
    letter-spacing: 0.06em;
  }
  .state { color: var(--ab-green); }
  .state.off { color: var(--ab-red-bright); }
  pre {
    margin: 0;
    padding: 12px;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: var(--ab-font-crt);
    font-size: 15px;
    line-height: 1.35;
    text-shadow: 0 0 6px rgba(109, 213, 140, 0.45);
    background-image:
      repeating-linear-gradient(0deg, rgba(109, 213, 140, 0.06) 0 1px, transparent 1px 3px),
      radial-gradient(ellipse at 50% 0%, rgba(109, 213, 140, 0.12), transparent 70%);
  }
</style>
