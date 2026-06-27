<script lang="ts">
  import { Check, ChevronsUpDown, Pencil, RotateCcw } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import * as Popover from '$lib/components/ui/popover';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { TuningProfile } from '$lib/api/preferences';
  import { DEFAULT_WORKSPACE_PREFERENCES } from '$lib/api/generated/workspace-preferences.defaults';
  import type { ThinkingValue } from '$lib/features/preferences/shared/preferences-constants';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import {
    preferenceFieldMeta,
    preferenceHint,
    type PreferencePath
  } from '$lib/features/preferences/shared/preferences-schema';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';
  import { cn } from '$lib/utils';

  type TuningProfileScope = 'llm' | 'memory' | 'knowledge';

  type Props = {
    ctrl: PreferencesController;
    label: string;
    /** Overrides the schema description; omit (with `path`) to use the field's backend `description`. */
    hint?: string;
    /** Schema path for the bound field — sources the hint when `hint` is not given. */
    path?: PreferencePath;
    /** When set, writes via `ctrl.setDefaultTuningProfile` instead of `value`. */
    value?: string;
    scope?: TuningProfileScope;
    class?: string;
  };

  let {
    ctrl,
    label,
    hint: hintOverride = '',
    path,
    value = $bindable(''),
    scope,
    class: className = ''
  }: Props = $props();

  const hint = $derived(
    hintOverride || (path ? preferenceHint(preferenceFieldMeta(ctrl.fieldSchema, path)) : '') || ''
  );

  const THINKING_LABELS: Record<string, string> = {
    off: 'Off',
    minimal: 'Minimal',
    low: 'Low',
    medium: 'Medium',
    high: 'High'
  };

  function thinkingLabel(thinking: ThinkingValue | null | undefined): string {
    return thinking ? (THINKING_LABELS[thinking] ?? thinking) : 'Default';
  }

  /** Second line shown under each profile name (Temp · Max · Think [· Ctx]). */
  function profileSummary(profile: TuningProfile): string {
    const parts = [
      `Temp ${profile.temperature}`,
      `Max ${profile.max_tokens}`,
      `Think ${thinkingLabel(profile.thinking)}`
    ];
    if (profile.num_ctx != null) parts.push(`Ctx ${profile.num_ctx}`);
    return parts.join(' · ');
  }

  const selectedProfile = $derived(ctrl.draft?.tuning_profiles?.[value]);

  // Every preference field that references a tuning profile by id — drives the dialog's
  // "Used by" list so the user sees the blast radius before editing a shared profile.
  const PROFILE_REFERENCES: { label: string; get: (d: NonNullable<typeof ctrl.draft>) => string | undefined }[] = [
    { label: 'Default chat model', get: (d) => d.llm?.default_tuning_profile },
    { label: 'Memory default', get: (d) => d.memory?.default_tuning_profile },
    { label: 'Knowledge answering', get: (d) => d.knowledge?.default_tuning_profile },
    { label: 'Graph extraction model', get: (d) => d.graph?.extraction_tuning_profile },
    { label: 'Graph smaller model', get: (d) => d.graph?.small_tuning_profile },
    { label: 'Graph eval — answer', get: (d) => d.graph?.eval?.answer_tuning_profile },
    { label: 'Graph eval — judge', get: (d) => d.graph?.eval?.judge_tuning_profile },
    { label: 'Graph eval — retrieval', get: (d) => d.graph?.eval?.retrieval_tuning_profile }
  ];

  const usedBy = $derived.by(() => {
    const d = ctrl.draft;
    if (!d) return [];
    return PROFILE_REFERENCES.filter((ref) => ref.get(d) === value).map((ref) => ref.label);
  });

  let open = $state(false);

  function selectProfile(id: string) {
    open = false;
    if (scope) {
      ctrl.setDefaultTuningProfile(scope, id);
      return;
    }
    value = id;
    ctrl.markDirty();
  }

  // --- Inline edit dialog (persists immediately, applies to every model using the profile) ---
  let editOpen = $state(false);
  let editDraft = $state<TuningProfile | null>(null);

  function openEdit() {
    const profile = ctrl.draft?.tuning_profiles?.[value];
    if (!profile) return;
    editDraft = JSON.parse(JSON.stringify(profile)) as TuningProfile;
    editOpen = true;
  }

  const editDirty = $derived(
    editDraft && ctrl.draft?.tuning_profiles?.[value]
      ? JSON.stringify(editDraft) !== JSON.stringify(ctrl.draft.tuning_profiles[value])
      : false
  );

  async function applyEdit() {
    if (!editDraft) return;
    await ctrl.saveProfileNow(value, editDraft);
    editOpen = false;
  }

  function resetEdit() {
    const def = (DEFAULT_WORKSPACE_PREFERENCES.tuning_profiles as Record<string, TuningProfile>)[value];
    if (def) editDraft = JSON.parse(JSON.stringify(def)) as TuningProfile;
  }

  function setThinking(next: string) {
    if (editDraft) editDraft.thinking = next === 'default' ? null : (next as ThinkingValue);
  }

  function setNumCtx(next: string) {
    if (editDraft) editDraft.num_ctx = next.trim() === '' ? null : Number(next);
  }
</script>

