<script lang="ts">
  /**
   * Inline row for a SINGLE markdown prompt: shows the prompt name + a Default/Customized badge +
   * an Edit button that opens the large editor dialog. The page no longer edits the prompt in
   * place; the dialog saves the value straight to the backend (ctrl.saveDialogEdits), so this field
   * never marks the page-level form dirty.
   */
  import Button from '$lib/components/ui/button.svelte';
  import FieldHelp from '$lib/components/ui/field-help.svelte';
  import { cn } from '$lib/utils';
  import { getPreferenceByPath } from '$lib/features/preferences/state/preferences-edits';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import {
    preferenceFieldMeta,
    preferenceTitle,
    type PreferencePath
  } from '$lib/features/preferences/shared/preferences-schema';
  import PromptEditorDialog from './PromptEditorDialog.svelte';
  import type { PromptDialogModel, PromptSavePayload } from './prompt-editor';

  type Props = {
    ctrl: PreferencesController;
    /** Dotted preference path, e.g. "knowledge.answering.prompt". */
    path: string;
    /** Optional row title override; omit to use the field's backend `title`. */
    label?: string;
    /** Help text shown as a tooltip next to the label (no inline prose on the page). */
    hint?: string;
    ariaLabel: string;
    editorLabel?: string;
    dialogTitle?: string;
  };

  let { ctrl, path, label, hint, ariaLabel, editorLabel, dialogTitle }: Props = $props();

  let open = $state(false);

  const resolvedLabel = $derived(
    label ?? preferenceTitle(preferenceFieldMeta(ctrl.fieldSchema, path as PreferencePath)) ?? path
  );
  const value = $derived(String((getPreferenceByPath(ctrl.draft, path) as string) ?? ''));
  const defaultText = $derived(ctrl.promptDefaults[path] ?? '');
  const isDefault = $derived(value === defaultText);

  const model = $derived<PromptDialogModel>({
    kind: 'single',
    initialValue: value,
    defaultText
  });

  async function onSave(payload: PromptSavePayload): Promise<boolean> {
    if (payload.kind !== 'single') return false;
    return ctrl.saveDialogEdits({ [path]: payload.value });
  }
</script>

<div data-pref-path={path} class="flex flex-wrap items-center justify-between gap-3">
  <div class="flex items-center gap-2">
    <span class="inline-flex items-center gap-1.5 font-sans text-[0.9375rem] font-semibold text-foreground">
<!-- title shows the dotted preference path on hover. -->
      <span class="pref-field-label" title={path}>{resolvedLabel}</span>
      {#if hint?.trim()}
        <FieldHelp text={hint} />
      {/if}
    </span>
    <span
      class={cn(
        'rounded-full border px-2 py-0.5 text-xs font-medium',
        isDefault ? 'border-border/60 text-muted-foreground' : 'border-primary/40 text-primary'
      )}
    >
      {isDefault ? 'Default' : 'Customized'}
    </span>
  </div>
  <Button variant="outline" size="sm" onclick={() => (open = true)}>Edit prompt</Button>
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
