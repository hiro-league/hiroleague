<script lang="ts">
  // The one list: every extension, channels and apps alike. A row's name opens About; Settings shows only where
  // the core keeps its settings or it links an account.
  import { ArrowUpCircle, Link2Off, Lock, Settings2, ShieldCheck } from '@lucide/svelte';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import { Switch } from '$kit/components/ui/switch/index.js';
  import Panel from '$kit/ui/panel.svelte';
  import ResourceView from '$kit/ui/resource-view.svelte';
  import StatusDot from '$kit/ui/status-dot.svelte';
  import TableShell from '$kit/ui/table-shell.svelte';
  import { TABLE_GRID_ROW } from '$kit/ui/table-grid';
  import { dateTime } from '$kit/format/time';
  import { hasSettings, statusTime } from '../shared/extension-rows';
  import type { ExtensionsController } from '../state/extensions-controller.svelte';
  import { stateLine } from '../mockup/installed';
  import type { InstallsMock } from '../mockup/installs-mock.svelte';

  let { ctrl, mock }: { ctrl: ExtensionsController; mock: InstallsMock } = $props();

  // mockup (Installing apps, task 6): a To set column, and an installed app's state, start and stop, upgrade
  const GRID = '1.6fr 90px 80px 1.3fr 100px 230px';
  // ResourceView's shape: nothing to show yet reads as loading / failed; rows already held stay up while it reloads.
  const view = $derived({
    data: ctrl.rows.length || !(ctrl.loading || ctrl.error) ? ctrl.rows : null,
    error: ctrl.error ?? '',
    loading: ctrl.loading,
    reload: () => ctrl.load()
  });
</script>

<Panel title={`${ctrl.rows.length} shown · ${ctrl.connectedCount} connected`} class="grid gap-4">
  <ResourceView
    resource={view}
    loadingLabel="Loading extensions…"
    errorTitle="Could not load extensions"
    empty={(d) => d.length === 0}
    emptyMessage={ctrl.kinds.length
      ? 'No extension of this kind.'
      : 'Nothing is plugged in yet. Add an app with a pairing code, or install a channel.'}
    quiet
  >
    {#snippet children()}
      <TableShell layout="grid" minWidth={820} gridColumns={GRID} stickyHead>
        {#snippet headRow()}
          <span>Name</span>
          <span>Kind</span>
          <span>Version</span>
          <span>Status</span>
          <span>To set</span>
          <span class="text-right">Actions</span>
        {/snippet}
        {#snippet body()}
          {#each ctrl.rows as row (row.extension_id)}
            {@const installed = mock.installOf(row)}
            {@const status = installed ? stateLine(installed) : ctrl.statusOf(row)}
            {@const time = statusTime(row)}
            {@const left = mock.setupLeft(row)}
            <div class={TABLE_GRID_ROW} style:grid-template-columns={GRID}>
              <button type="button" class="group grid min-w-0 text-left" onclick={() => ctrl.openAbout(row)} title="About {row.label}">
                <span class="truncate font-sans text-sm font-semibold group-hover:underline">{row.label}</span>
                <span class="truncate text-xs text-muted-foreground">{row.description}</span>
              </button>
              <span>
                <Badge variant={row.kind === 'channel' ? 'secondary' : 'outline'}>
                  {row.kind === 'channel' ? 'Channel' : 'App'}
                </Badge>
              </span>
              <span class="truncate font-mono text-xs text-muted-foreground">{installed?.version || row.version || '—'}</span>
              <span class="grid min-w-0 gap-0.5">
                <span class="flex items-center gap-2 text-sm">
                  <StatusDot tone={status.tone} />
                  {status.text}
                </span>
                {#if installed}
                  <span class="truncate text-xs text-muted-foreground">Installed by the core, port {installed.port}</span>
                {:else if time}
                  <span class="truncate text-xs text-muted-foreground" title={row.remote ?? ''}>
                    {time.words} {dateTime(time.at)}
                  </span>
                {/if}
              </span>
              <span>
                {#if left.length}
                  <button type="button" onclick={() => ctrl.openAbout(row)} title={left.map((l) => l.title).join(', ')}>
                    <Badge variant="outline" class="border-warning/50 text-warning">{left.length} to set</Badge>
                  </button>
                {:else if row.kind === 'app' && row.connected}
                  <span class="text-xs text-muted-foreground">Nothing</span>
                {:else}
                  <span class="text-xs text-muted-foreground">—</span>
                {/if}
              </span>
              <span class="flex items-center justify-end gap-1.5">
                {#if installed}
                  <Switch
                    checked={installed.state === 'running'}
                    disabled={installed.state === 'upgrading'}
                    onCheckedChange={() => mock.toggle(row)}
                    tone="success"
                    aria-label={installed.state === 'running' ? `Stop ${row.label}` : `Start ${row.label}`}
                    title={installed.state === 'running' ? 'Running: stop it' : 'Stopped: start it'}
                    class="mx-2"
                  />
                  {#if installed.offered}
                    <Button size="sm" variant="outline" onclick={() => mock.openUpgrade(row)} title="Upgrade {row.label} to {installed.offered}">
                      <ArrowUpCircle size={13} /> {installed.offered}
                    </Button>
                  {/if}
                {/if}
                {#if row.started_by_core}
                  {#if row.mandatory}
                    <span class="inline-flex size-8 items-center justify-center text-muted-foreground" title="Phones' chat needs it: it can't be switched off or removed">
                      <Lock size={14} />
                    </span>
                  {:else}
                    <Switch
                      checked={row.enabled === true}
                      disabled={ctrl.isSwitching(row)}
                      onCheckedChange={() => void ctrl.toggle(row)}
                      tone="success"
                      aria-label={row.enabled ? `Switch ${row.label} off` : `Switch ${row.label} on`}
                      title={row.enabled ? 'On: the core runs it' : 'Off: the core does not start it'}
                      class="mx-2"
                    />
                  {/if}
                {/if}
                <!-- Permissions phase 8: an app that waits for the owner opens on its Permissions -->
                {#if row.kind === 'app' && row.waits}
                  <Button size="sm" onclick={() => ctrl.openAbout(row)} title="See what {row.label} asks for, and approve it">
                    <ShieldCheck size={13} /> Approve
                  </Button>
                {/if}
                {#if hasSettings(row)}
                  <Button size="sm" variant="outline" onclick={() => ctrl.openSettings(row)} title="{row.label}'s settings">
                    <Settings2 size={13} /> Settings
                  </Button>
                {/if}
                <Button
                  size="icon"
                  variant="ghost"
                  disabled={row.mandatory || ctrl.busy}
                  onclick={() => (installed ? mock.openRemove(row) : void ctrl.remove(row))}
                  title={row.mandatory ? "Phones' chat needs it: it can't be removed" : `Remove ${row.label}`}
                  aria-label="Remove {row.label}"
                >
                  <Link2Off size={15} />
                </Button>
              </span>
            </div>
          {/each}
        {/snippet}
      </TableShell>
    {/snippet}
  </ResourceView>
</Panel>
