<script lang="ts">
  import { Check, ChevronsUpDown, Pencil } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import * as Popover from '$lib/components/ui/popover';
  import type { TuningProfile } from '$lib/api/preferences';
  import { thinkingLabel } from '$lib/features/preferences/shared/preferences-constants';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import {
    preferenceFieldMeta,
    preferenceHint,
    preferenceTitle,
    type PreferencePath
  } from '$lib/features/preferences/shared/preferences-schema';
  import {
    getPreferenceByPath,
    setPreferenceByPath
  } from '$lib/features/preferences/state/preferences-edits';
  import { cn } from '$lib/utils';
  import TuningProfileEditorDialog from './TuningProfileEditorDialog.svelte';

  type TuningProfileScope = 'llm' | 'memory' | 'knowledge';

  type Props = {
    ctrl: PreferencesController;
    /** Optional label override; omit (with `path`) to use the field's backend `title`. */
    label?: string;
    /** Overrides the schema description; omit (with `path`) to use the field's backend `description`. */
    hint?: string;
    /** Schema path for the bound field — sources the label + hint AND the selected profile id. */
    path?: PreferencePath;
    scope?: TuningProfileScope;
    class?: string;
  };

  let { ctrl, label, hint: hintOverride = '', path, scope, class: className = '' }: Props = $props();

  // Selected profile id is owned by `path` (read from the draft), not passed in — removes the
  // double-write where the call site repeated `value={ctrl.draft.<path>}` alongside `path`.
  const value = $derived(
    path ? ((getPreferenceByPath(ctrl.draft, path) as string | null) ?? '') : ''
  );

  const fieldMeta = $derived(path ? preferenceFieldMeta(ctrl.fieldSchema, path) : null);
  const resolvedLabel = $derived(label ?? preferenceTitle(fieldMeta) ?? path ?? '');
  const hint = $derived(hintOverride || preferenceHint(fieldMeta) || '');

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
    // No scope: write the id straight to the bound path (mirrors the old `value = id` fallback).
    if (path && ctrl.draft) {
      setPreferenceByPath(ctrl.draft, path, id);
      ctrl.markDirty();
    }
  }

  // Inline edit dialog (the dialog component owns its working copy; persists via saveProfileNow).
  let editOpen = $state(false);
</script>

<FormField label={resolvedLabel} {hint} hintTooltip anchor={path} class={className}>
  <div class="flex items-stretch gap-2">
    <Popover.Root bind:open>
      <Popover.Trigger
        class={cn(
          'flex flex-1 items-center justify-between gap-2 rounded-md border border-input bg-background px-3 py-2 text-left outline-none transition-colors hover:bg-accent/40 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring'
        )}
        aria-label={`${resolvedLabel} — choose tuning profile`}
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
        <div class="max-h-[20rem] overflow-y-auto" role="listbox" aria-label={`${resolvedLabel} profiles`}>
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
      aria-label={`Edit ${resolvedLabel}`}
      title="Edit this tuning profile"
      onclick={() => (editOpen = true)}
    >
      <Pencil size={15} />
    </Button>
  </div>
</FormField>

<TuningProfileEditorDialog
  {ctrl}
  profileId={value}
  open={editOpen}
  onClose={() => (editOpen = false)}
/>
