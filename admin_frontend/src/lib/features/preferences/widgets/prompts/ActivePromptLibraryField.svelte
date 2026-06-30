<script lang="ts">
  /**
   * Single merged control for a versioned prompt library that ALSO has a persisted "active version"
   * pointer (graph.eval.retrieval_agent_prompts + active_retrieval_agent_prompt_id). One dropdown
   * SELECTS the active profile (saved with the page, via markDirty). Inline icon buttons —
   * New / Edit / Duplicate — all open the shared PromptEditorDialog, which keeps its full
   * management (edit text, New / Duplicate / Delete / Rename, immediate PATCH on its own Save).
   * There is intentionally no inline Delete here: deletion stays inside the dialog.
   *
   * Replaces the former two-control layout (separate "Active prompt profile" select +
   * PromptLibraryField "Version to edit" + "Edit versions" button).
   */
  import { Copy, Pencil, Plus } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import {
    getPreferenceByPath,
    setPreferenceByPath
  } from '$lib/features/preferences/state/preferences-edits';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';
  import {
    preferenceFieldMeta,
    preferenceHint,
    preferenceTitle,
    type PreferencePath
  } from '$lib/features/preferences/shared/preferences-schema';
  import type { AnswerPromptProfile } from '$lib/api/preferences';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import PromptEditorDialog from './PromptEditorDialog.svelte';
  import type { PromptDialogModel, PromptSavePayload } from './prompt-editor';

  type Props = {
    ctrl: PreferencesController;
    /** Dotted path to the dict, e.g. "graph.eval.retrieval_agent_prompts". */
    dictPath: string;
    /** Dotted path to the persisted "active version" pointer (the dropdown binds + saves here). */
    activeIdPath: string;
    defaultId?: string;
    /** Optional label override; omit to use the active-id field's backend `title`. */
    label?: string;
    /** Help text shown as a tooltip next to the label; omit to use the field's backend hint. */
    hint?: string;
    ariaLabel: string;
    editorLabel?: string;
    dialogTitle?: string;
  };

  let {
    ctrl,
    dictPath,
    activeIdPath,
    defaultId = 'default',
    label,
    hint,
    ariaLabel,
    editorLabel,
    dialogTitle
  }: Props = $props();

  let open = $state(false);
  // Which action the just-clicked icon asked the dialog to run on open (undefined = plain Edit).
  let pendingAction = $state<'create' | 'duplicate' | undefined>(undefined);

  const dict = $derived(
    (getPreferenceByPath(ctrl.draft, dictPath) ?? {}) as Record<string, AnswerPromptProfile>
  );
  const entries = $derived(
    Object.entries(dict).sort(([ka, a], [kb, b]) =>
      ka === defaultId ? -1 : kb === defaultId ? 1 : a.label.localeCompare(b.label)
    )
  );
  const activeId = $derived(String(getPreferenceByPath(ctrl.draft, activeIdPath) ?? defaultId));

  const resolvedLabel = $derived(
    label ??
      preferenceTitle(preferenceFieldMeta(ctrl.fieldSchema, activeIdPath as PreferencePath)) ??
      'Active prompt profile'
  );
  const resolvedHint = $derived(
    hint ?? preferenceHint(preferenceFieldMeta(ctrl.fieldSchema, activeIdPath as PreferencePath)) ?? ''
  );

  function setActive(id: string) {
    if (!ctrl.draft) return;
    setPreferenceByPath(ctrl.draft, activeIdPath, id);
    ctrl.markDirty();
  }

  function openDialog(action?: 'create' | 'duplicate') {
    pendingAction = action;
    open = true;
  }

  const model = $derived<PromptDialogModel>({
    kind: 'library',
    initialDict: dict,
    defaultId,
    // Edit/Duplicate act on the currently-active profile; New ignores it.
    initialSelectedId: activeId,
    initialAction: pendingAction
  });

  async function onSave(payload: PromptSavePayload): Promise<boolean> {
    if (payload.kind !== 'library') return false;
    const edits: Record<string, unknown> = { [dictPath]: payload.dict };
    // Repair a dangling active pointer if its target was deleted inside the dialog.
    const cur = getPreferenceByPath(ctrl.draft, activeIdPath);
    if (typeof cur === 'string' && !(cur in payload.dict)) edits[activeIdPath] = defaultId;
    return ctrl.saveDialogEdits(edits);
  }
</script>

<div class="flex flex-wrap items-end gap-3">
  <FormField
    label={resolvedLabel}
    anchor={activeIdPath}
    hint={resolvedHint}
    hintTooltip
    class="min-w-[16rem] flex-1"
  >
    <select class={ADMIN_SELECT_LG} value={activeId} onchange={(e) => setActive(e.currentTarget.value)}>
      {#each entries as [id, p] (id)}
        <option value={id}>{p.label}{p.locked ? ' 🔒' : ''}</option>
      {/each}
    </select>
  </FormField>
  <div class="flex gap-2 pb-px">
    <Button variant="outline" size="icon" aria-label="New prompt profile" title="New profile" onclick={() => openDialog('create')}>
      <Plus class="size-4" aria-hidden="true" />
    </Button>
    <Button variant="outline" size="icon" aria-label="Edit prompt profiles" title="Edit profile" onclick={() => openDialog()}>
      <Pencil class="size-4" aria-hidden="true" />
    </Button>
    <Button variant="outline" size="icon" aria-label="Duplicate prompt profile" title="Duplicate profile" onclick={() => openDialog('duplicate')}>
      <Copy class="size-4" aria-hidden="true" />
    </Button>
  </div>
</div>

<PromptEditorDialog
  {open}
  title={dialogTitle ?? `Edit: ${resolvedLabel}`}
  {ariaLabel}
  {editorLabel}
  {model}
  {onSave}
  onClose={() => {
    open = false;
    pendingAction = undefined;
  }}
  pending={ctrl.busy}
/>
