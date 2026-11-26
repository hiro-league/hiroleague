<script lang="ts">
  // About one extension, read only, drawn from its description. One shape for a channel and an app; what only one
  // kind has (a linked account, a site, offers, AI uses) shows when it has it. Its settings are a panel of their own.
  // Permissions phase 8: an app's sheet has two tabs, Info and Permissions; an app that waits for the owner opens on
  // Permissions, with Approve and Decline in the footer.
  import { ExternalLink, KeyRound, Link2Off, PlugZap, ShieldCheck } from '@lucide/svelte';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import DetailSheet from '$kit/ui/detail-sheet.svelte';
  import PageTabs, { type PageTab } from '$kit/ui/page-tabs.svelte';
  import StatusDot from '$kit/ui/status-dot.svelte';
  import { dateTime } from '$kit/format/time';
  import type { ExtensionRow } from '$lib/api/extensions';
  import { statusTime } from '../shared/extension-rows';
  import ExtensionApproval from './ExtensionApproval.svelte';
  import { createApprovalSheet } from '../state/approval-sheet.svelte';
  import type { ExtensionsController } from '../state/extensions-controller.svelte';
  import MockupBadge from '$kit/ui/mockup-badge.svelte';
  import type { InstallsMock } from '../mockup/installs-mock.svelte';

  let { ctrl, mock }: { ctrl: ExtensionsController; mock: InstallsMock } = $props();

  type SheetTab = 'info' | 'permissions';

  const row = $derived(ctrl.panel === 'about' ? ctrl.picked : null);
  // The sheet is open while a row is picked for About; closing it un-picks the row.
  const getOpen = () => row !== null;
  const setOpen = (next: boolean) => {
    if (!next) ctrl.closePanel();
  };

  // The tab picked for this row; a row picked anew opens on Permissions when its app waits, else on Info.
  let chosen = $state<{ id: string; tab: SheetTab } | null>(null);
  const waits = $derived(!!row && row.kind === 'app' && row.waits);
  // What the picked app asks (read only for an app: a channel asks for nothing)
  // mockup: Hello's mock row has no record in the core to read its approval from
  const sheet = createApprovalSheet(
    () => (row && row.kind === 'app' && !row.extension_id.startsWith('mockup-') ? row.extension_id : ''),
    () => ctrl.reload()
  );
  // mockup (Installing apps, task 6): an installed app's facts and what is left to set
  const installed = $derived(row ? mock.installOf(row) : null);
  const left = $derived(row ? mock.setupLeft(row) : []);
  const tab = $derived<SheetTab>(
    row && chosen?.id === row.extension_id ? chosen.tab : waits ? 'permissions' : 'info'
  );
  const tabs = $derived<PageTab<SheetTab>[]>([
    { id: 'info', label: 'Info' },
    { id: 'permissions', label: 'Permissions', ...(waits ? { count: row?.waiting_count ?? 0, countTone: 'primary' as const } : {}) }
  ]);
  const pick = (next: SheetTab) => {
    if (row) chosen = { id: row.extension_id, tab: next };
  };

  // One row of the Details list: its name, then its value
  const ROW = 'grid grid-cols-[160px_1fr] items-start gap-3 px-3 py-2 text-sm';

  function facts(r: ExtensionRow): [string, string][] {
    const out: [string, string][] = [
      ['Name', r.name],
      ['Version', mock.installOf(r)?.version || r.version || '—'], // mockup: an installed app's own
      ['Paired', r.paired_at ? dateTime(r.paired_at) : 'Not yet'],
      ['Started by', r.started_by_core ? 'The core' : 'Itself'],
      ['Relays chat', r.relays_chat ? "Yes: other people's messages" : 'No'],
      ['Settings kept', r.started_by_core ? 'In the core' : 'In the app']
    ];
    if (r.pairing) out.push(['Account', r.linked ? `Linked${r.account ? `: ${r.account}` : ''}` : 'Not linked']);
    return out;
  }

</script>

<DetailSheet
  bind:open={getOpen, setOpen}
  wide
  class="data-[side=right]:sm:max-w-4xl"
  title={row?.label ?? ''}
  description={row ? (row.kind === 'channel' ? 'Channel' : 'App') : ''}
