<script lang="ts">
  /**
   * One row of the Providers list for a local server's provider or a plan tool, in the same 10
   * columns and cell styling as `ProvidersTab`'s catalog rows: status as dot + short word in the
   * Online column, secondary facts in the admin's tooltip (`FieldHelp`) next to the name, and one
   * action button that opens the provider's dialog.
   */
  import { Settings2 } from '@lucide/svelte';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import FieldHelp from '$lib/components/ui/field-help.svelte';
  import StatusDot from '$kit/ui/status-dot.svelte';
  import { cn } from '$lib/utils';
  import type { ProviderRowStatus } from './ai-types';

  type Props = {
    name: string;
    id: string;
    status: ProviderRowStatus;
    hosting: string;
    auth: string;
    models: number;
    kinds: string;
    recommended: { kind: string; name: string; id: string } | null;
    updated: string;
    /** Secondary facts, shown in the tooltip. */
    info: string;
    actionLabel: string;
    onAction: () => void;
  };

  let { name, id, status, hosting, auth, models, kinds, recommended, updated, info, actionLabel, onAction }: Props =
    $props();

</script>

<tr class="border-t">
  <td class="px-2 py-3 text-center" title={status.title}>
    <StatusDot tone={status.tone} />
    <small
      class={cn(
        'block whitespace-nowrap text-[10px] leading-tight',
        status.tone === 'warn' ? 'text-warning' : 'text-muted-foreground'
      )}
    >
      {status.word}
    </small>
  </td>
  <td class="min-w-0 px-3 py-3">
    <div class="inline-flex max-w-full items-center gap-1">
      <span class="min-w-0 truncate font-sans text-sm font-semibold">{name}</span>
      <FieldHelp text={info} label={`About ${name}`} />
    </div>
    <small class="block truncate text-xs text-muted-foreground">{id}</small>
  </td>
  <td class="px-3 py-3"><Badge variant={hosting === 'local' ? 'outline' : 'default'}>{hosting}</Badge></td>
  <td class="truncate px-3 py-3 text-xs text-muted-foreground">{auth}</td>
  <td class="px-3 py-3 text-center text-xs text-muted-foreground">{models}</td>
  <td class="truncate px-3 py-3 text-xs text-muted-foreground">{kinds}</td>
  <td class="truncate px-3 py-3 text-xs text-muted-foreground">-</td>
  <td class="min-w-0 px-3 py-3">
    {#if recommended}
      <span class="block font-sans text-sm"><span class="text-muted-foreground">{recommended.kind}:</span> {recommended.name}</span>
      <small class="block truncate text-xs text-muted-foreground">{recommended.id}</small>
    {:else}
      <span class="text-xs text-muted-foreground">-</span>
    {/if}
  </td>
  <td class="whitespace-nowrap px-3 py-3 text-xs text-muted-foreground">{updated}</td>
  <td class="px-3 py-3">
    <Button size="sm" variant="outline" onclick={onAction}>
      <Settings2 size={13} />
      {actionLabel}
    </Button>
  </td>
</tr>
