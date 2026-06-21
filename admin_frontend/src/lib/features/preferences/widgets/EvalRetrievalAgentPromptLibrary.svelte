<script lang="ts">
  /**
   * Library manager for retrieval-agent system prompts (graph.eval.retrieval_agent_prompts).
   * The workspace's active profile is chosen in the parent card; this widget edits profiles.
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

  const DEFAULT_ID = 'default';

  let selectedId = $state(DEFAULT_ID);

  const prompts = $derived(ctrl.draft?.graph.eval.retrieval_agent_prompts ?? {});
  const entries = $derived(
    Object.entries(prompts).sort(([ka, a], [kb, b]) =>
      ka === DEFAULT_ID ? -1 : kb === DEFAULT_ID ? 1 : a.label.localeCompare(b.label)
    )
  );
  const selected = $derived(prompts[selectedId] ?? prompts[DEFAULT_ID] ?? null);
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
    ctrl.draft.graph.eval.retrieval_agent_prompts[id] = { label, locked: false, prompt: '' };
    selectedId = id;
    ctrl.markDirty();
  }

  function duplicateProfile() {
    if (!ctrl.draft || !selected) return;
    const label = `${selected.label} copy`;
    const id = uniqueId(slugify(label));
    ctrl.draft.graph.eval.retrieval_agent_prompts[id] = {
      label,
      locked: false,
      prompt: selected.prompt || (selected.locked ? defaultText : '')
    };
    selectedId = id;
    ctrl.markDirty();
  }

  function deleteProfile() {
    if (!ctrl.draft || !selected || selected.locked) return;
    const { [selectedId]: _removed, ...rest } = ctrl.draft.graph.eval.retrieval_agent_prompts;
    ctrl.draft.graph.eval.retrieval_agent_prompts = rest;
    if (ctrl.draft.graph.eval.active_retrieval_agent_prompt_id === selectedId) {
      ctrl.draft.graph.eval.active_retrieval_agent_prompt_id = DEFAULT_ID;
    }
    selectedId = DEFAULT_ID;
    ctrl.markDirty();
  }

  function renameSelected(label: string) {
    const p = ctrl.draft?.graph.eval.retrieval_agent_prompts[selectedId];
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
        editorLabel="Retrieval agent prompt editor"
        previewLabel="Preview"
        ariaLabel="Mem-eval retrieval agent prompt (markdown)"
        bind:value={ctrl.draft.graph.eval.retrieval_agent_prompts[selectedId].prompt}
        defaultValue={defaultText}
        onInput={ctrl.markDirty}
      />
    {/if}
  </div>
{/if}