>
  {#snippet adornment()}
    {#if row}<StatusDot tone={ctrl.statusOf(row).tone} label={ctrl.statusOf(row).text} />{/if}
  {/snippet}

  {#if row}
    {@const time = statusTime(row)}
    {#if row.description}<p class="text-muted-foreground">{row.description}</p>{/if}

    {#if row.kind === 'app'}
      <PageTabs {tabs} value={tab} onchange={pick} label="{row.label}'s sheet" variant="line" />
    {/if}

    {#if row.kind === 'app' && tab === 'permissions'}
      <ExtensionApproval {sheet} label={row.label} titleOf={ctrl.titleOf} />
    {:else}
      <!-- The app's details as one list; what other apps and Hiro may ask it, and its AI tasks, after it. -->
      <section class="grid gap-2">
        <h3 class="text-sm font-semibold">Details</h3>
        <dl class="divide-y rounded-md border">
          <div class={ROW}>
            <dt class="text-muted-foreground">Status</dt>
            <dd class="grid gap-0.5">
              <span class="flex items-center gap-2"><StatusDot tone={ctrl.statusOf(row).tone} /><span>{ctrl.statusOf(row).text}{#if time}<span class="text-muted-foreground">, {time.words} {dateTime(time.at)}</span>{/if}</span></span>
              {#if ctrl.testResult(row)}<span class="text-xs text-muted-foreground">{ctrl.testResult(row)}</span>{/if}
            </dd>
          </div>
          {#if row.site}
            <div class={ROW}>
              <dt class="text-muted-foreground">Address</dt>
              <dd class="min-w-0 truncate">
                <a href={row.site} target="_blank" rel="noreferrer" class="inline-flex items-center gap-1 text-primary hover:underline">{row.site} <ExternalLink size={12} /></a>
              </dd>
            </div>
          {/if}
          {#if sheet.networkName}
            <div class={ROW}>
              <dt class="text-muted-foreground">Network name</dt>
              <dd class="min-w-0 truncate">{sheet.networkName}</dd>
            </div>
          {/if}
          {#each facts(row) as [key, value] (key)}
            <div class={ROW}>
              <dt class="text-muted-foreground">{key}</dt>
              <dd class="min-w-0 truncate" title={value}>{value}</dd>
            </div>
          {/each}
          {#if installed}
            {#each [['Installed by', 'The core'], ['Port', String(installed.port)], ['Version before', installed.previous || '—'], ['Newer package', installed.offered || 'None'], ['Folder', installed.folder], ['Data', installed.data]] as [key, value] (key)}
              <div class={ROW}>
                <dt class="flex items-center gap-1.5 text-muted-foreground">{key} <MockupBadge /></dt>
                <dd class="min-w-0 truncate font-mono text-xs" title={value}>{value}</dd>
              </div>
            {/each}
          {/if}
        </dl>
      </section>

      {#if row.kind === 'app' && left.length}
        <section class="grid gap-2">
          <h3 class="flex items-center gap-2 text-sm font-semibold">To set <MockupBadge /></h3>
          <ul class="divide-y rounded-md border">
            {#each left as item (item.title)}
              <li class="flex items-center justify-between gap-3 px-3 py-2.5 text-sm">
                <span>{item.title}</span>
                <a href={item.link} target="_blank" rel="noreferrer" class="inline-flex items-center gap-1 text-primary hover:underline">Open <ExternalLink size={12} /></a>
              </li>
            {/each}
          </ul>
        </section>
      {/if}

      {#if row.kind === 'app'}
        <section class="grid gap-2">
          <h3 class="text-sm font-semibold">Available to other apps and Hiro</h3>
          {#if row.offers.length}
            <ul class="divide-y rounded-md border">
              {#each row.offers as offer (offer.name)}
                <li class="grid gap-0.5 px-3 py-2.5">
                  <span class="text-sm">{offer.name}</span>
                  {#if offer.says}<span class="text-xs text-muted-foreground">{offer.says}</span>{/if}
                </li>
              {/each}
            </ul>
          {:else}
            <p class="text-sm text-muted-foreground">Nothing.</p>
          {/if}
        </section>

        <section class="grid gap-2">
          <h3 class="text-sm font-semibold">AI tasks</h3>
          {#if row.uses.length}
            <div class="flex flex-wrap gap-1.5">
              {#each row.uses as use (use)}<Badge variant="secondary">{use}</Badge>{/each}
            </div>
          {:else}
            <p class="text-sm text-muted-foreground">None.</p>
          {/if}
        </section>
      {/if}
    {/if}
  {/if}

  {#snippet actions()}
    {#if row}
      {#if waits || (tab === 'permissions' && sheet.dirty)}
        <!-- The owner's answer, in reach without scrolling -->
        {#if waits && sheet.declinable}
          <Button variant="outline" disabled={ctrl.busy || sheet.saving.busy} onclick={() => void ctrl.decline(row)}>Decline</Button>
        {/if}
        <Button disabled={sheet.saving.busy || !sheet.approval} onclick={() => void sheet.approve()}>
          <ShieldCheck size={15} />
          {!waits ? 'Save' : row.pending ? `Approve ${row.label}` : 'Approve what is new'}
        </Button>
      {:else}
        <Button variant="outline" disabled={!row.connected || ctrl.testing} onclick={() => void ctrl.testCall(row)}>
          <PlugZap size={15} /> Test call
        </Button>
        {#if row.kind === 'app'}
          <Button
            variant="outline"
            disabled={ctrl.busy}
            title="For this app after it lost its key: it keeps its rights, AI picks and name"
            onclick={() => void ctrl.pairAgain(row)}
          >
            <KeyRound size={15} /> Pair again
          </Button>
        {/if}
        <Button variant="destructive" disabled={row.mandatory || ctrl.busy} onclick={() => (installed ? mock.openRemove(row) : void ctrl.remove(row))}>
          <Link2Off size={15} /> Remove
        </Button>
      {/if}
    {/if}
  {/snippet}
</DetailSheet>
