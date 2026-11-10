<script lang="ts">
  /**
   * How the runtime would pick this character's chat model and voice (Phase 7b step 5: from its AI /
   * voice profiles in order, then Hiro's chat profile / Hiro's voice). `full` in the view panel; one
   * collapsible column per edit section.
   */
  import { ChevronRight, CircleCheck } from '@lucide/svelte';
  import type {
    CharacterResolvedAiRow,
    CharacterResolvedPayload,
    CharacterResolvedVoiceRow
  } from '$lib/api/characters';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import {
    appliedTuningLine,
    llmCollapsedSummary,
    resolvedRowDotClass,
    resolvedRowTooltip,
    voiceCollapsedSummary
  } from '$lib/features/characters/shared/characters-resolved-pure';
  import { resolvedDetailsId } from '$lib/features/characters/shared/characters-a11y';
  import { cn } from '$lib/utils';

  let {
    resolved,
    error,
    staleHint = false,
    /** ``full``: view-mode panel with chat + voice. ``llm`` / ``voice``: one column for edit sections. */
    segment = 'full'
  }: {
    resolved: CharacterResolvedPayload | null;
    error: string | null;
    staleHint?: boolean;
    segment?: 'full' | 'llm' | 'voice';
  } = $props();

  /** Edit-section panels start collapsed so the row shows only the effective model until expanded. */
  let expanded = $state(false);

  type AppliedPanelArgs = {
    title: string;
    fromCharacter: boolean;
    hiroBadgeTitle: string;
    detailLines: string[];
    characterFooter: string;
    hiroFooter: string;
  };

  /** A candidate row (AI or voice profile): its name (or id when missing), model and voice. */
  type CandidateRow = (CharacterResolvedAiRow | CharacterResolvedVoiceRow) & { voice?: string | null };

  /** The applied voice panel's middle lines: the voice and the style it speaks in. */
  function voiceDetailLines(applied: { model: string; voice: string; style: string }): string[] {
    const lines = [`${applied.model} · voice “${applied.voice}”`];
    if (applied.style?.trim()) lines.push(`Style “${applied.style.trim()}”`);
    return lines;
  }

  function toggleExpanded() {
    if (segment === 'full') return;
    expanded = !expanded;
  }
</script>

