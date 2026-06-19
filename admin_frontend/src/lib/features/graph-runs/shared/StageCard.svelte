<script lang="ts">
  import type { Snippet } from 'svelte';

  // The collapsible "stage card" shared by both trace dialogs — a header that is one big toggle
  // (caret + label + optional badge + count pills) with an optional right-aligned meta line, and
  // a body that renders only while expanded. Extracted from the near-identical `.stage-card`
  // (ingest) and `.trace-stage` (retrieval) blocks.
  //
  // Pills are passed as DATA (not a snippet) so their styling stays inside this component; the
  // label / meta / body are snippets so each dialog renders its own content (highlighted labels,
  // tables, prompt disclosures, …).
  export type StagePill = { value: string | number; title?: string; tone?: 'neutral' | 'hit' };

  let {
    collapsed,
    onToggle,
    id = undefined,
    /** `'dedup'` paints the amber non-LLM accent border (ingest auto-merges). */
    accent = undefined,
    /** Decorative passthrough (retrieval tags each stage with its kind; unstyled). */
    dataKind = undefined,
    /** Small badge rendered right after the label text (ingest non-LLM stages). */
    badge = undefined,
    pills = [],
    expandTitle = 'Expand stage',
    collapseTitle = 'Collapse stage',
    /** Wrap the body in the padded `.stage-card__body` (ingest). Retrieval renders raw children. */
    bodyPadded = false,
    label,
    meta,
    children
  }: {
    collapsed: boolean;
    onToggle: () => void;
    id?: string;
    accent?: string;
    dataKind?: string;
    badge?: string;
    pills?: StagePill[];
    expandTitle?: string;
    collapseTitle?: string;
    bodyPadded?: boolean;
    label: Snippet;
    meta?: Snippet;
    children?: Snippet;
  } = $props();
</script>

<div class="stage-card" data-accent={accent} data-kind={dataKind} {id}>
  <header class="stage-card__head">
    <button
      type="button"
      class="stage-card__titlebtn"
      aria-expanded={!collapsed}
      title={collapsed ? expandTitle : collapseTitle}
      onclick={onToggle}
    >
      <span class="stage-card__caret">{collapsed ? '▸' : '▾'}</span>
      <span class="stage-card__label">
        {@render label()}
        {#if badge}<span class="stage-card__badge">{badge}</span>{/if}
      </span>
      {#each pills as pill, i (i)}
        <span
          class="stage-card__pill"
          class:stage-card__pill--hit={pill.tone === 'hit'}
          title={pill.title}
        >
          {pill.value}
        </span>
      {/each}
    </button>
    {#if meta}<span class="stage-card__meta">{@render meta()}</span>{/if}
  </header>

  {#if !collapsed}
    {#if bodyPadded}
      <div class="stage-card__body">{@render children?.()}</div>
    {:else}
      {@render children?.()}
    {/if}
  {/if}
</div>

<style>
  .stage-card {
    flex: none;
    border: 1px solid color-mix(in srgb, var(--muted-foreground) 18%, transparent);
    border-radius: 8px;
    overflow: hidden;
  }

  /* Non-LLM dedup stages get a distinct accent so they read as "observed, not model-driven". */
  .stage-card[data-accent='dedup'] {
    border-color: color-mix(in srgb, #f59e0b 45%, transparent);
  }

  .stage-card__head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 8px 10px;
    background: color-mix(in srgb, var(--muted-foreground) 8%, transparent);
  }

  /* Whole title row is the toggle — caret + label + count pills, all clickable. */
  .stage-card__titlebtn {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0;
    border: none;
    background: transparent;
    color: var(--foreground);
    cursor: pointer;
    text-align: left;
  }

  .stage-card__titlebtn:hover .stage-card__label {
    color: var(--primary);
  }

  .stage-card__titlebtn:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: 2px;
    border-radius: 4px;
  }

  .stage-card__caret {
    flex: none;
    width: 14px;
    font-size: 11px;
    line-height: 1;
    color: var(--muted-foreground);
  }

  .stage-card__label {
    min-width: 0;
    font-weight: 600;
    font-size: 13px;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .stage-card__badge {
    font-size: 10px;
    font-weight: 600;
    padding: 0 5px;
    border-radius: 3px;
    background: color-mix(in srgb, #f59e0b 20%, transparent);
    border: 1px solid color-mix(in srgb, #f59e0b 50%, transparent);
  }

  /* Count pills after the stage title: neutral = items/rows; --hit = search matches (eye-catch). */
  .stage-card__pill {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 18px;
    height: 17px;
    padding: 0 6px;
    border-radius: 999px;
    font-size: 10px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: var(--muted-foreground);
    background: color-mix(in srgb, var(--muted-foreground) 14%, transparent);
    border: 1px solid color-mix(in srgb, var(--muted-foreground) 24%, transparent);
  }

  .stage-card__pill--hit {
    color: #92400e;
    background: color-mix(in srgb, #facc15 60%, transparent);
    border-color: color-mix(in srgb, #facc15 80%, transparent);
  }

  .stage-card__meta {
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
      monospace;
    font-size: 11px;
    color: var(--muted-foreground);
    text-align: right;
    word-break: break-word;
  }

  .stage-card__body {
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
</style>
