<script lang="ts">
  import type { IngestEntityType, IngestTraceStage } from '$lib/api/graph-runs';
  import StageCard from '../shared/StageCard.svelte';
  import TraceTable from '../shared/TraceTable.svelte';
  import { fmtDate, isISO, prettyKey } from '../shared/trace-format';
  import {
    briefName,
    briefType,
    dedupJson,
    dedupMerges,
    extractedEntities as extractedEntitiesFor,
    inputView,
    messages,
    outputView,
    prettyOutput,
    resolveFactsView,
    stageCount as stageCountFor,
    stageMeta,
    type ExtractedEntityRow,
    type Phase,
    type ResolveFactsView,
    type ViewTable
  } from '../shared/ingest-trace-derive';

  let {
    phase,
    entityTypeById,
    isCollapsed,
    isPromptOpen,
    isJsonOpen,
    onToggleStage,
    onTogglePrompt,
    onToggleJson
  }: {
    phase: Phase;
    entityTypeById: Map<number, IngestEntityType>;
    isCollapsed: (index: number) => boolean;
    isPromptOpen: (index: number) => boolean;
    isJsonOpen: (index: number) => boolean;
    onToggleStage: (index: number) => void;
    onTogglePrompt: (index: number) => void;
    onToggleJson: (index: number) => void;
  } = $props();

  const extractedEntities = (stage: IngestTraceStage): ExtractedEntityRow[] | null =>
    extractedEntitiesFor(stage, entityTypeById);

  const stageCount = (stage: IngestTraceStage, node: string): number | null =>
    stageCountFor(stage, node, entityTypeById);
</script>

