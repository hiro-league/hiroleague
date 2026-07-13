<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import SectionCard from '$lib/components/page/SectionCard.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import { ADMIN_SECTION_TITLE } from '$lib/styling/admin-tokens';
  import type { ChannelDetailController } from '../../state/channel-detail-controller.svelte';
  import ChannelPairingPane from './ChannelPairingPane.svelte';

  let { ctrl }: { ctrl: ChannelDetailController } = $props();

  // Friendlier labels for the common declared actions; fall back to the raw name.
  const ACTION_LABELS: Record<string, string> = { logout: 'Log out', reconnect: 'Reconnect' };
  const label = (action: string) => ACTION_LABELS[action] ?? action;
</script>

<SectionCard class="grid gap-3">
  <h2 class={ADMIN_SECTION_TITLE}>Connection</h2>

  <div class="flex items-center gap-2 text-sm">
    <span
      class="inline-flex h-2.5 w-2.5 rounded-full {ctrl.connected
        ? 'bg-emerald-500'
        : ctrl.needsRepair
          ? 'bg-red-500'
          : 'bg-amber-500'}"
    ></span>
    <span class="font-medium capitalize">{ctrl.status?.state ?? 'unknown'}</span>
    {#if ctrl.status?.account}
      <span class="text-muted-foreground">· {ctrl.status.account}</span>
    {/if}
  </div>

  {#if ctrl.needsRepair && ctrl.statusMessage}
    <InlineDestructiveAlert message={ctrl.statusMessage} />
  {/if}

  <ChannelPairingPane kind={ctrl.pairingKind} connected={ctrl.connected} qrSvg={ctrl.qrSvg} />

  <div class="mt-2 flex flex-wrap gap-2">
    {#if ctrl.enabled}
      {#each ctrl.actions as action (action)}
        <Button variant="secondary" size="sm" onclick={() => ctrl.runAction(action)} disabled={ctrl.busy}>
          {label(action)}
        </Button>
      {/each}
      <Button
        variant="destructive-outline"
        size="sm"
        onclick={() => ctrl.disable()}
        disabled={ctrl.busy}
      >
        Disable
      </Button>
    {:else}
      <Button
        size="sm"
        variant="secondary"
        onclick={() => ctrl.install()}
        disabled={ctrl.busy || ctrl.installing}
      >
        {ctrl.installing ? 'Installing…' : 'Install'}
      </Button>
      <Button size="sm" onclick={() => ctrl.enable()} disabled={ctrl.busy || ctrl.installing}>
        Enable
      </Button>
    {/if}
  </div>

  {#if ctrl.installing}
    <p class="text-xs text-muted-foreground">
      Installing the plugin (uv tool install) — this can take a few minutes on first run while
      native dependencies download.
    </p>
  {/if}
</SectionCard>