<div class="grid gap-4 rounded-lg border border-dashed border-primary/25 bg-muted/15 p-4">
  {#snippet resolvedCandidateRow(row: CandidateRow, highlight: boolean, origin: 'character' | 'hiro')}
    <li
      class={cn(
        'flex w-full flex-col gap-1.5 rounded-md border bg-background/60 px-3 py-2 text-sm',
        highlight ? 'ring-1 ring-primary/50' : ''
      )}
    >
      <div class="flex items-start justify-between gap-2">
        <span class="flex min-w-0 flex-wrap items-center gap-2">
          <span
            class={cn(
              'size-2 shrink-0 rounded-full shadow-sm ring-2 ring-background',
              resolvedRowDotClass(row.status)
            )}
            title={resolvedRowTooltip(row.status)}
            aria-label={resolvedRowTooltip(row.status)}
          ></span>
          <span class="font-sans text-sm font-semibold">{row.label ?? row.profile_id}</span>
        </span>
        {#if origin === 'character'}
          <span
            class="shrink-0 rounded-md border border-emerald-600/35 bg-emerald-500/[0.12] px-2 py-0.5 font-sans text-[10px] font-bold uppercase tracking-wide text-emerald-900 dark:text-emerald-100"
            title="From this character’s list (ordered)."
          >
            Character
          </span>
        {:else}
          <span
            class="shrink-0 rounded-md border border-slate-500/40 bg-slate-500/[0.12] px-2 py-0.5 font-sans text-[10px] font-bold uppercase tracking-wide text-slate-800 dark:text-slate-100"
            title="Hiro's own (Settings → General) — used when no profile of the character can."
          >
            Hiro
          </span>
        {/if}
      </div>
      {#if row.model}
        <code class="w-fit rounded bg-muted px-1.5 py-0.5 font-mono text-xs"
          >{row.model}{row.voice ? ` · ${row.voice}` : ''}</code
        >
      {/if}
      {#if row.status !== 'available'}
        <span class="text-xs text-amber-800 dark:text-amber-200">{resolvedRowTooltip(row.status)}</span>
      {/if}
    </li>
  {/snippet}

  <!-- Single applied panel shared by the LLM and TTS columns; only the labels/footers differ. -->
  {#snippet appliedPanel(args: AppliedPanelArgs)}
    <div
      class="flex max-w-lg gap-3 rounded-md border border-emerald-600/25 bg-emerald-500/[0.06] p-3 text-sm dark:bg-emerald-950/25"
    >
      <span class="mt-0.5 shrink-0 text-emerald-600 dark:text-emerald-400" title="Selected">
        <CircleCheck size={22} strokeWidth={2.25} aria-hidden="true" />
      </span>
      <span class="sr-only">Selected</span>
      <div class="min-w-0 flex-1 space-y-1">
        <div class="flex flex-wrap items-center gap-2">
          <span class="break-all font-sans text-sm font-semibold">{args.title}</span>
          {#if args.fromCharacter}
            <span
              class="rounded-md border border-emerald-600/35 bg-emerald-500/[0.15] px-2 py-0.5 font-sans text-[10px] font-bold uppercase tracking-wide text-emerald-900 dark:text-emerald-100"
              title="Comes from this character’s list."
            >
              Character
            </span>
          {:else}
            <span
              class="rounded-md border border-slate-500/40 bg-slate-500/[0.12] px-2 py-0.5 font-sans text-[10px] font-bold uppercase tracking-wide text-slate-800 dark:text-slate-100"
              title={args.hiroBadgeTitle}
            >
              Hiro
            </span>
          {/if}
        </div>
        {#each args.detailLines as line (line)}
          <p class="text-xs text-muted-foreground">{line}</p>
        {/each}
        <p class="text-xs leading-snug text-muted-foreground">
          {args.fromCharacter ? args.characterFooter : args.hiroFooter}
        </p>
      </div>
    </div>
  {/snippet}

  <!-- LLM resolution column (candidate lists + applied). ``label`` is set only in the full view panel. -->
  {#snippet llmColumn(payload: CharacterResolvedPayload, label: string)}
    <div class="grid max-w-lg gap-2">
      {#if label}
        <span class="font-sans text-xs font-semibold uppercase text-muted-foreground">{label}</span>
      {/if}
      {#if payload.ai_rows.length === 0}
        <p class="text-sm text-muted-foreground">No AI profiles — Hiro's chat profile applies.</p>
      {:else}
        <span class="font-sans text-[10px] font-bold uppercase tracking-wide text-muted-foreground"
          >Character list</span
        >
        <ul class="space-y-2">
          {#each payload.ai_rows as row (row.profile_id)}
            {@render resolvedCandidateRow(
              row,
              payload.ai_applied?.source === 'character' && payload.ai_applied.profile_id === row.profile_id,
              'character'
            )}
          {/each}
        </ul>
      {/if}
      {#if payload.ai_workspace_row}
        <span class="mt-1 font-sans text-[10px] font-bold uppercase tracking-wide text-muted-foreground"
          >Hiro's chat profile</span
        >
        <ul class="space-y-2">
          {@render resolvedCandidateRow(
            payload.ai_workspace_row,
            payload.ai_applied?.source === 'workspace_fallback' &&
              payload.ai_applied.profile_id === payload.ai_workspace_row.profile_id,
            'hiro'
          )}
        </ul>
      {/if}
      {#if payload.ai_applied}
        {@render appliedPanel({
          title: payload.ai_applied.profile_label || payload.ai_applied.model_id,
          fromCharacter: payload.ai_applied.source === 'character',
          hiroBadgeTitle: "Hiro's chat profile — used when no profile of the character can answer.",
          detailLines: [payload.ai_applied.model_id, appliedTuningLine(payload.ai_applied)],
          characterFooter: 'From this character’s list (the first that can answer, or its fallback).',
          hiroFooter: "Hiro's chat profile — no profile in the character's list can answer, or the list is empty."
        })}
      {:else}
        <p class="text-sm text-destructive">
          No chat model resolved. Check the profiles' keys, and Hiro's chat profile in Settings → General.
        </p>
      {/if}
    </div>
  {/snippet}

  <!-- TTS resolution column (candidate lists + applied). ``label`` is set only in the full view panel. -->
  {#snippet voiceColumn(payload: CharacterResolvedPayload, label: string)}
    <div class="grid max-w-lg gap-2">
      {#if label}
        <span class="font-sans text-xs font-semibold uppercase text-muted-foreground">{label}</span>
      {/if}
      {#if payload.voice_disabled}
        <p class="text-sm text-muted-foreground">
          Voice replies are disabled in workspace settings — nothing is spoken for agent replies.
        </p>
      {:else if payload.voice_rows.length === 0}
        <p class="text-sm text-muted-foreground">No voice profiles — Hiro's voice applies.</p>
      {:else}
        <span class="font-sans text-[10px] font-bold uppercase tracking-wide text-muted-foreground"
          >Character list</span
        >
        <ul class="space-y-2">
          {#each payload.voice_rows as row (row.profile_id)}
            {@render resolvedCandidateRow(
              row,
              payload.voice_applied?.source === 'character' && payload.voice_applied.profile_id === row.profile_id,
              'character'
            )}
          {/each}
        </ul>
      {/if}
      {#if payload.voice_workspace_row}
        <span class="mt-1 font-sans text-[10px] font-bold uppercase tracking-wide text-muted-foreground"
          >Hiro's voice</span
        >
        <ul class="space-y-2">
          {@render resolvedCandidateRow(
            payload.voice_workspace_row,
            payload.voice_applied?.source === 'hiro' &&
              payload.voice_applied.profile_id === payload.voice_workspace_row.profile_id,
            'hiro'
          )}
        </ul>
      {/if}
      {#if !payload.voice_disabled}
        {#if payload.voice_applied}
          {@render appliedPanel({
            title: payload.voice_applied.label,
            fromCharacter: payload.voice_applied.source === 'character',
            hiroBadgeTitle: "Hiro's voice — used when no voice profile of the character has a key.",
            detailLines: voiceDetailLines(payload.voice_applied),
            characterFooter: 'From this character’s list (the first whose provider has a key).',
            hiroFooter: "Hiro's voice — no voice profile in the character's list has a key, or the list is empty."
          })}
        {:else}
          <p class="text-sm text-destructive">
            No voice resolved. Pick Hiro's voice in Settings → General, and set the speech provider's key.
          </p>
        {/if}
      {/if}
    </div>
  {/snippet}

  {#if segment === 'full'}
    <div>
      <span class="font-sans text-xs font-extrabold uppercase text-primary">Runtime</span>
      <h4 class="mt-1 text-base font-semibold">Resolved configuration</h4>
      <p class="mt-1 text-sm text-muted-foreground">
        Which AI profile and voice profile HiroServer would use for this character, given the keys in this
        workspace. Order matches the character's lists; the first usable one wins, then Hiro's own.
      </p>
    </div>
  {:else}
    <!-- Collapsed row shows section label + effective model only; expand for candidate lists + applied panel. -->
    <button
      type="button"
      class="flex w-full min-w-0 items-center gap-2 rounded-md py-1 text-left outline-none ring-offset-background transition hover:bg-muted/30 focus-visible:ring-2 focus-visible:ring-ring"
      aria-expanded={expanded}
      aria-controls={resolvedDetailsId(segment)}
      onclick={toggleExpanded}
    >
      <ChevronRight
        size={18}
        class={cn(
          'shrink-0 text-muted-foreground transition-transform duration-150',
          expanded && 'rotate-90'
        )}
        aria-hidden="true"
      />
      <span class="shrink-0 font-sans text-xs font-semibold uppercase text-muted-foreground">
        {#if segment === 'llm'}
          Chat resolution (saved)
        {:else}
          Voice resolution (saved)
        {/if}
      </span>
      <span
        class={cn(
          'min-w-0 flex-1 truncate font-sans text-sm',
          error ? 'text-destructive' : 'text-foreground'
        )}
      >
        {#if error}
          {error}
        {:else if !resolved}
          <span class="font-sans text-sm text-muted-foreground" role="status" aria-live="polite">
            Loading resolved configuration…
          </span>
        {:else if segment === 'llm'}
          {llmCollapsedSummary(resolved)}
        {:else}
          {voiceCollapsedSummary(resolved)}
        {/if}
      </span>
    </button>
  {/if}

  {#if staleHint}
    <p class="rounded-md bg-amber-500/10 px-3 py-2 font-sans text-xs text-amber-800 dark:text-amber-200">
      Lists above are unsaved. This panel still reflects the last saved character — save to refresh
      resolution.
    </p>
  {/if}

  {#if segment === 'full'}
    {#if error}
      <p class="text-sm text-destructive">{error}</p>
    {:else if !resolved}
      <InlineLoading label="Loading resolved configuration…" />
    {:else}
      <div class="grid gap-5 md:grid-cols-2 md:items-start">
        {@render llmColumn(resolved, 'Chat (AI profile)')}
        {@render voiceColumn(resolved, 'Voice (voice profile)')}
      </div>
    {/if}
  {:else}
    <!-- Region stays mounted (button's aria-controls target); ``hidden`` utility toggles display.
         Class swap, not the bare [hidden] attr, because ``display:grid`` would override it. -->
    <div
      id={resolvedDetailsId(segment)}
      class={cn('border-t border-border/40 pt-3', expanded ? 'grid gap-3' : 'hidden')}
    >
      <p class="text-xs text-muted-foreground">
        {#if segment === 'llm'}
          The AI profile chosen from the character's list, else Hiro's chat profile.
        {:else}
          The voice profile chosen from the character's list, else Hiro's voice.
        {/if}
      </p>
      {#if error}
        <p class="text-sm text-destructive">{error}</p>
      {:else if !resolved}
        <InlineLoading label="Loading resolved configuration…" />
      {:else if segment === 'llm'}
        {@render llmColumn(resolved, '')}
      {:else}
        {@render voiceColumn(resolved, '')}
      {/if}
    </div>
  {/if}
</div>
