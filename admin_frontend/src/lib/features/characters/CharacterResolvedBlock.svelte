<script lang="ts">
  import { ChevronRight, CircleCheck } from '@lucide/svelte';
  import type { CharacterResolvedPayload, CharacterResolvedRow } from '$lib/api/characters';
  import { cn } from '$lib/utils';

  /** One-line summary for collapsed LLM header (effective catalog model id + optional display name). */
  function llmCollapsedSummary(payload: CharacterResolvedPayload): string {
    if (!payload.llm_applied) return 'No model resolved';
    const applied = payload.llm_applied;
    const row =
      payload.llm_rows.find((r) => r.model_id === applied.model_id) ??
      (payload.llm_workspace_row?.model_id === applied.model_id ? payload.llm_workspace_row : undefined);
    const name = row?.display_name?.trim();
    return name ? `${applied.model_id} · ${name}` : applied.model_id;
  }

  /** One-line summary for collapsed TTS header (catalog model + optional display + bundled voice id). */
  function voiceCollapsedSummary(payload: CharacterResolvedPayload): string {
    if (payload.voice_disabled) return 'Voice replies disabled';
    if (!payload.voice_applied) return 'No TTS model resolved';
    const applied = payload.voice_applied;
    const vid = applied.catalog_model_id;
    const row =
      payload.voice_rows.find((r) => r.model_id === vid) ??
      (payload.voice_workspace_row?.model_id === vid ? payload.voice_workspace_row : undefined);
    const display = row?.display_name?.trim();
    const voice = applied.synthesis.voice?.trim();
    const base = display ? `${vid} · ${display}` : vid;
    return voice ? `${base} · ${voice}` : base;
  }

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

  function resolvedRowTooltip(status: CharacterResolvedRow['status']): string {
    switch (status) {
      case 'available':
        return 'Online — model is usable with this workspace.';
      case 'unavailable':
        return 'Offline — model is not usable with current workspace configuration.';
      case 'unknown':
        return 'Unknown — resolution could not determine usability.';
      case 'wrong_kind':
        return 'Offline — model kind does not match this slot.';
      case 'deprecated':
        return 'Deprecated — still listed but slated for removal.';
      default:
        return '';
    }
  }

  function resolvedRowDotClass(status: CharacterResolvedRow['status']): string {
    switch (status) {
      case 'available':
        return 'bg-emerald-500';
      case 'unavailable':
      case 'wrong_kind':
        return 'bg-red-500';
      case 'deprecated':
        return 'bg-amber-500';
      default:
        return 'bg-muted-foreground/50';
    }
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

  {#snippet llmAppliedPanel(applied: NonNullable<CharacterResolvedPayload['llm_applied']>)}
    <div
      class="flex max-w-lg gap-3 rounded-md border border-emerald-600/25 bg-emerald-500/[0.06] p-3 text-sm dark:bg-emerald-950/25"
    >
      <span class="mt-0.5 shrink-0 text-emerald-600 dark:text-emerald-400" title="Selected">
        <CircleCheck size={22} strokeWidth={2.25} aria-hidden="true" />
      </span>
      <span class="sr-only">Selected</span>
      <div class="min-w-0 flex-1 space-y-1">
        <div class="flex flex-wrap items-center gap-2">
          <code class="break-all font-mono text-sm font-semibold">{applied.model_id}</code>
          {#if applied.source === 'character'}
            <span
              class="rounded-md border border-emerald-600/35 bg-emerald-500/[0.15] px-2 py-0.5 font-sans text-[10px] font-bold uppercase tracking-wide text-emerald-900 dark:text-emerald-100"
              title="Effective model comes from this character’s list."
            >
              Character
            </span>
          {:else}
            <span
              class="rounded-md border border-slate-500/40 bg-slate-500/[0.12] px-2 py-0.5 font-sans text-[10px] font-bold uppercase tracking-wide text-slate-800 dark:text-slate-100"
              title="Workspace default chat — used when the character list has no usable model."
            >
              Workspace
            </span>
          {/if}
        </div>
        <p class="text-xs text-muted-foreground">
          temp {applied.temperature}, max tokens {applied.max_tokens}
        </p>
        <p class="text-xs leading-snug text-muted-foreground">
          {#if applied.source === 'character'}
            Taken from this character’s list (first online).
          {:else}
            Workspace fallback — no usable id in the character list, or the list is empty.
          {/if}
        </p>
      </div>
    </div>
  {/snippet}

  {#snippet voiceAppliedPanel(applied: NonNullable<CharacterResolvedPayload['voice_applied']>)}
    <div
      class="flex max-w-lg gap-3 rounded-md border border-emerald-600/25 bg-emerald-500/[0.06] p-3 text-sm dark:bg-emerald-950/25"
    >
      <span class="mt-0.5 shrink-0 text-emerald-600 dark:text-emerald-400" title="Selected">
        <CircleCheck size={22} strokeWidth={2.25} aria-hidden="true" />
      </span>
      <span class="sr-only">Selected</span>
      <div class="min-w-0 flex-1 space-y-1">
        <div class="flex flex-wrap items-center gap-2">
          <code class="break-all font-mono text-sm font-semibold">{applied.catalog_model_id}</code>
          {#if applied.source === 'character'}
            <span
              class="rounded-md border border-emerald-600/35 bg-emerald-500/[0.15] px-2 py-0.5 font-sans text-[10px] font-bold uppercase tracking-wide text-emerald-900 dark:text-emerald-100"
              title="Effective model comes from this character’s list."
            >
              Character
            </span>
          {:else}
            <span
              class="rounded-md border border-slate-500/40 bg-slate-500/[0.12] px-2 py-0.5 font-sans text-[10px] font-bold uppercase tracking-wide text-slate-800 dark:text-slate-100"
              title="Workspace default TTS — used when the character list has no usable model."
            >
              Workspace
            </span>
          {/if}
        </div>
        {#if applied.synthesis.voice}
          <p class="text-xs text-muted-foreground">
            Voice “{applied.synthesis.voice}”
            {#if applied.synthesis.instructions?.trim()}
              · instructions “{applied.synthesis.instructions.trim()}”
            {/if}
          </p>
        {:else if applied.synthesis.instructions?.trim()}
          <p class="text-xs text-muted-foreground">
            Instructions “{applied.synthesis.instructions.trim()}”
          </p>
        {/if}
        <p class="text-xs leading-snug text-muted-foreground">
          {#if applied.source === 'character'}
            Taken from this character’s list (first online for TTS).
          {:else}
            Workspace fallback — no usable TTS id in the character list, or the list is empty.
          {/if}
        </p>
      </div>
    </div>
  {/snippet}

  {#snippet llmSegmentBody()}
    <div class="grid max-w-lg gap-2">
      {#if resolved!.llm_rows.length === 0}
        <p class="text-sm text-muted-foreground">No preferred ids — workspace default chat applies.</p>
      {:else}
        <span class="font-sans text-[10px] font-bold uppercase tracking-wide text-muted-foreground"
          >Character list</span
        >
        <ul class="space-y-2">
          {#each resolved!.llm_rows as row (row.model_id)}
            {@render resolvedCandidateRow(
              row,
              resolved!.llm_applied?.source === 'character' &&
                resolved!.llm_applied.model_id === row.model_id &&
                row.status === 'available',
              'character'
            )}
          {/each}
        </ul>
      {/if}
      {#if resolved!.llm_workspace_row}
        <span class="mt-1 font-sans text-[10px] font-bold uppercase tracking-wide text-muted-foreground"
          >Workspace default</span
        >
        <ul class="space-y-2">
          {@render resolvedCandidateRow(
            resolved!.llm_workspace_row,
            resolved!.llm_applied?.source === 'workspace_fallback' &&
              resolved!.llm_applied!.model_id === resolved!.llm_workspace_row.model_id &&
              resolved!.llm_workspace_row.status === 'available',
            'workspace'
          )}
        </ul>
      {/if}
      {#if resolved!.llm_applied}
        {@render llmAppliedPanel(resolved!.llm_applied)}
      {:else}
        <p class="text-sm text-destructive">
          No chat model resolved. Check catalog, credentials, and default chat in preferences.
        </p>
      {/if}
    </div>
  {/snippet}

  {#snippet voiceSegmentBody()}
    <div class="grid max-w-lg gap-2">
      {#if resolved!.voice_disabled}
        <p class="text-sm text-muted-foreground">
          Voice replies are disabled in workspace preferences — TTS is not used for agent replies.
        </p>
      {:else if resolved!.voice_rows.length === 0}
        <p class="text-sm text-muted-foreground">No preferred TTS ids — workspace default TTS applies.</p>
      {:else}
        <span class="font-sans text-[10px] font-bold uppercase tracking-wide text-muted-foreground"
          >Character list</span
        >
        <ul class="space-y-2">
          {#each resolved!.voice_rows as row (row.model_id)}
            {@render resolvedCandidateRow(
              row,
              resolved!.voice_applied?.source === 'character' &&
                resolved!.voice_applied.catalog_model_id === row.model_id &&
                row.status === 'available',
              'character'
            )}
          {/each}
        </ul>
      {/if}
      {#if resolved!.voice_workspace_row}
        <span class="mt-1 font-sans text-[10px] font-bold uppercase tracking-wide text-muted-foreground"
          >Workspace default</span
        >
        <ul class="space-y-2">
          {@render resolvedCandidateRow(
            resolved!.voice_workspace_row,
            resolved!.voice_applied?.source === 'workspace_fallback' &&
              resolved!.voice_applied!.catalog_model_id === resolved!.voice_workspace_row.model_id &&
              resolved!.voice_workspace_row.status === 'available',
            'workspace'
          )}
        </ul>
      {/if}
      {#if !resolved!.voice_disabled}
        {#if resolved!.voice_applied}
          {@render voiceAppliedPanel(resolved!.voice_applied)}
        {:else}
          <p class="text-sm text-destructive">
            No TTS model resolved. Set default TTS in preferences and configure a TTS provider.
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
      aria-controls={`character-resolved-${segment}-details`}
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
          <span class="text-muted-foreground">Loading resolved configuration…</span>
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
      <p class="text-sm text-muted-foreground">Loading resolved configuration…</p>
    {:else}
      <div class="grid gap-5 md:grid-cols-2 md:items-start">
        <div class="grid max-w-lg gap-2">
          <span class="font-sans text-xs font-semibold uppercase text-muted-foreground">Chat (LLM)</span>
          {#if resolved.llm_rows.length === 0}
            <p class="max-w-lg text-sm text-muted-foreground">
              No preferred ids — workspace default chat applies.
            </p>
          {:else}
            <span class="font-sans text-[10px] font-bold uppercase tracking-wide text-muted-foreground"
              >Character list</span
            >
            <ul class="max-w-lg space-y-2">
              {#each resolved.llm_rows as row (row.model_id)}
                {@render resolvedCandidateRow(
                  row,
                  resolved.llm_applied?.source === 'character' &&
                    resolved.llm_applied.model_id === row.model_id &&
                    row.status === 'available',
                  'character'
                )}
              {/each}
            </ul>
          {/if}
          {#if resolved.llm_workspace_row}
            <span class="mt-1 font-sans text-[10px] font-bold uppercase tracking-wide text-muted-foreground"
              >Workspace default</span
            >
            <ul class="max-w-lg space-y-2">
              {@render resolvedCandidateRow(
                resolved.llm_workspace_row,
                resolved.llm_applied?.source === 'workspace_fallback' &&
                  resolved.llm_applied.model_id === resolved.llm_workspace_row.model_id &&
                  resolved.llm_workspace_row.status === 'available',
                'workspace'
              )}
            </ul>
          {/if}
          {#if resolved.llm_applied}
            {@render llmAppliedPanel(resolved.llm_applied)}
          {:else}
            <p class="max-w-lg text-sm text-destructive">
              No chat model resolved. Check catalog, credentials, and default chat in preferences.
            </p>
          {/if}
        </div>

        <div class="grid max-w-lg gap-2">
          <span class="font-sans text-xs font-semibold uppercase text-muted-foreground">Voice (TTS)</span>
          {#if resolved.voice_disabled}
            <p class="max-w-lg text-sm text-muted-foreground">
              Voice replies are disabled in workspace preferences — TTS is not used for agent replies.
            </p>
          {:else if resolved.voice_rows.length === 0}
            <p class="max-w-lg text-sm text-muted-foreground">
              No preferred TTS ids — workspace default TTS applies.
            </p>
          {:else}
            <span class="font-sans text-[10px] font-bold uppercase tracking-wide text-muted-foreground"
              >Character list</span
            >
            <ul class="max-w-lg space-y-2">
              {#each resolved.voice_rows as row (row.model_id)}
                {@render resolvedCandidateRow(
                  row,
                  resolved.voice_applied?.source === 'character' &&
                    resolved.voice_applied.catalog_model_id === row.model_id &&
                    row.status === 'available',
                  'character'
                )}
              {/each}
            </ul>
          {/if}
          {#if resolved.voice_workspace_row}
            <span class="mt-1 font-sans text-[10px] font-bold uppercase tracking-wide text-muted-foreground"
              >Workspace default</span
            >
            <ul class="max-w-lg space-y-2">
              {@render resolvedCandidateRow(
                resolved.voice_workspace_row,
                resolved.voice_applied?.source === 'workspace_fallback' &&
                  resolved.voice_applied.catalog_model_id === resolved.voice_workspace_row.model_id &&
                  resolved.voice_workspace_row.status === 'available',
                'workspace'
              )}
            </ul>
          {/if}
          {#if !resolved.voice_disabled}
            {#if resolved.voice_applied}
              {@render voiceAppliedPanel(resolved.voice_applied)}
            {:else}
              <p class="max-w-lg text-sm text-destructive">
                No TTS model resolved. Set default TTS in preferences and configure a TTS provider.
              </p>
            {/if}
          {/if}
        </div>
      </div>
    {/if}
  {:else if expanded}
    <div id="character-resolved-{segment}-details" class="grid gap-3 border-t border-border/40 pt-3">
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
        <p class="text-sm text-muted-foreground">Loading resolved configuration…</p>
      {:else if segment === 'llm'}
        {@render llmSegmentBody()}
      {:else}
        {@render voiceSegmentBody()}
      {/if}
    </div>
  {/if}
</div>
