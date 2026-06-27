<script lang="ts">
  /**
   * Unified, large prompt-editor dialog (single prompt OR versioned prompt library). Edits a LOCAL
   * working copy — nothing reaches the page draft. All mutations live here: edit text, and for a
   * library New / Duplicate / Delete / Rename. Save hands the result to the parent (which PATCHes
   * the backend immediately); Cancel / close discards the working copy (with a confirm when dirty).
   * The page only selects which version opens here — see PromptLibraryField.
   */
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import FormField from '$lib/components/ui/form-field.svelte';
  import MarkdownEditorPreview from '$lib/components/ui/markdown/MarkdownEditorPreview.svelte';
  import MarkdownPreview from '$lib/components/ui/markdown/MarkdownPreview.svelte';
  import { ADMIN_INPUT } from '$lib/styling/admin-tokens';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';
  import type { AnswerPromptProfile } from '$lib/api/preferences';
  import {
    slugifyPromptLabel,
    uniquePromptId,
    type PromptDialogModel,
    type PromptSavePayload
  } from './prompt-editor';

  type Props = {
    open: boolean;
    title: string;
    ariaLabel: string;
    editorLabel?: string;
    model: PromptDialogModel;
    /** Persist the working copy; returns true on success (dialog then closes). */
    onSave: (payload: PromptSavePayload) => Promise<boolean>;
    /** Close without saving (working copy is dropped). */
    onClose: () => void;
    pending?: boolean;
  };

  let {
    open,
    title,
    ariaLabel,
    editorLabel = 'Prompt editor',
    model,
    onSave,
    onClose,
    pending = false
  }: Props = $props();

  // --- local working state (seeded once per open; never written back to the page draft) ---
  let workingValue = $state(''); // single
  let workingDict = $state<Record<string, AnswerPromptProfile>>({}); // library
  let selectedId = $state('');
  let originalSnapshot = $state(''); // JSON of the seeded value, for dirty detection
  let confirmingClose = $state(false);
  // Plain latch (not reactive): reseed only when the dialog transitions closed → open, so a parent
  // re-render while open never wipes in-progress edits.
  let seeded = false;

  function seed() {
    if (model.kind === 'single') {
      workingValue = model.initialValue;
      originalSnapshot = JSON.stringify(model.initialValue);
    } else {
      workingDict = JSON.parse(JSON.stringify(model.initialDict));
      selectedId = model.initialSelectedId in workingDict ? model.initialSelectedId : model.defaultId;
      originalSnapshot = JSON.stringify(workingDict);
    }
    confirmingClose = false;
  }

  $effect(() => {
    if (open && !seeded) {
      seed();
      seeded = true;
    } else if (!open && seeded) {
      seeded = false;
    }
  });

  const defaultId = $derived(model.kind === 'library' ? model.defaultId : 'default');
  const libraryDefaultText = $derived(workingDict[defaultId]?.prompt ?? '');
  const entries = $derived(
    Object.entries(workingDict).sort(([ka, a], [kb, b]) =>
      ka === defaultId ? -1 : kb === defaultId ? 1 : a.label.localeCompare(b.label)
    )
  );
  const selected = $derived(workingDict[selectedId] ?? workingDict[defaultId] ?? null);

  const currentSnapshot = $derived(
    model.kind === 'single' ? JSON.stringify(workingValue) : JSON.stringify(workingDict)
  );
  const dirty = $derived(currentSnapshot !== originalSnapshot);

  // No empties: every editable (non-locked) prompt must have text before Save is allowed.
  const valid = $derived(
    model.kind === 'single'
      ? workingValue.trim().length > 0
      : Object.values(workingDict).every((p) => p.locked || p.prompt.trim().length > 0)
  );
  const canSave = $derived(dirty && valid && !pending);

  function createProfile() {
    const label = `Custom ${Object.keys(workingDict).length}`;
    const id = uniquePromptId(slugifyPromptLabel(label), workingDict);
    workingDict[id] = { label, locked: false, prompt: '' };
    selectedId = id;
  }

  function duplicateProfile() {
    if (!selected) return;
    const label = `${selected.label} copy`;
    const id = uniquePromptId(slugifyPromptLabel(label), workingDict);
    // Duplicating the locked default seeds from its full default text so editing starts from the
    // real prompt (a non-default profile's own prompt otherwise).
    workingDict[id] = {
      label,
      locked: false,
      prompt: selected.prompt || (selected.locked ? libraryDefaultText : '')
    };
    selectedId = id;
  }

  function deleteProfile() {
    if (!selected || selected.locked) return;
    // Reassign a fresh object (not delete) so the $state proxy reliably re-renders the list.
    const { [selectedId]: _removed, ...rest } = workingDict;
    workingDict = rest;
    selectedId = defaultId;
  }

  function renameSelected(label: string) {
    const p = workingDict[selectedId];
    if (!p || p.locked) return;
    p.label = label;
  }

  function attemptClose() {
    if (pending) return;
    if (dirty) {
      confirmingClose = true;
      return;
    }
    onClose();
  }

  function discardAndClose() {
    confirmingClose = false;
    onClose();
  }

  async function save() {
    if (!canSave) return;
    const payload: PromptSavePayload =
      model.kind === 'single'
        ? { kind: 'single', value: workingValue }
        : { kind: 'library', dict: workingDict };
    const ok = await onSave(payload);
    if (ok) onClose();
  }
