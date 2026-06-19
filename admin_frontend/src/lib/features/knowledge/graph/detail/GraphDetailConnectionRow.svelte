<script lang="ts">
  import { Building2, CalendarDays, Circle, MapPin, Package, Spline, User } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import GraphDetailHighlight from './GraphDetailHighlight.svelte';

  type ConnRow = {
    navKind: 'node' | 'edge';
    navId: string;
    title: string;
    subtitle: string;
    invalid: boolean;
    entityType: string | null;
  };

  const NODE_TYPE_ICON: Record<string, typeof Circle> = {
    Person: User,
    Place: MapPin,
    Event: CalendarDays,
    Organization: Building2,
    Object: Package,
    Entity: Circle
  };

  let {
    row,
    search,
    onNavigate,
    onPreview
  }: {
    row: ConnRow;
    search: string;
    onNavigate: (sel: { kind: 'node' | 'edge'; id: string }) => void;
    onPreview: (sel: { kind: 'node' | 'edge'; id: string } | null) => void;
  } = $props();

  const nodeIcon = (type: string | null): typeof Circle => NODE_TYPE_ICON[type ?? 'Entity'] ?? Circle;
  const RowIcon = $derived(row.navKind === 'edge' ? Spline : nodeIcon(row.entityType));
</script>

<button
  type="button"
  onclick={() => {
    onPreview(null);
    onNavigate({ kind: row.navKind, id: row.navId });
  }}
  onmouseenter={() => onPreview({ kind: row.navKind, id: row.navId })}
  onmouseleave={() => onPreview(null)}
  onfocus={() => onPreview({ kind: row.navKind, id: row.navId })}
  onblur={() => onPreview(null)}
  class="flex w-full items-start gap-2 rounded-md border bg-muted/30 px-2 py-1.5 text-left text-xs transition-colors hover:bg-accent"
>
  <RowIcon size={13} class="mt-0.5 flex-none text-muted-foreground" aria-hidden="true" />
  <div class="min-w-0 flex-1">
    <div class={cn('truncate font-medium', row.invalid && 'text-muted-foreground line-through')} title={row.title}>
      <GraphDetailHighlight text={row.title} {search} />
    </div>
    {#if row.subtitle}
      <div class="truncate text-[11px] text-muted-foreground" title={row.subtitle}>
        <GraphDetailHighlight text={row.subtitle} {search} />
      </div>
    {/if}
  </div>
</button>
