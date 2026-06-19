<script lang="ts">
  import { ChevronRight, CircleCheck } from '@lucide/svelte';
  import type { CharacterResolvedPayload, CharacterResolvedRow } from '$lib/api/characters';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import {
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
    modelId: string;
    source: 'character' | 'workspace_fallback';
    workspaceBadgeTitle: string;
    detailLines: string[];
    characterFooter: string;
    workspaceFooter: string;
  };

  /** Build the optional middle line(s) of the applied TTS panel, mirroring the saved synthesis. */
  function voiceDetailLines(synthesis: { voice: string; instructions: string }): string[] {
    const voice = synthesis.voice;
    const instr = synthesis.instructions?.trim();
    if (voice) {
      return [instr ? `Voice “${voice}” · instructions “${instr}”` : `Voice “${voice}”`];
    }
    if (instr) return [`Instructions “${instr}”`];
    return [];
  }

  function toggleExpanded() {
    if (segment === 'full') return;
    expanded = !expanded;
  }
</script>

<div class="grid gap-4 rounded-lg border border-dashed border-primary/25 bg-muted/15 p-4">
  {#snippet resolvedCandidateRow(
    row: CharacterResolvedRow,
    highlight: boolean,
    origin: 'character' | 'workspace'
  )}
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
          <code class="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">{row.model_id}</code>
        </span>
        {#if origin === 'character'}
          <span
            class="shrink-0 rounded-md border border-emerald-600/35 bg-emerald-500/[0.12] px-2 py-0.5 font-sans text-[10px] font-bold uppercase tracking-wide text-emerald-900 dark:text-emerald-100"
            title="From this character’s preferred list (ordered)."
          >
            Character
          </span>
        {:else}
          <span
            class="shrink-0 rounded-md border border-slate-500/40 bg-slate-500/[0.12] px-2 py-0.5 font-sans text-[10px] font-bold uppercase tracking-wide text-slate-800 dark:text-slate-100"
            title="Workspace default from preferences — used when the character list has no usable model."
          >
            Workspace
          </span>
        {/if}
      </div>
      {#if row.display_name}
        <span class="text-xs text-muted-foreground">{row.display_name}</span>
      {/if}
      {#if row.note}
        <span class="text-xs text-amber-800 dark:text-amber-200">{row.note}</span>
      {/if}
      {#if row.replacement_id}
        <span class="text-xs text-muted-foreground">Replacement: {row.replacement_id}</span>
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
          <code class="break-all font-mono text-sm font-semibold">{args.modelId}</code>
          {#if args.source === 'character'}
            <span
              class="rounded-md border border-emerald-600/35 bg-emerald-500/[0.15] px-2 py-0.5 font-sans text-[10px] font-bold uppercase tracking-wide text-emerald-900 dark:text-emerald-100"
              title="Effective model comes from this character’s list."
            >
              Character
            </span>
          {:else}
            <span
              class="rounded-md border border-slate-500/40 bg-slate-500/[0.12] px-2 py-0.5 font-sans text-[10px] font-bold uppercase tracking-wide text-slate-800 dark:text-slate-100"
              title={args.workspaceBadgeTitle}
            >
              Workspace
            </span>
          {/if}
        </div>
        {#each args.detailLines as line}
          <p class="text-xs text-muted-foreground">{line}</p>
        {/each}
        <p class="text-xs leading-snug text-muted-foreground">
          {args.source === 'character' ? args.characterFooter : args.workspaceFooter}
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
      {#if payload.llm_rows.length === 0}
        <p class="text-sm text-muted-foreground">No preferred ids — workspace default chat applies.</p>
      {:else}
        <span class="font-sans text-[10px] font-bold uppercase tracking-wide text-muted-foreground"
          >Character list</span
        >
        <ul class="space-y-2">
          {#each payload.llm_rows as row (row.model_id)}
            {@render resolvedCandidateRow(
              row,
              payload.llm_applied?.source === 'character' &&
                payload.llm_applied.model_id === row.model_id &&
                row.status === 'available',
              'character'
            )}
          {/each}
        </ul>
      {/if}
      {#if payload.llm_workspace_row}
        <span class="mt-1 font-sans text-[10px] font-bold uppercase tracking-wide text-muted-foreground"
          >Workspace default</span
        >
        <ul class="space-y-2">
          {@render resolvedCandidateRow(
            payload.llm_workspace_row,
            payload.llm_applied?.source === 'workspace_fallback' &&
              payload.llm_applied.model_id === payload.llm_workspace_row.model_id &&
              payload.llm_workspace_row.status === 'available',
            'workspace'
          )}
        </ul>
      {/if}
      {#if payload.llm_applied}
        {@render appliedPanel({
          modelId: payload.llm_applied.model_id,
          source: payload.llm_applied.source,
          workspaceBadgeTitle:
            'Workspace default chat — used when the character list has no usable model.',
          detailLines: [
            `temp ${payload.llm_applied.temperature}, max tokens ${payload.llm_applied.max_tokens}`
          ],
          characterFooter: 'Taken from this character’s list (first online).',
          workspaceFooter:
            'Workspace fallback — no usable id in the character list, or the list is empty.'
        })}
      {:else}
        <p class="text-sm text-destructive">
          No chat model resolved. Check catalog, credentials, and default chat in settings.
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
          Voice replies are disabled in workspace settings — TTS is not used for agent replies.
        </p>
      {:else if payload.voice_rows.length === 0}
        <p class="text-sm text-muted-foreground">No preferred TTS ids — workspace default TTS applies.</p>
      {:else}
        <span class="font-sans text-[10px] font-bold uppercase tracking-wide text-muted-foreground"
          >Character list</span
        >
        <ul class="space-y-2">
          {#each payload.voice_rows as row (row.model_id)}
            {@render resolvedCandidateRow(
              row,
              payload.voice_applied?.source === 'character' &&
                payload.voice_applied.catalog_model_id === row.model_id &&
                row.status === 'available',
              'character'
            )}
          {/each}
        </ul>
      {/if}
      {#if payload.voice_workspace_row}
        <span class="mt-1 font-sans text-[10px] font-bold uppercase tracking-wide text-muted-foreground"
          >Workspace default</span
        >
        <ul class="space-y-2">
          {@render resolvedCandidateRow(
            payload.voice_workspace_row,
            payload.voice_applied?.source === 'workspace_fallback' &&
              payload.voice_applied.catalog_model_id === payload.voice_workspace_row.model_id &&
              payload.voice_workspace_row.status === 'available',
            'workspace'
          )}
        </ul>
      {/if}
      {#if !payload.voice_disabled}
        {#if payload.voice_applied}
          {@render appliedPanel({
            modelId: payload.voice_applied.catalog_model_id,
            source: payload.voice_applied.source,
            workspaceBadgeTitle:
              'Workspace default TTS — used when the character list has no usable model.',
            detailLines: voiceDetailLines(payload.voice_applied.synthesis),
            characterFooter: 'Taken from this character’s list (first online for TTS).',
            workspaceFooter:
              'Workspace fallback — no usable TTS id in the character list, or the list is empty.'
          })}
        {:else}
          <p class="text-sm text-destructive">
            No TTS model resolved. Set default TTS in settings and configure a TTS provider.
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
        Which chat and TTS models HiroServer would pick for this character, given the catalog and
        credentials in this workspace. Order matches the character list; the first usable id wins.
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
          Chat LLM resolution (saved)
        {:else}
          TTS resolution (saved)
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
        {@render llmColumn(resolved, 'Chat (LLM)')}
        {@render voiceColumn(resolved, 'Voice (TTS)')}
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
          Effective LLM model selected from the character's list and workspace defaults.
        {:else}
          Effective TTS model selected from the character's list and workspace defaults.
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
