<!--
  L3 — live activity terminal for the Eval Batch.

  A scrollable, monospace, auto-following feed that turns the structured run
  state (setup activity trail + per-question rows + terminal status) into
  human-readable lines: "Episode 3/35 → Qdrant · …", "Graph extraction 12/35…",
  "Q 2/5 [✗→✓ Δ+3] …". This is the feedback that was missing — the run no longer
  looks frozen for minutes during the (slow, LLM-bound) graph build.

  Derives its lines from props (no transport here); the controller owns the SSE
  subscription and the server-state replay. Virtualized log feed — exempt from
  the shared table primitives per the admin Svelte conventions.
-->
<script lang="ts">
  import { ChevronRight } from '@lucide/svelte';
  import type {
    EvalQuestionPayload,
    EvalSetupProgressPayload
  } from '$lib/features/knowledge/shared/knowledge-events';
  import type { EvalRow, EvalStatus } from '$lib/features/knowledge/state/knowledge-eval.svelte';

  interface Props {
    setupEvents: EvalSetupProgressPayload[];
    rows: EvalRow[];
    status: EvalStatus;
    totalQuestions: number;
    summaryGate?: 'proceed' | 'pivot' | 'n/a' | null;
    summaryElapsedMs?: number | null;
    failureMessage?: string | null;
  }

  let {
    setupEvents,
    rows,
    status,
    totalQuestions,
    summaryGate = null,
    summaryElapsedMs = null,
    failureMessage = null
  }: Props = $props();

  type Tone = 'muted' | 'info' | 'success' | 'warn' | 'error';
  type Line = { text: string; tone: Tone };

  function setupLine(e: EvalSetupProgressPayload): Line {
    if (e.index && e.total) {
      // Per-episode progress.
      if (e.phase === 'build_graph' || e.phase === 'graph_build') {
        return { tone: 'info', text: `  graph extraction ${e.index}/${e.total}…` };
      }
      const head = `  episode ${e.index}/${e.total} → Qdrant`;
      const title = e.title ? ` · ${e.title}` : '';
      const snippet = e.snippet ? ` — ${e.snippet}` : '';
      return { tone: 'muted', text: `${head}${title}${snippet}` };
    }
    // Phase-start lines.
    if (e.phase === 'ingest_synthetic')
      return {
        tone: 'info',
        text: `▶ ingesting synthetic corpus${e.file_count ? ` (${e.file_count} files)` : ''}…`
      };
    if (e.phase === 'ingest_adam')
      return {
        tone: 'info',
        text: `▶ ingesting Adam corpus${e.episode_count ? ` (${e.episode_count} episodes)` : ''}…`
      };
    if (e.phase === 'build_graph' || e.phase === 'graph_build')
      return {
        tone: 'info',
        text: `▶ building knowledge graph${e.episode_count ? ` (${e.episode_count} episodes)` : ''}…`
      };
    return { tone: 'info', text: `▶ ${e.phase}…` };
  }

  function questionLines(r: EvalRow): Line[] {
    // Compact per-leg marks, e.g. "flat:✗ graphiti:✓"; only the run's legs.
    const modes = Object.keys(r.legs);
    const marks = modes.map((m) => `${m}:${r.legs[m].mark}`).join(' ');
    const delta = r.delta && r.delta !== '0' ? ` Δ${r.delta}` : '';
    const won = r.delta.startsWith('+');
    const lost = r.delta.startsWith('-');
    const head: Line = {
      tone: won ? 'success' : lost ? 'warn' : 'muted',
      text: `Q ${r.index + 1}/${r.total} [${marks}${delta}]${r.requires_graph ? ' ▲' : ''} ${r.question}`
    };
    // Prefer the graph leg's preview (graphiti), else flat, else any leg.
    const ans =
      r.legs.graphiti?.answer_preview ||
      r.legs.flat?.answer_preview ||
      (modes.length ? r.legs[modes[0]].answer_preview : '');
    const lines = [head];
    if (ans) lines.push({ tone: 'muted', text: `    ↳ ${ans}` });
    return lines;
  }

  const lines = $derived.by<Line[]>(() => {
    const out: Line[] = [];
    for (const e of setupEvents) out.push(setupLine(e));
    for (const r of [...rows].sort((a, b) => a.index - b.index)) out.push(...questionLines(r));
    if (status === 'running' && rows.length < totalQuestions) {
      out.push({
        tone: 'info',
        text: `… ${rows.length}/${totalQuestions} questions done — running…`
      });
    } else if (status === 'starting') {
      out.push({ tone: 'info', text: '… preparing…' });
    } else if (status === 'completed' && summaryGate) {
      const ms = summaryElapsedMs ? ` · ${summaryElapsedMs}ms` : '';
      if (summaryGate === 'proceed') out.push({ tone: 'success', text: `✅ PROCEED${ms}` });
      else if (summaryGate === 'pivot') out.push({ tone: 'warn', text: `❌ PIVOT${ms}` });
      else out.push({ tone: 'info', text: `ℹ️ done${ms}` });
    } else if (status === 'cancelled') {
      out.push({ tone: 'warn', text: '🛑 run cancelled' });
    } else if (status === 'failed') {
      out.push({ tone: 'error', text: `❌ failed${failureMessage ? `: ${failureMessage}` : ''}` });
    }
    return out;
  });

  const toneClass: Record<Tone, string> = {
    muted: 'text-muted-foreground',
    info: 'text-sky-500 dark:text-sky-400',
    success: 'text-emerald-600 dark:text-emerald-400',
    warn: 'text-amber-600 dark:text-amber-400',
    error: 'text-destructive'
  };

  // Auto-follow: stick to the bottom as lines arrive, but back off the moment the
  // user scrolls up to read history (re-engage when they return to the bottom).
  let scroller = $state<HTMLDivElement | null>(null);
  let pinned = $state(true);
  // Collapse toggle for the activity feed (header click). Body stays mounted
  // (hidden) so scroll position / auto-follow survive a collapse.
  let collapsed = $state(false);

  function onScroll() {
    if (!scroller) return;
    const slack = 24; // px tolerance so "near bottom" still counts as pinned
    pinned = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - slack;
  }

  $effect(() => {
    // Re-run when the line count changes (or on re-expand); only follow if the
    // user is pinned and the feed is visible.
    void lines.length;
    void collapsed;
    if (!collapsed && pinned && scroller) scroller.scrollTop = scroller.scrollHeight;
  });
