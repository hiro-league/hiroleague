<script lang="ts">
  import { FilterX } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import KnowledgeGraphFilterDropdown, {
    type GraphFilterOption
  } from './KnowledgeGraphFilterDropdown.svelte';
  import type { KnowledgeGraphModel } from '../state/knowledge-graph.svelte';
  import { colorFor, humanizeRelType } from './knowledge-graph-style';

  type Props = {
    graph: KnowledgeGraphModel;
  };

  let { graph }: Props = $props();

  // One dropdown PER node type, each listing that type's instances (pick all / none / some
  // Persons, etc.). The dropdown thinks in VISIBLE (checked) ids; the model stores hidden and
  // exposes the per-type selected set + per-instance connection count for us.
  const nodeGroups = $derived(graph.nodeInstanceFacets());
  const largeTypeThreshold = $derived(graph.largeTypeThreshold());

  // Edges use the SAME control: relation type as the option, edge-count as the weight.
  const edgeFacets = $derived(graph.edgeTypeFacets());
  // value stays the raw rel_type (canonical for filtering); label is humanized for display.
  const edgeOptions = $derived<GraphFilterOption[]>(
    edgeFacets.map((f) => ({ value: f.type, label: humanizeRelType(f.type), weight: f.count }))
  );
  const visibleEdgeTypes = $derived(edgeFacets.filter((f) => !f.hidden).map((f) => f.type));
</script>

<!-- One scrolling row so a long, derived type list never blows out the header height; the
     node-type group and Clear stay pinned at the ends. -->
<div class="flex flex-wrap items-center gap-x-4 gap-y-2">
  {#if nodeGroups.length}
    <div class="flex items-center gap-2" role="group" aria-label="Filter node instances by type">
      <span class="font-sans text-xs font-semibold text-muted-foreground">Nodes</span>
      <div class="flex flex-wrap items-center gap-1">
        {#each nodeGroups as group (group.type)}
          <KnowledgeGraphFilterDropdown
            label={group.type}
            color={colorFor(group.type)}
            options={group.options.map((o) => ({ value: o.id, label: o.name, weight: o.connections }))}
            selected={group.selectedIds}
            weightNoun="connection"
            note={group.count > largeTypeThreshold
              ? `${group.count} ${group.type} nodes — use search to narrow the list.`
              : undefined}
            onSelectedChange={(ids) => graph.setVisibleNodeIds(group.type, ids)}
          />
        {/each}
      </div>
    </div>
  {/if}

  {#if edgeOptions.length}
    <KnowledgeGraphFilterDropdown
      label="Edges"
      options={edgeOptions}
      selected={visibleEdgeTypes}
      weightNoun="edge"
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
