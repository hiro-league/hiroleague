<script lang="ts">
  import type { IngestTraceEdge, IngestTraceNode } from '$lib/api/graph-runs';
  import { shortGraphId } from '$lib/format/short-graph-id';
  import TraceTable from '../shared/TraceTable.svelte';
  import ValidityPill from '../shared/ValidityPill.svelte';
  import { fmtDate, isCurrent, temporalTitle } from '../shared/trace-format';

  let {
    nodes,
    edges
  }: {
    nodes: IngestTraceNode[];
    edges: IngestTraceEdge[];
  } = $props();
</script>

<section class="result-section">
  <h3 class="stage-group__title">Entities ({nodes.length})</h3>
  {#if nodes.length}
    <TraceTable>
      <thead>
        <tr>
          <th class="num">#</th>
          <th>Entity</th>
          <th>Type</th>
          <th>Summary</th>
          <th>UUID</th>
        </tr>
      </thead>
      <tbody>
        {#each nodes as n, ni (n.uuid + ':' + ni)}
          <tr>
            <td class="num">{ni + 1}</td>
            <td class="entity">{n.name || '—'}</td>
            <td class="rel">{n.entity_type || '—'}</td>
            <td class="fact">{n.summary || '—'}</td>
            <td class="uuid" title={n.uuid}>{shortGraphId(n.uuid)}</td>
          </tr>
        {/each}
      </tbody>
    </TraceTable>
  {:else}
    <p class="trace-empty">No entities persisted.</p>
  {/if}

  <h3 class="stage-group__title">Facts ({edges.length})</h3>
  {#if edges.length}
    <TraceTable>
      <thead>
        <tr>
          <th class="num">#</th>
          <th class="vstate" title="Validity: current (✓) vs superseded (✗)">v</th>
          <th>Fact</th>
          <th>Relation</th>
          <th>Valid</th>
          <th>Invalid</th>
          <th class="num" title="Supporting episodes (chunk_ids)">Eps</th>
          <th>UUID</th>
        </tr>
      </thead>
      <tbody>
        {#each edges as e, ei (e.uuid + ':' + ei)}
          <tr>
            <td class="num">{ei + 1}</td>
            <td class="vstate">
              <ValidityPill current={isCurrent(e)} title={temporalTitle(e)} />
            </td>
            <td class="fact">{e.fact}</td>
            <td class="rel">{e.name || '—'}</td>
            <td class="temporal" title={e.valid_at ?? ''}>{fmtDate(e.valid_at, false) || '—'}</td>
            <td class="temporal" title={e.invalid_at ?? ''}>{fmtDate(e.invalid_at, false) || '—'}</td>
            <td class="num">{e.episodes?.length ?? 0}</td>
            <td class="uuid" title={e.uuid}>{shortGraphId(e.uuid)}</td>
          </tr>
        {/each}
      </tbody>
    </TraceTable>
  {:else}
    <p class="trace-empty">No facts persisted.</p>
  {/if}
</section>

<style>
  .stage-group__title {
    margin: 4px 0 0;
    font-size: 13px;
    font-weight: 700;
    display: flex;
    align-items: baseline;
    gap: 6px;
  }

  .trace-empty {
    margin: 0;
    font-size: 12px;
    color: var(--muted-foreground);
  }

  .result-section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
</style>