<FormField {label} {hint} hintTooltip class={className}>
  <div class="flex items-stretch gap-2">
    <Popover.Root bind:open>
      <Popover.Trigger
        class={cn(
          'flex flex-1 items-center justify-between gap-2 rounded-md border border-input bg-background px-3 py-2 text-left outline-none transition-colors hover:bg-accent/40 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring'
        )}
        aria-label={`${label} — choose tuning profile`}
      >
        {#if selectedProfile}
          <span class="grid min-w-0 gap-0.5">
            <span class="truncate font-sans text-sm font-medium text-foreground">
              {selectedProfile.label}
            </span>
            <span class="truncate font-sans text-xs text-muted-foreground">
              {profileSummary(selectedProfile)}
            </span>
          </span>
        {:else}
          <span class="font-sans text-sm text-muted-foreground">Select a profile</span>
        {/if}
        <ChevronsUpDown size={16} class="shrink-0 text-muted-foreground" aria-hidden="true" />
      </Popover.Trigger>

      <Popover.Content align="start" class="w-80 max-w-[90vw] gap-0 p-1.5">
        <div class="max-h-[20rem] overflow-y-auto" role="listbox" aria-label={`${label} profiles`}>
          {#each ctrl.profileEntries as [id, profile] (id)}
            <button
              type="button"
              role="option"
              aria-selected={id === value}
              class={cn(
                'flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left transition-colors hover:bg-accent/60',
                id === value && 'bg-primary/15'
              )}
              onclick={() => selectProfile(id)}
            >
              <span class="grid min-w-0 flex-1 gap-0.5">
                <span class="truncate font-sans text-sm font-medium text-foreground">
                  {profile.label}
                </span>
                <span class="truncate font-sans text-xs text-muted-foreground">
                  {profileSummary(profile)}
                </span>
              </span>
              {#if id === value}
                <Check size={15} class="shrink-0 text-primary" aria-hidden="true" />
              {/if}
            </button>
          {/each}
        </div>
      </Popover.Content>
    </Popover.Root>

    <Button
      variant="outline"
      size="icon"
      class="size-auto shrink-0 px-3"
      disabled={!selectedProfile || ctrl.busy}
      aria-label={`Edit ${label}`}
      title="Edit this tuning profile"
      onclick={openEdit}
    >
      <Pencil size={15} />
    </Button>
  </div>
</FormField>

<Dialog.Root open={editOpen} onOpenChange={(next) => (editOpen = next)}>
  <Dialog.Content class="sm:max-w-lg">
    <Dialog.Header>
      <Dialog.Title>Edit tuning profile</Dialog.Title>
      <Dialog.Description>
        Changes apply to every model using this profile and are saved immediately.
      </Dialog.Description>
    </Dialog.Header>

    {#if editDraft}
      <div class="grid gap-3">
        <FormField label="Name">
          <input
            class={ADMIN_SELECT_LG}
            value={editDraft.label}
            oninput={(event) => { if (editDraft) editDraft.label = event.currentTarget.value; }}
          />
        </FormField>
        <div class="grid gap-3 sm:grid-cols-3">
          <FormField label="Temperature">
            <input
              type="number"
              min="0"
              max="2"
              step="0.1"
              class={ADMIN_SELECT_LG}
              value={editDraft.temperature}
              oninput={(event) => { if (editDraft) editDraft.temperature = Number(event.currentTarget.value); }}
            />
          </FormField>
          <FormField label="Max tokens">
            <input
              type="number"
              min="1"
              step="1"
              class={ADMIN_SELECT_LG}
              value={editDraft.max_tokens}
              oninput={(event) => { if (editDraft) editDraft.max_tokens = Number(event.currentTarget.value); }}
            />
          </FormField>
          <FormField label="Thinking">
            <select
              class={ADMIN_SELECT_LG}
              value={editDraft.thinking ?? 'default'}
              onchange={(event) => setThinking(event.currentTarget.value)}
            >
              <option value="default">Model default</option>
              <option value="off">Off</option>
              <option value="minimal">Minimal</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </FormField>
        </div>
        <FormField label="Context window" class="max-w-[12rem]">
          <input
            type="number"
            min="1"
            step="1"
            class={ADMIN_SELECT_LG}
            placeholder="Provider default"
            value={editDraft.num_ctx ?? ''}
            oninput={(event) => setNumCtx(event.currentTarget.value)}
          />
        </FormField>

        <div class="grid gap-1.5 rounded-md border border-border/70 bg-muted/30 p-3">
          <span class="font-sans text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Used by
          </span>
          {#if usedBy.length}
            <ul class="grid gap-1">
              {#each usedBy as ref (ref)}
                <li class="font-sans text-sm text-foreground">{ref}</li>
              {/each}
            </ul>
          {:else}
            <p class="font-sans text-sm text-muted-foreground">
              Not referenced by any current default.
            </p>
          {/if}
        </div>
      </div>
    {/if}

    <Dialog.Footer class="sm:justify-between">
      {#if editDraft?.locked}
        <Button variant="outline" disabled={ctrl.busy} onclick={resetEdit}>
          <RotateCcw size={14} /> Reset to default
        </Button>
      {:else}
        <span></span>
      {/if}
      <div class="flex items-center gap-2">
        <Button variant="outline" disabled={ctrl.busy} onclick={() => (editOpen = false)}>
          Cancel
        </Button>
        <Button disabled={ctrl.busy || !editDirty} onclick={applyEdit}>Update</Button>
      </div>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
