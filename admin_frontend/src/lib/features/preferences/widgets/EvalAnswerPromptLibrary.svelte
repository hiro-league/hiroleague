<script lang="ts">
  /**
   * Library manager for the mem-eval answer prompts (graph.eval.answer_prompts). Authors named
   * instruction blocks; a run picks WHICH one to use from the eval panel (not here). The locked
   * "default" profile carries the built-in default text and is read-only — Duplicate it to edit.
   * The whole dict round-trips on Save as one path (preferences-edits.ts), like tuning_profiles.
   */
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import MarkdownEditorPreview from '$lib/components/ui/markdown/MarkdownEditorPreview.svelte';
  import MarkdownPreview from '$lib/components/ui/markdown/MarkdownPreview.svelte';
  import { ADMIN_INPUT } from '$lib/styling/admin-tokens';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';

  type Props = { ctrl: PreferencesController };
  let { ctrl }: Props = $props();

  // The built-in profile id (mirrors DEFAULT_ANSWER_PROMPT_ID server-side) — always present.
  const DEFAULT_ID = 'default';

  // Which profile is being EDITED here (UI-local, not persisted — the run picker, on the eval
  // panel, chooses which profile a run USES). Defaults to the locked built-in.
  let selectedId = $state(DEFAULT_ID);

  const prompts = $derived(ctrl.draft?.graph.eval.answer_prompts ?? {});
  // Default profile first, then the rest alphabetically by label.
  const entries = $derived(
    Object.entries(prompts).sort(([ka, a], [kb, b]) =>
      ka === DEFAULT_ID ? -1 : kb === DEFAULT_ID ? 1 : a.label.localeCompare(b.label)
    )
  );
  const selected = $derived(prompts[selectedId] ?? prompts[DEFAULT_ID] ?? null);
  // The locked default's text is the canonical default — the "Restore default" source for the
  // editor, since the answer prompt no longer has a PROMPT_DEFAULTS entry.
  const defaultText = $derived(prompts[DEFAULT_ID]?.prompt ?? '');

  function slugify(label: string): string {
    const base = label
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '');
    return base || 'profile';
  }
  function uniqueId(base: string): string {
    let id = base;
    let n = 2;
    while (prompts[id]) {
      id = `${base}_${n}`;
      n += 1;
    }
    return id;
  }

  function createProfile() {
    if (!ctrl.draft) return;
    const label = `Custom ${Object.keys(prompts).length}`;
    const id = uniqueId(slugify(label));
    ctrl.draft.graph.eval.answer_prompts[id] = { label, locked: false, prompt: '' };
    selectedId = id;
    ctrl.markDirty();
  }

  function duplicateProfile() {
    if (!ctrl.draft || !selected) return;
    const label = `${selected.label} copy`;
    const id = uniqueId(slugify(label));
    // A duplicate of the locked default seeds from its full default text so editing starts from
    // the real prompt (selected.prompt is "" only for an un-customized profile).
    ctrl.draft.graph.eval.answer_prompts[id] = {
      label,
      locked: false,
      prompt: selected.prompt || (selected.locked ? defaultText : '')
    };
    selectedId = id;
    ctrl.markDirty();
  }

  function deleteProfile() {
    if (!ctrl.draft || !selected || selected.locked) return;
    // Reassign a fresh object (not delete) so the $state proxy reliably re-renders the list.
    const { [selectedId]: _removed, ...rest } = ctrl.draft.graph.eval.answer_prompts;
    ctrl.draft.graph.eval.answer_prompts = rest;
    selectedId = DEFAULT_ID;
    ctrl.markDirty();
  }

  function renameSelected(label: string) {
    const p = ctrl.draft?.graph.eval.answer_prompts[selectedId];
    if (!p || p.locked) return;
    p.label = label;
    ctrl.markDirty();
  }
</script>

{#if ctrl.draft && selected}
  <div class="grid gap-3">
    <div class="flex flex-wrap items-end gap-3">
      <FormField label="Profile" class="min-w-[16rem] flex-1" hint="">
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
          title={selected.locked ? 'The built-in default cannot be deleted.' : 'Delete this profile.'}
          onclick={deleteProfile}
        >
          Delete
        </Button>
      </div>
    </div>

    {#if selected.locked}
      <p class="rounded-md border border-border/50 bg-card/45 px-3 py-2 font-sans text-xs text-muted-foreground">
        This is the built-in default (read-only). <span class="font-medium">Duplicate</span> it to
        create an editable copy.
      </p>
      <div class="rounded-lg border-2 border-primary/20 bg-card p-4 text-sm shadow-sm">
        <MarkdownPreview markdown={selected.prompt || defaultText} compact />
      </div>
    {:else}
      <FormField label="Label" class="max-w-md" hint="">
        <input
          class={ADMIN_INPUT}
          value={selected.label}
          oninput={(e) => renameSelected(e.currentTarget.value)}
        />
      </FormField>
      <MarkdownEditorPreview
        editorLabel="Answer prompt editor"
        previewLabel="Preview"
        ariaLabel="Mem-eval answer prompt (markdown)"
        bind:value={ctrl.draft.graph.eval.answer_prompts[selectedId].prompt}
        defaultValue={defaultText}
        onInput={ctrl.markDirty}
      />
    {/if}
  </div>
{/if}
