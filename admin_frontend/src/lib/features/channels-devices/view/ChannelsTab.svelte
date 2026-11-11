<script lang="ts">
  import { Lock, Power, PowerOff, Settings2, RefreshCw } from '@lucide/svelte';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import PickSelect from '$kit/ui/pick-select.svelte';
  import Panel from '$kit/ui/panel.svelte';
  import ResourceView from '$kit/ui/resource-view.svelte';
  import TableShell from '$kit/ui/table-shell.svelte';
  import { TABLE_GRID_ROW } from '$kit/ui/table-grid';
  import type { Notify } from '$kit/ui/toast.svelte';
  import type { ChannelsController } from '../state/channels-controller.svelte';
  import ChannelDetail from './ChannelDetail.svelte';

  let { ctrl, notify }: { ctrl: ChannelsController; notify: Notify } = $props();

  // Which channel's generic detail view (§5.5) is open; null = the list.
  let selected = $state<string | null>(null);

  // "Install a channel" picker — the chosen catalog channel to install.
  let chosen = $state('');
  // Keep `chosen` valid: default to the first available and reset if it's been installed away.
  $effect(() => {
    const names = ctrl.available.map((c) => c.name);
    if (ctrl.available.length && !names.includes(chosen)) chosen = ctrl.available[0].name;
  });
  const chosenDescription = $derived(
    ctrl.available.find((c) => c.name === chosen)?.description ?? ''
  );

  async function handleInstall() {
    const name = chosen;
    if (!name) return;
    // On success, open the new channel's detail so the user can configure + Enable.
    if (await ctrl.install(name)) selected = name;
  }

  const CHANNEL_GRID = '180px 110px 1.4fr 1fr 210px';
  // ResourceView's shape: nothing to show yet reads as loading / failed; rows already held stay up while it reloads.
  const view = $derived({
    data: ctrl.rows.length || !(ctrl.loading || ctrl.error) ? ctrl.rows : null,
    error: ctrl.error ?? '',
    loading: ctrl.loading,
    reload: () => ctrl.load()
  });
</script>

{#if selected}
  {#key selected}
    <ChannelDetail
      name={selected}
      {notify}
      onBack={() => (selected = null)}
      onChanged={() => void ctrl.load()}
    />
  {/key}
{:else}
<div class="flex flex-col gap-4">
{#if ctrl.available.length > 0}
  <Panel class="grid gap-3">
    <div>
      <h3 class="text-lg font-semibold">Install a channel</h3>
      <span class="font-sans text-sm text-muted-foreground">
        Install a channel plugin, then configure and enable it.
      </span>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <PickSelect
        class="h-9 w-48 text-sm"
        value={chosen}
        onchange={(v) => (chosen = v)}
        options={ctrl.available.map((ch) => ({ value: ch.name, label: ch.label }))}
        label="Channel to install"
        disabled={!!ctrl.installing}
      />
      <Button size="sm" onclick={() => void handleInstall()} disabled={!!ctrl.installing || !chosen}>
        {ctrl.installing ? 'Installing…' : 'Install'}
      </Button>
    </div>
    {#if chosenDescription}
      <p class="text-xs text-muted-foreground">{chosenDescription}</p>
    {/if}
    {#if ctrl.installing}
      <p class="text-xs text-muted-foreground">
        Installing '{ctrl.installing}' (uv tool install) — this can take a few minutes on first
        run while native dependencies download.
      </p>
    {/if}
  </Panel>
{/if}

<Panel title="Channels" description={`${ctrl.rows.length} configured / ${ctrl.enabledCount} enabled`} class="grid gap-4">
  {#snippet actions()}
    <Button variant="outline" disabled={ctrl.loading} onclick={() => void ctrl.load()}>
      <RefreshCw size={15} /> Refresh
    </Button>
  {/snippet}
  <ResourceView
    resource={view}
    loadingLabel="Loading channels…"
    errorTitle="Could not load channels"
    empty={(d) => d.length === 0}
    emptyMessage="No channels configured for this workspace."
    quiet
  >
    {#snippet children()}
      <TableShell layout="grid" minWidth={920} gridColumns={CHANNEL_GRID}>
        {#snippet headRow()}
          <span>Name</span>
          <span>Status</span>
          <span>Command</span>
          <span>Config keys</span>
          <span>Actions</span>
        {/snippet}
        {#snippet body()}
          {#each ctrl.rows as row (row.name)}
            <div class={TABLE_GRID_ROW} style:grid-template-columns={CHANNEL_GRID}>
              <span class="truncate font-sans text-sm font-semibold" title={row.name}>{row.name}</span>
              <span>
                <Badge variant={row.enabled ? 'success' : 'outline'}>
                  {row.enabled ? 'Enabled' : 'Disabled'}
                </Badge>
              </span>
              <span class="truncate font-mono text-xs text-muted-foreground" title={row.command}>
                {row.command || '-'}
              </span>
              <span class="flex flex-wrap gap-1.5">
                {#if row.config_keys.length}
                  {#each row.config_keys as key}
                    <Badge variant="secondary">{key}</Badge>
                  {/each}
                {:else}
                  <small class="text-muted-foreground">-</small>
                {/if}
              </span>
              <span class="flex justify-end gap-1.5">
                <Button
                  size="sm"
                  variant="outline"
                  onclick={() => (selected = row.name)}
                  title="Manage channel"
                >
                  <Settings2 size={13} /> Manage
                </Button>
                {#if ctrl.isMandatory(row)}
                  <Button
                    size="icon"
                    variant="ghost"
                    class="opacity-45"
                    disabled
                    aria-label="Mandatory channel cannot be disabled"
                    title="Mandatory channel cannot be disabled"
                  >
                    <Lock size={15} />
                  </Button>
                {:else}
                  {@const ToggleIcon = row.enabled ? PowerOff : Power}
                  {@const toggleTitle = row.enabled ? 'Disable channel' : 'Enable channel'}
                  <Button
                    size="icon"
                    variant="ghost"
                    disabled={ctrl.isBusy(row)}
                    onclick={() => void ctrl.toggle(row)}
                    title={toggleTitle}
                    aria-label={toggleTitle}
                  >
                    <ToggleIcon size={15} />
                  </Button>
                {/if}
              </span>
            </div>
          {/each}
        {/snippet}
      </TableShell>
    {/snippet}
  </ResourceView>
</Panel>
</div>
{/if}
