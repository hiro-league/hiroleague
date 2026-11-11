<script lang="ts">
  /**
   * Unified, large prompt-editor dialog (single prompt OR versioned prompt library). Edits a LOCAL
   * working copy — nothing reaches the page draft. All mutations live here: edit text, and for a
   * library New / Duplicate / Delete / Rename. Save hands the result to the parent (which PATCHes
   * the backend immediately); Cancel / close discards the working copy (with a confirm when dirty).
   * The page only selects which version opens here — see PromptLibraryField.
   */
  import { untrack } from 'svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import { Draft } from '$kit/state/draft.svelte';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
  import Field from '$kit/ui/field.svelte';
  import MarkdownEditorPreview from '$lib/components/ui/markdown/MarkdownEditorPreview.svelte';
  import MarkdownPreview from '$lib/components/ui/markdown/MarkdownPreview.svelte';
  import { Input } from '$kit/components/ui/input/index.js';
  import type { AnswerPromptProfile } from '$lib/api/preferences';
  import PromptLibraryVersionBar from './PromptLibraryVersionBar.svelte';
  import {
    slugifyPromptLabel,
    uniquePromptId,
    type PromptDialogModel,
    type PromptSavePayload
  } from './prompt-editor';

  const uid = $props.id();

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
  // One draft for both kinds: `single` is the prompt text, `dict` the library; the other stays empty.
  // The dialog asks "Discard unsaved changes?" itself, so the draft does not also guard the page.
  const draft = new Draft<{ single: string; dict: Record<string, AnswerPromptProfile> }>(
    { single: '', dict: {} },
    { guard: false }
  );
  let selectedId = $state('');
  let confirmingClose = $state(false);
  // Plain latch (not reactive): reseed only when the dialog transitions closed → open, so a parent
  // re-render while open never wipes in-progress edits.
  let seeded = false;

  function seed() {
    if (model.kind === 'single') {
      draft.load({ single: model.initialValue, dict: {} }, true);
    } else {
      // Loaded BEFORE any initialAction so a New/Duplicate-on-open counts as a dirty change.
      draft.load({ single: '', dict: model.initialDict }, true);
      selectedId = model.initialSelectedId in draft.value.dict ? model.initialSelectedId : model.defaultId;
      // Reuse the dialog's own create/duplicate logic when the page's New/Duplicate icon opened us.
      if (model.initialAction === 'create') createProfile();
      else if (model.initialAction === 'duplicate') duplicateProfile();
    }
    confirmingClose = false;
  }

  $effect(() => {
    if (open && !seeded) {
      // Untracked: seeding reads the draft, which must not make this effect re-run on every edit.
      untrack(seed);
      seeded = true;
    } else if (!open && seeded) {
      seeded = false;
    }
  });

  const defaultId = $derived(model.kind === 'library' ? model.defaultId : 'default');
  const libraryDefaultText = $derived(draft.value.dict[defaultId]?.prompt ?? '');
  const entries = $derived(
    Object.entries(draft.value.dict).sort(([ka, a], [kb, b]) =>
      ka === defaultId ? -1 : kb === defaultId ? 1 : a.label.localeCompare(b.label)
    )
  );
  const selected = $derived(draft.value.dict[selectedId] ?? draft.value.dict[defaultId] ?? null);

  const dirty = $derived(draft.dirty);

  // No empties: every editable (non-locked) prompt must have text before Save is allowed.
  const valid = $derived(
    model.kind === 'single'
      ? draft.value.single.trim().length > 0
      : Object.values(draft.value.dict).every((p) => p.locked || p.prompt.trim().length > 0)
  );
  const canSave = $derived(dirty && valid && !pending);

  function createProfile() {
    const label = `Custom ${Object.keys(draft.value.dict).length}`;
    const id = uniquePromptId(slugifyPromptLabel(label), draft.value.dict);
    draft.value.dict[id] = { label, locked: false, prompt: '' };
    selectedId = id;
  }

  function duplicateProfile() {
    // Read the working dict directly (not the `selected` derived) so this is reliable when called
    // from seed() during initialAction, before the derived has recomputed for the new selectedId.
    const src = draft.value.dict[selectedId] ?? draft.value.dict[defaultId];
    if (!src) return;
    const label = `${src.label} copy`;
    const id = uniquePromptId(slugifyPromptLabel(label), draft.value.dict);
    // Duplicating the locked default seeds from its full default text so editing starts from the
    // real prompt (a non-default profile's own prompt otherwise).
    draft.value.dict[id] = {
      label,
      locked: false,
      prompt: src.prompt || (src.locked ? libraryDefaultText : '')
    };
    selectedId = id;
  }

  function deleteProfile() {
    if (!selected || selected.locked) return;
    // Reassign a fresh object (not delete) so the $state proxy reliably re-renders the list.
    const { [selectedId]: _removed, ...rest } = draft.value.dict;
    draft.value.dict = rest;
    selectedId = defaultId;
  }

  function renameSelected(label: string) {
    const p = draft.value.dict[selectedId];
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
        ? { kind: 'single', value: draft.value.single }
        : { kind: 'library', dict: draft.value.dict };
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
      <PromptLibraryVersionBar
        {entries}
        {selected}
        bind:selectedId
        onCreate={createProfile}
        onDuplicate={duplicateProfile}
        onDelete={deleteProfile}
      />
    {/if}

    <div class="min-h-0 flex-1 overflow-auto">
      {#if model.kind === 'single'}
        <MarkdownEditorPreview
          {editorLabel}
          previewLabel="Preview"
          {ariaLabel}
          bind:value={draft.value.single}
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
        <Field label="Label" for="{uid}-label" class="mb-3 max-w-md">
          <Input
            id="{uid}-label"
            value={selected.label}
            oninput={(e) => renameSelected(e.currentTarget.value)}
          />
        </Field>
        <MarkdownEditorPreview
          {editorLabel}
          previewLabel="Preview"
          {ariaLabel}
          bind:value={draft.value.dict[selectedId].prompt}
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