</script>

<div class="grid gap-1">
  <div class="flex items-center gap-2 px-0.5 font-sans text-xs text-muted-foreground">
    <button
      type="button"
      class="flex items-center gap-1 font-semibold uppercase tracking-wide hover:text-foreground"
      aria-expanded={!collapsed}
      aria-controls="knowledge-eval-activity-body"
      onclick={() => (collapsed = !collapsed)}
    >
      <ChevronRight
        size={13}
        class="shrink-0 transition-transform {collapsed ? '' : 'rotate-90'}"
        aria-hidden="true"
      />
      Activity
    </button>
    <span>· {lines.length} lines</span>
    {#if !pinned && !collapsed}
      <button
        type="button"
        class="ml-auto rounded border px-2 py-0.5 hover:bg-muted"
        onclick={() => {
          pinned = true;
          if (scroller) scroller.scrollTop = scroller.scrollHeight;
        }}
      >
        Jump to latest
      </button>
    {/if}
  </div>
  <div
    id="knowledge-eval-activity-body"
    bind:this={scroller}
    onscroll={onScroll}
    hidden={collapsed}
    class="h-56 overflow-y-auto rounded-md border bg-slate-950 px-3 py-2 font-mono text-xs leading-5 text-slate-200"
    role="log"
    aria-live="polite"
    aria-label="Eval run activity log"
  >
    {#if lines.length === 0}
      <p class="text-slate-500">No activity yet — press “Run eval”.</p>
    {:else}
      {#each lines as line, i (i)}
        <div class="whitespace-pre-wrap break-words {toneClass[line.tone]}">{line.text}</div>
      {/each}
    {/if}
  </div>
</div>
