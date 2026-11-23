<script lang="ts">
  // mockup: the one list's kind filter, a toggle per kind, several at once; none picked shows every kind.
  // Built on shadcn-svelte's Toggle Group (multiple), as CodeHiro's state filter is.
  import * as ToggleGroup from '$kit/components/ui/toggle-group/index.js';
  import type { ExtensionKind } from './one-list-mock';

  interface Props {
    picked: ExtensionKind[];
    counts: Record<ExtensionKind, number>;
    onchange: (next: ExtensionKind[]) => void;
  }
  let { picked, counts, onchange }: Props = $props();

  const KINDS: { id: ExtensionKind; label: string }[] = [
    { id: 'channel', label: 'Channels' },
    { id: 'app', label: 'Apps' }
  ];
</script>

<ToggleGroup.Root
  type="multiple"
  variant="outline"
  spacing={1}
  bind:value={() => picked, (v: string[]) => onchange(v as ExtensionKind[])}
  aria-label="Kinds shown (none picked: every kind)"
>
  {#each KINDS as k (k.id)}
    <ToggleGroup.Item
      value={k.id}
      class="h-7 min-w-0 gap-1.5 rounded-md px-2 text-xs font-normal text-muted-foreground hover:bg-transparent data-[state=on]:border-primary data-[state=on]:bg-primary/10 data-[state=on]:font-medium data-[state=on]:text-foreground"
    >
      {k.label}
      <span class="tabular-nums text-muted-foreground">{counts[k.id]}</span>
    </ToggleGroup.Item>
  {/each}
</ToggleGroup.Root>