{#snippet viewTable(view: ViewTable)}
  {#if view.kind === 'rows'}
    <TraceTable out>
      <thead>
        <tr>
          <th class="num">#</th>
          {#each view.columns as col (col)}<th>{prettyKey(col)}</th>{/each}
        </tr>
      </thead>
      <tbody>
        {#each view.rows as row, ri (ri)}
          <tr>
            <td class="num">{ri + 1}</td>
            {#each view.columns as col (col)}
              <td class="cell">
                {#if isISO(row[col])}<span title={row[col]}>{fmtDate(row[col])}</span>{:else}{row[col]}{/if}
              </td>
            {/each}
          </tr>
        {/each}
      </tbody>
    </TraceTable>
  {:else if view.kind === 'kv'}
    <TraceTable out>
      <tbody>
        {#each view.entries as entry (entry.key)}
          <tr>
            <td class="kv-key">{prettyKey(entry.key)}</td>
            <td class="cell">
              {#if isISO(entry.value)}<span title={entry.value}>{fmtDate(entry.value)}</span>{:else}{entry.value}{/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </TraceTable>
  {:else if view.kind === 'scalar'}
    <p class="out-scalar">{view.value}</p>
  {/if}
{/snippet}

{#snippet factVerdict(rfv: ResolveFactsView)}
  <div class="fact-verdict">
    <div class="fact-new">
      <span class="output-block__label">New fact</span>
      <p class="fact-new__text">{rfv.newFact || '—'}</p>
    </div>
    <p class="fact-summary">
      {#if rfv.contraCount}<span class="fact-badge fact-badge--contra">{rfv.contraCount} contradicted → invalidated</span>{/if}
      {#if rfv.dupCount}<span class="fact-badge fact-badge--dup">{rfv.dupCount} duplicate</span>{/if}
      {#if !rfv.contraCount && !rfv.dupCount}<span class="fact-badge fact-badge--new">added as new — no duplicate or contradiction</span>{/if}
    </p>
    {#if rfv.candidates.length}
      <TraceTable out>
        <thead>
          <tr><th class="num">idx</th><th>Origin</th><th>Candidate fact</th><th>Decision</th></tr>
        </thead>
        <tbody>
          {#each rfv.candidates as c (c.idx)}
            <tr class:fact-row--hit={c.decision !== 'none'}>
              <td class="num">{c.idx}</td>
              <td class="rel">{c.origin}</td>
              <td class="cell">{c.fact}</td>
              <td>
                {#if c.decision === 'contradicted'}
                  <span class="fact-badge fact-badge--contra">contradicted → invalidated</span>
                {:else if c.decision === 'duplicate'}
                  <span class="fact-badge fact-badge--dup">duplicate</span>
                {:else}
                  <span class="fact-dim">—</span>
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </TraceTable>
    {:else}
      <p class="trace-empty">No candidate facts — added directly as new.</p>
    {/if}
  </div>
{/snippet}

{#snippet entitiesTable(rows: ExtractedEntityRow[])}
  <TraceTable out>
    <thead>
      <tr>
        <th class="num">#</th>
        <th>Entity</th>
        <th>Type</th>
        <th>Type description</th>
      </tr>
    </thead>
    <tbody>
      {#each rows as row, ri (ri)}
        <tr>
          <td class="num">{ri + 1}</td>
          <td class="entity">{row.name}</td>
          <td><span class="type-chip">{row.typeName}</span></td>
          <td class="cell type-desc">{row.description || '—'}</td>
        </tr>
      {/each}
    </tbody>
  </TraceTable>
{/snippet}

{#if phase.hint}<p class="phase-hint">{phase.hint}</p>{/if}

{#each phase.groups as group (group.node)}
  <section class="stage-group">
    <h3 class="stage-group__title">
      {group.label}
      {#if group.stages.length > 1}<span class="stage-group__count">×{group.stages.length}</span>{/if}
    </h3>

    {#if group.node === 'dedup_entities_auto'}
      {@const gidx = group.stages[0].idx}
      {@const merges = dedupMerges(group)}
      <StageCard
        collapsed={isCollapsed(gidx)}
        onToggle={() => onToggleStage(gidx)}
        accent="dedup"
        badge="dedup"
        pills={[{ value: merges.length, title: 'Auto-merges' }]}
        expandTitle="Expand"
        collapseTitle="Collapse"
        bodyPadded
      >
        {#snippet label()}Merge map{/snippet}
        {#snippet meta()}auto-merges · deterministic (no LLM){/snippet}
        <p class="phase-hint">
          Exact-name / fuzzy MinHash collapses — each freshly-extracted entity reused an
          existing node without an LLM call.
        </p>
        <TraceTable out>
          <thead>
            <tr>
              <th class="num">#</th>
              <th>Extracted entity</th>
              <th class="arrow-col"></th>
              <th>Merged into (kept)</th>
              <th>Kept summary</th>
            </tr>
          </thead>
          <tbody>
            {#each merges as mg, mi (mg.idx)}
              <tr>
                <td class="num">{mi + 1}</td>
                <td class="entity">
                  {briefName(mg.from)}
                  {#if briefType(mg.from)}<span class="type-dim">· {briefType(mg.from)}</span>{/if}
                </td>
                <td class="arrow-col">→</td>
                <td class="entity">
                  {briefName(mg.into)}
                  {#if briefType(mg.into)}<span class="type-dim">· {briefType(mg.into)}</span>{/if}
                </td>
                <td class="cell">{mg.into.summary || '—'}</td>
              </tr>
            {/each}
          </tbody>
        </TraceTable>
        <button
          type="button"
          class="prompt-toggle"
          aria-expanded={isJsonOpen(gidx)}
          onclick={() => onToggleJson(gidx)}
        >
          {isJsonOpen(gidx) ? '\u25BE' : '\u25B8'} Raw JSON
        </button>
        {#if isJsonOpen(gidx)}
          <pre class="output-block__json">{dedupJson(group)}</pre>
        {/if}
      </StageCard>
    {:else}
      {#each group.stages as { stage, idx } (idx)}
        {@const ov = outputView(stage)}
        {@const iv = inputView(stage)}
        {@const rfv = group.node === 'resolve_facts' ? resolveFactsView(stage) : null}
        {@const ee = group.node === 'extract_entities' ? extractedEntities(stage) : null}
        {@const count = stageCount(stage, group.node)}
        <StageCard
          collapsed={isCollapsed(idx)}
          onToggle={() => onToggleStage(idx)}
          accent={stage.source}
          badge={stage.source !== 'llm' ? stage.source : undefined}
          pills={count !== null ? [{ value: count, title: 'Items produced by this stage' }] : []}
          bodyPadded
        >
          {#snippet label()}{stage.label}{/snippet}
          {#snippet meta()}{stageMeta(stage)}{/snippet}
          {#if iv.kind !== 'empty'}
            <div class="output-block">
              <span class="output-block__label">Input — what this stage was given</span>
              {@render viewTable(iv)}
            </div>
          {/if}

          <div class="output-block">
            {#if rfv}
              {@render factVerdict(rfv)}
            {:else if ee}
              {@render entitiesTable(ee)}
            {:else if ov.kind === 'empty'}
              <p class="trace-empty">No structured output.</p>
            {:else}
              {@render viewTable(ov)}
            {/if}

            {#if messages(stage).length}
              <button
                type="button"
                class="prompt-toggle"
                aria-expanded={isPromptOpen(idx)}
                onclick={() => onTogglePrompt(idx)}
              >
                {isPromptOpen(idx) ? '▾' : '▸'} Prompt ({messages(stage).length} messages) — the context this stage ran on
              </button>
              {#if isPromptOpen(idx)}
                <div class="prompt-list">
                  {#each messages(stage) as msg, mi (mi)}
                    <div class="prompt-msg">
                      <span class="prompt-msg__role">{msg.role}</span>
                      <pre class="prompt-msg__content">{msg.content}</pre>
                    </div>
                  {/each}
                </div>
              {/if}
            {/if}

            <button
              type="button"
              class="prompt-toggle"
              aria-expanded={isJsonOpen(idx)}
              onclick={() => onToggleJson(idx)}
            >
              {isJsonOpen(idx) ? '\u25BE' : '\u25B8'} Raw JSON
            </button>
            {#if isJsonOpen(idx)}
              <pre class="output-block__json">{prettyOutput(stage)}</pre>
            {/if}
          </div>
        </StageCard>
      {/each}
    {/if}
  </section>
{/each}

<style>
  .phase-hint {
    margin: 0;
    font-size: 11px;
    color: var(--muted-foreground);
  }

  .trace-empty {
    margin: 0;
    font-size: 12px;
    color: var(--muted-foreground);
  }

  .stage-group {
    flex: none;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .stage-group__title {
    margin: 4px 0 0;
    font-size: 13px;
    font-weight: 700;
    display: flex;
    align-items: baseline;
    gap: 6px;
  }

  .stage-group__count {
    font-size: 11px;
    font-weight: 600;
    color: var(--muted-foreground);
  }

  .prompt-toggle {
    align-self: flex-start;
    appearance: none;
    border: none;
    background: transparent;
    padding: 0;
    font-size: 11px;
    font-weight: 600;
    color: var(--muted-foreground);
    cursor: pointer;
  }

  .prompt-toggle:hover {
    color: var(--foreground);
  }

  .prompt-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .prompt-msg {
    border: 1px solid color-mix(in srgb, var(--muted-foreground) 14%, transparent);
    border-radius: 6px;
    overflow: hidden;
  }

  .prompt-msg__role {
    display: block;
    padding: 3px 8px;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted-foreground);
    background: color-mix(in srgb, var(--muted-foreground) 8%, transparent);
  }

  .prompt-msg__content,
  .output-block__json {
    margin: 0;
    padding: 8px;
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
      monospace;
    font-size: 11px;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 320px;
    overflow: auto;
  }

  .output-block__label {
    display: block;
    font-size: 11px;
    font-weight: 600;
    color: var(--muted-foreground);
    margin-bottom: 4px;
  }

  .output-block__json {
    border: 1px solid color-mix(in srgb, var(--primary) 25%, transparent);
    border-radius: 6px;
    background: color-mix(in srgb, var(--primary) 6%, transparent);
    margin-top: 6px;
  }

  .output-block {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .out-scalar {
    margin: 0;
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .type-chip {
    display: inline-block;
    padding: 0 6px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    white-space: nowrap;
    background: color-mix(in srgb, var(--primary) 14%, transparent);
    border: 1px solid color-mix(in srgb, var(--primary) 40%, transparent);
  }

  .type-desc {
    color: var(--muted-foreground);
  }

  .type-dim {
    color: var(--muted-foreground);
    font-weight: 400;
  }

  .fact-verdict {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .fact-new__text {
    margin: 2px 0 0;
    font-size: 12px;
    font-weight: 600;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .fact-summary {
    margin: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .fact-badge {
    display: inline-flex;
    align-items: center;
    font-size: 11px;
    font-weight: 600;
    padding: 1px 7px;
    border-radius: 999px;
    border: 1px solid transparent;
    white-space: nowrap;
  }

  .fact-badge--contra {
    color: #b45309;
    background: color-mix(in srgb, #f59e0b 16%, transparent);
    border-color: color-mix(in srgb, #f59e0b 45%, transparent);
  }

  .fact-badge--dup {
    color: #2563eb;
    background: color-mix(in srgb, #2563eb 14%, transparent);
    border-color: color-mix(in srgb, #2563eb 40%, transparent);
  }

  .fact-badge--new {
    color: #16a34a;
    background: color-mix(in srgb, #16a34a 14%, transparent);
    border-color: color-mix(in srgb, #16a34a 40%, transparent);
  }

  .fact-row--hit td {
    background: color-mix(in srgb, #f59e0b 8%, transparent);
  }

  .fact-dim {
    color: var(--muted-foreground);
  }
</style>
