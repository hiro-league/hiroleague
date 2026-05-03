<script lang="ts">
  import MarkdownEditorPreview from '$lib/components/ui/markdown/MarkdownEditorPreview.svelte';
  import CharacterSectionCard from '$lib/features/characters/CharacterSectionCard.svelte';
  import { characterSectionHintClass } from '$lib/features/characters/character-section-classes';
  import type { CharacterForm } from '$lib/features/characters/utils';

  let {
    form,
    markDirty
  }: {
    form: CharacterForm;
    markDirty: () => void;
  } = $props();
</script>

<CharacterSectionCard title="Character prompts">
  {#snippet hint()}
    <p class={characterSectionHintClass}>
      Markdown hints:
      <code class="rounded bg-muted px-1 py-0.5 font-mono text-xs">**bold**</code>,
      <code class="rounded bg-muted px-1 py-0.5 font-mono text-xs">*italic*</code>,
      <code class="rounded bg-muted px-1 py-0.5 font-mono text-xs">`code`</code>, headings (
      <code class="rounded bg-muted px-1 py-0.5 font-mono text-xs">#</code>), blank-line paragraphs, and lists when
      every line starts with
      <code class="rounded bg-muted px-1 py-0.5 font-mono text-xs">- </code>.
    </p>
  {/snippet}

  <div class="grid gap-8">
    <MarkdownEditorPreview
      editorLabel="Prompt markdown editor"
      previewLabel="Preview"
      ariaLabel="Character prompt (markdown)"
      bind:value={form.prompt}
      onInput={markDirty}
    />
    <MarkdownEditorPreview
      editorLabel="Backstory markdown editor"
      previewLabel="Preview"
      ariaLabel="Character backstory (markdown)"
      bind:value={form.backstory}
      onInput={markDirty}
    />
  </div>
</CharacterSectionCard>
