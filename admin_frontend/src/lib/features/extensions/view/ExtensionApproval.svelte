<script lang="ts">
  // An app's Permissions tab (Permissions phase 8): what it asks to do on its own. A new version's extras come first,
  // in their own list; then Required (approved with the app) and Optional (a switch each). The app's details are on
  // the Info tab; Approve, Save and Decline sit in the sheet's footer.
  import { Switch } from '$kit/components/ui/switch/index.js';
  import Notice from '$kit/ui/notice.svelte';
  import ResourceView from '$kit/ui/resource-view.svelte';
  import type { ApprovalItem } from '$lib/api/extensions';
  import { itemKey } from '../shared/approval-items';
  import type { ApprovalSheet } from '../state/approval-sheet.svelte';

  interface Props {
    sheet: ApprovalSheet;
    /** The app's title, as people read it. */
    label: string;
    /** Another app's title, by its name (for "Ask HomeHiro"). */
    titleOf: (name: string) => string;
  }
  let { sheet, label, titleOf }: Props = $props();

  // The owner's words; an ask to another app names it, an address or a network name shows its subject
  function words(i: ApprovalItem): string {
    if (i.permission === 'apps.ask') return `Ask ${titleOf(i.subject)} for its data`;
    const said = i.words.charAt(0).toUpperCase() + i.words.slice(1);
    return i.subject ? `${said}: ${i.subject}` : said;
  }

  const view = $derived({
    data: sheet.approval,
    error: sheet.error ?? '',
    loading: !sheet.approval && !sheet.error,
    reload: () => {}
  });
</script>

{#snippet list(title: string, says: string, rows: ApprovalItem[])}
  <section class="grid gap-2">
    <div class="flex items-baseline gap-2">
      <h3 class="text-sm font-semibold">{title}</h3>
      <span class="text-xs text-muted-foreground">{says}</span>
    </div>
    <ul class="divide-y rounded-md border">
      {#each rows as item (itemKey(item))}
        <li class="grid grid-cols-[1fr_auto] items-center gap-4 px-3 py-2.5">
          <div class="grid min-w-0 gap-0.5">
            <span class="text-sm">{words(item)}</span>
            {#if item.why}<span class="text-xs text-muted-foreground">{item.why}</span>{/if}
          </div>
          {#if !item.required}
            <Switch
              checked={sheet.isOn(itemKey(item))}
              onCheckedChange={(on) => sheet.setSwitch(itemKey(item), on)}
              aria-label="{words(item)}: {sheet.isOn(itemKey(item)) ? 'on' : 'off'}"
              title={sheet.isOn(itemKey(item)) ? 'On: it may do this' : 'Off: it is refused this'}
            />
          {/if}
        </li>
      {/each}
    </ul>
  </section>
{/snippet}

<ResourceView resource={view} loadingLabel="Reading what it asks…" errorTitle="Could not read what it asks" quiet>
  {#snippet children()}
    {@const approval = sheet.approval}
    {@const g = sheet.groups}
    {#if approval && g}
      <div class="grid gap-6">
        <p class="text-sm text-muted-foreground">
          {#if approval.approved_for_everything}
            {label} is from before approvals: it may do everything it did, until it says what it asks.
          {:else if approval.pending}
            {label} waits for your approval: until then it gets nothing it asks for.
          {:else if g.fresh.length}
            A new version of {label} asks for more. It keeps working with what you approved before.
          {:else}
            What {label} may do on its own, with nobody signed in.
          {/if}
        </p>
        {#if sheet.saving.error}<Notice tone="error" size="sm" message={sheet.saving.error} />{/if}
        {#if g.fresh.length}{@render list('New in this version', 'waits for your yes', g.fresh)}{/if}
        {#if g.required.length}{@render list('Required', 'it can’t work without these', g.required)}{/if}
        {#if g.optional.length}{@render list('Optional', 'switch each on or off', g.optional)}{/if}
        {#if !g.fresh.length && !g.required.length && !g.optional.length}
          <p class="text-sm text-muted-foreground">It asks for nothing beyond what every app has.</p>
        {/if}
      </div>
    {/if}
  {/snippet}
</ResourceView>
