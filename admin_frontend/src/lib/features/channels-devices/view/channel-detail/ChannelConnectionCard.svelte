<script lang="ts">
  import { Button } from '$kit/components/ui/button/index.js';
  import Panel from '$kit/ui/panel.svelte';
  import Notice from '$kit/ui/notice.svelte';
  import StatusDot from '$kit/ui/status-dot.svelte';
  import type { ChannelDetailController } from '../../state/channel-detail-controller.svelte';
  import ChannelPairingPane from './ChannelPairingPane.svelte';

  let { ctrl, onRequestUninstall }: {
    ctrl: ChannelDetailController;
    onRequestUninstall: () => void;
  } = $props();

  // Friendlier labels for the common declared actions; fall back to the raw name.
  const ACTION_LABELS: Record<string, string> = { logout: 'Log out', reconnect: 'Reconnect' };
  const label = (action: string) => ACTION_LABELS[action] ?? action;
</script>

<Panel title="Connection" contentClass="grid gap-3">
  <div class="flex items-center gap-2 text-sm">
    <StatusDot size="md" tone={ctrl.connected ? 'ok' : ctrl.needsRepair ? 'error' : 'warn'} />
    <span class="font-medium capitalize">{ctrl.status?.state ?? 'unknown'}</span>
    {#if ctrl.status?.account}
      <span class="text-muted-foreground">· {ctrl.status.account}</span>
    {/if}
  </div>

  {#if ctrl.needsRepair && ctrl.statusMessage}
    <Notice message={ctrl.statusMessage} />
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
        variant="destructive"
        size="sm"
        onclick={() => ctrl.disable()}
        disabled={ctrl.busy}
      >
        Disable
      </Button>
    {:else}
      <Button size="sm" onclick={() => ctrl.enable()} disabled={ctrl.busy}>
        Enable
      </Button>
    {/if}
    <Button
      variant="destructive"
      size="sm"
      class="ml-auto"
      onclick={onRequestUninstall}
      disabled={ctrl.busy || ctrl.uninstalling}
    >
      {ctrl.uninstalling ? 'Uninstalling…' : 'Uninstall'}
    </Button>
  </div>
</Panel>