</script>

<Dialog.Root
  {open}
  onOpenChange={(next) => {
    if (!next) attemptClose();
  }}
>
  <Dialog.Content
    class="flex max-h-[88vh] w-[min(1100px,calc(100vw-2rem))] flex-col gap-4 sm:max-w-none"
    showCloseButton={false}
  >
    <Dialog.Header class="flex flex-row items-center justify-between gap-3 space-y-0">
      <Dialog.Title class="break-words">{title}</Dialog.Title>
    </Dialog.Header>

    {#if model.kind === 'library' && selected}
      <div class="flex flex-wrap items-end gap-3">
        <FormField label="Version" class="min-w-[16rem] flex-1" hint="">
          <select class={ADMIN_SELECT_LG} bind:value={selectedId}>
            {#each entries as [id, p] (id)}
              <option value={id}>{p.label}{p.locked ? ' 🔒' : ''}</option>
            {/each}
          </select>
        </FormField>
        <div class="flex flex-wrap gap-2 pb-1">
          <Button variant="outline" size="sm" onclick={createProfile}>+ New</Button>
          <Button variant="outline" size="sm" onclick={duplicateProfile}>Duplicate</Button>
          <Button
            variant="outline"
            size="sm"
            disabled={selected.locked}
            title={selected.locked
              ? 'The built-in default cannot be deleted.'
              : 'Delete this version.'}
            onclick={deleteProfile}
          >
            Delete
          </Button>
        </div>
      </div>
    {/if}

    <div class="min-h-0 flex-1 overflow-auto">
      {#if model.kind === 'single'}
        <MarkdownEditorPreview
          {editorLabel}
          previewLabel="Preview"
          {ariaLabel}
          bind:value={workingValue}
          defaultValue={model.defaultText}
          minHeightClass="min-h-[max(18rem,52vh)]"
        />
      {:else if selected?.locked}
        <p
          class="mb-3 rounded-md border border-border/50 bg-card/45 px-3 py-2 font-sans text-xs text-muted-foreground"
        >
          This is the built-in default (read-only). <span class="font-medium">Duplicate</span> it to
          create an editable copy.
        </p>
        <div
          class="min-h-[max(18rem,52vh)] overflow-auto rounded-lg border-2 border-primary/20 bg-card p-4 text-sm shadow-sm"
        >
          <MarkdownPreview markdown={selected.prompt || libraryDefaultText} compact />
        </div>
      {:else if selected}
        <FormField label="Label" class="mb-3 max-w-md" hint="">
          <input
            class={ADMIN_INPUT}
            value={selected.label}
            oninput={(e) => renameSelected(e.currentTarget.value)}
          />
        </FormField>
        <MarkdownEditorPreview
          {editorLabel}
          previewLabel="Preview"
          {ariaLabel}
          bind:value={workingDict[selectedId].prompt}
          defaultValue={libraryDefaultText}
          minHeightClass="min-h-[max(16rem,42vh)]"
        />
      {/if}
    </div>

    {#if confirmingClose}
      <div
        class="flex flex-wrap items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2"
      >
        <span class="text-sm text-foreground">Discard unsaved changes to this prompt?</span>
        <div class="flex gap-2">
          <Button variant="outline" size="sm" onclick={() => (confirmingClose = false)}>
            Keep editing
          </Button>
          <Button variant="destructive" size="sm" onclick={discardAndClose}>Discard</Button>
        </div>
      </div>
    {/if}

    <Dialog.Footer class="items-center">
      {#if !valid}
        <span class="mr-auto text-xs text-muted-foreground">
          A prompt can't be empty — use “Restore default” to bring back the built-in text.
        </span>
      {/if}
      <Button variant="outline" disabled={pending} onclick={attemptClose}>Cancel</Button>
      <Button disabled={!canSave} onclick={() => void save()}>
        {pending ? 'Saving…' : 'Save'}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
