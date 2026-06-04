<script lang="ts">
  import { FilterX } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import MultiSelectFilter, {
    type MultiSelectOption
  } from '$lib/components/ui/multi-select-filter.svelte';
  import { cn } from '$lib/utils';
  import type { KnowledgeGraphModel } from '../state/knowledge-graph.svelte';
  import { colorFor } from './knowledge-graph-style';

  type Props = {
    graph: KnowledgeGraphModel;
  };

  let { graph }: Props = $props();

  const nodeFacets = $derived(graph.nodeTypeFacets());
  const edgeFacets = $derived(graph.edgeTypeFacets());

  // Edge relation vocabulary is free-form and long, so it goes in a searchable
  // multi-select dropdown. The dropdown thinks in VISIBLE (checked) values; the
  // model stores hidden, so we map between them here.
  const edgeOptions = $derived<MultiSelectOption[]>(
    edgeFacets.map((f) => ({ value: f.type, label: f.type, count: f.count }))
  );
  const visibleEdgeTypes = $derived(edgeFacets.filter((f) => !f.hidden).map((f) => f.type));

  // Shared chip styling: pressed (= visible) reads solid; un-pressed (= hidden)
  // dims, matching the catalog filter toggles.
  const chipBase =
    'inline-flex h-7 items-center gap-1.5 rounded-md border px-2 text-xs font-medium transition-colors';
  const chipOn = 'border-border bg-background text-foreground hover:bg-accent';
  const chipOff = 'border-transparent bg-muted/40 text-muted-foreground opacity-55 hover:opacity-100';
</script>

<!-- One scrolling row so a long, derived edge-type list never blows out the
     header height; the node-type group and Clear stay pinned at the ends. -->
<div class="flex flex-wrap items-center gap-x-4 gap-y-2">
  {#if nodeFacets.length}
    <div class="flex items-center gap-2" role="group" aria-label="Filter node types">
      <span class="font-sans text-xs font-semibold text-muted-foreground">Nodes</span>
      <div class="flex flex-wrap items-center gap-1">
        {#each nodeFacets as facet (facet.type)}
          {@const visible = !facet.hidden}
          <button
            type="button"
            class={cn(chipBase, visible ? chipOn : chipOff)}
            aria-pressed={visible}
            title={`${visible ? 'Hide' : 'Show'} ${facet.type} (${facet.count})`}
            onclick={() => graph.toggleNodeType(facet.type)}
          >
            <span
              class="size-2.5 rounded-full"
              style:background-color={colorFor(facet.type)}
              style:opacity={visible ? '1' : '0.5'}
              aria-hidden="true"
            ></span>
            {facet.type}
            <span class="tabular-nums text-muted-foreground">{facet.count}</span>
          </button>
        {/each}
      </div>
    </div>
  {/if}

  {#if edgeOptions.length}
    <MultiSelectFilter
      label="Edges"
      options={edgeOptions}
      selected={visibleEdgeTypes}
      searchPlaceholder="Search relations…"
      onSelectedChange={(values) => graph.setVisibleEdgeTypes(values)}
    />
  {/if}

  <Button
    variant="outline"
    size="sm"
    disabled={!graph.hasActiveFilters()}
    onclick={() => graph.clearFilters()}
  >
    <FilterX size={14} aria-hidden="true" /> Clear
  </Button>
</div>
