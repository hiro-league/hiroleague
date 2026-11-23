<script lang="ts">
  // mockup: one extension's detail, drawn from its description. One shape for a channel and an app; the
  // parts only one kind has (a link to an account, settings kept in the core, a site, offers) show when it has them.
  import { ExternalLink, Link2Off, PlugZap, QrCode, SlidersHorizontal } from '@lucide/svelte';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import DetailSheet from '$kit/ui/detail-sheet.svelte';
  import SectionLabel from '$kit/ui/section-label.svelte';
  import StatusDot from '$kit/ui/status-dot.svelte';
  import { dateTime } from '$kit/format/time';
  import { statusOf, type MockExtension } from './one-list-mock';
  import type { OneListMockup } from './one-list-mockup.svelte';

  let { list }: { list: OneListMockup } = $props();

  const row = $derived(list.selected);
  // The sheet is open while a row is picked; closing it un-picks the row.
  const getOpen = () => row !== null;
  const setOpen = (next: boolean) => {
    if (!next) list.close();
  };

  function facts(r: MockExtension): [string, string][] {
    return [
      ['Name', r.name],
      ['Version', r.version],
      ['Paired', dateTime(r.paired_at)],
      ['Started by', r.started_by_core ? 'The core' : 'Itself'],
      ['Relays chat', r.relays_chat ? "Yes: other people's messages" : 'No'],
      ['Its settings', r.started_by_core ? 'Kept in the core' : 'Kept in the app']
    ];
  }
</script>

<DetailSheet bind:open={getOpen, setOpen} title={row?.label ?? ''} description={row ? (row.kind === 'channel' ? 'Channel' : 'App') : ''}>
  {#snippet adornment()}
    {#if row}<StatusDot tone={statusOf(row).tone} label={statusOf(row).text} />{/if}
  {/snippet}

  {#if row}
    {@const status = statusOf(row)}
    <p class="text-muted-foreground">{row.description}</p>

    <section class="grid gap-2">
      <SectionLabel>Connection</SectionLabel>
      <p>
        {status.text}{#if row.enabled !== false}
          , {row.connected ? 'since' : 'last seen'} {dateTime(row.since)}{/if}
      </p>
    </section>

    <section class="grid gap-2">
      <SectionLabel>About</SectionLabel>
      <dl class="grid grid-cols-[120px_1fr] gap-x-3 gap-y-1.5">
        {#each facts(row) as [key, value] (key)}
          <dt class="text-muted-foreground">{key}</dt>
          <dd class="min-w-0 truncate">{value}</dd>
        {/each}
      </dl>
    </section>

    {#if row.link}
      <section class="grid gap-2">
        <SectionLabel>Its account</SectionLabel>
        <div class="flex items-center justify-between gap-3">
          <span class="flex items-center gap-2">
            <StatusDot tone={row.link.linked ? 'ok' : 'warn'} />
            {row.link.linked ? `Linked: ${row.link.account}` : 'Not linked'}
          </span>
          <Button size="sm" variant="outline" onclick={() => list.notYet("show the account's QR code to link it")}>
            <QrCode size={13} /> {row.link.linked ? 'Link again' : 'Link'}
          </Button>
        </div>
      </section>
    {/if}

    {#if row.settings}
      <section class="grid gap-2">
        <SectionLabel>
          Settings
          {#snippet actions()}
            {#if row.settings?.length}
              <Button size="sm" variant="outline" onclick={() => list.notYet('open its settings form, drawn from its config_schema')}>
                <SlidersHorizontal size={13} /> Change
              </Button>
            {/if}
          {/snippet}
        </SectionLabel>
        {#if row.settings.length}
          <dl class="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1.5">
            {#each row.settings as s (s.key)}
              <dt class="text-muted-foreground">{s.label}</dt>
              <dd>{s.secret ? (s.value ? 'Set' : 'Not set') : s.value}</dd>
            {/each}
          </dl>
        {:else}
          <p class="text-muted-foreground">It has no settings.</p>
        {/if}
      </section>
    {/if}

    {#if row.site}
      <section class="grid gap-2">
        <SectionLabel>Its site</SectionLabel>
        <a href={row.site} target="_blank" rel="noreferrer" class="inline-flex items-center gap-1.5 text-primary hover:underline">
          {row.site} <ExternalLink size={13} />
        </a>
      </section>
    {/if}

    {#if row.offers}
      <section class="grid gap-2">
        <SectionLabel>What it offers</SectionLabel>
        {#if row.offers.length}
          <ul class="grid gap-1.5">
            {#each row.offers as offer (offer.name)}
              <li><span class="font-medium">{offer.name}</span> <span class="text-muted-foreground">· {offer.says}</span></li>
            {/each}
          </ul>
        {:else}
          <p class="text-muted-foreground">Nothing for other apps or Hiro to ask.</p>
        {/if}
      </section>
    {/if}

    {#if row.uses}
      <section class="grid gap-2">
        <SectionLabel>AI uses</SectionLabel>
        {#if row.uses.length}
          <div class="flex flex-wrap gap-1.5">
            {#each row.uses as use (use)}<Badge variant="secondary">{use}</Badge>{/each}
          </div>
        {:else}
          <p class="text-muted-foreground">None.</p>
        {/if}
      </section>
    {/if}
  {/if}

  {#snippet actions()}
    {#if row}
      <Button
        variant="outline"
        disabled={!row.connected}
        onclick={() => list.notYet('ask it for its name and version (the test call)')}
      >
        <PlugZap size={15} /> Test call
      </Button>
      <Button variant="destructive" disabled={row.mandatory} onclick={() => void list.remove(row)}>
        <Link2Off size={15} /> Remove
      </Button>
    {/if}
  {/snippet}
</DetailSheet>
