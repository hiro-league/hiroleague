<script lang="ts">
  /**
   * Inline control for a versioned prompt LIBRARY (graph.eval.answer_prompts /
   * retrieval_agent_prompts). The page only SELECTS which version to open; all management — edit
   * text, New / Duplicate / Delete / Rename — happens in the editor dialog, which saves the whole
   * dict to the backend on Save (or discards on Cancel). The "active/used" version stays owned
   * elsewhere (eval panel / active_*_id selector); this is edit-only.
   */
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import { getPreferenceByPath } from '$lib/features/preferences/state/preferences-edits';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';
  import {
    preferenceFieldMeta,
    preferenceTitle,
    type PreferencePath
  } from '$lib/features/preferences/shared/preferences-schema';
  import type { AnswerPromptProfile } from '$lib/api/preferences';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import PromptEditorDialog from './PromptEditorDialog.svelte';
  import type { PromptDialogModel, PromptSavePayload } from './prompt-editor';

  type Props = {
    ctrl: PreferencesController;
    /** Dotted path to the dict, e.g. "graph.eval.answer_prompts". */
    dictPath: string;
    /** Optional label override; omit to use the dict field's backend `title`. */
    label?: string;
    /** Help text shown as a tooltip next to the field label (no inline prose on the page). */
    hint?: string;
    ariaLabel: string;
    editorLabel?: string;
    dialogTitle?: string;
    /** Dotted path to a persisted "active version" pointer to repair if its target is deleted. */
    activeIdPath?: string;
    defaultId?: string;
  };

  let {
    ctrl,
    dictPath,
    label,
    hint,
    ariaLabel,
    editorLabel,
    dialogTitle,
    activeIdPath,
    defaultId = 'default'
  }: Props = $props();

  let open = $state(false);
  const resolvedLabel = $derived(
    label ?? preferenceTitle(preferenceFieldMeta(ctrl.fieldSchema, dictPath as PreferencePath)) ?? dictPath
  );
  // Seeded by the clamp effect below (to defaultId) once the dict is known — avoids capturing the
  // `defaultId` prop in the $state initializer (state_referenced_locally).
  let selectedId = $state('');

  const dict = $derived(
    (getPreferenceByPath(ctrl.draft, dictPath) ?? {}) as Record<string, AnswerPromptProfile>
  );
  const entries = $derived(
    Object.entries(dict).sort(([ka, a], [kb, b]) =>
      ka === defaultId ? -1 : kb === defaultId ? 1 : a.label.localeCompare(b.label)
    )
  );

  // Keep the selection valid as the dict changes (e.g. the open version was deleted via the dialog).
  $effect(() => {
    if (!(selectedId in dict)) selectedId = defaultId;
  });

  const model = $derived<PromptDialogModel>({
    kind: 'library',
    initialDict: dict,
    defaultId,
    initialSelectedId: selectedId
  });

  async function onSave(payload: PromptSavePayload): Promise<boolean> {
    if (payload.kind !== 'library') return false;
    const edits: Record<string, unknown> = { [dictPath]: payload.dict };
    // Repair a dangling "active version" pointer when its target was deleted in the dialog.
    if (activeIdPath) {
      const activeId = getPreferenceByPath(ctrl.draft, activeIdPath);
      if (typeof activeId === 'string' && !(activeId in payload.dict)) {
        edits[activeIdPath] = defaultId;
      }
    }
    return ctrl.saveDialogEdits(edits);
  }
</script>

<div data-pref-path={dictPath} class="flex flex-wrap items-end gap-3">
  <FormField label="Version to edit" class="min-w-[16rem] flex-1" {hint} hintTooltip>
    <select class={ADMIN_SELECT_LG} bind:value={selectedId}>
      {#each entries as [id, p] (id)}
        <option value={id}>{p.label}{p.locked ? ' 🔒' : ''}</option>
      {/each}
    </select>
  </FormField>
  <Button variant="outline" size="sm" class="mb-1" onclick={() => (open = true)}>
    Edit versions
  </Button>
</div>

<PromptEditorDialog
  {open}
  title={dialogTitle ?? `Edit: ${resolvedLabel}`}
  {ariaLabel}
  {editorLabel}
  {model}
  {onSave}
  onClose={() => (open = false)}
  pending={ctrl.busy}
/>
