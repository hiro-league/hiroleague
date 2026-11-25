<script lang="ts">
  // mockup: an app's Permissions tab (Permissions phase 8): what it asks to do on its own. What a new version newly
  // asks comes first, in its own list; then Required (approved with the app) and Optional (a switch each). The app's
  // details are on the Info tab; Approve and Decline sit in the sheet's footer.
  import { Switch } from '$kit/components/ui/switch/index.js';
  import MockupBadge from '$kit/ui/mockup-badge.svelte';
  import { askWords, type Ask } from '$lib/approval-mockup/approval-mockup';
  import { approvalMockup } from '$lib/approval-mockup/store.svelte';

  interface Props {
    /** The app's name, its key. */
    name: string;
    /** The app's title, as people read it. */
    label: string;
    /** Another app's title, by its name (for "Ask HomeHiro"). */
    titleOf: (name: string) => string;
  }
  let { name, label, titleOf }: Props = $props();

  const approval = $derived(approvalMockup.of(name));
  // Each ask keeps its index for its switch.
  const indexed = $derived((approval?.asks ?? []).map((item, i) => ({ item, i })));
  // A new app's asks are all new: they go in Required and Optional. A new version's extras get their own list.
  const fresh = $derived(approval && !approval.pending ? indexed.filter((x) => x.item.waiting) : []);
  const rest = $derived(indexed.filter((x) => !fresh.includes(x)));
  const required = $derived(rest.filter((x) => x.item.required));
  const optional = $derived(rest.filter((x) => !x.item.required));
</script>

{#snippet list(title: string, says: string, rows: { item: Ask; i: number }[])}
  <section class="grid gap-2">
    <div class="flex items-baseline gap-2">
      <h3 class="text-sm font-semibold">{title}</h3>
      <span class="text-xs text-muted-foreground">{says}</span>
    </div>
    <ul class="divide-y rounded-md border">
      {#each rows as { item, i } (item.permission + (item.to ?? ''))}
        <li class="grid grid-cols-[1fr_auto] items-center gap-4 px-3 py-2.5">
          <div class="grid min-w-0 gap-0.5">
            <span class="text-sm">{askWords(item, titleOf)}</span>
            <span class="text-xs text-muted-foreground">{item.why}</span>
          </div>
          {#if !item.required}
            <Switch
              checked={item.approved}
              onCheckedChange={(on) => approvalMockup.setSwitch(name, i, on)}
              aria-label="{askWords(item, titleOf)}: {item.approved ? 'on' : 'off'}"
              title={item.approved ? 'On: it may do this' : 'Off: it is refused this'}
            />
          {/if}
        </li>
      {/each}
    </ul>
  </section>
{/snippet}

{#if approval}
  <div class="grid gap-6">
    <div class="flex items-start justify-between gap-3">
      <p class="text-sm text-muted-foreground">
        {#if approval.pending}
          {label} waits for your approval: until then it gets nothing it asks for.
        {:else if fresh.length}
          A new version of {label} asks for more. It keeps working with what you approved before.
        {:else}
          What {label} may do on its own, with nobody signed in.
        {/if}
      </p>
      <MockupBadge />
    </div>

    {#if fresh.length}
      {@render list('New in this version', 'waits for your yes', fresh)}
    {/if}
    {#if required.length}
      {@render list('Required', 'it can’t work without these', required)}
    {/if}
    {#if optional.length}
      {@render list('Optional', 'switch each on or off', optional)}
    {/if}
  </div>
{/if}
