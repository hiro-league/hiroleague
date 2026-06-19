<!--
  Reusable corpus transcript with search + match highlight.

  Renders the memory-eval corpus episodes as a dated transcript, with a search box that filters to
  matching episodes and highlights the term in the body. Used in two places:
    1. The Eval panel's "Corpus" section (review the turns the questions probe).
    2. A "Corpus" tab inside the retrieval/ingest trace dialogs (cross-reference a recalled/
       ingested fact against its source episode while inspecting the pipeline).

  The "enhanced" reading affordances (Markdown toggle, per-episode line clamp + show more/less,
  sticky episode index rail, position readout) only render in the Corpus-tab layout (when
  `stickyTop` is set). The compact trace-dialog tab stays a dense plain-text transcript.
-->
<script lang="ts">
  import Badge from '$lib/components/ui/badge.svelte';
  import GraphRangeSlider from '$lib/features/knowledge/graph/GraphRangeSlider.svelte';
  import MarkdownPreview from '$lib/components/ui/markdown/MarkdownPreview.svelte';
  import { Microscope, Share2, X } from '@lucide/svelte';
  import { SvelteSet } from 'svelte/reactivity';
  import type { CorpusEpisodeExtraction, EvalEpisode } from '$lib/api/knowledge';
  import { highlightSegments } from '$lib/features/knowledge/eval/eval-highlight';
  import { approxTokens, fmtCompact } from '$lib/features/knowledge/eval/eval-format';

  let {
    episodes,
    /** Compact = denser padding + smaller max-height, for the trace-dialog tab. */
    compact = false,
    /** Search term — bindable so a parent can own the input (e.g. the panel's Corpus header). */
    search = $bindable(''),
    /** Render the built-in search bar. Off when the parent supplies its own input. */
    showSearch = true,
    /** Show a standalone "N of M match" count line — used when the search input lives elsewhere
        (e.g. the trace dialog's top search drives this list, so the count surfaces here). */
    showCount = false,
    /** Bound the transcript with an inner scroll (`max-h-96`). Off ⇒ the list grows with the page
        (the panel's Corpus tab wants the page to own the scroll, not a nested box). */
    scroll = true,
    /** Per-episode at-ingest extraction (entity/fact counts + ingest-trace pointer), keyed by
        episode id. When given, each row shows an extracted/not badge; the ingest-pipeline button
        appears when `onOpenPipeline` is also wired. Omitted (the trace-dialog tab) ⇒ plain
        transcript, unchanged. */
    extraction,
    /** Open the ingest-pipeline dialog for one episode (its run_id + step_index). When set together
        with `extraction`, a "pipeline" button renders on every episode that has a trace. */
    onOpenPipeline,
    /** Open the Knowledge Graph view focused on this episode (its group + chunk_id). When set, a
        "graph" button renders on each episode (before "pipeline"). */
    onOpenGraph,
    /** When provided, render the search + filters together as ONE sticky toolbar pinned at this CSS
        `top` value (the Corpus tab passes the panel's sticky offset). Omitted ⇒ the legacy inline
        search/filter layout (the trace-dialog tab). Also gates the reading affordances (Markdown
        toggle, line clamp, index rail, position readout). */
    stickyTop
  }: {
    episodes: EvalEpisode[];
    compact?: boolean;
    search?: string;
    showSearch?: boolean;
    showCount?: boolean;
    scroll?: boolean;
    extraction?: Record<string, CorpusEpisodeExtraction>;
    onOpenPipeline?: (info: { id: string; runId: string; stepIndex: number | '' }) => void;
    onOpenGraph?: (info: { id: string }) => void;
    stickyTop?: string;
  } = $props();

  // ---- Reading-affordance tunables (Corpus tab only) ------------------------------------------
  // Collapsed episode bodies clamp to this many text lines until "Show more" is clicked. TUNE HERE.
  const CLAMP_LINES = 6;
  // Approx characters-per-line used to decide whether a body is long enough to warrant the clamp
  // toggle — a cheap heuristic so we don't measure every rendered node. Tune alongside CLAMP_LINES.
  const CHARS_PER_LINE = 88;
  const CLAMP_CHARS = CLAMP_LINES * CHARS_PER_LINE;
  // 1.5rem == Tailwind leading-6 line-height; the clamp box height is CLAMP_LINES of those.
  const CLAMP_MAX_HEIGHT = `${CLAMP_LINES * 1.5}rem`;

  // The Corpus tab gets the full reading UI; the compact trace-dialog tab stays a plain transcript.
  const enhanced = $derived(stickyTop !== undefined);
  const searching = $derived(!!search.trim());

  // Markdown rendering is a deliberate mode swap: ON ⇒ render bodies as Markdown; but while a search
  // term is active we always fall back to highlighted plain text (you can't <mark>-highlight inside
  // rendered/sanitized HTML by segment), so matches stay visible. The choice persists across reloads
  // (localStorage) so the reader's preferred mode sticks.
  const MD_PREF_KEY = 'hiro.knowledge.eval.corpusMarkdown';
  function readMarkdownPref(): boolean {
    try {
      return localStorage.getItem(MD_PREF_KEY) === '1';
    } catch {
      return false;
    }
  }
  let markdownMode = $state(readMarkdownPref());
  function toggleMarkdown() {
    markdownMode = !markdownMode;
    try {
      localStorage.setItem(MD_PREF_KEY, markdownMode ? '1' : '0');
    } catch {
      // localStorage unavailable (private mode / SSR) — the toggle still works in-session.
    }
  }
  const renderMarkdown = $derived(markdownMode && !searching);

  // 1-based episode position in the FULL corpus (stable; not the filtered subset), shown in the
  // row header and the index rail. Built once per corpus so the number is the real turn ordinal
  // regardless of search.
  const episodeNo = $derived.by(() => {
    const m = new Map<string, number>();
    episodes.forEach((ep, i) => m.set(ep.id, i + 1));
    return m;
  });

  // ---- Per-episode expand state (clamp override) ----------------------------------------------
  const expanded = new SvelteSet<string>();
  function toggleExpand(id: string) {
    if (expanded.has(id)) expanded.delete(id);
    else expanded.add(id);
  }
  function expandAll() {
    for (const ep of filtered) expanded.add(ep.id);
  }
  function collapseAll() {
    expanded.clear();
  }
  // Clamp candidate = long body. While searching we expand everything (so the highlighted hit is
  // never hidden below the fold), so the clamp only applies when not searching.
  function needsClamp(ep: EvalEpisode): boolean {
    return ep.body.length > CLAMP_CHARS || ep.body.split('\n').length > CLAMP_LINES;
  }
  function isCollapsed(ep: EvalEpisode): boolean {
    return enhanced && !searching && needsClamp(ep) && !expanded.has(ep.id);
  }

  // Reset expand state whenever the corpus changes so a stale set doesn't leak across corpora.
  $effect(() => {
    episodes; // track identity
    expanded.clear();
  });

  // ---- Extraction filters (Corpus tab only; gated on `extraction` being supplied) ----
  // "Only without extraction" = traced episodes that produced 0 entities AND 0 facts. The two range
  // sliders bound entity/fact counts. All filters (checkbox + ranges + search) AND together; an
  // episode with no trace is hidden whenever any count filter is active (it has no counts to match).
  let noExtractionOnly = $state(false);
  let entRange = $state<[number, number] | null>(null);
  let factRange = $state<[number, number] | null>(null);

  const extractionValues = $derived(extraction ? Object.values(extraction) : []);
  const hasExtraction = $derived(extractionValues.length > 0);
  const maxEnt = $derived(extractionValues.reduce((m, x) => Math.max(m, x.entity_count), 0));
  const maxFact = $derived(extractionValues.reduce((m, x) => Math.max(m, x.fact_count), 0));

  // Reset the filters whenever the corpus (extraction map) changes, so switching corpus doesn't
  // carry a stale range/checkbox into a different turn set.
  $effect(() => {
    extraction; // track the map identity
    noExtractionOnly = false;
    entRange = null;
    factRange = null;
  });

  const entActive = $derived(!!entRange && (entRange[0] > 0 || entRange[1] < maxEnt));
  const factActive = $derived(!!factRange && (factRange[0] > 0 || factRange[1] < maxFact));
  const countFilterActive = $derived(noExtractionOnly || entActive || factActive);

  const filtered = $derived.by(() => {
    const term = search.trim().toLowerCase();
    let list = term
      ? episodes.filter((ep) => `${ep.body} ${ep.speaker} ${ep.id}`.toLowerCase().includes(term))
      : episodes;
    if (extraction && countFilterActive) {
      const [eLo, eHi] = entRange ?? [0, maxEnt];
      const [fLo, fHi] = factRange ?? [0, maxFact];
      list = list.filter((ep) => {
        const x = extraction[ep.id];
        if (!x) return false; // no trace ⇒ no counts to satisfy a count filter
        if (noExtractionOnly && !(x.entity_count === 0 && x.fact_count === 0)) return false;
        if (entActive && (x.entity_count < eLo || x.entity_count > eHi)) return false;
        if (factActive && (x.fact_count < fLo || x.fact_count > fHi)) return false;
        return true;
      });
    }
    return list;
  });

  function resetFilters() {
    noExtractionOnly = false;
    entRange = null;
    factRange = null;
  }

  // ---- Episode index rail + position readout (Corpus tab only) --------------------------------
  // Card elements registered by id so the rail can scroll one into view and the IntersectionObserver
  // can report which is at the top of the viewport.
  const nodes = new Map<string, HTMLElement>();
  function register(node: HTMLElement, _id: string) {
    nodes.set(_id, node);
    return {
      destroy() {
        nodes.delete(_id);
      }
    };
  }

  let railEl = $state<HTMLElement | undefined>(undefined);
  // The episode currently near the top of the viewport — drives the position readout + rail accent.
  let currentId = $state<string | null>(null);
  const currentNo = $derived(
    episodeNo.get(currentId ?? filtered[0]?.id ?? '') ?? null
  );

  function jumpTo(id: string) {
    // Reflect the click immediately so the rail highlight + readout match the clicked number
    // (the scroll handler below then keeps it correct as the smooth scroll settles).
    currentId = id;
    nodes.get(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // Current episode = the LAST one whose top has crossed the sticky anchor line (the rail's own
  // top, where episodes land via scroll-margin-top). Deterministic by scroll position — so clicking
  // rail N lands N at the anchor and selects N exactly (the old IntersectionObserver band could pick
  // a short episode 1–2 rows above). Page owns the scroll here, so we listen on window.
  function recomputeCurrent() {
    if (!enhanced) return;
    // +12px tolerance so an episode parked at scroll-margin-top counts as "at" the line, not below.
    const anchor = (railEl?.getBoundingClientRect().top ?? 0) + 12;
    let cur: string | null = filtered[0]?.id ?? null;
    for (const ep of filtered) {
      const n = nodes.get(ep.id);
      if (!n) continue;
      if (n.getBoundingClientRect().top <= anchor) cur = ep.id;
      else break; // first episode still below the line → everything after is too
    }
    currentId = cur;
  }
  $effect(() => {
    if (!enhanced) return;
    filtered; // recompute when the filtered set changes
    recomputeCurrent();
    const onScroll = () => recomputeCurrent();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
    };
  });

  // Keep the active rail item scrolled into view within the rail's own scroll box.
  $effect(() => {
    if (!enhanced || !railEl || !currentId) return;
    const btn = railEl.querySelector(`[data-rail="${CSS.escape(currentId)}"]`);
    btn?.scrollIntoView({ block: 'nearest' });
  });

  // Episode timestamps are dated turns; show the date only (time-of-day is noise here).
  function fmtDate(iso: string): string {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toISOString().slice(0, 10);
  }
</script>

<!-- Shared filter controls (checkbox + the two range sliders + reset) — rendered inside the sticky
     toolbar (Corpus tab) or the inline bar (legacy), so both layouts stay in sync. -->
{#snippet filterControls()}
  <label class="flex items-center gap-1.5 font-sans text-xs select-none">
    <input type="checkbox" bind:checked={noExtractionOnly} class="size-3.5 rounded border" />
    Only without extraction
  </label>
  {#if maxEnt > 0}
    <div class="flex items-center gap-2">
      <span class="font-sans text-xs font-medium text-emerald-600 dark:text-emerald-400">Entities</span>
      <div class="w-28">
        <GraphRangeSlider
          min={0}
          max={maxEnt}
          step={1}
          value={entRange ?? [0, maxEnt]}
          format={(v) => String(v)}
          onChange={(lo, hi) => (entRange = [lo, hi])}
        />
      </div>
    </div>
  {/if}
  {#if maxFact > 0}
    <div class="flex items-center gap-2">
      <span class="font-sans text-xs font-medium text-violet-600 dark:text-violet-400">Facts</span>
      <div class="w-28">
        <GraphRangeSlider
          min={0}
          max={maxFact}
          step={1}
          value={factRange ?? [0, maxFact]}
          format={(v) => String(v)}
          onChange={(lo, hi) => (factRange = [lo, hi])}
        />
      </div>
    </div>
  {/if}
  {#if countFilterActive}
    <button
      type="button"
      class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted"
      onclick={resetFilters}
    >
      Reset filters
    </button>
  {/if}
{/snippet}

<!-- The episode list — shared by both layouts (the enhanced rail+list and the legacy single box).
     `register`/`data-ep-id` feed the index rail + position observer (no-ops when not enhanced). -->
{#snippet episodeRows()}
  {#if filtered.length === 0}
    <p class="px-3 py-2 font-sans text-xs text-muted-foreground">
      {#if search.trim() || countFilterActive}No episodes match the current filters.{:else}No episodes.{/if}
    </p>
  {:else}
    {#each filtered as ep (ep.id)}
      <!-- Zebra striping is a clearer row separator than a faint hairline, with zero extra
           vertical space (just a tint on alternate rows). -->
      <div
        use:register={ep.id}
        data-ep-id={ep.id}
        class="border-t border-border {compact ? 'px-3 py-1.5' : 'px-3 py-2'} first:border-t-0 odd:bg-muted/40"
        style={enhanced ? `scroll-margin-top: calc(${stickyTop} + 3.5rem);` : undefined}
      >
        <!-- Header band: full-bleed muted strip (non-compact) so each episode's metadata reads as a
             clear band against the body in both light and dark themes. -->
        <div
          class={compact
            ? 'flex flex-wrap items-center gap-2 font-sans text-[11px] text-muted-foreground'
            : '-mx-3 -mt-2 mb-2 flex flex-wrap items-center gap-2 border-b border-border bg-muted px-3 py-1.5 font-sans text-[11px] text-muted-foreground'}
        >
          <!-- Episode # (1-based corpus position) — larger, leading the header — then the speaker. -->
          <span class="font-mono text-sm font-semibold text-foreground tabular-nums">#{episodeNo.get(ep.id)}</span>
          {#if ep.speaker}<Badge variant="outline" class="font-sans normal-case">{ep.speaker}</Badge>{/if}
          <span class="font-mono">{ep.id}</span>
          <span class="font-mono tabular-nums">{fmtDate(ep.timestamp)}</span>
          <!-- Approx text size (≈ chars/4) — a cheap "how big is this turn" cue. -->
          <span class="font-mono tabular-nums text-muted-foreground/70" title="Approximate tokens (≈ chars / 4)">~{fmtCompact(approxTokens(ep.body))} tok</span>
          {#if extraction}
            {@const x = extraction[ep.id]}
            {#if x === undefined}
              <!-- No ingest trace for this episode (corpus ingested with tracing off, or not yet
                   remembered) — say so rather than implying "extracted nothing". -->
              <span class="font-sans text-muted-foreground/70">no trace</span>
            {:else if x.entity_count === 0 && x.fact_count === 0}
              <Badge variant="outline" class="border-amber-400/60 font-sans normal-case text-amber-600 dark:text-amber-400">no extraction</Badge>
            {:else}
              <!-- Entities/facts in distinct accent colors so the two counts read apart at a glance. -->
              <span class="font-mono tabular-nums">
                <span class="font-medium text-emerald-600 dark:text-emerald-400">{x.entity_count} entities</span>
                <span class="text-muted-foreground/60"> · </span>
                <span class="font-medium text-violet-600 dark:text-violet-400">{x.fact_count} facts</span>
              </span>
            {/if}
            {#if x !== undefined && x.run_id && onOpenPipeline}
              <!-- Pipeline button (before graph): open the ingestion pipeline trace for this episode. -->
              <button
                type="button"
                class="inline-flex items-center gap-1 rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 font-sans text-[10px] font-medium text-emerald-700 transition-colors hover:bg-emerald-500/20 dark:text-emerald-400"
                title="Open the ingestion pipeline trace for this episode"
                onclick={() => onOpenPipeline?.({ id: ep.id, runId: x.run_id, stepIndex: x.step_index })}
              >
                <Microscope size={11} aria-hidden="true" />
                pipeline
              </button>
            {/if}
            {#if onOpenGraph}
              <!-- Graph button (after pipeline): open the Knowledge Graph filtered to this
                   episode's entities/facts (its group + chunk_id). -->
              <button
                type="button"
                class="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/10 px-2 py-0.5 font-sans text-[10px] font-medium text-primary transition-colors hover:bg-primary/20"
                title="Open this episode in the Knowledge Graph (filtered to its entities/facts)"
                onclick={() => onOpenGraph?.({ id: ep.id })}
              >
                <Share2 size={11} aria-hidden="true" />
                graph
              </button>
            {/if}
          {/if}
        </div>
        <!-- Body — clamped to CLAMP_LINES until expanded (Corpus tab). Markdown mode swaps the plain
             highlighted text for rendered Markdown; search always forces plain text so hits show. -->
        <div style={isCollapsed(ep) ? `max-height: ${CLAMP_MAX_HEIGHT}; overflow: hidden;` : undefined}>
          {#if renderMarkdown}
            <MarkdownPreview markdown={ep.body} compact class="text-[13px]" />
          {:else}
            <p class="whitespace-pre-wrap font-sans text-[13px] leading-6">{#each highlightSegments(ep.body, search) as seg}{#if seg.hit}<mark class="rounded bg-amber-200 text-inherit dark:bg-amber-500/40">{seg.text}</mark>{:else}{seg.text}{/if}{/each}</p>
          {/if}
        </div>
        {#if enhanced && !searching && needsClamp(ep)}
          <button
            type="button"
            class="mt-1 font-sans text-xs font-medium text-primary hover:underline"
            onclick={() => toggleExpand(ep.id)}
          >
            {expanded.has(ep.id) ? 'Show less' : 'Show more'}
          </button>
        {/if}
      </div>
    {/each}
  {/if}
{/snippet}

<div class="grid gap-2">
  {#if stickyTop !== undefined}
    <!-- Corpus tab: search + extraction filters + reading controls on ONE sticky line, pinned under
         the page header/sub-tabs. The corpus stats line lives in the panel and scrolls away. -->
    <div
      class="sticky z-10 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border bg-background px-3 py-2 backdrop-blur supports-[backdrop-filter]:bg-background/90"
      style="top: {stickyTop};"
    >
      <div class="relative">
        <input
          class="h-7 w-56 rounded-md border bg-background pl-2 pr-7 font-sans text-xs"
          placeholder="Search episodes…"
          bind:value={search}
        />
        {#if search.trim()}
          <button
            type="button"
            class="absolute inset-y-0 right-1.5 my-auto flex size-4 items-center justify-center rounded text-muted-foreground hover:text-foreground"
            onclick={() => (search = '')}
            title="Clear search"
            aria-label="Clear search"
          >
            <X size={12} aria-hidden="true" />
          </button>
        {/if}
      </div>
      {#if hasExtraction}{@render filterControls()}{/if}
      <!-- Reading controls: Markdown mode swap + bulk expand/collapse. -->
      <span class="mx-0.5 h-4 w-px bg-border" aria-hidden="true"></span>
      <button
        type="button"
        class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 {markdownMode ? 'border-primary/40 bg-primary/10 font-medium text-primary' : ''}"
        aria-pressed={markdownMode}
        disabled={searching}
        title={searching
          ? 'Plain text is shown while searching so matches stay highlighted'
          : 'Render episode bodies as Markdown'}
        onclick={toggleMarkdown}
      >
        Markdown
      </button>
      {#if !searching}
        <button
          type="button"
          class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted"
          onclick={expandAll}
        >
          Expand all
        </button>
        <button
          type="button"
          class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted"
          onclick={collapseAll}
        >
          Collapse all
        </button>
      {/if}
      <!-- Right side: filter match count (when filtering) + current-position readout. -->
      <span class="ml-auto font-mono text-[11px] tabular-nums text-muted-foreground">{#if searching || countFilterActive}{filtered.length}/{episodes.length}{/if}{#if currentNo}{#if searching || countFilterActive}<span class="text-muted-foreground/60"> · </span>{/if}<span class="text-muted-foreground/60">#</span>{currentNo}/{episodes.length}{/if}</span>
    </div>
    <!-- Index rail (left) + transcript (right). Page owns the scroll; the rail is sticky with its
         own overflow so it stays reachable through a long corpus. -->
    <div class="flex items-start gap-3">
      <nav
        bind:this={railEl}
        aria-label="Episode index"
        class="sticky max-h-[70vh] w-12 shrink-0 overflow-y-auto rounded-md border bg-muted/20 p-1"
        style="top: calc({stickyTop} + 3.25rem);"
      >
        {#each filtered as ep (ep.id)}
          <button
            type="button"
            data-rail={ep.id}
            class="block w-full cursor-pointer rounded px-1 py-0.5 text-right font-mono text-[11px] tabular-nums transition-colors hover:bg-primary/10 hover:font-semibold hover:text-primary {currentId === ep.id ? 'bg-primary/15 font-semibold text-primary' : 'text-muted-foreground'}"
            title={`${ep.speaker || 'episode'} · ${fmtDate(ep.timestamp)}`}
            onclick={() => jumpTo(ep.id)}
          >
            {episodeNo.get(ep.id)}
          </button>
        {/each}
      </nav>
      <div class="min-w-0 flex-1 rounded-md border">
        {@render episodeRows()}
      </div>
    </div>
  {:else}
    {#if showSearch}
      <div class="flex flex-wrap items-center gap-2">
        <input
          class="h-7 w-56 rounded-md border bg-background px-2 font-sans text-xs"
          placeholder="Search episodes…"
          bind:value={search}
        />
        {#if search.trim()}
          <span class="font-sans text-xs text-muted-foreground">
            {filtered.length} of {episodes.length} match
          </span>
          <button
            type="button"
            class="rounded border px-2 py-0.5 font-sans text-xs hover:bg-muted"
            onclick={() => (search = '')}
          >
            Clear
          </button>
        {/if}
      </div>
    {/if}
    {#if showCount}
      <span class="font-sans text-xs text-muted-foreground">
        {#if search.trim()}{filtered.length} of {episodes.length} match{:else}{episodes.length} episodes{/if}
      </span>
    {/if}
    {#if hasExtraction}
      <div class="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border bg-muted/30 px-3 py-2">
        {@render filterControls()}
      </div>
    {/if}
    <!-- Compact (trace-dialog tab) or scroll=false: no inner scroll — an outer region owns the
         scroll, so there's a single scrollbar instead of a nested one. -->
    <div class="rounded-md border {compact || !scroll ? '' : 'max-h-96 overflow-y-auto'}">
      {@render episodeRows()}
    </div>
  {/if}
</div>
