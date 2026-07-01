<script lang="ts">
  /**
   * Inline tuning-profile editor dialog. Edits a LOCAL working copy seeded from the draft when the
   * dialog opens; "Update" persists it immediately via `ctrl.saveProfileNow` (applies to every model
   * referencing the profile). Split out of `TuningProfileSelect` so the picker stays thin.
   */
  import { RotateCcw } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { TuningProfile } from '$lib/api/preferences';
  import { DEFAULT_WORKSPACE_PREFERENCES } from '$lib/api/generated/workspace-preferences.defaults';
  import type { ThinkingValue } from '$lib/features/preferences/shared/preferences-constants';
  import { THINKING_SELECT_OPTIONS } from '$lib/features/preferences/shared/preferences-constants';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';

  type Props = {
    ctrl: PreferencesController;
    /** Id of the profile being edited (the picker's currently-selected profile). */
    profileId: string;
    open: boolean;
    onClose: () => void;
  };

  let { ctrl, profileId, open, onClose }: Props = $props();

  // Working copy, seeded from the draft when the dialog transitions closed → open (a plain latch, not
  // reactive, so a parent re-render while open never wipes in-progress edits).
  let editDraft = $state<TuningProfile | null>(null);
  let seeded = false;

  $effect(() => {
    if (open && !seeded) {
      const profile = ctrl.draft?.tuning_profiles?.[profileId];
      editDraft = profile ? (JSON.parse(JSON.stringify(profile)) as TuningProfile) : null;
      seeded = true;
    } else if (!open && seeded) {
      seeded = false;
    }
  });

  const editDirty = $derived(
    editDraft && ctrl.draft?.tuning_profiles?.[profileId]
      ? JSON.stringify(editDraft) !== JSON.stringify(ctrl.draft.tuning_profiles[profileId])
      : false
  );

  // Every preference field that references a tuning profile by id — the "Used by" list shows the
  // blast radius before editing a shared profile.
  const PROFILE_REFERENCES: {
    label: string;
    get: (d: NonNullable<typeof ctrl.draft>) => string | undefined;
  }[] = [
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
    return PROFILE_REFERENCES.filter((ref) => ref.get(d) === profileId).map((ref) => ref.label);
  });

  async function applyEdit() {
    if (!editDraft) return;
    await ctrl.saveProfileNow(profileId, editDraft);
    onClose();
  }

  function resetEdit() {
    const def = (DEFAULT_WORKSPACE_PREFERENCES.tuning_profiles as Record<string, TuningProfile>)[
      profileId
    ];
    if (def) editDraft = JSON.parse(JSON.stringify(def)) as TuningProfile;
  }

  function setThinking(next: string) {
    if (editDraft) editDraft.thinking = next === 'default' ? null : (next as ThinkingValue);
  }

  function setNumCtx(next: string) {
    if (editDraft) editDraft.num_ctx = next.trim() === '' ? null : Number(next);
  }
</script>

<Dialog.Root
  {open}
  onOpenChange={(next) => {
    if (!next) onClose();
  }}
>
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
            oninput={(event) => {
              if (editDraft) editDraft.label = event.currentTarget.value;
            }}
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
              oninput={(event) => {
                if (editDraft) editDraft.temperature = Number(event.currentTarget.value);
              }}
            />
          </FormField>
          <FormField label="Max tokens">
            <input
              type="number"
              min="1"
              step="1"
              class={ADMIN_SELECT_LG}
              value={editDraft.max_tokens}
              oninput={(event) => {
                if (editDraft) editDraft.max_tokens = Number(event.currentTarget.value);
              }}
            />
          </FormField>
          <FormField label="Thinking">
            <select
              class={ADMIN_SELECT_LG}
              value={editDraft.thinking ?? 'default'}
              onchange={(event) => setThinking(event.currentTarget.value)}
            >
              {#each THINKING_SELECT_OPTIONS as option (option.value)}
                <option value={option.value}>{option.label}</option>
              {/each}
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
          <span
            class="font-sans text-xs font-semibold uppercase tracking-wide text-muted-foreground"
          >
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
        <Button variant="outline" disabled={ctrl.busy} onclick={onClose}>Cancel</Button>
        <Button disabled={ctrl.busy || !editDirty} onclick={applyEdit}>Update</Button>
      </div>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
